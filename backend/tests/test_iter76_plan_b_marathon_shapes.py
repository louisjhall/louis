"""
Plan B backend validation — Marathon programme quality (goal-aware shapes +
running templates + progression tracking).

Tests the deterministic slices of Plan B:
  T1 — Marathon shape catalogue (event_weekly_shape)
  T2 — Strength shape catalogue (strength_weekly_shape)
  T3 — Fallback plan for Marathon Prep + 4 days/wk (Louis scenario)
  T4 — programme_context_for_llm surfaces weekly_shape_ideal + progression
  T5 — persist_programme_record stores B1/B3 fields
  T6 — Validator rules from Plan A still fire (regression)
  T7 — Non-endurance goal fallback → push/pull/leg split, NOT running
  T8 — Backend smoke: /api/auth/me + /api/programme/current schema
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import pathlib
import pytest
import requests

# Ensure /app/backend is on sys.path so we can import server.* modules directly
BACKEND = str(pathlib.Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")


# ---------------------------------------------------------------------------
# T1 — Marathon shape catalogue
# ---------------------------------------------------------------------------

class TestMarathonShapes:
    def test_marathon_foundation_4days(self):
        from feature_programme_quality import event_weekly_shape
        shape = event_weekly_shape("marathon", "foundation", 4)
        # First 4 slots are training; remainder is mobility/recovery padding
        assert shape[:4] == ["easy_run", "long_run", "strength_support", "easy_run"], shape
        assert set(shape[4:]).issubset({"mobility", "recovery"})
        assert "mobility" in shape and "recovery" in shape

    def test_marathon_build_has_tempo(self):
        from feature_programme_quality import event_weekly_shape
        shape = event_weekly_shape("marathon", "build", 4)
        assert "tempo" in shape[:4]
        assert "long_run" in shape[:4]
        # Build should NOT rely on intervals (peak does)
        assert "intervals" not in shape[:4]

    def test_marathon_peak_has_intervals(self):
        from feature_programme_quality import event_weekly_shape
        shape = event_weekly_shape("marathon", "peak", 4)
        assert "intervals" in shape[:4]
        assert "long_run" in shape[:4]

    def test_marathon_deload_no_hard_sessions(self):
        from feature_programme_quality import event_weekly_shape
        shape = event_weekly_shape("marathon", "deload", 4)
        # No tempo / no intervals in the training slots
        training = shape[:4]
        assert "tempo" not in training
        assert "intervals" not in training
        assert "long_run" in training  # still preserved (reduced volume via meta)

    def test_unknown_event_falls_back_to_marathon(self):
        from feature_programme_quality import event_weekly_shape
        unknown = event_weekly_shape("ultra_moonrun_9000", "foundation", 4)
        marathon = event_weekly_shape("marathon", "foundation", 4)
        assert unknown == marathon


# ---------------------------------------------------------------------------
# T2 — Strength shape catalogue
# ---------------------------------------------------------------------------

class TestStrengthShapes:
    def test_build_muscle_4days(self):
        from feature_programme_quality import strength_weekly_shape
        shape = strength_weekly_shape("build_muscle", 4)
        assert shape[:4] == ["push_strength", "pull_strength", "leg_strength", "upper_strength"], shape
        assert set(shape[4:]).issubset({"mobility", "recovery"})

    def test_lose_fat_3days(self):
        from feature_programme_quality import strength_weekly_shape
        shape = strength_weekly_shape("lose_fat", 3)
        assert shape[:3] == ["upper_strength", "conditioning", "lower_strength"], shape
        assert set(shape[3:]).issubset({"mobility", "recovery"})

    def test_unknown_goal_falls_back_to_general(self):
        from feature_programme_quality import strength_weekly_shape
        shape = strength_weekly_shape("bogus_key_xyz", 3)
        expected = strength_weekly_shape("general_fitness", 3)
        assert shape == expected


# ---------------------------------------------------------------------------
# T3 — Louis fallback plan (Marathon Prep + 4 days/wk)
# ---------------------------------------------------------------------------

def _make_roster_days(start_iso: str, day_types: list[str]) -> dict:
    """Build a roster dict from an ordered list of day_type strings."""
    d0 = _dt.date.fromisoformat(start_iso)
    days = [
        {"date": (d0 + _dt.timedelta(days=i)).isoformat(),
         "day_type": t, "duty_hours": 10 if "long_haul" in t else 0}
        for i, t in enumerate(day_types)
    ]
    return {"id": "roster_test_iter76", "days": days, "is_active": True}


def _mon_key(iso: str) -> str:
    d = _dt.date.fromisoformat(iso[:10])
    return (d - _dt.timedelta(days=d.weekday())).isoformat()


class TestLouisMarathonFallback:
    @pytest.fixture
    def louis_plan(self):
        from feature_workout_fallback import build_template_plan
        from server import _apply_days_cap_and_min_content
        # Louis: marathon-prep client, 4 days/wk, hotel gym reliable
        user = {
            "id": "test_louis_iter76",
            "profile": {
                "main_goal_key": "event",
                "event_type_pref": "marathon",
                "training_days_per_week": 4,
                "hotel_gyms": "hotel_gym_reliable",
            },
        }
        # 14-day roster: 2 long-hauls + 2 layovers scattered, rest = home
        day_types = [
            "home", "long_haul_flight", "layover", "home",
            "home", "home", "home",
            "long_haul_flight", "layover", "home",
            "home", "home", "home", "home",
        ]
        # Start on a Monday so weeks align cleanly
        # Find next Monday from today for deterministic Mon-Sun windows
        today = _dt.date.today()
        monday = today - _dt.timedelta(days=today.weekday())
        roster = _make_roster_days(monday.isoformat(), day_types)
        workouts = build_template_plan(user, roster)
        _apply_days_cap_and_min_content(workouts, user["profile"])
        return {"user": user, "roster": roster, "workouts": workouts}

    def test_no_full_body_strength_title(self, louis_plan):
        titles = [w.get("title") for w in louis_plan["workouts"]]
        assert "Full Body Strength" not in titles, f"Got titles: {titles}"

    def test_at_least_one_long_run_per_week(self, louis_plan):
        wo = louis_plan["workouts"]
        buckets: dict[str, list[dict]] = {}
        for w in wo:
            buckets.setdefault(_mon_key(w["date"]), []).append(w)
        for wk, items in buckets.items():
            longs = [w for w in items if w.get("title") == "Long Run"]
            assert len(longs) >= 1, f"Week {wk} has no Long Run. Titles: {[w['title'] for w in items]}"

    def test_at_least_one_easy_run_per_week(self, louis_plan):
        wo = louis_plan["workouts"]
        buckets: dict[str, list[dict]] = {}
        for w in wo:
            buckets.setdefault(_mon_key(w["date"]), []).append(w)
        for wk, items in buckets.items():
            easies = [w for w in items if w.get("title") == "Easy Run"]
            assert len(easies) >= 1, f"Week {wk} has no Easy Run"

    def test_exactly_one_strength_for_runners_per_week(self, louis_plan):
        wo = louis_plan["workouts"]
        buckets: dict[str, list[dict]] = {}
        for w in wo:
            buckets.setdefault(_mon_key(w["date"]), []).append(w)
        for wk, items in buckets.items():
            sfr = [w for w in items if w.get("title") == "Strength for Runners"]
            assert len(sfr) == 1, f"Week {wk} has {len(sfr)} Strength for Runners (expected 1)"

    def test_real_sessions_capped_at_training_days(self, louis_plan):
        wo = louis_plan["workouts"]
        LIGHT = {"recovery", "mobility", "rest"}
        buckets: dict[str, list[dict]] = {}
        for w in wo:
            buckets.setdefault(_mon_key(w["date"]), []).append(w)
        for wk, items in buckets.items():
            real = [w for w in items if str(w.get("focus") or "").lower() not in LIGHT]
            assert len(real) <= 4, f"Week {wk} has {len(real)} real sessions (>4). Focuses: {[w.get('focus') for w in items]}"

    def test_long_haul_days_get_flight_recovery(self, louis_plan):
        # Any workout on a long_haul day must be "Flight Recovery Mobility"
        roster_by_date = {d["date"]: d for d in louis_plan["roster"]["days"]}
        for w in louis_plan["workouts"]:
            d = roster_by_date.get(w["date"])
            if d and "long_haul" in d["day_type"]:
                assert w.get("title") == "Flight Recovery Mobility", (
                    f"Long-haul day {w['date']} got '{w.get('title')}' not Flight Recovery Mobility"
                )

    def test_no_short_strength_card_with_too_few_exercises(self, louis_plan):
        # After A4 flag, any 30+ min strength card with <3 exercises must be
        # marked incomplete_content — assert either the card has 3+ exercises
        # OR it's flagged for coach review.
        LIGHT = {"recovery", "mobility", "rest"}
        ENDUR = {"long_run", "long", "tempo", "intervals", "zone2", "swim", "bike", "brick", "race_prep"}
        for w in louis_plan["workouts"]:
            focus = str(w.get("focus") or "").lower()
            if focus in LIGHT or focus in ENDUR:
                continue
            dur = int(w.get("duration_min") or 0)
            exs = w.get("exercises") or []
            if dur >= 30 and len(exs) < 3:
                assert w.get("validation_status") == "incomplete_content", (
                    f"Card {w.get('title')} @ {w['date']} has {len(exs)} exs, dur {dur} — should be flagged"
                )


# ---------------------------------------------------------------------------
# T7 — Non-endurance goal fallback → strength split
# ---------------------------------------------------------------------------

class TestBuildMuscleFallback:
    def test_build_muscle_produces_strength_split_no_runs(self):
        from feature_workout_fallback import build_template_plan
        user = {
            "id": "test_bm_iter76",
            "profile": {
                "main_goal_key": "build_muscle",
                "training_days_per_week": 4,
            },
        }
        today = _dt.date.today()
        monday = today - _dt.timedelta(days=today.weekday())
        # 7 clean home days
        day_types = ["home"] * 7
        roster = _make_roster_days(monday.isoformat(), day_types)
        workouts = build_template_plan(user, roster)
        titles = [w.get("title") for w in workouts]
        # No running content
        for run_title in ("Easy Run", "Long Run", "Tempo Run", "Interval Session"):
            assert run_title not in titles, f"build_muscle got a run: {titles}"
        # Has upper push / pull / leg split
        expected_any = {"Upper Push + Core", "Upper Pull + Core", "Lower Body Strength", "Upper Body Strength"}
        assert expected_any.intersection(titles), f"No strength split found in {titles}"


# ---------------------------------------------------------------------------
# T4 — programme_context_for_llm surfaces new fields
# ---------------------------------------------------------------------------

class TestProgrammeContext:
    def test_marathon_context_includes_weekly_shape_and_progression(self):
        from feature_programme_quality import programme_context_for_llm
        user = {
            "id": "test_ctx_iter76",
            "profile": {
                "main_goal_key": "event",
                "event_type_pref": "marathon",
                "training_days_per_week": 4,
            },
        }
        today = _dt.date.today()
        monday = today - _dt.timedelta(days=today.weekday())
        roster = _make_roster_days(monday.isoformat(), ["home"] * 14)
        ctx = asyncio.get_event_loop().run_until_complete(
            programme_context_for_llm(user, roster)
        )
        # weekly_shape_ideal is a non-empty list of session-type strings
        assert isinstance(ctx.get("weekly_shape_ideal"), list) and ctx["weekly_shape_ideal"], ctx
        assert ctx.get("event_type_pref") == "marathon"
        assert isinstance(ctx.get("session_type_meta"), dict) and ctx["session_type_meta"]
        # Progression block
        prog = ctx.get("progression")
        assert isinstance(prog, dict), ctx
        for k in (
            "phase", "phase_label", "week_index", "target_sessions_per_week",
            "sessions_planned_this_week", "sessions_completed_this_week",
            "sessions_missed_this_week", "next_progression", "deload_status",
        ):
            assert k in prog, f"progression missing key {k}: {prog}"


# ---------------------------------------------------------------------------
# T5 — persist_programme_record stores B1/B3 fields
# ---------------------------------------------------------------------------

class TestPersistProgrammeFields:
    def test_persist_stores_weekly_shape_event_type_progression(self):
        import server
        from feature_programme_quality import (
            programme_context_for_llm, validate_programme, persist_programme_record,
        )
        user = {
            "id": "test_persist_iter76_" + _dt.datetime.utcnow().isoformat(),
            "profile": {
                "main_goal_key": "event",
                "event_type_pref": "marathon",
                "training_days_per_week": 4,
            },
        }
        today = _dt.date.today()
        monday = today - _dt.timedelta(days=today.weekday())
        roster = _make_roster_days(monday.isoformat(), ["home"] * 7)
        roster["id"] = f"roster_persist_iter76_{_dt.datetime.utcnow().isoformat()}"

        async def _run():
            ctx = await programme_context_for_llm(user, roster)
            # minimal workouts — validator not the point of this test
            wo = [
                {"date": monday.isoformat(), "title": "Long Run", "focus": "long_run",
                 "duration_min": 75, "exercises": [{"name": "run"}], "warmup": []},
                {"date": (monday + _dt.timedelta(days=2)).isoformat(),
                 "title": "Easy Run", "focus": "long_run",
                 "duration_min": 40, "exercises": [{"name": "run"}], "warmup": []},
            ]
            v = validate_programme(user, roster, wo, ctx)
            pid = await persist_programme_record(user, roster, wo, ctx, v)
            row = await server.db.programmes.find_one({"id": pid}, {"_id": 0})
            # Cleanup
            await server.db.programmes.delete_one({"id": pid})
            return row

        row = asyncio.get_event_loop().run_until_complete(_run())
        assert row is not None
        assert isinstance(row.get("weekly_shape_ideal"), list) and row["weekly_shape_ideal"]
        assert row.get("event_type_pref") == "marathon"
        assert isinstance(row.get("progression"), dict)
        for k in ("phase", "week_index", "target_sessions_per_week", "next_progression"):
            assert k in row["progression"]


# ---------------------------------------------------------------------------
# T6 — Regression: Plan A validator rules still fire
# ---------------------------------------------------------------------------

class TestValidatorRegression:
    def _mk_ctx(self, goal="event", ev="marathon", target=4):
        return {
            "goal_key": goal,
            "target_sessions_per_week": target,
            "phase": {"key": "build"},
            "profile_snapshot": {"event_type_pref": ev} if ev else {},
        }

    def test_marathon_all_strength_no_runs_errors(self):
        from feature_programme_quality import validate_programme
        user = {"id": "u1", "profile": {"main_goal_key": "event"}}
        roster = _make_roster_days(_dt.date.today().isoformat(), ["home"] * 7)
        # 3 strength cards, no runs
        base = _dt.date.today()
        wo = [
            {"date": (base + _dt.timedelta(days=i)).isoformat(),
             "title": "Upper Body Strength", "focus": "push",
             "duration_min": 45, "exercises": [{"name": "x"}] * 4}
            for i in range(3)
        ]
        v = validate_programme(user, roster, wo, self._mk_ctx())
        assert not v["ok"]
        assert any("no running-focused sessions" in e for e in v["errors"]), v

    def test_over_target_sessions_errors(self):
        from feature_programme_quality import validate_programme
        user = {"id": "u2", "profile": {}}
        base = _dt.date.today() - _dt.timedelta(days=_dt.date.today().weekday())
        # 6 real sessions in a week vs target 3 → target+2+ triggers hard error
        wo = [
            {"date": (base + _dt.timedelta(days=i)).isoformat(),
             "title": "Long Run", "focus": "long_run",  # so no A9 error fires
             "duration_min": 40, "exercises": [{"name": "r"}]}
            for i in range(6)
        ]
        roster = _make_roster_days(base.isoformat(), ["home"] * 7)
        v = validate_programme(user, roster, wo, self._mk_ctx(target=3))
        assert not v["ok"]
        assert any("exceeds target" in e for e in v["errors"]), v

    def test_template_source_majority_warns(self):
        from feature_programme_quality import validate_programme
        user = {"id": "u3", "profile": {}}
        base = _dt.date.today()
        # 6/8 template, has runs
        wo = []
        for i in range(6):
            wo.append({"date": (base + _dt.timedelta(days=i)).isoformat(),
                       "title": "Easy Run", "focus": "long_run",
                       "duration_min": 40, "exercises": [{"name": "r"}],
                       "source": "template"})
        for i in range(6, 8):
            wo.append({"date": (base + _dt.timedelta(days=i)).isoformat(),
                       "title": "Easy Run", "focus": "long_run",
                       "duration_min": 40, "exercises": [{"name": "r"}]})
        roster = _make_roster_days(base.isoformat(), ["home"] * 8)
        v = validate_programme(user, roster, wo, self._mk_ctx(target=6))
        assert any("template fallback" in w for w in v["warnings"]), v

    def test_repeated_title_warns(self):
        from feature_programme_quality import validate_programme
        user = {"id": "u4", "profile": {}}
        base = _dt.date.today()
        wo = [
            {"date": (base + _dt.timedelta(days=i)).isoformat(),
             "title": "Long Run", "focus": "long_run",
             "duration_min": 40, "exercises": [{"name": "r"}]}
            for i in range(5)
        ]
        roster = _make_roster_days(base.isoformat(), ["home"] * 7)
        v = validate_programme(user, roster, wo, self._mk_ctx(target=6))
        assert any("repeated workout title" in w for w in v["warnings"]), v

    def test_incomplete_content_flagged_as_error(self):
        from feature_programme_quality import validate_programme
        user = {"id": "u5", "profile": {}}
        base = _dt.date.today()
        wo = [
            {"date": (base + _dt.timedelta(days=1)).isoformat(),
             "title": "Long Run", "focus": "long_run",
             "duration_min": 40, "exercises": [{"name": "r"}]},
            {"date": (base + _dt.timedelta(days=2)).isoformat(),
             "title": "Strength", "focus": "push",
             "duration_min": 45, "exercises": [{"name": "x"}],
             "validation_status": "incomplete_content"},
        ]
        roster = _make_roster_days(base.isoformat(), ["home"] * 7)
        v = validate_programme(user, roster, wo, self._mk_ctx(target=6))
        assert not v["ok"]
        assert any("too few exercises for their duration" in e for e in v["errors"]), v


# ---------------------------------------------------------------------------
# T8 — Backend smoke tests over public URL
# ---------------------------------------------------------------------------

class TestBackendSmoke:
    def test_auth_login_client(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "client@crewfit.com", "password": "Client123!"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert "token" in j and "user" in j

    def test_auth_me_with_token(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "client@crewfit.com", "password": "Client123!"},
            timeout=30,
        )
        assert r.status_code == 200
        tok = r.json()["token"]
        r2 = requests.get(f"{BASE_URL}/api/auth/me",
                          headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r2.status_code == 200

    def test_programme_current_shape_when_present(self):
        # Login as any client and check /api/programme/current schema
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "client@crewfit.com", "password": "Client123!"},
            timeout=30,
        )
        assert r.status_code == 200
        tok = r.json()["token"]
        r2 = requests.get(
            f"{BASE_URL}/api/programme/current",
            headers={"Authorization": f"Bearer {tok}"}, timeout=30,
        )
        assert r2.status_code == 200
        body = r2.json()
        # Endpoint returns {} when no programme exists — acceptable
        if body:
            # If data exists, must NOT leak mongo _id
            assert "_id" not in body
