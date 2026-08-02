"""Iter 131c — stacked-date bundle rescue + partial-week quotas.

Adds two behaviours to the V2 scheduler:

1. **Bundle rescue** — when a compulsory (KEY or IMPORTANT non-skippable)
   exposure has no valid slot but a date in the same week is occupied only
   by lower-priority (SUPPORTING/OPTIONAL) placements, the rescue evicts
   the WHOLE bundle atomically, retries the compulsory, and if the
   compulsory validates, re-adds only Mobility from the evicted bundle if
   it still fits within the daily cap. Non-mobility items become unfilled.
   Never evicts another compulsory. Restores the whole bundle exactly if
   the compulsory still fails.

2. **Partial-week quotas** — `build_demand` accepts `window_start` /
   `window_end` bounds and treats any week with fewer than 5 in-window
   days as a "partial week". Partial weeks do NOT emit compulsory
   exposures (no KEY, no IMPORTANT non-skippable), so a 1-2 day opening
   or closing week cannot generate unfillable blockers.
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
    build_demand, schedule_demand, RequiredExposure, DemandPlan,
)
from feature_v2_roster_context import DayContext  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _monday() -> _dt.date:
    d = _dt.date(2026, 6, 1)
    return d - _dt.timedelta(days=d.weekday())


def _sole_ctx_list(monday: _dt.date, *,
                    opportunity_by_day: dict[int, int],
                    cap_by_day: dict[int, int],
                    day_type: str = "home_day") -> list[DayContext]:
    out = []
    for i in range(7):
        d = monday + _dt.timedelta(days=i)
        out.append(DayContext(
            date=d, day_type=day_type,
            duty_burden_score=0,
            training_opportunity=opportunity_by_day.get(i, 30),
            available_time_min=cap_by_day.get(i, 45),
            recommended_intensity_ceiling=None,
            recovery_state="fresh",
            recent_hard_days_48h=0, upcoming_hard_days_48h=0,
            consecutive_duty_days=0, sleep_opportunity="normal",
            tz_shift_last_48h=0, layover_length_hours=0,
            duty_duration_min_today=0, reasons=[],
        ))
    return out


def _mk_exposure(*, exposure_id: str, kind: str, priority: str,
                  can_skip: bool, week_start: _dt.date,
                  duration: int = 45, ordinal: int = 1) -> RequiredExposure:
    week_end = week_start + _dt.timedelta(days=6)
    return RequiredExposure(
        exposure_id=exposure_id,
        objective_id=f"obj_{kind}",
        kind=kind, priority=priority,
        target_duration_min=duration,
        duration_min_min=max(15, duration - 15),
        duration_max_min=duration + 15,
        intensity_target="rpe6-7" if kind.startswith("strength") else "z2",
        week_index=0, ordinal_within_week=ordinal,
        can_skip_if_missed=can_skip,
        quota_source="test.iter131c",
        target_week_start=week_start, target_week_end=week_end,
        allowed_window_start=week_start, allowed_window_end=week_end,
    )


def _fat_loss_foundation():
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    return goal, phase


# ---------------------------------------------------------------------------
# Fix 1 — bundle rescue on stacked lower-priority dates
# ---------------------------------------------------------------------------

class TestBundleRescue(unittest.TestCase):

    def test_clears_stacked_supporting_bundle_and_re_adds_mobility(self):
        """A required KEY strength has no valid slot; the only usable date
        has BOTH an Aerobic Z2 (SUPPORTING) and a Mobility (SUPPORTING)
        stacked on it. Rescue must evict the whole bundle, place the KEY,
        and re-add the Mobility (which is compatible and short)."""
        goal, phase = _fat_loss_foundation()
        monday = _monday()
        # Only Wed clears KEY floor. Wed cap 90m so KEY + mobility both fit
        # once cardio is evicted. But strength (45m) + cardio (30m) + mobility
        # (15m) = 90m — right at the cap. In practice this is tight; the
        # test asserts KEY places and mobility re-adds.
        ctxs = _sole_ctx_list(
            monday,
            opportunity_by_day={2: 90},
            cap_by_day={2: 90},
        )

        key_exp = _mk_exposure(
            exposure_id="key_strength_1",
            kind="strength_full_body",
            priority="KEY",
            can_skip=False,
            week_start=monday,
            duration=45,
        )
        demand = DemandPlan(
            required_exposures=[key_exp],
            frequency_caps={"client_training_days_per_week_max": 7},
        )

        # Preplace BOTH aerobic Z2 and mobility on Wed. Total = 30+15 = 45m
        # — so a 45m KEY would exceed 45+45=90 IF nothing evicted, but we
        # force the pathology by making the daily cap tight enough that KEY
        # cannot stack. Use cap=60 so mobility(15) + KEY(45) = 60 fits, but
        # cardio(30) + mobility(15) + KEY(45) = 90 exceeds 60.
        ctxs[2] = DayContext(
            date=monday + _dt.timedelta(days=2),
            day_type="home_day",
            duty_burden_score=0, training_opportunity=90,
            available_time_min=60,
            recommended_intensity_ceiling=None, recovery_state="fresh",
            recent_hard_days_48h=0, upcoming_hard_days_48h=0,
            consecutive_duty_days=0, sleep_opportunity="normal",
            tz_shift_last_48h=0, layover_length_hours=0,
            duty_duration_min_today=0, reasons=[],
        )
        existing = [
            Placement(
                exposure_id="preplaced_cardio",
                objective_id="obj_cardio",
                kind="aerobic_z2",
                date=monday + _dt.timedelta(days=2),
                priority="SUPPORTING", exposure_number=1,
                intensity_class="EASY",
                target_duration_min=30,
                intensity_target="z2", key=False,
            ),
            Placement(
                exposure_id="preplaced_mob",
                objective_id="obj_mob",
                kind="mobility",
                date=monday + _dt.timedelta(days=2),
                priority="SUPPORTING", exposure_number=1,
                intensity_class="EASY",
                target_duration_min=15,
                intensity_target="flow", key=False,
            ),
        ]
        result = schedule_demand(
            demand=demand, day_contexts=ctxs,
            goal=goal, phase=phase,
            preferred_weekdays={0, 1, 2, 3, 4},
            existing_placements=existing,
        )

        wed = monday + _dt.timedelta(days=2)
        strength = [p for p in result.placements if p.kind == "strength_full_body"]
        self.assertEqual(len(strength), 1, "KEY strength should have been placed")
        self.assertEqual(strength[0].date, wed, "KEY should have taken the Wed slot")

        # Mobility should have been re-added if it fits: 45 (strength) + 15
        # (mobility) = 60 which fits under 60. Aerobic Z2 (30) would push
        # total to 90 > 60, so should have been evicted and left unfilled.
        mob_readded = [p for p in result.placements
                       if p.exposure_id == "preplaced_mob"]
        cardio_dropped = [u for u in result.unfilled
                          if u.exposure_id == "preplaced_cardio"]
        self.assertEqual(len(mob_readded), 1,
                          "Compatible mobility should have been re-added")
        self.assertEqual(len(cardio_dropped), 1,
                          "Aerobic Z2 should have been left unfilled after eviction")
        self.assertEqual(cardio_dropped[0].reason_code,
                          "displaced_by_compulsory_rescue")

    def test_restores_full_bundle_when_compulsory_still_fails(self):
        """If the compulsory cannot validate on the cleared date (e.g. still
        below opportunity floor), the ENTIRE bundle is restored exactly."""
        goal, phase = _fat_loss_foundation()
        monday = _monday()
        # Every day has opportunity 20 — KEY floor 55, so KEY cannot validate.
        ctxs = _sole_ctx_list(
            monday,
            opportunity_by_day={},
            cap_by_day={},
        )
        key_exp = _mk_exposure(
            exposure_id="key_strength_x",
            kind="strength_full_body",
            priority="KEY",
            can_skip=False,
            week_start=monday,
            duration=45,
        )
        demand = DemandPlan(
            required_exposures=[key_exp],
            frequency_caps={"client_training_days_per_week_max": 7},
        )
        existing = [
            Placement(
                exposure_id="preplaced_cardio",
                objective_id="obj_cardio",
                kind="aerobic_z2",
                date=monday + _dt.timedelta(days=2),
                priority="SUPPORTING", exposure_number=1,
                intensity_class="EASY",
                target_duration_min=30,
                intensity_target="z2", key=False,
            ),
            Placement(
                exposure_id="preplaced_mob",
                objective_id="obj_mob",
                kind="mobility",
                date=monday + _dt.timedelta(days=2),
                priority="SUPPORTING", exposure_number=1,
                intensity_class="EASY",
                target_duration_min=15,
                intensity_target="flow", key=False,
            ),
        ]
        result = schedule_demand(
            demand=demand, day_contexts=ctxs,
            goal=goal, phase=phase,
            preferred_weekdays={0, 1, 2, 3, 4},
            existing_placements=existing,
        )
        # Both original placements must survive intact.
        preserved_cardio = [p for p in result.placements
                            if p.exposure_id == "preplaced_cardio"]
        preserved_mob = [p for p in result.placements
                         if p.exposure_id == "preplaced_mob"]
        self.assertEqual(len(preserved_cardio), 1,
                          "Aerobic Z2 should be restored exactly")
        self.assertEqual(len(preserved_mob), 1,
                          "Mobility should be restored exactly")
        # KEY still unfilled.
        self.assertTrue(
            any(u.exposure_id == "key_strength_x" for u in result.unfilled),
            "KEY should remain unfilled if it still cannot validate"
        )

    def test_bundle_rescue_never_evicts_a_compulsory_on_shared_date(self):
        """A compulsory KEY strength is preplaced on Wed alongside a mobility.
        A new IMPORTANT non-skippable exposure cannot find any other slot.
        The rescue MUST NOT evict Wed (because Wed has a compulsory)."""
        goal, phase = _fat_loss_foundation()
        monday = _monday()
        ctxs = _sole_ctx_list(
            monday,
            opportunity_by_day={2: 90},
            cap_by_day={2: 90},
        )
        wed = monday + _dt.timedelta(days=2)
        existing = [
            Placement(
                exposure_id="preplaced_key",
                objective_id="obj_key",
                kind="strength_full_body",
                date=wed, priority="KEY", exposure_number=1,
                intensity_class="HARD", target_duration_min=45,
                intensity_target="rpe6-7", key=True,
            ),
            Placement(
                exposure_id="preplaced_mob",
                objective_id="obj_mob",
                kind="mobility",
                date=wed, priority="SUPPORTING", exposure_number=1,
                intensity_class="EASY", target_duration_min=15,
                intensity_target="flow", key=False,
            ),
        ]
        imp_exp = _mk_exposure(
            exposure_id="imp_strength_x",
            kind="strength_full_body",
            priority="IMPORTANT",
            can_skip=False,
            week_start=monday,
            duration=45,
        )
        demand = DemandPlan(
            required_exposures=[imp_exp],
            frequency_caps={"client_training_days_per_week_max": 7},
        )
        result = schedule_demand(
            demand=demand, day_contexts=ctxs,
            goal=goal, phase=phase,
            preferred_weekdays={0, 1, 2, 3, 4},
            existing_placements=existing,
        )
        # KEY must still be present (never evicted).
        self.assertEqual(
            len([p for p in result.placements
                 if p.exposure_id == "preplaced_key"]),
            1, "Rescue must NEVER evict a compulsory placement (even on a shared date)"
        )
        # Mobility on Wed must NOT be evicted either (Wed is a
        # compulsory-shared date → bundle-rescue skips it entirely).
        self.assertEqual(
            len([p for p in result.placements
                 if p.exposure_id == "preplaced_mob"]),
            1, "Mobility on a compulsory-shared date must not be evicted"
        )


# ---------------------------------------------------------------------------
# Fix 2 — partial-week quotas
# ---------------------------------------------------------------------------

class TestPartialWeekQuotas(unittest.TestCase):

    def test_saturday_start_does_not_require_full_weekly_quota(self):
        """A programme window that starts on Saturday and ends on Sunday
        (2 days) must NOT generate any compulsory KEY or IMPORTANT
        non-skippable exposures for that week."""
        # Fat-loss foundation has 3 × KEY strength_full_body per week.
        goal, phase = _fat_loss_foundation()
        # Monday of the partial week (in the past); planning window starts
        # on Saturday.
        monday_partial = _dt.date(2026, 8, 3)  # Mon 3 Aug
        # Actually the earlier example — programme opens Sat 1 Aug 2026.
        # Sat 1 Aug is week starting Mon 27 Jul 2026.
        monday_partial = _dt.date(2026, 7, 27)
        window_start = _dt.date(2026, 8, 1)    # Sat 1 Aug
        window_end = _dt.date(2026, 8, 2)      # Sun 2 Aug (2-day partial)

        demand = build_demand(
            client_id="test_partial",
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
            week_start_dates=[monday_partial],
            window_start=window_start,
            window_end=window_end,
        )

        # No compulsory (KEY or IMPORTANT non-skippable) exposures should
        # have been generated for this partial week.
        compulsory = [
            e for e in demand.required_exposures
            if e.priority.upper() == "KEY"
            or (e.priority.upper() == "IMPORTANT" and not e.can_skip_if_missed)
        ]
        self.assertEqual(
            len(compulsory), 0,
            f"Partial week should have NO compulsory exposures. Got: "
            f"{[(e.kind, e.priority, e.can_skip_if_missed) for e in compulsory]}"
        )
        # And there should be a partial_week note in demand.notes.
        partial_notes = [n for n in demand.notes if "partial_week" in n]
        self.assertTrue(
            len(partial_notes) >= 1,
            f"Expected a partial_week note in demand.notes; got {demand.notes}"
        )

    def test_full_week_still_enforces_all_compulsory_requirements(self):
        """A fully-in-window week must still emit all compulsory exposures."""
        goal, phase = _fat_loss_foundation()
        monday = _monday()
        # Window covers the whole week.
        window_start = monday
        window_end = monday + _dt.timedelta(days=6)

        demand = build_demand(
            client_id="test_full",
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
            week_start_dates=[monday],
            window_start=window_start,
            window_end=window_end,
        )
        key_strength = [
            e for e in demand.required_exposures
            if e.kind == "strength_full_body" and e.priority.upper() == "KEY"
        ]
        self.assertGreaterEqual(
            len(key_strength), 3,
            f"Full week fat-loss foundation must emit ≥3 KEY strength "
            f"exposures. Got {len(key_strength)}"
        )
        # No partial_week note.
        partial_notes = [n for n in demand.notes if "partial_week" in n]
        self.assertEqual(len(partial_notes), 0,
                          "Full week must not produce a partial_week note")

    def test_marathon_long_run_still_protected_on_full_weeks(self):
        """A marathon foundation full week must still emit its KEY Long Run."""
        goal = get_goal_config("running.marathon")
        phase = goal.phase_specs["foundation"]
        monday = _monday()
        demand = build_demand(
            client_id="test_pietro",
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
            window_start=monday,
            window_end=monday + _dt.timedelta(days=6),
        )
        long_runs = [e for e in demand.required_exposures if e.kind == "run_long"]
        self.assertGreaterEqual(
            len(long_runs), 1,
            f"Marathon foundation full week must emit ≥1 run_long exposure. "
            f"Got {len(long_runs)}: {[e.priority for e in long_runs]}"
        )
        # And it should be a KEY (non-skippable).
        self.assertEqual(long_runs[0].priority.upper(), "KEY")
        self.assertFalse(long_runs[0].can_skip_if_missed,
                          "Long Run must be non-skippable")


if __name__ == "__main__":
    unittest.main()
