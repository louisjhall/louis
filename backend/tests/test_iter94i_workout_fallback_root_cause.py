"""
Iter 94i — Root-cause fixes for the "Equipment didn't match / Content was
missing / safe bodyweight" fallback.

Covers:

* `bodyweight_substitute_for(item)` produces a valid bodyweight exercise for
  every movement pattern.
* V2 resolver NEVER silently drops an exercise — unresolved items are
  swapped in-place with a bodyweight sub AND a draft exercise-request task.
* `_ensure_workout_content` uses the friendly client message
  (no "content was missing" scare copy).
* `enforce_equipment_gate` uses the friendly client message and stashes the
  technical detail on `change_reason_technical`.
* A `coach_task` is written when a workout gets healed, dedup'd per workout_id.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

import pytest
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")


# ---------------------------------------------------------------------------
# Unit — bodyweight_substitute_for
# ---------------------------------------------------------------------------

def test_bodyweight_substitute_covers_every_common_pattern():
    from feature_workout_fallback_v2 import bodyweight_substitute_for
    cases = [
        ({"name": "Barbell Back Squat"},               "squat"),
        ({"name": "Conventional Deadlift"},            "hinge"),
        ({"name": "Barbell Bench Press"},              "push"),
        ({"name": "Overhead Press"},                   "vertical_push"),
        ({"name": "Cable Row"},                        "pull"),
        ({"name": "Pull-Up"},                          "vertical_pull"),
        ({"name": "Walking Lunge"},                    "lunge"),
        ({"name": "Bulgarian Split Squat"},            "lunge"),  # matched by "lunge" or "split"
        ({"name": "Farmer's Carry"},                   "carry"),
        ({"name": "Burpees"},                          "conditioning"),
        ({"name": "Sprint intervals"},                 "cardio"),
        ({"name": "Plank"},                            "core"),
        ({"name": "Bird Dog"},                         "anti_rotation"),
        # Also honours explicit movement_pattern field
        ({"movement_pattern": "squat"},                "squat"),
    ]
    for item, _expected in cases:
        sub = bodyweight_substitute_for(item)
        assert sub.get("name"), f"No sub name for {item}"
        assert sub.get("equipment") == ["bodyweight"], f"Not bodyweight: {sub}"
        assert sub["substitute_for"] == (item.get("name") or item.get("exercise_name") or "unnamed exercise")
        assert "substitution_reason" in sub
        assert sub["source"] == "resolver_bodyweight_fallback"


def test_bodyweight_substitute_preserves_sets_reps_rpe():
    from feature_workout_fallback_v2 import bodyweight_substitute_for
    item = {"name": "Cable Lat Pulldown", "sets": 4, "reps": "8", "rest_sec": 90, "rpe": 8}
    sub = bodyweight_substitute_for(item)
    assert sub["sets"] == 4
    assert sub["reps"] == "8"
    assert sub["rest_sec"] == 90
    assert sub["rpe"] == 8


# ---------------------------------------------------------------------------
# Unit — friendly wording constants
# ---------------------------------------------------------------------------

def test_friendly_wording_has_no_scare_copy():
    from feature_workout_fallback_v2 import (
        CLIENT_FRIENDLY_FALLBACK_REASON,
        CLIENT_FRIENDLY_EQUIPMENT_MISMATCH_REASON,
    )
    for msg in (CLIENT_FRIENDLY_FALLBACK_REASON, CLIENT_FRIENDLY_EQUIPMENT_MISMATCH_REASON):
        lower = msg.lower()
        for banned in ("content was missing", "broken", "error", "failed", "ai "):
            assert banned not in lower, f"Banned phrase {banned!r} in: {msg}"
        assert "session adjusted" in lower
        assert "louis" in lower
        assert "safe" in lower


def test_friendly_wording_never_mentions_ai():
    """Explicit product directive — never say 'AI' to clients."""
    from feature_workout_fallback_v2 import (
        CLIENT_FRIENDLY_FALLBACK_REASON,
        CLIENT_FRIENDLY_EQUIPMENT_MISMATCH_REASON,
    )
    for msg in (CLIENT_FRIENDLY_FALLBACK_REASON, CLIENT_FRIENDLY_EQUIPMENT_MISMATCH_REASON):
        assert " ai " not in f" {msg.lower()} "
        assert " AI " not in f" {msg} "


# ---------------------------------------------------------------------------
# Unit — _ensure_workout_content uses the new friendly wording
# ---------------------------------------------------------------------------

def test_ensure_workout_content_uses_friendly_message():
    """Empty workouts get healed with the safe bodyweight stub. The
    client-facing change_reason must be the friendly "Session adjusted" copy —
    NOT the old "content was missing" scare copy."""
    from server import _ensure_workout_content
    doc = {
        "id": "w1", "date": "2026-08-01",
        "exercises": [], "warmup": [], "cooldown": [],
        "duration_min": 45, "focus": "strength_support",
    }
    user = {"id": "u1", "profile": {"equipment": ["bodyweight_only"]}}
    healed = _ensure_workout_content(doc, user)
    assert healed["needs_coach_review"] is True
    assert healed["validation_status"] == "adjusted_fallback"
    assert healed["fallback_used"] is True
    assert healed["fallback_type"] == "safe_bodyweight_stub"
    assert "session adjusted" in (healed.get("change_reason") or "").lower()
    # ---- Zero scare copy in the client-visible message
    scare = healed["change_reason"].lower()
    assert "content was missing" not in scare
    assert "broken" not in scare
    # ---- Technical detail preserved for the coach task
    assert healed["insufficient_content_reason"] == "llm_returned_empty_exercises"


# ---------------------------------------------------------------------------
# Unit — equipment gate friendly wording
# ---------------------------------------------------------------------------

def test_equipment_gate_uses_friendly_wording():
    from feature_equipment_matcher import enforce_equipment_gate
    workout = {"id": "w2", "date": "2026-08-02", "exercises": [
        {"name": "Barbell Bench Press"},
        {"name": "Push-up"},
    ]}
    # Client only has bodyweight — barbell bench press must fail.
    result = enforce_equipment_gate(workout, available={"bodyweight"})
    assert result["fails"] == 1
    assert workout["needs_coach_review"] is True
    assert workout["validation_status"] == "adjusted_fallback"
    assert "session adjusted" in workout["change_reason"].lower()
    assert workout["change_reason_technical"], "Technical detail missing"
    # Push-up should have passed
    assert workout["exercises"][1]["equipment_check"] == "pass"
    assert workout["exercises"][0]["equipment_check"] == "fail"


# ---------------------------------------------------------------------------
# Integration — V2 resolver never silently drops
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_ex", [
    {"name": "Zercher Snatch Grip Cable Deadlift", "movement_pattern": "hinge"},
    {"name": "Some Made-Up Weighted Movement",     "movement_pattern": "push"},
])
def test_v2_resolver_never_silently_drops(bad_ex):
    """Unresolvable items must be swapped with a bodyweight sub, not vanish."""
    from feature_v2_resolver import apply_resolver_to_workouts

    # Fake user with bodyweight-only setup
    user = {"id": "test_uid", "profile": {"equipment": ["bodyweight_only"]}, "name": "Test"}
    workout = {"id": "w3", "date": "2026-08-03", "exercises": [
        {"name": "Push-up"},    # will match / substitute
        bad_ex,                 # will NOT match — must swap to bodyweight
    ]}

    async def _run():
        # Force an empty pool so nothing matches — every exercise hits
        # the "unresolved" path.
        import feature_v2_resolver as mod
        orig_get_pool = mod.get_approved_pool
        mod.get_approved_pool = lambda: _empty_pool()  # noqa: E731
        try:
            return await apply_resolver_to_workouts([workout], user=user)
        finally:
            mod.get_approved_pool = orig_get_pool

    async def _empty_pool():
        return []

    stats = asyncio.get_event_loop().run_until_complete(_run())

    # BEFORE the fix: exs_out would be empty (both dropped).
    # AFTER the fix: both are bodyweight subs.
    exs = workout["exercises"]
    assert len(exs) == 2, f"Silent drop happened. Only got {[e.get('name') for e in exs]}"
    for e in exs:
        assert e.get("equipment") == ["bodyweight"], f"Non-bodyweight sub: {e}"
        assert e.get("source") == "resolver_bodyweight_fallback"
        assert e.get("substitute_for"), "Missing substitute_for provenance"
    assert workout.get("needs_coach_review") is True


# ---------------------------------------------------------------------------
# Integration — coach_task creation
# ---------------------------------------------------------------------------

def test_create_workout_fallback_task_is_idempotent():
    """Two heals of the same workout_id must NOT create two tasks."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from feature_workout_fallback_v2 import create_workout_fallback_task

    async def _run():
        c = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = c[os.environ["DB_NAME"]]
        wid = f"testwo_{int(time.time()*1000)}"
        uid = f"testuid_{int(time.time()*1000)}"
        user = {"id": uid, "name": "Test User"}
        workout = {"id": wid, "date": "2026-08-04",
                   "title": "Session A", "focus": "strength_support"}
        try:
            r1 = await create_workout_fallback_task(
                user=user, workout=workout,
                reason="llm empty", validation_errors=["empty_exercises_after_generation"], db=db,
            )
            r2 = await create_workout_fallback_task(
                user=user, workout=workout,
                reason="llm empty (retry)", db=db,
            )
            assert r1 == r2, f"Second call created a NEW task ({r1} vs {r2}) — not idempotent"
            n = await db.coach_tasks.count_documents({"payload.workout_id": wid})
            assert n == 1, f"Expected 1 task for workout, found {n}"
        finally:
            await db.coach_tasks.delete_many({"payload.workout_id": wid})

    asyncio.get_event_loop().run_until_complete(_run())
