"""
Iteration 56 — Roster-upload safety-net re-verification.

Covers:
  * GET /api/roster/jobs/active surfaces needs_review job (within 7d, not ack'd)
  * GET /api/roster/jobs/active hides jobs where client_acknowledged=true
  * GET /api/roster/jobs/active still surfaces queued/processing (regression)
  * POST /api/roster/jobs/{id}/acknowledge dismisses the job (→ empty)
  * POST /api/roster/jobs/{unknown}/acknowledge returns 404
"""

import os
import sys
import asyncio
import datetime as _dt
import uuid
import pytest
import requests

sys.path.insert(0, "/app/backend")

def _load_backend_url():
    for k in ("EXPO_BACKEND_URL", "EXPO_PUBLIC_BACKEND_URL", "EXPO_PACKAGER_HOSTNAME"):
        v = os.environ.get(k)
        if v:
            return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as fh:
            for line in fh:
                line = line.strip()
                for k in ("EXPO_BACKEND_URL", "EXPO_PUBLIC_BACKEND_URL", "EXPO_PACKAGER_HOSTNAME"):
                    if line.startswith(k + "="):
                        return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    except Exception:
        pass
    return ""

BASE_URL = _load_backend_url()
assert BASE_URL, "EXPO_BACKEND_URL not resolvable"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": CLIENT_EMAIL, "password": CLIENT_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_id(client_token):
    r = requests.get(f"{BASE_URL}/api/auth/me",
                     headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _wipe_active_jobs(client_id):
    """Ensure no lingering jobs from other tests pollute /active for this user.
    We flip queued/processing to abandoned, and mark existing needs_review/partial/failed
    as already acknowledged so they don't leak into these tests."""
    from server import db
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.roster_jobs.update_many(
        {"user_id": client_id, "status": {"$in": ["queued", "processing"]}},
        {"$set": {"status": "abandoned"}},
    ))
    loop.run_until_complete(db.roster_jobs.update_many(
        {"user_id": client_id, "status": {"$in": ["needs_review", "partial", "failed"]},
         "client_acknowledged": {"$ne": True}},
        {"$set": {"client_acknowledged": True, "acknowledged_at": _dt.datetime.utcnow().isoformat()}},
    ))
    yield


def _insert_stub_job(user_id: str, status: str, acknowledged: bool = False,
                     updated_delta_days: int = 0) -> str:
    """Insert a roster_jobs doc directly. updated_delta_days<0 means older."""
    from server import db
    loop = asyncio.get_event_loop()
    job_id = f"TEST_JOB_{uuid.uuid4().hex[:10]}"
    updated_at = (_dt.datetime.utcnow() + _dt.timedelta(days=updated_delta_days)).isoformat()
    doc = {
        "id": job_id,
        "user_id": user_id,
        "roster_id": None,
        "status": status,
        "stage": "generating",
        "progress": 95,
        "message": f"stub {status}",
        "created_at": updated_at,
        "updated_at": updated_at,
        "TEST": True,
    }
    if acknowledged:
        doc["client_acknowledged"] = True
        doc["acknowledged_at"] = updated_at
    loop.run_until_complete(db.roster_jobs.insert_one(doc))
    return job_id


def _delete_job(job_id: str):
    from server import db
    try:
        asyncio.get_event_loop().run_until_complete(
            db.roster_jobs.delete_one({"id": job_id})
        )
    except Exception:
        pass


# ---------- tests ----------

def test_active_returns_needs_review_within_7_days(client_token, client_id):
    """A recent needs_review job (not ack'd) MUST be surfaced by /roster/jobs/active."""
    job_id = _insert_stub_job(client_id, "needs_review")
    try:
        r = requests.get(f"{BASE_URL}/api/roster/jobs/active",
                         headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("id") == job_id, f"needs_review job not surfaced. Got: {j}"
        assert j.get("status") == "needs_review"
    finally:
        _delete_job(job_id)


def test_active_hides_acknowledged_needs_review(client_token, client_id):
    """A needs_review job with client_acknowledged=true MUST NOT be surfaced."""
    job_id = _insert_stub_job(client_id, "needs_review", acknowledged=True)
    try:
        r = requests.get(f"{BASE_URL}/api/roster/jobs/active",
                         headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j == {}, f"Acknowledged job should be hidden, got: {j}"
    finally:
        _delete_job(job_id)


def test_active_still_returns_processing_job(client_token, client_id):
    """Regression: queued/processing jobs still surface (no ack gate)."""
    job_id = _insert_stub_job(client_id, "processing")
    try:
        r = requests.get(f"{BASE_URL}/api/roster/jobs/active",
                         headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("id") == job_id, f"processing job not surfaced. Got: {j}"
        assert j.get("status") == "processing"
    finally:
        _delete_job(job_id)


def test_acknowledge_hides_needs_review_job(client_token, client_id):
    """POST /acknowledge should mark job ack'd → subsequent /active returns {}."""
    job_id = _insert_stub_job(client_id, "needs_review")
    try:
        # First confirm it surfaces
        r1 = requests.get(f"{BASE_URL}/api/roster/jobs/active",
                          headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
        assert r1.json().get("id") == job_id

        # Acknowledge it
        r2 = requests.post(f"{BASE_URL}/api/roster/jobs/{job_id}/acknowledge",
                           headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json() == {"ok": True}

        # DB should have client_acknowledged=true
        from server import db
        loop = asyncio.get_event_loop()
        doc = loop.run_until_complete(db.roster_jobs.find_one({"id": job_id}, {"_id": 0}))
        assert doc.get("client_acknowledged") is True
        assert doc.get("acknowledged_at")

        # Subsequent /active should be empty
        r3 = requests.get(f"{BASE_URL}/api/roster/jobs/active",
                          headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
        assert r3.status_code == 200
        assert r3.json() == {}, f"After ack, /active must be empty. Got: {r3.json()}"
    finally:
        _delete_job(job_id)


def test_acknowledge_unknown_job_returns_404(client_token):
    bogus = f"NO_SUCH_JOB_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{BASE_URL}/api/roster/jobs/{bogus}/acknowledge",
                      headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"


# ---------- regression ----------

def test_workouts_week_contains_today(client_token):
    """Regression: /workouts/week returns rows including today's ISO date so the
    frontend NEXT 7 DAYS list can render a 'Today' row at the top."""
    r = requests.get(f"{BASE_URL}/api/workouts/week",
                     headers={"Authorization": f"Bearer {client_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    today_iso = _dt.date.today().isoformat()
    dates = {(w.get("date") or "") for w in items}
    assert today_iso in dates, (
        f"Expected today's row ({today_iso}) in /workouts/week response so the "
        f"frontend can show 'Today' at top. Dates present: {sorted(dates)[:5]}..."
    )
