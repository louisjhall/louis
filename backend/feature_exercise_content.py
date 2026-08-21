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
from fastapi.responses import FileResponse, Response
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

import storage as _storage
_STORAGE_NS = "exercise_images"

MODEL_ID = "gemini-3.1-flash-image-preview"

# ---- Style constants (per user brief §Exercise) ----------------------------

EXERCISE_STYLE_MALE = (
    "Premium dark athletic coaching photograph for the CrewFit exercise library. "
    "The MALE model MUST look like the man in the FIRST attached reference photo — same "
    "athletic build, same haircut, same skin tone, same forearm tattoos, same natural "
    "face. His face should be CLEARLY VISIBLE and NATURALLY LIT — do NOT darken, shade, "
    "obscure, silhouette or shadow his face. The model can be looking down at the "
    "equipment, at his hands, at the floor, or three-quarters away as the movement "
    "requires, but the face itself must be evenly lit and identifiable as the man in "
    "the reference photo. The body, movement and posture remain the visual focus. "
    "OUTFIT: plain black t-shirt with the CrewFit chest logo shown in the SECOND "
    "attached reference image — reproduce that exact logo faithfully on the left "
    "chest at a small, tasteful size (do NOT invent a new logo, do NOT enlarge it, "
    "do NOT stretch or recolour it). Plain black joggers or dark shorts, and "
    "**RED running trainers** (Nike-style, bright red uppers, white sole) — the "
    "shoes must always be red for brand consistency. "
    "SETTING: dark studio with a black brick textured wall directly behind the "
    "model, hard rim lighting from the left, deep shadow filling the rest of the "
    "frame — but the face and the chest logo remain evenly lit. Full-figure vertical "
    "composition, portrait 3:4 crop, model centred, hands, feet and any equipment "
    "fully in-frame — never cropped. "
    "IMPORTANT: do NOT place any additional wordmark, watermark, badge or graphic "
    "anywhere in the image (on the wall, floor, banners or corners). The ONLY "
    "branding allowed is the CrewFit chest logo from the second reference image, "
    "shown once, small, on the t-shirt. The rest of the image must be clean and "
    "text-free. Realistic athletic proportions, no bodybuilding exaggeration, no "
    "shirtless, no cheesy influencer pose, no obvious AI hands or feet artefacts."
)

EXERCISE_STYLE_FEMALE = (
    "Premium dark athletic coaching photograph for the CrewFit exercise library. "
    "The FEMALE model is a realistic athletic woman, mid-20s to mid-30s, brown "
    "hair pulled back in a low ponytail, natural athletic build, minimal makeup, "
    "friendly professional look — not over-sexualised, not a stock model. Her face "
    "should be CLEARLY VISIBLE and NATURALLY LIT — do NOT darken, shade, silhouette "
    "or obscure her face. She can be looking down at her hands, equipment, or "
    "three-quarters away as the movement requires, but the face remains evenly lit. "
    "The body, movement and posture are the visual focus. "
    "OUTFIT: plain black fitted athletic top (short-sleeve or long-sleeve, modest, "
    "not a sports bra) with the CrewFit chest logo shown in the ATTACHED reference "
    "image — reproduce that exact logo faithfully on the left chest at a small, "
    "tasteful size (do NOT invent a new logo, do NOT enlarge it, do NOT stretch "
    "or recolour it). Black athletic leggings, and **RED running trainers** "
    "(Nike-style, bright red uppers, white sole) — the shoes must always be red "
    "for brand consistency. "
    "SETTING: dark studio with a black brick textured wall directly behind the "
    "model, hard rim lighting from the left, deep shadow filling the rest of the "
    "frame — but the face and the chest logo remain evenly lit. Full-figure vertical "
    "composition, portrait 3:4 crop, model centred, hands, feet and any equipment "
    "fully in-frame — never cropped. "
    "IMPORTANT: do NOT place any additional wordmark, watermark, badge or graphic "
    "anywhere in the image (on the wall, floor, banners or corners). The ONLY "
    "branding allowed is the CrewFit chest logo from the reference image, shown "
    "once, small, on the top. The rest of the image must be clean and text-free. "
    "Realistic athletic proportions, no over-sexualisation, no cheesy influencer "
    "pose, no obvious AI hands or feet artefacts."
)

# Pilot persona — for Flight Support exercises. Pilots are demonstrated
# IN UNIFORM so the visual context matches the pre/post/turnaround
# scenario the client is actually in. We keep the same premium-dark
# studio look and brick backdrop so the pilot frames blend seamlessly
# with the rest of the exercise library.
EXERCISE_STYLE_PILOT = (
    "Premium dark athletic coaching photograph for the CrewFit exercise library. "
    "The MALE model is an airline PILOT IN FULL UNIFORM, mid-30s to mid-40s, "
    "clean-cut short hair, athletic professional build, friendly captain-of-the-"
    "aircraft look. His face should be CLEARLY VISIBLE and NATURALLY LIT — do "
    "NOT darken, shade, silhouette or obscure his face. He can look down at his "
    "hands / equipment / floor or three-quarters away as the movement requires, "
    "but the face remains evenly lit. "
    "UNIFORM (MUST BE ACCURATE): a crisp WHITE short-sleeve pilot shirt with "
    "black-and-gold four-bar CAPTAIN epaulettes on both shoulders, a subtle "
    "black airline tie, plain BLACK pilot trousers with a smart crease, and "
    "plain BLACK leather pilot shoes (NOT trainers — pilots wear leather shoes). "
    "The uniform must look believable to real crew — proper epaulette stripes, "
    "buttoned collar, tie sitting straight when standing. NO high-visibility "
    "jackets, NO cap on head for movement clarity, NO wings badge if it would "
    "distort during pose. "
    "SETTING: dark studio with a black brick textured wall directly behind the "
    "model, hard rim lighting from the left, deep shadow filling the rest of the "
    "frame — but the face and epaulettes remain evenly lit. Full-figure vertical "
    "composition, portrait 3:4 crop, model centred, hands, feet and any equipment "
    "fully in-frame — never cropped. "
    "IMPORTANT: do NOT place any wordmark, watermark, airline name, aircraft "
    "photo, badge or graphic anywhere in the image (on the wall, floor, banners "
    "or corners). The uniform stripes are the only branding. The rest of the "
    "image must be clean and text-free. Realistic athletic proportions under "
    "the uniform — this is a fit, in-service pilot demonstrating a real "
    "movement, not a stock photo model."
)

# Legacy alias — some callers still import EXERCISE_STYLE. Default to male.
EXERCISE_STYLE = EXERCISE_STYLE_MALE

STATUS_VALUES = {
    # TitleCase — the legacy Draft → Approved workflow
    "Draft", "Needs Review", "Artwork Needed", "Coaching Points Needed",
    "Video Needed", "Ready for Approval", "Approved", "Live",
    "Needs Update", "Rejected", "Archived",
    # Iter189f · snake_case — the V2 resolver workflow (draft_requested
    # is what the V2 resolver inserts, coach_review_needed is what the
    # coach admin uses to promote a candidate). Missing these blocked
    # the auto-YT hook on PATCH because the endpoint 400s before the
    # hook line runs. `draft` (lowercase) is a legacy value used by
    # older resolver code paths — still present in the DB.
    "draft_requested", "coach_review_needed", "draft",
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
    # Iter181c — override the similarity-guard 409 when the coach is
    # deliberately creating a variant that the fuzzy matcher would
    # otherwise flag (e.g. "Kettlebell Deadlift" vs "Barbell Deadlift"
    # when the equipment disqualifier fails for some odd token set).
    force: Optional[bool] = False


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
    # NEW — explicit persona selector. When provided, supersedes `female`.
    # Accepts "male" | "female" | "pilot". Legacy callers that only pass
    # `female` continue to work (mapped to "female"|"male").
    persona: Optional[str] = None


# ---- Persona helpers -------------------------------------------------------
# Single source of truth for how the three coach-side persona choices map
# through the whole pipeline (prompt, storage field, image record, logging).

VALID_PERSONAS = ("male", "female", "pilot")


def _resolve_persona(persona: Optional[str], female: Optional[bool]) -> str:
    """Legacy `female` bool -> new persona string. Explicit persona wins."""
    if persona:
        p = str(persona).lower().strip()
        if p in VALID_PERSONAS:
            return p
    return "female" if female else "male"


def _style_for_persona(persona: str) -> str:
    return {
        "male":   EXERCISE_STYLE_MALE,
        "female": EXERCISE_STYLE_FEMALE,
        "pilot":  EXERCISE_STYLE_PILOT,
    }.get(persona, EXERCISE_STYLE_MALE)


def _slot_map_field_for_persona(persona: str) -> str:
    """Which map on the exercise doc stores THIS persona's slot->image_id."""
    return {
        "male":   "demo_slots",
        "female": "demo_slots_female",
        "pilot":  "demo_slots_pilot",
    }.get(persona, "demo_slots")


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

async def _generate_ex_image(prompt: str, session_id: str, *, use_louis_ref: bool = False) -> bytes:
    """Generate an exercise image via Nano Banana.

    Reference images attached:
      - The CrewFit brand logo is ALWAYS attached (both male + female) so
        Nano Banana copies the real logo onto the t-shirt / top instead of
        hallucinating a red blob. Iter 103.
      - When ``use_louis_ref`` is true (male generations), Louis's
        full-body reference photo is ALSO attached FIRST so Nano Banana
        locks identity + outfit + red shoes.

    Order in the multimodal payload matters — the model treats the first
    image as the primary reference. For male: [louis, logo]. For female:
    [logo] only.
    """
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message="You are a premium visual designer for CrewFit exercise demonstration images.",
    )
    chat.with_model("gemini", MODEL_ID).with_params(modalities=["image", "text"])

    refs: list = []
    if use_louis_ref:
        # Import lazily to avoid a hard dep back into server.py at module load.
        try:
            from server import _louis_ref_b64
            refs.append(ImageContent(image_base64=_louis_ref_b64()))
        except Exception:
            logger.exception("could not attach Louis reference; falling back to text-only")
    # ALWAYS attach the CrewFit logo (male + female). Silent fallback if the
    # asset is missing — text prompt still describes the logo.
    try:
        from server import _crewfit_logo_b64
        refs.append(ImageContent(image_base64=_crewfit_logo_b64()))
    except Exception:
        logger.exception("could not attach CrewFit logo reference; falling back to text-only for logo")

    message_kwargs: dict = {"text": prompt}
    if refs:
        message_kwargs["file_contents"] = refs

    _t, imgs = await chat.send_message_multimodal_response(UserMessage(**message_kwargs))
    if not imgs:
        raise HTTPException(502, "no image returned")
    data = imgs[0].get("data") if isinstance(imgs[0], dict) else None
    if not data:
        raise HTTPException(502, "empty image data")
    return base64.b64decode(data)


def _build_ex_prompt(
    ex: dict, slot: str, extra: Optional[str],
    female: Optional[bool] = None, persona: Optional[str] = None,
) -> str:
    name = ex.get("exercise_name") or "exercise"
    equipment = ", ".join(ex.get("equipment_type") or []) or "bodyweight"
    body_area = ex.get("body_area") or ""
    resolved = _resolve_persona(persona, female)
    style = _style_for_persona(resolved)
    slot_map = {
        "start":    f"START POSITION of the {name} — the moment before the movement begins",
        "end":      f"END POSITION of the {name} — the completed position",
        "mid":      f"MID-REP POSITION of the {name} — half-way through the movement",
        "top":      f"TOP POSITION of the {name} — the highest / most-contracted / lockout point",
        "bottom":   f"BOTTOM POSITION of the {name} — the deepest / most-loaded / lowest point of the movement (e.g. for a push-up, chest close to floor; for a squat, hips below knees)",
        "apex":     f"APEX / peak-contraction position of the {name} — the hardest point of the movement",
        "stretch":  f"STRETCHED position of the {name} — muscles under maximum stretch / lengthened tension",
        "loaded":   f"LOADED HOLD position of the {name} — the isometric hold that defines this movement",
        "finish":   f"FINISH position of the {name} — after the movement has been completed",
        "primary":  f"the main demonstration of the {name}",
    }
    slot_line = slot_map.get(slot, slot_map["primary"])
    body_focus = f" Emphasise {body_area} musculature and posture." if body_area else ""
    equip_line = f" Equipment shown: {equipment}."
    extra_line = f" {extra}" if extra else ""
    return f"{style} Show {slot_line}.{body_focus}{equip_line}{extra_line}"


async def _run_image_job(image_id: str, prompt: str, *, use_louis_ref: bool = False) -> None:
    try:
        raw = await _generate_ex_image(prompt, session_id=f"ex-{image_id}", use_louis_ref=use_louis_ref)
        key = f"{_STORAGE_NS}/{image_id}.png"
        await _storage.storage.write_bytes(key, raw, content_type="image/png")
        path = IMG_ROOT / f"{image_id}.png"
        await db.exercise_content_images.update_one(
            {"id": image_id},
            {"$set": {"status": "ready",
                      "storage_key": key,
                      "storage_path": str(path) if _storage.storage.name == "disk" else None,
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



def _default_slots_for_movement(ex: dict) -> list[str]:
    """Pick sensible default required image slots based on the exercise's
    movement pattern / name. Every default includes PRIMARY so the preview
    card always renders."""
    tokens = " ".join([
        ex.get("exercise_name") or "",
        ex.get("movement_pattern") or "",
        ex.get("category") or "",
        ex.get("body_area") or "",
        " ".join(ex.get("tags") or []),
    ]).lower()

    def has(*ks: str) -> bool:
        return any(k in tokens for k in ks)

    if has("push-up", "push up", "pushup", "press-up", "press up", "pressup",
           "bench press", "chest press", "dip"):
        return ["primary", "start", "bottom"]
    if has("overhead press", "shoulder press", "military press", "push press"):
        return ["primary", "start", "top"]
    if has("row", "pulldown", "pull-up", "pull up", "pullup", "chin-up",
           "chinup", "face pull", "reverse fly", "high pull"):
        return ["primary", "start", "top"]
    if has("squat", "lunge", "split squat", "deadlift", "rdl", "hip hinge",
           "hinge", "step-up", "step up", "good morning"):
        return ["primary", "start", "bottom"]
    if has("bridge", "hip thrust", "thrust"):
        return ["primary", "start", "top"]
    if has("calf raise", "calf"):
        return ["primary", "start", "top"]
    if has("rotation", "twist", "windmill", "world's greatest"):
        return ["primary", "start", "finish"]
    if has("plank", "hollow hold", "l-sit", "wall sit"):
        return ["primary", "loaded"]
    if has("stretch", "mobility", "release", "opener", "myrtl"):
        return ["primary", "stretch"]
    return ["primary", "start", "end"]


def resolved_required_slots(ex: dict) -> list[str]:
    """Coach-configured slots take priority; falls back to movement default."""
    conf = ex.get("required_slots") or []
    if isinstance(conf, list) and conf:
        return conf
    return _default_slots_for_movement(ex)


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
        # New — movement-aware slot storage. Legacy fields above stay in
        # sync as mirrors so existing readers keep working. Every persona
        # gets its own map so pilot / female frames never overwrite each
        # other or the default (louis) frames.
        "demo_slots": {},              # {"bottom": img_id, "top": img_id, ...}  · MALE-LOUIS
        "demo_slots_female": {},
        "demo_slots_pilot": {},
        # Required slots for THIS movement — coach can edit. If left empty
        # the backend derives sensible defaults from movement/name tokens.
        "required_slots": [],
    }


@api.post("/exercise-content")
async def ex_create(
    body: ExerciseCreate,
    admin: dict = Depends(require_admin()),
    response: Response = None,
):
    """Manual coach add. Duplicate-guarded: if a similar exercise already
    exists (canonical-key exact, or token-Jaccard ≥ 0.85, or char-level
    SequenceMatcher ≥ 0.80), we DO NOT create a new row — we return HTTP
    409 with the matched exercise so the coach can decide whether to link,
    rename, or override with `?force=true`.
    """
    ex_id = new_id()
    now = now_iso()
    payload = body.model_dump()
    flags = _default_status_flags()
    if payload.get("coaching_points"):
        flags["content_status"] = {**flags["content_status"], "coaching_points": True}
    if payload.get("primary_video_url"):
        flags["content_status"] = {**flags["content_status"], "video": True}

    # ---- Similarity guard (Iter181c) ----------------------------------
    # Manual coach add — HTTP 409 with match details so the coach can
    # choose. Frontend passes `?force=true` (as query param OR body flag)
    # to override.
    try:
        from feature_exercise_dedup import (
            check_duplicate_candidate,
            record_duplicate_flag,
            canonical_key as _ck,
            safe_upsert_exercise,
        )
    except Exception:
        check_duplicate_candidate = None  # type: ignore
        safe_upsert_exercise = None       # type: ignore
        _ck = None                        # type: ignore
    force = bool(getattr(body, "force", False)) or bool(payload.pop("force", False))
    match = None
    if check_duplicate_candidate and not force:
        try:
            match = await check_duplicate_candidate(
                body.exercise_name,
                movement_pattern=payload.get("movement_pattern"),
                equipment_type=payload.get("equipment_type") or [],
            )
        except Exception:
            logger.exception("ex_create: similarity check failed — allowing insert")
            match = None
    if match:
        # Audit-trail the near-collision so a coach can review it later.
        try:
            await record_duplicate_flag(
                proposed_name=body.exercise_name,
                matched_id=match["id"],
                matched_name=match.get("exercise_name") or "",
                score=match.get("score", 0.0),
                gate=match.get("gate", "unknown"),
                source="manual",
                triggered_by=admin.get("id"),
            )
        except Exception:
            pass
        if response is not None:
            response.status_code = 409
        return {
            "status": "conflict",
            "reason": "similar_exists",
            "match": {
                "id": match["id"],
                "exercise_name": match.get("exercise_name"),
                "score": match.get("score"),
                "gate": match.get("gate"),
            },
            "detail": (
                f"An exercise named {match.get('exercise_name')!r} already exists "
                f"({match.get('gate')}, score {match.get('score')}). Send "
                f"`force: true` to create anyway, or link workouts to the existing "
                f"exercise instead."
            ),
        }

    doc = {
        "id": ex_id,
        **payload,
        **flags,
        "canonical_name_key": _ck(body.exercise_name) if _ck else None,
        "created_by": admin["id"],
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    # ---- Upsert-on-conflict via unique-index safety net ---------------
    if safe_upsert_exercise:
        r = await safe_upsert_exercise(doc)
        if not r.get("inserted"):
            # A concurrent request won the race — return the winner.
            existing = r.get("existing") or {}
            if response is not None:
                response.status_code = 409
            return {
                "status": "conflict",
                "reason": "race_lost",
                "match": {"id": existing.get("id"), "exercise_name": existing.get("exercise_name")},
            }
    else:
        await db.exercises_v2.insert_one(doc)
    await _log(ex_id, admin["id"], "created", f"Created '{body.exercise_name}'")

    # Auto-media generation — kick off standard image slots + coaching
    # points as soon as the exercise is created. Non-blocking; coach
    # still has to approve. Silent no-op if AUTO_MEDIA_GEN is disabled
    # OR if MANUAL_MODE is on (the auto-enqueue guard short-circuits).
    try:
        from feature_auto_media_gen import auto_enqueue_media_for_exercise
        await auto_enqueue_media_for_exercise(ex_id, triggered_by=admin["id"])
    except Exception:
        logger.exception("auto_media_gen: enqueue after coach-create failed (non-fatal)")

    # Iter189f · Auto YouTube video search on create. Fire-and-forget —
    # never blocks the create response. Result → Needs Review.
    try:
        from feature_youtube_video_finder import trigger_single_search
        from feature_auto_media_gen import _spawn_bg
        _spawn_bg(trigger_single_search(
            ex_id, triggered_by=admin.get("id") or "coach", reason="exercise_created",
        ))
    except Exception:
        logger.exception("auto_yt: trigger on create failed (non-fatal)")

    doc.pop("_id", None)
    return {"exercise": doc}


@api.get("/exercise-content")
async def ex_list(
    q: Optional[str] = None, category: Optional[str] = None,
    training_type: Optional[str] = None, status: Optional[str] = None,
    body_area: Optional[str] = None, missing_content: bool = False,
    used_tomorrow: bool = False, approved_only: bool = False,
    needs_review: bool = False, in_progress: bool = False,
    needs_media: bool = False,
    limit: int = 200, _: dict = Depends(current_user),
):
    query: dict = {}
    if category: query["category"] = category
    if training_type: query["training_type"] = training_type
    if body_area: query["body_area"] = body_area
    if status: query["status"] = status
    if approved_only: query["status"] = {"$in": ["Approved", "Live"]}
    if used_tomorrow: query["used_in_tomorrow_workouts_count"] = {"$gt": 0}
    # Iter 140f — Phase A: absorb Demand Queue into Exercise Library UI.
    # No schema change; these are just view filters over the existing
    # `exercises_v2` statuses + content_status flags.
    if needs_review:
        # Old Demand Queue view — drafts + coach-review candidates.
        query["status"] = {"$in": ["draft_requested", "coach_review_needed"]}
    if in_progress:
        # Anything actively transitioning: coach-review candidates, or an
        # exercise currently mid-generation (image/content job in flight).
        query["$or"] = [
            {"status": "coach_review_needed"},
            {"active_generation_job": True},
            {"approved_video_status": {"$in": ["queued", "generating"]}},
        ]
    if needs_media:
        # Approved rows that still have gaps in required content.
        query["status"] = {"$in": ["Approved", "Live"]}
        query["$or"] = [
            {"content_status.images": False},
            {"content_status.coaching_points": False},
            {"content_status.video": False},
            {"approved_video_status": {"$in": [None, "", "missing"]}},
        ]
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
    # Iter 129c — Needs Media urgency: `used_in_tomorrow_workouts_count` first
    # (LIVE tomorrow primary), then `used_in_upcoming_workouts_count` (next 7
    # days), then latest edit. This makes tomorrow's client-facing exercises
    # rise to the top of the library WITHOUT requiring the coach to click
    # the TOMORROW filter.
    rows = await db.exercises_v2.find(query, {"_id": 0}).sort([
        ("used_in_tomorrow_workouts_count", -1),
        ("used_in_upcoming_workouts_count", -1),
        ("updated_at", -1),
    ]).to_list(limit)
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

    # Iter189f · Auto YouTube video search when status transitions INTO
    # draft_requested or coach_review_needed. Fire-and-forget. Skipped
    # if the row already has a primary_video_url (idempotent).
    old_status = (ex.get("status") or "").strip()
    new_status = (updates.get("status") or old_status).strip()
    if (new_status in ("draft_requested", "coach_review_needed")
            and old_status != new_status
            and not (ex.get("primary_video_url") or updates.get("primary_video_url"))):
        try:
            from feature_youtube_video_finder import trigger_single_search
            from feature_auto_media_gen import _spawn_bg
            _spawn_bg(trigger_single_search(
                ex_id, triggered_by=admin.get("id") or "coach",
                reason=f"status_change:{old_status}→{new_status}",
            ))
        except Exception:
            logger.exception("auto_yt: trigger on patch failed (non-fatal)")

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
        # Phase 5: mark Live exercises as client-safe by default.
        updates["visibility"] = "client_visible"
        updates["safe_for_programming"] = True
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
        # Phase 5: full approvals also flip client-safety flags so the
        # v2_resolver immediately makes the exercise selectable.
        updates["visibility"] = "client_visible"
        updates["safe_for_programming"] = True
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
    # New: accept any of the extended slot types. Legacy start/end/primary
    # still write to their dedicated top-level fields; everything else
    # (mid, top, bottom, apex, stretch, loaded, finish) lives in the
    # `demo_slots` map on the exercise doc.
    valid_slots = {"primary", "start", "end", "mid", "top", "bottom",
                   "apex", "stretch", "loaded", "finish"}
    slot = body.slot if body.slot in valid_slots else "primary"
    persona = _resolve_persona(body.persona, body.female)
    prompt = _build_ex_prompt(ex, slot, body.prompt_extra, persona=persona)

    image_id = new_id()
    now = now_iso()
    # `gender` is kept for legacy readers ("male" | "female"); `persona`
    # carries the full three-way choice ("male" | "female" | "pilot").
    # The Flight Support media resolver keys off `persona`.
    gender_legacy = "female" if persona == "female" else "male"
    await db.exercise_content_images.insert_one({
        "id": image_id, "exercise_id": ex_id, "slot": slot,
        "requested_slot": slot,
        "gender": gender_legacy,
        "persona": persona,
        "prompt": prompt, "status": "generating",
        "storage_path": None, "size_bytes": None, "mime": None,
        "created_by": admin["id"], "created_at": now, "updated_at": now,
    })

    # Storage layout:
    #  * Legacy fields kept in sync for primary/start/end when persona=male
    #    so existing ExerciseThumbnail and workout-preview readers work
    #    unchanged. Female + Pilot only populate their own persona maps
    #    (never overwrite Louis's default frames).
    #  * All other slots (bottom, top, apex, finish, ...) go into the
    #    dynamic per-persona map.
    legacy_key_by_slot = {
        "primary": "primary_image_id",
        "start":   "demo_start_image_id",
        "end":     "demo_end_image_id",
    }
    set_updates: dict = {
        "approved_image_status": "Needs Review",
        "content_status.images": True,
        "updated_at": now,
    }
    slot_map_field = _slot_map_field_for_persona(persona)
    set_updates[f"{slot_map_field}.{slot}"] = image_id
    if slot in legacy_key_by_slot:
        legacy_key = legacy_key_by_slot[slot]
        if persona == "male":
            set_updates[legacy_key] = image_id
        elif persona == "female":
            female_key = legacy_key.replace("_id", "_female_id")
            set_updates[female_key] = image_id
            if not ex.get(legacy_key):
                set_updates[legacy_key] = image_id
        else:  # pilot
            pilot_key = legacy_key.replace("_id", "_pilot_id")
            set_updates[pilot_key] = image_id
            # Do NOT overwrite Louis's default frame — pilot lives in its
            # own lane and is resolved by the Flight Support media layer.
    await db.exercises_v2.update_one({"id": ex_id}, {"$set": set_updates})
    # Louis's identity reference is ONLY attached for the "male" persona.
    # Female + Pilot use text-only prompts (with the CrewFit logo ref).
    asyncio.create_task(_run_image_job(image_id, prompt, use_louis_ref=(persona == "male")))
    await _log(ex_id, admin["id"], "image_generated", f"slot={slot} persona={persona}")
    return {
        "image_id": image_id, "slot": slot,
        "gender": gender_legacy, "persona": persona,
        "status": "generating",
    }


@api.patch("/exercise-content/{ex_id}/required-slots")
async def ex_set_required_slots(
    ex_id: str, body: dict,
    admin: dict = Depends(require_admin()),
):
    """Coach picks which image positions this exercise needs.
    Accepts ``{"slots": ["primary", "start", "bottom"]}``. Empty list
    resets to the movement-pattern default."""
    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex:
        raise HTTPException(404, "not found")
    valid = {"primary", "start", "end", "mid", "top", "bottom",
             "apex", "stretch", "loaded", "finish"}
    raw = (body or {}).get("slots", [])
    if not isinstance(raw, list):
        raise HTTPException(400, "slots must be a list")
    cleaned = [s for s in raw if s in valid]
    await db.exercises_v2.update_one(
        {"id": ex_id},
        {"$set": {"required_slots": cleaned, "updated_at": now_iso()}},
    )
    await _log(ex_id, admin["id"], "required_slots_updated", f"slots={cleaned}")
    return {"required_slots": cleaned, "resolved": cleaned or _default_slots_for_movement(ex)}


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
    mime = doc.get("mime") or "image/png"
    key = doc.get("storage_key") or f"{_STORAGE_NS}/{img_id}.png"

    # If the image is still cooking, serve a tiny transparent placeholder
    # PNG with `no-store` so browsers/RN DO NOT cache the not-yet-ready
    # response. This is the core fix for the "generated image never
    # appears" bug — a 404 would get cached and later be shown as a broken
    # tile even after the real file lands on disk.
    status = str(doc.get("status") or "").lower()
    async def _serve_placeholder(reason: str):
        # 1×1 transparent PNG.
        import base64
        _placeholder = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lPAAAAAB"
            "JRU5ErkJggg=="
        )
        return Response(
            content=_placeholder,
            media_type="image/png",
            headers={
                "Cache-Control": "no-store, must-revalidate",
                "X-Image-Status": status or "unknown",
                "X-Image-Reason": reason,
            },
        )
    if status in ("generating", "queued", "pending"):
        return await _serve_placeholder("still-generating")
    if status == "failed":
        return await _serve_placeholder("generation-failed")

    if _storage.is_cloud():
        data = await _storage.storage.read_bytes(key)
        if data is None:
            p = doc.get("storage_path")
            if p and Path(p).exists():
                return FileResponse(p, media_type=mime, headers={"Cache-Control": "public, max-age=300"})
            # File not yet on disk (race between DB update and worker
            # writing the file). Serve the placeholder with no-store so
            # the next fetch will retry rather than caching a 404.
            return await _serve_placeholder("file-not-yet-on-disk")
        return Response(
            content=data, media_type=mime,
            headers={"Cache-Control": "public, max-age=300"},
        )
    p = doc.get("storage_path") or str(IMG_ROOT / f"{img_id}.png")
    if not Path(p).exists():
        return await _serve_placeholder("file-not-yet-on-disk")
    return FileResponse(
        p, media_type=mime,
        headers={"Cache-Control": "public, max-age=300"},
    )


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


def _today_iso_date() -> str:
    return _dt.date.today().isoformat()


def _week_iso_date() -> str:
    return (_dt.date.today() + _dt.timedelta(days=7)).isoformat()


async def _bump_usage_counts() -> None:
    """Recompute per-exercise scheduling counts by matching workouts against
    both ``exercise_id`` (v2 workouts) AND ``exercise_name`` (legacy / manual
    workouts). Also records ``first_scheduled_date`` so the JIT scan can
    prioritise HIGH / MEDIUM / LOW tasks.

    Called before scan-todos and also fired in the background by the
    server after every workout write."""
    today = _today_iso_date()
    week = _week_iso_date()
    # Reset the two counts + first_scheduled_date on every exercise so
    # unscheduled ones drop back to zero cleanly.
    await db.exercises_v2.update_many({}, {"$set": {
        "used_in_tomorrow_workouts_count": 0,
        "used_in_upcoming_workouts_count": 0,
        "first_scheduled_date": None,
    }})

    # Build a name index once so we can resolve legacy workouts by name.
    name_to_id: dict[str, str] = {}
    async for x in db.exercises_v2.find({}, {"_id": 0, "id": 1, "exercise_name": 1}):
        n = (x.get("exercise_name") or "").strip().lower()
        if n:
            name_to_id[n] = x["id"]

    # Iter 129c — Add a very small alias layer so common shorthand used in
    # session_specs resolves to canonical exercises WITHOUT creating
    # duplicate library rows (spec §6). Additive only — never overwrites an
    # existing canonical name.
    _ALIASES = {
        "dumbbell rdl": "dumbbell romanian deadlift",
        "db rdl": "dumbbell romanian deadlift",
        "rdl": "romanian deadlift",
        "push-up": "push up",
        "pushup": "push up",
        "push ups": "push up",
        "sl rdl": "single-leg romanian deadlift (dumbbell)",
    }
    for alias, target in _ALIASES.items():
        if alias in name_to_id:
            continue
        # Direct match
        tid = name_to_id.get(target)
        if not tid:
            # Fuzzy — allow the target string to be contained in a canonical
            # library name (e.g. "push up" → "Push-Up").
            for canon, cid in name_to_id.items():
                if target in canon or canon in target:
                    tid = cid
                    break
        if tid:
            name_to_id[alias] = tid

    tomorrow_counts: dict[str, int] = {}
    upcoming_counts: dict[str, int] = {}
    first_seen: dict[str, str] = {}
    tomorrow = _tomorrow_iso_date()

    async for w in db.workouts.find(
        {"date": {"$gte": today, "$lte": week}},
        {"_id": 0, "date": 1, "exercises": 1, "warm_up": 1, "cool_down": 1},
    ):
        wdate = w.get("date") or ""
        blocks = list(w.get("exercises") or []) + list(w.get("warm_up") or []) + list(w.get("cool_down") or [])
        for e in blocks:
            xid = e.get("exercise_id") or e.get("id")
            if not xid:
                nm = (e.get("name") or "").strip().lower()
                xid = name_to_id.get(nm)
            if not xid:
                continue
            upcoming_counts[xid] = upcoming_counts.get(xid, 0) + 1
            if wdate == tomorrow:
                tomorrow_counts[xid] = tomorrow_counts.get(xid, 0) + 1
            prev = first_seen.get(xid)
            if not prev or (wdate and wdate < prev):
                first_seen[xid] = wdate

    # --- V2 Live plan scan ---------------------------------------------------
    # The authoritative source for a client's current programme is
    # `plan_live_v2.placements` + `session_specs.payload.*.exercises`. Legacy
    # `db.workouts` may be stale or empty for V2 clients. Without this scan
    # a Live session due tomorrow (e.g. Pietro's Strength Full Body #1) never
    # bumps `used_in_tomorrow_workouts_count`, so its exercises are invisible
    # to the Needs Media queue.
    def _iter_exercise_names(payload: dict):
        """Yield every {'name': ...} entry inside a session_spec payload,
        regardless of the block key (main / warmup / cooldown / whatever)."""
        if not isinstance(payload, dict):
            return
        for _k, v in payload.items():
            if isinstance(v, dict):
                # {"exercises": [...]} pattern
                for ex in (v.get("exercises") or []):
                    if isinstance(ex, dict) and (ex.get("name") or ex.get("exercise_id")):
                        yield ex
                # nested dicts (e.g. main -> {type, exercises})
                for _kk, vv in v.items():
                    if isinstance(vv, list):
                        for ex in vv:
                            if isinstance(ex, dict) and (ex.get("name") or ex.get("exercise_id")):
                                yield ex
            elif isinstance(v, list):
                for ex in v:
                    if isinstance(ex, dict) and (ex.get("name") or ex.get("exercise_id")):
                        yield ex

    async for live in db.plan_live_v2.find(
        {"active": True},
        {"_id": 0, "placements": 1, "session_specs": 1},
    ):
        specs = live.get("session_specs") or {}
        if not isinstance(specs, dict):
            # tolerate list form
            specs = {(s.get("exposure_id") or ""): s for s in specs if isinstance(s, dict)}
        for p in (live.get("placements") or []):
            pdate = p.get("date") or ""
            if not (today <= pdate <= week):
                continue
            if p.get("kind") == "rest":
                continue
            spec = specs.get(p.get("exposure_id") or "") or {}
            for ex in _iter_exercise_names(spec.get("payload") or {}):
                xid = ex.get("exercise_id")
                if not xid:
                    nm = (ex.get("name") or "").strip().lower()
                    xid = name_to_id.get(nm)
                if not xid:
                    continue
                upcoming_counts[xid] = upcoming_counts.get(xid, 0) + 1
                if pdate == tomorrow:
                    tomorrow_counts[xid] = tomorrow_counts.get(xid, 0) + 1
                prev = first_seen.get(xid)
                if not prev or (pdate and pdate < prev):
                    first_seen[xid] = pdate
                # Iter 130c — also count alternate exercises (`subs_allowed`)
                # so the coach sees missing media BEFORE a client swaps to
                # them. Each alt is treated as an "upcoming" occurrence but
                # not a "tomorrow" one (since the client may never pick it),
                # which keeps HIGH-priority tasks focused on primary picks.
                #
                # Iter 130d — if an alt name has no library row at all, we
                # auto-create a `draft` exercises_v2 stub so it enters the
                # media queue immediately (previously these were silently
                # skipped by name_to_id, leaving Louis blind to the gap).
                # Also mirror the alias fuzzy-match layer the primary loop
                # uses ("dumbbell rdl" → "dumbbell romanian deadlift").
                for alt_name in (ex.get("subs_allowed") or []):
                    an = (alt_name or "").strip()
                    if not an:
                        continue
                    an_lc = an.lower()
                    aid = name_to_id.get(an_lc) or name_to_id.get(_ALIASES.get(an_lc, ""))
                    if not aid:
                        # Try fuzzy contains-match against the library
                        for canon, cid in name_to_id.items():
                            if an_lc == canon or an_lc in canon or canon in an_lc:
                                aid = cid
                                break
                    if not aid:
                        # Auto-create a draft stub so this alt shows up in
                        # the media queue as "needs_review". Non-destructive:
                        # if a proper library entry is added later, the coach
                        # can archive this stub. Iter181c — routes through
                        # the shared similarity gate; if a fuzzy match is
                        # found we silently REUSE it rather than creating
                        # another dupe row. Also uses the upsert-on-conflict
                        # helper so concurrent workers can't race-insert.
                        try:
                            from feature_exercise_dedup import (
                                check_duplicate_candidate,
                                record_duplicate_flag,
                                canonical_key as _ck,
                                safe_upsert_exercise,
                            )
                            match = await check_duplicate_candidate(an)
                            if match:
                                await record_duplicate_flag(
                                    proposed_name=an,
                                    matched_id=match["id"],
                                    matched_name=match.get("exercise_name") or "",
                                    score=match.get("score", 0.0),
                                    gate=match.get("gate", "unknown"),
                                    source="subs_allowed",
                                )
                                aid = match["id"]
                                name_to_id[an_lc] = aid
                                logger.info(
                                    "subs_allowed: matched existing %r for proposed %r "
                                    "(gate=%s score=%s)",
                                    match.get("exercise_name"), an,
                                    match.get("gate"), match.get("score"),
                                )
                            else:
                                aid = new_id()
                                r = await safe_upsert_exercise({
                                    "id": aid,
                                    "exercise_name": an,
                                    "canonical_name_key": _ck(an),
                                    "status": "Draft",
                                    "approval_status": "needs_review",
                                    "auto_created_from": "subs_allowed",
                                    "auto_created_at": now_iso(),
                                    "auto_created_for_exposure_id": p.get("exposure_id"),
                                    "content_status": {"images": False, "video": False, "coaching_points": False},
                                    "used_in_tomorrow_workouts_count": 0,
                                    "used_in_upcoming_workouts_count": 0,
                                    "first_scheduled_date": None,
                                })
                                aid = r["id"]
                                name_to_id[an_lc] = aid
                        except Exception:
                            logger.exception("auto-create alt stub failed for %r", an)
                            continue
                    upcoming_counts[aid] = upcoming_counts.get(aid, 0) + 1
                    prev = first_seen.get(aid)
                    if not prev or (pdate and pdate < prev):
                        first_seen[aid] = pdate

    for xid, c in upcoming_counts.items():
        await db.exercises_v2.update_one({"id": xid}, {"$set": {
            "used_in_tomorrow_workouts_count": tomorrow_counts.get(xid, 0),
            "used_in_upcoming_workouts_count": c,
            "first_scheduled_date": first_seen.get(xid),
        }})


def _priority_for_date(first_date: str | None) -> str:
    """HIGH = today/tomorrow, MEDIUM = 2-7 days, LOW = anything else."""
    if not first_date:
        return "low"
    try:
        d = _dt.date.fromisoformat(first_date)
    except Exception:
        return "low"
    delta = (d - _dt.date.today()).days
    if delta <= 1:
        return "high"
    if delta <= 7:
        return "normal"  # coach feed treats normal as medium
    return "low"


@api.post("/exercise-content/scan-todos")
async def ex_scan_todos(admin: dict = Depends(require_admin())):
    """Create Coach To-Do tasks for exercises scheduled within the next 7
    days that are missing important content. Idempotent per exercise —
    dedupes against existing open tasks. Auto-triggered by the server on
    workout writes; also safe to invoke on demand."""
    created = await run_exercise_media_scan(admin_user=admin)
    return {"created": created}


async def run_exercise_media_scan(admin_user: dict | None = None) -> int:
    """Programmatic entry point used both by the HTTP endpoint above and by
    the background worker that fires after every workout write. Returns the
    number of new coach tasks created."""
    if admin_user is None:
        admin_user = await db.users.find_one(
            {"role": "coach", "is_primary_coach": True}, {"_id": 0, "password_hash": 0},
        ) or await db.users.find_one({"role": "coach"}, {"_id": 0, "password_hash": 0})
        if not admin_user:
            return 0
    await _bump_usage_counts()
    created = 0
    async for ex in db.exercises_v2.find({"used_in_upcoming_workouts_count": {"$gt": 0}}):
        if ex.get("status") == "Live" and ex.get("approval_status") == "approved":
            continue

        missing: list[str] = []
        cs = ex.get("content_status") or {}
        # Movement-aware: check EACH required slot instead of just artwork.
        required = resolved_required_slots(ex)
        legacy_lookup = {
            "primary": "primary_image_id",
            "start":   "demo_start_image_id",
            "end":     "demo_end_image_id",
        }
        demo_slots = ex.get("demo_slots") or {}
        missing_slots: list[str] = []
        for slot in required:
            has = False
            if slot in legacy_lookup and ex.get(legacy_lookup[slot]):
                has = True
            elif demo_slots.get(slot):
                has = True
            if not has:
                missing_slots.append(slot)
        if missing_slots:
            missing.append(f"images ({', '.join(missing_slots)})")
        if not cs.get("coaching_points"):
            missing.append("coaching_points")
        if not cs.get("video"):
            missing.append("video")
        if not missing and ex.get("approval_status") != "approved":
            missing.append("approval")

        if not missing:
            continue

        kind = f"exercise_needs_{missing[0]}" if len(missing) == 1 else "exercise_needs_full_approval"
        first_date = ex.get("first_scheduled_date")
        priority = _priority_for_date(first_date)
        existing = await db.coach_tasks.find_one({
            "task_type": kind,
            "payload.exercise_id": ex["id"],
            "status": {"$in": ["todo", "open", "snoozed", "pending"]},
        })
        if existing:
            if existing.get("priority") != priority and priority == "high":
                await db.coach_tasks.update_one({"id": existing["id"]}, {"$set": {
                    "priority": priority,
                    "payload.first_scheduled_date": first_date,
                }})
            continue

        clients = ex.get("used_in_upcoming_workouts_count", 0)
        window = "today or tomorrow" if priority == "high" else "the next 7 days"
        summary = (
            f"This exercise appears in {clients} client workout"
            f"{'s' if clients != 1 else ''} in {window}. Missing: "
            f"{', '.join(missing)}."
        )
        await _create_coach_task(
            user=admin_user,
            task_type=kind,
            title=f"Approve exercise content for {ex.get('exercise_name')}",
            description=summary,
            priority=priority,
            category="exercise_content",
            payload={
                "exercise_id": ex["id"],
                "exercise_name": ex.get("exercise_name"),
                "missing": missing,
                "clients_affected": clients,
                "first_scheduled_date": first_date,
                "actions": [
                    {"key": "review", "label": "Review Exercise"},
                    {"key": "approve_all", "label": "Approve All"},
                    {"key": "regen_images", "label": "Regenerate Images"},
                    {"key": "find_video", "label": "Find Video"},
                    {"key": "snooze", "label": "Snooze"},
                    {"key": "dismiss", "label": "Dismiss"},
                ],
            },
        )
        created += 1
    return created


# ---- Coach Dashboard summary tile ----------------------------------------

@api.get("/coach/exercise-media-summary")
async def ex_media_summary(admin: dict = Depends(require_admin())):
    """Small summary used by the coach dashboard tile. Cheap Mongo counts,
    not the full library — safe to call on every dashboard mount."""
    await _bump_usage_counts()
    needed_this_week = await db.exercises_v2.count_documents({
        "used_in_upcoming_workouts_count": {"$gt": 0},
        "$or": [
            {"primary_image_id": {"$in": [None, ""]}, "demo_start_image_id": {"$in": [None, ""]}},
            {"content_status.video": {"$ne": True}},
            {"content_status.coaching_points": {"$ne": True}},
            {"approval_status": {"$ne": "approved"}},
        ],
    })
    needed_tomorrow = await db.exercises_v2.count_documents({
        "used_in_tomorrow_workouts_count": {"$gt": 0},
        "$or": [
            {"primary_image_id": {"$in": [None, ""]}, "demo_start_image_id": {"$in": [None, ""]}},
            {"content_status.video": {"$ne": True}},
            {"approval_status": {"$ne": "approved"}},
        ],
    })
    missing_videos = await db.exercises_v2.count_documents({
        "used_in_upcoming_workouts_count": {"$gt": 0},
        "content_status.video": {"$ne": True},
    })
    ready_for_review = await db.exercises_v2.count_documents({
        "approved_image_status": "Needs Review",
    })
    return {
        "needed_this_week": needed_this_week,
        "needed_tomorrow": needed_tomorrow,
        "missing_videos": missing_videos,
        "ready_for_review": ready_for_review,
    }


# ---- Prompt preview (credit control: no gen without seeing prompt first) --

@api.get("/exercise-content/{ex_id}/image-prompt")
async def ex_image_prompt_preview(
    ex_id: str,
    slot: str = "primary",
    prompt_extra: str | None = None,
    female: bool | None = None,
    persona: str | None = None,
    admin: dict = Depends(require_admin()),
):
    """Return the exact prompt that would be sent for image generation so
    the coach can review / edit / cancel BEFORE burning AI credits."""
    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex:
        raise HTTPException(404, "not found")
    valid = {"primary", "start", "end", "mid", "top", "bottom",
             "apex", "stretch", "loaded", "finish"}
    if slot not in valid:
        slot = "primary"
    resolved = _resolve_persona(persona, female)
    prompt = _build_ex_prompt(ex, slot, prompt_extra, persona=resolved)
    return {
        "exercise_id": ex_id,
        "exercise_name": ex.get("exercise_name"),
        "slot": slot,
        "persona": resolved,
        "prompt": prompt,
        "estimated_cost_usd": 0.039,   # single Nano Banana image
        "warning": "This will consume ~1 image credit on your Emergent LLM key.",
    }


# ---- Written content generation (coaching points, mistakes, alternatives) --

@api.post("/exercise-content/{ex_id}/generate-content")
async def ex_generate_content(
    ex_id: str, body: dict,
    admin: dict = Depends(require_admin()),
):
    """Generate a single written-content field for one exercise via Claude
    (Emergent LLM). Never bulk-fires. Field-scoped so the coach picks
    exactly what to fill."""
    kind = (body or {}).get("kind", "")
    if kind not in ("coaching_points", "common_mistakes", "alternatives", "instructions"):
        raise HTTPException(400, "kind must be coaching_points|common_mistakes|alternatives|instructions")
    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex:
        raise HTTPException(404, "not found")

    name = ex.get("exercise_name") or "exercise"
    equipment = ", ".join(ex.get("equipment_type") or []) or "bodyweight"
    body_area = ex.get("body_area") or ""
    difficulty = ex.get("difficulty_level") or "intermediate"

    task = {
        "coaching_points":  "Return 4–6 short concise coaching points (imperative, one line each). Focus on technique cues an aviation-crew client can execute in a hotel gym.",
        "common_mistakes":  "Return 3–5 common mistakes clients make with this exercise. Each item is one short sentence.",
        "alternatives":     "Return 3–5 alternative exercises that train the same pattern, ordered by similarity. Only the exercise names, no explanation.",
        "instructions":     "Return 3–5 sentences of client-facing plain-English instructions for how to perform the exercise, written warmly (as if Louis is coaching the client through it).",
    }[kind]

    system = (
        "You are Louis Hall, CrewFit's founder and aviation performance coach. "
        "Write like a real coach: direct, practical, safety-aware. Never make "
        "medical claims. Never diagnose. Always assume the client has limited "
        "equipment and is on the road."
    )
    prompt = (
        f"Exercise: {name}\nEquipment: {equipment}\nBody area: {body_area}\n"
        f"Difficulty: {difficulty}\n\n{task}\n\n"
        "OUTPUT: strict JSON matching one of these shapes based on the task above. "
        "For lists: {\"items\": [\"string\", ...]}. "
        "For instructions: {\"text\": \"one paragraph\"}. "
        "No prose outside the JSON."
    )

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"ex-content-{ex_id}-{kind}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929").with_params(max_tokens=500)
        reply = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:
        logger.exception("content gen failed for %s/%s", ex_id, kind)
        raise HTTPException(502, f"Content generation failed: {e}")

    import json, re
    text = str(reply or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    try:
        parsed = json.loads(m.group(0)) if m else {}
    except Exception:
        parsed = {}

    updates: dict = {"updated_at": now_iso()}
    result_payload: dict = {"kind": kind}

    if kind == "instructions":
        val = str(parsed.get("text") or text).strip()
        updates["client_facing_instructions"] = val
        result_payload["text"] = val
    else:
        items = parsed.get("items") or []
        if not isinstance(items, list):
            items = []
        # Fallback: try to split lines if JSON failed.
        if not items and text:
            items = [ln.lstrip("-• 0123456789.").strip() for ln in text.splitlines() if ln.strip()][:6]
        items = [str(i).strip() for i in items if str(i).strip()][:6]
        field_map = {
            "coaching_points": "coaching_points",
            "common_mistakes": "common_mistakes",
            "alternatives":    "alternatives",
        }
        updates[field_map[kind]] = items
        if kind == "coaching_points":
            updates["content_status.coaching_points"] = bool(items)
        result_payload["items"] = items

    await db.exercises_v2.update_one({"id": ex_id}, {"$set": updates})

    # Manual Mode Stage D — Atlas alternatives: when the LLM returns
    # alternative exercise names, they must become REAL library records
    # (drafts if new) so the coach media queue and swap-menu can use them
    # instead of dangling strings. Idempotent — dedup handled downstream.
    if kind == "alternatives" and result_payload.get("items"):
        try:
            from feature_media_queue import resolve_or_draft_exercise
            alt_ids: list[str] = []
            for alt_name in result_payload["items"]:
                xid = await resolve_or_draft_exercise(
                    alt_name,
                    user=admin,           # coach/admin is the requesting actor
                    parent=ex,            # copy movement_pattern / body_area / kit
                    reason=f"atlas_alternative_of:{ex.get('exercise_name') or ex_id}",
                )
                if xid:
                    alt_ids.append(xid)
            # Persist the resolved ids so the frontend can hop straight to
            # each alternative's library entry without a re-lookup.
            await db.exercises_v2.update_one(
                {"id": ex_id},
                {"$set": {"alternative_exercise_ids": alt_ids, "updated_at": now_iso()}},
            )
            result_payload["alternative_exercise_ids"] = alt_ids
        except Exception:
            logger.exception("atlas alternatives library backfill failed for %s", ex_id)

    await _log(ex_id, admin["id"], "content_generated", f"kind={kind}")
    # Record AI usage for telemetry.
    try:
        await db.ai_usage.insert_one({
            "user_id": admin["id"],
            "feature": f"exercise_content_{kind}",
            "exercise_id": ex_id,
            "tokens_estimate": 500,
            "created_at": now_iso(),
        })
    except Exception:
        pass

    fresh = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    return {"exercise": fresh, **result_payload}

