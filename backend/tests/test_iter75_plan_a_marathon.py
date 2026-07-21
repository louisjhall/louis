"""
Iteration 75 — Plan A Marathon-Prep programme fix validation.

Backend-only unit tests for:
  1. `_apply_days_cap_and_min_content` (server.py)
       — A3 days-per-week cap + A4 incomplete-content flag.
  2. `validate_programme` (feature_programme_quality.py)
       — rules 7-11 added by Plan A.
  3. Louis migrated-profile sanity check (louishallpt@gmail.com).
  4. Live endpoint smoke: /api/programme/current and /api/auth/me.

We invoke the sync helpers directly (no LLM/Claude calls), and hit the
public URL for the light integration probes.
"""
from __future__ import annotations

import os
import sys
import pytest
import requests

# make backend importable
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://flight-fit-plans.preview.emergentagent.com",
).rstrip("/")


# ------------------------------------------------------------------
# fixtures
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def apply_cap_fn():
    from server import _apply_days_cap_and_min_content
    return _apply_days_cap_and_min_content


@pytest.fixture(scope="module")
def validate_fn():
    from feature_programme_quality import validate_programme
    return validate_programme


@pytest.fixture(scope="module")
def louis_client_login():
    """Login as Louis (coach). Yields (token, session)."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "louis@crewfit.net", "password": "Louis123!"},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"Louis login failed: {r.status_code} {r.text}")
    token = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _wk(day_iso: str, focus: str = "full", duration: int = 45,
        exercises: int = 1, title: str = "Full Body Strength",
        key_session: bool = False) -> dict:
    return {
        "id": f"wk-{day_iso}-{focus}",
        "date": day_iso,
        "title": title,
        "focus": focus,
        "duration_min": duration,
        "exercises": [{"name": f"Ex {i}"} for i in range(exercises)],
        "key_session": key_session,
        "source": "template",
    }


# ==================================================================
# Test 1 — Louis migrated-profile sanity check (from Mongo direct)
# ==================================================================
class TestLouisProfileMigration:
    def test_louis_profile_populated(self):
        from pymongo import MongoClient
        cli = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        db = cli[os.environ.get("DB_NAME", "crewfit_v1")]
        u = db.users.find_one({"email": "louishallpt@gmail.com"}, {"_id": 0})
        assert u is not None, "louishallpt@gmail.com user missing"
        prof = u.get("profile") or {}
        assert prof.get("main_goal_key") == "event", \
            f"main_goal_key should be 'event', got {prof.get('main_goal_key')}"
        assert prof.get("training_days_per_week") == 4, \
            f"training_days_per_week should be 4, got {prof.get('training_days_per_week')}"
        assert prof.get("event_type_pref") == "marathon", \
            f"event_type_pref should be 'marathon', got {prof.get('event_type_pref')}"
        assert prof.get("primary_goal_id") == "marathon"

    def test_apply_handoff_called_from_finalize(self):
        """Static-source verification that the handoff runs *after* DNA insert."""
        with open("/app/backend/server.py", "r") as fh:
            src = fh.read()
        # Anchor: the handoff must appear inside assessment_finalize, after
        # coaching_dna.insert_one, and before returning `dna_doc_clean`.
        assert "async def assessment_finalize" in src
        idx_finalize = src.index("async def assessment_finalize")
        # look at slice: 2500 chars is enough for the finalize function
        window = src[idx_finalize: idx_finalize + 6000]
        assert "coaching_dna.insert_one" in window, "DNA insert must be present"
        assert "_apply_assessment_answers_to_profile(user[\"id\"], a)" in window, \
            "handoff call must exist inside assessment_finalize"
        assert window.index("coaching_dna.insert_one") < \
               window.index("_apply_assessment_answers_to_profile(user"), \
            "handoff must be called AFTER dna insert"


# ==================================================================
# Test 2 — days-per-week cap (A3)
# ==================================================================
class TestDaysPerWeekCap:
    def test_seven_strength_capped_to_four(self, apply_cap_fn):
        # Mon 2026-01-05 .. Sun 2026-01-11
        dates = [f"2026-01-{d:02d}" for d in range(5, 12)]
        workouts = [_wk(d) for d in dates]
        apply_cap_fn(workouts, {"training_days_per_week": 4})

        strength = [w for w in workouts if w["focus"] == "full"]
        recovery = [w for w in workouts if w["focus"] == "recovery"]
        assert len(strength) == 4, f"expected 4 strength kept, got {len(strength)}"
        assert len(recovery) == 3, f"expected 3 demoted to recovery, got {len(recovery)}"
        for w in recovery:
            assert w["title"] == "Optional Recovery Walk"
            assert w["duration_min"] == 20
            assert w.get("optional") is True
            assert w.get("source_reason") == "days_per_week_cap"

    def test_no_cap_when_under_limit(self, apply_cap_fn):
        dates = [f"2026-01-{d:02d}" for d in range(5, 8)]  # 3 workouts
        workouts = [_wk(d) for d in dates]
        apply_cap_fn(workouts, {"training_days_per_week": 4})
        strength = [w for w in workouts if w["focus"] == "full"]
        assert len(strength) == 3, "no demotions when under cap"

    def test_key_sessions_preserved(self, apply_cap_fn):
        dates = [f"2026-01-{d:02d}" for d in range(5, 12)]
        workouts = []
        # first workout is a key long-run — must survive cap
        workouts.append(_wk(dates[0], focus="long_run", title="Long Run 15k",
                            key_session=True))
        for d in dates[1:]:
            workouts.append(_wk(d))
        apply_cap_fn(workouts, {"training_days_per_week": 3})
        # Long run must still be present
        surv = [w for w in workouts if w.get("key_session")]
        assert len(surv) == 1 and surv[0]["focus"] == "long_run", \
            "key long-run must not be demoted"

    def test_cap_missing_or_invalid_is_noop(self, apply_cap_fn):
        dates = [f"2026-01-{d:02d}" for d in range(5, 12)]
        workouts = [_wk(d) for d in dates]
        apply_cap_fn(workouts, {})  # no cap
        assert all(w["focus"] == "full" for w in workouts)


# ==================================================================
# Test 3 — min-content flagging (A4)
# ==================================================================
class TestMinContentFlag:
    def test_strength_45min_1ex_flagged(self, apply_cap_fn):
        w = _wk("2026-01-05", focus="full", duration=45, exercises=1)
        workouts = [w]
        apply_cap_fn(workouts, {})  # no cap, but A4 still runs
        assert w.get("validation_status") == "incomplete_content"
        assert w.get("needs_coach_review") is True
        assert w.get("insufficient_content_reason")

    def test_endurance_run_exempt(self, apply_cap_fn):
        w = {
            "id": "run1",
            "date": "2026-01-05",
            "title": "Easy Run",
            "focus": "long_run",
            "duration_min": 45,
            "exercises": [{"name": "Easy 5k"}],
        }
        apply_cap_fn([w], {})
        assert w.get("validation_status") != "incomplete_content"
        assert not w.get("needs_coach_review")

    def test_recovery_walk_exempt(self, apply_cap_fn):
        w = {
            "id": "rec1",
            "date": "2026-01-05",
            "title": "Recovery Walk",
            "focus": "recovery",
            "duration_min": 20,
            "exercises": [],
        }
        apply_cap_fn([w], {})
        assert w.get("validation_status") != "incomplete_content"

    def test_strength_with_3_exercises_ok(self, apply_cap_fn):
        w = _wk("2026-01-05", focus="full", duration=45, exercises=3)
        apply_cap_fn([w], {})
        assert w.get("validation_status") != "incomplete_content"

    def test_short_strength_below_30min_ok(self, apply_cap_fn):
        w = _wk("2026-01-05", focus="push", duration=20, exercises=1)
        apply_cap_fn([w], {})
        assert w.get("validation_status") != "incomplete_content"


# ==================================================================
# Test 4 — validator rules 7-11
# ==================================================================
class TestValidatorRules:
    def _ctx(self, goal_key="event", event_type="marathon", target=4):
        return {
            "goal_key": goal_key,
            "target_sessions_per_week": target,
            "profile_snapshot": {
                "event_type_pref": event_type,
                "primary_goal_id": event_type if event_type else None,
                "main_goal_key": goal_key,
            },
            "phase": {"key": "build"},
        }

    def _roster(self):
        # Wide date window so the "no real training in next 7 days" rule
        # doesn't shadow our target rules. We pass 5 non-heavy days.
        return {"days": []}

    def test_rule9_marathon_no_run_errors(self, validate_fn):
        # 4 strength workouts, no run
        dates = [f"2026-01-{d:02d}" for d in range(5, 9)]
        workouts = [_wk(d) for d in dates]
        ctx = self._ctx()
        res = validate_fn({}, self._roster(), workouts, ctx)
        joined = " | ".join(res["errors"]).lower()
        assert "running" in joined, f"expected running-focused error, got {res['errors']}"

    def test_rule8_over_target_hard_errors(self, validate_fn):
        # target 3, provide 5 strength sessions in same week → target+2 → error
        dates = [f"2026-01-{d:02d}" for d in range(5, 10)]
        workouts = [_wk(d, focus="push", title="Push Day") for d in dates]
        ctx = self._ctx(goal_key="build_muscle", event_type=None, target=3)
        res = validate_fn({}, self._roster(), workouts, ctx)
        joined = " | ".join(res["errors"]).lower()
        assert "exceeds target" in joined, f"expected 'exceeds target' error, got {res['errors']}"

    def test_rule8_over_target_soft_warns(self, validate_fn):
        # target 3, provide 4 sessions → target+1 → warning
        dates = [f"2026-01-{d:02d}" for d in range(5, 9)]
        workouts = [_wk(d, focus="push", title="Push Day") for d in dates]
        ctx = self._ctx(goal_key="build_muscle", event_type=None, target=3)
        res = validate_fn({}, self._roster(), workouts, ctx)
        joined = " | ".join(res["warnings"]).lower()
        assert "vs target" in joined, f"expected soft-over warning, got {res['warnings']}"

    def test_rule10_template_ratio_warns(self, validate_fn):
        dates = [f"2026-01-{d:02d}" for d in range(5, 9)]
        workouts = [_wk(d, title="Session A") for d in dates]
        # All source='template' via _wk helper
        ctx = self._ctx(goal_key="build_muscle", event_type=None, target=4)
        res = validate_fn({}, self._roster(), workouts, ctx)
        joined = " | ".join(res["warnings"]).lower()
        assert "template" in joined, f"expected template warning, got {res['warnings']}"

    def test_rule11_repeated_title_warns(self, validate_fn):
        # 5 identical titles across two weeks
        dates = [f"2026-01-{d:02d}" for d in (5, 6, 12, 13, 19)]
        workouts = [_wk(d, title="Full Body Strength") for d in dates]
        ctx = self._ctx(goal_key="build_muscle", event_type=None, target=4)
        res = validate_fn({}, self._roster(), workouts, ctx)
        joined = " | ".join(res["warnings"]).lower()
        assert "repeated" in joined or "full body strength" in joined, \
            f"expected repeated-title warning, got {res['warnings']}"

    def test_rule7_incomplete_content_error(self, validate_fn):
        w = _wk("2026-01-05", focus="full")
        w["validation_status"] = "incomplete_content"
        w["needs_coach_review"] = True
        ctx = self._ctx(goal_key="build_muscle", event_type=None, target=4)
        res = validate_fn({}, self._roster(), [w], ctx)
        joined = " | ".join(res["errors"]).lower()
        assert "too few exercises" in joined, \
            f"expected incomplete_content error, got {res['errors']}"


# ==================================================================
# Test 5 — endpoint smoke
# ==================================================================
class TestEndpointSmoke:
    def test_backend_alive(self):
        r = requests.get(f"{BASE_URL}/api/auth/me", timeout=10)
        # Should be 401 missing token (backend up), not 5xx / connection refused
        assert r.status_code in (401, 403), f"backend not responding: {r.status_code}"

    def test_login_louis(self, louis_client_login):
        # simply reusing the fixture proves login worked
        r = louis_client_login.get(f"{BASE_URL}/api/auth/me", timeout=10)
        assert r.status_code == 200
        me = r.json()
        assert me.get("email") == "louis@crewfit.net"

    def test_programme_current_endpoint_reachable(self, louis_client_login):
        # This coach user may or may not have a programme, but the endpoint
        # must respond cleanly (no 5xx).
        r = louis_client_login.get(f"{BASE_URL}/api/programme/current", timeout=15)
        assert r.status_code < 500, f"unexpected 5xx: {r.status_code} {r.text[:200]}"

    def test_louishallpt_programme_current(self, louis_client_login):
        """Login as louishallpt is not possible via password; use coach-scoped
        endpoint to confirm no 5xx regression for that user's programme."""
        # We just ping the coach clients list; hard programme lookup requires
        # user auth. Passing means the routes still register.
        r = louis_client_login.get(f"{BASE_URL}/api/coach/clients", timeout=15)
        assert r.status_code < 500, f"coach/clients 5xx: {r.status_code}"
