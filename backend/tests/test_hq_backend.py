"""Tests for CrewFit Coaching Headquarters backend endpoints.

Covers the 7 new HQ-related endpoints added ~line 1200-1450 in
`/app/backend/server.py`:

  * PATCH  /api/user/profile
  * GET    /api/personal-records
  * POST   /api/personal-records
  * PATCH  /api/personal-records/{pr_id}
  * DELETE /api/personal-records/{pr_id}
  * GET    /api/achievements
  * GET    /api/notes/coach
  * GET    /api/notes/ai

Live backend @ http://localhost:8001. Auth = seeded client
(client@crewfit.com / Client123!). Cleanup: created PR is deleted; the
seeded client's `name` is restored after the name-change test.
"""

import datetime as _dt

import pytest
import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"

EXPECTED_STAT_KEYS = {
    "workouts_completed", "workouts_total", "personal_records",
    "events_planned", "assessments_completed", "current_streak",
    "reality_adaptations",
}
EXPECTED_BADGE_IDS = {
    "first_workout", "ten_workouts", "fifty_workouts", "century",
    "streak_3", "streak_7", "streak_14",
    "first_pr", "event_planner", "intelligence", "adaptive",
}


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture(scope="module")
def auth():
    """Login as the seeded client and remember the original name so we
    can restore it after the name-change test."""
    r = requests.post(
        f"{API}/auth/login",
        json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data["token"]
    user = data["user"]
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    original_name = user.get("name") or "Alex Rivera"

    yield {"token": token, "user": user, "headers": headers,
           "original_name": original_name}

    # Teardown — restore original name if it was changed
    try:
        requests.patch(
            f"{API}/user/profile",
            json={"name": original_name},
            headers=headers,
            timeout=15,
        )
    except Exception as e:
        print(f"WARN: failed to restore original name: {e}")


# ==================================================================
# PATCH /api/user/profile
# ==================================================================
class TestUserProfilePatch:
    def test_patch_profile_fields(self, auth):
        payload = {"height_cm": 181, "weight_kg": 79.5, "dob": "1990-05-12"}
        r = requests.patch(f"{API}/user/profile", json=payload,
                           headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        u = body.get("user")
        assert u, f"no user in response: {body}"
        profile = u.get("profile") or {}
        assert profile.get("height_cm") == 181, profile
        assert profile.get("weight_kg") == 79.5, profile
        assert profile.get("dob") == "1990-05-12", profile

    def test_patch_name_updates_root(self, auth):
        r = requests.patch(f"{API}/user/profile",
                           json={"name": "Alex CrewFit"},
                           headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        u = r.json().get("user")
        assert u.get("name") == "Alex CrewFit", u

    def test_patch_empty_body_noop(self, auth):
        r = requests.patch(f"{API}/user/profile", json={},
                           headers=auth["headers"], timeout=15)
        assert r.status_code == 200, f"empty patch should be 200 no-op: {r.status_code} {r.text}"
        u = r.json().get("user")
        assert u is not None


# ==================================================================
# Personal Records CRUD
# ==================================================================
class TestPersonalRecordsCRUD:
    """Order-sensitive: create → list → patch → delete."""

    def test_01_list_initial(self, auth):
        r = requests.get(f"{API}/personal-records",
                         headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "records" in body and isinstance(body["records"], list), body

    def test_02_create(self, auth, request):
        payload = {
            "name": "Back Squat 1RM",
            "category": "strength",
            "value": 140.0,
            "unit": "kg",
            "notes": "felt strong",
        }
        r = requests.post(f"{API}/personal-records", json=payload,
                          headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        rec = r.json().get("record")
        assert rec, r.text
        assert rec.get("id"), rec
        assert rec.get("name") == "Back Squat 1RM"
        assert rec.get("category") == "strength"
        assert rec.get("value") == 140.0
        assert rec.get("unit") == "kg"
        assert rec.get("notes") == "felt strong"
        # date defaults to today (utc)
        today = _dt.datetime.utcnow().date().isoformat()
        assert rec.get("date") == today, f"expected date={today}, got {rec.get('date')}"
        # Stash for later tests + cleanup
        request.config.cache.set("hq/pr_id", rec["id"])

    def test_03_list_includes_new(self, auth, request):
        pr_id = request.config.cache.get("hq/pr_id", None)
        assert pr_id, "create test must run first"
        r = requests.get(f"{API}/personal-records",
                         headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        records = r.json().get("records", [])
        found = [rec for rec in records if rec.get("id") == pr_id]
        assert found, f"created PR {pr_id} not in list"
        assert found[0].get("value") == 140.0

    def test_04_patch(self, auth, request):
        pr_id = request.config.cache.get("hq/pr_id", None)
        assert pr_id
        payload = {
            "name": "Back Squat 1RM",
            "category": "strength",
            "value": 145.0,
            "unit": "kg",
        }
        r = requests.patch(f"{API}/personal-records/{pr_id}", json=payload,
                           headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        rec = r.json().get("record")
        assert rec, r.text
        assert rec.get("value") == 145.0, rec
        assert rec.get("id") == pr_id

    def test_05_patch_nonexistent_returns_404(self, auth):
        payload = {"name": "x", "value": 1.0, "unit": "kg"}
        r = requests.patch(f"{API}/personal-records/nonexistent_id_xyz",
                           json=payload, headers=auth["headers"], timeout=15)
        assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text}"

    def test_06_delete(self, auth, request):
        pr_id = request.config.cache.get("hq/pr_id", None)
        assert pr_id
        r = requests.delete(f"{API}/personal-records/{pr_id}",
                            headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("deleted") is True, body
        # verify gone
        r2 = requests.get(f"{API}/personal-records",
                          headers=auth["headers"], timeout=15)
        assert r2.status_code == 200
        records = r2.json().get("records", [])
        assert not any(rec.get("id") == pr_id for rec in records), \
            f"PR {pr_id} still in list after delete"

    def test_07_delete_nonexistent_returns_deleted_false(self, auth):
        r = requests.delete(f"{API}/personal-records/nonexistent_id_xyz",
                            headers=auth["headers"], timeout=15)
        assert r.status_code == 200, f"expected 200 (not 404): {r.status_code} {r.text}"
        assert r.json().get("deleted") is False, r.json()


# ==================================================================
# GET /api/achievements
# ==================================================================
class TestAchievements:
    def test_shape(self, auth):
        r = requests.get(f"{API}/achievements",
                         headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()

        stats = body.get("stats")
        assert isinstance(stats, dict), body
        assert set(stats.keys()) == EXPECTED_STAT_KEYS, \
            f"stats keys mismatch: {set(stats.keys())} vs {EXPECTED_STAT_KEYS}"
        # all stat values numeric
        for k, v in stats.items():
            assert isinstance(v, (int, float)) and not isinstance(v, bool), \
                f"stat {k} not numeric: {v!r}"
        # current_streak must be int
        assert isinstance(stats["current_streak"], int), \
            f"current_streak not int: {stats['current_streak']!r}"
        assert stats["current_streak"] >= 0

        badges = body.get("badges")
        assert isinstance(badges, list) and len(badges) == 11, \
            f"expected 11 badges, got {len(badges) if isinstance(badges, list) else type(badges)}"
        got_ids = {b.get("id") for b in badges}
        assert got_ids == EXPECTED_BADGE_IDS, \
            f"badge id mismatch: {got_ids} vs {EXPECTED_BADGE_IDS}"
        for b in badges:
            for key in ("id", "title", "sub", "emoji", "unlocked"):
                assert key in b, f"badge missing {key}: {b}"
            assert isinstance(b["unlocked"], bool), \
                f"unlocked not bool for {b['id']}: {b['unlocked']!r}"


# ==================================================================
# GET /api/notes/coach & /api/notes/ai
# ==================================================================
class TestNotes:
    def test_notes_coach_shape(self, auth):
        r = requests.get(f"{API}/notes/coach",
                         headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("workout_notes", "reality_reviews", "messages"):
            assert key in body, f"missing key {key} in {body}"
            assert isinstance(body[key], list), \
                f"{key} not a list: {type(body[key])}"
        # every workout_note must have non-empty coach_notes
        for w in body["workout_notes"]:
            assert w.get("coach_notes"), \
                f"workout_note has empty coach_notes: {w}"

    def test_notes_ai_shape(self, auth):
        r = requests.get(f"{API}/notes/ai",
                         headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("dna_history", "reality_context", "move_rationales"):
            assert key in body, f"missing key {key} in {body}"
            assert isinstance(body[key], list), \
                f"{key} not a list: {type(body[key])}"
        # every reality_context item has context_summary
        for rc in body["reality_context"]:
            assert rc.get("context_summary"), \
                f"reality_context missing context_summary: {rc}"


# ==================================================================
# Auth gating — all endpoints reject unauthenticated
# ==================================================================
class TestAuthGating:
    ENDPOINTS = [
        ("PATCH",  "/user/profile",              {"height_cm": 170}),
        ("GET",    "/personal-records",          None),
        ("POST",   "/personal-records",
         {"name": "x", "value": 1.0, "unit": "kg"}),
        ("PATCH",  "/personal-records/xxx",
         {"name": "x", "value": 1.0, "unit": "kg"}),
        ("DELETE", "/personal-records/xxx",      None),
        ("GET",    "/achievements",              None),
        ("GET",    "/notes/coach",               None),
        ("GET",    "/notes/ai",                  None),
    ]

    @pytest.mark.parametrize("method,path,payload", ENDPOINTS)
    def test_no_auth_rejected(self, method, path, payload):
        url = f"{API}{path}"
        kwargs = {"timeout": 10}
        if payload is not None:
            kwargs["json"] = payload
        r = requests.request(method, url, **kwargs)
        assert r.status_code in (401, 403), \
            f"{method} {path}: expected 401/403 got {r.status_code} ({r.text[:150]})"
