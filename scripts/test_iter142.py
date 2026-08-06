#!/usr/bin/env python3
"""
Iter 142 test — Coach preset swap & Hotel rescue fallback route through the
unified Exercise Library.

No real LLM/image calls. Uses spies on auto_enqueue and asserts every
exercise in the resulting workout has an `exercise_id` field pointing at a
real exercises_v2 row (approved or draft), and that Phase B dedup applies.
"""
from __future__ import annotations
import asyncio, os, sys, json
from unittest.mock import patch, AsyncMock

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
os.environ["EXERCISE_BACKFILL_DISABLED"] = "false"

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

import feature_v2_resolver as R                        # noqa: E402
import feature_auto_media_gen as A                     # noqa: E402
import feature_media_queue as M                        # noqa: E402
import feature_coach_workout_swap as CS                # noqa: E402
import feature_v2_plan_live_adapt as LA                # noqa: E402
import server as S                                     # noqa: E402


enq_calls: list[dict] = []
async def spy_enqueue(ex_id, *, triggered_by=None, suppress_kinds=()):
    enq_calls.append({"ex_id": ex_id, "suppress_kinds": tuple(suppress_kinds)})
    return {"skipped": False}


async def main():
    local_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for mod in (R, A, M, CS, LA, S):
        try: mod.db = local_db
        except Exception: pass

    # cleanup
    await local_db.workouts.delete_many({"id": {"$regex": "^__it142__"}})
    await local_db.exercises_v2.delete_many({"reason_needed": {"$regex": "^coach_preset_swap|^hotel_adapt_rescue"}})

    coach = await local_db.users.find_one({"role": "coach"}, {"_id": 0})
    active_client = await local_db.users.find_one(
        {"id": "7a708652-5635-4c3a-a8cc-033220f1f03d"}, {"_id": 0}
    )
    assert coach and active_client

    # Seed a workout to swap
    test_wid = "__it142__ws1"
    await local_db.workouts.insert_one({
        "id": test_wid, "user_id": active_client["id"], "date": "2026-08-20",
        "source": "coach_manual",
        "title": "Original", "focus": "strength", "duration_min": 45,
        "exercises": [{"name": "Original Ex", "sets": 3, "reps": "10"}],
        "warmup": [], "cooldown": [],
    })

    print("─── TEST 1 · Coach preset swap resolves every preset exercise ───")
    enq_calls.clear()
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        # invoke handler directly
        from feature_coach_workout_swap import coach_workout_apply_swap, ApplySwapBody
        result = await coach_workout_apply_swap(
            test_wid, ApplySwapBody(preset_id="bodyweight_full_35", reason="test"),
            coach=coach,
        )

    fresh = result["workout"]
    exs = fresh["exercises"]
    print(f"  Preset applied: {len(exs)} exercises")
    for e in exs:
        assert "exercise_id" in e, f"MISSING exercise_id in {e}"
        assert e.get("library_source") in ("approved_match", "draft"), \
            f"bad library_source: {e}"
        row = await local_db.exercises_v2.find_one({"id": e["exercise_id"]}, {"_id":0, "exercise_name":1, "status":1})
        assert row, f"exercise_id points to nothing: {e['exercise_id']}"
        print(f"    · {e.get('exercise_name'):30s} → id={e['exercise_id'][:8]}… "
              f"src={e['library_source']:15s} row='{row.get('exercise_name')}'")
    summary = fresh["coach_swap_library_summary"]
    print(f"  Summary: {summary}")
    assert summary["unresolved"] == 0, "unresolved items present"
    print("  ✓ every preset exercise has valid exercise_id + library_source")
    print("  ✓ zero unresolved names")

    print("\n─── TEST 2 · Second apply → Phase B reuses (no duplicate drafts) ───")
    # Reset workout state
    await local_db.workouts.update_one({"id": test_wid}, {"$set": {
        "exercises": [{"name": "Reset Ex", "sets": 3, "reps": "10"}],
    }})
    prev_ids = {e["exercise_id"] for e in exs}
    enq_calls.clear()
    before_count = await local_db.exercises_v2.count_documents({
        "reason_needed": "coach_preset_swap:bodyweight_full_35"
    })
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        result2 = await coach_workout_apply_swap(
            test_wid, ApplySwapBody(preset_id="bodyweight_full_35", reason="test2"),
            coach=coach,
        )
    new_ids = {e["exercise_id"] for e in result2["workout"]["exercises"]}
    after_count = await local_db.exercises_v2.count_documents({
        "reason_needed": "coach_preset_swap:bodyweight_full_35"
    })
    assert new_ids == prev_ids, f"Phase B failed — ids diverged: {new_ids ^ prev_ids}"
    assert after_count == before_count, (
        f"duplicate drafts created — before={before_count} after={after_count}"
    )
    assert len(enq_calls) == 0, f"auto-enqueue fired on dedup path ({len(enq_calls)} calls)"
    print(f"  ✓ Second apply reused all {len(new_ids)} ids (Phase B works)")
    print(f"  ✓ 0 new drafts, 0 enqueues")

    print("\n─── TEST 3 · Hotel rescue fallback → 3 items, all with exercise_id ───")
    # Simulate the rescue path directly (mirror _apply_change_setup_manual's
    # rescue block: kept_main is empty → 3 rescue names get resolved).
    rescue_specs = [
        {"name": "Bodyweight Squat", "sets": 3, "reps": "15",
         "rest_sec": 45, "hotel_adapted_fallback": True},
        {"name": "Push-Up (or incline)", "sets": 3, "reps": "10-15",
         "rest_sec": 45, "hotel_adapted_fallback": True},
        {"name": "Plank", "sets": 3, "reps": "30s",
         "rest_sec": 30, "hotel_adapted_fallback": True},
    ]
    enq_calls.clear()
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        from feature_media_queue import resolve_or_draft_exercise
        rescued = []
        for spec in rescue_specs:
            ex_id = await resolve_or_draft_exercise(
                spec["name"], user=active_client,
                reason="hotel_adapt_rescue_fallback",
                workout_id=test_wid,
            )
            item = dict(spec)
            item["exercise_name"] = spec["name"]
            if ex_id:
                item["exercise_id"] = ex_id
                row = await local_db.exercises_v2.find_one({"id": ex_id}, {"_id":0,"status":1,"approval_status":1,"exercise_name":1}) or {}
                item["library_source"] = "approved_match" if str(row.get("status")) in ("Approved","Live") or str(row.get("approval_status")).lower()=="approved" else "draft"
            rescued.append(item)

    for r in rescued:
        assert r.get("exercise_id"), f"MISSING id on rescue item: {r}"
        row = await local_db.exercises_v2.find_one({"id": r["exercise_id"]}, {"_id":0,"exercise_name":1,"status":1})
        assert row
        print(f"    · {r['exercise_name']:30s} → id={r['exercise_id'][:8]}… "
              f"src={r['library_source']:15s} row='{row.get('exercise_name')}'")
    print("  ✓ all 3 rescue items carry exercise_id + library_source")

    print("\n─── TEST 4 · Rescue re-run → Phase B reuses (no dupes) ───")
    prev_rescue_ids = {r["exercise_id"] for r in rescued}
    enq_calls.clear()
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        from feature_media_queue import resolve_or_draft_exercise
        rerun_ids = []
        for spec in rescue_specs:
            ex_id = await resolve_or_draft_exercise(
                spec["name"], user=active_client,
                reason="hotel_adapt_rescue_fallback",
                workout_id=test_wid,
            )
            rerun_ids.append(ex_id)
    assert set(rerun_ids) == prev_rescue_ids, (
        f"rescue re-run created new drafts! prev={prev_rescue_ids} new={set(rerun_ids)}"
    )
    assert len(enq_calls) == 0
    print(f"  ✓ rescue re-run reused all 3 ids (Phase B), 0 new drafts")

    print("\n─── CLEANUP ───")
    await local_db.workouts.delete_many({"id": {"$regex": "^__it142__"}})
    await local_db.exercises_v2.delete_many({"reason_needed": {"$regex": "^coach_preset_swap|^hotel_adapt_rescue"}})
    print("  ✓ test rows removed")

    print("\n" + "="*68)
    print("ITER 142 — ALL TESTS PASSED (no real API calls)")
    print("="*68)


if __name__ == "__main__":
    asyncio.run(main())
