"""
feature_media_queue — Shared coach media-queue helpers (Manual-Mode Stage F).

Central place for pushing missing exercises into the coach media queue so that
every writer in the app (Manual Workouts, Traffic Light variants, Atlas
alternatives, Flight Support fallback) files draft requests via ONE canonical
path. Removes the risk of stranded exercises with no library record and no
media coverage.

Public API:
  * resolve_or_draft_exercise(name, *, user, parent=None, reason, ...) → id|None
        Look an exercise up in db.exercises_v2 by name. If found, return its
        id. If not, file a draft-requested library record via
        create_exercise_request_if_missing so the coach can approve it later.
  * scan_media_queue_for_sections(client, sections, workout_id) → list[dict]
        For each exercise across the given sections, queue a draft request if
        the exercises_v2 row is missing or missing media (image OR video).
        Dedup'd by exercise_id.
  * backfill_exercise_ids(items, *, user, reason, workout_id=None, parent=None)
        In-place mutate a list of exercise dicts so every item that has a name
        but no exercise_id gets one, creating a draft library record if
        needed. Used by Traffic Light red-variant template rows that ship
        with names only.

Design notes:
  * All operations are idempotent — safe to call on every workout save.
  * We NEVER create duplicate library records — de-dup happens inside
    create_exercise_request_if_missing (case/punctuation insensitive).
  * Failures are logged but never raise — media queue backfill must never
    break a workout save.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from server import db, logger


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

async def resolve_or_draft_exercise(
    name: str,
    *,
    user: dict,
    parent: Optional[dict] = None,
    reason: str = "media_queue_backfill",
    programme_id: Optional[str] = None,
    workout_id: Optional[str] = None,
) -> Optional[str]:
    """Return the exercises_v2 id for `name`, creating a draft if absent.

    `parent` is an optional exercises_v2 doc whose movement_pattern /
    body_area / equipment_type / tags will be copied to the new draft — used
    when we're queueing an "alternative" of an existing library exercise so
    the draft carries useful metadata from day one.
    """
    if not name or not str(name).strip():
        return None
    try:
        from feature_v2_resolver import create_exercise_request_if_missing
    except Exception:
        logger.exception("media_queue: cannot import create_exercise_request_if_missing")
        return None
    item: dict[str, Any] = {"name": str(name).strip()}
    if parent:
        if parent.get("movement_pattern"):
            item["movement_pattern"] = parent.get("movement_pattern")
        if parent.get("body_area"):
            item["body_area"] = parent.get("body_area")
        if parent.get("equipment_type"):
            item["equipment_type"] = parent.get("equipment_type") or []
        if parent.get("difficulty_level"):
            item["difficulty_level"] = parent.get("difficulty_level")
        if parent.get("tags"):
            item["tags"] = parent.get("tags") or []
    try:
        return await create_exercise_request_if_missing(
            item,
            user=user,
            programme_id=programme_id,
            workout_id=workout_id,
            reason=reason,
        )
    except Exception:
        logger.exception("media_queue: resolve_or_draft_exercise failed for %s", name)
        return None


async def scan_media_queue_for_sections(
    client: dict,
    sections: dict[str, list[dict]],
    workout_id: Optional[str] = None,
    *,
    reason: str = "coach_media_queue_scan",
) -> list[dict]:
    """For each exercise across the given section lists, queue a draft
    request if the exercises_v2 row is missing or has no media yet.

    `sections` is a plain dict e.g. {"warmup": [...], "main": [...],
    "cooldown": [...], "amber": [...], "red": [...]}. Dedup'd across the
    whole payload by exercise_id (so amber ↔ green overlap doesn't double-
    file).
    """
    try:
        from feature_v2_resolver import create_exercise_request_if_missing
    except Exception:
        logger.exception("media_queue: cannot import create_exercise_request_if_missing")
        return []
    queued: list[dict] = []
    seen: set[str] = set()
    for _section, items in (sections or {}).items():
        for e in items or []:
            xid = e.get("exercise_id")
            if not xid:
                continue
            if xid in seen:
                continue
            seen.add(xid)
            v2 = await db.exercises_v2.find_one({"id": xid}, {"_id": 0})
            if not v2:
                try:
                    await create_exercise_request_if_missing(
                        {"name": e.get("name") or xid},
                        user=client, programme_id=None, workout_id=workout_id,
                        reason=reason,
                    )
                    queued.append({"exercise_id": xid, "name": e.get("name") or xid})
                except Exception:
                    logger.exception("media_queue: create_exercise_request_if_missing failed for %s", xid)
                continue
            has_image = bool(v2.get("primary_image_url"))
            has_video = bool(v2.get("primary_video_url"))
            status = (v2.get("status") or "").lower()
            approved = status in ("approved", "live")
            if approved and (has_image or has_video):
                continue
            try:
                await create_exercise_request_if_missing(
                    {
                        "name": v2.get("exercise_name") or e.get("name") or xid,
                        "movement_pattern": v2.get("movement_pattern"),
                        "body_area": v2.get("body_area"),
                        "equipment_type": v2.get("equipment_type") or [],
                        "difficulty_level": v2.get("difficulty_level"),
                        "tags": v2.get("tags") or [],
                    },
                    user=client, programme_id=None, workout_id=workout_id,
                    reason=f"{reason}_missing_media",
                )
                queued.append(
                    {"exercise_id": xid,
                     "name": v2.get("exercise_name") or e.get("name") or xid}
                )
            except Exception:
                logger.exception("media_queue: create_exercise_request_if_missing failed for %s", xid)
    return queued


async def backfill_exercise_ids(
    items: list[dict],
    *,
    user: dict,
    reason: str,
    workout_id: Optional[str] = None,
    parent: Optional[dict] = None,
) -> list[dict]:
    """Mutate `items` in place — for every entry without an exercise_id,
    look the name up in the library and either attach an existing id or
    create a fresh draft. Returns the (same) mutated list.

    Used by Traffic Light red-variant hardcoded template rows and Atlas
    alternatives which only carry `name`.
    """
    if not items:
        return items
    for e in items:
        if e.get("exercise_id"):
            continue
        name = (e.get("name") or "").strip()
        if not name:
            continue
        xid = await resolve_or_draft_exercise(
            name, user=user, parent=parent,
            reason=reason, workout_id=workout_id,
        )
        if xid:
            e["exercise_id"] = xid
    return items


__all__ = [
    "resolve_or_draft_exercise",
    "scan_media_queue_for_sections",
    "backfill_exercise_ids",
]
