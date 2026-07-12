"""Iteration 53: roster retry endpoint + assessment fallback icon (no emoji).

Covers:
- POST /api/roster/jobs/{id}/retry: 401 unauth, 404 missing job
- POST /api/roster/jobs/{id}/retry: 400 when job has no roster_id (via injected job)
- helpers _generation_heartbeat + _open_coach_task_for_stuck_generation import
- _assessment_fallback_next returns options with `icon` and NO `emoji`
- /api/setup-day/status: 401 without auth, 200 with auth (module-load sanity)
"""
import os
import uuid
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
import asyncio

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")


# ---------- retry endpoint auth + shape ------------------------------------
class TestRosterRetryEndpoint:
    def test_retry_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/roster/jobs/does-not-exist/retry", timeout=15)
        # FastAPI Depends(current_user) → 401 or 403 without token
        assert r.status_code in (401, 403), f"expected auth failure, got {r.status_code} {r.text}"

    def test_retry_404_for_missing_job(self, api, client_auth):
        r = api.post(
            f"{BASE_URL}/api/roster/jobs/nonexistent-{uuid.uuid4().hex[:8]}/retry",
            headers=client_auth["headers"], timeout=15,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"
        body = r.json()
        assert "detail" in body
        assert "not found" in body["detail"].lower()

    def test_retry_400_when_job_has_no_roster_id(self, api, client_auth):
        """Insert a fake completed job with roster_id=None and confirm retry returns 400."""
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "crewfit_v1")
        fake_job_id = f"TEST_{uuid.uuid4().hex[:12]}"
        user_id = client_auth["user"]["id"]

        async def _run():
            mc = AsyncIOMotorClient(mongo_url)
            db = mc[db_name]
            try:
                await db.roster_jobs.insert_one({
                    "id": fake_job_id,
                    "user_id": user_id,
                    "status": "failed",
                    "stage": "extracting",
                    "message": "roster unreadable",
                    "progress": 30,
                    "roster_id": None,
                    "error": "unreadable",
                    "retry_count": 0,
                    "created_at": "2026-01-01T00:00:00Z",
                })
                try:
                    r = requests.post(
                        f"{BASE_URL}/api/roster/jobs/{fake_job_id}/retry",
                        headers=client_auth["headers"], timeout=15,
                    )
                    return r.status_code, r.text
                finally:
                    await db.roster_jobs.delete_many({"id": fake_job_id})
            finally:
                mc.close()

        status, text = asyncio.run(_run())
        assert status == 400, f"expected 400 for no-roster job, got {status} {text}"
        assert "re-upload" in text.lower() or "no roster" in text.lower() or "did not save" in text.lower(), \
            f"expected helpful message, got: {text}"


# ---------- helper importability -------------------------------------------
class TestHelpersImport:
    def test_helpers_importable(self):
        """_generation_heartbeat + _open_coach_task_for_stuck_generation must load."""
        import importlib, sys
        # Ensure /app/backend is on the path
        if "/app/backend" not in sys.path:
            sys.path.insert(0, "/app/backend")
        srv = importlib.import_module("server")
        assert hasattr(srv, "_generation_heartbeat"), "missing _generation_heartbeat"
        assert hasattr(srv, "_open_coach_task_for_stuck_generation"), (
            "missing _open_coach_task_for_stuck_generation"
        )
        assert callable(srv._generation_heartbeat)
        assert callable(srv._open_coach_task_for_stuck_generation)


# ---------- assessment fallback: icon, no emoji ----------------------------
class TestAssessmentFallbackIcon:
    def test_fallback_uses_icon_and_no_emoji(self):
        """Directly call _assessment_fallback_next({}) — the deterministic
        fallback that populates icons for options."""
        import importlib, sys, json
        if "/app/backend" not in sys.path:
            sys.path.insert(0, "/app/backend")
        srv = importlib.import_module("server")
        # Empty assessment (no answers) → returns first question 'role'
        wrapper = srv._assessment_fallback_next({"answers": []})
        assert isinstance(wrapper, dict), f"expected dict, got {type(wrapper)}"
        assert "next_question" in wrapper, f"expected wrapper with next_question, got {list(wrapper.keys())}"
        q = wrapper["next_question"]
        assert q.get("id") == "role", f"expected role first, got {q.get('id')}"
        assert "options" in q, f"expected options in q, got {list(q.keys())}"
        opts = q["options"]
        assert isinstance(opts, list) and len(opts) > 0
        for opt in opts:
            assert "icon" in opt, f"option missing 'icon': {opt}"
            assert "emoji" not in opt, f"option should NOT have 'emoji': {opt}"

    def test_multi_fallback_questions_all_use_icon(self):
        """Walk the fallback through several answered questions — every one
        that returns options must use `icon` and no `emoji`."""
        import importlib, sys
        if "/app/backend" not in sys.path:
            sys.path.insert(0, "/app/backend")
        srv = importlib.import_module("server")
        # Simulate an assessment where role is already answered → should
        # move to primary_goal (multi-select with many options)
        wrapper2 = srv._assessment_fallback_next({
            "answers": [{"question_id": "role", "answer": "pilot"}]
        })
        assert isinstance(wrapper2, dict)
        q2 = wrapper2.get("next_question", {})
        assert q2.get("id") == "primary_goal", f"expected primary_goal, got {q2.get('id')}"
        for opt in q2.get("options", []):
            assert "icon" in opt
            assert "emoji" not in opt


# ---------- server module load sanity via /api/setup-day/status ------------
class TestSetupDayStatus:
    def test_setup_day_status_401_without_auth(self, api):
        r = api.get(f"{BASE_URL}/api/setup-day/status", timeout=15)
        assert r.status_code in (401, 403), f"expected auth failure, got {r.status_code} {r.text}"

    def test_setup_day_status_200_with_auth(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/setup-day/status", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, f"expected 200, got {r.status_code} {r.text}"
        body = r.json()
        # Just ensure shape has expected keys
        assert "is_setup_day" in body
