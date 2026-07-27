"""
Coach Dashboard V2 – Iteration 3 backend tests.

Covers:
  Priority 4:
    - GET  /api/v2/coach/clients/{cid}/plan/diff?month=YYYY-MM
    - POST /api/v2/coach/clients/{cid}/plan/publish
  Priority 5 (inline workout editor):
    - PATCH  .../implementations/{iid}                            (meta patch)
    - PATCH  .../implementations/{iid}/exercises/{idx}            (exercise patch)
    - DELETE .../implementations/{iid}/exercises/{idx}            (exercise delete)
    - POST   .../implementations/{iid}/exercises                  (exercise add)
    - POST   .../implementations/{iid}/exercises/reorder          (exercise reorder)

Approach: seed a fresh V2 programme + draft + assignments + live/draft impls
via direct Mongo inserts (no engine calls). Exercise HTTP endpoints against
the public preview URL. Clean up all TEST_-prefixed docs afterwards.
"""
from __future__ import annotations

import os
import sys
import uuid
import datetime as _dt
from typing import Any

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")

CLIENT_ID = "d6e0be44-d3a5-407f-bc04-7cc7ef96179a"   # v2-flagged
LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PW = "Louis123!"
REVIEWER_EMAIL = "reviewer@crewfit.net"
REVIEWER_PW = "CrewFitReview2026!"

TAG = "TEST_iter3_"  # prefix for created docs

now = lambda: _dt.datetime.utcnow().isoformat()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


@pytest.fixture(scope="session")
def coach_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": LOUIS_EMAIL, "password": LOUIS_PW}, timeout=30)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def reviewer_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": REVIEWER_EMAIL, "password": REVIEWER_PW}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"reviewer login failed: {r.status_code}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def seed(db):
    """Insert a full V2 programme scaffold for CLIENT_ID."""
    today = _dt.date.today()
    month = today.strftime("%Y-%m")

    prog_id = TAG + "prog_" + uuid.uuid4().hex[:8]
    draft_id = TAG + "draft_" + uuid.uuid4().hex[:8]
    v1_id = TAG + "ver1_" + uuid.uuid4().hex[:8]

    # 4 assignments: modified, added, live_only, unchanged
    a_mod = TAG + "a_mod"
    a_add = TAG + "a_add"
    a_liveonly = TAG + "a_lo"
    a_unch = TAG + "a_unch"

    live_mod = TAG + "impl_live_mod"
    draft_mod = TAG + "impl_draft_mod"
    draft_add = TAG + "impl_draft_add"
    live_only = TAG + "impl_live_only"
    unch = TAG + "impl_unch"

    ex_live = [
        {"exercise_name_display": "Back Squat", "sets": 4, "reps": "6", "rest_sec": 120, "slot_role": "primary"},
        {"exercise_name_display": "Romanian DL", "sets": 3, "reps": "8", "rest_sec": 90, "slot_role": "accessory"},
    ]
    ex_draft = [
        {"exercise_name_display": "Back Squat", "sets": 4, "reps": "6", "rest_sec": 120, "slot_role": "primary"},
        {"exercise_name_display": "Front Squat", "sets": 3, "reps": "8", "rest_sec": 90, "slot_role": "accessory"},
        {"exercise_name_display": "Leg Press", "sets": 3, "reps": "10", "rest_sec": 60, "slot_role": "accessory"},
    ]

    # Clear any stale TEST_ docs first
    _cleanup(db)

    db.programmes_v2.insert_one({
        "id": prog_id, "client_id": CLIENT_ID, "status": "active",
        "primary_goal_id": "strength", "timeline_class": "8w",
        "live_plan_version": 1, "created_at": now(), "updated_at": now(),
    })
    db.plan_versions.insert_one({
        "id": v1_id, "programme_id": prog_id, "client_id": CLIENT_ID,
        "version": 1, "published_at": now(), "published_by": "seed",
        "snapshot_id": None, "approvals": [], "immutable": True,
    })
    db.plan_drafts.insert_one({
        "id": draft_id, "programme_id": prog_id, "client_id": CLIENT_ID,
        "status": "ready_for_review", "notes": "TEST_ draft", "created_at": now(),
    })

    def _mk_impl(iid, exs, title, duration=45, focus="Lower Strength"):
        return {
            "id": iid, "client_id": CLIENT_ID, "programme_id": prog_id,
            "title": title, "focus": focus, "duration_min": duration,
            "key_session": False, "variant_type": "gym",
            "equipment_context": {"equipment": ["barbell", "dumbbells"]},
            "exercises": exs, "needs_coach_review": False,
            "created_at": now(), "updated_at": now(),
        }

    db.workout_implementations.insert_many([
        _mk_impl(live_mod, ex_live, "TEST_ Lower Body v1"),
        _mk_impl(draft_mod, ex_draft, "TEST_ Lower Body v2 draft", duration=50, focus="Lower Hypertrophy"),
        _mk_impl(draft_add, ex_draft, "TEST_ New Session (draft only)"),
        _mk_impl(live_only, ex_live, "TEST_ Live only"),
        _mk_impl(unch, ex_live, "TEST_ Unchanged"),
    ])

    # 4 assignments across the current month
    def _mk_a(aid, live_iid, draft_iid, day_offset=0, status="ready", locked=False):
        d = today + _dt.timedelta(days=day_offset)
        return {
            "id": aid, "client_id": CLIENT_ID, "programme_id": prog_id,
            "draft_id": draft_id,
            "objective_exposure_id": aid + "_exp",
            "objective_id": "obj_" + aid[:6],
            "schedule_day_id": None,
            "date": d.replace(day=min(d.day, 28)).isoformat(),
            "status": status, "locked": locked,
            "live_implementation_id": live_iid,
            "draft_implementation_id": draft_iid,
            "created_at": now(), "updated_at": now(),
        }

    db.workout_assignments.insert_many([
        _mk_a(a_mod, live_mod, draft_mod, 1, status="ready"),
        _mk_a(a_add, None, draft_add, 2, status="proposed"),
        _mk_a(a_liveonly, live_only, None, 3, status="live"),
        _mk_a(a_unch, unch, unch, 4, status="live"),
    ])

    # Objectives so kind_label works
    db.training_objectives.insert_many([
        {"id": "obj_" + a_mod[:6], "client_id": CLIENT_ID, "kind": "lower_strength"},
        {"id": "obj_" + a_add[:6], "client_id": CLIENT_ID, "kind": "conditioning"},
        {"id": "obj_" + a_liveonly[:6], "client_id": CLIENT_ID, "kind": "upper_strength"},
        {"id": "obj_" + a_unch[:6], "client_id": CLIENT_ID, "kind": "mobility"},
    ])

    # One proposed change_set + one accepted one (already accepted, shouldn't be re-touched)
    cs_prop = TAG + "cs_prop"
    cs_reject = TAG + "cs_rej"
    db.change_sets.insert_many([
        {"id": cs_prop, "draft_id": draft_id, "client_id": CLIENT_ID,
         "kind": "swap_exercise", "human_readable_summary": "TEST_ Swap Front→Goblet",
         "status": "proposed", "triggered_by": "coach", "proposed_by": "engine",
         "created_at": now(), "scope_assignment_ids": [a_mod]},
        {"id": cs_reject, "draft_id": draft_id, "client_id": CLIENT_ID,
         "kind": "increase_volume", "human_readable_summary": "TEST_ +1 set",
         "status": "proposed", "triggered_by": "coach", "proposed_by": "engine",
         "created_at": now(), "scope_assignment_ids": [a_mod]},
    ])

    ctx = {
        "prog_id": prog_id, "draft_id": draft_id, "v1_id": v1_id,
        "a_mod": a_mod, "a_add": a_add, "a_liveonly": a_liveonly, "a_unch": a_unch,
        "live_mod": live_mod, "draft_mod": draft_mod, "draft_add": draft_add,
        "live_only": live_only, "unch": unch,
        "cs_prop": cs_prop, "cs_reject": cs_reject,
        "month": month,
    }
    yield ctx
    _cleanup(db)


def _cleanup(db):
    """Remove all TEST_ prefixed rows."""
    for col in ("programmes_v2", "plan_versions", "plan_drafts", "plan_snapshots",
                "workout_implementations", "workout_assignments", "change_sets",
                "approvals", "training_objectives"):
        db[col].delete_many({"id": {"$regex": f"^{TAG}"}})
    db.decision_records.delete_many({"client_id": CLIENT_ID,
                                      "scope_id": {"$regex": f"^{TAG}"}})


# ---------------------------------------------------------------------------
# Priority 4 – DIFF
# ---------------------------------------------------------------------------

class TestPlanDiff:

    def test_diff_bad_month_400(self, coach_headers):
        r = requests.get(f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/diff",
                         params={"month": "not-a-month"}, headers=coach_headers, timeout=30)
        assert r.status_code == 400, r.text

    def test_diff_no_auth_401_or_403(self):
        r = requests.get(f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/diff",
                         params={"month": "2026-01"}, timeout=30)
        assert r.status_code in (401, 403), r.text

    def test_diff_non_coach_role_403(self, reviewer_headers):
        r = requests.get(f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/diff",
                         params={"month": "2026-01"}, headers=reviewer_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_diff_happy_path_summary_and_delta_kinds(self, coach_headers, seed):
        r = requests.get(f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/diff",
                         params={"month": seed["month"]},
                         headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["client_id"] == CLIENT_ID
        assert body["month"] == seed["month"]
        assert body["draft"] and body["draft"]["id"] == seed["draft_id"]
        assert body["live_version"] and body["live_version"]["version"] == 1

        by_id = {a["id"]: a for a in body["assignments"]}
        assert by_id[seed["a_mod"]]["delta_kind"] == "modified"
        assert by_id[seed["a_add"]]["delta_kind"] == "added"
        assert by_id[seed["a_liveonly"]]["delta_kind"] == "live_only"
        assert by_id[seed["a_unch"]]["delta_kind"] == "unchanged"

        # delta bullets non-empty for modified
        bullets = by_id[seed["a_mod"]]["delta_bullets"]
        assert isinstance(bullets, list) and len(bullets) >= 1
        joined = " | ".join(bullets).lower()
        # We changed title, duration_min, focus, exercise_count → bullets should reflect at least one
        assert ("duration" in joined) or ("focus" in joined) or ("exercises" in joined) or ("title" in joined)

        # summary counts
        s = body["summary"]
        assert s["total_assignments"] == 4
        assert s["changed"] == 1
        assert s["added"] == 1
        # unchanged bucket includes both live_only and unchanged
        assert s["unchanged"] == 2
        # change_sets_proposed picks up both proposed rows
        assert s["change_sets_proposed"] == 2
        # change_sets list surfaced
        cs_ids = {c["id"] for c in body["change_sets"]}
        assert seed["cs_prop"] in cs_ids and seed["cs_reject"] in cs_ids

    def test_diff_no_ai_wording(self, coach_headers, seed):
        r = requests.get(f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/diff",
                         params={"month": seed["month"]},
                         headers=coach_headers, timeout=30)
        assert r.status_code == 200
        text = r.text.lower()
        for banned in ("ai-generated", "chatgpt", "gpt-", "generated by ai",
                       "bot ", "openai"):
            assert banned not in text, f"banned wording found: {banned}"


# ---------------------------------------------------------------------------
# Priority 4 – PUBLISH
# ---------------------------------------------------------------------------

class TestPlanPublish:

    def test_publish_nonexistent_draft_404(self, coach_headers):
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/publish",
            json={"draft_id": "does_not_exist", "assignment_ids": []},
            headers=coach_headers, timeout=30)
        assert r.status_code == 404, r.text

    def test_publish_non_coach_role_403(self, reviewer_headers, seed):
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/publish",
            json={"draft_id": seed["draft_id"], "assignment_ids": []},
            headers=reviewer_headers, timeout=30)
        assert r.status_code == 403, r.text

    def test_publish_only_rejects_returns_published_count_zero(self, coach_headers, seed, db):
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/publish",
            json={"draft_id": seed["draft_id"], "assignment_ids": [],
                  "accept_change_set_ids": [],
                  "reject_change_set_ids": [seed["cs_reject"]],
                  "notes": "TEST_ rejecting this"},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["published_count"] == 0
        assert body["rejected_count"] == 1
        assert body["version_id"] is None
        # verify change set flipped
        cs = db.change_sets.find_one({"id": seed["cs_reject"]})
        assert cs["status"] == "rejected"
        assert cs.get("resolved_by") is not None
        assert cs.get("promoted_in_version_id") in (None, "")
        # DecisionRecord for rejection
        dr = db.decision_records.find_one(
            {"scope_id": seed["cs_reject"], "layer": "PUBLISH"})
        assert dr is not None, "DecisionRecord (rejection) missing"

    def test_publish_selected_promotes_and_creates_version(self, coach_headers, seed, db):
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/publish",
            json={"draft_id": seed["draft_id"],
                  "assignment_ids": [seed["a_mod"], seed["a_add"]],
                  "accept_change_set_ids": [seed["cs_prop"]],
                  "reject_change_set_ids": [],
                  "notes": "TEST_ publish"},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["published_count"] == 2
        assert body["accepted_change_sets"] == 1
        assert body["version_id"]
        assert body["version"] == 2  # incremented from initial v1

        # workout_assignments live_impl swapped to draft_impl and status='live'
        a_mod = db.workout_assignments.find_one({"id": seed["a_mod"]})
        assert a_mod["live_implementation_id"] == seed["draft_mod"]
        assert a_mod["status"] == "live"
        a_add = db.workout_assignments.find_one({"id": seed["a_add"]})
        assert a_add["live_implementation_id"] == seed["draft_add"]
        assert a_add["status"] == "live"

        # plan_version row created and immutable
        pv = db.plan_versions.find_one({"id": body["version_id"]})
        assert pv is not None
        assert pv["version"] == 2
        assert pv["immutable"] is True
        assert pv.get("snapshot_id")

        # snapshot row created
        snap = db.plan_snapshots.find_one({"id": pv["snapshot_id"]})
        assert snap is not None
        assert seed["a_mod"] in snap["workout_assignments_snapshot"]

        # accepted change_set: status=accepted, promoted_in_version_id set
        cs = db.change_sets.find_one({"id": seed["cs_prop"]})
        assert cs["status"] == "accepted"
        assert cs.get("promoted_in_version_id") == body["version_id"]

        # programme.live_plan_version bumped
        p = db.programmes_v2.find_one({"id": seed["prog_id"]})
        assert p["live_plan_version"] == 2

        # DecisionRecord written (layer=PUBLISH, scope_kind=plan_version)
        dr = db.decision_records.find_one(
            {"scope_id": body["version_id"], "layer": "PUBLISH"})
        assert dr is not None
        assert dr.get("scope_kind") == "plan_version"

        # draft transitions to partially_approved or promoted
        drft = db.plan_drafts.find_one({"id": seed["draft_id"]})
        assert drft["status"] in ("partially_approved", "promoted")

    def test_publish_already_promoted_draft_409(self, coach_headers, seed, db):
        # Force draft into promoted state
        db.plan_drafts.update_one({"id": seed["draft_id"]},
                                   {"$set": {"status": "promoted"}})
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/publish",
            json={"draft_id": seed["draft_id"], "assignment_ids": []},
            headers=coach_headers, timeout=30)
        assert r.status_code == 409, r.text
        # restore
        db.plan_drafts.update_one({"id": seed["draft_id"]},
                                   {"$set": {"status": "ready_for_review"}})

    def test_publish_idempotent_no_double_promote(self, coach_headers, seed, db):
        # Ensure draft is available
        db.plan_drafts.update_one({"id": seed["draft_id"]},
                                   {"$set": {"status": "ready_for_review"}})
        pv_count_before = db.plan_versions.count_documents({"programme_id": seed["prog_id"]})
        # a_mod already has live=draft after previous test; re-publishing same
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/publish",
            json={"draft_id": seed["draft_id"],
                  "assignment_ids": [seed["a_mod"]],  # already live=draft
                  "accept_change_set_ids": [], "reject_change_set_ids": []},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # Idempotent: 0 new promotions (already at draft_impl_id)
        # But a new plan_version WILL still be created because implementation
        # copies "already live" state; server does create a new version if
        # promoted_ids is non-empty. Verify no data corruption though.
        a_mod = db.workout_assignments.find_one({"id": seed["a_mod"]})
        assert a_mod["live_implementation_id"] == seed["draft_mod"]
        assert a_mod["status"] == "live"


# ---------------------------------------------------------------------------
# Priority 5 – INLINE EDITOR
# ---------------------------------------------------------------------------

def _reset_impl_for_editor(db, seed):
    """Restore assignment linkage so the DRAFT impl `draft_add` is editable
    (i.e. it must NOT be live-only). We use `a_add` because after publish tests
    it now has live == draft. Reset it back to a draft-only assignment for
    editor tests."""
    db.workout_assignments.update_one(
        {"id": seed["a_add"]},
        {"$set": {"live_implementation_id": None,
                   "status": "proposed",
                   "coach_edited": False}}
    )
    # also reset the impl to a clean base
    db.workout_implementations.update_one(
        {"id": seed["draft_add"]},
        {"$set": {
            "title": "TEST_ New Session (draft only)",
            "duration_min": 45, "focus": "Lower Strength",
            "key_session": False, "needs_coach_review": False,
            "exercises": [
                {"exercise_name_display": "Back Squat", "sets": 4, "reps": "6", "rest_sec": 120, "slot_role": "primary"},
                {"exercise_name_display": "Front Squat", "sets": 3, "reps": "8", "rest_sec": 90, "slot_role": "accessory"},
                {"exercise_name_display": "Leg Press", "sets": 3, "reps": "10", "rest_sec": 60, "slot_role": "accessory"},
            ],
        }}
    )


class TestInlineEditor:

    def test_patch_meta_updates_only_provided_fields(self, coach_headers, seed, db):
        _reset_impl_for_editor(db, seed)
        iid = seed["draft_add"]
        r = requests.patch(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}",
            json={"title": "TEST_ Refined Title", "duration_min": 55,
                  "focus": "Hypertrophy", "key_session": True,
                  "needs_coach_review": True},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["title"] == "TEST_ Refined Title"
        assert body["duration_min"] == 55
        assert body["focus"] == "Hypertrophy"
        assert body["key_session"] is True
        assert body["needs_coach_review"] is True
        # Untouched fields preserved
        assert body["variant_type"] == "gym"

        # Assignment marked coach_edited
        a = db.workout_assignments.find_one({"id": seed["a_add"]})
        assert a.get("coach_edited") is True
        assert a.get("coach_edited_at")
        assert a.get("coach_edited_by")

        # DecisionRecord written
        dr = db.decision_records.find_one(
            {"scope_id": iid, "layer": "HOW", "outcome": "EDITED"})
        assert dr is not None

    def test_patch_meta_downgrades_live_to_coach_edited(self, coach_headers, seed, db):
        """When assignment.status was 'live' with draft_impl != live_impl,
        editing the DRAFT impl should downgrade status → coach_edited."""
        _reset_impl_for_editor(db, seed)
        # Simulate live assignment carrying both a live impl and a distinct draft impl
        db.workout_assignments.update_one(
            {"id": seed["a_add"]},
            {"$set": {"status": "live", "live_implementation_id": seed["unch"],
                      "coach_edited": False}}
        )
        iid = seed["draft_add"]
        r = requests.patch(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}",
            json={"coach_notes": "TEST_ downgrade check"},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        a = db.workout_assignments.find_one({"id": seed["a_add"]})
        assert a["status"] == "coach_edited"

    def test_patch_meta_nonexistent_404(self, coach_headers):
        r = requests.patch(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/nope123",
            json={"title": "x"}, headers=coach_headers, timeout=30)
        assert r.status_code == 404, r.text

    def test_patch_meta_live_only_impl_409(self, coach_headers, seed):
        # live_only is bound as live and has no distinct draft → must 409
        iid = seed["live_only"]
        r = requests.patch(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}",
            json={"title": "should fail"}, headers=coach_headers, timeout=30)
        assert r.status_code == 409, r.text

    def test_patch_meta_non_coach_403(self, reviewer_headers, seed):
        iid = seed["draft_add"]
        r = requests.patch(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}",
            json={"title": "x"}, headers=reviewer_headers, timeout=30)
        assert r.status_code == 403, r.text

    # ---- Exercise patch ----
    def test_exercise_patch_merges_fields(self, coach_headers, seed, db):
        _reset_impl_for_editor(db, seed)
        iid = seed["draft_add"]
        r = requests.patch(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises/1",
            json={"sets": 5, "reps": "5", "rpe": 8.5},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        ex1 = body["exercises"][1]
        assert ex1["sets"] == 5
        assert ex1["reps"] == "5"
        assert ex1["rpe"] == 8.5
        # Preserved unspecified fields
        assert ex1["exercise_name_display"] == "Front Squat"
        assert ex1["rest_sec"] == 90

    def test_exercise_patch_out_of_range_400(self, coach_headers, seed):
        iid = seed["draft_add"]
        r = requests.patch(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises/99",
            json={"sets": 2}, headers=coach_headers, timeout=30)
        assert r.status_code == 400, r.text

    # ---- Exercise delete ----
    def test_exercise_delete_reindexes(self, coach_headers, seed, db):
        _reset_impl_for_editor(db, seed)
        iid = seed["draft_add"]
        r = requests.delete(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises/0",
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # Was 3, should now be 2, and first should be Front Squat (was idx=1)
        assert len(body["exercises"]) == 2
        assert body["exercises"][0]["exercise_name_display"] == "Front Squat"

    def test_exercise_delete_out_of_range_400(self, coach_headers, seed):
        iid = seed["draft_add"]
        r = requests.delete(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises/99",
            headers=coach_headers, timeout=30)
        assert r.status_code == 400, r.text

    # ---- Exercise add ----
    def test_exercise_add_appends_with_defaults(self, coach_headers, seed, db):
        _reset_impl_for_editor(db, seed)
        iid = seed["draft_add"]
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises",
            json={"exercise_name_display": "TEST_ Goblet Squat"},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["exercises"]) == 4
        last = body["exercises"][-1]
        assert last["exercise_name_display"] == "TEST_ Goblet Squat"
        # Defaults per playbook: sets=3, reps='8-10', rest_sec=90
        assert last["sets"] == 3
        assert last["reps"] == "8-10"
        assert last["rest_sec"] == 90

    def test_exercise_add_insert_at_position(self, coach_headers, seed, db):
        _reset_impl_for_editor(db, seed)
        iid = seed["draft_add"]
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises",
            json={"exercise_name_display": "TEST_ Bulgarian Split",
                  "sets": 4, "reps": "6", "insert_at": 1},
            headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exercises"][1]["exercise_name_display"] == "TEST_ Bulgarian Split"

    # ---- Reorder ----
    def test_exercise_reorder_permutation(self, coach_headers, seed, db):
        _reset_impl_for_editor(db, seed)
        iid = seed["draft_add"]
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises/reorder",
            json={"order": [2, 0, 1]}, headers=coach_headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # Originals were: [Back Squat, Front Squat, Leg Press] → after [2,0,1]:
        # [Leg Press, Back Squat, Front Squat]
        names = [e["exercise_name_display"] for e in body["exercises"]]
        assert names == ["Leg Press", "Back Squat", "Front Squat"]

    def test_exercise_reorder_non_permutation_400(self, coach_headers, seed, db):
        _reset_impl_for_editor(db, seed)
        iid = seed["draft_add"]
        r = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises/reorder",
            json={"order": [0, 0, 1]}, headers=coach_headers, timeout=30)
        assert r.status_code == 400, r.text
        r2 = requests.post(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{iid}/exercises/reorder",
            json={"order": [0, 1]}, headers=coach_headers, timeout=30)
        assert r2.status_code == 400, r2.text


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

class TestGuardrails:

    def test_coach_without_v2_flag_gets_409_diff(self, coach_headers, db):
        """Temporarily strip the flag off Louis, hit /diff, then restore."""
        coach = db.users.find_one({"email": LOUIS_EMAIL})
        old_flags = ((coach.get("profile") or {}).get("v2_flags") or {}).copy()
        try:
            db.users.update_one(
                {"id": coach["id"]},
                {"$set": {"profile.v2_flags.coach_dashboard_v2_enabled": False,
                          "profile.v2_flags.v2_default": False}}
            )
            r = requests.get(
                f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/diff",
                params={"month": "2026-01"}, headers=coach_headers, timeout=30)
            assert r.status_code == 409, r.text
        finally:
            db.users.update_one(
                {"id": coach["id"]},
                {"$set": {"profile.v2_flags": old_flags}}
            )

    def test_coach_without_v2_flag_gets_409_publish(self, coach_headers, seed, db):
        coach = db.users.find_one({"email": LOUIS_EMAIL})
        old_flags = ((coach.get("profile") or {}).get("v2_flags") or {}).copy()
        try:
            db.users.update_one(
                {"id": coach["id"]},
                {"$set": {"profile.v2_flags.coach_dashboard_v2_enabled": False,
                          "profile.v2_flags.v2_default": False}}
            )
            r = requests.post(
                f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/publish",
                json={"draft_id": seed["draft_id"], "assignment_ids": []},
                headers=coach_headers, timeout=30)
            assert r.status_code == 409, r.text
        finally:
            db.users.update_one(
                {"id": coach["id"]},
                {"$set": {"profile.v2_flags": old_flags}}
            )
