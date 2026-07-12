"""Iteration 44 follow-up — Verify E11000 collision fix on sibling
workout-generation endpoints.

Iteration 44 fixed the primary path `_process_upload_and_generate`. The
same buggy pattern (delete_one({'id': doc['id']}) + insert_one) was flagged
in TWO more workers in server.py:
  1. workouts_generate_month  (POST /api/workouts/generate-month)  ~ line 3967
  2. workouts_regenerate      (POST /api/workouts/regenerate)      ~ line 4066

Both now use delete_many({"user_id": user, "date": d}) + insert_one wrapped
in try/except.

This module verifies:
  * The endpoints accept a valid roster, return status=queued + job_id.
  * The background worker completes with status=done and no raw Mongo
    error strings leak (E11000 / uniq_user_date / duplicate key).
  * When a cross-roster collision exists on a target date, the worker
    still cleanly writes exactly one workout for that (user_id, date).
  * The regeneration path deletes-and-inserts cleanly.
  * Sanity: GET /api/gdpr/export and GET /api/beta/status return 200.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")

COLLISION_ROSTER_ID = "TEST-iter44-fu-collision"


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db(event_loop):
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": CLIENT_EMAIL, "password": CLIENT_PW}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def ch(client_token):
    return {"Authorization": f"Bearer {client_token['token']}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def target_roster(client_token, db, event_loop):
    """Pick an existing roster with days for this client. Prefer one whose
    days already have workouts (so the code path exercises the collision
    logic)."""
    uid = client_token["user"]["id"]

    async def _run():
        rosters = await db.rosters.find(
            {"user_id": uid}, {"_id": 0}
        ).sort("created_at", -1).to_list(200)
        # prefer rosters with >=5 days
        for r in rosters:
            if len(r.get("days") or []) >= 5:
                return r
        return rosters[0] if rosters else None

    r = event_loop.run_until_complete(_run())
    assert r is not None, "no roster found for client"
    assert r.get("days"), f"roster {r.get('id')} has no days"
    return r


# ---------------- helpers ----------------

def _poll_workouts_job(job_id: str, headers: dict, timeout_s: int = 240) -> dict:
    """Poll /api/workouts/job/{id} until status is terminal ('done' or
    'failed'). Returns final job doc."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/workouts/job/{job_id}", headers=headers, timeout=15)
        assert r.status_code == 200, f"job status returned {r.status_code}: {r.text[:200]}"
        j = r.json()
        last = j
        if j.get("status") in ("done", "failed"):
            return j
        time.sleep(2)
    pytest.fail(f"job {job_id} never reached terminal state within {timeout_s}s. last={last}")


def _assert_no_mongo_leak(payload) -> None:
    blob = str(payload).lower()
    assert "e11000" not in blob, f"raw Mongo E11000 leaked: {payload}"
    assert "uniq_user_date" not in blob, f"index name leaked: {payload}"
    assert "duplicate key" not in blob, f"raw duplicate-key error leaked: {payload}"


def _seed_cross_roster_collision(db, event_loop, user_id: str, dates: list[str]) -> int:
    """Insert one 'foreign' workout per date under COLLISION_ROSTER_ID so
    that the generate/regenerate worker MUST sweep on (user_id,date) rather
    than on (id) to avoid E11000."""
    async def _run():
        # Clear anything existing for those dates first so we can freely seed
        await db.workouts.delete_many({"user_id": user_id, "date": {"$in": dates}})
        docs = [{
            "id": f"TEST_wk_{uuid.uuid4().hex[:10]}",
            "user_id": user_id,
            "roster_id": COLLISION_ROSTER_ID,
            "date": d,
            "day_load": "green",
            "title": "TEST seeded cross-roster row",
            "location": "Home Workout",
            "duration_min": 30,
            "focus": "full",
            "warmup": [], "exercises": [], "alternatives": {},
            "rationale": "iter44 followup seed",
            "key_session": False,
            "event_phase": None,
            "approved": False, "completed": False,
            "coach_notes": "", "coach_locked": False,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        } for d in dates]
        if docs:
            await db.workouts.insert_many(docs)
        return await db.workouts.count_documents(
            {"user_id": user_id, "date": {"$in": dates},
             "roster_id": COLLISION_ROSTER_ID})
    return event_loop.run_until_complete(_run())


# ---------------- tests ----------------

class TestGenerateMonthE11000:
    """POST /api/workouts/generate-month must complete without leaking E11000
    even when a cross-roster row exists on target dates."""

    def test_seed_and_generate_month(self, client_token, ch, target_roster,
                                     db, event_loop):
        uid = client_token["user"]["id"]
        rid = target_roster["id"]
        dates = [d.get("date") for d in target_roster["days"] if d.get("date")][:5]
        assert dates, "no target dates"

        # Seed cross-roster collisions on the first few dates of the roster.
        n = _seed_cross_roster_collision(db, event_loop, uid, dates)
        assert n == len(dates), f"seed inserted {n}/{len(dates)}"

        # Kick off generation
        r = requests.post(f"{API}/workouts/generate-month",
                          json={"roster_id": rid}, headers=ch, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("status") == "queued", body
        assert body.get("job_id"), body
        job_id = body["job_id"]

        # Poll to terminal
        terminal = _poll_workouts_job(job_id, ch, timeout_s=300)
        _assert_no_mongo_leak(terminal)
        assert terminal["status"] == "done", (
            f"generate-month did not complete: {terminal}")

        # After completion, the seeded collision rows for these dates must
        # have been swept and replaced. Verify exactly one row per date and
        # roster_id is the *new* roster (not the seed).
        async def _verify():
            rows = await db.workouts.find(
                {"user_id": uid, "date": {"$in": dates}}, {"_id": 0}
            ).to_list(500)
            return rows
        rows = event_loop.run_until_complete(_verify())
        by_date: dict[str, list] = {}
        for w in rows:
            by_date.setdefault(w["date"], []).append(w)
        for d in dates:
            arr = by_date.get(d, [])
            assert len(arr) == 1, f"date {d}: expected 1 row, got {len(arr)} rows={arr}"
            assert arr[0]["roster_id"] != COLLISION_ROSTER_ID, (
                f"date {d}: seed roster_id was not replaced -> {arr[0]}")
            assert arr[0]["roster_id"] == rid, (
                f"date {d}: roster_id mismatch, expected {rid} got {arr[0]['roster_id']}")

        # Stash for the regenerate test
        pytest.iter44fu_roster_id = rid
        pytest.iter44fu_dates = dates


class TestRegenerateE11000:
    """POST /api/workouts/regenerate on a subset of dates that already have
    workouts must NOT surface E11000."""

    def test_regenerate_subset(self, client_token, ch, db, event_loop):
        uid = client_token["user"]["id"]
        rid = getattr(pytest, "iter44fu_roster_id", None)
        all_dates = getattr(pytest, "iter44fu_dates", None)
        if not rid or not all_dates:
            pytest.skip("generate-month test did not run / stash roster+dates")

        # Take a 3-date subset that already has workouts (guaranteed by the
        # previous test) so we exercise the delete-then-insert branch.
        subset = all_dates[:3]

        # Seed a cross-roster collision again on the subset to force the
        # delete_many code path.
        _seed_cross_roster_collision(db, event_loop, uid, subset)

        r = requests.post(f"{API}/workouts/regenerate",
                          json={"roster_id": rid, "dates": subset},
                          headers=ch, timeout=15)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()
        assert body.get("status") == "queued", body
        job_id = body.get("job_id")
        assert job_id, body

        terminal = _poll_workouts_job(job_id, ch, timeout_s=300)
        _assert_no_mongo_leak(terminal)
        assert terminal["status"] == "done", f"regenerate did not complete: {terminal}"

        # Verify each subset date has exactly one workout and roster_id is
        # the real roster (delete_many swept the seed).
        async def _verify():
            return await db.workouts.find(
                {"user_id": uid, "date": {"$in": subset}}, {"_id": 0}
            ).to_list(500)
        rows = event_loop.run_until_complete(_verify())
        by_date: dict[str, list] = {}
        for w in rows:
            by_date.setdefault(w["date"], []).append(w)
        for d in subset:
            arr = by_date.get(d, [])
            assert len(arr) == 1, (
                f"regenerate date {d}: expected 1 row got {len(arr)}")
            assert arr[0]["roster_id"] == rid, (
                f"regenerate date {d}: roster_id mismatch {arr[0]}")
            assert arr[0]["roster_id"] != COLLISION_ROSTER_ID


class TestGlobalUniqueIndex:
    """After the two workers ran, the compound unique index invariant must
    still hold across the whole workouts collection."""

    def test_no_dup_user_date_groups(self, db, event_loop):
        async def _run():
            pipe = [
                {"$group": {"_id": {"u": "$user_id", "d": "$date"},
                            "c": {"$sum": 1}}},
                {"$match": {"c": {"$gt": 1}}},
            ]
            return await db.workouts.aggregate(pipe).to_list(2000)
        dups = event_loop.run_until_complete(_run())
        assert dups == [], f"duplicate (user_id,date) groups: {dups[:5]}"


class TestSanity:
    def test_gdpr_export(self, ch):
        # Endpoint is GET (server code); task description said POST but
        # implementation exposes GET. Try GET first, fall back to POST.
        r = requests.get(f"{API}/gdpr/export", headers=ch, timeout=60)
        if r.status_code == 405:
            r = requests.post(f"{API}/gdpr/export", headers=ch, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        # Should be JSON body
        try:
            j = r.json()
        except Exception:
            pytest.fail(f"gdpr/export did not return JSON: {r.text[:200]}")
        assert isinstance(j, dict), f"expected dict, got {type(j).__name__}"

    def test_beta_status(self, ch):
        r = requests.get(f"{API}/beta/status", headers=ch, timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert isinstance(r.json(), dict)


# ---------------- teardown ----------------

@pytest.fixture(scope="module", autouse=True)
def _module_cleanup(client_token, db, event_loop):
    yield
    uid = client_token["user"]["id"]
    async def _run():
        # Any stragglers left under the seeder roster_id
        await db.workouts.delete_many(
            {"user_id": uid, "roster_id": COLLISION_ROSTER_ID})
    try:
        event_loop.run_until_complete(_run())
    except Exception:
        pass
