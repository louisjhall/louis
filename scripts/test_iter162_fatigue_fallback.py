"""
Iter 162 · Verify the Fatigue-Logic Fallback: when a V2 user asks for a
Reality action on a date that has NO plan_live_v2 placement, the mutation
should NOT return "nothing found" — it should fall through to the legacy
db.workouts mutator.

Read-only against production data (uses uniquely-named test docs it
inserts and deletes). No LLM calls.
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


async def main():
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]

    # Seed a V2-flagged user with an active V2 plan (that has NO placement
    # for date 2027-01-15) AND a legacy db.workouts row for that same date.
    uid = f"TEST-v2-legacy-{uuid.uuid4().hex[:8]}"
    date = "2027-01-15"
    plan_id = f"TEST-plan-{uuid.uuid4().hex[:8]}"
    wid = f"TEST-w-{uuid.uuid4().hex[:8]}"
    try:
        await db.users.insert_one({
            "id": uid, "email": f"{uid}@test.crewfit.io",
            "profile": {"v2_flags": {"v2_default": True}},
        })
        # V2 plan with placements ONLY for a different date.
        await db.plan_live_v2.insert_one({
            "id": plan_id,
            "client_id": uid,
            "active": True,
            "placements": [{"date": "2027-01-14", "kind": "strength",
                            "exposure_id": "T-EX-1", "target_duration_min": 45}],
            "session_specs": {"T-EX-1": {"kind": "strength", "spec_kind": "strength",
                                          "duration_min": 45}},
            "created_at": "2027-01-01T00:00:00Z",
        })
        # Legacy workout for the missing date.
        await db.workouts.insert_one({
            "id": wid,
            "user_id": uid,
            "date": date,
            "title": "Legacy Long Run",
            "focus": "endurance",
            "workout_type": "cardio",
            "duration_min": 60,
            "exercises": [{"name": "Zone 2 run", "duration_sec": 60 * 60}],
            "source": "coach_manual",
        })

        # Import handler AFTER seeding — it caches the DB reference.
        from server import _apply_reality_action

        print("\n[1] V2 user with plan_live_v2 → date has NO placement → legacy fallback")
        result = await _apply_reality_action(uid, {
            "kind": "reduce", "date": date, "target_min": 30,
        })
        if not result.get("changed"):
            _fail(f"Expected 'changed: True', got: {result}")
        _ok(f"changed=True, before={result.get('before')}, after={result.get('after')}")

        # Verify the DB.workouts row was actually mutated.
        row = await db.workouts.find_one({"id": wid})
        if row.get("duration_min") != 30:
            _fail(f"Expected duration_min=30 on legacy row, got: {row.get('duration_min')}")
        _ok(f"Legacy db.workouts row mutated: duration_min = {row.get('duration_min')}")

        print("\n[2] V2 user with placement present → still uses V2 path (no legacy touch)")
        # Reset the legacy row to prove V2 wins for its own date.
        await db.workouts.update_one({"id": wid}, {"$set": {"duration_min": 60}})
        # Insert a legacy row for the V2-owned date so we can prove V2 didn't
        # accidentally mutate it.
        wid2 = f"TEST-w-guard-{uuid.uuid4().hex[:8]}"
        await db.workouts.insert_one({
            "id": wid2, "user_id": uid, "date": "2027-01-14",
            "title": "Should not be touched", "duration_min": 45,
            "exercises": [],
        })
        result2 = await _apply_reality_action(uid, {
            "kind": "reduce", "date": "2027-01-14", "target_min": 20,
        })
        if not result2.get("changed"):
            _fail(f"V2 path should have mutated placement, got: {result2}")
        _ok(f"V2 path applied: changed={result2['changed']}, after={result2['after']}")

        # Legacy row for that date must stay untouched.
        guard = await db.workouts.find_one({"id": wid2})
        if guard.get("duration_min") != 45:
            _fail(f"Legacy row wrongly touched on V2 date: {guard.get('duration_min')}")
        _ok("Legacy row untouched on V2-owned date")

        await db.workouts.delete_one({"id": wid2})

        print("\n✅  Iter 162 Fatigue-Legacy-Fallback tests passed.")

    finally:
        await db.users.delete_one({"id": uid})
        await db.plan_live_v2.delete_one({"id": plan_id})
        await db.workouts.delete_one({"id": wid})
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
