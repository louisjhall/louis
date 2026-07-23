"""
Iter 94j — Programme Week 1 + First-Day Choice.

Covers:

* `_display_week_for` computes the correct week from
  `programme_start_date_local` (0-6 days → Week 1, 7-13 → Week 2, etc.).
* `enrich_programme_for_display` attaches `display_week`, `phase_display_label`,
  `first_day_choice_needed`, `is_setup_day_today`.
* `/programme/first-day-status` returns needs_choice=true on Day 1 before the
  client answers, and false after.
* `/programme/first-day-choice` accepts setup_day / light_mobility_today /
  train_today, updates the programme doc, soft-cancels today's workout for
  setup_day / light_mobility_today, and creates a coach task if
  train_today is blocked by a long-haul roster day.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import date, timedelta

import httpx
import pytest
from dotenv import load_dotenv

sys.path.insert(0, "/app/backend")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001/api")


# ---------------------------------------------------------------------------
# Unit — _display_week_for
# ---------------------------------------------------------------------------

def test_display_week_returns_1_on_day_1():
    from feature_programme_quality import _display_week_for
    today_iso = date.today().isoformat()
    assert _display_week_for({"programme_start_date_local": today_iso}) == 1
    assert _display_week_for({"start_date": today_iso}) == 1


def test_display_week_returns_2_after_7_days():
    from feature_programme_quality import _display_week_for
    start = (date.today() - timedelta(days=7)).isoformat()
    assert _display_week_for({"programme_start_date_local": start}) == 2


def test_display_week_returns_3_after_14_days():
    from feature_programme_quality import _display_week_for
    start = (date.today() - timedelta(days=14)).isoformat()
    assert _display_week_for({"programme_start_date_local": start}) == 3


def test_display_week_handles_datetime_string():
    from feature_programme_quality import _display_week_for
    today_dt = date.today().isoformat() + "T14:23:11+00:00"
    assert _display_week_for({"programme_start_date_local": today_dt}) == 1


def test_display_week_ignores_calendar_iso_week():
    """The BUG: some programmes had week_index = 2 stored due to an off-by-one.
    display_week must IGNORE week_index and compute from the start date."""
    from feature_programme_quality import _display_week_for
    p = {
        "programme_start_date_local": date.today().isoformat(),
        "week_index": 2,  # bug value
    }
    # display_week uses the START DATE, not week_index — so Day 1 → Week 1
    assert _display_week_for(p) == 1


# ---------------------------------------------------------------------------
# Unit — enrich_programme_for_display
# ---------------------------------------------------------------------------

def test_enrich_programme_adds_display_week_and_flags():
    from feature_programme_quality import enrich_programme_for_display
    p = {
        "programme_start_date_local": date.today().isoformat(),
        "week_index": 1,
        "phase": {"key": "foundation", "label": "Foundation"},
        "first_day_choice": None,
        "validation_status": "ok",
    }
    r = enrich_programme_for_display(p)
    assert r["display_week"] == 1
    assert r["phase_display_label"] == "Foundation — Week 1"
    assert r["first_day_choice_needed"] is True
    assert r["is_setup_day_today"] is False


def test_enrich_programme_is_setup_day_today_only_when_choice_is_setup():
    from feature_programme_quality import enrich_programme_for_display
    today = date.today().isoformat()
    p1 = {"programme_start_date_local": today, "first_day_choice": "setup_day"}
    p2 = {"programme_start_date_local": today, "first_day_choice": "train_today"}
    p3 = {"programme_start_date_local": (date.today() - timedelta(days=3)).isoformat(),
          "first_day_choice": "setup_day"}
    assert enrich_programme_for_display(p1)["is_setup_day_today"] is True
    assert enrich_programme_for_display(p2)["is_setup_day_today"] is False
    # setup_day chosen 3 days ago — today is NOT the setup day
    assert enrich_programme_for_display(p3)["is_setup_day_today"] is False


def test_enrich_programme_no_choice_needed_after_answered():
    from feature_programme_quality import enrich_programme_for_display
    p = {
        "programme_start_date_local": date.today().isoformat(),
        "first_day_choice": "setup_day",  # answered
    }
    assert enrich_programme_for_display(p)["first_day_choice_needed"] is False


# ---------------------------------------------------------------------------
# E2E — first-day status + choice via HTTP
# ---------------------------------------------------------------------------

def _seed_client_with_programme(c: httpx.Client, start_iso: str = None) -> tuple[str, dict]:
    """Sign up, complete training-setup, and seed a fresh programme in Mongo."""
    from motor.motor_asyncio import AsyncIOMotorClient
    email = f"iter94j_{int(time.time()*1000)}@t.com"
    r = c.post("/auth/signup", json={
        "name": "T", "email": email, "password": "Passw0rd!",
        "age_confirmed": True, "role": "client",
        "sex": "male", "job_title": "Cabin Crew",
    })
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    uid = (j.get("user") or {}).get("id")
    h = {"Authorization": f"Bearer {tok}"}
    c.post("/profile/training-setup", json={
        "flying_type": "short_haul", "primary_goal": "lose_fat",
        "training_days": 4, "time_home": 45,
        "equipment_home": ["bodyweight_only", "dumbbells"],
        "injuries": "None", "no_go_movements": [],
    }, headers=h)

    async def _seed():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        anchor = start_iso or date.today().isoformat()
        await db.programmes.insert_one({
            "id": f"prog_{int(time.time()*1000)}",
            "user_id": uid,
            "roster_id": None,
            "week_index": 1,
            "goal_key": "lose_fat", "goal_label": "Fat Loss",
            "phase": {"key": "foundation", "label": "Foundation"},
            "programme_start_date_local": anchor,
            "start_date": anchor,
            "first_day_choice": None,
            "validation_status": "ok",
            "created_at": anchor + "T00:00:00+00:00",
            "updated_at": anchor + "T00:00:00+00:00",
        })

    asyncio.get_event_loop().run_until_complete(_seed())
    return uid, h


def test_first_day_status_needs_choice_on_day_1():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        _uid, h = _seed_client_with_programme(c)
        r = c.get("/programme/first-day-status", headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["needs_choice"] is True
        assert j["display_week"] == 1
        assert j["current_choice"] is None


def test_first_day_status_no_choice_after_answering():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        _uid, h = _seed_client_with_programme(c)
        r = c.post("/programme/first-day-choice", json={"choice": "setup_day"}, headers=h)
        assert r.status_code == 200, r.text
        r = c.get("/programme/first-day-status", headers=h)
        j = r.json()
        assert j["needs_choice"] is False
        assert j["current_choice"] == "setup_day"


def test_setup_day_soft_cancels_todays_workout():
    """Chose setup_day → any workout scheduled for today gets optional=True + role."""
    from motor.motor_asyncio import AsyncIOMotorClient
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        uid, h = _seed_client_with_programme(c)
        today = date.today().isoformat()

        async def _seed_wo():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            wid = f"wo_{int(time.time()*1000)}"
            await db.workouts.insert_one({
                "id": wid, "user_id": uid, "date": today,
                "title": "Session A", "focus": "strength_support",
                "exercises": [{"name": "Push-up"}], "duration_min": 45,
                "completed": False, "coach_locked": False,
            })
            return wid

        wid = asyncio.get_event_loop().run_until_complete(_seed_wo())

        r = c.post("/programme/first-day-choice", json={"choice": "setup_day"}, headers=h)
        assert r.status_code == 200

        async def _check():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            w = await db.workouts.find_one({"id": wid})
            return w

        w = asyncio.get_event_loop().run_until_complete(_check())
        assert w["optional"] is True
        assert w["role"] == "setup_day_soft"
        assert "setup day" in (w.get("change_reason") or "").lower()


def test_train_today_blocked_by_long_haul_creates_coach_task():
    """Chose train_today but today's roster is long-haul → coach task created."""
    from motor.motor_asyncio import AsyncIOMotorClient
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        uid, h = _seed_client_with_programme(c)
        today = date.today().isoformat()

        async def _seed_roster():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            rid = f"rost_{int(time.time()*1000)}"
            await db.rosters.insert_one({
                "id": rid, "user_id": uid, "status": "active",
                "days": [{"date": today, "day_type": "Long-Haul Duty", "load": "red"}],
            })
            # Point programme at this roster
            await db.programmes.update_one({"user_id": uid}, {"$set": {"roster_id": rid}})

        asyncio.get_event_loop().run_until_complete(_seed_roster())
        r = c.post("/programme/first-day-choice", json={"choice": "train_today"}, headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["block_reason"], f"Expected block_reason, got {j}"

        # Coach task exists
        async def _check_task():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            t = await db.coach_tasks.find_one({"type": "first_day_blocked", "client_id": uid})
            return t

        t = asyncio.get_event_loop().run_until_complete(_check_task())
        assert t is not None, "coach_task for first_day_blocked was NOT created"
        assert t["priority"] == "medium"


def test_train_today_no_block_when_roster_is_ok():
    from motor.motor_asyncio import AsyncIOMotorClient
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        uid, h = _seed_client_with_programme(c)
        today = date.today().isoformat()

        async def _seed_roster():
            db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
            rid = f"rost_ok_{int(time.time()*1000)}"
            await db.rosters.insert_one({
                "id": rid, "user_id": uid, "status": "active",
                "days": [{"date": today, "day_type": "Home Day", "load": "green"}],
            })
            await db.programmes.update_one({"user_id": uid}, {"$set": {"roster_id": rid}})

        asyncio.get_event_loop().run_until_complete(_seed_roster())
        r = c.post("/programme/first-day-choice", json={"choice": "train_today"}, headers=h)
        assert r.status_code == 200
        j = r.json()
        assert j["block_reason"] is None
        assert j["programme"]["first_real_workout_date_local"] == today


def test_client_home_home_delivers_display_week_1_for_new_client():
    """Real end-to-end sanity: /programme/current returns display_week=1 on Day 1."""
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        _uid, h = _seed_client_with_programme(c)
        r = c.get("/programme/current", headers=h)
        assert r.status_code == 200
        j = r.json()
        assert j.get("display_week") == 1, (
            f"Expected display_week=1 on Day 1, got {j.get('display_week')} "
            f"(week_index={j.get('week_index')}, start_date_local={j.get('programme_start_date_local')})"
        )


def test_client_home_display_week_2_after_a_week():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        seven_days_ago = (date.today() - timedelta(days=8)).isoformat()
        _uid, h = _seed_client_with_programme(c, start_iso=seven_days_ago)
        r = c.get("/programme/current", headers=h)
        j = r.json()
        assert j.get("display_week") == 2
