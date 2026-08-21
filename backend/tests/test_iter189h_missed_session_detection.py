"""
Iter189h — Missed session detection fix.

Bug: /api/recovery/missed AND /api/calendar/range considered a workout
"missed" if workouts.completed==False, even when the client had logged
individual sets in `workout_sets`. Fix: treat a workout as completed if
it has AT LEAST ONE row in workout_sets (matching workout_id + user_id).

Tests exercise:
  1. GET /api/recovery/missed excludes a workout that has ≥1 logged set.
  2. GET /api/recovery/missed still includes a workout with no logged sets.
  3. GET /api/calendar/range badges the logged-but-not-completed workout as
     "completed" (and workout.completed=true in payload).
  4. feature_live_state.compute_live_state treats a logged workout as
     completed (missed_sessions_14d does not count it).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import uuid
import pytest
import requests

# Ensure /app/backend is on path (compute_live_state direct import)
sys.path.insert(0, "/app/backend")

from pymongo import MongoClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


# --------------------------- Mongo fixture (sync via pymongo for CRUD) -----
@pytest.fixture(scope="module")
def mongo_db():
    url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    dbname = os.environ.get("DB_NAME", "crewfit_v1")
    client = MongoClient(url)
    db = client[dbname]
    yield db
    client.close()


def _arun(coro):
    """Run an async coroutine on a fresh event loop (needed for direct
    compute_live_state calls with motor)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --------------------------- Fixture data ---------------------------------
YESTERDAY = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()


def _make_workout(user_id: str, *, completed=False, wid=None, focus="strength_upper", key=False):
    return {
        "id": wid or f"TEST_iter189h_wk_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "date": YESTERDAY,
        "title": "TEST iter189h Upper",
        "focus": focus,
        "session_type": "strength_upper",
        "day_load": "amber",
        "completed": completed,
        "skipped": False,
        "key_session": key,
        "estimated_minutes": 45,
        "created_at": _dt.datetime.utcnow().isoformat(),
    }


def _make_set(user_id: str, workout_id: str):
    return {
        "id": f"TEST_iter189h_set_{uuid.uuid4().hex[:10]}",
        "user_id": user_id,
        "workout_id": workout_id,
        "exercise_id": "bench_press",
        "set_index": 1,
        "reps": 10,
        "weight_kg": 40,
        "rpe": 7,
        "created_at": _dt.datetime.utcnow().isoformat(),
    }


# --------------------------- Cleanup helper -------------------------------
def _cleanup(db, user_id):
    db.workouts.delete_many({"user_id": user_id, "id": {"$regex": "^TEST_iter189h_"}})
    db.workout_sets.delete_many({"user_id": user_id, "id": {"$regex": "^TEST_iter189h_"}})


# --------------------------- Test 1 ---------------------------------------
def test_recovery_missed_excludes_workout_with_logged_sets(api, base_url, client_auth, mongo_db):
    """Iter189h — /api/recovery/missed excludes a workout with ≥1 logged set."""
    user_id = client_auth["user"]["id"]
    w = _make_workout(user_id, completed=False)
    st = _make_set(user_id, w["id"])

    _cleanup(mongo_db, user_id)
    mongo_db.workouts.insert_one(w)
    mongo_db.workout_sets.insert_one(st)
    try:
        r = api.get(f"{base_url}/api/recovery/missed?window=14",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        ids = [m.get("id") for m in data.get("missed", [])]
        assert w["id"] not in ids, (
            f"BUG: workout {w['id']} with logged sets showed up as missed. "
            f"Response: {data}"
        )
    finally:
        _cleanup(mongo_db, user_id)


# --------------------------- Test 2 ---------------------------------------
def test_recovery_missed_includes_workout_without_logged_sets(api, base_url, client_auth, mongo_db):
    """Regression — a workout with NO logged sets should still appear."""
    user_id = client_auth["user"]["id"]
    w = _make_workout(user_id, completed=False)

    _cleanup(mongo_db, user_id)
    mongo_db.workouts.insert_one(w)
    try:
        r = api.get(f"{base_url}/api/recovery/missed?window=14",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        ids = [m.get("id") for m in data.get("missed", [])]
        assert w["id"] in ids, (
            f"Regression: workout {w['id']} without logged sets was NOT flagged missed. "
            f"Response: {data}"
        )
    finally:
        _cleanup(mongo_db, user_id)


# --------------------------- Test 3 ---------------------------------------
def test_calendar_range_badges_logged_workout_as_completed(api, base_url, client_auth, mongo_db):
    """/api/calendar/range badge='completed' when workout has ≥1 logged set."""
    user_id = client_auth["user"]["id"]
    w = _make_workout(user_id, completed=False)
    st = _make_set(user_id, w["id"])

    _cleanup(mongo_db, user_id)
    mongo_db.workouts.insert_one(w)
    mongo_db.workout_sets.insert_one(st)
    try:
        today = _dt.date.today().isoformat()
        two_days_ago = (_dt.date.today() - _dt.timedelta(days=2)).isoformat()
        r = api.get(
            f"{base_url}/api/calendar/range?from={two_days_ago}&to={today}",
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        day_card = next((d for d in data.get("days", []) if d.get("date") == YESTERDAY), None)
        assert day_card is not None, f"No day card for {YESTERDAY}. Days: {[d.get('date') for d in data.get('days', [])]}"
        assert day_card.get("badge") == "completed", (
            f"BUG: badge={day_card.get('badge')}, expected 'completed'. Card: {day_card}"
        )
        wk = day_card.get("workout") or {}
        assert wk.get("completed") is True, (
            f"BUG: workout.completed={wk.get('completed')}, expected True. Card: {day_card}"
        )
    finally:
        _cleanup(mongo_db, user_id)


# --------------------------- Test 4 (unit) --------------------------------
def test_compute_live_state_counts_logged_workout_as_completed(mongo_db):
    """feature_live_state.compute_live_state treats logged workout as completed.

    Uses a synthetic user_id so we bypass the (user_id, date) unique index
    conflict against pre-seeded real-client workouts.
    """
    from feature_live_state import compute_live_state

    user_id = f"TEST_iter189h_user_{uuid.uuid4().hex[:10]}"
    w = _make_workout(user_id, completed=False)
    st = _make_set(user_id, w["id"])
    w2 = _make_workout(user_id, completed=False)
    w2["id"] = f"TEST_iter189h_wk_ctrl_{uuid.uuid4().hex[:10]}"
    w2["date"] = (_dt.date.today() - _dt.timedelta(days=2)).isoformat()

    _cleanup(mongo_db, user_id)
    mongo_db.workouts.insert_one(w)
    mongo_db.workout_sets.insert_one(st)
    mongo_db.workouts.insert_one(w2)

    async def run():
        url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        dbname = os.environ.get("DB_NAME", "crewfit_v1")
        mclient = AsyncIOMotorClient(url)
        try:
            mdb = mclient[dbname]
            return await compute_live_state(mdb, user_id, days=14)
        finally:
            mclient.close()

    try:
        state = _arun(run())
        planned_past = state.get("planned_sessions_14d", 0)
        completed_past = state.get("completed_sessions_14d", 0)
        missed_14d = state.get("missed_sessions_14d", 0)

        assert planned_past >= 2, f"planned_sessions_14d={planned_past} (<2). state={state}"
        assert completed_past >= 1, f"completed_sessions_14d={completed_past} (<1). state={state}"
        assert missed_14d < planned_past, (
            f"missed_sessions_14d={missed_14d} vs planned={planned_past}. State={state}"
        )
    finally:
        _cleanup(mongo_db, user_id)
