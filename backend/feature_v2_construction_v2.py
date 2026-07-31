"""
CrewFit V2 Engine V2 — Session Construction (HOW)
==================================================

Converts a scheduled Placement into a sport-typed SessionSpec. Every session
kind has its own spec shape — no more generic "exercises[]" for running.

Public API:

    build_session_spec(placement, phase_kind, equipment_ctx, restrictions,
                       day_ctx)  →  SessionSpec  or  None if unbuildable

SessionSpec is discriminated by `spec_kind`:
    "running"          — warmup / main{type,distance,pace,hr_zone,intervals[]}
                         / cooldown
    "strength"         — exercises[{name, sets, reps, load_target, rest_sec,
                                    equipment_used, subs_allowed}], equipment
    "mobility"         — flow_blocks[{name, duration_sec}]
    "recovery"         — flow_blocks + notes
    "travel_recovery"  — activation cues, no equipment required
    "rest"             — {} — nothing to build
    "cycling"          — analogous to running
    "swimming"         — swim sets
    "brick"            — bike segment + run segment
    "activation"       — 6-10 min primer

Every session has an `environment` field:
    running:  "outdoor" | "treadmill" | "auto"
    cycling:  "outdoor" | "indoor_trainer" | "auto"
    swim:     "pool" | "open_water" | "auto"
    strength: "gym" | "home" | "hotel_room" | "bodyweight_only" | "auto"

Equipment labels shown to the coach ONLY match the true modality — a running
session never shows "bodyweight, dumbbells" as its equipment context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from feature_v2_sport_configs import (
    session_kind_meta, session_family,
    MODALITY_RUN, MODALITY_CYCLE, MODALITY_SWIM, MODALITY_STRENGTH,
    MODALITY_MOBILITY, MODALITY_RECOVERY, MODALITY_ACTIVATION, MODALITY_BRICK,
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class SessionSpec:
    spec_kind: str                                  # "running" | "strength" | ...
    kind: str                                       # canonical session kind
    duration_min: int                               # actual prescribed duration
    intensity_target: str                           # copied from placement
    environment: str                                # "outdoor" | "treadmill" | ...
    equipment_used: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)   # kind-specific
    rationale: str = ""
    coach_review_required: bool = False
    review_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "spec_kind": self.spec_kind,
            "kind": self.kind,
            "duration_min": self.duration_min,
            "intensity_target": self.intensity_target,
            "environment": self.environment,
            "equipment_used": list(self.equipment_used),
            "payload": self.payload,
            "rationale": self.rationale,
            "coach_review_required": self.coach_review_required,
            "review_reason": self.review_reason,
        }


# ---------------------------------------------------------------------------
# Environment selection
# ---------------------------------------------------------------------------

def _pick_running_environment(day_type: str, equipment_ctx: set[str]) -> str:
    # Iter 118 — travel-safe default. On layover/hotel/turnaround days we
    # NEVER assume the client's permanent treadmill is available. Only a
    # temporary equipment override (merged into equipment_ctx by the caller)
    # can upgrade to treadmill.
    if day_type in ("layover_arrival", "layover_departure", "turnaround",
                     "layover", "hotel", "layover_full"):
        return "flexible"          # client picks outdoor / treadmill later
    if "treadmill" in equipment_ctx and day_type in ("standby", "duty"):
        return "treadmill"
    return "outdoor"


def _pick_cycling_environment(day_type: str, equipment_ctx: set[str]) -> str:
    if "indoor_trainer" in equipment_ctx or "smart_trainer" in equipment_ctx:
        if day_type in ("layover_arrival", "layover_departure", "turnaround",
                          "layover", "hotel"):
            return "indoor_trainer"
    return "outdoor"


def _pick_swim_environment(day_type: str, equipment_ctx: set[str]) -> str:
    if "pool" in equipment_ctx:
        return "pool"
    if day_type in ("layover_arrival", "layover_departure", "layover_full",
                     "layover", "hotel"):
        return "pool"  # hotel pool is the assumption; coach can confirm
    return "pool"


def _pick_strength_environment(day_type: str, equipment_ctx: set[str]) -> str:
    # Iter 118 — travel-safe default. Layover days are NEVER assumed to have
    # the client's home equipment available. Only a *temporary* equipment
    # context (this_session / today / this_layover) can upgrade the layover
    # session to a gym implementation. Permanent DNA equipment is ignored
    # on layover / hotel days.
    if day_type in ("layover_arrival", "layover_departure", "turnaround",
                     "layover", "hotel", "layover_full"):
        # A caller may have merged a temporary override into equipment_ctx
        # before calling us. If we can see gym-grade items, allow gym.
        if "barbell" in equipment_ctx and "rack" in equipment_ctx:
            return "gym"
        if equipment_ctx & {"dumbbells", "kettlebell", "cable_stack", "bench"}:
            return "hotel_gym"
        return "hotel_room"
    if "barbell" in equipment_ctx and "rack" in equipment_ctx:
        return "gym"
    if equipment_ctx & {"dumbbells", "kettlebell", "cable_stack"}:
        return "home"
    return "bodyweight_only"


# ---------------------------------------------------------------------------
# Running builders
# ---------------------------------------------------------------------------

def _running_easy(duration_min: int) -> dict:
    wu = max(5, int(duration_min * 0.12))
    cd = max(5, int(duration_min * 0.08))
    steady = max(10, duration_min - wu - cd)
    return {
        "warmup": {"duration_min": wu, "hr_zone": "z1",
                   "cue": "Walk into easy jog. Loose ankles, tall posture."},
        "main":   {"type": "steady",
                   "duration_min": steady, "hr_zone": "z2",
                   "pace_target": "conversational",
                   "cue": "Nasal breathing, chat-pace. No pushing."},
        "cooldown": {"duration_min": cd, "hr_zone": "z1",
                     "cue": "Walk-out. Light stretch — hips + calves."},
    }


def _running_long(duration_min: int, phase_kind: str) -> dict:
    wu = 10
    cd = 5
    steady = max(30, duration_min - wu - cd)
    pace = ("MP+60s" if phase_kind in ("specific_prep", "taper", "race_week")
            else "MP+90s")
    return {
        "warmup": {"duration_min": wu, "hr_zone": "z1",
                   "cue": "Walk 2 min. 8 min easy jog. Progressive."},
        "main":   {"type": "long_steady",
                   "duration_min": steady, "hr_zone": "z2",
                   "pace_target": pace,
                   "fuel_cue": "Fuel every 30-40 min if >75 min.",
                   "cue": "Aerobic base. Stay relaxed."},
        "cooldown": {"duration_min": cd, "hr_zone": "z1",
                     "cue": "5 min walk. Stretch quads + calves."},
    }


def _running_tempo(duration_min: int) -> dict:
    wu = 10
    cd = 5
    tempo = max(15, duration_min - wu - cd)
    return {
        "warmup": {"duration_min": wu, "hr_zone": "z1-z2",
                   "cue": "Easy jog. Include 4 x 20s strides."},
        "main":   {"type": "tempo",
                   "duration_min": tempo, "hr_zone": "z4",
                   "pace_target": "10K–HM pace",
                   "cue": "Comfortably-hard. Sustained. Breath 3:3."},
        "cooldown": {"duration_min": cd, "hr_zone": "z1",
                     "cue": "5 min easy jog into walk."},
    }


def _running_intervals(duration_min: int) -> dict:
    wu = 10
    cd = 5
    work_avail = max(15, duration_min - wu - cd)
    reps = min(6, max(3, work_avail // 5))
    return {
        "warmup": {"duration_min": wu, "hr_zone": "z1-z2",
                   "cue": "Progressive jog. 4 x 20s strides."},
        "main":   {"type": "intervals",
                   "reps": reps, "work_sec": 180, "rest_sec": 90,
                   "duration_min": reps * (3 + 1.5),
                   "hr_zone": "z4-z5",
                   "pace_target": "5K–10K pace",
                   "cue": f"{reps} × 3 min hard / 90s easy jog."},
        "cooldown": {"duration_min": cd, "hr_zone": "z1",
                     "cue": "5 min slow jog into walk."},
    }


def _running_race_pace(duration_min: int, is_marathon: bool) -> dict:
    wu = 10
    cd = 5
    mp = max(20, duration_min - wu - cd)
    pace_target = "goal marathon pace" if is_marathon else "goal race pace"
    return {
        "warmup": {"duration_min": wu, "hr_zone": "z2",
                   "cue": "Progressive to race pace. 4 x 20s strides."},
        "main":   {"type": "race_pace",
                   "duration_min": mp, "hr_zone": "z3-z4",
                   "pace_target": pace_target,
                   "cue": "Lock in target. Practise fuelling + rhythm."},
        "cooldown": {"duration_min": cd, "hr_zone": "z1",
                     "cue": "5 min easy jog. Stretch."},
    }


def _running_strides(duration_min: int) -> dict:
    return {
        "warmup": {"duration_min": 5, "hr_zone": "z1", "cue": "Easy jog."},
        "main":   {"type": "strides",
                   "duration_min": max(10, duration_min - 10),
                   "reps": 6, "work_sec": 20, "rest_sec": 60,
                   "hr_zone": "neuromuscular",
                   "cue": "Fast but relaxed. Not a sprint."},
        "cooldown": {"duration_min": 5, "hr_zone": "z1", "cue": "Slow jog."},
    }


def _running_recovery(duration_min: int) -> dict:
    return {
        "warmup": {"duration_min": 5, "hr_zone": "z1", "cue": "Slow walk-jog."},
        "main":   {"type": "recovery",
                   "duration_min": max(15, duration_min - 10),
                   "hr_zone": "z1",
                   "pace_target": "very easy — 60-80% of usual easy pace",
                   "cue": "Purely aerobic. Restorative."},
        "cooldown": {"duration_min": 5, "hr_zone": "z1", "cue": "Walk."},
    }


RUNNING_BUILDERS: dict[str, Any] = {
    "run_easy":         lambda dur, ph: _running_easy(dur),
    "run_recovery":     lambda dur, ph: _running_recovery(dur),
    "run_long":         lambda dur, ph: _running_long(dur, ph),
    "run_tempo":        lambda dur, ph: _running_tempo(dur),
    "run_threshold":    lambda dur, ph: _running_tempo(dur),
    "run_intervals":    lambda dur, ph: _running_intervals(dur),
    "run_vo2":          lambda dur, ph: _running_intervals(dur),
    "run_marathon_pace":lambda dur, ph: _running_race_pace(dur, True),
    "run_race_pace":    lambda dur, ph: _running_race_pace(dur, False),
    "run_strides":      lambda dur, ph: _running_strides(dur),
    # Iter 121 — General Fitness / Fat Loss aerobic Z2 (cardio-modality-agnostic).
    # By default outputs a run; construction may swap for bike/walk based on
    # client_profile.cardio_preference.
    "aerobic_z2":       lambda dur, ph: _running_easy(dur),
    "walk_z2":          lambda dur, ph: _running_easy(dur),
}


# Iter 121 — Iter121 walk / conditioning builders

def _walking_z2(duration_min: int) -> dict:
    """Structured brisk walking session — a legitimate aerobic exposure for
    General Fitness / Fat Loss clients who do not want to run."""
    wu = max(3, int(duration_min * 0.10))
    cd = max(3, int(duration_min * 0.08))
    steady = max(10, duration_min - wu - cd)
    return {
        "warmup": {"duration_min": wu, "hr_zone": "z1",
                   "cue": "Easy walk. Loose ankles + shoulders."},
        "main":   {"type": "brisk_walk", "duration_min": steady,
                   "hr_zone": "z2", "pace_target": "brisk / conversational",
                   "cue": "Purposeful pace. Tall posture, arms swinging."},
        "cooldown": {"duration_min": cd, "hr_zone": "z1",
                     "cue": "Slow walk. Deep breathing."},
    }


def _conditioning_mixed_circuit(duration_min: int) -> dict:
    """Deterministic mixed conditioning circuit. Bodyweight-safe by default;
    scales up with dumbbells / kettlebell if available. Not a punishment
    workout — moderate density, 3–4 short circuits."""
    wu = 5
    cd = 4
    work = max(12, duration_min - wu - cd)
    rounds = 3 if work < 20 else 4
    return {
        "warmup": {"duration_min": wu,
                   "cue": "Dynamic mobility + light cardio.",
                   "drills": [
                       {"name": "Leg swings", "duration_sec": 30},
                       {"name": "World's greatest stretch", "duration_sec": 45},
                       {"name": "Jumping jacks", "duration_sec": 30},
                   ]},
        "main": {"type": "circuit",
                 "duration_min": work,
                 "rounds": rounds,
                 "rest_between_rounds_sec": 60,
                 "stations": [
                     {"name": "Goblet Squat or Bodyweight Squat", "duration_sec": 40},
                     {"name": "Push-up (kneeling ok)", "duration_sec": 30},
                     {"name": "Kettlebell Swing or Hip Hinge Reach", "duration_sec": 30},
                     {"name": "Alternating Reverse Lunge", "duration_sec": 40},
                     {"name": "Plank Hold", "duration_sec": 30},
                 ],
                 "cue": "Moderate effort. Aim RPE 6-7. Not maximal."},
        "cooldown": {"duration_min": cd,
                     "cue": "Slow walk + easy breathing. Down-regulate."},
    }


def _conditioning_intervals(duration_min: int) -> dict:
    """Short interval conditioning — bodyweight or kettlebell friendly."""
    wu = 6
    cd = 5
    work = max(10, duration_min - wu - cd)
    return {
        "warmup": {"duration_min": wu, "cue": "Progressive movement prep + 2 easy rounds."},
        "main": {"type": "intervals",
                 "duration_min": work,
                 "reps": 8, "work_sec": 40, "rest_sec": 20,
                 "cue": "8 × 40s work / 20s rest. Alternate lower & upper stations.",
                 "stations": [
                     {"name": "Kettlebell Swing or Squat Jump"},
                     {"name": "Push-up or Renegade Row"},
                 ]},
        "cooldown": {"duration_min": cd, "cue": "Walk + slow breathing."},
    }


# ---------------------------------------------------------------------------
# Cycling builders (analogous)
# ---------------------------------------------------------------------------

def _cycling_easy(dur: int) -> dict:
    return {"warmup": {"duration_min": 5, "hr_zone": "z1", "cue": "Spin up."},
            "main":   {"type": "steady", "duration_min": max(15, dur-10),
                       "hr_zone": "z1-z2", "cadence": "85-95 rpm",
                       "cue": "Chat-pace spin."},
            "cooldown": {"duration_min": 5, "hr_zone": "z1", "cue": "Easy spin."}}


def _cycling_endurance(dur: int) -> dict:
    return {"warmup": {"duration_min": 10, "hr_zone": "z1-z2", "cue": "Progressive."},
            "main":   {"type": "endurance", "duration_min": max(30, dur-15),
                       "hr_zone": "z2", "cadence": "85-95 rpm",
                       "cue": "Aerobic base. Steady power."},
            "cooldown": {"duration_min": 5, "hr_zone": "z1", "cue": "Spin down."}}


def _cycling_long(dur: int) -> dict:
    return {"warmup": {"duration_min": 15, "hr_zone": "z1-z2", "cue": "Ease into it."},
            "main":   {"type": "long", "duration_min": max(60, dur-20),
                       "hr_zone": "z2", "cadence": "85-95 rpm",
                       "fuel_cue": "60g carbs/h after 90 min.",
                       "cue": "Sustained aerobic. Fuel + hydrate."},
            "cooldown": {"duration_min": 5, "hr_zone": "z1", "cue": "Spin down."}}


def _cycling_tempo(dur: int) -> dict:
    wu = 10; cd = 5
    return {"warmup": {"duration_min": wu, "hr_zone": "z2", "cue": "Progressive."},
            "main":   {"type": "tempo", "duration_min": max(15, dur-wu-cd),
                       "hr_zone": "z3-z4", "power_target": "88-92% FTP",
                       "cue": "Sustained sub-threshold effort."},
            "cooldown": {"duration_min": cd, "hr_zone": "z1", "cue": "Easy spin."}}


def _cycling_threshold(dur: int) -> dict:
    wu = 10; cd = 5
    work_min = max(20, dur - wu - cd)
    return {"warmup": {"duration_min": wu, "hr_zone": "z2", "cue": "Progressive + 3x30s openers."},
            "main":   {"type": "threshold",
                       "duration_min": work_min,
                       "hr_zone": "z4", "power_target": "95-105% FTP",
                       "reps": 2 if work_min > 30 else 1,
                       "cue": "Sustainable, hard. Race-effort economy."},
            "cooldown": {"duration_min": cd, "hr_zone": "z1", "cue": "Spin down."}}


def _cycling_intervals(dur: int) -> dict:
    wu = 10; cd = 5
    return {"warmup": {"duration_min": wu, "hr_zone": "z2", "cue": "3x30s openers included."},
            "main":   {"type": "intervals",
                       "reps": 5, "work_sec": 180, "rest_sec": 180,
                       "duration_min": 30,
                       "hr_zone": "z5", "power_target": "115-125% FTP",
                       "cue": "5 x 3 min VO2 / 3 min easy."},
            "cooldown": {"duration_min": cd, "hr_zone": "z1", "cue": "Spin down."}}


CYCLING_BUILDERS: dict[str, Any] = {
    "bike_easy":       lambda dur, ph: _cycling_easy(dur),
    "bike_recovery":   lambda dur, ph: _cycling_easy(dur),
    "bike_endurance":  lambda dur, ph: _cycling_endurance(dur),
    "bike_long":       lambda dur, ph: _cycling_long(dur),
    "bike_tempo":      lambda dur, ph: _cycling_tempo(dur),
    "bike_threshold":  lambda dur, ph: _cycling_threshold(dur),
    "bike_intervals":  lambda dur, ph: _cycling_intervals(dur),
}


# ---------------------------------------------------------------------------
# Swimming builders
# ---------------------------------------------------------------------------

def _swim_technique(dur: int) -> dict:
    return {"warmup": {"duration_min": 5, "cue": "200m easy + drills."},
            "main":   {"type": "technique",
                       "duration_min": max(15, dur - 10),
                       "sets": ["4 x 50 catch-up drill / 20s rest",
                                "4 x 50 fingertip-drag / 20s rest",
                                "4 x 50 3-3-3 drill / 20s rest",
                                "300 easy free — smooth stroke"],
                       "cue": "Focus: catch + rotation."},
            "cooldown": {"duration_min": 5, "cue": "200m easy free/backstroke."}}


def _swim_aerobic(dur: int) -> dict:
    return {"warmup": {"duration_min": 5, "cue": "200m easy + 4x50 build."},
            "main":   {"type": "aerobic",
                       "duration_min": max(20, dur - 10),
                       "sets": ["10 x 100 free / 15s rest — steady effort"],
                       "cue": "Aerobic. Consistent 1500m pace + 10s."},
            "cooldown": {"duration_min": 5, "cue": "200m mix — easy."}}


def _swim_endurance(dur: int) -> dict:
    return {"warmup": {"duration_min": 5, "cue": "300m easy."},
            "main":   {"type": "endurance",
                       "duration_min": max(30, dur - 10),
                       "sets": ["1500-2500m continuous steady free"],
                       "cue": "Race-pace + 10s / 100. Long, smooth."},
            "cooldown": {"duration_min": 5, "cue": "200m easy."}}


def _swim_threshold(dur: int) -> dict:
    return {"warmup": {"duration_min": 5, "cue": "300m easy + 4x50 build."},
            "main":   {"type": "threshold",
                       "duration_min": max(20, dur - 10),
                       "sets": ["6 x 200 free @ CSS / 20s rest",
                                "OR 12 x 100 @ CSS / 15s rest"],
                       "cue": "Threshold pace (~1500 TT pace)."},
            "cooldown": {"duration_min": 5, "cue": "200m easy."}}


def _swim_intervals(dur: int) -> dict:
    return {"warmup": {"duration_min": 5, "cue": "300m easy + 6x25 build."},
            "main":   {"type": "intervals",
                       "duration_min": max(20, dur - 10),
                       "sets": ["10 x 50 @ 400 pace / 20s rest",
                                "6 x 100 @ 200 pace / 40s rest"],
                       "cue": "VO2 effort. Fast turnover."},
            "cooldown": {"duration_min": 5, "cue": "200m easy."}}


SWIM_BUILDERS: dict[str, Any] = {
    "swim_technique":  lambda dur, ph: _swim_technique(dur),
    "swim_aerobic":    lambda dur, ph: _swim_aerobic(dur),
    "swim_endurance":  lambda dur, ph: _swim_endurance(dur),
    "swim_threshold":  lambda dur, ph: _swim_threshold(dur),
    "swim_intervals":  lambda dur, ph: _swim_intervals(dur),
    "swim_recovery":   lambda dur, ph: _swim_aerobic(dur),
    "swim_open_water": lambda dur, ph: _swim_endurance(dur),
}


# ---------------------------------------------------------------------------
# Strength builder — sport-typed with exercise substitution
# ---------------------------------------------------------------------------

# Movement pattern → exercise pool with equipment tags
_STRENGTH_POOL: dict[str, list[dict]] = {
    "squat":    [
        {"name": "Back Squat", "equipment": ["barbell", "rack"]},
        {"name": "Front Squat", "equipment": ["barbell", "rack"]},
        {"name": "Goblet Squat", "equipment": ["dumbbells"]},
        {"name": "Kettlebell Goblet Squat", "equipment": ["kettlebell"]},
        {"name": "Split Squat", "equipment": ["dumbbells"]},
        {"name": "Bulgarian Split Squat", "equipment": ["dumbbells"]},
        {"name": "Bodyweight Squat 3-sec eccentric", "equipment": ["bodyweight"]},
    ],
    "hinge":    [
        {"name": "Barbell Deadlift", "equipment": ["barbell"]},
        {"name": "Romanian Deadlift", "equipment": ["barbell"]},
        {"name": "Dumbbell RDL", "equipment": ["dumbbells"]},
        {"name": "Kettlebell Swing", "equipment": ["kettlebell"]},
        {"name": "Single-leg RDL", "equipment": ["dumbbells"]},
        {"name": "Glute Bridge Hold", "equipment": ["bodyweight"]},
    ],
    "horizontal_push": [
        {"name": "Bench Press", "equipment": ["barbell", "rack", "bench"]},
        {"name": "Dumbbell Bench Press", "equipment": ["dumbbells", "bench"]},
        {"name": "Push-up", "equipment": ["bodyweight"]},
        {"name": "Push-up (feet elevated)", "equipment": ["bodyweight"]},
        {"name": "Ring Push-up", "equipment": ["rings"]},
    ],
    "vertical_push": [
        {"name": "Overhead Press", "equipment": ["barbell", "rack"]},
        {"name": "Dumbbell Shoulder Press", "equipment": ["dumbbells"]},
        {"name": "Pike Push-up", "equipment": ["bodyweight"]},
    ],
    "horizontal_pull": [
        {"name": "Bent-over Row", "equipment": ["barbell"]},
        {"name": "Dumbbell Row", "equipment": ["dumbbells"]},
        {"name": "Cable Row", "equipment": ["cable_stack"]},
        {"name": "Inverted Row", "equipment": ["bodyweight", "bar"]},
        {"name": "Band Row", "equipment": ["band"]},
        # Iter 119 — pure bodyweight fallback so hotel-room / bodyweight-only
        # sessions can still hit a pulling pattern (no bar required).
        {"name": "Prone Y-T-W Row (bodyweight)", "equipment": ["bodyweight"]},
    ],
    "vertical_pull": [
        {"name": "Pull-up", "equipment": ["pull_up_bar"]},
        {"name": "Chin-up", "equipment": ["pull_up_bar"]},
        {"name": "Lat Pulldown", "equipment": ["cable_stack"]},
        {"name": "Band Pulldown", "equipment": ["band"]},
    ],
    "trunk":    [
        {"name": "Plank", "equipment": ["bodyweight"]},
        {"name": "Side Plank", "equipment": ["bodyweight"]},
        {"name": "Dead Bug", "equipment": ["bodyweight"]},
        {"name": "Hollow Hold", "equipment": ["bodyweight"]},
        {"name": "Suitcase Carry", "equipment": ["dumbbells"]},
    ],
    "power":   [
        {"name": "Trap-bar Jump", "equipment": ["barbell"]},
        {"name": "Kettlebell Swing (hard)", "equipment": ["kettlebell"]},
        {"name": "Broad Jump", "equipment": ["bodyweight"]},
        {"name": "Box Jump", "equipment": ["box"]},
    ],
}


# Composition templates per strength focus
_STRENGTH_TEMPLATES: dict[str, list[dict]] = {
    "strength_full_body": [
        {"role": "primary_squat",         "pattern": "squat",           "sets": 3, "reps": "6-8",  "rest_sec": 120, "rpe": "8"},
        {"role": "primary_hinge",         "pattern": "hinge",           "sets": 3, "reps": "6-8",  "rest_sec": 120, "rpe": "8"},
        {"role": "primary_horizontal_push","pattern": "horizontal_push","sets": 3, "reps": "8-10", "rest_sec": 90,  "rpe": "7"},
        {"role": "primary_horizontal_pull","pattern": "horizontal_pull","sets": 3, "reps": "8-10", "rest_sec": 90,  "rpe": "7"},
        {"role": "trunk",                 "pattern": "trunk",           "sets": 2, "reps": "30-45s","rest_sec": 45, "rpe": "6"},
    ],
    "strength_upper": [
        {"role": "primary_horizontal_push","pattern": "horizontal_push","sets": 4, "reps": "6-8",  "rest_sec": 120, "rpe": "8"},
        {"role": "primary_vertical_pull",  "pattern": "vertical_pull",  "sets": 4, "reps": "6-8",  "rest_sec": 120, "rpe": "8"},
        {"role": "primary_vertical_push",  "pattern": "vertical_push",  "sets": 3, "reps": "8-10", "rest_sec": 90,  "rpe": "7"},
        {"role": "primary_horizontal_pull","pattern": "horizontal_pull","sets": 3, "reps": "8-10", "rest_sec": 90,  "rpe": "7"},
        {"role": "trunk",                  "pattern": "trunk",          "sets": 2, "reps": "30-45s","rest_sec": 45, "rpe": "6"},
    ],
    "strength_lower": [
        {"role": "primary_squat",         "pattern": "squat",           "sets": 4, "reps": "5-6",  "rest_sec": 150, "rpe": "8"},
        {"role": "primary_hinge",         "pattern": "hinge",           "sets": 4, "reps": "5-6",  "rest_sec": 150, "rpe": "8"},
        {"role": "single_leg",            "pattern": "squat",           "sets": 3, "reps": "8/side","rest_sec": 90, "rpe": "7"},
        {"role": "trunk",                 "pattern": "trunk",           "sets": 2, "reps": "30-45s","rest_sec": 45, "rpe": "6"},
    ],
    "strength_push": [
        {"role": "primary_horizontal_push","pattern": "horizontal_push","sets": 4, "reps": "6-8",  "rest_sec": 120, "rpe": "8"},
        {"role": "primary_vertical_push",  "pattern": "vertical_push",  "sets": 4, "reps": "8-10", "rest_sec": 90,  "rpe": "7"},
        {"role": "accessory_horizontal_push","pattern": "horizontal_push","sets": 3, "reps": "10-12","rest_sec": 75,"rpe": "7"},
        {"role": "trunk",                  "pattern": "trunk",          "sets": 2, "reps": "30-45s","rest_sec": 45,"rpe": "6"},
    ],
    "strength_pull": [
        {"role": "primary_vertical_pull",  "pattern": "vertical_pull",  "sets": 4, "reps": "6-8",  "rest_sec": 120, "rpe": "8"},
        {"role": "primary_horizontal_pull","pattern": "horizontal_pull","sets": 4, "reps": "8-10", "rest_sec": 90,  "rpe": "7"},
        {"role": "accessory_pull",         "pattern": "horizontal_pull","sets": 3, "reps": "10-12","rest_sec": 75, "rpe": "7"},
        {"role": "trunk",                  "pattern": "trunk",          "sets": 2, "reps": "30-45s","rest_sec": 45, "rpe": "6"},
    ],
    "strength_maintenance": [
        {"role": "squat",                 "pattern": "squat",           "sets": 2, "reps": "8-10", "rest_sec": 90,  "rpe": "6"},
        {"role": "hinge",                 "pattern": "hinge",           "sets": 2, "reps": "8-10", "rest_sec": 90,  "rpe": "6"},
        {"role": "push",                  "pattern": "horizontal_push", "sets": 2, "reps": "10-12","rest_sec": 75, "rpe": "6"},
        {"role": "pull",                  "pattern": "horizontal_pull", "sets": 2, "reps": "10-12","rest_sec": 75, "rpe": "6"},
    ],
    "strength_power": [
        {"role": "power",                 "pattern": "power",           "sets": 4, "reps": "3-5",  "rest_sec": 180, "rpe": "9"},
        {"role": "primary_squat",         "pattern": "squat",           "sets": 3, "reps": "5-6",  "rest_sec": 150, "rpe": "8"},
        {"role": "primary_hinge",         "pattern": "hinge",           "sets": 3, "reps": "5-6",  "rest_sec": 150, "rpe": "8"},
    ],
    "strength_hypertrophy": [
        {"role": "compound",              "pattern": "horizontal_push", "sets": 4, "reps": "8-12", "rest_sec": 90,  "rpe": "8"},
        {"role": "compound",              "pattern": "horizontal_pull", "sets": 4, "reps": "8-12", "rest_sec": 90,  "rpe": "8"},
        {"role": "accessory",             "pattern": "squat",           "sets": 3, "reps": "10-12","rest_sec": 75, "rpe": "7"},
        {"role": "accessory",             "pattern": "hinge",           "sets": 3, "reps": "10-12","rest_sec": 75, "rpe": "7"},
        {"role": "trunk",                 "pattern": "trunk",           "sets": 3, "reps": "30-45s","rest_sec": 45, "rpe": "7"},
    ],
    "strength_support": [
        {"role": "squat",                 "pattern": "squat",           "sets": 2, "reps": "10-12", "rest_sec": 75, "rpe": "6"},
        {"role": "hinge",                 "pattern": "hinge",           "sets": 2, "reps": "10-12", "rest_sec": 75, "rpe": "6"},
        {"role": "trunk",                 "pattern": "trunk",           "sets": 2, "reps": "30-45s","rest_sec": 45,"rpe": "6"},
    ],
}


def _pick_exercise(pattern: str, equipment_ctx: set[str], avoid: set[str]) -> Optional[dict]:
    pool = _STRENGTH_POOL.get(pattern) or []
    # Filter by equipment (all equipment tags must be available)
    for ex in pool:
        eq = set(ex["equipment"])
        if not eq.issubset(equipment_ctx):
            continue
        # Filter by avoid patterns
        name_lower = ex["name"].lower()
        blocked = False
        for a in avoid:
            a = a.lower()
            if a in name_lower or a == pattern:
                blocked = True
                break
        if not blocked:
            return ex
    # Absolute fallback — prefer STRICT bodyweight-only substitutes first
    # (Iter 119 — the loose "'bodyweight' in equipment" check used to leak
    # exercises like Inverted Row that also require a bar, which is not
    # available in a true bodyweight-only setup).
    for ex in pool:
        if set(ex["equipment"]) <= {"bodyweight"}:
            return ex
    # Last-ditch fallback — anything that lists bodyweight at all
    for ex in pool:
        if "bodyweight" in ex["equipment"]:
            return ex
    return None


def _build_strength(kind: str, dur: int, equipment_ctx: set[str],
                    avoid: set[str],
                    exposure_number: int = 1,
                    variety_preference: str = "moderate",
                    training_experience: Optional[str] = None,
                    locked_exercises: Optional[dict[str, str]] = None,
                    session_slot: int = 0,
                    week_index: int = 0,
                    ) -> tuple[list[dict], list[str]]:
    """Iter 121b + Iter 130g — block-based anchor rotation + Session A/B/C
    pattern remap.

    - Anchor slot primaries stay stable within a "block" (4/6/12 exposures
      by variety level) and refresh at block boundaries — measurable
      progression + genuine variety.
    - For strength_full_body, `session_slot` cycles A/B/C so consecutive
      full-body sessions in the same week hit different push/pull axes AND
      different anchor exercises.
    - Beginners are clamped to at-most MODERATE.
    - `week_index` drives a conservative RPE progression note per week.
    """
    from feature_v2_variety import (
        pick_exercise_with_variety, full_body_pattern_remap,
    )

    template = _STRENGTH_TEMPLATES.get(kind) or _STRENGTH_TEMPLATES.get("strength_full_body")
    remap = full_body_pattern_remap(exposure_number, variety_preference,
                                     training_experience, kind,
                                     session_slot=session_slot)
    exercises: list[dict] = []
    equipment_used: set[str] = set()
    locked_exercises = locked_exercises or {}
    for slot in template or []:
        # Session A/B/C remap: swap horizontal↔vertical for push/pull anchors
        # per session_slot so the three weekly full-body sessions feel
        # meaningfully different.
        pattern = remap.get(slot["role"], slot["pattern"])
        ex = pick_exercise_with_variety(
            pattern=pattern,
            slot_role=slot["role"],
            pool=_STRENGTH_POOL.get(pattern) or [],
            equipment_ctx=set(equipment_ctx),
            exposure_number=exposure_number,
            variety_preference=variety_preference,
            training_experience=training_experience,
            avoid_patterns=set(avoid),
            locked_name=locked_exercises.get(slot["role"]),
            session_slot=session_slot,
        )
        if not ex:
            continue
        exercises.append({
            "role": slot["role"],
            "name": ex["name"],
            "sets": slot["sets"],
            "reps": slot["reps"],
            "rest_sec": slot["rest_sec"],
            "load_target": slot["rpe"],
            "equipment_used": ex["equipment"],
            "subs_allowed": [p["name"] for p in _STRENGTH_POOL.get(pattern, [])
                             if p["name"] != ex["name"]][:3],
        })
        equipment_used.update(ex["equipment"])
    return exercises, sorted(equipment_used)


# ---------------------------------------------------------------------------
# Mobility + Recovery + Activation + Rest builders
# ---------------------------------------------------------------------------

def _mobility_flow(dur: int) -> dict:
    return {"flow_blocks": [
        {"name": "Cat-Cow + World's Greatest Stretch",
         "duration_sec": max(180, dur * 20)},
        {"name": "Hip Openers: 90-90s + Deep Squat Hold + Thoracic Rotations",
         "duration_sec": max(180, dur * 20)},
        {"name": "Legs-up-Wall + Diaphragm Breathing",
         "duration_sec": max(120, dur * 20)},
    ]}


def _recovery_flow(dur: int) -> dict:
    return {"flow_blocks": [
        {"name": "Slow-tempo Mobility", "duration_sec": max(300, dur * 30)},
        {"name": "Foam Roll (quads, calves, hips)", "duration_sec": max(300, dur * 30)},
        {"name": "Down-regulation: nasal breathing", "duration_sec": 180},
    ]}


def _travel_recovery(dur: int) -> dict:
    return {"flow_blocks": [
        {"name": "Ankle circles + calf drainage", "duration_sec": 180},
        {"name": "Hip flexor + T-spine unlock",   "duration_sec": 240},
        {"name": "Diaphragm resets (4-7-8)",      "duration_sec": 180},
        {"name": "Optional 10 min easy walk",     "duration_sec": max(0, dur - 10) * 60},
    ]}


def _activation(dur: int) -> dict:
    return {"flow_blocks": [
        {"name": "Glute bridges 2x10",           "duration_sec": 60},
        {"name": "Band pull-aparts 2x15",         "duration_sec": 60},
        {"name": "Dead bug 2x8/side",            "duration_sec": 90},
        {"name": "Optional light plyo primer 4x20m", "duration_sec": max(0, dur - 4) * 60},
    ]}


# ---------------------------------------------------------------------------
# Triathlon brick
# ---------------------------------------------------------------------------

def _brick_bike_run(dur: int) -> dict:
    bike_min = int(dur * 0.6)
    run_min = int(dur * 0.35)
    trans = max(2, dur - bike_min - run_min)
    return {
        "segments": [
            {"modality": "bike",
             "type": "endurance",
             "duration_min": bike_min, "hr_zone": "z2-z3",
             "cadence": "85-95 rpm",
             "cue": "Aerobic. Finish with 5-min pickup to z3."},
            {"modality": "transition",
             "duration_min": trans,
             "cue": "Quick shoes swap, 30s standing shake-out."},
            {"modality": "run",
             "type": "off_bike",
             "duration_min": run_min, "hr_zone": "z3",
             "pace_target": "goal race pace",
             "cue": "Legs will feel odd — turnover, not stride length."},
        ]
    }


# ---------------------------------------------------------------------------
# The main dispatch
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Warmup drill packs (Iter 113)
# ---------------------------------------------------------------------------
# V2 running / cycling warmups used to arrive as a single duration+cue block
# which lost the "specific movement drills" UX from the legacy engine. This
# module attaches a short, context-appropriate `drills` list onto the warmup
# payload without touching duration budgets or Engine V2 spacing rules. The
# frontend renders these as an itemised list under the WARMUP block.

_RUN_DRILLS_STANDARD: list[dict] = [
    {"name": "Ankle circles",         "duration_sec": 20, "cue": "Each foot"},
    {"name": "Leg swings (front/back)","duration_sec": 30, "cue": "Each leg"},
    {"name": "Leg swings (side)",     "duration_sec": 30, "cue": "Each leg"},
    {"name": "Walking lunges",        "duration_sec": 45, "cue": "Loose hips"},
    {"name": "High knees",            "duration_sec": 20, "cue": "Cadence prep"},
    {"name": "Butt kicks",            "duration_sec": 20, "cue": "Heel to glute"},
]

_RUN_DRILLS_INTERVAL: list[dict] = _RUN_DRILLS_STANDARD + [
    {"name": "A-skips",  "duration_sec": 30, "cue": "Snappy, tall posture"},
    {"name": "Strides",  "duration_sec": 20, "reps": 4, "rest_sec": 60,
     "cue": "4 × 20s at fast-but-relaxed"},
]

_CYCLE_DRILLS_STANDARD: list[dict] = [
    {"name": "Easy spin",         "duration_sec": 120, "cue": "Loose legs"},
    {"name": "Cadence pyramid",   "duration_sec": 60,
     "cue": "20s @ 90rpm → 100rpm → 110rpm"},
    {"name": "Standing pedal",    "duration_sec": 30, "cue": "Out of saddle"},
]

_CYCLE_DRILLS_INTERVAL: list[dict] = _CYCLE_DRILLS_STANDARD + [
    {"name": "Openers", "duration_sec": 30, "reps": 3, "rest_sec": 30,
     "cue": "3 × 30s hard efforts"},
]


def _attach_warmup_drills(payload: dict, modality: str, kind: str) -> dict:
    """Attach a `drills` array to the warmup block. Non-destructive."""
    wu = payload.get("warmup") if isinstance(payload, dict) else None
    if not isinstance(wu, dict):
        return payload
    if wu.get("drills"):
        return payload  # respect any explicit drills the builder produced
    interval_ish = kind in (
        "run_intervals", "run_vo2", "run_tempo", "run_threshold",
        "run_marathon_pace", "run_race_pace", "run_strides",
        "cycle_intervals", "cycle_vo2", "cycle_threshold",
    )
    if modality == "run":
        wu["drills"] = _RUN_DRILLS_INTERVAL if interval_ish else _RUN_DRILLS_STANDARD
    elif modality == "cycle":
        wu["drills"] = _CYCLE_DRILLS_INTERVAL if interval_ish else _CYCLE_DRILLS_STANDARD
    return payload


def build_session_spec(
    *,
    kind: str,
    duration_min: int,
    intensity_target: str,
    phase_kind: str,
    day_type: str,
    equipment_ctx: set[str],
    avoid_patterns: set[str],
    intensity_ceiling: str = "any",
    exposure_number: int = 1,
    variety_preference: str = "moderate",
    training_experience: Optional[str] = None,
    cardio_preference: str = "run",
    locked_exercises: Optional[dict[str, str]] = None,
    session_slot: int = 0,
    week_index: int = 0,
) -> SessionSpec:
    """Return a SessionSpec for the given placement. On failure to produce
    content, sets coach_review_required=True on the SessionSpec with a reason;
    NEVER returns None so the state machine can transition to `failed`.

    Iter 121 additions:
      - `exposure_number` + `variety_preference` drive deterministic exercise
        rotation for non-anchor strength slots.
      - `cardio_preference` resolves cardio-modality-agnostic quotas
        (`aerobic_z2`) into run / bike / walk.
      - `locked_exercises` allows coach to pin a specific exercise per slot.
    """
    meta = session_kind_meta(kind)
    modality = meta.get("modality")

    if kind == "rest":
        return SessionSpec(
            spec_kind="rest", kind=kind, duration_min=0,
            intensity_target="rest", environment="none",
            equipment_used=[], payload={"note": "Rest — no session"},
            rationale="Programmed rest day",
        )

    # Iter 121 — resolve cardio-modality-agnostic kinds using client preference.
    # `aerobic_z2` is stored on placements as-is (WHAT preserved); construction
    # decides HOW based on preference & equipment.
    # Iter 130g — support low-impact modalities (elliptical, rower, recumbent
    # bike, incline_walk) for clients who cannot / prefer not to run.
    if kind in ("aerobic_z2",):
        pref = (cardio_preference or "run").lower()
        if pref in ("bike", "stationary_bike", "spin") and "bike" in equipment_ctx:
            resolved = "bike_easy"
        elif pref == "recumbent_bike":
            resolved = "recumbent_bike_easy"
        elif pref == "walk":
            resolved = "walk_z2"
        elif pref == "incline_walk":
            resolved = "incline_walk_z2"
        elif pref == "elliptical":
            resolved = "elliptical_z2"
        elif pref == "rower":
            resolved = "rower_z2"
        else:
            resolved = "run_easy"
        # Rebuild meta for resolved kind
        meta = session_kind_meta(resolved) or {"modality": MODALITY_RUN}
        modality = meta.get("modality")
        kind_effective = resolved
    else:
        kind_effective = kind

    # Iter 130g — deterministic low-impact cardio builders. These live
    # OUTSIDE the running/cycling modality dispatch so they never route to
    # a running builder for clients who explicitly cannot run.
    _LOW_IMPACT_KINDS = {
        "elliptical_z2":       ("Elliptical Z2",
                                "Moderate steady stride. Full range, tall posture.",
                                ["elliptical"], "any"),
        "rower_z2":            ("Rowing Z2",
                                "Legs-hips-arms drive. 24-28 strokes/min. Nasal-breath pace.",
                                ["rower"], "any"),
        "recumbent_bike_easy": ("Recumbent Bike Easy",
                                "Steady seated cadence 75-85 rpm. Conversational.",
                                ["recumbent_bike"], "any"),
        "incline_walk_z2":     ("Incline Walk Z2",
                                "5-8% incline, 5.0-5.5 km/h. Brisk conversational.",
                                ["treadmill"], "any"),
    }
    if kind_effective in _LOW_IMPACT_KINDS:
        title, cue, equip, env = _LOW_IMPACT_KINDS[kind_effective]
        wu = max(3, int(duration_min * 0.10))
        cd = max(3, int(duration_min * 0.08))
        steady = max(10, duration_min - wu - cd)
        return SessionSpec(
            spec_kind="cardio", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=equip,
            payload={
                "warmup":   {"duration_min": wu, "hr_zone": "z1", "cue": "Easy start; loose posture."},
                "main":     {"type": title.lower().replace(" ", "_"),
                             "duration_min": steady, "hr_zone": "z2",
                             "cue": cue},
                "cooldown": {"duration_min": cd, "hr_zone": "z1", "cue": "Slow down; deep breathing."},
            },
            rationale=(f"{title} — {phase_kind} phase (low-impact cardio per client preference)"),
        )

    if modality == MODALITY_RUN:
        if kind_effective == "walk_z2":
            env = _pick_running_environment(day_type, equipment_ctx)
            payload = _walking_z2(duration_min)
            return SessionSpec(
                spec_kind="running", kind=kind, duration_min=duration_min,
                intensity_target=intensity_target, environment=env,
                equipment_used=["walking_shoes"],
                payload=payload,
                rationale=f"Aerobic Z2 walk — {phase_kind} phase (cardio pref: walk)",
            )
        builder = RUNNING_BUILDERS.get(kind_effective)
        if not builder:
            return _unbuildable(kind, duration_min, "no running builder registered")
        env = _pick_running_environment(day_type, equipment_ctx)
        payload = builder(duration_min, phase_kind)
        payload = _attach_warmup_drills(payload, "run", kind_effective)
        return SessionSpec(
            spec_kind="running", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=["treadmill"] if env == "treadmill" else ["running_shoes"],
            payload=payload,
            rationale=f"{kind.replace('_',' ').title()} — {phase_kind} phase",
        )

    if modality == MODALITY_CYCLE:
        builder = CYCLING_BUILDERS.get(kind_effective)
        if not builder:
            return _unbuildable(kind, duration_min, "no cycling builder")
        env = _pick_cycling_environment(day_type, equipment_ctx)
        payload = builder(duration_min, phase_kind)
        payload = _attach_warmup_drills(payload, "cycle", kind_effective)
        return SessionSpec(
            spec_kind="cycling", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=(["bike", "indoor_trainer"] if env == "indoor_trainer"
                             else ["bike"]),
            payload=payload,
            rationale=f"{kind.replace('_',' ').title()} — {phase_kind} phase",
        )

    if modality == MODALITY_SWIM:
        builder = SWIM_BUILDERS.get(kind_effective)
        if not builder:
            return _unbuildable(kind, duration_min, "no swim builder")
        env = _pick_swim_environment(day_type, equipment_ctx)
        payload = builder(duration_min, phase_kind)
        return SessionSpec(
            spec_kind="swimming", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=["pool_access", "goggles"],
            payload=payload,
            rationale=f"{kind.replace('_',' ').title()} — {phase_kind} phase",
        )

    if modality == MODALITY_STRENGTH:
        # Iter 121 — dispatch conditioning kinds to circuit builders.
        if kind_effective in ("conditioning_mixed",):
            env = _pick_strength_environment(day_type, equipment_ctx)
            return SessionSpec(
                spec_kind="conditioning", kind=kind, duration_min=duration_min,
                intensity_target=intensity_target, environment=env,
                equipment_used=sorted((equipment_ctx & {"dumbbells", "kettlebell", "mat"})
                                        or {"bodyweight"}),
                payload=_conditioning_mixed_circuit(duration_min),
                rationale=f"Mixed conditioning circuit — {phase_kind} phase",
            )
        if kind_effective in ("conditioning_intervals",):
            env = _pick_strength_environment(day_type, equipment_ctx)
            return SessionSpec(
                spec_kind="conditioning", kind=kind, duration_min=duration_min,
                intensity_target=intensity_target, environment=env,
                equipment_used=sorted((equipment_ctx & {"dumbbells", "kettlebell", "mat"})
                                        or {"bodyweight"}),
                payload=_conditioning_intervals(duration_min),
                rationale=f"Conditioning intervals — {phase_kind} phase",
            )
        env = _pick_strength_environment(day_type, equipment_ctx)
        exercises, used_equip = _build_strength(
            kind_effective, duration_min, equipment_ctx, avoid_patterns,
            exposure_number=exposure_number,
            variety_preference=variety_preference,
            training_experience=training_experience,
            locked_exercises=locked_exercises or {},
            session_slot=session_slot,
            week_index=week_index,
        )
        if not exercises:
            return _unbuildable(kind, duration_min,
                                "no compatible exercises for current equipment/restrictions")
        # Iter 130g — deterministic per-week progression note. Non-LLM.
        _RPE_LADDER = ["RPE 6", "RPE 6-7", "RPE 7", "RPE 7-8", "RPE 8", "RPE 8 + add 1 set"]
        _SESSION_LABELS = {0: "A", 1: "B", 2: "C"}
        session_label = _SESSION_LABELS.get(session_slot % 3, "A")
        label_note = (f"Full Body {session_label}"
                       if kind_effective == "strength_full_body" else "")
        progression_note = (
            f"Week {week_index + 1}: target load "
            f"{_RPE_LADDER[min(week_index, len(_RPE_LADDER)-1)]}"
            + (f" · {label_note}" if label_note else "")
        )
        return SessionSpec(
            spec_kind="strength", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=used_equip,
            payload={
                "exercises": exercises,
                "session_label": session_label
                                  if kind_effective == "strength_full_body" else None,
                "progression": progression_note,
            },
            rationale=f"{kind.replace('_',' ').title()} — {phase_kind} phase",
        )

    if modality == MODALITY_MOBILITY:
        return SessionSpec(
            spec_kind="mobility", kind=kind, duration_min=duration_min,
            intensity_target="flow", environment="any",
            equipment_used=["mat"],
            payload=_mobility_flow(duration_min),
            rationale="Mobility flow — restorative and joint prep",
        )

    if modality == MODALITY_RECOVERY:
        payload = (_travel_recovery(duration_min) if kind == "travel_recovery"
                   else _recovery_flow(duration_min))
        return SessionSpec(
            spec_kind="travel_recovery" if kind == "travel_recovery" else "recovery",
            kind=kind, duration_min=duration_min,
            intensity_target="recovery", environment="any",
            equipment_used=(["mat", "foam_roller"] if kind == "recovery" else []),
            payload=payload,
            rationale=("Travel recovery — reduce swelling, restore mobility"
                        if kind == "travel_recovery" else "Recovery session"),
        )

    if modality == MODALITY_ACTIVATION:
        return SessionSpec(
            spec_kind="activation", kind=kind, duration_min=duration_min,
            intensity_target="easy", environment="any",
            equipment_used=["band"],
            payload=_activation(duration_min),
            rationale="Neuromuscular activation primer",
        )

    if modality == MODALITY_BRICK:
        env_bike = _pick_cycling_environment(day_type, equipment_ctx)
        return SessionSpec(
            spec_kind="brick", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target,
            environment=f"bike:{env_bike}+run:outdoor",
            equipment_used=["bike", "running_shoes"],
            payload=_brick_bike_run(duration_min),
            rationale="Triathlon brick — race-specific transfer",
        )

    return _unbuildable(kind, duration_min, f"no builder for modality={modality}")


def _unbuildable(kind: str, dur: int, why: str) -> SessionSpec:
    return SessionSpec(
        spec_kind="unbuildable", kind=kind, duration_min=dur,
        intensity_target="?", environment="?",
        equipment_used=[], payload={}, rationale="",
        coach_review_required=True, review_reason=why,
    )


__all__ = ["SessionSpec", "build_session_spec"]
