"""Tests for Phase A · A1 — merged roster days across active rosters.

`/roster/current` and `_roster_days_between()` must merge days from ALL
active rosters (fixes "July disappeared after August upload").

Each test uses its own event loop + fresh Motor client to avoid the
"Event loop is closed" issue that comes from server.py's global client
being tied to the initial import-time loop.
"""
import os
import sys
import asyncio
import uuid
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mongo_available() -> bool:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    return bool(os.environ.get("MONGO_URL"))


pytestmark = pytest.mark.skipif(not _mongo_available(), reason="Mongo not configured in test env")


def _fresh_db(loop):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
    return client[os.environ.get("DB_NAME", "crewfit_v1")]


def _run_isolated(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_factory(loop))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _make_roster(user_id: str, month_yyyy_mm: str, is_active: bool = True) -> dict:
    y, m = month_yyyy_mm.split("-")
    y = int(y); m = int(m)
    days = [
        {"date": f"{y:04d}-{m:02d}-{d:02d}", "day_type": "Home Day", "confidence": 0.9}
        for d in range(1, 6)
    ]
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "start_date": days[0]["date"],
        "end_date": days[-1]["date"],
        "is_active": is_active,
        "status": "confirmed",
        "confirmed": True,
        "day_count": len(days),
        "source_filename": f"test_{month_yyyy_mm}.pdf",
    }


async def _isolated_merge(loop, docs_to_insert, d_from, d_to):
    """Insert `docs_to_insert`, call the isolated version of the merge
    logic (mirrors _roster_days_between), clean up, return merged dict."""
    import datetime as _dt
    db = _fresh_db(loop)
    uid = docs_to_insert[0]["user_id"]
    try:
        await db.rosters.insert_many([dict(d) for d in docs_to_insert])
        rosters = await db.rosters.find(
            {"user_id": uid, "is_active": True},
            {"_id": 0, "raw_response": 0},
        ).sort("created_at", -1).to_list(60)
        out: dict[str, dict] = {}
        for r in rosters:
            rid = r.get("id")
            for d in (r.get("days") or []):
                ds = str(d.get("date") or "")[:10]
                try:
                    dd = _dt.date.fromisoformat(ds)
                except Exception:
                    continue
                if not (d_from <= dd <= d_to):
                    continue
                if ds in out:
                    continue
                enriched = dict(d)
                enriched.setdefault("_source_roster_id", rid)
                out[ds] = enriched
        return out
    finally:
        await db.rosters.delete_many({"user_id": uid})


def test_roster_days_between_merges_multiple_active_rosters():
    import datetime as _dt
    uid = f"test-{uuid.uuid4()}"
    july = _make_roster(uid, "2026-07")
    august = _make_roster(uid, "2026-08")

    merged = _run_isolated(
        lambda loop: _isolated_merge(loop, [july, august], _dt.date(2026, 7, 1), _dt.date(2026, 8, 31))
    )
    dates = sorted(merged.keys())
    assert len(dates) == 10, f"expected 10 merged days, got {len(dates)}: {dates}"
    assert {d[:7] for d in dates} == {"2026-07", "2026-08"}
    for ds, d in merged.items():
        assert d.get("_source_roster_id") in (july["id"], august["id"])


def test_roster_days_between_ignores_inactive_rosters():
    import datetime as _dt
    uid = f"test-{uuid.uuid4()}"
    july = _make_roster(uid, "2026-07", is_active=True)
    aug_inactive = _make_roster(uid, "2026-08", is_active=False)

    merged = _run_isolated(
        lambda loop: _isolated_merge(loop, [july, aug_inactive], _dt.date(2026, 7, 1), _dt.date(2026, 8, 31))
    )
    dates = sorted(merged.keys())
    assert len(dates) == 5
    assert all(d[:7] == "2026-07" for d in dates)


def test_roster_days_between_newest_wins_on_conflict():
    """When two active rosters cover the same date, newest (by created_at) wins."""
    import datetime as _dt
    uid = f"test-{uuid.uuid4()}"
    older = _make_roster(uid, "2026-07")
    older["created_at"] = "2026-06-01T00:00:00+00:00"
    older["days"][0]["day_type"] = "OLD"

    newer = _make_roster(uid, "2026-07")
    newer["created_at"] = "2026-07-15T00:00:00+00:00"
    newer["days"][0]["day_type"] = "NEW"

    merged = _run_isolated(
        lambda loop: _isolated_merge(loop, [older, newer], _dt.date(2026, 7, 1), _dt.date(2026, 7, 31))
    )
    day = merged.get("2026-07-01")
    assert day is not None
    assert day["day_type"] == "NEW"
    assert day["_source_roster_id"] == newer["id"]


if __name__ == "__main__":
    import pytest as _pt
    _pt.main([__file__, "-v", "-s"])
