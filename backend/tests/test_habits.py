"""Goal-Based Habit Tracking backend regression tests.

Covers:
  - Client habit endpoints:
      POST /api/habits/seed (idempotent + fresh)
      GET  /api/habits/today (day_type + workout aware)
      GET  /api/habits/mine
      POST /api/habits/{id}/log (upsert + streak preservation)
      GET  /api/habits/{id}/logs
      POST /api/habits/reminders/toggle
      GET  /api/habits/reviews/latest
  - Coach habit endpoints:
      GET   /api/coach/clients/{id}/habits
      POST  /api/coach/clients/{id}/habits (manual create)
      PATCH /api/coach/habits/{id} (pause / archive / resume)
      POST  /api/coach/habits/reviews/{id}/approve
      POST  /api/coach/habits/reviews/{id}/reject
      Role guards
  - Streak preservation on skipped / not_possible
  - _apply_habit_review 5-active-habit cap
  - Habit visibility (post-flight + day_type_rules=['layover'])
  - Regression: coach controls + change_log endpoints still work.

Uses direct pymongo for setup/cleanup of habit_reviews (LLM path is too slow /
already-fired for the current week for the seeded client, so we inject reviews
directly to test approve/reject logic).
"""
import os
import time
import uuid
import datetime as _dt
import pymongo
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASS = "Client123!"
COACH_EMAIL = "coach@crewfit.com"
COACH_PASS = "Coach123!"

# ---------- helpers ----------

def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email} failed: {r.status_code} {r.text[:200]}"
    d = r.json()
    return d["token"], d["user"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mongo():
    c = pymongo.MongoClient(MONGO_URL)
    return c[DB_NAME]


@pytest.fixture(scope="module")
def client_auth():
    t, u = _login(CLIENT_EMAIL, CLIENT_PASS)
    return {"token": t, "user": u, "headers": _hdr(t)}


@pytest.fixture(scope="module")
def coach_auth():
    t, u = _login(COACH_EMAIL, COACH_PASS)
    return {"token": t, "user": u, "headers": _hdr(t)}


# ============================================================
# 1. Client habit endpoints
# ============================================================
class TestHabitsMineAndToday:
    def test_habits_mine_returns_active(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "active" in d and "paused" in d
        assert isinstance(d["active"], list)
        assert len(d["active"]) >= 1
        h = d["active"][0]
        for k in ("id", "title", "reason", "habit_type", "status", "created_by"):
            assert k in h, f"missing {k}"
        assert h["status"] == "active"
        assert "streak" in h and isinstance(h["streak"], int)

    def test_habits_today_structure(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/habits/today", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "habits" in d and "date_local" in d
        assert "day_type" in d and "flight_day" in d
        assert isinstance(d["habits"], list)
        for h in d["habits"]:
            assert "today_log" in h
            assert "streak" in h

    def test_seed_is_idempotent_for_existing_client(self, client_auth):
        r = requests.post(f"{BASE_URL}/api/habits/seed", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["seeded"] == 0, f"expected idempotent seed=0, got {d}"


class TestHabitLog:
    def test_log_done_and_streak(self, client_auth):
        m = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15).json()
        assert m["active"], "client needs at least one active habit"
        hid = m["active"][0]["id"]
        r = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                          headers=client_auth["headers"],
                          json={"status": "done"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["log"]["status"] == "done"
        assert d["streak"] >= 1

    def test_log_upserts_on_same_day(self, client_auth, mongo):
        m = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15).json()
        hid = m["active"][0]["id"]
        uid = client_auth["user"]["id"]
        today_iso = _dt.date.today().isoformat()
        r1 = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                           headers=client_auth["headers"],
                           json={"status": "done", "date_local": today_iso}, timeout=15)
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                           headers=client_auth["headers"],
                           json={"status": "skipped", "reason": "test-upsert", "date_local": today_iso},
                           timeout=15)
        assert r2.status_code == 200
        assert r2.json()["log"]["status"] == "skipped"
        # exactly one row for that (habit, user, date)
        cnt = mongo.habit_logs.count_documents(
            {"habit_id": hid, "user_id": uid, "date_local": today_iso})
        assert cnt == 1, f"upsert broken — {cnt} rows for today"
        # restore to done so later tests see a clean state
        requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                      headers=client_auth["headers"],
                      json={"status": "done", "date_local": today_iso}, timeout=15)

    def test_log_invalid_status_400(self, client_auth):
        m = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15).json()
        hid = m["active"][0]["id"]
        r = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                          headers=client_auth["headers"],
                          json={"status": "banana"}, timeout=15)
        assert r.status_code == 400, f"expected 400 for bad status, got {r.status_code}"

    def test_log_unknown_habit_404(self, client_auth):
        r = requests.post(f"{BASE_URL}/api/habits/does-not-exist/log",
                          headers=client_auth["headers"],
                          json={"status": "done"}, timeout=15)
        assert r.status_code == 404

    def test_logs_history_sorted_desc(self, client_auth):
        m = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15).json()
        hid = m["active"][0]["id"]
        r = requests.get(f"{BASE_URL}/api/habits/{hid}/logs",
                         headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        logs = r.json()["logs"]
        assert isinstance(logs, list)
        if len(logs) >= 2:
            assert logs[0]["date_local"] >= logs[1]["date_local"], "logs not desc"


class TestStreakPreservation:
    """KIND-BY-DESIGN — skipped/not_possible must NOT break streak."""

    def test_skipped_yesterday_done_today_gives_streak_2(self, client_auth, coach_auth, mongo):
        # Use a fresh dedicated habit so nothing else interferes.
        client_id = client_auth["user"]["id"]
        create = requests.post(f"{BASE_URL}/api/coach/clients/{client_id}/habits",
                               headers=coach_auth["headers"],
                               json={"title": "TEST_streak_skipped", "habit_type": "daily"}, timeout=15)
        assert create.status_code == 200, create.text
        hid = create.json()["habit"]["id"]
        try:
            today = _dt.date.today()
            yesterday = (today - _dt.timedelta(days=1)).isoformat()
            # Skipped yesterday
            r1 = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                               headers=client_auth["headers"],
                               json={"status": "skipped", "reason": "roster", "date_local": yesterday}, timeout=15)
            assert r1.status_code == 200
            # Done today
            r2 = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                               headers=client_auth["headers"],
                               json={"status": "done", "date_local": today.isoformat()}, timeout=15)
            assert r2.status_code == 200, r2.text
            assert r2.json()["streak"] == 2, f"streak should be 2, got {r2.json()['streak']}"
        finally:
            mongo.habits.delete_one({"id": hid})
            mongo.habit_logs.delete_many({"habit_id": hid})

    def test_not_possible_preserves_streak(self, client_auth, coach_auth, mongo):
        client_id = client_auth["user"]["id"]
        create = requests.post(f"{BASE_URL}/api/coach/clients/{client_id}/habits",
                               headers=coach_auth["headers"],
                               json={"title": "TEST_streak_not_possible", "habit_type": "daily"}, timeout=15)
        assert create.status_code == 200
        hid = create.json()["habit"]["id"]
        try:
            today = _dt.date.today()
            r1 = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                               headers=client_auth["headers"],
                               json={"status": "not_possible", "reason": "layover",
                                     "date_local": (today - _dt.timedelta(days=1)).isoformat()}, timeout=15)
            assert r1.status_code == 200
            r2 = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                               headers=client_auth["headers"],
                               json={"status": "done", "date_local": today.isoformat()}, timeout=15)
            assert r2.json()["streak"] == 2, f"streak should be 2 with not_possible, got {r2.json()['streak']}"
        finally:
            mongo.habits.delete_one({"id": hid})
            mongo.habit_logs.delete_many({"habit_id": hid})

    def test_missing_day_breaks_streak(self, client_auth, coach_auth, mongo):
        client_id = client_auth["user"]["id"]
        create = requests.post(f"{BASE_URL}/api/coach/clients/{client_id}/habits",
                               headers=coach_auth["headers"],
                               json={"title": "TEST_streak_broken", "habit_type": "daily"}, timeout=15)
        hid = create.json()["habit"]["id"]
        try:
            today = _dt.date.today()
            # log 3 days ago done, skip yesterday (no log), log today done → streak should be 1 (just today)
            r_old = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                                  headers=client_auth["headers"],
                                  json={"status": "done",
                                        "date_local": (today - _dt.timedelta(days=3)).isoformat()}, timeout=15)
            assert r_old.status_code == 200
            r_today = requests.post(f"{BASE_URL}/api/habits/{hid}/log",
                                    headers=client_auth["headers"],
                                    json={"status": "done", "date_local": today.isoformat()}, timeout=15)
            assert r_today.json()["streak"] == 1, f"missing-day streak break failed: got {r_today.json()['streak']}"
        finally:
            mongo.habits.delete_one({"id": hid})
            mongo.habit_logs.delete_many({"habit_id": hid})


class TestRemindersToggle:
    def test_toggle_persists(self, client_auth, mongo):
        uid = client_auth["user"]["id"]
        r_off = requests.post(f"{BASE_URL}/api/habits/reminders/toggle",
                              headers=client_auth["headers"],
                              json={"enabled": False}, timeout=15)
        assert r_off.status_code == 200
        assert r_off.json()["enabled"] is False
        u = mongo.users.find_one({"id": uid}, {"habit_reminders_enabled": 1, "_id": 0})
        assert u.get("habit_reminders_enabled") is False
        r_on = requests.post(f"{BASE_URL}/api/habits/reminders/toggle",
                             headers=client_auth["headers"],
                             json={"enabled": True}, timeout=15)
        assert r_on.status_code == 200
        assert r_on.json()["enabled"] is True
        u = mongo.users.find_one({"id": uid}, {"habit_reminders_enabled": 1, "_id": 0})
        assert u.get("habit_reminders_enabled") is True


class TestReviewsLatest:
    def test_reviews_latest_ok(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/habits/reviews/latest",
                         headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert "review" in r.json()


# ============================================================
# 2. Fresh signup → POST /habits/seed
# ============================================================
class TestFreshSeed:
    def test_signup_and_seed_new_client(self, mongo):
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_habit_seed_{uniq}@example.com"
        rs = requests.post(f"{BASE_URL}/api/auth/signup",
                           json={"email": email, "password": "Pass1234!", "name": "TEST Seed User",
                                 "role": "client"}, timeout=30)
        assert rs.status_code == 200, rs.text
        tok = rs.json()["token"]
        try:
            r = requests.post(f"{BASE_URL}/api/habits/seed",
                              headers=_hdr(tok), timeout=60)
            assert r.status_code == 200, r.text
            seeded = r.json()["seeded"]
            # deterministic fallback pack has 4-5 items; LLM likely 3-5
            assert 3 <= seeded <= 5, f"expected 3-5 habits seeded, got {seeded}"
            # idempotency: second call = 0
            r2 = requests.post(f"{BASE_URL}/api/habits/seed",
                               headers=_hdr(tok), timeout=30)
            assert r2.json()["seeded"] == 0
            # Habits should have required shape
            mine = requests.get(f"{BASE_URL}/api/habits/mine", headers=_hdr(tok), timeout=15).json()
            assert len(mine["active"]) == seeded
            for h in mine["active"]:
                for k in ("id", "title", "reason", "habit_type", "status", "created_by", "linked_goal",
                          "day_type_rules", "frequency", "difficulty_level"):
                    assert k in h, f"seeded habit missing {k}"
                assert h["status"] == "active"
                assert h["created_by"] == "atlas"
        finally:
            uid = rs.json()["user"]["id"]
            mongo.habits.delete_many({"user_id": uid})
            mongo.habit_logs.delete_many({"user_id": uid})
            mongo.users.delete_one({"id": uid})


# ============================================================
# 3. Habit visibility on /habits/today
# ============================================================
class TestHabitVisibility:
    def test_post_flight_habit_hidden_without_workout(self, client_auth, coach_auth, mongo):
        client_id = client_auth["user"]["id"]
        # Ensure today has no workout row for this test
        today = _dt.date.today().isoformat()
        # Snapshot & remove any today workout so /habits/today falls back to roster
        existing_wk = list(mongo.workouts.find({"user_id": client_id, "date": today}, {"_id": 0}))
        mongo.workouts.delete_many({"user_id": client_id, "date": today})
        # Also ensure the (possibly seeded) roster for today is not layover
        existing_rosters = list(mongo.rosters.find({"user_id": client_id, "is_active": True}, {"_id": 0}))
        # Force a non-layover, non-flight roster for today
        forced_roster_id = f"TEST_roster_{uuid.uuid4().hex[:8]}"
        mongo.rosters.update_many({"user_id": client_id, "is_active": True}, {"$set": {"is_active": False}})
        mongo.rosters.insert_one({
            "id": forced_roster_id, "user_id": client_id, "is_active": True,
            "created_at": _dt.datetime.utcnow().isoformat(),
            "days": [{"date": today, "type": "home_day", "day_type": "home_day"}],
        })
        # Create post-flight habit
        create = requests.post(f"{BASE_URL}/api/coach/clients/{client_id}/habits",
                               headers=coach_auth["headers"],
                               json={"title": "TEST_post_flight_visibility",
                                     "habit_type": "post-flight",
                                     "day_type_rules": ["layover"]}, timeout=15)
        assert create.status_code == 200
        hid = create.json()["habit"]["id"]
        try:
            t = requests.get(f"{BASE_URL}/api/habits/today",
                             headers=client_auth["headers"], timeout=15).json()
            ids = [h["id"] for h in t["habits"]]
            assert hid not in ids, f"post-flight habit should NOT show on home_day, but did (day_type={t.get('day_type')})"

            # Now flip the roster day_type to 'layover' — should appear
            mongo.rosters.update_one({"id": forced_roster_id},
                                     {"$set": {"days": [{"date": today, "type": "layover", "day_type": "layover"}]}})
            t2 = requests.get(f"{BASE_URL}/api/habits/today",
                              headers=client_auth["headers"], timeout=15).json()
            ids2 = [h["id"] for h in t2["habits"]]
            assert hid in ids2, f"post-flight habit should show on layover day (day_type={t2.get('day_type')})"
        finally:
            # cleanup — restore rosters + workouts
            mongo.habits.delete_one({"id": hid})
            mongo.habit_logs.delete_many({"habit_id": hid})
            mongo.rosters.delete_one({"id": forced_roster_id})
            for r in existing_rosters:
                r.pop("_id", None)
                mongo.rosters.update_one({"id": r["id"]}, {"$set": r}, upsert=True)
            for w in existing_wk:
                w.pop("_id", None)
                mongo.workouts.insert_one(w)


# ============================================================
# 4. Coach endpoints (habits + reviews)
# ============================================================
class TestCoachHabits:
    def test_coach_get_habits(self, client_auth, coach_auth):
        cid = client_auth["user"]["id"]
        r = requests.get(f"{BASE_URL}/api/coach/clients/{cid}/habits",
                         headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("active", "paused", "archived", "completion", "latest_review", "pending_review"):
            assert k in d, f"coach habits missing {k}"
        for h in d["active"]:
            assert h["id"] in d["completion"]
            c = d["completion"][h["id"]]
            for k in ("done", "skipped", "not_possible", "rate"):
                assert k in c

    def test_coach_create_and_change_log(self, client_auth, coach_auth, mongo):
        cid = client_auth["user"]["id"]
        title = f"TEST_coach_created_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/coach/clients/{cid}/habits",
                          headers=coach_auth["headers"],
                          json={"title": title, "reason": "coach reason", "linked_goal": "recovery"},
                          timeout=15)
        assert r.status_code == 200, r.text
        h = r.json()["habit"]
        try:
            assert h["created_by"] == "coach"
            assert h["title"] == title
            assert h["status"] == "active"
            # coach_change_log entry present
            log = mongo.coach_change_log.find_one({"client_id": cid, "meta.habit_id": h["id"]})
            assert log is not None, "coach_change_log entry missing for coach-created habit"
            assert log.get("actor") == "coach"
            assert log.get("category") == "programme"
        finally:
            mongo.habits.delete_one({"id": h["id"]})
            mongo.coach_change_log.delete_many({"meta.habit_id": h["id"]})

    def test_coach_patch_pause_archive_activate(self, client_auth, coach_auth, mongo):
        cid = client_auth["user"]["id"]
        r = requests.post(f"{BASE_URL}/api/coach/clients/{cid}/habits",
                          headers=coach_auth["headers"],
                          json={"title": "TEST_patch"}, timeout=15)
        hid = r.json()["habit"]["id"]
        try:
            # Pause
            r1 = requests.patch(f"{BASE_URL}/api/coach/habits/{hid}",
                                headers=coach_auth["headers"],
                                json={"status": "paused"}, timeout=15)
            assert r1.status_code == 200, r1.text
            assert r1.json()["habit"]["status"] == "paused"
            assert r1.json()["habit"]["paused_at"] is not None
            # Archive
            r2 = requests.patch(f"{BASE_URL}/api/coach/habits/{hid}",
                                headers=coach_auth["headers"],
                                json={"status": "archived"}, timeout=15)
            assert r2.status_code == 200
            assert r2.json()["habit"]["status"] == "archived"
            assert r2.json()["habit"]["deleted_at"] is not None
            # Reactivate → paused_at cleared
            r3 = requests.patch(f"{BASE_URL}/api/coach/habits/{hid}",
                                headers=coach_auth["headers"],
                                json={"status": "active"}, timeout=15)
            assert r3.status_code == 200
            assert r3.json()["habit"]["status"] == "active"
            assert r3.json()["habit"]["paused_at"] is None
            # target edit
            r4 = requests.patch(f"{BASE_URL}/api/coach/habits/{hid}",
                                headers=coach_auth["headers"],
                                json={"target": "9000", "reason": "updated reason"}, timeout=15)
            assert r4.status_code == 200
            assert r4.json()["habit"]["target"] == "9000"
            assert r4.json()["habit"]["reason"] == "updated reason"
            # change log entries
            logs = list(mongo.coach_change_log.find({"meta.habit_id": hid}))
            assert len(logs) >= 3, f"expected >=3 change_log entries, got {len(logs)}"
        finally:
            mongo.habits.delete_one({"id": hid})
            mongo.habit_logs.delete_many({"habit_id": hid})
            mongo.coach_change_log.delete_many({"meta.habit_id": hid})

    def test_coach_patch_no_updates_400(self, coach_auth, client_auth, mongo):
        cid = client_auth["user"]["id"]
        r = requests.post(f"{BASE_URL}/api/coach/clients/{cid}/habits",
                          headers=coach_auth["headers"], json={"title": "TEST_no_up"}, timeout=15)
        hid = r.json()["habit"]["id"]
        try:
            r2 = requests.patch(f"{BASE_URL}/api/coach/habits/{hid}",
                                headers=coach_auth["headers"], json={}, timeout=15)
            assert r2.status_code == 400
        finally:
            mongo.habits.delete_one({"id": hid})
            mongo.coach_change_log.delete_many({"meta.habit_id": hid})

    def test_role_guards(self, client_auth):
        # Client trying to call coach endpoints must be rejected
        cid = client_auth["user"]["id"]
        r_get = requests.get(f"{BASE_URL}/api/coach/clients/{cid}/habits",
                             headers=client_auth["headers"], timeout=15)
        assert r_get.status_code in (401, 403), f"expected 401/403, got {r_get.status_code}"
        r_post = requests.post(f"{BASE_URL}/api/coach/clients/{cid}/habits",
                               headers=client_auth["headers"],
                               json={"title": "bad"}, timeout=15)
        assert r_post.status_code in (401, 403)
        r_patch = requests.patch(f"{BASE_URL}/api/coach/habits/fake",
                                 headers=client_auth["headers"],
                                 json={"status": "paused"}, timeout=15)
        assert r_patch.status_code in (401, 403)
        r_appr = requests.post(f"{BASE_URL}/api/coach/habits/reviews/fake/approve",
                               headers=client_auth["headers"], json={}, timeout=15)
        assert r_appr.status_code in (401, 403)
        # Anonymous
        r_anon = requests.get(f"{BASE_URL}/api/coach/clients/{cid}/habits", timeout=15)
        assert r_anon.status_code in (401, 403)


# ============================================================
# 5. Habit review approve / reject (injected review)
# ============================================================
def _now_iso():
    return _dt.datetime.utcnow().replace(tzinfo=_dt.timezone.utc).isoformat()


class TestReviewApproveReject:

    def _seed_pending_review(self, mongo, client_id, existing_habit_id, new_title):
        rid = f"TEST_review_{uuid.uuid4().hex[:8]}"
        review = {
            "id": rid,
            "user_id": client_id,
            "user_name": "Alex Rivera",
            "check_in_id": f"TEST_ci_{uuid.uuid4().hex[:8]}",
            "week_start": _dt.date.today().isoformat(),
            "week_end": _dt.date.today().isoformat(),
            "completion_rate": 0.42,
            "atlas_summary": "TEST atlas summary",
            "coach_summary": "TEST coach summary",
            "what_worked": "",
            "what_did_not": "",
            "stats": [],
            "recommendations": [{
                "habit_id": existing_habit_id,
                "action": "scale_down",
                "new_target": "2 sessions",
                "reason": "TEST scale down",
                "risk_level": "low",
            }],
            "new_habits": [{"title": new_title, "reason": "TEST", "habit_type": "daily"}],
            "coach_review_required": True,
            "coach_review_status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "created_at": _now_iso(),
            "applied_at": None,
        }
        mongo.habit_reviews.insert_one(review)
        # Also create a linked coach task (mimic what _run_habit_review_after_checkin does)
        task_id = f"TEST_task_{uuid.uuid4().hex[:8]}"
        mongo.coach_tasks.insert_one({
            "id": task_id,
            "user_id": client_id,
            "client_id": client_id,
            "type": "habit_review",
            "task_type": "habit_review",
            "category": "programme",
            "title": "TEST habit review task",
            "description": "",
            "priority": "normal",
            "risk_level": "low",
            "status": "todo",
            "payload": {"habit_review_id": rid},
            "created_at": _now_iso(),
        })
        return rid, task_id

    def test_approve_applies_and_closes_task(self, coach_auth, client_auth, mongo):
        cid = client_auth["user"]["id"]
        mine = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15).json()
        h0 = mine["active"][0]
        # Count active habits — if already at 5, new_habit won't be inserted (cap)
        active_before = len(mine["active"])
        rid, task_id = self._seed_pending_review(mongo, cid, h0["id"], "TEST_new_habit_apply")
        try:
            r = requests.post(f"{BASE_URL}/api/coach/habits/reviews/{rid}/approve",
                              headers=coach_auth["headers"],
                              json={"coach_note": "approving in test"}, timeout=30)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["review"]["coach_review_status"] == "approved"
            applied = d["applied"]
            assert applied["updated"] == 1
            # new habit only if active_before < 5
            expected_created = 1 if active_before < 5 else 0
            assert applied["created"] == expected_created, f"created={applied['created']} expected {expected_created}"
            # Target on h0 updated
            saved = mongo.habits.find_one({"id": h0["id"]}, {"_id": 0})
            assert saved["target"] == "2 sessions"
            # Coach task resolved
            task = mongo.coach_tasks.find_one({"id": task_id}, {"_id": 0})
            assert task["status"] == "done"
            assert task.get("completed_at")
            # Change log entry
            log = mongo.coach_change_log.find_one({"meta.review_id": rid, "actor": "coach"})
            assert log is not None
            # Second approve → 400
            r2 = requests.post(f"{BASE_URL}/api/coach/habits/reviews/{rid}/approve",
                               headers=coach_auth["headers"], json={}, timeout=15)
            assert r2.status_code == 400
        finally:
            # revert h0.target
            mongo.habits.update_one({"id": h0["id"]}, {"$set": {"target": h0.get("target")}})
            # remove any created new habits (they'll have last_review_id=rid)
            mongo.habits.delete_many({"last_review_id": rid, "created_by": "coach"})
            mongo.habit_reviews.delete_one({"id": rid})
            mongo.coach_tasks.delete_one({"id": task_id})
            mongo.coach_change_log.delete_many({"meta.review_id": rid})

    def test_reject_flow(self, coach_auth, client_auth, mongo):
        cid = client_auth["user"]["id"]
        mine = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15).json()
        h0 = mine["active"][0]
        rid, task_id = self._seed_pending_review(mongo, cid, h0["id"], "TEST_new_habit_reject")
        try:
            r = requests.post(f"{BASE_URL}/api/coach/habits/reviews/{rid}/reject",
                              headers=coach_auth["headers"],
                              json={"coach_note": "not this week"}, timeout=15)
            assert r.status_code == 200, r.text
            rv = mongo.habit_reviews.find_one({"id": rid}, {"_id": 0})
            assert rv["coach_review_status"] == "rejected"
            assert rv["reviewed_by"]
            # Task dismissed
            task = mongo.coach_tasks.find_one({"id": task_id}, {"_id": 0})
            assert task["status"] == "dismissed"
            # No changes to habit
            saved = mongo.habits.find_one({"id": h0["id"]}, {"_id": 0})
            assert saved["target"] == h0.get("target")
            # Repeated reject → 400
            r2 = requests.post(f"{BASE_URL}/api/coach/habits/reviews/{rid}/reject",
                               headers=coach_auth["headers"], json={}, timeout=15)
            assert r2.status_code == 400
            # Repeated approve → 400
            r3 = requests.post(f"{BASE_URL}/api/coach/habits/reviews/{rid}/approve",
                               headers=coach_auth["headers"], json={}, timeout=15)
            assert r3.status_code == 400
        finally:
            mongo.habit_reviews.delete_one({"id": rid})
            mongo.coach_tasks.delete_one({"id": task_id})
            mongo.coach_change_log.delete_many({"meta.review_id": rid})


# ============================================================
# 6. _apply_habit_review must cap active habits at 5
# ============================================================
class TestMaxHabitsCap:
    def test_new_habits_not_inserted_when_5_active(self, coach_auth, client_auth, mongo):
        cid = client_auth["user"]["id"]
        mine = requests.get(f"{BASE_URL}/api/habits/mine", headers=client_auth["headers"], timeout=15).json()
        active_count = len(mine["active"])
        added_ids: list[str] = []
        try:
            # Pad up to 5 active
            while active_count < 5:
                r = requests.post(f"{BASE_URL}/api/coach/clients/{cid}/habits",
                                  headers=coach_auth["headers"],
                                  json={"title": f"TEST_pad_{uuid.uuid4().hex[:5]}"}, timeout=15)
                assert r.status_code == 200, r.text
                added_ids.append(r.json()["habit"]["id"])
                active_count += 1
            # Now inject a review with 3 new habits and one recommendation of type 'keep'
            rid = f"TEST_cap_{uuid.uuid4().hex[:6]}"
            mongo.habit_reviews.insert_one({
                "id": rid,
                "user_id": cid,
                "week_start": _dt.date.today().isoformat(),
                "week_end": _dt.date.today().isoformat(),
                "recommendations": [],
                "new_habits": [
                    {"title": "TEST_cap_1", "habit_type": "daily"},
                    {"title": "TEST_cap_2", "habit_type": "daily"},
                    {"title": "TEST_cap_3", "habit_type": "daily"},
                ],
                "coach_review_status": "pending",
                "created_at": _now_iso(),
            })
            r = requests.post(f"{BASE_URL}/api/coach/habits/reviews/{rid}/approve",
                              headers=coach_auth["headers"], json={}, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["applied"]["created"] == 0, "cap should block all 3 new habits when at 5 active"
            # Verify none present
            for t in ("TEST_cap_1", "TEST_cap_2", "TEST_cap_3"):
                assert mongo.habits.find_one({"user_id": cid, "title": t}) is None
            mongo.habit_reviews.delete_one({"id": rid})
            mongo.coach_change_log.delete_many({"meta.review_id": rid})
        finally:
            for h in added_ids:
                mongo.habits.delete_one({"id": h})
                mongo.coach_change_log.delete_many({"meta.habit_id": h})


# ============================================================
# 7. Regression: existing coach controls + change_log endpoints still ok
# ============================================================
class TestRegressionExistingEndpoints:
    def test_coach_controls_get_put(self, coach_auth, client_auth, mongo):
        cid = client_auth["user"]["id"]
        r = requests.get(f"{BASE_URL}/api/coach/clients/{cid}/controls",
                         headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "controls" in d
        # Restore auto_approval_risk_threshold to default 'none'
        r2 = requests.put(f"{BASE_URL}/api/coach/clients/{cid}/controls",
                          headers=coach_auth["headers"],
                          json={"auto_approval_risk_threshold": "none"}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["controls"]["auto_approval_risk_threshold"] == "none"

    def test_coach_change_log_endpoint(self, coach_auth):
        r = requests.get(f"{BASE_URL}/api/coach/change-log?limit=5",
                         headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert "items" in r.json() or "log" in r.json() or "entries" in r.json() or isinstance(r.json(), (list, dict))


# ============================================================
# 8. Full check-in submit → background habit review generation
# ============================================================
class TestCheckinReviewGeneration:
    """Fresh client → seed habits → submit check-in → wait <=45s for habit_review."""

    def test_checkin_triggers_habit_review(self, mongo):
        uniq = uuid.uuid4().hex[:8]
        email = f"TEST_review_flow_{uniq}@example.com"
        rs = requests.post(f"{BASE_URL}/api/auth/signup",
                           json={"email": email, "password": "Pass1234!",
                                 "name": "TEST Review Flow", "role": "client"}, timeout=30)
        assert rs.status_code == 200, rs.text
        tok = rs.json()["token"]
        uid = rs.json()["user"]["id"]
        try:
            # Seed habits
            r_seed = requests.post(f"{BASE_URL}/api/habits/seed", headers=_hdr(tok), timeout=60)
            assert r_seed.status_code == 200
            assert r_seed.json()["seeded"] >= 3
            # Log one habit as done so completion isn't zero
            mine = requests.get(f"{BASE_URL}/api/habits/mine", headers=_hdr(tok), timeout=15).json()
            hid = mine["active"][0]["id"]
            requests.post(f"{BASE_URL}/api/habits/{hid}/log", headers=_hdr(tok),
                          json={"status": "done"}, timeout=15)
            # Submit a check-in
            ci = requests.post(f"{BASE_URL}/api/checkins/submit", headers=_hdr(tok),
                               json={"answers": {"energy": 7, "sleep": 7, "stress": 3, "recovery": 7,
                                                 "pain": "None", "nutrition": "Good",
                                                 "biggest_challenge": "layover jet lag"}},
                               timeout=60)
            assert ci.status_code == 200, ci.text
            # Wait up to 45s for the background task to insert habit_reviews doc
            review = None
            deadline = time.time() + 45
            while time.time() < deadline:
                r = requests.get(f"{BASE_URL}/api/habits/reviews/latest",
                                 headers=_hdr(tok), timeout=15)
                if r.status_code == 200 and r.json().get("review"):
                    review = r.json()["review"]
                    break
                time.sleep(2)
            assert review is not None, "habit_review not generated within 45s"
            for k in ("id", "completion_rate", "atlas_summary", "recommendations", "new_habits",
                      "coach_review_status", "week_start", "week_end"):
                assert k in review, f"review missing {k}"
            assert review["coach_review_status"] in ("pending", "auto_applied")
            # If pending → there should be a coach To-Do task for this review
            if review["coach_review_status"] == "pending":
                task = mongo.coach_tasks.find_one({
                    "payload.habit_review_id": review["id"],
                    "task_type": "habit_review",
                })
                assert task is not None, "pending review must create a coach_task"
                assert task.get("category") == "programme"
        finally:
            # cleanup
            mongo.habits.delete_many({"user_id": uid})
            mongo.habit_logs.delete_many({"user_id": uid})
            mongo.habit_reviews.delete_many({"user_id": uid})
            mongo.check_ins.delete_many({"user_id": uid})
            mongo.coach_tasks.delete_many({"user_id": uid})
            mongo.coach_change_log.delete_many({"client_id": uid})
            mongo.users.delete_one({"id": uid})
