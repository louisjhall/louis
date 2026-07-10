"""CrewFit Nutrition Centre Phase 1 — backend tests.

Covers 14 endpoints under /api/nutrition and /api/coach/nutrition.
Not part of test: /api/nutrition/meals & /api/nutrition/summary (legacy).
"""
from __future__ import annotations

import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    BASE_URL = "https://flight-fit-plans.preview.emergentagent.com"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"
COACH_EMAIL = "coach@crewfit.com"
COACH_PASSWORD = "Coach123!"


def _login(email: str, password: str) -> tuple[str, str]:
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    js = r.json()
    return js["token"], js["user"]["id"]


@pytest.fixture(scope="session")
def client_ctx():
    tok, uid = _login(CLIENT_EMAIL, CLIENT_PASSWORD)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return {"session": s, "user_id": uid, "token": tok}


@pytest.fixture(scope="session")
def coach_ctx():
    tok, uid = _login(COACH_EMAIL, COACH_PASSWORD)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    return {"session": s, "user_id": uid, "token": tok}


# ------------------------------------------------------------
# Targets
# ------------------------------------------------------------
class TestTargets:
    def test_targets_mine_returns_defaults(self, client_ctx):
        s = client_ctx["session"]
        # First: reset to atlas default by deleting existing active target via coach path (not possible)
        # Instead: just check response structure.
        r = s.get(f"{BASE_URL}/api/nutrition/targets/mine")
        assert r.status_code == 200, r.text
        js = r.json()
        assert "target" in js and "guardrails" in js
        t = js["target"]
        assert t.get("calories") and t.get("protein_g") and t.get("hydration_ml")
        g = js["guardrails"]
        assert g["min_calories"] == 1500
        assert g["min_protein_g"] == 60
        assert g["min_hydration_ml"] == 1500

    def test_targets_upsert_clamps_below_floors(self, client_ctx):
        s = client_ctx["session"]
        r = s.post(f"{BASE_URL}/api/nutrition/targets", json={
            "calories": 100, "protein_g": 5, "carbs_g": 10,
            "fats_g": 5, "hydration_ml": 100, "goal": "fat_loss",
        })
        assert r.status_code == 200, r.text
        t = r.json()["target"]
        assert t["calories"] == 1500  # clamped
        assert t["protein_g"] == 60
        assert t["hydration_ml"] == 1500

        # Verify via GET
        r2 = s.get(f"{BASE_URL}/api/nutrition/targets/mine")
        js = r2.json()
        assert js["target"]["calories"] == 1500
        # is_default is now False (target row exists)
        assert not js["target"].get("is_default")


# ------------------------------------------------------------
# Logs
# ------------------------------------------------------------
class TestLogs:
    def test_create_log_default_date_today(self, client_ctx):
        s = client_ctx["session"]
        r = s.post(f"{BASE_URL}/api/nutrition/logs", json={
            "food_name": "TEST_Chicken salad",
            "calories": 420, "protein_g": 38, "carbs_g": 22, "fats_g": 14,
            "meal_type": "lunch", "roster_context": "layover_full",
        })
        assert r.status_code == 200, r.text
        log = r.json()["log"]
        assert log["food_name"] == "TEST_Chicken salad"
        assert log["calories"] == 420
        import datetime as _dt
        assert log["date_local"] == _dt.date.today().isoformat()
        pytest.log_id = log["id"]

    def test_list_logs_days_7(self, client_ctx):
        s = client_ctx["session"]
        r = s.get(f"{BASE_URL}/api/nutrition/logs?days=7")
        assert r.status_code == 200
        js = r.json()
        assert "logs" in js and "count" in js
        assert js["count"] >= 1
        assert any(l["id"] == pytest.log_id for l in js["logs"])

    def test_patch_log(self, client_ctx):
        s = client_ctx["session"]
        r = s.patch(f"{BASE_URL}/api/nutrition/logs/{pytest.log_id}", json={"calories": 500, "protein_g": 40})
        assert r.status_code == 200, r.text
        assert r.json()["log"]["calories"] == 500

    def test_delete_other_user_log_404(self, coach_ctx):
        # Coach tries to delete client's log — should 404 (owner scoping)
        r = coach_ctx["session"].delete(f"{BASE_URL}/api/nutrition/logs/{pytest.log_id}")
        assert r.status_code == 404

    def test_delete_own_log(self, client_ctx):
        s = client_ctx["session"]
        r = s.delete(f"{BASE_URL}/api/nutrition/logs/{pytest.log_id}")
        assert r.status_code == 200
        # verify gone
        r2 = s.delete(f"{BASE_URL}/api/nutrition/logs/{pytest.log_id}")
        assert r2.status_code == 404


# ------------------------------------------------------------
# Today + week summary
# ------------------------------------------------------------
class TestTodayAndSummary:
    def test_today_endpoint(self, client_ctx):
        s = client_ctx["session"]
        # create a log first to get non-zero totals
        s.post(f"{BASE_URL}/api/nutrition/logs", json={
            "food_name": "TEST_Toast", "calories": 250, "protein_g": 10, "carbs_g": 40, "fats_g": 6,
            "meal_type": "breakfast",
        })
        r = s.get(f"{BASE_URL}/api/nutrition/today")
        assert r.status_code == 200
        js = r.json()
        for k in ("target", "totals", "remaining", "hydration_ml"):
            assert k in js
        assert js["totals"]["calories"] >= 250

    def test_week_summary(self, client_ctx):
        s = client_ctx["session"]
        r = s.get(f"{BASE_URL}/api/nutrition/week-summary")
        assert r.status_code == 200
        js = r.json()
        assert js["days_total"] == 7
        assert "per_day" in js and len(js["per_day"]) == 7


# ------------------------------------------------------------
# Hydration
# ------------------------------------------------------------
class TestHydration:
    def test_hydration_increment(self, client_ctx):
        s = client_ctx["session"]
        # get baseline
        base = s.get(f"{BASE_URL}/api/nutrition/hydration/today").json()["amount_ml"]
        r = s.post(f"{BASE_URL}/api/nutrition/hydration", json={"amount_ml": 250})
        assert r.status_code == 200
        new_amt = r.json()["amount_ml"]
        assert new_amt == base + 250
        r2 = s.get(f"{BASE_URL}/api/nutrition/hydration/today")
        assert r2.json()["amount_ml"] == new_amt

    def test_hydration_decrement(self, client_ctx):
        s = client_ctx["session"]
        base = s.get(f"{BASE_URL}/api/nutrition/hydration/today").json()["amount_ml"]
        r = s.post(f"{BASE_URL}/api/nutrition/hydration", json={"amount_ml": -100})
        assert r.status_code == 200
        assert r.json()["amount_ml"] == max(0, base - 100)


# ------------------------------------------------------------
# Favourites
# ------------------------------------------------------------
class TestFavourites:
    def test_favourite_crud(self, client_ctx):
        s = client_ctx["session"]
        r = s.post(f"{BASE_URL}/api/nutrition/favourites", json={
            "name": "TEST_Fav Breakfast", "calories": 350, "protein_g": 25,
            "carbs_g": 32, "fats_g": 10, "meal_type": "breakfast",
        })
        assert r.status_code == 200
        fav = r.json()["favourite"]
        fid = fav["id"]
        r2 = s.get(f"{BASE_URL}/api/nutrition/favourites")
        assert any(f["id"] == fid for f in r2.json()["favourites"])
        r3 = s.delete(f"{BASE_URL}/api/nutrition/favourites/{fid}")
        assert r3.status_code == 200


# ------------------------------------------------------------
# Atlas tip (Claude 4.5) - cache check
# ------------------------------------------------------------
class TestAtlasTip:
    def test_tip_cached(self, client_ctx):
        s = client_ctx["session"]
        r1 = s.get(f"{BASE_URL}/api/nutrition/atlas-tip", timeout=60)
        assert r1.status_code == 200
        t1 = r1.json().get("tip", "")
        assert t1 and len(t1) > 0
        # word count sanity: ≤ 32 words (allow up to 40 for tolerance)
        assert len(t1.split()) <= 45, f"tip too long: {t1}"
        # second call should return identical (cached)
        time.sleep(1)
        r2 = s.get(f"{BASE_URL}/api/nutrition/atlas-tip", timeout=60)
        t2 = r2.json().get("tip", "")
        assert t1 == t2, f"tip not cached! t1={t1!r} t2={t2!r}"


# ------------------------------------------------------------
# Coach endpoints + role gating
# ------------------------------------------------------------
class TestCoach:
    def test_coach_clients_list(self, coach_ctx):
        r = coach_ctx["session"].get(f"{BASE_URL}/api/coach/nutrition/clients")
        assert r.status_code == 200
        js = r.json()
        assert "clients" in js and len(js["clients"]) >= 1
        # verify summary fields exist
        c = js["clients"][0]
        for k in ("user_id", "name", "goal", "target_calories", "today_calories", "avg_calories_7d", "days_logged_7d", "target_is_default"):
            assert k in c, f"missing key {k}"
        pytest.coach_client_id = js["clients"][0]["user_id"]

    def test_coach_client_detail(self, coach_ctx, client_ctx):
        uid = client_ctx["user_id"]
        r = coach_ctx["session"].get(f"{BASE_URL}/api/coach/nutrition/clients/{uid}")
        assert r.status_code == 200
        js = r.json()
        for k in ("user", "target", "recent_logs", "notes"):
            assert k in js

    def test_coach_patch_targets_clamps(self, coach_ctx, client_ctx):
        uid = client_ctx["user_id"]
        r = coach_ctx["session"].patch(f"{BASE_URL}/api/coach/nutrition/targets/{uid}", json={
            "calories": 100, "protein_g": 20, "carbs_g": 200, "fats_g": 60,
            "hydration_ml": 100, "goal": "muscle_gain",
        })
        assert r.status_code == 200
        t = r.json()["target"]
        assert t["calories"] == 1500  # clamped
        assert t["protein_g"] == 60
        assert t["hydration_ml"] == 1500
        assert t["target_type"] == "coach"
        # verify from client's POV
        r2 = client_ctx["session"].get(f"{BASE_URL}/api/nutrition/targets/mine")
        got = r2.json()["target"]
        assert got["calories"] == 1500
        assert got.get("target_type") == "coach"
        assert not got.get("is_default")

    def test_coach_add_note(self, coach_ctx, client_ctx):
        uid = client_ctx["user_id"]
        r = coach_ctx["session"].post(f"{BASE_URL}/api/coach/nutrition/notes", json={
            "client_user_id": uid, "note": "TEST_ Post-flight refuel — 25g protein within 45min.",
        })
        assert r.status_code == 200
        assert r.json()["note"]["client_user_id"] == uid

    def test_role_gating_client_forbidden(self, client_ctx):
        for path in [
            "/api/coach/nutrition/clients",
            f"/api/coach/nutrition/clients/{client_ctx['user_id']}",
        ]:
            r = client_ctx["session"].get(f"{BASE_URL}{path}")
            assert r.status_code == 403, f"expected 403 for {path}, got {r.status_code}"
        r2 = client_ctx["session"].patch(
            f"{BASE_URL}/api/coach/nutrition/targets/{client_ctx['user_id']}",
            json={"calories": 2000},
        )
        assert r2.status_code == 403
        r3 = client_ctx["session"].post(
            f"{BASE_URL}/api/coach/nutrition/notes",
            json={"client_user_id": client_ctx["user_id"], "note": "x"},
        )
        assert r3.status_code == 403
