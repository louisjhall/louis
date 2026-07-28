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
    # On layover / hotel / turnaround days, treadmill is often the only option
    if day_type in ("layover_arrival", "layover_departure", "turnaround",
                     "layover", "hotel", "layover_full"):
        if "treadmill" in equipment_ctx:
            return "treadmill"
        return "outdoor"          # coach may resolve
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
    if "barbell" in equipment_ctx and "rack" in equipment_ctx:
        return "gym"
    if day_type in ("layover_arrival", "layover_departure", "turnaround",
                     "layover", "hotel", "layover_full"):
        return "hotel_room"
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
    # Absolute fallback — bodyweight substitute
    for ex in pool:
        if "bodyweight" in ex["equipment"]:
            return ex
    return None


def _build_strength(kind: str, dur: int, equipment_ctx: set[str],
                    avoid: set[str]) -> tuple[list[dict], list[str]]:
    template = _STRENGTH_TEMPLATES.get(kind) or _STRENGTH_TEMPLATES.get("strength_full_body")
    exercises: list[dict] = []
    equipment_used: set[str] = set()
    for slot in template or []:
        ex = _pick_exercise(slot["pattern"], equipment_ctx, avoid)
        if not ex:
            continue
        exercises.append({
            "role": slot["role"],
            "name": ex["name"],
            "sets": slot["sets"],
            "reps": slot["reps"],
            "rest_sec": slot["rest_sec"],
            "load_target": slot["rpe"],   # RPE-driven for now
            "equipment_used": ex["equipment"],
            "subs_allowed": [p["name"] for p in _STRENGTH_POOL.get(slot["pattern"], [])
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
) -> SessionSpec:
    """Return a SessionSpec for the given placement. On failure to produce
    content, sets coach_review_required=True on the SessionSpec with a reason;
    NEVER returns None so the state machine can transition to `failed`."""
    meta = session_kind_meta(kind)
    modality = meta.get("modality")

    if kind == "rest":
        return SessionSpec(
            spec_kind="rest", kind=kind, duration_min=0,
            intensity_target="rest", environment="none",
            equipment_used=[], payload={"note": "Rest — no session"},
            rationale="Programmed rest day",
        )

    if modality == MODALITY_RUN:
        builder = RUNNING_BUILDERS.get(kind)
        if not builder:
            return _unbuildable(kind, duration_min, "no running builder registered")
        env = _pick_running_environment(day_type, equipment_ctx)
        payload = builder(duration_min, phase_kind)
        payload = _attach_warmup_drills(payload, "run", kind)
        return SessionSpec(
            spec_kind="running", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=["treadmill"] if env == "treadmill" else ["running_shoes"],
            payload=payload,
            rationale=f"{kind.replace('_',' ').title()} — {phase_kind} phase",
        )

    if modality == MODALITY_CYCLE:
        builder = CYCLING_BUILDERS.get(kind)
        if not builder:
            return _unbuildable(kind, duration_min, "no cycling builder")
        env = _pick_cycling_environment(day_type, equipment_ctx)
        payload = builder(duration_min, phase_kind)
        payload = _attach_warmup_drills(payload, "cycle", kind)
        return SessionSpec(
            spec_kind="cycling", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=(["bike", "indoor_trainer"] if env == "indoor_trainer"
                             else ["bike"]),
            payload=payload,
            rationale=f"{kind.replace('_',' ').title()} — {phase_kind} phase",
        )

    if modality == MODALITY_SWIM:
        builder = SWIM_BUILDERS.get(kind)
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
        env = _pick_strength_environment(day_type, equipment_ctx)
        exercises, used_equip = _build_strength(kind, duration_min, equipment_ctx, avoid_patterns)
        if not exercises:
            return _unbuildable(kind, duration_min,
                                "no compatible exercises for current equipment/restrictions")
        return SessionSpec(
            spec_kind="strength", kind=kind, duration_min=duration_min,
            intensity_target=intensity_target, environment=env,
            equipment_used=used_equip,
            payload={"exercises": exercises},
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
