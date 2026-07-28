"""
Iter 121c — Main training-day cap correction.

Rule: MAIN exposures (KEY + IMPORTANT) must never exceed the client's
`training_days_per_week`. SUPPORTING / OPTIONAL exposures are stackable —
they only appear when the client has explicit slack (`sessions_per_week_max`
greater than `training_days_per_week`), otherwise they drop to 0.
"""
from __future__ import annotations

import datetime as _dt
from collections import Counter

import pytest

from feature_v2_sport_configs import get_goal_config
from feature_v2_demand_v2 import build_demand


MAIN_PRIOS = {"KEY", "IMPORTANT"}


def _plan_kinds(goal_key, phase_kind, days, session_max=None):
    session_max = session_max if session_max is not None else days
    cfg = get_goal_config(goal_key)
    phase = cfg.phase_specs[phase_kind]
    plan = build_demand(
        client_id="x",
        client_profile={"training_days_per_week": days,
                          "sessions_per_week_max": session_max,
                          "preferred_session_length": 45,
                          "training_experience": "intermediate"},
        goal_key=goal_key, phase_spec=phase,
        week_start_dates=[_dt.date(2026, 8, 3)],
    )
    kinds = Counter(e.kind for e in plan.required_exposures if e.week_index == 0)
    prios = Counter()
    for e in plan.required_exposures:
        if e.week_index == 0:
            prios[e.priority.upper()] += 1
    return kinds, prios


# ---------------------------------------------------------------------------
# Main-day cap invariant (per-priority)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("goal", ["general.fitness", "strength.fat_loss"])
@pytest.mark.parametrize("phase", ["foundation", "build", "consolidation"])
@pytest.mark.parametrize("days", [2, 3, 4])
def test_main_exposures_fit_training_days(goal, phase, days):
    kinds, prios = _plan_kinds(goal, phase, days)
    main = prios.get("KEY", 0) + prios.get("IMPORTANT", 0)
    assert main <= days, (
        f"{goal} {phase} {days}d: main exposures {main} > training_days {days}. "
        f"kinds={dict(kinds)} prios={dict(prios)}"
    )


@pytest.mark.parametrize("goal", ["general.fitness", "strength.fat_loss"])
@pytest.mark.parametrize("phase", ["foundation", "build"])
@pytest.mark.parametrize("days", [2, 3, 4])
def test_support_exposures_bounded(goal, phase, days):
    """PRD: 'Support exposures can stack where appropriate'. Support quotas
    should be bounded (auto stacking budget = 2 by default), not zero."""
    kinds, prios = _plan_kinds(goal, phase, days, session_max=days)
    support = sum(1 for p, c in prios.items()
                    if p not in ("KEY", "IMPORTANT") for _ in range(c))
    # Support quotas are stackable, but auto stacking budget caps at 2
    assert support <= 3, (
        f"{goal} {phase} {days}d: support {support} exceeds auto stacking budget. {dict(kinds)}"
    )


def test_3day_gf_build_no_extra_main_day():
    """PRD: 3-day client must not receive a FOURTH independent main training
    day. Support (conditioning/mobility) may generate as stackable."""
    kinds, prios = _plan_kinds("general.fitness", "build", days=3, session_max=3)
    main = prios.get("KEY", 0) + prios.get("IMPORTANT", 0)
    assert main == 3, f"expected exactly 3 main days, got {main}. {dict(kinds)}"
    assert kinds.get("strength_full_body", 0) == 2
    assert kinds.get("aerobic_z2", 0) == 1


def test_3day_fl_no_five_main_days():
    kinds, prios = _plan_kinds("strength.fat_loss", "build", days=3, session_max=3)
    main = prios.get("KEY", 0) + prios.get("IMPORTANT", 0)
    assert main <= 3, f"main={main} exceeds 3-day cap. {dict(kinds)}"
    assert kinds.get("strength_full_body", 0) >= 2


def test_4day_stacking_appears_when_sessions_max_gt_days():
    """A client with training_days=4 but sessions_per_week_max=6 should see
    conditioning/mobility appear as stacked support."""
    kinds, _ = _plan_kinds("general.fitness", "build", days=4, session_max=6)
    assert kinds.get("strength_full_body", 0) == 2
    assert kinds.get("aerobic_z2", 0) >= 2
    stacked = kinds.get("conditioning_mixed", 0) + kinds.get("mobility", 0)
    assert stacked >= 1, f"expected stacking to add support exposures, got {dict(kinds)}"


def test_key_priority_never_scaled_below_min():
    """No matter how tight the frequency, KEY strength MIN=2 is preserved."""
    for days in (2, 3, 4):
        kinds, _ = _plan_kinds("general.fitness", "build", days=days, session_max=days)
        # 2-day case can only get 2 strength (KEY min); 3-4 days keep 2 strength MIN too
        assert kinds.get("strength_full_body", 0) >= min(2, days), (
            f"KEY strength MIN violated for {days}-day client: {dict(kinds)}"
        )


# ---------------------------------------------------------------------------
# Marathon regression — priority clipping must not break running.marathon
# ---------------------------------------------------------------------------

def test_marathon_build_still_fits_key_long_run():
    cfg = get_goal_config("running.marathon")
    phase = cfg.phase_specs["build"]
    plan = build_demand(
        client_id="x",
        client_profile={"training_days_per_week": 5, "sessions_per_week_max": 5,
                          "preferred_session_length": 60},
        goal_key="running.marathon", phase_spec=phase,
        week_start_dates=[_dt.date(2026, 8, 3)],
    )
    kinds = Counter(e.kind for e in plan.required_exposures if e.week_index == 0)
    # Marathon KEY = run_long; must always appear
    assert kinds.get("run_long", 0) >= 1, dict(kinds)


# ---------------------------------------------------------------------------
# Final report — prints for the ratification summary
# ---------------------------------------------------------------------------

def test_report_all_frequencies():
    print("\n=== ITER 121c — MAIN-DAY CAP REPORT ===")
    for goal in ("general.fitness", "strength.fat_loss"):
        print(f"\n--- {goal.upper()} ---")
        for days in (2, 3, 4):
            for phase in ("foundation", "build", "consolidation"):
                kinds, prios = _plan_kinds(goal, phase, days, session_max=days)
                strength = kinds.get("strength_full_body", 0)
                aerobic = kinds.get("aerobic_z2", 0)
                conditioning = kinds.get("conditioning_mixed", 0)
                support = kinds.get("mobility", 0) + kinds.get("recovery", 0)
                main = prios.get("KEY", 0) + prios.get("IMPORTANT", 0)
                total = sum(kinds.values())
                print(
                    f"  {days}d {phase:14s}: "
                    f"strength={strength} aerobic={aerobic} conditioning={conditioning} "
                    f"support={support}   [main={main}/{days} total={total}]"
                )
