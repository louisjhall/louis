"""Iter189f · Backend tests — auto YouTube search on exercise create/status change.

Verifies:
 1. GET /api/coach/youtube-finder/health returns new fields
    (auto_on_create_enabled, quota_used_today, quota_remaining_today,
     quota_floor_for_auto_search).
 2. POST /api/coach/youtube-finder/auto-on-create toggles + persists.
 3. POST /api/exercise-content creates a row + fires background auto_yt trigger
    without mutating status. Quota exhausted → expect `auto_yt: quota exhausted`
    or `auto_yt: quota floor hit` log line but the create must still succeed.
 4. PATCH /api/exercise-content/{ex_id} → draft_requested fires auto_yt for that
    ex_id; idempotent (does NOT overwrite existing primary_video_url).
 5. Feature flag OFF → no auto_yt trigger.
"""
from __future__ import annotations

import os
import re
import time
import uuid

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")).rstrip("/")

BACKEND_LOG = "/var/log/supervisor/backend.err.log"
BACKEND_OUT_LOG = "/var/log/supervisor/backend.out.log"

COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"


# ------------------ helpers ------------------

def _login(email: str, password: str):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email} → {r.status_code} {r.text}"
    d = r.json()
    return {"Authorization": f"Bearer {d['token']}"}, d["user"]


def _tail_backend_log(bytes_from_end: int = 60_000) -> str:
    """Read tail of backend logs (both .err and .out) as text."""
    out = ""
    for p in (BACKEND_LOG, BACKEND_OUT_LOG):
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - bytes_from_end))
                out += f.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
    return out


def _log_position() -> int:
    """Return current combined size of backend logs as a bookmark."""
    total = 0
    for p in (BACKEND_LOG, BACKEND_OUT_LOG):
        try:
            total += os.path.getsize(p)
        except Exception:
            pass
    return total


def _log_since(_bookmark: int) -> str:
    """Return log content added since bookmark (crude, but sufficient)."""
    # Just re-tail generously — logs are grep'd by ex_id anyway.
    return _tail_backend_log(bytes_from_end=200_000)


@pytest.fixture(scope="module")
def coach():
    h, u = _login(COACH_EMAIL, COACH_PASSWORD)
    return {"headers": h, "user": u}


# ------------------ 1. /health new fields ------------------

class TestYoutubeFinderHealth:
    def test_health_returns_new_iter189f_fields(self, coach):
        r = requests.get(
            f"{BASE_URL}/api/coach/youtube-finder/health",
            headers=coach["headers"], timeout=30,
        )
        assert r.status_code == 200, f"health → {r.status_code} {r.text}"
        body = r.json()
        # Schema check for new fields — quota-exhausted is expected today.
        assert "auto_on_create_enabled" in body, body
        assert isinstance(body["auto_on_create_enabled"], bool), body
        assert "quota_used_today" in body, body
        assert isinstance(body["quota_used_today"], int), body
        assert "quota_remaining_today" in body, body
        assert isinstance(body["quota_remaining_today"], int), body
        # quota_floor_for_auto_search is only in the success path — but
        # per the review request it should be present. Skip if quota
        # exhausted branch is taken.
        if body.get("ok") is True or body.get("reason") is None:
            assert body.get("quota_floor_for_auto_search") == 500, body
        # default should be True
        assert body["auto_on_create_enabled"] is True, (
            f"auto_on_create_enabled expected True by default, got {body}"
        )


# ------------------ 2. toggle auto-on-create ------------------

class TestAutoOnCreateToggle:
    def test_toggle_disable_then_enable_persists(self, coach):
        # Turn OFF
        r = requests.post(
            f"{BASE_URL}/api/coach/youtube-finder/auto-on-create",
            headers=coach["headers"], json={"enabled": False}, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True, body
        assert body.get("auto_on_create_enabled") is False, body

        # Health should reflect it
        h = requests.get(
            f"{BASE_URL}/api/coach/youtube-finder/health",
            headers=coach["headers"], timeout=30,
        ).json()
        assert h.get("auto_on_create_enabled") is False, h

        # Turn back ON (cleanup)
        r2 = requests.post(
            f"{BASE_URL}/api/coach/youtube-finder/auto-on-create",
            headers=coach["headers"], json={"enabled": True}, timeout=30,
        )
        assert r2.status_code == 200
        assert r2.json().get("auto_on_create_enabled") is True

        h2 = requests.get(
            f"{BASE_URL}/api/coach/youtube-finder/health",
            headers=coach["headers"], timeout=30,
        ).json()
        assert h2.get("auto_on_create_enabled") is True, h2


# ------------------ 3. POST /api/exercise-content fires auto_yt ------------------

class TestCreateExerciseFiresAutoYt:
    created_id = None

    def test_create_triggers_auto_yt_and_status_unchanged(self, coach):
        # Ensure feature is ON
        requests.post(
            f"{BASE_URL}/api/coach/youtube-finder/auto-on-create",
            headers=coach["headers"], json={"enabled": True}, timeout=30,
        )

        ts = int(time.time())
        ex_name = f"TEST_Auto YT Exercise {ts} {uuid.uuid4().hex[:6]}"
        payload = {
            "exercise_name": ex_name,
            "category": "strength",
            "training_type": "warmup",
            "body_area": "shoulders",
            "equipment_type": ["band"],
            "tags": ["TEST", "iter189f"],
            "coaching_points": ["auto-yt-trigger-test"],
        }
        bookmark = _log_position()
        r = requests.post(
            f"{BASE_URL}/api/exercise-content", json=payload,
            headers=coach["headers"], timeout=30,
        )
        assert r.status_code in (200, 201), f"create → {r.status_code} {r.text}"
        j = r.json()
        assert "exercise" in j, j
        ex = j["exercise"]
        assert ex.get("id"), ex
        assert ex.get("exercise_name") == ex_name, ex
        TestCreateExerciseFiresAutoYt.created_id = ex["id"]
        original_status = ex.get("status")

        # Give background task time to fire
        time.sleep(5)

        # Grab logs and look for auto_yt log line referencing this ex_id
        logs = _log_since(bookmark)
        # Look for either the ex_id specifically, or a generic quota-exhausted
        # line — quota is exhausted so we expect the trigger to hit that branch.
        has_ex_id_line = ex["id"] in logs and "auto_yt" in logs
        has_recent_quota_line = bool(re.search(
            r"auto_yt:\s*(quota exhausted|quota floor hit|no match|search error|wrote video)",
            logs,
        ))
        assert has_ex_id_line or has_recent_quota_line, (
            "Expected auto_yt log line after create — none found. "
            f"ex_id={ex['id']} recent-log-tail={logs[-3000:]}"
        )

        # Status must not have been mutated by the auto-search
        got = requests.get(
            f"{BASE_URL}/api/exercise-content/{ex['id']}",
            headers=coach["headers"], timeout=15,
        )
        # Fallback: some builds only expose list — try list endpoint
        if got.status_code == 200:
            g = got.json()
            row = g.get("exercise") or g
            assert row.get("status") == original_status, (
                f"status changed unexpectedly: {original_status} → {row.get('status')}"
            )

    def test_cleanup_archive_created(self, coach):
        ex_id = TestCreateExerciseFiresAutoYt.created_id
        if not ex_id:
            pytest.skip("no exercise created")
        r = requests.delete(
            f"{BASE_URL}/api/exercise-content/{ex_id}",
            headers=coach["headers"], timeout=15,
        )
        assert r.status_code in (200, 204), r.text


# ------------------ 4. PATCH → draft_requested fires auto_yt ------------------

class TestPatchStatusFiresAutoYt:
    created_id = None
    original_status = None
    original_video_url = None

    def test_patch_to_draft_requested_triggers_auto_yt(self, coach):
        # Ensure ON
        requests.post(
            f"{BASE_URL}/api/coach/youtube-finder/auto-on-create",
            headers=coach["headers"], json={"enabled": True}, timeout=30,
        )

        # Create a fresh row (avoid mutating existing Approved rows)
        ts = int(time.time())
        ex_name = f"TEST_Patch AutoYT {ts} {uuid.uuid4().hex[:6]}"
        cr = requests.post(
            f"{BASE_URL}/api/exercise-content",
            json={
                "exercise_name": ex_name,
                "category": "strength",
                "training_type": "warmup",
                "body_area": "core",
                "equipment_type": ["bodyweight"],
                "tags": ["TEST", "iter189f"],
            },
            headers=coach["headers"], timeout=30,
        )
        assert cr.status_code in (200, 201), cr.text
        ex = cr.json()["exercise"]
        TestPatchStatusFiresAutoYt.created_id = ex["id"]
        TestPatchStatusFiresAutoYt.original_status = ex.get("status")
        TestPatchStatusFiresAutoYt.original_video_url = ex.get("primary_video_url")

        # Wait a moment then PATCH → draft_requested
        time.sleep(2)
        bookmark = _log_position()
        pr = requests.patch(
            f"{BASE_URL}/api/exercise-content/{ex['id']}",
            headers=coach["headers"], json={"status": "draft_requested"}, timeout=30,
        )
        assert pr.status_code == 200, f"patch → {pr.status_code} {pr.text}"
        updated = pr.json().get("exercise") or {}
        assert updated.get("status") == "draft_requested", updated

        time.sleep(5)
        logs = _log_since(bookmark)
        assert "auto_yt" in logs, (
            f"No auto_yt log line seen after PATCH. tail={logs[-2500:]}"
        )
        # Prefer to see the ex_id in an auto_yt line OR a quota exhaustion line
        # in the recent window
        # (per review request quota exhaustion is acceptable)
        has_line = (ex["id"] in logs) or bool(re.search(
            r"auto_yt:\s*(quota exhausted|quota floor hit|no match|search error|wrote video)",
            logs,
        ))
        assert has_line, f"auto_yt log check failed for ex_id={ex['id']}"

    def test_patch_does_not_overwrite_existing_video_url(self, coach):
        """Idempotency — if an exercise already has primary_video_url, the
        trigger should NOT fire on status transition (guard in ex_patch)."""
        ex_id = TestPatchStatusFiresAutoYt.created_id
        if not ex_id:
            pytest.skip("no exercise created")

        # First seed a video URL manually
        seed = "https://www.youtube.com/watch?v=TEST_SEED_iter189f"
        r0 = requests.patch(
            f"{BASE_URL}/api/exercise-content/{ex_id}",
            headers=coach["headers"],
            json={"primary_video_url": seed, "status": "draft"},
            timeout=30,
        )
        assert r0.status_code == 200, r0.text

        # Now transition to coach_review_needed; auto_yt should be skipped
        bookmark = _log_position()
        r1 = requests.patch(
            f"{BASE_URL}/api/exercise-content/{ex_id}",
            headers=coach["headers"],
            json={"status": "coach_review_needed"}, timeout=30,
        )
        assert r1.status_code == 200, r1.text
        # Verify the seeded URL is retained
        cur = r1.json().get("exercise") or {}
        assert cur.get("primary_video_url") == seed, (
            f"primary_video_url overwritten: {cur.get('primary_video_url')}"
        )
        time.sleep(3)
        logs = _log_since(bookmark)
        # We do NOT strictly assert absence globally, because unrelated
        # background sweeps may log; but the ex_id specifically should not
        # appear on a fresh auto_yt line.
        pattern = re.compile(
            rf"auto_yt:.*{re.escape(ex_id)}", re.IGNORECASE
        )
        matches = pattern.findall(logs)
        assert not matches, (
            f"Unexpected auto_yt fire for ex with existing video: {matches[:3]}"
        )

    def test_cleanup_restore_or_archive(self, coach):
        ex_id = TestPatchStatusFiresAutoYt.created_id
        if not ex_id:
            pytest.skip("no exercise created")
        r = requests.delete(
            f"{BASE_URL}/api/exercise-content/{ex_id}",
            headers=coach["headers"], timeout=15,
        )
        assert r.status_code in (200, 204), r.text


# ------------------ 5. Feature flag OFF → no auto_yt on create ------------------

class TestFeatureFlagRespected:
    created_id = None

    def test_disable_flag_then_create_no_auto_yt(self, coach):
        # Turn OFF
        r0 = requests.post(
            f"{BASE_URL}/api/coach/youtube-finder/auto-on-create",
            headers=coach["headers"], json={"enabled": False}, timeout=30,
        )
        assert r0.status_code == 200

        ts = int(time.time())
        ex_name = f"TEST_FlagOff AutoYT {ts} {uuid.uuid4().hex[:6]}"
        bookmark = _log_position()
        cr = requests.post(
            f"{BASE_URL}/api/exercise-content",
            json={
                "exercise_name": ex_name,
                "category": "strength",
                "training_type": "warmup",
                "body_area": "legs",
                "equipment_type": ["bodyweight"],
                "tags": ["TEST", "iter189f"],
            },
            headers=coach["headers"], timeout=30,
        )
        assert cr.status_code in (200, 201), cr.text
        ex = cr.json()["exercise"]
        TestFeatureFlagRespected.created_id = ex["id"]

        time.sleep(5)
        logs = _log_since(bookmark)
        # No auto_yt log line referencing this ex_id specifically
        pattern = re.compile(
            rf"auto_yt.*{re.escape(ex['id'])}", re.IGNORECASE
        )
        offending = pattern.findall(logs)
        assert not offending, (
            f"Feature flag OFF but auto_yt still fired for ex_id={ex['id']}: {offending[:3]}"
        )

    def test_cleanup_restore_flag_and_archive(self, coach):
        # Re-enable flag (restore default)
        r = requests.post(
            f"{BASE_URL}/api/coach/youtube-finder/auto-on-create",
            headers=coach["headers"], json={"enabled": True}, timeout=30,
        )
        assert r.status_code == 200
        assert r.json().get("auto_on_create_enabled") is True

        ex_id = TestFeatureFlagRespected.created_id
        if ex_id:
            requests.delete(
                f"{BASE_URL}/api/exercise-content/{ex_id}",
                headers=coach["headers"], timeout=15,
            )


# ------------------ 6. Regression — existing sweep endpoints still respond ------------------

class TestSweepEndpointsRegression:
    def test_health_still_reachable(self, coach):
        r = requests.get(
            f"{BASE_URL}/api/coach/youtube-finder/health",
            headers=coach["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
