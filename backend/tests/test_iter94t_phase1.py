"""
Iter 94t Phase 1 — Master Fix Phase 1 tests.

Covers:
- App config / feature flags (public + admin CRUD + audit)
- Exercise media reconciliation
- Calendar range (regression) + missed workout recovery
- Timezone status resolver
- Role-based access enforcement
"""
import os
import time

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

CLIENT_EMAIL = "testcal2@crewfit.com"
CLIENT_PASS = "TestCal123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASS = "Louis123!"

EXPECTED_FLAGS = [
    "guided_flow_enabled",
    "guided_flow_timer_mode_enabled",
    "guided_flow_image_autoscroll",
    "exercise_media_required",
    "missing_media_client_fallback_enabled",
    "hotel_system_enabled",
    "progress_charts_enabled",
    "nutrition_dashboard_enabled",
    "wearable_steps_enabled",
    "habits_dynamic_enabled",
    "first_day_workout_choice_enabled",
    "whatsapp_support_enabled",
    "beta_banner_enabled",
    "missed_workout_recovery_enabled",
    "timezone_card_enabled",
    "calendar_scroll_enabled",
]


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()


@pytest.fixture(scope="module")
def coach_headers():
    d = _login(COACH_EMAIL, COACH_PASS)
    return {"Authorization": f"Bearer {d['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client_headers():
    d = _login(CLIENT_EMAIL, CLIENT_PASS)
    return {"Authorization": f"Bearer {d['token']}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# App config / feature flags
# ---------------------------------------------------------------------------

class TestAppConfigPublic:

    def test_get_app_config_returns_16_default_flags(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/app-config", headers=client_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "flags" in body and "content" in body and "updated_at" in body
        flags = body["flags"]
        # All 16 expected flags must exist
        missing = [k for k in EXPECTED_FLAGS if k not in flags]
        assert not missing, f"missing default flags: {missing}"
        # wearable_steps_enabled MUST default to False, others True
        assert flags["wearable_steps_enabled"] is False, f"wearable_steps should be False, got {flags['wearable_steps_enabled']}"
        for k in EXPECTED_FLAGS:
            if k == "wearable_steps_enabled":
                continue
            assert flags[k] is True, f"flag {k} should default True, got {flags[k]}"

    def test_get_app_config_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/app-config", timeout=30)
        assert r.status_code in (401, 403), f"expected auth guard, got {r.status_code}"


class TestAppConfigAdmin:

    def test_admin_list_requires_coach(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/admin/app-config", headers=client_headers, timeout=30)
        assert r.status_code == 403, f"client should be 403, got {r.status_code} {r.text[:200]}"

    def test_admin_list_config(self, coach_headers):
        r = requests.get(f"{BASE_URL}/api/admin/app-config", headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body
        keys = {i["key"] for i in body["items"]}
        # All 16 default flags should be listed
        missing = [k for k in EXPECTED_FLAGS if k not in keys]
        assert not missing, f"admin list missing defaults: {missing}"
        assert "safe_content_keys" in body

    def test_admin_upsert_requires_coach(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/admin/app-config",
                          headers=client_headers,
                          json={"key": "TEST_flag_client", "value": True}, timeout=30)
        assert r.status_code == 403

    def test_admin_upsert_creates_flag_and_updates(self, coach_headers):
        key = "TEST_iter94t_toggle"
        # Create
        r = requests.post(f"{BASE_URL}/api/admin/app-config",
                          headers=coach_headers,
                          json={"key": key, "value": True, "description": "test flag"}, timeout=30)
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        assert item["key"] == key and item["value"] is True

        # Public config should now include it
        r2 = requests.get(f"{BASE_URL}/api/app-config", headers=coach_headers, timeout=30)
        assert r2.status_code == 200
        assert r2.json()["flags"].get(key) is True

        # Update
        r3 = requests.post(f"{BASE_URL}/api/admin/app-config",
                           headers=coach_headers,
                           json={"key": key, "value": False}, timeout=30)
        assert r3.status_code == 200
        assert r3.json()["item"]["value"] is False

        # Cleanup: disable
        requests.delete(f"{BASE_URL}/api/admin/app-config/{key}", headers=coach_headers, timeout=30)

    def test_admin_delete_soft_disables(self, coach_headers):
        key = "TEST_iter94t_delete_target"
        # Create
        r = requests.post(f"{BASE_URL}/api/admin/app-config",
                          headers=coach_headers,
                          json={"key": key, "value": True}, timeout=30)
        assert r.status_code == 200
        # Should show in public config
        assert key in requests.get(f"{BASE_URL}/api/app-config", headers=coach_headers, timeout=30).json()["flags"]

        # Delete (soft disable)
        rd = requests.delete(f"{BASE_URL}/api/admin/app-config/{key}", headers=coach_headers, timeout=30)
        assert rd.status_code == 200, rd.text
        assert rd.json().get("disabled") == key

        # Public should no longer include it
        pub = requests.get(f"{BASE_URL}/api/app-config", headers=coach_headers, timeout=30).json()
        assert key not in pub["flags"], f"soft-disabled flag {key} still in public config"

    def test_admin_delete_missing_returns_404(self, coach_headers):
        r = requests.delete(f"{BASE_URL}/api/admin/app-config/TEST_nonexistent_key_xyz",
                            headers=coach_headers, timeout=30)
        assert r.status_code == 404

    def test_admin_audit_lists_writes(self, coach_headers):
        key = "TEST_iter94t_audit_probe"
        # Do a write so audit definitely has an entry
        requests.post(f"{BASE_URL}/api/admin/app-config", headers=coach_headers,
                      json={"key": key, "value": True}, timeout=30)
        time.sleep(0.3)
        r = requests.get(f"{BASE_URL}/api/admin/app-config/audit", headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        rows = r.json().get("audit", [])
        assert isinstance(rows, list)
        keys_seen = {row.get("key") for row in rows}
        assert key in keys_seen, f"audit didn't record write for {key}"
        # Cleanup
        requests.delete(f"{BASE_URL}/api/admin/app-config/{key}", headers=coach_headers, timeout=30)

    def test_admin_audit_requires_coach(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/admin/app-config/audit", headers=client_headers, timeout=30)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Media reconciliation
# ---------------------------------------------------------------------------

class TestMediaReconciliation:

    def test_reconcile_requires_coach(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/admin/media/reconcile", headers=client_headers, timeout=60)
        assert r.status_code == 403

    def test_reconcile_runs_and_returns_summary(self, coach_headers):
        r = requests.post(f"{BASE_URL}/api/admin/media/reconcile", headers=coach_headers, timeout=120)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "total_opened" in body
        assert "clients_scanned" in body
        assert isinstance(body.get("summary"), list)
        assert body["clients_scanned"] >= 1

    def test_reconcile_is_idempotent(self, coach_headers):
        # Snapshot open todos
        first = requests.post(f"{BASE_URL}/api/admin/media/reconcile", headers=coach_headers, timeout=120)
        assert first.status_code == 200
        r1 = requests.get(f"{BASE_URL}/api/admin/media/todos", headers=coach_headers, timeout=30)
        assert r1.status_code == 200
        count1 = r1.json().get("count", 0)

        # Second reconcile — should not create duplicates for same workouts
        second = requests.post(f"{BASE_URL}/api/admin/media/reconcile", headers=coach_headers, timeout=120)
        assert second.status_code == 200
        r2 = requests.get(f"{BASE_URL}/api/admin/media/todos", headers=coach_headers, timeout=30)
        assert r2.status_code == 200
        count2 = r2.json().get("count", 0)
        # New todos on the second run must not exceed the first (idempotency)
        assert count2 == count1, f"idempotency failure: todos went from {count1} → {count2}"

    def test_todos_endpoint_requires_coach(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/admin/media/todos", headers=client_headers, timeout=30)
        assert r.status_code == 403

    def test_todos_priority_matches_days_until(self, coach_headers):
        r = requests.get(f"{BASE_URL}/api/admin/media/todos", headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        todos = r.json().get("todos", [])
        # If we have any todos, check priority mapping. days_until stored in payload.
        for t in todos:
            payload = t.get("payload") or {}
            days_until = payload.get("days_until")
            prio = t.get("priority")
            if days_until is None or prio is None:
                continue
            if days_until <= 1:
                assert prio in ("urgent",), f"days_until={days_until} should be urgent, got {prio}"
            elif days_until <= 7:
                assert prio in ("urgent", "high"), f"days_until={days_until} should be high, got {prio}"
            elif days_until <= 30:
                assert prio in ("urgent", "high", "medium"), f"days_until={days_until} priority mismatch: {prio}"


# ---------------------------------------------------------------------------
# Calendar range regression
# ---------------------------------------------------------------------------

class TestCalendarRange:

    def test_calendar_range_returns_days(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/calendar/range",
                         params={"from": "2025-01-01", "to": "2026-12-31"},
                         headers=client_headers, timeout=30)
        # Note: server caps range to -60/+60 days from today.
        assert r.status_code == 200, r.text
        body = r.json()
        assert "days" in body and isinstance(body["days"], list) and len(body["days"]) > 0
        assert "from" in body and "to" in body and "today" in body
        assert "counts" in body
        # Every day must carry a badge and date
        for d in body["days"][:5]:
            assert "date" in d and "badge" in d

    def test_calendar_range_default_bounds(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/calendar/range", headers=client_headers, timeout=30)
        assert r.status_code == 200
        body = r.json()
        assert len(body["days"]) > 30  # ~60 days


# ---------------------------------------------------------------------------
# Missed workout recovery
# ---------------------------------------------------------------------------

class TestMissedRecovery:

    def test_missed_list(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/recovery/missed",
                         params={"window": 14}, headers=client_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "missed" in body and "count" in body
        assert isinstance(body["missed"], list)
        # Sanity check on schema of any returned item
        for m in body["missed"][:3]:
            assert "id" in m and "date" in m and "priority" in m
            assert "recommendation" in m and m["recommendation"] in ("recover", "skip", "ask_louis")

    def test_recovery_suggestions_returns_rated_slots(self, client_headers):
        # Grab any missed workout to test with
        missed = requests.get(f"{BASE_URL}/api/recovery/missed",
                              params={"window": 30}, headers=client_headers, timeout=30).json().get("missed", [])
        if not missed:
            pytest.skip("no missed workouts to run suggestions on")
        wid = missed[0]["id"]
        r = requests.post(f"{BASE_URL}/api/recovery/{wid}/suggestions", headers=client_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "suggestions" in body and isinstance(body["suggestions"], list)
        assert "workout" in body and body["workout"]["id"] == wid
        assert body.get("recommendation") in ("recover", "skip", "ask_louis", "move")
        # Each suggestion must have a rating
        valid_ratings = {"good", "okay", "not_ideal", "blocked"}
        for s in body["suggestions"]:
            assert s["rating"] in valid_ratings, f"invalid rating {s['rating']}"
            assert "date" in s and "reason" in s

    def test_previously_recovered_workout_persists_recovered_from_date(self, client_headers):
        """Regression: verify persisted `recovered_from_date` is still preserved
        on the workout that a prior session recovered. This gives us confidence
        even when the current DB state has no fresh recoverable workouts to
        exercise the move flow live."""
        r = requests.get(f"{BASE_URL}/api/calendar/range", headers=client_headers, timeout=30)
        assert r.status_code == 200
        days = r.json().get("days", [])
        recovered = [d for d in days if (d.get("workout") or {}).get("recovered_from_date")]
        if not recovered:
            pytest.skip("no previously-recovered workouts to check")
        w = recovered[0]["workout"]
        assert w.get("recovered_from_date"), "recovered_from_date missing"
        assert w.get("recovered_to_date") == recovered[0]["date"], \
            f"recovered_to_date should equal current date: {w.get('recovered_to_date')} vs {recovered[0]['date']}"
        # The badge on the calendar day should reflect recovered
        assert recovered[0].get("badge") == "recovered", \
            f"expected badge=recovered, got {recovered[0].get('badge')}"

    def test_recover_preserves_recovered_from_date(self, client_headers):
        # Find a fresh recoverable workout
        missed = requests.get(f"{BASE_URL}/api/recovery/missed",
                              params={"window": 14}, headers=client_headers, timeout=30).json().get("missed", [])
        recoverable = [m for m in missed if m.get("recoverable") and not m.get("coach_locked")]
        if not recoverable:
            pytest.skip("no recoverable missed workouts available")
        target = recoverable[0]
        wid = target["id"]
        original_date = target["date"]

        # Get suggestions to pick a good target date
        sugs = requests.post(f"{BASE_URL}/api/recovery/{wid}/suggestions", headers=client_headers, timeout=30).json()
        good = [s for s in sugs.get("suggestions", []) if s["rating"] in ("good", "okay") and not s.get("blocked")]
        # Prefer a future day that isn't today to avoid replace_today conflicts
        future = [s for s in good if s.get("days_from_today", 0) >= 2]
        pick = future[0] if future else (good[0] if good else None)
        if not pick:
            pytest.skip("no safe recovery slot returned by suggestions")

        r = requests.post(f"{BASE_URL}/api/recovery/{wid}/recover",
                          headers=client_headers,
                          json={"target_date": pick["date"], "action": "move"}, timeout=30)
        # We tolerate 409 if the slot conflicts with an existing workout — we just need
        # to verify successful moves preserve recovered_from_date.
        if r.status_code == 409:
            pytest.skip(f"target conflicts: {r.text[:200]}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        w = body.get("workout") or {}
        assert w.get("recovered_from_date") == original_date, \
            f"expected recovered_from_date={original_date}, got {w.get('recovered_from_date')}"
        assert w.get("date") == pick["date"]
        assert w.get("recovery_status") == "recovered"

    def test_skip_marks_skipped(self, client_headers):
        # Find a missed workout to skip. Prefer an older / optional one so we don't
        # burn a fresh recoverable session.
        missed = requests.get(f"{BASE_URL}/api/recovery/missed",
                              params={"window": 30}, headers=client_headers, timeout=30).json().get("missed", [])
        candidates = [m for m in missed if not m.get("coach_locked")]
        if not candidates:
            pytest.skip("no skippable missed workouts")
        # Prefer optional_recovery or oldest first
        candidates.sort(key=lambda m: (0 if m.get("priority") == "optional_recovery" else 1, -m.get("days_ago", 0)))
        wid = candidates[0]["id"]
        r = requests.post(f"{BASE_URL}/api/recovery/{wid}/skip",
                          headers=client_headers,
                          json={"reason": "TEST_skip"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True and body.get("workout_id") == wid

        # Verify: missed list should no longer contain it
        after = requests.get(f"{BASE_URL}/api/recovery/missed",
                             params={"window": 30}, headers=client_headers, timeout=30).json().get("missed", [])
        assert wid not in {m["id"] for m in after}, "skipped workout still surfaced in missed list"


# ---------------------------------------------------------------------------
# Timezone status
# ---------------------------------------------------------------------------

class TestTimezoneStatus:

    def test_timezone_status_returns_source_and_home(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/profile/timezone-status", headers=client_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # All required keys must exist (may be None but present)
        for k in ("home_base", "home_timezone", "current_timezone",
                  "current_timezone_source", "current_timezone_confidence",
                  "needs_confirmation"):
            assert k in body, f"missing key {k} in timezone-status"
        # Source must be one of the documented values
        assert body["current_timezone_source"] in (
            "roster", "client_confirmed", "device", "home_base", "unknown"
        )

    def test_timezone_status_accepts_device_tz(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/profile/timezone-status",
                         params={"device_tz": "Europe/London"},
                         headers=client_headers, timeout=30)
        assert r.status_code == 200
        body = r.json()
        # If no roster / no client_confirmed set, source may be "device"
        assert body["current_timezone_source"] in (
            "roster", "client_confirmed", "device", "home_base", "unknown"
        )
