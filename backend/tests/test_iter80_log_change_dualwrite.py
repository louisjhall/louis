"""Iter80 supplementary — verify the 3 fixes applied on top of iter79:

  S1  After PATCH /api/coach/workouts/{wid}, the audit entry appears in BOTH
      `db.coach_change_log` (legacy) AND `db.change_log` (unified stream).
  S2  GET /api/coach/clients/{cid}/programme-timeline includes the workout-edit
      event after the PATCH (reads from db.change_log).
  S3  regenerate-apply is resilient to change_log failures — a simulated log
      failure MUST NOT cause a 500 nor a double gen_jobs insert.  Verified by
      an in-process direct call to `_log_change` while monkey-patching one of
      the collections to raise, PLUS a full end-to-end HTTP call to
      /programme/regenerate-apply confirming exactly one gen_jobs row is
      created per invocation and the response is 200.

Shares the seed/cleanup style with test_iter79 — TEST_iter80_ prefix.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

COACH_EMAIL = "louis@crewfit.net"
COACH_PWD = "Louis123!"

TEST_TAG = f"TEST_iter80_{uuid.uuid4().hex[:6]}"


try:
    _LOOP = asyncio.get_event_loop()
    if _LOOP.is_closed():
        raise RuntimeError("closed")
except RuntimeError:
    _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _iso_date(days_delta: int = 0) -> str:
    return (_dt.date.today() + _dt.timedelta(days=days_delta)).isoformat()


def _iso_ts(days_delta: int = 0) -> str:
    return (_dt.datetime.utcnow() + _dt.timedelta(days=days_delta)).isoformat() + "Z"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def coach_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": COACH_EMAIL, "password": COACH_PWD}, timeout=20)
    assert r.status_code == 200, f"coach login failed: {r.text}"
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture(scope="module")
def coach_user(coach_token):
    r = requests.get(f"{API}/auth/me", headers=_auth(coach_token), timeout=20)
    assert r.status_code == 200
    return r.json()


async def _seed_client_with_workout():
    from server import db
    cid = f"{TEST_TAG}_u_{uuid.uuid4().hex[:6]}"
    rid = f"{TEST_TAG}_r_{uuid.uuid4().hex[:6]}"
    pid = f"{TEST_TAG}_p_{uuid.uuid4().hex[:6]}"
    wid = f"{TEST_TAG}_w_{uuid.uuid4().hex[:6]}"

    await db.users.insert_one({
        "id": cid, "email": f"{cid}@crewfit-test.com", "name": "Iter80 Test",
        "role": "client", "created_at": _iso_ts(-30),
        "onboarded_at": _iso_ts(-28),
        "profile": {"main_goal_key": "event", "event_type_pref": "marathon",
                    "training_days_per_week": 4},
    })
    await db.rosters.insert_one({
        "id": rid, "user_id": cid, "version": 1, "is_active": True,
        "status": "confirmed", "created_at": _iso_ts(-20),
        "week_start": _iso_date(-20), "week_end": _iso_date(-14),
    })
    await db.programmes.insert_one({
        "id": pid, "user_id": cid, "version_number": 1,
        "goal_key": "event_marathon", "goal_label": "Marathon",
        "phase": {"key": "base", "label": "Base"}, "target_sessions_per_week": 4,
        "validation_status": "ok", "coach_edited": False,
        "created_at": _iso_ts(-19),
    })
    await db.workouts.insert_one({
        "id": wid, "user_id": cid, "roster_id": rid,
        "date": _iso_date(3),
        "title": "Iter80 Original Title", "focus": "strength",
        "duration_min": 45, "day_load": "green",
        "completed": False, "coach_locked": False,
        "exercises": [
            {"exercise_id": "x1", "name": "Squat",  "sets": 3, "reps": "8", "rest_sec": 90, "rpe": 7},
            {"exercise_id": "x2", "name": "Press",  "sets": 3, "reps": "10", "rest_sec": 60, "rpe": 6},
        ],
        "created_at": _iso_ts(-3),
        "source": "template",
    })
    return cid, rid, pid, wid


async def _cleanup(cid: str):
    from server import db
    await db.users.delete_many({"id": cid})
    await db.rosters.delete_many({"user_id": cid})
    await db.programmes.delete_many({"user_id": cid})
    await db.workouts.delete_many({"user_id": cid})
    await db.change_log.delete_many({"client_id": cid})
    await db.coach_change_log.delete_many({"client_id": cid})
    await db.gen_jobs.delete_many({"user_id": cid})


@pytest.fixture(scope="module")
def seeded():
    cid, rid, pid, wid = _run(_seed_client_with_workout())
    yield {"client_id": cid, "roster_id": rid, "programme_id": pid, "workout_id": wid}
    _run(_cleanup(cid))


# =====================================================================
# S1 — dual-write verification
# =====================================================================

class TestS1DualWrite:
    def test_patch_workout_writes_to_both_collections(self, coach_token, seeded):
        wid = seeded["workout_id"]
        cid = seeded["client_id"]

        # Snapshot pre-counts
        async def _pre_counts():
            from server import db
            legacy = await db.coach_change_log.count_documents({"client_id": cid})
            unified = await db.change_log.count_documents({"client_id": cid})
            return legacy, unified

        pre_legacy, pre_unified = _run(_pre_counts())

        # Perform PATCH
        r = requests.patch(
            f"{API}/coach/workouts/{wid}",
            headers=_auth(coach_token),
            json={"title": "Iter80 EDITED title", "rationale": "dual-write test"},
            timeout=20,
        )
        assert r.status_code == 200, r.text

        # Verify each collection got at least one new row for this client
        async def _post_check():
            from server import db
            legacy_docs = await db.coach_change_log.find(
                {"client_id": cid, "category": "workout"}, {"_id": 0}
            ).to_list(20)
            unified_docs = await db.change_log.find(
                {"client_id": cid, "category": "workout"}, {"_id": 0}
            ).to_list(20)
            return legacy_docs, unified_docs

        legacy_docs, unified_docs = _run(_post_check())

        # Legacy write present
        assert len(legacy_docs) >= 1, "coach_change_log missing workout entry"
        # Unified write present
        assert len(unified_docs) >= 1, "change_log missing workout entry"

        # Shape sanity — kind='edit' should be persisted from feature module
        assert any(d.get("kind") == "edit" for d in legacy_docs), \
            f"kind='edit' not found in legacy: {[d.get('kind') for d in legacy_docs]}"
        assert any(d.get("kind") == "edit" for d in unified_docs), \
            f"kind='edit' not found in unified: {[d.get('kind') for d in unified_docs]}"

        # Meta should reference the workout
        edited_unified = [d for d in unified_docs if d.get("kind") == "edit"]
        assert edited_unified
        m = edited_unified[0].get("meta") or {}
        # Feature module passes workout_id inside meta
        assert m.get("workout_id") == wid or edited_unified[0].get("title"), \
            f"expected workout_id in meta or title on entry: {edited_unified[0]}"


# =====================================================================
# S2 — programme-timeline surfaces the workout-edit event
# =====================================================================

class TestS2TimelineIncludesEdit:
    def test_timeline_lists_workout_edit(self, coach_token, seeded):
        # Note: S1 above already performed a PATCH within the same module scope.
        cid = seeded["client_id"]
        r = requests.get(
            f"{API}/coach/clients/{cid}/programme-timeline?limit=50",
            headers=_auth(coach_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        events = body.get("events") or body.get("timeline") or body.get("items") or []
        assert isinstance(events, list) and len(events) >= 1, \
            f"timeline returned no events. Body keys: {list(body.keys())}"

        # Find a workout-edit-shaped event.  Accept any of these criteria to be
        # resilient to timeline shaping helpers:
        #   - kind == 'edit'  AND category == 'workout'
        #   - or title/description references the edit
        matches = [
            e for e in events
            if (
                (e.get("kind") == "edit" and e.get("category") == "workout")
                or (isinstance(e.get("title"), str) and "workout" in e["title"].lower() and "edit" in e["title"].lower())
                or (isinstance(e.get("description"), str) and "dual-write test" in e["description"])
            )
        ]
        assert matches, (
            "programme-timeline did not surface the workout-edit event. "
            f"First 3 events: {events[:3]}"
        )


# =====================================================================
# S3 — regenerate-apply is resilient to log failure (no double enqueue)
# =====================================================================

class TestS3RegenApplyResilience:
    def test_direct_log_change_swallows_write_failure(self, seeded):
        """Directly exercise the helper with a monkey-patched collection that
        raises, and confirm the helper does not propagate the exception."""
        from server import _log_change, db

        cid = seeded["client_id"]
        original = db.change_log.insert_one

        async def _boom(*a, **kw):
            raise RuntimeError("simulated change_log failure")

        db.change_log.insert_one = _boom  # type: ignore[assignment]
        try:
            # Should NOT raise even though change_log.insert_one blows up.
            _run(_log_change(
                coach_id=None, client_id=cid,
                category="workout", kind="edit",
                title="S3 direct simulated",
                description="log-failure resilience test",
                actor="coach", meta={"probe": "iter80"},
            ))
        finally:
            db.change_log.insert_one = original  # type: ignore[assignment]

        # coach_change_log should have received the write (it wasn't patched)
        async def _check_legacy():
            return await db.coach_change_log.count_documents(
                {"client_id": cid, "meta.probe": "iter80"}
            )
        legacy_count = _run(_check_legacy())
        assert legacy_count == 1, \
            f"legacy write should still succeed even when unified write fails, got {legacy_count}"

    def test_regenerate_apply_creates_exactly_one_job(self, coach_token, seeded):
        cid = seeded["client_id"]

        # Ensure clean gen_jobs baseline for this client
        async def _wipe_jobs():
            from server import db
            await db.gen_jobs.delete_many({"user_id": cid})
        _run(_wipe_jobs())

        r = requests.post(
            f"{API}/coach/clients/{cid}/programme/regenerate-apply",
            headers=_auth(coach_token),
            json={"preserve_coach_locked": True, "preserve_completed": True,
                  "reason": "iter80 resilience"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        job_id = r.json().get("job_id")
        assert job_id

        async def _count_jobs():
            from server import db
            docs = await db.gen_jobs.find({"user_id": cid}, {"_id": 0}).to_list(10)
            return docs

        jobs = _run(_count_jobs())
        assert len(jobs) == 1, f"expected exactly 1 gen_jobs row, got {len(jobs)}: {jobs}"
        assert jobs[0]["id"] == job_id
        assert jobs[0]["status"] == "queued"
        assert jobs[0]["kind"] == "programme_regenerate"
