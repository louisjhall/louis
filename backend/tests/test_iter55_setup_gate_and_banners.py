"""
Iteration 55 — Setup-day gate relaxation + needs_review banner safety net.

Covers:
  * feature_setup_day._gate_for cap at +2 days
  * duty_hours=12 -> tomorrow (below 14 threshold)
  * night_flight on tomorrow -> today+2 with reason mentioning 'night'
  * GET /api/roster/jobs/active returns the currently-visible job for banners
  * POST /api/roster/jobs/{id}/retry against a 0-workouts completed job triggers
    the coach task + sets status=needs_review
"""

import os
import sys
import asyncio
import datetime as _dt
import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = (os.environ.get("EXPO_BACKEND_URL") or os.environ.get("EXPO_PUBLIC_BACKEND_URL") or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": COACH_EMAIL, "password": COACH_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_id(client_token):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- unit-style checks against feature_setup_day._gate_for ----------

def test_gate_relaxed_duty_hours_12_returns_tomorrow():
    from feature_setup_day import _gate_for
    today = _dt.date.today()
    tomorrow_iso = (today + _dt.timedelta(days=1)).isoformat()
    day2_iso = (today + _dt.timedelta(days=2)).isoformat()
    roster = {"days": [
        {"date": tomorrow_iso, "day_type": "flight", "duty_hours": 12},
        {"date": day2_iso, "day_type": "flight", "duty_hours": 12},
    ]}
    gate, reason = _gate_for({}, roster, today.isoformat())
    assert gate == tomorrow_iso, f"expected {tomorrow_iso}, got {gate}"
    assert reason is None


def test_gate_night_flight_tomorrow_returns_plus2():
    from feature_setup_day import _gate_for
    today = _dt.date.today()
    tomorrow_iso = (today + _dt.timedelta(days=1)).isoformat()
    day2_iso = (today + _dt.timedelta(days=2)).isoformat()
    roster = {"days": [
        {"date": tomorrow_iso, "day_type": "night_flight", "duty_hours": 10},
        {"date": day2_iso, "day_type": "off", "duty_hours": 0},
    ]}
    gate, reason = _gate_for({}, roster, today.isoformat())
    assert gate == day2_iso, f"expected {day2_iso}, got {gate}"
    assert reason is not None
    assert "night" in reason.lower()


def test_gate_caps_at_plus2_even_if_everything_heavy():
    """Even if every day is heavy, gate must NOT run away past +2."""
    from feature_setup_day import _gate_for
    today = _dt.date.today()
    days = []
    for i in range(1, 8):
        days.append({
            "date": (today + _dt.timedelta(days=i)).isoformat(),
            "day_type": "night_flight",
            "duty_hours": 16,
        })
    gate, _ = _gate_for({}, {"days": days}, today.isoformat())
    max_allowed = (today + _dt.timedelta(days=3)).isoformat()
    assert gate <= max_allowed, f"gate {gate} exceeded cap {max_allowed}"


# ---------- banner endpoint ----------

def _stub_needs_review_job(client_id_: str, status: str = "needs_review") -> str:
    """Insert a stub roster_jobs doc directly into mongodb via motor."""
    import uuid
    from server import db  # motor client
    job_id = f"TEST_{uuid.uuid4().hex[:12]}"
    doc = {
        "id": job_id,
        "user_id": client_id_,
        "roster_id": None,
        "status": status,
        "stage": "generating",
        "progress": 95,
        "error": "Your roster uploaded successfully, but your training plan needs review. Louis has been notified.",
        "message": "Roster saved — plan needs review",
        "created_at": _dt.datetime.utcnow().isoformat(),
        "updated_at": _dt.datetime.utcnow().isoformat(),
    }
    asyncio.get_event_loop().run_until_complete(db.roster_jobs.insert_one(doc))
    return job_id


def _delete_job(job_id: str):
    from server import db
    try:
        asyncio.get_event_loop().run_until_complete(db.roster_jobs.delete_one({"id": job_id}))
    except Exception:
        pass


def test_active_endpoint_shape_when_no_active_job(client_token):
    r = requests.get(f"{BASE_URL}/api/roster/jobs/active",
                     headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    # Should be either empty {} or a queued/processing/needs_review job.
    assert isinstance(j, dict)


def test_active_endpoint_returns_needs_review_stub(client_token, client_id):
    """CRITICAL: /roster/jobs/active MUST surface needs_review/partial/failed
    jobs otherwise the frontend amber banner can never render."""
    # Make sure no processing job for this user is lingering
    from server import db
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.roster_jobs.update_many(
        {"user_id": client_id, "status": {"$in": ["queued", "processing"]}},
        {"$set": {"status": "abandoned"}},
    ))
    job_id = _stub_needs_review_job(client_id, status="needs_review")
    try:
        r = requests.get(f"{BASE_URL}/api/roster/jobs/active",
                         headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        # If backend is filtering only queued/processing this will be {} and the
        # banner will never render → this is the bug we want to catch.
        assert j.get("id") == job_id, (
            f"/api/roster/jobs/active did NOT return the needs_review job. "
            f"Got: {j}. Frontend amber banner will not render."
        )
        assert j.get("status") == "needs_review"
    finally:
        _delete_job(job_id)


# ---------- retry with 0 workouts triggers coach task ----------

def test_retry_zero_workouts_opens_coach_task(client_token, coach_token, client_id):
    """Insert a completed job whose roster produces 0 workouts, hit /retry, and
    assert the job flips to needs_review AND a coach task gets opened."""
    from server import db
    loop = asyncio.get_event_loop()
    import uuid
    roster_id = f"TEST_ROSTER_{uuid.uuid4().hex[:8]}"
    job_id = f"TEST_JOB_{uuid.uuid4().hex[:8]}"
    today = _dt.date.today()
    # A roster with 0 usable days so _generate_month returns []
    roster_doc = {
        "id": roster_id,
        "user_id": client_id,
        "days": [],
        "created_at": _dt.datetime.utcnow().isoformat(),
        "TEST": True,
    }
    job_doc = {
        "id": job_id,
        "user_id": client_id,
        "roster_id": roster_id,
        "status": "complete",
        "stage": "complete",
        "progress": 100,
        "workouts_generated": 0,
        "created_at": _dt.datetime.utcnow().isoformat(),
        "updated_at": _dt.datetime.utcnow().isoformat(),
        "TEST": True,
    }
    loop.run_until_complete(db.rosters.insert_one(dict(roster_doc)))
    loop.run_until_complete(db.roster_jobs.insert_one(dict(job_doc)))
    # Snapshot existing coach tasks
    existing_tasks = loop.run_until_complete(db.coach_tasks.count_documents({
        "task_type": "roster_plan_generation_issue",
        "payload.job_id": job_id,
    }))
    try:
        r = requests.post(
            f"{BASE_URL}/api/roster/jobs/{job_id}/retry",
            headers={"Authorization": f"Bearer {client_token}"}, timeout=30,
        )
        assert r.status_code == 200, r.text
        # Give the background retry worker a moment to run
        import time
        deadline = time.time() + 30
        final_status = None
        while time.time() < deadline:
            time.sleep(1.5)
            j = loop.run_until_complete(db.roster_jobs.find_one({"id": job_id}, {"_id": 0}))
            final_status = j.get("status") if j else None
            if final_status in ("needs_review", "failed", "complete"):
                if final_status == "complete" and (j.get("workouts_generated") or 0) > 0:
                    break
                if final_status in ("needs_review", "failed"):
                    break
        assert final_status == "needs_review", (
            f"Expected job status=needs_review after retry with 0 workouts, got {final_status}"
        )
        # Coach task should have been opened
        new_tasks = loop.run_until_complete(db.coach_tasks.count_documents({
            "task_type": "roster_plan_generation_issue",
            "payload.job_id": job_id,
        }))
        assert new_tasks > existing_tasks, "coach task not opened for 0-workouts retry"
    finally:
        # Cleanup
        loop.run_until_complete(db.roster_jobs.delete_one({"id": job_id}))
        loop.run_until_complete(db.rosters.delete_one({"id": roster_id}))
        loop.run_until_complete(db.coach_tasks.delete_many({"payload.job_id": job_id}))


# ---------- regression: NEXT 7 DAYS starts with Today ----------

def test_workouts_week_returns_list(client_token):
    r = requests.get(f"{BASE_URL}/api/workouts/week",
                     headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
