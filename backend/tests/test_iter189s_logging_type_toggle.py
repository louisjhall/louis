"""Iter189s — Backend contract tests for reps/time toggle refactor.

Verifies:
  1. POST /api/exercise-content accepts logging_type and persists it.
  2. PATCH /api/exercise-content/{id} can update logging_type.
  3. PATCH /api/coach/library/exercise/{id}/logging-type sets/clears override.
"""
import os
import pytest
import requests
import uuid

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"


@pytest.fixture(scope="module")
def coach_headers():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": COACH_EMAIL, "password": COACH_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"coach login failed: {r.status_code} {r.text}"
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def created_exercise_id(coach_headers):
    """Create a test exercise once; delete after tests complete."""
    name = f"TEST_iter189s_{uuid.uuid4().hex[:8]}"
    r = requests.post(
        f"{BASE_URL}/api/exercise-content",
        headers=coach_headers,
        json={
            "exercise_name": name,
            "category": "Strength",
            "logging_type": "timer",
            "force": True,  # bypass any similarity guard for this unique name
        },
        timeout=30,
    )
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    ex = r.json().get("exercise") or {}
    ex_id = ex.get("id")
    assert ex_id, f"no id in response: {r.text}"
    yield ex_id
    # Teardown — archive it
    try:
        requests.delete(f"{BASE_URL}/api/exercise-content/{ex_id}", headers=coach_headers, timeout=10)
    except Exception:
        pass


# ----- POST /api/exercise-content -----
class TestCreatePersistsLoggingType:
    def test_create_with_timer_persists(self, coach_headers, created_exercise_id):
        # GET back and check field
        r = requests.get(
            f"{BASE_URL}/api/exercise-content/{created_exercise_id}",
            headers=coach_headers,
            timeout=15,
        )
        assert r.status_code == 200, r.text
        ex = r.json().get("exercise") or {}
        assert ex.get("logging_type") == "timer", (
            f"Expected logging_type='timer' after create, got {ex.get('logging_type')!r}"
        )


# ----- PATCH /api/exercise-content/{id} -----
class TestPatchLoggingType:
    def test_patch_to_reps(self, coach_headers, created_exercise_id):
        r = requests.patch(
            f"{BASE_URL}/api/exercise-content/{created_exercise_id}",
            headers=coach_headers,
            json={"logging_type": "reps"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        ex = r.json().get("exercise") or {}
        assert ex.get("logging_type") == "reps", (
            f"PATCH did not persist logging_type='reps': got {ex.get('logging_type')!r}"
        )
        # GET verify
        r2 = requests.get(
            f"{BASE_URL}/api/exercise-content/{created_exercise_id}",
            headers=coach_headers,
            timeout=15,
        )
        assert r2.status_code == 200
        assert r2.json().get("exercise", {}).get("logging_type") == "reps"

    def test_patch_back_to_timer(self, coach_headers, created_exercise_id):
        r = requests.patch(
            f"{BASE_URL}/api/exercise-content/{created_exercise_id}",
            headers=coach_headers,
            json={"logging_type": "timer"},
            timeout=15,
        )
        assert r.status_code == 200
        assert r.json().get("exercise", {}).get("logging_type") == "timer"


# ----- PATCH /api/coach/library/exercise/{id}/logging-type -----
class TestOverrideEndpoint:
    def test_set_override_timer(self, coach_headers, created_exercise_id):
        r = requests.patch(
            f"{BASE_URL}/api/coach/library/exercise/{created_exercise_id}/logging-type",
            headers=coach_headers,
            json={"logging_type": "timer"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Response shape may vary; do a soft check
        assert body is not None

        # verify persisted
        r2 = requests.get(
            f"{BASE_URL}/api/exercise-content/{created_exercise_id}",
            headers=coach_headers,
            timeout=15,
        )
        ex = r2.json().get("exercise") or {}
        assert ex.get("logging_type_override") == "timer", (
            f"override not persisted: {ex.get('logging_type_override')!r}"
        )

    def test_clear_override_null(self, coach_headers, created_exercise_id):
        r = requests.patch(
            f"{BASE_URL}/api/coach/library/exercise/{created_exercise_id}/logging-type",
            headers=coach_headers,
            json={"logging_type": None},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        # GET check
        r2 = requests.get(
            f"{BASE_URL}/api/exercise-content/{created_exercise_id}",
            headers=coach_headers,
            timeout=15,
        )
        ex = r2.json().get("exercise") or {}
        # Should be cleared (None or missing)
        assert not ex.get("logging_type_override"), (
            f"override should be cleared, got {ex.get('logging_type_override')!r}"
        )


# ----- Backfill verification: 204 rows should be logging_type='timer' -----
class TestBackfillVerification:
    def test_at_least_some_timer_exercises_exist(self, coach_headers):
        """Ensure the backfill ran — expect multiple exercises with logging_type='timer'."""
        # List some plank/run named exercises
        r = requests.get(
            f"{BASE_URL}/api/exercise-content?q=plank",
            headers=coach_headers,
            timeout=15,
        )
        assert r.status_code == 200
        rows = r.json().get("exercises") or []
        # At least one plank exercise should exist with logging_type='timer'
        timer_planks = [x for x in rows if str(x.get("logging_type") or "").lower() == "timer"]
        # If backfill ran, we expect at least one
        assert len(timer_planks) >= 1, (
            f"No plank exercise found with logging_type='timer'. "
            f"Backfill may not have run. Sample: "
            f"{[(x.get('exercise_name'), x.get('logging_type')) for x in rows[:5]]}"
        )
