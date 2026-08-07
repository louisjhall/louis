"""
Iter 146 — Coach Calendar: merge manual workouts (db.workouts, source=coach_manual)
into cells and override V2 generated plans on shared dates.

This test uses mongomock via monkey-patching `db` on `feature_v2_coach_home`
to avoid needing a real Mongo instance. It exercises the endpoint by calling
`endpoint_coach_calendar` directly.

Run:
    cd /app/backend && python /app/scripts/test_iter146_calendar_manual_merge.py
"""
import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "/app/backend")


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_args, **_kw):
        return self

    async def to_list(self, _n):
        return list(self._docs)


class FakeCollection:
    def __init__(self, docs=None, one=None):
        self._docs = docs or []
        self._one = one

    def find(self, *_a, **_kw):
        return FakeCursor(self._docs)

    async def find_one(self, *_a, **_kw):
        return self._one


async def main():
    # Delay import so we can monkey-patch after — import server first to
    # allow all its side-effect imports of feature_v2_coach_home to complete
    # (avoids partial-init circular import).
    import server  # noqa: F401
    import feature_v2_coach_home as mod

    CID = "cli-1"
    START = "2026-06-15"

    # Users: one client
    users_docs = [{
        "id": CID, "name": "Test", "email": "test@example.com",
        "role": "client", "profile": {},
    }]

    # V2 live plan with 2 placements: one on 2026-06-15 (will be overridden),
    # one on 2026-06-16 (will remain).
    live_doc = {
        "id": "plan-1",
        "placements": [
            {"date": "2026-06-15", "kind": "session", "exposure_id": "exp-a"},
            {"date": "2026-06-16", "kind": "session", "exposure_id": "exp-b"},
        ],
        "session_specs": {
            "exp-a": {"spec_kind": "strength", "duration_min": 45},
            "exp-b": {"spec_kind": "running",  "duration_min": 30},
        },
    }

    # Manual workouts: one on 2026-06-15 (overrides V2), one on 2026-06-17 (fills empty day).
    manual_docs = [
        {
            "id": "man-1", "user_id": CID, "date": "2026-06-15",
            "title": "Coach Custom Push Day", "workout_type": "strength",
            "focus": "strength", "duration_min": 55,
            "source": "coach_manual", "manual_lock": True,
        },
        {
            "id": "man-2", "user_id": CID, "date": "2026-06-17",
            "title": "", "workout_type": "mobility",
            "duration_min": 20,
            "source": "coach_manual", "manual_lock": True,
        },
    ]

    def find_dispatcher(query, *_a, **_kw):
        # db.workouts is queried with source=coach_manual
        if query.get("source") == "coach_manual":
            return FakeCursor(manual_docs)
        # schedule_days, others -> return empty
        return FakeCursor([])

    fake_db = MagicMock()
    fake_db.users.find = MagicMock(return_value=FakeCursor(users_docs))
    fake_db.schedule_days.find = MagicMock(return_value=FakeCursor([]))
    fake_db.plan_live_v2.find_one = AsyncMock(return_value=live_doc)
    fake_db.workouts = SimpleNamespace(find=find_dispatcher)
    fake_db.plan_drafts_v2.find_one = AsyncMock(return_value=None)
    fake_db.programmes_v2.find_one = AsyncMock(return_value=None)
    fake_db.programme_phases_v2.find_one = AsyncMock(return_value=None)

    mod.db = fake_db

    # Neutralise flight-support import (raise-based fallback works)
    # so we don't hit that path.
    async def fake_flight(*_a, **_kw):
        return {}

    # Bypass role dep by calling underlying function via .__wrapped__ chain
    # (FastAPI Depends wraps but our function is a plain coroutine).
    result = await mod.endpoint_coach_calendar(
        days=7, start=START, include_test=True, q=None,
        coach={"id": "coach-1", "role": "coach"},
    )

    rows = result["clients"]
    assert len(rows) == 1, f"expected 1 client row, got {len(rows)}"
    days = {c["date"]: c for c in rows[0]["days"]}

    # Day 2026-06-15 → manual OVERRIDES V2
    d15 = days["2026-06-15"]
    assert len(d15["trainings"]) == 1, f"day15 should have exactly 1 training (manual only), got {d15['trainings']}"
    t15 = d15["trainings"][0]
    assert t15["id"] == "manual:man-1", f"day15 id should be manual:man-1, got {t15['id']}"
    assert t15["label"] == "Coach Custom Push Day", f"day15 label mismatch: {t15['label']}"
    assert t15["kind"] == "strength"
    assert t15["duration_min"] == 55
    assert t15.get("source") == "manual"

    # Day 2026-06-16 → generated V2 remains (no manual)
    d16 = days["2026-06-16"]
    assert len(d16["trainings"]) == 1
    t16 = d16["trainings"][0]
    assert t16["id"].startswith("v2p:"), f"day16 should be V2 placement, got {t16['id']}"
    assert t16["label"] == "Run"

    # Day 2026-06-17 → manual only (no V2 placement) — empty title falls back to humanised kind
    d17 = days["2026-06-17"]
    assert len(d17["trainings"]) == 1
    t17 = d17["trainings"][0]
    assert t17["id"] == "manual:man-2"
    assert t17["label"] == "Mobility", f"expected humanised fallback label, got {t17['label']}"

    print("OK — manual workouts folded into calendar; override rule respected.")
    print(f"  · 2026-06-15: {t15['id']} ({t15['label']})  ← manual overrides V2")
    print(f"  · 2026-06-16: {t16['id']} ({t16['label']})  ← V2 retained")
    print(f"  · 2026-06-17: {t17['id']} ({t17['label']})  ← manual-only day")


if __name__ == "__main__":
    asyncio.run(main())
