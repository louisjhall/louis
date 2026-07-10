"""Backend tests for feature_nutrition_travel (Phase 4).

Endpoints under test:
    GET  /api/nutrition/travel/context
    POST /api/nutrition/travel/decision
    POST /api/nutrition/travel/airport
    POST /api/nutrition/travel/timing
    POST /api/nutrition/travel/guide

Live LLM (Claude Sonnet 4.5) is invoked. Timeout is set generously (60s).
Cache is bypassed by mutating params (notes/airport_code/etc.) for each fresh
call, then a repeat is issued to prove `cached:true`.
"""
import os
import time
import uuid
import pytest
import requests

BASE = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"

BANNED = ["cheat", "bad food", "dirty food", "failed"]
# note: "diet" as a substring is scrubbed to "nutrition " so must not appear
# as standalone word either


# ---------- helpers -------------------------------------------------
def _flat_text(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " || ".join(_flat_text(x) for x in obj)
    if isinstance(obj, dict):
        return " || ".join(_flat_text(v) for v in obj.values())
    return ""


def _assert_no_banned(text: str) -> None:
    lower = text.lower()
    for word in BANNED:
        assert word not in lower, f"banned word '{word}' present in: {text[:200]}"


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE}/api/auth/login",
        json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# unique nonce per test run so cache always misses the first time
NONCE = uuid.uuid4().hex[:8]


# ---------- 1. GET /context -----------------------------------------
class TestContext:
    def test_context_ok(self, auth_headers):
        r = requests.get(f"{BASE}/api/nutrition/travel/context",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        ctx = r.json()["context"]
        for k in ("goal", "target_calories", "target_protein_g",
                  "target_hydration_ml", "today_calories", "today_protein_g",
                  "hydration_ml_today", "remaining", "logs_today"):
            assert k in ctx, f"missing key {k} in context"
        for k in ("calories", "protein_g", "hydration_ml"):
            assert k in ctx["remaining"], f"remaining missing {k}"

    def test_context_unauth(self):
        r = requests.get(f"{BASE}/api/nutrition/travel/context", timeout=10)
        assert r.status_code == 401


# ---------- 2. POST /decision ---------------------------------------
class TestDecision:
    body = {
        "situation": "night_flight",
        "hunger_level": "medium",
        "next_context": "sleep_soon",
        "notes": f"nonce {NONCE}",
    }

    def test_decision_first_call(self, auth_headers):
        r = requests.post(f"{BASE}/api/nutrition/travel/decision",
                          headers=auth_headers, json=self.body, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cached"] is False
        d = data["decision"]
        for k in ("headline", "reason", "do_this", "avoid",
                  "protein_led_options", "hydration_note", "confidence"):
            assert k in d, f"missing {k}"
        assert d["headline"], "empty headline"
        assert isinstance(d["do_this"], list) and len(d["do_this"]) >= 1
        assert isinstance(d["avoid"], list) and len(d["avoid"]) >= 1
        assert isinstance(d["protein_led_options"], list) and len(d["protein_led_options"]) >= 1
        _assert_no_banned(_flat_text(d))
        assert "context" in data

    def test_decision_cached_second_call(self, auth_headers):
        # small pause so 1st call's cache write commits
        time.sleep(1)
        r = requests.post(f"{BASE}/api/nutrition/travel/decision",
                          headers=auth_headers, json=self.body, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cached"] is True, "expected cached response on 2nd call"
        # payload identical
        assert data["decision"]["headline"]

    def test_decision_invalid_situation(self, auth_headers):
        r = requests.post(f"{BASE}/api/nutrition/travel/decision",
                          headers=auth_headers,
                          json={"situation": "unknown"}, timeout=15)
        assert r.status_code == 400

    def test_decision_unauth(self):
        r = requests.post(f"{BASE}/api/nutrition/travel/decision",
                          json=self.body, timeout=15)
        assert r.status_code == 401


# ---------- 3. POST /airport ----------------------------------------
class TestAirport:
    body = {
        "airport_code": "DXB",
        "time_available_min": 60,
        "hunger_level": "medium",
        "next_context": "duty",
        # airport_name doubles as cache-buster
        "airport_name": f"Dubai T3 {NONCE}",
    }

    def test_airport_ok(self, auth_headers):
        r = requests.post(f"{BASE}/api/nutrition/travel/airport",
                          headers=auth_headers, json=self.body, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        plan = data["plan"]
        for k in ("headline", "best_moves", "ok_moves", "avoid_if_possible",
                  "snack_backup", "hydration_reminder", "if_time_is_short",
                  "confidence"):
            assert k in plan, f"missing {k}"
        for k in ("best_moves", "ok_moves", "avoid_if_possible", "snack_backup"):
            assert isinstance(plan[k], list)
            assert 1 <= len(plan[k]) <= 5, f"{k} out of bounds: {plan[k]}"
        _assert_no_banned(_flat_text(plan))

    def test_airport_unauth(self):
        r = requests.post(f"{BASE}/api/nutrition/travel/airport",
                          json=self.body, timeout=15)
        assert r.status_code == 401


# ---------- 4. POST /timing -----------------------------------------
class TestTiming:
    body = {
        "home_tz": "Europe/London",
        "current_tz": "Asia/Dubai",
        "flight_context": "long_haul",
        "planned_sleep_local": "22:30",
        "next_workout_context": f"tomorrow_am",  # note is cache-key part
    }

    def test_timing_ok(self, auth_headers):
        # cache-bust via unique home_tz suffix? server uses exact enum
        # instead we rely on nonce-free params; will still hit real LLM
        # if cache is empty for today. If a previous run cached this exact
        # combo we accept the cached response.
        r = requests.post(f"{BASE}/api/nutrition/travel/timing",
                          headers=auth_headers, json=self.body, timeout=60)
        assert r.status_code == 200, r.text
        data = r.json()
        t = data["timing"]
        for k in ("headline", "meal_plan", "caffeine_cutoff", "hydration_focus",
                  "post_flight_recovery_meal", "confidence"):
            assert k in t
        mp = t["meal_plan"]
        assert isinstance(mp, list) and 2 <= len(mp) <= 6, f"meal_plan len {len(mp)}"
        for entry in mp:
            assert "when" in entry and "what" in entry
            assert entry["when"] and entry["what"]
        _assert_no_banned(_flat_text(t))

    def test_timing_unauth(self):
        r = requests.post(f"{BASE}/api/nutrition/travel/timing",
                          json=self.body, timeout=15)
        assert r.status_code == 401


# ---------- 5. POST /guide ------------------------------------------
class TestGuide:
    def test_guide_hotel_buffet(self, auth_headers):
        r = requests.post(f"{BASE}/api/nutrition/travel/guide",
                          headers=auth_headers,
                          json={"topic": "hotel_buffet"}, timeout=60)
        assert r.status_code == 200, r.text
        g = r.json()["guide"]
        for k in ("topic", "title", "one_liner", "steps", "watchouts",
                  "if_goal_is_fat_loss", "if_goal_is_muscle_gain",
                  "if_goal_is_endurance"):
            assert k in g
        assert g["topic"] == "hotel_buffet"
        assert isinstance(g["steps"], list) and 5 <= len(g["steps"]) <= 8
        _assert_no_banned(_flat_text(g))

    def test_guide_invalid_topic(self, auth_headers):
        r = requests.post(f"{BASE}/api/nutrition/travel/guide",
                          headers=auth_headers,
                          json={"topic": "invalid_topic"}, timeout=15)
        assert r.status_code == 400

    def test_guide_unauth(self):
        r = requests.post(f"{BASE}/api/nutrition/travel/guide",
                          json={"topic": "hotel_buffet"}, timeout=15)
        assert r.status_code == 401
