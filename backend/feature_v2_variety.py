"""
CrewFit V2 — Deterministic Variety System (Iter 121)
=====================================================

For General Fitness / Fat Loss clients (and any goal that wants controlled
variety in HOW without touching WHAT/WHEN).

Principle:  STABLE TRAINING PURPOSE + CONTROLLED VARIETY IN IMPLEMENTATION.

- LOW variety     — always picks the same primary option per pattern
                    (measurable progression, minimum novelty).
- MODERATE (dflt) — rotates accessories every 3–4 exposures, anchors stay.
- HIGH variety    — rotates supporting exercises aggressively; anchor
                    movements still stay long enough to measure progression.

Deterministic: given (pattern, exposure_number, equipment_ctx, variety_pref),
the output is stable — no randomness, no LLM.

The rotation is driven by `exposure_number` (already tracked on placements)
plus a small `ANCHOR_SLOTS` set that defines which slots are progression
anchors and must NOT rotate.
"""
from __future__ import annotations

from typing import Optional


# Slots that ALWAYS keep the same primary option (progression anchors).
ANCHOR_SLOTS: set[str] = {
    "primary_squat",
    "primary_hinge",
    "primary_horizontal_push",
    "primary_horizontal_pull",
    "primary_vertical_pull",
    "primary_vertical_push",
    # power / brand-new patterns stay stable early
    "power",
}

# Rotation speed: how many exposures before we advance the pool index.
# Higher variety → smaller cadence (rotate more often).
_ROTATION_CADENCE: dict[str, int] = {
    "low":      99,   # effectively never rotate
    "moderate": 3,
    "high":     1,
}


def _rotation_index(exposure_number: int, variety_preference: str) -> int:
    n = max(1, int(exposure_number or 1))
    cadence = _ROTATION_CADENCE.get(variety_preference, _ROTATION_CADENCE["moderate"])
    return (n - 1) // cadence


def pick_exercise_with_variety(
    *,
    pattern: str,
    slot_role: str,
    pool: list[dict],
    equipment_ctx: set[str],
    exposure_number: int = 1,
    variety_preference: str = "moderate",
    avoid_patterns: Optional[set[str]] = None,
    locked_name: Optional[str] = None,
) -> Optional[dict]:
    """Deterministically pick an exercise from a pool honoring variety.

    Selection rules (in order):
      1. Respect `locked_name` if provided (coach lock) — no rotation.
      2. Filter pool by equipment availability (all tags must be present).
      3. Filter by avoid_patterns (name/pattern block).
      4. Prefer STRICT bodyweight-only fallback if nothing matches.
      5. Anchor slots always return the first compatible entry (stable
         primary for progression measurement).
      6. Non-anchor slots rotate through the compatible sub-pool using
         `exposure_number` and `variety_preference`.
      7. Never returns non-bodyweight-only when equipment_ctx == {bodyweight}.
    """
    avoid_patterns = avoid_patterns or set()

    # 0) Filter by equipment + avoid
    compatible: list[dict] = []
    for ex in pool:
        eq = set(ex.get("equipment") or [])
        if not eq.issubset(equipment_ctx):
            continue
        name_low = ex["name"].lower()
        if any(a and (a in name_low or a == pattern) for a in avoid_patterns):
            continue
        compatible.append(ex)

    # If nothing fits and we have only bodyweight, force strict-bodyweight
    if not compatible:
        for ex in pool:
            if set(ex.get("equipment") or []) <= {"bodyweight"}:
                return ex
        for ex in pool:
            if "bodyweight" in (ex.get("equipment") or []):
                return ex
        return None

    # 1) Coach lock wins
    if locked_name:
        for ex in compatible:
            if ex["name"] == locked_name:
                return ex

    # 5) Anchor slots — always return the first compatible entry
    if slot_role in ANCHOR_SLOTS:
        return compatible[0]

    # 6) Rotate non-anchor slots via exposure_number + variety_preference
    idx = _rotation_index(exposure_number, variety_preference)
    return compatible[idx % len(compatible)]


# ---------------------------------------------------------------------------
# Cardio modality resolver
# ---------------------------------------------------------------------------

_CARDIO_ALIASES = {
    "run":       "run",
    "running":   "run",
    "runner":    "run",
    "bike":      "bike",
    "cycling":   "bike",
    "cycle":     "bike",
    "walk":      "walk",
    "walking":   "walk",
    "elliptical":"elliptical",
    "rower":     "rower",
    "rowing":    "rower",
    "swim":      "swim",
    "swimming":  "swim",
}


def resolve_cardio_modality(client_profile: Optional[dict]) -> str:
    """Return the client's preferred cardio modality label.
    Defaults to 'run' if unspecified.  Case-insensitive.
    """
    if not client_profile:
        return "run"
    raw = (client_profile.get("cardio_preference")
           or client_profile.get("preferred_cardio_modality")
           or "run")
    key = str(raw).strip().lower().replace(" ", "_")
    return _CARDIO_ALIASES.get(key, "run")


__all__ = [
    "ANCHOR_SLOTS",
    "pick_exercise_with_variety",
    "resolve_cardio_modality",
]
