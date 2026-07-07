"""Tests for §26 Phase A — Embedded Exercise Video System.

Endpoints under test:
- GET  /api/exercises/video?name=...
- POST /api/exercises/videos-batch  { exercises: [names] }

Regression:
- /api/auth/login, /api/coach/dashboard, /api/coach/calendar, /api/coach/analytics,
  /api/workouts/{id}, /api/roster/current
"""
import os
import time
import requests
import pytest

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")

EMBED_FRIENDLY = {
    "athlean-x", "athlean x",
    "jeff nippard",
    "jeremy ethier",
    "renaissance periodization",
    "built with science",
}


# ---------------------------------------------------------------------------
# GET /api/exercises/video
# ---------------------------------------------------------------------------
class TestGetExerciseVideo:
    def test_unauthenticated_returns_401(self, api, base_url):
        r = api.get(f"{base_url}/api/exercises/video?name=Push-Up", timeout=15)
        assert r.status_code in (401, 403), f"unexpected {r.status_code}: {r.text[:200]}"

    def test_common_exercises_return_valid_video(self, api, base_url, client_auth):
        """Try 6 common exercises. All should return a video from an embed-friendly channel."""
        names = ["Push-Up", "Deadlift", "Bench Press", "Bulgarian Split Squat", "Plank", "Goblet Squat"]
        results = {}
        for nm in names:
            r = api.get(
                f"{base_url}/api/exercises/video",
                params={"name": nm},
                headers=client_auth["headers"],
                timeout=30,
            )
            assert r.status_code == 200, f"{nm}: {r.status_code} {r.text[:200]}"
            data = r.json()
            assert data["exercise"] == nm
            v = data.get("video")
            # We tolerate a null result for obscure names but common lifts must resolve
            assert v is not None, f"expected video for '{nm}', got null"
            assert isinstance(v.get("video_id"), str) and len(v["video_id"]) == 11, f"{nm} bad video_id: {v.get('video_id')}"
            assert v.get("source") == "youtube_search"
            assert v.get("thumbnail_url", "").startswith("https://img.youtube.com/vi/"), f"{nm} thumb: {v.get('thumbnail_url')}"
            assert v.get("approval_status") in ("auto", "approved")
            assert v.get("channel_hint")
            results[nm] = v
        # print sample
        print("\nSample:", {k: (v["channel"], v["video_id"]) for k, v in results.items()})

    def test_channel_hint_is_embed_friendly(self, api, base_url, client_auth):
        r = api.get(
            f"{base_url}/api/exercises/video",
            params={"name": "Bench Press"},
            headers=client_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200
        v = r.json()["video"]
        hint = (v.get("channel_hint") or "").lower()
        assert any(f in hint for f in EMBED_FRIENDLY), f"channel_hint '{hint}' not embed-friendly"

    def test_squat_channel_not_squat_university(self, api, base_url, client_auth):
        """The chosen video for a squat variant must NOT be Squat University (they block embeds)."""
        r = api.get(
            f"{base_url}/api/exercises/video",
            params={"name": "Goblet Squat"},
            headers=client_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200
        v = r.json()["video"]
        channel = (v.get("channel") or "").lower()
        assert "squat university" not in channel, f"picked blocked channel: {channel}"

    def test_second_call_is_cached(self, api, base_url, client_auth):
        """After first call caches to db, second call must return same video_id (fast)."""
        r1 = api.get(
            f"{base_url}/api/exercises/video",
            params={"name": "Deadlift"},
            headers=client_auth["headers"],
            timeout=30,
        )
        assert r1.status_code == 200
        v1 = r1.json()["video"]

        t0 = time.time()
        r2 = api.get(
            f"{base_url}/api/exercises/video",
            params={"name": "Deadlift"},
            headers=client_auth["headers"],
            timeout=15,
        )
        elapsed = time.time() - t0
        assert r2.status_code == 200
        v2 = r2.json()["video"]
        assert v1["video_id"] == v2["video_id"], "cache mismatch"
        # cache hit should be well under a second (no HTTP fetch to youtube.com)
        assert elapsed < 3.0, f"cache hit unexpectedly slow: {elapsed:.2f}s"

    def test_coach_can_fetch_video(self, api, base_url, coach_auth):
        r = api.get(
            f"{base_url}/api/exercises/video",
            params={"name": "Row"},
            headers=coach_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200
        assert r.json()["exercise"] == "Row"


# ---------------------------------------------------------------------------
# POST /api/exercises/videos-batch
# ---------------------------------------------------------------------------
class TestBatchExerciseVideos:
    def test_unauthenticated_returns_401(self, api, base_url):
        r = api.post(
            f"{base_url}/api/exercises/videos-batch",
            json={"exercises": ["Push-Up"]},
            timeout=15,
        )
        assert r.status_code in (401, 403)

    def test_batch_returns_all_names(self, api, base_url, client_auth):
        names = ["Push-Up", "Deadlift", "Row", "Plank"]
        r = api.post(
            f"{base_url}/api/exercises/videos-batch",
            json={"exercises": names},
            headers=client_auth["headers"],
            timeout=60,
        )
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        assert "results" in data and "fetched" in data
        results = data["results"]
        for nm in names:
            assert nm in results, f"missing '{nm}' in batch results (got keys {list(results.keys())})"
        # At least 3/4 common lifts must resolve to a real video
        with_video = sum(1 for nm in names if results.get(nm) and results[nm].get("video", {}).get("video_id"))
        assert with_video >= 3, f"only {with_video}/4 resolved: {results}"

    def test_batch_populates_cache_then_single_get_is_fast(self, api, base_url, client_auth):
        # warm via batch
        names = ["Push-Up", "Deadlift"]
        r = api.post(
            f"{base_url}/api/exercises/videos-batch",
            json={"exercises": names},
            headers=client_auth["headers"],
            timeout=60,
        )
        assert r.status_code == 200
        # single GET must be a cache hit
        t0 = time.time()
        r2 = api.get(
            f"{base_url}/api/exercises/video",
            params={"name": "Push-Up"},
            headers=client_auth["headers"],
            timeout=15,
        )
        elapsed = time.time() - t0
        assert r2.status_code == 200
        assert r2.json()["video"] is not None
        assert elapsed < 3.0, f"cache hit slow: {elapsed:.2f}s"

    def test_empty_and_dedupe(self, api, base_url, client_auth):
        r = api.post(
            f"{base_url}/api/exercises/videos-batch",
            json={"exercises": ["Push-Up", "Push-Up", "  ", ""]},
            headers=client_auth["headers"],
            timeout=60,
        )
        assert r.status_code == 200
        results = r.json()["results"]
        # Should dedupe blanks and repeats; at least Push-Up returned
        assert "Push-Up" in results


# ---------------------------------------------------------------------------
# Regression — pre-existing endpoints must still work
# ---------------------------------------------------------------------------
class TestRegression:
    def test_login(self, api, base_url):
        r = api.post(
            f"{base_url}/api/auth/login",
            json={"email": "coach@crewfit.com", "password": "Coach123!"},
            timeout=15,
        )
        assert r.status_code == 200
        assert "token" in r.json()

    def test_coach_dashboard(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/dashboard", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), (dict, list))

    def test_coach_calendar(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/calendar?days=14", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "dates" in d and "clients" in d
        assert len(d["dates"]) == 14

    def test_coach_analytics(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/analytics?days=30", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "clients" in d
        assert "load_distribution" in d

    def test_roster_current(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200

    def test_workout_by_id(self, api, base_url, client_auth):
        # Fetch week to get any workout id
        r = api.get(f"{base_url}/api/workouts/week", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        # normalise into list of workouts
        arr = data if isinstance(data, list) else data.get("workouts", []) or []
        # sometimes weekly is grouped by day
        if not arr and isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    arr = v
                    break
        if not arr:
            pytest.skip(f"no workouts in week payload: {str(data)[:150]}")
        wid = arr[0].get("id") or arr[0].get("_id")
        if not wid:
            pytest.skip(f"no id in workout: {arr[0]}")
        r2 = api.get(f"{base_url}/api/workouts/{wid}", headers=client_auth["headers"], timeout=15)
        assert r2.status_code == 200
