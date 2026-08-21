"""Iter189g · Alternatives Redesign — Backend regression tests.

Covers:
  1. GET /api/exercises/alternatives?name=... — new purpose-tagged shape,
     legacy list, empty state, and catalog match branches. Max 3 items.
  2. POST /api/exercise-content/{ex_id}/generate-content (kind=alternatives)
     — writes both `alternatives` and `alternatives_meta` and returns
     `alternative_exercise_ids`.
  3. POST /api/workouts/{id}/swap-exercise — smoke test only, unchanged
     behaviour.
"""

import os
import pytest
import requests
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or "https://flight-fit-plans.preview.emergentagent.com"
API = f"{BASE_URL}/api"

COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"

# ---------------------------------------------------------------- helpers ----

@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": COACH_EMAIL, "password": COACH_PASSWORD
    }, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def coach_headers(coach_token):
    return {"Authorization": f"Bearer {coach_token}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mongo_db():
    # Use the same env the backend uses.
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    return client[db_name]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ------------------------------------------------------------- Test 1: GET ----

class TestExerciseAlternativesEndpoint:
    """GET /api/exercises/alternatives — Iter189g contract."""

    def test_1a_alternatives_meta_dedup_and_cap(self, coach_headers, mongo_db):
        """Row with alternatives_meta (4 entries, 1 invalid purpose, 1 duplicate)
        → exactly 3 items, valid purposes only, purpose_label populated."""
        # Pick an Approved exercise to seed. Prefer Push-Up.
        ex = _run(mongo_db.exercises_v2.find_one(
            {"exercise_name": {"$regex": "^Push-?Up$", "$options": "i"},
             "status": "Approved"},
            {"_id": 0, "id": 1, "exercise_name": 1,
             "alternatives": 1, "alternatives_meta": 1},
        ))
        if not ex:
            ex = _run(mongo_db.exercises_v2.find_one(
                {"status": "Approved"},
                {"_id": 0, "id": 1, "exercise_name": 1,
                 "alternatives": 1, "alternatives_meta": 1},
            ))
        assert ex, "No Approved exercise found to seed with"

        original_meta = ex.get("alternatives_meta")
        original_alts = ex.get("alternatives")

        seed_meta = [
            {"name": "TEST_Band Chest Press", "purpose": "equipment_swap",
             "why": "Same push pattern with a band."},
            {"name": "TEST_Knee Push-Up", "purpose": "easier_regression",
             "why": "Reduces load for fresh trainees."},
            # duplicate purpose — must be dropped
            {"name": "TEST_Wall Push-Up", "purpose": "easier_regression",
             "why": "Even easier — should be filtered as duplicate."},
            # invalid purpose — must be dropped
            {"name": "TEST_Bogus", "purpose": "unknown_purpose",
             "why": "Should be filtered out."},
            # valid third — injury-friendly
            {"name": "TEST_Incline Push-Up", "purpose": "injury_mobility_friendly",
             "why": "Safer variant for shoulder issues."},
        ]
        try:
            _run(mongo_db.exercises_v2.update_one(
                {"id": ex["id"]}, {"$set": {"alternatives_meta": seed_meta}}
            ))
            r = requests.get(
                f"{API}/exercises/alternatives",
                params={"name": ex["exercise_name"]},
                headers=coach_headers, timeout=30,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["source"] == "v2_library"
            alts = data["alternatives"]
            assert len(alts) == 3, f"expected exactly 3, got {len(alts)}: {alts}"

            purposes = [a["purpose"] for a in alts]
            assert len(set(purposes)) == 3, f"purposes not unique: {purposes}"
            for a in alts:
                assert a["purpose"] in ("equipment_swap", "easier_regression",
                                        "injury_mobility_friendly"), a
                assert a.get("purpose_label"), a
                assert a.get("name")
                assert a.get("why")
            names = [a["name"] for a in alts]
            assert "TEST_Bogus" not in names
            assert "TEST_Wall Push-Up" not in names  # dup dropped
        finally:
            # Restore
            set_doc = {}
            unset_doc = {}
            if original_meta is None:
                unset_doc["alternatives_meta"] = ""
            else:
                set_doc["alternatives_meta"] = original_meta
            update = {}
            if set_doc:
                update["$set"] = set_doc
            if unset_doc:
                update["$unset"] = unset_doc
            _run(mongo_db.exercises_v2.update_one({"id": ex["id"]}, update))

    def test_1b_legacy_flat_alternatives_capped_at_3(self, coach_headers, mongo_db):
        """Row with legacy `alternatives` list of 5 strings → capped at 3,
        no purpose labels."""
        # Find an Approved exercise WITHOUT alternatives_meta to keep the code
        # path clean, or clear meta while testing.
        ex = _run(mongo_db.exercises_v2.find_one(
            {"status": "Approved",
             "$or": [{"alternatives_meta": {"$exists": False}},
                     {"alternatives_meta": []}]},
            {"_id": 0, "id": 1, "exercise_name": 1,
             "alternatives": 1, "alternatives_meta": 1},
        ))
        assert ex, "No approved exercise without alternatives_meta found"

        original_alts = ex.get("alternatives")
        seed_alts = ["TEST_Alt A", "TEST_Alt B", "TEST_Alt C",
                     "TEST_Alt D", "TEST_Alt E"]
        try:
            _run(mongo_db.exercises_v2.update_one(
                {"id": ex["id"]},
                {"$set": {"alternatives": seed_alts},
                 "$unset": {"alternatives_meta": ""}},
            ))
            r = requests.get(
                f"{API}/exercises/alternatives",
                params={"name": ex["exercise_name"]},
                headers=coach_headers, timeout=30,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["source"] == "v2_library"
            alts = data["alternatives"]
            assert len(alts) == 3, f"expected 3, got {len(alts)}"
            for a in alts:
                assert a.get("purpose") in (None, ""), f"legacy should have no purpose: {a}"
                assert a.get("purpose_label") in (None, ""), f"legacy should have no purpose_label: {a}"
                assert a["name"].startswith("TEST_Alt")
        finally:
            set_doc = {}
            unset_doc = {}
            if original_alts is None:
                unset_doc["alternatives"] = ""
            else:
                set_doc["alternatives"] = original_alts
            update = {}
            if set_doc:
                update["$set"] = set_doc
            if unset_doc:
                update["$unset"] = unset_doc
            _run(mongo_db.exercises_v2.update_one({"id": ex["id"]}, update))

    def test_1c_no_library_no_catalog_returns_empty(self, coach_headers):
        """Unknown exercise not in library and not matching ALT_CATALOG
        (no substring: squat/deadlift/bench/row/press/pull_up/lunge/plank/
        chin/pullup/overhead/shoulder) → empty list."""
        r = requests.get(
            f"{API}/exercises/alternatives",
            params={"name": "TEST_ZZZ_Nonexistent_Move_XYZ_2026"},
            headers=coach_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["source"] == "none", data
        assert data["alternatives"] == []

    def test_1d_catalog_match_capped_at_3(self, coach_headers):
        """A name matching ALT_CATALOG (e.g., "Barbell Bench Press" → bench)
        returns capped-at-3 items, no purpose labels."""
        r = requests.get(
            f"{API}/exercises/alternatives",
            params={"name": "TEST_Barbell Bench Press__no_lib_match"},
            headers=coach_headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # We prepend TEST_ + suffix so it doesn't match a v2 library row, but
        # the catalog matcher uses substring — "bench" is present.
        assert data["source"] == "catalog", data
        alts = data["alternatives"]
        assert 1 <= len(alts) <= 3
        for a in alts:
            assert a.get("purpose") is None
            assert a.get("purpose_label") is None
            assert a.get("name")


# ------------------------------------------- Test 2: generate-content (LLM) ----

class TestGenerateAlternativesLLM:
    """POST /api/exercise-content/{ex_id}/generate-content kind=alternatives."""

    def test_generate_alternatives_writes_meta_and_backfills_ids(
        self, coach_headers, mongo_db
    ):
        # Pick an Approved exercise that does NOT already have
        # alternatives_meta, so we can observe the write cleanly.
        ex = _run(mongo_db.exercises_v2.find_one(
            {"status": "Approved",
             "$or": [{"alternatives_meta": {"$exists": False}},
                     {"alternatives_meta": []}]},
            {"_id": 0, "id": 1, "exercise_name": 1,
             "alternatives": 1, "alternatives_meta": 1,
             "alternative_exercise_ids": 1},
        ))
        if not ex:
            pytest.skip("No suitable Approved exercise without alternatives_meta")

        ex_id = ex["id"]
        original_alts = ex.get("alternatives")
        original_meta = ex.get("alternatives_meta")
        original_ids = ex.get("alternative_exercise_ids")

        r = None
        for attempt in range(2):
            r = requests.post(
                f"{API}/exercise-content/{ex_id}/generate-content",
                json={"kind": "alternatives"},
                headers=coach_headers,
                timeout=120,
            )
            if r.status_code == 200:
                break
        assert r is not None and r.status_code == 200, (
            f"generate failed after retry: {r.status_code} {r.text[:400]}"
        )
        payload = r.json()
        # `result_payload` is the whole response OR nested; the endpoint
        # returns the result_payload dict at the top level (per code).
        assert payload.get("kind") == "alternatives", payload
        assert isinstance(payload.get("items"), list), payload
        assert isinstance(payload.get("alternatives_meta"), list), payload
        assert isinstance(payload.get("alternative_exercise_ids"), list), payload
        assert len(payload["items"]) <= 3
        assert len(payload["alternatives_meta"]) <= 3
        assert len(payload["alternative_exercise_ids"]) == len(payload["items"])
        # Each meta entry must have name/purpose/why with a valid purpose.
        for m in payload["alternatives_meta"]:
            assert m.get("name")
            assert m.get("purpose") in (
                "equipment_swap", "easier_regression", "injury_mobility_friendly"
            ), m
            # `why` may be empty in edge cases but the field key must exist
            assert "why" in m

        # DB assertion — verify both fields were persisted.
        fresh = _run(mongo_db.exercises_v2.find_one(
            {"id": ex_id},
            {"_id": 0, "alternatives": 1, "alternatives_meta": 1,
             "alternative_exercise_ids": 1},
        ))
        assert fresh is not None
        assert isinstance(fresh.get("alternatives"), list)
        assert isinstance(fresh.get("alternatives_meta"), list)
        assert len(fresh["alternatives"]) == len(payload["items"])
        assert len(fresh["alternatives_meta"]) == len(payload["alternatives_meta"])
        assert fresh.get("alternative_exercise_ids") == payload["alternative_exercise_ids"]

        # Revert
        set_doc = {}
        unset_doc = {}
        for field, orig in (
            ("alternatives", original_alts),
            ("alternatives_meta", original_meta),
            ("alternative_exercise_ids", original_ids),
        ):
            if orig is None:
                unset_doc[field] = ""
            else:
                set_doc[field] = orig
        update = {}
        if set_doc:
            update["$set"] = set_doc
        if unset_doc:
            update["$unset"] = unset_doc
        if update:
            _run(mongo_db.exercises_v2.update_one({"id": ex_id}, update))


# --------------------------------------------- Test 3: swap-exercise smoke ----

class TestSwapExerciseSmoke:
    """POST /api/workouts/{id}/swap-exercise — verify unchanged behaviour.

    Uses a TEST_ workout inserted directly into db.workouts to avoid touching
    real client data. Cleans up after.
    """

    def test_swap_exercise_returns_200(self, coach_headers, coach_token, mongo_db):
        # Login as the coach's OWN user (Louis) — the swap requires client-role
        # ownership OR coach role. In the V1 branch, coach role bypasses the
        # ownership check because the code only enforces `user_id == user['id']`
        # when role == "client". So we can insert a TEST workout owned by any
        # id and call as coach.
        import uuid, datetime
        wid = f"TEST_swap_{uuid.uuid4().hex[:8]}"
        workout = {
            "id": wid,
            "user_id": "TEST_owner_dummy_id",
            "date": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "title": "TEST Swap Smoke",
            "exercises": [
                {"name": "TEST_Original Squat", "sets": 3, "reps": "8",
                 "rest_sec": 90, "rpe": 7, "order": 0, "section": "main"}
            ],
            "created_at": datetime.datetime.utcnow().isoformat(),
        }
        _run(mongo_db.workouts.insert_one(workout))
        try:
            r = requests.post(
                f"{API}/workouts/{wid}/swap-exercise",
                json={"exercise_index": 0,
                       "new_name": "TEST_Goblet Squat",
                       "reason": "smoke_test"},
                headers=coach_headers, timeout=30,
            )
            assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
            data = r.json()
            # Endpoint returns workout object — accept either shape
            # ("workout" nested or top-level "id"/"exercises").
            wk = data.get("workout") or data
            assert wk, data
            # Verify the exercise name was actually updated (via DB read).
            fresh = _run(mongo_db.workouts.find_one(
                {"id": wid}, {"_id": 0, "exercises": 1}
            ))
            assert fresh and fresh["exercises"][0]["name"] == "TEST_Goblet Squat"
        finally:
            # Cleanup TEST workout + any audit rows
            _run(mongo_db.workouts.delete_many({"id": wid}))
            _run(mongo_db.workout_exercise_swaps.delete_many({"workout_id": wid}))
            _run(mongo_db.coach_tasks.delete_many({"workout_id": wid}))
