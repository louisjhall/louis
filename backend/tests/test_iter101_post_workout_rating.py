"""Iter 101 · Quick post-workout rating — backend tests.

Covers /api/workouts/{wid}/complete accepting optional rating + note + pain
fields, and the selective emission of coach_tasks (task_type=workout_review).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL") or os.environ.get("EXPO_BACKEND_URL")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL / EXPO_BACKEND_URL must be set"
BASE_URL = BASE_URL.rstrip("/")

REVIEWER_EMAIL = "reviewer@crewfit.net"
REVIEWER_PASSWORD = "CrewFitReview2026!"
LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PASSWORD = "Louis123!"


# ------------------------------ Fixtures ------------------------------------
@pytest.fixture(scope="module")
def reviewer_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": REVIEWER_EMAIL, "password": REVIEWER_PASSWORD})
    assert r.status_code == 200, f"reviewer login failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("access_token") or data["token"]


@pytest.fixture(scope="module")
def louis_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": LOUIS_EMAIL, "password": LOUIS_PASSWORD})
    assert r.status_code == 200, f"louis login failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("access_token") or data["token"]


@pytest.fixture(scope="module")
def reviewer_headers(reviewer_token):
    return {"Authorization": f"Bearer {reviewer_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def louis_headers(louis_token):
    return {"Authorization": f"Bearer {louis_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def upcoming_workouts(reviewer_headers):
    """Return list of reviewer workouts with completed=false, sorted by date."""
    r = requests.get(f"{BASE_URL}/api/workouts/week", headers=reviewer_headers)
    assert r.status_code == 200, f"workouts/week failed: {r.status_code} {r.text}"
    rows = r.json()
    incomplete = [w for w in rows if not w.get("completed")]
    assert len(incomplete) >= 5, f"expected 5+ incomplete workouts, got {len(incomplete)}: {[w.get('title') for w in rows]}"
    return incomplete


def _find_task_for_workout(louis_headers, wid: str) -> dict | None:
    r = requests.get(f"{BASE_URL}/api/coach/tasks?filter_type=workout_review", headers=louis_headers)
    assert r.status_code == 200, f"coach/tasks failed: {r.status_code} {r.text}"
    for t in r.json().get("tasks", []):
        if t.get("workout_id") == wid:
            return t
    return None


# ------------------------------ Test 1 --------------------------------------
def test_smooth_flight_creates_no_task(reviewer_headers, louis_headers, upcoming_workouts):
    """rating=smooth_flight → 200, completed=true, needs_coach_review=false, NO coach task."""
    wid = upcoming_workouts[0]["id"]
    r = requests.post(f"{BASE_URL}/api/workouts/{wid}/complete",
                      headers=reviewer_headers, json={"rating": "smooth_flight"})
    assert r.status_code == 200, f"complete failed: {r.status_code} {r.text}"
    doc = r.json()
    assert doc.get("completed") is True, f"completed not true: {doc.get('completed')}"
    assert doc.get("rating") == "smooth_flight", f"rating mismatch: {doc.get('rating')}"
    assert doc.get("needs_coach_review") is False, f"needs_coach_review should be false: {doc.get('needs_coach_review')}"

    task = _find_task_for_workout(louis_headers, wid)
    assert task is None, f"expected NO coach task for smooth_flight, got: {task}"


# ------------------------------ Test 2 --------------------------------------
def test_heavy_turbulence_no_pain_creates_task(reviewer_headers, louis_headers, upcoming_workouts):
    """rating=heavy_turbulence, pain_reported=false → task with priority=high, summary mentions 'Heavy turbulence'."""
    wid = upcoming_workouts[1]["id"]
    r = requests.post(f"{BASE_URL}/api/workouts/{wid}/complete",
                      headers=reviewer_headers,
                      json={"rating": "heavy_turbulence", "pain_reported": False})
    assert r.status_code == 200, f"complete failed: {r.status_code} {r.text}"
    doc = r.json()
    assert doc.get("needs_coach_review") is True, f"needs_coach_review should be true: {doc.get('needs_coach_review')}"
    assert doc.get("rating") == "heavy_turbulence"

    task = _find_task_for_workout(louis_headers, wid)
    assert task is not None, "expected a workout_review coach task for heavy_turbulence"
    assert task.get("priority") == "high", f"priority should be high, got {task.get('priority')}"
    assert task.get("workout_id") == wid
    summary = task.get("summary") or ""
    assert "Heavy turbulence" in summary, f"summary should mention 'Heavy turbulence': {summary!r}"


# ------------------------------ Test 3 --------------------------------------
def test_diverted_with_pain_note(reviewer_headers, louis_headers, upcoming_workouts):
    """rating=diverted, pain_reported=true, pain_note='Left knee' → summary contains 'Reported pain' AND 'Left knee'."""
    wid = upcoming_workouts[2]["id"]
    r = requests.post(f"{BASE_URL}/api/workouts/{wid}/complete",
                      headers=reviewer_headers,
                      json={"rating": "diverted", "pain_reported": True, "pain_note": "Left knee"})
    assert r.status_code == 200, f"complete failed: {r.status_code} {r.text}"
    doc = r.json()
    assert doc.get("needs_coach_review") is True
    assert doc.get("rating") == "diverted"

    task = _find_task_for_workout(louis_headers, wid)
    assert task is not None, "expected a workout_review coach task for diverted"
    summary = task.get("summary") or ""
    assert "Reported pain" in summary, f"summary should mention 'Reported pain': {summary!r}"
    assert "Left knee" in summary, f"summary should mention 'Left knee': {summary!r}"
    assert task.get("priority") == "high"


# ------------------------------ Test 4 --------------------------------------
def test_smooth_flight_with_optional_note_creates_task(reviewer_headers, louis_headers, upcoming_workouts):
    """rating=smooth_flight + optional_note → task with priority=normal, summary contains the note."""
    wid = upcoming_workouts[3]["id"]
    note = "Slept badly last night"
    r = requests.post(f"{BASE_URL}/api/workouts/{wid}/complete",
                      headers=reviewer_headers,
                      json={"rating": "smooth_flight", "optional_note": note})
    assert r.status_code == 200, f"complete failed: {r.status_code} {r.text}"
    doc = r.json()
    assert doc.get("needs_coach_review") is True, "note should force needs_coach_review=true"
    assert doc.get("rating") == "smooth_flight"

    task = _find_task_for_workout(louis_headers, wid)
    assert task is not None, "expected a workout_review coach task when optional_note provided"
    assert task.get("priority") == "normal", f"priority should be normal, got {task.get('priority')}"
    summary = task.get("summary") or ""
    assert note in summary, f"summary should contain the note ({note!r}): {summary!r}"


# ------------------------------ Test 5 --------------------------------------
def test_pain_fields_ignored_for_smooth_flight(reviewer_headers, louis_headers, upcoming_workouts):
    """Non-attention rating strips pain_reported + pain_note; stored value must be null."""
    wid = upcoming_workouts[4]["id"]
    r = requests.post(f"{BASE_URL}/api/workouts/{wid}/complete",
                      headers=reviewer_headers,
                      json={"rating": "smooth_flight", "pain_reported": True, "pain_note": "spurious"})
    assert r.status_code == 200, f"complete failed: {r.status_code} {r.text}"
    doc = r.json()
    assert doc.get("rating") == "smooth_flight"
    # Pain fields should have been stripped server-side.
    completion = doc.get("completion") or {}
    assert completion.get("pain_reported") is None, f"pain_reported should be null: {completion.get('pain_reported')!r}"
    assert completion.get("pain_note") is None, f"pain_note should be null: {completion.get('pain_note')!r}"
    # And with pain fields null + no note, needs_coach_review must be false.
    assert doc.get("needs_coach_review") is False, f"needs_coach_review should be false: {doc.get('needs_coach_review')}"

    task = _find_task_for_workout(louis_headers, wid)
    assert task is None, f"expected NO coach task when pain fields stripped, got: {task}"
