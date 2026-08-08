"""
Iter 161 · Dashboard Polish verification — 2 targeted checks.

  1. Rest day revert clears variants.{green,amber,red} exercises/warmup/
     cooldown/duration_min (not just top-level).
  2. feature_calendar_recovery._is_off_workout returns True for
     focus=recovery, workout_type=recovery, duration_min=0.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "crewfit_v1"


def _ok(m): print(f"  ✅  {m}")
def _fail(m): print(f"  ❌  {m}"); raise AssertionError(m)


async def test_variant_clearing(db):
    print("\n[A] Rest-day revert clears variants.green/amber/red")
    from server import _heal_workouts_batch

    tid = f"TEST-rev-variants-{uuid.uuid4().hex[:6]}"
    await db.workouts.insert_one({
        "id": tid, "user_id": "utest", "date": "2026-09-15",
        "title": "Full Rest", "workout_type": "recovery",
        "source": "coach_manual", "duration_min": 40,
        "exercises": [{"name": "Junk"}],
        "fallback_used": True, "validation_status": "adjusted_fallback",
        "variants": {
            "green": {"exercises": [{"name": "GreenEx"}], "duration_min": 40,
                      "warmup": [{"name": "GreenWU"}], "cooldown": []},
            "amber": {"exercises": [{"name": "AmberEx1"}, {"name": "AmberEx2"}],
                      "duration_min": 25, "warmup": [], "cooldown": []},
            "red":   {"exercises": [{"name": "RedEx"}], "duration_min": 15,
                      "warmup": [], "cooldown": [{"name": "RedCD"}]},
        },
    })
    rows = await db.workouts.find({"id": tid}).to_list(1)
    await _heal_workouts_batch(rows, {"id": "utest"})
    persisted = await db.workouts.find_one({"id": tid})
    v = persisted.get("variants") or {}
    for k in ("green", "amber", "red"):
        vv = v.get(k) or {}
        if vv.get("exercises"):
            _fail(f"variant.{k}.exercises not cleared: {vv.get('exercises')}")
        if vv.get("warmup"):
            _fail(f"variant.{k}.warmup not cleared: {vv.get('warmup')}")
        if vv.get("cooldown"):
            _fail(f"variant.{k}.cooldown not cleared: {vv.get('cooldown')}")
        if vv.get("duration_min") not in (0, None):
            _fail(f"variant.{k}.duration_min not cleared: {vv.get('duration_min')}")
    _ok("variants.{green,amber,red} exercises/warmup/cooldown/duration all cleared and persisted")
    if persisted.get("exercises"):
        _fail("top-level exercises still populated after revert")
    _ok("top-level exercises still empty")
    await db.workouts.delete_one({"id": tid})


async def test_is_off_workout():
    print("\n[B] _is_off_workout treats focus=recovery / workout_type=recovery / duration_min=0 as off")
    from feature_calendar_recovery import _is_off_workout

    cases = [
        ({"focus": "recovery"}, True, "focus=recovery"),
        ({"workout_type": "recovery"}, True, "workout_type=recovery"),
        ({"workout_type": "rest"}, True, "workout_type=rest"),
        ({"duration_min": 0}, True, "duration_min=0"),
        ({"title": "Full Rest"}, True, "title contains 'Full Rest'"),
        ({"title": "Rest Day"}, True, "title starts with 'Rest'"),
        ({"focus": "push", "workout_type": "strength", "duration_min": 45}, False, "regular strength"),
        ({"focus": "long_run", "duration_min": 60}, False, "long run"),
        ({"focus": "intervals"}, False, "intervals stay training"),
    ]
    for w, expected, label in cases:
        got = _is_off_workout(w)
        if got != expected:
            _fail(f"{label}: expected {expected}, got {got}")
        _ok(f"{label} → {got}")


async def main():
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    await test_variant_clearing(db)
    await test_is_off_workout()
    print("\n✅  Iter 161 Dashboard Polish tests passed.")
    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
