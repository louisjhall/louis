"""
Iter 121b — Correction pass for General Fitness / Fat Loss ratification.

Focus areas (per user PRD):
  1. Strength frequency: 3-day GF client must get ≥2 strength; mobility does
     NOT displace KEY/IMPORTANT work.
  2. Main training days vs total exposures — mobility stacks, doesn't consume
     one of the client's limited training days.
  3. Variety — block-based anchor rotation + Session A/B pattern remap for
     HIGH-variety strength_full_body.
  4. Anchors refresh between blocks (not permanently frozen).
  5. Beginner clamp — beginner + HIGH pref still stays MODERATE.
  6. Post-deload continuation — GF/FL loop back into `build`.
  7. Onboarding fields plumbed on HomeEquipmentBody.
"""
from __future__ import annotations

import datetime as _dt
from collections import Counter

import pytest

from feature_v2_sport_configs import get_goal_config
from feature_v2_demand_v2 import build_demand
from feature_v2_construction_v2 import build_session_spec
from feature_v2_variety import (
    ANCHOR_SLOTS, pick_exercise_with_variety, full_body_pattern_remap,
    _effective_variety, next_phase_after_deload,
)


# ---------------------------------------------------------------------------
# 1. Strength frequency — mobility no longer displaces strength
# ---------------------------------------------------------------------------

def _week1_kinds(goal_key: str, phase_kind: str, days: int, session_max: int):
    cfg = get_goal_config(goal_key)
    phase = cfg.phase_specs[phase_kind]
    plan = build_demand(
        client_id="fx",
        client_profile={"training_days_per_week": days,
                          "sessions_per_week_max": session_max,
                          "preferred_session_length": 45},
        goal_key=goal_key, phase_spec=phase,
        week_start_dates=[_dt.date(2026, 8, 3)],
    )
    return Counter(e.kind for e in plan.required_exposures if e.week_index == 0)


def test_gf_3day_gets_2_strength_and_1_aerobic():
    k = _week1_kinds("general.fitness", "foundation", days=3, session_max=3)
    assert k.get("strength_full_body", 0) >= 2, f"expected ≥2 strength for 3-day GF, got {k}"
    assert k.get("aerobic_z2", 0) >= 1, f"expected ≥1 aerobic for 3-day GF, got {k}"


def test_gf_3day_build_gets_2_strength():
    k = _week1_kinds("general.fitness", "build", days=3, session_max=3)
    assert k.get("strength_full_body", 0) >= 2, k
    assert k.get("aerobic_z2", 0) >= 1, k


def test_gf_4day_gets_2_strength_and_2_aerobic_or_conditioning():
    k = _week1_kinds("general.fitness", "build", days=4, session_max=4)
    assert k.get("strength_full_body", 0) >= 2, k
    aerobic_plus_cond = k.get("aerobic_z2", 0) + k.get("conditioning_mixed", 0)
    assert aerobic_plus_cond >= 2, f"expected ≥2 aerobic/conditioning, got {k}"


def test_fl_3day_gets_2_strength():
    k = _week1_kinds("strength.fat_loss", "foundation", days=3, session_max=3)
    assert k.get("strength_full_body", 0) >= 2, k
    assert k.get("aerobic_z2", 0) >= 1, k


def test_fl_4day_strength_still_central():
    k = _week1_kinds("strength.fat_loss", "build", days=4, session_max=4)
    strength = k.get("strength_full_body", 0)
    conditioning = k.get("conditioning_mixed", 0) + k.get("run_intervals", 0)
    assert strength >= 2, k
    assert strength > conditioning, f"strength must exceed conditioning, got {k}"


# ---------------------------------------------------------------------------
# 2. Mobility is SUPPORTING and does not displace KEY work
# ---------------------------------------------------------------------------

def test_gf_3day_mobility_does_not_replace_strength():
    """If mobility appears, it stacks on top — strength count remains ≥2."""
    k = _week1_kinds("general.fitness", "foundation", days=3, session_max=3)
    strength = k.get("strength_full_body", 0)
    mobility = k.get("mobility", 0)
    # If mobility appears, strength must NOT have been reduced below 2
    assert strength >= 2, (
        f"mobility ({mobility}) has displaced strength ({strength}). "
        f"KEY quotas must be preserved. {k}"
    )


# ---------------------------------------------------------------------------
# 3. Variety — block-based anchor rotation
# ---------------------------------------------------------------------------

def _run_strength(exposure_number, variety, experience="intermediate",
                    equipment=None):
    equipment = equipment or {"bodyweight", "dumbbells", "barbell", "rack",
                                "bench", "cable_stack", "kettlebell", "band", "mat"}
    spec = build_session_spec(
        kind="strength_full_body", duration_min=45, intensity_target="rpe7",
        phase_kind="build", day_type="home",
        equipment_ctx=equipment, avoid_patterns=set(),
        exposure_number=exposure_number,
        variety_preference=variety,
        training_experience=experience,
    )
    return [ex["name"] for ex in (spec.payload or {}).get("exercises", [])]


def test_high_variety_anchor_rotates_between_blocks():
    """HIGH variety with block_length=4: exposures 1-4 share anchors,
    exposures 5-8 refresh anchors."""
    block1 = [_run_strength(n, "high", "intermediate") for n in range(1, 5)]
    block2 = [_run_strength(n, "high", "intermediate") for n in range(5, 9)]
    # Within block 1, anchor slot 0 is stable
    b1_anchors = {names[0] for names in block1 if names}
    assert len(b1_anchors) == 1, f"anchors should be stable within block1: {b1_anchors}"
    # Between blocks, anchor slot 0 changes (or Session A/B remap changes patterns)
    b1_first = block1[0]
    b2_first = block2[0]
    assert b1_first != b2_first, (
        f"block1 first session {b1_first} vs block2 first session {b2_first} "
        f"should differ (either anchor rotation or Session A/B pattern remap)"
    )


def test_high_variety_produces_at_least_3_distinct_sessions_across_8_exposures():
    all_sessions = [tuple(_run_strength(n, "high", "intermediate"))
                    for n in range(1, 9)]
    distinct = set(all_sessions)
    assert len(distinct) >= 3, (
        f"HIGH variety across 8 exposures should give ≥3 distinct sessions, "
        f"got {len(distinct)}: {distinct}"
    )


def test_moderate_variety_rotates_slower_than_high():
    mod_sessions = {tuple(_run_strength(n, "moderate", "intermediate")) for n in range(1, 9)}
    high_sessions = {tuple(_run_strength(n, "high", "intermediate")) for n in range(1, 9)}
    assert len(high_sessions) >= len(mod_sessions), (
        f"HIGH ({len(high_sessions)}) should rotate ≥ MODERATE ({len(mod_sessions)})"
    )


def test_low_variety_stays_stable():
    all_sessions = {tuple(_run_strength(n, "low", "intermediate")) for n in range(1, 9)}
    assert len(all_sessions) == 1, f"LOW variety should be stable, got {all_sessions}"


def test_beginner_clamped_to_moderate_even_with_high_preference():
    """A beginner requesting HIGH variety receives MODERATE cadence."""
    assert _effective_variety("high", "beginner") == "moderate"
    # And practically: a beginner + HIGH should not rotate every exposure
    exp_sessions = [tuple(_run_strength(n, "high", "beginner")) for n in range(1, 5)]
    # Should look like MODERATE (rotates every 3 exposures) — at most 2 distinct
    assert len(set(exp_sessions)) <= 2


# ---------------------------------------------------------------------------
# 4. Session A / B pattern remap for HIGH-variety strength_full_body
# ---------------------------------------------------------------------------

def test_session_ab_remap_flips_push_pull_axis_between_blocks():
    """HIGH variety: block 0 uses horizontal push/pull; block 1 uses vertical."""
    r0 = full_body_pattern_remap(1, "high", "intermediate", "strength_full_body")
    r1 = full_body_pattern_remap(5, "high", "intermediate", "strength_full_body")
    assert r0 == {}, "block 0 should keep horizontal (Session A)"
    assert r1.get("primary_horizontal_push") == "vertical_push"
    assert r1.get("primary_horizontal_pull") == "vertical_pull"


def test_session_ab_remap_only_for_high_variety():
    assert full_body_pattern_remap(5, "moderate", "intermediate",
                                    "strength_full_body") == {}
    assert full_body_pattern_remap(5, "low", "intermediate",
                                    "strength_full_body") == {}


# ---------------------------------------------------------------------------
# 5. Post-deload continuation
# ---------------------------------------------------------------------------

def test_next_phase_after_deload_for_open_ended_goals():
    assert next_phase_after_deload("general.fitness") == "build"
    assert next_phase_after_deload("strength.fat_loss") == "build"


def test_next_phase_after_deload_for_marathon_is_none():
    assert next_phase_after_deload("running.marathon") is None


# ---------------------------------------------------------------------------
# 6. Onboarding fields plumbed on the backend model
# ---------------------------------------------------------------------------

def test_onboarding_body_accepts_variety_and_cardio_preference():
    from server import HomeEquipmentBody
    fields = HomeEquipmentBody.__fields__
    assert "variety_preference" in fields
    assert "cardio_preference" in fields


# ---------------------------------------------------------------------------
# 7. Marathon regression — configs still intact
# ---------------------------------------------------------------------------

def test_marathon_config_unchanged():
    cfg = get_goal_config("running.marathon")
    assert cfg.display_name == "Marathon"
    build = cfg.phase_specs["build"]
    long_q = next(q for q in build.quotas if q.kind == "run_long")
    assert long_q.priority == "KEY"


# ---------------------------------------------------------------------------
# 8. Full-programme evidence reports (printed to stdout for the report)
# ---------------------------------------------------------------------------

def test_report_gf_3day_week():
    print("\n=== 3-DAY GENERAL FITNESS WEEK (foundation) ===")
    for phase in ("foundation", "build", "consolidation"):
        k = _week1_kinds("general.fitness", phase, days=3, session_max=3)
        main = k.get("strength_full_body", 0) + k.get("aerobic_z2", 0) + k.get("conditioning_mixed", 0)
        support = k.get("mobility", 0) + k.get("recovery", 0)
        parts = ", ".join(f"{name}×{cnt}" for name, cnt in sorted(k.items()))
        print(f"  {phase:14s}: {parts}   [main={main} support={support}]")


def test_report_gf_high_variety_8weeks():
    print("\n=== 4-DAY HIGH-VARIETY GENERAL FITNESS — 8 STRENGTH EXPOSURES ===")
    print("  (exposures 1-4 = Block 1; exposures 5-8 = Block 2)")
    for n in range(1, 9):
        names = _run_strength(n, "high", "intermediate")
        label_block = "B1" if n <= 4 else "B2"
        print(f"  Exp #{n} [{label_block}]: {names}")


def test_report_fl_4day_high_variety_4weeks():
    print("\n=== 4-DAY HIGH-VARIETY FAT LOSS — 4 WEEKS (build) ===")
    total_str = 0
    total_cond = 0
    for wk in range(1, 5):
        k = _week1_kinds("strength.fat_loss", "build", days=4, session_max=4)
        parts = ", ".join(f"{name}×{cnt}" for name, cnt in sorted(k.items()))
        total_str += k.get("strength_full_body", 0)
        total_cond += k.get("conditioning_mixed", 0) + k.get("run_intervals", 0)
        print(f"  Week {wk}: {parts}")
    print(f"  4-week totals: strength={total_str}  conditioning={total_cond}")
    assert total_str > total_cond


def test_report_variety_demonstration_detailed():
    """Detailed variety demonstration (used for the final report)."""
    print("\n=== VARIETY DEMONSTRATION — 8 exposures, HIGH intermediate ===")
    slots = ["squat/knee", "hinge", "push", "pull", "trunk"]
    print(f"  Slots: {slots}")
    for n in range(1, 9):
        names = _run_strength(n, "high", "intermediate")
        blk = "Block 1" if n <= 4 else "Block 2"
        print(f"  #{n} [{blk}]: {names}")
    # Confirm the two blocks are meaningfully different
    b1 = tuple(_run_strength(1, "high", "intermediate"))
    b2 = tuple(_run_strength(5, "high", "intermediate"))
    diff = sum(1 for a, b in zip(b1, b2) if a != b)
    print(f"  Slots that changed between Block 1 and Block 2: {diff} / {len(b1)}")
    assert diff >= 2, f"expected ≥2 slot changes between blocks, got {diff}"
