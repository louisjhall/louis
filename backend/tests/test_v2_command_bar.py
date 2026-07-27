"""Command Bar apply-flow pytest (no LLM call — inject a canned preview).

Verifies:
  - Applying an accepted `add_directive` proposal creates a coach_directive row.
  - Applying an accepted `move_assignment` proposal creates a change_set row.
  - DecisionRecord written for both.
  - Flag-gate blocks when coach flag is off.
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


def test_command_bar_apply_creates_directive_and_change_set():
    async def _t(loop):
        from feature_v2_coach_command_bar import command_apply, CommandApplyBody
        from fastapi import HTTPException
        db = _db(loop)
        cid = f"co_{os.urandom(3).hex()}"
        c = f"c_{os.urandom(3).hex()}"

        await db.users.insert_one({
            "id": cid, "role": "coach", "status": "active", "email": "co@t.local",
            "profile": {"v2_flags": {"coach_dashboard_v2_enabled": True}},
        })
        await db.users.insert_one({
            "id": c, "role": "client", "status": "active", "email": "cli@t.local",
            "profile": {},
        })

        # Insert a canned preview with two proposals
        preview_id = "pv_test"
        pid_dir = "prop_dir"
        pid_move = "prop_move"
        await db.command_bar_previews.insert_one({
            "id": preview_id, "client_id": c, "coach_id": cid,
            "month": "2026-07", "input_text": "test",
            "draft_id": None,
            "proposals": [
                {"proposal_id": pid_dir, "kind": "add_directive",
                 "directive_kind": "avoid_movement",
                 "directive_scope": "until_changed",
                 "target_kind_or_pattern": "gait_run_tempo",
                 "summary": "Avoid tempo running", "reason": "knee"},
                {"proposal_id": pid_move, "kind": "move_assignment",
                 "assignment_id": "a1",
                 "target_date": "2026-07-08",
                 "new_date": "2026-07-10",
                 "summary": "Move long run to Sunday", "reason": "recovery"},
            ],
            "status": "pending",
            "created_at": _dt.datetime.utcnow().isoformat(),
        })

        try:
            r = await command_apply(c, CommandApplyBody(
                preview_id=preview_id,
                accept_proposal_ids=[pid_dir, pid_move],
            ), coach={"id": cid})
            assert r["change_sets_created"] == 1
            assert r["directives_created"] == 1

            # Directive persisted
            d = await db.coach_directives.find_one({"client_id": c, "source": "command_bar"}, {"_id": 0})
            assert d and d["kind"] == "avoid_movement"

            # ChangeSet persisted
            cs = await db.change_sets.find_one({"client_id": c, "triggered_by": "ai_command_bar"}, {"_id": 0})
            assert cs and cs["kind"] == "assignment_moved"

            # Decision records written
            drc = await db.decision_records.count_documents(
                {"client_id": c, "rule_or_prompt.id": "command_bar"}
            )
            assert drc >= 2

            # Preview marked applied
            pv = await db.command_bar_previews.find_one({"id": preview_id}, {"_id": 0})
            assert pv["status"] == "applied"

            # Flag gate: flip off, retry, expect 409
            await db.users.update_one({"id": cid},
                                       {"$set": {"profile.v2_flags.coach_dashboard_v2_enabled": False}})
            with pytest.raises(HTTPException) as ei:
                await command_apply(c, CommandApplyBody(
                    preview_id=preview_id, accept_proposal_ids=[pid_dir]
                ), coach={"id": cid})
            assert ei.value.status_code == 409

        finally:
            await db.users.delete_many({"id": {"$in": [cid, c]}})
            await db.command_bar_previews.delete_many({"client_id": c})
            await db.coach_directives.delete_many({"client_id": c})
            await db.change_sets.delete_many({"client_id": c})
            await db.decision_records.delete_many({"client_id": c})

    _run(_t)
