"""
Iter 66 — Coach Dashboard Upgrade Slice 1
Admin lifecycle endpoints: archive/pause/restore/soft-delete/permanent-delete,
audit log, coach client filtering, admin permission gating, login gating.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "louis@crewfit.net"
ADMIN_PASSWORD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"


# ---------------- Helpers / fixtures ----------------

@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Louis login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("token"), "no token in Louis login response"
    return data["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client_headers():
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"client login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


def _register_temp_user() -> dict:
    """Register a fresh throwaway client and return its details incl. id/password."""
    suffix = uuid.uuid4().hex[:8]
    email = f"test.iter66.{suffix}@crewfit.com"
    password = "TempPass123!"
    payload = {
        "email": email,
        "password": password,
        "name": f"TEST iter66 {suffix}",
        "role": "client",
        "age_confirmed": True,
    }
    r = requests.post(f"{API}/auth/signup", json=payload, timeout=15)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    body = r.json()
    user = body.get("user") or body
    uid = user.get("id")
    assert uid, f"no user id in register response: {body}"
    return {"id": uid, "email": email, "password": password, "token": body.get("token")}


def _get_user_status(admin_headers: dict, uid: str) -> dict:
    r = requests.get(f"{API}/coach/clients/{uid}", headers=admin_headers, timeout=15)
    assert r.status_code == 200, f"get client failed: {r.status_code} {r.text}"
    data = r.json()
    # /coach/clients/{id} wraps user under "client"
    return data.get("client") or data


# ---------------- Louis admin flag ----------------

class TestLouisAdmin:
    """Verify Louis has is_admin=true after startup."""

    def test_louis_can_hit_admin_endpoint(self, admin_headers):
        # If Louis is admin, global audit-log should return 200
        r = requests.get(f"{API}/admin/audit-log?limit=1", headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"expected admin access for Louis, got {r.status_code} {r.text}"

    def test_louis_me_shows_admin(self, admin_headers):
        r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        me = r.json()
        assert me.get("is_admin") is True or me.get("role") == "admin", f"Louis not admin: {me}"


# ---------------- Admin gating ----------------

class TestAdminGating:
    """Non-admin (client) must be forbidden from lifecycle endpoints."""

    def test_client_cannot_archive(self, client_headers):
        # Use a random uuid; permission check happens before body work in FastAPI dep resolution
        r = requests.post(f"{API}/admin/clients/whatever/archive",
                         json={"mode": "archive_only"}, headers=client_headers, timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"

    def test_client_cannot_view_audit_log(self, client_headers):
        r = requests.get(f"{API}/admin/clients/whatever/audit-log", headers=client_headers, timeout=15)
        assert r.status_code == 403


# ---------------- Archive / Pause / Restore ----------------

class TestArchiveRestore:

    def test_archive_only_keeps_login_active(self, admin_headers):
        u = _register_temp_user()
        try:
            # Archive with archive_only
            r = requests.post(f"{API}/admin/clients/{u['id']}/archive",
                             json={"mode": "archive_only", "reason": "TEST_archive_only"},
                             headers=admin_headers, timeout=15)
            assert r.status_code == 200, f"archive failed: {r.text}"
            assert r.json().get("status") == "archived"

            # Confirm doc state
            snap = _get_user_status(admin_headers, u["id"])
            assert snap.get("status") == "archived", f"status not archived: {snap.get('status')}"

            # archived client CAN still log in
            login = requests.post(f"{API}/auth/login",
                                  json={"email": u["email"], "password": u["password"]}, timeout=15)
            assert login.status_code == 200, f"archived user login should succeed, got {login.status_code} {login.text}"

            # Restore
            r2 = requests.post(f"{API}/admin/clients/{u['id']}/restore",
                              json={"reason": "TEST_restore"}, headers=admin_headers, timeout=15)
            assert r2.status_code == 200, f"restore failed: {r2.text}"
            assert r2.json().get("status") == "active"
            snap2 = _get_user_status(admin_headers, u["id"])
            assert snap2.get("status") == "active"
        finally:
            # cleanup — permanent delete anonymises
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)

    def test_archive_pause_blocks_login(self, admin_headers):
        u = _register_temp_user()
        try:
            r = requests.post(f"{API}/admin/clients/{u['id']}/archive",
                             json={"mode": "archive_pause", "reason": "TEST_pause"},
                             headers=admin_headers, timeout=15)
            assert r.status_code == 200
            assert r.json().get("status") == "paused"

            snap = _get_user_status(admin_headers, u["id"])
            assert snap.get("status") == "paused"

            login = requests.post(f"{API}/auth/login",
                                  json={"email": u["email"], "password": u["password"]}, timeout=15)
            assert login.status_code == 403, f"paused user login should be forbidden, got {login.status_code}"
            assert "unavailable" in login.text.lower() or "contact" in login.text.lower()

            # Restore paused → active
            r2 = requests.post(f"{API}/admin/clients/{u['id']}/restore",
                              json={}, headers=admin_headers, timeout=15)
            assert r2.status_code == 200
            assert _get_user_status(admin_headers, u["id"]).get("status") == "active"
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)

    def test_restore_active_client_rejected(self, admin_headers):
        u = _register_temp_user()
        try:
            r = requests.post(f"{API}/admin/clients/{u['id']}/restore",
                             json={}, headers=admin_headers, timeout=15)
            assert r.status_code == 400, f"restore of active should 400, got {r.status_code}"
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)

    def test_invalid_archive_mode(self, admin_headers):
        u = _register_temp_user()
        try:
            r = requests.post(f"{API}/admin/clients/{u['id']}/archive",
                             json={"mode": "bogus"}, headers=admin_headers, timeout=15)
            assert r.status_code == 400
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)


# ---------------- Soft delete ----------------

class TestSoftDelete:

    def test_soft_delete_blocks_login(self, admin_headers):
        u = _register_temp_user()
        try:
            r = requests.post(f"{API}/admin/clients/{u['id']}/soft-delete",
                             json={"reason": "TEST_soft"}, headers=admin_headers, timeout=15)
            assert r.status_code == 200, f"soft-delete failed: {r.text}"
            assert r.json().get("status") == "deletion_pending"

            snap = _get_user_status(admin_headers, u["id"])
            assert snap.get("status") == "deletion_pending"

            login = requests.post(f"{API}/auth/login",
                                  json={"email": u["email"], "password": u["password"]}, timeout=15)
            assert login.status_code == 403

            # restore from deletion_pending works
            r2 = requests.post(f"{API}/admin/clients/{u['id']}/restore", json={},
                              headers=admin_headers, timeout=15)
            assert r2.status_code == 200
            assert _get_user_status(admin_headers, u["id"]).get("status") == "active"
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)


# ---------------- Permanent delete ----------------

class TestPermanentDelete:

    def test_missing_confirmation_rejected(self, admin_headers):
        u = _register_temp_user()
        try:
            r = requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                             json={"confirmation": "not-delete"}, headers=admin_headers, timeout=15)
            assert r.status_code == 400
            r2 = requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                              json={}, headers=admin_headers, timeout=15)
            assert r2.status_code in (400, 422)
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)

    def test_permanent_delete_anonymises(self, admin_headers):
        u = _register_temp_user()
        r = requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE", "reason": "TEST_perm"},
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, f"perm-delete failed: {r.text}"
        assert r.json().get("status") == "deleted"

        # Verify anonymisation
        snap = _get_user_status(admin_headers, u["id"])
        assert snap.get("status") == "deleted"
        assert (snap.get("email") or "").startswith("deleted+"), f"email not anonymised: {snap.get('email')}"
        name = snap.get("name") or ""
        assert name.startswith("[deleted client"), f"name not anonymised: {name}"

        # deleted user cannot login
        login = requests.post(f"{API}/auth/login",
                              json={"email": u["email"], "password": u["password"]}, timeout=15)
        assert login.status_code in (401, 403), f"deleted user login should fail, got {login.status_code}"


# ---------------- Admin-account guard ----------------

class TestCannotModifyAdmin:

    def _louis_id(self, admin_headers):
        r = requests.get(f"{API}/auth/me", headers=admin_headers, timeout=15)
        return r.json().get("id")

    def test_cannot_archive_admin(self, admin_headers):
        lid = self._louis_id(admin_headers)
        r = requests.post(f"{API}/admin/clients/{lid}/archive",
                         json={"mode": "archive_only"}, headers=admin_headers, timeout=15)
        assert r.status_code == 400, f"archiving admin should 400, got {r.status_code}"

    def test_cannot_soft_delete_admin(self, admin_headers):
        lid = self._louis_id(admin_headers)
        r = requests.post(f"{API}/admin/clients/{lid}/soft-delete",
                         json={}, headers=admin_headers, timeout=15)
        assert r.status_code == 400

    def test_cannot_permanent_delete_admin(self, admin_headers):
        lid = self._louis_id(admin_headers)
        r = requests.post(f"{API}/admin/clients/{lid}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)
        assert r.status_code == 400


# ---------------- Audit log ----------------

class TestAuditLog:

    def test_audit_captures_lifecycle_actions(self, admin_headers):
        u = _register_temp_user()
        try:
            requests.post(f"{API}/admin/clients/{u['id']}/archive",
                         json={"mode": "archive_only", "reason": "audit_a"},
                         headers=admin_headers, timeout=15)
            requests.post(f"{API}/admin/clients/{u['id']}/restore",
                         json={"reason": "audit_r"}, headers=admin_headers, timeout=15)
            requests.post(f"{API}/admin/clients/{u['id']}/soft-delete",
                         json={"reason": "audit_s"}, headers=admin_headers, timeout=15)
            requests.post(f"{API}/admin/clients/{u['id']}/restore",
                         json={"reason": "audit_r2"}, headers=admin_headers, timeout=15)

            r = requests.get(f"{API}/admin/clients/{u['id']}/audit-log?limit=50",
                            headers=admin_headers, timeout=15)
            assert r.status_code == 200
            data = r.json()
            entries = data.get("entries", [])
            actions = [e.get("action") for e in entries]
            assert "client.archive" in actions
            assert "client.restore" in actions
            assert "client.soft_delete" in actions

            # First entry should be most recent (client.restore) — verify shape
            first = entries[0]
            for key in ("actor_id", "actor_name", "action", "target_user_id", "timestamp"):
                assert key in first, f"missing {key} in audit entry: {first}"
            assert first["target_user_id"] == u["id"]
            # before/after should be populated on lifecycle transitions
            assert first.get("before") is not None
            assert first.get("after") is not None
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)

    def test_global_audit_log(self, admin_headers):
        r = requests.get(f"{API}/admin/audit-log?limit=50", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "entries" in data
        assert isinstance(data["entries"], list)

    def test_global_audit_filter_by_action(self, admin_headers):
        # ensure at least one archive event exists
        u = _register_temp_user()
        try:
            requests.post(f"{API}/admin/clients/{u['id']}/archive",
                         json={"mode": "archive_only"}, headers=admin_headers, timeout=15)
            r = requests.get(f"{API}/admin/audit-log?action=client.archive&limit=20",
                            headers=admin_headers, timeout=15)
            assert r.status_code == 200
            entries = r.json().get("entries", [])
            assert all(e.get("action") == "client.archive" for e in entries)
            assert len(entries) >= 1
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)


# ---------------- Coach client listing filters ----------------

class TestCoachClientListingFilter:

    def test_default_excludes_archived(self, admin_headers):
        u = _register_temp_user()
        try:
            requests.post(f"{API}/admin/clients/{u['id']}/archive",
                         json={"mode": "archive_only"}, headers=admin_headers, timeout=15)

            r_default = requests.get(f"{API}/coach/clients", headers=admin_headers, timeout=15)
            assert r_default.status_code == 200
            default_ids = {c.get("id") for c in r_default.json()}
            assert u["id"] not in default_ids, "archived client should be hidden by default"

            r_include = requests.get(f"{API}/coach/clients?include_archived=true",
                                     headers=admin_headers, timeout=15)
            assert r_include.status_code == 200
            include_ids = {c.get("id") for c in r_include.json()}
            assert u["id"] in include_ids

            r_status = requests.get(f"{API}/coach/clients?status=archived",
                                    headers=admin_headers, timeout=15)
            assert r_status.status_code == 200
            status_ids = {c.get("id") for c in r_status.json()}
            assert u["id"] in status_ids
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)

    def test_dashboard_default_excludes_archived(self, admin_headers):
        u = _register_temp_user()
        try:
            requests.post(f"{API}/admin/clients/{u['id']}/archive",
                         json={"mode": "archive_only"}, headers=admin_headers, timeout=15)

            r_default = requests.get(f"{API}/coach/dashboard", headers=admin_headers, timeout=15)
            assert r_default.status_code == 200
            d = r_default.json()
            default_ids = {c.get("id") for c in d.get("clients", [])}
            assert u["id"] not in default_ids

            r_include = requests.get(f"{API}/coach/dashboard?include_archived=true",
                                     headers=admin_headers, timeout=15)
            assert r_include.status_code == 200
            include_ids = {c.get("id") for c in r_include.json().get("clients", [])}
            assert u["id"] in include_ids
        finally:
            requests.post(f"{API}/admin/clients/{u['id']}/permanent-delete",
                         json={"confirmation": "DELETE"}, headers=admin_headers, timeout=15)

    def test_seeded_client_still_visible(self, admin_headers):
        """Regression: client@crewfit.com must still show up in default listing."""
        r = requests.get(f"{API}/coach/clients", headers=admin_headers, timeout=15)
        assert r.status_code == 200
        emails = [c.get("email") for c in r.json()]
        assert CLIENT_EMAIL in emails, f"seeded client missing from default list"
