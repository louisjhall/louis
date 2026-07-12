"""Tests for the new CrewFit Food Search backend endpoints.

Covers:
- /api/nutrition/food-search
- /api/nutrition/food-recent
- /api/nutrition/food-estimate
- Regressions: /api/nutrition/today, /api/nutrition/summary,
  older /api/nutrition/food/search, /api/coach/profile/main, /api/messages.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("token") or data.get("access_token") or (data.get("data") or {}).get("token")
    assert tok, f"No token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(client_token):
    return {"Authorization": f"Bearer {client_token}", "Content-Type": "application/json"}


# --------------------------------------------------------------------------
# Food search
# --------------------------------------------------------------------------
class TestFoodSearch:
    def test_local_fallback_chicken(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/food-search", params={"q": "chicken", "limit": 4}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("results"), list) and len(body["results"]) > 0
        # At least one local Chicken*
        chick_local = [x for x in body["results"] if x.get("source") == "local" and (x.get("name") or "").startswith("Chicken")]
        assert chick_local, f"No local 'Chicken*' item found in results: {[x.get('name') for x in body['results']]}"
        chips = body.get("chips")
        assert isinstance(chips, list) and len(chips) >= 5
        for c in chips:
            assert "label" in c and "query" in c

    def test_banana_top_result(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/food-search", params={"q": "banana", "limit": 3}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        results = body.get("results") or []
        assert results, "banana results empty"
        top = results[0]
        assert top.get("name") == "Banana", f"Top result was: {top.get('name')}"
        assert top.get("source") == "local"
        assert top.get("calories") == 89
        assert top.get("protein_g", 0) > 0

    def test_query_too_short(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/food-search", params={"q": "a", "limit": 4}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("results") == []
        assert isinstance(body.get("chips"), list) and len(body["chips"]) > 0

    def test_empty_query(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/food-search", params={"q": ""}, headers=auth_headers, timeout=15)
        assert 400 <= r.status_code < 500, f"Expected 4xx, got {r.status_code}: {r.text}"


# --------------------------------------------------------------------------
# Food recent + round-trip
# --------------------------------------------------------------------------
class TestFoodRecent:
    def test_recent_empty_state_returns_array(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/food-recent", params={"limit": 6}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("results"), list)

    def test_round_trip_log_then_recent(self, auth_headers):
        payload = {
            "food_name": "Chicken Breast, Cooked",
            "meal_type": "lunch",
            "calories": 330,
            "protein_g": 62,
            "carbs_g": 0,
            "fats_g": 7,
            "portion": "2 x 100g",
            "source": "food_search",
        }
        r = requests.post(f"{BASE_URL}/api/nutrition/logs", json=payload, headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"Failed to POST log: {r.status_code} {r.text}"

        r2 = requests.get(f"{BASE_URL}/api/nutrition/food-recent", params={"limit": 3}, headers=auth_headers, timeout=15)
        assert r2.status_code == 200, r2.text
        results = (r2.json() or {}).get("results") or []
        assert results, "food-recent returned empty after logging"
        first = results[0]
        assert first.get("food_name") == "Chicken Breast, Cooked", f"First item: {first}"
        assert first.get("calories") == 330
        assert first.get("protein_g") == 62
        assert first.get("carbs_g") == 0
        assert first.get("fats_g") == 7


# --------------------------------------------------------------------------
# Food estimate (atlas)
# --------------------------------------------------------------------------
class TestFoodEstimate:
    def test_estimate_happy_path(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/nutrition/food-estimate",
            json={"description": "Hotel buffet eggs and toast"},
            headers=auth_headers,
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("estimated") is True
        assert isinstance(body.get("calories"), (int, float)) and body["calories"] > 0
        assert isinstance(body.get("protein_g"), (int, float)) and body["protein_g"] > 0
        assert isinstance(body.get("carbs_g"), (int, float)) and body["carbs_g"] >= 0
        assert isinstance(body.get("fats_g"), (int, float)) and body["fats_g"] >= 0
        assert isinstance(body.get("serving_size"), str) and body["serving_size"]
        assert isinstance(body.get("explanation"), str) and body["explanation"]
        src = body.get("source") or ""
        assert src.startswith("atlas"), f"Unexpected source: {src}"

    def test_estimate_short_input(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/nutrition/food-estimate",
            json={"description": "a"},
            headers=auth_headers,
            timeout=15,
        )
        assert r.status_code in (400, 422), f"Expected 400/422, got {r.status_code}: {r.text}"


# --------------------------------------------------------------------------
# Regressions
# --------------------------------------------------------------------------
class TestRegression:
    def test_nutrition_today(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/today", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text

    def test_nutrition_summary(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/summary", params={"days": 7}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text

    def test_older_barcode_food_search(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/nutrition/food/search", params={"q": "chicken"}, headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"Barcode-style food/search regressed: {r.status_code} {r.text}"

    def test_coach_profile_main_is_louis(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/coach/profile/main", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        text = str(body).lower()
        assert "louis" in text, f"Louis identity missing from /coach/profile/main: {body}"

    def test_messages_partner_is_louis(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/messages", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        text = str(body).lower()
        assert "louis" in text, f"Louis missing from /messages: {body}"
