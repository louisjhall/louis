"""Iter 131a — KEY rescue + aligned strength-spacing behaviour.

Covers the four changes shipped in Iter 131a:

1. `_STRENGTH_FORBIDDEN` no longer forbids adjacent-day
   `strength_full → strength_full`.
2. `session_family_recovery_hours["strength_full"]` reduced 48h → 24h in
   every goal that previously enforced 48h. Same-day two-strength_full is
   still blocked (0h < 24h) but next-day is permitted.
3. `key_spacing_48h` in the sequencer now only fires across DIFFERENT
   families (cross-family KEY-to-KEY still 48h; same-family KEY-to-KEY
   deferred to family recovery).
4. `schedule_demand` now runs a single-pass KEY-rescue after the greedy
   loop: any unfilled KEY exposure evicts a same-week SUPPORTING placement
   that opened a new training date, and retries. Restores if KEY still
   fails.

Also re-confirms:
* Consecutive/near-consecutive strength_full A/B/C is now permitted.
* Marathon draft with 0 Long Runs still ERROR (validator unchanged).
* Iter 130g/130h protections intact.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_v2_sport_configs import (  # noqa: E402
    canonicalise_goal_key, get_goal_config, is_forbidden_sequence,
    session_recovery_hours, SPORT_CONFIGS,
)
from feature_v2_sequencing import (  # noqa: E402
    Placement, PlacementPlan, validate_placement, apply_placement, week_key,
)
from feature_v2_demand_v2 import (  # noqa: E402
    build_demand, schedule_demand, RequiredExposure, Unfilled,
)
from feature_v2_roster_context import DayContext  # noqa: E402
from feature_v2_validators_v2 import validate_programme  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _monday() -> _dt.date:
    d = _dt.date(2026, 6, 1)
    return d - _dt.timedelta(days=d.weekday())


def _week_days_ctx(monday: _dt.date, *,
                    opportunity: int = 90, cap_min: int = 90,
                    day_type: str = "home_day") -> list[DayContext]:
    """Seven generous DayContexts starting Monday."""
    out = []
    for i in range(7):
        d = monday + _dt.timedelta(days=i)
        out.append(DayContext(
            date=d, day_type=day_type,
            duty_burden_score=0, training_opportunity=opportunity,
            available_time_min=cap_min,
            recommended_intensity_ceiling=None,
            recovery_state="fresh",
            recent_hard_days_48h=0,
            upcoming_hard_days_48h=0,
            consecutive_duty_days=0,
            sleep_opportunity="normal",
            tz_shift_last_48h=0,
            layover_length_hours=0,
            duty_duration_min_today=0,
            reasons=[],
        ))
    return out


def _fat_loss_setup():
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    return goal, phase


# ---------------------------------------------------------------------------
# Rule 1 — adjacent-day strength_full is no longer forbidden
# ---------------------------------------------------------------------------

class TestRule1_AdjacentDayNoLongerForbidden(unittest.TestCase):

    def test_strength_full_to_strength_full_not_in_forbidden_list(self):
        for goal_key in [
            "strength.fat_loss", "strength.hypertrophy", "strength.general",
            "running.marathon", "running.10k",
        ]:
            self.assertFalse(
                is_forbidden_sequence(
                    "strength_full_body", "strength_full_body", goal_key
                ),
                f"strength_full → strength_full unexpectedly forbidden for {goal_key}"
            )

    def test_strength_full_to_run_long_still_forbidden(self):
        # Regression: this pair MUST remain forbidden.
        self.assertTrue(
            is_forbidden_sequence(
                "strength_full_body", "run_long", "running.marathon"
            )
        )


# ---------------------------------------------------------------------------
# Rule 2 — 24h family recovery for strength_full
# ---------------------------------------------------------------------------

class TestRule2_FamilyRecovery24h(unittest.TestCase):

    def test_strength_full_recovery_is_24h_across_relevant_goals(self):
        for goal_key in [
            "strength.fat_loss", "strength.hypertrophy", "strength.general",
            "strength.functional_fitness", "running.10k",
        ]:
            self.assertEqual(
                session_recovery_hours("strength_full_body", goal_key), 24,
                f"{goal_key} still enforces >24h family recovery for strength_full"
            )

    def test_same_day_two_strength_full_still_blocked(self):
        goal, phase = _fat_loss_setup()
        monday = _monday()
        plan = PlacementPlan(placements=[])
        apply_placement(plan, exposure_id="e1", objective_id="obj_s",
                        kind="strength_full_body", date=monday,
                        priority="KEY", intensity_target="rpe6-7",
                        target_duration_min=45)
        check = validate_placement(
            kind="strength_full_body", date=monday, plan=plan,
            goal=goal, phase=phase,
            day_ctx_burden=0, day_ctx_opportunity=90,
            priority="KEY", target_duration_min=45,
            daily_time_cap_min=180,
        )
        self.assertFalse(check.ok,
                          f"Same-day two-strength_full unexpectedly allowed: {check.reason_code}")

    def test_next_day_strength_full_is_now_permitted(self):
        goal, phase = _fat_loss_setup()
        monday = _monday()
        plan = PlacementPlan(placements=[])
        apply_placement(plan, exposure_id="e1", objective_id="obj_s",
                        kind="strength_full_body", date=monday,
                        priority="KEY", intensity_target="rpe6-7",
                        target_duration_min=45)
        # Try Tuesday (24h later)
        check = validate_placement(
            kind="strength_full_body", date=monday + _dt.timedelta(days=1),
            plan=plan, goal=goal, phase=phase,
            day_ctx_burden=0, day_ctx_opportunity=90,
            priority="KEY", target_duration_min=45,
            daily_time_cap_min=180,
        )
        self.assertTrue(check.ok,
                         f"Next-day strength_full rejected: {check.reason_code}: {check.human_reason}")


# ---------------------------------------------------------------------------
# Rule 3 — key_spacing safeguard is cross-family only
# ---------------------------------------------------------------------------

class TestRule3_KeySpacingCrossFamilyOnly(unittest.TestCase):

    def test_same_family_key_next_day_ok(self):
        """strength_full KEY on Mon + strength_full KEY on Tue → OK
        (fell through to 24h family recovery, which is satisfied)."""
        goal, phase = _fat_loss_setup()
        monday = _monday()
        plan = PlacementPlan(placements=[])
        apply_placement(plan, exposure_id="e1", objective_id="obj_s",
                        kind="strength_full_body", date=monday,
                        priority="KEY", intensity_target="rpe6-7",
                        target_duration_min=45)
        check = validate_placement(
            kind="strength_full_body", date=monday + _dt.timedelta(days=1),
            plan=plan, goal=goal, phase=phase,
            day_ctx_burden=0, day_ctx_opportunity=90,
            priority="KEY", target_duration_min=45,
            daily_time_cap_min=180,
        )
        self.assertTrue(check.ok, f"same-family KEY D+1 rejected: {check.reason_code}")

    def test_cross_family_key_next_day_still_blocked(self):
        """strength_full KEY on Mon + run_long KEY on Tue is a CROSS-family
        pair. It must still be blocked by:
        (a) the strength_full→run_long forbidden sequence, and/or
        (b) the narrowed key_spacing_48h_cross_family safeguard."""
        goal = get_goal_config("running.marathon")
        phase = goal.phase_specs["aerobic_base"]
        monday = _monday()
        plan = PlacementPlan(placements=[])
        apply_placement(plan, exposure_id="e1", objective_id="obj_s",
                        kind="strength_full_body", date=monday,
                        priority="KEY", intensity_target="rpe6-7",
                        target_duration_min=45)
        check = validate_placement(
            kind="run_long", date=monday + _dt.timedelta(days=1),
            plan=plan, goal=goal, phase=phase,
            day_ctx_burden=0, day_ctx_opportunity=90,
            priority="KEY", target_duration_min=90,
            daily_time_cap_min=180,
        )
        self.assertFalse(check.ok,
                          "Cross-family KEY-to-KEY on adjacent days must remain blocked")
        # The block may come from either forbidden_sequence or cross-family
        # safeguard — both are acceptable.
        self.assertIn(check.reason_code,
                       ("forbidden_sequence", "key_spacing_48h_cross_family",
                        "insufficient_family_recovery_next", "insufficient_family_recovery"))


# ---------------------------------------------------------------------------
# Rule 4 — KEY rescue post-pass
# ---------------------------------------------------------------------------

class TestRule4_KeyRescuePostPass(unittest.TestCase):

    def test_key_rescue_evicts_supporting_when_key_would_otherwise_fail(self):
        """
        Setup: strength.fat_loss foundation demands 3 KEY strength_full_body.
        Constrain the week so only Monday and Wednesday have KEY-clearing
        opportunity (≥55). The other days have opportunity=30 (SUPPORTING
        floor is 25, so support can go anywhere; KEY floor is 55 so KEY
        cannot).
        Pre-existing placement: a SUPPORTING mobility on Wednesday (which
        opened a training day).
        Expected: after schedule_demand, all 3 KEY strength_full_body
        should be placed. The KEY-rescue pass should have evicted the
        Wednesday mobility to make room for the 3rd strength.
        """
        goal, phase = _fat_loss_setup()
        monday = _monday()

        # Build DayContexts where only Mon (0) and Wed (2) allow KEY.
        ctxs: list[DayContext] = []
        for i in range(7):
            d = monday + _dt.timedelta(days=i)
            opp = 90 if i in (0, 2, 4) else 30
            ctxs.append(DayContext(
                date=d, day_type="home_day",
                duty_burden_score=0, training_opportunity=opp,
                available_time_min=90 if opp == 90 else 45,
                recommended_intensity_ceiling=None,
                recovery_state="fresh",
                recent_hard_days_48h=0,
                upcoming_hard_days_48h=0,
                consecutive_duty_days=0,
                sleep_opportunity="normal",
                tz_shift_last_48h=0,
                layover_length_hours=0,
                duty_duration_min_today=0,
                reasons=[],
            ))

        # Demand: 3 KEY strength + 1 SUPPORTING mobility (in target week)
        demand = build_demand(
            client_id="joel_test",
            client_profile={
                "primary_goal": "fat_loss",
                "training_days_per_week": 5,
                "sessions_per_week_min": 3,
                "sessions_per_week_max": 5,
                "preferred_training_days": ["mon", "tue", "wed", "thu", "fri"],
                "training_experience": "intermediate",
                "variety_preference": "high",
                "cardio_preference": "elliptical",
                "dislikes_running": True,
            },
            goal_key=goal.key,
            phase_spec=phase,
            week_start_dates=[monday],
        )

        # We simulate the pathology by seeding a SUPPORTING placement on
        # Wed BEFORE the scheduler runs — a scenario that can also arise
        # naturally when SUPPORTING wins the cadence-rank on Wed. The
        # scheduler's greedy pass then finds 3 KEY exposures but only 2
        # KEY-cleared days (Mon + Fri) — the 3rd KEY falls into unfilled.
        # The rescue pass evicts the Wed mobility and retries KEY there.
        existing = [
            Placement(
                exposure_id="preplaced_mob",
                objective_id="obj_mob",
                kind="mobility",
                date=monday + _dt.timedelta(days=2),
                priority="SUPPORTING", exposure_number=1,
                intensity_class="EASY",
                target_duration_min=15,
                intensity_target="flow",
                key=False,
            )
        ]

        result = schedule_demand(
            demand=demand, day_contexts=ctxs,
            goal=goal, phase=phase,
            preferred_weekdays={0, 1, 2, 3, 4},
            existing_placements=existing,
        )

        strength_placements = [
            p for p in result.placements if p.kind == "strength_full_body"
        ]
        self.assertEqual(
            len(strength_placements), 3,
            f"Expected 3 strength_full_body placements after rescue, got "
            f"{len(strength_placements)}. Placements: "
            f"{[(p.kind, p.date) for p in result.placements]}. "
            f"Unfilled: {[(u.kind, u.priority) for u in result.unfilled]}"
        )
        # And it should have taken the Wed slot (the one we pre-placed
        # a support on).
        wed_date = monday + _dt.timedelta(days=2)
        wed_strengths = [p for p in strength_placements if p.date == wed_date]
        self.assertEqual(
            len(wed_strengths), 1,
            "Rescue was expected to reclaim the Wed slot for KEY strength"
        )
        # And the mobility that got evicted should show up in unfilled
        # with reason 'displaced_by_key_rescue' OR be re-placed elsewhere
        # (support may find another support-eligible date).
        # We only assert that KEY was placed correctly, since a re-place
        # of mobility elsewhere is acceptable.

    def test_key_rescue_restores_supporting_if_key_still_fails(self):
        """If the evicted date still fails KEY validation (e.g. below
        opportunity floor), the SUPPORTING must be restored exactly."""
        goal, phase = _fat_loss_setup()
        monday = _monday()

        # ALL days below KEY floor (55) — KEY cannot pass anywhere.
        ctxs: list[DayContext] = []
        for i in range(7):
            d = monday + _dt.timedelta(days=i)
            ctxs.append(DayContext(
                date=d, day_type="home_day",
                duty_burden_score=0, training_opportunity=40,  # below KEY floor
                available_time_min=60,
                recommended_intensity_ceiling=None,
                recovery_state="fresh",
                recent_hard_days_48h=0,
                upcoming_hard_days_48h=0,
                consecutive_duty_days=0,
                sleep_opportunity="normal",
                tz_shift_last_48h=0,
                layover_length_hours=0,
                duty_duration_min_today=0,
                reasons=[],
            ))
        demand = build_demand(
            client_id="joel_test",
            client_profile={
                "primary_goal": "fat_loss",
                "training_days_per_week": 3,
                "preferred_training_days": ["mon", "tue", "wed", "thu", "fri"],
                "training_experience": "intermediate",
                "variety_preference": "high",
                "cardio_preference": "elliptical",
                "dislikes_running": True,
            },
            goal_key=goal.key,
            phase_spec=phase,
            week_start_dates=[monday],
        )
        # Preplace a SUPPORTING that would look like a rescue candidate
        existing = [
            Placement(
                exposure_id="preplaced_mob",
                objective_id="obj_mob",
                kind="mobility",
                date=monday + _dt.timedelta(days=2),
                priority="SUPPORTING", exposure_number=1,
                intensity_class="EASY",
                target_duration_min=15,
                intensity_target="flow",
                key=False,
            )
        ]
        result = schedule_demand(
            demand=demand, day_contexts=ctxs,
            goal=goal, phase=phase,
            preferred_weekdays={0, 1, 2, 3, 4},
            existing_placements=existing,
        )
        # SUPPORTING must still be present because rescue failed.
        preserved = [p for p in result.placements
                     if p.exposure_id == "preplaced_mob"]
        self.assertEqual(len(preserved), 1,
                          "Preplaced SUPPORTING should have been restored")


# ---------------------------------------------------------------------------
# Marathon Long-Run validator regression
# ---------------------------------------------------------------------------

class TestMarathonLongRunStillErrors(unittest.TestCase):

    def test_marathon_missing_long_run_still_errors(self):
        goal = get_goal_config("running.marathon")
        phase = goal.phase_specs["aerobic_base"]
        monday = _monday()
        demand = build_demand(
            client_id="pietro_test",
            client_profile={
                "primary_goal": "marathon",
                "training_days_per_week": 5,
                "preferred_training_days": ["mon", "wed", "fri", "sat", "sun"],
                "training_experience": "intermediate",
                "variety_preference": "moderate",
                "cardio_preference": "run",
            },
            goal_key="running.marathon",
            phase_spec=phase,
            week_start_dates=[monday],
        )
        # Placements: 2 easy runs + 2 strength, but NO long run
        placements = [
            Placement(exposure_id="e1", objective_id="obj_re",
                       kind="run_easy",
                       date=monday, priority="SUPPORTING", exposure_number=1,
                       intensity_class="EASY", target_duration_min=30,
                       intensity_target="z2", key=False),
            Placement(exposure_id="e2", objective_id="obj_re",
                       kind="run_easy",
                       date=monday + _dt.timedelta(days=2),
                       priority="SUPPORTING", exposure_number=2,
                       intensity_class="EASY", target_duration_min=30,
                       intensity_target="z2", key=False),
            Placement(exposure_id="e3", objective_id="obj_sf",
                       kind="strength_full_body",
                       date=monday + _dt.timedelta(days=1),
                       priority="IMPORTANT", exposure_number=1,
                       intensity_class="HARD", target_duration_min=45,
                       intensity_target="rpe7", key=False),
            Placement(exposure_id="e4", objective_id="obj_sf",
                       kind="strength_full_body",
                       date=monday + _dt.timedelta(days=3),
                       priority="IMPORTANT", exposure_number=2,
                       intensity_class="HARD", target_duration_min=45,
                       intensity_target="rpe7", key=False),
        ]
        caps = {monday + _dt.timedelta(days=i): 90 for i in range(7)}
        day_types = {(monday + _dt.timedelta(days=i)).isoformat(): "home_day"
                     for i in range(7)}
        v = validate_programme(
            demand=demand, placements=placements,
            phase=phase, goal=goal, unfilled=[],
            client_profile={"primary_goal": "marathon"},
            session_specs={}, weeks=1,
            daily_time_cap_by_date=caps,
            day_type_by_date=day_types,
        )
        errs = [(i.code, i.severity) for i in v.issues if i.severity == "error"]
        self.assertTrue(
            any(c[0] == "marathon_long_run_missing" for c in errs),
            f"Expected marathon_long_run_missing ERROR, got issues: {errs}"
        )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
