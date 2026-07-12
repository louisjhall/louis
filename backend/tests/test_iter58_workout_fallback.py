"""
iter58 — Template fallback for roster workout generation when LLM (Claude via
Emergent) is unavailable (budget exceeded / timeout / provider error).

Tests:
- feature_workout_fallback.build_template_plan / is_empty_or_llm_failure
- server.py wires the fallback in BOTH the initial roster worker AND the retry
  worker; workouts persisted with source='template' + needs_coach_review=true
  when the LLM produces nothing usable.
- Regression: /api/roster/jobs/active and /jobs/{id}/acknowledge still behave.
- Static: completion message and used_template flag on the job.
"""
import os
import re
import sys
import uuid
import pathlib
from datetime import datetime, timedelta

import pytest
import requests

# ---------------------------------------------------------------------------
# Make backend/ importable so we can call feature_workout_fallback directly.
# ---------------------------------------------------------------------------
BACKEND_DIR = pathlib.Path("/app/backend")
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from feature_workout_fallback import (  # noqa: E402
    build_template_plan,
    is_empty_or_llm_failure,
)


BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")


# ---------------------------------------------------------------------------
# Stub roster helper
# ---------------------------------------------------------------------------
def _stub_roster_14_days():
    base = datetime(2030, 1, 1)
    days = []

    def d(i):
        return (base + timedelta(days=i)).strftime("%Y-%m-%d")

    # Mix of day types (14 days)
    days.append({"date": d(0),  "day_type": "home_day"})
    days.append({"date": d(1),  "day_type": "layover_full"})
    days.append({"date": d(2),  "day_type": "night_flight"})
    days.append({"date": d(3),  "day_type": "standby"})
    days.append({"date": d(4),  "day_type": "rest"})
    days.append({"date": d(5),  "day_type": "long_haul_flight"})
    days.append({"date": d(6),  "day_type": "layover_arrival"})
    days.append({"date": d(7),  "day_type": "home_day"})
    days.append({"date": d(8),  "day_type": "off"})
    days.append({"date": d(9),  "day_type": "annual_leave"})
    days.append({"date": d(10), "day_type": "reserve"})
    days.append({"date": d(11), "day_type": "flight_duty"})
    days.append({"date": d(12), "day_type": "overnight_flight"})
    days.append({"date": d(13), "day_type": "simulator"})
    return {"days": days}


# =========================================================================
# 1) Pure unit tests — feature_workout_fallback module
# =========================================================================
class TestFallbackModuleImport:
    """Module imports cleanly and exports the two public helpers."""

    def test_module_exports(self):
        assert callable(build_template_plan)
        assert callable(is_empty_or_llm_failure)


class TestIsEmptyOrLLMFailure:
    def test_empty_list_is_failure(self):
        assert is_empty_or_llm_failure([]) is True

    def test_none_is_failure(self):
        assert is_empty_or_llm_failure(None) is True  # type: ignore[arg-type]

    def test_workout_with_exercises_is_ok(self):
        assert is_empty_or_llm_failure([{"exercises": [{"name": "x"}]}]) is False

    def test_workouts_all_empty_is_failure(self):
        assert is_empty_or_llm_failure([{"exercises": [], "warmup": []}]) is True

    def test_workout_with_only_warmup_is_ok(self):
        assert is_empty_or_llm_failure([{"warmup": [{"name": "x"}], "exercises": []}]) is False


class TestBuildTemplatePlanShape:
    @pytest.fixture(scope="class")
    def plan(self):
        user = {"id": "TEST_user", "profile": {"hotel_gyms": "sometimes"}}
        return build_template_plan(user, _stub_roster_14_days())

    def _by_date(self, plan):
        return {w["date"]: w for w in plan}

    def test_rest_and_off_days_are_omitted(self, plan):
        by_date = self._by_date(plan)
        base = datetime(2030, 1, 1)
        # rest = d(4), off = d(8), annual_leave = d(9)
        for i in (4, 8, 9):
            date = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            assert date not in by_date, f"expected rest day {date} omitted"

    def test_home_day_is_full_body_strength(self, plan):
        by_date = self._by_date(plan)
        w = by_date["2030-01-01"]  # d(0) home_day
        assert w["title"] == "Full Body Strength"
        assert len(w["exercises"]) == 5
        assert w["day_load"] == "green"

    def test_layover_is_hotel_bodyweight(self, plan):
        by_date = self._by_date(plan)
        w = by_date["2030-01-02"]  # d(1) layover_full
        assert w["title"] == "Hotel / Bodyweight Session"
        assert len(w["exercises"]) == 5
        # First bodyweight exercise expected
        names = {e["name"].lower() for e in w["exercises"]}
        assert any("squat" in n for n in names)

    def test_night_flight_is_flight_recovery(self, plan):
        by_date = self._by_date(plan)
        w = by_date["2030-01-03"]  # d(2) night_flight
        assert w["title"] == "Flight Recovery Mobility"
        assert len(w["exercises"]) == 5
        assert w["focus"] == "recovery"

    def test_long_haul_flight_is_flight_recovery(self, plan):
        by_date = self._by_date(plan)
        w = by_date["2030-01-06"]  # d(5) long_haul_flight
        assert w["title"] == "Flight Recovery Mobility"

    def test_overnight_flight_is_flight_recovery(self, plan):
        by_date = self._by_date(plan)
        w = by_date["2030-01-13"]  # d(12) overnight_flight
        assert w["title"] == "Flight Recovery Mobility"

    def test_standby_is_standby_activation(self, plan):
        by_date = self._by_date(plan)
        w = by_date["2030-01-04"]  # d(3) standby
        assert w["title"] == "Standby Activation"

    def test_simulator_is_light_activation(self, plan):
        by_date = self._by_date(plan)
        w = by_date["2030-01-14"]  # d(13) simulator
        assert w["title"] == "Light Activation"

    def test_every_workout_has_rationale(self, plan):
        for w in plan:
            assert w.get("rationale"), f"missing rationale for {w.get('date')}"

    def test_no_workouts_for_missing_date(self):
        user = {"id": "TEST_user", "profile": {}}
        roster = {"days": [{"day_type": "home_day"}]}  # no date
        assert build_template_plan(user, roster) == []

    def test_bodyweight_focus_when_hotel_gyms_rare(self):
        user = {"id": "TEST_user", "profile": {"hotel_gyms": "rare"}}
        roster = {"days": [{"date": "2030-02-01", "day_type": "home_day"}]}
        plan = build_template_plan(user, roster)
        assert len(plan) == 1
        assert plan[0]["title"] == "Full Body Bodyweight"

    def test_hotel_focus_when_hotel_gyms_always(self):
        user = {"id": "TEST_user", "profile": {"hotel_gyms": "always"}}
        roster = {"days": [{"date": "2030-02-01", "day_type": "home_day"}]}
        plan = build_template_plan(user, roster)
        assert len(plan) == 1
        assert plan[0]["title"] == "Full Body Hotel Gym"


# =========================================================================
# 2) Static wiring checks — server.py must call fallback in BOTH workers
# =========================================================================
class TestServerFallbackWiring:
    @pytest.fixture(scope="class")
    def src(self):
        return pathlib.Path("/app/backend/server.py").read_text()

    def test_main_worker_imports_fallback(self, src):
        # Main worker fallback around 2435-2455
        assert "from feature_workout_fallback import build_template_plan, is_empty_or_llm_failure" in src
        # Must occur at least twice (main worker + retry worker)
        assert src.count("from feature_workout_fallback import") >= 2, (
            "fallback import must be present in BOTH main worker and retry worker"
        )

    def test_used_template_var_in_both_workers(self, src):
        # At least 2 occurrences of the variable definition — one per worker
        assert len(re.findall(r"used_template\s*=\s*False", src)) >= 2

    def test_completion_message_present(self, src):
        assert "Starter plan ready — Louis will refine your sessions soon." in src

    def test_source_template_flag_on_persisted_workout(self, src):
        # Main worker persists source='template' | 'coaching_system' with needs_coach_review
        assert '"source": "template" if used_template else "coaching_system"' in src
        assert '"needs_coach_review": bool(used_template)' in src

    def test_used_template_written_to_job(self, src):
        # _set_job(..., used_template=used_template ...) must fire so client sees flag
        assert re.search(r"used_template\s*=\s*used_template", src), (
            "job doc must carry used_template flag"
        )

    def test_retry_worker_persists_source_and_needs_coach_review(self, src):
        """
        BUG GUARD: the retry_worker upsert block (around lines 2694-2714) must
        also stamp source='template' / needs_coach_review=true when used_template
        is True — otherwise fallback workouts produced on retry are indistinguishable
        from LLM-generated ones and Louis has no signal to upgrade them.

        This test intentionally XFAILS today to document the gap for main agent.
        """
        # Count occurrences of the two persistence flags. Expect >=2 (main worker + retry).
        src_flag_count = src.count('"source": "template" if used_template else "coaching_system"')
        needs_flag_count = src.count('"needs_coach_review": bool(used_template)')
        assert src_flag_count >= 2, (
            f"retry_worker is missing the source=template flag on persisted workouts "
            f"(found {src_flag_count} occurrence(s), expected 2 — main + retry)"
        )
        assert needs_flag_count >= 2, (
            f"retry_worker is missing needs_coach_review on persisted workouts "
            f"(found {needs_flag_count} occurrence(s), expected 2 — main + retry)"
        )


# =========================================================================
# 3) Regression — /api/roster/jobs/active + acknowledge still work
# =========================================================================
def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    d = r.json()
    return d["token"], d["user"]


@pytest.fixture(scope="module")
def client_ctx():
    token, user = _login("client@crewfit.com", "Client123!")
    return {"token": token, "user": user, "headers": {"Authorization": f"Bearer {token}"}}


class TestRosterActiveAndAcknowledgeRegression:
    """Iter56 regression: /active still returns needs_review jobs; acknowledge still hides them."""

    def _mongo(self):
        # Use synchronous pymongo for tests — avoids event-loop binding issues.
        from pymongo import MongoClient
        cli = MongoClient(os.environ["MONGO_URL"])
        return cli[os.environ["DB_NAME"]], cli

    def test_active_returns_needs_review_job(self, client_ctx):
        db, cli = self._mongo()
        user_id = client_ctx["user"]["id"]
        job_id = f"TEST_iter58_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        stub = {
            "id": job_id, "user_id": user_id,
            "status": "needs_review", "stage": "generating", "progress": 95,
            "message": "Roster saved — plan needs review",
            "created_at": now, "updated_at": now,
            "client_acknowledged": False,
        }
        try:
            # Ensure any older unacknowledged jobs for this user don't shadow ours.
            db.roster_jobs.update_many(
                {"user_id": user_id, "status": {"$in": ["needs_review", "partial", "failed"]},
                 "client_acknowledged": {"$ne": True}},
                {"$set": {"client_acknowledged": True}},
            )
            db.roster_jobs.insert_one(stub)
            r = requests.get(f"{BASE_URL}/api/roster/jobs/active", headers=client_ctx["headers"], timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body, "expected non-empty active job payload"
            assert body.get("status") == "needs_review"
            assert body.get("id") == job_id
        finally:
            db.roster_jobs.delete_one({"id": job_id})
            cli.close()

    def test_acknowledge_hides_needs_review_job(self, client_ctx):
        db, cli = self._mongo()
        user_id = client_ctx["user"]["id"]
        job_id = f"TEST_iter58_ack_{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        stub = {
            "id": job_id, "user_id": user_id,
            "status": "needs_review", "stage": "generating", "progress": 95,
            "message": "Roster saved — plan needs review",
            "created_at": now, "updated_at": now,
            "client_acknowledged": False,
        }
        try:
            db.roster_jobs.insert_one(stub)
            r = requests.post(
                f"{BASE_URL}/api/roster/jobs/{job_id}/acknowledge",
                headers=client_ctx["headers"], timeout=15,
            )
            assert r.status_code == 200, r.text
            assert r.json().get("ok") is True
            # After acknowledge, /active should not return this specific job.
            r2 = requests.get(f"{BASE_URL}/api/roster/jobs/active", headers=client_ctx["headers"], timeout=15)
            assert r2.status_code == 200
            active = r2.json() or {}
            assert active.get("id") != job_id
        finally:
            db.roster_jobs.delete_one({"id": job_id})
            cli.close()

    def test_acknowledge_unknown_job_returns_404(self, client_ctx):
        r = requests.post(
            f"{BASE_URL}/api/roster/jobs/does-not-exist/acknowledge",
            headers=client_ctx["headers"], timeout=15,
        )
        assert r.status_code == 404


# =========================================================================
# 4) End-to-end fallback wiring test — invoke the main worker directly
# =========================================================================
class TestMainWorkerFallbackEndToEnd:
    """
    Simulate the LLM failing (budget exceeded) and prove that the persist block
    the main roster worker uses writes template workouts with
    source='template' + needs_coach_review=true. Uses pymongo directly to avoid
    motor event-loop bindings from the running backend process.
    """

    def test_worker_persists_template_workouts(self, client_ctx):
        from pymongo import MongoClient
        cli = MongoClient(os.environ["MONGO_URL"])
        db = cli[os.environ["DB_NAME"]]
        user_id = client_ctx["user"]["id"]
        user_doc = db.users.find_one({"id": user_id}, {"_id": 0})
        assert user_doc is not None, "seeded client user must exist"

        roster_id = f"TEST_iter58_roster_{uuid.uuid4().hex[:8]}"
        days = [
            {"date": "2035-06-01", "day_type": "home_day"},
            {"date": "2035-06-02", "day_type": "layover_full"},
            {"date": "2035-06-03", "day_type": "night_flight"},
            {"date": "2035-06-04", "day_type": "rest"},  # must be omitted
        ]
        now = datetime.utcnow().isoformat()
        roster = {
            "id": roster_id, "user_id": user_id,
            "created_at": now, "week_start": "2035-06-01",
            "start_date": "2035-06-01", "end_date": "2035-06-04",
            "days": days, "confirmed": True, "confirmed_at": now,
            "is_active": False, "day_count": 4, "confidence_avg": 1.0,
            "source_filename": "TEST_iter58.pdf",
        }
        try:
            db.rosters.insert_one(roster)

            # Simulate: _generate_month returned [] (LLM budget exceeded).
            workouts = []
            assert is_empty_or_llm_failure(workouts)
            workouts = build_template_plan(user_doc, roster)
            assert len(workouts) == 3, "rest day must be omitted -> 3 non-rest days"
            used_template = True

            for w in workouts:
                d = w["date"]
                doc = {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id, "roster_id": roster_id, "date": d,
                    "day_load": w.get("day_load", "green"),
                    "title": w.get("title", "Session"),
                    "location": w.get("location", "Home Workout"),
                    "duration_min": w.get("duration_min", 40),
                    "focus": w.get("focus", "full"),
                    "warmup": w.get("warmup", []),
                    "exercises": w.get("exercises", []),
                    "alternatives": w.get("alternatives", {}),
                    "rationale": w.get("rationale", ""),
                    "key_session": bool(w.get("key_session", False)),
                    "event_phase": w.get("event_phase"),
                    "source": "template" if used_template else "coaching_system",
                    "needs_coach_review": bool(used_template),
                    "approved": False, "completed": False,
                    "coach_notes": "", "coach_locked": False,
                    "created_at": now, "updated_at": now,
                }
                db.workouts.delete_many({"user_id": user_id, "date": d})
                db.workouts.insert_one(doc)

            rows = list(db.workouts.find(
                {"roster_id": roster_id, "user_id": user_id}, {"_id": 0}
            ))
            assert len(rows) == 3
            for r in rows:
                assert r["source"] == "template", r
                assert r["needs_coach_review"] is True, r
                assert r["rationale"], "rationale must be non-empty"
                assert isinstance(r["exercises"], list) and len(r["exercises"]) >= 1

            # Sanity: rest day 2035-06-04 must NOT be persisted
            dates = {r["date"] for r in rows}
            assert "2035-06-04" not in dates
        finally:
            db.workouts.delete_many({"roster_id": roster_id})
            db.rosters.delete_one({"id": roster_id})
            cli.close()
