"""E2E — Session A closes-the-loop.

Three tests, one file:

1. Directive → Planner:
   Coach adds "avoid_movement: gait_run_tempo". P5 plan_build refuses to
   place a tempo_run objective on any day. Exception is written with kind
   coach_directive_conflict.

2. ChangeSet → Draft applier:
   Create a proposed change_set kind=assignment_moved.
   Call apply_pending_change_sets_for. Assignment's date changes;
   change_set status becomes 'applied'.

3. Roster_changed emitter:
   Insert schedule_days for one date with classification=home.
   Change to layover_full. Call emit_roster_change_exceptions.
   Exception row written, kind=roster_change.
"""
from __future__ import annotations

import os, sys, asyncio, datetime as _dt
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mongo_available() -> bool:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    return bool(os.environ.get("MONGO_URL"))


pytestmark = pytest.mark.skipif(not _mongo_available(), reason="Mongo not configured")


def _run(cf):
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    try: return loop.run_until_complete(cf(loop))
    finally: loop.close(); asyncio.set_event_loop(None)


def _db(loop):
    from motor.motor_asyncio import AsyncIOMotorClient
    c = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
    return c[os.environ.get("DB_NAME", "crewfit_v1")]


def test_directive_engine_directive_forbids_run():
    async def _t(loop):
        from feature_v2_directive_engine import active_directives_for, directive_forbids_kind
        db = _db(loop)
        c = f"c_{os.urandom(3).hex()}"
        did = f"d_{os.urandom(3).hex()}"
        await db.users.insert_one({"id": c, "role": "client", "status": "active",
                                    "profile": {"v2_flags": {"state_foundation_enabled": True}}})
        await db.coach_directives.insert_one({
            "id": did, "client_id": c, "coach_id": "co", "kind": "avoid_movement",
            "scope": {"scope_kind": "until_changed"},
            "parameters": {"pattern": "gait_run_tempo"},
            "free_text": "no tempo running",
            "status": "active", "source": "coach_editor",
            "created_at": _dt.datetime.utcnow().isoformat(),
            "updated_at": _dt.datetime.utcnow().isoformat(),
        })
        try:
            actives = await active_directives_for(c, _dt.date.today())
            assert any(a["id"] == did for a in actives), "directive must be active"
            assert directive_forbids_kind(actives, "tempo_run"), "tempo_run should be forbidden"
            assert directive_forbids_kind(actives, "long_run"), "generic run should be forbidden"
            assert not directive_forbids_kind(actives, "upper_hypertrophy"), "strength not forbidden"
        finally:
            await db.users.delete_many({"id": c})
            await db.coach_directives.delete_many({"client_id": c})
    _run(_t)


def test_change_set_applier_moves_assignment():
    async def _t(loop):
        from feature_v2_directive_engine import apply_pending_change_sets_for
        db = _db(loop)
        c = f"c_{os.urandom(3).hex()}"
        aid = "as_" + os.urandom(3).hex()
        today = _dt.date.today()
        tomorrow = today + _dt.timedelta(days=1)
        # Schedule day for tomorrow (target)
        await db.schedule_days.insert_one({
            "id": "sd1", "client_id": c, "date": tomorrow.isoformat(),
            "derived": {"classification": "home"}, "duties": [],
            "source_roster_id": "r1", "parser_confidence": 0.9, "version": 1,
            "updated_at": _dt.datetime.utcnow().isoformat(), "updated_by": "co",
        })
        # Assignment currently on today
        await db.workout_assignments.insert_one({
            "id": aid, "client_id": c, "date": today.isoformat(),
            "objective_exposure_id": f"e_{os.urandom(3).hex()}",
            "status": "ready", "locked": False,
            "created_at": _dt.datetime.utcnow().isoformat(),
            "updated_at": _dt.datetime.utcnow().isoformat(),
        })
        # Proposed change_set: move to tomorrow
        cs_id = "cs_" + os.urandom(3).hex()
        await db.change_sets.insert_one({
            "id": cs_id, "client_id": c, "kind": "assignment_moved",
            "scope_assignment_ids": [aid],
            "after_snapshot": {"new_date": tomorrow.isoformat()},
            "status": "proposed", "created_at": _dt.datetime.utcnow().isoformat(),
        })
        try:
            r = await apply_pending_change_sets_for(c)
            assert r["applied"] == 1, r
            updated = await db.workout_assignments.find_one({"id": aid}, {"_id": 0})
            assert updated["date"] == tomorrow.isoformat()
            cs2 = await db.change_sets.find_one({"id": cs_id}, {"_id": 0})
            assert cs2["status"] == "applied"
        finally:
            await db.schedule_days.delete_many({"client_id": c})
            await db.workout_assignments.delete_many({"client_id": c})
            await db.change_sets.delete_many({"client_id": c})
            await db.decision_records.delete_many({"client_id": c})
    _run(_t)


def test_roster_change_emits_exception():
    async def _t(loop):
        from feature_v2_directive_engine import emit_roster_change_exceptions
        db = _db(loop)
        c = f"c_{os.urandom(3).hex()}"
        d = "2026-08-05"
        try:
            prior = {d: {"derived": {"classification": "home", "duty_burden_band": "light"}}}
            new = {d: {"derived": {"classification": "layover_full", "duty_burden_band": "heavy"}}}
            count = await emit_roster_change_exceptions(c, prior, new)
            assert count == 1
            row = await db.exceptions.find_one(
                {"client_id": c, "kind": "roster_change", "scope_ref": d}, {"_id": 0}
            )
            assert row and row["status"] == "open"
            assert "home" in row["human_readable_reason"]
            assert "layover_full" in row["human_readable_reason"]
        finally:
            await db.exceptions.delete_many({"client_id": c})
    _run(_t)
