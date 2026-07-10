"""feature_exercise_content — unified CrewFit Exercise Content Library.

One collection (`exercises_v2`) that replaces the old exercise-library /
video-library split. Includes warm-ups, mobility, cardio drills, rehab &
cooldown. Powered by the same Nano Banana pipeline used for brand images.

Endpoints (all prefixed with /api):
  POST   /exercise-content                    — create (admin)
  GET    /exercise-content                    — list + filters + search
  GET    /exercise-content/{id}               — detail
  PATCH  /exercise-content/{id}               — update
  DELETE /exercise-content/{id}               — archive
  POST   /exercise-content/{id}/approve       — one-click approvals
  POST   /exercise-content/{id}/generate-image— start / end / primary
  GET    /exercise-content/images/{img_id}/stream — auth-signed streaming
  POST   /exercise-content/scan-todos         — nightly coach-todo generator
  GET    /exercise-content/{id}/log           — change-log
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel
from typing import Any, Optional
import asyncio
import base64
import datetime as _dt
import os
import re

from server import (
    api, db, current_user, require_admin, new_id, now_iso, logger,
    EMERGENT_LLM_KEY, _create_coach_task,
)


IMG_ROOT = Path(os.environ.get("EXERCISE_IMAGE_ROOT", "/app/backend/uploads/exercise_images"))
IMG_ROOT.mkdir(parents=True, exist_ok=True)

MODEL_ID = "gemini-3.1-flash-image-preview"

# ---- Style constants (per user brief §Exercise) ----------------------------

EXERCISE_STYLE = (
    "Premium dark athletic coaching visual for CrewFit exercise library. "
    "SOLID BLACK studio background. Realistic athletic person in dark training "
    "clothing (t-shirt + shorts / joggers). Full-figure or correctly cropped "
    "body positioning — do not cut off hands, feet or equipment. Movement and "
    "body position are the focus. Equipment is clearly visible. Face is SOFTLY "
    "SHADED / less prominent, not the visual focus (soft shadow across upper "
    "face). High contrast against the black background. Clean coaching "
    "visual, no distracting environment, no bodybuilding look, no shirtless, "
    "no exaggerated musculature, no obvious AI face artefacts. Consistent "
    "lighting, portrait 3:4 aspect ratio."
)

STATUS_VALUES = {
    "Draft", "Needs Review", "Artwork Needed", "Coaching Points Needed",
    "Video Needed", "Ready for Approval", "Approved", "Live",
    "Needs Update", "Rejected", "Archived",
}

APPROVAL_VALUES = {"pending", "approved", "rejected"}


class ExerciseCreate(BaseModel):
    exercise_name: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    movement_pattern: Optional[str] = None
    body_area: Optional[str] = None
    equipment_type: Optional[list[str]] = None
    training_type: Optional[str] = None
    difficulty_level: Optional[str] = None
    tags: Optional[list[str]] = None
    coaching_points: Optional[list[str]] = None
    common_mistakes: Optional[list[str]] = None
    client_facing_instructions: Optional[str] = None
    primary_video_url: Optional[str] = None
    backup_video_url: Optional[str] = None
    notes: Optional[str] = None
    alternatives: Optional[list[str]] = None
    regressions: Optional[list[str]] = None
    progressions: Optional[list[str]] = None


class ExercisePatch(BaseModel):
    exercise_name: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    movement_pattern: Optional[str] = None
    body_area: Optional[str] = None
    equipment_type: Optional[list[str]] = None
    training_type: Optional[str] = None
    difficulty_level: Optional[str] = None
    tags: Optional[list[str]] = None
    coaching_points: Optional[list[str]] = None
    common_mistakes: Optional[list[str]] = None
    client_facing_instructions: Optional[str] = None
    primary_video_url: Optional[str] = None
    backup_video_url: Optional[str] = None
    notes: Optional[str] = None
    alternatives: Optional[list[str]] = None
    regressions: Optional[list[str]] = None
    progressions: Optional[list[str]] = None
    status: Optional[str] = None
    approved_video_status: Optional[str] = None
    approved_image_status: Optional[str] = None


class ApproveBody(BaseModel):
    scope: str = "all"                  # all|images|coaching|video|mark_live|needs_update
    note: Optional[str] = None


class GenImageBody(BaseModel):
    slot: str = "primary"               # primary|start|end
    prompt_extra: Optional[str] = None
    female: Optional[bool] = None


# ---- Change log helper ----------------------------------------------------

async def _log(exercise_id: str, actor_id: str, kind: str, detail: str = "") -> None:
    doc = {
        "id": new_id(),
        "exercise_id": exercise_id,
        "actor_id": actor_id,
        "kind": kind,                   # created | image_generated | video_changed |
                                        # coaching_edited | approval_changed | status_changed
        "detail": detail[:400],
        "created_at": now_iso(),
    }
    try: await db.exercise_content_log.insert_one(doc)
    except Exception: logger.exception("exercise log write failed")


# ---- Nano Banana image generator (specialised for exercises) --------------

async def _generate_ex_image(prompt: str, session_id: str) -> bytes:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message="You are a premium visual designer for CrewFit exercise demonstration images.",
    )
    chat.with_model("gemini", MODEL_ID).with_params(modalities=["image", "text"])
    _t, imgs = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    if not imgs:
        raise HTTPException(502, "no image returned")
    data = imgs[0].get("data") if isinstance(imgs[0], dict) else None
    if not data:
        raise HTTPException(502, "empty image data")
    return base64.b64decode(data)


def _build_ex_prompt(ex: dict, slot: str, extra: Optional[str], female: Optional[bool]) -> str:
    name = ex.get("exercise_name") or "exercise"
    equipment = ", ".join(ex.get("equipment_type") or []) or "bodyweight"
    body_area = ex.get("body_area") or ""
    subject = ("female" if female else "male") + " athlete"
    slot_map = {
        "start":   f"START POSITION of the {name} — the moment before the movement begins",
        "end":     f"END POSITION of the {name} — the completed / peak-contraction position",
        "primary": f"the main demonstration of the {name}",
    }
    slot_line = slot_map.get(slot, slot_map["primary"])
    body_focus = f" Emphasise {body_area} musculature and posture." if body_area else ""
    equip_line = f" Equipment shown: {equipment}."
    extra_line = f" {extra}" if extra else ""
    return f"{EXERCISE_STYLE} Show {slot_line}. Subject: realistic athletic {subject}.{body_focus}{equip_line}{extra_line}"


async def _run_image_job(image_id: str, prompt: str) -> None:
    try:
        raw = await _generate_ex_image(prompt, session_id=f"ex-{image_id}")
        path = IMG_ROOT / f"{image_id}.png"
        path.write_bytes(raw)
        await db.exercise_content_images.update_one(
            {"id": image_id},
            {"$set": {"status": "ready", "storage_path": str(path),
                      "size_bytes": len(raw), "mime": "image/png",
                      "updated_at": now_iso()}},
        )
    except HTTPException as he:
        await db.exercise_content_images.update_one(
            {"id": image_id},
            {"$set": {"status": "failed", "error": he.detail, "updated_at": now_iso()}},
        )
    except Exception as e:
        logger.exception("exercise image job failed")
        await db.exercise_content_images.update_one(
            {"id": image_id},
            {"$set": {"status": "failed", "error": str(e)[:400], "updated_at": now_iso()}},
        )


async def _reconcile_ex_stale() -> None:
    try:
        await db.exercise_content_images.update_many(
            {"status": {"$in": ["generating", "pending"]}},
            {"$set": {"status": "failed", "error": "server restart", "updated_at": now_iso()}},
        )
    except Exception: logger.exception("exercise image reconcile failed")


# ---- CRUD -----------------------------------------------------------------

def _default_status_flags() -> dict:
    return {
        "status": "Draft",
        "approval_status": "pending",
        "approved_image_status": "Missing",
        "approved_video_status": "Missing",
        "content_status": {"images": False, "coaching_points": False, "video": False},
        "used_in_upcoming_workouts_count": 0,
        "used_in_active_programmes_count": 0,
        "used_in_tomorrow_workouts_count": 0,
        "primary_image_id": None,
        "demo_start_image_id": None,
        "demo_end_image_id": None,
    }


@api.post("/exercise-content")
async def ex_create(body: ExerciseCreate, admin: dict = Depends(require_admin())):
    ex_id = new_id()
    now = now_iso()
    doc = {
        "id": ex_id,
        **body.model_dump(),
        **_default_status_flags(),
        "created_by": admin["id"],
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    await db.exercises_v2.insert_one(doc)
    await _log(ex_id, admin["id"], "created", f"Created '{body.exercise_name}'")
    doc.pop("_id", None)
    return {"exercise": doc}


@api.get("/exercise-content")
async def ex_list(
    q: Optional[str] = None, category: Optional[str] = None,
    training_type: Optional[str] = None, status: Optional[str] = None,
    body_area: Optional[str] = None, missing_content: bool = False,
    used_tomorrow: bool = False, approved_only: bool = False,
    limit: int = 200, _: dict = Depends(current_user),
):
    query: dict = {}
    if category: query["category"] = category
    if training_type: query["training_type"] = training_type
    if body_area: query["body_area"] = body_area
    if status: query["status"] = status
    if approved_only: query["status"] = {"$in": ["Approved", "Live"]}
    if used_tomorrow: query["used_in_tomorrow_workouts_count"] = {"$gt": 0}
    if missing_content:
        query["$or"] = [
            {"content_status.images": False},
            {"content_status.coaching_points": False},
            {"content_status.video": False},
        ]
    if q:
        rx = {"$regex": re.escape(q), "$options": "i"}
        query.setdefault("$and", []).append({"$or": [
            {"exercise_name": rx}, {"tags": rx}, {"movement_pattern": rx},
            {"body_area": rx}, {"equipment_type": rx},
        ]})
    rows = await db.exercises_v2.find(query, {"_id": 0}).sort("updated_at", -1).to_list(limit)
    return {"exercises": rows, "count": len(rows)}


@api.get("/exercise-content/{ex_id}")
async def ex_detail(ex_id: str, _: dict = Depends(current_user)):
    doc = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    if not doc: raise HTTPException(404, "not found")
    return {"exercise": doc}


@api.patch("/exercise-content/{ex_id}")
async def ex_patch(ex_id: str, body: ExercisePatch, admin: dict = Depends(require_admin())):
    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex: raise HTTPException(404, "not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "status" in updates and updates["status"] not in STATUS_VALUES:
        raise HTTPException(400, "invalid status")
    # Auto-update content_status flags
    cs = dict(ex.get("content_status") or {})
    if "coaching_points" in updates:
        cs["coaching_points"] = bool(updates["coaching_points"])
    if "primary_video_url" in updates:
        cs["video"] = bool(updates["primary_video_url"])
    updates["content_status"] = cs
    updates["updated_at"] = now_iso()
    await db.exercises_v2.update_one({"id": ex_id}, {"$set": updates})
    kinds = []
    if "coaching_points" in updates: kinds.append("coaching_edited")
    if "primary_video_url" in updates or "backup_video_url" in updates: kinds.append("video_changed")
    if "status" in updates: kinds.append("status_changed")
    for k in (kinds or ["updated"]):
        await _log(ex_id, admin["id"], k)
    ex = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    return {"exercise": ex}


@api.delete("/exercise-content/{ex_id}")
async def ex_archive(ex_id: str, admin: dict = Depends(require_admin())):
    await db.exercises_v2.update_one({"id": ex_id},
        {"$set": {"status": "Archived", "updated_at": now_iso()}})
    await _log(ex_id, admin["id"], "status_changed", "→ Archived")
    return {"ok": True}


# ---- Approvals ------------------------------------------------------------

@api.post("/exercise-content/{ex_id}/approve")
async def ex_approve(ex_id: str, body: ApproveBody = ApproveBody(),
                     admin: dict = Depends(require_admin())):
    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex: raise HTTPException(404, "not found")
    now = now_iso()
    updates: dict = {"reviewed_by": admin["id"], "reviewed_at": now, "updated_at": now}
    scope = body.scope
    if scope == "images":
        updates["approved_image_status"] = "Approved"
    elif scope == "coaching":
        cs = dict(ex.get("content_status") or {}); cs["coaching_points"] = True
        updates["content_status"] = cs
    elif scope == "video":
        updates["approved_video_status"] = "Approved"
    elif scope == "mark_live":
        updates["status"] = "Live"; updates["approval_status"] = "approved"
    elif scope == "needs_update":
        updates["status"] = "Needs Update"
    elif scope == "all":
        updates["approved_image_status"] = "Approved"
        updates["approved_video_status"] = "Approved"
        cs = dict(ex.get("content_status") or {})
        cs["coaching_points"] = bool(ex.get("coaching_points"))
        cs["images"] = True; cs["video"] = True
        updates["content_status"] = cs
        updates["status"] = "Approved"; updates["approval_status"] = "approved"
    else:
        raise HTTPException(400, "invalid scope")
    await db.exercises_v2.update_one({"id": ex_id}, {"$set": updates})
    await _log(ex_id, admin["id"], "approval_changed", f"scope={scope} {body.note or ''}")
    ex = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    return {"exercise": ex}


# ---- Image generation -----------------------------------------------------

@api.post("/exercise-content/{ex_id}/generate-image")
async def ex_gen_image(ex_id: str, body: GenImageBody = GenImageBody(),
                       admin: dict = Depends(require_admin())):
    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex: raise HTTPException(404, "not found")
    slot = body.slot if body.slot in ("primary", "start", "end") else "primary"
    prompt = _build_ex_prompt(ex, slot, body.prompt_extra, body.female)

    image_id = new_id()
    now = now_iso()
    await db.exercise_content_images.insert_one({
        "id": image_id, "exercise_id": ex_id, "slot": slot,
        "prompt": prompt, "status": "generating",
        "storage_path": None, "size_bytes": None, "mime": None,
        "created_by": admin["id"], "created_at": now, "updated_at": now,
    })
    # Point the exercise doc at this new image immediately (client sees generating→ready)
    slot_key = {"primary": "primary_image_id", "start": "demo_start_image_id", "end": "demo_end_image_id"}[slot]
    await db.exercises_v2.update_one({"id": ex_id},
        {"$set": {slot_key: image_id,
                  "approved_image_status": "Needs Review",
                  "content_status.images": True,
                  "updated_at": now}})
    asyncio.create_task(_run_image_job(image_id, prompt))
    await _log(ex_id, admin["id"], "image_generated", f"slot={slot}")
    return {"image_id": image_id, "slot": slot, "status": "generating"}


@api.get("/exercise-content/images/{img_id}/stream")
async def ex_img_stream(img_id: str,
                        token: Optional[str] = Query(None),
                        authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        await current_user(authorization=authorization)
    else:
        from feature_profile import _user_from_token
        await _user_from_token(token)
    doc = await db.exercise_content_images.find_one({"id": img_id})
    if not doc: raise HTTPException(404, "image not found")
    p = doc.get("storage_path")
    if not p or not Path(p).exists(): raise HTTPException(404, "file missing")
    return FileResponse(p, media_type=doc.get("mime") or "image/png")


@api.get("/exercise-content/images/{img_id}")
async def ex_img_get(img_id: str, _: dict = Depends(current_user)):
    doc = await db.exercise_content_images.find_one({"id": img_id}, {"_id": 0, "storage_path": 0})
    if not doc: raise HTTPException(404, "not found")
    return {"image": doc}


# ---- Change-log -----------------------------------------------------------

@api.get("/exercise-content/{ex_id}/log")
async def ex_log(ex_id: str, _: dict = Depends(current_user)):
    rows = await db.exercise_content_log.find(
        {"exercise_id": ex_id}, {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    return {"log": rows}


# ---- Coach To-Do Feed scan (Phase 2 essential) ----------------------------

def _tomorrow_iso_date() -> str:
    return (_dt.date.today() + _dt.timedelta(days=1)).isoformat()


async def _bump_usage_counts() -> None:
    """Recompute used_in_tomorrow_workouts_count for every exercise from workouts."""
    tomorrow = _tomorrow_iso_date()
    # Reset counts
    await db.exercises_v2.update_many({}, {"$set": {"used_in_tomorrow_workouts_count": 0}})
    # Aggregate — assume workouts have shape {date: 'YYYY-MM-DD', exercises: [{exercise_id, ...}]}
    counts: dict[str, int] = {}
    async for w in db.workouts.find({"date": tomorrow}, {"_id": 0, "exercises": 1}):
        for e in (w.get("exercises") or []):
            xid = e.get("exercise_id") or e.get("id")
            if xid:
                counts[xid] = counts.get(xid, 0) + 1
    for xid, c in counts.items():
        await db.exercises_v2.update_one({"id": xid},
            {"$set": {"used_in_tomorrow_workouts_count": c}})


@api.post("/exercise-content/scan-todos")
async def ex_scan_todos(admin: dict = Depends(require_admin())):
    """Create Coach To-Do tasks for exercises scheduled tomorrow that are
    missing important content. Idempotent per day — checks existing tasks."""
    await _bump_usage_counts()
    created = 0
    async for ex in db.exercises_v2.find({"used_in_tomorrow_workouts_count": {"$gt": 0}}):
        # Skip if already fully live and approved
        if ex.get("status") == "Live" and ex.get("approval_status") == "approved":
            continue
        missing = []
        cs = ex.get("content_status") or {}
        if not (ex.get("primary_image_id") or ex.get("demo_start_image_id")):
            missing.append("artwork")
        if not cs.get("coaching_points"):
            missing.append("coaching_points")
        if not cs.get("video"):
            missing.append("video")
        if not missing and ex.get("approval_status") != "approved":
            missing.append("approval")

        if not missing:
            continue

        kind = f"exercise_needs_{missing[0]}" if len(missing) == 1 else "exercise_needs_full_approval"
        due = _tomorrow_iso_date()
        # Dedupe: don't create if an open task of same type exists for this exercise
        existing = await db.coach_tasks.find_one({
            "task_type": kind,
            "payload.exercise_id": ex["id"],
            "status": {"$in": ["open", "snoozed", "pending"]},
        })
        if existing:
            continue
        clients = ex.get("used_in_tomorrow_workouts_count", 0)
        summary = (
            f"This exercise appears in {clients} client workout"
            f"{'s' if clients != 1 else ''} tomorrow. Missing: "
            f"{', '.join(missing)}."
        )
        await _create_coach_task(
            user=admin,
            task_type=kind,
            title=f"Approve exercise content for {ex.get('exercise_name')}",
            description=summary,
            priority="high" if clients >= 3 else "normal",
            category="exercise_content",
            payload={
                "exercise_id": ex["id"],
                "missing": missing,
                "clients_affected": clients,
                "due_date": due,
                "actions": [
                    {"key": "review", "label": "Review Exercise"},
                    {"key": "approve_all", "label": "Approve All"},
                    {"key": "regen_images", "label": "Regenerate Images"},
                    {"key": "snooze", "label": "Snooze"},
                    {"key": "dismiss", "label": "Dismiss"},
                ],
            },
        )
        created += 1
    return {"created": created}
