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

    @router.get("/coach/flight-support/media-queue")
    async def coach_media_queue(
        status: str = Query("all", description="all | needs_media | complete"),
        persona_missing: str = Query(
            "any", description="any | pilot | louis | female — filter by which persona is missing"
        ),
        search: str = Query("", description="Case-insensitive substring on exercise_name"),
        limit: int = Query(200, ge=1, le=1000),
        user=Depends(get_current_user),
    ):
        """Return the Media Queue matrix: one row per exercise with which
        (persona × slot) frames are covered vs missing.

        Coach-only. Rows are sorted so PILOT-missing entries surface first
        (that's the whole point of the Phase 2 upgrade), followed by
        LOUIS-missing, then FEMALE-missing, then complete.
        """
        from server import db  # lazy import to avoid circularity
        if (user.get("role") or "").lower() not in ("coach", "admin"):
            raise HTTPException(403, "coach only")

        q: dict = {"used_in_flight_support": True}
        if status == "needs_media":
            q["status"] = "needs_media"
        elif status == "complete":
            q["status"] = "complete"
        if search:
            import re as _re
            q["exercise_name"] = {"$regex": _re.escape(search), "$options": "i"}

        rows: list[dict] = []
        cursor = db.media_queue.find(q, {"_id": 0}).limit(limit)
        async for row in cursor:
            personas = row.get("personas") or {}
            missing = row.get("missing") or {}
            # If the row is older and doesn't have `missing` derived, compute it.
            if not missing:
                all_slots = set(ORDERED_SLOTS)
                missing = {
                    p: sorted(list(all_slots - set(personas.get(p) or [])))
                    for p in SUPPORTED_PERSONAS
                }
            # Persona missing filter
            if persona_missing in SUPPORTED_PERSONAS:
                if not (missing.get(persona_missing) or []):
                    continue
            # Build matrix cells (persona × slot → bool)
            matrix = {
                p: {slot: (slot in (personas.get(p) or [])) for slot in ORDERED_SLOTS}
                for p in SUPPORTED_PERSONAS
            }
            covered_count = sum(
                1 for p in SUPPORTED_PERSONAS
                for s in ORDERED_SLOTS if matrix[p][s]
            )
            row_out = {
                "exercise_id": row.get("exercise_id"),
                "exercise_name": row.get("exercise_name") or "",
                "status": row.get("status") or ("complete" if covered_count == 9 else "needs_media"),
                "preferred_persona": row.get("preferred_persona") or "pilot",
                "matrix": matrix,
                "missing": missing,
                "covered": covered_count,
                "total_cells": 9,
                "flight_support_contexts": row.get("flight_support_contexts") or [],
                "updated_at": row.get("updated_at"),
            }
            rows.append(row_out)

        # Priority sort: pilot-missing first, then louis-missing, then female-missing, then complete.
        def _sort_key(r: dict) -> tuple:
            pilot_miss = len(r["missing"].get("pilot") or [])
            louis_miss = len(r["missing"].get("louis") or [])
            female_miss = len(r["missing"].get("female") or [])
            # Highest priority (lowest tuple) = most pilot-missing
            return (
                -pilot_miss,           # more pilot-missing = higher (more negative)
                -louis_miss,
                -female_miss,
                r["exercise_name"].lower(),
            )

        rows.sort(key=_sort_key)

        # Aggregate stats for the dashboard header
        stats = {
            "total": len(rows),
            "needs_media": sum(1 for r in rows if r["status"] == "needs_media"),
            "complete": sum(1 for r in rows if r["status"] == "complete"),
            "pilot_missing_count": sum(1 for r in rows if r["missing"].get("pilot")),
            "louis_missing_count": sum(1 for r in rows if r["missing"].get("louis")),
            "female_missing_count": sum(1 for r in rows if r["missing"].get("female")),
        }

        return {"items": rows, "stats": stats}

    app.include_router(router)
    logger.info(
        "feature_flight_support_media: /api/exercise-content/frames + "
        "/api/coach/flight-support/media-queue registered"
    )


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
