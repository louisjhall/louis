"""Iter 131b — targeted test for the engine_v2_kickoff in-flight lock.

Verifies that a duplicate rebuild request for the same client, arriving
while a first rebuild is still running, returns a lightweight
`{ok:true, in_flight:true, status:"rebuild_already_running"}` response
without starting a second expensive build.

This test drives only the lock branch by monkey-patching the DB layer;
it does not spin up the FastAPI app or exercise the full pipeline.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest

from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feature_v2_engine_v2_kickoff as kickoff_mod  # noqa: E402


class _FakeLockCollection:
    """Minimal in-memory stand-in for db.engine_v2_kickoff_locks.

    Enforces _id uniqueness like MongoDB does.
    """
    def __init__(self):
        self.docs: dict[str, dict] = {}

    async def insert_one(self, doc):
        if doc["_id"] in self.docs:
            raise DuplicateKeyError(f"duplicate _id {doc['_id']}")
        self.docs[doc["_id"]] = dict(doc)
        return types.SimpleNamespace(inserted_id=doc["_id"])

    async def find_one(self, flt):
        return self.docs.get(flt["_id"])

    async def delete_one(self, flt):
        removed = self.docs.pop(flt["_id"], None)
        return types.SimpleNamespace(deleted_count=1 if removed else 0)


class _FakeDb:
    def __init__(self, lock_col):
        self.engine_v2_kickoff_locks = lock_col


class _FakeCoach:
    def get(self, k, default=None):
        return {"id": "coach_x", "email": "louis@crewfit.net"}.get(k, default)


class _FakeBody:
    planning_window_weeks = 4


class TestKickoffLock(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Swap the db module attribute so the endpoint sees our fake.
        self._real_db = kickoff_mod.db
        self._fake_lock = _FakeLockCollection()
        kickoff_mod.db = _FakeDb(self._fake_lock)  # type: ignore[assignment]
        # Stub _is_engine_v2_enabled to True so we get past the flag check.
        self._real_enabled = kickoff_mod._is_engine_v2_enabled
        async def _always_on(_cid): return True
        kickoff_mod._is_engine_v2_enabled = _always_on  # type: ignore[assignment]

    async def asyncTearDown(self):
        kickoff_mod.db = self._real_db  # type: ignore[assignment]
        kickoff_mod._is_engine_v2_enabled = self._real_enabled  # type: ignore[assignment]

    async def test_second_call_returns_in_flight(self):
        """Simulate: first call has acquired the lock and is still running.
        Second call must return {ok:true, in_flight:true} without doing work."""
        # Manually plant a fresh lock — simulating the state during a real
        # in-progress rebuild.
        cid = "client_abc"
        self._fake_lock.docs[f"kickoff:{cid}"] = {
            "_id": f"kickoff:{cid}",
            "client_id": cid,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "coach_id": "coach_x",
            "coach_email": "louis@crewfit.net",
        }
        # Stub the impl so we can assert it was NOT called for the
        # duplicate request.
        called = {"n": 0}
        async def _fake_impl(*a, **kw): called["n"] += 1; return {"ok": True}
        real_impl = kickoff_mod._engine_v2_kickoff_impl
        kickoff_mod._engine_v2_kickoff_impl = _fake_impl  # type: ignore
        try:
            result = await kickoff_mod.engine_v2_kickoff(
                client_id=cid,
                body=_FakeBody(),
                coach=_FakeCoach(),
            )
        finally:
            kickoff_mod._engine_v2_kickoff_impl = real_impl  # type: ignore

        self.assertTrue(result.get("ok"), f"unexpected result: {result}")
        self.assertTrue(result.get("in_flight"),
                          f"expected in_flight=True, got: {result}")
        self.assertEqual(result.get("status"), "rebuild_already_running")
        self.assertEqual(called["n"], 0,
                          "impl must NOT be called when a rebuild is already running")

    async def test_stale_lock_is_cleared_and_reacquired(self):
        """A lock older than 180s is treated as abandoned. The new request
        force-clears it and runs the impl normally."""
        cid = "client_stale"
        # Plant an obviously stale lock (10 minutes ago).
        stale_iso = (datetime.now(timezone.utc) -
                     __import__("datetime").timedelta(minutes=10)).isoformat()
        self._fake_lock.docs[f"kickoff:{cid}"] = {
            "_id": f"kickoff:{cid}",
            "client_id": cid,
            "status": "running",
            "started_at": stale_iso,
            "coach_id": "coach_x",
        }
        called = {"n": 0}
        async def _fake_impl(*a, **kw):
            called["n"] += 1
            return {"ok": True, "draft_id": "draft_new", "counts": {"placements": 5}}
        real_impl = kickoff_mod._engine_v2_kickoff_impl
        kickoff_mod._engine_v2_kickoff_impl = _fake_impl  # type: ignore
        try:
            result = await kickoff_mod.engine_v2_kickoff(
                client_id=cid,
                body=_FakeBody(),
                coach=_FakeCoach(),
            )
        finally:
            kickoff_mod._engine_v2_kickoff_impl = real_impl  # type: ignore

        self.assertFalse(result.get("in_flight"))
        self.assertEqual(result.get("draft_id"), "draft_new")
        self.assertEqual(called["n"], 1,
                          "impl must run once when a stale lock is cleared")

    async def test_first_call_acquires_lock_and_releases_on_success(self):
        """On a clean state, the endpoint acquires the lock, runs the
        impl, and releases the lock on success."""
        cid = "client_fresh"
        called = {"n": 0}
        # During impl execution the lock must be held.
        async def _fake_impl(*a, **kw):
            called["n"] += 1
            # Lock present while impl runs
            in_lock = self._fake_lock.docs.get(f"kickoff:{cid}")
            self.assertIsNotNone(in_lock, "lock must be held during impl")
            return {"ok": True, "draft_id": "draft_1"}
        real_impl = kickoff_mod._engine_v2_kickoff_impl
        kickoff_mod._engine_v2_kickoff_impl = _fake_impl  # type: ignore
        try:
            result = await kickoff_mod.engine_v2_kickoff(
                client_id=cid, body=_FakeBody(), coach=_FakeCoach(),
            )
        finally:
            kickoff_mod._engine_v2_kickoff_impl = real_impl  # type: ignore

        self.assertEqual(called["n"], 1)
        self.assertEqual(result.get("draft_id"), "draft_1")
        # After success the lock must be released.
        self.assertNotIn(f"kickoff:{cid}", self._fake_lock.docs)

    async def test_lock_released_even_when_impl_raises(self):
        """If the pipeline raises, the lock must still be released so the
        coach can safely retry."""
        cid = "client_retry"
        async def _fake_impl(*a, **kw): raise RuntimeError("boom")
        real_impl = kickoff_mod._engine_v2_kickoff_impl
        kickoff_mod._engine_v2_kickoff_impl = _fake_impl  # type: ignore
        try:
            with self.assertRaises(RuntimeError):
                await kickoff_mod.engine_v2_kickoff(
                    client_id=cid, body=_FakeBody(), coach=_FakeCoach(),
                )
        finally:
            kickoff_mod._engine_v2_kickoff_impl = real_impl  # type: ignore

        self.assertNotIn(f"kickoff:{cid}", self._fake_lock.docs,
                          "lock must be released after a raised exception")


if __name__ == "__main__":
    unittest.main()
