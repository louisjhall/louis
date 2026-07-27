"""Coach Dashboard V2 · Directive editor + generation status + programme summary."""
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


def _coach(uid):
    return {"id": uid, "role": "coach", "status": "active", "email": f"{uid[:8]}@t.local",
            "profile": {"v2_flags": {"coach_dashboard_v2_enabled": True}}}


def _client(uid):
    return {"id": uid, "role": "client", "status": "active", "email": f"{uid[:8]}@c.local",
            "name": f"C {uid[:6]}", "profile": {"v2_flags": {"state_foundation_enabled": True}}}


def test_directive_create_list_patch():
    async def _t(loop):
        from feature_v2_coach_directives import (
            dashboard_directive_create, dashboard_directive_list, dashboard_directive_patch,
            DirectiveBody, DirectiveScope, DirectivePatchBody,
        )
        db = _db(loop)
        co = f"co_{os.urandom(3).hex()}"; c = f"c_{os.urandom(3).hex()}"
        await db.users.insert_one(_coach(co)); await db.users.insert_one(_client(c))
        try:
            r = await dashboard_directive_create(c, DirectiveBody(
                kind="avoid_movement",
                scope=DirectiveScope(scope_kind="this_week"),
                parameters={"pattern": "gait_run_tempo"},
                free_text="No tempo running this week",
            ), coach={"id": co})
            assert r["id"] and r["kind"] == "avoid_movement" and r["source"] == "coach_editor"

            lst = await dashboard_directive_list(c, status="active", coach={"id": co})
            assert any(d["id"] == r["id"] for d in lst["directives"])

            p = await dashboard_directive_patch(c, r["id"],
                DirectivePatchBody(status="cancelled"), coach={"id": co})
            assert p["status"] == "cancelled"
        finally:
            await db.users.delete_many({"id": {"$in": [co, c]}})
            await db.coach_directives.delete_many({"client_id": c})
            await db.decision_records.delete_many({"client_id": c})
    _run(_t)


def test_generation_status_shape():
    async def _t(loop):
        from feature_v2_coach_directives import generation_status
        db = _db(loop)
        co = f"co_{os.urandom(3).hex()}"; c = f"c_{os.urandom(3).hex()}"
        await db.users.insert_one(_coach(co)); await db.users.insert_one(_client(c))
        try:
            r = await generation_status(c, month=None, coach={"id": co})
            assert r["client_id"] == c
            # exactly 8 stages, canonical order
            names = [s["stage"] for s in r["stages"]]
            assert names == [
                "roster_uploaded","roster_parsed","schedule_created","planning_programme",
                "generating_workouts","validating","ready_for_review","published",
            ]
            for s in r["stages"]:
                assert s["state"] in ("pending","in_progress","done","error")
        finally:
            await db.users.delete_many({"id": {"$in": [co, c]}})
    _run(_t)


def test_programme_summary_empty():
    async def _t(loop):
        from feature_v2_coach_directives import programme_summary
        db = _db(loop)
        co = f"co_{os.urandom(3).hex()}"; c = f"c_{os.urandom(3).hex()}"
        await db.users.insert_one(_coach(co)); await db.users.insert_one(_client(c))
        try:
            r = await programme_summary(c, coach={"id": co})
            assert r["present"] is False
        finally:
            await db.users.delete_many({"id": {"$in": [co, c]}})
    _run(_t)
