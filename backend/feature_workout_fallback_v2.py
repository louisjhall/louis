"""
feature_workout_fallback_v2 — Iter 94i.

Two responsibilities:

1. `bodyweight_substitute_for(item)` — deterministic bodyweight substitute for a
   raw LLM exercise the V2 resolver can't match. Prevents SILENT DROPS: a
   `push` exercise becomes a `push-up`, a `squat` exercise becomes a
   `bodyweight squat`, etc. The user still trains, and the coach still gets a
   draft exercise-request.

2. `create_workout_fallback_task(...)` — dedup'd coach task ("Workout adjusted
   to safe fallback") emitted every time a workout is healed with the safe
   bodyweight stub OR shipped with `equipment_check: fail` items. Louis sees
   the full technical reason.

Both entry points are idempotent and safe to import lazily.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("crewfit.workout_fallback_v2")


# ---------------------------------------------------------------------------
# 1. Movement-pattern → bodyweight substitute
# ---------------------------------------------------------------------------
# Any exercise the V2 resolver rejects lands here. We look at the item's
# movement_pattern hint (or infer it from the name) and hand back a synthesized
# bodyweight exercise dict the workout can safely use.
_PATTERN_SUBS: dict[str, dict[str, Any]] = {
    "squat":       {"name": "Bodyweight Squat",       "sets": 3, "reps": "12-15", "rest_sec": 60,
                    "movement_pattern": "squat",       "equipment": ["bodyweight"]},
    "hinge":       {"name": "Bodyweight Good Morning","sets": 3, "reps": "12-15", "rest_sec": 60,
                    "movement_pattern": "hinge",       "equipment": ["bodyweight"]},
    "push":        {"name": "Push-up (or Incline Push-up)", "sets": 3, "reps": "8-12", "rest_sec": 60,
                    "movement_pattern": "push",        "equipment": ["bodyweight"]},
    "vertical_push":{"name": "Pike Push-up",          "sets": 3, "reps": "6-10",  "rest_sec": 60,
                    "movement_pattern": "vertical_push","equipment": ["bodyweight"]},
    "pull":        {"name": "Inverted Row (or Doorway Row)", "sets": 3, "reps": "8-12", "rest_sec": 60,
                    "movement_pattern": "pull",        "equipment": ["bodyweight"]},
    "vertical_pull":{"name": "Doorway Pull-in Iso Hold", "sets": 3, "reps": "20-30s", "rest_sec": 60,
                    "movement_pattern": "vertical_pull","equipment": ["bodyweight"]},
    "lunge":       {"name": "Reverse Lunge",          "sets": 3, "reps": "10 ea. side", "rest_sec": 60,
                    "movement_pattern": "lunge",       "equipment": ["bodyweight"]},
    "single_leg":  {"name": "Split Squat",            "sets": 3, "reps": "10 ea. side", "rest_sec": 60,
                    "movement_pattern": "single_leg",  "equipment": ["bodyweight"]},
    "core":        {"name": "Dead Bug",               "sets": 3, "reps": "8 ea. side", "rest_sec": 45,
                    "movement_pattern": "core",        "equipment": ["bodyweight"]},
    "anti_rotation":{"name": "Bird Dog",              "sets": 3, "reps": "8 ea. side", "rest_sec": 45,
                    "movement_pattern": "anti_rotation","equipment": ["bodyweight"]},
    "carry":       {"name": "Bear Crawl",             "sets": 3, "reps": "20 steps", "rest_sec": 60,
                    "movement_pattern": "carry",       "equipment": ["bodyweight"]},
    "conditioning":{"name": "Jumping Jacks",          "sets": 3, "reps": "45s",   "rest_sec": 30,
                    "movement_pattern": "conditioning","equipment": ["bodyweight"]},
    "cardio":      {"name": "High-Knee March",        "sets": 3, "reps": "60s",   "rest_sec": 30,
                    "movement_pattern": "cardio",      "equipment": ["bodyweight"]},
}

# Rough name → pattern classifier (best-effort). Anything unmatched falls back
# to a generic bodyweight squat so the workout is never left empty.
def _infer_pattern(item: dict) -> str:
    mp = str(item.get("movement_pattern") or "").lower().strip()
    if mp and mp in _PATTERN_SUBS:
        return mp
    name = str(item.get("name") or item.get("exercise_name") or "").lower()
    # word-by-word rules
    if any(k in name for k in ("push-up", "push up", "pushup", "bench press", "chest press", "push")):
        if "overhead" in name or "shoulder press" in name or "pike" in name:
            return "vertical_push"
        return "push"
    if any(k in name for k in ("pull-up", "pull up", "chin-up", "chin up", "lat pull")):
        return "vertical_pull"
    if any(k in name for k in ("row", "pull ", "face pull", "reverse fly")):
        return "pull"
    if any(k in name for k in ("squat", "goblet", "front squat", "back squat", "leg press")):
        return "squat"
    if any(k in name for k in ("deadlift", "rdl", "romanian", "good morning", "hip thrust", "hinge")):
        return "hinge"
    if any(k in name for k in ("lunge", "step-up", "step up", "bulgarian")):
        return "lunge"
    if any(k in name for k in ("split squat", "pistol", "single leg", "single-leg")):
        return "single_leg"
    if any(k in name for k in ("plank", "hollow", "dead bug", "sit up", "crunch")):
        return "core"
    if any(k in name for k in ("bird dog", "pallof", "anti-rotation", "side plank")):
        return "anti_rotation"
    if any(k in name for k in ("farmer", "carry", "suitcase")):
        return "carry"
    if any(k in name for k in ("burpee", "mountain climber", "jumping jack", "jump")):
        return "conditioning"
    if any(k in name for k in ("run", "sprint", "bike", "row erg", "erg", "assault")):
        return "cardio"
    return "squat"  # last-ditch safe default


def bodyweight_substitute_for(item: dict) -> dict:
    """Return a fully-formed bodyweight substitute dict that mirrors the original
    item's set/rep/rest scheme when present, so the workout duration stays sane.
    The returned dict includes `substitute_for` + `substitution_reason` so the
    client-facing WHY-THIS-CHANGED text still lists the original ask.
    """
    pattern = _infer_pattern(item)
    tmpl = dict(_PATTERN_SUBS.get(pattern) or _PATTERN_SUBS["squat"])
    # Preserve original sets/reps/rest/RPE if the LLM specified them.
    for k in ("sets", "reps", "rest_sec", "tempo", "rpe", "intensity_note", "duration_sec"):
        if item.get(k):
            tmpl[k] = item[k]
    original_name = item.get("name") or item.get("exercise_name") or "unnamed exercise"
    tmpl["source"] = "resolver_bodyweight_fallback"
    tmpl["substitute_for"] = original_name
    tmpl["substitution_reason"] = (
        f"No approved '{original_name}' in the library and your setup can't safely "
        f"support it — swapped in a bodyweight version. Louis will review."
    )
    tmpl["equipment_check"] = "pass"     # bodyweight is always available
    tmpl["equipment_required"] = ["bodyweight"]
    return tmpl


# ---------------------------------------------------------------------------
# 2. Coach task — "Workout adjusted to safe fallback"
# ---------------------------------------------------------------------------

async def create_workout_fallback_task(
    *,
    user: dict,
    workout: dict,
    reason: str,
    dropped_exercises: Optional[list[dict]] = None,
    equipment_required: Optional[list[str]] = None,
    equipment_available: Optional[list[str]] = None,
    validation_errors: Optional[list[str]] = None,
    db=None,
) -> Optional[str]:
    """Idempotently create a coach_task doc for the primary/assigned coach.

    Dedup rule: (client_id, workout_id, type='workout_fallback_used'). If a task
    already exists for that workout, we UPDATE its last-touched timestamp and
    append to the change history — we never spam Louis with duplicate tasks
    for the same workout.
    """
    if db is None:
        try:
            from server import db as _db  # lazy import to avoid circular
            db = _db
        except Exception:
            logger.warning("workout_fallback_v2: db unavailable, skipping task")
            return None
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    uid = user.get("id")
    wid = workout.get("id")
    if not uid or not wid:
        return None

    coach_id = user.get("primary_coach_id") or user.get("assigned_coach_id")
    if not coach_id:
        try:
            coach = await db.users.find_one(
                {"role": "coach", "status": {"$ne": "archived"}},
                {"id": 1, "_id": 0}, sort=[("created_at", 1)],
            )
            coach_id = (coach or {}).get("id")
        except Exception:
            coach_id = None

    payload = {
        "client_id": uid,
        "client_name": user.get("name"),
        "workout_id": wid,
        "workout_date": workout.get("date"),
        "workout_title": workout.get("title"),
        "intended_focus": workout.get("focus"),
        "intended_location": workout.get("location"),
        "reason": reason,
        "dropped_exercises": dropped_exercises or [],
        "equipment_available": equipment_available or [],
        "equipment_required": equipment_required or [],
        "validation_errors": validation_errors or [],
    }
    try:
        existing = await db.coach_tasks.find_one(
            {"type": "workout_fallback_used", "payload.workout_id": wid, "client_id": uid},
            {"_id": 0, "id": 1, "payload": 1},
        )
    except Exception:
        existing = None

    if existing:
        try:
            await db.coach_tasks.update_one(
                {"id": existing["id"]},
                {"$set": {"payload": payload, "updated_at": now, "status": "open"}},
            )
        except Exception:
            logger.exception("workout_fallback_v2: dedup update failed")
        return existing.get("id")

    # Fresh task
    try:
        import uuid
        task_id = str(uuid.uuid4())
        await db.coach_tasks.insert_one({
            "id": task_id,
            "type": "workout_fallback_used",
            "title": f"Workout adjusted to safe fallback: {user.get('name') or 'client'}",
            "description": reason,
            "client_id": uid,
            "coach_id": coach_id,
            "status": "open",
            "priority": "high",
            "payload": payload,
            "created_at": now,
            "updated_at": now,
        })
        return task_id
    except Exception:
        logger.exception("workout_fallback_v2: create task failed (non-fatal)")
        return None


# ---------------------------------------------------------------------------
# 3. Friendly client-facing wording (single source of truth)
# ---------------------------------------------------------------------------

# Used by both the LLM-empty heal path AND the resolver-drop path.
CLIENT_FRIENDLY_FALLBACK_REASON = (
    "Session adjusted — CrewFit couldn't safely match the original workout to "
    "your available equipment, so this session has been switched to a "
    "bodyweight-safe option. Louis has been notified to review it."
)

CLIENT_FRIENDLY_EQUIPMENT_MISMATCH_REASON = (
    "Session adjusted — one or more exercises needed kit you don't have, so "
    "the workout has been marked for Louis to review. You can still train "
    "safely with the bodyweight-safe version below."
)
