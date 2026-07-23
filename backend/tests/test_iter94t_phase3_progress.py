"""
Iter 94t Phase 3 — Dynamic Progress backend regression tests.

Covers:
- Body metrics CRUD (POST/GET)
- Running metrics CRUD (POST/GET)
- Strength metrics with Epley 1RM formula
- Progress photo base64 upload, signed URL fetch, list, delete
- HMAC token validation (invalid/expired → 403)
- Photo size and mime validation (>6MB → 413, bad mime → 400)
- Goal-adaptive dashboard payload shape and goal_class detection
- Admin coach client-detail progress dashboard (require_role=coach)
- Phase 1/2 regressions (app-config, media reconcile, calendar/range,
  recovery/missed, profile/timezone-status, nutrition/today)
"""
import base64
import io
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

CLIENT_EMAIL = "testcal2@crewfit.com"
CLIENT_PASS = "TestCal123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASS = "Louis123!"

# Tiny 1x1 red JPEG (base64). Small enough for happy-path tests.
TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwc"
    "KDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcI"
    "CQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRol"
    "JicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
    "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/APf6KKKACiiigD//2Q=="
)


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:200]}"
    return r.json()


@pytest.fixture(scope="module")
def client_data():
    return _login(CLIENT_EMAIL, CLIENT_PASS)


@pytest.fixture(scope="module")
def client_headers(client_data):
    return {"Authorization": f"Bearer {client_data['token']}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client_id(client_data):
    return client_data["user"]["id"]


@pytest.fixture(scope="module")
def coach_headers():
    d = _login(COACH_EMAIL, COACH_PASS)
    return {"Authorization": f"Bearer {d['token']}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Body metrics
# ---------------------------------------------------------------------------

class TestBodyMetrics:
    def test_post_body_metric_creates_entry(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/progress/body", headers=client_headers,
                          json={"weight_kg": 82.5, "waist_cm": 88.0,
                                "hips_cm": 96.0, "chest_cm": 101.0,
                                "notes": "TEST_iter94t_phase3"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        m = body["metric"]
        assert m["weight_kg"] == 82.5
        assert m["waist_cm"] == 88.0
        assert m["hips_cm"] == 96.0
        assert m["chest_cm"] == 101.0
        assert "id" in m and "date" in m and "user_id" in m
        assert "_id" not in m, "ObjectId should be excluded"

    def test_post_body_metric_rejects_all_null(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/progress/body", headers=client_headers,
                          json={"notes": "no measurements"}, timeout=30)
        assert r.status_code == 400, r.text

    def test_post_body_metric_validates_range(self, client_headers):
        # weight_kg must be 20..400
        r = requests.post(f"{BASE_URL}/api/progress/body", headers=client_headers,
                          json={"weight_kg": 999}, timeout=30)
        assert r.status_code == 422, r.text

    def test_get_body_metrics_returns_recent(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/progress/body",
                         params={"days": 30}, headers=client_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "metrics" in body and isinstance(body["metrics"], list)
        assert len(body["metrics"]) >= 1
        # Should contain our just-created row
        found = any(m.get("notes") == "TEST_iter94t_phase3" and m.get("weight_kg") == 82.5
                    for m in body["metrics"])
        assert found, "Newly-created body metric not returned in GET"

    def test_get_body_metrics_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/progress/body", timeout=30)
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Running metrics
# ---------------------------------------------------------------------------

class TestRunningMetrics:
    def test_post_running_creates_entry(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/progress/running", headers=client_headers,
                          json={"duration_min": 45.0, "distance_km": 8.2,
                                "rpe": 6, "session_type": "long_run",
                                "notes": "TEST_iter94t_phase3_run"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        m = body["metric"]
        assert m["duration_min"] == 45.0
        assert m["distance_km"] == 8.2
        assert m["session_type"] == "long_run"
        assert "id" in m and "_id" not in m

    def test_post_running_validates_duration(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/progress/running", headers=client_headers,
                          json={"duration_min": 0}, timeout=30)
        assert r.status_code == 422

    def test_get_running_metrics(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/progress/running",
                         params={"weeks": 4}, headers=client_headers, timeout=30)
        assert r.status_code == 200, r.text
        rows = r.json().get("metrics", [])
        assert isinstance(rows, list)
        assert any(m.get("notes") == "TEST_iter94t_phase3_run" for m in rows)


# ---------------------------------------------------------------------------
# Strength metrics + Epley 1RM
# ---------------------------------------------------------------------------

class TestStrengthMetrics:
    def test_post_strength_computes_epley_1rm(self, client_headers):
        # Epley: load × (1 + reps/30). For 100kg × 10 reps → 100 × (1 + 10/30) = 133.3
        r = requests.post(f"{BASE_URL}/api/progress/strength", headers=client_headers,
                          json={"exercise_name": "TEST_iter94t Back Squat",
                                "sets": 3, "reps": 10, "load_kg": 100.0,
                                "rpe": 7,
                                "notes": "TEST_iter94t_phase3_strength"}, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        m = body["metric"]
        assert m["exercise_name"] == "TEST_iter94t Back Squat"
        assert m["exercise_key"] == "test_iter94t back squat"
        assert m["load_kg"] == 100.0
        # Epley computed
        expected = round(100.0 * (1 + 10 / 30.0), 1)
        assert m["estimated_1rm_kg"] == expected, \
            f"Epley 1RM mismatch: expected {expected}, got {m['estimated_1rm_kg']}"
        assert m["estimated_1rm_kg"] == 133.3

    def test_post_strength_1rm_reps_1(self, client_headers):
        # 1 rep: load × (1 + 1/30) = load × 31/30
        r = requests.post(f"{BASE_URL}/api/progress/strength", headers=client_headers,
                          json={"exercise_name": "TEST_iter94t Deadlift 1RM",
                                "sets": 1, "reps": 1, "load_kg": 150.0}, timeout=30)
        assert r.status_code == 200
        expected = round(150.0 * (1 + 1 / 30.0), 1)  # 155.0
        assert r.json()["metric"]["estimated_1rm_kg"] == expected

    def test_get_strength(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/progress/strength",
                         params={"weeks": 4}, headers=client_headers, timeout=30)
        assert r.status_code == 200
        rows = r.json().get("metrics", [])
        assert any(m.get("notes") == "TEST_iter94t_phase3_strength" for m in rows)


# ---------------------------------------------------------------------------
# Progress photos: upload, list, signed-URL fetch, delete
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def uploaded_photo(client_headers):
    r = requests.post(f"{BASE_URL}/api/progress/photo/base64", headers=client_headers,
                      json={"angle": "front", "photo_b64": TINY_JPEG_B64,
                            "mime": "image/jpeg"}, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["photo"]


class TestProgressPhotos:
    def test_upload_base64_returns_signed_url(self, uploaded_photo):
        p = uploaded_photo
        assert "id" in p and "url" in p and "expires_at_epoch" in p
        assert p["url"].startswith("/api/progress/photo/")
        assert "u=" in p["url"] and "e=" in p["url"] and "t=" in p["url"]
        assert p["mime"] == "image/jpeg"
        assert p["angle"] == "front"
        assert p["private"] is True
        assert p["size_bytes"] > 0
        assert "_id" not in p

    def test_upload_rejects_bad_mime(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/progress/photo/base64", headers=client_headers,
                          json={"angle": "front", "photo_b64": TINY_JPEG_B64,
                                "mime": "image/gif"}, timeout=30)
        assert r.status_code == 400, r.text

    def test_upload_rejects_bad_angle(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/progress/photo/base64", headers=client_headers,
                          json={"angle": "sideways", "photo_b64": TINY_JPEG_B64,
                                "mime": "image/jpeg"}, timeout=30)
        assert r.status_code == 400

    def test_upload_rejects_bad_base64(self, client_headers):
        r = requests.post(f"{BASE_URL}/api/progress/photo/base64", headers=client_headers,
                          json={"angle": "front", "photo_b64": "$$$not-b64$$$",
                                "mime": "image/jpeg"}, timeout=30)
        assert r.status_code == 400

    def test_upload_rejects_over_6mb(self, client_headers):
        # Create ~6.5MB of binary and base64 encode.
        big = base64.b64encode(b"A" * (6 * 1024 * 1024 + 512 * 1024)).decode()
        r = requests.post(f"{BASE_URL}/api/progress/photo/base64", headers=client_headers,
                          json={"angle": "front", "photo_b64": big,
                                "mime": "image/jpeg"}, timeout=60)
        assert r.status_code == 413, f"expected 413 for >6MB, got {r.status_code} {r.text[:200]}"

    def test_list_photos_returns_recent(self, client_headers, uploaded_photo):
        r = requests.get(f"{BASE_URL}/api/progress/photos",
                         params={"months": 6}, headers=client_headers, timeout=30)
        assert r.status_code == 200
        photos = r.json().get("photos", [])
        assert any(p["id"] == uploaded_photo["id"] for p in photos)
        # Each has a fresh signed URL
        for p in photos:
            assert "url" in p and "expires_at_epoch" in p
            assert p["url"].startswith("/api/progress/photo/")

    def test_signed_url_serves_image(self, uploaded_photo):
        # Public preview base + relative URL
        url = f"{BASE_URL}{uploaded_photo['url']}"
        r = requests.get(url, timeout=30)
        assert r.status_code == 200, f"signed URL fetch failed: {r.status_code} {r.text[:200]}"
        # Should return image bytes
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 0

    def test_signed_url_rejects_bad_token(self, uploaded_photo, client_id):
        pid = uploaded_photo["id"]
        exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        bad_url = f"{BASE_URL}/api/progress/photo/{pid}?u={client_id}&e={exp}&t=deadbeefdeadbeefdeadbeef"
        r = requests.get(bad_url, timeout=30)
        assert r.status_code == 403, f"expected 403 for bad token, got {r.status_code}"

    def test_signed_url_rejects_expired_token(self, uploaded_photo, client_id):
        pid = uploaded_photo["id"]
        # Expired 1 hour ago; token would need to be signed correctly but expired
        # The verify checks expiry BEFORE HMAC compare, so any token+past-exp is 403.
        past_exp = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        expired_url = (
            f"{BASE_URL}/api/progress/photo/{pid}?u={client_id}&e={past_exp}"
            f"&t=aaaaaaaaaaaaaaaaaaaaaaaa"
        )
        r = requests.get(expired_url, timeout=30)
        assert r.status_code == 403, f"expected 403 for expired token, got {r.status_code}"

    def test_delete_photo(self, client_headers):
        # Create a fresh photo just to delete
        r = requests.post(f"{BASE_URL}/api/progress/photo/base64", headers=client_headers,
                          json={"angle": "back", "photo_b64": TINY_JPEG_B64,
                                "mime": "image/jpeg"}, timeout=30)
        assert r.status_code == 200
        pid = r.json()["photo"]["id"]
        # Delete
        rd = requests.delete(f"{BASE_URL}/api/progress/photo/{pid}", headers=client_headers, timeout=30)
        assert rd.status_code == 200, rd.text
        assert rd.json().get("ok") is True
        assert rd.json().get("deleted") == pid
        # Verify gone from listing
        rl = requests.get(f"{BASE_URL}/api/progress/photos", headers=client_headers, timeout=30)
        ids = {p["id"] for p in rl.json().get("photos", [])}
        assert pid not in ids, "deleted photo still in listing"

    def test_delete_nonexistent_returns_404(self, client_headers):
        r = requests.delete(f"{BASE_URL}/api/progress/photo/nonexistent-photo-xyz",
                            headers=client_headers, timeout=30)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Goal-adaptive dashboard
# ---------------------------------------------------------------------------

REQUIRED_DASHBOARD_KEYS = {
    "goal_class", "adherence", "nutrition_last_14d", "habits_last_7d",
    "body", "running", "strength", "photos",
}


class TestProgressDashboard:
    def test_dashboard_returns_all_required_keys(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/progress/dashboard",
                         headers=client_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        missing = REQUIRED_DASHBOARD_KEYS - set(body.keys())
        assert not missing, f"missing dashboard keys: {missing}"

    def test_dashboard_body_shape(self, client_headers):
        body = requests.get(f"{BASE_URL}/api/progress/dashboard",
                            headers=client_headers, timeout=30).json()
        b = body["body"]
        for k in ("latest", "starting", "series_weight", "series_waist",
                  "weight_change_kg", "waist_change_cm"):
            assert k in b, f"body sub-key missing: {k}"
        # We just posted a weight metric — series_weight must be non-empty
        assert isinstance(b["series_weight"], list)
        assert len(b["series_weight"]) >= 1
        for pt in b["series_weight"]:
            assert "date" in pt and "value" in pt

    def test_dashboard_running_shape(self, client_headers):
        body = requests.get(f"{BASE_URL}/api/progress/dashboard",
                            headers=client_headers, timeout=30).json()
        r = body["running"]
        for k in ("count", "long_run_min", "series"):
            assert k in r, f"running sub-key missing: {k}"
        # We logged a long_run above with duration 45min
        assert r["long_run_min"] >= 45

    def test_dashboard_strength_shape(self, client_headers):
        body = requests.get(f"{BASE_URL}/api/progress/dashboard",
                            headers=client_headers, timeout=30).json()
        s = body["strength"]
        for k in ("key_lifts", "sessions"):
            assert k in s
        assert isinstance(s["key_lifts"], list)
        # We logged 2 strength entries above
        assert s["sessions"] >= 2

    def test_dashboard_goal_class_is_valid(self, client_headers):
        body = requests.get(f"{BASE_URL}/api/progress/dashboard",
                            headers=client_headers, timeout=30).json()
        assert body["goal_class"] in ("fat_loss", "running", "strength", "health"), \
            f"unknown goal_class {body['goal_class']}"

    def test_dashboard_photos_have_signed_urls(self, client_headers):
        body = requests.get(f"{BASE_URL}/api/progress/dashboard",
                            headers=client_headers, timeout=30).json()
        for p in body["photos"]:
            assert "url" in p and p["url"].startswith("/api/progress/photo/")
            assert "expires_at_epoch" in p

    def test_dashboard_adherence_shape(self, client_headers):
        body = requests.get(f"{BASE_URL}/api/progress/dashboard",
                            headers=client_headers, timeout=30).json()
        a = body["adherence"]
        for k in ("weeks", "workouts_planned", "workouts_completed",
                  "workouts_missed", "adherence_pct"):
            assert k in a


# ---------------------------------------------------------------------------
# Goal detection (unit-level) — direct module call, no HTTP.
# ---------------------------------------------------------------------------

class TestGoalDetection:
    """Exercises _detect_goal_class using imported module directly."""

    def _detect(self, profile):
        # Local import to avoid affecting server startup in HTTP tests
        import sys
        sys.path.insert(0, "/app/backend")
        from feature_progress_dynamic import _detect_goal_class  # noqa
        return _detect_goal_class(profile)

    def test_fat_loss(self):
        assert self._detect({"main_goal_key": "fat_loss"}) == "fat_loss"
        assert self._detect({"main_goal_key": "weight_loss"}) == "fat_loss"
        assert self._detect({"main_goal_key": "recomposition"}) == "fat_loss"

    def test_running(self):
        assert self._detect({"main_goal_key": "running"}) == "running"
        assert self._detect({"main_goal_key": "marathon"}) == "running"
        assert self._detect({"primary_goal": "half_marathon"}) == "running"

    def test_strength(self):
        assert self._detect({"main_goal_key": "strength"}) == "strength"
        assert self._detect({"main_goal_key": "hypertrophy"}) == "strength"
        assert self._detect({"primary_goal": "power"}) == "strength"

    def test_health_default(self):
        assert self._detect({}) == "health"
        assert self._detect({"main_goal_key": "general_fitness"}) == "health"
        assert self._detect({"main_goal_key": "recovery"}) == "health"
        # Unknown goal → health fallback
        assert self._detect({"main_goal_key": "wibble"}) == "health"

    def test_secondary_goals_considered(self):
        assert self._detect({"secondary_goals": ["marathon"]}) == "running"


# ---------------------------------------------------------------------------
# Admin coach progress dashboard
# ---------------------------------------------------------------------------

class TestAdminProgressDashboard:
    def test_requires_coach(self, client_headers, client_id):
        r = requests.get(f"{BASE_URL}/api/admin/client/{client_id}/progress-dashboard",
                         headers=client_headers, timeout=30)
        assert r.status_code == 403, f"client should be 403, got {r.status_code}"

    def test_coach_can_view_client(self, coach_headers, client_id):
        r = requests.get(f"{BASE_URL}/api/admin/client/{client_id}/progress-dashboard",
                         headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # Same required keys as client-facing dashboard
        missing = REQUIRED_DASHBOARD_KEYS - set(body.keys())
        assert not missing, f"admin dashboard missing keys: {missing}"
        # Plus a client block
        assert "client" in body
        assert body["client"]["id"] == client_id
        assert body["client"].get("email") == CLIENT_EMAIL

    def test_coach_404_for_bad_uid(self, coach_headers):
        r = requests.get(f"{BASE_URL}/api/admin/client/nonexistent-user-xyz/progress-dashboard",
                         headers=coach_headers, timeout=30)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Phase 1 & 2 regressions (spot checks)
# ---------------------------------------------------------------------------

class TestPhase12Regression:
    def test_app_config(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/app-config", headers=client_headers, timeout=30)
        assert r.status_code == 200
        assert "flags" in r.json()

    def test_admin_media_reconcile(self, coach_headers):
        r = requests.post(f"{BASE_URL}/api/admin/media/reconcile",
                          headers=coach_headers, timeout=120)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        assert "clients_scanned" in r.json()

    def test_calendar_range(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/calendar/range",
                         headers=client_headers, timeout=30)
        assert r.status_code == 200
        assert "days" in r.json()

    def test_recovery_missed(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/recovery/missed",
                         params={"window": 14}, headers=client_headers, timeout=30)
        assert r.status_code == 200
        assert "missed" in r.json() and "count" in r.json()

    def test_profile_timezone_status(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/profile/timezone-status",
                         headers=client_headers, timeout=30)
        assert r.status_code == 200
        for k in ("home_base", "home_timezone", "current_timezone",
                  "current_timezone_source"):
            assert k in r.json()

    def test_nutrition_today(self, client_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/today",
                         headers=client_headers, timeout=30)
        assert r.status_code == 200
        for k in ("date_local", "target", "totals", "hydration_ml", "remaining"):
            assert k in r.json()
