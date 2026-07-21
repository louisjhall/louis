"""
Iter 82 — Empty-workout content guard + client roster-day correction.

Fixes verified:
  * `_ensure_workout_content` fills a bodyweight fallback into any workout
    persisted with 0 exercises + 0 warmup (unless it's a rest day).
  * Sets `needs_coach_review=True` and stamps `change_reason` explaining.
  * Rest / off / recovery workouts are untouched.
  * PATCH /api/roster/{rid}/day updates a single day and flags the downstream
    workout for coach review.
"""
import sys
import copy
import uuid as _uuid
sys.path.insert(0, "/app/backend")

from server import _ensure_workout_content


def _fake_user():
    return {"id": "u1", "profile": {"equipment": ["dumbbells"]}}


def test_content_guard_fills_empty_workout():
    doc = {
        "id": "w1", "date": "2026-07-21", "title": "Push",
        "day_type": "home", "exercises": [], "warmup": [],
    }
    fixed = _ensure_workout_content(copy.deepcopy(doc), _fake_user())
    assert len(fixed.get("exercises") or []) > 0, "Content guard MUST fill empty exercises"
    assert fixed.get("needs_coach_review") is True
    assert fixed.get("validation_status") == "needs_review"
    assert "Content was missing" in (fixed.get("change_reason") or "")
    assert fixed.get("insufficient_content_reason") == "llm_returned_empty_exercises"


def test_content_guard_leaves_populated_workout_alone():
    doc = {
        "id": "w2", "date": "2026-07-21", "title": "Push",
        "day_type": "home",
        "exercises": [{"name": "Push-up", "sets": 3, "reps": "10"}],
        "warmup": [],
    }
    original = copy.deepcopy(doc)
    fixed = _ensure_workout_content(copy.deepcopy(doc), _fake_user())
    assert fixed["exercises"] == original["exercises"]
    assert not fixed.get("needs_coach_review")
    assert not fixed.get("change_reason")


def test_content_guard_skips_rest_days():
    doc = {
        "id": "w3", "date": "2026-07-21", "title": "Rest Day",
        "day_type": "rest", "exercises": [], "warmup": [],
    }
    fixed = _ensure_workout_content(copy.deepcopy(doc), _fake_user())
    assert fixed["exercises"] == []
    assert not fixed.get("needs_coach_review")


def test_content_guard_skips_recovery_titles():
    doc = {
        "id": "w4", "date": "2026-07-21", "title": "Active Recovery",
        "day_type": "home", "exercises": [], "warmup": [],
    }
    fixed = _ensure_workout_content(copy.deepcopy(doc), _fake_user())
    assert not fixed.get("needs_coach_review")


def test_content_guard_appends_reason_when_one_exists():
    doc = {
        "id": "w5", "date": "2026-07-21", "title": "Push",
        "day_type": "layover", "exercises": [], "warmup": [],
        "change_reason": "Hotel gym unknown — bodyweight only.",
    }
    fixed = _ensure_workout_content(copy.deepcopy(doc), _fake_user())
    assert "Hotel gym unknown" in fixed["change_reason"]
    assert "Content was missing" in fixed["change_reason"]
    # Both reasons joined with the "  · " separator
    assert "  · " in fixed["change_reason"]


# ---- PATCH /api/roster/{rid}/day HTTP tests ------------------------------

def test_patch_roster_day_updates_day_and_flags_workout(api, base_url, client_auth):
    from server import db, new_id, now_iso
    import asyncio

    _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)
    def _r(coro): return _LOOP.run_until_complete(coro)

    uid = client_auth["user"]["id"]
    tag = _uuid.uuid4().hex[:6]
    rid = f"r_{tag}"
    date = "2026-08-01"

    _r(db.rosters.delete_many({"id": rid}))
    _r(db.workouts.delete_many({"user_id": uid, "date": date}))
    _r(db.rosters.insert_one({
        "id": rid, "user_id": uid, "created_at": now_iso(),
        "start_date": "2026-08-01", "end_date": "2026-08-07",
        "is_active": True,
        "days": [
            {"date": "2026-08-01", "day_type": "home"},
            {"date": "2026-08-02", "day_type": "home"},
        ],
    }))
    _r(db.workouts.insert_one({
        "id": f"w_{tag}", "user_id": uid, "date": date,
        "title": "Push", "day_type": "home",
        "exercises": [{"name": "Bench Press"}],
        "created_at": now_iso(),
    }))

    try:
        r = api.patch(
            f"{base_url}/api/roster/{rid}/day",
            json={"date": date, "day_type": "layover_full_day", "layover_city": "Dubai"},
            headers=client_auth["headers"],
            timeout=30,
        )
        assert r.status_code == 200, r.text
        day = r.json().get("day") or {}
        assert day["day_type"] == "layover_full_day"
        assert day["layover_city"] == "Dubai"
        assert day["client_corrected"] is True

        w = _r(db.workouts.find_one({"id": f"w_{tag}"}, {"_id": 0}))
        assert w.get("needs_coach_review") is True
        assert "corrected the roster" in (w.get("change_reason") or "").lower()

        r2 = api.patch(
            f"{base_url}/api/roster/{rid}/day",
            json={"date": "2099-01-01", "day_type": "off"},
            headers=client_auth["headers"], timeout=30,
        )
        assert r2.status_code == 404

        r3 = api.patch(
            f"{base_url}/api/roster/does-not-exist/day",
            json={"date": date, "day_type": "off"},
            headers=client_auth["headers"], timeout=30,
        )
        assert r3.status_code == 404
    finally:
        _r(db.rosters.delete_one({"id": rid}))
        _r(db.workouts.delete_many({"user_id": uid, "date": date}))
