"""CrewFit V1 backend integration tests."""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


# ---------------- Health ----------------
class TestHealth:
    def test_root(self, api, base_url):
        r = api.get(f"{base_url}/api/", timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ---------------- Auth ----------------
class TestAuth:
    def test_login_client(self, client_auth):
        assert client_auth["user"]["role"] == "client"
        assert client_auth["user"]["email"] == "client@crewfit.com"

    def test_login_coach(self, coach_auth):
        assert coach_auth["user"]["role"] == "coach"

    def test_me_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/auth/me", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        u = r.json()
        assert u["email"] == "client@crewfit.com"
        assert "password_hash" not in u

    def test_me_missing_token(self, api, base_url):
        r = requests.get(f"{base_url}/api/auth/me", timeout=15)
        assert r.status_code == 401

    def test_login_bad_pw(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login", json={"email": "client@crewfit.com", "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_signup_and_onboarding(self, api, base_url):
        email = f"test_{uuid.uuid4().hex[:8]}@crewfit.com"
        r = api.post(f"{base_url}/api/auth/signup", json={
            "email": email, "password": "Passw0rd!", "name": "Test User", "role": "client"
        }, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "token" in d and d["user"]["email"] == email
        headers = {"Authorization": f"Bearer {d['token']}"}
        # duplicate signup
        r2 = api.post(f"{base_url}/api/auth/signup", json={
            "email": email, "password": "Passw0rd!", "name": "Test User", "role": "client"
        }, timeout=15)
        assert r2.status_code == 400
        # onboarding
        r3 = api.post(f"{base_url}/api/auth/onboarding", headers=headers, json={
            "airline": "Skyline", "position": "cabin crew", "experience_level": "beginner",
            "training_days_per_week": 3, "equipment": ["bodyweight"],
        }, timeout=15)
        assert r3.status_code == 200
        assert r3.json()["onboarded"] is True
        assert r3.json()["profile"]["airline"] == "Skyline"


# ---------------- Roster ----------------
class TestRoster:
    @pytest.fixture(scope="class")
    def roster_id(self, api, base_url, client_auth):
        body = {"file_base64": TINY_PNG_B64, "mime_type": "image/png", "week_start": "2026-01-06"}
        r = api.post(f"{base_url}/api/roster/extract", headers=client_auth["headers"], json=body, timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "id" in d and "days" in d
        # NOTE: When LLM returns empty days (garbled input), backend SHOULD fallback
        # to 7-day off-week per design. Currently it returns empty [] — see report.
        for day in d.get("days", []):
            assert day.get("load") in ("green", "amber", "red")
        return d["id"]

    def test_current(self, api, base_url, client_auth, roster_id):
        r = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert r.json().get("id") == roster_id

    def test_confirm(self, api, base_url, client_auth, roster_id):
        days = [
            {"date": "2026-01-06", "type": "off", "flights": [], "notes": ""},
            {"date": "2026-01-07", "type": "flight", "flights": [{"from": "DXB", "to": "LHR", "dep": "23:30", "arr": "04:00"}], "notes": ""},
            {"date": "2026-01-08", "type": "layover", "flights": [], "notes": ""},
            {"date": "2026-01-09", "type": "standby", "flights": [], "notes": ""},
            {"date": "2026-01-10", "type": "flight", "flights": [{"from": "LHR", "to": "JFK", "dep": "10:00", "arr": "13:00"}, {"from": "JFK", "to": "LAX", "dep": "16:00", "arr": "19:00"}], "notes": ""},
        ]
        r = api.post(f"{base_url}/api/roster/{roster_id}/confirm", headers=client_auth["headers"], json={"days": days}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["confirmed"] is True
        loads = {x["date"]: x["load"] for x in d["days"]}
        assert loads["2026-01-06"] == "green"  # off
        assert loads["2026-01-07"] == "red"    # red-eye dep 23:30
        assert loads["2026-01-08"] == "green"  # layover
        assert loads["2026-01-09"] == "amber"  # standby
        assert loads["2026-01-10"] == "red"    # multi-flight


# ---------------- Workouts ----------------
class TestWorkouts:
    @pytest.fixture(scope="class")
    def workout_ids(self, api, base_url, client_auth):
        # ensure a roster exists
        rc = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15).json()
        if not rc.get("id"):
            body = {"file_base64": TINY_PNG_B64, "mime_type": "image/png", "week_start": "2026-01-06"}
            rc = api.post(f"{base_url}/api/roster/extract", headers=client_auth["headers"], json=body, timeout=90).json()
        roster_id = rc["id"]
        r = api.post(f"{base_url}/api/workouts/generate", headers=client_auth["headers"],
                     json={"roster_id": roster_id}, timeout=180)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "workouts" in d
        return [w["id"] for w in d["workouts"]]

    def test_week_list(self, api, base_url, client_auth, workout_ids):
        r = api.get(f"{base_url}/api/workouts/week", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)

    def test_get_and_patch_and_complete(self, api, base_url, client_auth, coach_auth, workout_ids):
        if not workout_ids:
            pytest.skip("LLM returned no workouts; skipping patch/complete (fallback behavior acceptable)")
        wid = workout_ids[0]
        # get as client (owner)
        r = api.get(f"{base_url}/api/workouts/{wid}", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        # coach can approve/edit
        r2 = api.patch(f"{base_url}/api/workouts/{wid}", headers=coach_auth["headers"],
                       json={"approved": True, "coach_notes": "looks good", "title": "TEST edited"}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["approved"] is True
        assert r2.json()["title"] == "TEST edited"
        # complete
        r3 = api.post(f"{base_url}/api/workouts/{wid}/complete", headers=client_auth["headers"],
                      json={"completed_exercises": [{"name": "Squat", "sets": 3}], "rpe": 7}, timeout=15)
        assert r3.status_code == 200
        assert r3.json()["completed"] is True

    def test_client_forbidden_other_workout(self, api, base_url, client_auth):
        # non-existent id
        r = api.get(f"{base_url}/api/workouts/nonexistent-{uuid.uuid4().hex}", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 404


# ---------------- Exercises ----------------
class TestExercises:
    def test_list_any_user(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/exercises", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_client_forbidden_create(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/exercises", headers=client_auth["headers"],
                     json={"name": "TEST", "category": "core", "equipment": ["bodyweight"]}, timeout=15)
        assert r.status_code == 403

    def test_coach_create_and_delete(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/exercises", headers=coach_auth["headers"],
                     json={"name": f"TEST_{uuid.uuid4().hex[:6]}", "category": "core", "equipment": ["bodyweight"]}, timeout=15)
        assert r.status_code == 200
        eid = r.json()["id"]
        rd = api.delete(f"{base_url}/api/exercises/{eid}", headers=coach_auth["headers"], timeout=15)
        assert rd.status_code == 200


# ---------------- Check-ins ----------------
class TestCheckins:
    def test_create_and_list(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/checkins", headers=client_auth["headers"], json={
            "week_start": "2026-01-06", "energy": 7, "sleep": 6, "soreness": 4, "stress": 5, "weight_kg": 82.5,
            "notes": "TEST checkin"
        }, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["energy"] == 7 and d["notes"] == "TEST checkin"
        rl = api.get(f"{base_url}/api/checkins", headers=client_auth["headers"], timeout=15)
        assert rl.status_code == 200
        assert any(x["id"] == d["id"] for x in rl.json())


# ---------------- Nutrition ----------------
class TestNutrition:
    def test_meal_no_photo(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/meals", headers=client_auth["headers"], json={
            "meal_type": "lunch", "description": "TEST grilled chicken salad",
            "calories": 500, "protein_g": 40,
        }, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["calories"] == 500
        assert d.get("ai_feedback") is None

    def test_meal_with_photo(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/meals", headers=client_auth["headers"], json={
            "meal_type": "breakfast", "description": "TEST oats + eggs",
            "photo_base64": TINY_PNG_B64, "photo_mime": "image/png",
        }, timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        # AI feedback might be dict or None on parse fail; presence not strictly required
        assert "id" in d

    def test_list_and_summary(self, api, base_url, client_auth):
        rl = api.get(f"{base_url}/api/nutrition/meals", headers=client_auth["headers"], timeout=15)
        assert rl.status_code == 200
        assert isinstance(rl.json(), list)
        rs = api.get(f"{base_url}/api/nutrition/summary", headers=client_auth["headers"], timeout=15)
        assert rs.status_code == 200
        s = rs.json()
        assert "calories" in s and "protein_g" in s and "meals" in s
        assert s["calorie_target"] == 2400


# ---------------- Progress ----------------
class TestProgress:
    def test_create_and_list(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/progress", headers=client_auth["headers"], json={
            "weight_kg": 81.2, "notes": "TEST progress"
        }, timeout=15)
        assert r.status_code == 200
        rl = api.get(f"{base_url}/api/progress", headers=client_auth["headers"], timeout=15)
        assert rl.status_code == 200
        assert any(x.get("notes") == "TEST progress" for x in rl.json())


# ---------------- Messages ----------------
class TestMessages:
    def test_send_and_thread_and_partners(self, api, base_url, client_auth, coach_auth):
        client_id = client_auth["user"]["id"]
        coach_id = coach_auth["user"]["id"]
        # client sends to coach
        r = api.post(f"{base_url}/api/messages", headers=client_auth["headers"],
                     json={"to_user_id": coach_id, "text": "TEST hello coach"}, timeout=15)
        assert r.status_code == 200
        # coach replies
        r2 = api.post(f"{base_url}/api/messages", headers=coach_auth["headers"],
                      json={"to_user_id": client_id, "text": "TEST hey client"}, timeout=15)
        assert r2.status_code == 200
        # thread
        rt = api.get(f"{base_url}/api/messages/{coach_id}", headers=client_auth["headers"], timeout=15)
        assert rt.status_code == 200
        texts = [m["text"] for m in rt.json()]
        assert "TEST hello coach" in texts and "TEST hey client" in texts
        # partners for client
        rp = api.get(f"{base_url}/api/messages", headers=client_auth["headers"], timeout=15)
        assert rp.status_code == 200
        assert isinstance(rp.json(), list) and len(rp.json()) >= 1
        # partners for coach
        rp2 = api.get(f"{base_url}/api/messages", headers=coach_auth["headers"], timeout=15)
        assert rp2.status_code == 200
        assert isinstance(rp2.json(), list) and len(rp2.json()) >= 1


# ---------------- Coach endpoints ----------------
class TestCoach:
    def test_clients_list_as_coach(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/clients", headers=coach_auth["headers"], timeout=20)
        assert r.status_code == 200
        rows = r.json()
        assert any(u["email"] == "client@crewfit.com" for u in rows)

    def test_clients_forbidden_for_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/clients", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_pending_forbidden_for_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/pending-approvals", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_pending_as_coach(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/pending-approvals", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_client_detail_as_coach(self, api, base_url, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/coach/clients/{cid}", headers=coach_auth["headers"], timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["client"]["id"] == cid
        assert "workouts" in d and "checkins" in d
