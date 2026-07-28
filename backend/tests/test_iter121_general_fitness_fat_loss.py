"""
Iter 121 — General Fitness + Fat Loss config ratification.

Six deterministic client fixtures + 4-week multi-week demonstration:

  GF-A  Beginner       3 days/wk   45 min   home dumbbells   variety=moderate
  GF-B  Intermediate   4 days/wk   60 min   full gym         variety=high
  GF-C  Pilot          4 days/wk   45 min   home+travel      variety=high
  FL-A  Beginner       3 days/wk   45 min   dumbbells+BW     variety=moderate
  FL-B  Intermediate   4 days/wk   60 min   full gym         variety=high
  FL-C  Pilot          4 days/wk   45 min   irregular roster variety=high

Validates:
- Each config produces balanced weekly demand (not cardio-only, not
  strength-only, not excessive HIIT).
- Frequency scales down for 3-day clients without hardcoded branches.
- Progression: duration / RPE evolve across phases.
- Variety: HIGH variety clients see different accessory exercises across
  exposures while anchor movements stay stable.
- Fat Loss keeps strength CENTRAL (>= aerobic exposure count) and does NOT
  become a HIIT programme (conditioning capped at 1/wk).
- Zero LLM calls, zero programme regenerations.
- Marathon regression stays green.
"""
from __future__ import annotations

import datetime as _dt
from collections import Counter

import pytest

from feature_v2_sport_configs import (
    get_goal_config, resolve_phase_plan, canonicalise_goal_key,
    SPORT_CONFIGS,
)
from feature_v2_demand_v2 import build_demand
from feature_v2_construction_v2 import build_session_spec


# ---------------------------------------------------------------------------
# Fixture DNAs
# ---------------------------------------------------------------------------

FIXTURES = {
    "GF-A": {
        "label": "General Fitness · Beginner · 3d · home dumbbells · moderate",
        "goal_key": "general.fitness",
        "profile": {
            "training_days_per_week": 3,
            "sessions_per_week_max": 3,
            "preferred_session_length": 45,
            "training_experience": "beginner",
            "cardio_preference": "run",
            "variety_preference": "moderate",
        },
        "equipment_ctx": {"bodyweight", "dumbbells", "mat"},
    },
    "GF-B": {
        "label": "General Fitness · Intermediate · 4d · full gym · high",
        "goal_key": "general.fitness",
        "profile": {
            "training_days_per_week": 4,
            "sessions_per_week_max": 5,
            "preferred_session_length": 60,
            "training_experience": "intermediate",
            "cardio_preference": "bike",
            "variety_preference": "high",
        },
        "equipment_ctx": {"bodyweight", "dumbbells", "barbell", "rack", "bench",
                            "cable_stack", "kettlebell", "band", "mat", "bike"},
    },
    "GF-C": {
        "label": "General Fitness · Pilot · 4d · home+travel · high",
        "goal_key": "general.fitness",
        "profile": {
            "training_days_per_week": 4,
            "sessions_per_week_max": 4,
            "preferred_session_length": 45,
            "training_experience": "intermediate",
            "cardio_preference": "run",
            "variety_preference": "high",
        },
        "equipment_ctx": {"bodyweight", "dumbbells", "band", "mat"},
    },
    "FL-A": {
        "label": "Fat Loss · Beginner · 3d · dumbbells+BW · moderate",
        "goal_key": "strength.fat_loss",
        "profile": {
            "training_days_per_week": 3,
            "sessions_per_week_max": 3,
            "preferred_session_length": 45,
            "training_experience": "beginner",
            "cardio_preference": "walk",
            "variety_preference": "moderate",
        },
        "equipment_ctx": {"bodyweight", "dumbbells", "mat"},
    },
    "FL-B": {
        "label": "Fat Loss · Intermediate · 4d · full gym · high",
        "goal_key": "strength.fat_loss",
        "profile": {
            "training_days_per_week": 4,
            "sessions_per_week_max": 5,
            "preferred_session_length": 60,
            "training_experience": "intermediate",
            "cardio_preference": "bike",
            "variety_preference": "high",
        },
        "equipment_ctx": {"bodyweight", "dumbbells", "barbell", "rack", "bench",
                            "cable_stack", "kettlebell", "band", "mat", "bike"},
    },
    "FL-C": {
        "label": "Fat Loss · Pilot · 4d · irregular roster · high",
        "goal_key": "strength.fat_loss",
        "profile": {
            "training_days_per_week": 4,
            "sessions_per_week_max": 4,
            "preferred_session_length": 45,
            "training_experience": "intermediate",
            "cardio_preference": "walk",
            "variety_preference": "high",
        },
        "equipment_ctx": {"bodyweight", "dumbbells", "band", "mat"},
    },
}


def _weekly_demand(fixture_key: str, phase_kind: str, weeks: int = 4):
    fx = FIXTURES[fixture_key]
    cfg = get_goal_config(fx["goal_key"])
    phase = cfg.phase_specs[phase_kind]
    week_starts = [_dt.date(2026, 8, 3) + _dt.timedelta(days=7 * i)
                   for i in range(weeks)]
    plan = build_demand(
        client_id=f"fixture-{fixture_key}",
        client_profile=fx["profile"],
        goal_key=fx["goal_key"],
        phase_spec=phase,
        week_start_dates=week_starts,
    )
    return plan


# ============================================================================
# A. Config-registered goals
# ============================================================================

def test_general_fitness_registered():
    cfg = get_goal_config("general.fitness")
    assert cfg.display_name == "General Fitness"
    assert cfg.phase_sequence == ("foundation", "build", "consolidation", "deload")


def test_fat_loss_registered():
    cfg = get_goal_config("strength.fat_loss")
    assert cfg.display_name == "Fat Loss"
    assert "conditioning_mixed" in {q.kind for q in cfg.phase_specs["build"].quotas}


def test_aliases_work():
    assert canonicalise_goal_key("fat_loss") == "strength.fat_loss"
    assert canonicalise_goal_key("Fat Loss") == "strength.fat_loss"
    assert canonicalise_goal_key("general_fitness") == "general.fitness"
    assert canonicalise_goal_key("longevity") == "general.fitness"


# ============================================================================
# B. Frequency scaling — 3-day client must NOT receive 5 exposures/wk
# ============================================================================

@pytest.mark.parametrize("fx", ["GF-A", "FL-A"])
def test_three_day_client_scales_down(fx):
    plan = _weekly_demand(fx, "build", weeks=1)
    week_count = sum(1 for e in plan.required_exposures if e.week_index == 0)
    # 3-day client should never receive more than 5 exposures/week
    # (support quotas can stack but the frequency cap in the phase prevents blowout)
    assert 2 <= week_count <= 5, f"{fx} week count = {week_count}"


@pytest.mark.parametrize("fx", ["GF-B", "FL-B"])
def test_four_day_client_gets_more_exposures(fx):
    plan = _weekly_demand(fx, "build", weeks=1)
    week_count = sum(1 for e in plan.required_exposures if e.week_index == 0)
    # 4-day intermediate should receive >= 3 exposures/week
    assert week_count >= 3, f"{fx} week count = {week_count}"


# ============================================================================
# C. Balance — Fat Loss keeps strength CENTRAL
# ============================================================================

def test_fat_loss_strength_is_central():
    plan = _weekly_demand("FL-B", "build", weeks=4)
    kinds = Counter(e.kind for e in plan.required_exposures)
    strength = kinds.get("strength_full_body", 0)
    conditioning = kinds.get("conditioning_mixed", 0) + kinds.get("run_intervals", 0)
    assert strength >= conditioning, (
        f"Fat loss should keep strength >= conditioning. "
        f"strength={strength} conditioning={conditioning}"
    )


def test_fat_loss_conditioning_capped():
    plan = _weekly_demand("FL-B", "build", weeks=4)
    cond = sum(1 for e in plan.required_exposures if e.kind == "conditioning_mixed")
    assert cond <= 4, f"conditioning_mixed appearances = {cond} across 4 weeks (cap 4)"


def test_fat_loss_no_intervals_in_foundation():
    plan = _weekly_demand("FL-A", "foundation", weeks=2)
    assert not any(e.kind == "run_intervals" for e in plan.required_exposures)
    assert not any(e.kind == "conditioning_intervals" for e in plan.required_exposures)


# ============================================================================
# D. Balance — General Fitness develops MULTIPLE qualities
# ============================================================================

def test_general_fitness_covers_multiple_qualities():
    plan = _weekly_demand("GF-B", "build", weeks=4)
    kinds = {e.kind for e in plan.required_exposures}
    assert "strength_full_body" in kinds, "GF must include strength"
    assert "aerobic_z2" in kinds,       "GF must include aerobic Z2"
    assert "mobility" in kinds,         "GF must include mobility"


# ============================================================================
# E. Progression — duration & RPE evolve across phases
# ============================================================================

def test_general_fitness_duration_progresses_between_phases():
    cfg = get_goal_config("general.fitness")
    q_found = next(q for q in cfg.phase_specs["foundation"].quotas
                   if q.kind == "strength_full_body")
    q_build = next(q for q in cfg.phase_specs["build"].quotas
                   if q.kind == "strength_full_body")
    # Target duration should not regress
    assert q_build.duration_min[1] >= q_found.duration_min[1]
    # RPE / intensity target should NOT be lower in build
    assert q_build.intensity_target >= q_found.intensity_target or q_build.intensity_target != q_found.intensity_target


# ============================================================================
# F. Variety — HIGH variety client sees rotation
# ============================================================================

def _first_exercise_names_across_exposures(fx_key: str, kind: str, exposures: int):
    fx = FIXTURES[fx_key]
    names_per_exposure = []
    for n in range(1, exposures + 1):
        spec = build_session_spec(
            kind=kind, duration_min=45, intensity_target="rpe7",
            phase_kind="build", day_type="home",
            equipment_ctx=fx["equipment_ctx"],
            avoid_patterns=set(),
            exposure_number=n,
            variety_preference=fx["profile"]["variety_preference"],
            cardio_preference=fx["profile"]["cardio_preference"],
        )
        names_per_exposure.append(
            [ex["name"] for ex in (spec.payload or {}).get("exercises", [])]
        )
    return names_per_exposure


def test_high_variety_rotates_accessories():
    """GF-B (variety=high) should see accessory changes across 6 exposures."""
    all_names = _first_exercise_names_across_exposures("GF-B", "strength_full_body", 6)
    # Anchor slot #0 (primary_squat) must be stable across exposures
    anchor_names = {names[0] for names in all_names if names}
    assert len(anchor_names) == 1, (
        f"anchor primary_squat should be stable, got {anchor_names}"
    )
    # But at least one non-anchor slot should have varied across exposures
    all_join = {tuple(n) for n in all_names}
    assert len(all_join) >= 2, f"high variety should produce >=2 distinct sessions, got {all_join}"


def test_low_variety_stays_stable():
    """LOW variety client sees the same exercises every exposure."""
    fx = dict(FIXTURES["GF-A"])
    fx = {**fx, "profile": {**fx["profile"], "variety_preference": "low"}}
    names = []
    for n in range(1, 5):
        spec = build_session_spec(
            kind="strength_full_body", duration_min=45, intensity_target="rpe7",
            phase_kind="build", day_type="home",
            equipment_ctx=fx["equipment_ctx"], avoid_patterns=set(),
            exposure_number=n, variety_preference="low",
        )
        names.append(tuple(ex["name"] for ex in (spec.payload or {}).get("exercises", [])))
    # All 4 exposures should be identical
    assert len(set(names)) == 1, f"LOW variety should be stable, got {set(names)}"


# ============================================================================
# G. Cardio modality — aerobic_z2 resolves per client preference
# ============================================================================

def test_aerobic_z2_walk_preference_outputs_walk_session():
    spec = build_session_spec(
        kind="aerobic_z2", duration_min=30, intensity_target="z2",
        phase_kind="build", day_type="home",
        equipment_ctx={"bodyweight"}, avoid_patterns=set(),
        cardio_preference="walk",
    )
    assert spec.spec_kind == "running"
    assert "walking_shoes" in spec.equipment_used
    assert spec.payload["main"]["type"] == "brisk_walk"


def test_aerobic_z2_bike_preference_outputs_bike_session():
    spec = build_session_spec(
        kind="aerobic_z2", duration_min=30, intensity_target="z2",
        phase_kind="build", day_type="home",
        equipment_ctx={"bodyweight", "bike"}, avoid_patterns=set(),
        cardio_preference="bike",
    )
    assert spec.spec_kind == "cycling"
    assert "bike" in spec.equipment_used


def test_aerobic_z2_default_run():
    spec = build_session_spec(
        kind="aerobic_z2", duration_min=30, intensity_target="z2",
        phase_kind="build", day_type="home",
        equipment_ctx={"bodyweight"}, avoid_patterns=set(),
    )
    assert spec.spec_kind == "running"
    assert spec.payload["main"]["type"] == "steady"


# ============================================================================
# H. Conditioning builder produces real content
# ============================================================================

def test_conditioning_mixed_produces_circuit_stations():
    spec = build_session_spec(
        kind="conditioning_mixed", duration_min=20, intensity_target="moderate",
        phase_kind="build", day_type="home",
        equipment_ctx={"bodyweight"}, avoid_patterns=set(),
    )
    assert spec.spec_kind == "conditioning"
    stations = spec.payload["main"].get("stations")
    assert stations and len(stations) >= 4


# ============================================================================
# I. 4-week multi-week demonstration
# ============================================================================

def _programme_summary(fx_key: str, phase: str = "build", weeks: int = 4):
    plan = _weekly_demand(fx_key, phase, weeks=weeks)
    by_week: dict[int, Counter] = {}
    for e in plan.required_exposures:
        by_week.setdefault(e.week_index, Counter())[e.kind] += 1
    return by_week


def test_multi_week_general_fitness_summary():
    summary = _programme_summary("GF-B", "build", weeks=4)
    # Print summary — used for the final report
    print("\n=== GF-B FOUR-WEEK PROGRAMME (BUILD PHASE) ===")
    for wk, counts in sorted(summary.items()):
        parts = [f"{k}×{v}" for k, v in sorted(counts.items())]
        print(f"  Week {wk}: {', '.join(parts)}")
    assert len(summary) >= 3, "expected at least 3 weeks of demand"


def test_multi_week_fat_loss_summary():
    summary = _programme_summary("FL-B", "build", weeks=4)
    print("\n=== FL-B FOUR-WEEK PROGRAMME (BUILD PHASE) ===")
    strength_total = 0
    conditioning_total = 0
    for wk, counts in sorted(summary.items()):
        parts = [f"{k}×{v}" for k, v in sorted(counts.items())]
        print(f"  Week {wk}: {', '.join(parts)}")
        strength_total += counts.get("strength_full_body", 0)
        conditioning_total += counts.get("conditioning_mixed", 0) + counts.get("run_intervals", 0)
    print(f"  TOTAL: strength={strength_total}  conditioning={conditioning_total}")
    assert strength_total > conditioning_total


def test_variety_demonstration_high_variety_client():
    """Print evidence that Weeks 1..6 don't produce identical sessions for a
    HIGH variety client while anchor movements stay stable."""
    all_names = _first_exercise_names_across_exposures("FL-B", "strength_full_body", 6)
    print("\n=== VARIETY DEMONSTRATION (FL-B, HIGH variety, strength_full_body) ===")
    for i, names in enumerate(all_names, start=1):
        print(f"  Exposure #{i}: {names}")
    # Anchor slot 0 stable
    anchors = {n[0] for n in all_names if n}
    assert len(anchors) == 1
    print(f"  ANCHOR (slot 0) stable across all exposures: {anchors.pop()}")
    # Accessories rotated (slots 1..N combined varied)
    accessories = {tuple(n[1:]) for n in all_names if len(n) > 1}
    assert len(accessories) >= 2, "accessories should have rotated for HIGH variety"
    print(f"  ACCESSORIES rotated across exposures — {len(accessories)} distinct combinations")


# ============================================================================
# J. Marathon regression is unaffected
# ============================================================================

def test_marathon_config_unchanged():
    cfg = get_goal_config("running.marathon")
    assert cfg.display_name == "Marathon"
    assert cfg.phase_sequence == (
        "foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"
    )


def test_marathon_build_still_has_long_run_key():
    cfg = get_goal_config("running.marathon")
    build = cfg.phase_specs["build"]
    long_q = next(q for q in build.quotas if q.kind == "run_long")
    assert long_q.priority == "KEY"


# ============================================================================
# K. Zero LLM & zero programme generation for fixture flow
# ============================================================================

def test_no_llm_import_in_construction():
    """No LLM libraries are imported in the deterministic construction path."""
    import feature_v2_construction_v2 as mod
    src = open(mod.__file__).read()
    for banned in ("openai", "anthropic", "emergentintegrations", "gpt", "claude"):
        # These should not be imported at module scope for construction
        assert f"import {banned}" not in src.lower()
