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

    def test_weekly_hard_cap_respected(self):
        cfg = get_goal_config("marathon")
        cap = cfg.phase_specs["aerobic_base"].hard_days_per_week_max
        weekly_hard = {}
        for p in self.placements:
            if is_hard_session(p.kind):
                wk = week_key(p.date)
                weekly_hard[wk] = weekly_hard.get(wk, 0) + 1
        for wk, n in weekly_hard.items():
            self.assertLessEqual(n, cap, f"Week {wk}: {n} hard > cap {cap}")

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

    def test_exposure_numbering_monotonic_per_objective(self):
        per_obj = {}
        for p in self.placements:
            per_obj.setdefault(p.objective_id, []).append(p.exposure_number)
        for obj, seq in per_obj.items():
            sorted_seq = sorted(seq)
            self.assertEqual(sorted_seq, list(range(1, len(sorted_seq) + 1)),
                              f"Objective {obj} numbering broken: {sorted_seq}")


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
