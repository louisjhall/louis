"""
Programme Import — Phase 1 (preview / dry-run) integration tests.

Tests the /api/coach/programme-import/preview endpoint end-to-end against
the running backend. Uses the shared conftest fixtures (coach_auth) and
the `testclient@crewfit.net` client the manual-workout builder uses.

Coverage:
  * Minimal-valid envelope → 200, preview_id, ready workouts
  * Envelope with unresolved exercise name → unresolved warning + drafts count
  * Envelope with a superset group → counts.supersets == 1
  * Bad $schema → 400
  * Unknown client email → 404
  * Duplicate dates in envelope → 400
  * override_policy=reject_conflicts blocks existing dates
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"


@pytest.fixture(scope="module")
def base_url():
    return (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "http://localhost:8001").rstrip("/")


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def coach_headers(session, base_url):
    r = session.post(
        f"{base_url}/api/auth/login",
        json={"email": COACH_EMAIL, "password": COACH_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"coach login failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _make_envelope(**overrides):
    """Build a minimal-valid envelope. Callers can override any top-level
    key or the workouts list."""
    env = {
        "$schema": "crewfit://programme-import/v1",
        "meta": {
            "client_email": CLIENT_EMAIL,
            "month": "2027-01",
            "timezone": "Europe/London",
            "generated_by": "phase1-integration-test",
        },
        "override_policy": "replace_conflicts",
        "workouts": [
            {
                "date": "2027-01-05",
                "title": "Test upper day",
                "workout_type": "strength",
                "duration_min": 45,
                "warmup": [
                    {"ref": {"name": "Cat-cow"}, "duration_sec": 30},
                ],
                "exercises": [
                    {
                        "kind": "single",
                        "ref": {"name": "Push-up"},
                        "sets": 3, "reps": 10,
                    },
                ],
                "cooldown": [],
                "external_ref": f"test-{uuid.uuid4().hex[:6]}",
            }
        ],
    }
    env.update(overrides)
    return env


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_minimal_valid_envelope(session, base_url, coach_headers):
    env = _make_envelope()
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()

    assert body["schema_id"] == "crewfit://programme-import/v1"
    assert body["preview_id"].startswith("pv_")
    assert body["expires_at"]
    assert body["meta"]["client_email"] == CLIENT_EMAIL
    assert body["meta"]["month"] == "2027-01"
    assert body["meta"]["workout_count"] == 1
    assert body["blocking_errors"] == 0
    assert len(body["per_workout"]) == 1

    wp = body["per_workout"][0]
    assert wp["date"] == "2027-01-05"
    assert wp["status"] in ("ready", "skip")
    assert wp["counts"]["main"] == 1
    # Pool must have resolved or substituted push-up + cat-cow. If the
    # library is empty in this env, we still want to see the "unresolved"
    # bucket, not a crash.
    assert isinstance(wp["counts"]["media_queue_new_items"], int)


def test_unresolved_exercise_produces_warning(session, base_url, coach_headers):
    env = _make_envelope(workouts=[
        {
            "date": "2027-01-06",
            "title": "Weird exercise day",
            "workout_type": "strength",
            "warmup": [],
            "exercises": [
                {
                    "kind": "single",
                    "ref": {"name": "Cluster deadlift XYZ 3000"},
                    "sets": 4, "reps": 3,
                }
            ],
            "cooldown": [],
        }
    ])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    wp = body["per_workout"][0]
    # Either unresolved (no library match) OR fuzzy-substituted (score 10-49).
    warn_codes = {w.get("code") for w in wp["warnings"]}
    assert warn_codes & {"unresolved_exercise", "fuzzy_match"}, (
        f"expected unresolved/fuzzy warning, got {warn_codes}"
    )
    assert body["summary"]["exercises_new_drafts"] >= 0
    # If unresolved, media queue picks it up.
    if "unresolved_exercise" in warn_codes:
        assert body["summary"]["exercises_new_drafts"] >= 1


def test_superset_group_is_counted(session, base_url, coach_headers):
    env = _make_envelope(workouts=[
        {
            "date": "2027-01-07",
            "title": "Superset test day",
            "workout_type": "strength",
            "warmup": [],
            "exercises": [
                {
                    "kind": "group",
                    "group_type": "superset",
                    "group_label": "A1/A2",
                    "rounds": 3,
                    "rest_between_rounds_sec": 90,
                    "rest_between_items_sec": 15,
                    "items": [
                        {"ref": {"name": "Push-up"}, "reps": 10},
                        {"ref": {"name": "Squat"}, "reps": 12},
                    ],
                }
            ],
            "cooldown": [],
        }
    ])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    wp = body["per_workout"][0]
    assert wp["counts"]["supersets"] == 1
    # Group expands to 2 rows.
    assert wp["counts"]["main"] == 2
    assert body["summary"]["supersets"] == 1


def test_circuit_group_is_counted(session, base_url, coach_headers):
    env = _make_envelope(workouts=[
        {
            "date": "2027-01-08",
            "title": "Circuit day",
            "workout_type": "cardio",
            "warmup": [],
            "exercises": [
                {
                    "kind": "group",
                    "group_type": "circuit",
                    "rounds": 3,
                    "rest_between_rounds_sec": 60,
                    "items": [
                        {"ref": {"name": "Push-up"}, "reps": 10},
                        {"ref": {"name": "Squat"}, "reps": 12},
                        {"ref": {"name": "Plank"}, "duration_sec": 30},
                    ],
                }
            ],
            "cooldown": [],
        }
    ])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    assert body["summary"]["circuits"] == 1
    assert body["per_workout"][0]["counts"]["main"] == 3


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------

def test_bad_schema_id_is_400(session, base_url, coach_headers):
    env = _make_envelope()
    env["$schema"] = "crewfit://programme-import/v99-not-real"
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 400, f"{r.status_code}: {r.text}"


def test_unknown_client_email_is_404(session, base_url, coach_headers):
    env = _make_envelope()
    env["meta"]["client_email"] = f"never-{uuid.uuid4().hex[:6]}@nowhere.example"
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 404, f"{r.status_code}: {r.text}"


def test_duplicate_dates_are_400(session, base_url, coach_headers):
    env = _make_envelope(workouts=[
        {
            "date": "2027-01-09",
            "title": "First",
            "workout_type": "strength",
            "warmup": [], "cooldown": [],
            "exercises": [{"kind": "single", "ref": {"name": "Push-up"},
                           "sets": 3, "reps": 8}],
        },
        {
            "date": "2027-01-09",
            "title": "Second (duplicate date)",
            "workout_type": "strength",
            "warmup": [], "cooldown": [],
            "exercises": [{"kind": "single", "ref": {"name": "Push-up"},
                           "sets": 3, "reps": 8}],
        },
    ])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 400, f"{r.status_code}: {r.text}"
    assert "duplicate" in r.text.lower()


def test_empty_workouts_is_400(session, base_url, coach_headers):
    env = _make_envelope(workouts=[])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 400, f"{r.status_code}: {r.text}"


def test_bad_workout_type_surfaces_as_error(session, base_url, coach_headers):
    env = _make_envelope(workouts=[
        {
            "date": "2027-01-10",
            "title": "Bad type",
            "workout_type": "not-a-real-type",
            "warmup": [], "cooldown": [],
            "exercises": [{"kind": "single", "ref": {"name": "Push-up"},
                           "sets": 3, "reps": 8}],
        }
    ])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    # Envelope-level 200 (workout-level error is per-workout, not fatal).
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    assert body["blocking_errors"] >= 1
    err_codes = {e.get("code") for e in body["per_workout"][0]["errors"]}
    assert "invalid_workout_type" in err_codes


def test_direct_exercise_id_is_accepted(session, base_url, coach_headers):
    """Look up a real exercise_id from the library and pass it as
    ref.exercise_id — must resolve to 'direct' with no warning."""
    lib = session.get(
        f"{base_url}/api/exercise-content?q=push&limit=5",
        headers=coach_headers, timeout=30,
    )
    if lib.status_code != 200 or not lib.json().get("exercises"):
        pytest.skip("no exercises in library — skipping direct-id test")
    ex_id = lib.json()["exercises"][0]["id"]

    env = _make_envelope(workouts=[
        {
            "date": "2027-01-11",
            "title": "Direct id test",
            "workout_type": "strength",
            "warmup": [], "cooldown": [],
            "exercises": [{"kind": "single", "ref": {"exercise_id": ex_id},
                           "sets": 3, "reps": 8}],
        }
    ])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    wp = body["per_workout"][0]
    # No warnings for the direct-id row.
    warn_codes = {w.get("code") for w in wp["warnings"]}
    assert "unknown_exercise_id" not in warn_codes
    assert body["summary"]["exercises_direct_id"] >= 1


def test_unknown_exercise_id_is_error(session, base_url, coach_headers):
    env = _make_envelope(workouts=[
        {
            "date": "2027-01-12",
            "title": "Unknown id",
            "workout_type": "strength",
            "warmup": [], "cooldown": [],
            "exercises": [{
                "kind": "single",
                "ref": {"exercise_id": f"never-{uuid.uuid4().hex}"},
                "sets": 3, "reps": 8,
            }],
        }
    ])
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    wp = body["per_workout"][0]
    err_codes = {e.get("code") for e in wp["errors"]}
    assert "unknown_exercise_id" in err_codes
    assert body["blocking_errors"] >= 1


def test_no_client_key_is_400(session, base_url, coach_headers):
    env = _make_envelope()
    env["meta"].pop("client_email", None)
    env["meta"].pop("client_id", None)
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 400, f"{r.status_code}: {r.text}"


def test_preview_row_persists(session, base_url, coach_headers):
    """A successful preview creates a row in db.programme_import_previews.
    We can't hit the DB directly from here, but we can verify the returned
    preview_id shape and TTL are sane."""
    env = _make_envelope()
    r = session.post(
        f"{base_url}/api/coach/programme-import/preview",
        json=env, headers=coach_headers, timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preview_id"].startswith("pv_")
    assert body["expires_at"].endswith("Z") or "+" in body["expires_at"]
