"""
Iteration 71 — signup age gate + user account wipe verification.

Covers:
  * Case 2: signup with fresh email succeeds & login works; cleanup via soft-delete.
  * Case 3: previously-used email (post-wipe) can be re-registered.
  * Case 4: baseline accounts intact (Louis admin, client demo, preview sandbox, admin/coaches list).
  * Case 5: age_confirmed=false → 400; age_confirmed=true → 200.
"""

import os
import uuid
import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_BACKEND_URL")
    or os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")

LOUIS = {"email": "louis@crewfit.net", "password": "Louis123!"}
CLIENT = {"email": "client@crewfit.com", "password": "Client123!"}
COACH_LEGACY = {"email": "coach@crewfit.com", "password": "Coach123!"}


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def louis_token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json=LOUIS, timeout=30)
    assert r.status_code == 200, f"Louis login failed: {r.status_code} {r.text}"
    return r.json()["token"]


# ---------------------------------------------------------------------------
# Case 4 — baseline accounts intact
# ---------------------------------------------------------------------------
class TestBaselineAccounts:
    def test_louis_login_admin_coach(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json=LOUIS, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data
        u = data["user"]
        assert u["email"] == "louis@crewfit.net"
        assert u["role"] == "coach"
        assert u.get("is_admin") is True, f"Louis should be admin, got: {u}"

    def test_client_demo_login_active(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login", json=CLIENT, timeout=30)
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u["email"] == "client@crewfit.com"
        assert u["role"] == "client"
        assert str(u.get("status", "active")).lower() == "active"

    def test_sandbox_info(self, api, louis_token):
        r = api.get(
            f"{BASE_URL}/api/coach/preview/sandbox-info",
            headers={"Authorization": f"Bearer {louis_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # response may nest under different keys; check both flat + nested
        blob = data if "email" in data else data.get("user") or data.get("sandbox") or {}
        email = blob.get("email") or data.get("email")
        name = blob.get("name") or data.get("name")
        assert email == "preview@crewfit.test", f"sandbox-info payload={data}"
        assert name == "New Client Preview", f"sandbox-info payload={data}"

    def test_admin_coaches_contains_louis_and_legacy(self, api, louis_token):
        r = api.get(
            f"{BASE_URL}/api/admin/coaches",
            headers={"Authorization": f"Bearer {louis_token}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        coaches = payload if isinstance(payload, list) else payload.get("coaches") or payload.get("items") or []
        emails = {c.get("email") for c in coaches}
        assert "louis@crewfit.net" in emails, f"Louis missing: {emails}"
        assert "coach@crewfit.com" in emails, f"Legacy coach missing: {emails}"


# ---------------------------------------------------------------------------
# Case 5 — age_confirmed contract
# ---------------------------------------------------------------------------
class TestAgeGate:
    def test_signup_missing_age_rejected(self, api):
        uid = uuid.uuid4().hex[:8]
        r = api.post(
            f"{BASE_URL}/api/auth/signup",
            json={
                "email": f"test_noage_{uid}@example.com",
                "password": "Test123!",
                "name": "No Age",
                "role": "client",
                "age_confirmed": False,
            },
            timeout=30,
        )
        assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code}: {r.text}"

    def test_signup_with_age_true_succeeds(self, api, louis_token):
        uid = uuid.uuid4().hex[:8]
        email = f"test_agetrue_{uid}@example.com"
        r = api.post(
            f"{BASE_URL}/api/auth/signup",
            json={
                "email": email,
                "password": "Test123!",
                "name": "Age Confirmed",
                "role": "client",
                "age_confirmed": True,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data
        assert data["user"]["email"] == email
        # cleanup
        try:
            uid_created = data["user"]["id"]
            api.post(
                f"{BASE_URL}/api/admin/clients/{uid_created}/soft-delete",
                headers={"Authorization": f"Bearer {louis_token}"},
                json={"reason": "iter71 test cleanup"},
                timeout=30,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Case 2 — signup end-to-end
# ---------------------------------------------------------------------------
class TestSignupE2E:
    def test_signup_login_and_cleanup(self, api, louis_token):
        uid = uuid.uuid4().hex[:8]
        email = f"newtester_iter71_{uid}@example.com"
        password = "Test123!"

        # signup
        r = api.post(
            f"{BASE_URL}/api/auth/signup",
            json={
                "email": email,
                "password": password,
                "name": "New Tester Iter71",
                "role": "client",
                "age_confirmed": True,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data
        assert data["user"]["email"] == email
        user_id = data["user"]["id"]

        # login with new creds
        r2 = api.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["user"]["email"] == email

        # soft-delete as Louis
        r3 = api.post(
            f"{BASE_URL}/api/admin/clients/{user_id}/soft-delete",
            headers={"Authorization": f"Bearer {louis_token}"},
            json={"reason": "iter71 e2e cleanup"},
            timeout=30,
        )
        assert r3.status_code == 200, r3.text


# ---------------------------------------------------------------------------
# Case 3 — reused (previously wiped) emails registrable
# ---------------------------------------------------------------------------
class TestWipeReuse:
    @pytest.mark.parametrize(
        "email",
        [
            "test1@example.com",
            "deleted+af084794@crewfit.deleted",
        ],
    )
    def test_previously_used_email_registrable(self, api, louis_token, email):
        r = api.post(
            f"{BASE_URL}/api/auth/signup",
            json={
                "email": email,
                "password": "Test123!",
                "name": "Wiped Reuse",
                "role": "client",
                "age_confirmed": True,
            },
            timeout=30,
        )
        assert r.status_code == 200, f"expected reuse ok for {email}, got {r.status_code}: {r.text}"
        # Cleanup: hard-delete directly via Mongo so test stays idempotent
        # (soft-delete leaves email row and would break next run).
        try:
            import os
            from pymongo import MongoClient
            from dotenv import load_dotenv
            load_dotenv("/app/backend/.env")
            mc = MongoClient(os.environ["MONGO_URL"])
            mc[os.environ["DB_NAME"]].users.delete_one({"email": email.lower()})
            mc.close()
        except Exception as _e:
            print(f"cleanup warn: {_e}")
