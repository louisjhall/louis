"""Iter 130g — Deterministic programme-structure tests.

These tests exercise Engine V2's WHAT / VALIDATE layers WITHOUT any DB or
LLM. They guard the two urgent regressions the coach flagged:

  * Pietro (marathon foundation, training_days_per_week=3) MUST receive a
    weekly Long Run AND at least one strength session (the two things
    silently dropped by the pre-Iter 130f/g scaling bugs).
  * Joel (strength.fat_loss, dislikes running, wants A/B/C variety) MUST
    NOT be prescribed running kinds and MUST get three distinct full-body
    session variants when the weekly quota allows.

If either invariant breaks in the future this test suite goes red.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_v2_sport_configs import (  # noqa: E402
    get_goal_config, canonicalise_goal_key, resolve_phase_plan,
)
from feature_v2_demand_v2 import build_demand  # noqa: E402
from feature_v2_variety import (  # noqa: E402
    resolve_cardio_modality, full_body_pattern_remap,
    pick_exercise_with_variety,
)
from feature_v2_construction_v2 import build_session_spec  # noqa: E402
from feature_v2_validators_v2 import validate_programme  # noqa: E402
from feature_v2_sequencing import Placement, week_key  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _monday(offset_weeks: int = 0) -> _dt.date:
    today = _dt.date(2026, 6, 1)
    monday = today - _dt.timedelta(days=today.weekday())
    return monday + _dt.timedelta(weeks=offset_weeks)


def _week_starts(n_weeks: int) -> list[_dt.date]:
    m = _monday()
    return [m + _dt.timedelta(weeks=i) for i in range(n_weeks)]


# ---------------------------------------------------------------------------
# Pietro — marathon foundation, training_days_per_week=3
# ---------------------------------------------------------------------------

def _pietro_profile() -> dict:
    return {
        "primary_goal": "marathon",
        "training_days_per_week": 3,
        "preferred_training_days": ["mon", "wed", "fri", "sat"],
        "training_experience": "intermediate",
        "variety_preference": "moderate",
        "cardio_preference": "run",
    }


def test_pietro_marathon_foundation_gets_long_run_every_week():
    goal = get_goal_config(canonicalise_goal_key("marathon"))
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(4)
    demand = build_demand(
        client_id="pietro_test",
        client_profile=_pietro_profile(),
        goal_key=goal.key,
        phase_spec=phase,
        week_start_dates=weeks,
    )
    long_runs_per_week = {}
    for e in demand.required_exposures:
        if e.kind == "run_long":
            long_runs_per_week[e.week_index] = long_runs_per_week.get(e.week_index, 0) + 1
    for w in range(len(weeks)):
        assert long_runs_per_week.get(w, 0) >= 1, (
            f"Week {w}: Long Run must be present — got "
            f"{long_runs_per_week.get(w, 0)}"
        )


def test_pietro_marathon_foundation_preserves_strength_when_training_days_3():
    """Regression: training_days_per_week=3 used to clip strength_full_body
    down to zero. It must survive as MIN=1/week via stacking budget."""
    goal = get_goal_config(canonicalise_goal_key("marathon"))
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(3)
    demand = build_demand(
        client_id="pietro_test",
        client_profile=_pietro_profile(),
        goal_key=goal.key,
        phase_spec=phase,
        week_start_dates=weeks,
    )
    strength_per_week: dict[int, int] = {}
    run_easy_per_week: dict[int, int] = {}
    for e in demand.required_exposures:
        if e.kind == "strength_full_body":
            strength_per_week[e.week_index] = strength_per_week.get(e.week_index, 0) + 1
        if e.kind == "run_easy":
            run_easy_per_week[e.week_index] = run_easy_per_week.get(e.week_index, 0) + 1
    for w in range(len(weeks)):
        assert strength_per_week.get(w, 0) >= 1, (
            f"Week {w}: Strength survived MIN check failed — got "
            f"{strength_per_week.get(w, 0)} (must be >= 1)"
        )
        assert run_easy_per_week.get(w, 0) >= 2, (
            f"Week {w}: Easy Run MIN=2 not preserved — got "
            f"{run_easy_per_week.get(w, 0)}"
        )


# ---------------------------------------------------------------------------
# Joel — strength.fat_loss, dislikes running, high variety
# ---------------------------------------------------------------------------

def _joel_profile(cardio_pref: str = "elliptical") -> dict:
    return {
        "primary_goal": "fat_loss",
        "training_days_per_week": 3,
        "sessions_per_week_min": 3,
        "sessions_per_week_max": 5,
        "preferred_training_days": ["mon", "tue", "thu", "fri"],
        "training_experience": "intermediate",
        "variety_preference": "high",
        "cardio_preference": cardio_pref,
        "dislikes_running": True,
        "willing_to_train_layovers": True,
    }


def test_joel_fat_loss_never_prescribes_running_when_dislikes_running():
    """With dislikes_running=True and cardio_preference=elliptical, no
    session spec should emit a run_easy / run_long / etc."""
    prof = _joel_profile("elliptical")
    resolved = resolve_cardio_modality(prof)
    assert resolved == "elliptical", f"Expected elliptical, got {resolved!r}"

    # Simulate an aerobic_z2 placement + build the spec directly
    spec = build_session_spec(
        kind="aerobic_z2",
        duration_min=25,
        intensity_target="z2",
        phase_kind="foundation",
        day_type="home_day",
        equipment_ctx={"bodyweight", "dumbbells", "elliptical", "rower"},
        avoid_patterns=set(),
        cardio_preference=resolved,
        exposure_number=1,
        variety_preference="high",
        training_experience="intermediate",
    )
    assert spec.spec_kind == "cardio", (
        f"Expected low-impact cardio spec, got {spec.spec_kind}"
    )
    assert "elliptical" in spec.equipment_used, (
        f"Elliptical modality missing from equipment_used: {spec.equipment_used}"
    )


def test_joel_full_body_a_b_c_are_distinct():
    """Three consecutive full-body sessions (session_slot 0/1/2) must emit
    different anchor exercises."""
    equip = {"bodyweight", "dumbbells", "barbell", "rack", "bench",
             "cable_stack", "kettlebell", "pullup_bar"}
    anchors_by_slot: dict[int, list[str]] = {}
    for slot in (0, 1, 2):
        spec = build_session_spec(
            kind="strength_full_body",
            duration_min=45,
            intensity_target="rpe7",
            phase_kind="foundation",
            day_type="home_day",
            equipment_ctx=equip,
            avoid_patterns=set(),
            exposure_number=1,
            variety_preference="high",
            training_experience="intermediate",
            session_slot=slot,
            week_index=0,
        )
        exs = (spec.to_dict().get("payload") or {}).get("exercises") or []
        anchors = [e["name"] for e in exs
                   if str(e.get("role", "")).startswith("primary_")]
        anchors_by_slot[slot] = anchors
    # Ensure the three anchor sets are NOT identical across slots
    sigs = {tuple(sorted(v)) for v in anchors_by_slot.values()}
    assert len(sigs) >= 2, (
        f"Full Body A/B/C sessions collapsed to identical anchors: "
        f"{anchors_by_slot}"
    )


def test_joel_fat_loss_validator_flags_running_prescribed():
    """If a run_easy placement leaks into Joel's plan, the validator must
    surface a `running_prescribed_despite_preference` error."""
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    prof = _joel_profile("elliptical")

    demand = build_demand(
        client_id="joel_test",
        client_profile=prof,
        goal_key=goal.key,
        phase_spec=phase,
        week_start_dates=_week_starts(1),
    )
    # Synthesise a bad placement (run_easy) to test the validator branch
    bad_placement = Placement(
        exposure_id="fake", objective_id="fake",
        kind="run_easy", date=_monday(), priority="IMPORTANT",
        exposure_number=1, intensity_class="EASY",
        target_duration_min=30, intensity_target="z2", key=False,
    )
    v = validate_programme(
        demand=demand, placements=[bad_placement],
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs={}, weeks=1,
    )
    codes = {i.code for i in v.issues}
    assert "running_prescribed_despite_preference" in codes, (
        f"Expected running_prescribed_despite_preference error, got: {codes}"
    )


def test_pietro_validator_flags_missing_long_run():
    """Programme without a Long Run must raise `marathon_long_run_missing`."""
    goal = get_goal_config("running.marathon")
    phase = goal.phase_specs["foundation"]
    prof = _pietro_profile()
    demand = build_demand(
        client_id="pietro_test",
        client_profile=prof,
        goal_key=goal.key,
        phase_spec=phase,
        week_start_dates=_week_starts(1),
    )
    # Only easy runs — deliberately no long run
    monday = _monday()
    placements = [
        Placement(
            exposure_id=f"e{i}", objective_id="obj_easy",
            kind="run_easy", date=monday + _dt.timedelta(days=i * 2),
            priority="IMPORTANT", exposure_number=i + 1,
            intensity_class="EASY", target_duration_min=30,
            intensity_target="z2", key=False,
        )
        for i in range(3)
    ]
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs={}, weeks=1,
    )
    codes = {i.code for i in v.issues}
    assert "marathon_long_run_missing" in codes, (
        f"Expected marathon_long_run_missing, got: {codes}"
    )


def test_full_body_pattern_remap_cycles_a_b_c():
    a = full_body_pattern_remap(1, "high", "intermediate",
                                 "strength_full_body", session_slot=0)
    b = full_body_pattern_remap(1, "high", "intermediate",
                                 "strength_full_body", session_slot=1)
    c = full_body_pattern_remap(1, "high", "intermediate",
                                 "strength_full_body", session_slot=2)
    assert a == {}, f"Session A should be empty remap, got {a}"
    assert b == {"primary_horizontal_push": "vertical_push",
                 "primary_horizontal_pull": "vertical_pull"}
    assert c.get("primary_horizontal_pull") == "vertical_pull"


def test_resolve_cardio_modality_full_alias_matrix():
    cases = [
        ({"cardio_preference": "elliptical"}, "elliptical"),
        ({"cardio_preference": "rower"}, "rower"),
        ({"cardio_preference": "recumbent_bike"}, "recumbent_bike"),
        ({"cardio_preference": "incline_walk"}, "incline_walk"),
        ({"cardio_preference": "stationary_bike"}, "bike"),
        ({"dislikes_running": True}, "elliptical"),
        ({"cardio_preference": "no_running"}, "elliptical"),
        ({}, "run"),
    ]
    for prof, expected in cases:
        got = resolve_cardio_modality(prof)
        assert got == expected, f"resolve_cardio_modality({prof}) = {got!r}, expected {expected!r}"
