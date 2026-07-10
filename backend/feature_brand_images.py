"""feature_brand_images — CrewFit V1.5 AI-generated visual library.

Uses Gemini Nano Banana (gemini-3.1-flash-image-preview) via emergentintegrations
to seed a small library of premium branded images that CrewFit renders on:
 - client home hero
 - workout header card
 - recovery / standby / event countdown cards

Design decisions:
 - LIBRARY-FIRST: we don't call the image model per-user. Instead a curated
   set of ~8 context-keyed images is generated once (admin can regenerate any).
 - Storage: raw PNG bytes written to /app/backend/uploads/brand_images/<id>.png
 - Metadata: crewfit_images collection with a `context` dict for smart picking.
 - Fallback: if the library is empty for a context, /pick falls back to
   `hero_default`; if that too is missing, returns 404 and the frontend uses
   a solid-color placeholder.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from typing import Any, Optional
import asyncio
import base64
import os

from server import (
    api, db, current_user, require_admin, new_id, now_iso, logger,
    EMERGENT_LLM_KEY,
)


BRAND_ROOT = Path(os.environ.get("BRAND_IMAGE_ROOT", "/app/backend/uploads/brand_images"))
BRAND_ROOT.mkdir(parents=True, exist_ok=True)


# ---- Prompt template + library seed ---------------------------------------

BASE_STYLE = (
    "Premium dark aviation fitness app image, minimalist cinematic style, "
    "realistic athletic person, aviation lifestyle context, deep black and "
    "navy background, subtle crimson red accent lighting, airport hotel / "
    "aircraft / runway / travel environment cues, professional performance "
    "coaching feel, clean composition, portrait 3:4 aspect, "
    "not bodybuilding, not shirtless, not exaggerated muscles, not stock "
    "photo, not cartoon, not sexualised, high-end mobile app visual."
)

# Category → (prompt suffix, matching-context spec used by /pick)
LIBRARY: list[dict] = [
    {
        "key": "hero_default",
        "category": "hero",
        "prompt": f"{BASE_STYLE} Wide cinematic view of a runway at dusk with a "
                  f"single subtle silhouette of an athletic pilot in the foreground, "
                  f"deep navy sky, distant aircraft lights, calm and focused.",
        "context": {},
    },
    {
        "key": "hero_pilot_male",
        "category": "hero",
        "prompt": f"{BASE_STYLE} Realistic male commercial airline pilot in dark "
                  f"training kit, lean athletic build (not bodybuilder), standing "
                  f"in a hotel hallway with luggage nearby, calm and focused, "
                  f"warm subtle crimson accent from a window.",
        "context": {"role": "pilot", "gender": "male"},
    },
    {
        "key": "hero_pilot_female",
        "category": "hero",
        "prompt": f"{BASE_STYLE} Realistic female commercial airline pilot in "
                  f"dark athletic-fit training kit, lean athletic build, standing "
                  f"in a modern airport lounge with subtle crimson accent light, "
                  f"calm and focused, professional.",
        "context": {"role": "pilot", "gender": "female"},
    },
    {
        "key": "hero_cabin_crew_female",
        "category": "hero",
        "prompt": f"{BASE_STYLE} Realistic female cabin-crew athlete doing gentle "
                  f"mobility in a modern airport hotel room, minimalist cinematic "
                  f"lighting, deep navy tones, calm recovery focus.",
        "context": {"role": "cabin_crew", "gender": "female"},
    },
    {
        "key": "workout_strength_hotel_gym",
        "category": "workout",
        "prompt": f"{BASE_STYLE} Realistic aviation-uniformed athlete doing "
                  f"controlled dumbbell strength training in a small hotel gym, "
                  f"warm downlight, aviation travel context (jacket on chair), "
                  f"athletic but not bodybuilder, professional.",
        "context": {"workout_type": "strength"},
    },
    {
        "key": "workout_endurance_marathon",
        "category": "workout",
        "prompt": f"{BASE_STYLE} Realistic long-distance runner training on an "
                  f"empty runway at dawn, subtle red taxiway lights receding into "
                  f"the distance, focused endurance aesthetic, aviation lifestyle.",
        "context": {"workout_type": "endurance", "goal": "marathon"},
    },
    {
        "key": "recovery_long_haul",
        "category": "recovery",
        "prompt": f"{BASE_STYLE} Minimalist image showing long-haul travel "
                  f"recovery — a modern airport hotel room at night with a glass "
                  f"of water, foam roller, dim bedside light, jetlag recovery "
                  f"aesthetic, calm and clinical.",
        "context": {"context": "recovery", "day_type": "long_haul"},
    },
    {
        "key": "standby_readiness",
        "category": "standby",
        "prompt": f"{BASE_STYLE} Minimalist aviation-themed image with an airport "
                  f"lounge in the background and a pilot's flight bag / uniform "
                  f"neatly folded, subtle radar-scope glow on a small screen, "
                  f"low-fatigue readiness theme, no visible people.",
        "context": {"context": "standby"},
    },
    {
        "key": "event_countdown",
        "category": "event",
        "prompt": f"{BASE_STYLE} Realistic race-day scene at a professional "
                  f"start line at dawn — race arch silhouette, empty course, "
                  f"crimson banner accent, focused pre-race energy, aviation "
                  f"travel bag on the ground.",
        "context": {"context": "event", "phase": "peak"},
    },
]


def _score_context(entry_ctx: dict, query_ctx: dict) -> int:
    """Simple context-matching score. Highest wins in /pick."""
    if not entry_ctx:
        return 0
    score = 0
    for k, v in entry_ctx.items():
        if not v:
            continue
        if query_ctx.get(k) == v:
            score += 3
        elif query_ctx.get(k):
            score -= 1     # mismatch on a specified key
    return score


# ---- Nano Banana generator ------------------------------------------------

MODEL_ID = "gemini-3.1-flash-image-preview"


async def _generate_image_bytes(prompt: str, session_id: str) -> bytes:
    """Call Nano Banana and return raw PNG bytes.

    Uses emergentintegrations LlmChat with modalities=[image,text].
    Raises HTTPException on failure so the background task can persist an error state.
    """
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:
        raise HTTPException(500, f"emergentintegrations missing: {e}")

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message="You are a premium visual designer for CrewFit, an elite aviation performance coaching app.",
    )
    chat.with_model("gemini", MODEL_ID).with_params(modalities=["image", "text"])

    try:
        _text, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    except Exception as e:
        raise HTTPException(502, f"nano banana call failed: {str(e)[:200]}")
    if not images:
        raise HTTPException(502, "nano banana returned no image")
    img0 = images[0]
    data = img0.get("data") if isinstance(img0, dict) else None
    if not data:
        raise HTTPException(502, "nano banana returned empty image data")
    return base64.b64decode(data)


async def _run_generate_job(image_id: str) -> None:
    doc = await db.crewfit_images.find_one({"id": image_id})
    if not doc:
        return
    try:
        await db.crewfit_images.update_one({"id": image_id},
            {"$set": {"status": "generating", "updated_at": now_iso()}})
        raw = await _generate_image_bytes(doc["prompt"], session_id=f"brand-{image_id}")
        path = BRAND_ROOT / f"{image_id}.png"
        path.write_bytes(raw)
        await db.crewfit_images.update_one({"id": image_id},
            {"$set": {
                "status": "ready",
                "storage_path": str(path),
                "size_bytes": len(raw),
                "mime": "image/png",
                "error": None,
                "updated_at": now_iso(),
            }})
    except HTTPException as he:
        logger.warning("brand image job failed: %s", he.detail)
        await db.crewfit_images.update_one({"id": image_id},
            {"$set": {"status": "failed", "error": he.detail, "updated_at": now_iso()}})
    except Exception as e:
        logger.exception("brand image job crashed")
        await db.crewfit_images.update_one({"id": image_id},
            {"$set": {"status": "failed", "error": str(e)[:400], "updated_at": now_iso()}})


# ---- API ------------------------------------------------------------------

class RegenBody(BaseModel):
    prompt: Optional[str] = None


class PatchBody(BaseModel):
    is_default: Optional[bool] = None
    status: Optional[str] = None       # "ready"|"hidden"|"approved" (approved==ready in V1)
    label: Optional[str] = None


@api.post("/brand-images/seed")
async def brand_images_seed(admin: dict = Depends(require_admin())):
    """Create pending entries for each library category (if missing) and kick off generation."""
    created = []
    for spec in LIBRARY:
        existing = await db.crewfit_images.find_one({"key": spec["key"]})
        if existing:
            continue
        image_id = new_id()
        now = now_iso()
        doc = {
            "id": image_id,
            "key": spec["key"],
            "category": spec["category"],
            "context": spec["context"],
            "prompt": spec["prompt"],
            "status": "pending",
            "is_default": True,
            "label": spec["key"].replace("_", " ").title(),
            "storage_path": None,
            "size_bytes": None,
            "mime": None,
            "error": None,
            "created_by": admin["id"],
            "created_at": now,
            "updated_at": now,
        }
        await db.crewfit_images.insert_one(doc)
        created.append(image_id)
        asyncio.create_task(_run_generate_job(image_id))
    return {"created": created, "count": len(created)}


@api.get("/brand-images")
async def brand_images_list(
    _: dict = Depends(current_user),
    category: Optional[str] = None,
    include_hidden: bool = False,
):
    q: dict = {}
    if category:
        q["category"] = category
    if not include_hidden:
        q["status"] = {"$ne": "hidden"}
    rows = await db.crewfit_images.find(q, {"_id": 0, "storage_path": 0}).to_list(200)
    return {"images": rows, "count": len(rows)}


@api.get("/brand-images/pick")
async def brand_images_pick(
    role: Optional[str] = None,
    gender: Optional[str] = None,
    goal: Optional[str] = None,
    workout_type: Optional[str] = None,
    phase: Optional[str] = None,
    context: Optional[str] = None,
    day_type: Optional[str] = None,
    _: dict = Depends(current_user),
):
    """Return the best-matching READY image for a context; falls back to hero_default."""
    query_ctx = {k: v for k, v in {
        "role": role, "gender": gender, "goal": goal,
        "workout_type": workout_type, "phase": phase,
        "context": context, "day_type": day_type,
    }.items() if v}

    rows = await db.crewfit_images.find(
        {"status": "ready"}, {"_id": 0, "storage_path": 0},
    ).to_list(200)
    if not rows:
        raise HTTPException(404, "no ready images yet")

    scored = [(r, _score_context(r.get("context") or {}, query_ctx)) for r in rows]
    scored.sort(key=lambda t: t[1], reverse=True)
    # Prefer default among ties
    best_score = scored[0][1]
    winners = [r for r, s in scored if s == best_score]
    winners.sort(key=lambda r: (not r.get("is_default"), r.get("key") != "hero_default"))
    winner = winners[0]
    return {"image": winner, "match_score": best_score, "candidates": len(rows)}


@api.get("/brand-images/{image_id}/stream")
async def brand_image_stream(
    image_id: str,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Public-ish streaming. Requires auth (header or ?token=) — used by <Image>."""
    if authorization and authorization.startswith("Bearer "):
        await current_user(authorization=authorization)
    else:
        # Reuse the profile helper for query-token auth
        from feature_profile import _user_from_token
        await _user_from_token(token)
    doc = await db.crewfit_images.find_one({"id": image_id})
    if not doc:
        raise HTTPException(404, "image not found")
    path = doc.get("storage_path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "image file missing")
    return FileResponse(path, media_type=doc.get("mime") or "image/png")


@api.post("/brand-images/{image_id}/regenerate")
async def brand_image_regenerate(image_id: str, body: RegenBody = RegenBody(),
                                 admin: dict = Depends(require_admin())):
    doc = await db.crewfit_images.find_one({"id": image_id})
    if not doc:
        raise HTTPException(404, "image not found")
    if doc.get("status") == "generating":
        raise HTTPException(409, "already generating")
    updates: dict = {"status": "pending", "error": None, "updated_at": now_iso()}
    if body.prompt:
        updates["prompt"] = body.prompt
    await db.crewfit_images.update_one({"id": image_id}, {"$set": updates})
    asyncio.create_task(_run_generate_job(image_id))
    return {"ok": True}


@api.patch("/brand-images/{image_id}")
async def brand_image_patch(image_id: str, body: PatchBody,
                            admin: dict = Depends(require_admin())):
    doc = await db.crewfit_images.find_one({"id": image_id})
    if not doc:
        raise HTTPException(404, "image not found")
    updates: dict = {"updated_at": now_iso()}
    if body.is_default is not None: updates["is_default"] = body.is_default
    if body.status is not None:
        if body.status not in ("ready", "hidden", "approved"):
            raise HTTPException(400, "invalid status")
        updates["status"] = "ready" if body.status == "approved" else body.status
    if body.label is not None: updates["label"] = body.label
    await db.crewfit_images.update_one({"id": image_id}, {"$set": updates})
    return {"ok": True}


@api.delete("/brand-images/{image_id}")
async def brand_image_delete(image_id: str, admin: dict = Depends(require_admin())):
    doc = await db.crewfit_images.find_one({"id": image_id})
    if not doc:
        raise HTTPException(404, "image not found")
    path = doc.get("storage_path")
    if path:
        try: Path(path).unlink(missing_ok=True)
        except Exception: pass
    await db.crewfit_images.update_one({"id": image_id},
        {"$set": {"status": "hidden", "storage_path": None, "updated_at": now_iso()}})
    return {"ok": True}
