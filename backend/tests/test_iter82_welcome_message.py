"""
Iter 82 — Louis welcome message on assessment finalize.

Uses a module-scoped event loop so the motor client stays bound to a single
loop across all tests (asyncio.run creates a new loop each call which breaks
motor's cached client).
"""
import sys
import asyncio
import uuid as _uuid
sys.path.insert(0, "/app/backend")

import pytest


# ---------------------------------------------------------------------------
# Shared event loop for the entire module
# ---------------------------------------------------------------------------

_LOOP: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


def _run(coro):
    return _get_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_louis_if_missing():
    from server import db, new_id, now_iso
    louis = await db.users.find_one({"email": "louis@crewfit.net"})
    if not louis:
        await db.users.insert_one({
            "id": new_id(),
            "email": "louis@crewfit.net",
            "name": "Louis Hall",
            "role": "coach",
            "created_at": now_iso(),
            "status": "active",
        })
        louis = await db.users.find_one({"email": "louis@crewfit.net"})
    return louis


async def _fresh_client(first_name: str = "Test"):
    from server import db, now_iso
    tag = _uuid.uuid4().hex[:8]
    user = {
        "id": f"user_{tag}",
        "email": f"welcome_{tag}@test.com",
        "name": f"{first_name} Pilot",
        "first_name": first_name,
        "last_name": "Pilot",
        "role": "client",
        "created_at": now_iso(),
        "onboarded": False,
        "status": "active",
    }
    await db.users.insert_one(user)
    return user


async def _cleanup(user):
    from server import db
    await db.users.delete_one({"id": user["id"]})
    await db.messages.delete_many({"to_user_id": user["id"]})
    await db.rosters.delete_many({"user_id": user["id"]})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_welcome_message_sends_once_and_is_idempotent():
    async def _inner():
        from server import _send_louis_welcome_message_if_needed, db
        louis = await _seed_louis_if_missing()
        user = await _fresh_client(first_name="Alex")
        try:
            await _send_louis_welcome_message_if_needed(user)
            msg = await db.messages.find_one({"to_user_id": user["id"], "welcome_message": True})
            assert msg is not None, "Welcome message must be created"
            assert msg["from_user_id"] == louis["id"]
            assert msg["to_user_id"] == user["id"]
            assert "Alex" in msg["text"], "should personalise with first_name"
            assert "BETA" in msg["text"], "should explain beta"
            assert "louis@crewfit.net" in msg["text"], "should include Louis's email"
            assert "roster" in msg["text"].lower(), "should prompt roster upload"
            assert "Louis" in msg["text"], "should sign off"

            fresh = await db.users.find_one({"id": user["id"]})
            assert fresh.get("louis_welcome_sent") is True
            assert fresh.get("assigned_coach_id") == louis["id"]

            # Second call — must NOT create another message
            await _send_louis_welcome_message_if_needed(user)
            count = await db.messages.count_documents({"to_user_id": user["id"], "welcome_message": True})
            assert count == 1

            # Third call with refreshed user (sentinel already set in DB)
            refreshed = await db.users.find_one({"id": user["id"]})
            await _send_louis_welcome_message_if_needed(refreshed)
            count2 = await db.messages.count_documents({"to_user_id": user["id"], "welcome_message": True})
            assert count2 == 1
        finally:
            await _cleanup(user)
    _run(_inner())


def test_welcome_message_skipped_for_coach_role():
    async def _inner():
        from server import _send_louis_welcome_message_if_needed, db, now_iso
        tag = _uuid.uuid4().hex[:8]
        coach = {
            "id": f"coach_{tag}",
            "email": f"coach_{tag}@test.com",
            "name": "Some Coach",
            "role": "coach",
            "created_at": now_iso(),
            "status": "active",
        }
        await db.users.insert_one(coach)
        try:
            await _send_louis_welcome_message_if_needed(coach)
            count = await db.messages.count_documents({"to_user_id": coach["id"], "welcome_message": True})
            assert count == 0
        finally:
            await db.users.delete_one({"id": coach["id"]})
    _run(_inner())


def test_welcome_message_with_roster_omits_upload_prompt():
    async def _inner():
        from server import _send_louis_welcome_message_if_needed, db, new_id, now_iso
        await _seed_louis_if_missing()
        user = await _fresh_client(first_name="Roster")
        await db.rosters.insert_one({
            "id": new_id(), "user_id": user["id"], "created_at": now_iso(),
            "start_date": "2026-07-20", "end_date": "2026-08-20", "days": [],
        })
        try:
            await _send_louis_welcome_message_if_needed(user)
            msg = await db.messages.find_one({"to_user_id": user["id"], "welcome_message": True})
            assert msg is not None
            assert "upload your next roster" not in msg["text"].lower()
            assert "BETA" in msg["text"]
            assert "louis@crewfit.net" in msg["text"]
        finally:
            await _cleanup(user)
    _run(_inner())
