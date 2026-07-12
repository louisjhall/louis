"""
Iteration 57 — Roster generation timeout bumps.

Static + smoke checks after main agent bumped:
  * server.py:_run_chunk wraps call_claude in wait_for(..., timeout=75.0)
  * BOTH outer wait_for(_generate_month, ..., timeout=180.0) at ~2435 and ~2644
  * frontend roster-upload.tsx SLOW_MS=90_000 and STUCK_MS=210_000

We DO NOT trigger a real roster upload (would burn Gemini credits). We only:
  * static-check the exact constants in the source files
  * smoke check /api/setup-day/status responds 401 without auth
  * smoke check retry endpoint on a needs_review stub job returns
    {job_id, status: 'processing'} and does not immediately fail
  * smoke check /api/roster/jobs/active still surfaces needs_review jobs
    (iteration 56 regression)
"""

import os
import re
import sys
import asyncio
import datetime as _dt
import time
import uuid
import pytest
import requests

sys.path.insert(0, "/app/backend")


def _load_backend_url() -> str:
    for k in ("EXPO_BACKEND_URL", "EXPO_PUBLIC_BACKEND_URL"):
        v = os.environ.get(k)
        if v:
            return v.rstrip("/")
    try:
        with open("/app/frontend/.env") as fh:
            for line in fh:
                line = line.strip()
                for k in ("EXPO_BACKEND_URL", "EXPO_PUBLIC_BACKEND_URL"):
                    if line.startswith(k + "="):
                        return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    except Exception:
        pass
    return ""


BASE_URL = _load_backend_url()
assert BASE_URL, "EXPO_BACKEND_URL not resolvable"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"

SERVER_PY = "/app/backend/server.py"
ROSTER_TSX = "/app/frontend/app/roster-upload.tsx"


# ---------- STATIC CHECKS ---------------------------------------------------

def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestStaticConstants:
    """Verify the exact constants the main agent claims to have bumped."""

    def test_run_chunk_wraps_call_claude_75s(self):
        src = _read(SERVER_PY)
        # `_run_chunk` must exist
        assert "async def _run_chunk(" in src, "_run_chunk helper missing"
        # And must wrap call_claude in wait_for(...timeout=75)
        pattern = r"wait_for\(\s*call_claude\([^)]*\)\s*,\s*timeout\s*=\s*75(\.0)?\s*\)"
        assert re.search(pattern, src), (
            "Expected asyncio.wait_for(call_claude(...), timeout=75.0) inside _run_chunk"
        )

    def test_outer_generate_month_180s_present_twice(self):
        src = _read(SERVER_PY)
        pattern = r"wait_for\(\s*_generate_month\(user,\s*roster\)\s*,\s*timeout\s*=\s*180(\.0)?\s*\)"
        matches = re.findall(pattern, src)
        assert len(matches) >= 2, (
            f"Expected TWO wait_for(_generate_month(user, roster), timeout=180.0) "
            f"calls (initial roster worker + retry worker); found {len(matches)}"
        )

    def test_no_stale_90s_or_120s_generate_month_timeouts(self):
        """Guard: main agent should NOT have left an old 90s/120s cap around
        _generate_month lurking anywhere in server.py."""
        src = _read(SERVER_PY)
        # 90 or 120 second wait_for wrapping _generate_month specifically
        stale = re.findall(
            r"wait_for\(\s*_generate_month\([^)]*\)\s*,\s*timeout\s*=\s*(?:90|120)(\.0)?\s*\)",
            src,
        )
        assert not stale, f"Found stale wait_for on _generate_month with 90s/120s: {stale}"

    def test_frontend_slow_and_stuck_constants(self):
        src = _read(ROSTER_TSX)
        assert re.search(r"const\s+SLOW_MS\s*=\s*90[_]?000\s*;", src), (
            "SLOW_MS must be 90_000 in roster-upload.tsx"
        )
        assert re.search(r"const\s+STUCK_MS\s*=\s*210[_]?000\s*;", src), (
            "STUCK_MS must be 210_000 in roster-upload.tsx"
        )


# ---------- BACKEND SMOKE ---------------------------------------------------

@pytest.fixture(scope="module")
def client_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": CLIENT_EMAIL, "password": CLIENT_PW},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_id(client_token):
    r = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {client_token}"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


class TestBackendSmoke:
    """Ensure backend server is reachable + core routes still respond."""

    def test_backend_reachable(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=10)
        # Some deployments return 200, some 404 — just want to prove the route
        # layer is up. Anything other than 5xx is fine.
        assert r.status_code < 500, f"backend not reachable: {r.status_code} {r.text[:200]}"

    def test_setup_day_status_requires_auth(self):
        """/api/setup-day/status must respond 401/403 without a token
        (endpoint reachable, not 404, not 500)."""
        r = requests.get(f"{BASE_URL}/api/setup-day/status", timeout=15)
        assert r.status_code in (401, 403), (
            f"expected 401/403 without auth, got {r.status_code}: {r.text[:200]}"
        )

    def test_setup_day_status_with_auth(self, client_token):
        r = requests.get(
            f"{BASE_URL}/api/setup-day/status",
            headers={"Authorization": f"Bearer {client_token}"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # Should return a dict payload (may vary per client).
        assert isinstance(r.json(), dict)


# ---------- RETRY ENDPOINT (stubbed job) ------------------------------------

def _insert_stub_roster_and_job(user_id: str, status: str = "needs_review") -> tuple[str, str]:
    """Insert a fake roster + needs_review job so we can hit /retry without
    running the real upload flow. Returns (job_id, roster_id)."""
    from server import db
    loop = asyncio.get_event_loop()
    roster_id = f"TEST_ROSTER_{uuid.uuid4().hex[:8]}"
    job_id = f"TEST_JOB_{uuid.uuid4().hex[:10]}"
    now = _dt.datetime.utcnow().isoformat()
    # Minimal roster — the retry worker just needs the doc to exist.
    roster_doc = {
        "id": roster_id,
        "user_id": user_id,
        "days": [],  # empty is OK; _generate_month handles empty gracefully
        "created_at": now,
        "updated_at": now,
        "TEST": True,
    }
    job_doc = {
        "id": job_id,
        "user_id": user_id,
        "roster_id": roster_id,
        "status": status,
        "stage": "generating",
        "progress": 90,
        "message": "stub needs_review",
        "created_at": now,
        "updated_at": now,
        "retry_count": 0,
        "TEST": True,
    }
    loop.run_until_complete(db.rosters.insert_one(roster_doc))
    loop.run_until_complete(db.roster_jobs.insert_one(job_doc))
    return job_id, roster_id


def _cleanup_stub(job_id: str, roster_id: str):
    from server import db
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(db.roster_jobs.delete_one({"id": job_id}))
    except Exception:
        pass
    try:
        loop.run_until_complete(db.rosters.delete_one({"id": roster_id}))
    except Exception:
        pass


class TestRetryEndpoint:
    """POST /api/roster/jobs/{id}/retry should immediately return processing
    on a needs_review job — worker runs in background."""

    def test_retry_needs_review_returns_processing(self, client_token, client_id):
        job_id, roster_id = _insert_stub_roster_and_job(client_id, "needs_review")
        try:
            r = requests.post(
                f"{BASE_URL}/api/roster/jobs/{job_id}/retry",
                headers={"Authorization": f"Bearer {client_token}"},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("job_id") == job_id, body
            assert body.get("status") == "processing", body

            # And DB should reflect status=processing right away (before worker
            # possibly transitions it to needs_review/partial).
            from server import db
            loop = asyncio.get_event_loop()
            time.sleep(0.5)
            doc = loop.run_until_complete(
                db.roster_jobs.find_one({"id": job_id}, {"_id": 0})
            )
            assert doc is not None
            # Worker may already have moved status forward, but retry_count
            # MUST have been bumped and stage set to generating.
            assert int(doc.get("retry_count") or 0) >= 1, doc
            assert doc.get("stage") == "generating", doc
        finally:
            _cleanup_stub(job_id, roster_id)

    def test_retry_unknown_job_returns_404(self, client_token):
        bogus = f"NO_SUCH_JOB_{uuid.uuid4().hex[:8]}"
        r = requests.post(
            f"{BASE_URL}/api/roster/jobs/{bogus}/retry",
            headers={"Authorization": f"Bearer {client_token}"},
            timeout=15,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:200]}"


# ---------- ITER56 REGRESSION ----------------------------------------------

class TestIter56Regression:
    """Re-verify /api/roster/jobs/active still surfaces needs_review/partial/failed
    (ack-gated) so the amber banner + retry flow keeps working."""

    def test_active_surfaces_needs_review(self, client_token, client_id):
        from server import db
        loop = asyncio.get_event_loop()

        # First hide any lingering unacknowledged jobs so this test is deterministic.
        loop.run_until_complete(db.roster_jobs.update_many(
            {
                "user_id": client_id,
                "status": {"$in": ["queued", "processing"]},
            },
            {"$set": {"status": "abandoned"}},
        ))
        loop.run_until_complete(db.roster_jobs.update_many(
            {
                "user_id": client_id,
                "status": {"$in": ["needs_review", "partial", "failed"]},
                "client_acknowledged": {"$ne": True},
            },
            {"$set": {"client_acknowledged": True,
                      "acknowledged_at": _dt.datetime.utcnow().isoformat()}},
        ))

        job_id, roster_id = _insert_stub_roster_and_job(client_id, "needs_review")
        try:
            r = requests.get(
                f"{BASE_URL}/api/roster/jobs/active",
                headers={"Authorization": f"Bearer {client_token}"},
                timeout=15,
            )
            assert r.status_code == 200, r.text
            j = r.json()
            assert j.get("id") == job_id, f"needs_review job not surfaced: {j}"
            assert j.get("status") == "needs_review"
        finally:
            _cleanup_stub(job_id, roster_id)
