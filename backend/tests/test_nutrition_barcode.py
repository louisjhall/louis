"""Backend tests for Nutrition Phase 2 — barcode lookup + log-from-barcode."""
import time
import pytest

COKE = "5449000000996"
UNKNOWN = "0000000000001"
UNKNOWN2 = "99999999999999"  # 14 digits — confirmed not in OFF at test time.
# Note: spec suggested "9999999999999" but OFF has a real "Salatgurke" test entry there.


# --- barcode/lookup ---------------------------------------------------------

class TestBarcodeLookupAuth:
    def test_lookup_requires_auth(self, api, base_url):
        r = api.get(f"{base_url}/api/nutrition/barcode/lookup?code={COKE}", timeout=15)
        assert r.status_code in (401, 403), r.text


class TestBarcodeLookupValidation:
    def test_invalid_barcode_non_numeric(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/barcode/lookup?code=abc",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 400
        assert "invalid" in r.text.lower()

    def test_invalid_barcode_too_short(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/barcode/lookup?code=1",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 400


class TestBarcodeLookupOFF:
    def test_lookup_coke_found(self, api, base_url, client_auth):
        # First we clear any pre-existing cache row so we can verify cached:false
        # But we don't have direct DB access here — we simply verify shape and
        # allow either cached=True/False for the first hit (previous runs may have cached).
        r = api.get(f"{base_url}/api/nutrition/barcode/lookup?code={COKE}",
                    headers=client_auth["headers"], timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["found"] is True, data
        assert data["barcode"] == COKE
        assert data["source"] == "open_food_facts"
        p = data["product"]
        assert isinstance(p, dict) and p.get("name")
        # Cola should mention "cola" in name (case-insensitive)
        assert "cola" in p["name"].lower(), p["name"]
        assert p.get("source") == "open_food_facts"
        # macros should be present
        for k in ("calories", "protein_g", "carbs_g", "fats_g"):
            assert k in p

    def test_lookup_cached_second_call(self, api, base_url, client_auth):
        # First call to warm cache
        api.get(f"{base_url}/api/nutrition/barcode/lookup?code={COKE}",
                headers=client_auth["headers"], timeout=20)
        # Second call should be cached
        r = api.get(f"{base_url}/api/nutrition/barcode/lookup?code={COKE}",
                    headers=client_auth["headers"], timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert data["found"] is True
        assert data["cached"] is True, data

    def test_lookup_not_found(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/barcode/lookup?code={UNKNOWN}",
                    headers=client_auth["headers"], timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["found"] is False
        assert data["product"] is None

    def test_lookup_not_found_negative_cache(self, api, base_url, client_auth):
        # Second call should still return found:false; whether cached==True
        # depends on implementation — the barcode_cache row must exist w/ product=None
        r1 = api.get(f"{base_url}/api/nutrition/barcode/lookup?code={UNKNOWN}",
                     headers=client_auth["headers"], timeout=20)
        assert r1.status_code == 200
        r2 = api.get(f"{base_url}/api/nutrition/barcode/lookup?code={UNKNOWN}",
                     headers=client_auth["headers"], timeout=20)
        assert r2.status_code == 200
        assert r2.json()["found"] is False


# --- logs/from-barcode ------------------------------------------------------

class TestLogFromBarcode:
    def test_log_from_barcode_success(self, api, base_url, client_auth):
        body = {"barcode": COKE, "servings": 2, "meal_type": "snack", "save_as_favourite": True}
        r = api.post(f"{base_url}/api/nutrition/logs/from-barcode",
                     json=body, headers=client_auth["headers"], timeout=25)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "log" in data and "product" in data
        log = data["log"]
        product = data["product"]
        assert log["source"] == "barcode"
        assert log["barcode"] == COKE
        # Verify scaling (2×)
        expected_cal = round(float(product.get("calories") or 0) * 2)
        assert log["calories"] == expected_cal, (log["calories"], expected_cal)
        assert log["protein_g"] == round(float(product.get("protein_g") or 0) * 2, 1)
        assert log["carbs_g"] == round(float(product.get("carbs_g") or 0) * 2, 1)
        assert log["fats_g"] == round(float(product.get("fats_g") or 0) * 2, 1)
        assert "2" in log["portion"] and "x" in log["portion"].lower(), log["portion"]

        # Verify a log row exists via nutrition/today (or /logs endpoint if present)
        # Simpler: check nutrition/today totals bumped; but we may not have exact isolation.
        # Verify favourites has an entry with matching name
        rf = api.get(f"{base_url}/api/nutrition/favourites",
                     headers=client_auth["headers"], timeout=15)
        if rf.status_code == 200:
            favs = rf.json()
            if isinstance(favs, dict):
                favs = favs.get("favourites") or favs.get("items") or []
            names = [f.get("name", "").lower() for f in favs]
            assert any("cola" in n for n in names), names

    def test_log_from_barcode_bad_servings_negative(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/logs/from-barcode",
                     json={"barcode": COKE, "servings": -1, "meal_type": "snack"},
                     headers=client_auth["headers"], timeout=15)
        assert r.status_code == 400

    def test_log_from_barcode_bad_servings_too_large(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/logs/from-barcode",
                     json={"barcode": COKE, "servings": 100, "meal_type": "snack"},
                     headers=client_auth["headers"], timeout=15)
        assert r.status_code == 400

    def test_log_from_barcode_bad_barcode(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/logs/from-barcode",
                     json={"barcode": "abc", "servings": 1, "meal_type": "snack"},
                     headers=client_auth["headers"], timeout=15)
        assert r.status_code == 400

    def test_log_from_barcode_unknown_product(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/logs/from-barcode",
                     json={"barcode": UNKNOWN2, "servings": 1, "meal_type": "snack"},
                     headers=client_auth["headers"], timeout=25)
        assert r.status_code == 404, r.text


# --- food/search ------------------------------------------------------------

class TestFoodSearch:
    def test_search_min_length_guard(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/food/search?q=a",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data.get("results") == []

    def test_search_valid_query(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/nutrition/food/search?q=milk&limit=5",
                    headers=client_auth["headers"], timeout=25)
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
        assert isinstance(data["results"], list)
        assert len(data["results"]) <= 5
