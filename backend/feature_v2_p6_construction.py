"""
feature_v2_p6_construction — V2 Phase 6: Workout construction (HOW layer).

Materialises WorkoutImplementations from WorkoutAssignments by:
  1. Looking up a matching workout_slot_template for the objective_kind + phase_kind.
  2. Ranking approved exercises_v2 records that match each slot's role_pattern_pool
     and the equipment_context.
  3. Applying deterministic post-filters (contraindication vs restrictions & readiness pain_flags).
  4. Emitting a WorkoutImplementation with sets/reps/rest resolved from the slot spec.
  5. Optionally polishing rationale via LLM (best-effort; falls back to template).

Ships behind `v2_flags.construction_v2_enabled`. Requires P3+P5 upstream.
"""
from __future__ import annotations

import datetime as _dt
import random
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg, emit_metric
)

FLAG = "construction_v2_enabled"


# ---------------------------------------------------------------------------
# Slot templates (seeded)
# ---------------------------------------------------------------------------

_SLOT_TEMPLATES_SEED = [
    # ---- Strength ----
    {
        "objective_kind": "upper_hypertrophy", "phase_kind": "hypertrophy",
        "intent": "primary", "target_duration_min": 45,
        "slots": [
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"],
             "equipment_preference": ["barbell", "dumbbells", "machine_chest_press"],
             "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7-8", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"],
             "equipment_preference": ["dumbbells", "cable_stack", "machine_row"],
             "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7-8", "key": True, "required": True},
            {"role": "secondary_vertical_push", "role_pattern_pool": ["vertical_push"],
             "equipment_preference": ["dumbbells", "barbell"], "sets": 3, "reps": "10-12",
             "rest_sec": 60, "rpe_target": "7", "key": False, "required": False},
            {"role": "secondary_vertical_pull", "role_pattern_pool": ["vertical_pull"],
             "equipment_preference": ["pull_up_bar", "machine_lat_pulldown", "band"],
             "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": False, "required": False},
            {"role": "trunk", "role_pattern_pool": ["anti_extension", "anti_rotate"],
             "equipment_preference": ["bodyweight", "cable_stack"], "sets": 2, "reps": "30-45s",
             "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
        "short_variants": [
            {"target_duration_min": 30, "keep_slots": ["primary_horizontal_push", "primary_horizontal_pull", "trunk"], "compress_rules": {}},
            {"target_duration_min": 20, "keep_slots": ["primary_horizontal_push", "primary_horizontal_pull"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"],
             "equipment_preference": ["bodyweight"], "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"],
             "equipment_preference": ["bodyweight", "band"], "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "trunk", "role_pattern_pool": ["anti_extension"], "equipment_preference": ["bodyweight"],
             "sets": 2, "reps": "30-45s", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
    },
    {
        "objective_kind": "lower_hypertrophy", "phase_kind": "hypertrophy",
        "intent": "primary", "target_duration_min": 45,
        "slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"],
             "equipment_preference": ["barbell", "dumbbells", "machine_leg_press"],
             "sets": 4, "reps": "6-8", "rest_sec": 120, "rpe_target": "8", "key": True, "required": True},
            {"role": "primary_hinge", "role_pattern_pool": ["hinge"],
             "equipment_preference": ["barbell", "dumbbells", "kettlebell"],
             "sets": 3, "reps": "8-10", "rest_sec": 120, "rpe_target": "7-8", "key": True, "required": True},
            {"role": "unilateral_leg", "role_pattern_pool": ["lunge"],
             "equipment_preference": ["dumbbells", "kettlebell", "bodyweight"],
             "sets": 3, "reps": "10 each side", "rest_sec": 60, "rpe_target": "7", "key": False, "required": False},
            {"role": "trunk", "role_pattern_pool": ["anti_rotate"], "equipment_preference": ["cable_stack", "band", "bodyweight"],
             "sets": 2, "reps": "30-45s", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
        "short_variants": [
            {"target_duration_min": 30, "keep_slots": ["primary_squat", "primary_hinge", "trunk"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["bodyweight"],
             "sets": 3, "reps": "12-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_hinge", "role_pattern_pool": ["hinge"], "equipment_preference": ["bodyweight"],
             "sets": 3, "reps": "10-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "unilateral_leg", "role_pattern_pool": ["lunge"], "equipment_preference": ["bodyweight"],
             "sets": 3, "reps": "10 each side", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
    },
    {
        "objective_kind": "full_body_strength", "phase_kind": "foundation",
        "intent": "primary", "target_duration_min": 40,
        "slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["barbell", "dumbbells", "bodyweight"],
             "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"],
             "equipment_preference": ["dumbbells", "barbell", "bodyweight"], "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"],
             "equipment_preference": ["dumbbells", "cable_stack", "band"], "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
            {"role": "trunk", "role_pattern_pool": ["anti_extension", "anti_rotate"],
             "equipment_preference": ["bodyweight"], "sets": 2, "reps": "30-45s", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
        "short_variants": [
            {"target_duration_min": 25, "keep_slots": ["primary_squat", "primary_horizontal_push", "primary_horizontal_pull"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["bodyweight"], "sets": 3, "reps": "12-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"], "equipment_preference": ["bodyweight"], "sets": 3, "reps": "8-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"], "equipment_preference": ["bodyweight", "band"], "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
        ],
    },
    # ---- Endurance ----
    {
        "objective_kind": "easy_run", "phase_kind": "aerobic_base",
        "intent": "primary", "target_duration_min": 40,
        "slots": [
            {"role": "cardio_z2", "role_pattern_pool": ["gait_run_easy"],
             "equipment_preference": ["outdoor_run_safe", "treadmill"],
             "sets": 1, "reps": "z2", "rest_sec": 0, "rpe_target": "4-5", "key": True, "required": True,
             "hr_zone": "z2"},
        ],
        "short_variants": [
            {"target_duration_min": 20, "keep_slots": ["cardio_z2"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "cardio_z2_indoor", "role_pattern_pool": ["gait_run_easy"], "equipment_preference": ["bodyweight"],
             "sets": 1, "reps": "z2 (marching / step)", "rest_sec": 0, "rpe_target": "4-5", "key": True, "required": True},
        ],
    },
    {
        "objective_kind": "long_run", "phase_kind": "build",
        "intent": "primary", "target_duration_min": 90,
        "slots": [
            {"role": "cardio_long", "role_pattern_pool": ["gait_run_long"],
             "equipment_preference": ["outdoor_run_safe"], "sets": 1, "reps": "60-90 min z2",
             "rest_sec": 0, "rpe_target": "5-6", "key": True, "required": True, "hr_zone": "z2"},
        ],
        "short_variants": [
            {"target_duration_min": 60, "keep_slots": ["cardio_long"], "compress_rules": {}},
            {"target_duration_min": 45, "keep_slots": ["cardio_long"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "cardio_long_indoor", "role_pattern_pool": ["gait_run_long"], "equipment_preference": ["treadmill"],
             "sets": 1, "reps": "45-60 min z2", "rest_sec": 0, "rpe_target": "5", "key": True, "required": True},
        ],
    },
    {
        "objective_kind": "tempo_run", "phase_kind": "build",
        "intent": "primary", "target_duration_min": 45,
        "slots": [
            {"role": "cardio_tempo", "role_pattern_pool": ["gait_run_tempo"],
             "equipment_preference": ["outdoor_run_safe", "treadmill"], "sets": 1, "reps": "20-30min tempo",
             "rest_sec": 0, "rpe_target": "7", "key": True, "required": True, "hr_zone": "z4"},
        ],
        "short_variants": [{"target_duration_min": 30, "keep_slots": ["cardio_tempo"], "compress_rules": {}}],
        "bodyweight_fallback_slots": [
            {"role": "cardio_tempo_indoor", "role_pattern_pool": ["gait_run_tempo"], "equipment_preference": ["treadmill"],
             "sets": 1, "reps": "20 min tempo", "rest_sec": 0, "rpe_target": "7", "key": True, "required": True},
        ],
    },
    {
        "objective_kind": "mobility", "phase_kind": "foundation",
        "intent": "primary", "target_duration_min": 20,
        "slots": [
            {"role": "flow", "role_pattern_pool": ["mobility_flow"],
             "equipment_preference": ["mat", "bodyweight"], "sets": 1, "reps": "15-20 min flow",
             "rest_sec": 0, "rpe_target": "3-4", "key": False, "required": True},
        ],
        "short_variants": [{"target_duration_min": 10, "keep_slots": ["flow"], "compress_rules": {}}],
        "bodyweight_fallback_slots": [
            {"role": "flow", "role_pattern_pool": ["mobility_flow"], "equipment_preference": ["bodyweight"],
             "sets": 1, "reps": "10-15 min flow", "rest_sec": 0, "rpe_target": "3-4", "key": False, "required": True},
        ],
    },
]


async def seed_slot_templates_once() -> None:
    all_templates = list(_SLOT_TEMPLATES_SEED)
    # Extra templates defined lower in this file — merge safely at call time.
    try:
        all_templates += list(_EXTRA_SLOT_TEMPLATES_SEED)  # type: ignore[name-defined]
    except NameError:
        pass
    for t in all_templates:
        await db.workout_slot_templates.update_one(
            {"objective_kind": t["objective_kind"], "phase_kind": t["phase_kind"], "intent": t["intent"]},
            {"$setOnInsert": {**t, "id": new_id(), "created_at": now_iso(), "updated_at": now_iso()}},
            upsert=True,
        )


# ---------------------------------------------------------------------------
# Exercise selection
# ---------------------------------------------------------------------------

async def _select_exercise_for_slot(
    slot: dict, equipment_avail: set[str], avoid_regions: set[str]
) -> Optional[dict]:
    """Find best approved exercise from exercises_v2 for a slot."""
    pool = list(slot.get("role_pattern_pool") or [])
    pref = list(slot.get("equipment_preference") or [])
    if not pool:
        return None

    # Query candidates
    q: dict = {
        "$and": [
            {"$or": [{"movement_pattern": {"$in": pool}}, {"movement_family": {"$in": pool}}]},
            {"$or": [{"approval": "approved"}, {"approval_status": {"$in": ["approved", "live"]}}]},
        ]
    }
    if equipment_avail:
        q["$and"].append({"equipment_type": {"$in": list(equipment_avail)}})

    candidates = await db.exercises_v2.find(q, {"_id": 0}).limit(50).to_list(50)
    if not candidates:
        # fall back to exercises legacy
        candidates = await db.exercises.find(
            {"$or": [{"movement_pattern": {"$in": pool}}, {"movement_family": {"$in": pool}}]},
            {"_id": 0}
        ).limit(50).to_list(50) or []

    # Post-filter: avoid contraindicated regions
    def _ok(ex: dict) -> bool:
        contra = set(ex.get("contraindications") or [])
        return not (avoid_regions & contra)

    candidates = [c for c in candidates if _ok(c)]
    if not candidates:
        return None

    # Rank: exact equipment match first, then compound, then random
    def _score(ex: dict) -> tuple[int, int, int]:
        eq = set(ex.get("equipment_type") or [])
        pref_score = 100 - min(99, next((i for i, p in enumerate(pref) if p in eq), 99))
        compound_score = 1 if ex.get("compound") else 0
        return (pref_score, compound_score, random.randint(0, 1000))

    candidates.sort(key=_score, reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# P1-3 / P0-1: Endurance session builders (blocks[] schema)
# ---------------------------------------------------------------------------
# For non-strength sessions (running, cycling, swim, mobility), we DO NOT
# populate exercises[] — those templates are gym-shape. Instead we build a
# `blocks` list. Each block:
#   {type, duration_min, pace_target?, hr_zone?, effort_rpe?, cue?}
#
# The V2 workout drawer renders exercises[] for gym focus and blocks[] for
# endurance focus. An implementation with NEITHER cannot leave "building".

def _build_running_blocks(focus: str, target_min: int, phase_kind: str,
                          avoid: set[str]) -> list[dict]:
    """Return a blocks[] list for a running session."""
    # Skip running altogether if a "no run" restriction is active
    if any(kw in avoid for kw in ("gait_run_easy", "gait_run_tempo",
                                   "gait_run_long", "foot", "plantar")):
        return []
    if focus in ("easy_run", "z2_run", "recovery_run"):
        wu = max(5, int(target_min * 0.15))
        cd = max(5, int(target_min * 0.10))
        steady = max(10, target_min - wu - cd)
        return [
            {"type": "warmup", "duration_min": wu, "hr_zone": "z1",
             "effort_rpe": 3, "cue": "Walk → easy jog."},
            {"type": "steady", "duration_min": steady, "hr_zone": "z2",
             "pace_target": "conversational", "effort_rpe": 4,
             "cue": "Nasal breath, chat-pace."},
            {"type": "cooldown", "duration_min": cd, "hr_zone": "z1",
             "effort_rpe": 2, "cue": "Walk-out + light mobility."},
        ]
    if focus == "long_run":
        wu = 10; cd = 5
        steady = max(30, target_min - wu - cd)
        return [
            {"type": "warmup", "duration_min": wu, "hr_zone": "z1",
             "effort_rpe": 3, "cue": "Progressive warmup — walk to easy jog."},
            {"type": "steady", "duration_min": steady, "hr_zone": "z2",
             "pace_target": "MP + 60-90s", "effort_rpe": 5,
             "cue": "Aerobic base. Fuel every 30-40 min."},
            {"type": "cooldown", "duration_min": cd, "hr_zone": "z1",
             "effort_rpe": 2, "cue": "Cool down walk + stretch."},
        ]
    if focus == "tempo_run":
        wu = 10; cd = 5
        tempo = max(15, target_min - wu - cd)
        return [
            {"type": "warmup", "duration_min": wu, "hr_zone": "z1",
             "effort_rpe": 3, "cue": "Easy jog + 4x20s strides."},
            {"type": "tempo", "duration_min": tempo, "hr_zone": "z4",
             "pace_target": "10K–HM pace", "effort_rpe": 7,
             "cue": "Comfortably-hard. Sustained effort."},
            {"type": "cooldown", "duration_min": cd, "hr_zone": "z1",
             "effort_rpe": 2, "cue": "5 min easy jog + walk."},
        ]
    if focus in ("interval_run", "intervals_run", "vo2_intervals", "threshold_intervals"):
        wu = 10; cd = 5
        work_avail = max(15, target_min - wu - cd)
        # 5x3min z4 with 90s recovery is a solid default for aerobic build
        reps = min(6, max(3, work_avail // 5))
        return [
            {"type": "warmup", "duration_min": wu, "hr_zone": "z1",
             "effort_rpe": 3, "cue": "Jog + 4x20s strides."},
            {"type": "interval", "duration_min": reps * 3, "hr_zone": "z4",
             "pace_target": "5K–10K pace", "effort_rpe": 8,
             "sets": reps, "work_sec": 180, "rest_sec": 90,
             "cue": f"{reps} × 3 min hard / 90s easy jog."},
            {"type": "cooldown", "duration_min": cd, "hr_zone": "z1",
             "effort_rpe": 2, "cue": "Slow jog + walk."},
        ]
    if focus in ("race_pace", "specific_prep", "marathon_pace"):
        wu = 10; cd = 5
        mp = max(20, target_min - wu - cd)
        return [
            {"type": "warmup", "duration_min": wu, "hr_zone": "z2",
             "effort_rpe": 4, "cue": "Progressive to MP."},
            {"type": "steady", "duration_min": mp, "hr_zone": "z3",
             "pace_target": "goal marathon pace", "effort_rpe": 6,
             "cue": "Lock in target MP. Practise fuelling."},
            {"type": "cooldown", "duration_min": cd, "hr_zone": "z1",
             "effort_rpe": 2, "cue": "5 min easy jog + walk."},
        ]
    return []


def _build_mobility_blocks(target_min: int, avoid: set[str]) -> list[dict]:
    duration = max(10, min(target_min or 20, 30))
    return [
        {"type": "flow", "duration_min": max(5, duration // 3),
         "cue": "Breath-led warm flow: cat/cow → world's greatest stretch."},
        {"type": "flow", "duration_min": max(5, duration // 3),
         "cue": "Hip openers: 90-90s, deep squat hold, thoracic rotations."},
        {"type": "flow", "duration_min": max(5, duration - 2*(duration // 3)),
         "cue": "Downshift: legs-up-wall + slow diaphragm breathing."},
    ]


def _build_cardio_generic_blocks(focus: str, target_min: int) -> list[dict]:
    """Cycling / swim / rowing generic aerobic session."""
    wu = 5; cd = 5
    steady = max(10, target_min - wu - cd)
    return [
        {"type": "warmup", "duration_min": wu, "hr_zone": "z1",
         "effort_rpe": 3, "cue": "Easy pace to build."},
        {"type": "steady", "duration_min": steady, "hr_zone": "z2",
         "effort_rpe": 5, "cue": "Sustained aerobic effort."},
        {"type": "cooldown", "duration_min": cd, "hr_zone": "z1",
         "effort_rpe": 2, "cue": "Cool down."},
    ]


# Extra slot templates for phase-varied endurance
_EXTRA_SLOT_TEMPLATES_SEED = [
    # Easy runs in every phase
    {"objective_kind": "easy_run", "phase_kind": "foundation", "intent": "primary",
     "target_duration_min": 30, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "easy_run", "phase_kind": "build", "intent": "primary",
     "target_duration_min": 45, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "easy_run", "phase_kind": "specific_prep", "intent": "primary",
     "target_duration_min": 45, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "easy_run", "phase_kind": "taper", "intent": "primary",
     "target_duration_min": 30, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "easy_run", "phase_kind": "race_week", "intent": "primary",
     "target_duration_min": 20, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    # Long runs
    {"objective_kind": "long_run", "phase_kind": "aerobic_base", "intent": "primary",
     "target_duration_min": 75, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "long_run", "phase_kind": "specific_prep", "intent": "primary",
     "target_duration_min": 110, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "long_run", "phase_kind": "taper", "intent": "primary",
     "target_duration_min": 60, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    # Tempo runs
    {"objective_kind": "tempo_run", "phase_kind": "specific_prep", "intent": "primary",
     "target_duration_min": 50, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    # Intervals
    {"objective_kind": "interval_run", "phase_kind": "build", "intent": "primary",
     "target_duration_min": 40, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "interval_run", "phase_kind": "specific_prep", "intent": "primary",
     "target_duration_min": 45, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    # Marathon-pace / race pace
    {"objective_kind": "race_pace", "phase_kind": "specific_prep", "intent": "primary",
     "target_duration_min": 60, "slots": [], "short_variants": [], "bodyweight_fallback_slots": []},
    # Mobility across phases
    {"objective_kind": "mobility", "phase_kind": "aerobic_base", "intent": "primary",
     "target_duration_min": 20, "slots": [
        {"role": "flow", "role_pattern_pool": ["mobility_flow"],
         "equipment_preference": ["mat", "bodyweight"], "sets": 1, "reps": "15-20 min flow",
         "rest_sec": 0, "rpe_target": "3-4", "key": False, "required": True}],
     "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "mobility", "phase_kind": "build", "intent": "primary",
     "target_duration_min": 20, "slots": [
        {"role": "flow", "role_pattern_pool": ["mobility_flow"],
         "equipment_preference": ["mat", "bodyweight"], "sets": 1, "reps": "15-20 min flow",
         "rest_sec": 0, "rpe_target": "3-4", "key": False, "required": True}],
     "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "mobility", "phase_kind": "specific_prep", "intent": "primary",
     "target_duration_min": 20, "slots": [
        {"role": "flow", "role_pattern_pool": ["mobility_flow"],
         "equipment_preference": ["mat", "bodyweight"], "sets": 1, "reps": "15-20 min flow",
         "rest_sec": 0, "rpe_target": "3-4", "key": False, "required": True}],
     "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "mobility", "phase_kind": "taper", "intent": "primary",
     "target_duration_min": 15, "slots": [
        {"role": "flow", "role_pattern_pool": ["mobility_flow"],
         "equipment_preference": ["mat", "bodyweight"], "sets": 1, "reps": "10-15 min flow",
         "rest_sec": 0, "rpe_target": "3", "key": False, "required": True}],
     "short_variants": [], "bodyweight_fallback_slots": []},
    {"objective_kind": "mobility", "phase_kind": "race_week", "intent": "primary",
     "target_duration_min": 10, "slots": [
        {"role": "flow", "role_pattern_pool": ["mobility_flow"],
         "equipment_preference": ["mat", "bodyweight"], "sets": 1, "reps": "10 min gentle flow",
         "rest_sec": 0, "rpe_target": "2-3", "key": False, "required": True}],
     "short_variants": [], "bodyweight_fallback_slots": []},
    # Strength support in running phases
    {"objective_kind": "strength_support", "phase_kind": "aerobic_base", "intent": "primary",
     "target_duration_min": 30,
     "slots": [
         {"role": "primary_hinge", "role_pattern_pool": ["hinge"],
          "equipment_preference": ["dumbbells", "kettlebell", "bodyweight"],
          "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
         {"role": "primary_squat", "role_pattern_pool": ["squat"],
          "equipment_preference": ["dumbbells", "bodyweight"],
          "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
         {"role": "trunk", "role_pattern_pool": ["anti_extension", "anti_rotate"],
          "equipment_preference": ["bodyweight"],
          "sets": 2, "reps": "30-45s", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
     ],
     "bodyweight_fallback_slots": [
         {"role": "primary_hinge", "role_pattern_pool": ["hinge"], "equipment_preference": ["bodyweight"],
          "sets": 3, "reps": "10-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
         {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["bodyweight"],
          "sets": 3, "reps": "12-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
     ],
     "short_variants": []},
    {"objective_kind": "strength_support", "phase_kind": "build", "intent": "primary",
     "target_duration_min": 35,
     "slots": [
         {"role": "primary_squat", "role_pattern_pool": ["squat"],
          "equipment_preference": ["dumbbells", "barbell", "bodyweight"],
          "sets": 3, "reps": "6-8", "rest_sec": 120, "rpe_target": "8", "key": True, "required": True},
         {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"],
          "equipment_preference": ["dumbbells", "bodyweight"],
          "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
         {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"],
          "equipment_preference": ["dumbbells", "band"],
          "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
     ],
     "bodyweight_fallback_slots": [
         {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["bodyweight"],
          "sets": 3, "reps": "12-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
         {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"], "equipment_preference": ["bodyweight"],
          "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
         {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"], "equipment_preference": ["bodyweight", "band"],
          "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
     ],
     "short_variants": []},
]


def _is_endurance_focus(focus: str) -> bool:
    return focus in {
        "easy_run", "long_run", "tempo_run", "interval_run", "intervals_run",
        "vo2_intervals", "threshold_intervals",
        "race_pace", "marathon_pace",
        "z2_run", "recovery_run",
        "easy_ride", "long_ride", "tempo_ride", "interval_ride",
        "easy_swim", "long_swim",
    }


def _is_running_focus(focus: str) -> bool:
    return focus in {
        "easy_run", "long_run", "tempo_run", "interval_run", "intervals_run",
        "vo2_intervals", "threshold_intervals",
        "race_pace", "marathon_pace",
        "z2_run", "recovery_run",
    }


def _is_mobility_focus(focus: str) -> bool:
    return focus in {"mobility", "mobility_flow", "recovery_mobility", "yoga"}


# ---------------------------------------------------------------------------
# Build implementation
# ---------------------------------------------------------------------------

class BuildImplBody(BaseModel):
    assignment_ids: Optional[list[str]] = None
    draft_id: Optional[str] = None
    programme_id: Optional[str] = None
    include_variants: bool = False   # produce amber/red short variants too


async def _load_context(client_id: str) -> tuple[set[str], set[str]]:
    """Return (equipment_types_avail, movement_regions_to_avoid).

    Reads (in priority):
      - equipment_contexts (scope=permanent) — most recent
      - restrictions collection (source of truth for injuries)
      - falls back to profile fields if collections are empty
      - readiness_states signals.pain_flags
      - active coach directives
    """
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    prof = (user or {}).get("profile") or {}

    # ----- Equipment -----
    equip_perm: set[str] = set()
    # First: permanent equipment_context
    ec = await db.equipment_contexts.find_one(
        {"client_id": client_id, "scope": "permanent"}, {"_id": 0},
        sort=[("created_at", -1)]
    )
    if ec and ec.get("equipment"):
        for e in ec["equipment"]:
            equip_perm.add(str(e).strip().lower())
    # Fallback: profile fields
    if not equip_perm:
        for src_key in ("equipment_permanent", "equipment", "home_equipment"):
            v = prof.get(src_key)
            if not v: continue
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        equip_perm.update((str(e).strip().lower() for e in (item.get("equipment") or [])))
                    elif isinstance(item, str):
                        equip_perm.add(item.strip().lower())
            elif isinstance(v, str):
                equip_perm.add(v.strip().lower())
    # If STILL nothing declared, allow bodyweight + typical hotel-room equipment
    if not equip_perm:
        equip_perm = {"bodyweight", "mat", "band"}
    equip_perm.discard("")

    # ----- Restrictions / avoid movement patterns -----
    avoid: set[str] = set()
    # From restrictions collection (populated by P0-6 sync)
    async for r in db.restrictions.find({"client_id": client_id, "status": "active"}, {"_id": 0}):
        if r.get("region"):
            avoid.add(str(r["region"]).lower())
        for p in (r.get("avoid_patterns") or []):
            avoid.add(str(p).lower())
    # Legacy profile.persistent_restrictions
    for r in prof.get("persistent_restrictions") or []:
        if isinstance(r, dict) and r.get("region"):
            avoid.add(str(r["region"]).lower())
    # Latest readiness pain flags
    rs = await db.readiness_states.find_one({"client_id": client_id}, {"_id": 0}, sort=[("as_of_date", -1)])
    for p in ((rs or {}).get("signals", {}).get("pain_flags") or []):
        avoid.add((p.get("region") or "").lower())
    # Active coach directives — avoid_movement patterns
    try:
        import datetime as _dtm
        from feature_v2_directive_engine import active_directives_for
        dirs = await active_directives_for(client_id, _dtm.date.today())
    except Exception:
        dirs = []
    for d in dirs:
        if d.get("kind") == "avoid_movement":
            patt = ((d.get("parameters") or {}).get("pattern") or "").lower()
            if patt: avoid.add(patt)
            txt = (d.get("free_text") or "").lower()
            if "run" in txt: avoid.add("gait_run_tempo"); avoid.add("gait_run_easy")
            if "knee" in txt: avoid.add("knee")
    return equip_perm, {r for r in avoid if r}


@api.post("/v2/coach/clients/{client_id}/plan/build-implementations")
async def implementations_build(
    client_id: str, body: BuildImplBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id, "status": {"$in": ["proposed", "ready"]}}
    if body.assignment_ids:
        q["id"] = {"$in": body.assignment_ids}
    elif body.programme_id:
        q["programme_id"] = body.programme_id
    elif body.draft_id:
        q["draft_id"] = body.draft_id
    assignments = await db.workout_assignments.find(q, {"_id": 0}).to_list(500)
    if not assignments:
        return {"implementations_created": 0, "note": "no assignments matched"}

    equip_avail, avoid_regions = await _load_context(client_id)
    built = 0
    building_flagged = 0
    for a in assignments:
        obj = await db.training_objectives.find_one({"id": a.get("objective_id")}, {"_id": 0})
        if not obj:
            continue
        phase = await db.programme_phases_v2.find_one({"id": obj.get("phase_id")}, {"_id": 0})
        if not phase:
            continue

        focus = obj["kind"]
        target_min = a.get("planned_duration_min") or 40
        is_running = _is_running_focus(focus)
        is_endurance = _is_endurance_focus(focus)
        is_mobility = _is_mobility_focus(focus)

        # Find matching slot template (may be empty for endurance)
        tmpl = await db.workout_slot_templates.find_one(
            {"objective_kind": focus, "phase_kind": phase["phase_kind"], "intent": "primary"},
            {"_id": 0}
        )
        if not tmpl:
            tmpl = await db.workout_slot_templates.find_one(
                {"objective_kind": focus, "intent": "primary"}, {"_id": 0}
            )
        if not tmpl:
            family_map = {
                "push_strength": "full_body_strength", "pull_strength": "full_body_strength",
                "lower_strength": "full_body_strength", "upper_strength": "full_body_strength",
                "strength_support": "full_body_strength",
                "strength_endurance": "full_body_strength",
            }
            fallback_kind = family_map.get(focus)
            if fallback_kind:
                tmpl = await db.workout_slot_templates.find_one(
                    {"objective_kind": fallback_kind, "intent": "primary"}, {"_id": 0}
                )

        # ----- P1-3: build blocks[] for endurance / mobility focuses -----
        blocks_out: list[dict] = []
        if is_running:
            blocks_out = _build_running_blocks(focus, target_min, phase.get("phase_kind") or "", avoid_regions)
        elif is_endurance:
            blocks_out = _build_cardio_generic_blocks(focus, target_min)
        elif is_mobility:
            blocks_out = _build_mobility_blocks(target_min, avoid_regions)

        # ----- Strength: exercises[] -----
        exercises_out: list[dict] = []
        if tmpl and not (is_running or is_endurance) and not is_mobility:
            gym_ish = equip_avail & {"barbell", "dumbbells", "cable_stack", "machine_chest_press",
                                     "machine_row", "machine_leg_press", "pull_up_bar"}
            slots = tmpl.get("slots") if gym_ish else (tmpl.get("bodyweight_fallback_slots") or tmpl.get("slots"))
            for slot in slots or []:
                ex = await _select_exercise_for_slot(slot, equip_avail, avoid_regions)
                if not ex and slot.get("required"):
                    fb = next((s for s in (tmpl.get("bodyweight_fallback_slots") or []) if s.get("role") == slot.get("role")), None)
                    if fb:
                        ex = await _select_exercise_for_slot(fb, equip_avail, avoid_regions)
                if not ex:
                    continue
                exercises_out.append({
                    "slot_role": slot.get("role"),
                    "exercise_id": ex.get("id"),
                    "exercise_name_display": ex.get("exercise_name") or ex.get("name") or "Exercise",
                    "sets": slot.get("sets"),
                    "reps": slot.get("reps"),
                    "rest_sec": slot.get("rest_sec"),
                    "rpe": slot.get("rpe_target"),
                    "hr_zone": slot.get("hr_zone"),
                    "coaching_cue": "",
                })
        elif tmpl and is_mobility:
            # mobility templates may still have a flow slot — record it as an exercise row
            for slot in tmpl.get("slots") or []:
                exercises_out.append({
                    "slot_role": slot.get("role"),
                    "exercise_id": None,
                    "exercise_name_display": "Mobility flow",
                    "sets": slot.get("sets"),
                    "reps": slot.get("reps"),
                    "rest_sec": slot.get("rest_sec"),
                    "rpe": slot.get("rpe_target"),
                    "hr_zone": None,
                    "coaching_cue": "Breath-led, low intensity.",
                })

        # ----- P0-2 gating: need SOMETHING to ship -----
        has_content = bool(exercises_out) or bool(blocks_out)
        wid = new_id()
        impl_doc = {
            "id": wid,
            "assignment_id": a["id"],
            "client_id": client_id,
            "date": a["date"],
            "variant_of_id": None, "variant_type": "green",
            "equipment_context": {"equipment": list(equip_avail)},
            "duration_min": target_min or (tmpl.get("target_duration_min") if tmpl else 40),
            "title": f"{focus.replace('_', ' ').title()}",
            "location_label": "",
            "focus": focus,
            "warmup": [{"name": "Movement prep", "duration_sec": 300}] if not blocks_out else [],
            "exercises": exercises_out,
            "blocks": blocks_out,
            "cooldown": [{"name": "Cooldown & mobility", "duration_sec": 180}] if not blocks_out else [],
            "rationale": f"{(phase.get('phase_kind') or 'phase').title()} phase · {obj['importance']} session · from the plan Louis built for you.",
            "key_session": (obj.get("importance") == "key"),
            "source": "template_v2",
            "needs_coach_review": not has_content,
            "built_at": now_iso(),
            "cache_key": f"{focus}::{phase.get('phase_kind')}::{','.join(sorted(equip_avail))}",
        }
        await db.workout_implementations.insert_one(dict(impl_doc))

        if has_content:
            # Assignment reaches "ready" only when implementation has content
            await db.workout_assignments.update_one(
                {"id": a["id"]},
                {"$set": {"draft_implementation_id": wid, "status": "ready", "updated_at": now_iso()}}
            )
            await db.objective_exposures.update_one(
                {"assignment_id": a["id"]},
                {"$set": {"implementation_id": wid, "updated_at": now_iso()}}
            )
            content_type = "blocks" if blocks_out else "exercises"
            content_count = len(blocks_out) if blocks_out else len(exercises_out)
            await write_decision(
                actor="system", layer="HOW", scope_kind="workout_implementation",
                scope_id=wid, client_id=client_id, outcome="READY",
                reason=f"Built {focus} implementation ({content_count} {content_type}) from slot template",
            )
            await emit_metric("workout_built", client_id=client_id, numeric_value=1,
                              labels={"objective_kind": focus, "phase_kind": phase.get("phase_kind")})
            built += 1
        else:
            # P0-2 + P1-4: leave status=building AND surface a coach-review exception
            await db.workout_assignments.update_one(
                {"id": a["id"]},
                {"$set": {"draft_implementation_id": wid, "status": "building",
                          "needs_coach_review": True, "updated_at": now_iso()}}
            )
            await db.objective_exposures.update_one(
                {"assignment_id": a["id"]},
                {"$set": {"implementation_id": wid, "updated_at": now_iso()}}
            )
            await write_decision(
                actor="system", layer="HOW", scope_kind="workout_implementation",
                scope_id=wid, client_id=client_id, outcome="BLOCKED",
                reason=(
                    f"Could not build content for {focus} (phase={phase.get('phase_kind')}). "
                    "No slot template resolved AND no endurance/mobility builder matched. "
                    "Assignment left at status='building' for coach review."
                ),
            )
            # Emit an exception so it appears in the coach's Needs-Review tray
            try:
                await db.exceptions.insert_one({
                    "id": new_id(),
                    "client_id": client_id,
                    "draft_id": a.get("draft_id"),
                    "kind": "impl_build_failed", "severity": "warning",
                    "scope_ref": a["id"],
                    "triggered_at": now_iso(),
                    "human_readable_reason": (
                        f"Could not auto-build {focus} session on {a['date']}. "
                        "Coach needs to review — no template matched."
                    ),
                    "status": "open",
                    "proposed_resolutions": [
                        {"action": "swap_to_similar_kind"},
                        {"action": "manual_edit"},
                        {"action": "skip"},
                    ],
                })
            except Exception:
                pass
            building_flagged += 1

    return {
        "implementations_created": built,
        "implementations_needing_review": building_flagged,
    }


@api.get("/v2/coach/clients/{client_id}/plan/implementations/{assignment_id}")
async def implementation_get(
    client_id: str, assignment_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    row = await db.workout_implementations.find_one(
        {"assignment_id": assignment_id, "client_id": client_id}, {"_id": 0}
    )
    if not row:
        raise HTTPException(404, "No implementation for this assignment")
    return row


@api.get("/v2/catalog/slot-templates")
async def catalog_slot_templates(coach: dict = Depends(require_role("coach"))) -> dict:
    rows = await db.workout_slot_templates.find({}, {"_id": 0}).sort("objective_kind", 1).to_list(200)
    return {"slot_templates": rows}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("workout_implementations", [
        ([("assignment_id", 1)], False, "impl_assign"),
        ([("client_id", 1), ("date", 1)], False, "impl_client_date"),
    ])
    await ensure_indexes("workout_slot_templates", [
        ([("objective_kind", 1), ("phase_kind", 1), ("intent", 1)], False, "slot_tmpl_key"),
    ])
    await seed_slot_templates_once()


bg(_bootstrap())


logger.info("feature_v2_p6_construction: /api/v2 implementations + slot templates registered")
