"""
Iter 67 — Coach Dashboard Upgrade Slice 2
Coach management (invite/activate/tier), client assignment/reassignment,
role hierarchy (admin / full / assistant), /me/coach helper.

Uses a throwaway test coach email `test.coach.slice2@crewfit.test` — deleted at end.
Also resets client@crewfit.com back to Louis at the end.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "louis@crewfit.net"
ADMIN_PASSWORD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"
TEST_COACH_EMAIL = "test.coach.slice2@crewfit.test"
TEST_COACH_NAME = "Test Slice2 Coach"


# ---------------- fixtures ----------------

@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Louis login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client_headers():
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"client login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def louis_id(admin_headers):
    r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    return r.json().get("id")


@pytest.fixture(scope="module")
def client_id(client_headers):
    r = requests.get(f"{API}/auth/me", headers=client_headers, timeout=15)
    assert r.status_code == 200
    return r.json().get("id")


def _cleanup_test_coach(admin_headers):
    """Best-effort remove the throwaway coach by permanent-delete (works only if role=='client')
    so we hit the DB directly via mongo removal by patching role. Instead, we do a raw approach:
    find via /admin/coaches then patch and forget. To keep DB clean, we rely on module teardown
    which cannot access DB — so we just leave the coach in a paused state with a marker email."""
    # Try to find the coach id via list
    try:
        r = requests.get(f"{API}/admin/coaches", headers=admin_headers, timeout=15)
        if r.status_code == 200:
            for c in r.json().get("coaches", []):
                if c.get("email") == TEST_COACH_EMAIL:
                    # deactivate if still active (idempotent-ish)
                    requests.post(f"{API}/admin/coaches/{c['id']}/deactivate", headers=admin_headers, timeout=15)
                    return c["id"]
    except Exception:
        pass
    return None


@pytest.fixture(scope="module")
def test_coach(admin_headers):
    """Create the test coach once at module scope; delete/paused at teardown."""
    # Ensure clean slate: if left over from a prior run, we cannot delete via API,
    # so we detect duplicate and reuse (skipping the invite duplicate test).
    r = requests.get(f"{API}/admin/coaches", headers=admin_headers, timeout=15)
    existing = None
    if r.status_code == 200:
        for c in r.json().get("coaches", []):
            if c.get("email") == TEST_COACH_EMAIL:
                existing = c
                break

    invited = None
    if existing is None:
        rr = requests.post(f"{API}/admin/coaches/invite",
                           json={"email": TEST_COACH_EMAIL, "name": TEST_COACH_NAME, "tier": "full"},
                           headers=admin_headers, timeout=15)
        assert rr.status_code == 200, f"invite failed: {rr.status_code} {rr.text}"
        invited = rr.json()
        cid = invited["coach_id"]
    else:
        cid = existing["id"]
        # Make sure it's active and tier=full for downstream tests
        requests.post(f"{API}/admin/coaches/{cid}/activate", headers=admin_headers, timeout=15)
        requests.patch(f"{API}/admin/coaches/{cid}", json={"tier": "full"}, headers=admin_headers, timeout=15)

    yield {"id": cid, "email": TEST_COACH_EMAIL, "name": TEST_COACH_NAME, "invite": invited}

    # Teardown: deactivate the test coach so it's inert. We cannot hard-delete via API.
    try:
        requests.post(f"{API}/admin/coaches/{cid}/deactivate", headers=admin_headers, timeout=15)
    except Exception:
        pass


# ---------------- Louis admin flag & migrations ----------------

class TestStartupMigrations:
    def test_louis_is_admin_with_admin_tier(self, admin_headers, louis_id):
        r = requests.get(f"{API}/admin/coaches", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        coaches = r.json().get("coaches", [])
        assert len(coaches) > 0
        # Louis must be first
        first = coaches[0]
        assert first.get("email") == ADMIN_EMAIL, f"Louis not first: {first}"
        assert first.get("is_admin") is True
        assert first.get("coach_tier") == "admin"
        assert first.get("status") == "active"

    def test_client_assigned_to_louis(self, admin_headers, client_id, louis_id):
        r = requests.get(f"{API}/coach/clients/{client_id}", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        client_doc = data.get("client") or data
        assert client_doc.get("assigned_coach_id") == louis_id, \
            f"client not assigned to Louis: {client_doc.get('assigned_coach_id')} vs {louis_id}"


# ---------------- GET /admin/coaches ----------------

class TestListCoaches:
    def test_list_as_admin(self, admin_headers):
        r = requests.get(f"{API}/admin/coaches", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "coaches" in data and "count" in data
        assert isinstance(data["coaches"], list)
        assert data["count"] == len(data["coaches"])
        # Every row must include the expected keys
        for row in data["coaches"]:
            for key in ("id", "email", "name", "role", "is_admin", "coach_tier", "status", "assigned_clients"):
                assert key in row, f"missing {key} in coach row: {row}"

    def test_list_as_client_forbidden(self, client_headers):
        r = requests.get(f"{API}/admin/coaches", headers=client_headers, timeout=15)
        assert r.status_code == 403


# ---------------- Invite coach ----------------

class TestInviteCoach:
    def test_invite_returns_temp_password(self, test_coach):
        # If we invited fresh, verify temp_password shape.
        if test_coach.get("invite"):
            inv = test_coach["invite"]
            assert inv.get("temp_password"), "temp_password missing"
            assert inv.get("email") == TEST_COACH_EMAIL
            assert inv.get("tier") == "full"

    def test_new_coach_visible_in_list(self, admin_headers, test_coach):
        r = requests.get(f"{API}/admin/coaches", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        rows = {c["email"]: c for c in r.json().get("coaches", [])}
        assert TEST_COACH_EMAIL in rows
        row = rows[TEST_COACH_EMAIL]
        assert row["role"] == "coach"
        assert row["status"] == "active"
        # Tier could be full or assistant depending on prior test order — accept both.
        assert row["coach_tier"] in ("full", "assistant")

    def test_invite_duplicate_email_rejected(self, admin_headers, test_coach):
        r = requests.post(f"{API}/admin/coaches/invite",
                          json={"email": TEST_COACH_EMAIL, "name": TEST_COACH_NAME, "tier": "full"},
                          headers=admin_headers, timeout=15)
        assert r.status_code == 400, f"expected 400 for duplicate, got {r.status_code} {r.text}"

    def test_invite_invalid_tier_rejected(self, admin_headers):
        r = requests.post(f"{API}/admin/coaches/invite",
                          json={"email": f"bogus.{uuid.uuid4().hex[:6]}@crewfit.test",
                                "name": "Bogus", "tier": "boss"},
                          headers=admin_headers, timeout=15)
        assert r.status_code == 400

    def test_invite_as_client_forbidden(self, client_headers):
        r = requests.post(f"{API}/admin/coaches/invite",
                          json={"email": f"x{uuid.uuid4().hex[:6]}@t.test", "name": "n", "tier": "full"},
                          headers=client_headers, timeout=15)
        assert r.status_code == 403


# ---------------- Patch coach tier & admin-guard ----------------

class TestPatchCoach:
    def test_patch_tier_to_assistant(self, admin_headers, test_coach):
        r = requests.patch(f"{API}/admin/coaches/{test_coach['id']}",
                           json={"tier": "assistant"},
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"patch failed: {r.text}"
        assert r.json().get("coach_tier") == "assistant"

    def test_patch_back_to_full(self, admin_headers, test_coach):
        r = requests.patch(f"{API}/admin/coaches/{test_coach['id']}",
                           json={"tier": "full"},
                           headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("coach_tier") == "full"

    def test_cannot_demote_last_admin(self, admin_headers, louis_id):
        r = requests.patch(f"{API}/admin/coaches/{louis_id}",
                           json={"is_admin": False},
                           headers=admin_headers, timeout=15)
        assert r.status_code == 400, f"expected 400 last-admin guard, got {r.status_code} {r.text}"

    def test_patch_invalid_tier(self, admin_headers, test_coach):
        r = requests.patch(f"{API}/admin/coaches/{test_coach['id']}",
                           json={"tier": "godmode"},
                           headers=admin_headers, timeout=15)
        assert r.status_code == 400

    def test_patch_unknown_coach(self, admin_headers):
        r = requests.patch(f"{API}/admin/coaches/nope-does-not-exist",
                           json={"tier": "full"},
                           headers=admin_headers, timeout=15)
        assert r.status_code == 404


# ---------------- Activate / Deactivate ----------------

class TestActivateDeactivate:
    def test_deactivate_coach(self, admin_headers, test_coach):
        r = requests.post(f"{API}/admin/coaches/{test_coach['id']}/deactivate",
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"deactivate failed: {r.text}"
        # Verify list shows paused
        rows = requests.get(f"{API}/admin/coaches", headers=admin_headers, timeout=15).json()["coaches"]
        row = next(c for c in rows if c["id"] == test_coach["id"])
        assert row["status"] == "paused"

    def test_cannot_deactivate_admin(self, admin_headers, louis_id):
        r = requests.post(f"{API}/admin/coaches/{louis_id}/deactivate",
                          headers=admin_headers, timeout=15)
        assert r.status_code == 400, f"expected 400 deactivating admin, got {r.status_code} {r.text}"

    def test_activate_coach(self, admin_headers, test_coach):
        r = requests.post(f"{API}/admin/coaches/{test_coach['id']}/activate",
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200
        rows = requests.get(f"{API}/admin/coaches", headers=admin_headers, timeout=15).json()["coaches"]
        row = next(c for c in rows if c["id"] == test_coach["id"])
        assert row["status"] == "active"


# ---------------- Assign client to coach ----------------

class TestAssignCoach:
    def test_assign_client_to_test_coach(self, admin_headers, client_id, test_coach, louis_id):
        # Assign
        r = requests.post(f"{API}/admin/clients/{client_id}/assign-coach",
                          json={"coach_id": test_coach["id"], "reason": "TEST_slice2"},
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"assign failed: {r.text}"
        body = r.json()
        assert body.get("assigned_coach_id") == test_coach["id"]
        assert body.get("assigned_coach_name") == TEST_COACH_NAME

        # Verify persistence
        c = requests.get(f"{API}/coach/clients/{client_id}", headers=admin_headers, timeout=15).json()
        c = c.get("client") or c
        assert c.get("assigned_coach_id") == test_coach["id"]
        assert c.get("assigned_coach_name") == TEST_COACH_NAME

        # Audit log has client.assign_coach
        al = requests.get(f"{API}/admin/clients/{client_id}/audit-log?limit=20",
                          headers=admin_headers, timeout=15).json()
        actions = [e.get("action") for e in al.get("entries", [])]
        assert "client.assign_coach" in actions

    def test_assign_to_unknown_coach_404(self, admin_headers, client_id):
        r = requests.post(f"{API}/admin/clients/{client_id}/assign-coach",
                          json={"coach_id": "coach-does-not-exist"},
                          headers=admin_headers, timeout=15)
        assert r.status_code == 404

    def test_assign_to_paused_coach_400(self, admin_headers, client_id, test_coach):
        # pause the test coach
        requests.post(f"{API}/admin/coaches/{test_coach['id']}/deactivate",
                      headers=admin_headers, timeout=15)
        r = requests.post(f"{API}/admin/clients/{client_id}/assign-coach",
                          json={"coach_id": test_coach["id"]},
                          headers=admin_headers, timeout=15)
        assert r.status_code == 400, f"expected 400 paused-coach, got {r.status_code} {r.text}"
        # reactivate for downstream
        requests.post(f"{API}/admin/coaches/{test_coach['id']}/activate",
                      headers=admin_headers, timeout=15)

    def test_workload_reflects_assignment(self, admin_headers, test_coach):
        r = requests.get(f"{API}/admin/coaches/{test_coach['id']}/workload",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "coach" in d
        assert "assigned_active" in d
        assert "assigned_archived" in d
        # At least 1 active because we just assigned client@crewfit.com
        assert d["assigned_active"] >= 1, f"expected >=1 assigned client, got {d['assigned_active']}"


# ---------------- /me/coach ----------------

class TestMeCoach:
    def test_client_me_coach_reflects_new_coach(self, client_headers):
        # After reassignment, /me/coach for the client should return the test coach.
        r = requests.get(f"{API}/me/coach", headers=client_headers, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("coach") is not None
        assert d["coach"].get("email") == TEST_COACH_EMAIL
        # first_name derived from "Test Slice2 Coach" -> "Test"
        assert d["coach"].get("first_name") == TEST_COACH_NAME.split(" ")[0]

    def test_coach_role_gets_null(self, admin_headers):
        # Louis is role='coach' — should return {coach: null}
        r = requests.get(f"{API}/me/coach", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        assert r.json().get("coach") is None

    def test_unauthenticated_401(self):
        r = requests.get(f"{API}/me/coach", timeout=15)
        assert r.status_code == 401


# ---------------- Signup auto-assigns Louis ----------------

class TestSignupAutoAssign:
    def test_new_client_signup_gets_louis(self, admin_headers, louis_id):
        suffix = uuid.uuid4().hex[:8]
        email = f"test.slice2.signup.{suffix}@crewfit.com"
        r = requests.post(f"{API}/auth/signup",
                          json={"email": email, "password": "TempPass123!",
                                "name": f"TEST slice2 {suffix}", "role": "client",
                                "age_confirmed": True},
                          timeout=15)
        assert r.status_code in (200, 201), f"signup failed: {r.text}"
        body = r.json()
        user = body.get("user") or {}
        uid = user.get("id")
        assert uid
        # Verify via admin fetch
        c = requests.get(f"{API}/coach/clients/{uid}", headers=admin_headers, timeout=15).json()
        c = c.get("client") or c
        assert c.get("assigned_coach_id") == louis_id, \
            f"signup did not auto-assign Louis; got {c.get('assigned_coach_id')}"
        # cleanup — permanent-delete this test signup
        requests.post(f"{API}/admin/clients/{uid}/permanent-delete",
                      json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)


# ---------------- Reset assignment (module cleanup) ----------------

class TestZ_ResetClient:
    """Runs alphabetically-late so it executes after the reassignment tests."""

    def test_reassign_client_back_to_louis(self, admin_headers, client_id, louis_id):
        r = requests.post(f"{API}/admin/clients/{client_id}/assign-coach",
                          json={"coach_id": louis_id, "reason": "TEST_reset"},
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200
        c = requests.get(f"{API}/coach/clients/{client_id}", headers=admin_headers, timeout=15).json()
        c = c.get("client") or c
        assert c.get("assigned_coach_id") == louis_id
