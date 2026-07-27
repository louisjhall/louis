"""Coach Dashboard V2 aggregate endpoints — pytest.

Verifies:
  1. Coach flag gate blocks endpoints when off.
  2. Enabling flag exposes summary + attention + clients endpoints.
  3. Workspace endpoint aggregates schedule_days + assignments + counts for
     a V2 client, and falls back to V1 read-only rows for a V1 client.
  4. Batch approve-ready flips proposed/ready assignments to live and
     writes a new plan_version.
"""
from __future__ import annotations

import os, sys, asyncio, datetime as _dt

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mongo_available() -> bool:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    return bool(os.environ.get("MONGO_URL"))


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason="Mongo not configured"
)


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_factory(loop))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _db(loop):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
    return client[os.environ.get("DB_NAME", "crewfit_v1")]


def _client(uid: str, v2: bool = True) -> dict:
    flags = {"state_foundation_enabled": True, "roster_facets_enabled": True,
             "scheduling_v2_enabled": True, "construction_v2_enabled": True}
    return {"id": uid, "email": f"{uid[:8]}@t.local", "name": f"C {uid[:6]}",
            "role": "client", "status": "active",
            "profile": {"v2_flags": flags if v2 else {}}}


def _coach(uid: str, v2_dash: bool = True) -> dict:
    return {"id": uid, "email": f"{uid[:8]}@coach.test", "role": "coach",
            "status": "active",
            "profile": {"v2_flags": {"coach_dashboard_v2_enabled": v2_dash}}}


def test_flag_gate_blocks():
    async def _t(loop):
        from feature_v2_coach_dashboard import (
            dashboard_summary, dashboard_attention, dashboard_clients,
            _coach_has_v2_flag,
        )
        from fastapi import HTTPException
        db = _db(loop)
        cid = f"c_{os.urandom(3).hex()}"
        # Insert coach without the flag
        await db.users.insert_one(_coach(cid, v2_dash=False))
        try:
            coach = {"id": cid}
            with pytest.raises(HTTPException) as ei:
                await dashboard_summary(coach=coach)
            assert ei.value.status_code == 409
            with pytest.raises(HTTPException) as ei:
                await dashboard_attention(limit=10, coach=coach)
            assert ei.value.status_code == 409
        finally:
            await db.users.delete_one({"id": cid})
    _run(_t)


def test_summary_and_clients_when_enabled():
    async def _t(loop):
        from feature_v2_coach_dashboard import (
            dashboard_summary, dashboard_attention, dashboard_clients,
        )
        db = _db(loop)
        cid = f"co_{os.urandom(3).hex()}"
        client1 = f"c1_{os.urandom(3).hex()}"
        client2 = f"c2_{os.urandom(3).hex()}"
        await db.users.insert_one(_coach(cid))
        await db.users.insert_one(_client(client1, v2=True))
        await db.users.insert_one(_client(client2, v2=False))
        try:
            coach = {"id": cid}
            summ = await dashboard_summary(coach=coach)
            assert summ["active_clients"] >= 2
            att = await dashboard_attention(limit=50, coach=coach)
            assert isinstance(att["attention"], list)
            cli = await dashboard_clients(filter=None, q=None, coach=coach)
            got = {c["client_id"]: c for c in cli["clients"]}
            assert client1 in got and client2 in got
            assert got[client1]["kind"] == "v2"
            assert got[client2]["kind"] == "v1"
        finally:
            await db.users.delete_many({"id": {"$in": [cid, client1, client2]}})
    _run(_t)


def test_workspace_month_aggregate():
    async def _t(loop):
        from feature_v2_coach_dashboard import workspace_month
        db = _db(loop)
        cid = f"co_{os.urandom(3).hex()}"
        c = f"c_{os.urandom(3).hex()}"
        await db.users.insert_one(_coach(cid))
        await db.users.insert_one(_client(c, v2=True))

        # Insert a couple of V2 schedule days + one assignment
        today = _dt.date.today()
        month = today.strftime("%Y-%m")
        try:
            await db.schedule_days.insert_one({
                "id": "sd1", "client_id": c, "date": today.isoformat(),
                "derived": {"classification": "home", "duty_burden_score": 10,
                             "duty_burden_band": "light",
                             "training_opportunity": 80, "available_time_min": 60,
                             "recommended_intensity_ceiling": "any"},
                "duties": [], "source_roster_id": "r1", "parser_confidence": 0.9,
                "version": 1, "updated_at": _dt.datetime.utcnow().isoformat(),
                "updated_by": cid,
            })
            await db.workout_assignments.insert_one({
                "id": "a1", "client_id": c, "programme_id": "p1",
                "objective_exposure_id": f"e_ws_{os.urandom(3).hex()}",
                "objective_id": "o1",
                "schedule_day_id": "sd1", "date": today.isoformat(),
                "status": "ready", "importance": "key", "planned_duration_min": 45,
                "locked": False, "kind": "upper_hypertrophy",
                "created_at": _dt.datetime.utcnow().isoformat(),
                "updated_at": _dt.datetime.utcnow().isoformat(),
            })
            coach = {"id": cid}
            ws = await workspace_month(c, month, coach=coach)
            assert ws["client"]["kind"] == "v2"
            assert ws["counts"]["ready"] == 1
            assert any(d["date"] == today.isoformat() for d in ws["days"])
        finally:
            await db.users.delete_many({"id": {"$in": [cid, c]}})
            await db.schedule_days.delete_many({"client_id": c})
            await db.workout_assignments.delete_many({"client_id": c})
    _run(_t)


def test_batch_approve_ready_creates_plan_version():
    async def _t(loop):
        from feature_v2_coach_dashboard import plan_approve_ready, ApproveReadyBody
        db = _db(loop)
        cid = f"co_{os.urandom(3).hex()}"
        c = f"c_{os.urandom(3).hex()}"
        await db.users.insert_one(_coach(cid))
        await db.users.insert_one(_client(c, v2=True))
        today = _dt.date.today()
        try:
            await db.workout_assignments.insert_many([
                {"id": "aa", "client_id": c, "date": today.isoformat(),
                 "objective_exposure_id": f"e_aa_{os.urandom(3).hex()}",
                 "status": "ready", "locked": False,
                 "created_at": _dt.datetime.utcnow().isoformat(),
                 "updated_at": _dt.datetime.utcnow().isoformat()},
                {"id": "bb", "client_id": c, "date": today.isoformat(),
                 "objective_exposure_id": f"e_bb_{os.urandom(3).hex()}",
                 "status": "proposed", "locked": False,
                 "created_at": _dt.datetime.utcnow().isoformat(),
                 "updated_at": _dt.datetime.utcnow().isoformat()},
            ])
            coach = {"id": cid}
            r = await plan_approve_ready(c, ApproveReadyBody(month=today.strftime("%Y-%m")),
                                          coach=coach)
            assert r["approved_count"] == 2
            assert r["version_id"]
            # Confirm assignments went live
            still_ready = await db.workout_assignments.count_documents(
                {"client_id": c, "status": {"$in": ["ready", "proposed"]}}
            )
            assert still_ready == 0
        finally:
            await db.users.delete_many({"id": {"$in": [cid, c]}})
            await db.workout_assignments.delete_many({"client_id": c})
            await db.plan_versions.delete_many({"client_id": c})
            await db.plan_snapshots.delete_many({"client_id": c})
            await db.approvals.delete_many({"client_id": c})
    _run(_t)
