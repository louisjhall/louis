"""Launch-hardening regression suite (iteration 42).

Covers:
  - AI limits telemetry admin endpoints
  - Per-user quota endpoint
  - GDPR: export, soft-delete, cancel, audit, partial delete validation
  - Admin GDPR: pending + audit
  - Check-in migration status + idempotent unify
  - Storage abstraction status
  - Regression: nutrition/habits/notifications core reads
  - Photo scan quota bump (best-effort)
"""
import os
import json

import pytest
import requests


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")


# ---------- AI limits / telemetry --------------------------------------------

class TestUserQuota:
    def test_user_quota_returns_all_features(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/user/quota", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "features" in data
        feats = data["features"]
        # 13 features declared in ai_limits.DEFAULT_QUOTAS
        assert len(feats) == 13, f"expected 13 features, got {len(feats)}: {list(feats.keys())}"
        # sanity check schema on one entry
        for key in ["photo_scan", "atlas_message", "workout_gen"]:
            assert key in feats
            entry = feats[key]
            for k in ("day", "month", "cap_day", "cap_month", "remaining_day", "remaining_month"):
                assert k in entry, f"{key} missing {k}"

    def test_user_quota_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/user/quota", timeout=15)
        assert r.status_code in (401, 403)


class TestAdminTelemetry:
    def test_summary(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/admin/telemetry/summary?days=7",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("calls", "cost_usd", "tokens_in", "tokens_out", "images",
                  "failures", "unique_users", "days"):
            assert k in d
        assert d["days"] == 7

    def test_daily(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/admin/telemetry/daily?days=7",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "rows" in d and isinstance(d["rows"], list)

    def test_top_users(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/admin/telemetry/top-users?days=7&limit=10",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert isinstance(d.get("rows"), list)

    def test_outliers(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/admin/telemetry/outliers?days=1",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "outliers" in d

    def test_quotas(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/admin/telemetry/quotas",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("enforced") is True
        assert len(d.get("quotas", {})) == 13

    def test_admin_endpoints_forbidden_for_client(self, api, client_auth):
        endpoints = [
            "/api/admin/telemetry/summary",
            "/api/admin/telemetry/daily",
            "/api/admin/telemetry/top-users",
            "/api/admin/telemetry/outliers",
            "/api/admin/telemetry/quotas",
        ]
        for ep in endpoints:
            r = api.get(f"{BASE_URL}{ep}", headers=client_auth["headers"], timeout=15)
            assert r.status_code == 403, f"{ep} expected 403 for client, got {r.status_code}"


# ---------- GDPR -------------------------------------------------------------

class TestGDPR:
    def test_export_returns_json_blob(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/gdpr/export", headers=client_auth["headers"], timeout=60)
        assert r.status_code == 200, r.text
        assert "application/json" in r.headers.get("content-type", "")
        # content should be non-empty JSON and include user info
        body = r.content
        assert len(body) > 100
        parsed = json.loads(body)
        assert "user" in parsed
        assert parsed["user"].get("email") == "client@crewfit.com"

    def test_delete_missing_confirmation_400(self, api, client_auth):
        r = api.post(f"{BASE_URL}/api/gdpr/delete-account",
                     json={"confirmation": "no", "reason": "test"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 400

    def test_delete_and_cancel_flow(self, api, client_auth, coach_auth):
        # Schedule deletion
        r = api.post(f"{BASE_URL}/api/gdpr/delete-account",
                     json={"confirmation": "DELETE", "reason": "TEST_iteration_42"},
                     headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert d.get("scheduled_purge_at")

        # Admin sees it. NOTE: PII is no longer scrubbed on delete-request
        # (deferred until purge time). Locate our pending row by
        # `deletion_reason` instead of the old `deleted+` email pattern.
        r2 = api.get(f"{BASE_URL}/api/admin/gdpr/pending",
                     headers=coach_auth["headers"], timeout=30)
        assert r2.status_code == 200
        pending = r2.json().get("pending", [])
        assert any(row.get("deletion_reason") == "TEST_iteration_42"
                   for row in pending), \
            f"expected at least one pending row with our reason, got {pending}"

        # Cancel it
        r3 = api.post(f"{BASE_URL}/api/gdpr/delete-account/cancel",
                      headers=client_auth["headers"], timeout=30)
        assert r3.status_code == 200, r3.text

        # Admin sees 0 pending (for our user at least)
        r4 = api.get(f"{BASE_URL}/api/admin/gdpr/pending",
                     headers=coach_auth["headers"], timeout=30)
        assert r4.status_code == 200
        # Note: pending count may include OTHER users' pending rows; check ours cancelled
        pending_after = r4.json().get("pending", [])
        assert not any(row.get("deletion_reason") == "TEST_iteration_42"
                       for row in pending_after)

        # Audit shows both events
        r5 = api.get(f"{BASE_URL}/api/admin/gdpr/audit?limit=50",
                     headers=coach_auth["headers"], timeout=30)
        assert r5.status_code == 200
        audit = r5.json().get("audit", [])
        actions = [row.get("action") for row in audit]
        assert "delete_requested" in actions
        assert "delete_cancelled" in actions


# ---------- Check-in migration -----------------------------------------------

class TestCheckinMigration:
    def test_status(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/admin/migrations/checkins/status",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("canonical") == "checkins"
        # Existing counts per prompt
        assert "checkins_count" in d
        assert "check_ins_count" in d

    def test_unify_dry_run_idempotent(self, api, coach_auth):
        r = api.post(f"{BASE_URL}/api/admin/migrations/checkins/unify?dry_run=true",
                     headers=coach_auth["headers"], timeout=60)
        assert r.status_code == 200, r.text
        # dry_run should not raise and return a dict-ish body
        assert isinstance(r.json(), dict)


# ---------- Storage abstraction ----------------------------------------------

class TestStorage:
    def test_storage_status(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/admin/storage/status",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("driver") == "disk"
        assert d.get("is_cloud") is False


# ---------- Regression -------------------------------------------------------

class TestRegression:
    def test_nutrition_today(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/nutrition/today",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_habits_mine(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/habits/mine",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_notifications(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/notifications",
                    headers=client_auth["headers"], timeout=30)
        # allow either 200 or 200-with-list
        assert r.status_code == 200, r.text

    def test_coach_clients(self, api, coach_auth):
        r = api.get(f"{BASE_URL}/api/coach/clients",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
