"""
Iteration 62 — Traffic Light Workout Variants (Green / Amber / Red)

Tests:
1. /workouts/{wid}/variants — legacy backfill returns fully populated variants,
   persists variants_source='derived', second call idempotent.
   Requires auth (401 unauthorised).
2. Amber shape rules: fewer sets, duration <= 0.75 * green.duration,
   >=5 green exercises → amber has one fewer, reps ranges preserved as ranges.
3. Red context awareness — long_haul, layover, night_flight, standby templates
   picked based on the roster day (via seeded rosters).
4. /select-variant — happy path (amber), 400 invalid variant, 403 wrong client.
5. Regression — /workouts/{wid} still returns base fields required by frontend.
"""
from __future__ import annotations

import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone

import pytest
import requests

# Import server modules so we can seed DB directly (mirrors iter61 pattern)
sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(email: str, password: str):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    d = r.json()
    return d["token"], d["user"]


@pytest.fixture(scope="module")
def client_auth():
    token, user = _login("client@crewfit.com", "Client123!")
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture(scope="module")
def coach_auth():
    token, user = _login("coach@crewfit.com", "Coach123!")
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(scope="module")
def db():
    """Direct pymongo handle for seeding (no ObjectId returned since we assign our own ids)."""
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")
    # load backend/.env
    try:
        with open("/app/backend/.env") as fh:
            for line in fh:
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.strip().partition("=")
                    v = v.strip().strip('"').strip("'")
                    if k == "MONGO_URL":
                        mongo_url = v
                    if k == "DB_NAME":
                        db_name = v
    except Exception:
        pass
    return MongoClient(mongo_url)[db_name]


_DATE_COUNTER = {"n": 0}


def _next_date():
    _DATE_COUNTER["n"] += 1
    # Use year 2099 and sequential month/day to avoid unique index collisions
    n = _DATE_COUNTER["n"]
    month = 6 + (n // 28)
    day = (n % 28) + 1
    return f"2099-{month:02d}-{day:02d}"


def _seed_workout(db, client_user, *, date=None, roster_id=None, variants=None, exercises=None):
    wid = f"TEST_wo_{uuid.uuid4().hex[:8]}"
    date = date or _next_date()
    exercises = exercises if exercises is not None else [
        {"name": "Back Squat", "sets": 4, "reps": "8-10", "rest_sec": 90, "rpe": 8},
        {"name": "Bench Press", "sets": 4, "reps": "8", "rest_sec": 90, "rpe": 8},
        {"name": "Bent-over Row", "sets": 3, "reps": "10-12", "rest_sec": 75, "rpe": 7},
        {"name": "Overhead Press", "sets": 3, "reps": "8-10", "rest_sec": 75, "rpe": 7},
        {"name": "Bicep Curl", "sets": 3, "reps": "12", "rest_sec": 60, "rpe": 6},
        {"name": "Tricep Pushdown", "sets": 3, "reps": "12-15", "rest_sec": 60, "rpe": 6},
    ]
    doc = {
        "id": wid,
        "user_id": client_user["id"],
        "date": date,
        "title": "Full Body Strength",
        "duration_min": 60,
        "focus": "strength",
        "warmup": [{"name": "Bike", "duration_sec": 300}],
        "exercises": exercises,
        "rationale": "Base strength stimulus.",
        "day_load": "green",
        "approved": True,
        "completed": False,
        "variants": variants if variants is not None else {"green": None, "amber": None, "red": None},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    if roster_id:
        doc["roster_id"] = roster_id
    db.workouts.insert_one(doc)
    return wid


def _seed_roster(db, client_user, *, day_type, date, flights=None):
    rid = f"TEST_ro_{uuid.uuid4().hex[:8]}"
    doc = {
        "id": rid,
        "user_id": client_user["id"],
        "coach_id": client_user.get("coach_id"),
        "source_filename": "TEST_iter62_seed.pdf",
        "active": False,  # do not disturb real active roster
        "days": [{"date": date, "day_type": day_type, "flights": flights or []}],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    db.rosters.insert_one(doc)
    return rid


@pytest.fixture(scope="module")
def cleanup_registry():
    reg = {"workouts": [], "rosters": []}
    yield reg
    # teardown handled by finalizer in each fixture that adds


@pytest.fixture(autouse=True, scope="module")
def _cleanup_at_end(db, cleanup_registry):
    yield
    if cleanup_registry["workouts"]:
        db.workouts.delete_many({"id": {"$in": cleanup_registry["workouts"]}})
    if cleanup_registry["rosters"]:
        db.rosters.delete_many({"id": {"$in": cleanup_registry["rosters"]}})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVariantsBackfill:
    """GET /api/workouts/{wid}/variants — legacy backfill path."""

    def test_401_without_token(self, db, client_auth, cleanup_registry):
        wid = _seed_workout(db, client_auth["user"])
        cleanup_registry["workouts"].append(wid)
        r = requests.get(f"{BASE_URL}/api/workouts/{wid}/variants", timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 without token, got {r.status_code}"

    def test_backfill_populates_and_persists(self, db, client_auth, cleanup_registry):
        wid = _seed_workout(db, client_auth["user"])
        cleanup_registry["workouts"].append(wid)
        r = requests.get(f"{BASE_URL}/api/workouts/{wid}/variants", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["workout_id"] == wid
        v = body["variants"]
        for k in ("green", "amber", "red"):
            assert isinstance(v.get(k), dict), f"variant {k} missing/not dict"
            for f in ("title", "duration_min", "focus", "exercises", "rationale", "intensity_note"):
                assert f in v[k], f"variant {k} missing field {f}"

        # DB was persisted with variants_source='derived'
        doc = db.workouts.find_one({"id": wid})
        assert doc.get("variants_source") == "derived"
        assert isinstance(doc.get("variants", {}).get("green"), dict)

        # Idempotent — second call returns same green title, still 'derived'
        r2 = requests.get(f"{BASE_URL}/api/workouts/{wid}/variants", headers=client_auth["headers"], timeout=30)
        assert r2.status_code == 200
        v2 = r2.json()["variants"]
        assert v2["green"]["title"] == v["green"]["title"]
        assert v2["amber"]["title"] == v["amber"]["title"]
        doc2 = db.workouts.find_one({"id": wid})
        assert doc2.get("variants_source") == "derived"


class TestAmberShape:
    def test_amber_scaling(self, db, client_auth, cleanup_registry):
        wid = _seed_workout(db, client_auth["user"])  # 6 exercises with reps ranges
        cleanup_registry["workouts"].append(wid)
        r = requests.get(f"{BASE_URL}/api/workouts/{wid}/variants", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        v = r.json()["variants"]
        green, amber = v["green"], v["amber"]

        # Duration check: amber <= 0.75 * green
        assert amber["duration_min"] <= int(green["duration_min"]) * 0.75 + 0.01, \
            f"amber duration {amber['duration_min']} > 75% of green {green['duration_min']}"

        # Since green has 6 exercises (>=5), amber must have 1 fewer
        assert len(amber["exercises"]) == len(green["exercises"]) - 1, \
            f"amber exercises {len(amber['exercises'])} vs green {len(green['exercises'])}"

        # Every kept amber exercise has fewer sets than its green counterpart
        for i, aex in enumerate(amber["exercises"]):
            gex = green["exercises"][i]
            try:
                assert int(aex.get("sets") or 0) <= int(gex.get("sets") or 0), \
                    f"amber ex {i} sets {aex.get('sets')} > green {gex.get('sets')}"
                # And it should actually be reduced when green sets >= 3
                if int(gex.get("sets") or 0) >= 3:
                    assert int(aex.get("sets")) < int(gex.get("sets")), \
                        f"amber ex {i} sets not reduced ({aex.get('sets')} vs {gex.get('sets')})"
            except (TypeError, ValueError):
                pass

        # Reps that were ranges remain ranges
        for i, aex in enumerate(amber["exercises"]):
            gex = green["exercises"][i]
            greps = str(gex.get("reps") or "")
            areps = str(aex.get("reps") or "")
            if "-" in greps:
                assert "-" in areps, f"amber ex {i} lost range (green '{greps}' → amber '{areps}')"

    def test_amber_short_session_keeps_all_exercises(self, db, client_auth, cleanup_registry):
        # Only 3 exercises → amber must NOT cull
        exs = [
            {"name": "Squat", "sets": 4, "reps": "8-10", "rest_sec": 90, "rpe": 8},
            {"name": "Push-up", "sets": 3, "reps": "10", "rest_sec": 60, "rpe": 7},
            {"name": "Row", "sets": 3, "reps": "10-12", "rest_sec": 60, "rpe": 7},
        ]
        wid = _seed_workout(db, client_auth["user"], exercises=exs)
        cleanup_registry["workouts"].append(wid)
        r = requests.get(f"{BASE_URL}/api/workouts/{wid}/variants", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        v = r.json()["variants"]
        assert len(v["amber"]["exercises"]) == 3


class TestRedContext:
    def _get_red(self, wid, headers):
        r = requests.get(f"{BASE_URL}/api/workouts/{wid}/variants", headers=headers, timeout=30)
        assert r.status_code == 200
        return r.json()["variants"]["red"]

    def test_red_layover(self, db, client_auth, cleanup_registry):
        date = "2099-06-11"
        rid = _seed_roster(db, client_auth["user"], day_type="Layover", date=date)
        cleanup_registry["rosters"].append(rid)
        wid = _seed_workout(db, client_auth["user"], date=date, roster_id=rid)
        cleanup_registry["workouts"].append(wid)
        red = self._get_red(wid, client_auth["headers"])
        assert red.get("focus") == "recovery"
        assert red.get("context_tag") == "layover", f"expected layover, got {red.get('context_tag')}"
        assert "Layover" in red.get("title", "")

    def test_red_long_haul(self, db, client_auth, cleanup_registry):
        date = "2099-06-12"
        rid = _seed_roster(
            db, client_auth["user"], day_type="Flight", date=date,
            flights=[{"flight_time_hours": 9.5, "night_flight": False}],
        )
        cleanup_registry["rosters"].append(rid)
        wid = _seed_workout(db, client_auth["user"], date=date, roster_id=rid)
        cleanup_registry["workouts"].append(wid)
        red = self._get_red(wid, client_auth["headers"])
        assert red.get("context_tag") == "long_haul", f"expected long_haul, got {red.get('context_tag')}"
        assert "Post-flight" in red.get("title", "") or "Recovery" in red.get("title", "")

    def test_red_standby(self, db, client_auth, cleanup_registry):
        date = "2099-06-13"
        rid = _seed_roster(db, client_auth["user"], day_type="Standby", date=date)
        cleanup_registry["rosters"].append(rid)
        wid = _seed_workout(db, client_auth["user"], date=date, roster_id=rid)
        cleanup_registry["workouts"].append(wid)
        red = self._get_red(wid, client_auth["headers"])
        assert red.get("context_tag") == "standby", f"expected standby, got {red.get('context_tag')}"

    def test_red_night_flight(self, db, client_auth, cleanup_registry):
        date = "2099-06-14"
        rid = _seed_roster(
            db, client_auth["user"], day_type="Night Flight", date=date,
            flights=[{"flight_time_hours": 3.0, "night_flight": True}],
        )
        cleanup_registry["rosters"].append(rid)
        wid = _seed_workout(db, client_auth["user"], date=date, roster_id=rid)
        cleanup_registry["workouts"].append(wid)
        red = self._get_red(wid, client_auth["headers"])
        assert red.get("context_tag") == "night_flight", f"expected night_flight, got {red.get('context_tag')}"

    def test_red_default_when_no_roster(self, db, client_auth, cleanup_registry):
        wid = _seed_workout(db, client_auth["user"], date="2099-06-15")
        cleanup_registry["workouts"].append(wid)
        red = self._get_red(wid, client_auth["headers"])
        assert red.get("context_tag") == "default", f"expected default, got {red.get('context_tag')}"


class TestSelectVariant:
    def test_select_amber_success(self, db, client_auth, cleanup_registry):
        wid = _seed_workout(db, client_auth["user"])
        cleanup_registry["workouts"].append(wid)
        r = requests.post(
            f"{BASE_URL}/api/workouts/{wid}/select-variant",
            headers=client_auth["headers"], json={"variant": "amber"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"ok": True, "variant": "amber"} or (body.get("ok") is True and body.get("variant") == "amber")
        # Persisted
        doc = db.workouts.find_one({"id": wid})
        assert doc.get("selected_variant") == "amber"
        assert doc.get("selected_variant_at") is not None

    def test_select_invalid_variant_400(self, db, client_auth, cleanup_registry):
        wid = _seed_workout(db, client_auth["user"])
        cleanup_registry["workouts"].append(wid)
        r = requests.post(
            f"{BASE_URL}/api/workouts/{wid}/select-variant",
            headers=client_auth["headers"], json={"variant": "blue"}, timeout=15,
        )
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"

    def test_select_wrong_client_403(self, db, client_auth, cleanup_registry):
        # Seed a workout owned by a different fake user id
        fake_user = {"id": "TEST_fake_user_" + uuid.uuid4().hex[:6], "coach_id": None}
        wid = _seed_workout(db, fake_user)
        cleanup_registry["workouts"].append(wid)
        r = requests.post(
            f"{BASE_URL}/api/workouts/{wid}/select-variant",
            headers=client_auth["headers"], json={"variant": "amber"}, timeout=15,
        )
        assert r.status_code == 403, f"expected 403 got {r.status_code} {r.text}"


class TestRegression:
    def test_get_workout_still_returns_base_fields(self, db, client_auth, cleanup_registry):
        wid = _seed_workout(db, client_auth["user"])
        cleanup_registry["workouts"].append(wid)
        r = requests.get(f"{BASE_URL}/api/workouts/{wid}", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        w = r.json()
        for f in ("title", "exercises", "warmup", "rationale", "duration_min", "focus"):
            assert f in w, f"workout GET missing field {f}"
        assert isinstance(w["exercises"], list) and len(w["exercises"]) > 0

    def test_variants_endpoint_404_for_missing(self, client_auth):
        r = requests.get(
            f"{BASE_URL}/api/workouts/NOPE_DOES_NOT_EXIST/variants",
            headers=client_auth["headers"], timeout=15,
        )
        assert r.status_code == 404
