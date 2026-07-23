"""
Iter 94u — Daily Briefing feature backend tests.

Covers:
- GET /api/coach-profile — Louis Hall record
- GET /api/daily-briefing/today — build + idempotency
- POST /api/daily-briefing/dismiss — sets dismissed_at + should_show_modal=false
- GET/POST /api/daily-briefing/preferences — defaults, updates, invalid tone
- POST /api/daily-briefing/regenerate — new briefing, new id
- Timezone/greeting for Asia/Dubai testcal2 client
- Goal detection (fat_loss)
- Layover title + layover_focus (seeded roster)
- Missed-yesterday (seeded workout)
- Phase 1-3 regression endpoints
"""
import os
import time
import pytest
import requests
import datetime as _dt
from zoneinfo import ZoneInfo

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

TESTCAL_EMAIL = "testcal2@crewfit.com"
TESTCAL_PASS = "TestCal123!"
LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PASS = "Louis123!"


# ------- helpers -------

@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(api, email, password):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    data = r.json()
    return data["token"], data["user"]


@pytest.fixture(scope="module")
def client_auth(api):
    token, user = _login(api, TESTCAL_EMAIL, TESTCAL_PASS)
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def coach_auth(api):
    token, user = _login(api, LOUIS_EMAIL, LOUIS_PASS)
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}}


def _regenerate(api, headers):
    r = api.post(f"{BASE_URL}/api/daily-briefing/regenerate", headers=headers, timeout=30)
    assert r.status_code == 200, f"regen failed: {r.status_code} {r.text}"
    return r.json()


# ------- 1. coach-profile -------

class TestCoachProfile:
    def test_returns_louis_hall(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/coach-profile", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("name") == "Louis Hall"
        assert data.get("role") == "CrewFit Coach"
        assert data.get("coach_id") == "louis-hall"
        assert data.get("email") == "louis@crewfit.net"
        assert "wa.link" in (data.get("whatsapp_url") or "") or data.get("whatsapp_url", "").startswith("http")
        assert data.get("active") is True

    def test_requires_auth(self, api):
        r = api.get(f"{BASE_URL}/api/coach-profile", timeout=30)
        assert r.status_code in (401, 403)


# ------- 2. daily-briefing/today -------

class TestDailyBriefingToday:
    def test_shape(self, api, client_auth):
        _regenerate(api, client_auth["headers"])
        r = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert "briefing" in payload
        b = payload["briefing"]
        for key in ("title", "greeting", "workout_focus", "nutrition_focus",
                    "recovery_focus", "main_action", "habits", "coach", "timezone"):
            assert key in b, f"missing field: {key}"
        assert "label" in b["main_action"] and "route" in b["main_action"]
        assert b["coach"]["name"] == "Louis Hall"
        assert payload["should_show_modal"] is True or payload["should_show_modal"] is False
        assert payload["enabled"] is True

    def test_idempotent_same_id(self, api, client_auth):
        _regenerate(api, client_auth["headers"])
        r1 = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        r2 = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        assert r1.status_code == 200 and r2.status_code == 200
        id1 = r1.json()["briefing"].get("id")
        id2 = r2.json()["briefing"].get("id")
        assert id1 is not None
        assert id1 == id2, f"Not idempotent: {id1} != {id2}"

    def test_timezone_is_dubai(self, api, client_auth):
        _regenerate(api, client_auth["headers"])
        r = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        b = r.json()["briefing"]
        assert b["timezone"] == "Asia/Dubai", f"unexpected tz: {b['timezone']}"

    def test_greeting_matches_dubai_hour(self, api, client_auth):
        _regenerate(api, client_auth["headers"])
        r = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        b = r.json()["briefing"]
        hour = _dt.datetime.now(ZoneInfo("Asia/Dubai")).hour
        greeting = (b.get("greeting") or "").lower()
        if hour < 5:
            assert greeting.startswith("hi"), greeting
        elif hour < 12:
            assert greeting.startswith("morning"), greeting
        elif hour < 17:
            assert greeting.startswith("afternoon"), greeting
        elif hour < 21:
            assert greeting.startswith("evening"), greeting
        else:
            assert greeting.startswith("hi"), greeting

    def test_goal_class_fat_loss(self, api, client_auth):
        _regenerate(api, client_auth["headers"])
        r = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        b = r.json()["briefing"]
        assert b.get("goal_class") == "fat_loss", f"goal_class: {b.get('goal_class')}"


# ------- 3. dismiss -------

class TestDismiss:
    def test_dismiss_sets_flag_and_hides_modal(self, api, client_auth):
        _regenerate(api, client_auth["headers"])
        api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        d = api.post(f"{BASE_URL}/api/daily-briefing/dismiss",
                     headers=client_auth["headers"], json={"reason": "test"}, timeout=30)
        assert d.status_code == 200, d.text
        assert d.json().get("ok") is True

        r = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        payload = r.json()
        assert payload["should_show_modal"] is False
        assert payload["briefing"].get("dismissed_at") is not None


# ------- 4. preferences -------

class TestPreferences:
    def test_defaults_after_reset(self, api, client_auth):
        # Ensure fresh defaults by unsetting via direct update if we have one, else at least ensure endpoint returns valid shape
        # Reset by explicitly setting defaults
        api.post(f"{BASE_URL}/api/daily-briefing/preferences",
                 headers=client_auth["headers"],
                 json={"daily_summary_enabled": True,
                       "daily_summary_push_enabled": False,
                       "daily_summary_tone": "gentle"}, timeout=30)
        r = api.get(f"{BASE_URL}/api/daily-briefing/preferences",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        p = r.json()
        assert p["daily_summary_enabled"] is True
        assert p["daily_summary_push_enabled"] is False
        assert p["daily_summary_tone"] == "gentle"

    def test_update_prefs(self, api, client_auth):
        r = api.post(f"{BASE_URL}/api/daily-briefing/preferences",
                     headers=client_auth["headers"],
                     json={"daily_summary_push_enabled": True,
                           "daily_summary_tone": "direct"}, timeout=30)
        assert r.status_code == 200, r.text
        # verify persisted
        rv = api.get(f"{BASE_URL}/api/daily-briefing/preferences",
                     headers=client_auth["headers"], timeout=30)
        p = rv.json()
        assert p["daily_summary_push_enabled"] is True
        assert p["daily_summary_tone"] == "direct"
        # restore
        api.post(f"{BASE_URL}/api/daily-briefing/preferences",
                 headers=client_auth["headers"],
                 json={"daily_summary_push_enabled": False, "daily_summary_tone": "gentle"},
                 timeout=30)

    def test_invalid_tone_400(self, api, client_auth):
        r = api.post(f"{BASE_URL}/api/daily-briefing/preferences",
                     headers=client_auth["headers"],
                     json={"daily_summary_tone": "aggressive"}, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ------- 5. regenerate -------

class TestRegenerate:
    def test_regenerate_new_id(self, api, client_auth):
        r1 = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
        first_id = r1.json()["briefing"]["id"]
        # small pause so created_at differs
        time.sleep(0.5)
        r2 = api.post(f"{BASE_URL}/api/daily-briefing/regenerate", headers=client_auth["headers"], timeout=30)
        assert r2.status_code == 200, r2.text
        data = r2.json()
        assert data.get("ok") is True
        new_id = data["briefing"]["id"]
        assert new_id != first_id, f"regenerate returned same id: {first_id}"


# ------- 6. Roster layover + missed-yesterday (data seeding via DB) -------

class TestRosterAndMissed:
    @pytest.fixture(scope="class")
    def db(self):
        # direct DB writes for isolated seed
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        # Load .env
        from pathlib import Path
        env_path = Path("/app/backend/.env")
        env = {}
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
        mongo_url = env.get("MONGO_URL") or os.environ.get("MONGO_URL")
        db_name = env.get("DB_NAME") or os.environ.get("DB_NAME")
        assert mongo_url and db_name, "MONGO_URL / DB_NAME missing"
        client = AsyncIOMotorClient(mongo_url)
        return {"client": client, "db": client[db_name], "loop": asyncio.new_event_loop()}

    def test_layover_title_and_focus(self, api, client_auth, db):
        loop = db["loop"]
        d = db["db"]
        user_id = client_auth["user"]["id"]
        today_local = _dt.datetime.now(ZoneInfo("Asia/Dubai")).date().isoformat()

        # Seed an active roster with today = layover in Dubai layover_city.
        # First remove any active rosters for isolation of test.
        async def _seed():
            # Deactivate existing active rosters
            await d.rosters.update_many({"user_id": user_id, "status": "active"},
                                        {"$set": {"status": "archived"}})
            roster_doc = {
                "id": f"test-roster-{int(time.time())}",
                "user_id": user_id,
                "status": "active",
                "created_at": _dt.datetime.utcnow().isoformat(),
                "days": [
                    {
                        "date": today_local,
                        "day_type": "layover",
                        "layover_city": "singapore",
                    }
                ],
            }
            await d.rosters.insert_one(roster_doc)
            return roster_doc["id"]

        roster_id = loop.run_until_complete(_seed())

        try:
            # Force fresh briefing
            _regenerate(api, client_auth["headers"])
            r = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
            assert r.status_code == 200
            b = r.json()["briefing"]
            assert "Singapore" in (b.get("title") or ""), f"title should include Singapore: {b.get('title')}"
            assert "Layover Focus" in (b.get("title") or "")
            assert b.get("layover_focus"), "layover_focus should be populated"
            assert "singapore" in (b.get("layover_focus") or "").lower()
            assert b.get("city", "").lower() == "singapore"
        finally:
            async def _cleanup():
                await d.rosters.delete_one({"id": roster_id})
            loop.run_until_complete(_cleanup())
            # Regenerate so downstream tests get clean state
            _regenerate(api, client_auth["headers"])

    def test_missed_yesterday_surfaces(self, api, client_auth, db):
        loop = db["loop"]
        d = db["db"]
        user_id = client_auth["user"]["id"]
        y_local = (_dt.datetime.now(ZoneInfo("Asia/Dubai")).date() - _dt.timedelta(days=1)).isoformat()

        seeded_id = f"test-wo-missed-{int(time.time())}"

        async def _seed():
            await d.workouts.insert_one({
                "id": seeded_id,
                "user_id": user_id,
                "date": y_local,
                "title": "Test Missed Strength",
                "completed": False,
                "skipped": False,
                "key_session": True,
            })

        loop.run_until_complete(_seed())

        try:
            _regenerate(api, client_auth["headers"])
            r = api.get(f"{BASE_URL}/api/daily-briefing/today", headers=client_auth["headers"], timeout=30)
            b = r.json()["briefing"]
            missed = b.get("missed_yesterday")
            assert missed is not None, "missed_yesterday should surface"
            # Must be a missed non-rest workout on yesterday's date
            assert missed.get("date") == y_local
            assert (missed.get("title") or "").lower().startswith("test missed")
        finally:
            async def _cleanup():
                await d.workouts.delete_one({"id": seeded_id})
            loop.run_until_complete(_cleanup())


# ------- 7. Phase 1-3 regression endpoints -------

class TestRegressionEndpoints:
    def test_app_config(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/app-config", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_calendar_range(self, api, client_auth):
        today = _dt.date.today().isoformat()
        end = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
        r = api.get(f"{BASE_URL}/api/calendar/range?start={today}&end={end}",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_recovery_missed(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/recovery/missed",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_profile_timezone_status(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/profile/timezone-status",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_nutrition_today(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/nutrition/today",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_progress_dashboard(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/progress/dashboard",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
