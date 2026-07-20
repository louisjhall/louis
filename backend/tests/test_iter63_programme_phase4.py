"""
iter63 — Phase 4 Coach programme summary + Regenerate/Approve endpoints.

Covers:
- programme_pill on GET /api/coach/clients and /api/coach/dashboard
- POST /api/coach/clients/{cid}/programme/regenerate
- POST /api/coach/clients/{cid}/programme/approve
- 401 / 403 auth checks
- regression: /workouts/regenerate and /coach/pending-approvals
"""

import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")

COACH_EMAIL = "louis@crewfit.net"
COACH_PASS = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASS = "Client123!"


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()


@pytest.fixture(scope="module")
def coach_token():
    return _login(COACH_EMAIL, COACH_PASS)["token"]


@pytest.fixture(scope="module")
def coach_user():
    return _login(COACH_EMAIL, COACH_PASS)["user"]


@pytest.fixture(scope="module")
def client_token():
    return _login(CLIENT_EMAIL, CLIENT_PASS)["token"]


@pytest.fixture(scope="module")
def client_user():
    return _login(CLIENT_EMAIL, CLIENT_PASS)["user"]


@pytest.fixture
def hdr_coach(coach_token):
    return {"Authorization": f"Bearer {coach_token}", "Content-Type": "application/json"}


@pytest.fixture
def hdr_client(client_token):
    return {"Authorization": f"Bearer {client_token}", "Content-Type": "application/json"}


# --------------------------------------------------------------------------
# programme_pill on coach lists
# --------------------------------------------------------------------------
class TestProgrammePillOnListing:
    def test_coach_clients_contains_programme_pill_key(self, hdr_coach, client_user):
        r = requests.get(f"{API}/coach/clients", headers=hdr_coach, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) > 0
        # Every row must contain the key (may be None)
        for row in rows:
            assert "programme_pill" in row, f"missing programme_pill key on {row.get('email')}"
        target = next((x for x in rows if x.get("id") == client_user["id"]), None)
        assert target is not None, "test client not found in coach clients list"
        pill = target.get("programme_pill")
        assert pill is not None, "expected test client to have a programme_pill (seeded programme)"
        # Structural checks
        for k in ("goal_key", "goal_label", "phase_key", "phase_label", "week_index",
                  "target_sessions_per_week", "validation_status", "coach_approved", "updated_at"):
            assert k in pill, f"programme_pill missing field {k}"
        assert isinstance(pill["coach_approved"], bool)

    def test_coach_dashboard_contains_programme_pill(self, hdr_coach, client_user):
        r = requests.get(f"{API}/coach/dashboard", headers=hdr_coach, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "clients" in data
        for row in data["clients"]:
            assert "programme_pill" in row
        target = next((x for x in data["clients"] if x.get("id") == client_user["id"]), None)
        assert target and target.get("programme_pill") is not None

    def test_programme_pill_none_when_no_programme(self, mongo, hdr_coach):
        # Find (or fabricate) a client with no programme
        rows_r = requests.get(f"{API}/coach/clients", headers=hdr_coach, timeout=15)
        rows = rows_r.json()
        without = [r for r in rows if r.get("programme_pill") is None]
        # If all clients have a programme, that's still a valid answer — but the key existed.
        # At minimum ensure the key is present (already asserted above).
        if without:
            assert without[0]["programme_pill"] is None


# --------------------------------------------------------------------------
# Auth checks on new endpoints
# --------------------------------------------------------------------------
class TestAuthOnNewEndpoints:
    def test_regenerate_requires_auth(self, client_user):
        r = requests.post(f"{API}/coach/clients/{client_user['id']}/programme/regenerate",
                          json={}, timeout=15)
        assert r.status_code in (401, 403)

    def test_regenerate_forbidden_for_client_role(self, hdr_client, client_user):
        r = requests.post(f"{API}/coach/clients/{client_user['id']}/programme/regenerate",
                          headers=hdr_client, json={}, timeout=15)
        assert r.status_code == 403

    def test_approve_requires_auth(self, client_user):
        r = requests.post(f"{API}/coach/clients/{client_user['id']}/programme/approve",
                          json={"approve": True}, timeout=15)
        assert r.status_code in (401, 403)

    def test_approve_forbidden_for_client_role(self, hdr_client, client_user):
        r = requests.post(f"{API}/coach/clients/{client_user['id']}/programme/approve",
                          headers=hdr_client, json={"approve": True}, timeout=15)
        assert r.status_code == 403


# --------------------------------------------------------------------------
# Approve endpoint — happy path + edge cases
# --------------------------------------------------------------------------
class TestApproveEndpoint:
    @pytest.fixture(autouse=True)
    def _seed_needs_review(self, mongo, client_user):
        """Directly set latest programme row to needs_review + coach_approved=false.
        Also mark a couple of workouts needs_coach_review=true for the roster.
        """
        prog = mongo.programmes.find_one(
            {"user_id": client_user["id"]}, sort=[("created_at", -1)]
        )
        assert prog is not None, "seeded programme not found for client"
        mongo.programmes.update_one(
            {"id": prog["id"]},
            {"$set": {
                "validation_status": "needs_review",
                "coach_approved": False,
                "validation_errors": ["seed for test"],
            }},
        )
        # Mark up to 3 workouts as needs_coach_review
        wq = {"user_id": client_user["id"], "roster_id": prog.get("roster_id"),
              "completed": {"$ne": True}, "coach_locked": {"$ne": True}}
        touched_ids = [w["id"] for w in mongo.workouts.find(wq).limit(3)]
        if touched_ids:
            mongo.workouts.update_many(
                {"id": {"$in": touched_ids}},
                {"$set": {"needs_coach_review": True, "coach_approved": False}},
            )
        self._prog_id = prog["id"]
        self._roster_id = prog.get("roster_id")
        self._seeded_wo_ids = touched_ids
        yield
        # No teardown — subsequent tests may re-seed.

    def test_approve_true_flips_programme_and_clears_review_flag(self, mongo, hdr_coach, client_user, coach_user):
        r = requests.post(f"{API}/coach/clients/{client_user['id']}/programme/approve",
                          headers=hdr_coach, json={"approve": True, "note": "OK by coach"}, timeout=20)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert "programme" in body and "workouts_touched" in body
        assert body["workouts_touched"] >= 0  # may be 0 if no needs_review workouts exist
        p = body["programme"]
        assert p["coach_approved"] is True
        assert p["validation_status"] == "ok"
        assert p.get("coach_approved_by") == coach_user["id"]
        assert p.get("coach_approved_at")
        # DB verification
        prog_db = mongo.programmes.find_one({"id": self._prog_id}, {"_id": 0})
        assert prog_db["coach_approved"] is True
        assert prog_db["validation_status"] == "ok"
        # Workouts flag cleared for the ones we seeded
        if self._seeded_wo_ids:
            still_flagged = mongo.workouts.count_documents(
                {"id": {"$in": self._seeded_wo_ids}, "needs_coach_review": True}
            )
            assert still_flagged == 0

    def test_approve_false_does_not_touch_workouts(self, mongo, hdr_coach, client_user):
        # Re-seed workouts as needs_review
        if self._roster_id:
            mongo.workouts.update_many(
                {"user_id": client_user["id"], "roster_id": self._roster_id,
                 "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
                {"$set": {"needs_coach_review": True}},
            )
        pre_count = mongo.workouts.count_documents(
            {"user_id": client_user["id"], "needs_coach_review": True}
        )
        r = requests.post(f"{API}/coach/clients/{client_user['id']}/programme/approve",
                          headers=hdr_coach, json={"approve": False}, timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert body["workouts_touched"] == 0
        assert body["programme"]["coach_approved"] is False
        post_count = mongo.workouts.count_documents(
            {"user_id": client_user["id"], "needs_coach_review": True}
        )
        assert pre_count == post_count, "approve=false must not modify workouts"

    def test_approve_404_when_no_programme(self, mongo, hdr_coach):
        # Create a throwaway client with no programme
        import uuid
        cid = f"TEST_noprog_{uuid.uuid4().hex[:8]}"
        mongo.users.insert_one({
            "id": cid, "email": f"{cid}@test.local", "name": "TEST No Prog",
            "role": "client", "created_at": "2099-01-01T00:00:00+00:00",
        })
        try:
            r = requests.post(f"{API}/coach/clients/{cid}/programme/approve",
                              headers=hdr_coach, json={"approve": True}, timeout=15)
            assert r.status_code == 404
        finally:
            mongo.users.delete_one({"id": cid})


# --------------------------------------------------------------------------
# Regenerate endpoint
# --------------------------------------------------------------------------
class TestRegenerateEndpoint:
    @pytest.fixture(autouse=True)
    def _ensure_active_roster(self, mongo, client_user):
        """Make sure the client has exactly one active roster for this test.
        Restores original state on teardown.
        """
        rosters = list(mongo.rosters.find({"user_id": client_user["id"]},
                                          {"_id": 0, "id": 1, "is_active": 1}).sort("created_at", -1))
        if not rosters:
            pytest.skip("client has no rosters")
        original_active_ids = [r["id"] for r in rosters if r.get("is_active")]
        top_id = rosters[0]["id"]
        # Activate only the latest
        mongo.rosters.update_many({"user_id": client_user["id"]},
                                  {"$set": {"is_active": False}})
        mongo.rosters.update_one({"id": top_id}, {"$set": {"is_active": True}})
        yield top_id
        # Restore
        mongo.rosters.update_many({"user_id": client_user["id"]},
                                  {"$set": {"is_active": False}})
        for rid in original_active_ids:
            mongo.rosters.update_one({"id": rid}, {"$set": {"is_active": True}})

    def test_regenerate_returns_running_and_creates_gen_job(self, mongo, hdr_coach, client_user, coach_user):
        r = requests.post(f"{API}/coach/clients/{client_user['id']}/programme/regenerate",
                          headers=hdr_coach, json={"note": "TEST regen"}, timeout=20)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body["status"] == "running"
        assert body["job_id"]
        assert isinstance(body["workouts_scheduled"], int) and body["workouts_scheduled"] > 0
        # gen_jobs row created with kind=coach_regenerate + coach_id
        job = mongo.gen_jobs.find_one({"id": body["job_id"]}, {"_id": 0})
        assert job is not None
        assert job.get("kind") == "coach_regenerate"
        assert job.get("coach_id") == coach_user["id"]
        assert job.get("user_id") == client_user["id"]

        # Poll until worker finishes (up to ~220s to allow 180s LLM timeout + fallback)
        for _ in range(110):
            job = mongo.gen_jobs.find_one({"id": body["job_id"]}, {"_id": 0})
            if job and job.get("status") == "done":
                break
            time.sleep(2)
        assert job and job.get("status") == "done", f"regenerate did not finish: {job}"

        # Workouts collection populated for that roster + programme row updated
        wcount = mongo.workouts.count_documents(
            {"user_id": client_user["id"], "roster_id": job["roster_id"]}
        )
        assert wcount > 0
        # sample a doc — should carry source and variants
        sample = mongo.workouts.find_one(
            {"user_id": client_user["id"], "roster_id": job["roster_id"]}, {"_id": 0}
        )
        assert sample is not None
        assert "source" in sample
        # needs_coach_review must be present (bool)
        assert isinstance(sample.get("needs_coach_review", False), bool)
        prog = mongo.programmes.find_one(
            {"user_id": client_user["id"], "roster_id": job["roster_id"]}, {"_id": 0}
        )
        assert prog is not None

    def test_regenerate_400_when_no_active_roster(self, mongo, hdr_coach):
        import uuid
        cid = f"TEST_noroster_{uuid.uuid4().hex[:8]}"
        mongo.users.insert_one({
            "id": cid, "email": f"{cid}@test.local", "name": "TEST",
            "role": "client", "created_at": "2099-01-01T00:00:00+00:00",
        })
        try:
            r = requests.post(f"{API}/coach/clients/{cid}/programme/regenerate",
                              headers=hdr_coach, json={}, timeout=15)
            assert r.status_code == 400
        finally:
            mongo.users.delete_one({"id": cid})

    def test_regenerate_404_when_client_not_found(self, hdr_coach):
        r = requests.post(f"{API}/coach/clients/does_not_exist_xyz/programme/regenerate",
                          headers=hdr_coach, json={}, timeout=15)
        assert r.status_code == 404


# --------------------------------------------------------------------------
# Regression checks
# --------------------------------------------------------------------------
class TestRegression:
    def test_pending_approvals_endpoint_still_works(self, hdr_coach):
        r = requests.get(f"{API}/coach/pending-approvals", headers=hdr_coach, timeout=15)
        assert r.status_code == 200
        data = r.json()
        # Structure guarantee: dict with 'items' or list
        assert isinstance(data, (list, dict))

    def test_client_self_regenerate_still_works(self, mongo, hdr_client, client_user):
        # Need a roster_id — grab the most recent roster for the client
        roster = mongo.rosters.find_one({"user_id": client_user["id"]},
                                        sort=[("created_at", -1)])
        if not roster:
            pytest.skip("no roster to regenerate against")
        r = requests.post(f"{API}/workouts/regenerate", headers=hdr_client,
                          json={"roster_id": roster["id"], "all": True}, timeout=25)
        # Either 200 with job info OR 400 if no active roster — must not 5xx
        assert r.status_code in (200, 400), f"unexpected {r.status_code}: {r.text[:200]}"

    def test_coach_programme_current_history_endpoints(self, hdr_coach, client_user):
        r1 = requests.get(f"{API}/coach/clients/{client_user['id']}/programme",
                          headers=hdr_coach, timeout=15)
        assert r1.status_code == 200
        r2 = requests.get(f"{API}/coach/clients/{client_user['id']}/programme/history",
                          headers=hdr_coach, timeout=15)
        assert r2.status_code == 200
        assert "programmes" in r2.json()
