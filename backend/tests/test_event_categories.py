"""Tests for the category-aware Event Training system (feature_event_categories).

Covers:
 * GET  /api/events/catalog          (auth required)
 * POST /api/events                  (category inferred by name / event_type)
 * GET  /api/events/current          (enriched with category_label, days_label, etc.)
 * POST /api/events/backfill-categories
"""
from __future__ import annotations

import os
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def client_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"Client login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": COACH_EMAIL, "password": COACH_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"Coach login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _future_date(days: int = 60) -> str:
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def _create_event(token: str, event_type: str, event_name: str, category: str | None = None):
    payload = {
        "event_type": event_type,
        "event_name": event_name,
        "event_date": _future_date(60),
        "preferred_days": [],
    }
    if category is not None:
        payload["category"] = category
    r = requests.post(f"{BASE_URL}/api/events", json=payload, headers=_h(token), timeout=30)
    return r


def _get_current(token: str):
    r = requests.get(f"{BASE_URL}/api/events/current", headers=_h(token), timeout=30)
    return r


# ------------------------------------------------------------------
# Catalog
# ------------------------------------------------------------------

class TestCatalog:
    def test_catalog_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/events/catalog", timeout=30)
        assert r.status_code in (401, 403), f"Expected auth failure, got {r.status_code}"

    def test_catalog_shape(self, client_token):
        r = requests.get(f"{BASE_URL}/api/events/catalog", headers=_h(client_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "categories" in data and "events" in data
        assert isinstance(data["categories"], list)
        assert isinstance(data["events"], list)

        cat_keys = {c["key"] for c in data["categories"]}
        required = {"race", "medical", "aviation_work", "sport_hobby", "personal"}
        missing = required - cat_keys
        assert not missing, f"Missing categories: {missing}. Got: {cat_keys}"

        # Each category must have required fields
        for c in data["categories"]:
            for k in ("key", "label", "days_label", "icon", "colour"):
                assert k in c, f"Category {c.get('key')} missing key '{k}'"

        # Events entries must have slug, label, category
        for e in data["events"][:5]:
            for k in ("slug", "label", "category"):
                assert k in e, f"Catalog event missing key '{k}': {e}"

        # A quick spot check: race days_label
        race = next(c for c in data["categories"] if c["key"] == "race")
        assert race["days_label"] == "days to race"
        medical = next(c for c in data["categories"] if c["key"] == "medical")
        assert medical["days_label"] == "days to review"


# ------------------------------------------------------------------
# Category inference via POST /events + GET /events/current
# ------------------------------------------------------------------

class TestCategoryInference:
    def test_medical_blood_pressure(self, client_token):
        r = _create_event(client_token, event_type="airline_medical",
                          event_name="Airline Medical Renewal (Blood Pressure)")
        assert r.status_code == 200, r.text
        cur = _get_current(client_token).json()
        assert cur.get("category") == "medical", cur
        assert cur.get("days_label") == "days to review"
        assert cur.get("category_label") == "Medical / Aviation Health"
        assert cur.get("safety_note"), "safety_note field expected for medical category"
        assert isinstance(cur.get("days_value"), int)

    def test_race_10k_london(self, client_token):
        r = _create_event(client_token, event_type="10K", event_name="10K London")
        assert r.status_code == 200, r.text
        cur = _get_current(client_token).json()
        assert cur.get("category") == "race", cur
        assert cur.get("days_label") == "days to race"

    def test_sport_hobby_tennis(self, client_token):
        r = _create_event(client_token, event_type="tennis",
                          event_name="Tennis match with friends")
        assert r.status_code == 200, r.text
        cur = _get_current(client_token).json()
        assert cur.get("category") == "sport_hobby", cur
        assert cur.get("days_label") == "days to activity"

    def test_aviation_work_simulator(self, client_token):
        r = _create_event(client_token, event_type="simulator",
                          event_name="Simulator Assessment")
        assert r.status_code == 200, r.text
        cur = _get_current(client_token).json()
        assert cur.get("category") == "aviation_work", cur
        assert cur.get("days_label") == "days to assessment"

    def test_personal_holiday_confidence(self, client_token):
        r = _create_event(client_token, event_type="confidence_goal",
                          event_name="Holiday Confidence Goal")
        assert r.status_code == 200, r.text
        cur = _get_current(client_token).json()
        assert cur.get("category") == "personal", cur
        assert cur.get("days_label") == "days to event"


# ------------------------------------------------------------------
# Backfill
# ------------------------------------------------------------------

class TestBackfill:
    def test_backfill_shape(self, coach_token):
        r = requests.post(f"{BASE_URL}/api/events/backfill-categories",
                          headers=_h(coach_token), timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "updated" in data
        assert "total_missing" in data
        assert isinstance(data["updated"], int)
        assert isinstance(data["total_missing"], int)


# ------------------------------------------------------------------
# Ensure current event stays medical for FE test (leave client with medical)
# ------------------------------------------------------------------

class TestZFinalizeMedical:
    """Runs last (alphabetical). Leaves client with a medical event so FE tests
    can verify the home-card copy on the seeded client."""

    def test_leave_client_with_medical(self, client_token):
        r = _create_event(client_token,
                          event_type="airline_medical",
                          event_name="Airline Medical Renewal (Blood Pressure)")
        assert r.status_code == 200
        cur = _get_current(client_token).json()
        assert cur.get("category") == "medical"
        assert cur.get("days_label") == "days to review"
