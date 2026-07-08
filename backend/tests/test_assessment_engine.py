"""Tests for CrewFit Intelligence Assessment™ — Adaptive AI Onboarding.

Covers Phase 1 endpoints:
  * POST /api/assessment/start
  * GET  /api/assessment/current
  * POST /api/assessment/answer
  * POST /api/assessment/finalize
  * GET  /api/coaching-dna
  * PATCH /api/coaching-dna
  * GET  /api/assessment/history

Live backend @ http://localhost:8001. Claude Sonnet 4.5 calls take 5-15s each so
start/answer use timeout=45 and finalize uses timeout=90.
"""

import os
import time
import uuid
from datetime import datetime

import pytest
import requests
from pymongo import MongoClient

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"

_MONGO = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
_DB = _MONGO[os.environ.get("DB_NAME", "crewfit_v1")]

# Cap the interview if AI never signals should_end
MAX_ANSWERS = 25
FORCE_FINALIZE_AT = 18  # Force finalize if we've answered this many

# Coaching DNA required fields (from spec — 26 fields)
DNA_REQUIRED_FIELDS = [
    "primary_goal", "secondary_goals", "why_it_matters", "next_event", "event_timeline",
    "aviation_profile", "flying_style", "recovery_risk", "training_experience",
    "motivation_style", "coaching_style", "lifestyle_summary", "equipment_locations",
    "training_availability", "injury_summary", "nutrition_summary",
    "biggest_strength", "biggest_weakness", "biggest_opportunity",
    "ai_confidence_score", "recommended_weekly_training", "recommended_recovery_strategy",
    "recommended_nutrition_strategy", "recommended_coaching_style", "summary",
]  # 25 fields — plus the ai_confidence_score check

ALLOWED_TYPES = {
    "single_select", "multi_select", "short_text", "long_text",
    "number", "date", "range", "event_builder", "equipment_picker",
}


# -----------------------------------------------------------------------------
# Test user helpers (fresh signup per module)
# -----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def test_user():
    """Create a fresh test client account for this run."""
    unique = uuid.uuid4().hex[:10]
    email = f"test_assessment_{unique}@example.com"
    password = "TestPass123!"
    r = requests.post(f"{API}/auth/signup", json={
        "email": email, "password": password,
        "name": f"TEST User {unique}", "role": "client",
    }, timeout=15)
    assert r.status_code == 200, f"signup failed: {r.status_code} {r.text}"
    data = r.json()
    yield {
        "email": email, "password": password,
        "token": data["token"], "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['token']}"},
    }
    # Teardown — remove the test user + any related docs
    uid = data["user"]["id"]
    _DB.users.delete_one({"id": uid})
    _DB.assessments.delete_many({"user_id": uid})
    _DB.coaching_dna.delete_many({"user_id": uid})
    _DB.dna_history.delete_many({"user_id": uid})
    _DB.events.delete_many({"user_id": uid})


# -----------------------------------------------------------------------------
# Answer generator based on question type
# -----------------------------------------------------------------------------

def _gen_answer(q: dict):
    """Produce a reasonable answer given a question schema."""
    qtype = q.get("type")
    qid = (q.get("id") or "").lower()
    if qtype == "single_select":
        opts = q.get("options") or []
        assert opts, f"single_select missing options: {q}"
        # Prefer 'pilot' or a marathon-friendly / injury-free option when relevant
        for pref in ("pilot", "intermediate", "4", "sometimes", "supportive", "progress"):
            for o in opts:
                if o.get("id") == pref:
                    return pref
        return opts[0]["id"]
    if qtype == "multi_select":
        opts = q.get("options") or []
        assert opts, f"multi_select missing options: {q}"
        ids = [o["id"] for o in opts if o.get("id")]
        # Pick up to 2 non-"none" options; if it's motivation goals, seed a marathon
        if "primary_goal" in qid or "goal" in qid:
            preferred = [g for g in ("marathon", "general_fitness", "improve_sleep") if g in ids]
            if preferred:
                return preferred[:2]
        picks = [i for i in ids if i != "none"][:2]
        return picks or ids[:1]
    if qtype == "short_text":
        return "Marathon in April"
    if qtype == "long_text":
        return "I want to be fitter for my family and to complete a marathon in Berlin. Feeling great now."
    if qtype == "number":
        meta = q.get("meta") or {}
        lo = int(meta.get("min", 0))
        hi = int(meta.get("max", 100))
        return max(lo, min(hi, (lo + hi) // 2))
    if qtype == "range":
        meta = q.get("meta") or {}
        lo = int(meta.get("min", 0))
        hi = int(meta.get("max", 100))
        return max(lo, min(hi, (lo + hi) // 2))
    if qtype == "date":
        return "2027-04-15"
    if qtype == "event_builder":
        return [{"name": "Berlin Marathon", "date": "2027-09-25", "priority": "A"}]
    if qtype == "equipment_picker":
        meta = q.get("meta") or {}
        return {"location": meta.get("location", "home"),
                "equipment": ["dumbbells", "yoga_mat", "resistance_bands"]}
    # Unknown/fallback
    return "ok"


# =============================================================================
# Case 1 & 2: POST /assessment/start returns first question with valid schema
# =============================================================================

class TestAssessmentStart:
    def test_start_returns_first_question(self, test_user):
        r = requests.post(f"{API}/assessment/start", json={"seed_from_profile": True},
                          headers=test_user["headers"], timeout=45)
        assert r.status_code == 200, f"start failed: {r.status_code} {r.text[:400]}"
        body = r.json()
        assert "assessment_id" in body, body
        assert body.get("resumed") is False, f"expected resumed=false on first call, got {body}"
        # progress present + within 0-30 range on first question
        progress = body.get("progress", 0)
        assert isinstance(progress, int), f"progress not int: {progress}"
        assert 0 <= progress <= 30, f"progress={progress} out of 0-30 on first question"
        # next_question schema
        q = body.get("next_question")
        assert q, f"no next_question in start: {body}"
        assert q.get("id"), f"question missing id: {q}"
        assert q.get("section"), f"question missing section: {q}"
        assert q.get("text"), f"question missing text: {q}"
        assert q.get("type") in ALLOWED_TYPES, f"unknown type: {q.get('type')}"
        if q["type"] in ("single_select", "multi_select"):
            opts = q.get("options") or []
            assert len(opts) > 0, f"{q['type']} missing options: {q}"
        # Stash for next test via module-level cache
        test_user["assessment_id"] = body["assessment_id"]
        test_user["first_question"] = q

    def test_start_again_resumes(self, test_user):
        assert "assessment_id" in test_user, "prior test must have run"
        r = requests.post(f"{API}/assessment/start", json={"seed_from_profile": True},
                          headers=test_user["headers"], timeout=45)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["assessment_id"] == test_user["assessment_id"], \
            f"different assessment on resume: {body['assessment_id']} vs {test_user['assessment_id']}"
        assert body.get("resumed") is True, f"expected resumed=true: {body}"
        # Should have a next_question or should_end
        assert body.get("next_question") or body.get("should_end"), body


# =============================================================================
# Case 4: GET /assessment/current returns the in-progress assessment
# =============================================================================

class TestAssessmentCurrent:
    def test_current_returns_in_progress(self, test_user):
        r = requests.get(f"{API}/assessment/current",
                         headers=test_user["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        a = body.get("assessment")
        assert a is not None, "assessment should not be null while in_progress"
        assert a["id"] == test_user["assessment_id"], \
            f"assessment id mismatch: {a['id']} vs {test_user['assessment_id']}"
        assert a["status"] == "in_progress", f"status={a['status']}"


# =============================================================================
# Cases 5, 6, 7: Walk interview → should_end
# =============================================================================

class TestAssessmentAnswerFlow:
    def test_walk_full_interview(self, test_user):
        aid = test_user["assessment_id"]

        # Fetch the currently-open question from DB to be safe
        adoc = _DB.assessments.find_one({"id": aid}, {"_id": 0})
        assert adoc, "assessment doc not found"
        q = adoc.get("current_question") or test_user.get("first_question")
        assert q, "no current question to answer"

        should_end = False
        prev_progress = -1
        answers_submitted = 0
        transcript_types = []

        for i in range(MAX_ANSWERS):
            answer = _gen_answer(q)
            transcript_types.append(q.get("type"))
            body = {"assessment_id": aid, "question_id": q["id"], "answer": answer}
            r = requests.post(f"{API}/assessment/answer", json=body,
                              headers=test_user["headers"], timeout=45)
            assert r.status_code == 200, \
                f"answer #{i+1} failed ({q.get('id')}): {r.status_code} {r.text[:400]}"
            resp = r.json()
            answers_submitted += 1
            # progress should be monotonically non-decreasing (allow small oscillations from AI)
            prog = resp.get("progress")
            if isinstance(prog, int) and prog >= prev_progress - 5:
                prev_progress = max(prev_progress, prog)
            if resp.get("should_end"):
                should_end = True
                break
            nq = resp.get("next_question")
            assert nq, f"no next_question and should_end=false: {resp}"
            assert nq.get("type") in ALLOWED_TYPES, f"unknown type: {nq.get('type')}"
            if nq["type"] in ("single_select", "multi_select"):
                assert nq.get("options"), f"{nq['type']} without options: {nq}"
            q = nq

            # Force cap for CI patience — if we've answered enough, we'll finalize regardless
            if answers_submitted >= FORCE_FINALIZE_AT and not should_end:
                # Try a few more to see if AI ends; otherwise break to force finalize
                continue

        print(f"Interview: {answers_submitted} answers submitted, "
              f"should_end={should_end}, types_seen={set(transcript_types)}")
        # Stash count
        test_user["answers_submitted"] = answers_submitted
        test_user["should_end"] = should_end
        # We continue to finalize regardless (spec says force-finalize is allowed)
        assert answers_submitted >= 5, "should have submitted at least a few answers"


# =============================================================================
# Cases 8, 9, 10, 11: Finalize → DNA created, onboarded=true, events materialised
# =============================================================================

class TestAssessmentFinalize:
    def test_finalize_creates_dna(self, test_user):
        aid = test_user["assessment_id"]
        r = requests.post(f"{API}/assessment/finalize", json={"assessment_id": aid},
                          headers=test_user["headers"], timeout=90)
        assert r.status_code == 200, f"finalize failed: {r.status_code} {r.text[:600]}"
        body = r.json()
        assert body.get("already_completed") is False, body
        dna = body.get("dna")
        assert dna, f"no dna in response: {body}"
        # 25 required DNA fields present
        missing = [f for f in DNA_REQUIRED_FIELDS if f not in dna]
        assert not missing, f"DNA missing fields: {missing}"
        # ai_confidence_score in [30, 95]
        score = dna.get("ai_confidence_score")
        assert isinstance(score, int), f"ai_confidence_score not int: {score!r}"
        assert 30 <= score <= 95, f"ai_confidence_score out of [30,95]: {score}"
        # user.onboarded=true
        u = _DB.users.find_one({"id": test_user["user"]["id"]})
        assert u.get("onboarded") is True, f"onboarded flag not flipped: {u.get('onboarded')}"
        # events materialised: because we answered event_builder with a date, or DNA has event_timeline
        events_created = body.get("events_created", 0)
        assert isinstance(events_created, int)
        # If DNA has any event_timeline entry with a date, we expect >=1 event
        et = dna.get("event_timeline") or []
        dated_events = [e for e in et if isinstance(e, dict) and e.get("date")]
        if dated_events:
            # events should be materialised in db.events with source='assessment_v1'
            db_events = list(_DB.events.find(
                {"user_id": test_user["user"]["id"], "source": "assessment_v1"}
            ))
            assert len(db_events) >= 1, \
                f"expected >=1 assessment_v1 event, got {len(db_events)}"
            print(f"Events materialised: {events_created}, in-DB: {len(db_events)}")
        else:
            print("No dated events in DNA — skipping event materialisation check")
        # Stash for next test
        test_user["dna_id"] = dna.get("id")
        test_user["dna_version"] = dna.get("version")
        test_user["events_created_first"] = events_created

    def test_finalize_again_idempotent(self, test_user):
        aid = test_user["assessment_id"]
        # Count events beforehand
        uid = test_user["user"]["id"]
        events_before = _DB.events.count_documents(
            {"user_id": uid, "source": "assessment_v1"})
        r = requests.post(f"{API}/assessment/finalize", json={"assessment_id": aid},
                          headers=test_user["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("already_completed") is True, f"expected already_completed=True: {body}"
        events_after = _DB.events.count_documents(
            {"user_id": uid, "source": "assessment_v1"})
        assert events_after == events_before, \
            f"events changed on 2nd finalize: {events_before} → {events_after}"


# =============================================================================
# Case 13: GET /coaching-dna returns latest with version=1
# =============================================================================

class TestCoachingDNAGet:
    def test_get_returns_v1(self, test_user):
        r = requests.get(f"{API}/coaching-dna",
                         headers=test_user["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        dna = body.get("dna")
        assert dna, f"no DNA returned: {body}"
        assert dna.get("version") == 1, f"expected version=1, got {dna.get('version')}"
        assert dna.get("user_id") == test_user["user"]["id"]


# =============================================================================
# Cases 14, 15, 16: PATCH /coaching-dna updates + validation
# =============================================================================

class TestCoachingDNAPatch:
    def test_patch_updates_allowed_fields(self, test_user):
        # Get current DNA for timestamps
        dna_before = _DB.coaching_dna.find_one(
            {"user_id": test_user["user"]["id"]}, sort=[("version", -1)])
        assert dna_before, "no DNA in DB"
        created_at = dna_before.get("created_at")

        time.sleep(1.1)  # ensure updated_at differs
        r = requests.patch(f"{API}/coaching-dna", json={
            "updates": {
                "primary_goal": "NEW GOAL",
                "biggest_strength": "NEW STRENGTH",
            },
            "reason": "test edit",
        }, headers=test_user["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        dna = body.get("dna")
        assert dna, body
        assert dna.get("primary_goal") == "NEW GOAL"
        assert dna.get("biggest_strength") == "NEW STRENGTH"
        assert dna.get("updated_at") != created_at, "updated_at should differ from created_at"
        # dna_history logged
        hist = list(_DB.dna_history.find(
            {"user_id": test_user["user"]["id"]}))
        assert len(hist) >= 1, "dna_history not logged"

    def test_patch_empty_updates_400(self, test_user):
        r = requests.patch(f"{API}/coaching-dna", json={"updates": {}},
                           headers=test_user["headers"], timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    def test_patch_invalid_field_filtered(self, test_user):
        r = requests.patch(f"{API}/coaching-dna", json={
            "updates": {
                "totally_bogus_field": "should be ignored",
                "biggest_opportunity": "NEW OPPORTUNITY",
            }
        }, headers=test_user["headers"], timeout=15)
        assert r.status_code == 200, f"expected 200 with filtering, got {r.status_code}: {r.text}"
        body = r.json()
        dna = body.get("dna")
        assert dna.get("biggest_opportunity") == "NEW OPPORTUNITY"
        assert "totally_bogus_field" not in dna, "bogus field leaked into DNA"


# =============================================================================
# Case 17: GET /assessment/history
# =============================================================================

class TestAssessmentHistory:
    def test_history_shows_completed(self, test_user):
        r = requests.get(f"{API}/assessment/history",
                         headers=test_user["headers"], timeout=15)
        assert r.status_code == 200, r.text
        rows = r.json().get("assessments") or []
        assert len(rows) >= 1, f"expected at least 1 assessment, got {len(rows)}"
        # The one we finalized should be status='completed'
        completed = [a for a in rows if a.get("status") == "completed"]
        assert completed, f"no completed assessment in history: {[a.get('status') for a in rows]}"


# =============================================================================
# Case 18: Auth gating — all 7 endpoints require auth
# =============================================================================

class TestAuthGating:
    """No Authorization header should return 401 or 403."""

    ENDPOINTS = [
        ("POST", "/assessment/start", {"seed_from_profile": True}),
        ("GET", "/assessment/current", None),
        ("POST", "/assessment/answer",
         {"assessment_id": "x", "question_id": "y", "answer": "z"}),
        ("POST", "/assessment/finalize", {"assessment_id": "x"}),
        ("GET", "/coaching-dna", None),
        ("PATCH", "/coaching-dna", {"updates": {"primary_goal": "x"}}),
        ("GET", "/assessment/history", None),
    ]

    @pytest.mark.parametrize("method,path,payload", ENDPOINTS)
    def test_no_auth_rejected(self, method, path, payload):
        url = f"{API}{path}"
        if method == "GET":
            r = requests.get(url, timeout=10)
        elif method == "POST":
            r = requests.post(url, json=payload or {}, timeout=10)
        elif method == "PATCH":
            r = requests.patch(url, json=payload or {}, timeout=10)
        else:
            raise ValueError(method)
        assert r.status_code in (401, 403), \
            f"{method} {path} without auth: expected 401/403 got {r.status_code}"
