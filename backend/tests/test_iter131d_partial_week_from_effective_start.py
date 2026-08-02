"""Iter 131d — partial-week uses effective start date (not Monday alignment).

The Iter 131c partial-week fix used `window_start` as the lower bound, but
`engine_v2_kickoff` always sets `window_start` to the Monday of the current
week. That means for a Saturday-effective-start client, the opening week
was counted as 7 in-window days and the partial-week gate never fired —
so a 2-day opening week still emitted 3 compulsory KEY strength exposures.

This iteration adds `effective_start_date` to `build_demand` and passes
`today` from kickoff. Tests here exercise the **exact same argument shape
that `engine_v2_kickoff` produces**, so we can no longer pass an
"already-corrected" window_start and mask the bug.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_v2_sport_configs import get_goal_config  # noqa: E402
from feature_v2_sequencing import Placement  # noqa: E402
from feature_v2_demand_v2 import (  # noqa: E402
    build_demand, schedule_demand,
)
from feature_v2_roster_context import DayContext  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers that mirror engine_v2_kickoff's internal argument construction
# ---------------------------------------------------------------------------

def _kickoff_shape_args(today: _dt.date, weeks: int = 4):
    """Return (window_start, window_end, week_starts, effective_start_date)
    computed exactly as `feature_v2_engine_v2_kickoff.py` does at line ~361:

        window_start = today - timedelta(days=today.weekday())   # this Monday
        week_starts  = [window_start + 7*i for i in range(weeks)]
        window_end   = week_starts[-1] + timedelta(days=6)

    plus Iter 131d's effective_start_date = today.
    """
    window_start = today - _dt.timedelta(days=today.weekday())
    week_starts = [window_start + _dt.timedelta(days=7 * i) for i in range(weeks)]
    window_end = week_starts[-1] + _dt.timedelta(days=6)
    return window_start, window_end, week_starts, today


# ---------------------------------------------------------------------------
# Fix 1 — Saturday-start does not require full-week quota
# ---------------------------------------------------------------------------

class TestPartialWeekFromEffectiveStart(unittest.TestCase):

    def test_saturday_start_via_real_kickoff_shape(self):
        """Kickoff-shaped invocation: today = Sat 1 Aug 2026. The Monday
        of that week (Mon 27 Jul) becomes window_start, and the 2-day
        partial opening week must emit NO compulsory strength exposures.
        This is the failing case reported from Joel's Production rebuild."""
        goal = get_goal_config("strength.fat_loss")
        phase = goal.phase_specs["foundation"]

        today = _dt.date(2026, 8, 1)   # Saturday
        window_start, window_end, week_starts, effective_start = \
            _kickoff_shape_args(today, weeks=4)

        # Sanity: the shape matches the kickoff bug precisely.
        self.assertEqual(window_start, _dt.date(2026, 7, 27))  # Monday
        self.assertEqual(effective_start, _dt.date(2026, 8, 1))  # Saturday

        demand = build_demand(
            client_id="joel_test",
            client_profile={
                "primary_goal": "fat_loss",
                "training_days_per_week": 5,
                "preferred_training_days": ["mon", "tue", "wed", "thu", "fri"],
                "training_experience": "intermediate",
                "variety_preference": "high",
                "cardio_preference": "elliptical",
                "dislikes_running": True,
            },
            goal_key=goal.key,
            phase_spec=phase,
            week_start_dates=week_starts,
            window_start=window_start,
            window_end=window_end,
            effective_start_date=effective_start,
        )

        # The opening week (week_index=0) must have NO KEY strength
        # exposures — only 2 days (Sat + Sun) are usable, and a 3× KEY
        # weekly quota would be impossible.
        wk0_key = [
            e for e in demand.required_exposures
            if e.week_index == 0
            and e.priority.upper() == "KEY"
            and e.kind == "strength_full_body"
        ]
        self.assertEqual(
            len(wk0_key), 0,
            f"Opening 2-day partial week must emit NO KEY strength "
            f"exposures. Got {len(wk0_key)}: "
            f"{[(e.kind, e.target_week_start) for e in wk0_key]}. "
            f"Notes: {[n for n in demand.notes if 'partial' in n]}"
        )
        # A partial_week note should be recorded for week 0 so the coach
        # can see why the week was skipped.
        partial_notes_wk0 = [n for n in demand.notes
                             if "partial_week" in n and "2026-07-27" in n]
        self.assertGreaterEqual(
            len(partial_notes_wk0), 1,
            f"Expected partial_week note for week 2026-07-27. Notes: {demand.notes}"
        )

    def test_full_weeks_after_partial_still_emit_all_compulsory(self):
        """The 3 full weeks that follow the partial opening week must
        still emit 3 × KEY strength each."""
        goal = get_goal_config("strength.fat_loss")
        phase = goal.phase_specs["foundation"]

        today = _dt.date(2026, 8, 1)
        window_start, window_end, week_starts, effective_start = \
            _kickoff_shape_args(today, weeks=4)

        demand = build_demand(
            client_id="joel_test",
            client_profile={
                "primary_goal": "fat_loss",
                "training_days_per_week": 5,
                "preferred_training_days": ["mon", "tue", "wed", "thu", "fri"],
                "training_experience": "intermediate",
                "variety_preference": "high",
                "cardio_preference": "elliptical",
                "dislikes_running": True,
            },
            goal_key=goal.key,
            phase_spec=phase,
            week_start_dates=week_starts,
            window_start=window_start,
            window_end=window_end,
            effective_start_date=effective_start,
        )
        # For each of weeks 1, 2, 3 (full weeks), expect ≥3 KEY strength
        # exposures.
        for wk in (1, 2, 3):
            wk_key = [
                e for e in demand.required_exposures
                if e.week_index == wk
                and e.priority.upper() == "KEY"
                and e.kind == "strength_full_body"
            ]
            self.assertGreaterEqual(
                len(wk_key), 3,
                f"Full week {wk} must emit ≥3 KEY strength. Got {len(wk_key)}"
            )

    def test_marathon_full_week_still_requires_long_run(self):
        """Regression: a Pietro-style marathon full week must still emit
        the KEY Long Run."""
        goal = get_goal_config("running.marathon")
        phase = goal.phase_specs["foundation"]

        # Use a Monday-effective-start so all 4 weeks are full.
        today = _dt.date(2026, 8, 3)  # Monday
        window_start, window_end, week_starts, effective_start = \
            _kickoff_shape_args(today, weeks=4)
        self.assertEqual(window_start, today)  # sanity: today IS Monday

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
            week_start_dates=week_starts,
            window_start=window_start,
            window_end=window_end,
            effective_start_date=effective_start,
        )
        # Every full week must have ≥1 KEY run_long.
        for wk in range(4):
            wk_long = [
                e for e in demand.required_exposures
                if e.week_index == wk
                and e.priority.upper() == "KEY"
                and e.kind == "run_long"
            ]
            self.assertGreaterEqual(
                len(wk_long), 1,
                f"Marathon full week {wk} must emit ≥1 KEY run_long. Got {len(wk_long)}"
            )


# ---------------------------------------------------------------------------
# Fix 2 — Full-week 3× strength via bundle rescue, kickoff-shaped
# ---------------------------------------------------------------------------

class TestFullWeekThreeStrengthViaBundleRescue(unittest.TestCase):

    def test_stacked_cardio_plus_mobility_on_third_date_yields_3_strengths(self):
        """A Joel-style full week: 3 usable training dates. Two are used by
        the greedy pass for KEY strength #1 and #2. The 3rd usable date is
        pre-populated with BOTH aerobic Z2 and mobility. The bundle rescue
        must clear the whole bundle, place the 3rd KEY strength there, and
        re-add the mobility (which fits under the cap)."""
        goal = get_goal_config("strength.fat_loss")
        phase = goal.phase_specs["foundation"]

        # Full week Mon–Sun with a realistic Joel shape: Mon/Wed/Fri
        # available for KEY (opp 90, cap 60), other days low.
        monday = _dt.date(2026, 8, 3)  # Monday of full week
        ctxs = []
        for i in range(7):
            d = monday + _dt.timedelta(days=i)
            if i in (0, 2, 4):
                opp, cap = 90, 60
            else:
                opp, cap = 20, 45
            ctxs.append(DayContext(
                date=d, day_type="home_day",
                duty_burden_score=0, training_opportunity=opp,
                available_time_min=cap,
                recommended_intensity_ceiling=None,
                recovery_state="fresh",
                recent_hard_days_48h=0, upcoming_hard_days_48h=0,
                consecutive_duty_days=0, sleep_opportunity="normal",
                tz_shift_last_48h=0, layover_length_hours=0,
                duty_duration_min_today=0, reasons=[],
            ))

        # Build a real full-week demand via kickoff-shaped inputs.
        window_start, window_end, week_starts, effective_start = \
            _kickoff_shape_args(monday, weeks=1)
        demand = build_demand(
            client_id="joel_full_test",
            client_profile={
                "primary_goal": "fat_loss",
                "training_days_per_week": 5,
                "preferred_training_days": ["mon", "tue", "wed", "thu", "fri"],
                "training_experience": "intermediate",
                "variety_preference": "high",
                "cardio_preference": "elliptical",
                "dislikes_running": True,
            },
            goal_key=goal.key,
            phase_spec=phase,
            week_start_dates=week_starts,
            window_start=window_start,
            window_end=window_end,
            effective_start_date=effective_start,
        )

        # Pre-place BOTH aerobic Z2 and mobility on the 3rd usable date
        # (Friday). Greedy pass will place 2 KEY strengths on Mon+Wed, then
        # the 3rd KEY should fail on Friday (cap 60 vs 30+15+45=90) — the
        # bundle rescue must fire, evict cardio+mobility, place the KEY,
        # and re-add mobility (60 - 45 = 15 spare, fits mobility=15).
        friday = monday + _dt.timedelta(days=4)
        existing = [
            Placement(
                exposure_id="pre_cardio_fri", objective_id="obj_c",
                kind="aerobic_z2", date=friday, priority="SUPPORTING",
                exposure_number=1, intensity_class="EASY",
                target_duration_min=30, intensity_target="z2", key=False,
            ),
            Placement(
                exposure_id="pre_mob_fri", objective_id="obj_m",
                kind="mobility", date=friday, priority="SUPPORTING",
                exposure_number=1, intensity_class="EASY",
                target_duration_min=15, intensity_target="flow", key=False,
            ),
        ]

        result = schedule_demand(
            demand=demand, day_contexts=ctxs,
            goal=goal, phase=phase,
            preferred_weekdays={0, 1, 2, 3, 4},
            existing_placements=existing,
        )

        strength = [p for p in result.placements
                    if p.kind == "strength_full_body"]
        self.assertEqual(
            len(strength), 3,
            f"Full week must place 3 strength_full_body sessions after "
            f"bundle rescue. Got {len(strength)}. "
            f"Placements: {[(p.kind, p.date, p.priority) for p in result.placements]}. "
            f"Unfilled: {[(u.kind, u.priority, u.reason_code) for u in result.unfilled]}"
        )
        # And one of the strengths should be on Friday (the reclaimed date).
        self.assertTrue(
            any(p.date == friday for p in strength),
            "Bundle rescue should have placed a strength on Friday"
        )
        # Mobility should have been re-added.
        self.assertTrue(
            any(p.exposure_id == "pre_mob_fri" for p in result.placements),
            "Mobility should have been re-added post-rescue"
        )
        # Aerobic Z2 dropped to unfilled.
        self.assertTrue(
            any(u.exposure_id == "pre_cardio_fri" for u in result.unfilled),
            "Aerobic Z2 should have been evicted and left unfilled"
        )


if __name__ == "__main__":
    unittest.main()
