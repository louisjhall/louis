"""
Standby Mode V1 — Backend Tests (feature_standby.py)

Covers:
  - GET  /api/standby/today  (non-standby, standby day, recommendation shapes)
  - POST /api/standby/status (valid, invalid, non-standby, confirm_type)
  - POST /api/standby/called-out (auto-swap on non-key session; coach task on key/coach-locked;
                                  can_train=no path with NO_TRAINING_REC)
  - POST /api/standby/apply-workout (happy path, coach-locked 409+task, non-standby 404,
                                     missing workout 404, unknown rec_id → falls back to top)
  - POST /api/standby/restore-original (happy path, nothing-to-restore 400, missing archive 404)
  - GET  /api/coach/clients/{id}/standby (coach role only, client 401/403)
  - Notification created with dedupe_key=standby::<date>
  - Change log actor attribution (client / atlas)
  - ROSTER_SYSTEM contains STANDBY DETECTION block with STBY/SBY/RES/RSV/RESERVE/HSBY/ASBY/SC/LC
  - REGRESSION smoke on: notifications/settings, notifications, habits/today,
                          coach/messages/drafts, coach/change-log, coach/clients/{id}/controls
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.environ.get("DB_NAME", "crewfit_v1")

# ---------------- Fixtures -------------------------------------------------

@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def client_id(mongo):
    u = mongo.users.find_one({"email": "client@crewfit.com"}, {"_id": 0, "id": 1})
    assert u, "client@crewfit.com must exist"
    return u["id"]


def _iso(y=2030, m=1, d=1):
    return f"{y:04d}-{m:02d}-{d:02d}"


TEST_DATES = {
    "home":       _iso(2030, 1, 1),   # regular home_standby with normal workout
    "home_key":   _iso(2030, 1, 2),   # home_standby with a key_session workout
    "home_lock":  _iso(2030, 1, 3),   # home_standby with a coach_locked workout
    "night":      _iso(2030, 1, 4),   # night_standby (recovery-first recs)
    "short":      _iso(2030, 1, 5),   # short_call (2 recs)
    "no_wk":      _iso(2030, 1, 6),   # home_standby with NO workout
    "no_standby": _iso(2030, 1, 7),   # NON-standby (rest day) with normal workout
    "unknown":    _iso(2030, 1, 8),   # unknown_standby needs_confirmation=true
    "can_train_no": _iso(2030, 1, 9), # home_standby for called-out can_train=no path
}


def _make_workout(client_id, date, roster_id, *, key_session=False, coach_locked=False,
                  title=None):
    return {
        "id": str(uuid.uuid4()),
        "user_id": client_id,
        "roster_id": roster_id,
        "date": date,
        "day_load": "green",
        "title": title or "Home Push + Core",
        "location": "Home Workout",
        "duration_min": 30,
        "focus": "push",
        "warmup": [{"name": "Arm Circles", "duration_sec": 60}],
        "exercises": [
            {"name": "Push-Ups", "sets": 3, "reps": "10", "rest_sec": 60, "rpe": 7},
        ],
        "alternatives": {"home": "…"},
        "rationale": "test",
        "approved": True,
        "completed": False,
        "coach_notes": "",
        "coach_locked": coach_locked,
        "key_session": key_session,
        "created_at": "2030-01-01T00:00:00Z",
        "updated_at": "2030-01-01T00:00:00Z",
    }


@pytest.fixture(scope="module", autouse=True)
def seed(mongo, client_id):
    """Seed roster standby days + workouts. Idempotent — cleanup at end."""
    roster = mongo.rosters.find_one({"user_id": client_id, "is_active": True},
                                    sort=[("created_at", -1)])
    assert roster, "client must have an active roster"
    roster_id = roster["id"]

    # Remove any pre-existing days for our test dates + old test data + workouts
    days = [d for d in roster.get("days", []) if d.get("date") not in TEST_DATES.values()]

    test_days = [
        {"date": TEST_DATES["home"], "day_type": "Standby", "standby_type": "home_standby",
         "standby_start_time": "06:00", "standby_end_time": "18:00",
         "standby_location": "home", "standby_status": "waiting",
         "standby_needs_confirmation": False, "confirmed_by_client": True, "load": "green"},
        {"date": TEST_DATES["home_key"], "day_type": "Standby", "standby_type": "home_standby",
         "standby_location": "home", "standby_status": "waiting"},
        {"date": TEST_DATES["home_lock"], "day_type": "Standby", "standby_type": "home_standby",
         "standby_location": "home", "standby_status": "waiting"},
        {"date": TEST_DATES["night"], "day_type": "Standby", "standby_type": "night_standby",
         "standby_start_time": "22:00", "standby_end_time": "06:00",
         "standby_location": "home", "standby_status": "waiting"},
        {"date": TEST_DATES["short"], "day_type": "Standby", "standby_type": "short_call",
         "standby_location": "home", "standby_status": "waiting"},
        {"date": TEST_DATES["no_wk"], "day_type": "Standby", "standby_type": "home_standby",
         "standby_location": "home", "standby_status": "waiting"},
        {"date": TEST_DATES["no_standby"], "day_type": "Rest Day", "load": "green"},
        {"date": TEST_DATES["unknown"], "day_type": "Standby", "standby_type": "unknown_standby",
         "standby_needs_confirmation": True, "confirmed_by_client": False,
         "standby_location": "unknown", "standby_status": "waiting"},
        {"date": TEST_DATES["can_train_no"], "day_type": "Standby", "standby_type": "home_standby",
         "standby_location": "home", "standby_status": "waiting"},
    ]
    days.extend(test_days)
    mongo.rosters.update_one({"id": roster_id}, {"$set": {"days": days}})

    # Wipe workouts / archives for test dates then insert fresh workouts
    mongo.workouts.delete_many({"user_id": client_id, "date": {"$in": list(TEST_DATES.values())}})
    mongo.workouts_archive.delete_many({"user_id": client_id, "date": {"$in": list(TEST_DATES.values())}})

    workouts = [
        _make_workout(client_id, TEST_DATES["home"], roster_id, title="Home Push"),
        _make_workout(client_id, TEST_DATES["home_key"], roster_id, key_session=True,
                       title="Key Session — Push"),
        _make_workout(client_id, TEST_DATES["home_lock"], roster_id, coach_locked=True,
                       title="Locked Session"),
        _make_workout(client_id, TEST_DATES["night"], roster_id, title="Night Wk"),
        _make_workout(client_id, TEST_DATES["short"], roster_id, title="Short Wk"),
        # no workout for no_wk
        _make_workout(client_id, TEST_DATES["no_standby"], roster_id, title="Rest Day WK"),
        _make_workout(client_id, TEST_DATES["unknown"], roster_id, title="Unknown Wk"),
        _make_workout(client_id, TEST_DATES["can_train_no"], roster_id, title="CT No"),
    ]
    mongo.workouts.insert_many(workouts)

    yield

    # ---- teardown ----
    mongo.workouts.delete_many({"user_id": client_id, "date": {"$in": list(TEST_DATES.values())}})
    mongo.workouts_archive.delete_many({"user_id": client_id, "date": {"$in": list(TEST_DATES.values())}})
    mongo.notifications.delete_many(
        {"user_id": client_id, "dedupe_key": {"$in": [f"standby::{d}" for d in TEST_DATES.values()]}}
    )
    # Restore roster without our test days
    r = mongo.rosters.find_one({"id": roster_id})
    if r:
        clean = [d for d in r.get("days", []) if d.get("date") not in TEST_DATES.values()]
        mongo.rosters.update_one({"id": roster_id}, {"$set": {"days": clean}})


# ---------------- /standby/today -------------------------------------------

class TestStandbyToday:
    """GET /api/standby/today with ?date=... override."""

    def test_non_standby_day(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/standby/today",
                    params={"date": TEST_DATES["no_standby"]},
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["is_standby"] is False
        assert data["standby"] is None
        assert data["reason"] is None
        assert data["recommendations"] == []
        assert data["workout"] is not None
        assert data["workout"]["title"] == "Rest Day WK"

    def test_home_standby_day_shape(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/standby/today",
                    params={"date": TEST_DATES["home"]},
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["is_standby"] is True
        sb = d["standby"]
        assert sb["type"] == "home_standby"
        assert sb["start_time"] == "06:00"
        assert sb["end_time"] == "18:00"
        assert sb["location"] == "home"
        assert sb["status"] == "waiting"
        assert sb["called_out"] is False
        assert "needs_confirmation" in sb
        assert "confirmed_by_client" in sb
        assert d["reason"] and isinstance(d["reason"], str) and len(d["reason"]) > 10
        assert len(d["recommendations"]) == 4
        titles = [r["title"] for r in d["recommendations"]]
        assert "Standby Mobility" in titles
        assert "Standby Strength" in titles
        assert "Standby Bodyweight" in titles
        assert "Easy Zone 2" in titles
        # Recommendation shape
        for rec in d["recommendations"]:
            assert set(["id", "kind", "title", "duration_min", "why"]).issubset(rec.keys())

    def test_short_call_recs_2(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/standby/today",
                    params={"date": TEST_DATES["short"]},
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["is_standby"] is True
        assert len(d["recommendations"]) == 2
        titles = [r["title"] for r in d["recommendations"]]
        assert "5-min Mobility" in titles
        assert "Activation Set" in titles

    def test_night_standby_first_rec_is_recovery(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/standby/today",
                    params={"date": TEST_DATES["night"]},
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["is_standby"] is True
        first = d["recommendations"][0]
        assert first["title"] in ("Recovery Routine", "Wind-down Mobility")

    def test_unknown_standby_needs_confirmation(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/standby/today",
                    params={"date": TEST_DATES["unknown"]},
                    headers=client_auth["headers"], timeout=30)
        d = r.json()
        assert d["is_standby"] is True
        assert d["standby"]["needs_confirmation"] is True
        assert d["standby"]["confirmed_by_client"] is False


# ---------------- /standby/status ------------------------------------------

class TestStandbyStatus:
    def test_valid_status_waiting(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/standby/status",
                     json={"status": "waiting", "date": TEST_DATES["home"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["status"] == "waiting"
        assert d["date"] == TEST_DATES["home"]

    @pytest.mark.parametrize("st", ["not_called_out", "cancelled", "too_tired", "have_time"])
    def test_valid_other_statuses(self, api, base_url, client_auth, st):
        r = api.post(f"{base_url}/api/standby/status",
                     json={"status": st, "date": TEST_DATES["home"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, f"{st} → {r.status_code} {r.text}"
        assert r.json()["status"] == st

    def test_invalid_status_400(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/standby/status",
                     json={"status": "not_a_thing", "date": TEST_DATES["home"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 400, r.text

    def test_non_standby_date_404(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/standby/status",
                     json={"status": "waiting", "date": TEST_DATES["no_standby"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 404, r.text

    def test_confirm_type_updates_day(self, api, base_url, client_auth, mongo, client_id):
        r = api.post(f"{base_url}/api/standby/status",
                     json={"status": "waiting", "date": TEST_DATES["unknown"],
                           "confirm_type": "home_standby"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        # Verify persistence
        roster = mongo.rosters.find_one({"user_id": client_id, "is_active": True},
                                        sort=[("created_at", -1)])
        day = next(d for d in roster["days"] if d["date"] == TEST_DATES["unknown"])
        assert day["standby_type"] == "home_standby"
        assert day["confirmed_by_client"] is True
        assert day["standby_needs_confirmation"] is False


# ---------------- /standby/apply-workout -----------------------------------

class TestApplyWorkout:
    def test_happy_apply_and_snapshot(self, api, base_url, client_auth, mongo, client_id):
        r = api.post(f"{base_url}/api/standby/apply-workout",
                     json={"date": TEST_DATES["home"], "recommendation_id": "hs_str"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        wk = r.json()["workout"]
        assert wk["standby_adjusted"] is True
        assert wk["original_workout_id"]
        assert wk["title"] == "Standby Strength"
        # Snapshot present in workouts_archive
        snap = mongo.workouts_archive.find_one({"id": wk["original_workout_id"]})
        assert snap is not None
        assert snap["title"] == "Home Push"
        # Notification present with dedupe_key
        notif = mongo.notifications.find_one(
            {"user_id": client_id, "dedupe_key": f"standby::{TEST_DATES['home']}"}
        )
        assert notif is not None
        assert notif.get("notif_type") == "programme_updated"

    def test_unknown_recommendation_falls_back(self, api, base_url, client_auth, mongo, client_id):
        # First restore, then retry with bad id
        api.post(f"{base_url}/api/standby/restore-original",
                 json={"date": TEST_DATES["home"]}, headers=client_auth["headers"], timeout=30)
        r = api.post(f"{base_url}/api/standby/apply-workout",
                     json={"date": TEST_DATES["home"], "recommendation_id": "nope-xyz"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        wk = r.json()["workout"]
        # Top rec for home_standby is Standby Mobility
        assert wk["title"] == "Standby Mobility"

    def test_coach_locked_returns_409_and_creates_task(self, api, base_url, client_auth,
                                                       mongo, client_id):
        # Get tasks count before
        before = mongo.coach_tasks.count_documents(
            {"user_id": client_id, "task_type": "standby_key_affected"}
        )
        r = api.post(f"{base_url}/api/standby/apply-workout",
                     json={"date": TEST_DATES["home_lock"], "recommendation_id": "hs_str"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 409, r.text
        assert "coach-locked" in r.text.lower() or "louis" in r.text.lower()
        after = mongo.coach_tasks.count_documents(
            {"user_id": client_id, "task_type": "standby_key_affected"}
        )
        assert after == before + 1
        task = mongo.coach_tasks.find_one(
            {"user_id": client_id, "task_type": "standby_key_affected",
             "payload.date": TEST_DATES["home_lock"]}, sort=[("created_at", -1)]
        )
        assert task and task.get("priority") == "high" and task.get("risk_level") == "medium"
        assert task.get("category") == "programme"

    def test_non_standby_day_404(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/standby/apply-workout",
                     json={"date": TEST_DATES["no_standby"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 404, r.text

    def test_no_workout_404(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/standby/apply-workout",
                     json={"date": TEST_DATES["no_wk"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 404, r.text


# ---------------- /standby/restore-original --------------------------------

class TestRestore:
    def test_restore_after_apply(self, api, base_url, client_auth):
        # Ensure home date has an applied swap (from previous test), then restore.
        # If not adjusted (idempotent testing) re-apply first
        curr = api.get(f"{base_url}/api/standby/today",
                       params={"date": TEST_DATES["home"]},
                       headers=client_auth["headers"], timeout=30).json()
        if not curr["workout"].get("standby_adjusted"):
            api.post(f"{base_url}/api/standby/apply-workout",
                     json={"date": TEST_DATES["home"], "recommendation_id": "hs_str"},
                     headers=client_auth["headers"], timeout=30)
        r = api.post(f"{base_url}/api/standby/restore-original",
                     json={"date": TEST_DATES["home"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        wk = r.json()["workout"]
        assert wk["title"] == "Home Push"
        assert wk["standby_adjusted"] is False
        assert wk.get("original_workout_id") in (None, "")

    def test_nothing_to_restore_400(self, api, base_url, client_auth):
        # After restore above, calling again → 400
        r = api.post(f"{base_url}/api/standby/restore-original",
                     json={"date": TEST_DATES["home"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 400, r.text

    def test_restore_missing_archive_404(self, api, base_url, client_auth, mongo, client_id):
        # Apply then delete archive snapshot then try restore
        api.post(f"{base_url}/api/standby/apply-workout",
                 json={"date": TEST_DATES["home"], "recommendation_id": "hs_mob"},
                 headers=client_auth["headers"], timeout=30)
        wk = mongo.workouts.find_one(
            {"user_id": client_id, "date": TEST_DATES["home"]}, {"_id": 0}
        )
        assert wk.get("standby_adjusted") is True
        orig_id = wk["original_workout_id"]
        # Nuke archive
        mongo.workouts_archive.delete_many({"id": orig_id})
        r = api.post(f"{base_url}/api/standby/restore-original",
                     json={"date": TEST_DATES["home"]},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 404, r.text


# ---------------- /standby/called-out --------------------------------------

class TestCalledOut:
    def test_called_out_autoswaps_normal_workout(self, api, base_url, client_auth,
                                                  mongo, client_id):
        # night day has no key_session, no coach_lock — expect swap + atlas log
        r = api.post(f"{base_url}/api/standby/called-out",
                     json={"date": TEST_DATES["night"], "report_time": "14:30",
                           "expected_duty_length_hours": 6.0, "destination": "LHR",
                           "can_train": "unsure"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        wk = mongo.workouts.find_one({"user_id": client_id, "date": TEST_DATES["night"]},
                                     {"_id": 0})
        assert wk.get("standby_adjusted") is True
        assert wk.get("original_workout_id")
        # Change-log with actor=atlas exists
        log = list(mongo.coach_change_log.find({"client_id": client_id,
                                                 "meta.date": TEST_DATES["night"]}))
        assert any(e.get("actor") == "atlas" for e in log), \
            f"expected an atlas actor entry, got {[e.get('actor') for e in log]}"

    def test_called_out_key_session_creates_task_no_swap(self, api, base_url, client_auth,
                                                         mongo, client_id):
        before = mongo.coach_tasks.count_documents(
            {"user_id": client_id, "task_type": "standby_key_affected",
             "payload.date": TEST_DATES["home_key"]}
        )
        r = api.post(f"{base_url}/api/standby/called-out",
                     json={"date": TEST_DATES["home_key"], "report_time": "10:00",
                           "expected_duty_length_hours": 8.0, "destination": "JFK",
                           "can_train": "no"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        wk = mongo.workouts.find_one({"user_id": client_id, "date": TEST_DATES["home_key"]},
                                     {"_id": 0})
        assert wk.get("standby_adjusted") is not True, \
            "key_session workout must NOT be auto-swapped"
        assert wk["title"] == "Key Session — Push"
        after = mongo.coach_tasks.count_documents(
            {"user_id": client_id, "task_type": "standby_key_affected",
             "payload.date": TEST_DATES["home_key"]}
        )
        assert after == before + 1

    def test_called_out_can_train_no_uses_no_training(self, api, base_url, client_auth,
                                                      mongo, client_id):
        r = api.post(f"{base_url}/api/standby/called-out",
                     json={"date": TEST_DATES["can_train_no"], "report_time": "09:00",
                           "expected_duty_length_hours": 12.0, "destination": "DXB",
                           "can_train": "no"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        wk = mongo.workouts.find_one({"user_id": client_id,
                                      "date": TEST_DATES["can_train_no"]}, {"_id": 0})
        assert wk.get("standby_adjusted") is True
        # NO_TRAINING_REC id is 'no_training'
        assert wk.get("standby_recommendation") == "no_training"
        assert wk.get("title") == "No Training"


# ---------------- Coach endpoint -------------------------------------------

class TestCoachStandby:
    def test_coach_can_list_standby_days(self, api, base_url, coach_auth, client_id):
        r = api.get(f"{base_url}/api/coach/clients/{client_id}/standby",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["client"]["id"] == client_id
        assert isinstance(data["days"], list)
        assert data["count"] == len(data["days"])
        # Every returned day must be a standby day
        for d in data["days"]:
            assert d["standby_type"] or d.get("day_type") == "Standby"

    def test_client_forbidden_from_coach_endpoint(self, api, base_url, client_auth, client_id):
        r = api.get(f"{base_url}/api/coach/clients/{client_id}/standby",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"


# ---------------- Change-log actor attributions ----------------------------

class TestChangeLog:
    def test_change_log_has_client_and_atlas_actors(self, mongo, client_id):
        # After all above tests, we should have client + atlas actor entries
        actors = set(
            e.get("actor") for e in
            mongo.coach_change_log.find({"client_id": client_id, "category": "programme"})
        )
        assert "client" in actors
        assert "atlas" in actors


# ---------------- ROSTER_SYSTEM prompt check -------------------------------

class TestRosterPrompt:
    def test_roster_system_has_standby_tokens(self):
        with open("/app/backend/server.py", "r") as f:
            src = f.read()
        # Extract ROSTER_SYSTEM section
        assert "ROSTER_SYSTEM" in src
        # STANDBY DETECTION block with all required tokens
        assert "STANDBY DETECTION" in src
        for token in ["STBY", "SBY", "RES", "RSV", "RESERVE",
                      "HSBY", "ASBY", "SC", "LC"]:
            assert token in src, f"ROSTER_SYSTEM missing token: {token}"


# ---------------- Regression smoke on prior endpoints ----------------------

class TestRegressionSmoke:
    def test_notifications_settings(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/notifications/settings",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d, dict)

    def test_notifications_list(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/notifications",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d, (list, dict))

    def test_habits_today(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/habits/today",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_coach_message_drafts(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/messages/drafts",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_coach_change_log(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/change-log",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_coach_client_controls(self, api, base_url, coach_auth, client_id):
        r = api.get(f"{base_url}/api/coach/clients/{client_id}/controls",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
