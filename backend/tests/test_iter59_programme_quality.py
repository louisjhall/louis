"""
Iteration 59 — Phase 1: Programme Quality wiring tests.

Verifies:
- /api/programme/current reachable + returns row after generation
- /api/coach/clients/{id}/programme returns {programme, next_7_days}
- Retry-worker path persists a `programmes` row + writes source /
  needs_coach_review / variants on workout docs
- persist_programme_record is idempotent per (user_id, roster_id)
- Workout schema fields (source, needs_coach_review, variants) are present
"""
import datetime as dt
import os
import time

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")


def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    j = r.json()
    return j["token"], j["user"]


@pytest.fixture(scope="module")
def client_auth():
    token, user = _login(CLIENT_EMAIL, CLIENT_PW)
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture(scope="module")
def coach_auth():
    token, user = _login(COACH_EMAIL, COACH_PW)
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture(scope="module")
def mongo_db():
    return MongoClient(MONGO_URL)[DB_NAME]


# ---------------------------------------------------------------------------
# 1. /programme/current reachable and doesn't 500 for fresh users
# ---------------------------------------------------------------------------
class TestProgrammeCurrentEndpoint:
    def test_programme_current_reachable(self, client_auth):
        r = requests.get(f"{API}/programme/current", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


# ---------------------------------------------------------------------------
# 2. Retry-worker path: exercises the full programme wiring
#    (roster/jobs/{job_id}/retry re-runs generation + validation + persistence)
# ---------------------------------------------------------------------------
class TestRetryWorkerFullPipeline:
    def test_find_completed_job_with_roster(self, client_auth, mongo_db):
        uid = client_auth["user"]["id"]
        job = mongo_db.roster_jobs.find_one(
            {"user_id": uid, "roster_id": {"$ne": None}, "status": {"$in": ["complete", "done", "needs_review", "failed"]}},
            sort=[("created_at", -1)],
        )
        assert job, "no roster_job with a roster_id found for seed client"
        pytest.job_id = job["id"]
        pytest.roster_id = job["roster_id"]
        print(f"[retry] using job_id={pytest.job_id} roster_id={pytest.roster_id}")

    def test_kick_off_retry(self, client_auth):
        r = requests.post(
            f"{API}/roster/jobs/{pytest.job_id}/retry",
            headers=client_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"

    def test_wait_for_retry_done(self, client_auth):
        deadline = time.time() + 220
        last = None
        while time.time() < deadline:
            s = requests.get(f"{API}/roster/jobs/{pytest.job_id}", headers=client_auth["headers"], timeout=30).json()
            last = s
            if s.get("status") in ("complete", "done", "needs_review", "failed"):
                break
            time.sleep(4)
        assert last and last.get("status") in ("complete", "done", "needs_review"), f"retry did not complete: {last}"
        print(f"[retry] final status={last.get('status')}")

    def test_programme_row_persisted(self, client_auth, mongo_db):
        uid = client_auth["user"]["id"]
        p = mongo_db.programmes.find_one({"user_id": uid, "roster_id": pytest.roster_id})
        assert p, "no programme row persisted for (user, roster)"
        # goal_key
        assert p.get("goal_key"), f"missing goal_key"
        # phase
        assert (p.get("phase") or {}).get("key") in ("foundation", "build", "peak", "deload"), f"bad phase {p.get('phase')}"
        # week_index >= 1
        assert int(p.get("week_index") or 0) >= 1
        # target_sessions_per_week >= 2
        assert int(p.get("target_sessions_per_week") or 0) >= 2
        # validation_status set
        assert p.get("validation_status") in ("ok", "needs_review")
        # roster_id matches
        assert p["roster_id"] == pytest.roster_id
        print(
            f"[programme row] goal={p['goal_key']} phase={p['phase']['key']} "
            f"week={p['week_index']} target={p['target_sessions_per_week']} validation={p['validation_status']}"
        )

    def test_workout_docs_have_schema_fields(self, client_auth, mongo_db):
        uid = client_auth["user"]["id"]
        wks = list(
            mongo_db.workouts.find({"user_id": uid, "roster_id": pytest.roster_id}, {"_id": 0}).limit(20)
        )
        assert wks, "no workouts for roster"
        for w in wks:
            assert "source" in w, f"missing source on {w.get('date')}"
            assert w["source"] in ("coaching_system", "template"), f"bad source {w.get('source')}"
            assert isinstance(w.get("needs_coach_review"), bool), f"needs_coach_review not bool on {w.get('date')}"
            v = w.get("variants")
            assert isinstance(v, dict), f"variants missing on {w.get('date')}"
            assert set(v.keys()) >= {"green", "amber", "red"}, f"variants keys={list(v.keys())}"
        # At least one workout should have a non-empty rationale (LLM-produced).
        with_rat = [w for w in wks if (w.get("rationale") or "").strip()]
        assert with_rat, "no workout has a rationale"
        print(f"[schema] {len(wks)} sampled OK, {len(with_rat)} have rationale")

    def test_idempotent_second_retry_no_duplicate(self, client_auth, mongo_db):
        uid = client_auth["user"]["id"]
        before = mongo_db.programmes.count_documents({"user_id": uid, "roster_id": pytest.roster_id})
        assert before == 1
        r = requests.post(
            f"{API}/roster/jobs/{pytest.job_id}/retry", headers=client_auth["headers"], timeout=30
        )
        assert r.status_code == 200
        deadline = time.time() + 220
        while time.time() < deadline:
            s = requests.get(f"{API}/roster/jobs/{pytest.job_id}", headers=client_auth["headers"], timeout=30).json()
            if s.get("status") in ("complete", "done", "needs_review", "failed"):
                break
            time.sleep(4)
        after = mongo_db.programmes.count_documents({"user_id": uid, "roster_id": pytest.roster_id})
        assert after == before, f"programme row duplicated on retry: {before} -> {after}"


# ---------------------------------------------------------------------------
# 3. /programme/current returns the freshly persisted programme
# ---------------------------------------------------------------------------
class TestProgrammeCurrentReturnsRow:
    def test_returns_row(self, client_auth):
        r = requests.get(f"{API}/programme/current", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        p = r.json()
        assert p, "programme empty"
        assert p.get("goal_key")
        assert (p.get("phase") or {}).get("key") in ("foundation", "build", "peak", "deload")
        assert int(p.get("week_index") or 0) >= 1
        assert int(p.get("target_sessions_per_week") or 0) >= 2


# ---------------------------------------------------------------------------
# 4. Coach visibility
# ---------------------------------------------------------------------------
class TestCoachProgrammeEndpoints:
    def test_coach_programme_for_client(self, coach_auth, client_auth):
        client_id = client_auth["user"]["id"]
        r = requests.get(
            f"{API}/coach/clients/{client_id}/programme", headers=coach_auth["headers"], timeout=30
        )
        assert r.status_code == 200
        j = r.json()
        assert "programme" in j and j["programme"], "programme missing"
        assert "next_7_days" in j
        assert isinstance(j["next_7_days"], list)

    def test_coach_programme_history(self, coach_auth, client_auth):
        client_id = client_auth["user"]["id"]
        r = requests.get(
            f"{API}/coach/clients/{client_id}/programme/history",
            headers=coach_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200
        j = r.json()
        assert "programmes" in j
        assert isinstance(j["programmes"], list)
        assert j["count"] >= 1


# ---------------------------------------------------------------------------
# 5. Template-fallback workouts (if any exist) should have source='template'
#    + needs_coach_review=True. Skip if none in the DB.
# ---------------------------------------------------------------------------
class TestTemplateFallbackSchema:
    def test_template_workouts_flagged(self, mongo_db):
        tw = list(mongo_db.workouts.find({"source": "template"}, {"_id": 0}).limit(20))
        if not tw:
            pytest.skip("no template-sourced workouts in DB to verify")
        for w in tw:
            assert w.get("needs_coach_review") is True, f"template workout not flagged: {w.get('date')}"
            v = w.get("variants") or {}
            assert set(v.keys()) >= {"green", "amber", "red"}
        print(f"[template] {len(tw)} template workouts checked")


# ---------------------------------------------------------------------------
# 6. Regression — /workouts/generate-month still works end-to-end
# ---------------------------------------------------------------------------
class TestWorkoutsGenerateMonthRegression:
    def test_generate_month_end_to_end(self, client_auth, mongo_db):
        uid = client_auth["user"]["id"]
        # Use the same roster the retry-worker path uses.
        rid = pytest.roster_id
        r = requests.post(
            f"{API}/workouts/generate-month",
            json={"roster_id": rid},
            headers=client_auth["headers"],
            timeout=60,
        )
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        deadline = time.time() + 220
        while time.time() < deadline:
            s = requests.get(f"{API}/workouts/job/{job_id}", headers=client_auth["headers"], timeout=30).json()
            if s.get("status") in ("done", "failed"):
                break
            time.sleep(4)
        assert s.get("status") == "done", f"generate-month did not complete: {s}"
        wks = s.get("workouts") or []
        assert wks, "no workouts produced by generate-month"
        # Schema check — this endpoint still writes source/needs_coach_review/variants
        for w in wks[:5]:
            assert "source" in w
            assert "needs_coach_review" in w
            assert "variants" in w
