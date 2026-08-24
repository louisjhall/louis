"""Iter189u — Clear Month backend contract tests

Focuses on the new `skip_completed: bool` flag on
POST /api/coach/clients/{cid}/workouts/bulk-delete.

Behaviour matrix:
- skip_completed=true  → completed workouts silently excluded, 200
- skip_completed=false → 409 if any completed workout in range
- Roster / Flight Support / Activities collections untouched
"""

import os
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"
CLIENT_ID = "0b0651e2-3453-4c39-b858-b377e8284f8c"  # Alex Rivera


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def coach_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": COACH_EMAIL, "password": COACH_PW}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mongo_db():
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        # Fall back to reading backend .env
        for line in open("/app/backend/.env"):
            k, _, v = line.strip().partition("=")
            v = v.strip().strip('"').strip("'")
            if k == "MONGO_URL" and not mongo_url:
                mongo_url = v
            if k == "DB_NAME" and not db_name:
                db_name = v
    assert mongo_url and db_name, "MONGO_URL / DB_NAME missing"
    return MongoClient(mongo_url)[db_name]


TEST_MONTH_START = "2026-06-01"
TEST_MONTH_END = "2026-06-30"


def _seed_workout(db, date_str: str, completed: bool):
    wid = f"TEST_iter189u_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": wid,
        "user_id": CLIENT_ID,
        "date": date_str,
        "title": "TEST_iter189u seeded",
        "workout_type": "strength",
        "source": "coach_manual",
        "completed": completed,
        "created_at": "2026-06-01T00:00:00Z",
    }
    db.workouts.insert_one(doc)
    return wid


def _cleanup(db):
    db.workouts.delete_many({"user_id": CLIENT_ID, "title": "TEST_iter189u seeded"})


# ---------------- tests ----------------

class TestClearMonthContract:

    def test_1_auth_required(self):
        # Sanity: unauth call rejected
        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{CLIENT_ID}/workouts/bulk-delete",
            json={"start_date": TEST_MONTH_START, "end_date": TEST_MONTH_END,
                  "reason": "test", "confirm": True},
            timeout=30,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_2_skip_completed_true_wipes_pending_only(self, coach_headers, mongo_db):
        _cleanup(mongo_db)
        # Seed 2 pending + 1 completed
        _seed_workout(mongo_db, "2026-06-05", completed=False)
        _seed_workout(mongo_db, "2026-06-12", completed=False)
        completed_id = _seed_workout(mongo_db, "2026-06-20", completed=True)

        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{CLIENT_ID}/workouts/bulk-delete",
            headers=coach_headers,
            json={"start_date": TEST_MONTH_START, "end_date": TEST_MONTH_END,
                  "reason": "iter189u test skip_completed",
                  "confirm": True, "skip_completed": True},
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        # Only the 2 non-completed test rows deleted (existing pending
        # workouts in that window may also be counted; assert >=2)
        assert body.get("deleted_count", 0) >= 2, \
            f"expected >=2 deleted, got {body.get('deleted_count')}"

        # Completed row should still exist
        still = mongo_db.workouts.find_one({"id": completed_id})
        assert still is not None, "completed workout was deleted (should have been preserved)"
        assert still.get("completed") is True

        _cleanup(mongo_db)

    def test_3_default_false_returns_409_when_completed_present(self, coach_headers, mongo_db):
        _cleanup(mongo_db)
        _seed_workout(mongo_db, "2026-06-05", completed=False)
        _seed_workout(mongo_db, "2026-06-20", completed=True)

        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{CLIENT_ID}/workouts/bulk-delete",
            headers=coach_headers,
            json={"start_date": TEST_MONTH_START, "end_date": TEST_MONTH_END,
                  "reason": "iter189u test default_false",
                  "confirm": True},  # skip_completed omitted → default false
            timeout=30,
        )
        assert r.status_code == 409, f"expected 409, got {r.status_code} {r.text}"

        # Both test rows should still exist
        remaining = mongo_db.workouts.count_documents(
            {"user_id": CLIENT_ID, "title": "TEST_iter189u seeded"}
        )
        assert remaining == 2, f"expected 2 remaining, got {remaining}"

        _cleanup(mongo_db)

    def test_4_empty_month_returns_zero(self, coach_headers, mongo_db):
        _cleanup(mongo_db)
        # Use a far-future window highly unlikely to contain workouts
        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{CLIENT_ID}/workouts/bulk-delete",
            headers=coach_headers,
            json={"start_date": "2099-01-01", "end_date": "2099-01-31",
                  "reason": "iter189u empty month",
                  "confirm": True, "skip_completed": True},
            timeout=30,
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("deleted_count") == 0

    def test_5_confirm_required(self, coach_headers):
        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{CLIENT_ID}/workouts/bulk-delete",
            headers=coach_headers,
            json={"start_date": TEST_MONTH_START, "end_date": TEST_MONTH_END,
                  "reason": "test", "skip_completed": True},  # confirm omitted
            timeout=30,
        )
        assert r.status_code == 400

    def test_6_roster_and_flight_support_untouched(self, coach_headers, mongo_db):
        """Snapshot roster & flight_support collections; run clear month;
        assert counts unchanged."""
        _cleanup(mongo_db)
        # Snapshot
        roster_before = mongo_db.roster_days.count_documents({"user_id": CLIENT_ID})
        fs_before = mongo_db.flight_support_overrides.count_documents({"user_id": CLIENT_ID})
        activities_before = mongo_db.activities.count_documents({"user_id": CLIENT_ID})

        _seed_workout(mongo_db, "2026-06-14", completed=False)

        r = requests.post(
            f"{BASE_URL}/api/coach/clients/{CLIENT_ID}/workouts/bulk-delete",
            headers=coach_headers,
            json={"start_date": TEST_MONTH_START, "end_date": TEST_MONTH_END,
                  "reason": "iter189u roster preservation test",
                  "confirm": True, "skip_completed": True},
            timeout=30,
        )
        assert r.status_code == 200

        roster_after = mongo_db.roster_days.count_documents({"user_id": CLIENT_ID})
        fs_after = mongo_db.flight_support_overrides.count_documents({"user_id": CLIENT_ID})
        activities_after = mongo_db.activities.count_documents({"user_id": CLIENT_ID})

        assert roster_after == roster_before, \
            f"roster_days changed! before={roster_before} after={roster_after}"
        assert fs_after == fs_before, \
            f"flight_support_overrides changed! before={fs_before} after={fs_after}"
        assert activities_after == activities_before, \
            f"activities changed! before={activities_before} after={activities_after}"

        _cleanup(mongo_db)
