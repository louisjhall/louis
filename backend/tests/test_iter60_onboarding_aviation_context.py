"""
Iteration 60 — Basic Profile Setup follow-up.

Verifies the new aviation-context fields on the onboarding step:
  - job_title, route_focus, aircraft_type, main_goal_key persist to user.profile
  - _resolve_goal_key prefers structured main_goal_key over free-text
  - invalid key falls through gracefully to keyword matcher
  - null key + free-text goal='lose 4kg' still resolves to lose_fat (regression)
  - programme_context_for_llm.profile_snapshot includes the new fields
"""

import os
import sys
import asyncio

import pytest
import requests

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"

# Make backend module importable for unit tests on _resolve_goal_key.
sys.path.insert(0, "/app/backend")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _login(email, pw):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    j = r.json()
    return j["token"], j["user"]


@pytest.fixture(scope="module")
def client_auth():
    token, user = _login(CLIENT_EMAIL, CLIENT_PW)
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


# ---------------------------------------------------------------------------
# Utility — fetch /auth/me
# ---------------------------------------------------------------------------
def _me(headers):
    r = requests.get(f"{API}/auth/me", headers=headers, timeout=30)
    assert r.status_code == 200, f"/auth/me failed: {r.status_code} {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# 1. POST /api/auth/onboarding with new fields → persists + onboarded=true
# ---------------------------------------------------------------------------
class TestOnboardingPersistsNewFields:
    def test_onboarding_saves_aviation_fields(self, client_auth):
        payload = {
            "airline": "TEST_Skyline Air",
            "home_base": "LHR",
            "position": "Pilot",
            "job_title": "Captain",
            "route_focus": "long_haul",
            "aircraft_type": "A380",
            "main_goal_key": "build_muscle",
            "equipment": ["dumbbells", "yoga mat"],
            "cardio_equipment": [],
            "training_location": "home gym",
            "max_home_minutes": 60,
            "preferred_days": ["Mon", "Wed", "Fri"],
            "disliked_exercises": None,
            "injuries": None,
            "goal": "Build strength on rotations",
            "experience_level": "intermediate",
            "strength_level": "intermediate",
            "will_run_outside": True,
            "swim_cycle": None,
            "training_days_per_week": 4,
            "height_cm": 180,
            "weight_kg": 82,
            "calorie_target": 2400,
            "protein_target": 160,
        }
        r = requests.post(
            f"{API}/auth/onboarding",
            json=payload,
            headers=client_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"
        body = r.json()
        assert body.get("onboarded") is True
        prof = body.get("profile") or {}
        assert prof.get("job_title") == "Captain"
        assert prof.get("route_focus") == "long_haul"
        assert prof.get("aircraft_type") == "A380"
        assert prof.get("main_goal_key") == "build_muscle"
        # Existing fields still there
        assert prof.get("airline") == "TEST_Skyline Air"
        assert prof.get("home_base") == "LHR"
        assert prof.get("position") == "Pilot"

    def test_me_reflects_persisted_profile(self, client_auth):
        me = _me(client_auth["headers"])
        prof = me.get("profile") or {}
        assert prof.get("job_title") == "Captain"
        assert prof.get("route_focus") == "long_haul"
        assert prof.get("main_goal_key") == "build_muscle"


# ---------------------------------------------------------------------------
# 2. Unit test: _resolve_goal_key structured key wins
# ---------------------------------------------------------------------------
class TestResolveGoalKey:
    def test_structured_key_used_when_valid(self):
        from feature_programme_quality import _resolve_goal_key
        profile = {
            "main_goal_key": "build_muscle",
            "goal": "lose weight",  # would have matched lose_fat via keywords
        }
        assert _resolve_goal_key(profile) == "build_muscle"

    def test_invalid_structured_key_falls_through_to_text(self):
        from feature_programme_quality import _resolve_goal_key
        profile = {
            "main_goal_key": "nonsense_key",
            "goal": "lose 4kg",
        }
        # Must not crash and must fall through to free-text matcher.
        assert _resolve_goal_key(profile) == "lose_fat"

    def test_null_key_free_text_lose_fat(self):
        from feature_programme_quality import _resolve_goal_key
        profile = {"main_goal_key": None, "goal": "lose 4kg"}
        assert _resolve_goal_key(profile) == "lose_fat"

    def test_missing_key_free_text_lose_fat(self):
        from feature_programme_quality import _resolve_goal_key
        # No main_goal_key at all
        assert _resolve_goal_key({"goal": "lose 4kg"}) == "lose_fat"

    def test_empty_profile_returns_default(self):
        from feature_programme_quality import _resolve_goal_key, DEFAULT_GOAL_KEY
        assert _resolve_goal_key({}) == DEFAULT_GOAL_KEY

    def test_all_valid_goal_keys_supported(self):
        from feature_programme_quality import _resolve_goal_key, GOAL_MATRIX
        for k in GOAL_MATRIX.keys():
            assert _resolve_goal_key({"main_goal_key": k}) == k


# ---------------------------------------------------------------------------
# 3. Unit test: programme_context_for_llm.profile_snapshot includes new fields
# ---------------------------------------------------------------------------
class TestProgrammeContextSnapshot:
    def test_snapshot_includes_new_fields(self):
        from feature_programme_quality import programme_context_for_llm

        user = {
            "id": "TEST_user_unit_1",
            "profile": {
                "job_title": "Captain",
                "airline": "Skyline",
                "home_base": "LHR",
                "route_focus": "long_haul",
                "aircraft_type": "A380",
                "main_goal_key": "build_muscle",
                "experience": "intermediate",
            },
        }
        roster = {"id": "TEST_roster_unit_1", "days": [{"date": "2026-01-06", "day_type": "off"}]}
        ctx = asyncio.get_event_loop().run_until_complete(
            programme_context_for_llm(user, roster)
        )
        snap = ctx.get("profile_snapshot") or {}
        assert snap.get("job_title") == "Captain"
        assert snap.get("airline") == "Skyline"
        assert snap.get("home_base") == "LHR"
        assert snap.get("route_focus") == "long_haul"
        assert snap.get("aircraft_type") == "A380"
        assert snap.get("main_goal_key") == "build_muscle"
        # goal_key resolved correctly
        assert ctx.get("goal_key") == "build_muscle"
        # build_muscle target = 4 sessions/wk (unless beginner-capped)
        assert ctx.get("target_sessions_per_week") == 4


# ---------------------------------------------------------------------------
# 4. End-to-end: after onboarding with main_goal_key='build_muscle',
#    /api/programme/current reflects goal_key='build_muscle' + target=4.
#    We trigger via a retry on the existing completed roster job (fast),
#    same technique used in iter59.
# ---------------------------------------------------------------------------
class TestProgrammeReflectsBuildMuscle:
    def test_programme_shows_build_muscle_after_regenerate(self, client_auth):
        import time
        from pymongo import MongoClient

        MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")
        mongo_db = MongoClient(MONGO_URL)[DB_NAME]

        uid = client_auth["user"]["id"]
        job = mongo_db.roster_jobs.find_one(
            {"user_id": uid, "roster_id": {"$ne": None},
             "status": {"$in": ["complete", "done", "needs_review", "failed"]}},
            sort=[("created_at", -1)],
        )
        if not job:
            pytest.skip("no completed roster_job for client; skip end-to-end programme check")
        job_id = job["id"]

        r = requests.post(
            f"{API}/roster/jobs/{job_id}/retry",
            headers=client_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200, f"{r.status_code} {r.text}"

        deadline = time.time() + 240
        last = None
        while time.time() < deadline:
            s = requests.get(
                f"{API}/roster/jobs/{job_id}", headers=client_auth["headers"], timeout=30
            ).json()
            last = s
            if s.get("status") in ("complete", "done", "needs_review", "failed"):
                break
            time.sleep(4)
        assert last and last.get("status") in ("complete", "done", "needs_review"), \
            f"retry did not complete: {last}"

        p = requests.get(
            f"{API}/programme/current", headers=client_auth["headers"], timeout=30
        ).json()
        assert p, "programme empty"
        assert p.get("goal_key") == "build_muscle", \
            f"expected build_muscle, got {p.get('goal_key')}"
        # build_muscle default target=4 (unless beginner-capped to 3)
        assert int(p.get("target_sessions_per_week") or 0) in (3, 4, 5)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
