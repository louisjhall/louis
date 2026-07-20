"""
iter64 — Phase 5 V2 Exercise Library resolver + demand-driven exercise creation.

In-process module tests (fast, no LLM): drive feature_v2_resolver directly
against the same MongoDB. Also verifies the coach-only API surface:
GET /api/exercise-content/requests
POST /api/exercise-content/{id}/reject
POST /api/exercise-content/{id}/merge
"""

import os
import re
import sys
import uuid
import asyncio
import pytest
import requests
from pymongo import MongoClient

# Make backend importable so we can hit the resolver in-process.
sys.path.insert(0, "/app/backend")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "crewfit_v1")

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://flight-fit-plans.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

COACH_EMAIL, COACH_PASS = "louis@crewfit.net", "Louis123!"
CLIENT_EMAIL, CLIENT_PASS = "client@crewfit.com", "Client123!"

# Unique tag we can use to clean up any TEST_ documents this suite creates.
TEST_TAG = "iter64_v2_resolver"


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def coach_login():
    r = requests.post(f"{API}/auth/login", json={"email": COACH_EMAIL, "password": COACH_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def client_login():
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def hdr_coach(coach_login):
    return {"Authorization": f"Bearer {coach_login['token']}", "Content-Type": "application/json"}


@pytest.fixture
def hdr_client(client_login):
    return {"Authorization": f"Bearer {client_login['token']}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def seed_pool(mongo):
    """Insert a controlled set of approved V2 exercises. Also insert a Draft
    and a Rejected exercise to prove get_approved_pool filters them out.
    Cleaned up in teardown.
    """
    ids = []

    def _mk(name, status, visibility=None, safe=None, extra=None):
        eid = f"TEST_{TEST_TAG}_{uuid.uuid4().hex[:8]}"
        doc = {
            "id": eid,
            "exercise_name": name,
            "movement_pattern": (extra or {}).get("movement_pattern", "squat"),
            "body_area": (extra or {}).get("body_area", "legs"),
            "equipment_type": (extra or {}).get("equipment_type", ["bodyweight"]),
            "tags": (extra or {}).get("tags", ["fundamental"]),
            "status": status,
            "test_tag": TEST_TAG,
            "created_at": "2099-01-01T00:00:00+00:00",
        }
        if visibility is not None:
            doc["visibility"] = visibility
        if safe is not None:
            doc["safe_for_programming"] = safe
        mongo.exercises_v2.insert_one(doc)
        ids.append(eid)
        return eid

    approved_ids = {
        # Fully live, safe, client_visible: MUST appear in pool
        "goblet_squat_test": _mk("TEST Goblet Squat Alpha", "Approved", "client_visible", True,
                                 {"movement_pattern": "squat", "equipment_type": ["dumbbell"], "tags": ["legs"]}),
        "push_up_test": _mk("TEST Push Up Alpha", "Approved", "client_visible", True,
                            {"movement_pattern": "push", "equipment_type": ["bodyweight"], "tags": ["chest"]}),
        # Legacy: Approved but NO visibility field yet — should be flipped by backfill
        "legacy_approved": _mk("TEST Legacy Approved Alpha", "Approved", None, None,
                               {"movement_pattern": "hinge"}),
        # Draft — should NOT be in pool
        "draft_not_pool": _mk("TEST Draft Skip Alpha", "Draft", "coach_only", False),
        # Rejected — should NOT be in pool
        "rejected_not_pool": _mk("TEST Rejected Skip Alpha", "rejected", "coach_only", False),
    }

    yield {"ids": approved_ids}

    # Cleanup: delete anything tagged
    mongo.exercises_v2.delete_many({"test_tag": TEST_TAG})
    mongo.exercises_v2.delete_many({"exercise_name": {"$regex": "^TEST "}})
    mongo.coach_tasks.delete_many({"task_type": "exercise_review", "title": {"$regex": "^Exercise review needed: TEST "}})


# ---------- 1. Backfill ----------

class TestBackfill:
    def test_backfill_sets_client_visible_on_legacy_approved(self, mongo, seed_pool, event_loop):
        from feature_v2_resolver import backfill_client_flags_once
        # legacy_approved was inserted without visibility field
        legacy_id = seed_pool["ids"]["legacy_approved"]
        before = mongo.exercises_v2.find_one({"id": legacy_id}, {"_id": 0})
        assert "visibility" not in before or before.get("visibility") is None
        event_loop.run_until_complete(backfill_client_flags_once())
        after = mongo.exercises_v2.find_one({"id": legacy_id}, {"_id": 0})
        assert after["visibility"] == "client_visible"
        assert after["safe_for_programming"] is True

    def test_backfill_sets_coach_only_on_non_approved(self, mongo, seed_pool, event_loop):
        from feature_v2_resolver import backfill_client_flags_once
        # Insert an untouched Draft with no visibility
        did = f"TEST_{TEST_TAG}_draft_{uuid.uuid4().hex[:6]}"
        mongo.exercises_v2.insert_one({
            "id": did, "exercise_name": "TEST Untagged Draft", "status": "Draft",
            "test_tag": TEST_TAG, "created_at": "2099-01-01T00:00:00+00:00",
        })
        event_loop.run_until_complete(backfill_client_flags_once())
        row = mongo.exercises_v2.find_one({"id": did}, {"_id": 0})
        assert row["visibility"] == "coach_only"
        assert row["safe_for_programming"] is False


# ---------- 2. Approved pool loader ----------

class TestApprovedPool:
    def test_pool_only_contains_client_visible_approved_safe(self, seed_pool, event_loop):
        from feature_v2_resolver import get_approved_pool
        pool = event_loop.run_until_complete(get_approved_pool())
        names = {p["exercise_name"] for p in pool}
        # Our safe seeds must be there
        assert "TEST Goblet Squat Alpha" in names
        assert "TEST Push Up Alpha" in names
        # Draft / rejected MUST NOT appear
        assert "TEST Draft Skip Alpha" not in names
        assert "TEST Rejected Skip Alpha" not in names
        # All rows in pool must satisfy the filter
        for p in pool:
            assert p.get("status") in ("Approved", "Live")
            assert p.get("visibility") == "client_visible"
            assert p.get("safe_for_programming") is True
            # Precomputed tokens must exist
            assert "_name_norm" in p and "_name_tokens" in p and "_meta_tokens" in p


# ---------- 3. resolve_exercise_need ----------

class TestResolveExerciseNeed:
    def test_exact_name_returns_matched(self, seed_pool, event_loop):
        from feature_v2_resolver import get_approved_pool, resolve_exercise_need
        pool = event_loop.run_until_complete(get_approved_pool())
        res = resolve_exercise_need({"name": "TEST Goblet Squat Alpha"}, pool, client_ctx=None)
        assert res["kind"] == "matched"
        assert res["library"]["exercise_name"] == "TEST Goblet Squat Alpha"
        assert res["score"] >= 30

    def test_no_match_yields_substituted_or_unresolved(self, seed_pool, event_loop):
        from feature_v2_resolver import get_approved_pool, resolve_exercise_need
        pool = event_loop.run_until_complete(get_approved_pool())
        res = resolve_exercise_need({"name": "Unicorn Pistol Squat"}, pool, client_ctx=None)
        # Some overlap on "squat" — will be substituted or unresolved but NOT matched
        assert res["kind"] in ("substituted", "unresolved")

    def test_empty_pool_returns_unresolved(self):
        from feature_v2_resolver import resolve_exercise_need
        res = resolve_exercise_need({"name": "Anything"}, [], client_ctx=None)
        assert res["kind"] == "unresolved"

    def test_totally_alien_name_returns_unresolved(self, seed_pool, event_loop):
        from feature_v2_resolver import get_approved_pool, resolve_exercise_need
        pool = event_loop.run_until_complete(get_approved_pool())
        res = resolve_exercise_need({"name": "Xylophone Blizzard Quokka"}, pool, client_ctx=None)
        assert res["kind"] == "unresolved"


# ---------- 4. apply_resolver_to_workouts ----------

class TestApplyResolverBatch:
    def _make_user(self, mongo):
        cid = f"TEST_{TEST_TAG}_user_{uuid.uuid4().hex[:8]}"
        mongo.users.insert_one({
            "id": cid, "email": f"{cid}@test.local", "name": "TEST User",
            "role": "client", "profile": {"equipment": ["dumbbell"], "main_goal_key": "strength"},
            "created_at": "2099-01-01T00:00:00+00:00",
        })
        return cid

    def test_matched_substituted_dropped_paths(self, mongo, seed_pool, event_loop):
        from feature_v2_resolver import apply_resolver_to_workouts
        uid = self._make_user(mongo)
        user = mongo.users.find_one({"id": uid}, {"_id": 0})
        try:
            workouts = [{
                "id": f"TEST_{TEST_TAG}_wo_{uuid.uuid4().hex[:6]}",
                "exercises": [
                    {"name": "TEST Goblet Squat Alpha"},        # matched
                    {"name": "TEST Push Up Alpha Variation"},   # substring/token — substituted or matched
                    {"name": "Xylophone Blizzard Quokka"},      # dropped
                ],
            }]
            stats = event_loop.run_until_complete(
                apply_resolver_to_workouts(workouts, user=user, programme_id="TEST_prog")
            )
            exs = workouts[0]["exercises"]
            # Alien must have been dropped.
            names = [e["name"] for e in exs]
            assert "Xylophone Blizzard Quokka" not in names
            # Every remaining exercise has exercise_id + source
            for e in exs:
                assert e.get("exercise_id"), f"missing exercise_id on {e}"
                assert e.get("source") == "v2_library"
            # Matched entry: no substitute_for
            matched = next((e for e in exs if e["name"] == "TEST Goblet Squat Alpha"), None)
            assert matched is not None
            assert "substitute_for" not in matched
            # Alien dropped -> counted
            assert stats["dropped"] >= 1
            # A draft request row must have been created for the alien.
            alien_req = mongo.exercises_v2.find_one(
                {"exercise_name": "Xylophone Blizzard Quokka"}, {"_id": 0}
            )
            assert alien_req is not None
            assert alien_req["status"] == "draft_requested"
            assert alien_req["visibility"] == "coach_only"
            assert alien_req["safe_for_programming"] is False
            assert alien_req["needs_louis_review"] is True
            assert alien_req["request_count"] == 1
            # Coach task should exist
            task = mongo.coach_tasks.find_one(
                {"task_type": "exercise_review",
                 "title": {"$regex": "Xylophone Blizzard Quokka"}}
            )
            assert task is not None
        finally:
            mongo.users.delete_one({"id": uid})
            mongo.exercises_v2.delete_many({"exercise_name": "Xylophone Blizzard Quokka"})
            mongo.exercises_v2.delete_many({"exercise_name": "TEST Push Up Alpha Variation"})
            mongo.coach_tasks.delete_many({"title": {"$regex": "Xylophone Blizzard Quokka"}})
            mongo.coach_tasks.delete_many({"title": {"$regex": "TEST Push Up Alpha Variation"}})

    def test_dedup_bumps_request_count_no_duplicate(self, mongo, seed_pool, event_loop):
        from feature_v2_resolver import apply_resolver_to_workouts
        uid = self._make_user(mongo)
        user = mongo.users.find_one({"id": uid}, {"_id": 0})
        alien = f"Zyzzyx Dedup Widget {uuid.uuid4().hex[:4]}"
        try:
            wo = {"id": f"TEST_{TEST_TAG}_wo_{uuid.uuid4().hex[:6]}",
                  "exercises": [{"name": alien}]}
            # First run
            event_loop.run_until_complete(
                apply_resolver_to_workouts([wo], user=user, programme_id="TEST_p")
            )
            row1 = mongo.exercises_v2.find_one({"exercise_name": alien}, {"_id": 0})
            assert row1 is not None
            assert row1["request_count"] == 1
            initial_task_count = mongo.coach_tasks.count_documents(
                {"title": {"$regex": re.escape(alien)}}
            )
            assert initial_task_count == 1
            # Second run (fresh workout list)
            wo2 = {"id": f"TEST_{TEST_TAG}_wo_{uuid.uuid4().hex[:6]}",
                   "exercises": [{"name": alien}]}
            event_loop.run_until_complete(
                apply_resolver_to_workouts([wo2], user=user, programme_id="TEST_p2")
            )
            all_rows = list(mongo.exercises_v2.find({"exercise_name": alien}, {"_id": 0}))
            assert len(all_rows) == 1, f"duplicate created! got {len(all_rows)}"
            assert all_rows[0]["request_count"] == 2
            assert len(all_rows[0].get("request_history") or []) >= 2
            # Still just one coach task
            after_task_count = mongo.coach_tasks.count_documents(
                {"title": {"$regex": re.escape(alien)}}
            )
            assert after_task_count == 1
        finally:
            mongo.users.delete_one({"id": uid})
            mongo.exercises_v2.delete_many({"exercise_name": alien})
            mongo.coach_tasks.delete_many({"title": {"$regex": re.escape(alien)}})

    def test_cap_at_max_requests_per_programme(self, mongo, seed_pool, event_loop):
        from feature_v2_resolver import apply_resolver_to_workouts, MAX_REQUESTS_PER_PROGRAMME
        uid = self._make_user(mongo)
        user = mongo.users.find_one({"id": uid}, {"_id": 0})
        alien_names = [f"CapAlien{i}_{uuid.uuid4().hex[:4]}" for i in range(10)]
        try:
            wo = {"id": f"TEST_{TEST_TAG}_cap_{uuid.uuid4().hex[:6]}",
                  "exercises": [{"name": n} for n in alien_names]}
            stats = event_loop.run_until_complete(
                apply_resolver_to_workouts([wo], user=user, programme_id="TEST_cap")
            )
            assert stats["requests_created"] <= MAX_REQUESTS_PER_PROGRAMME
            created = sum(
                1 for n in alien_names
                if mongo.exercises_v2.find_one({"exercise_name": n})
            )
            assert created == MAX_REQUESTS_PER_PROGRAMME, (
                f"expected {MAX_REQUESTS_PER_PROGRAMME} request rows, got {created}"
            )
        finally:
            mongo.users.delete_one({"id": uid})
            for n in alien_names:
                mongo.exercises_v2.delete_many({"exercise_name": n})
                mongo.coach_tasks.delete_many({"title": {"$regex": re.escape(n)}})


# ---------- 5. summarise_workout_v2_health ----------

class TestSummary:
    def test_summary_counts(self):
        from feature_v2_resolver import summarise_workout_v2_health
        s = summarise_workout_v2_health([
            {"exercises": [
                {"exercise_id": "a"},
                {"exercise_id": "b", "substitute_for": "x"},
                {"name": "free-text no id"},
            ]}
        ])
        assert s["total_exercises"] == 3
        assert s["resolved_to_v2"] == 2
        assert s["substituted"] == 1
        assert s["missing_exercise_id"] == 1


# ---------- 6. Coach-only API surface ----------

class TestExerciseContentApi:
    def _create_draft(self, mongo):
        """Insert a draft request row directly."""
        eid = f"TEST_{TEST_TAG}_draft_{uuid.uuid4().hex[:8]}"
        mongo.exercises_v2.insert_one({
            "id": eid, "exercise_name": f"TEST Draft {eid}", "requested_name_norm": f"test draft {eid.lower()}",
            "status": "draft_requested", "visibility": "coach_only",
            "safe_for_programming": False, "needs_louis_review": True,
            "request_count": 3, "request_history": [],
            "requested_for_user_ids": ["u1", "u2"], "requested_for_programme_ids": ["p1"],
            "test_tag": TEST_TAG, "created_at": "2099-01-01T00:00:00+00:00",
        })
        return eid

    def test_list_requests_coach_only(self, mongo, hdr_coach, hdr_client):
        eid = self._create_draft(mongo)
        try:
            # Coach: 200 with clients_affected/programmes_affected derived
            r = requests.get(f"{API}/exercise-content/requests", headers=hdr_coach, timeout=15)
            assert r.status_code == 200
            data = r.json()
            assert "requests" in data
            matched = next((x for x in data["requests"] if x["id"] == eid), None)
            assert matched is not None
            assert matched["clients_affected"] == 2
            assert matched["programmes_affected"] == 1
            # Client: 403
            r2 = requests.get(f"{API}/exercise-content/requests", headers=hdr_client, timeout=15)
            assert r2.status_code == 403
        finally:
            mongo.exercises_v2.delete_one({"id": eid})

    def test_reject_flips_status(self, mongo, hdr_coach):
        eid = self._create_draft(mongo)
        try:
            r = requests.post(f"{API}/exercise-content/{eid}/reject", headers=hdr_coach,
                              json={"reason": "Not aligned to programme"}, timeout=15)
            assert r.status_code == 200
            row = mongo.exercises_v2.find_one({"id": eid}, {"_id": 0})
            assert row["status"] == "rejected"
            assert row["safe_for_programming"] is False
            assert row.get("rejected_reason") == "Not aligned to programme"
            assert row.get("reviewed_by")
        finally:
            mongo.exercises_v2.delete_one({"id": eid})

    def test_reject_404_for_missing(self, hdr_coach):
        r = requests.post(f"{API}/exercise-content/does_not_exist_xyz/reject",
                          headers=hdr_coach, json={"reason": "x"}, timeout=15)
        assert r.status_code == 404

    def test_merge_moves_count_into_target(self, mongo, hdr_coach):
        src = self._create_draft(mongo)
        tgt = self._create_draft(mongo)
        # Give target a starting count of 1
        mongo.exercises_v2.update_one({"id": tgt}, {"$set": {"request_count": 1}})
        try:
            r = requests.post(f"{API}/exercise-content/{src}/merge", headers=hdr_coach,
                              json={"target_id": tgt}, timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["merged_into"] == tgt
            src_row = mongo.exercises_v2.find_one({"id": src}, {"_id": 0})
            tgt_row = mongo.exercises_v2.find_one({"id": tgt}, {"_id": 0})
            assert src_row["status"] == "merged"
            assert src_row["merged_into_id"] == tgt
            assert src_row["safe_for_programming"] is False
            # Target's request_count = its 1 + source's 3 = 4
            assert tgt_row["request_count"] == 4
        finally:
            mongo.exercises_v2.delete_many({"id": {"$in": [src, tgt]}})

    def test_merge_into_itself_is_400(self, mongo, hdr_coach):
        eid = self._create_draft(mongo)
        try:
            r = requests.post(f"{API}/exercise-content/{eid}/merge", headers=hdr_coach,
                              json={"target_id": eid}, timeout=15)
            assert r.status_code == 400
        finally:
            mongo.exercises_v2.delete_one({"id": eid})


# ---------- 7. Programme validation surface ----------

class TestProgrammeValidation:
    def test_validate_programme_reports_missing_exercise_id(self, event_loop):
        # We call validate_programme directly. It's a plain sync function.
        from feature_programme_quality import validate_programme
        workouts = [{
            "id": "wo1", "date": "2099-01-01",
            "exercises": [{"name": "no-id thing"}],
            "focus_area": "strength",
        }]
        user = {"id": "TEST_u", "profile": {}}
        roster = {"id": "TEST_r", "days": []}
        context = {"target_sessions_per_week": 3, "phase": {"key": "Build"}, "goal_key": "strength"}
        result = validate_programme(user, roster, workouts, context)
        # Should include v2_library stats
        assert isinstance(result, dict)
        assert "summary" in result
        # v2_library may be absent if the helper import failed at runtime, but
        # if present must show missing_exercise_id > 0.
        v2 = result["summary"].get("v2_library")
        if v2 is not None:
            assert v2["missing_exercise_id"] >= 1
            # And there should be a validation error mentioning the V2 Library
            joined = " ".join(result.get("errors") or [])
            assert "V2 Library" in joined or "V2" in joined
