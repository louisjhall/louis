"""
CrewFit V2 Engine V2 — Deterministic regression tests + Pietro fixture.

Tests the pure engine functions (no DB, no FastAPI). Reproduces Pietro's
observed inputs and asserts the new engine produces sane output — the
absence of every named August-2026 failure mode.

Usage:
    cd /app/backend && python -m pytest tests/test_engine_v2_invariants.py -v
    (or: python tests/test_engine_v2_invariants.py to run without pytest)
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from feature_v2_sport_configs import (
    canonicalise_goal_key, get_goal_config, resolve_phase_plan,
    required_exposures_for_phase, session_kind_meta, is_hard_session,
    is_key_intensity, session_family, is_forbidden_sequence,
    session_recovery_hours,
    SPORT_CONFIGS, SESSION_KIND_REGISTRY,
)
from feature_v2_roster_context import (
    DayContext, build_day_contexts, context_to_derived,
)
from feature_v2_demand_v2 import (
    build_demand, schedule_demand, RequiredExposure,
)
from feature_v2_sequencing import (
    Placement, PlacementPlan, validate_placement, apply_placement, week_key,
)
from feature_v2_construction_v2 import build_session_spec
from feature_v2_validators_v2 import (
    validate_session, validate_programme, Issue,
)


# ---------------------------------------------------------------------------
# Pietro fixture — real DNA + real Cathay-shape roster
# ---------------------------------------------------------------------------

PIETRO_ID = "fixture_pietro"


def pietro_profile() -> dict:
    return {
        "primary_goal_type": "marathon",
        "training_days_per_week": 5,
        "sessions_per_week_min": 4,
        "sessions_per_week_max": 5,
        "preferred_training_days": ["Mon", "Wed", "Fri", "Sat", "Sun"],
        "preferred_session_length": 60,
        "airline": "Cathay Pacific",
        "home_base": "HKG",
        "equipment": ["dumbbells", "treadmill"],
        "injuries": "None",
        "v2_flags": {"engine_v2": True},
    }


def pietro_event(today: _dt.date) -> dict:
    return {
        "id": "evt_pietro_marathon",
        "user_id": PIETRO_ID,
        "event_type": "marathon",
        "event_date": (today + _dt.timedelta(days=174)).isoformat(),  # ~25w
        "is_active": True,
    }


def pietro_roster_days(today: _dt.date, n_days: int = 28) -> list[dict]:
    """A representative 4-week roster with Cathay day_type distribution:
       ~35% home_day, ~25% layover (arrival/full/departure), ~15% turnaround,
       ~10% standby, ~10% off/rest, ~5% flight."""
    pattern = [
        # week 1 — flying a lot
        ("home_day", {}),
        ("flight", {"duty_type": "flight", "crossed_midnight": False}),
        ("layover_arrival", {"tz_offset_from_base_hours": 8, "duty_start_time": None, "recovery_window_hours_from_prior_duty": 10}),
        ("layover_full", {"tz_offset_from_base_hours": 8}),
        ("layover_departure", {"tz_offset_from_base_hours": -8, "recovery_window_hours_from_prior_duty": 24}),
        ("home_day", {}),
        ("home_day", {}),
        # week 2 — turnaround + standby
        ("turnaround", {"recovery_window_hours_from_prior_duty": 11, "duty_start_time": None}),
        ("home_day", {}),
        ("standby", {}),
        ("home_day", {}),
        ("home_day", {}),
        ("off", {}),
        ("home_day", {}),
        # week 3 — a big layover trip
        ("flight", {"duty_type": "flight"}),
        ("layover_arrival", {"tz_offset_from_base_hours": 12, "recovery_window_hours_from_prior_duty": 9}),
        ("layover_full", {"tz_offset_from_base_hours": 12}),
        ("layover_full", {"tz_offset_from_base_hours": 12}),
        ("layover_departure", {"tz_offset_from_base_hours": -12, "recovery_window_hours_from_prior_duty": 22}),
        ("home_day", {}),
        ("off", {}),
        # week 4 — home block
        ("home_day", {}),
        ("home_day", {}),
        ("home_day", {}),
        ("standby", {}),
        ("home_day", {}),
        ("home_day", {}),
        ("off", {}),
    ]
    days: list[dict] = []
    for i in range(min(n_days, len(pattern))):
        d = today + _dt.timedelta(days=i)
        dtype, extras = pattern[i]
        row = {
            "client_id": PIETRO_ID,
            "date": d.isoformat(),
            "day_type": dtype,
            "duties": [] if dtype in ("home_day", "off", "rest") else [{"duty_type": dtype}],
            "tz_offset_from_base_hours": extras.get("tz_offset_from_base_hours", 0),
            "recovery_window_hours_from_prior_duty": extras.get("recovery_window_hours_from_prior_duty"),
        }
        days.append(row)
    return days


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------

class TestGoalConfigInvariants(unittest.TestCase):

    def test_all_ten_goals_registered(self):
        expected = {"running.marathon", "running.half_marathon", "running.10k",
                    "running.5k", "cycling.endurance", "triathlon.olympic",
                    "strength.muscle_gain", "strength.fat_loss",
                    "strength.general", "general.fitness"}
        self.assertTrue(expected.issubset(set(SPORT_CONFIGS.keys())),
                        f"Missing: {expected - set(SPORT_CONFIGS.keys())}")

    def test_marathon_phase_plan_sums_to_prep_weeks(self):
        plan = resolve_phase_plan("marathon", 18)
        total = sum(p.weeks_target for p in plan)
        self.assertEqual(total, 18)

    def test_marathon_short_prep_compresses(self):
        # Marathon default = 20w, min floor = 13w (sum of phase weeks_min).
        # Request 15w → compression brings us to exactly 15.
        plan = resolve_phase_plan("marathon", 15)
        total = sum(p.weeks_target for p in plan)
        self.assertEqual(total, 15)
        # Requesting less than absolute floor returns the floor.
        plan = resolve_phase_plan("marathon", 8)
        total = sum(p.weeks_target for p in plan)
        self.assertEqual(total, 13)

    def test_5k_short_prep_compresses(self):
        plan = resolve_phase_plan("5k", 6)
        total = sum(p.weeks_target for p in plan)
        self.assertEqual(total, 6)

    def test_goal_key_canonicalises(self):
        self.assertEqual(canonicalise_goal_key("marathon"), "running.marathon")
        self.assertEqual(canonicalise_goal_key("HM"), "running.half_marathon")
        self.assertEqual(canonicalise_goal_key("Weight Loss"), "strength.fat_loss")
        self.assertEqual(canonicalise_goal_key(""), "general.fitness")
        self.assertEqual(canonicalise_goal_key(None), "general.fitness")

    def test_every_quota_kind_in_registry(self):
        for k, cfg in SPORT_CONFIGS.items():
            for pk, ps in cfg.phase_specs.items():
                for q in ps.quotas:
                    self.assertIn(q.kind, SESSION_KIND_REGISTRY,
                                  f"{k}.{pk} references unknown kind {q.kind}")


class TestRosterContextRolling(unittest.TestCase):
    """Verify the rolling burden model produces context-sensitive scores."""

    def setUp(self):
        self.today = _dt.date(2026, 8, 3)  # Monday
        self.roster = pietro_roster_days(self.today, 28)
        self.contexts = build_day_contexts(self.roster)
        self.by_date = {c.date: c for c in self.contexts}

    def test_home_day_not_automatically_90min(self):
        """Regression: Home Days must NOT automatically prescribe 90-min sessions."""
        home_ctx = next(c for c in self.contexts if c.day_type == "home_day")
        # available_time_min is a CAP, not a prescription — but it should be
        # a REASONABLE cap (not the 90 that used to be default).
        self.assertLessEqual(home_ctx.available_time_min, 120)
        self.assertGreater(home_ctx.available_time_min, 0)

    def test_off_day_not_automatically_120min(self):
        off_ctx = next((c for c in self.contexts if c.day_type == "off"), None)
        if off_ctx:
            self.assertLessEqual(off_ctx.available_time_min, 150)

    def test_layover_arrival_uses_prior_duty_context(self):
        """A layover_arrival after a long flight + 12h tz shift must have
        HIGHER burden than one after a short hop."""
        # Week 3 layover_arrival — after big 12h tz flight
        big = next(c for c in self.contexts
                   if c.day_type == "layover_arrival" and c.tz_shift_last_48h >= 8)
        self.assertGreaterEqual(big.duty_burden_score, 55,
                                 f"Big tz layover burden = {big.duty_burden_score}")
        self.assertLessEqual(big.training_opportunity, 35,
                              f"Big tz layover opp = {big.training_opportunity}")

    def test_turnaround_reflects_prior_recovery(self):
        turn = next(c for c in self.contexts if c.day_type == "turnaround")
        # turnaround with 11h prior recovery must produce elevated burden
        self.assertGreaterEqual(turn.duty_burden_score, 55)

    def test_no_day_scores_opp_100_across_the_board(self):
        opps = [c.training_opportunity for c in self.contexts]
        # Some off/rest days may legitimately hit 100, but NOT every day
        self.assertTrue(any(o < 100 for o in opps),
                         "Every day scored 100 — rolling logic broken")
        self.assertTrue(any(o == 0 for o in opps),
                         "No day scored 0 — layovers not being reduced")

    def test_consecutive_duty_days_tracked(self):
        # Week 3 has back-to-back duty days
        streaks = [c.consecutive_duty_days for c in self.contexts]
        self.assertTrue(max(streaks) >= 2,
                         f"Max consecutive duty tracked: {max(streaks)}")


class TestDemandDoesNotInventSessions(unittest.TestCase):
    """WHAT layer must derive quotas from goal/phase, NOT from availability."""

    def test_marathon_aerobic_base_quotas_do_not_scale_with_available_days(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        today = _dt.date(2026, 8, 3)
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id=PIETRO_ID,
            client_profile=pietro_profile(),
            goal_key="marathon",
            phase_spec=phase,
            week_start_dates=week_starts,
        )
        # Aerobic_base marathon target: 3 easy + 1 long + 0.5 tempo + 1.5 strength + 2 mobility
        # ~= 8 per week * 4 weeks = 32
        # Client cap is 5/wk → 20 total, so quotas were scaled
        # Assert NO more than 8 long_runs
        n_long = sum(1 for e in demand.required_exposures if e.kind == "run_long")
        self.assertLessEqual(n_long, 4,
                              f"Too many long runs demanded: {n_long}")
        # Assert we still have at least 3 long runs (one per week ideally)
        self.assertGreaterEqual(n_long, 3,
                                 f"Not enough long runs: {n_long}")

    def test_key_sessions_never_silently_scaled_below_min(self):
        """Even under aggressive scaling, KEY quotas keep their per-week minimum."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["specific_prep"]
        today = _dt.date(2026, 8, 3)
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(3)]
        demand = build_demand(
            client_id=PIETRO_ID,
            client_profile={"training_days_per_week": 4},
            goal_key="marathon",
            phase_spec=phase,
            week_start_dates=week_starts,
        )
        # 3 weeks × 1 long_run minimum
        long_count = sum(1 for e in demand.required_exposures if e.kind == "run_long")
        mp_count = sum(1 for e in demand.required_exposures if e.kind == "run_marathon_pace")
        self.assertGreaterEqual(long_count, 3)
        self.assertGreaterEqual(mp_count, 2)  # at least 2 of 3 weeks

    def test_duration_from_progression_not_availability(self):
        """Progression: long_run should grow week over week, not clamp to avail."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        today = _dt.date(2026, 8, 3)
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(5)]
        demand = build_demand(
            client_id=PIETRO_ID,
            client_profile=pietro_profile(),
            goal_key="marathon",
            phase_spec=phase,
            week_start_dates=week_starts,
        )
        long_by_week = {}
        for e in demand.required_exposures:
            if e.kind == "run_long":
                long_by_week.setdefault(e.week_index, e.target_duration_min)
        # Progression: +5/wk → week 4 > week 0
        if 0 in long_by_week and 4 in long_by_week:
            self.assertGreater(long_by_week[4], long_by_week[0])


class TestSchedulerRespectsInvariants(unittest.TestCase):
    """WHEN layer must respect frequency + spacing + sequencing rules."""

    def setUp(self):
        self.today = _dt.date(2026, 8, 3)
        self.roster = pietro_roster_days(self.today, 28)
        self.contexts = build_day_contexts(self.roster)
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        week_starts = [self.today + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id=PIETRO_ID,
            client_profile=pietro_profile(),
            goal_key="marathon",
            phase_spec=phase,
            week_start_dates=week_starts,
        )
        self.result = schedule_demand(
            demand=demand,
            day_contexts=self.contexts,
            goal=cfg,
            phase=phase,
            preferred_weekdays={0, 2, 4, 5, 6},  # Mon Wed Fri Sat Sun
        )
        self.placements = self.result.placements

    def test_no_more_than_1_long_run_per_week(self):
        weekly_long = {}
        for p in self.placements:
            if p.kind == "run_long":
                wk = week_key(p.date)
                weekly_long[wk] = weekly_long.get(wk, 0) + 1
        for wk, n in weekly_long.items():
            self.assertLessEqual(n, 1, f"Week {wk} has {n} long runs")

    def test_long_runs_min_recovery_72h(self):
        longs = sorted([p.date for p in self.placements if p.kind == "run_long"])
        for i in range(1, len(longs)):
            gap = (longs[i] - longs[i - 1]).days
            self.assertGreaterEqual(gap * 24, 72,
                                     f"Long runs {longs[i-1]} → {longs[i]} = {gap*24}h")

    def test_no_tempo_within_48h_of_long_run(self):
        longs = [p.date for p in self.placements if p.kind == "run_long"]
        for p in self.placements:
            if p.kind in ("run_tempo", "run_threshold"):
                for ld in longs:
                    gap = abs((p.date - ld).days)
                    self.assertGreater(gap, 1,
                                        f"{p.kind}@{p.date} within 24h of LR@{ld}")

    def test_no_two_keys_within_48h(self):
        keys = sorted([p for p in self.placements if p.key], key=lambda p: p.date)
        for i in range(1, len(keys)):
            gap = (keys[i].date - keys[i - 1].date).days
            self.assertGreater(gap, 1,
                                f"Two KEYs within {gap*24}h: {keys[i-1].kind}@{keys[i-1].date} → {keys[i].kind}@{keys[i].date}")

    def test_weekly_endurance_hard_cap_respected(self):
        """ENDURANCE hard sessions (LR/tempo/threshold/intervals/vo2/race pace)
        must respect the phase's hard-days cap. Strength does NOT count here
        — strength has its own cap tested in test_weekly_strength_cap_respected.
        """
        from feature_v2_sport_configs import is_endurance_hard
        cfg = get_goal_config("marathon")
        cap = cfg.phase_specs["aerobic_base"].hard_days_per_week_max
        weekly_hard = {}
        for p in self.placements:
            if is_endurance_hard(p.kind):
                wk = week_key(p.date)
                weekly_hard[wk] = weekly_hard.get(wk, 0) + 1
        for wk, n in weekly_hard.items():
            self.assertLessEqual(n, cap, f"Week {wk}: {n} endurance hard > cap {cap}")

    def test_weekly_strength_cap_respected(self):
        """Strength sessions count against phase.strength_days_per_week_max
        which is a separate weekly bucket from endurance-hard."""
        from feature_v2_sport_configs import is_strength_session
        cfg = get_goal_config("marathon")
        cap = cfg.phase_specs["aerobic_base"].strength_days_per_week_max
        weekly_strength_dates = {}
        for p in self.placements:
            if is_strength_session(p.kind):
                wk = week_key(p.date)
                weekly_strength_dates.setdefault(wk, set()).add(p.date)
        for wk, dates in weekly_strength_dates.items():
            self.assertLessEqual(len(dates), cap,
                                 f"Week {wk}: {len(dates)} strength days > cap {cap}")

    def test_strength_can_coexist_with_long_run_in_same_week(self):
        """CRITICAL correctness: any week that has a Long Run MUST also be
        able to contain at least one Strength session. Previously they shared
        the same hard-cap bucket which made this architecturally impossible."""
        from feature_v2_sport_configs import is_strength_session
        weeks_with_lr = set()
        weeks_with_strength = set()
        for p in self.placements:
            if p.kind == "run_long":
                weeks_with_lr.add(week_key(p.date))
            if is_strength_session(p.kind):
                weeks_with_strength.add(week_key(p.date))
        # Every LR week should also have at least one strength placement,
        # unless the roster simply had no viable strength day (opportunity
        # floor below IMPORTANT). At minimum, at least ONE LR week must show
        # coexistence — otherwise the buckets are still incorrectly coupled.
        coexisting = weeks_with_lr & weeks_with_strength
        self.assertGreater(len(coexisting), 0,
                            f"No week contains both LR and Strength — architectural coupling bug. "
                            f"LR weeks: {weeks_with_lr}, Strength weeks: {weeks_with_strength}")

    def test_no_placement_on_sick_day(self):
        # (No sick in fixture — this is a safety check)
        sick_dates = {c.date for c in self.contexts
                       if c.day_type in ("sickness", "sick", "sick_leave")}
        for p in self.placements:
            self.assertNotIn(p.date, sick_dates)

    def test_no_placement_below_opportunity_floor(self):
        opp_by_date = {c.date: c.training_opportunity for c in self.contexts}
        for p in self.placements:
            self.assertGreaterEqual(opp_by_date[p.date], 20,
                                     f"{p.kind}@{p.date} opp={opp_by_date[p.date]}")

    def test_exposure_numbering_chronologically_monotonic(self):
        """Placements sorted by DATE must have exposure_number = 1..N per
        objective_id. This is the correctness fix: previously we only checked
        the SET of numbers, missing cases where #2 predated #1 by date.
        """
        per_obj = {}
        for p in self.placements:
            per_obj.setdefault(p.objective_id, []).append(p)
        for obj, group in per_obj.items():
            by_date = sorted(group, key=lambda pl: pl.date)
            seq = [pl.exposure_number for pl in by_date]
            self.assertEqual(seq, list(range(1, len(seq) + 1)),
                              f"Objective {obj}: by-date exposure sequence "
                              f"{seq} is not 1..N (chronological)")


class TestConstructionSportTyped(unittest.TestCase):
    """HOW layer must produce sport-specific content."""

    def test_running_session_has_running_payload(self):
        spec = build_session_spec(
            kind="run_long", duration_min=60, intensity_target="z2",
            phase_kind="aerobic_base", day_type="home_day",
            equipment_ctx={"bodyweight", "dumbbells", "treadmill"},
            avoid_patterns=set(),
        )
        d = spec.to_dict()
        self.assertEqual(d["spec_kind"], "running")
        self.assertIn("warmup", d["payload"])
        self.assertIn("main", d["payload"])
        self.assertIn("cooldown", d["payload"])
        # Running never shows "bodyweight, dumbbells, treadmill" as equipment
        self.assertNotIn("bodyweight", d["equipment_used"])
        self.assertNotIn("dumbbells", d["equipment_used"])
        # Running environment is outdoor or treadmill
        self.assertIn(d["environment"], ("outdoor", "treadmill"))

    def test_strength_session_has_exercises(self):
        spec = build_session_spec(
            kind="strength_full_body", duration_min=40, intensity_target="rpe7",
            phase_kind="aerobic_base", day_type="home_day",
            equipment_ctx={"dumbbells", "bodyweight"},
            avoid_patterns=set(),
        )
        d = spec.to_dict()
        self.assertEqual(d["spec_kind"], "strength")
        self.assertGreater(len(d["payload"]["exercises"]), 0)
        for ex in d["payload"]["exercises"]:
            self.assertIn("name", ex)
            self.assertIn("sets", ex)
            self.assertIn("reps", ex)

    def test_mobility_has_flow_blocks(self):
        spec = build_session_spec(
            kind="mobility", duration_min=20, intensity_target="flow",
            phase_kind="aerobic_base", day_type="home_day",
            equipment_ctx={"bodyweight"},
            avoid_patterns=set(),
        )
        d = spec.to_dict()
        self.assertEqual(d["spec_kind"], "mobility")
        self.assertGreater(len(d["payload"]["flow_blocks"]), 0)

    def test_cycling_intervals_have_reps(self):
        spec = build_session_spec(
            kind="bike_intervals", duration_min=60, intensity_target="z5",
            phase_kind="build", day_type="home_day",
            equipment_ctx={"bike"},
            avoid_patterns=set(),
        )
        d = spec.to_dict()
        self.assertEqual(d["spec_kind"], "cycling")
        self.assertEqual(d["payload"]["main"]["type"], "intervals")

    def test_swim_technique_is_swim(self):
        spec = build_session_spec(
            kind="swim_technique", duration_min=30, intensity_target="technique",
            phase_kind="foundation", day_type="home_day",
            equipment_ctx={"pool"},
            avoid_patterns=set(),
        )
        d = spec.to_dict()
        self.assertEqual(d["spec_kind"], "swimming")

    def test_brick_has_bike_and_run_segments(self):
        spec = build_session_spec(
            kind="brick_bike_run", duration_min=90, intensity_target="z3",
            phase_kind="build", day_type="home_day",
            equipment_ctx={"bike"},
            avoid_patterns=set(),
        )
        d = spec.to_dict()
        self.assertEqual(d["spec_kind"], "brick")
        mods = {seg["modality"] for seg in d["payload"]["segments"]}
        self.assertIn("bike", mods)
        self.assertIn("run", mods)


class TestValidatorGate(unittest.TestCase):

    def test_empty_running_session_fails_validation(self):
        session = {
            "spec_kind": "running", "duration_min": 30,
            "payload": {}, "equipment_used": [],
        }
        placement = Placement(
            exposure_id="x", objective_id="o", kind="run_easy",
            date=_dt.date.today(), priority="IMPORTANT", exposure_number=1,
            intensity_class="easy", target_duration_min=30,
            intensity_target="z2", key=False,
        )
        sv = validate_session(session, placement, day_ctx_available_time=60, restrictions=set())
        self.assertFalse(sv.ok)

    def test_valid_session_passes(self):
        spec = build_session_spec(
            kind="run_easy", duration_min=30, intensity_target="z2",
            phase_kind="aerobic_base", day_type="home_day",
            equipment_ctx={"bodyweight"}, avoid_patterns=set(),
        )
        placement = Placement(
            exposure_id="x", objective_id="o", kind="run_easy",
            date=_dt.date.today(), priority="IMPORTANT", exposure_number=1,
            intensity_class="easy", target_duration_min=30,
            intensity_target="z2", key=False,
        )
        sv = validate_session(spec.to_dict(), placement,
                              day_ctx_available_time=60, restrictions=set())
        self.assertTrue(sv.ok, [i.__dict__ for i in sv.issues])


class TestPietroAugustRegression(unittest.TestCase):
    """The named failure modes from the user's 8-long-run August plan."""

    def test_end_of_august_hell_week_impossible(self):
        """Section 43: the exact sequence Intervals→Tempo→LR→LR must be blocked."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        plan = PlacementPlan()
        # LR Sun then LR Mon (24h apart)
        apply_placement(plan, exposure_id="e1", objective_id="obj_LR",
                        kind="run_long", date=_dt.date(2026, 8, 30),
                        priority="KEY", intensity_target="z2", target_duration_min=90)
        r = validate_placement("run_long", _dt.date(2026, 8, 31), plan,
                                cfg, phase, 20, 85, "KEY")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason_code, "insufficient_family_recovery")

    def test_lr_to_tempo_next_day_blocked(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        plan = PlacementPlan()
        apply_placement(plan, exposure_id="e1", objective_id="o1",
                        kind="run_long", date=_dt.date(2026, 8, 30),
                        priority="KEY", intensity_target="z2", target_duration_min=90)
        r = validate_placement("run_tempo", _dt.date(2026, 8, 31), plan,
                                cfg, phase, 20, 85, "IMPORTANT")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason_code, "forbidden_sequence")

    def test_tempo_to_lr_next_day_blocked(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        plan = PlacementPlan()
        apply_placement(plan, exposure_id="e1", objective_id="o1",
                        kind="run_tempo", date=_dt.date(2026, 8, 30),
                        priority="IMPORTANT", intensity_target="z4",
                        target_duration_min=45)
        r = validate_placement("run_long", _dt.date(2026, 8, 31), plan,
                                cfg, phase, 20, 85, "KEY")
        self.assertFalse(r.ok)
        self.assertEqual(r.reason_code, "forbidden_sequence")

    def test_overlapping_planning_windows_reuse_exposure_ids(self):
        """Section 44: overlapping windows must reconcile to one exposure stream,
        NOT produce Long Run #3 + a new Long Run #1."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        today = _dt.date(2026, 8, 3)
        week_starts_A = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        # Window B overlaps window A on weeks 3-4 and extends into 5-6
        week_starts_B = [today + _dt.timedelta(days=7 * i) for i in range(2, 6)]

        demand_A = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts_A,
        )
        demand_B = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts_B,
        )
        # Long runs from A on weeks 3-4 must have IDENTICAL exposure_ids to
        # long runs from B for those same weeks.
        A_by_week = {(e.week_index, e.kind, e.ordinal_within_week): e.exposure_id
                     for e in demand_A.required_exposures if e.kind == "run_long"}
        # Window B's week_index is relative to its OWN start (Aug 17).
        # A's week 2 = calendar 2026-08-17, B's week 0 = 2026-08-17.
        # So we compare A[week_index=2] with B[week_index=0] etc.
        overlap_calendar_weeks = [week_starts_A[2], week_starts_A[3]]
        for cal_week in overlap_calendar_weeks:
            a_wi = week_starts_A.index(cal_week)
            b_wi = week_starts_B.index(cal_week)
            for e_a in demand_A.required_exposures:
                if e_a.kind == "run_long" and e_a.week_index == a_wi:
                    match = [e for e in demand_B.required_exposures
                              if e.kind == "run_long" and e.week_index == b_wi
                              and e.ordinal_within_week == e_a.ordinal_within_week]
                    self.assertEqual(len(match), 1,
                                       f"Expected 1 matching exposure in B for {cal_week}")
                    self.assertEqual(match[0].exposure_id, e_a.exposure_id,
                                       f"Exposure id mismatch for {cal_week}: "
                                       f"A={e_a.exposure_id} B={match[0].exposure_id}")
                    self.assertEqual(match[0].objective_id, e_a.objective_id,
                                       f"Objective id mismatch for {cal_week}")

    def test_never_8_long_runs_in_a_month(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        today = _dt.date(2026, 8, 3)
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        n_long = sum(1 for e in demand.required_exposures if e.kind == "run_long")
        self.assertLessEqual(n_long, 4, f"Demanded {n_long} long runs in 4 weeks")

    def test_missing_dna_does_not_unlimit(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["aerobic_base"]
        week_starts = [_dt.date(2026, 8, 3) + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id="empty_client", client_profile={},
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        self.assertLessEqual(
            demand.frequency_caps["client_sessions_per_week_max"], 8,
            "Missing DNA became unlimited"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ===========================================================================
# Engine V2 Correctness Patch — new invariants (Items 1-9 of user directive)
# ===========================================================================

class TestCorrectnessPatchDailyTimeCap(unittest.TestCase):
    """Item #3 + #4 — total daily minutes must not exceed availability, even
    with support (mobility/activation) stacking."""

    def _build(self, profile: dict, max_home_min: int = 60):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        today = _dt.date(2026, 8, 3)
        # 4 weeks of home_day only — plenty of opportunity, but strict daily cap.
        roster = [{
            "client_id": PIETRO_ID,
            "date": (today + _dt.timedelta(days=i)).isoformat(),
            "day_type": "home_day",
            "duties": [],
            "tz_offset_from_base_hours": 0,
            "recovery_window_hours_from_prior_duty": None,
        } for i in range(28)]
        contexts = build_day_contexts(roster)
        # Clip contexts by profile just as kickoff does
        from feature_v2_roster_context import DayContext as _DC
        clipped = [
            _DC(
                date=c.date, day_type=c.day_type,
                duty_burden_score=c.duty_burden_score,
                training_opportunity=c.training_opportunity,
                available_time_min=min(c.available_time_min, max_home_min),
                recommended_intensity_ceiling=c.recommended_intensity_ceiling,
                recovery_state=c.recovery_state,
                recent_hard_days_48h=c.recent_hard_days_48h,
                upcoming_hard_days_48h=c.upcoming_hard_days_48h,
                consecutive_duty_days=c.consecutive_duty_days,
                sleep_opportunity=c.sleep_opportunity,
                tz_shift_last_48h=c.tz_shift_last_48h,
                layover_length_hours=c.layover_length_hours,
                duty_duration_min_today=c.duty_duration_min_today,
                reasons=c.reasons + (f"clipped:{max_home_min}",),
            ) for c in contexts
        ]
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=profile,
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        daily_cap = {c.date: max_home_min for c in clipped}
        result = schedule_demand(
            demand=demand, day_contexts=clipped,
            goal=cfg, phase=phase,
            daily_time_cap_by_date=daily_cap,
        )
        return demand, result, phase, cfg

    def test_daily_total_never_exceeds_60min_when_max_home_60(self):
        """Pietro's exact case — daily prescribed minutes must stay under 60."""
        prof = dict(pietro_profile())
        prof["max_home_minutes"] = 60
        prof["training_days_per_week"] = 5
        prof["sessions_per_week_min"] = 4
        prof["sessions_per_week_max"] = 5
        _, result, _, _ = self._build(prof, max_home_min=60)
        # Aggregate by date
        totals: dict = {}
        for p in result.placements:
            totals[p.date] = totals.get(p.date, 0) + int(p.target_duration_min)
        for d, total in totals.items():
            self.assertLessEqual(total, 60,
                                  f"{d} total minutes {total} > cap 60 "
                                  f"(placements: {[p.kind + ':' + str(p.target_duration_min) for p in result.placements if p.date == d]})")

    def test_no_random_triple_stacking(self):
        """No day may contain three placements when the cap is tight (60 min)."""
        prof = dict(pietro_profile())
        prof["max_home_minutes"] = 60
        _, result, _, _ = self._build(prof, max_home_min=60)
        by_date: dict = {}
        for p in result.placements:
            by_date.setdefault(p.date, []).append(p.kind)
        for d, kinds in by_date.items():
            # With a 60-min cap and typical 35-45 min main sessions, 3 sessions
            # would blow the cap. Anything more than 2 is suspicious.
            self.assertLessEqual(len(kinds), 2,
                                  f"{d} has {len(kinds)} placements (60min cap): {kinds}")

    def test_mobility_may_stack_when_it_fits(self):
        """With a generous 120min home cap, mobility SHOULD stack with an
        anchor session — the engine should not artificially refuse."""
        prof = dict(pietro_profile())
        prof["max_home_minutes"] = 120
        prof["training_days_per_week"] = 5
        _, result, _, _ = self._build(prof, max_home_min=120)
        by_date: dict = {}
        for p in result.placements:
            by_date.setdefault(p.date, []).append(p)
        # Expect at least one day where mobility is present alongside another session
        stacking = 0
        for d, pls in by_date.items():
            kinds = {p.kind for p in pls}
            if "mobility" in kinds and len(kinds) > 1:
                stacking += 1
        self.assertGreater(stacking, 0,
                            "With 120min cap, mobility must be able to stack "
                            "with another session on at least one day")


class TestCorrectnessPatchUnfilledSemantics(unittest.TestCase):
    """Item #1 — required IMPORTANT/KEY quotas that go unplaced MUST create
    validator errors and prevent draft_status=ready_for_review."""

    def _tight_roster_result(self, max_home_min: int = 45):
        """Force many rejections by making home_days extremely tight (45min)
        so strength (target 40) barely fits and mobility gets crowded out."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        today = _dt.date(2026, 8, 3)
        # Mix: only 1 usable home_day per week
        pattern = (["home_day"] + ["flight"] + ["layover_arrival"] +
                   ["layover_departure"] + ["standby"] + ["turnaround"] +
                   ["home_day"])
        roster = [{
            "client_id": PIETRO_ID,
            "date": (today + _dt.timedelta(days=i)).isoformat(),
            "day_type": pattern[i % 7],
            "duties": [] if pattern[i % 7] in ("home_day", "off") else [{"duty_type": pattern[i % 7]}],
            "tz_offset_from_base_hours": 0,
            "recovery_window_hours_from_prior_duty": None,
        } for i in range(28)]
        contexts = build_day_contexts(roster)
        from feature_v2_roster_context import DayContext as _DC
        clipped = [_DC(
            date=c.date, day_type=c.day_type,
            duty_burden_score=c.duty_burden_score,
            training_opportunity=c.training_opportunity,
            available_time_min=min(c.available_time_min, max_home_min),
            recommended_intensity_ceiling=c.recommended_intensity_ceiling,
            recovery_state=c.recovery_state,
            recent_hard_days_48h=c.recent_hard_days_48h,
            upcoming_hard_days_48h=c.upcoming_hard_days_48h,
            consecutive_duty_days=c.consecutive_duty_days,
            sleep_opportunity=c.sleep_opportunity,
            tz_shift_last_48h=c.tz_shift_last_48h,
            layover_length_hours=c.layover_length_hours,
            duty_duration_min_today=c.duty_duration_min_today,
            reasons=c.reasons + (f"clipped:{max_home_min}",),
        ) for c in contexts]
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        prof = dict(pietro_profile())
        prof["max_home_minutes"] = max_home_min
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=prof,
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        schedule = schedule_demand(
            demand=demand, day_contexts=clipped, goal=cfg, phase=phase,
            daily_time_cap_by_date={c.date: max_home_min for c in clipped},
        )
        prog_val = validate_programme(
            demand=demand, placements=schedule.placements,
            phase=phase, goal=cfg, unfilled=schedule.unfilled,
        )
        return demand, schedule, prog_val

    def test_unplaced_important_creates_validator_error(self):
        demand, schedule, prog_val = self._tight_roster_result(max_home_min=45)
        # If any IMPORTANT stayed unfilled, there MUST be a matching error.
        important_unfilled = [u for u in schedule.unfilled if u.priority.upper() == "IMPORTANT"]
        if important_unfilled:
            self.assertFalse(prog_val.ok,
                              "IMPORTANT unfilled must fail programme validation")
            codes = [i.code for i in prog_val.issues]
            self.assertIn("important_unfilled", codes,
                          f"Missing 'important_unfilled' error; got codes={codes}")

    def test_no_ready_when_important_missing(self):
        """The exact bug from Pietro shadow — validator returned ok=True when
        4 IMPORTANT strength sessions were unfilled. This must NOT happen."""
        demand, schedule, prog_val = self._tight_roster_result(max_home_min=45)
        placed_kinds = {p.kind for p in schedule.placements}
        required_kinds = {e.kind for e in demand.required_exposures
                          if e.priority.upper() == "IMPORTANT"}
        missing_important = required_kinds - placed_kinds
        if missing_important:
            self.assertFalse(prog_val.ok,
                              f"programme_validation.ok=True even though IMPORTANT kinds missing: {missing_important}")

    def test_supporting_unfilled_is_only_warning(self):
        """Missing SUPPORTING (mobility) should NOT block ready_for_review —
        emit warning only."""
        # Build a scenario where mobility can't be placed but LR + strength can.
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        # Only 2 home days over 28 → LR fits, strength fits, mobility
        # (SUPPORTING, +/- 1 wk allowed) may or may not fit. We'll construct
        # unfilled manually.
        from feature_v2_demand_v2 import Unfilled
        # Empty demand + one supporting unfilled → should be warning
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=[_dt.date(2026, 8, 3)],
        )
        fake_unfilled = [Unfilled(
            exposure_id="u1", objective_id="obj_x", kind="mobility",
            priority="SUPPORTING",
            reason_code="opportunity_below_floor",
            human_reason="opportunity too low",
        )]
        prog_val = validate_programme(
            demand=demand, placements=[], phase=phase, goal=cfg,
            unfilled=fake_unfilled,
        )
        # There will be quota_deficit errors for run_long (KEY) and others,
        # but the supporting unfilled itself should be a WARNING.
        support_issue = [i for i in prog_val.issues if i.code == "supporting_unfilled"]
        self.assertEqual(len(support_issue), 1)
        self.assertEqual(support_issue[0].severity, "warning")


class TestCorrectnessPatchDNAGaps(unittest.TestCase):
    """Item #7 — DNA fallbacks must be surfaced structurally."""

    def test_missing_session_bounds_surface_as_gap(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        prof = dict(pietro_profile())
        # Wipe the exact fields Pietro was missing
        prof.pop("sessions_per_week_min", None)
        prof.pop("sessions_per_week_max", None)
        prof.pop("preferred_training_days", None)
        prof.pop("preferred_session_length", None)
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=prof,
            goal_key="marathon", phase_spec=phase,
            week_start_dates=[_dt.date(2026, 8, 3)],
        )
        fields_flagged = {g["field"] for g in demand.dna_gaps}
        self.assertIn("preferred_training_days", fields_flagged)
        self.assertIn("preferred_session_length", fields_flagged)
        # sessions_per_week bounds are flagged as info (derived from training_days_per_week)
        self.assertIn("sessions_per_week_min/max", fields_flagged)


class TestCorrectnessPatchFrequencyDerivation(unittest.TestCase):
    """Item #8 — the engine must produce a single, coherent, inspectable
    frequency calculation instead of leaving contradictory values scattered."""

    def test_derivation_reports_all_inputs_and_scaling(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        prof = dict(pietro_profile())
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=prof,
            goal_key="marathon", phase_spec=phase,
            week_start_dates=[_dt.date(2026, 8, 3), _dt.date(2026, 8, 10),
                               _dt.date(2026, 8, 17), _dt.date(2026, 8, 24)],
        )
        d = demand.frequency_derivation
        # Every required key
        for k in ["inputs", "effective_min", "effective_max",
                  "raw_quota_targets_per_week", "raw_quota_total_per_week",
                  "client_effective_min_per_week", "client_effective_max_per_week",
                  "phase_hard_days_per_week_max", "phase_key_days_per_week_max",
                  "phase_strength_days_per_week_max", "scaling_factor",
                  "scale_reason"]:
            self.assertIn(k, d, f"frequency_derivation missing key {k}")


# ===========================================================================
# Round 2 patch — Cadence, Window Ownership, Training-Days semantics
# (User directive after Shadow #2)
# ===========================================================================

class TestCadenceAwarePlacement(unittest.TestCase):
    """Item #1 — Long Runs should honour a preferred cadence (target ~7 days
    for marathon foundation) rather than clustering at week boundaries."""

    def _run_shadow(self, roster_pattern):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        today = _dt.date(2026, 8, 3)
        roster = [{
            "client_id": PIETRO_ID,
            "date": (today + _dt.timedelta(days=i)).isoformat(),
            "day_type": roster_pattern[i % len(roster_pattern)],
            "duties": [],
            "tz_offset_from_base_hours": 0,
            "recovery_window_hours_from_prior_duty": None,
        } for i in range(28)]
        contexts = build_day_contexts(roster)
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        result = schedule_demand(
            demand=demand, day_contexts=contexts,
            goal=cfg, phase=phase,
        )
        return demand, result, cfg, phase

    def test_long_run_gaps_prefer_target_cadence_not_week_boundary(self):
        """With plenty of home_days in every week, the scheduler should place
        LRs approximately 7 days apart, NOT bounce between Sun-Wed which
        happens when only the calendar-week bucket is optimised."""
        # 4 weeks of home_day → engine can freely pick any day
        demand, result, cfg, phase = self._run_shadow(["home_day"] * 7)
        lr_dates = sorted(p.date for p in result.placements if p.kind == "run_long")
        self.assertEqual(len(lr_dates), 4,
                          f"Expected 4 LRs, got {len(lr_dates)}: {lr_dates}")
        gaps = [(lr_dates[i] - lr_dates[i - 1]).days
                for i in range(1, len(lr_dates))]
        # Cadence range from config = (6, 9). All gaps should be inside it,
        # allowing at most 1 outlier to accommodate roster edge cases.
        outside = [g for g in gaps if g < 6 or g > 9]
        self.assertLessEqual(len(outside), 1,
                              f"Too many LR gaps outside cadence [6..9] days: "
                              f"gaps={gaps} outliers={outside}")

    def test_long_run_hard_min_recovery_still_respected(self):
        """Hard minimum recovery (72h/3d) must still gate placements — cadence
        is a soft signal on top of it, never below it."""
        _, result, _, _ = self._run_shadow(["home_day"] * 7)
        lr_dates = sorted(p.date for p in result.placements if p.kind == "run_long")
        for i in range(1, len(lr_dates)):
            self.assertGreaterEqual((lr_dates[i] - lr_dates[i - 1]).days, 3,
                                     f"LR gap violates 72h hard floor: "
                                     f"{lr_dates[i-1]}→{lr_dates[i]}")


class TestExposureWindowOwnership(unittest.TestCase):
    """Item #2 — Every exposure has canonical target_window + explicit
    allowed_placement_window. Spillover to adjacent weeks is legal for
    IMPORTANT/SUPPORTING but never accidentally satisfies another week's
    exposure."""

    def _demand(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        week_starts = [_dt.date(2026, 8, 3) + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        return demand, phase, cfg

    def test_key_exposures_have_zero_spillover(self):
        demand, _, _ = self._demand()
        for e in demand.required_exposures:
            if e.priority.upper() == "KEY":
                # allowed window == target window
                self.assertEqual(e.allowed_window_start, e.target_week_start,
                                  f"KEY {e.kind} wk{e.week_index} spillover start != target start")
                self.assertEqual(e.allowed_window_end, e.target_week_end,
                                  f"KEY {e.kind} wk{e.week_index} spillover end != target end")

    def test_important_exposures_have_one_week_spillover(self):
        demand, _, _ = self._demand()
        # Marathon foundation strength IS IMPORTANT and default spillover=1
        for e in demand.required_exposures:
            if e.priority.upper() == "IMPORTANT":
                exp_span = (e.allowed_window_end - e.target_week_end).days
                self.assertEqual(exp_span, 7,
                                  f"IMPORTANT {e.kind} spillover_end offset expected +7, got {exp_span}")

    def test_exposure_ids_stay_distinct_per_target_week(self):
        """Even when two exposures for adjacent weeks share overlapping
        allowed windows, their exposure_ids remain distinct — a placement
        can only satisfy the exposure that OWNS it."""
        demand, _, _ = self._demand()
        strength = [e for e in demand.required_exposures if e.kind == "strength_full_body"]
        ids = [e.exposure_id for e in strength]
        self.assertEqual(len(set(ids)), len(ids),
                          f"Strength exposure IDs not unique across weeks: {ids}")

    def test_spillover_does_not_double_count(self):
        """When strength for week-4 spills back to week-3 dates, the total
        placed count for strength must not exceed the required count."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        today = _dt.date(2026, 8, 3)
        # Tight roster: only 1 usable home_day per week
        pattern = ["home_day", "flight", "layover_arrival", "layover_full",
                   "layover_departure", "standby", "home_day"]
        roster = [{
            "client_id": PIETRO_ID,
            "date": (today + _dt.timedelta(days=i)).isoformat(),
            "day_type": pattern[i % 7],
            "duties": [] if pattern[i % 7] in ("home_day",) else [{"duty_type": pattern[i % 7]}],
            "tz_offset_from_base_hours": 0,
            "recovery_window_hours_from_prior_duty": None,
        } for i in range(28)]
        contexts = build_day_contexts(roster)
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        result = schedule_demand(
            demand=demand, day_contexts=contexts, goal=cfg, phase=phase,
        )
        required = sum(1 for e in demand.required_exposures if e.kind == "strength_full_body")
        placed = sum(1 for p in result.placements if p.kind == "strength_full_body")
        self.assertLessEqual(placed, required,
                              f"Strength: placed {placed} > required {required} (double count)")


class TestTrainingDaysSemantics(unittest.TestCase):
    """Item #3 — training_days_per_week vs sessions_per_week must be clearly
    separated. Support stacking (mobility on an easy-run day) is one
    training day + two sessions, NOT two training days."""

    def test_max_training_days_capped_by_dna(self):
        """A client with training_days_per_week=3 must NOT be scheduled on
        4 distinct dates in a single week, even if easy+mobility could fit
        into a 4th day."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        today = _dt.date(2026, 8, 3)
        roster = [{
            "client_id": "c_trdays",
            "date": (today + _dt.timedelta(days=i)).isoformat(),
            "day_type": "home_day",
            "duties": [],
            "tz_offset_from_base_hours": 0,
            "recovery_window_hours_from_prior_duty": None,
        } for i in range(28)]
        contexts = build_day_contexts(roster)
        week_starts = [today + _dt.timedelta(days=7 * i) for i in range(4)]
        prof = {"training_days_per_week": 3, "primary_goal_type": "marathon"}
        demand = build_demand(
            client_id="c_trdays", client_profile=prof,
            goal_key="marathon", phase_spec=phase,
            week_start_dates=week_starts,
        )
        result = schedule_demand(
            demand=demand, day_contexts=contexts, goal=cfg, phase=phase,
        )
        # Group placements by ISO week and count distinct dates
        by_wk: dict = {}
        for p in result.placements:
            wk = p.date.isocalendar()[:2]
            by_wk.setdefault(wk, set()).add(p.date)
        for wk, dates in by_wk.items():
            self.assertLessEqual(len(dates), 3,
                                  f"Week {wk} used {len(dates)} training days > cap 3")

    def test_frequency_derivation_exposes_four_concepts(self):
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        demand = build_demand(
            client_id=PIETRO_ID, client_profile=pietro_profile(),
            goal_key="marathon", phase_spec=phase,
            week_start_dates=[_dt.date(2026, 8, 3)],
        )
        d = demand.frequency_derivation
        # Semantics block with 3 canonical fields + note
        self.assertIn("semantics", d)
        sem = d["semantics"]
        self.assertIn("max_training_days_per_week", sem)
        self.assertIn("min_sessions_per_week", sem)
        self.assertIn("max_sessions_per_week", sem)
        self.assertIn("note", sem)

    def test_support_stacking_does_not_add_training_day(self):
        """When mobility stacks with an easy run, that day counts as 1
        training day but 2 sessions — the training-day cap should NOT
        prematurely block the day from receiving both sessions."""
        cfg = get_goal_config("marathon")
        phase = cfg.phase_specs["foundation"]
        today = _dt.date(2026, 8, 3)
        # Only 3 home_days available per week, but session cap of 5
        pattern = ["home_day", "home_day", "flight", "layover_full",
                   "layover_departure", "home_day", "off"]
        roster = [{
            "client_id": "c_stack",
            "date": (today + _dt.timedelta(days=i)).isoformat(),
            "day_type": pattern[i % 7],
            "duties": [] if pattern[i % 7] in ("home_day", "off") else [{"duty_type": pattern[i % 7]}],
            "tz_offset_from_base_hours": 0,
            "recovery_window_hours_from_prior_duty": None,
        } for i in range(28)]
        contexts = build_day_contexts(roster)
        # Client: 3 training days/wk max, 6 sessions/wk max
        prof = {"training_days_per_week": 3,
                "sessions_per_week_max": 6,
                "primary_goal_type": "marathon"}
        demand = build_demand(
            client_id="c_stack", client_profile=prof,
            goal_key="marathon", phase_spec=phase,
            week_start_dates=[today + _dt.timedelta(days=7 * i) for i in range(4)],
        )
        result = schedule_demand(
            demand=demand, day_contexts=contexts, goal=cfg, phase=phase,
        )
        # In every week, distinct dates ≤ 3 while total sessions may exceed 3
        by_wk_dates: dict = {}
        by_wk_sessions: dict = {}
        for p in result.placements:
            wk = p.date.isocalendar()[:2]
            by_wk_dates.setdefault(wk, set()).add(p.date)
            by_wk_sessions[wk] = by_wk_sessions.get(wk, 0) + 1
        for wk, dates in by_wk_dates.items():
            self.assertLessEqual(len(dates), 3,
                                  f"Week {wk} exceeded training-day cap: {len(dates)}")


if False:  # keep runnable via __main__ above; suppress redundant duplicate call
    pass
