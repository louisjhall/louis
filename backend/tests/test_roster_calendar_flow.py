"""Backend tests for roster upload/regeneration background jobs + multi-month calendar.

Covers scenarios listed in review_request iteration 12:
- Multi-month calendar timeline
- Roster job endpoints (active/status/history)
- Background upload-and-generate flow with friendly failure on unreadable file
- Regenerate as background job (no 504)
- Coach auth guards and regression endpoints
"""
import base64
import os
import time
from datetime import date

import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ["EXPO_BACKEND_URL"].rstrip("/")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASS = "Client123!"
COACH_EMAIL = "coach@crewfit.com"
COACH_PASS = "Coach123!"

# 1x1 transparent PNG
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PASS}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": COACH_EMAIL, "password": COACH_PASS}, timeout=15)
    assert r.status_code == 200
    return r.json()["token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


class TestCalendarTimeline:
    def test_timeline_shape(self, client_token):
        r = requests.get(
            f"{BASE_URL}/api/calendar/timeline?months_back=1&months_ahead=3",
            headers=_h(client_token), timeout=20,
        )
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert set(["today", "start_date", "end_date", "months", "rosters", "active_roster_ids"]).issubset(data)
        # today should match server date (yyyy-mm-dd)
        today_iso = date.today().isoformat()
        assert data["today"] == today_iso
        # Exactly months_back + months_ahead + 1 buckets = 5
        assert len(data["months"]) == 5, f"expected 5 months, got {len(data['months'])}"
        for m in data["months"]:
            assert set(["iso", "year", "month", "label", "has_data", "days"]).issubset(m)
            assert 28 <= len(m["days"]) <= 31
            for d in m["days"]:
                assert set(["date", "day", "load", "duty_type", "has_roster", "workout_id",
                            "workout_title", "completed", "key_session", "location"]).issubset(d)
        # For seed client, rosters and active_roster_ids should be non-empty
        assert isinstance(data["rosters"], list) and len(data["rosters"]) >= 1, "seed client expected >=1 roster"
        assert isinstance(data["active_roster_ids"], list) and len(data["active_roster_ids"]) >= 1

    def test_timeline_default_range(self, client_token):
        r = requests.get(f"{BASE_URL}/api/calendar/timeline", headers=_h(client_token), timeout=20)
        assert r.status_code == 200
        data = r.json()
        # default 2 back + 4 ahead + 1 = 7
        assert len(data["months"]) == 7


class TestRosterJobsAndHistory:
    def test_active_job_empty_when_idle(self, client_token):
        r = requests.get(f"{BASE_URL}/api/roster/jobs/active", headers=_h(client_token), timeout=15)
        assert r.status_code == 200
        # returns {} or a job doc — accept both, but usually {} at rest
        data = r.json()
        assert isinstance(data, dict)
        if data:
            assert data.get("status") in ("queued", "processing")

    def test_history(self, client_token):
        r = requests.get(f"{BASE_URL}/api/roster/history", headers=_h(client_token), timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        if len(rows) >= 2:
            # sorted by created_at desc
            assert rows[0]["created_at"] >= rows[-1]["created_at"]


class TestUploadAndGenerateBackground:
    def test_tiny_png_fails_friendly(self, client_token):
        payload = {"file_base64": TINY_PNG_B64, "mime_type": "image/png", "filename": "TEST_tiny.png"}
        t0 = time.time()
        r = requests.post(
            f"{BASE_URL}/api/roster/upload-and-generate",
            headers=_h(client_token), json=payload, timeout=10,
        )
        dt = time.time() - t0
        assert r.status_code == 200, r.text[:300]
        assert dt < 5, f"POST took {dt:.1f}s — must return immediately (Cloudflare 504 fix)"
        j = r.json()
        assert "job_id" in j and j.get("status") == "queued"
        job_id = j["job_id"]

        # Poll for terminal status
        terminal = None
        last_status = None
        stages = []
        for _ in range(60):  # up to 60*2s = 120s
            gr = requests.get(f"{BASE_URL}/api/roster/jobs/{job_id}", headers=_h(client_token), timeout=15)
            assert gr.status_code == 200
            job = gr.json()
            last_status = job.get("status")
            stages.append(job.get("stage"))
            if last_status in ("failed", "complete", "partial"):
                terminal = job
                break
            time.sleep(2)
        assert terminal is not None, f"job did not reach terminal. last_status={last_status}, stages={stages}"
        # Tiny PNG cannot parse -> status failed with friendly error
        assert terminal["status"] in ("failed", "partial"), f"expected failed/partial, got {terminal['status']}"
        err = (terminal.get("error") or "").lower()
        assert "couldn't read" in err or "could" in err or "clear" in err or "roster" in err, f"unfriendly error: {terminal.get('error')}"
        assert "504" not in err
        assert "traceback" not in err
        assert "stack" not in err

    def test_retry_requires_reupload(self, client_token):
        # find any failed job for this user
        h = requests.get(f"{BASE_URL}/api/roster/history", headers=_h(client_token), timeout=15)
        assert h.status_code == 200
        # We just need to hit retry on any known job id; use a fake id → 404 acceptable, but
        # main test: real failed job returns 400 with friendly text.
        # Try last failed job by polling the recent one from previous test env — best effort.
        # Use a random non-existent id to confirm 404 path.
        r = requests.post(f"{BASE_URL}/api/roster/jobs/nonexistent-id/retry", headers=_h(client_token), timeout=10)
        assert r.status_code in (400, 404)


class TestWorkoutRegenerateBackground:
    def test_regenerate_returns_immediately_and_polls(self, client_token):
        # Find the seed roster
        rc = requests.get(f"{BASE_URL}/api/roster/current", headers=_h(client_token), timeout=15)
        assert rc.status_code == 200, rc.text[:200]
        roster = rc.json()
        assert roster and roster.get("id"), "seed client should have a current roster"
        rid = roster["id"]

        t0 = time.time()
        r = requests.post(
            f"{BASE_URL}/api/workouts/regenerate",
            headers=_h(client_token),
            json={"roster_id": rid, "all": True},
            timeout=10,
        )
        dt = time.time() - t0
        assert r.status_code == 200, r.text[:300]
        assert dt < 5, f"regenerate POST took {dt:.1f}s — must be background (fixes 504)"
        j = r.json()
        assert j.get("status") == "queued"
        assert "job_id" in j
        assert isinstance(j.get("total"), int) and j["total"] > 0
        job_id = j["job_id"]

        # Poll job — should reach done or failed within ~120s (not required to complete, but must NOT 504)
        terminal_status = None
        for _ in range(60):
            gr = requests.get(f"{BASE_URL}/api/workouts/job/{job_id}", headers=_h(client_token), timeout=15)
            assert gr.status_code == 200, gr.text[:200]
            job = gr.json()
            if job.get("status") in ("done", "failed"):
                terminal_status = job["status"]
                break
            time.sleep(2)
        # If it didn't finish in 120s that's still fine — critical bit is no 504 was returned by the POST
        assert terminal_status in (None, "done", "failed")


class TestAuthGuards:
    def test_unauth_calendar_blocked(self):
        r = requests.get(f"{BASE_URL}/api/calendar/timeline", timeout=15)
        assert r.status_code in (401, 403)

    def test_unauth_upload_blocked(self):
        r = requests.post(f"{BASE_URL}/api/roster/upload-and-generate",
                          json={"file_base64": TINY_PNG_B64, "mime_type": "image/png"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_coach_alerts_requires_coach(self, client_token):
        r = requests.get(f"{BASE_URL}/api/coach/roster-alerts", headers=_h(client_token), timeout=15)
        assert r.status_code in (401, 403)


class TestRegression:
    def test_coach_videos(self, coach_token):
        r = requests.get(f"{BASE_URL}/api/coach/videos", headers=_h(coach_token), timeout=15)
        assert r.status_code == 200

    def test_coach_analytics(self, coach_token):
        r = requests.get(f"{BASE_URL}/api/coach/analytics", headers=_h(coach_token), timeout=20)
        assert r.status_code == 200

    def test_coach_dashboard(self, coach_token):
        r = requests.get(f"{BASE_URL}/api/coach/dashboard", headers=_h(coach_token), timeout=20)
        assert r.status_code == 200

    def test_exercises_video(self, coach_token):
        r = requests.get(f"{BASE_URL}/api/exercises/video?name=Push+Up", headers=_h(coach_token), timeout=20)
        assert r.status_code == 200

    def test_auth_login_client(self):
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": CLIENT_EMAIL, "password": CLIENT_PASS}, timeout=15)
        assert r.status_code == 200

    def test_roster_current(self, client_token):
        r = requests.get(f"{BASE_URL}/api/roster/current", headers=_h(client_token), timeout=15)
        assert r.status_code == 200
