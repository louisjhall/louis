"""
Iter 91 (Phase 1 Foundation Lock) — batch verification for tasks 1.7, 1.8,
1.9, 1.10 plus regression for 1.4 and 1.6.

Covered:
- Task 1.7 backend: GET /events/active + PATCH /events/{eid}/priority
- Task 1.9 backend: programmes.strength_overload for non-endurance goals,
  absent for endurance ("event"), adherence gating (sets_delta=0 + "hold"
  when last week <50% completed).
- Task 1.10 backend: /coach/dashboard exposes profile_incomplete bucket
  and client summary carries profile_incomplete_pill; clears after
  /profile/training-setup fills the essentials.
- Regression 1.4: /roster/upload-and-generate → 409 profile_incomplete
  with friendly_labels + missing_fields when essentials wiped.
- Regression 1.6: marathon periodisation — long-run km progresses and
  tapers when race is <=2 weeks.
"""
import os
import uuid
import asyncio
import datetime as dt
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL is required"
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": pw}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["token"], d["user"]


@pytest.fixture(scope="module")
def client_ctx():
    tok, u = _login(CLIENT_EMAIL, CLIENT_PW)
    return {"token": tok, "user": u,
            "headers": {"Authorization": f"Bearer {tok}",
                        "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def coach_ctx():
    tok, u = _login(COACH_EMAIL, COACH_PW)
    return {"token": tok, "user": u,
            "headers": {"Authorization": f"Bearer {tok}",
                        "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def mdb():
    """Sync pymongo handle for seeding / cleanup."""
    cli = MongoClient(MONGO_URL)
    return cli[DB_NAME]


_LOOP = asyncio.new_event_loop()


def _run(coro):
    """Run an async coroutine on a persistent loop so Motor's bound IOLoop stays alive."""
    return _LOOP.run_until_complete(coro)


# ===========================================================================
# TASK 1.7 — GET /events/active + PATCH /events/{eid}/priority
# ===========================================================================

class TestTask17Events:
    """Multi-event dashboard + priority PATCH endpoints."""

    @pytest.fixture(autouse=True)
    def _seed(self, client_ctx, mdb):
        """Insert two future-dated events for the client."""
        uid = client_ctx["user"]["id"]
        today = dt.date.today()
        self.ev1_id = f"ev_test_{uuid.uuid4().hex[:8]}"
        self.ev2_id = f"ev_test_{uuid.uuid4().hex[:8]}"
        mdb.events.insert_many([
            {"id": self.ev1_id, "user_id": uid,
             "event_name": "TEST Marathon Alpha",
             "event_type": "marathon",
             "event_date": (today + dt.timedelta(weeks=12)).isoformat(),
             "priority": "B", "is_active": True,
             "created_at": dt.datetime.utcnow().isoformat()},
            {"id": self.ev2_id, "user_id": uid,
             "event_name": "TEST Half Beta",
             "event_type": "half_marathon",
             "event_date": (today + dt.timedelta(weeks=20)).isoformat(),
             "priority": "C", "is_active": True,
             "created_at": dt.datetime.utcnow().isoformat()},
        ])
        yield
        mdb.events.delete_many({"id": {"$in": [self.ev1_id, self.ev2_id]}})

    def test_events_active_returns_ordered_future_events(self, client_ctx):
        r = requests.get(f"{BASE_URL}/api/events/active",
                         headers=client_ctx["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "events" in data
        # Filter to our seeded ones only
        ours = [e for e in data["events"] if e["id"] in (self.ev1_id, self.ev2_id)]
        assert len(ours) == 2
        # Ordered ascending by event_date
        assert ours[0]["event_date"] < ours[1]["event_date"]
        # weeks_to_event calculated
        assert isinstance(ours[0]["weeks_to_event"], int)
        # is_endurance flag
        assert ours[0]["is_endurance"] is True

    def test_patch_priority_persists(self, client_ctx, mdb):
        r = requests.patch(f"{BASE_URL}/api/events/{self.ev1_id}/priority",
                           headers=client_ctx["headers"],
                           json={"priority": "A"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["priority"] == "A"
        assert d["success"] is True
        # Verify persisted
        ev = mdb.events.find_one({"id": self.ev1_id})
        assert ev["priority"] == "A"

    def test_patch_priority_promotion_demotes_previous_a(self, client_ctx, mdb):
        # Set ev1 to A first
        requests.patch(f"{BASE_URL}/api/events/{self.ev1_id}/priority",
                       headers=client_ctx["headers"],
                       json={"priority": "A"}, timeout=30)
        # Now promote ev2 to A — ev1 should be demoted to B
        r = requests.patch(f"{BASE_URL}/api/events/{self.ev2_id}/priority",
                           headers=client_ctx["headers"],
                           json={"priority": "A"}, timeout=30)
        assert r.status_code == 200
        ev1 = mdb.events.find_one({"id": self.ev1_id})
        assert ev1["priority"] == "B", "promoting ev2 to A must demote ev1 to B"

    def test_patch_priority_invalid_value(self, client_ctx):
        r = requests.patch(f"{BASE_URL}/api/events/{self.ev1_id}/priority",
                           headers=client_ctx["headers"],
                           json={"priority": "X"}, timeout=30)
        assert r.status_code == 400

    def test_patch_priority_cross_user_forbidden(self, coach_ctx):
        # Coach (different user) trying to PATCH client's event → 404 (not found in scope)
        r = requests.patch(f"{BASE_URL}/api/events/{self.ev1_id}/priority",
                           headers=coach_ctx["headers"],
                           json={"priority": "A"}, timeout=30)
        assert r.status_code in (403, 404), r.text


# ===========================================================================
# TASK 1.9 — Strength overload for non-endurance goals
# ===========================================================================

class TestTask19StrengthOverload:
    """Verify programme_ctx.strength_overload behavior via the buildctx helper."""

    def test_build_muscle_client_has_strength_overload(self, mdb):
        """For a build_muscle profile, strength_overload must be present."""
        # Direct helper call — proves the context builder emits the block.
        import sys
        sys.path.insert(0, "/app/backend")
        from feature_programme_quality import programme_context_for_llm

        uid = f"utest_{uuid.uuid4().hex[:8]}"
        mdb.users.insert_one({
            "id": uid, "role": "client",
            "email": f"TEST_{uid}@example.com",
            "profile": {"main_goal_key": "build_muscle",
                        "training_days_per_week": 4,
                        "equipment": ["dumbbells"]},
            "created_at": dt.datetime.utcnow().isoformat(),
        })
        try:
            u = mdb.users.find_one({"id": uid})
            ctx = _run(programme_context_for_llm(u, {"id": None, "days": []}))
            assert ctx["goal_key"] == "build_muscle"
            assert "strength_overload" in ctx and ctx["strength_overload"], (
                "strength_overload must be present for non-endurance goals"
            )
            so = ctx["strength_overload"]
            # Required shape keys
            for k in ("sets_delta", "reps_target", "load_delta_pct", "rpe",
                      "note", "adherence_note", "phase_key", "goal_key"):
                assert k in so, f"strength_overload missing '{k}'"
            assert so["goal_key"] == "build_muscle"
        finally:
            mdb.users.delete_one({"id": uid})

    def test_endurance_client_has_no_strength_overload(self, mdb):
        import sys
        sys.path.insert(0, "/app/backend")
        from feature_programme_quality import programme_context_for_llm

        uid = f"utest_{uuid.uuid4().hex[:8]}"
        mdb.users.insert_one({
            "id": uid, "role": "client",
            "email": f"TEST_{uid}@example.com",
            "profile": {"main_goal_key": "event",
                        "event_type_pref": "marathon",
                        "training_days_per_week": 4,
                        "equipment": ["dumbbells"]},
            "created_at": dt.datetime.utcnow().isoformat(),
        })
        try:
            u = mdb.users.find_one({"id": uid})
            ctx = _run(programme_context_for_llm(u, {"id": None, "days": []}))
            assert ctx["goal_key"] == "event"
            assert "strength_overload" not in ctx, (
                "strength_overload MUST NOT be present for endurance/event goal"
            )
        finally:
            mdb.users.delete_one({"id": uid})

    def test_adherence_gating_hold_when_under_50pct(self, mdb):
        """Seed prior-week workouts <50% completed → sets_delta=0 + 'hold' note."""
        import sys
        sys.path.insert(0, "/app/backend")
        from feature_programme_quality import programme_context_for_llm

        uid = f"utest_{uuid.uuid4().hex[:8]}"
        today = dt.date.today()
        monday = today - dt.timedelta(days=today.weekday())
        prev_monday = monday - dt.timedelta(days=7)
        # Insert 4 planned workouts LAST week, only 1 completed → 25% adherence
        workouts = []
        for i in range(4):
            wid = f"wtest_{uuid.uuid4().hex[:8]}"
            workouts.append({
                "id": wid, "user_id": uid,
                "date": (prev_monday + dt.timedelta(days=i)).isoformat(),
                "focus": "strength",
                "completed": (i == 0),  # only 1 of 4 completed
            })
        mdb.users.insert_one({
            "id": uid, "role": "client",
            "email": f"TEST_{uid}@example.com",
            "profile": {"main_goal_key": "build_muscle",
                        "training_days_per_week": 4,
                        "equipment": ["dumbbells"]},
            "created_at": dt.datetime.utcnow().isoformat(),
        })
        mdb.workouts.insert_many(workouts)
        try:
            u = mdb.users.find_one({"id": uid})
            ctx = _run(programme_context_for_llm(u, {"id": None, "days": []}))
            so = ctx.get("strength_overload")
            assert so, "strength_overload should exist"
            # phase might be foundation/build; either way adherence gating applies
            if so.get("phase_key") != "deload":
                assert so["sets_delta"] == 0, (
                    f"sets_delta must be 0 when adherence <50%, got {so['sets_delta']}"
                )
            assert "hold" in (so.get("adherence_note") or "").lower(), (
                f"adherence_note must contain 'hold', got: {so.get('adherence_note')!r}"
            )
        finally:
            mdb.users.delete_one({"id": uid})
            mdb.workouts.delete_many({"user_id": uid})


# ===========================================================================
# TASK 1.10 — Profile completeness on coach dashboard
# ===========================================================================

class TestTask110ProfileIncomplete:
    """Coach dashboard surfaces profile_incomplete bucket + per-client pill."""

    @pytest.fixture(autouse=True)
    def _wipe_client_essentials(self, client_ctx, mdb):
        """Save then wipe the client's profile essentials so pill triggers."""
        uid = client_ctx["user"]["id"]
        original = mdb.users.find_one({"id": uid}, {"_id": 0, "profile": 1})
        mdb.users.update_one({"id": uid}, {"$unset": {
            "profile.equipment": "",
            "profile.training_days_per_week": "",
            "profile.time_home_min": "",
        }})
        yield original
        # Restore
        if original and original.get("profile"):
            p = original["profile"]
            restore = {}
            for k in ("equipment", "training_days_per_week", "time_home_min"):
                if k in p:
                    restore[f"profile.{k}"] = p[k]
            if restore:
                mdb.users.update_one({"id": uid}, {"$set": restore})

    def test_dashboard_exposes_profile_incomplete_bucket(self, coach_ctx, client_ctx):
        r = requests.get(f"{BASE_URL}/api/coach/dashboard",
                         headers=coach_ctx["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "counts" in data
        assert "profile_incomplete" in data["counts"], (
            "dashboard counts must include profile_incomplete bucket"
        )
        # Our client should be in the incomplete list
        target = next((c for c in data["clients"]
                       if c["id"] == client_ctx["user"]["id"]), None)
        assert target is not None, "seeded client missing from dashboard"
        assert target.get("profile_incomplete_pill"), (
            "target client must carry profile_incomplete_pill after essentials wipe"
        )
        pill = target["profile_incomplete_pill"]
        assert isinstance(pill.get("missing_fields"), list) and pill["missing_fields"]
        assert isinstance(pill.get("friendly_labels"), list)
        assert isinstance(pill.get("missing_count"), int) and pill["missing_count"] > 0

    def test_dashboard_filter_narrows_to_profile_incomplete(self, coach_ctx, client_ctx):
        r = requests.get(f"{BASE_URL}/api/coach/dashboard?filter=profile_incomplete",
                         headers=coach_ctx["headers"], timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        ids = [c["id"] for c in data["clients"]]
        assert client_ctx["user"]["id"] in ids, (
            "filter=profile_incomplete should include our seeded client"
        )
        # All returned clients must carry the pill
        for c in data["clients"]:
            assert c.get("profile_incomplete_pill"), (
                f"client {c['id']} in profile_incomplete bucket but no pill"
            )

    def test_pill_clears_after_training_setup_submit(self, coach_ctx, client_ctx, mdb):
        # Submit full essentials via /profile/training-setup
        body = {
            "primary_goal": "build_muscle",
            "training_days": 4,
            "time_home": 45,
            "time_layover": 30,
            "equipment_home": ["dumbbells", "bands"],
            "hotel_gym_reliability": "often",
            "injuries": "none",
            "no_go_movements": ["overhead_press"],  # non-empty; see bug note
        }
        r = requests.post(f"{BASE_URL}/api/profile/training-setup",
                          headers=client_ctx["headers"], json=body, timeout=30)
        assert r.status_code == 200, r.text
        # Re-check coach dashboard
        r2 = requests.get(f"{BASE_URL}/api/coach/dashboard",
                          headers=coach_ctx["headers"], timeout=30)
        assert r2.status_code == 200
        data = r2.json()
        target = next((c for c in data["clients"]
                       if c["id"] == client_ctx["user"]["id"]), None)
        assert target is not None
        pill = target.get("profile_incomplete_pill")
        # After a full setup submit the pill should be gone (None).
        assert pill in (None, {}, False), (
            f"pill should be cleared after setup, got: {pill}"
        )


# ===========================================================================
# REGRESSION — Task 1.4: /roster/upload-and-generate returns 409 when incomplete
# ===========================================================================

class TestRegression14ProfileGate:
    @pytest.fixture(autouse=True)
    def _wipe(self, client_ctx, mdb):
        uid = client_ctx["user"]["id"]
        original = mdb.users.find_one({"id": uid}, {"_id": 0, "profile": 1})
        mdb.users.update_one({"id": uid}, {"$unset": {
            "profile.equipment": "",
            "profile.training_days_per_week": "",
            "profile.time_home_min": "",
        }})
        yield
        if original and original.get("profile"):
            p = original["profile"]
            restore = {f"profile.{k}": p[k] for k in
                       ("equipment", "training_days_per_week", "time_home_min")
                       if k in p}
            if restore:
                mdb.users.update_one({"id": uid}, {"$set": restore})

    def test_roster_upload_returns_409_profile_incomplete(self, client_ctx):
        # Provide a tiny junk payload — the profile gate fires BEFORE any AI call.
        payload = {"file_base64": "aGVsbG8=", "mime_type": "text/plain",
                   "filename": "TEST_roster.txt"}
        r = requests.post(f"{BASE_URL}/api/roster/upload-and-generate",
                          headers=client_ctx["headers"], json=payload, timeout=30)
        assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
        body = r.json()
        detail = body.get("detail") or body
        assert detail.get("code") == "profile_incomplete"
        assert isinstance(detail.get("missing_fields"), list) and detail["missing_fields"]
        assert isinstance(detail.get("friendly_labels"), list) and detail["friendly_labels"]


# ===========================================================================
# REGRESSION — Task 1.6: marathon periodisation (long-run progression + taper)
# ===========================================================================

class TestRegression16MarathonPeriodisation:
    """Verify long-run km progresses and tapers via the phase resolver."""

    def test_marathon_phase_progression_and_taper(self):
        import sys
        sys.path.insert(0, "/app/backend")
        from feature_programme_quality import (
            _phase_for_weeks_to_race, _long_run_km_for_week,
        )
        # Phase should differ between 10wk out and 2wk out
        p_far = _phase_for_weeks_to_race(10)
        p_taper = _phase_for_weeks_to_race(2)
        assert p_far["key"] != p_taper["key"], (
            f"phase must change as race approaches: 10wk={p_far['key']}, 2wk={p_taper['key']}"
        )
        # Taper/race-week key should reflect tapering (race_week or taper)
        assert p_taper["key"] in ("race_week", "taper", "peak"), p_taper
        # Long run at 10wk out MUST exceed long run at 2wk out (tapering)
        lr_far = _long_run_km_for_week("marathon", 10, 5)
        lr_taper = _long_run_km_for_week("marathon", 2, 5)
        assert lr_far > lr_taper, (
            f"long-run must taper: 10wk={lr_far}km, 2wk={lr_taper}km"
        )
