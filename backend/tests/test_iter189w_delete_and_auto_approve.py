"""Iter189w · Backend tests for
  1) DELETE /api/messages/{message_id} sender-only hard delete
  2) _tick_auto_approve_stale_reviews is now a NO-OP (returns 0, no DB writes)
  3) Coach explicit approval still works and does NOT insert an auto Louis
     chat message.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import uuid

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASS = "Client123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASS = "Louis123!"


# ---------------------------------------------------------------------------
# Fixtures — login and mongo direct
# ---------------------------------------------------------------------------
def _login(email: str, password: str):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    d = r.json()
    return d["token"], d["user"]


@pytest.fixture(scope="module")
def client_auth():
    tok, u = _login(CLIENT_EMAIL, CLIENT_PASS)
    return {"token": tok, "user": u, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def coach_auth():
    tok, u = _login(COACH_EMAIL, COACH_PASS)
    return {"token": tok, "user": u, "headers": {"Authorization": f"Bearer {tok}"}}


def _fresh_db():
    """Return a fresh motor db handle — must be called inside the running loop
    so motor binds to it correctly."""
    sys.path.insert(0, "/app/backend")
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ===========================================================================
# A · DELETE /api/messages/{message_id}
# ===========================================================================
class TestDeleteMessage:
    def test_full_flow_sender_only_delete(self, client_auth, coach_auth):
        coach_id = coach_auth["user"]["id"]
        client_id = client_auth["user"]["id"]

        # A1 — client sends
        r = requests.post(f"{BASE_URL}/api/messages",
                          json={"to_user_id": coach_id, "text": f"TEST_iter189w_client_{uuid.uuid4().hex[:6]}"},
                          headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        client_msg = r.json()
        client_msg_id = client_msg.get("id")
        assert client_msg_id, f"client send missing id: {client_msg}"

        # A2 — coach sends
        r = requests.post(f"{BASE_URL}/api/messages",
                          json={"to_user_id": client_id, "text": f"TEST_iter189w_coach_delete_me_{uuid.uuid4().hex[:6]}"},
                          headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        coach_msg = r.json()
        coach_msg_id = coach_msg.get("id")
        assert coach_msg_id

        # A3 — coach deletes own → 200 {ok, deleted_id}
        r = requests.delete(f"{BASE_URL}/api/messages/{coach_msg_id}",
                            headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert body.get("deleted_id") == coach_msg_id

        # A4 — client GET /messages/{coach_id} → no coach_msg
        r = requests.get(f"{BASE_URL}/api/messages/{coach_id}",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        assert coach_msg_id not in ids, "deleted coach message still visible to client"

        # A5 — coach GET /messages/{client_id} → no coach_msg
        r = requests.get(f"{BASE_URL}/api/messages/{client_id}",
                         headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()]
        assert coach_msg_id not in ids, "deleted coach message still visible to coach"

        # A6 — coach tries to delete CLIENT's message → 403
        r = requests.delete(f"{BASE_URL}/api/messages/{client_msg_id}",
                            headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

        # A7 — delete non-existent → 404
        r = requests.delete(f"{BASE_URL}/api/messages/does-not-exist-{uuid.uuid4().hex}",
                            headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text}"

        # Cleanup — remove client_msg_id too
        requests.delete(f"{BASE_URL}/api/messages/{client_msg_id}",
                        headers=client_auth["headers"], timeout=30)


# ===========================================================================
# B · _tick_auto_approve_stale_reviews is a no-op
# ===========================================================================
class TestAutoApproveNeutered:
    def test_tick_returns_zero_without_touching_db(self):
        """B1 · Direct call must return 0 and not flip any roster."""
        sys.path.insert(0, "/app/backend")
        from feature_roster_coach_review import _tick_auto_approve_stale_reviews

        loop = asyncio.new_event_loop()
        try:
            async def _run():
                db = _fresh_db()
                return await _tick_auto_approve_stale_reviews(db)
            result = loop.run_until_complete(_run())
        finally:
            loop.close()
        assert result == 0

    def test_stale_roster_stays_awaiting_review(self):
        """B2 · Seed a stale awaiting_review roster; tick; ensure no state flip
        and no Louis auto_kind:'roster_auto_approve' message inserted."""
        sys.path.insert(0, "/app/backend")
        from feature_roster_coach_review import _tick_auto_approve_stale_reviews

        rid = f"TEST_iter189w_stale_{uuid.uuid4().hex[:8]}"
        uid = f"TEST_iter189w_user_{uuid.uuid4().hex[:8]}"
        stale_iso = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=48)).isoformat().replace("+00:00", "Z")

        loop = asyncio.new_event_loop()
        try:
            async def _setup_and_run():
                db = _fresh_db()
                await db.rosters.insert_one({
                    "id": rid,
                    "user_id": uid,
                    "coach_review_state": "awaiting_review",
                    "awaiting_review_since": stale_iso,
                    "start_date": "2027-01-01",
                    "end_date": "2027-01-31",
                    "created_at": stale_iso,
                    "TEST_iter189w": True,
                })
                pre_msg_count = await db.messages.count_documents({
                    "to_user_id": uid, "auto_kind": "roster_auto_approve",
                })
                res = await _tick_auto_approve_stale_reviews(db)
                assert res == 0, f"tick returned {res}, expected 0"

                fresh = await db.rosters.find_one({"id": rid}, {"_id": 0})
                assert fresh is not None
                assert fresh.get("coach_review_state") == "awaiting_review", (
                    f"roster state flipped to {fresh.get('coach_review_state')}"
                )

                post_msg_count = await db.messages.count_documents({
                    "to_user_id": uid, "auto_kind": "roster_auto_approve",
                })
                assert post_msg_count == pre_msg_count, (
                    "auto Louis message inserted despite disabled tick"
                )
                # cleanup
                await db.rosters.delete_one({"id": rid})
                await db.messages.delete_many({"to_user_id": uid})

            loop.run_until_complete(_setup_and_run())
        finally:
            loop.close()

    def test_scheduler_call_is_commented_out(self):
        """B3 · Grep the running server.py — the tick call in the reminder
        block should be commented out."""
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        # Find any UNCOMMENTED occurrence of the tick invocation
        offending = []
        for lineno, line in enumerate(src.splitlines(), start=1):
            if "_tick_auto_approve_stale_reviews(db)" in line:
                stripped = line.strip()
                if not stripped.startswith("#"):
                    offending.append((lineno, line))
        assert not offending, f"un-commented tick call still wired: {offending}"


# ===========================================================================
# C · Coach explicit approval still works and inserts no auto Louis message
# ===========================================================================
class TestCoachExplicitApproveStillWorks:
    def test_explicit_approve_flips_state_no_auto_message(self, coach_auth):
        """Seed an awaiting_review roster for a real user assigned to Louis;
        POST /api/coach/rosters/{rid}/review outcome=approved; confirm state
        flips and NO auto_kind='roster_auto_approve' message appears."""
        sys.path.insert(0, "/app/backend")

        coach_id = coach_auth["user"]["id"]
        rid = f"TEST_iter189w_explicit_{uuid.uuid4().hex[:8]}"

        loop = asyncio.new_event_loop()
        try:
            async def _seed_and_verify():
                db = _fresh_db()
                # find a client assigned to Louis (or fall back to the working test client)
                client = await db.users.find_one(
                    {"role": "client", "assigned_coach_id": coach_id},
                    {"_id": 0, "id": 1, "assigned_coach_id": 1},
                )
                if not client:
                    # assign our working client on the fly
                    await db.users.update_one(
                        {"email": CLIENT_EMAIL},
                        {"$set": {"assigned_coach_id": coach_id, "TEST_iter189w_reassigned": True}},
                    )
                    client = await db.users.find_one({"email": CLIENT_EMAIL}, {"_id": 0, "id": 1})
                uid = client["id"]

                await db.rosters.insert_one({
                    "id": rid,
                    "user_id": uid,
                    "coach_review_state": "awaiting_review",
                    "awaiting_review_since": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                    "start_date": "2027-02-01",
                    "end_date": "2027-02-28",
                    "TEST_iter189w": True,
                })
                pre_auto = await db.messages.count_documents({
                    "to_user_id": uid, "auto_kind": "roster_auto_approve",
                })
                return uid, pre_auto

            uid, pre_auto = loop.run_until_complete(_seed_and_verify())

            # Explicit coach approve via HTTP
            r = requests.post(
                f"{BASE_URL}/api/coach/rosters/{rid}/review",
                json={"outcome": "approved"},
                headers=coach_auth["headers"],
                timeout=30,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("ok") is True
            roster = body.get("roster") or {}
            # state should be coach_approved (or similar approved marker)
            state = roster.get("coach_review_state") or roster.get("state")
            assert state in ("coach_approved", "approved"), f"unexpected state {state}: {roster}"

            async def _verify_no_auto_msg():
                db = _fresh_db()
                post_auto = await db.messages.count_documents({
                    "to_user_id": uid, "auto_kind": "roster_auto_approve",
                })
                assert post_auto == pre_auto, (
                    "explicit approval unexpectedly inserted an auto_24h Louis message"
                )
                # cleanup
                await db.rosters.delete_one({"id": rid})

            loop.run_until_complete(_verify_no_auto_msg())
        finally:
            loop.close()
