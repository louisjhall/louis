"""
CrewFit V2 — Deterministic Variety System (Iter 121b block-based)
==================================================================

Principle:  STABLE TRAINING PURPOSE + CONTROLLED VARIETY IN IMPLEMENTATION.

Variety operates at three tiers, in decreasing rate:

  1. Movement PATTERN  — never changes for a given slot (squat is always
                         a squat pattern; horizontal_pull is always horizontal_pull).
  2. Anchor EXERCISE   — the primary exercise for each anchor slot is stable
                         WITHIN a programming block, refreshed between blocks.
  3. Accessory/Trunk   — rotates every exposure at HIGH variety, less often
                         at MODERATE, effectively never at LOW.

A "block" is `block_length` exposures. Within a block, anchor exercises are
pinned so progression can be measured. When the block advances, anchors are
refreshed by walking the compatible pool one step.

Block lengths per variety level:
  LOW      : 12 exposures    (very slow anchor rotation)
  MODERATE :  6 exposures    (rotate anchors twice per ~12-exposure phase)
  HIGH     :  4 exposures    (rotate anchors every ~4 exposures)

Beginners are clamped to at-most MODERATE regardless of preference — they
need repetition to establish movement quality and measurable progression.

Session A / Session B pattern rotation:
  For HIGH variety clients on a full-body kind, alternate between two
  pattern schemes so consecutive exposures do not use identical patterns:
    Session A: squat / horizontal_push / hinge / horizontal_pull / trunk
    Session B: squat / vertical_push  / hinge / vertical_pull  / trunk
  (The current strength_full_body template already includes both hinge and
  horizontal patterns; Session B lets us swap the push and pull axes.)
"""
from __future__ import annotations

from typing import Optional


# Slots that pin their PRIMARY exercise within a block (progression anchors).
ANCHOR_SLOTS: set[str] = {
    "primary_squat",
    "primary_hinge",
    "primary_horizontal_push",
    "primary_horizontal_pull",
    "primary_vertical_pull",
    "primary_vertical_push",
    "power",
}

# Non-anchor rotation cadence (in exposures) per variety level.
_ACCESSORY_CADENCE: dict[str, int] = {
    "low":      99,
    "moderate":  3,
    "high":      1,
}

# Anchor block length (in exposures) — anchors are pinned within a block
# and refresh at block boundaries.
_ANCHOR_BLOCK_LENGTH: dict[str, int] = {
    "low":      12,
    "moderate":  6,
    "high":      4,
}


def _effective_variety(
    variety_preference: str, training_experience: Optional[str]
) -> str:
    v = (variety_preference or "moderate").lower()
    exp = (training_experience or "").lower()
    # Beginners never get HIGH — they need repetition
    if exp in ("beginner", "novice", "new") and v == "high":
        return "moderate"
    return v if v in _ACCESSORY_CADENCE else "moderate"


def _anchor_block_index(exposure_number: int, variety_preference: str,
                         training_experience: Optional[str]) -> int:
    v = _effective_variety(variety_preference, training_experience)
    block_len = _ANCHOR_BLOCK_LENGTH.get(v, _ANCHOR_BLOCK_LENGTH["moderate"])
    n = max(1, int(exposure_number or 1))
    return (n - 1) // block_len


def _accessory_index(exposure_number: int, variety_preference: str,
                      training_experience: Optional[str]) -> int:
    v = _effective_variety(variety_preference, training_experience)
    cadence = _ACCESSORY_CADENCE.get(v, _ACCESSORY_CADENCE["moderate"])
    n = max(1, int(exposure_number or 1))
    return (n - 1) // cadence


def pick_exercise_with_variety(
    *,
    pattern: str,
    slot_role: str,
    pool: list[dict],
    equipment_ctx: set[str],
    exposure_number: int = 1,
    variety_preference: str = "moderate",
    training_experience: Optional[str] = None,
    avoid_patterns: Optional[set[str]] = None,
    locked_name: Optional[str] = None,
) -> Optional[dict]:
    """Deterministically pick an exercise from a pool honoring variety.

    - Movement PATTERN never changes for the slot.
    - Anchor slot primaries rotate at block boundaries (block_length
      exposures) so progression stays measurable but exercises refresh.
    - Non-anchor slots rotate every `accessory_cadence` exposures.
    - Beginners are clamped to at-most MODERATE regardless of preference.
    - Coach `locked_name` always wins.
    """
    avoid_patterns = avoid_patterns or set()

    compatible: list[dict] = []
    for ex in pool:
        eq = set(ex.get("equipment") or [])
        if not eq.issubset(equipment_ctx):
            continue
        name_low = ex["name"].lower()
        if any(a and (a in name_low or a == pattern) for a in avoid_patterns):
            continue
        compatible.append(ex)

    # Nothing fits — fall back to strict bodyweight, then loose bodyweight
    if not compatible:
        for ex in pool:
            if set(ex.get("equipment") or []) <= {"bodyweight"}:
                return ex
        for ex in pool:
            if "bodyweight" in (ex.get("equipment") or []):
                return ex
        return None

    # Coach lock wins
    if locked_name:
        for ex in compatible:
            if ex["name"] == locked_name:
                return ex

    if slot_role in ANCHOR_SLOTS:
        # Rotate anchors at block boundaries
        idx = _anchor_block_index(exposure_number, variety_preference,
                                   training_experience)
        return compatible[idx % len(compatible)]

    # Non-anchor accessories rotate faster
    idx = _accessory_index(exposure_number, variety_preference,
                            training_experience)
    return compatible[idx % len(compatible)]


# ---------------------------------------------------------------------------
# Session A / B pattern rotation for HIGH-variety full-body sessions
# ---------------------------------------------------------------------------
# For strength_full_body sessions and HIGH-variety clients we alternate the
# push/pull axis so consecutive exposures don't drill the same patterns.
# The template slots still map to their pattern; we just remap the pattern
# for two of the slots on odd exposures.

_FULL_BODY_SESSION_B_REMAP = {
    "primary_horizontal_push": "vertical_push",
    "primary_horizontal_pull": "vertical_pull",
}


def full_body_pattern_remap(exposure_number: int, variety_preference: str,
                             training_experience: Optional[str],
                             kind: str) -> dict[str, str]:
    """Return a slot_role → alternative_pattern remap for HIGH-variety
    full-body strength sessions. Empty dict for LOW/MODERATE or non-full-body.
    """
    if kind != "strength_full_body":
        return {}
    v = _effective_variety(variety_preference, training_experience)
    if v != "high":
        return {}
    # Alternate every anchor block (not every exposure) so within a block the
    # patterns stay consistent enough to progress on.
    block_idx = _anchor_block_index(exposure_number, variety_preference,
                                     training_experience)
    if block_idx % 2 == 1:
        return dict(_FULL_BODY_SESSION_B_REMAP)
    return {}


# ---------------------------------------------------------------------------
# Cardio modality resolver
# ---------------------------------------------------------------------------

_CARDIO_ALIASES = {
    "run":       "run", "running":   "run", "runner":    "run",
    "bike":      "bike","cycling":   "bike","cycle":     "bike",
    "walk":      "walk","walking":   "walk",
    "elliptical":"elliptical",
    "rower":     "rower","rowing":  "rower",
    "swim":      "swim","swimming":  "swim",
    "no_preference": "run", "none": "run", "":"run",
}


def resolve_cardio_modality(client_profile: Optional[dict]) -> str:
    if not client_profile:
        return "run"
    raw = (client_profile.get("cardio_preference")
           or client_profile.get("preferred_cardio_modality") or "run")
    key = str(raw).strip().lower().replace(" ", "_")
    return _CARDIO_ALIASES.get(key, "run")


# ---------------------------------------------------------------------------
# Post-deload phase continuation
# ---------------------------------------------------------------------------

# For open-ended goals (General Fitness / Fat Loss) the phase sequence
# doesn't stop after `deload`. Coach automation loops the client back into
# a fresh `build` block (skipping `foundation` because they already have it).
_POST_DELOAD_NEXT: dict[str, str] = {
    "general.fitness":   "build",
    "strength.fat_loss": "build",
    "strength.general":  "build",
}


def next_phase_after_deload(goal_key: str) -> Optional[str]:
    """Return the next phase kind after a completed `deload` for open-ended
    goals. Returns None for finite race-training goals (marathon etc.)."""
    return _POST_DELOAD_NEXT.get(goal_key)


__all__ = [
    "ANCHOR_SLOTS",
    "pick_exercise_with_variety",
    "full_body_pattern_remap",
    "resolve_cardio_modality",
    "next_phase_after_deload",
]
