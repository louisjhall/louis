"""Iteration 14 follow-up verification.

Checks the two HIGH-priority fixes flagged in iteration_13:

1. `db.workouts` has been de-duplicated: no (user_id, date) group has >1 row.
2. A UNIQUE compound index `uniq_user_date` exists on `db.workouts`.
3. POST /api/calendar/day-override now flips the workout status on a real
   client date and there is exactly ONE workout row for (user_id, date)
   after the flip (formerly xfail).
4. Inserting a second workout with the same (user_id, date) raises a
   MongoDB DuplicateKeyError at write time.
5. Regression: /api/roster/upload-and-generate, /api/workouts/regenerate,
   /api/calendar/timeline, /api/coach/analytics still return
   200/expected status codes.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import date, timedelta

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://flight-fit-plans.preview.emergentagent.com"
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"
COACH_EMAIL = "coach@crewfit.com"
COACH_PW = "Coach123!"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PW}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(f"{API}/auth/login", json={"email": COACH_EMAIL, "password": COACH_PW}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def ch(client_token):
    return {"Authorization": f"Bearer {client_token}", "Content-Type": "application/json"}


@pytest.fixture
def coh(coach_token):
    return {"Authorization": f"Bearer {coach_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db(event_loop):
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


# ---------- Data-integrity checks ----------

class TestDedupAndIndex:
    def test_no_duplicate_user_date_groups(self, db, event_loop):
        async def _run():
            pipeline = [
                {"$group": {"_id": {"u": "$user_id", "d": "$date"}, "c": {"$sum": 1}}},
                {"$match": {"c": {"$gt": 1}}},
            ]
            return await db.workouts.aggregate(pipeline).to_list(length=1000)

        dups = event_loop.run_until_complete(_run())
        assert dups == [], f"expected zero duplicate (user_id,date) groups, got {len(dups)}: sample={dups[:3]}"

    def test_unique_compound_index_present(self, db, event_loop):
        async def _run():
            return await db.workouts.index_information()

        info = event_loop.run_until_complete(_run())
        assert "uniq_user_date" in info, f"missing unique index; got={list(info)}"
        idx = info["uniq_user_date"]
        assert idx.get("unique") is True, f"index exists but is NOT unique: {idx}"
        assert idx["key"] == [("user_id", 1), ("date", 1)], f"unexpected keys: {idx['key']}"

    def test_duplicate_insert_raises_dup_key_error(self, db, event_loop):
        """Insert a synthetic workout row, then try to insert a second row
        with the same (user_id, date). The unique index must reject it."""
        marker_user = f"TEST_dup_{uuid.uuid4().hex[:8]}"
        marker_date = "2099-01-01"
        doc = {
            "id": f"TEST_wk_{uuid.uuid4().hex[:8]}",
            "user_id": marker_user,
            "date": marker_date,
            "title": "TEST synthetic",
            "status": None,
        }
        dup = {**doc, "id": f"TEST_wk_{uuid.uuid4().hex[:8]}"}

        async def _run():
            await db.workouts.insert_one(doc)
            raised = False
            try:
                await db.workouts.insert_one(dup)
            except DuplicateKeyError:
                raised = True
            # cleanup
            await db.workouts.delete_many({"user_id": marker_user})
            return raised

        raised = event_loop.run_until_complete(_run())
        assert raised, "expected DuplicateKeyError on second insert with same (user_id, date)"


# ---------- Day-override status flip (formerly xfail) ----------

def _pick_upcoming_workout(headers):
    r = requests.get(f"{API}/calendar/timeline?months_back=0&months_ahead=3", headers=headers, timeout=20)
    if r.status_code != 200:
        return None
    for m in r.json().get("months", []):
        for d in m.get("days", []):
            wid = d.get("workout_id")
            if not wid:
                continue
            w = requests.get(f"{API}/workouts/{wid}", headers=headers, timeout=15)
            if w.status_code != 200:
                continue
            wj = w.json()
            if not wj.get("coach_locked") and not wj.get("completed"):
                return wj
    return None


class TestDayOverrideStatusFlipDeterministic:
    def test_neutral_override_flips_status_to_updating_exactly_one_row(self, ch, db, event_loop):
        wk = _pick_upcoming_workout(ch)
        if not wk:
            pytest.skip("No unlocked workout available")
        d = wk["date"]
        r = requests.post(
            f"{API}/calendar/day-override",
            json={"date": d, "tags": ["poor_sleep"], "training_preference": "reduce"},
            headers=ch,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json()["coach_locked"] is False

        async def _count_and_status():
            rows = await db.workouts.find({"user_id": wk["user_id"], "date": d}, {"_id": 0}).to_list(length=10)
            return rows

        rows = event_loop.run_until_complete(_count_and_status())
        assert len(rows) == 1, f"expected exactly ONE workout row for (user,date)={d}, got {len(rows)}"
        assert rows[0].get("status") == "updating", f"row status={rows[0].get('status')}"

        # timeline surfaces the same row now (no ambiguity possible)
        w2 = requests.get(f"{API}/workouts/{wk['id']}", headers=ch, timeout=10).json()
        assert w2.get("status") == "updating", f"timeline workout id status={w2.get('status')}"

        # cleanup: clear override and reset status
        requests.delete(f"{API}/calendar/day-override?date={d}", headers=ch, timeout=10)

    def test_sick_tag_flips_status_to_coach_reviewing(self, ch, db, event_loop):
        wk = _pick_upcoming_workout(ch)
        if not wk:
            pytest.skip("No unlocked workout available")
        d = wk["date"]
        r = requests.post(
            f"{API}/calendar/day-override",
            json={"date": d, "tags": ["sick"]},
            headers=ch,
            timeout=15,
        )
        assert r.status_code == 200

        async def _rows():
            return await db.workouts.find({"user_id": wk["user_id"], "date": d}, {"_id": 0}).to_list(length=10)

        rows = event_loop.run_until_complete(_rows())
        assert len(rows) == 1, f"expected ONE workout row on {d}, got {len(rows)}"
        assert rows[0].get("status") == "coach_reviewing", f"status={rows[0].get('status')}"

        requests.delete(f"{API}/calendar/day-override?date={d}", headers=ch, timeout=10)


# ---------- Regression on prior endpoints ----------

class TestRegression:
    def test_calendar_timeline_ok(self, ch):
        r = requests.get(f"{API}/calendar/timeline?months_back=1&months_ahead=2", headers=ch, timeout=20)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "months" in j and isinstance(j["months"], list) and len(j["months"]) >= 1
        # Each month should have days array and at least one day with load info
        m0 = j["months"][0]
        assert "days" in m0
        # Check some day has a load value
        has_load = any((d.get("load") is not None) for m in j["months"] for d in m.get("days", []))
        assert has_load, "expected at least one day with a load value"

    def test_coach_analytics_ok(self, coh):
        r = requests.get(f"{API}/coach/analytics", headers=coh, timeout=20)
        assert r.status_code == 200, r.text
        # response should be a dict with some keys
        assert isinstance(r.json(), dict)

    def test_roster_upload_and_generate_reachable(self, ch):
        # Empty payload -> 4xx not 5xx
        r = requests.post(f"{API}/roster/upload-and-generate", json={}, headers=ch, timeout=25)
        assert r.status_code in (200, 400, 422), f"unexpected status {r.status_code}: {r.text[:200]}"

    def test_workouts_regenerate_returns_job(self, ch):
        rc = requests.get(f"{API}/roster/current", headers=ch, timeout=20)
        if rc.status_code != 200 or not rc.json():
            pytest.skip("no active roster")
        rid = rc.json().get("id")
        r = requests.post(f"{API}/workouts/regenerate", json={"roster_id": rid, "scope": "week"}, headers=ch, timeout=30)
        assert r.status_code in (200, 202, 400), r.text

    def test_no_new_duplicates_after_regenerate(self, db, event_loop):
        """After the regenerate test above (if it ran), the unique index must
        still hold — no duplicate rows should have been produced."""

        async def _run():
            pipeline = [
                {"$group": {"_id": {"u": "$user_id", "d": "$date"}, "c": {"$sum": 1}}},
                {"$match": {"c": {"$gt": 1}}},
            ]
            return await db.workouts.aggregate(pipeline).to_list(length=1000)

        dups = event_loop.run_until_complete(_run())
        assert dups == [], f"regenerate produced duplicates: {dups[:3]}"
