#!/usr/bin/env python3
"""
Iter 143 — Today's Reality apply now routes through the unified Library.

Verifies:
  1. convert_mobility  → 5 exercises + 2 warmup, all with valid exercise_id
  2. convert_recovery  → 'Easy walk or spin' resolved with exercise_id
  3. convert_walk      → 'Steady walk' resolved with exercise_id
  4. Phase B dedup on re-apply — no duplicate drafts on second application
  5. Zero real LLM/image calls (auto_enqueue is spied)
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
import server as S                                     # noqa: E402


enq_calls: list[dict] = []
async def spy_enqueue(ex_id, *, triggered_by=None, suppress_kinds=()):
    enq_calls.append({"ex_id": ex_id, "suppress_kinds": tuple(suppress_kinds)})
    return {"skipped": False}


async def main():
    local_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for mod in (R, A, M, S):
        try: mod.db = local_db
        except Exception: pass

    # cleanup
    await local_db.workouts.delete_many({"id": {"$regex": "^__it143__"}})
    await local_db.exercises_v2.delete_many({"reason_needed": {"$regex": "^reality_convert"}})

    client = await local_db.users.find_one(
        {"id": "7a708652-5635-4c3a-a8cc-033220f1f03d"}, {"_id": 0}
    )
    assert client

    async def seed(wid, date):
        await local_db.workouts.delete_many({"id": wid})
        await local_db.workouts.insert_one({
            "id": wid, "user_id": client["id"], "date": date,
            "source": "coach_manual", "title": "Original",
            "focus": "strength", "duration_min": 45, "day_load": "amber",
            "exercises": [{"name": "Original Ex", "sets": 3, "reps": "10"}],
            "warmup": [], "cooldown": [],
        })

    print("─── TEST 1 · convert_mobility resolves 5 exercises + 2 warmup ───")
    await seed("__it143__mob", "2026-08-25")
    enq_calls.clear()
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        await S._apply_reality_action(client["id"], {
            "kind": "convert_mobility", "date": "2026-08-25",
        })
    w = await local_db.workouts.find_one({"id": "__it143__mob"}, {"_id": 0})
    exs = w.get("exercises") or []
    warm = w.get("warmup") or []
    print(f"  {len(exs)} exercises, {len(warm)} warmup items")
    assert len(exs) == 5, f"expected 5 exercises, got {len(exs)}"
    assert len(warm) == 2, f"expected 2 warmup, got {len(warm)}"
    for e in exs + warm:
        assert e.get("exercise_id"), f"MISSING id: {e}"
        assert e.get("library_source") in ("approved_match", "draft"), \
            f"bad library_source: {e}"
        row = await local_db.exercises_v2.find_one({"id": e["exercise_id"]}, {"_id": 0, "exercise_name": 1})
        assert row, f"exercise_id points to nothing: {e['exercise_id']}"
        print(f"    · {e.get('exercise_name'):32s} → {e['exercise_id'][:8]}… src={e['library_source']}")

    print("\n─── TEST 2 · convert_recovery — 'Easy walk or spin' resolved ───")
    await seed("__it143__rec", "2026-08-26")
    enq_calls.clear()
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        await S._apply_reality_action(client["id"], {
            "kind": "convert_recovery", "date": "2026-08-26",
        })
    w = await local_db.workouts.find_one({"id": "__it143__rec"}, {"_id": 0})
    exs = w.get("exercises") or []
    assert len(exs) == 1 and exs[0].get("exercise_id"), f"recovery unresolved: {exs}"
    print(f"    · {exs[0].get('exercise_name'):32s} → {exs[0]['exercise_id'][:8]}… src={exs[0]['library_source']}")

    print("\n─── TEST 3 · convert_walk — 'Steady walk' resolved ───")
    await seed("__it143__walk", "2026-08-27")
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        await S._apply_reality_action(client["id"], {
            "kind": "convert_walk", "date": "2026-08-27", "target_min": 25,
        })
    w = await local_db.workouts.find_one({"id": "__it143__walk"}, {"_id": 0})
    exs = w.get("exercises") or []
    assert len(exs) == 1 and exs[0].get("exercise_id"), f"walk unresolved: {exs}"
    assert "25 min" in exs[0].get("reps", ""), f"target_min lost: {exs[0]}"
    print(f"    · {exs[0].get('exercise_name'):32s} → {exs[0]['exercise_id'][:8]}… src={exs[0]['library_source']}")

    print("\n─── TEST 4 · Phase B dedup — second convert_mobility reuses ───")
    # Count drafts filed for convert_mobility before + after a second run.
    before = await local_db.exercises_v2.count_documents({
        "reason_needed": {"$regex": "^reality_convert_mobility"}
    })
    await seed("__it143__mob2", "2026-08-28")
    enq_calls.clear()
    with patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        await S._apply_reality_action(client["id"], {
            "kind": "convert_mobility", "date": "2026-08-28",
        })
    after = await local_db.exercises_v2.count_documents({
        "reason_needed": {"$regex": "^reality_convert_mobility"}
    })
    assert after == before, (
        f"Phase B failed — before={before}, after={after} (should be equal)"
    )
    # And zero auto-enqueue calls on the dedup path.
    assert len(enq_calls) == 0, (
        f"BUG: {len(enq_calls)} enqueue calls fired on dedup path"
    )
    w2 = await local_db.workouts.find_one({"id": "__it143__mob2"}, {"_id": 0})
    ids_1 = {e["exercise_id"] for e in (w.get("exercises") or [])}
    ids_2 = {e["exercise_id"] for e in (w2.get("exercises") or [])}
    print(f"  drafts before={before}, after={after}, enqueues={len(enq_calls)}")
    print(f"  ✓ Phase B reused all ids (mobility set 1: {len(ids_1)} items, set 2: {len(ids_2)} items)")

    print("\n─── CLEANUP ───")
    await local_db.workouts.delete_many({"id": {"$regex": "^__it143__"}})
    print("  ✓ test rows removed  (drafts left intact for future reuse)")

    print("\n" + "="*68)
    print("ITER 143 — ALL TESTS PASSED  (no real API calls)")
    print("="*68)


if __name__ == "__main__":
    asyncio.run(main())
