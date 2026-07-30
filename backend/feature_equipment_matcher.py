"""
feature_equipment_matcher — Strict Equipment Matching (Phase 2 of MASTER FIX PROMPT).

Hard validation gates: bench exercises REQUIRE a bench, cable exercises REQUIRE
a cable stack, barbell exercises REQUIRE a barbell, etc. No silent drops —
when equipment is missing, we flag the workout with `needs_coach_review` and a
client-visible `change_reason`.

Two entry points:
  * `validate_exercise_equipment(exercise, available)` — pure check
  * `enforce_equipment_gate(workout, available, hotel_context)` — mutates the
    workout in place, adds needs_coach_review + change_reason on failure

Available equipment is a normalised set derived from:
  * The client profile (`profile.equipment` — home/gym setup)
  * OR the hotel_profile equipment map (during a layover)
  * OR the empty set (bodyweight-only fallback)
"""
from __future__ import annotations

import re
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Equipment taxonomy — canonical set used across the app
# ---------------------------------------------------------------------------
CANONICAL_EQUIPMENT = {
    "bodyweight",           # always available (no equipment needed)
    "dumbbells", "adjustable_dumbbells",
    "barbell", "olympic_barbell", "ez_bar", "trap_bar",
    "bench", "flat_bench", "adjustable_bench", "incline_bench",
    "cable_stack", "cable_machine",
    "smith_machine",
    "leg_press", "leg_extension", "leg_curl",
    "chest_press_machine", "shoulder_press_machine",
    "lat_pulldown", "seated_cable_row",
    "pull_up_bar", "chin_up_bar",
    "kettlebell",
    "resistance_bands",
    "treadmill", "stationary_bike", "rowing_machine", "elliptical",
    "medicine_ball", "slam_ball",
    "trx", "suspension_trainer",
    "yoga_mat",
    "foam_roller",
    "pool",
    "box", "plyo_box",
    "wall",
}

# Aliases seen in real client data / hotel profiles — normalise them into the
# canonical set. Keys are lowered.
EQUIPMENT_ALIASES = {
    "db": "dumbbells", "dumbbell": "dumbbells",
    "adjustable dumbbells": "adjustable_dumbbells",
    "bb": "barbell", "olympic bar": "olympic_barbell",
    "cable": "cable_stack", "cables": "cable_stack",
    "cable machine": "cable_stack", "functional trainer": "cable_stack",
    "pull up bar": "pull_up_bar", "pullup bar": "pull_up_bar", "chinup bar": "chin_up_bar",
    "kettlebells": "kettlebell", "kb": "kettlebell",
    "bands": "resistance_bands",
    "rower": "rowing_machine",
    "bike": "stationary_bike", "exercise bike": "stationary_bike",
    "cross trainer": "elliptical",
    "run track": "treadmill",  # if a hotel says "run track"
    "mat": "yoga_mat", "gym mat": "yoga_mat", "exercise mat": "yoga_mat",
    "med ball": "medicine_ball",
    "leg press machine": "leg_press",
    "chest press": "chest_press_machine",
    "shoulder press": "shoulder_press_machine",
    "lat pull down": "lat_pulldown", "lat pull-down": "lat_pulldown",
    "cable row": "seated_cable_row",
    "squat rack": "barbell", "power rack": "barbell", "rack": "barbell",
    "gym": "full_gym_marker",  # marker only — expands via preset
    "hotel gym": "full_gym_marker",
    "home gym": "full_gym_marker",
    # Iter 128m — Full Commercial Gym preset: permanent HOME setup expressing
    # "typical well-equipped commercial gym". Deliberately CONSERVATIVE —
    # does NOT imply hack squats, GHDs, belt squats, sled, hip thrust machines,
    # SkiErg, assault bike, specialty bars, etc. Any of those may be added
    # by the client explicitly on top.
    "commercial gym": "full_commercial_gym_marker",
    "full commercial gym": "full_commercial_gym_marker",
    "commercial_gym_standard": "full_commercial_gym_marker",
    "full_commercial_gym": "full_commercial_gym_marker",
    "no equipment": "bodyweight", "none": "bodyweight",
}

# When a client says "full_gym_marker" or when hotel gym_type=full_gym, expand
# to this canonical set. (Kept lean — this marker is also used by hotel gyms
# where we do NOT want to assume machines exist.)
FULL_GYM_EXPANSION = {
    "dumbbells", "barbell", "bench", "cable_stack", "smith_machine",
    "treadmill", "stationary_bike", "rowing_machine", "kettlebell",
    "pull_up_bar", "yoga_mat", "medicine_ball",
}

# Iter 128m — Full Commercial Gym preset (permanent HOME setup only).
# Conservative inventory of equipment that MOST full commercial gyms carry.
# Does NOT include specialist / bodybuilding machines (hack squat, GHD, belt
# squat, hip thrust machine, sled, SkiErg, safety bar, trap bar, etc.) —
# those require explicit client confirmation on top of this preset.
FULL_COMMERCIAL_GYM_EXPANSION = {
    # Free weights
    "dumbbells", "adjustable_dumbbells",
    "barbell", "olympic_barbell",
    "bench", "adjustable_bench", "flat_bench", "incline_bench",
    "kettlebell",
    # Racks / smith
    "smith_machine",
    # Cables + functional
    "cable_stack",
    "lat_pulldown", "seated_cable_row",
    # Machines (common commercial subset only)
    "leg_press", "leg_extension", "leg_curl",
    "chest_press_machine", "shoulder_press_machine",
    # Accessories
    "pull_up_bar",
    "resistance_bands",
    "yoga_mat", "medicine_ball",
    # Cardio
    "treadmill", "stationary_bike", "rowing_machine", "elliptical",
}


def _norm_equip_token(s: str) -> Optional[str]:
    """Normalise a single equipment string into a canonical key or None."""
    if not s:
        return None
    k = str(s).strip().lower().replace("-", " ").replace("_", " ")
    k = re.sub(r"\s+", " ", k).strip()
    # exact hit on canonical (with spaces→underscores)
    key_us = k.replace(" ", "_")
    if key_us in CANONICAL_EQUIPMENT:
        return key_us
    # alias hit
    if k in EQUIPMENT_ALIASES:
        return EQUIPMENT_ALIASES[k]
    if key_us in EQUIPMENT_ALIASES:
        return EQUIPMENT_ALIASES[key_us]
    return None


def normalise_available(items: Any) -> set[str]:
    """
    Turn a client's equipment list / hotel's equipment dict into a normalised
    set of canonical equipment keys. Always includes 'bodyweight'.
    """
    out: set[str] = {"bodyweight"}
    if not items:
        return out

    # dict form (hotel_profile equipment map: {key: bool})
    if isinstance(items, dict):
        for k, v in items.items():
            if not v:
                continue
            n = _norm_equip_token(str(k))
            if n == "full_gym_marker":
                out |= FULL_GYM_EXPANSION
            elif n == "full_commercial_gym_marker":
                out |= FULL_COMMERCIAL_GYM_EXPANSION
            elif n:
                out.add(n)
        return out

    # list / iterable form
    if isinstance(items, (list, tuple, set)):
        for it in items:
            n = _norm_equip_token(str(it))
            if n == "full_gym_marker":
                out |= FULL_GYM_EXPANSION
            elif n == "full_commercial_gym_marker":
                out |= FULL_COMMERCIAL_GYM_EXPANSION
            elif n:
                out.add(n)
    return out


# ---------------------------------------------------------------------------
# Exercise → required equipment inference
# ---------------------------------------------------------------------------

# Ordered list of (regex, required_keys_any_of) — first match wins.
# `any_of` means: the client must have AT LEAST ONE of these equipment keys.
# E.g. "dumbbell OR kettlebell" is fine for many press variants.
EQUIPMENT_REGEXES: list[tuple[re.Pattern, tuple[str, ...]]] = [
    # Barbell family — barbell + bench for bench press variants
    (re.compile(r"\bbarbell.*bench press\b", re.I), ("barbell",)),
    (re.compile(r"\bbench press\b", re.I),          ("bench",)),  # any-bench check
    (re.compile(r"\bincline (dumbbell|db) press\b", re.I), ("bench",)),
    (re.compile(r"\bdecline (dumbbell|db) press\b", re.I), ("bench",)),
    (re.compile(r"\bbench (fly|flye|dip|press)\b", re.I), ("bench",)),

    # Barbell-only lifts
    (re.compile(r"\b(back|front|zercher) squat\b", re.I),     ("barbell", "smith_machine")),
    (re.compile(r"\bbarbell (row|deadlift|rdl|clean|snatch|press|shrug|curl)\b", re.I), ("barbell",)),
    (re.compile(r"\bconventional deadlift\b", re.I),          ("barbell",)),
    (re.compile(r"\brdl\b", re.I),                            ("barbell", "dumbbells", "kettlebell")),
    (re.compile(r"\bromanian deadlift\b", re.I),              ("barbell", "dumbbells", "kettlebell")),
    (re.compile(r"\bhip thrust\b", re.I),                     ("barbell", "dumbbells", "bench")),

    # Cable
    (re.compile(r"\bcable\b", re.I),                          ("cable_stack",)),
    (re.compile(r"\btricep pushdown\b", re.I),                ("cable_stack", "resistance_bands")),
    (re.compile(r"\blat pulldown\b", re.I),                   ("cable_stack",)),
    (re.compile(r"\bface pull\b", re.I),                      ("cable_stack", "resistance_bands")),

    # Machine
    (re.compile(r"\bsmith machine\b", re.I),                  ("smith_machine",)),
    (re.compile(r"\bleg press\b", re.I),                      ("leg_press",)),
    (re.compile(r"\bleg extension\b", re.I),                  ("leg_extension",)),
    (re.compile(r"\bleg curl\b", re.I),                       ("leg_curl",)),
    (re.compile(r"\bhack squat\b", re.I),                     ("leg_press", "smith_machine")),

    # Dumbbell / kettlebell family (any of)
    (re.compile(r"\b(dumbbell|db)\b", re.I),                  ("dumbbells",)),
    (re.compile(r"\bkettlebell\b", re.I),                     ("kettlebell",)),
    (re.compile(r"\b(goblet|farmer|suitcase)\b", re.I),       ("dumbbells", "kettlebell")),
    (re.compile(r"\bfarmer'?s walk\b", re.I),                 ("dumbbells", "kettlebell")),

    # Bench-required accessory
    (re.compile(r"\b(chest supported|prone) row\b", re.I),    ("bench",)),
    (re.compile(r"\bskull crushers?\b", re.I),                ("bench", "dumbbells")),

    # Pull-up family
    (re.compile(r"\b(pull[- ]?up|chin[- ]?up|muscle[- ]?up)\b", re.I), ("pull_up_bar",)),

    # Cardio machines
    (re.compile(r"\btreadmill\b", re.I),                      ("treadmill",)),
    (re.compile(r"\bstationary bike\b", re.I),                ("stationary_bike",)),
    (re.compile(r"\brow(er|ing)\b", re.I),                    ("rowing_machine",)),
    (re.compile(r"\bassault bike\b", re.I),                   ("stationary_bike",)),

    # Bands
    (re.compile(r"\bresistance band\b", re.I),                ("resistance_bands",)),
    (re.compile(r"\bband (pull|row|press|curl)\b", re.I),     ("resistance_bands",)),

    # Box / plyo
    (re.compile(r"\bbox jump\b", re.I),                       ("box",)),
    (re.compile(r"\bstep ?up\b", re.I),                       ("box", "bench")),

    # Medicine / slam ball
    (re.compile(r"\b(slam ball|medicine ball|med ball|wall ball)\b", re.I),
                                                              ("medicine_ball",)),

    # TRX
    (re.compile(r"\btrx|suspension\b", re.I),                 ("trx",)),
]


def required_equipment(exercise: dict[str, Any]) -> tuple[str, ...]:
    """
    Return a tuple of equipment keys — the exercise requires AT LEAST ONE of
    these to be safe. Empty tuple = bodyweight (always safe).

    Priority order:
      1. Exercise doc explicit `equipment_type` list (from library) — if it
         contains something OTHER than bodyweight, return the first such.
      2. Regex match on exercise name.
      3. Empty tuple (bodyweight).
    """
    # 1. Library equipment_type
    et = exercise.get("equipment_type") or exercise.get("equipment") or []
    if isinstance(et, str):
        et = [et]
    if isinstance(et, (list, tuple, set)):
        keys: list[str] = []
        for x in et:
            n = _norm_equip_token(str(x))
            if n and n not in ("bodyweight",) and n != "full_gym_marker":
                keys.append(n)
        if keys:
            return tuple(keys)

    # 2. Name regex
    name = str(exercise.get("name") or exercise.get("exercise_name") or "")
    for pat, req in EQUIPMENT_REGEXES:
        if pat.search(name):
            return req

    # 3. Default → bodyweight (no requirement)
    return ()


def validate_exercise_equipment(
    exercise: dict[str, Any],
    available: set[str],
) -> dict[str, Any]:
    """
    Pure validation: does this exercise's required equipment exist in the
    available set?

    Returns:
      {
        "passes": bool,
        "required": tuple(str),     # what the exercise needs (any of)
        "missing": tuple(str),      # keys not in available (empty if passes)
        "reason": str or None,      # short client-facing reason on failure
      }
    """
    req = required_equipment(exercise)
    if not req:
        return {"passes": True, "required": (), "missing": (), "reason": None}
    if any(k in available for k in req):
        return {"passes": True, "required": req, "missing": (), "reason": None}
    # Build a friendly reason
    names = _human_names(req)
    reason = f"Requires {names} — not available at your current setup."
    return {"passes": False, "required": req, "missing": req, "reason": reason}


def _human_names(keys: tuple[str, ...]) -> str:
    """Turn ('barbell', 'smith_machine') into 'a barbell or smith machine'."""
    friendly = {
        "barbell": "a barbell", "olympic_barbell": "an olympic barbell",
        "bench": "a bench", "flat_bench": "a bench", "adjustable_bench": "an adjustable bench",
        "cable_stack": "a cable machine", "cable_machine": "a cable machine",
        "smith_machine": "a Smith machine",
        "leg_press": "a leg-press machine", "leg_extension": "a leg-extension machine", "leg_curl": "a leg-curl machine",
        "dumbbells": "dumbbells", "adjustable_dumbbells": "adjustable dumbbells",
        "kettlebell": "a kettlebell",
        "pull_up_bar": "a pull-up bar", "chin_up_bar": "a chin-up bar",
        "treadmill": "a treadmill", "stationary_bike": "a bike", "rowing_machine": "a rower",
        "resistance_bands": "resistance bands",
        "medicine_ball": "a med ball", "slam_ball": "a slam ball",
        "trx": "TRX / suspension straps",
        "box": "a plyo box", "plyo_box": "a plyo box",
        "pool": "a pool",
    }
    parts = [friendly.get(k, k.replace("_", " ")) for k in keys]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} or {parts[1]}"
    return ", ".join(parts[:-1]) + f", or {parts[-1]}"


# ---------------------------------------------------------------------------
# Workout-level enforcement — mutates the workout in place
# ---------------------------------------------------------------------------

def enforce_equipment_gate(
    workout: dict[str, Any],
    *,
    available: set[str],
    hotel_context: bool = False,
    hotel_name: Optional[str] = None,
) -> dict[str, Any]:
    """
    Runs strict equipment validation on every exercise. Mutates the workout
    in place: any failing exercise gets tagged with `equipment_check: "fail"`
    and a `equipment_reason` string. If ANY exercise fails, the whole
    workout is flagged `needs_coach_review: true` with a `change_reason`.

    Args:
      workout: the workout dict (with .exercises list)
      available: normalised set of equipment keys
      hotel_context: True if this is a layover / hotel session
      hotel_name: optional hotel name to include in the reason

    Returns a summary:
      {
        "checked": int,
        "passes": int,
        "fails": int,
        "failed_names": [str, ...],
        "needs_review": bool,
      }
    """
    exs = workout.get("exercises") or []
    passes = 0
    fails = 0
    failed_names: list[str] = []
    for ex in exs:
        res = validate_exercise_equipment(ex, available)
        ex["equipment_check"] = "pass" if res["passes"] else "fail"
        if not res["passes"]:
            ex["equipment_reason"] = res["reason"]
            ex["equipment_required"] = list(res["required"])
            fails += 1
            failed_names.append(str(ex.get("name") or ex.get("exercise_name") or ""))
        else:
            passes += 1
    needs_review = fails > 0
    if needs_review:
        workout["needs_coach_review"] = True
        # Iter 94i — mark this precisely so the client UI can render the
        # right banner + action buttons and Louis knows it was an equipment gate.
        workout["validation_status"] = workout.get("validation_status") or "adjusted_fallback"
        workout["fallback_used"] = True
        workout["fallback_type"] = "equipment_gate"
        prefix = "Hotel gym is limited" if hotel_context else "Your setup is missing kit"
        names_line = ", ".join(failed_names[:3]) + ("..." if len(failed_names) > 3 else "")
        loc_suffix = f" at {hotel_name}" if hotel_context and hotel_name else ""
        # Iter 94i — friendly client message. The technical detail (specific
        # exercises + missing equipment) still lives on each exercise's
        # `equipment_reason` for the coach task; the client just sees the
        # calm summary.
        workout["change_reason"] = (
            "Session adjusted — one or more exercises needed kit you don't have "
            f"{f'at {hotel_name}' if hotel_context and hotel_name else ''}. "
            "Louis has been notified. You can still train safely with the "
            "bodyweight-safe version below."
        ).strip()
        # Keep the technical summary for coach / debug logs.
        workout["change_reason_technical"] = (
            f"{prefix}{loc_suffix} — {fails} exercise(s) need coach review: {names_line}."
        )
    return {
        "checked": len(exs),
        "passes": passes,
        "fails": fails,
        "failed_names": failed_names,
        "needs_review": needs_review,
    }
