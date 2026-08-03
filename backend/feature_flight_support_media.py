"""
feature_flight_support_media.py — Iter 128

Media resolver for Flight Support.

Contract:
  GET /api/exercise-content/frames/{exercise_id}?persona=pilot
    → {
        exercise_id, name, persona_used, frames: [
          {slot: "start", url: "/api/exercise-content/images/<id>/stream", persona: "pilot"},
          {slot: "mid",   url: "…",  persona: "louis"},   # fallback happened
          {slot: "end",   url: "…",  persona: "pilot"},
        ],
        missing: [],
        media_queue_ids: [...],
      }

Persona preference for Flight Support is:
  pilot → louis (male) → female → any-ready

Backward-compat:
  Legacy exercise_content_images have `female: bool`, no `persona` field.
  We treat  female=True  →  persona="female"
            female=False → persona="louis"
  New pilot images are stored with persona="pilot".

Missing-media pipeline:
  Any missing (persona=pilot, slot=X) gets one canonical Media Queue row per
  exercise. We do NOT create one row per (persona, slot). The queue row has:
    exercise_id (unique key), personas: {louis:[..], female:[..], pilot:[..]},
    used_in_flight_support: true, flight_support_contexts: ["pre_flight", ...]
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends

logger = logging.getLogger("crewfit.flight_support_media")
router = APIRouter(prefix="/api", tags=["flight-support-media"])

ORDERED_SLOTS = ("start", "mid", "end")
PERSONA_FALLBACK = ["pilot", "louis", "female"]
SUPPORTED_PERSONAS = ("louis", "female", "pilot")


def _persona_of(img: dict) -> str:
    """Resolve persona of an existing exercise_content_images row."""
    p = img.get("persona")
    if p in SUPPORTED_PERSONAS:
        return p
    return "female" if img.get("female") else "louis"


async def resolve_flight_support_frames(db, key: str, prefer: str = "pilot") -> dict:
    """Return the ordered START/MID/END frames for Flight Support.

    `key` may be either an exercise id OR a case-insensitive exercise name.
    Looks in `exercises` (canonical library, `.name`) then falls back to
    `exercises_v2` (`.exercise_name`) and finally `exercise_content` for
    forward compatibility.
    """
    import re as _re
    ex = None
    name_regex = {"$regex": f"^{_re.escape(key.strip())}$", "$options": "i"}
    for (coll, name_field) in (
        ("exercises",         "name"),
        ("exercises_v2",      "exercise_name"),
        ("exercise_content",  "name"),
    ):
        # First by id
        ex = await db[coll].find_one({"id": key})
        if not ex:
            ex = await db[coll].find_one({name_field: name_regex})
        if ex:
            ex["_name"] = ex.get(name_field) or ex.get("name")
            break
    if not ex:
        raise HTTPException(404, "exercise not found")
    exercise_id = ex.get("id")

    # Pull all ready images for this exercise, grouped by (persona, slot).
    cursor = db.exercise_content_images.find({
        "exercise_id": exercise_id,
        "status": "ready",
    })
    by_key: dict[tuple[str, str], dict] = {}
    coverage: dict[str, set] = {"louis": set(), "female": set(), "pilot": set()}
    async for img in cursor:
        persona = _persona_of(img)
        slot = (img.get("slot") or "").lower()
        if slot not in ORDERED_SLOTS:
            continue
        by_key[(persona, slot)] = img
        coverage[persona].add(slot)

    # Build the resolved frame sequence with persona-fallback per slot.
    prefer = prefer if prefer in SUPPORTED_PERSONAS else "pilot"
    fallback_chain = [prefer] + [p for p in PERSONA_FALLBACK if p != prefer]

    frames: list[dict] = []
    missing_slots: list[str] = []
    for slot in ORDERED_SLOTS:
        picked = None
        picked_persona = None
        for persona in fallback_chain:
            img = by_key.get((persona, slot))
            if img:
                picked = img
                picked_persona = persona
                break
        if picked:
            frames.append({
                "slot": slot,
                "url": f"/api/exercise-content/images/{picked.get('id')}/stream",
                "persona": picked_persona,
                "image_id": picked.get("id"),
            })
        else:
            missing_slots.append(slot)

    # Upsert Media Queue row if we're missing preferred-persona coverage.
    prefer_missing = [s for s in ORDERED_SLOTS if not by_key.get((prefer, s))]
    if prefer_missing:
        await _upsert_media_queue(
            db=db,
            exercise_id=exercise_id,
            exercise_name=ex.get("_name") or ex.get("name") or ex.get("exercise_name") or "",
            coverage={p: sorted(list(v)) for p, v in coverage.items()},
            preferred_persona=prefer,
            preferred_missing=prefer_missing,
        )
        # Manual Mode Stage F — also file a draft on the coach media queue
        # (exercises_v2 request_count / demand queue) so Flight Support
        # gaps show up alongside manual-workout gaps in the same coach UI.
        # Never blocks the response.
        try:
            from feature_media_queue import scan_media_queue_for_sections
            await scan_media_queue_for_sections(
                {"id": None},
                {"flight_support": [{
                    "exercise_id": exercise_id,
                    "name": ex.get("_name") or ex.get("name") or ex.get("exercise_name") or "",
                }]},
                workout_id=None,
                reason="flight_support_media_gap",
            )
        except Exception:
            logger.exception("flight_support: coach media queue backfill failed for %s", exercise_id)

    return {
        "exercise_id": exercise_id,
        "name": ex.get("_name") or ex.get("name") or ex.get("exercise_name"),
        "persona_preferred": prefer,
        "frames": frames,
        "missing_slots": missing_slots,           # slots with ZERO media in any persona
        "preferred_persona_missing": prefer_missing,
        "coverage": {p: sorted(list(v)) for p, v in coverage.items()},
    }


async def _upsert_media_queue(
    *, db, exercise_id: str, exercise_name: str,
    coverage: dict, preferred_persona: str, preferred_missing: list,
) -> None:
    """One canonical Media Queue row per exercise. Never duplicate.

    Row shape (extends the existing media queue collection):
      { exercise_id, exercise_name,
        used_in_flight_support: true,
        flight_support_contexts: ["pre_flight"|"post_flight"|"layover"|"turnaround"],
        personas: {louis: [slots], female: [slots], pilot: [slots]},
        missing: {louis: [], female: [], pilot: []},
        preferred_persona: "pilot",
        status: "needs_media" | "complete",
        updated_at }
    """
    all_slots = set(ORDERED_SLOTS)
    missing_by_persona = {
        p: sorted(list(all_slots - set(covered)))
        for p, covered in coverage.items()
    }
    is_complete = not any(missing_by_persona.get(p) for p in ("louis", "female", "pilot"))

    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    await db.media_queue.update_one(
        {"exercise_id": exercise_id},
        {
            "$set": {
                "exercise_id":              exercise_id,
                "exercise_name":            exercise_name,
                "used_in_flight_support":   True,
                "personas":                 coverage,
                "missing":                  missing_by_persona,
                "preferred_persona":        preferred_persona,
                "status":                   "complete" if is_complete else "needs_media",
                "updated_at":               now,
            },
            "$setOnInsert": {
                "created_at":  now,
                "flight_support_contexts": [],
            },
        },
        upsert=True,
    )


# ---- REST endpoint ---------------------------------------------------------
def register_routes(app, get_current_user):
    @router.get("/exercise-content/frames/{key:path}")
    async def get_frames(
        key: str,
        persona: str = Query("pilot"),
        user=Depends(get_current_user),
    ):
        # DB is imported lazily to avoid circular imports with server.py
        from server import db
        return await resolve_flight_support_frames(db, key, prefer=persona)

    app.include_router(router)
    logger.info("feature_flight_support_media: /api/exercise-content/frames registered")


# ---- Migration helper — call once at startup ------------------------------
async def backfill_personas(db) -> dict:
    """One-shot: set persona field on legacy exercise_content_images rows.

    - female=True  →  persona="female"
    - otherwise    →  persona="louis"

    Idempotent: only updates rows where `persona` is missing/unrecognised.
    """
    rf = await db.exercise_content_images.update_many(
        {"female": True, "persona": {"$nin": list(SUPPORTED_PERSONAS)}},
        {"$set": {"persona": "female"}},
    )
    rm = await db.exercise_content_images.update_many(
        {"female": {"$ne": True}, "persona": {"$nin": list(SUPPORTED_PERSONAS)}},
        {"$set": {"persona": "louis"}},
    )
    return {"female_backfilled": rf.modified_count, "louis_backfilled": rm.modified_count}
