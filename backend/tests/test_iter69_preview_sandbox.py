"""
iter69 — Persistent New Client Preview sandbox + Coach Kai removal.

Coverage:
  * POST /api/coach/preview/persistent — idempotent, returns sandbox token
  * POST /api/coach/preview/reset — wipes sandbox data, preserves user row
  * GET  /api/coach/preview/sandbox-info
  * GET  /api/coach/dashboard — includes preview_sandbox field
  * GET  /api/admin/coaches — legacy coach renamed, no "Kai"
  * Regression: preview/new-client, preview/impersonate, preview/demo-seed,
    coach/dashboard, coach/clients
  * Authz: 403 for client role on sandbox endpoints
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

LOUIS = {"email": "louis@crewfit.net", "password": "Louis123!"}
CLIENT = {"email": "client@crewfit.com", "password": "Client123!"}


# ---------- session / auth fixtures ----------
@pytest.fixture(scope="module")
def s():
    return requests.Session()


def _login(s, creds):
    r = s.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def louis_token(s):
    return _login(s, LOUIS)


@pytest.fixture(scope="module")
def client_token(s):
    return _login(s, CLIENT)


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ---------- POST /coach/preview/persistent ----------
class TestPersistent:
    def test_persistent_returns_expected_shape(self, s, louis_token):
        r = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert "token" in data and data["token"]
        assert data.get("kind") == "sandbox"
        assert data.get("expires_hours") == 2
        t = data.get("target", {})
        assert t.get("email") == "preview@crewfit.test"
        assert t.get("name") == "New Client Preview"
        assert t.get("role") == "client"
        assert t.get("id")

    def test_persistent_idempotent_same_id(self, s, louis_token):
        r1 = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15)
        r2 = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15)
        assert r1.status_code == 200 and r2.status_code == 200
        id1 = r1.json()["target"]["id"]
        id2 = r2.json()["target"]["id"]
        assert id1 == id2, f"sandbox id changed between calls: {id1} vs {id2}"

    def test_persistent_forbidden_for_client(self, s, client_token):
        r = s.post(f"{API}/coach/preview/persistent", headers=H(client_token), timeout=15)
        assert r.status_code == 403, f"expected 403 got {r.status_code}: {r.text[:200]}"


# ---------- GET /coach/preview/sandbox-info ----------
class TestSandboxInfo:
    def test_sandbox_info_shape(self, s, louis_token):
        # Ensure sandbox exists
        s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15)
        r = s.get(f"{API}/coach/preview/sandbox-info", headers=H(louis_token), timeout=15)
        assert r.status_code == 200, r.text[:200]
        sb = r.json().get("sandbox")
        assert sb is not None
        assert sb["email"] == "preview@crewfit.test"
        assert sb["name"] == "New Client Preview"
        for k in ("id", "onboarded", "current_step", "workouts_count", "has_roster"):
            assert k in sb, f"missing key {k} in sandbox-info"

    def test_sandbox_info_forbidden_for_client(self, s, client_token):
        r = s.get(f"{API}/coach/preview/sandbox-info", headers=H(client_token), timeout=15)
        assert r.status_code == 403


# ---------- POST /coach/preview/reset ----------
class TestReset:
    def test_reset_ok_and_preserves_id(self, s, louis_token):
        # Ensure sandbox exists
        p = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15).json()
        sandbox_id = p["target"]["id"]
        r = s.post(f"{API}/coach/preview/reset", headers=H(louis_token), json={"confirm": True}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        j = r.json()
        assert j.get("ok") is True
        assert j.get("sandbox_id") == sandbox_id
        assert "scrubbed" in j and isinstance(j["scrubbed"], dict)
        assert j.get("last_reset_at")

    def test_reset_makes_onboarded_false(self, s, louis_token):
        s.post(f"{API}/coach/preview/reset", headers=H(louis_token), json={"confirm": True}, timeout=30)
        info = s.get(f"{API}/coach/preview/sandbox-info", headers=H(louis_token), timeout=15).json()
        sb = info.get("sandbox")
        assert sb is not None
        assert sb["onboarded"] is False, f"expected onboarded=False after reset, got {sb.get('onboarded')}"
        assert sb["workouts_count"] == 0

    def test_reset_persistent_id_stable_after_reset(self, s, louis_token):
        before = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15).json()["target"]["id"]
        s.post(f"{API}/coach/preview/reset", headers=H(louis_token), json={"confirm": True}, timeout=30)
        after = s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15).json()["target"]["id"]
        assert before == after

    def test_reset_forbidden_for_client(self, s, client_token):
        r = s.post(f"{API}/coach/preview/reset", headers=H(client_token), json={"confirm": True}, timeout=15)
        assert r.status_code == 403


# ---------- GET /coach/dashboard preview_sandbox field ----------
class TestCoachDashboardSandboxField:
    def test_dashboard_has_preview_sandbox(self, s, louis_token):
        # ensure it exists
        s.post(f"{API}/coach/preview/persistent", headers=H(louis_token), timeout=15)
        r = s.get(f"{API}/coach/dashboard", headers=H(louis_token), timeout=20)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert "preview_sandbox" in data, "coach dashboard missing preview_sandbox field"
        sb = data["preview_sandbox"]
        assert sb is not None, "preview_sandbox should not be null after persistent has been called"
        assert sb.get("email") == "preview@crewfit.test"
        assert sb.get("name") == "New Client Preview"
        # Should NOT be in the main clients list (excluded via status filter)
        emails = {c.get("email") for c in data.get("clients", [])}
        assert "preview@crewfit.test" not in emails, "sandbox leaked into main clients list"

    def test_dashboard_still_returns_200_and_buckets(self, s, louis_token):
        r = s.get(f"{API}/coach/dashboard", headers=H(louis_token), timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "clients" in data and "counts" in data and "total" in data


# ---------- GET /admin/coaches — Kai removal ----------
class TestAdminCoachesNoKai:
    def test_admin_coaches_lists_louis_and_archived_legacy(self, s, louis_token):
        r = s.get(f"{API}/admin/coaches", headers=H(louis_token), timeout=15)
        assert r.status_code == 200, r.text[:300]
        coaches = r.json().get("coaches", [])
        assert len(coaches) >= 1
        louis = next((c for c in coaches if c.get("email") == "louis@crewfit.net"), None)
        assert louis is not None and louis.get("name") == "Louis Hall"
        legacy = next((c for c in coaches if c.get("email") == "coach@crewfit.com"), None)
        assert legacy is not None, "legacy coach@crewfit.com must still exist for backward-compat"
        assert legacy.get("name") == "Legacy Coach (archived)", f"legacy name should be renamed, got {legacy.get('name')}"
        assert legacy.get("status") == "archived", f"legacy status should be 'archived', got {legacy.get('status')}"

    def test_no_coach_named_kai(self, s, louis_token):
        r = s.get(f"{API}/admin/coaches", headers=H(louis_token), timeout=15)
        assert r.status_code == 200
        coaches = r.json().get("coaches", [])
        offenders = [c for c in coaches if "kai" in (c.get("name") or "").lower()]
        assert offenders == [], f"found Kai-named coaches: {offenders}"


# ---------- Regression: existing preview endpoints ----------
class TestRegressionExistingPreview:
    def test_preview_new_client_throwaway(self, s, louis_token):
        r = s.post(f"{API}/coach/preview/new-client", headers=H(louis_token), timeout=20)
        assert r.status_code == 200, f"new-client failed: {r.status_code} {r.text[:200]}"
        j = r.json()
        assert "token" in j
        assert j.get("target", {}).get("role") == "client"

    def test_preview_demo_seed(self, s, louis_token):
        r = s.post(f"{API}/coach/preview/demo-seed", headers=H(louis_token), timeout=30)
        assert r.status_code == 200, f"demo-seed failed: {r.status_code} {r.text[:300]}"

    def test_preview_impersonate_real_client(self, s, louis_token):
        # Find first real client
        clients = s.get(f"{API}/coach/clients", headers=H(louis_token), timeout=15).json()
        assert isinstance(clients, list) and len(clients) >= 1
        target_id = clients[0]["id"]
        r = s.post(f"{API}/coach/preview/impersonate",
                   headers=H(louis_token),
                   json={"target_user_id": target_id},
                   timeout=15)
        assert r.status_code == 200, f"impersonate failed: {r.status_code} {r.text[:300]}"
        assert "token" in r.json()

    def test_coach_clients_returns_200(self, s, louis_token):
        r = s.get(f"{API}/coach/clients", headers=H(louis_token), timeout=15)
        assert r.status_code == 200
        clients = r.json()
        assert isinstance(clients, list)
        emails = {c.get("email") for c in clients}
        assert "preview@crewfit.test" not in emails, "sandbox must not leak into /coach/clients"
