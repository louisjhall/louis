"""Regression test for the strength.muscle_gain weekly-strength-cap bug.

Bug: the hypertrophy/intensification phases of strength.muscle_gain declare
a combined strength quota target of 5 sessions/week (strength_upper 2 +
strength_lower 2 + strength_hypertrophy 1 for hypertrophy; strength_upper 2 +
strength_lower 2 + strength_power 1 for intensification), but
`PhaseSpec.strength_days_per_week_max` was never overridden for either phase,
so it silently inherited the class default of 2 — capping placement at 2
strength days/week regardless of what demand required. The 3rd+ strength
exposure could never be placed (KEY-vs-KEY rescue is not possible), and the
programme legitimately landed in `needs_review` every time. This was
self-documented in feature_v2_engine_v2_publish.GOAL_CONFIG_STATUS before the
fix.

Fix: strength_days_per_week_max=5 was added to both phases. This test proves
that with the fix, a client with ample weekly capacity gets all 5 required
strength sessions actually scheduled, and validate_programme raises neither
`weekly_strength_cap_exceeded` nor a strength `quota_deficit`.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_v2_sport_configs import get_goal_config, is_strength_session  # noqa: E402
from feature_v2_demand_v2 import build_demand, schedule_demand  # noqa: E402
from feature_v2_roster_context import DayContext  # noqa: E402
from feature_v2_validators_v2 import validate_programme  # noqa: E402
from feature_v2_sequencing import week_key  # noqa: E402


def _monday() -> _dt.date:
    d = _dt.date(2026, 6, 1)
    return d - _dt.timedelta(days=d.weekday())


def _generous_week_ctx(monday: _dt.date) -> list[DayContext]:
    """Seven wide-open days — no roster constraint should be the reason a
    strength session fails to place; only the weekly cap should matter."""
    out = []
    for i in range(7):
        out.append(DayContext(
            date=monday + _dt.timedelta(days=i),
            day_type="home_day",
            duty_burden_score=0,
            training_opportunity=90,
            available_time_min=90,
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


def _lifter_profile() -> dict:
    return {
        "primary_goal": "muscle_gain",
        "training_days_per_week": 6,
        "sessions_per_week_min": 5,
        "sessions_per_week_max": 9,
        "preferred_training_days": ["mon", "tue", "wed", "thu", "fri", "sat"],
        "training_experience": "intermediate",
        "variety_preference": "high",
    }


def _schedule_phase(phase_kind: str):
    goal = get_goal_config("strength.muscle_gain")
    phase = goal.phase_specs[phase_kind]
    monday = _monday()
    demand = build_demand(
        client_id="lifter_test", client_profile=_lifter_profile(),
        goal_key=goal.key, phase_spec=phase, week_start_dates=[monday],
    )
    ctxs = _generous_week_ctx(monday)
    result = schedule_demand(
        demand=demand, day_contexts=ctxs,
        goal=goal, phase=phase,
        preferred_weekdays={0, 1, 2, 3, 4, 5, 6},
    )
    validation = validate_programme(
        demand=demand, placements=result.placements, phase=phase, goal=goal,
        unfilled=result.unfilled, client_profile=_lifter_profile(), weeks=1,
    )
    return goal, phase, demand, result, validation


def test_hypertrophy_phase_caps_allow_the_declared_five_per_week_quota():
    """Guard against the cap silently regressing back below the quota."""
    goal = get_goal_config("strength.muscle_gain")
    hyp = goal.phase_specs["hypertrophy"]
    inten = goal.phase_specs["intensification"]
    assert hyp.strength_days_per_week_max >= 5, (
        f"hypertrophy strength_days_per_week_max={hyp.strength_days_per_week_max} "
        f"is below the declared 5/wk quota (strength_upper 2 + strength_lower 2 "
        f"+ strength_hypertrophy 1)"
    )
    assert inten.strength_days_per_week_max >= 5, (
        f"intensification strength_days_per_week_max={inten.strength_days_per_week_max} "
        f"is below the declared 5/wk quota (strength_upper 2 + strength_lower 2 "
        f"+ strength_power 1)"
    )


def test_hypertrophy_phase_schedules_all_required_strength_sessions():
    goal, phase, demand, result, validation = _schedule_phase("hypertrophy")

    required_strength = sum(
        1 for e in demand.required_exposures if is_strength_session(e.kind)
    )
    placed_strength = [p for p in result.placements if is_strength_session(p.kind)]

    assert required_strength == 5, (
        f"Expected hypertrophy demand to require 5 strength exposures/wk, "
        f"got {required_strength}: {[e.kind for e in demand.required_exposures]}"
    )
    assert len(placed_strength) == 5, (
        f"Expected all 5 strength sessions to be placed, got "
        f"{len(placed_strength)}. Placed: {[(p.kind, p.date) for p in placed_strength]}. "
        f"Unfilled: {[(u.kind, u.priority, u.reason_code) for u in result.unfilled]}"
    )

    strength_cap_issues = [
        i for i in validation.issues if i.code == "weekly_strength_cap_exceeded"
    ]
    assert not strength_cap_issues, (
        f"Did not expect weekly_strength_cap_exceeded, got {strength_cap_issues}"
    )
    quota_deficit_strength = [
        i for i in validation.issues
        if i.code == "quota_deficit" and any(
            k in i.message for k in ("strength_upper", "strength_lower", "strength_hypertrophy")
        )
    ]
    assert not quota_deficit_strength, (
        f"Did not expect a strength quota_deficit, got {quota_deficit_strength}"
    )


def test_intensification_phase_schedules_all_required_strength_sessions():
    goal, phase, demand, result, validation = _schedule_phase("intensification")

    required_strength = sum(
        1 for e in demand.required_exposures if is_strength_session(e.kind)
    )
    placed_strength = [p for p in result.placements if is_strength_session(p.kind)]

    assert required_strength == 5, (
        f"Expected intensification demand to require 5 strength exposures/wk, "
        f"got {required_strength}: {[e.kind for e in demand.required_exposures]}"
    )
    assert len(placed_strength) == 5, (
        f"Expected all 5 strength sessions to be placed, got "
        f"{len(placed_strength)}. Placed: {[(p.kind, p.date) for p in placed_strength]}. "
        f"Unfilled: {[(u.kind, u.priority, u.reason_code) for u in result.unfilled]}"
    )

    strength_cap_issues = [
        i for i in validation.issues if i.code == "weekly_strength_cap_exceeded"
    ]
    assert not strength_cap_issues, (
        f"Did not expect weekly_strength_cap_exceeded, got {strength_cap_issues}"
    )


if __name__ == "__main__":
    test_hypertrophy_phase_caps_allow_the_declared_five_per_week_quota()
    test_hypertrophy_phase_schedules_all_required_strength_sessions()
    test_intensification_phase_schedules_all_required_strength_sessions()
    print("OK")
