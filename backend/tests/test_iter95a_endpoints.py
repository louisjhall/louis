"""Iter 95a — HTTP-level tests for Dual-Session + Weekly Review dedupe.

Endpoints exercised:
  * GET  /api/dual-session/today
  * GET  /api/dual-session/upcoming?days=N
  * GET  /api/dual-session/debug/{user_id}
  * POST /api/weekly-review/checkin-complete   (idempotency / real UUID)
  * POST /api/weekly-review/progress-complete  (idempotency / real UUID)
  * GET  /api/weekly-review/current

Base URL is localhost:8001 as instructed by main agent.
"""
from __future__ import annotations

import os
import re
import uuid

import pytest
import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "testcal2@crewfit.com"
CLIENT_PASS = "TestCal123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASS = "Louis123!"

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _login(email: str, password: str) -> dict:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text[:300]}"
    j = r.json()
    assert "token" in j and "user" in j, f"unexpected login shape: {j}"
    return j


@pytest.fixture(scope="module")
def client_auth():
    j = _login(CLIENT_EMAIL, CLIENT_PASS)
    return {"token": j["token"], "user": j["user"],
            "headers": {"Authorization": f"Bearer {j['token']}"}}


@pytest.fixture(scope="module")
def coach_auth():
    j = _login(COACH_EMAIL, COACH_PASS)
    return {"token": j["token"], "user": j["user"],
            "headers": {"Authorization": f"Bearer {j['token']}"}}


# ---------------------------------------------------------------------------
# 1) Dual-Session — /today
# ---------------------------------------------------------------------------

class TestDualSessionToday:
    def test_today_client_200(self, client_auth):
        r = requests.get(f"{API}/dual-session/today", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert "enabled" in body, body
        assert "eligible" in body, body
        # 'reason' or 'session' must appear (not both/none rules but at least one is expected)
        assert body["enabled"] is True or body["enabled"] is False
        if body.get("enabled") and body.get("eligible"):
            assert "session" in body
            assert isinstance(body["session"], dict)
            assert body["session"].get("secondary") is True
        else:
            # Should have reason or evaluation
            assert "reason" in body or "evaluation" in body or not body.get("enabled")

    def test_today_no_500_for_seeded_mixed_user(self, client_auth):
        # This user is flying_type=mixed per task description
        r = requests.get(f"{API}/dual-session/today", headers=client_auth["headers"], timeout=15)
        assert r.status_code != 500, f"server error on today: {r.text[:400]}"
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 2) Dual-Session — /upcoming
# ---------------------------------------------------------------------------

class TestDualSessionUpcoming:
    def test_upcoming_default(self, client_auth):
        r = requests.get(f"{API}/dual-session/upcoming", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert "enabled" in body
        # When enabled, must include count, items, generated_at
        if body.get("enabled"):
            assert "count" in body
            assert "items" in body
            assert "generated_at" in body
            assert isinstance(body["items"], list)
            assert body["count"] == len(body["items"])

    def test_upcoming_days_param(self, client_auth):
        r = requests.get(
            f"{API}/dual-session/upcoming",
            params={"days": 14},
            headers=client_auth["headers"], timeout=15,
        )
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert "enabled" in body
        if body.get("enabled"):
            assert "items" in body
            assert isinstance(body["items"], list)
            # each item must include date + reason keys per implementation
            for it in body["items"]:
                assert "date" in it
                assert "reason" in it


# ---------------------------------------------------------------------------
# 3) Dual-Session — /debug (coach-only)
# ---------------------------------------------------------------------------

class TestDualSessionDebug:
    def test_debug_403_for_client(self, client_auth):
        uid = client_auth["user"]["id"]
        r = requests.get(f"{API}/dual-session/debug/{uid}",
                         headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403, f"expected 403 for client, got {r.status_code}: {r.text[:200]}"

    def test_debug_200_for_coach(self, coach_auth, client_auth):
        uid = client_auth["user"]["id"]
        r = requests.get(f"{API}/dual-session/debug/{uid}",
                         headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body.get("user_id") == uid
        assert "days_checked" in body
        assert "days" in body
        assert isinstance(body["days"], list)


# ---------------------------------------------------------------------------
# 4) Feature-flag toggle for dual_session_enabled
# ---------------------------------------------------------------------------

class TestDualSessionFlag:
    KEY = "dual_session_enabled"

    def _set_flag(self, coach_headers, value: bool):
        payload = {
            "key": self.KEY,
            "value": value,
            "kind": "flag",
            "enabled": True,
            "description": "Enable optional airport-activation dual session",
        }
        r = requests.post(f"{API}/admin/app-config", json=payload,
                          headers=coach_headers, timeout=15)
        assert r.status_code == 200, f"set flag {value} failed: {r.status_code} {r.text[:300]}"
        return r.json()

    def test_flag_toggle_disables_dual_session(self, coach_auth, client_auth):
        # Turn OFF
        self._set_flag(coach_auth["headers"], False)
        try:
            r = requests.get(f"{API}/dual-session/today",
                             headers=client_auth["headers"], timeout=15)
            assert r.status_code == 200, r.text[:300]
            body = r.json()
            assert body.get("enabled") is False, f"expected enabled=false, got {body}"
            assert "session" not in body, f"session should not be present when disabled, got {body}"

            # Upcoming: enabled should also be False, items empty
            r2 = requests.get(f"{API}/dual-session/upcoming",
                              headers=client_auth["headers"], timeout=15)
            assert r2.status_code == 200
            b2 = r2.json()
            assert b2.get("enabled") is False
            assert b2.get("items", []) == []
        finally:
            # Always turn back ON regardless of failure
            self._set_flag(coach_auth["headers"], True)

    def test_flag_restored_true(self, coach_auth, client_auth):
        # After the toggle test, the flag should be True again
        r = requests.get(f"{API}/dual-session/today",
                         headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert body.get("enabled") is True, f"flag should be restored, got {body}"


# ---------------------------------------------------------------------------
# 5) Weekly Review dedupe — video_task_id is a real UUID, not "existing"
# ---------------------------------------------------------------------------

class TestWeeklyReviewDedupe:
    def test_checkin_and_progress_twice_returns_real_uuid(self, client_auth):
        headers = client_auth["headers"]

        # First mark check-in
        r1a = requests.post(f"{API}/weekly-review/checkin-complete",
                            json={"note": "TEST_iter95a first"}, headers=headers, timeout=15)
        assert r1a.status_code == 200, r1a.text[:400]

        # First mark progress
        r2a = requests.post(f"{API}/weekly-review/progress-complete",
                            json={"note": "TEST_iter95a first"}, headers=headers, timeout=15)
        assert r2a.status_code == 200, r2a.text[:400]
        review1 = r2a.json().get("review") or {}

        # Second (idempotent) invocation
        r1b = requests.post(f"{API}/weekly-review/checkin-complete",
                            json={"note": "TEST_iter95a second"}, headers=headers, timeout=15)
        assert r1b.status_code == 200, r1b.text[:400]
        r2b = requests.post(f"{API}/weekly-review/progress-complete",
                            json={"note": "TEST_iter95a second"}, headers=headers, timeout=15)
        assert r2b.status_code == 200, r2b.text[:400]
        review2 = r2b.json().get("review") or {}

        vt1 = review1.get("video_task_id")
        vt2 = review2.get("video_task_id")

        # Must exist and be a real UUID, NOT the literal 'existing'
        assert vt1, f"first review missing video_task_id: {review1}"
        assert vt2, f"second review missing video_task_id: {review2}"
        assert vt1 != "existing", "video_task_id must NOT be literal 'existing'"
        assert vt2 != "existing", "video_task_id must NOT be literal 'existing'"

        # UUID shape (matches how new_id() is used in the codebase)
        assert UUID_RE.match(str(vt1)), f"vt1 not UUID: {vt1}"
        assert UUID_RE.match(str(vt2)), f"vt2 not UUID: {vt2}"

        # Idempotency: same task id returned across calls
        assert vt1 == vt2, f"dedupe broken: {vt1} != {vt2}"

        # Ancillary status flags
        assert review2.get("video_review_status") == "ready"
        assert review2.get("review_ready_for_louis") is True

    def test_weekly_review_current_shape(self, client_auth):
        r = requests.get(f"{API}/weekly-review/current",
                         headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        for k in ("training", "nutrition", "habits", "message_lines", "coach"):
            assert k in body, f"missing '{k}' in weekly-review/current payload: keys={list(body.keys())}"
        assert isinstance(body.get("message_lines"), list)
        assert isinstance(body.get("coach"), dict)


# ---------------------------------------------------------------------------
# 6) Coach-tasks dedupe — no duplicate weekly_video_review for same week
# ---------------------------------------------------------------------------

class TestCoachTaskDedupe:
    def test_no_duplicate_weekly_video_review_tasks(self, coach_auth, client_auth):
        """Query the DB layer through coach APIs. We list coach tasks and count
        weekly_video_review tasks for testcal2 for the current week_start."""
        # First, get the current week's review to know week_start.
        r_cur = requests.get(f"{API}/weekly-review/current",
                             headers=client_auth["headers"], timeout=15)
        assert r_cur.status_code == 200
        week_start = r_cur.json().get("week_start")
        assert week_start
        uid = client_auth["user"]["id"]

        # Coach tasks endpoint — try common paths
        candidates = ["/coach/tasks", "/admin/coach-tasks", "/coach/tasks/list"]
        tasks = None
        used = None
        for path in candidates:
            r = requests.get(f"{API}{path}", headers=coach_auth["headers"], timeout=15)
            if r.status_code == 200:
                j = r.json()
                arr = j.get("tasks") or j.get("items") or (j if isinstance(j, list) else None)
                if arr is not None:
                    tasks = arr
                    used = path
                    break
        if tasks is None:
            pytest.skip(f"no coach-tasks list endpoint reachable, tried {candidates}")

        matching = [
            t for t in tasks
            if t.get("task_type") == "weekly_video_review"
            and t.get("user_id") == uid
            and (t.get("payload") or {}).get("week_start") == week_start
            and t.get("status") in ("todo", "in_progress", "snoozed")
        ]
        assert len(matching) <= 1, (
            f"expected ≤1 weekly_video_review task for user={uid} week={week_start}, "
            f"found {len(matching)} via {used}: "
            + ", ".join(str(t.get("id")) for t in matching)
        )


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
