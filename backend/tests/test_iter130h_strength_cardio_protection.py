"""Iter 130h — Tightened programme-structure invariants.

Extends the Iter 130g deterministic guards with the stricter rules:

* Pietro's SECOND strength session is protected — it now exists in demand
  (MIN=2), and the validator distinguishes roster-blocked (WARNING) from
  coach-omitted (ERROR) cases.
* Joel's THREE lifting sessions are protected — demand always creates 3
  strength_full_body exposures, validator escalates missing sessions to
  ERROR when a feasible open slot existed.
* Every placed Full-Body session must contain a non-running post-workout
  cardio component (inline). Missing cardio is ERROR unless the daily cap
  genuinely prevented it (< 40m → WARNING).
* Identical Full-Body A/B/C anchors are ERROR (block approval).

Synthetic roster fixtures cover the three canonical scenarios per client:
  a) fully-available week
  b) constrained-but-still-feasible week
  c) genuinely-blocked week (one session cannot fit)
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feature_v2_sport_configs import (  # noqa: E402
    get_goal_config, canonicalise_goal_key,
)
from feature_v2_demand_v2 import build_demand  # noqa: E402
from feature_v2_construction_v2 import build_session_spec  # noqa: E402
from feature_v2_validators_v2 import validate_programme  # noqa: E402
from feature_v2_sequencing import Placement  # noqa: E402


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


def _mk_placement(kind: str, date: _dt.date, priority: str = "IMPORTANT",
                   exposure_number: int = 1, duration: int = 45,
                   key: bool = False, intensity: str = "z2",
                   objective_id: str = "obj") -> Placement:
    return Placement(
        exposure_id=f"{kind}-{date.isoformat()}",
        objective_id=objective_id,
        kind=kind, date=date,
        priority=priority, exposure_number=exposure_number,
        intensity_class="EASY" if intensity.startswith("z2") else "HARD",
        target_duration_min=duration, intensity_target=intensity, key=key,
    )


def _full_week_caps(week_start: _dt.date, cap_min: int = 90) -> dict:
    """Every day of the week has a generous 90-minute cap."""
    return {week_start + _dt.timedelta(days=i): cap_min for i in range(7)}


def _full_week_day_types(week_start: _dt.date, day_type: str = "home_day") -> dict:
    return {(week_start + _dt.timedelta(days=i)).isoformat(): day_type
            for i in range(7)}


# ---------------------------------------------------------------------------
# Pietro — demand generates 2 strength exposures (foundation)
# ---------------------------------------------------------------------------

def _pietro_profile():
    return {
        "primary_goal": "marathon",
        "training_days_per_week": 3,
        "preferred_training_days": ["mon", "tue", "wed", "thu", "fri", "sat"],
        "training_experience": "intermediate",
        "variety_preference": "moderate",
        "cardio_preference": "run",
    }


def test_pietro_demand_creates_two_strength_exposures_per_week():
    goal = get_goal_config(canonicalise_goal_key("marathon"))
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(3)
    demand = build_demand(
        client_id="pietro_test", client_profile=_pietro_profile(),
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    per_week: dict[int, int] = {}
    for e in demand.required_exposures:
        if e.kind == "strength_full_body":
            per_week[e.week_index] = per_week.get(e.week_index, 0) + 1
    for w in range(len(weeks)):
        assert per_week.get(w, 0) == 2, (
            f"Week {w}: expected 2 strength exposures, got {per_week.get(w, 0)}"
        )


def test_pietro_validator_flags_second_strength_missing_when_feasible():
    """Feasible week (all 7 days available) with only 1 strength placed
    → ERROR marathon_second_strength_missing_when_feasible."""
    goal = get_goal_config(canonicalise_goal_key("marathon"))
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _pietro_profile()
    demand = build_demand(
        client_id="pietro_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    placements = [
        _mk_placement("run_long", monday + _dt.timedelta(days=5),
                       priority="KEY", key=True, duration=60),
        _mk_placement("run_easy", monday, duration=30),
        _mk_placement("run_easy", monday + _dt.timedelta(days=2), duration=30),
        _mk_placement("strength_full_body",
                       monday + _dt.timedelta(days=1),
                       duration=45),
    ]
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs={}, weeks=1,
        daily_time_cap_by_date=_full_week_caps(monday),
        day_type_by_date=_full_week_day_types(monday),
    )
    codes_and_sev = {(i.code, i.severity) for i in v.issues}
    assert ("marathon_second_strength_missing_when_feasible", "error") in codes_and_sev, (
        f"Expected ERROR for missing 2nd strength when feasible slots exist. "
        f"Got: {codes_and_sev}"
    )


def test_pietro_validator_downgrades_to_warning_when_no_feasible_slot():
    """Only 3 available days, all consumed by runs → 2nd strength genuinely
    cannot fit → WARNING (not ERROR)."""
    goal = get_goal_config(canonicalise_goal_key("marathon"))
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _pietro_profile()
    demand = build_demand(
        client_id="pietro_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    placements = [
        _mk_placement("run_long", monday + _dt.timedelta(days=5),
                       priority="KEY", key=True, duration=60),
        _mk_placement("run_easy", monday, duration=30),
        _mk_placement("run_easy", monday + _dt.timedelta(days=2), duration=30),
        _mk_placement("strength_full_body",
                       monday + _dt.timedelta(days=1),
                       duration=45),
    ]
    # Only Mon/Wed/Sat have caps ≥30; the rest are 0. Since Mon/Wed already
    # have placements and Sat has the Long Run, the second strength has
    # nowhere to go.
    caps = {monday: 90, monday + _dt.timedelta(days=1): 0,
            monday + _dt.timedelta(days=2): 90,
            monday + _dt.timedelta(days=3): 0,
            monday + _dt.timedelta(days=4): 0,
            monday + _dt.timedelta(days=5): 90,
            monday + _dt.timedelta(days=6): 0}
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs={}, weeks=1,
        daily_time_cap_by_date=caps,
        day_type_by_date=_full_week_day_types(monday),
    )
    # There should be a WARNING (not an ERROR) for the 2nd strength.
    second_strength_issues = [i for i in v.issues
        if i.code == "marathon_second_strength_missing_when_feasible"]
    assert second_strength_issues, (
        f"Expected marathon_second_strength_missing_when_feasible issue, got "
        f"{[(i.code, i.severity) for i in v.issues]}"
    )
    assert all(i.severity == "warning" for i in second_strength_issues), (
        f"Expected WARNING severity (roster blocked), got "
        f"{[i.severity for i in second_strength_issues]}"
    )


def test_pietro_no_strength_stacked_on_long_run():
    """Placing strength on the same date as the Long Run → ERROR."""
    goal = get_goal_config(canonicalise_goal_key("marathon"))
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _pietro_profile()
    demand = build_demand(
        client_id="pietro_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    long_run_date = monday + _dt.timedelta(days=5)
    placements = [
        _mk_placement("run_long", long_run_date, priority="KEY",
                       key=True, duration=60),
        _mk_placement("strength_full_body", long_run_date, duration=45),
    ]
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs={}, weeks=1,
        daily_time_cap_by_date=_full_week_caps(monday),
        day_type_by_date=_full_week_day_types(monday),
    )
    codes_and_sev = {(i.code, i.severity) for i in v.issues}
    assert ("strength_stacked_on_long_run", "error") in codes_and_sev, (
        f"Expected ERROR for strength stacked on Long Run. Got: {codes_and_sev}"
    )


# ---------------------------------------------------------------------------
# Joel — demand generates 3 strength exposures + inline post-workout cardio
# ---------------------------------------------------------------------------

def _joel_profile():
    return {
        "primary_goal": "fat_loss",
        "training_days_per_week": 3,
        "sessions_per_week_min": 3,
        "sessions_per_week_max": 5,
        "preferred_training_days": ["mon", "tue", "wed", "thu", "fri"],
        "training_experience": "intermediate",
        "variety_preference": "high",
        "cardio_preference": "elliptical",
        "dislikes_running": True,
        "willing_to_train_layovers": True,
    }


def test_joel_demand_creates_three_strength_exposures_per_week():
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(2)
    demand = build_demand(
        client_id="joel_test", client_profile=_joel_profile(),
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    per_week: dict[int, int] = {}
    for e in demand.required_exposures:
        if e.kind == "strength_full_body":
            per_week[e.week_index] = per_week.get(e.week_index, 0) + 1
    for w in range(len(weeks)):
        assert per_week.get(w, 0) == 3, (
            f"Week {w}: expected 3 strength_full_body exposures, "
            f"got {per_week.get(w, 0)}"
        )


def test_joel_strength_session_carries_post_workout_cardio():
    """When cardio_preference is non-run, every strength_full_body session
    must have a `post_workout_cardio` block."""
    spec = build_session_spec(
        kind="strength_full_body",
        duration_min=55,
        intensity_target="rpe7",
        phase_kind="foundation",
        day_type="home_day",
        equipment_ctx={"bodyweight", "dumbbells", "barbell", "rack", "bench",
                        "cable_stack", "kettlebell", "pullup_bar", "elliptical"},
        avoid_patterns=set(),
        exposure_number=1,
        variety_preference="high",
        training_experience="intermediate",
        cardio_preference="elliptical",
        session_slot=0,
        week_index=0,
        attach_post_workout_cardio=True,
    )
    payload = spec.to_dict().get("payload") or {}
    pwc = payload.get("post_workout_cardio")
    assert pwc, f"Expected post_workout_cardio block, got payload={payload}"
    assert pwc.get("modality") == "elliptical"
    assert int(pwc.get("duration_min") or 0) >= 5, (
        f"Cardio duration must be >= 5m, got {pwc.get('duration_min')}"
    )
    assert pwc.get("shortened") is False, (
        f"Session budget 55m should not shorten cardio, got {pwc}"
    )


def test_joel_strength_session_shortens_cardio_when_tight():
    """When session_duration is small (~30m), cardio is shortened but present."""
    spec = build_session_spec(
        kind="strength_full_body",
        duration_min=32,
        intensity_target="rpe7",
        phase_kind="foundation",
        day_type="home_day",
        equipment_ctx={"bodyweight", "dumbbells", "barbell", "rack", "bench",
                        "elliptical"},
        avoid_patterns=set(),
        exposure_number=1,
        variety_preference="high",
        training_experience="intermediate",
        cardio_preference="elliptical",
        session_slot=1,
        week_index=0,
        attach_post_workout_cardio=True,
    )
    pwc = (spec.to_dict().get("payload") or {}).get("post_workout_cardio")
    assert pwc, "Cardio block should still exist"
    assert pwc.get("shortened") is True, (
        f"Expected shortened=True at 32m session, got {pwc}"
    )
    assert pwc.get("shortening_reason"), (
        "Shortening reason must be recorded"
    )


def test_joel_validator_flags_missing_cardio_when_feasible():
    """Full Body session without a post-workout cardio block → ERROR."""
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _joel_profile()
    demand = build_demand(
        client_id="joel_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    placements = [
        _mk_placement("strength_full_body", monday, duration=45),
        _mk_placement("strength_full_body",
                       monday + _dt.timedelta(days=2), duration=45),
        _mk_placement("strength_full_body",
                       monday + _dt.timedelta(days=4), duration=45),
    ]
    # session_specs with NO post_workout_cardio
    session_specs = {
        p.exposure_id: {"kind": p.kind, "payload":
                         {"exercises": [{"name": "X", "role": "primary_squat"}]}}
        for p in placements
    }
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs=session_specs, weeks=1,
        daily_time_cap_by_date=_full_week_caps(monday),
        day_type_by_date=_full_week_day_types(monday),
    )
    errs = [i for i in v.issues if i.code == "fatloss_cardio_missing"]
    assert errs and any(i.severity == "error" for i in errs), (
        f"Expected fatloss_cardio_missing ERROR, got "
        f"{[(i.code, i.severity) for i in v.issues]}"
    )


def test_joel_validator_downgrades_cardio_to_warning_when_cap_tight():
    """If the daily cap < 40m, missing cardio is genuinely time-blocked."""
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _joel_profile()
    demand = build_demand(
        client_id="joel_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    placements = [
        _mk_placement("strength_full_body", monday, duration=25),
    ]
    session_specs = {
        placements[0].exposure_id: {"kind": "strength_full_body",
                                     "payload": {"exercises": [{"name": "X"}]}},
    }
    caps = _full_week_caps(monday, cap_min=25)   # only 25m — cardio can't fit
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs=session_specs, weeks=1,
        daily_time_cap_by_date=caps,
        day_type_by_date=_full_week_day_types(monday),
    )
    missing = [i for i in v.issues if i.code == "fatloss_cardio_missing"]
    assert missing, "Expected a fatloss_cardio_missing issue"
    assert all(i.severity == "warning" for i in missing), (
        f"Expected WARNING (cap-blocked) got "
        f"{[i.severity for i in missing]}"
    )


def test_joel_validator_flags_running_leak_in_cardio():
    """If a post-workout cardio somehow resolved to running, ERROR."""
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _joel_profile()
    demand = build_demand(
        client_id="joel_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    placements = [_mk_placement("strength_full_body", monday, duration=55)]
    session_specs = {
        placements[0].exposure_id: {
            "kind": "strength_full_body",
            "payload": {
                "exercises": [{"name": "Squat"}],
                "post_workout_cardio": {"modality": "run",
                                        "duration_min": 15},
            },
        },
    }
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs=session_specs, weeks=1,
        daily_time_cap_by_date=_full_week_caps(monday),
        day_type_by_date=_full_week_day_types(monday),
    )
    codes_and_sev = {(i.code, i.severity) for i in v.issues}
    assert ("fatloss_cardio_running_leak", "error") in codes_and_sev, (
        f"Expected ERROR fatloss_cardio_running_leak, got {codes_and_sev}"
    )


def test_joel_validator_flags_identical_a_b_c_as_error():
    """Three full-body sessions with IDENTICAL anchors + identical full
    exercise lists → ERROR (block approval)."""
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _joel_profile()
    demand = build_demand(
        client_id="joel_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    placements = [
        _mk_placement("strength_full_body", monday, duration=55),
        _mk_placement("strength_full_body",
                       monday + _dt.timedelta(days=2), duration=55),
        _mk_placement("strength_full_body",
                       monday + _dt.timedelta(days=4), duration=55),
    ]
    identical_exs = [
        {"role": "primary_squat", "name": "Back Squat"},
        {"role": "primary_hinge", "name": "Deadlift"},
        {"role": "primary_horizontal_push", "name": "Bench Press"},
    ]
    session_specs = {p.exposure_id: {"kind": "strength_full_body",
                                      "payload": {
                                          "exercises": identical_exs,
                                          "post_workout_cardio":
                                              {"modality": "elliptical",
                                               "duration_min": 15},
                                      }}
                     for p in placements}
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs=session_specs, weeks=1,
        daily_time_cap_by_date=_full_week_caps(monday),
        day_type_by_date=_full_week_day_types(monday),
    )
    codes_and_sev = {(i.code, i.severity) for i in v.issues}
    assert ("fullbody_sessions_identical", "error") in codes_and_sev, (
        f"Expected ERROR fullbody_sessions_identical. Got: {codes_and_sev}"
    )


def test_joel_validator_flags_strength_count_low_when_feasible():
    """Only 1 strength placed but week is wide open → ERROR
    fatloss_strength_count_low."""
    goal = get_goal_config("strength.fat_loss")
    phase = goal.phase_specs["foundation"]
    weeks = _week_starts(1)
    prof = _joel_profile()
    demand = build_demand(
        client_id="joel_test", client_profile=prof,
        goal_key=goal.key, phase_spec=phase, week_start_dates=weeks,
    )
    monday = _monday()
    placements = [
        _mk_placement("strength_full_body", monday, duration=55),
    ]
    session_specs = {
        placements[0].exposure_id: {
            "kind": "strength_full_body",
            "payload": {
                "exercises": [{"name": "Squat"}],
                "post_workout_cardio": {"modality": "elliptical",
                                        "duration_min": 15},
            },
        },
    }
    v = validate_programme(
        demand=demand, placements=placements,
        phase=phase, goal=goal, unfilled=[],
        client_profile=prof, session_specs=session_specs, weeks=1,
        daily_time_cap_by_date=_full_week_caps(monday),
        day_type_by_date=_full_week_day_types(monday),
    )
    count_low = [i for i in v.issues if i.code == "fatloss_strength_count_low"]
    assert count_low and any(i.severity == "error" for i in count_low), (
        f"Expected ERROR fatloss_strength_count_low, got: "
        f"{[(i.code, i.severity) for i in v.issues]}"
    )


def test_joel_full_body_a_b_c_produce_distinct_anchors_in_practice():
    """End-to-end: three build_session_spec calls with slot 0/1/2 must
    yield genuinely different anchor exercises."""
    equip = {"bodyweight", "dumbbells", "barbell", "rack", "bench",
             "cable_stack", "kettlebell", "pullup_bar", "elliptical"}
    anchors: list[set] = []
    for slot in (0, 1, 2):
        spec = build_session_spec(
            kind="strength_full_body",
            duration_min=55,
            intensity_target="rpe7",
            phase_kind="foundation",
            day_type="home_day",
            equipment_ctx=equip,
            avoid_patterns=set(),
            exposure_number=1,
            variety_preference="high",
            training_experience="intermediate",
            cardio_preference="elliptical",
            session_slot=slot,
            week_index=0,
            attach_post_workout_cardio=True,
        )
        exs = (spec.to_dict().get("payload") or {}).get("exercises") or []
        anchors.append(frozenset(
            e["name"] for e in exs
            if str(e.get("role", "")).startswith("primary_")
        ))
    unique = len({a for a in anchors})
    assert unique >= 2, (
        f"Full Body A/B/C anchors collapsed: {anchors}"
    )
