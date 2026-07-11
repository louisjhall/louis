"""Iteration 43 follow-up tests — verify two fixes:

1. POST /api/admin/sentry/test-error returns ok:false when SENTRY_DSN unset.
2. POST /api/gdpr/delete-account no longer scrubs PII (email/name); cancel
   restores full functionality and login still works.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")


# ---------- Fix 1: Sentry test-error ----------
class TestSentryTestErrorFix:
    def test_sentry_test_error_returns_ok_false_when_dsn_unset(self, api, coach_auth):
        # Coach is admin per test_credentials.md
        r = api.post(f"{BASE_URL}/api/admin/sentry/test-error",
                     headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        # If DSN is actually unset in preview env we expect ok:false + note about DSN
        # Check backend env
        dsn = os.environ.get("SENTRY_DSN")
        if not dsn:
            assert body.get("ok") is False, f"expected ok=false when DSN unset, got: {body}"
            note = body.get("note", "")
            assert "SENTRY_DSN" in note or "DSN" in note, f"note should mention DSN: {note}"
        else:
            # DSN set path — just ensure endpoint responds structurally
            assert "ok" in body


# ---------- Fix 2: GDPR delete/cancel cycle preserves PII ----------
class TestGdprDeleteCancelPreservesPII:

    @pytest.fixture(scope="class")
    def fresh_user(self, api):
        email = f"gdpr-verify+{int(time.time())}-{uuid.uuid4().hex[:6]}@test.com"
        password = "TestPass123!"
        name = "GDPR Verify User"
        r = api.post(f"{BASE_URL}/api/auth/signup", json={
            "email": email, "password": password, "name": name,
            "role": "client", "age_confirmed": True,
        }, timeout=30)
        assert r.status_code == 200, f"signup failed: {r.status_code} {r.text}"
        data = r.json()
        return {
            "email": email, "password": password, "name": name,
            "token": data["token"], "user": data["user"],
            "headers": {"Authorization": f"Bearer {data['token']}"},
        }

    def test_1_signup_ok(self, fresh_user):
        assert fresh_user["user"]["email"] == fresh_user["email"]
        assert fresh_user["user"]["name"] == fresh_user["name"]

    def test_2_delete_account_does_not_scrub_pii(self, api, fresh_user):
        r = api.post(f"{BASE_URL}/api/gdpr/delete-account",
                     json={"confirmation": "DELETE"},
                     headers=fresh_user["headers"], timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert "scheduled_purge_at" in body

    def test_3_auth_me_still_has_original_pii_and_deleted_at(self, api, fresh_user):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers=fresh_user["headers"], timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        me = r.json()
        # Email and name must be intact
        assert me.get("email") == fresh_user["email"], f"email was scrubbed: {me.get('email')}"
        assert me.get("name") == fresh_user["name"], f"name was scrubbed: {me.get('name')}"
        # deleted_at must be set
        assert me.get("deleted_at"), f"deleted_at not set: {me}"
        assert me.get("purge_at"), f"purge_at not set: {me}"

    def test_4_cancel_deletion(self, api, fresh_user):
        r = api.post(f"{BASE_URL}/api/gdpr/delete-account/cancel",
                     headers=fresh_user["headers"], timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True

    def test_5_auth_me_clears_deleted_at_and_pii_intact(self, api, fresh_user):
        r = api.get(f"{BASE_URL}/api/auth/me",
                    headers=fresh_user["headers"], timeout=30)
        assert r.status_code == 200
        me = r.json()
        assert me.get("email") == fresh_user["email"]
        assert me.get("name") == fresh_user["name"]
        assert not me.get("deleted_at"), f"deleted_at still set: {me.get('deleted_at')}"
        assert not me.get("purge_at"), f"purge_at still set: {me.get('purge_at')}"

    def test_6_login_with_original_credentials_still_works(self, api, fresh_user):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": fresh_user["email"],
                           "password": fresh_user["password"]},
                     timeout=30)
        assert r.status_code == 200, f"login failed after cancel: {r.status_code} {r.text}"
        data = r.json()
        assert "token" in data
        assert data["user"]["email"] == fresh_user["email"]

    def test_7_cleanup_delete_test_user(self, api, fresh_user):
        # Re-issue delete-account to mark for purge (cleanup); actual purge is deferred.
        r = api.post(f"{BASE_URL}/api/gdpr/delete-account",
                     json={"confirmation": "DELETE",
                           "reason": "test cleanup"},
                     headers=fresh_user["headers"], timeout=30)
        assert r.status_code == 200


# ---------- Fix 2 regression: seed client account still works ----------
class TestSeedAccountStillWorks:
    def test_client_seed_login(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": "client@crewfit.com",
                           "password": "Client123!"}, timeout=30)
        assert r.status_code == 200, f"seed client login broken: {r.status_code} {r.text}"

    def test_coach_seed_login(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": "coach@crewfit.com",
                           "password": "Coach123!"}, timeout=30)
        assert r.status_code == 200, f"seed coach login broken: {r.status_code} {r.text}"
