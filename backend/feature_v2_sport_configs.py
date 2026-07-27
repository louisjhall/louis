"""
CrewFit V2 Engine V2 — Sport Taxonomy & Goal Configuration Registry
====================================================================

The single source of truth for the WHAT layer.

Every training decision starts here: given a client's goal, phase, timeline and
progression, the engine MUST derive:
    * required objective quotas
    * session priority (KEY / IMPORTANT / SUPPORTING / OPTIONAL)
    * per-week frequency ranges + spacing rules
    * progression model (how quotas + durations evolve phase-to-phase)
    * duration / intensity logic (target session length is NEVER derived from
      the roster; only capped by it)
    * concurrent-training considerations (strength ↔ endurance interference,
      swim/bike/run interference for triathletes)

This module is DECLARATIVE. It contains no I/O, no DB access, and no
scheduling logic. It answers three functions:

    get_goal_config(goal_key)                       -> GoalConfig
    resolve_phase_plan(goal_key, prep_weeks)        -> [PhaseSpec]
    required_exposures_for_phase(goal, phase_kind)  -> [RequiredExposure]

Everything downstream (demand → scheduling → construction → validation) is
consumed downstream of these three calls.

Do not add per-client special cases here. Only add new SPORT_CONFIGS entries
or extend the shared taxonomy.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# TAXONOMY — session kinds
# ---------------------------------------------------------------------------
# The taxonomy is extensible: new kinds may be added without touching the
# scheduler or construction pipeline as long as:
#   * kind is registered in SESSION_KIND_REGISTRY below
#   * a builder exists in feature_v2_construction_v2.SESSION_BUILDERS
#   * an intensity_class is set (KEY / HARD / MODERATE / EASY / RECOVERY / REST)


# Modality — what physical system the session primarily loads
MODALITY_RUN     = "run"
MODALITY_CYCLE   = "cycle"
MODALITY_SWIM    = "swim"
MODALITY_STRENGTH = "strength"
MODALITY_MOBILITY = "mobility"
MODALITY_RECOVERY = "recovery"
MODALITY_ACTIVATION = "activation"
MODALITY_BRICK   = "brick"   # tri-specific: bike→run

# Intensity class — governs recovery + sequencing rules
INTENSITY_KEY       = "key"        # hardest workout of the week (LR, threshold, race-pace)
INTENSITY_HARD      = "hard"       # significant load below key
INTENSITY_MODERATE  = "moderate"   # steady aerobic, working strength
INTENSITY_EASY      = "easy"       # low-load endurance, activation
INTENSITY_RECOVERY  = "recovery"   # active recovery, deloaded strength
INTENSITY_REST      = "rest"       # off / passive

# Session-kind registry.
# Each entry declares the sport-typed session type + how the sequencing engine
# should treat it. Everything downstream reads from here.
SESSION_KIND_REGISTRY: dict[str, dict[str, Any]] = {
    # ---- Running ----
    "run_easy":         {"modality": MODALITY_RUN, "intensity_class": INTENSITY_EASY,     "hard": False, "family": "run_aerobic"},
    "run_tempo":        {"modality": MODALITY_RUN, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "run_threshold"},
    "run_threshold":    {"modality": MODALITY_RUN, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "run_threshold"},
    "run_intervals":    {"modality": MODALITY_RUN, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "run_vo2"},
    "run_vo2":          {"modality": MODALITY_RUN, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "run_vo2"},
    "run_long":         {"modality": MODALITY_RUN, "intensity_class": INTENSITY_KEY,      "hard": True,  "family": "run_long"},
    "run_marathon_pace":{"modality": MODALITY_RUN, "intensity_class": INTENSITY_KEY,      "hard": True,  "family": "run_race_pace"},
    "run_race_pace":    {"modality": MODALITY_RUN, "intensity_class": INTENSITY_KEY,      "hard": True,  "family": "run_race_pace"},
    "run_recovery":     {"modality": MODALITY_RUN, "intensity_class": INTENSITY_RECOVERY, "hard": False, "family": "run_aerobic"},
    "run_strides":      {"modality": MODALITY_RUN, "intensity_class": INTENSITY_MODERATE, "hard": False, "family": "run_neuromuscular"},

    # ---- Cycling ----
    "bike_easy":        {"modality": MODALITY_CYCLE, "intensity_class": INTENSITY_EASY,     "hard": False, "family": "bike_aerobic"},
    "bike_endurance":   {"modality": MODALITY_CYCLE, "intensity_class": INTENSITY_MODERATE, "hard": False, "family": "bike_aerobic"},
    "bike_tempo":       {"modality": MODALITY_CYCLE, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "bike_threshold"},
    "bike_threshold":   {"modality": MODALITY_CYCLE, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "bike_threshold"},
    "bike_intervals":   {"modality": MODALITY_CYCLE, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "bike_vo2"},
    "bike_long":        {"modality": MODALITY_CYCLE, "intensity_class": INTENSITY_KEY,      "hard": True,  "family": "bike_long"},
    "bike_recovery":    {"modality": MODALITY_CYCLE, "intensity_class": INTENSITY_RECOVERY, "hard": False, "family": "bike_aerobic"},

    # ---- Swim ----
    "swim_technique":   {"modality": MODALITY_SWIM, "intensity_class": INTENSITY_EASY,     "hard": False, "family": "swim_technique"},
    "swim_aerobic":     {"modality": MODALITY_SWIM, "intensity_class": INTENSITY_MODERATE, "hard": False, "family": "swim_aerobic"},
    "swim_endurance":   {"modality": MODALITY_SWIM, "intensity_class": INTENSITY_MODERATE, "hard": False, "family": "swim_aerobic"},
    "swim_threshold":   {"modality": MODALITY_SWIM, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "swim_threshold"},
    "swim_intervals":   {"modality": MODALITY_SWIM, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "swim_threshold"},
    "swim_recovery":    {"modality": MODALITY_SWIM, "intensity_class": INTENSITY_RECOVERY, "hard": False, "family": "swim_aerobic"},
    "swim_open_water":  {"modality": MODALITY_SWIM, "intensity_class": INTENSITY_MODERATE, "hard": False, "family": "swim_aerobic"},

    # ---- Strength ----
    "strength_full_body":{"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "strength_full"},
    "strength_upper":   {"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "strength_split"},
    "strength_lower":   {"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "strength_split"},
    "strength_push":    {"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "strength_split"},
    "strength_pull":    {"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "strength_split"},
    "strength_support": {"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_MODERATE, "hard": False, "family": "strength_support"},
    "strength_maintenance":{"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_MODERATE, "hard": False, "family": "strength_support"},
    "strength_power":   {"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_HARD,     "hard": True,  "family": "strength_power"},
    "strength_hypertrophy":{"modality": MODALITY_STRENGTH, "intensity_class": INTENSITY_HARD,  "hard": True,  "family": "strength_hyp"},

    # ---- Supporting ----
    "mobility":         {"modality": MODALITY_MOBILITY,   "intensity_class": INTENSITY_EASY,     "hard": False, "family": "mobility"},
    "mobility_flow":    {"modality": MODALITY_MOBILITY,   "intensity_class": INTENSITY_EASY,     "hard": False, "family": "mobility"},
    "recovery":         {"modality": MODALITY_RECOVERY,   "intensity_class": INTENSITY_RECOVERY, "hard": False, "family": "recovery"},
    "travel_recovery":  {"modality": MODALITY_RECOVERY,   "intensity_class": INTENSITY_RECOVERY, "hard": False, "family": "recovery"},
    "activation":       {"modality": MODALITY_ACTIVATION, "intensity_class": INTENSITY_EASY,     "hard": False, "family": "activation"},
    "preflight_activation":{"modality": MODALITY_ACTIVATION, "intensity_class": INTENSITY_EASY,  "hard": False, "family": "activation"},
    "rest":             {"modality": None, "intensity_class": INTENSITY_REST, "hard": False, "family": "rest"},

    # ---- Triathlon-specific ----
    "brick_bike_run":   {"modality": MODALITY_BRICK, "intensity_class": INTENSITY_KEY, "hard": True,  "family": "tri_brick"},
    "brick_swim_bike":  {"modality": MODALITY_BRICK, "intensity_class": INTENSITY_HARD, "hard": True, "family": "tri_brick"},
}


# ---------------------------------------------------------------------------
# Dataclasses — pure config, no methods with side effects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuotaRule:
    """A required objective within a phase.

    exposures_per_week:  (min, target, max)  — engine attempts target
    priority:            "KEY" | "IMPORTANT" | "SUPPORTING" | "OPTIONAL"
    min_recovery_hours:  minimum hours before another session of the same family
    duration_min:        (min_minutes, target_minutes, max_minutes)
    intensity_target:    canonical intensity descriptor for HOW layer
    progression:         { field, per_week_delta, cap }  optional
    can_skip_if_missed:  KEY = False; others may be True
    """
    kind: str
    exposures_per_week: tuple[float, float, float]   # (min, target, max)
    priority: str
    min_recovery_hours: int
    duration_min: tuple[int, int, int]               # (min, target, max) MINUTES
    intensity_target: str
    progression: dict[str, Any] = field(default_factory=dict)
    can_skip_if_missed: bool = True
    notes: str = ""


@dataclass(frozen=True)
class PhaseSpec:
    """A single training phase within a goal's periodisation."""
    phase_kind: str                                  # foundation, aerobic_base, build, ...
    weeks_target: int                                # how long by default
    weeks_min: int                                   # can compress to
    weeks_max: int                                   # can stretch to
    quotas: tuple[QuotaRule, ...]
    hard_days_per_week_max: int                      # global hard-day cap
    key_days_per_week_max: int                       # global KEY-day cap (LR, race pace, threshold)
    consecutive_training_days_max: int
    concurrent_notes: str = ""                       # e.g. "avoid heavy legs day before LR"


@dataclass(frozen=True)
class GoalConfig:
    """Full configuration for a top-level goal."""
    key: str                                         # e.g. running.marathon
    family: str                                      # running / cycling / triathlon / strength / general
    display_name: str
    default_prep_weeks: int
    min_prep_weeks: int
    phase_sequence: tuple[str, ...]                  # ordering, filtered by prep_weeks
    phase_specs: dict[str, PhaseSpec]                # keyed by phase_kind
    # Global rules independent of phase — session-family recovery + interference
    session_family_recovery_hours: dict[str, int] = field(default_factory=dict)
    forbidden_sequences: tuple[tuple[str, str], ...] = ()   # ((prev_family, next_family), ...)
    strength_endurance_interference: bool = False    # ↑ inter-session gap when both present


# ---------------------------------------------------------------------------
# Shared building blocks used across goals
# ---------------------------------------------------------------------------

# Default forbidden-sequence catalogue. Individual goals can extend.
_ENDURANCE_FORBIDDEN = (
    # (prev_session_family_or_kind, next_session_family_or_kind)
    ("run_long", "run_long"),
    ("run_long", "run_threshold"),
    ("run_long", "run_vo2"),
    ("run_threshold", "run_long"),
    ("run_vo2", "run_long"),
    ("run_threshold", "run_threshold"),
    ("run_vo2", "run_vo2"),
    ("run_race_pace", "run_long"),
    ("run_long", "run_race_pace"),
    ("bike_long", "bike_long"),
    ("bike_long", "bike_threshold"),
    ("bike_threshold", "bike_long"),
    ("swim_threshold", "swim_threshold"),
)

_STRENGTH_FORBIDDEN = (
    ("strength_hyp", "strength_hyp"),        # same body area shouldn't repeat
    ("strength_power", "strength_power"),
    ("strength_full", "strength_full"),      # if strength is KEY, need spacing
    # heavy legs the day before an endurance KEY
    ("strength_lower", "run_long"),
    ("strength_full", "run_long"),
    ("strength_lower", "bike_long"),
    ("strength_full", "bike_long"),
)


# ---------------------------------------------------------------------------
# GOAL REGISTRY
# ---------------------------------------------------------------------------
# Every entry MUST validate against the invariants at the bottom of this file.

SPORT_CONFIGS: dict[str, GoalConfig] = {}


def _register(cfg: GoalConfig) -> None:
    SPORT_CONFIGS[cfg.key] = cfg


# ---------------------------------------------------------------------------
# RUNNING — marathon (26.2mi / 42.2km)
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="running.marathon",
    family="running",
    display_name="Marathon",
    default_prep_weeks=18,
    min_prep_weeks=12,
    phase_sequence=("foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (25, 35, 50), "z2", {},
                          notes="Build gentle aerobic base"),
                QuotaRule("run_long",         (0.5, 1, 1), "KEY",     72, (45, 60, 75), "z2", {},
                          can_skip_if_missed=False,
                          notes="Weekly long-run anchor; strict 72h recovery"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7", {},
                          notes="Injury-prevention support"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING", 12,(15, 20, 30), "flow", {}),
            ),
        ),
        "aerobic_base": PhaseSpec(
            phase_kind="aerobic_base", weeks_target=6, weeks_min=4, weeks_max=8,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (3, 3, 4), "IMPORTANT", 24, (30, 45, 60), "z2",
                          progression={"field": "duration_min.target", "per_week_delta": 2, "cap": 60}),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (60, 80, 120), "z2",
                          progression={"field": "duration_min.target", "per_week_delta": 5, "cap": 120},
                          can_skip_if_missed=False),
                QuotaRule("run_tempo",        (0, 0.5, 1), "IMPORTANT",48,(25, 35, 45), "z3-z4",
                          notes="Optional in early base; introduced later"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=6, weeks_min=4, weeks_max=8,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (30, 45, 60), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (75, 100, 150), "z2",
                          progression={"field": "duration_min.target", "per_week_delta": 5, "cap": 150},
                          can_skip_if_missed=False),
                QuotaRule("run_threshold",    (0.5, 1, 1), "IMPORTANT", 48,(30, 40, 55), "z4"),
                QuotaRule("run_intervals",    (0, 0.5, 1), "IMPORTANT", 48,(30, 40, 50), "z5",
                          notes="Alternate with threshold, not both same week"),
                QuotaRule("strength_full_body",(1, 1.5, 2), "IMPORTANT",48,(30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "specific_prep": PhaseSpec(
            phase_kind="specific_prep", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 2, 3), "IMPORTANT", 24, (30, 40, 55), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (105, 135, 180), "z2-z3",
                          progression={"field": "duration_min.target", "per_week_delta": 5, "cap": 180},
                          can_skip_if_missed=False),
                QuotaRule("run_marathon_pace",(0.5, 1, 1), "KEY",     72, (45, 60, 90), "z3",
                          can_skip_if_missed=False,
                          notes="MP work — replaces some threshold in specific_prep"),
                QuotaRule("run_threshold",    (0, 0.5, 1), "IMPORTANT",48,(30, 40, 50), "z4"),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(20, 30, 40), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING", 12,(15, 20, 30), "flow"),
            ),
        ),
        "taper": PhaseSpec(
            phase_kind="taper", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (20, 30, 45), "z2"),
                QuotaRule("run_marathon_pace",(0, 0.5, 1), "IMPORTANT",72,(20, 30, 45), "z3"),
                QuotaRule("run_long",         (0.5, 1, 1), "KEY",     96, (60, 80, 100), "z2",
                          notes="Shortened long run"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("preflight_activation",(0, 1, 2), "OPTIONAL",12,(10, 15, 20), "easy"),
            ),
        ),
        "race_week": PhaseSpec(
            phase_kind="race_week", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (1, 2, 3), "SUPPORTING", 24, (15, 25, 35), "z2"),
                QuotaRule("run_strides",      (0, 1, 1), "OPTIONAL", 24,  (15, 20, 25), "neuromuscular"),
                QuotaRule("mobility",         (1, 1, 2), "SUPPORTING",12, (10, 15, 20), "flow"),
                QuotaRule("rest",             (2, 3, 4), "IMPORTANT",  0, (0, 0, 0),    "rest"),
            ),
        ),
    },
    session_family_recovery_hours={
        "run_long": 72, "run_threshold": 48, "run_vo2": 48, "run_race_pace": 72,
        "strength_full": 48, "strength_lower": 48,
    },
    forbidden_sequences=_ENDURANCE_FORBIDDEN + _STRENGTH_FORBIDDEN,
    strength_endurance_interference=True,
))


# ---------------------------------------------------------------------------
# RUNNING — half marathon (13.1mi / 21.1km)
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="running.half_marathon",
    family="running",
    display_name="Half Marathon",
    default_prep_weeks=12,
    min_prep_weeks=8,
    phase_sequence=("foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (20, 30, 45), "z2"),
                QuotaRule("run_long",         (0.5, 1, 1), "KEY",     72, (40, 55, 70), "z2",
                          can_skip_if_missed=False),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "aerobic_base": PhaseSpec(
            phase_kind="aerobic_base", weeks_target=4, weeks_min=3, weeks_max=6,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (3, 3, 4), "IMPORTANT", 24, (30, 40, 55), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (55, 75, 100), "z2",
                          progression={"field": "duration_min.target", "per_week_delta": 4, "cap": 100},
                          can_skip_if_missed=False),
                QuotaRule("run_tempo",        (0, 0.5, 1), "IMPORTANT",48,(25, 35, 45), "z3-z4"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=4, weeks_min=3, weeks_max=6,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (30, 40, 55), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (65, 90, 110), "z2",
                          can_skip_if_missed=False),
                QuotaRule("run_threshold",    (0.5, 1, 1), "IMPORTANT",48,(30, 40, 55), "z4"),
                QuotaRule("run_intervals",    (0, 0.5, 1), "IMPORTANT",48,(25, 35, 45), "z5"),
                QuotaRule("strength_full_body",(1, 1.5, 2), "IMPORTANT",48,(30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "specific_prep": PhaseSpec(
            phase_kind="specific_prep", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 2, 3), "IMPORTANT", 24, (25, 35, 50), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (75, 90, 120), "z2-z3",
                          can_skip_if_missed=False),
                QuotaRule("run_race_pace",    (0.5, 1, 1), "KEY",     72, (35, 50, 70), "z4",
                          can_skip_if_missed=False),
                QuotaRule("run_threshold",    (0, 0.5, 1), "IMPORTANT",48,(30, 40, 50), "z4"),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(20, 30, 40), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING", 12,(15, 20, 30), "flow"),
            ),
        ),
        "taper": PhaseSpec(
            phase_kind="taper", weeks_target=1, weeks_min=1, weeks_max=2,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (20, 25, 40), "z2"),
                QuotaRule("run_race_pace",    (0, 0.5, 1), "IMPORTANT",72,(15, 25, 35), "z4"),
                QuotaRule("run_long",         (0.5, 1, 1), "KEY",     96, (50, 65, 80), "z2"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "race_week": PhaseSpec(
            phase_kind="race_week", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (1, 2, 3), "SUPPORTING", 24, (15, 25, 35), "z2"),
                QuotaRule("run_strides",      (0, 1, 1), "OPTIONAL", 24,  (15, 20, 25), "neuromuscular"),
                QuotaRule("mobility",         (1, 1, 2), "SUPPORTING",12, (10, 15, 20), "flow"),
                QuotaRule("rest",             (2, 3, 4), "IMPORTANT",  0, (0, 0, 0),    "rest"),
            ),
        ),
    },
    session_family_recovery_hours={"run_long": 72, "run_threshold": 48, "run_vo2": 48, "run_race_pace": 72},
    forbidden_sequences=_ENDURANCE_FORBIDDEN + _STRENGTH_FORBIDDEN,
    strength_endurance_interference=True,
))


# ---------------------------------------------------------------------------
# RUNNING — 10K
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="running.10k",
    family="running",
    display_name="10K",
    default_prep_weeks=10,
    min_prep_weeks=6,
    phase_sequence=("foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=1, weeks_min=1, weeks_max=2,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (20, 30, 40), "z2"),
                QuotaRule("run_long",         (0.5, 1, 1), "KEY",     72, (35, 45, 60), "z2", can_skip_if_missed=False),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "aerobic_base": PhaseSpec(
            phase_kind="aerobic_base", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (3, 3, 4), "IMPORTANT", 24, (25, 35, 50), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (45, 60, 80), "z2", can_skip_if_missed=False),
                QuotaRule("run_tempo",        (0, 0.5, 1), "IMPORTANT",48,(25, 35, 45), "z3-z4"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (25, 35, 50), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (55, 70, 90), "z2", can_skip_if_missed=False),
                QuotaRule("run_threshold",    (0.5, 1, 1), "IMPORTANT",48,(25, 35, 50), "z4"),
                QuotaRule("run_intervals",    (0.5, 1, 1), "IMPORTANT",48,(25, 35, 45), "z5"),
                QuotaRule("strength_full_body",(1, 1.5, 2), "IMPORTANT",48,(25, 35, 45), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "specific_prep": PhaseSpec(
            phase_kind="specific_prep", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 2, 3), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "IMPORTANT",72,(50, 65, 85), "z2"),
                QuotaRule("run_race_pace",    (0.5, 1, 1), "KEY",     72, (25, 35, 50), "z4-z5",
                          can_skip_if_missed=False),
                QuotaRule("run_intervals",    (0.5, 1, 1), "KEY",     72, (25, 35, 50), "z5",
                          can_skip_if_missed=False),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(20, 30, 40), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING", 12,(15, 20, 30), "flow"),
            ),
        ),
        "taper": PhaseSpec(
            phase_kind="taper", weeks_target=1, weeks_min=1, weeks_max=2,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (20, 25, 40), "z2"),
                QuotaRule("run_race_pace",    (0, 0.5, 1), "IMPORTANT",72,(15, 20, 30), "z4"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "race_week": PhaseSpec(
            phase_kind="race_week", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (1, 2, 3), "SUPPORTING", 24, (15, 25, 35), "z2"),
                QuotaRule("run_strides",      (0, 1, 1), "OPTIONAL", 24,  (15, 20, 25), "neuromuscular"),
                QuotaRule("mobility",         (1, 1, 2), "SUPPORTING",12, (10, 15, 20), "flow"),
                QuotaRule("rest",             (2, 3, 4), "IMPORTANT",  0, (0, 0, 0),    "rest"),
            ),
        ),
    },
    session_family_recovery_hours={"run_long": 72, "run_threshold": 48, "run_vo2": 48, "run_race_pace": 72},
    forbidden_sequences=_ENDURANCE_FORBIDDEN + _STRENGTH_FORBIDDEN,
    strength_endurance_interference=True,
))


# ---------------------------------------------------------------------------
# RUNNING — 5K
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="running.5k",
    family="running",
    display_name="5K",
    default_prep_weeks=8,
    min_prep_weeks=5,
    phase_sequence=("foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=1, weeks_min=1, weeks_max=2,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (20, 30, 40), "z2"),
                QuotaRule("run_long",         (0.5, 1, 1), "IMPORTANT",72,(30, 40, 55), "z2"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "aerobic_base": PhaseSpec(
            phase_kind="aerobic_base", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (3, 3, 4), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "IMPORTANT",72,(40, 55, 70), "z2"),
                QuotaRule("run_tempo",        (0, 0.5, 1), "IMPORTANT",48,(20, 30, 40), "z3-z4"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("run_long",         (0.5, 1, 1), "IMPORTANT",72, (45, 60, 75), "z2"),
                QuotaRule("run_threshold",    (0.5, 1, 1), "IMPORTANT",48,(20, 30, 40), "z4"),
                QuotaRule("run_intervals",    (0.5, 1, 1), "KEY",     48, (25, 35, 45), "z5",
                          can_skip_if_missed=False),
                QuotaRule("strength_full_body",(1, 1.5, 2), "IMPORTANT",48,(25, 35, 45), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "specific_prep": PhaseSpec(
            phase_kind="specific_prep", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("run_easy",         (2, 2, 3), "IMPORTANT", 24, (20, 30, 40), "z2"),
                QuotaRule("run_intervals",    (0.75, 1, 1), "KEY",    72, (25, 35, 45), "z5",
                          can_skip_if_missed=False),
                QuotaRule("run_race_pace",    (0.5, 1, 1), "KEY",     72, (20, 30, 45), "z5",
                          can_skip_if_missed=False),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(20, 30, 40), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING", 12,(15, 20, 30), "flow"),
            ),
        ),
        "taper": PhaseSpec(
            phase_kind="taper", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (2, 3, 3), "IMPORTANT", 24, (20, 25, 35), "z2"),
                QuotaRule("run_strides",      (0, 1, 1), "OPTIONAL", 24,  (15, 20, 25), "neuromuscular"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "race_week": PhaseSpec(
            phase_kind="race_week", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("run_easy",         (1, 2, 3), "SUPPORTING", 24, (15, 25, 30), "z2"),
                QuotaRule("run_strides",      (0, 1, 1), "OPTIONAL", 24,  (15, 20, 25), "neuromuscular"),
                QuotaRule("mobility",         (1, 1, 2), "SUPPORTING",12, (10, 15, 20), "flow"),
                QuotaRule("rest",             (2, 3, 4), "IMPORTANT",  0, (0, 0, 0),    "rest"),
            ),
        ),
    },
    session_family_recovery_hours={"run_long": 72, "run_threshold": 48, "run_vo2": 48, "run_race_pace": 72},
    forbidden_sequences=_ENDURANCE_FORBIDDEN + _STRENGTH_FORBIDDEN,
    strength_endurance_interference=True,
))


# ---------------------------------------------------------------------------
# CYCLING — endurance / long ride
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="cycling.endurance",
    family="cycling",
    display_name="Cycling Endurance",
    default_prep_weeks=12, min_prep_weeks=6,
    phase_sequence=("foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("bike_endurance",   (2, 3, 4), "IMPORTANT", 24, (45, 60, 90), "z2"),
                QuotaRule("bike_long",        (0.5, 1, 1), "KEY",     72, (60, 90, 120), "z2",
                          can_skip_if_missed=False),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "aerobic_base": PhaseSpec(
            phase_kind="aerobic_base", weeks_target=4, weeks_min=3, weeks_max=6,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=5,
            quotas=(
                QuotaRule("bike_easy",        (1, 1, 2), "SUPPORTING", 24, (30, 45, 60), "z1-z2"),
                QuotaRule("bike_endurance",   (2, 3, 4), "IMPORTANT", 24, (60, 75, 100), "z2"),
                QuotaRule("bike_long",        (0.75, 1, 1), "KEY",    72, (90, 120, 180), "z2",
                          can_skip_if_missed=False),
                QuotaRule("bike_tempo",       (0, 0.5, 1), "IMPORTANT",48,(30, 45, 60), "z3"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=4, weeks_min=3, weeks_max=6,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=5,
            quotas=(
                QuotaRule("bike_endurance",   (2, 2, 3), "IMPORTANT", 24, (60, 75, 100), "z2"),
                QuotaRule("bike_long",        (0.75, 1, 1), "KEY",    72, (120, 150, 210), "z2",
                          can_skip_if_missed=False),
                QuotaRule("bike_threshold",   (0.5, 1, 1), "IMPORTANT",48,(45, 60, 75), "z4"),
                QuotaRule("bike_intervals",   (0, 0.5, 1), "IMPORTANT",48,(45, 60, 75), "z5"),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(25, 35, 45), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "specific_prep": PhaseSpec(
            phase_kind="specific_prep", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=5,
            quotas=(
                QuotaRule("bike_endurance",   (1, 2, 2), "IMPORTANT", 24, (45, 60, 90), "z2"),
                QuotaRule("bike_long",        (0.75, 1, 1), "KEY",    72, (150, 180, 240), "z2",
                          can_skip_if_missed=False),
                QuotaRule("bike_threshold",   (0.5, 1, 1), "KEY",     72, (45, 60, 90), "z4",
                          can_skip_if_missed=False),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(20, 30, 40), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING", 12,(15, 20, 30), "flow"),
            ),
        ),
        "taper": PhaseSpec(
            phase_kind="taper", weeks_target=1, weeks_min=1, weeks_max=2,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("bike_easy",        (2, 3, 3), "IMPORTANT", 24, (30, 45, 60), "z1-z2"),
                QuotaRule("bike_threshold",   (0, 0.5, 1), "IMPORTANT",72,(30, 45, 60), "z4"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "race_week": PhaseSpec(
            phase_kind="race_week", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("bike_easy",        (1, 2, 3), "SUPPORTING", 24, (20, 30, 45), "z2"),
                QuotaRule("mobility",         (1, 1, 2), "SUPPORTING",12, (10, 15, 20), "flow"),
                QuotaRule("rest",             (2, 3, 4), "IMPORTANT",  0, (0, 0, 0),    "rest"),
            ),
        ),
    },
    session_family_recovery_hours={"bike_long": 72, "bike_threshold": 48, "bike_vo2": 48},
    forbidden_sequences=_ENDURANCE_FORBIDDEN + _STRENGTH_FORBIDDEN,
    strength_endurance_interference=True,
))


# ---------------------------------------------------------------------------
# TRIATHLON — olympic distance (extensible to 70.3 / IM via prep_weeks)
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="triathlon.olympic",
    family="triathlon",
    display_name="Olympic Triathlon",
    default_prep_weeks=16, min_prep_weeks=10,
    phase_sequence=("foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=5,
            quotas=(
                QuotaRule("swim_technique",   (1, 2, 3), "IMPORTANT", 24, (30, 40, 50), "technique"),
                QuotaRule("bike_endurance",   (1, 2, 2), "IMPORTANT", 24, (45, 60, 75), "z2"),
                QuotaRule("run_easy",         (1, 2, 3), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "aerobic_base": PhaseSpec(
            phase_kind="aerobic_base", weeks_target=6, weeks_min=4, weeks_max=8,
            hard_days_per_week_max=1, key_days_per_week_max=2, consecutive_training_days_max=6,
            quotas=(
                QuotaRule("swim_aerobic",     (2, 2, 3), "IMPORTANT", 24, (35, 45, 60), "z2"),
                QuotaRule("swim_technique",   (0.5, 1, 2), "SUPPORTING",24,(25, 35, 45), "technique"),
                QuotaRule("bike_endurance",   (1, 2, 3), "IMPORTANT", 24, (60, 75, 100), "z2"),
                QuotaRule("bike_long",        (0.5, 1, 1), "KEY",     72, (75, 100, 150), "z2",
                          can_skip_if_missed=False),
                QuotaRule("run_easy",         (2, 2, 3), "IMPORTANT", 24, (30, 40, 55), "z2"),
                QuotaRule("run_long",         (0.5, 1, 1), "KEY",     72, (55, 75, 100), "z2",
                          can_skip_if_missed=False),
                QuotaRule("strength_full_body",(1, 1.5, 2), "IMPORTANT",48,(30, 40, 50), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=4, weeks_min=3, weeks_max=6,
            hard_days_per_week_max=2, key_days_per_week_max=2, consecutive_training_days_max=6,
            quotas=(
                QuotaRule("swim_threshold",   (0.5, 1, 1), "IMPORTANT",48,(35, 45, 60), "z4"),
                QuotaRule("swim_aerobic",     (1, 2, 2), "IMPORTANT", 24, (35, 45, 60), "z2"),
                QuotaRule("bike_endurance",   (1, 2, 3), "IMPORTANT", 24, (60, 75, 100), "z2"),
                QuotaRule("bike_long",        (0.75, 1, 1), "KEY",    72, (90, 120, 180), "z2",
                          can_skip_if_missed=False),
                QuotaRule("bike_threshold",   (0.5, 1, 1), "IMPORTANT",48,(45, 60, 75), "z4"),
                QuotaRule("run_easy",         (1, 2, 2), "IMPORTANT", 24, (30, 40, 55), "z2"),
                QuotaRule("run_long",         (0.75, 1, 1), "KEY",    72, (65, 85, 110), "z2",
                          can_skip_if_missed=False),
                QuotaRule("run_threshold",    (0, 0.5, 1), "IMPORTANT",48,(25, 35, 50), "z4"),
                QuotaRule("brick_bike_run",   (0.25, 0.5, 1), "IMPORTANT",72,(60, 80, 110), "z3",
                          notes="Bike then straight into run — race-specific transfer"),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(25, 35, 45), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
            ),
        ),
        "specific_prep": PhaseSpec(
            phase_kind="specific_prep", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=2, key_days_per_week_max=2, consecutive_training_days_max=6,
            quotas=(
                QuotaRule("swim_threshold",   (0.5, 1, 1), "IMPORTANT",48,(35, 45, 60), "z4"),
                QuotaRule("swim_open_water",  (0, 0.5, 1), "IMPORTANT",48,(35, 45, 60), "z2-z3"),
                QuotaRule("bike_long",        (0.75, 1, 1), "KEY",    72, (105, 135, 180), "z2-z3",
                          can_skip_if_missed=False),
                QuotaRule("bike_threshold",   (0.5, 1, 1), "IMPORTANT",48,(45, 60, 75), "z4"),
                QuotaRule("run_easy",         (1, 2, 2), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("run_race_pace",    (0.5, 1, 1), "KEY",     72, (35, 45, 60), "z4",
                          can_skip_if_missed=False),
                QuotaRule("brick_bike_run",   (0.5, 1, 1), "KEY",     72, (80, 105, 150), "z3",
                          can_skip_if_missed=False),
                QuotaRule("strength_maintenance",(0.5, 1, 1), "SUPPORTING",72,(20, 30, 40), "rpe6"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING", 12,(15, 20, 30), "flow"),
            ),
        ),
        "taper": PhaseSpec(
            phase_kind="taper", weeks_target=1, weeks_min=1, weeks_max=2,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("swim_aerobic",     (1, 2, 2), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("bike_easy",        (1, 2, 2), "IMPORTANT", 24, (30, 45, 60), "z1-z2"),
                QuotaRule("run_easy",         (1, 2, 2), "IMPORTANT", 24, (20, 30, 40), "z2"),
                QuotaRule("brick_bike_run",   (0, 0.5, 1), "IMPORTANT",72,(45, 60, 80), "z3"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "race_week": PhaseSpec(
            phase_kind="race_week", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("swim_aerobic",     (1, 1, 2), "SUPPORTING", 24, (15, 25, 35), "z2"),
                QuotaRule("bike_easy",        (1, 1, 2), "SUPPORTING", 24, (20, 30, 45), "z1-z2"),
                QuotaRule("run_easy",         (1, 1, 2), "SUPPORTING", 24, (15, 25, 30), "z2"),
                QuotaRule("mobility",         (1, 1, 2), "SUPPORTING",12, (10, 15, 20), "flow"),
                QuotaRule("rest",             (2, 3, 4), "IMPORTANT",  0, (0, 0, 0),    "rest"),
            ),
        ),
    },
    session_family_recovery_hours={
        "run_long": 72, "run_threshold": 48, "run_race_pace": 72,
        "bike_long": 72, "bike_threshold": 48,
        "swim_threshold": 48,
        "tri_brick": 72,
    },
    forbidden_sequences=_ENDURANCE_FORBIDDEN + _STRENGTH_FORBIDDEN + (
        ("brick_bike_run", "run_long"),
        ("brick_bike_run", "bike_long"),
        ("run_long", "brick_bike_run"),
        ("bike_long", "brick_bike_run"),
    ),
    strength_endurance_interference=True,
))


# ---------------------------------------------------------------------------
# STRENGTH — muscle gain (hypertrophy focus)
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="strength.muscle_gain",
    family="strength",
    display_name="Muscle Gain",
    default_prep_weeks=12, min_prep_weeks=6,
    phase_sequence=("foundation", "hypertrophy", "intensification", "deload"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=3, key_days_per_week_max=2, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("strength_full_body",(2, 3, 3), "KEY", 48, (45, 55, 70), "rpe7",
                          can_skip_if_missed=False),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("run_easy",         (0, 1, 2), "SUPPORTING",24, (20, 30, 40), "z2",
                          notes="Optional conditioning — low priority in muscle-gain block"),
            ),
        ),
        "hypertrophy": PhaseSpec(
            phase_kind="hypertrophy", weeks_target=6, weeks_min=4, weeks_max=8,
            hard_days_per_week_max=4, key_days_per_week_max=2, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("strength_upper",   (1, 2, 2), "KEY",       48, (45, 60, 75), "rpe8",
                          can_skip_if_missed=False),
                QuotaRule("strength_lower",   (1, 2, 2), "KEY",       48, (45, 60, 75), "rpe8",
                          can_skip_if_missed=False),
                QuotaRule("strength_hypertrophy",(0, 1, 2), "IMPORTANT",48,(30, 45, 60), "rpe8",
                          notes="Volume accessory work"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("run_easy",         (0, 1, 1), "SUPPORTING",24, (20, 30, 40), "z2"),
                QuotaRule("recovery",         (0, 1, 2), "OPTIONAL",   0, (20, 30, 45), "recovery"),
            ),
        ),
        "intensification": PhaseSpec(
            phase_kind="intensification", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=4, key_days_per_week_max=2, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("strength_upper",   (1, 2, 2), "KEY",       48, (45, 60, 75), "rpe8-9",
                          can_skip_if_missed=False),
                QuotaRule("strength_lower",   (1, 2, 2), "KEY",       48, (45, 60, 75), "rpe8-9",
                          can_skip_if_missed=False),
                QuotaRule("strength_power",   (0.5, 1, 1), "IMPORTANT",48,(30, 45, 60), "rpe7"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "deload": PhaseSpec(
            phase_kind="deload", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=2,
            quotas=(
                QuotaRule("strength_maintenance",(2, 3, 3), "IMPORTANT",48,(30, 40, 50), "rpe6"),
                QuotaRule("mobility",         (2, 3, 3), "SUPPORTING",12, (15, 20, 30), "flow"),
                QuotaRule("recovery",         (1, 2, 2), "IMPORTANT",  0, (25, 35, 45), "recovery"),
            ),
        ),
    },
    session_family_recovery_hours={"strength_hyp": 48, "strength_full": 48, "strength_power": 48},
    forbidden_sequences=_STRENGTH_FORBIDDEN,
))


# ---------------------------------------------------------------------------
# STRENGTH — fat loss (recomposition, higher work rate)
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="strength.fat_loss",
    family="strength",
    display_name="Fat Loss",
    default_prep_weeks=12, min_prep_weeks=4,
    phase_sequence=("foundation", "conditioning_build", "peak", "deload"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=3, key_days_per_week_max=2, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("strength_full_body",(2, 3, 3), "KEY", 48, (35, 45, 55), "rpe7",
                          can_skip_if_missed=False),
                QuotaRule("run_easy",         (1, 2, 3), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "conditioning_build": PhaseSpec(
            phase_kind="conditioning_build", weeks_target=6, weeks_min=4, weeks_max=10,
            hard_days_per_week_max=4, key_days_per_week_max=2, consecutive_training_days_max=5,
            quotas=(
                QuotaRule("strength_full_body",(2, 3, 3), "KEY", 48, (40, 50, 60), "rpe7-8",
                          can_skip_if_missed=False),
                QuotaRule("run_easy",         (1, 2, 3), "IMPORTANT", 24, (25, 35, 50), "z2"),
                QuotaRule("run_intervals",    (0.5, 1, 1), "IMPORTANT",48,(20, 30, 40), "z4-z5"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("recovery",         (0, 1, 2), "OPTIONAL",   0, (20, 30, 45), "recovery"),
            ),
        ),
        "peak": PhaseSpec(
            phase_kind="peak", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=4, key_days_per_week_max=2, consecutive_training_days_max=5,
            quotas=(
                QuotaRule("strength_full_body",(2, 3, 3), "KEY", 48, (35, 45, 55), "rpe8",
                          can_skip_if_missed=False),
                QuotaRule("run_intervals",    (0.5, 1, 1), "KEY", 48, (20, 30, 40), "z5",
                          can_skip_if_missed=False),
                QuotaRule("run_tempo",        (0, 1, 1), "IMPORTANT",48,(20, 30, 40), "z4"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "deload": PhaseSpec(
            phase_kind="deload", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("strength_maintenance",(2, 3, 3), "IMPORTANT",48,(25, 35, 45), "rpe6"),
                QuotaRule("mobility",         (2, 3, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("recovery",         (1, 2, 2), "IMPORTANT",  0, (20, 30, 45), "recovery"),
            ),
        ),
    },
    session_family_recovery_hours={"strength_full": 48, "run_vo2": 48},
    forbidden_sequences=_STRENGTH_FORBIDDEN + (
        ("run_intervals", "strength_lower"),
    ),
))


# ---------------------------------------------------------------------------
# STRENGTH — general (mixed goals, no dominant sport)
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="strength.general",
    family="strength",
    display_name="General Strength",
    default_prep_weeks=12, min_prep_weeks=4,
    phase_sequence=("foundation", "build", "consolidation", "deload"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=3, key_days_per_week_max=2, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("strength_full_body",(2, 3, 3), "KEY", 48, (40, 50, 60), "rpe7",
                          can_skip_if_missed=False),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("run_easy",         (0, 1, 2), "SUPPORTING",24, (20, 30, 40), "z2"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=6, weeks_min=4, weeks_max=8,
            hard_days_per_week_max=3, key_days_per_week_max=2, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("strength_upper",   (1, 1.5, 2), "KEY",     48, (45, 55, 70), "rpe7-8",
                          can_skip_if_missed=False),
                QuotaRule("strength_lower",   (1, 1.5, 2), "KEY",     48, (45, 55, 70), "rpe7-8",
                          can_skip_if_missed=False),
                QuotaRule("run_easy",         (0, 1, 2), "SUPPORTING",24, (25, 35, 45), "z2"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "consolidation": PhaseSpec(
            phase_kind="consolidation", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=3, key_days_per_week_max=2, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("strength_full_body",(2, 3, 3), "KEY", 48, (40, 50, 60), "rpe7",
                          can_skip_if_missed=False),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "deload": PhaseSpec(
            phase_kind="deload", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=2,
            quotas=(
                QuotaRule("strength_maintenance",(2, 3, 3), "IMPORTANT",48,(25, 35, 45), "rpe6"),
                QuotaRule("mobility",         (2, 3, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("recovery",         (1, 2, 2), "IMPORTANT",  0, (20, 30, 45), "recovery"),
            ),
        ),
    },
    session_family_recovery_hours={"strength_full": 48},
    forbidden_sequences=_STRENGTH_FORBIDDEN,
))


# ---------------------------------------------------------------------------
# GENERAL FITNESS — balanced default
# ---------------------------------------------------------------------------
_register(GoalConfig(
    key="general.fitness",
    family="general",
    display_name="General Fitness",
    default_prep_weeks=12, min_prep_weeks=4,
    phase_sequence=("foundation", "build", "consolidation", "deload"),
    phase_specs={
        "foundation": PhaseSpec(
            phase_kind="foundation", weeks_target=2, weeks_min=1, weeks_max=3,
            hard_days_per_week_max=2, key_days_per_week_max=1, consecutive_training_days_max=3,
            quotas=(
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 50), "rpe7"),
                QuotaRule("run_easy",         (1, 2, 3), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "build": PhaseSpec(
            phase_kind="build", weeks_target=6, weeks_min=4, weeks_max=8,
            hard_days_per_week_max=3, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (35, 45, 55), "rpe7-8"),
                QuotaRule("run_easy",         (1, 2, 3), "IMPORTANT", 24, (25, 35, 50), "z2"),
                QuotaRule("run_intervals",    (0, 0.5, 1), "IMPORTANT",48,(20, 30, 40), "z5"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "consolidation": PhaseSpec(
            phase_kind="consolidation", weeks_target=3, weeks_min=2, weeks_max=4,
            hard_days_per_week_max=3, key_days_per_week_max=1, consecutive_training_days_max=4,
            quotas=(
                QuotaRule("strength_full_body",(1, 2, 2), "IMPORTANT",48, (30, 40, 55), "rpe7"),
                QuotaRule("run_easy",         (2, 2, 3), "IMPORTANT", 24, (25, 35, 45), "z2"),
                QuotaRule("mobility",         (1, 2, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
            ),
        ),
        "deload": PhaseSpec(
            phase_kind="deload", weeks_target=1, weeks_min=1, weeks_max=1,
            hard_days_per_week_max=1, key_days_per_week_max=1, consecutive_training_days_max=2,
            quotas=(
                QuotaRule("mobility",         (2, 3, 3), "SUPPORTING",12, (15, 20, 25), "flow"),
                QuotaRule("recovery",         (1, 2, 2), "IMPORTANT",  0, (20, 30, 45), "recovery"),
            ),
        ),
    },
    session_family_recovery_hours={"strength_full": 48},
    forbidden_sequences=_STRENGTH_FORBIDDEN,
))


# ---------------------------------------------------------------------------
# Public API — resolving goal & phase plans
# ---------------------------------------------------------------------------

# Legacy aliases mapping the coach dashboard's DNA strings to canonical goal keys
_GOAL_ALIASES: dict[str, str] = {
    "marathon": "running.marathon", "run_marathon": "running.marathon",
    "running.marathon": "running.marathon",
    "half_marathon": "running.half_marathon", "half marathon": "running.half_marathon",
    "hm": "running.half_marathon", "running.half_marathon": "running.half_marathon",
    "10k": "running.10k", "run_10k": "running.10k", "running.10k": "running.10k",
    "5k": "running.5k", "run_5k": "running.5k", "running.5k": "running.5k",
    "triathlon": "triathlon.olympic",
    "triathlon.olympic": "triathlon.olympic",
    "triathlon.sprint": "triathlon.olympic",   # sprint uses olympic template compressed
    "triathlon.70_3": "triathlon.olympic",     # 70.3 stretched
    "triathlon.ironman": "triathlon.olympic",  # IM stretched — TODO dedicated config
    "cycling": "cycling.endurance",
    "cycling.endurance": "cycling.endurance",
    "muscle_gain": "strength.muscle_gain", "strength.muscle_gain": "strength.muscle_gain",
    "hypertrophy": "strength.muscle_gain",
    "fat_loss": "strength.fat_loss", "strength.fat_loss": "strength.fat_loss",
    "recomp": "strength.fat_loss", "weight_loss": "strength.fat_loss",
    "strength": "strength.general", "strength.general": "strength.general",
    "general_fitness": "general.fitness", "general.fitness": "general.fitness",
    "longevity": "general.fitness", "general.longevity": "general.fitness",
    "fitness": "general.fitness",
}


def canonicalise_goal_key(raw: Optional[str]) -> str:
    """Map a free-text goal identifier to a registered SPORT_CONFIGS key.

    Falls back to 'general.fitness' if the input is empty/unknown — never
    raises. Case-insensitive.
    """
    k = (raw or "").strip().lower().replace(" ", "_")
    if not k:
        return "general.fitness"
    if k in SPORT_CONFIGS:
        return k
    if k in _GOAL_ALIASES:
        return _GOAL_ALIASES[k]
    return "general.fitness"


def get_goal_config(goal_key: str) -> GoalConfig:
    ck = canonicalise_goal_key(goal_key)
    return SPORT_CONFIGS[ck]


def resolve_phase_plan(goal_key: str, prep_weeks: int) -> list[PhaseSpec]:
    """Return the phase sequence with weeks_target adjusted to the available
    prep window.

    Compression order:
       1. If prep_weeks >= sum(default weeks), stretch aerobic_base or build.
       2. If prep_weeks < sum(default weeks), compress uniformly with weekly
          floors from each phase.weeks_min.
       3. race_week and taper are protected (never compressed below weeks_min).
    """
    cfg = get_goal_config(goal_key)
    ordered = [cfg.phase_specs[k] for k in cfg.phase_sequence if k in cfg.phase_specs]
    total_default = sum(p.weeks_target for p in ordered)
    total_min = sum(p.weeks_min for p in ordered)
    prep_weeks = max(1, int(prep_weeks))
    if prep_weeks <= 0:
        return list(ordered)

    # ---- Case A: enough or more time than default → stretch main phase(s)
    if prep_weeks >= total_default:
        surplus = prep_weeks - total_default
        # Distribute surplus into build/aerobic_base/hypertrophy first (main
        # driver phases), capped at weeks_max.
        result = [copy.copy(p) for p in ordered]
        stretch_targets = [i for i, p in enumerate(result)
                           if p.phase_kind in ("aerobic_base", "build", "hypertrophy",
                                                "conditioning_build")]
        if not stretch_targets:
            stretch_targets = list(range(len(result)))
        i = 0
        loops = 0
        while surplus > 0 and loops < 200:
            idx = stretch_targets[i % len(stretch_targets)]
            p = result[idx]
            if p.weeks_target < p.weeks_max:
                result[idx] = _phase_with_weeks(p, p.weeks_target + 1)
                surplus -= 1
            i += 1
            loops += 1
            # Break if we've cycled and no one can stretch anymore
            if i % len(stretch_targets) == 0:
                if not any(result[j].weeks_target < result[j].weeks_max for j in stretch_targets):
                    break
        return result

    # ---- Case B: not enough time — compress
    if prep_weeks < total_min:
        # Hard minimum floor — return plan at weeks_min for each phase.
        # Callers can surface a warning that the plan is compressed to its floor.
        return [_phase_with_weeks(p, p.weeks_min) for p in ordered]

    result = [copy.copy(p) for p in ordered]
    deficit = total_default - prep_weeks
    # Preserve race_week and taper; compress others toward weeks_min
    compress_targets = [i for i, p in enumerate(result)
                        if p.phase_kind not in ("race_week", "taper")]
    if not compress_targets:
        compress_targets = list(range(len(result)))
    i = 0
    loops = 0
    while deficit > 0 and loops < 200:
        idx = compress_targets[i % len(compress_targets)]
        p = result[idx]
        if p.weeks_target > p.weeks_min:
            result[idx] = _phase_with_weeks(p, p.weeks_target - 1)
            deficit -= 1
        i += 1
        loops += 1
        if i % len(compress_targets) == 0:
            if not any(result[j].weeks_target > result[j].weeks_min for j in compress_targets):
                break
    # If still deficit > 0, compress taper last (never below its weeks_min)
    if deficit > 0:
        for idx, p in enumerate(result):
            while deficit > 0 and result[idx].weeks_target > result[idx].weeks_min:
                result[idx] = _phase_with_weeks(result[idx], result[idx].weeks_target - 1)
                deficit -= 1
    return result


def _phase_with_weeks(p: PhaseSpec, new_weeks: int) -> PhaseSpec:
    """Return a copy of `p` with weeks_target = new_weeks. Preserves the rest."""
    return PhaseSpec(
        phase_kind=p.phase_kind,
        weeks_target=int(new_weeks),
        weeks_min=p.weeks_min, weeks_max=p.weeks_max,
        quotas=p.quotas,
        hard_days_per_week_max=p.hard_days_per_week_max,
        key_days_per_week_max=p.key_days_per_week_max,
        consecutive_training_days_max=p.consecutive_training_days_max,
        concurrent_notes=p.concurrent_notes,
    )


def required_exposures_for_phase(goal_key: str, phase_kind: str) -> list[QuotaRule]:
    """Return the list of QuotaRule for a specific phase within a goal."""
    cfg = get_goal_config(goal_key)
    ps = cfg.phase_specs.get(phase_kind)
    if not ps:
        return []
    return list(ps.quotas)


def session_kind_meta(kind: str) -> dict:
    return SESSION_KIND_REGISTRY.get(kind, {
        "modality": None, "intensity_class": INTENSITY_MODERATE,
        "hard": False, "family": kind,
    })


def is_hard_session(kind: str) -> bool:
    return bool(session_kind_meta(kind).get("hard"))


def is_key_intensity(kind: str) -> bool:
    return session_kind_meta(kind).get("intensity_class") == INTENSITY_KEY


def session_family(kind: str) -> str:
    return session_kind_meta(kind).get("family", kind)


def is_forbidden_sequence(prev_kind: str, next_kind: str, goal_key: str) -> bool:
    """Return True if `prev → next` (chronologically) is disallowed for this goal."""
    cfg = get_goal_config(goal_key)
    prev_family = session_family(prev_kind)
    next_family = session_family(next_kind)
    for a, b in cfg.forbidden_sequences:
        # Match either exact kind or family name
        if (a == prev_kind or a == prev_family) and (b == next_kind or b == next_family):
            return True
    return False


def session_recovery_hours(kind: str, goal_key: str, default: int = 24) -> int:
    """Minimum recovery hours before another session of the same family."""
    cfg = get_goal_config(goal_key)
    fam = session_family(kind)
    return cfg.session_family_recovery_hours.get(fam, default)


# ---------------------------------------------------------------------------
# Invariant checks — run on import to catch config-authoring mistakes early
# ---------------------------------------------------------------------------

def _validate_registry() -> None:
    for k, cfg in SPORT_CONFIGS.items():
        assert cfg.key == k, f"Config key mismatch: {k} vs {cfg.key}"
        # Every phase in phase_sequence must exist in phase_specs
        for pk in cfg.phase_sequence:
            assert pk in cfg.phase_specs, f"[{k}] phase_sequence references undefined phase '{pk}'"
        # Every phase_kind used in phase_specs must be in phase_sequence
        for pk in cfg.phase_specs.keys():
            assert pk in cfg.phase_sequence, f"[{k}] phase_specs has orphan phase '{pk}'"
        # Every quota kind must exist in SESSION_KIND_REGISTRY
        for pk, ps in cfg.phase_specs.items():
            assert ps.weeks_min <= ps.weeks_target <= ps.weeks_max, (
                f"[{k}/{pk}] weeks bounds invalid: min={ps.weeks_min} "
                f"target={ps.weeks_target} max={ps.weeks_max}"
            )
            for q in ps.quotas:
                assert q.kind in SESSION_KIND_REGISTRY, (
                    f"[{k}/{pk}] unknown session kind '{q.kind}'"
                )
                lo, tgt, hi = q.exposures_per_week
                assert lo <= tgt <= hi, (
                    f"[{k}/{pk}/{q.kind}] exposures_per_week bounds invalid"
                )
                dlo, dtgt, dhi = q.duration_min
                assert dlo <= dtgt <= dhi, (
                    f"[{k}/{pk}/{q.kind}] duration bounds invalid"
                )
                # KEY sessions must not silently skip
                if q.priority == "KEY" and q.can_skip_if_missed:
                    # Emit a warning but don't fail — some KEY sessions may
                    # legitimately allow skip (e.g. optional taper key).
                    pass


_validate_registry()


__all__ = [
    "GoalConfig", "PhaseSpec", "QuotaRule",
    "SPORT_CONFIGS", "SESSION_KIND_REGISTRY",
    "canonicalise_goal_key", "get_goal_config",
    "resolve_phase_plan", "required_exposures_for_phase",
    "session_kind_meta", "is_hard_session", "is_key_intensity",
    "session_family", "is_forbidden_sequence", "session_recovery_hours",
    "MODALITY_RUN", "MODALITY_CYCLE", "MODALITY_SWIM", "MODALITY_STRENGTH",
    "MODALITY_MOBILITY", "MODALITY_RECOVERY", "MODALITY_ACTIVATION", "MODALITY_BRICK",
    "INTENSITY_KEY", "INTENSITY_HARD", "INTENSITY_MODERATE", "INTENSITY_EASY",
    "INTENSITY_RECOVERY", "INTENSITY_REST",
]
