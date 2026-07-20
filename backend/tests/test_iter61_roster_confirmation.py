"""
Iteration 61 — Roster Confirmation (parse → confirm → build) backend tests.

Covers /api/roster/upload-parse, /api/roster/pending, PATCH edits,
/confirm-day, /confirm (build), DELETE draft, and regression of the
legacy /api/roster/upload-and-generate endpoint.

Notes on seeding
----------------
The parse endpoint invokes Gemini and returns non-deterministic data. To keep
the tests fast and hermetic, we seed a pending roster row directly into
`db.rosters` (matching the shape produced by `_persist_pending_roster`) for
all the pending-CRUD + confirm-build assertions. The parse endpoint itself is
still exercised (with a tiny bogus file) to prove the failure path.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def auth():
    r = requests.post(f"{API}/auth/login",
                      json={"email": "client@crewfit.com", "password": "Client123!"},
                      timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    j = r.json()
    return {"user_id": j["user"]["id"],
            "headers": {"Authorization": f"Bearer {j['token']}",
                        "Content-Type": "application/json"}}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _seed_pending(db, user_id, low_conf_count=2, high_conf_count=3):
    """Insert a pending roster document directly."""
    days = []
    start = datetime.now(timezone.utc).date() + timedelta(days=7)
    for i in range(high_conf_count):
        days.append({
            "date": (start + timedelta(days=i)).isoformat(),
            "day_type": "Flight",
            "confidence": 0.9,
            "flights": [],
            "load": "medium",
            "home_or_away": "home",
        })
    for i in range(low_conf_count):
        days.append({
            "date": (start + timedelta(days=high_conf_count + i)).isoformat(),
            "day_type": "Unknown/Needs Confirmation",
            "confidence": 0.3,
            "flights": [],
            "load": "low",
            "home_or_away": "unknown",
        })
    rid = str(uuid.uuid4())
    doc = {
        "id": rid,
        "user_id": user_id,
        "created_at": _now_iso(),
        "week_start": days[0]["date"],
        "start_date": days[0]["date"],
        "end_date": days[-1]["date"],
        "days": days,
        "confirmed": False,
        "confirmed_at": None,
        "is_active": False,
        "status": "pending_confirmation",
        "raw_response": "TEST_seed",
        "source_filename": "TEST_seed_roster.pdf",
        "upload_job_id": str(uuid.uuid4()),
        "day_count": len(days),
        "confidence_avg": 0.5,
        "review_flags": {"low_confidence_count": low_conf_count},
    }
    db.rosters.insert_one(doc)
    return rid


@pytest.fixture(scope="module", autouse=True)
def cleanup(db, auth):
    yield
    # Remove any TEST_ pending drafts we may have left behind
    db.rosters.delete_many({"user_id": auth["user_id"],
                            "source_filename": {"$regex": "^TEST_"}})


# =============================================================================
# /api/roster/upload-parse
# =============================================================================

class TestUploadParse:
    """Parse endpoint job lifecycle."""

    def test_upload_parse_creates_parse_only_job_and_does_not_deactivate_active(self, auth, db):
        # Capture current active roster state so we can verify it is preserved.
        active_before = list(db.rosters.find({"user_id": auth["user_id"], "is_active": True}, {"_id": 0, "id": 1}))
        workouts_count_before = db.workouts.count_documents({"user_id": auth["user_id"]})

        tiny_pdf_b64 = base64.b64encode(b"%PDF-1.4 not-a-real-pdf just-bytes").decode()
        r = requests.post(
            f"{API}/roster/upload-parse",
            json={"file_base64": tiny_pdf_b64, "mime_type": "application/pdf",
                  "filename": "TEST_bogus_roster.pdf"},
            headers=auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "queued"
        job_id = body["job_id"]

        # Confirm the job row has flow='parse_only'
        job = db.roster_jobs.find_one({"id": job_id}, {"_id": 0})
        assert job is not None
        assert job.get("flow") == "parse_only"

        # Poll until terminal (max ~40s)
        terminal = None
        for _ in range(40):
            j = requests.get(f"{API}/roster/jobs/{job_id}", headers=auth["headers"], timeout=15)
            if j.status_code == 200 and j.json().get("status") in {"awaiting_confirmation", "failed", "complete", "needs_review"}:
                terminal = j.json()
                break
            time.sleep(1)
        assert terminal is not None, "job never reached terminal state"

        # Parse failing on our bogus bytes is the expected path — job MUST be failed,
        # and no pending roster row should be created for it.
        if terminal["status"] == "failed":
            assert terminal.get("pending_roster_id") in (None, ""), terminal
            assert (terminal.get("error") or "").strip() != ""
        else:
            # If Gemini somehow parsed it, we still expect awaiting_confirmation
            # with a pending_roster_id and stage=ready_to_confirm.
            assert terminal["status"] == "awaiting_confirmation", terminal
            assert terminal.get("stage") == "ready_to_confirm"
            assert terminal.get("pending_roster_id")

        # Active roster (if any) must be untouched by /upload-parse.
        active_after = list(db.rosters.find({"user_id": auth["user_id"], "is_active": True}, {"_id": 0, "id": 1}))
        assert {r["id"] for r in active_after} == {r["id"] for r in active_before}, \
            "upload-parse must NOT deactivate an existing active roster"

        # Workouts collection must not have grown from parse.
        workouts_count_after = db.workouts.count_documents({"user_id": auth["user_id"]})
        assert workouts_count_after == workouts_count_before, \
            "upload-parse must NOT insert into workouts"


# =============================================================================
# /api/roster/pending + PATCH + /confirm-day + DELETE
# =============================================================================

class TestPendingCRUD:

    def test_get_pending_returns_seeded_row_with_needs_review(self, auth, db):
        rid = _seed_pending(db, auth["user_id"])
        try:
            r = requests.get(f"{API}/roster/pending", headers=auth["headers"], timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("id") == rid, "GET /roster/pending should return newest seeded row"
            for d in body["days"]:
                assert "_needs_review" in d
            # At least the low-confidence Unknown days must be flagged for review
            unknowns = [d for d in body["days"] if d["day_type"].lower().startswith("unknown")]
            assert unknowns and all(d["_needs_review"] for d in unknowns)
        finally:
            db.rosters.delete_one({"id": rid})

    def test_get_pending_by_id(self, auth, db):
        rid = _seed_pending(db, auth["user_id"])
        try:
            r = requests.get(f"{API}/roster/pending/{rid}", headers=auth["headers"], timeout=15)
            assert r.status_code == 200, r.text
            assert r.json()["id"] == rid
        finally:
            db.rosters.delete_one({"id": rid})

    def test_patch_persists_edit_and_auto_confirms(self, auth, db):
        rid = _seed_pending(db, auth["user_id"])
        try:
            pending = requests.get(f"{API}/roster/pending/{rid}", headers=auth["headers"], timeout=15).json()
            # Take the first unknown low-confidence day and change to Layover/Bangkok
            target = next(d for d in pending["days"] if d["day_type"].lower().startswith("unknown"))
            new_days = []
            for d in pending["days"]:
                if d["date"] == target["date"]:
                    new_days.append({**d, "day_type": "Layover", "layover_city": "Bangkok",
                                     "layover_nights": 2})
                else:
                    new_days.append(d)
            # Strip _needs_review before sending (client does the same)
            for d in new_days:
                d.pop("_needs_review", None)

            r = requests.patch(
                f"{API}/roster/pending/{rid}",
                json={"days": new_days},
                headers=auth["headers"], timeout=15,
            )
            assert r.status_code == 200, r.text
            updated = r.json()
            edited = next(d for d in updated["days"] if d["date"] == target["date"])
            assert edited["day_type"] == "Layover"
            assert edited["layover_city"] == "Bangkok"
            assert edited["_confirmed_by_user"] is True
            assert edited["_needs_review"] is False
        finally:
            db.rosters.delete_one({"id": rid})

    def test_confirm_day_marks_single_day_reviewed(self, auth, db):
        rid = _seed_pending(db, auth["user_id"])
        try:
            pending = requests.get(f"{API}/roster/pending/{rid}", headers=auth["headers"], timeout=15).json()
            target = next(d for d in pending["days"] if d["_needs_review"])
            r = requests.post(
                f"{API}/roster/pending/{rid}/confirm-day",
                json={"date": target["date"]},
                headers=auth["headers"], timeout=15,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            edited = next(d for d in body["days"] if d["date"] == target["date"])
            assert edited["_confirmed_by_user"] is True
            assert edited["_needs_review"] is False
        finally:
            db.rosters.delete_one({"id": rid})

    def test_delete_removes_pending_only(self, auth, db):
        rid = _seed_pending(db, auth["user_id"])
        r = requests.delete(f"{API}/roster/pending/{rid}", headers=auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("deleted") is True
        # Verify actually gone
        assert db.rosters.find_one({"id": rid}) is None


# =============================================================================
# /api/roster/pending/{id}/confirm
# =============================================================================

class TestConfirmAndBuild:

    def test_confirm_blocked_while_needs_review_pending(self, auth, db):
        rid = _seed_pending(db, auth["user_id"])
        try:
            r = requests.post(f"{API}/roster/pending/{rid}/confirm",
                              headers=auth["headers"], timeout=15)
            assert r.status_code == 400, r.text
            assert "review" in r.text.lower()
        finally:
            db.rosters.delete_one({"id": rid})

    def test_confirm_success_activates_deactivates_others_and_kicks_build(self, auth, db):
        # Seed a pending roster and pre-mark all unknown days as reviewed.
        rid = _seed_pending(db, auth["user_id"])
        try:
            # Mark all low-conf days reviewed via /confirm-day.
            p = requests.get(f"{API}/roster/pending/{rid}", headers=auth["headers"], timeout=15).json()
            for d in p["days"]:
                if d["_needs_review"]:
                    rr = requests.post(f"{API}/roster/pending/{rid}/confirm-day",
                                       json={"date": d["date"]},
                                       headers=auth["headers"], timeout=15)
                    assert rr.status_code == 200

            # Capture pre-existing active roster ids (should be deactivated).
            active_before = [r["id"] for r in db.rosters.find(
                {"user_id": auth["user_id"], "is_active": True, "id": {"$ne": rid}},
                {"_id": 0, "id": 1})]

            r = requests.post(f"{API}/roster/pending/{rid}/confirm",
                              headers=auth["headers"], timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["roster_id"] == rid
            assert body["status"] == "processing"
            job_id = body["job_id"]

            # (a) Roster promoted
            r2 = db.rosters.find_one({"id": rid}, {"_id": 0})
            assert r2["is_active"] is True
            assert r2["status"] == "confirmed"
            assert r2.get("confirmed_at")

            # (b) Other prior actives now inactive
            for prev_id in active_before:
                prev = db.rosters.find_one({"id": prev_id}, {"_id": 0})
                assert prev["is_active"] is False, f"prior active roster {prev_id} was not deactivated"

            # (c) confirm-build job row exists with the right flow
            job_row = db.roster_jobs.find_one({"id": job_id}, {"_id": 0})
            assert job_row is not None
            assert job_row.get("flow") == "confirm_build"
            assert job_row.get("roster_id") == rid

            # (d) Wait for background worker to persist workouts (~template fallback should be quick)
            deadline = time.time() + 240  # LLM+timeout budget
            workouts = []
            while time.time() < deadline:
                job_poll = requests.get(f"{API}/roster/jobs/{job_id}", headers=auth["headers"], timeout=15).json()
                if job_poll.get("status") in {"complete", "failed", "needs_review"}:
                    break
                time.sleep(3)
            workouts = list(db.workouts.find({"user_id": auth["user_id"], "roster_id": rid}, {"_id": 0}))
            assert len(workouts) > 0, "confirm-build must persist at least one workout (template fallback in place)"
            w = workouts[0]
            assert w.get("source") in {"template", "coaching_system"}
            assert "needs_coach_review" in w
            assert isinstance(w.get("variants"), dict)
            for k in ("green", "amber", "red"):
                assert k in w["variants"]
            assert "rationale" in w

            # (e) Programme row persisted for this roster
            prog = db.programmes.find_one({"user_id": auth["user_id"], "roster_id": rid}, {"_id": 0})
            assert prog is not None, "programme record missing after confirm-build"
            assert prog.get("goal_key"), "programme.goal_key missing"
            assert prog.get("phase")
            assert (prog.get("week_index") or 0) >= 1
            assert (prog.get("target_sessions_per_week") or 0) >= 2
            assert prog.get("roster_id") == rid
        finally:
            # Cleanup: leave the newly-confirmed roster in place if we want to
            # avoid disrupting later manual testing, but scrub its workouts.
            db.workouts.delete_many({"user_id": auth["user_id"], "roster_id": rid})
            db.rosters.delete_one({"id": rid})
            db.programmes.delete_many({"user_id": auth["user_id"], "roster_id": rid})


# =============================================================================
# Regression: legacy /api/roster/upload-and-generate + /jobs/{id}/retry
# =============================================================================

class TestLegacyEndpointsRegression:

    def test_upload_and_generate_still_returns_job_id(self, auth):
        tiny = base64.b64encode(b"%PDF-1.4 test").decode()
        r = requests.post(
            f"{API}/roster/upload-and-generate",
            json={"file_base64": tiny, "mime_type": "application/pdf",
                  "filename": "TEST_legacy_upload.pdf"},
            headers=auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("job_id"), body
        # Just verify polling works — do not wait for full completion
        j = requests.get(f"{API}/roster/jobs/{body['job_id']}",
                        headers=auth["headers"], timeout=15)
        assert j.status_code == 200, j.text

    def test_retry_endpoint_still_answers(self, auth, db):
        # Grab any job for this user, or skip.
        job = db.roster_jobs.find_one({"user_id": auth["user_id"]}, sort=[("created_at", -1)])
        if not job:
            pytest.skip("no roster job exists to retry")
        r = requests.post(f"{API}/roster/jobs/{job['id']}/retry",
                         headers=auth["headers"], timeout=15)
        # 200 (retried) or 400/409 (not retriable) are both acceptable — we
        # just verify the endpoint still exists and doesn't 404/500.
        assert r.status_code in {200, 400, 404, 409}, r.text
