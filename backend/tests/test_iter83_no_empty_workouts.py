"""
Iter 83 — Regression suite for the "workouts persisted with empty main
exercises" class of bug.

Layers under test:
  1. `_ensure_workout_content` — persistence-time guard.
  2. `_heal_workouts_batch`     — read-time heal-on-read.
  3. Startup sweep              — heals stale rows on backend boot.

If any of these tests fail, DO NOT ship — the app will show empty workouts to
real users again.
"""
import asyncio
import os
import sys
import uuid
from datetime import date, timedelta

import pytest

sys.path.insert(0, "/app/backend")

# Ensure motor can init before importing server.
os.environ.setdefault("EMERGENT_LLM_KEY", "x")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")

from server import _ensure_workout_content, _heal_workouts_batch  # noqa: E402


def _mongo() -> AsyncIOMotorClient:
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ---------------------------------------------------------------------------
# Layer 1 — guard tests
# ---------------------------------------------------------------------------

def _train_doc(**overrides) -> dict:
    base = {
        "id": f"test_{uuid.uuid4().hex[:8]}",
        "date": (date.today() + timedelta(days=1)).isoformat(),
        "user_id": "test_user",
        "title": "Full Body Strength",
        "exercises": [],
        "warmup": [{"name": "3 min brisk walk"}],
        "cooldown": [],
        "focus": "full",
        "day_type": "Home Day",
        "duration_min": 40,
    }
    base.update(overrides)
    return base


def test_guard_fills_empty_strength_training_day():
    user = {"id": "test_user", "profile": {}}
    doc = _train_doc(title="Full Body Strength")
    healed = _ensure_workout_content(doc, user)
    assert healed["exercises"], "Guard MUST inject main exercises on empty strength day"
    assert len(healed["exercises"]) >= 3


def test_guard_matches_easy_run_title():
    user = {"id": "test_user", "profile": {}}
    doc = _train_doc(title="Easy Run", focus="long_run", session_type="long_run")
    healed = _ensure_workout_content(doc, user)
    names = [e.get("name", "").lower() for e in healed.get("exercises", [])]
    assert any("easy run" in n for n in names), (
        f"Easy Run title MUST resolve to easy_run stub, got: {names}"
    )


def test_guard_matches_long_run_title():
    user = {"id": "test_user", "profile": {}}
    doc = _train_doc(title="Long Run", focus="long_run", session_type="long_run", duration_min=75)
    healed = _ensure_workout_content(doc, user)
    names = [e.get("name", "").lower() for e in healed.get("exercises", [])]
    assert any("long run" in n for n in names), (
        f"Long Run title MUST resolve to long_run stub, got: {names}"
    )


def test_guard_preserves_existing_warmup():
    user = {"id": "test_user", "profile": {}}
    original_warmup = [{"name": "Custom warmup step"}]
    doc = _train_doc(warmup=original_warmup)
    healed = _ensure_workout_content(doc, user)
    assert healed["warmup"] == original_warmup, "Guard MUST NOT clobber existing warmup"


def test_guard_skips_rest_days():
    user = {"id": "test_user", "profile": {}}
    doc = _train_doc(title="Rest Day", day_type="Rest Day", warmup=[])
    healed = _ensure_workout_content(doc, user)
    assert healed.get("exercises") in ([], None), "Rest days MUST NOT get filled"


def test_guard_skips_mobility_recovery_days():
    user = {"id": "test_user", "profile": {}}
    for title in ["Mobility Flow", "Recovery Walk", "Pre/Post-Flight Mobility",
                  "Standby Activation", "Optional Recovery Walk"]:
        doc = _train_doc(title=title)
        healed = _ensure_workout_content(doc, user)
        assert not healed.get("exercises"), (
            f"Mobility/recovery title '{title}' MUST NOT be filled with strength exercises"
        )


def test_guard_marks_needs_coach_review_after_fill():
    user = {"id": "test_user", "profile": {}}
    doc = _train_doc(title="Full Body Strength")
    healed = _ensure_workout_content(doc, user)
    assert healed.get("needs_coach_review") is True, (
        "A healed workout MUST be flagged for coach review"
    )
    assert healed.get("change_reason"), "A healed workout MUST carry a change_reason"


# ---------------------------------------------------------------------------
# Layer 2 — read-time heal-on-read test
# ---------------------------------------------------------------------------

async def _heal_batch_scenario():
    db = _mongo()
    uid = f"heal_test_{uuid.uuid4().hex[:8]}"
    d = (date.today() + timedelta(days=2)).isoformat()
    wid = f"wtest_{uuid.uuid4().hex[:8]}"
    await db.workouts.insert_one({
        "id": wid, "user_id": uid, "date": d,
        "title": "Full Body Strength",
        "exercises": [],
        "warmup": [{"name": "3 min brisk walk"}],
        "cooldown": [],
        "focus": "full", "day_type": "Home Day", "duration_min": 40,
        "completed": False, "approved": True,
    })
    try:
        rows = await db.workouts.find({"user_id": uid}, {"_id": 0}).to_list(10)
        assert len(rows) == 1 and not rows[0]["exercises"], "seed doc must be empty"

        user = {"id": uid, "profile": {}}
        healed = await _heal_workouts_batch(rows, user)
        assert healed[0].get("exercises"), "heal_batch MUST fill empty workout in memory"

        persisted = await db.workouts.find_one({"id": wid}, {"_id": 0})
        assert persisted.get("exercises"), (
            "heal_batch MUST persist the fix back to Mongo so other clients see it"
        )
        assert persisted.get("auto_healed_at"), (
            "Persisted heal MUST stamp auto_healed_at for audit"
        )
    finally:
        await db.workouts.delete_many({"user_id": uid})


def test_heal_batch_heals_and_persists():
    asyncio.run(_heal_batch_scenario())


async def _heal_batch_leaves_completed_alone_scenario():
    db = _mongo()
    uid = f"heal_test_{uuid.uuid4().hex[:8]}"
    d = (date.today() + timedelta(days=1)).isoformat()
    wid = f"wtest_{uuid.uuid4().hex[:8]}"
    await db.workouts.insert_one({
        "id": wid, "user_id": uid, "date": d,
        "title": "Full Body Strength",
        "exercises": [],
        "warmup": [],
        "focus": "full", "day_type": "Home Day", "duration_min": 40,
        "completed": True,
    })
    try:
        rows = await db.workouts.find({"user_id": uid}, {"_id": 0}).to_list(10)
        user = {"id": uid, "profile": {}}
        healed = await _heal_workouts_batch(rows, user)
        assert healed[0].get("exercises") in ([], None), (
            "Completed workouts MUST stay untouched — respect the user's log"
        )
    finally:
        await db.workouts.delete_many({"user_id": uid})


def test_heal_batch_leaves_completed_workouts_alone():
    asyncio.run(_heal_batch_leaves_completed_alone_scenario())


# ---------------------------------------------------------------------------
# Layer 3 — full HTTP path integration (no empty workout returned by API)
# ---------------------------------------------------------------------------

def test_workouts_week_api_never_returns_empty_training_workout(client_auth, api, base_url):
    """
    Hit the real /api/workouts/week endpoint as a client user and assert
    NO returned workout is missing main exercises on a training day.
    This is the end-to-end contract that closes the class of bug.
    """
    r = api.get(f"{base_url}/api/workouts/week", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200, f"workouts/week failed: {r.status_code} {r.text}"
    rows = r.json()
    empties = []
    today_iso = date.today().isoformat()
    for w in rows:
        if w.get("date", "") < today_iso:
            continue                          # skip history
        if w.get("completed"):
            continue                          # user log
        title = (w.get("title") or "").lower()
        if any(k in title for k in ("rest", "mobility", "recovery", "standby activation", "pre/post-flight")):
            continue                          # intentionally empty
        if not (w.get("exercises") or []):
            empties.append({"id": w.get("id"), "date": w.get("date"), "title": w.get("title")})
    assert not empties, (
        f"/api/workouts/week returned {len(empties)} empty training workouts — "
        f"the empty-workout bug has regressed: {empties[:5]}"
    )
