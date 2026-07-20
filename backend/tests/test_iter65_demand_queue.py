"""
iter65 — Phase 5 P1: Coach Demand Queue + Louis Review Modal + Just-in-time media.

Tests:
  - GET /api/exercise-requests/grouped bucketing (needed_soon vs awaiting_review vs history) + counts
  - POST /api/exercise-requests/{id}/approve-quick (with trigger_media true/false)
  - POST /api/exercise-requests/{id}/generate-media + idempotency (skip if already has image)
  - jit_media_sweep_once() direct call
  - Regression: feature_exercise_content.ex_approve sets client_visible for mark_live/all,
    NOT for images/coaching/video/needs_update
  - Negative: 404 on missing id, 403 as client
  - Regression: /exercise-requests (P0 list), reject, merge still function
"""

import os
import sys
import uuid
import asyncio
import datetime as _dt
import pytest
import requests
from pymongo import MongoClient

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

TEST_TAG = "iter65_demand_queue"


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    yield c[DB_NAME]
    c.close()


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def coach_token():
    r = requests.post(f"{API}/auth/login", json={"email": COACH_EMAIL, "password": COACH_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def client_token():
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PASS}, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def hdr_coach(coach_token):
    return {"Authorization": f"Bearer {coach_token}", "Content-Type": "application/json"}


@pytest.fixture
def hdr_client(client_token):
    return {"Authorization": f"Bearer {client_token}", "Content-Type": "application/json"}


def _mk_draft(mongo, workout_ids=None, name=None):
    eid = f"TEST_{TEST_TAG}_draft_{uuid.uuid4().hex[:8]}"
    nm = name or f"TEST Draft {eid}"
    mongo.exercises_v2.insert_one({
        "id": eid,
        "exercise_name": nm,
        "requested_name": nm,
        "requested_name_norm": nm.lower(),
        "suggested_name": nm,
        "status": "draft_requested",
        "visibility": "coach_only",
        "safe_for_programming": False,
        "needs_louis_review": True,
        "request_count": 1,
        "request_history": [],
        "requested_for_user_ids": ["u1"],
        "requested_for_programme_ids": ["p1"],
        "requested_for_workout_ids": workout_ids or [],
        "test_tag": TEST_TAG,
        "created_at": "2099-01-01T00:00:00+00:00",
        "updated_at": "2099-01-01T00:00:00+00:00",
    })
    return eid


def _cleanup(mongo):
    mongo.exercises_v2.delete_many({"test_tag": TEST_TAG})
    mongo.workouts.delete_many({"_iter65_test": True})
    mongo.exercise_content_images.delete_many({"created_by": "jit_media", "exercise_id": {"$regex": f"^TEST_{TEST_TAG}"}})


# ---------- 1. GET /exercise-requests/grouped ----------

class TestGrouped:
    def test_grouped_coach_returns_keys(self, mongo, hdr_coach):
        eid = _mk_draft(mongo)
        try:
            r = requests.get(f"{API}/exercise-requests/grouped", headers=hdr_coach, timeout=15)
            assert r.status_code == 200, r.text
            data = r.json()
            for key in ("needed_soon", "awaiting_review", "history", "counts"):
                assert key in data, f"missing {key}"
            for c in ("needed_soon", "awaiting_review", "history", "total_pending"):
                assert c in data["counts"], f"missing counts.{c}"
        finally:
            _cleanup(mongo)

    def test_grouped_client_forbidden(self, mongo, hdr_client):
        r = requests.get(f"{API}/exercise-requests/grouped", headers=hdr_client, timeout=15)
        assert r.status_code == 403

    def test_needed_soon_vs_awaiting_review_bucketing(self, mongo, hdr_coach):
        # Create an upcoming workout, a draft that references it (needed_soon),
        # and a draft with NO workout reference (awaiting_review).
        wid = f"TEST_{TEST_TAG}_wo_{uuid.uuid4().hex[:6]}"
        upcoming = (_dt.date.today() + _dt.timedelta(days=3)).isoformat()
        mongo.workouts.insert_one({
            "id": wid, "date": upcoming, "exercises": [],
            "_iter65_test": True, "test_tag": TEST_TAG,
        })
        needed_id = _mk_draft(mongo, workout_ids=[wid], name="TEST Needed Soon Ex")
        awaiting_id = _mk_draft(mongo, workout_ids=[], name="TEST Awaiting Review Ex")
        # And a rejected draft → history
        rej_id = _mk_draft(mongo, name="TEST Rejected Ex")
        mongo.exercises_v2.update_one({"id": rej_id}, {"$set": {"status": "rejected"}})
        try:
            r = requests.get(f"{API}/exercise-requests/grouped", headers=hdr_coach, timeout=15)
            assert r.status_code == 200
            data = r.json()
            needed_ids = [x["id"] for x in data["needed_soon"]]
            awaiting_ids = [x["id"] for x in data["awaiting_review"]]
            history_ids = [x["id"] for x in data["history"]]
            assert needed_id in needed_ids, f"needed_soon missing {needed_id}"
            assert awaiting_id in awaiting_ids, f"awaiting_review missing {awaiting_id}"
            # rejected should be in history, NOT in awaiting/needed
            assert rej_id in history_ids
            assert rej_id not in needed_ids
            assert rej_id not in awaiting_ids
        finally:
            _cleanup(mongo)


# ---------- 2. approve-quick ----------

class TestApproveQuick:
    def test_approve_quick_with_media_trigger(self, mongo, hdr_coach):
        eid = _mk_draft(mongo, name=f"TEST OrigName {uuid.uuid4().hex[:4]}")
        try:
            body = {
                "name": "Renamed Ex",
                "category": "strength",
                "movement_pattern": "hinge",
                "equipment_type": ["dumbbell"],
                "difficulty_level": "intermediate",
                "trigger_media": True,
            }
            r = requests.post(f"{API}/exercise-requests/{eid}/approve-quick",
                              headers=hdr_coach, json=body, timeout=30)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "exercise" in data and "media_triggered" in data
            ex = data["exercise"]
            assert ex["status"] == "Approved"
            assert ex["approval_status"] == "approved"
            assert ex["visibility"] == "client_visible"
            assert ex["safe_for_programming"] is True
            assert ex["needs_louis_review"] is False
            assert ex["exercise_name"] == "Renamed Ex"
            assert ex["category"] == "strength"
            assert ex["movement_pattern"] == "hinge"
            assert ex["equipment_type"] == ["dumbbell"]
            assert ex["difficulty_level"] == "intermediate"
            # media_triggered can be True (job queued) or False (already had image);
            # since we made a fresh draft with no image, expect True
            assert data["media_triggered"] is True
            job = mongo.exercise_content_images.find_one({"exercise_id": eid}, {"_id": 0})
            assert job is not None
            assert job["status"] in ("generating", "ready", "failed")
        finally:
            _cleanup(mongo)

    def test_approve_quick_without_media(self, mongo, hdr_coach):
        eid = _mk_draft(mongo)
        try:
            r = requests.post(f"{API}/exercise-requests/{eid}/approve-quick",
                              headers=hdr_coach, json={"trigger_media": False}, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["media_triggered"] is False
            job = mongo.exercise_content_images.find_one({"exercise_id": eid})
            assert job is None
        finally:
            _cleanup(mongo)

    def test_approve_quick_404_missing(self, hdr_coach):
        r = requests.post(f"{API}/exercise-requests/nope_missing_xyz_123/approve-quick",
                          headers=hdr_coach, json={}, timeout=15)
        assert r.status_code == 404

    def test_approve_quick_403_client(self, mongo, hdr_client):
        eid = _mk_draft(mongo)
        try:
            r = requests.post(f"{API}/exercise-requests/{eid}/approve-quick",
                              headers=hdr_client, json={}, timeout=15)
            assert r.status_code == 403
        finally:
            _cleanup(mongo)


# ---------- 3. generate-media (force) ----------

class TestGenerateMedia:
    def test_generate_media_on_approved_without_image(self, mongo, hdr_coach):
        eid = _mk_draft(mongo)
        # promote to Approved without an image
        mongo.exercises_v2.update_one({"id": eid}, {"$set": {
            "status": "Approved", "visibility": "client_visible",
            "safe_for_programming": True,
        }})
        try:
            r = requests.post(f"{API}/exercise-requests/{eid}/generate-media",
                              headers=hdr_coach, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["media_triggered"] is True
            job = mongo.exercise_content_images.find_one({"exercise_id": eid}, {"_id": 0})
            assert job is not None
        finally:
            _cleanup(mongo)

    def test_generate_media_forces_even_if_has_image(self, mongo, hdr_coach):
        """Endpoint uses force=True → still triggers even when primary_image_id present."""
        eid = _mk_draft(mongo)
        mongo.exercises_v2.update_one({"id": eid}, {"$set": {
            "status": "Approved", "visibility": "client_visible",
            "safe_for_programming": True,
            "primary_image_id": "already_here",
            "approved_image_status": "Approved",
        }})
        try:
            r = requests.post(f"{API}/exercise-requests/{eid}/generate-media",
                              headers=hdr_coach, timeout=15)
            assert r.status_code == 200
            # force=True in endpoint → must trigger
            assert r.json()["media_triggered"] is True
        finally:
            _cleanup(mongo)


# ---------- 4. _maybe_kick_media idempotency (direct call, force=False) ----------

class TestMaybeKickMediaIdempotency:
    def test_no_op_if_has_primary_image(self, mongo, event_loop):
        from feature_v2_resolver import _maybe_kick_media
        eid = _mk_draft(mongo)
        mongo.exercises_v2.update_one({"id": eid}, {"$set": {
            "status": "Approved", "primary_image": "img.jpg",
        }})
        try:
            ok = event_loop.run_until_complete(_maybe_kick_media(eid, force=False))
            assert ok is False
        finally:
            _cleanup(mongo)

    def test_no_op_if_approved_image_status_approved(self, mongo, event_loop):
        from feature_v2_resolver import _maybe_kick_media
        eid = _mk_draft(mongo)
        mongo.exercises_v2.update_one({"id": eid}, {"$set": {
            "status": "Approved", "approved_image_status": "Approved",
        }})
        try:
            ok = event_loop.run_until_complete(_maybe_kick_media(eid, force=False))
            assert ok is False
        finally:
            _cleanup(mongo)

    def test_no_op_if_not_approved_status(self, mongo, event_loop):
        from feature_v2_resolver import _maybe_kick_media
        eid = _mk_draft(mongo)  # status still 'draft_requested'
        try:
            ok = event_loop.run_until_complete(_maybe_kick_media(eid, force=False))
            assert ok is False
        finally:
            _cleanup(mongo)


# ---------- 5. jit_media_sweep_once ----------

class TestJitSweep:
    def test_sweep_no_candidates(self, mongo, event_loop):
        from feature_v2_resolver import jit_media_sweep_once
        _cleanup(mongo)
        stats = event_loop.run_until_complete(jit_media_sweep_once())
        assert isinstance(stats, dict)
        assert "queued" in stats and "candidates" in stats

    def test_sweep_queues_for_upcoming_approved_no_image(self, mongo, event_loop):
        from feature_v2_resolver import jit_media_sweep_once
        # Seed an approved exercise WITHOUT image
        eid = _mk_draft(mongo)
        mongo.exercises_v2.update_one({"id": eid}, {"$set": {
            "status": "Approved", "visibility": "client_visible",
            "safe_for_programming": True,
        }})
        # Seed a workout in the next 7 days that references it
        wid = f"TEST_{TEST_TAG}_wo_{uuid.uuid4().hex[:6]}"
        upcoming = (_dt.date.today() + _dt.timedelta(days=2)).isoformat()
        mongo.workouts.insert_one({
            "id": wid, "date": upcoming,
            "exercises": [{"exercise_id": eid, "name": "x"}],
            "_iter65_test": True, "test_tag": TEST_TAG,
        })
        try:
            stats = event_loop.run_until_complete(jit_media_sweep_once())
            assert stats["candidates"] >= 1
            # queued may be 0 if the exercise was already picked up in another test
            # but for a fresh eid we expect >= 1
            assert stats["queued"] >= 1
            # Verify a job row was created
            job = mongo.exercise_content_images.find_one({"exercise_id": eid}, {"_id": 0})
            assert job is not None
        finally:
            _cleanup(mongo)


# ---------- 6. ex_approve scope regression ----------

class TestExApproveVisibilityFlags:
    def _mk_approvable(self, mongo):
        eid = f"TEST_{TEST_TAG}_approvable_{uuid.uuid4().hex[:6]}"
        mongo.exercises_v2.insert_one({
            "id": eid, "exercise_name": f"TEST Approvable {eid}",
            "status": "Draft", "visibility": "coach_only", "safe_for_programming": False,
            "test_tag": TEST_TAG,
            "created_at": "2099-01-01T00:00:00+00:00",
        })
        return eid

    def test_mark_live_sets_flags(self, mongo, hdr_coach):
        eid = self._mk_approvable(mongo)
        try:
            r = requests.post(f"{API}/exercise-content/{eid}/approve",
                              headers=hdr_coach, json={"scope": "mark_live"}, timeout=15)
            assert r.status_code == 200, r.text
            row = mongo.exercises_v2.find_one({"id": eid}, {"_id": 0})
            assert row["visibility"] == "client_visible"
            assert row["safe_for_programming"] is True
        finally:
            _cleanup(mongo)

    def test_all_sets_flags(self, mongo, hdr_coach):
        eid = self._mk_approvable(mongo)
        try:
            r = requests.post(f"{API}/exercise-content/{eid}/approve",
                              headers=hdr_coach, json={"scope": "all"}, timeout=15)
            assert r.status_code == 200, r.text
            row = mongo.exercises_v2.find_one({"id": eid}, {"_id": 0})
            assert row["visibility"] == "client_visible"
            assert row["safe_for_programming"] is True
        finally:
            _cleanup(mongo)

    @pytest.mark.parametrize("scope", ["images", "coaching", "video", "needs_update"])
    def test_narrow_scopes_do_not_change_visibility(self, mongo, hdr_coach, scope):
        eid = self._mk_approvable(mongo)
        try:
            r = requests.post(f"{API}/exercise-content/{eid}/approve",
                              headers=hdr_coach, json={"scope": scope}, timeout=15)
            assert r.status_code == 200, r.text
            row = mongo.exercises_v2.find_one({"id": eid}, {"_id": 0})
            # Should still be coach_only + unsafe (unchanged)
            assert row["visibility"] == "coach_only", f"scope={scope} flipped visibility"
            assert row["safe_for_programming"] is False, f"scope={scope} flipped safe"
        finally:
            _cleanup(mongo)


# ---------- 7. Regression — P0 list + reject + merge still work ----------

class TestP0Regression:
    def test_list_requests_still_works(self, mongo, hdr_coach):
        eid = _mk_draft(mongo)
        try:
            r = requests.get(f"{API}/exercise-requests", headers=hdr_coach, timeout=15)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "requests" in data
            assert any(x["id"] == eid for x in data["requests"])
        finally:
            _cleanup(mongo)

    def test_reject_still_works(self, mongo, hdr_coach):
        eid = _mk_draft(mongo)
        try:
            r = requests.post(f"{API}/exercise-content/{eid}/reject",
                              headers=hdr_coach, json={"reason": "regression"}, timeout=15)
            assert r.status_code == 200, r.text
            row = mongo.exercises_v2.find_one({"id": eid}, {"_id": 0})
            assert row["status"] == "rejected"
        finally:
            _cleanup(mongo)

    def test_merge_still_works(self, mongo, hdr_coach):
        src = _mk_draft(mongo)
        tgt = _mk_draft(mongo)
        try:
            r = requests.post(f"{API}/exercise-content/{src}/merge",
                              headers=hdr_coach, json={"target_id": tgt}, timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["merged_into"] == tgt
        finally:
            _cleanup(mongo)
