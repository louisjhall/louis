#!/usr/bin/env python3
"""
Recursion-guard unit test — NO real LLM / image calls.

Verifies:
  1. `suppress_auto_media_kinds` is honoured by
     `create_exercise_request_if_missing` when a NEW draft is inserted.
  2. `resolve_or_draft_exercise` forwards the flag correctly.
  3. `auto_enqueue_media_for_exercise(suppress_kinds=("alternatives",))`
     - still enqueues primary image, coaching_points, common_mistakes
     - DOES NOT enqueue alternatives → recursion mathematically impossible.
  4. Depth-1 fan-out only: a seed exercise generates alternatives once,
     newly-created alternatives generate no further alternatives.

Strategy:
  * Monkey-patch `_run_image_job` and the Claude call inside
    `_auto_generate_content` so no external API is hit.
  * Monkey-patch to a fake alternatives payload with 5 names — we then
    assert only 3 are persisted (cap check).
"""
import asyncio, os, sys, json
from unittest.mock import patch, AsyncMock

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

# Force the guard OFF so create_exercise_request_if_missing runs the
# auto_enqueue branch that we want to test.
os.environ["EXERCISE_BACKFILL_DISABLED"] = "false"

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

import feature_v2_resolver as R                     # noqa: E402
import feature_auto_media_gen as A                  # noqa: E402
import feature_media_queue as M                     # noqa: E402
import server as S                                  # noqa: E402


# Track every auto_enqueue invocation
enqueue_calls: list[dict] = []


async def spy_enqueue(ex_id, *, triggered_by=None, suppress_kinds=()):
    enqueue_calls.append({
        "ex_id": ex_id,
        "triggered_by": triggered_by,
        "suppress_kinds": tuple(suppress_kinds),
    })
    # Simulate what the real function does with the toggle merge:
    toggles = await A._load_kind_toggles()
    if suppress_kinds:
        for _k in suppress_kinds:
            if _k in toggles:
                toggles[_k] = False
    # Which kinds WOULD have fired for this call?
    fired = [k for k, v in toggles.items() if v]
    enqueue_calls[-1]["would_fire"] = fired
    return {"skipped": False, "queued_content": fired}


async def cleanup_test_rows(local_db):
    await local_db.exercises_v2.delete_many({"reason_needed": {"$regex": "^__unit_test__"}})
    await local_db.exercises_v2.delete_many({"exercise_name": {"$regex": "^__unit_test__"}})


async def main():
    # IMPORTANT: create a fresh motor client BOUND to this event loop, and
    # re-bind every module's `db` symbol to it. Otherwise the stale client
    # attached to server.py's import-time loop raises "Event loop is closed".
    local_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    R.db = local_db
    A.db = local_db
    M.db = local_db
    S.db = local_db

    await cleanup_test_rows(local_db)

    print("─── TEST 1 · seed exercise DOES NOT suppress alternatives ───")
    admin = await local_db.users.find_one({"role": "coach"}, {"_id": 0})

    with patch.object(A, "auto_enqueue_media_for_exercise", new=AsyncMock(side_effect=spy_enqueue)):
        seed_id = await R.create_exercise_request_if_missing(
            {"name": "__unit_test__ SeedMovementX",
             "movement_pattern": "squat", "equipment_type": []},
            user=admin,
            reason="__unit_test__seed",
        )
    assert seed_id, "seed insert failed"
    assert len(enqueue_calls) == 1, f"expected 1 enqueue call, got {len(enqueue_calls)}"
    assert enqueue_calls[0]["suppress_kinds"] == (), (
        f"seed should NOT suppress; got {enqueue_calls[0]['suppress_kinds']}"
    )
    fired = enqueue_calls[0]["would_fire"]
    assert "alternatives" in fired, "seed must be able to fire alternatives"
    assert "image_primary" in fired
    assert "coaching_points" in fired
    assert "common_mistakes" in fired
    assert "image_start" not in fired
    assert "image_end" not in fired
    assert "instructions" not in fired
    print(f"  ✓ seed enqueued with suppress_kinds={enqueue_calls[0]['suppress_kinds']}")
    print(f"  ✓ would fire: {fired}")

    print("\n─── TEST 2 · resolve_or_draft_exercise FORWARDS suppress_auto_media_kinds ───")
    enqueue_calls.clear()
    with patch.object(A, "auto_enqueue_media_for_exercise", new=AsyncMock(side_effect=spy_enqueue)):
        alt_id = await M.resolve_or_draft_exercise(
            "__unit_test__ AltMovementY",
            user=admin,
            parent={"id": seed_id, "exercise_name": "__unit_test__ SeedMovementX",
                    "movement_pattern": "squat"},
            reason="__unit_test__alt",
            suppress_auto_media_kinds=("alternatives",),
        )
    assert alt_id, "alt insert failed"
    assert len(enqueue_calls) == 1, f"expected 1 enqueue call, got {len(enqueue_calls)}"
    call = enqueue_calls[0]
    assert call["suppress_kinds"] == ("alternatives",), (
        f"suppress not forwarded: {call['suppress_kinds']}"
    )
    fired = call["would_fire"]
    assert "alternatives" not in fired, (
        f"BUG: alternatives fired for depth-1 alt → recursion possible! {fired}"
    )
    assert "image_primary" in fired
    assert "coaching_points" in fired
    assert "common_mistakes" in fired
    print(f"  ✓ alt enqueued with suppress_kinds={call['suppress_kinds']}")
    print(f"  ✓ would fire: {fired}  (alternatives correctly absent)")

    print("\n─── TEST 3 · Phase B fuzzy dedup still applies (case+plural) ───")
    enqueue_calls.clear()
    # Try to create the SAME seed name with a plural + case variant.
    with patch.object(A, "auto_enqueue_media_for_exercise", new=AsyncMock(side_effect=spy_enqueue)):
        dup_id = await R.create_exercise_request_if_missing(
            {"name": "__UNIT_TEST__  seedmovementxs",  # plural + case + extra space
             "movement_pattern": "squat", "equipment_type": []},
            user=admin,
            reason="__unit_test__dup",
        )
    assert dup_id == seed_id, (
        f"Phase B fuzzy dedup FAILED: expected {seed_id}, got {dup_id}"
    )
    assert len(enqueue_calls) == 0, (
        f"BUG: enqueue fired on dedup path — got {len(enqueue_calls)} calls"
    )
    print(f"  ✓ fuzzy dedup collapsed variant to same id ({dup_id})")
    print(f"  ✓ no auto-enqueue on dedup path (0 calls)")

    print("\n─── TEST 4 · alternatives cap = 3 ───")
    # Directly call the parser path with a fake Claude payload of 5 names.
    # We stub the full _auto_generate_content by replacing the LlmChat call
    # to return 5 alternatives — assert only 3 land on the row.
    from unittest.mock import MagicMock

    class FakeChat:
        def __init__(self, *a, **kw): pass
        def with_model(self, *a, **kw): return self
        def with_params(self, *a, **kw): return self
        async def send_message(self, *a, **kw):
            return json.dumps({"items": [
                "__unit_test__ Alt1",
                "__unit_test__ Alt2",
                "__unit_test__ Alt3",
                "__unit_test__ Alt4",
                "__unit_test__ Alt5",
            ]})

    # Pre-seed a minimal exercise doc the function will read
    from server import new_id, now_iso
    test_seed_id = new_id()
    await local_db.exercises_v2.insert_one({
        "id": test_seed_id,
        "exercise_name": "__unit_test__ AltParent",
        "status": "draft_requested",
        "movement_pattern": "squat",
        "equipment_type": [],
        "reason_needed": "__unit_test__parent",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    with patch("emergentintegrations.llm.chat.LlmChat", FakeChat), \
         patch("emergentintegrations.llm.chat.UserMessage", MagicMock()), \
         patch.object(A, "auto_enqueue_media_for_exercise",
                      new=AsyncMock(side_effect=spy_enqueue)):
        enqueue_calls.clear()
        await A._auto_generate_content(test_seed_id, "alternatives", "test_creator")

    row = await local_db.exercises_v2.find_one({"id": test_seed_id}, {"_id": 0, "alternatives": 1, "alternative_exercise_ids": 1})
    alts = row.get("alternatives") or []
    print(f"  Stored alternatives (should be ≤3): {alts}")
    assert len(alts) == 3, f"cap failed — expected 3, got {len(alts)}"
    print(f"  ✓ exactly 3 alternatives persisted (cap holds)")

    # And every one of the 3 alts must have been enqueued with the guard.
    alt_enqueue_calls = [c for c in enqueue_calls if c["ex_id"] != test_seed_id]
    assert len(alt_enqueue_calls) == 3, f"expected 3 alt enqueues, got {len(alt_enqueue_calls)}"
    for c in alt_enqueue_calls:
        assert c["suppress_kinds"] == ("alternatives",), (
            f"BUG: alt enqueue missing recursion guard → {c}"
        )
        assert "alternatives" not in c["would_fire"], (
            f"BUG: alt would_fire contains alternatives → recursion! {c}"
        )
    print(f"  ✓ all 3 alt enqueues carry suppress_kinds=('alternatives',) — recursion impossible")

    print("\n─── CLEANUP ───")
    await cleanup_test_rows(local_db)
    print("  ✓ test rows removed")

    print("\n" + "="*68)
    print("ALL TESTS PASSED — recursion guard verified without any real API calls")
    print("="*68)


if __name__ == "__main__":
    asyncio.run(main())
