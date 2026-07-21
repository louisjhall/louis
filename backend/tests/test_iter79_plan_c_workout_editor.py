"""Iter79 Plan C4/C5/C6/C7 — coach workout editor + exercise CRUD/swap/search
+ single-workout regenerate preview + programme regenerate preview/apply.

Coverage:
  T1  PATCH /api/coach/workouts/{wid}                       (meta edit + audit)
  T2  POST/PATCH/DELETE /api/coach/workouts/{wid}/exercises… (add/edit/delete/reorder)
  T3  POST /api/coach/workouts/{wid}/exercises/{idx}/swap    (V2 replace + preserve)
  T4  GET  /api/exercises/v2/search                          (filters + status guard)
  T5  POST /api/coach/workouts/{wid}/regenerate-preview      (presets shorter/easier/harder/tired/as_running/bogus)
  T6  POST /api/coach/clients/{cid}/programme/regenerate-preview
  T7  POST /api/coach/clients/{cid}/programme/regenerate-apply
  T8  Regression smoke — coach dashboard + client programme endpoints healthy

Ephemeral seeds; every seeded row is prefixed TEST_iter79_ and torn down.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

COACH_EMAIL = "louis@crewfit.net"
COACH_PWD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PWD = "Client123!"

TEST_TAG = f"TEST_iter79_{uuid.uuid4().hex[:6]}"

# Single event loop across whole session — motor is bound to first loop
try:
    _LOOP = asyncio.get_event_loop()
    if _LOOP.is_closed():
        raise RuntimeError("closed")
except RuntimeError:
    _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _iso_date(days_delta: int = 0) -> str:
    return (_dt.date.today() + _dt.timedelta(days=days_delta)).isoformat()


def _iso_ts(days_delta: int = 0) -> str:
    return (_dt.datetime.utcnow() + _dt.timedelta(days=days_delta)).isoformat() + "Z"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def coach_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": COACH_EMAIL, "password": COACH_PWD}, timeout=20)
    assert r.status_code == 200, f"coach login failed: {r.text}"
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture(scope="module")
def coach_user(coach_token):
    r = requests.get(f"{API}/auth/me", headers=_auth(coach_token), timeout=20)
    assert r.status_code == 200
    return r.json()


async def _seed_v2_exercises() -> list[str]:
    from server import db
    ex_ids = []
    seeds = [
        {"exercise_name": "Back Squat", "movement_pattern": "squat", "equipment_type": "barbell",
         "difficulty": "intermediate", "tags": ["strength"], "body_regions": ["legs"],
         "status": "Approved"},
        {"exercise_name": "Goblet Squat", "movement_pattern": "squat", "equipment_type": "dumbbell",
         "difficulty": "beginner", "tags": ["hotel_friendly", "strength"], "body_regions": ["legs"],
         "status": "Approved"},
        {"exercise_name": "Push-up", "movement_pattern": "push", "equipment_type": "bodyweight",
         "difficulty": "beginner", "tags": ["bodyweight", "hotel_friendly", "strength"],
         "body_regions": ["chest"], "status": "Approved"},
        {"exercise_name": "Cat Cow", "movement_pattern": "flexion", "equipment_type": "bodyweight",
         "difficulty": "beginner", "tags": ["mobility", "bodyweight", "hotel_friendly"],
         "body_regions": ["spine"], "status": "Live"},
        {"exercise_name": "Draft Deadlift", "movement_pattern": "hinge", "equipment_type": "barbell",
         "difficulty": "advanced", "tags": ["strength"], "body_regions": ["posterior"],
         "status": "Draft"},  # NOT approved — should never appear
    ]
    for i, s in enumerate(seeds):
        eid = f"{TEST_TAG}_ex_{i}"
        await db.exercises_v2.insert_one({
            "id": eid, "coaching_notes": "Cue: brace core. Neutral spine.",
            "created_at": _iso_ts(-30), **s,
        })
        ex_ids.append(eid)
    return ex_ids


async def _seed_client_with_workout() -> tuple[str, str, str, str]:
    """Seed client with active roster + programme + one editable upcoming workout.
    Returns (client_id, roster_id, programme_id, workout_id)."""
    from server import db
    cid = f"{TEST_TAG}_u_{uuid.uuid4().hex[:6]}"
    rid = f"{TEST_TAG}_r_{uuid.uuid4().hex[:6]}"
    pid = f"{TEST_TAG}_p_{uuid.uuid4().hex[:6]}"
    wid = f"{TEST_TAG}_w_{uuid.uuid4().hex[:6]}"

    await db.users.insert_one({
        "id": cid, "email": f"{cid}@crewfit-test.com", "name": "Iter79 Test",
        "role": "client", "created_at": _iso_ts(-30),
        "onboarded_at": _iso_ts(-28),
        "profile": {"main_goal_key": "event", "event_type_pref": "marathon", "training_days_per_week": 4},
    })
    await db.rosters.insert_one({
        "id": rid, "user_id": cid, "version": 1, "is_active": True,
        "status": "confirmed", "created_at": _iso_ts(-20),
        "week_start": _iso_date(-20), "week_end": _iso_date(-14),
    })
    await db.programmes.insert_one({
        "id": pid, "user_id": cid, "version_number": 1,
        "goal_key": "event_marathon", "goal_label": "Marathon",
        "phase": {"key": "base", "label": "Base"}, "target_sessions_per_week": 4,
        "validation_status": "ok", "coach_edited": False,
        "created_at": _iso_ts(-19),
    })
    # Editable upcoming workout with 5 exercises (so shorter drops last + still >=4)
    await db.workouts.insert_one({
        "id": wid, "user_id": cid, "roster_id": rid,
        "date": _iso_date(3),
        "title": "Full Body Strength", "focus": "strength",
        "duration_min": 45, "day_load": "green",
        "completed": False, "coach_locked": False,
        "exercises": [
            {"exercise_id": f"{TEST_TAG}_ex_0", "name": "Back Squat",  "sets": 4, "reps": "5-8", "rest_sec": 120, "rpe": 8},
            {"exercise_id": f"{TEST_TAG}_ex_2", "name": "Push-up",     "sets": 3, "reps": "10",  "rest_sec": 60,  "rpe": 7},
            {"exercise_id": f"{TEST_TAG}_ex_1", "name": "Goblet Squat","sets": 3, "reps": "10",  "rest_sec": 60,  "rpe": 6},
            {"exercise_id": f"{TEST_TAG}_ex_3", "name": "Cat Cow",     "sets": 2, "reps": "10",  "rest_sec": 30,  "rpe": 4},
            {"exercise_id": f"{TEST_TAG}_ex_0", "name": "Accessory",   "sets": 3, "reps": "12",  "rest_sec": 45,  "rpe": 6},
        ],
        "created_at": _iso_ts(-3),
        "source": "template",
    })
    # A completed workout (for read-only test)
    await db.workouts.insert_one({
        "id": f"{wid}_done", "user_id": cid, "roster_id": rid,
        "date": _iso_date(-2), "title": "Done", "focus": "endurance",
        "completed": True, "completed_at": _iso_ts(-2),
        "duration_min": 30, "exercises": [],
    })
    return cid, rid, pid, wid


async def _cleanup(cid: str, ex_ids: list[str] | None = None):
    from server import db
    await db.users.delete_many({"id": cid})
    await db.rosters.delete_many({"user_id": cid})
    await db.programmes.delete_many({"user_id": cid})
    await db.workouts.delete_many({"user_id": cid})
    await db.change_log.delete_many({"client_id": cid})
    await db.gen_jobs.delete_many({"user_id": cid})
    if ex_ids:
        await db.exercises_v2.delete_many({"id": {"$in": ex_ids}})


@pytest.fixture(scope="module")
def seeded():
    ex_ids = _run(_seed_v2_exercises())
    cid, rid, pid, wid = _run(_seed_client_with_workout())
    yield {"client_id": cid, "roster_id": rid, "programme_id": pid, "workout_id": wid, "ex_ids": ex_ids}
    _run(_cleanup(cid, ex_ids))


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PWD}, timeout=20)
    if r.status_code == 200:
        d = r.json()
        return d.get("access_token") or d.get("token")
    return None


# =====================================================================
# T1 — Workout meta PATCH
# =====================================================================

class TestT1WorkoutMeta:
    def test_patch_updates_and_flags(self, coach_token, coach_user, seeded):
        wid = seeded["workout_id"]
        r = requests.patch(
            f"{API}/coach/workouts/{wid}",
            headers=_auth(coach_token),
            json={"title": "New title", "duration_min": 35, "rationale": "Test rationale"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert set(body["updated_fields"]) == {"title", "duration_min", "rationale"}

        # Verify persistence via direct DB
        async def _check():
            from server import db
            w = await db.workouts.find_one({"id": wid}, {"_id": 0})
            return w
        w = _run(_check())
        assert w["title"] == "New title"
        assert w["duration_min"] == 35
        assert w["rationale"] == "Test rationale"
        assert w["coach_edited"] is True
        assert w["edited_by"] == coach_user["id"]
        assert w["needs_coach_review"] is False
        assert w["validation_status"] == "coach_approved"

        # change_log entry
        async def _log_count():
            from server import db
            return await db.change_log.count_documents({
                "client_id": seeded["client_id"], "category": "workout", "kind": "edit",
            })
        n = _run(_log_count())
        assert n >= 1

    def test_patch_completed_workout_400(self, coach_token, seeded):
        done_id = f"{seeded['workout_id']}_done"
        r = requests.patch(
            f"{API}/coach/workouts/{done_id}",
            headers=_auth(coach_token),
            json={"title": "should reject"},
            timeout=20,
        )
        assert r.status_code == 400, r.text


# =====================================================================
# T2 — Exercise CRUD
# =====================================================================

class TestT2ExerciseCRUD:
    def test_add_valid_and_bogus(self, coach_token, seeded):
        wid = seeded["workout_id"]
        # bogus id → 404
        r = requests.post(
            f"{API}/coach/workouts/{wid}/exercises/add",
            headers=_auth(coach_token),
            json={"exercise_id": "does-not-exist"}, timeout=20,
        )
        assert r.status_code == 404

        # valid — Goblet Squat
        r = requests.post(
            f"{API}/coach/workouts/{wid}/exercises/add",
            headers=_auth(coach_token),
            json={"exercise_id": seeded["ex_ids"][1], "sets": 4, "reps": "12"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["exercises_count"] == 6  # was 5 → +1

    def test_edit_exercise(self, coach_token, seeded):
        wid = seeded["workout_id"]
        r = requests.patch(
            f"{API}/coach/workouts/{wid}/exercises/1",
            headers=_auth(coach_token),
            json={"sets": 5, "rpe": 8.5}, timeout=20,
        )
        assert r.status_code == 200, r.text
        ex = r.json()["exercise"]
        assert ex["sets"] == 5
        assert ex["rpe"] == 8.5

    def test_edit_exercise_out_of_range(self, coach_token, seeded):
        wid = seeded["workout_id"]
        r = requests.patch(
            f"{API}/coach/workouts/{wid}/exercises/999",
            headers=_auth(coach_token), json={"sets": 3}, timeout=20,
        )
        assert r.status_code == 404

    def test_delete_exercise(self, coach_token, seeded):
        wid = seeded["workout_id"]
        # After add+edit above → 6 exercises. delete idx=0 → 5.
        r = requests.delete(
            f"{API}/coach/workouts/{wid}/exercises/0",
            headers=_auth(coach_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["exercises_count"] == 5

    def test_reorder_valid_and_invalid(self, coach_token, seeded):
        wid = seeded["workout_id"]

        async def _len():
            from server import db
            w = await db.workouts.find_one({"id": wid}, {"_id": 0, "exercises": 1})
            return len(w.get("exercises") or [])
        n = _run(_len())
        assert n == 5

        # valid permutation
        order = list(range(n))[::-1]
        r = requests.post(
            f"{API}/coach/workouts/{wid}/exercises/reorder",
            headers=_auth(coach_token), json={"order": order}, timeout=20,
        )
        assert r.status_code == 200, r.text

        # invalid (duplicates)
        r = requests.post(
            f"{API}/coach/workouts/{wid}/exercises/reorder",
            headers=_auth(coach_token), json={"order": [0, 0, 0, 0, 0]}, timeout=20,
        )
        assert r.status_code == 400


# =====================================================================
# T3 — Exercise swap
# =====================================================================

class TestT3ExerciseSwap:
    def test_swap_preserves_prescription(self, coach_token, seeded):
        wid = seeded["workout_id"]

        # capture prescription at idx=0
        async def _get():
            from server import db
            w = await db.workouts.find_one({"id": wid}, {"_id": 0, "exercises": 1})
            return w["exercises"][0]
        original = _run(_get())

        # swap with Push-up (ex_2)
        r = requests.post(
            f"{API}/coach/workouts/{wid}/exercises/0/swap",
            headers=_auth(coach_token),
            json={"replacement_exercise_id": seeded["ex_ids"][2], "preserve_prescription": True, "reason": "no barbell"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        new_ex = r.json()["exercise"]
        assert new_ex["name"] == "Push-up"
        assert new_ex["sets"] == original.get("sets")
        assert new_ex["reps"] == original.get("reps")
        assert new_ex["rest_sec"] == original.get("rest_sec")
        assert new_ex["rpe"] == original.get("rpe")
        assert new_ex["swapped_from"]["name"] == original.get("name")
        assert new_ex["swapped_from"]["reason"] == "no barbell"

    def test_swap_no_preserve_defaults(self, coach_token, seeded):
        wid = seeded["workout_id"]
        r = requests.post(
            f"{API}/coach/workouts/{wid}/exercises/1/swap",
            headers=_auth(coach_token),
            json={"replacement_exercise_id": seeded["ex_ids"][3], "preserve_prescription": False},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        ex = r.json()["exercise"]
        assert ex["sets"] == 3
        assert ex["reps"] == "8-10"
        assert ex["rest_sec"] == 60
        assert ex["rpe"] == 7

    def test_swap_override_wins(self, coach_token, seeded):
        wid = seeded["workout_id"]
        r = requests.post(
            f"{API}/coach/workouts/{wid}/exercises/2/swap",
            headers=_auth(coach_token),
            json={
                "replacement_exercise_id": seeded["ex_ids"][1],
                "preserve_prescription": True,
                "override_sets": 5,
            },
            timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json()["exercise"]["sets"] == 5

    def test_swap_bogus_replacement_404(self, coach_token, seeded):
        r = requests.post(
            f"{API}/coach/workouts/{seeded['workout_id']}/exercises/0/swap",
            headers=_auth(coach_token),
            json={"replacement_exercise_id": "nope"}, timeout=20,
        )
        assert r.status_code == 404


# =====================================================================
# T4 — V2 search
# =====================================================================

class TestT4V2Search:
    def test_query_filter(self, coach_token, seeded):
        r = requests.get(f"{API}/exercises/v2/search?q=squat", headers=_auth(coach_token), timeout=20)
        assert r.status_code == 200
        names = [e["exercise_name"] for e in r.json()["exercises"]]
        # both Back Squat and Goblet Squat should appear (regex, case-insensitive)
        assert any("Back Squat" in n for n in names)
        assert any("Goblet Squat" in n for n in names)
        # Draft Deadlift is status=Draft → must never appear
        assert not any("Draft Deadlift" in n for n in names)

    def test_movement_filter(self, coach_token, seeded):
        r = requests.get(f"{API}/exercises/v2/search?movement=squat", headers=_auth(coach_token), timeout=20)
        assert r.status_code == 200
        rows = r.json()["exercises"]
        # Every returned row must have movement_pattern == 'squat'
        for row in rows:
            if row.get("id", "").startswith(TEST_TAG):
                assert row["movement_pattern"] == "squat"

    def test_tag_intersection(self, coach_token, seeded):
        r = requests.get(
            f"{API}/exercises/v2/search?hotel_friendly=true&bodyweight=true",
            headers=_auth(coach_token), timeout=20,
        )
        assert r.status_code == 200
        rows = r.json()["exercises"]
        # Must contain Push-up and Cat Cow (both hotel_friendly + bodyweight)
        seeded_rows = [r for r in rows if r.get("id", "").startswith(TEST_TAG)]
        names = [r["exercise_name"] for r in seeded_rows]
        assert "Push-up" in names
        assert "Cat Cow" in names
        # Must NOT contain Back Squat (only strength) or Goblet Squat (no bodyweight tag)
        assert "Back Squat" not in names
        assert "Goblet Squat" not in names

    def test_draft_excluded(self, coach_token, seeded):
        r = requests.get(f"{API}/exercises/v2/search?q=Draft", headers=_auth(coach_token), timeout=20)
        assert r.status_code == 200
        names = [e["exercise_name"] for e in r.json()["exercises"]]
        assert "Draft Deadlift" not in names

    def test_limit_capped(self, coach_token, seeded):
        r = requests.get(f"{API}/exercises/v2/search?limit=500", headers=_auth(coach_token), timeout=20)
        assert r.status_code == 200
        assert r.json()["count"] <= 100


# =====================================================================
# T5 — C6 regenerate-preview
# =====================================================================

class TestT5WorkoutRegenPreview:
    def test_preset_shorter(self, coach_token, seeded):
        wid = seeded["workout_id"]
        # First get current state (may have been edited by earlier tests)
        async def _get():
            from server import db
            return await db.workouts.find_one({"id": wid}, {"_id": 0})
        w = _run(_get())
        original_dur = w["duration_min"]
        r = requests.post(
            f"{API}/coach/workouts/{wid}/regenerate-preview",
            headers=_auth(coach_token), json={"preset": "shorter"}, timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["preset"] == "shorter"
        # duration approx 65%
        expected = max(15, int(original_dur * 0.65))
        assert d["preview"]["duration_min"] == expected
        # exercises count reduced by 1 if >=5
        assert len(d["preview"]["exercises"]) == max(0, len(w.get("exercises") or []) - 1)

    def test_preset_easier_floors_rpe(self, coach_token, seeded):
        r = requests.post(
            f"{API}/coach/workouts/{seeded['workout_id']}/regenerate-preview",
            headers=_auth(coach_token), json={"preset": "easier"}, timeout=20,
        )
        assert r.status_code == 200
        for ex in r.json()["preview"]["exercises"]:
            if isinstance(ex.get("rpe"), (int, float)):
                assert ex["rpe"] >= 4

    def test_preset_harder_caps_sets(self, coach_token, seeded):
        r = requests.post(
            f"{API}/coach/workouts/{seeded['workout_id']}/regenerate-preview",
            headers=_auth(coach_token), json={"preset": "harder"}, timeout=20,
        )
        assert r.status_code == 200
        for ex in r.json()["preview"]["exercises"]:
            if isinstance(ex.get("sets"), int):
                assert ex["sets"] <= 6

    def test_preset_tired(self, coach_token, seeded):
        r = requests.post(
            f"{API}/coach/workouts/{seeded['workout_id']}/regenerate-preview",
            headers=_auth(coach_token), json={"preset": "tired"}, timeout=20,
        )
        assert r.status_code == 200
        p = r.json()["preview"]
        assert p["title"] == "Recovery + Mobility"
        assert p["duration_min"] == 20
        assert p["focus"] == "mobility"
        assert p["day_load"] == "amber"

    def test_preset_as_running(self, coach_token, seeded):
        r = requests.post(
            f"{API}/coach/workouts/{seeded['workout_id']}/regenerate-preview",
            headers=_auth(coach_token), json={"preset": "as_running"}, timeout=20,
        )
        assert r.status_code == 200
        p = r.json()["preview"]
        assert p["title"] == "Easy Run"
        assert p["focus"] == "long_run"
        assert p["duration_min"] == 40

    def test_preset_unknown_400(self, coach_token, seeded):
        r = requests.post(
            f"{API}/coach/workouts/{seeded['workout_id']}/regenerate-preview",
            headers=_auth(coach_token), json={"preset": "nope"}, timeout=20,
        )
        assert r.status_code == 400


# =====================================================================
# T6 — C7 programme regenerate-preview
# =====================================================================

class TestT6ProgrammeRegenPreview:
    def test_preview_shape(self, coach_token, seeded):
        cid = seeded["client_id"]
        r = requests.post(
            f"{API}/coach/clients/{cid}/programme/regenerate-preview",
            headers=_auth(coach_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        for k in (
            "ok", "client", "roster_id", "current_programme_id",
            "old_summary", "new_summary", "would_change", "would_keep",
            "preserved", "first_new_workout_date",
            "target_sessions_per_week", "goal_key",
        ):
            assert k in d, f"missing {k}"
        assert d["client"]["id"] == cid
        assert d["roster_id"] == seeded["roster_id"]
        # old_summary excludes completed & deactivated
        assert "total_workouts" in d["old_summary"]
        # preserved counts should be a dict with keys
        assert "completed_workouts" in d["preserved"]
        assert "coach_locked_workouts" in d["preserved"]

    def test_preview_no_active_roster_400(self, coach_token):
        # Fresh client with no roster
        async def _mk():
            from server import db
            uid = f"{TEST_TAG}_noroster_{uuid.uuid4().hex[:6]}"
            await db.users.insert_one({
                "id": uid, "email": f"{uid}@crewfit-test.com",
                "name": "NR", "role": "client", "created_at": _iso_ts(-1),
            })
            return uid
        uid = _run(_mk())
        try:
            r = requests.post(
                f"{API}/coach/clients/{uid}/programme/regenerate-preview",
                headers=_auth(coach_token), timeout=20,
            )
            assert r.status_code == 400
        finally:
            _run(_cleanup(uid))


# =====================================================================
# T7 — C7 programme regenerate-apply
# =====================================================================

class TestT7ProgrammeRegenApply:
    def test_apply_queues_job(self, coach_token, coach_user, seeded):
        cid = seeded["client_id"]
        r = requests.post(
            f"{API}/coach/clients/{cid}/programme/regenerate-apply",
            headers=_auth(coach_token),
            json={"preserve_coach_locked": True, "preserve_completed": True, "reason": "test"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d.get("job_id")
        job_id = d["job_id"]

        # verify gen_jobs row
        async def _get_job():
            from server import db
            return await db.gen_jobs.find_one({"id": job_id}, {"_id": 0})
        job = _run(_get_job())
        assert job is not None
        assert job["status"] == "queued"
        assert job["kind"] == "programme_regenerate"
        assert job["user_id"] == cid
        assert job["roster_id"] == seeded["roster_id"]
        assert job["requested_by_coach"] == coach_user["id"]
        assert job["reason"] == "test"
        assert job["regen_flags"]["preserve_coach_locked"] is True
        assert job["regen_flags"]["preserve_completed"] is True

        # change_log entry
        async def _get_log():
            from server import db
            return await db.change_log.count_documents({
                "client_id": cid, "category": "programme", "kind": "regenerate",
            })
        assert _run(_get_log()) >= 1

    def test_apply_no_active_roster_400(self, coach_token):
        async def _mk():
            from server import db
            uid = f"{TEST_TAG}_apply_nr_{uuid.uuid4().hex[:6]}"
            await db.users.insert_one({
                "id": uid, "email": f"{uid}@crewfit-test.com",
                "name": "NR2", "role": "client", "created_at": _iso_ts(-1),
            })
            return uid
        uid = _run(_mk())
        try:
            r = requests.post(
                f"{API}/coach/clients/{uid}/programme/regenerate-apply",
                headers=_auth(coach_token), json={"reason": "x"}, timeout=20,
            )
            assert r.status_code == 400
        finally:
            _run(_cleanup(uid))


# =====================================================================
# T8 — Regression smoke
# =====================================================================

class TestT8RegressionSmoke:
    def test_coach_dashboard(self, coach_token):
        r = requests.get(f"{API}/coach/dashboard", headers=_auth(coach_token), timeout=30)
        assert r.status_code == 200

    def test_coach_roster_alerts(self, coach_token):
        r = requests.get(f"{API}/coach/roster-alerts", headers=_auth(coach_token), timeout=20)
        assert r.status_code == 200

    def test_programme_overview_still_healthy(self, coach_token, seeded):
        r = requests.get(
            f"{API}/coach/clients/{seeded['client_id']}/programme-overview",
            headers=_auth(coach_token), timeout=30,
        )
        assert r.status_code == 200

    def test_programme_timeline_still_healthy(self, coach_token, seeded):
        r = requests.get(
            f"{API}/coach/clients/{seeded['client_id']}/programme-timeline?limit=20",
            headers=_auth(coach_token), timeout=30,
        )
        assert r.status_code == 200
