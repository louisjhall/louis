"""Iter 94w — Sunday Weekly Review from Louis (backend tests)."""
import os
import re
import time
import uuid
import datetime as _dt
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_BACKEND_URL") or "https://flight-fit-plans.preview.emergentagent.com"
BASE_URL = BASE_URL.rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "testcal2@crewfit.com"
CLIENT_PASSWORD = "TestCal123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")


def _monday(today: _dt.date) -> str:
    return (today - _dt.timedelta(days=today.weekday())).isoformat()


def _sunday(today: _dt.date) -> str:
    m = today - _dt.timedelta(days=today.weekday())
    return (m + _dt.timedelta(days=6)).isoformat()


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_user(client_token):
    r = requests.get(f"{API}/auth/me",
                     headers={"Authorization": f"Bearer {client_token}"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": COACH_EMAIL, "password": COACH_PASSWORD}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module", autouse=True)
def cleanup_start(db, client_user):
    """Ensure a clean state for testcal2 for the current week before tests run."""
    ws = _monday(_dt.date.today())
    uid = client_user["id"]
    db.weekly_reviews.delete_many({"user_id": uid, "week_start": ws})
    db.coach_tasks.delete_many({"user_id": uid, "task_type": "weekly_video_review"})
    yield
    # module teardown
    db.weekly_reviews.delete_many({"user_id": uid, "week_start": ws})
    db.coach_tasks.delete_many({"user_id": uid, "task_type": "weekly_video_review"})


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------- Tests: GET /weekly-review/current ----------
class TestWeeklyReviewCurrent:
    def test_returns_all_required_fields(self, client_token, client_user):
        r = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()

        assert doc["week_start"] == _monday(_dt.date.today())
        assert doc["week_end"] == _sunday(_dt.date.today())
        assert doc["goal_class"] in ("fat_loss", "running", "strength", "return_to_training", "health")

        # training block
        t = doc["training"]
        for k in ("planned", "completed", "missed", "skipped", "recovered",
                  "key_planned", "key_completed", "adherence_pct"):
            assert k in t, f"training missing {k}"

        # nutrition block
        n = doc["nutrition"]
        for k in ("days_logged", "avg_calories", "avg_protein_g", "days_hit_protein"):
            assert k in n, f"nutrition missing {k}"

        # habits block
        h = doc["habits"]
        for k in ("completed", "planned", "pct"):
            assert k in h, f"habits missing {k}"

        assert "roster_summary" in doc
        assert "has_progress" in doc
        assert isinstance(doc["message_lines"], list) and len(doc["message_lines"]) >= 3
        assert doc["checkin_status"] in ("complete", "incomplete")
        assert doc["progress_status"] in ("complete", "incomplete")
        assert "review_ready_for_louis" in doc

    def test_message_starts_and_ends_correctly(self, client_token, client_user):
        r = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30)
        assert r.status_code == 200
        lines = r.json()["message_lines"]
        first_name = (client_user.get("name") or "there").split(" ")[0] or "there"
        assert lines[0] == f"Hi {first_name}, here's your CrewFit weekly review so far.", lines[0]
        # Last non-empty line should be "Louis"
        assert lines[-1] == "Louis", f"last line was {lines[-1]!r}"

    def test_message_contains_required_prompts(self, client_token):
        r = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30)
        joined = "\n".join(r.json()["message_lines"])
        assert "Please complete your weekly check-in and update your Progress tab today." in joined
        assert "I'll review your week properly and come back with a short video for you." in joined

    def test_no_ai_or_generated_wording(self, client_token):
        r = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30)
        joined = "\n".join(r.json()["message_lines"])
        # Word-boundary matching to avoid false positives like "Aim"
        for pattern in (r"\bAI\b", r"\bgenerated\b", r"\bautomated\b", r"\bauto-generated\b"):
            assert not re.search(pattern, joined, re.IGNORECASE), \
                f"forbidden term matching {pattern!r} present in message"

    def test_idempotent_same_week_start(self, client_token):
        r1 = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30).json()
        r2 = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30).json()
        assert r1["week_start"] == r2["week_start"]
        assert r1.get("id") == r2.get("id") or (r1.get("created_at") == r2.get("created_at"))


# ---------- Tests: check-in / progress completion ----------
class TestCheckinAndProgressFlow:
    def test_checkin_complete_sets_status(self, client_token):
        r = requests.post(f"{API}/weekly-review/checkin-complete",
                          headers=_auth(client_token), json={"note": "feeling good"}, timeout=30)
        assert r.status_code == 200, r.text
        review = r.json()["review"]
        assert review["checkin_status"] == "complete"
        assert review.get("checkin_completed_at")

        # verify persistence via GET
        g = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30).json()
        assert g["checkin_status"] == "complete"

    def test_progress_complete_sets_status_and_video_task(self, client_token, client_user, db):
        r = requests.post(f"{API}/weekly-review/progress-complete",
                          headers=_auth(client_token), json={"note": "logged weight"}, timeout=30)
        assert r.status_code == 200, r.text
        review = r.json()["review"]
        assert review["progress_status"] == "complete"
        assert review.get("progress_updated_at")

        # Since checkin was already complete, coach task should now exist and flags flipped
        g = requests.get(f"{API}/weekly-review/current", headers=_auth(client_token), timeout=30).json()
        assert g["progress_status"] == "complete"
        assert g["checkin_status"] == "complete"
        assert g["review_ready_for_louis"] is True, g
        assert g.get("video_review_status") == "ready"

        # Coach task created once
        ws = _monday(_dt.date.today())
        tasks = list(db.coach_tasks.find({
            "user_id": client_user["id"],
            "task_type": "weekly_video_review",
        }))
        assert len(tasks) == 1, f"expected exactly 1 weekly_video_review coach_task, got {len(tasks)}: {tasks}"
        assert tasks[0]["category"] == "weekly_review"

    def test_no_duplicate_task_on_repeat_complete(self, client_token, client_user, db):
        # Call both endpoints again — should NOT create a second task
        requests.post(f"{API}/weekly-review/checkin-complete",
                      headers=_auth(client_token), json={"note": "again"}, timeout=30)
        requests.post(f"{API}/weekly-review/progress-complete",
                      headers=_auth(client_token), json={"note": "again"}, timeout=30)
        tasks = list(db.coach_tasks.find({
            "user_id": client_user["id"],
            "task_type": "weekly_video_review",
        }))
        assert len(tasks) == 1, f"duplicate coach tasks created: {len(tasks)}"


# ---------- Tests: Regenerate ----------
class TestRegenerate:
    def test_regenerate_preserves_statuses(self, client_token):
        # Preconditions from previous class: both statuses complete
        r = requests.post(f"{API}/weekly-review/regenerate",
                          headers=_auth(client_token), timeout=30)
        assert r.status_code == 200, r.text
        rv = r.json()["review"]
        assert rv["checkin_status"] == "complete"
        assert rv["progress_status"] == "complete"
        assert rv.get("review_ready_for_louis") is True
        # message still ends with Louis
        assert rv["message_lines"][-1] == "Louis"


# ---------- Tests: Admin listing ----------
class TestAdminList:
    def test_client_forbidden(self, client_token):
        r = requests.get(f"{API}/admin/weekly-reviews", headers=_auth(client_token), timeout=30)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text}"

    def test_coach_can_list_with_client_details(self, coach_token, client_user):
        r = requests.get(f"{API}/admin/weekly-reviews", headers=_auth(coach_token), timeout=30)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "reviews" in payload
        assert "count" in payload
        assert payload["week_start"] == _monday(_dt.date.today())
        # our client's review should be there with name + email stitched in
        matching = [x for x in payload["reviews"] if x.get("user_id") == client_user["id"]]
        assert matching, "testcal2's review missing from admin list"
        assert matching[0].get("client_email") == CLIENT_EMAIL
        assert matching[0].get("client_name")


# ---------- Tests: Low-data client ----------
class TestLowDataClient:
    @pytest.fixture(scope="class")
    def fresh_client(self, db):
        # Create a fresh signup with unique email
        email = f"TEST_lowdata_{uuid.uuid4().hex[:8]}@example.com"
        password = "LowData123!"
        r = requests.post(f"{API}/auth/signup", json={
            "email": email, "password": password, "name": "TestLow Data",
            "first_name": "TestLow", "last_name": "Data",
            "age": 30, "age_confirmed": True,
        }, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        yield data
        # cleanup
        try:
            db.users.delete_many({"email": email.lower()})
            db.weekly_reviews.delete_many({"user_id": data["user"]["id"]})
            db.coach_tasks.delete_many({"user_id": data["user"]["id"]})
        except Exception:
            pass

    def test_low_data_message(self, fresh_client):
        tok = fresh_client["token"]
        r = requests.get(f"{API}/weekly-review/current", headers=_auth(tok), timeout=30)
        assert r.status_code == 200, r.text
        doc = r.json()
        joined = "\n".join(doc["message_lines"])
        assert "I don't have enough data logged yet" in joined, joined
        # Sanity: message still opens with 'Hi' and closes with 'Louis'
        assert doc["message_lines"][0].startswith("Hi ")
        assert doc["message_lines"][-1] == "Louis"
        # No AI/generated language
        for pattern in (r"\bAI\b", r"\bgenerated\b", r"\bautomated\b"):
            assert not re.search(pattern, joined, re.IGNORECASE)
