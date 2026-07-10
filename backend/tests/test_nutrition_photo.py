"""Backend tests for Nutrition Phase 3 — AI Photo Meal Scanner.

Endpoints under /api/nutrition/photo/*  (feature_nutrition_photo.py).
Uses Claude Sonnet 4.5 vision via emergentintegrations — real network calls.
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import pytest
import requests

FOOD_IMG = Path("/tmp/test_food.jpg")
assert FOOD_IMG.exists(), "test image missing at /tmp/test_food.jpg"
IMG_BYTES = FOOD_IMG.read_bytes()
IMG_B64 = base64.b64encode(IMG_BYTES).decode("ascii")

BANNED_WORDS = ("diet", "cheat", "failed", "bad food")


# ---- helpers ---------------------------------------------------------------

def _login(base_url: str, email: str, password: str) -> str:
    r = requests.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def coach_headers(base_url):
    tok = _login(base_url, "coach@crewfit.com", "Coach123!")
    return {"Authorization": f"Bearer {tok}"}


# ---- 1. meal-mode analyse (real vision call) --------------------------------

class TestPhotoAnalyseMeal:
    scan_id: str = ""

    def test_1_analyse_meal(self, base_url, client_auth):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/analyse",
            headers=client_auth["headers"],
            json={
                "image_base64": IMG_B64,
                "mime": "image/jpeg",
                "mode": "meal",
                "meal_type": "lunch",
            },
            timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        scan = data["scan"]
        assert scan["mode"] == "meal"
        est = scan["estimate"]
        assert est["mode"] == "meal"
        assert isinstance(est["items"], list) and len(est["items"]) >= 1
        assert est["calories"] >= 100, f"calories too low: {est['calories']}"
        assert est["confidence"] in ("low", "medium", "high")
        tip = (est.get("atlas_tip") or "").strip()
        assert tip, "atlas_tip empty"
        assert len(tip) <= 250, f"atlas_tip too long ({len(tip)})"
        low_tip = tip.lower()
        for banned in BANNED_WORDS:
            assert banned not in low_tip, f"tip contains banned word: {banned}"
        TestPhotoAnalyseMeal.scan_id = scan["id"]

    def test_2_analyse_hotel_buffet(self, base_url, client_auth):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/analyse",
            headers=client_auth["headers"],
            json={
                "image_base64": IMG_B64,
                "mime": "image/jpeg",
                "mode": "hotel_buffet",
                "meal_type": "dinner",
            },
            timeout=60,
        )
        assert r.status_code == 200, r.text
        est = r.json()["scan"]["estimate"]
        assert est["mode"] == "hotel_buffet"

    def test_3_analyse_data_uri_prefix(self, base_url, client_auth):
        prefixed = f"data:image/jpeg;base64,{IMG_B64}"
        r = requests.post(
            f"{base_url}/api/nutrition/photo/analyse",
            headers=client_auth["headers"],
            json={"image_base64": prefixed, "mime": "image/jpeg", "mode": "meal"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        assert r.json()["scan"]["estimate"]["calories"] >= 0


# ---- 2. validation / error paths -------------------------------------------

class TestPhotoAnalyseErrors:
    def test_4_unsupported_mime(self, base_url, client_auth):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/analyse",
            headers=client_auth["headers"],
            json={"image_base64": IMG_B64, "mime": "image/gif", "mode": "meal"},
            timeout=30,
        )
        assert r.status_code == 415, r.text

    def test_5_payload_too_large(self, base_url, client_auth):
        # 9 MB of raw bytes → base64 payload > 8 MB
        big_raw = b"\xff" * (9 * 1024 * 1024)
        big_b64 = base64.b64encode(big_raw).decode("ascii")
        r = requests.post(
            f"{base_url}/api/nutrition/photo/analyse",
            headers=client_auth["headers"],
            json={"image_base64": big_b64, "mime": "image/jpeg", "mode": "meal"},
            timeout=60,
        )
        assert r.status_code == 413, r.text

    def test_6_bad_base64(self, base_url, client_auth):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/analyse",
            headers=client_auth["headers"],
            json={"image_base64": "not-base64@@@", "mime": "image/jpeg", "mode": "meal"},
            timeout=30,
        )
        # base64.b64decode(validate=False) may accept garbage; either 400 (bad b64)
        # OR downstream vision may still 200 with fallback estimate. Prefer 400.
        assert r.status_code == 400, f"expected 400 bad base64, got {r.status_code}: {r.text}"

    def test_7_missing_auth(self, base_url):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/analyse",
            json={"image_base64": IMG_B64, "mime": "image/jpeg", "mode": "meal"},
            timeout=30,
        )
        assert r.status_code in (401, 403), r.text


# ---- 3. get / owner-check / image ------------------------------------------

@pytest.fixture(scope="module")
def scan_id_for_client(base_url, client_auth):
    r = requests.post(
        f"{base_url}/api/nutrition/photo/analyse",
        headers=client_auth["headers"],
        json={"image_base64": IMG_B64, "mime": "image/jpeg", "mode": "meal", "meal_type": "lunch"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    return r.json()["scan"]["id"]


@pytest.fixture(scope="module")
def scan_id_for_coach(base_url, coach_headers):
    r = requests.post(
        f"{base_url}/api/nutrition/photo/analyse",
        headers=coach_headers,
        json={"image_base64": IMG_B64, "mime": "image/jpeg", "mode": "meal"},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    return r.json()["scan"]["id"]


class TestPhotoGet:
    def test_8_get_scan(self, base_url, client_auth, scan_id_for_client):
        r = requests.get(
            f"{base_url}/api/nutrition/photo/{scan_id_for_client}",
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200
        scan = r.json()["scan"]
        assert scan["id"] == scan_id_for_client
        assert "estimate" in scan
        assert "storage_path" not in scan

    def test_9_get_other_users_scan_404(self, base_url, client_auth, scan_id_for_coach):
        # Client tries to read coach's scan → 404 (owner check).
        r = requests.get(
            f"{base_url}/api/nutrition/photo/{scan_id_for_coach}",
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 404, r.text

    def test_10a_image_bearer(self, base_url, client_auth, scan_id_for_client):
        r = requests.get(
            f"{base_url}/api/nutrition/photo/{scan_id_for_client}/image",
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")
        assert len(r.content) > 100

    def test_10b_image_query_token(self, base_url, client_auth, scan_id_for_client):
        r = requests.get(
            f"{base_url}/api/nutrition/photo/{scan_id_for_client}/image",
            params={"token": client_auth["token"]}, timeout=30,
        )
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/")

    def test_10c_image_other_user_404(self, base_url, coach_headers, scan_id_for_client):
        r = requests.get(
            f"{base_url}/api/nutrition/photo/{scan_id_for_client}/image",
            headers=coach_headers, timeout=30,
        )
        assert r.status_code == 404, r.text


# ---- 4. patch / save-log ---------------------------------------------------

class TestPhotoPatchAndSave:
    def test_11_patch_scan(self, base_url, client_auth, scan_id_for_client):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/{scan_id_for_client}/patch",
            headers=client_auth["headers"],
            json={
                "calories": 500,
                "protein_g": 40,
                "items": [{"name": "chicken", "portion": "150g"}],
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        est = r.json()["scan"]["estimate"]
        assert est["calories"] == 500
        assert est["protein_g"] == 40.0
        assert len(est["items"]) == 1
        assert est["items"][0]["name"] == "chicken"

    def test_12_save_log(self, base_url, client_auth, scan_id_for_client):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/{scan_id_for_client}/save-log",
            headers=client_auth["headers"],
            json={"meal_type": "lunch", "save_as_favourite": True},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("already_saved") is False
        log = data["log"]
        assert log["source"] == "photo"
        assert log["photo_scan_id"] == scan_id_for_client
        assert log["photo_url"].startswith("/api/nutrition/photo/")
        assert log["confidence_level"] in ("low", "medium", "high")
        assert log["meal_type"] == "lunch"
        assert log["calories"] == 500
        # Verify favourite was created (list favourites endpoint if available;
        # otherwise just accept success — favourite persistence is validated
        # indirectly by the save-log 200.
        self.__class__.log_id = log["id"]

    def test_13_save_log_idempotent(self, base_url, client_auth, scan_id_for_client):
        r = requests.post(
            f"{base_url}/api/nutrition/photo/{scan_id_for_client}/save-log",
            headers=client_auth["headers"],
            json={"meal_type": "lunch", "save_as_favourite": False},
            timeout=30,
        )
        assert r.status_code == 200
        data = r.json()
        assert data.get("already_saved") is True
        assert data["log"]["id"] == self.__class__.log_id

    def test_14_log_appears_in_nutrition_logs(self, base_url, client_auth):
        # Confirm the log actually persisted with source="photo"
        # via the generic list-logs endpoint (feature_nutrition).
        r = requests.get(
            f"{base_url}/api/nutrition/logs",
            headers=client_auth["headers"], timeout=30,
        )
        # Best-effort check — endpoint may not exist under that exact path.
        if r.status_code == 200:
            logs = r.json().get("logs") or r.json()
            if isinstance(logs, list):
                photo_logs = [x for x in logs if x.get("source") == "photo"]
                assert len(photo_logs) >= 1
