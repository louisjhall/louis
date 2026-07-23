"""
Iter 93 / Master Fix Phase 2 backend regression sweep.

Phase 2 is a frontend-only rework — no new backend routes were added. This suite
verifies that the endpoints the reworked UI leans on still return the expected
shapes, and that Phase 1 endpoints (app-config, media reconcile, calendar range,
recovery, timezone) have not regressed.

Endpoints under test:
    - Nutrition centre used by NutritionTodayCard + full /nutrition screen:
        GET  /api/nutrition/today
        GET  /api/nutrition/summary
        GET  /api/nutrition/week-summary
        GET  /api/nutrition/targets/mine
        GET  /api/nutrition/atlas-tip
        GET  /api/nutrition/insights/latest
        POST /api/nutrition/logs → GET /api/nutrition/today totals sync
        POST /api/nutrition/meals (existence + shape)
    - Guided workout flow:
        GET  /api/workouts/{id}                     (exercises list)
        GET  /api/exercises/content?name=<name>     (media resolver)
        GET  /api/exercise-content?q=<name>         (library search)
    - Phase 1 regression:
        GET  /api/app-config
        POST /api/admin/media/reconcile
        GET  /api/calendar/range
        GET  /api/recovery/missed
        POST /api/recovery/{wid}/suggestions
        GET  /api/profile/timezone-status
"""
import os
import datetime as _dt
import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")

CLIENT_EMAIL = "testcal2@crewfit.com"
CLIENT_PASSWORD = "TestCal123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"


# --------------------------------------------------------------------------- fixtures
def _login(email: str, password: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    data = r.json()
    return {
        "token": data["token"],
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['token']}", "Content-Type": "application/json"},
    }


@pytest.fixture(scope="module")
def client_auth():
    return _login(CLIENT_EMAIL, CLIENT_PASSWORD)


@pytest.fixture(scope="module")
def coach_auth():
    return _login(COACH_EMAIL, COACH_PASSWORD)


# --------------------------------------------------------------------------- Nutrition centre
class TestNutritionToday:
    """Shape used by NutritionTodayCard on the home screen."""

    def test_today_returns_totals_target_remaining(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/nutrition/today", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # top-level keys
        for k in ["date_local", "target", "totals", "hydration_ml", "remaining"]:
            assert k in body, f"missing top-level key '{k}' in /nutrition/today response: {body.keys()}"
        # target shape
        target = body["target"]
        assert isinstance(target, dict)
        for k in ["calories", "protein_g"]:
            assert k in target, f"target missing '{k}': {target.keys()}"
        # totals shape
        totals = body["totals"]
        for k in ["calories", "protein_g", "carbs_g", "fats_g", "count"]:
            assert k in totals, f"totals missing '{k}': {totals.keys()}"
        # remaining shape
        remaining = body["remaining"]
        for k in ["calories", "protein_g", "hydration_ml"]:
            assert k in remaining, f"remaining missing '{k}': {remaining.keys()}"
        # date is ISO YYYY-MM-DD
        _dt.date.fromisoformat(body["date_local"])

    def test_today_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/nutrition/today", timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 unauth, got {r.status_code}"


class TestNutritionSummary:
    def test_summary_shape(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/nutrition/summary", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        for k in ["date", "calories", "protein_g", "calorie_target", "protein_target", "meals"]:
            assert k in b, f"summary missing '{k}': {b.keys()}"
        assert isinstance(b["meals"], list)


class TestNutritionWeekSummary:
    def test_week_summary_shape(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/nutrition/week-summary", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        for k in ["days_logged", "days_total", "avg_calories", "avg_protein_g", "per_day"]:
            assert k in b, f"week-summary missing '{k}': {b.keys()}"
        assert b["days_total"] == 7
        assert isinstance(b["per_day"], list) and len(b["per_day"]) == 7
        for row in b["per_day"]:
            assert "date" in row and "calories" in row and "protein_g" in row


class TestNutritionTargetsMine:
    def test_targets_mine_shape(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/nutrition/targets/mine", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        assert "target" in b and "guardrails" in b
        t = b["target"]
        # target must at least expose calorie/protein numbers used by the UI
        for k in ["calories", "protein_g"]:
            assert k in t, f"target missing '{k}': {t.keys()}"
        # guardrails floor/ceiling
        g = b["guardrails"]
        for k in ["min_calories", "min_protein_g", "max_calories", "max_protein_g", "min_hydration_ml"]:
            assert k in g, f"guardrails missing '{k}': {g.keys()}"


class TestNutritionAtlasTip:
    def test_atlas_tip_returns_string(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/nutrition/atlas-tip", headers=client_auth["headers"], timeout=45)
        # Atlas tip is a Claude call; if the LLM key is degraded backend should still return 200 with fallback
        assert r.status_code == 200, r.text
        b = r.json()
        # Endpoint returns at minimum {"tip": "..."} — accept any dict shape but must include "tip" or "text"
        assert "tip" in b or "text" in b or "message" in b, f"atlas-tip unexpected shape: {b}"


class TestNutritionInsightsLatest:
    def test_insights_latest_reachable(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/nutrition/insights/latest", headers=client_auth["headers"], timeout=30)
        # It's OK if the user has no insight yet — endpoint just needs to respond without 5xx
        assert r.status_code in (200, 204, 404), f"unexpected status {r.status_code}: {r.text[:200]}"
        if r.status_code == 200:
            b = r.json()
            assert isinstance(b, dict)


class TestNutritionLogsFeedTodayTotals:
    """POST /api/nutrition/logs → GET /api/nutrition/today should reflect the new totals."""

    def test_log_shows_in_today_totals(self, client_auth):
        before = requests.get(f"{BASE_URL}/api/nutrition/today", headers=client_auth["headers"], timeout=30).json()
        payload = {
            "food_name": "TEST_iter93 protein bar",
            "meal_type": "snack",
            "source": "manual",
            "description": "TEST_iter93 protein bar",
            "calories": 123,
            "protein_g": 11.5,
            "carbs_g": 8,
            "fats_g": 4,
        }
        cr = requests.post(f"{BASE_URL}/api/nutrition/logs", headers=client_auth["headers"], json=payload, timeout=30)
        assert cr.status_code == 200, cr.text
        log_id = cr.json()["log"]["id"]

        try:
            after = requests.get(f"{BASE_URL}/api/nutrition/today", headers=client_auth["headers"], timeout=30).json()
            assert after["totals"]["calories"] - before["totals"]["calories"] >= 123
            assert round(after["totals"]["protein_g"] - before["totals"]["protein_g"], 1) >= 11.5
        finally:
            requests.delete(f"{BASE_URL}/api/nutrition/logs/{log_id}", headers=client_auth["headers"], timeout=15)


class TestNutritionMealsEndpoint:
    """POST /api/nutrition/meals is a separate collection used by the meal-scan flow.
    Verify the endpoint exists and returns the meal payload we posted. This is what
    the NutritionTodayCard exposes on tap → photo-scan entry point (via /nutrition screen)."""

    def test_meal_create_and_list(self, client_auth):
        payload = {
            "meal_type": "snack",
            "description": "TEST_iter93 apple",
            "calories": 95,
            "protein_g": 0,
        }
        cr = requests.post(f"{BASE_URL}/api/nutrition/meals", headers=client_auth["headers"], json=payload, timeout=30)
        assert cr.status_code == 200, cr.text
        b = cr.json()
        assert b.get("description") == "TEST_iter93 apple"
        assert b.get("calories") == 95
        # GET /nutrition/meals should include it
        lr = requests.get(f"{BASE_URL}/api/nutrition/meals", headers=client_auth["headers"], timeout=30)
        assert lr.status_code == 200
        rows = lr.json()
        assert any(r.get("id") == b.get("id") for r in rows), "created meal not in /nutrition/meals list"


# --------------------------------------------------------------------------- Guided workout flow (regression)
class TestGuidedWorkoutRegression:
    def _first_workout_id(self, headers):
        # Prefer calendar/range to find any workout id; fall back to /calendar/next
        today = _dt.date.today().isoformat()
        r = requests.get(
            f"{BASE_URL}/api/calendar/range",
            params={"start": (_dt.date.today() - _dt.timedelta(days=30)).isoformat(),
                    "end": (_dt.date.today() + _dt.timedelta(days=30)).isoformat()},
            headers=headers, timeout=30,
        )
        if r.status_code != 200:
            return None
        for day in r.json().get("days", []):
            w = day.get("workout")
            if w and w.get("id"):
                return w["id"]
        return None

    def test_workouts_get_returns_exercises(self, client_auth):
        wid = self._first_workout_id(client_auth["headers"])
        if not wid:
            pytest.skip("no workout on testcal2 calendar to test /workouts/{id}")
        r = requests.get(f"{BASE_URL}/api/workouts/{wid}", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        w = r.json()
        # guided flow needs an exercises array (empty is allowed for rest days but the field must exist)
        assert "exercises" in w or "blocks" in w or "sections" in w, (
            f"workout missing an exercises/blocks/sections field: {list(w.keys())}"
        )

    def test_exercises_content_by_name(self, client_auth):
        r = requests.get(
            f"{BASE_URL}/api/exercises/content",
            params={"name": "Push-up"},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        # accept either a dict (single match) or a list (search results)
        assert isinstance(b, (dict, list))

    def test_exercise_content_search(self, client_auth):
        r = requests.get(
            f"{BASE_URL}/api/exercise-content",
            params={"q": "push"},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        # library search returns list or {items: [...]}
        items = b if isinstance(b, list) else b.get("items") or b.get("results") or []
        assert isinstance(items, list)


# --------------------------------------------------------------------------- Phase 1 regression
class TestPhase1Regression:
    def test_app_config_public(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/app-config", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, dict) and len(body) >= 1

    def test_admin_media_reconcile(self, coach_auth):
        r = requests.post(
            f"{BASE_URL}/api/admin/media/reconcile",
            headers=coach_auth["headers"], json={}, timeout=90,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert "clients_scanned" in b
        assert isinstance(b["clients_scanned"], int)

    def test_calendar_range(self, client_auth):
        r = requests.get(
            f"{BASE_URL}/api/calendar/range",
            params={"start": (_dt.date.today() - _dt.timedelta(days=7)).isoformat(),
                    "end": (_dt.date.today() + _dt.timedelta(days=7)).isoformat()},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert "days" in b and isinstance(b["days"], list)

    def test_recovery_missed(self, client_auth):
        r = requests.get(
            f"{BASE_URL}/api/recovery/missed",
            params={"window": 14},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        # accept list or {missed: [...]}
        items = b if isinstance(b, list) else b.get("missed") or b.get("items") or b.get("workouts") or []
        assert isinstance(items, list)

    def test_recovery_suggestions_endpoint_reachable(self, client_auth):
        # find any past incomplete workout via calendar/range
        r = requests.get(
            f"{BASE_URL}/api/calendar/range",
            params={"start": (_dt.date.today() - _dt.timedelta(days=30)).isoformat(),
                    "end": _dt.date.today().isoformat()},
            headers=client_auth["headers"], timeout=30,
        )
        wid = None
        if r.status_code == 200:
            for day in r.json().get("days", []):
                w = day.get("workout")
                if w and w.get("id") and not w.get("completed") and not w.get("skipped"):
                    wid = w["id"]
                    break
        if not wid:
            pytest.skip("no candidate missed workout to test /recovery/{wid}/suggestions")
        sr = requests.post(
            f"{BASE_URL}/api/recovery/{wid}/suggestions",
            headers=client_auth["headers"], json={}, timeout=45,
        )
        # 200 with slots, or 404/409 if the backend refuses — must not 5xx
        assert sr.status_code < 500, f"suggestions 5xx: {sr.status_code} {sr.text}"
        if sr.status_code == 200:
            b = sr.json()
            assert isinstance(b, dict)

    def test_profile_timezone_status(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/profile/timezone-status", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        b = r.json()
        for k in ["home_timezone", "current_timezone", "current_timezone_source", "needs_confirmation"]:
            assert k in b, f"timezone-status missing '{k}': {b.keys()}"
        assert b["current_timezone_source"] in ("roster", "client_confirmed", "device", "home_base", "unknown")
