"""
Iter81 Phase 3 — Integration test verifying that a progression snapshot is only
created when the LAST planned workout of the ISO week is completed.

Flow:
  1. Login as client.
  2. Ensure the client has no progression snapshot for the target ISO week
     (we drop any existing snapshot for the fresh week we'll build).
  3. Insert 3 planned workouts on a fresh future ISO week (Mon/Wed/Fri).
  4. Complete the Mon workout via POST /api/workouts/{wid}/complete
     → assert NO snapshot yet (still 2 planned remaining).
  5. Complete the Wed workout → still NO snapshot (1 remaining).
  6. Complete the Fri (final) workout → snapshot IS created with matching week_key.

Uses direct MongoDB writes for seed workouts (mirrors iteration_82 pattern).
"""
import os
import sys
import datetime as _dt
import uuid
import pytest
import requests
import pymongo

sys.path.insert(0, "/app/backend")
from feature_progression import iso_week_bounds, week_key  # noqa: E402


MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")


def _future_iso_week_monday():
    """Return a Monday date in a far-future ISO week that no real workouts touch."""
    # 2027-08-02 is a Monday and is far past current fixtures used elsewhere
    return _dt.date(2027, 8, 2)


@pytest.fixture(scope="module")
def mdb():
    assert MONGO_URL and DB_NAME, "MONGO_URL / DB_NAME env vars required"
    client = pymongo.MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def seeded_week(mdb, client_auth):
    """Seed 3 planned workouts for a fresh future ISO week. Cleanup after."""
    uid = client_auth["user"]["id"]
    monday = _future_iso_week_monday()
    wk = week_key(monday)
    mon_str, sun_str = iso_week_bounds(monday)
    mon_str, sun_str = mon_str.isoformat(), sun_str.isoformat()

    # Cleanup any existing snapshot/workouts for this week
    mdb.progression_snapshots.delete_many({"user_id": uid, "week_key": wk})
    mdb.workouts.delete_many(
        {"user_id": uid, "date": {"$gte": mon_str, "$lte": sun_str}}
    )

    wkts = []
    for offset, tag in [(0, "Mon"), (2, "Wed"), (4, "Fri")]:
        d = monday + _dt.timedelta(days=offset)
        w = {
            "id": f"TEST_p3_{uuid.uuid4().hex[:8]}",
            "user_id": uid,
            "date": d.isoformat(),
            "title": f"TEST Phase3 {tag}",
            "exercises": [
                {"name": "Push-up", "sets": 3, "reps": 10}
            ],
            "warmup": [],
            "completed": False,
            "created_at": _dt.datetime.utcnow().isoformat() + "Z",
        }
        mdb.workouts.insert_one(w)
        # strip Mongo _id in the returned struct so tests can compare cleanly
        w.pop("_id", None)
        wkts.append(w)

    yield {"week_key": wk, "monday": monday, "workouts": wkts}

    # Teardown
    mdb.workouts.delete_many({"user_id": uid, "id": {"$in": [w["id"] for w in wkts]}})
    mdb.progression_snapshots.delete_many({"user_id": uid, "week_key": wk})


def _complete(api, base_url, headers, wid, rpe=7):
    r = api.post(
        f"{base_url}/api/workouts/{wid}/complete",
        headers=headers,
        json={
            "completed_exercises": [{"name": "Push-up", "sets": 3, "reps": 10}],
            "rpe": rpe,
            "notes": "TEST_phase3",
        },
        timeout=30,
    )
    assert r.status_code == 200, f"complete failed: {r.status_code} {r.text[:200]}"
    return r.json()


class TestPhase3SnapshotTrigger:
    def test_no_snapshot_after_first_of_three(
        self, api, base_url, client_auth, mdb, seeded_week
    ):
        uid = client_auth["user"]["id"]
        wk = seeded_week["week_key"]
        # Complete Monday workout
        _complete(api, base_url, client_auth["headers"], seeded_week["workouts"][0]["id"])
        snap = mdb.progression_snapshots.find_one({"user_id": uid, "week_key": wk})
        assert snap is None, f"Snapshot should NOT exist after 1/3 completions, got: {snap}"

    def test_no_snapshot_after_second_of_three(
        self, api, base_url, client_auth, mdb, seeded_week
    ):
        uid = client_auth["user"]["id"]
        wk = seeded_week["week_key"]
        _complete(api, base_url, client_auth["headers"], seeded_week["workouts"][1]["id"])
        snap = mdb.progression_snapshots.find_one({"user_id": uid, "week_key": wk})
        assert snap is None, f"Snapshot should NOT exist after 2/3 completions, got: {snap}"

    def test_snapshot_created_after_final_completion(
        self, api, base_url, client_auth, mdb, seeded_week
    ):
        uid = client_auth["user"]["id"]
        wk = seeded_week["week_key"]
        resp = _complete(api, base_url, client_auth["headers"], seeded_week["workouts"][2]["id"])
        snap = mdb.progression_snapshots.find_one(
            {"user_id": uid, "week_key": wk}, {"_id": 0}
        )
        assert snap is not None, "Snapshot MUST exist after completing final planned session"
        assert snap["week_key"] == wk
        assert snap["metrics"]["sessions_planned"] == 3
        assert snap["metrics"]["sessions_completed"] == 3
        assert snap["metrics"]["adherence_pct"] == 100.0
        assert snap["status"] in ("progressing_well", "maintain", "reduce_load", "deload")
        # Response body should include _progression_snapshot marker
        assert resp.get("_progression_snapshot") is not None, \
            "workout/complete response should include _progression_snapshot when trigger fires"
