"""Iter77 Plan D + Reassessment micro-form regression tests.

Coverage:
  T1  hook_exercise_request_task (create + dedup + escalate)
  T2  reconcile_exercise_review_tasks (orphan back-fill)
  T3  GET /api/coach/exercise-reviews/counts
  T4  GET /api/roster/management
  T5  POST /api/roster/delete-and-restart (both modes + guards)
  T6  server.py — safety guard code inspection
  T7  GET /api/reassessment/short-form (all kinds + 404)
  T8  POST /api/reassessment/short-form (persist + coach task + prompt dismiss + coaching_dna untouched)
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import re
import sys
import uuid
from pathlib import Path

import pytest
import requests

# Ensure backend module import works for direct-call tests (T1/T2)
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or "https://flight-fit-plans.preview.emergentagent.com"
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PWD = "Client123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PWD = "Louis123!"


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
def client_token_and_id() -> tuple[str, str]:
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PWD}, timeout=20)
    assert r.status_code == 200, f"client login failed: {r.text}"
    d = r.json()
    tok = d.get("access_token") or d.get("token")
    me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=20).json()
    return tok, me["id"]


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# Async helpers for direct DB access (T1/T2/T5/T8)
# ---------------------------------------------------------------------------

# Single event loop across whole session — motor client is bound to the first loop
_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


# =====================================================================
# T1 — hook_exercise_request_task
# =====================================================================

class TestT1ExerciseHook:
    def test_hook_creates_then_dedups_and_escalates(self):
        from server import db, new_id, now_iso  # type: ignore
        from feature_exercise_request_tasks import hook_exercise_request_task, TASK_TYPE  # type: ignore

        async def run():
            ex_id = f"TEST_ex_{uuid.uuid4().hex[:8]}"
            user_a = {"id": f"TEST_u_{uuid.uuid4().hex[:6]}", "name": "Alpha", "email": "a@test"}
            user_b = {"id": f"TEST_u_{uuid.uuid4().hex[:6]}", "name": "Beta", "email": "b@test"}
            prog_a = f"TEST_prog_{uuid.uuid4().hex[:6]}"
            prog_b = f"TEST_prog_{uuid.uuid4().hex[:6]}"

            # Seed a workout in 30 days (normal priority) so we have a baseline
            far_wk_id = f"TEST_w_{uuid.uuid4().hex[:6]}"
            far_date = (_dt.date.today() + _dt.timedelta(days=25)).isoformat()
            await db.workouts.insert_one({
                "id": far_wk_id, "user_id": user_a["id"], "date": far_date,
                "exercises": [{"exercise_id": ex_id, "name": "TEST"}],
                "completed": False,
            })
            exercise = {
                "id": ex_id, "exercise_name": "TEST Wall Squat",
                "movement_pattern": "squat", "equipment_type": "wall",
            }
            tid1 = await hook_exercise_request_task(exercise, user_a, prog_a, far_wk_id)
            assert tid1, "expected task id"
            t1 = await db.coach_tasks.find_one({"id": tid1}, {"_id": 0})
            assert t1["task_type"] == TASK_TYPE
            assert t1["priority"] == "normal"  # 25 days away
            assert user_a["id"] in (t1["payload"]["clients_affected"] or [])

            # Second call — different client + urgent workout (tomorrow) → escalate to urgent
            near_wk_id = f"TEST_w_{uuid.uuid4().hex[:6]}"
            near_date = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
            await db.workouts.insert_one({
                "id": near_wk_id, "user_id": user_b["id"], "date": near_date,
                "exercises": [{"exercise_id": ex_id, "name": "TEST"}],
                "completed": False,
            })
            tid2 = await hook_exercise_request_task(exercise, user_b, prog_b, near_wk_id)
            assert tid2 == tid1, "dedup: should reuse the same task"
            t2 = await db.coach_tasks.find_one({"id": tid1}, {"_id": 0})
            assert t2["priority"] == "urgent", f"expected escalation to urgent, got {t2['priority']}"
            assert user_a["id"] in t2["payload"]["clients_affected"]
            assert user_b["id"] in t2["payload"]["clients_affected"]
            assert prog_a in t2["payload"]["programmes_affected"]
            assert prog_b in t2["payload"]["programmes_affected"]
            assert t2["payload"]["request_count"] >= 2

            # Verify NO duplicate
            count = await db.coach_tasks.count_documents({
                "task_type": TASK_TYPE, "payload.exercise_id": ex_id,
                "status": {"$in": ["todo", "in_progress", "snoozed"]},
            })
            assert count == 1, f"expected exactly 1 task, found {count}"

            # Cleanup
            await db.workouts.delete_many({"id": {"$in": [far_wk_id, near_wk_id]}})
            await db.coach_tasks.delete_one({"id": tid1})

        _run(run())


# =====================================================================
# T2 — reconciliation
# =====================================================================

class TestT2Reconciliation:
    def test_reconcile_backfills_orphan(self):
        from server import db  # type: ignore
        from feature_exercise_request_tasks import reconcile_exercise_review_tasks, TASK_TYPE  # type: ignore

        async def run():
            ex_id = f"TEST_orphan_{uuid.uuid4().hex[:8]}"
            await db.exercises_v2.insert_one({
                "id": ex_id,
                "exercise_name": "TEST Orphan Row",
                "status": "draft_requested",
                "needs_louis_review": True,
                "request_count": 1,
            })
            result = await reconcile_exercise_review_tasks()
            assert result["checked"] >= 1
            assert result["orphans_fixed"] >= 1
            row = await db.coach_tasks.find_one({
                "task_type": TASK_TYPE, "payload.exercise_id": ex_id,
            }, {"_id": 0})
            assert row is not None, "expected task after reconcile"
            assert row["payload"]["source"] == "reconciliation"
            assert row["payload"]["recovered"] is True

            # Cleanup
            await db.exercises_v2.delete_one({"id": ex_id})
            await db.coach_tasks.delete_one({"id": row["id"]})

        _run(run())


# =====================================================================
# T3 — counts endpoint
# =====================================================================

class TestT3Counts:
    def test_counts_endpoint(self, coach_token):
        r = requests.get(f"{API}/coach/exercise-reviews/counts", headers=_auth(coach_token), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("unresolved", "needed_soon", "urgent", "high", "media_needed", "at"):
            assert k in data, f"missing {k}"
        for k in ("unresolved", "needed_soon", "urgent", "high", "media_needed"):
            assert isinstance(data[k], int) and data[k] >= 0

    def test_list_endpoint_bucket_filters(self, coach_token):
        for bucket in ("needed_soon", "drafts_waiting", "media_needed", "history"):
            r = requests.get(
                f"{API}/coach/exercise-reviews/list",
                params={"filter_bucket": bucket},
                headers=_auth(coach_token), timeout=20,
            )
            assert r.status_code == 200, f"{bucket}: {r.text}"
            assert "tasks" in r.json()


# =====================================================================
# T4 — roster/management
# =====================================================================

class TestT4RosterManagement:
    def test_roster_management_shape(self, client_token_and_id):
        tok, _ = client_token_and_id
        r = requests.get(f"{API}/roster/management", headers=_auth(tok), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("active_roster", "programme", "upcoming_workouts_count",
                  "coach_locked_upcoming_count", "pending_replacement", "versions_total"):
            assert k in data, f"missing {k}"
        assert isinstance(data["upcoming_workouts_count"], int)
        assert isinstance(data["coach_locked_upcoming_count"], int)
        assert isinstance(data["versions_total"], int)


# =====================================================================
# T5 — delete-and-restart flow
# =====================================================================

class TestT5DeleteAndRestart:
    def test_full_delete_flow_with_seed(self):
        """Direct-DB test: seed test user + roster + workouts, then call the endpoint."""
        from server import db, now_iso  # type: ignore

        async def run():
            uid = f"TEST_del_{uuid.uuid4().hex[:8]}"
            roster_id = f"TEST_r_{uuid.uuid4().hex[:6]}"
            prog_id = f"TEST_p_{uuid.uuid4().hex[:6]}"
            future_a = f"TEST_wa_{uuid.uuid4().hex[:6]}"
            future_locked = f"TEST_wl_{uuid.uuid4().hex[:6]}"
            past_done = f"TEST_wp_{uuid.uuid4().hex[:6]}"
            job_id = f"TEST_j_{uuid.uuid4().hex[:6]}"
            tomorrow = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
            day_after = (_dt.date.today() + _dt.timedelta(days=2)).isoformat()
            yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()

            # Seed a real login-capable test user (preview flag ON so we skip typed DELETE requirement for the 2nd test)
            # For the first test we DO enforce typed_delete=DELETE.
            import bcrypt
            pwd_hash = bcrypt.hashpw(b"testpwd", bcrypt.gensalt()).decode()
            await db.users.insert_one({
                "id": uid, "email": f"{uid.lower()}@crewfit-test.com", "name": "Test Delete User",
                "password_hash": pwd_hash, "role": "client",
            })
            await db.rosters.insert_one({
                "id": roster_id, "user_id": uid, "is_active": True,
                "status": "active", "week_start": yesterday, "week_end": tomorrow,
                "created_at": now_iso(),
            })
            await db.programmes.insert_one({
                "id": prog_id, "user_id": uid, "roster_id": roster_id,
                "status": "active", "created_at": now_iso(),
            })
            await db.workouts.insert_many([
                {"id": future_a, "user_id": uid, "roster_id": roster_id,
                 "date": tomorrow, "completed": False, "coach_locked": False},
                {"id": future_locked, "user_id": uid, "roster_id": roster_id,
                 "date": day_after, "completed": False, "coach_locked": True},
                {"id": past_done, "user_id": uid, "roster_id": roster_id,
                 "date": yesterday, "completed": True, "coach_locked": False},
            ])
            await db.gen_jobs.insert_one({
                "id": job_id, "user_id": uid, "roster_id": roster_id, "status": "queued",
            })

            # Login the test user
            login_r = requests.post(f"{API}/auth/login",
                                    json={"email": f"{uid.lower()}@crewfit-test.com", "password": "testpwd"},
                                    timeout=20)
            assert login_r.status_code == 200, f"seed user login failed: {login_r.text}"
            tok = login_r.json().get("access_token") or login_r.json().get("token")

            # --- Guard 1: missing typed_delete on real account ---
            r = requests.post(f"{API}/roster/delete-and-restart",
                              json={"mode": "delete_and_future_plan", "confirm": True},
                              headers=_auth(tok), timeout=20)
            assert r.status_code == 400, f"expected 400 without typed_delete, got {r.status_code}: {r.text}"

            # --- Guard 2: confirm=False ---
            r = requests.post(f"{API}/roster/delete-and-restart",
                              json={"mode": "delete_and_future_plan", "confirm": False, "typed_delete": "DELETE"},
                              headers=_auth(tok), timeout=20)
            assert r.status_code == 400

            # --- Happy path: delete_and_future_plan ---
            r = requests.post(f"{API}/roster/delete-and-restart",
                              json={"mode": "delete_and_future_plan", "confirm": True,
                                    "typed_delete": "DELETE", "reason": "iter77 test"},
                              headers=_auth(tok), timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is True
            assert body["roster_status"] == "awaiting_roster"
            cs = body["cleanup_summary"]
            assert cs["roster_id"] == roster_id
            assert cs["workouts_deactivated"] == 1
            assert cs["coach_locked_preserved"] == 1
            assert cs["programme_deactivated_id"] == prog_id
            assert cs["jobs_cancelled"] >= 1

            # DB assertions
            rr = await db.rosters.find_one({"id": roster_id}, {"_id": 0})
            assert rr["status"] == "deleted_by_client"
            assert rr["is_active"] is False
            assert rr.get("deleted_at") and rr.get("deleted_by") == uid

            fa = await db.workouts.find_one({"id": future_a}, {"_id": 0})
            assert fa.get("deactivated") is True
            assert fa.get("deactivated_reason") == "roster_deleted"

            fl = await db.workouts.find_one({"id": future_locked}, {"_id": 0})
            assert fl.get("deactivated") is not True, "coach-locked must NOT be deactivated"

            pd = await db.workouts.find_one({"id": past_done}, {"_id": 0})
            assert pd.get("deactivated") is not True, "completed workout must NOT be deactivated"

            prow = await db.programmes.find_one({"id": prog_id}, {"_id": 0})
            assert prow["status"] == "awaiting_roster"
            assert prow.get("deactivated") is True

            jr = await db.gen_jobs.find_one({"id": job_id}, {"_id": 0})
            assert jr["status"] == "cancelled"

            u = await db.users.find_one({"id": uid}, {"_id": 0})
            assert u.get("roster_status") == "awaiting_roster"

            audit_events = await db.roster_audit_log.find(
                {"user_id": uid}, {"_id": 0}).to_list(50)
            events = {a["event"] for a in audit_events}
            expected_events = {"roster.deletion_requested", "roster.deactivated",
                               "workouts.deactivated", "programme.deactivated",
                               "gen_jobs.cancelled", "roster.deleted"}
            missing = expected_events - events
            assert not missing, f"missing audit events: {missing}"

            # Coach task created
            ct = await db.coach_tasks.find_one(
                {"task_type": "roster_deleted", "payload.client_id": uid}, {"_id": 0})
            assert ct is not None, "roster_deleted coach task not created"
            assert ct["payload"]["cleanup_summary"]["workouts_deactivated"] == 1

            # --- Guard 3: no active roster now → 400 ---
            r = requests.post(f"{API}/roster/delete-and-restart",
                              json={"mode": "delete_and_future_plan", "confirm": True,
                                    "typed_delete": "DELETE"},
                              headers=_auth(tok), timeout=20)
            assert r.status_code == 400

            # ---- Cleanup ----
            await db.rosters.delete_many({"user_id": uid})
            await db.programmes.delete_many({"user_id": uid})
            await db.workouts.delete_many({"user_id": uid})
            await db.gen_jobs.delete_many({"user_id": uid})
            await db.users.delete_one({"id": uid})
            await db.roster_audit_log.delete_many({"user_id": uid})
            if ct:
                await db.coach_tasks.delete_one({"id": ct["id"]})

        _run(run())

    def test_delete_only_mode_preserves_workouts(self):
        from server import db, now_iso  # type: ignore
        import bcrypt

        async def run():
            uid = f"TEST_del2_{uuid.uuid4().hex[:8]}"
            roster_id = f"TEST_r2_{uuid.uuid4().hex[:6]}"
            future_a = f"TEST_wo_{uuid.uuid4().hex[:6]}"
            tomorrow = (_dt.date.today() + _dt.timedelta(days=1)).isoformat()

            pwd_hash = bcrypt.hashpw(b"testpwd", bcrypt.gensalt()).decode()
            await db.users.insert_one({
                "id": uid, "email": f"{uid.lower()}@crewfit-test.com", "name": "T2",
                "password_hash": pwd_hash, "role": "client",
            })
            await db.rosters.insert_one({
                "id": roster_id, "user_id": uid, "is_active": True,
                "status": "active", "created_at": now_iso(),
            })
            await db.workouts.insert_one({
                "id": future_a, "user_id": uid, "roster_id": roster_id,
                "date": tomorrow, "completed": False, "coach_locked": False,
            })

            login_r = requests.post(f"{API}/auth/login",
                                    json={"email": f"{uid.lower()}@crewfit-test.com", "password": "testpwd"},
                                    timeout=20)
            tok = login_r.json().get("access_token") or login_r.json().get("token")

            r = requests.post(f"{API}/roster/delete-and-restart",
                              json={"mode": "delete_only", "confirm": True,
                                    "typed_delete": "DELETE"},
                              headers=_auth(tok), timeout=30)
            assert r.status_code == 200, r.text
            cs = r.json()["cleanup_summary"]
            assert cs["workouts_deactivated"] == 0
            assert cs["programme_deactivated_id"] is None
            assert cs["jobs_cancelled"] == 0

            wo = await db.workouts.find_one({"id": future_a}, {"_id": 0})
            assert wo.get("deactivated") is not True, "delete_only must NOT deactivate workouts"

            # Cleanup
            await db.rosters.delete_many({"user_id": uid})
            await db.workouts.delete_many({"user_id": uid})
            await db.users.delete_one({"id": uid})
            await db.roster_audit_log.delete_many({"user_id": uid})
            await db.coach_tasks.delete_many({"payload.client_id": uid})

        _run(run())


# =====================================================================
# T6 — safety guard code inspection
# =====================================================================

class TestT6SafetyGuard:
    def test_safety_guard_code_present(self):
        src = Path("/app/backend/server.py").read_text()
        # Must have the D5 guard block
        assert "Safety guard (Plan D5)" in src, "missing 'Safety guard (Plan D5)' block"
        # Must re-query rosters and check is_active/deleted_by_client
        assert 'db.rosters.find_one' in src and 'deleted_by_client' in src, "missing rosters re-query with deleted_by_client check"
        assert re.search(r'not _roster_check\.get\("is_active"\).*or.*deleted_by_client', src), \
            "missing is_active/deleted_by_client conditional"
        # Must also check cancelled gen_job
        assert '_job_check' in src and 'skipping persist' in src, "missing gen_job cancelled check"


# =====================================================================
# T7 — reassessment short-form GET
# =====================================================================

class TestT7ShortFormGet:
    @pytest.mark.parametrize("kind", ["missed_workouts", "life_change", "roster_uploaded", "event_completed"])
    def test_get_form(self, client_token_and_id, kind):
        tok, _ = client_token_and_id
        r = requests.get(f"{API}/reassessment/short-form",
                         params={"kind": kind}, headers=_auth(tok), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["kind"] == kind
        assert data["title"]
        assert data["intro"]
        assert data["duration_estimate"]
        assert data["button_label"]
        assert isinstance(data["questions"], list) and len(data["questions"]) >= 3

    def test_missed_workouts_shape(self, client_token_and_id):
        tok, _ = client_token_and_id
        r = requests.get(f"{API}/reassessment/short-form",
                         params={"kind": "missed_workouts"}, headers=_auth(tok), timeout=20)
        data = r.json()
        qs = {q["id"]: q for q in data["questions"]}
        assert "reason" in qs and qs["reason"]["type"] == "single_select"
        assert len(qs["reason"]["options"]) == 8
        assert "energy_level" in qs and qs["energy_level"]["type"] == "range"
        assert qs["energy_level"]["meta"]["min"] == 1 and qs["energy_level"]["meta"]["max"] == 5
        assert "adjust_plan" in qs and qs["adjust_plan"]["type"] == "single_select"
        assert "note" in qs and qs["note"]["type"] == "long_text" and qs["note"].get("optional") is True

    def test_roster_uploaded_shape(self, client_token_and_id):
        tok, _ = client_token_and_id
        r = requests.get(f"{API}/reassessment/short-form",
                         params={"kind": "roster_uploaded"}, headers=_auth(tok), timeout=20)
        data = r.json()
        qs = {q["id"]: q for q in data["questions"]}
        assert "training_days_per_week" in qs
        opts = [o["id"] for o in qs["training_days_per_week"]["options"]]
        assert opts == ["2", "3", "4", "5", "6"]

    def test_unknown_kind_404(self, client_token_and_id):
        tok, _ = client_token_and_id
        r = requests.get(f"{API}/reassessment/short-form",
                         params={"kind": "nonsense_kind"}, headers=_auth(tok), timeout=20)
        assert r.status_code == 404


# =====================================================================
# T8 — reassessment short-form POST
# =====================================================================

class TestT8ShortFormPost:
    def test_post_roster_uploaded_flow(self, client_token_and_id):
        from server import db, new_id, now_iso  # type: ignore
        tok, uid = client_token_and_id

        async def prep_and_verify():
            # Snapshot coaching_dna row count + hash for the user
            dna_before = await db.coaching_dna.find_one({"user_id": uid}, {"_id": 0})
            dna_before_ct = await db.coaching_dna.count_documents({"user_id": uid})

            # Seed an active reassessment prompt
            prompt_id = f"TEST_pr_{uuid.uuid4().hex[:8]}"
            await db.reassessment_prompts.insert_one({
                "id": prompt_id, "user_id": uid, "kind": "roster_uploaded",
                "dismissed": False, "created_at": now_iso(),
            })
            return prompt_id, dna_before, dna_before_ct

        async def verify_and_cleanup(prompt_id, dna_before, dna_before_ct):
            # Response persisted
            resp = await db.reassessment_responses.find_one(
                {"user_id": uid, "kind": "roster_uploaded", "prompt_id": prompt_id}, {"_id": 0}
            )
            assert resp is not None
            assert resp["answers"]["training_days_per_week"] == "5"
            assert resp["answers"]["energy_baseline"] == 4

            # Profile updated
            u = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
            assert u.get("profile", {}).get("training_days_per_week") == 5

            # Prompt dismissed
            pr = await db.reassessment_prompts.find_one({"id": prompt_id}, {"_id": 0})
            assert pr["dismissed"] is True
            assert pr["resolved_via"] == "short_form"

            # Coach task created
            ct = await db.coach_tasks.find_one(
                {"task_type": "reassessment_response", "payload.response_id": resp["id"]}, {"_id": 0})
            assert ct is not None
            assert ct["payload"]["kind"] == "roster_uploaded"
            assert ct["payload"]["profile_updates"]["training_days_per_week"] == 5

            # coaching_dna UNTOUCHED
            dna_after_ct = await db.coaching_dna.count_documents({"user_id": uid})
            assert dna_after_ct == dna_before_ct, "coaching_dna row count changed!"
            dna_after = await db.coaching_dna.find_one({"user_id": uid}, {"_id": 0})
            assert dna_after == dna_before, "coaching_dna content changed!"

            # Cleanup
            await db.reassessment_prompts.delete_one({"id": prompt_id})
            await db.reassessment_responses.delete_one({"id": resp["id"]})
            if ct:
                await db.coach_tasks.delete_one({"id": ct["id"]})

        prompt_id, dna_before, dna_before_ct = _run(prep_and_verify())
        r = requests.post(f"{API}/reassessment/short-form",
                          headers=_auth(tok),
                          json={"kind": "roster_uploaded", "prompt_id": prompt_id,
                                "answers": {"training_days_per_week": "5", "energy_baseline": 4}},
                          timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert "training_days_per_week" in body["profile_updates"]

        _run(verify_and_cleanup(prompt_id, dna_before, dna_before_ct))
