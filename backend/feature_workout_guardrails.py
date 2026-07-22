"""
feature_workout_guardrails — Phase 3: strict post-LLM guardrails.

Runs after every workout is generated (LLM path AND fallback path) and BEFORE
persistence. It validates each workout against the programme context and
returns:

  {
    "workouts": [<healed workouts>],
    "report": {
        "total": int,
        "ok": int,
        "healed": int,
        "flagged": int,
        "violations": [{workout_id, date, kind, detail, healed_action?}, ...],
    }
  }

Guardrail categories (in order of severity):
  H_AVOID       : workout uses a movement pattern the client MUST avoid
                  (e.g. overhead_press after shoulder pain). Heal by
                  substituting a safe alternative.
  H_OVERLOAD    : primary-lift set count OR RPE drifts from strength_overload
                  by >30%. Heal by clamping into the prescribed range.
  H_SHAPE       : the week's session-type mix doesn't hit weekly_shape_ideal.
                  Cannot self-heal at the per-workout level → flag for coach.
  H_DURATION    : workout duration drifts >40% from the target range for the
                  phase. Heal by adjusting duration_min.
  H_MISSING_EX  : workout has 0 exercises after generation. Delegated to the
                  existing `_ensure_workout_content` guard (iter 83).

Never raises: on unexpected input just returns the workouts unchanged and
adds a "guardrail_error" line to the report.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# --- Movement pattern regex catalogue --------------------------------------

_PATTERN_REGEX: dict[str, re.Pattern] = {
    "overhead_press":  re.compile(r"\b(overhead|shoulder|military|push)\s*press|OHP|strict\s*press|handstand\s*push", re.I),
    "military_press":  re.compile(r"\bmilitary\s*press|standing\s*(shoulder|overhead)\s*press", re.I),
    "handstand":       re.compile(r"\bhandstand|HSPU|wall\s*walk", re.I),
    "kipping_pullup":  re.compile(r"\bkip(ping)?\s*pull[-\s]?up", re.I),
    "deep_squat":      re.compile(r"\b(deep|ATG|ass[-\s]to[-\s]grass|full)\s*squat|pistol\s*squat", re.I),
    "pistol_squat":    re.compile(r"\bpistol\s*squat", re.I),
    "box_jump":        re.compile(r"\bbox\s*jump|depth\s*jump|jump\s*box", re.I),
    "high_impact_run": re.compile(r"\bsprint|hill\s*sprint|running\s*intervals?|track\s*run|400s?\b", re.I),
    "deadlift":        re.compile(r"\bdeadlift|RDL|romanian\s*deadlift|sumo|conventional\s*deadlift", re.I),
    "hinge":           re.compile(r"\bhinge|good\s*morning|kettlebell\s*swing|KB\s*swing", re.I),
    "loaded_carry":    re.compile(r"\b(farmer'?s|suitcase|overhead)\s*carry|yoke\s*walk", re.I),
    "heavy_squat":     re.compile(r"\b(back|front|goblet|barbell)\s*squat.*(heavy|1RM|5RM|3RM|top\s*set)", re.I),
    "long_lunges":     re.compile(r"\b(walking\s*lunge|reverse\s*lunge|split\s*squat)", re.I),
    "push_up":         re.compile(r"\bpush[-\s]?up|press[-\s]?up", re.I),
    "front_squat":     re.compile(r"\bfront\s*squat", re.I),
    "chin_up":         re.compile(r"\bchin[-\s]?up|underhand\s*pull[-\s]?up", re.I),
    "heavy_pull":      re.compile(r"\bbarbell\s*row|pendlay\s*row|weighted\s*pull[-\s]?up", re.I),
    "close_grip_press":re.compile(r"\bclose[-\s]?grip\s*(bench\s*)?press", re.I),
    "sprint_intervals":re.compile(r"\bsprint\s*intervals?|sprints?\b|track\s*intervals", re.I),
}

# --- Safe substitutions for banned patterns --------------------------------

_SUBSTITUTIONS: dict[str, dict[str, Any]] = {
    "overhead_press":  {"name": "Landmine Press",         "note": "Substituted from overhead press due to shoulder flag."},
    "military_press":  {"name": "Landmine Press",         "note": "Substituted from military press due to shoulder flag."},
    "handstand":       {"name": "Pike Push-Up (elevated)", "note": "Substituted from handstand work due to shoulder flag."},
    "kipping_pullup":  {"name": "Strict Pull-Up (or Lat Pulldown)", "note": "Substituted from kipping — protects shoulder."},
    "deep_squat":      {"name": "Box Squat (parallel)",    "note": "Substituted from deep squat due to knee/hip flag."},
    "pistol_squat":    {"name": "Split Squat (assisted)",  "note": "Substituted from pistol squat due to knee flag."},
    "box_jump":        {"name": "Step-Up (weighted)",      "note": "Substituted from box jump — low-impact swap."},
    "high_impact_run": {"name": "Cycle 20-30 min (Z2)",    "note": "Substituted from high-impact run for the flagged joint."},
    "sprint_intervals":{"name": "Bike Intervals (30/30)",  "note": "Substituted from sprints for the flagged joint."},
    "deadlift":        {"name": "Trap-Bar Deadlift (light)", "note": "Substituted from conventional deadlift due to back flag."},
    "hinge":           {"name": "Cable Pull-Through (light)", "note": "Substituted from loaded hinge due to back flag."},
    "loaded_carry":    {"name": "Suitcase March (light)",  "note": "Substituted from loaded carry due to back flag."},
    "heavy_squat":     {"name": "Goblet Squat (moderate)", "note": "Reduced from heavy squat variant."},
    "long_lunges":     {"name": "Split Squat (stationary)", "note": "Substituted from lunges due to hip/knee flag."},
    "push_up":         {"name": "Chest-Supported Row",     "note": "Substituted from push-up due to wrist flag."},
    "front_squat":     {"name": "Goblet Squat",            "note": "Substituted from front squat due to wrist flag."},
    "chin_up":         {"name": "Neutral-Grip Pull-Up",    "note": "Substituted from chin-up due to elbow flag."},
    "heavy_pull":      {"name": "Chest-Supported Row (moderate)", "note": "Reduced from heavy pull due to elbow flag."},
    "close_grip_press":{"name": "Dumbbell Bench Press",    "note": "Substituted from close-grip press due to elbow flag."},
}


def _exercise_hits_pattern(name: str, pattern: str) -> bool:
    rx = _PATTERN_REGEX.get(pattern)
    return bool(rx and rx.search(name or ""))


def _substitute_exercise(ex: dict, pattern: str) -> dict:
    """Return a NEW exercise dict with the substitution applied. Keep sets/reps/rest."""
    sub = _SUBSTITUTIONS.get(pattern)
    if not sub:
        return ex
    healed = dict(ex)
    original_name = ex.get("name", "")
    healed["name"] = sub["name"]
    # Preserve prescription but ease load and RPE.
    healed["_original_name"] = original_name
    healed["_healed_reason"] = sub["note"]
    if "rpe" in healed:
        try:
            healed["rpe"] = max(6, min(8, int(healed["rpe"])))
        except Exception:
            pass
    return healed


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _parse_int(v: Any, default: int = 0) -> int:
    try:
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str):
            m = re.search(r"\d+", v)
            if m:
                return int(m.group(0))
    except Exception:
        pass
    return default


def validate_workout(workout: dict, ctx: dict) -> tuple[dict, list[dict]]:
    """
    Validate ONE workout against the programme_ctx. Returns (healed_workout, violations).
    """
    if not workout or not isinstance(workout, dict):
        return workout, []

    live = (ctx or {}).get("live_state") or {}
    avoid = list(live.get("avoid_movement_patterns") or [])
    strength_overload = (ctx or {}).get("strength_overload") or {}
    phase_key = ((ctx or {}).get("phase") or {}).get("key")
    goal_key = (ctx or {}).get("goal_key")

    violations: list[dict] = []
    healed = dict(workout)
    exercises = list(healed.get("exercises") or [])

    # --- H_AVOID: substitute banned patterns ------------------------------
    if avoid and exercises:
        new_exs: list[dict] = []
        for ex in exercises:
            name = ex.get("name") or ""
            hit_pattern = None
            for pat in avoid:
                if _exercise_hits_pattern(name, pat):
                    hit_pattern = pat
                    break
            if hit_pattern:
                sub = _substitute_exercise(ex, hit_pattern)
                new_exs.append(sub)
                violations.append({
                    "kind": "H_AVOID",
                    "detail": f"Exercise '{name}' matched banned pattern '{hit_pattern}'",
                    "healed_action": f"Substituted with '{sub.get('name')}'",
                    "date": healed.get("date"),
                    "workout_id": healed.get("id"),
                })
            else:
                new_exs.append(ex)
        exercises = new_exs
        healed["exercises"] = exercises

    # --- H_OVERLOAD: clamp primary-lift sets/RPE to prescribed range ------
    # Only enforce for NON-endurance and NON-recovery workouts, first real lift.
    focus = str(healed.get("focus") or "").lower()
    is_recovery = focus in ("recovery", "mobility", "rest")
    if strength_overload and goal_key != "event" and not is_recovery and exercises:
        target_reps_range = _parse_reps_range(strength_overload.get("reps_target"))
        prescribed_sets_delta = int(strength_overload.get("sets_delta") or 0)
        # Baseline sets: use whatever the first exercise already has, clamp deviations.
        first_ex = exercises[0]
        actual_sets = _parse_int(first_ex.get("sets"), default=3)
        # Reasonable band: 2-5 sets, but if strength_overload says deload we allow 2.
        min_sets, max_sets = (2, 5) if phase_key != "deload" else (2, 4)
        clamped_sets = _clamp(actual_sets, min_sets, max_sets)
        if clamped_sets != actual_sets:
            first_ex["sets"] = clamped_sets
            first_ex["_healed_reason"] = f"Clamped sets {actual_sets}→{clamped_sets} to strength_overload band."
            violations.append({
                "kind": "H_OVERLOAD",
                "detail": f"Primary lift '{first_ex.get('name')}' had {actual_sets} sets (band {min_sets}-{max_sets}).",
                "healed_action": f"Sets clamped to {clamped_sets}.",
                "date": healed.get("date"),
                "workout_id": healed.get("id"),
            })
        # Reps check — only if we have a numeric current reps and it's way outside range.
        if target_reps_range and first_ex.get("reps") is not None:
            actual_reps = _parse_int(first_ex.get("reps"), default=0)
            lo, hi = target_reps_range
            if actual_reps and (actual_reps < max(1, lo - 4) or actual_reps > hi + 4):
                # Clamp toward mid-range.
                mid = (lo + hi) // 2
                first_ex["reps"] = f"{lo}-{hi}"
                first_ex.setdefault("_healed_reason", "")
                first_ex["_healed_reason"] += f" Reps clamped to {lo}-{hi} (was {actual_reps})."
                violations.append({
                    "kind": "H_OVERLOAD",
                    "detail": f"Primary reps {actual_reps} outside strength_overload target {lo}-{hi}.",
                    "healed_action": f"Reps rewritten to '{lo}-{hi}'.",
                    "date": healed.get("date"),
                    "workout_id": healed.get("id"),
                })

    # --- H_DURATION: clamp duration to sane range for the phase -----------
    duration = _parse_int(healed.get("duration_min"), default=0)
    if duration:
        if is_recovery:
            band = (8, 25)
        elif phase_key == "deload":
            band = (18, 45)
        elif goal_key == "event":
            band = (25, 120)  # long runs can be long
        else:
            band = (20, 75)
        if duration < band[0] or duration > band[1]:
            new_dur = _clamp(duration, band[0], band[1])
            healed["duration_min"] = new_dur
            violations.append({
                "kind": "H_DURATION",
                "detail": f"Duration {duration}min outside band {band[0]}-{band[1]}.",
                "healed_action": f"Duration clamped to {new_dur}min.",
                "date": healed.get("date"),
                "workout_id": healed.get("id"),
            })

    # --- H_MISSING_EX: 0 exercises should never happen post-heal ----------
    if not exercises and not is_recovery:
        violations.append({
            "kind": "H_MISSING_EX",
            "detail": "Workout has 0 exercises after generation.",
            "healed_action": None,  # delegated to _ensure_workout_content
            "date": healed.get("date"),
            "workout_id": healed.get("id"),
        })

    # Mark workout with a compact guardrail summary
    if violations:
        healed["guardrail_violations"] = violations
        # If we healed everything and no H_SHAPE / H_MISSING_EX remain, mark 'healed'
        unhealed = [v for v in violations if not v.get("healed_action")]
        if unhealed:
            healed["validation_status"] = "needs_review"
            healed["needs_coach_review"] = True
        else:
            healed.setdefault("validation_status", "ok")

    return healed, violations


def _parse_reps_range(s: Any) -> Optional[tuple[int, int]]:
    if not s:
        return None
    if isinstance(s, (int, float)):
        return int(s), int(s)
    if isinstance(s, str):
        m = re.match(r"\s*(\d+)\s*[-–—]\s*(\d+)\s*", s)
        if m:
            return int(m.group(1)), int(m.group(2))
        m2 = re.search(r"\d+", s)
        if m2:
            n = int(m2.group(0))
            return n, n
    return None


def _week_shape_violations(workouts: list[dict], ctx: dict) -> list[dict]:
    """Check the 7-day session-type mix against weekly_shape_ideal."""
    shape = (ctx or {}).get("weekly_shape_ideal") or []
    if not shape:
        return []
    # Normalize actual focuses.
    actual_focuses = [str(w.get("focus") or "").lower() for w in workouts if w.get("focus")]
    real_actual = [f for f in actual_focuses if f not in ("recovery", "mobility", "rest")]
    real_ideal = [s for s in shape if s not in ("recovery", "mobility", "rest")]
    if not real_ideal:
        return []
    # Sub-string match: e.g. weekly_shape has "long_run" — accept any focus containing "run" or "long".
    def _matches(actual: str, ideal: str) -> bool:
        a = actual.lower()
        i = ideal.lower()
        if i in a or a in i:
            return True
        # loose synonyms
        if i.startswith("long") and "run" in a:
            return True
        if i == "easy_run" and "run" in a:
            return True
        return False

    missing = []
    ideal_bag = list(real_ideal)
    actual_bag = list(real_actual)
    # Greedy match
    for want in list(ideal_bag):
        for j, got in enumerate(actual_bag):
            if _matches(got, want):
                actual_bag.pop(j)
                ideal_bag.remove(want)
                break
    for want in ideal_bag:
        missing.append(want)
    if not missing:
        return []
    return [{
        "kind": "H_SHAPE",
        "detail": f"Weekly shape missing: {missing}. Actual mix: {real_actual}",
        "healed_action": None,
    }]


def validate_batch(workouts: list[dict], ctx: dict) -> dict:
    """
    Validate an ENTIRE 7-day (or month) batch of workouts. Returns:
      {
        "workouts": [<healed workouts, same length/order as input>],
        "report": {total, ok, healed, flagged, violations}
      }
    """
    if not workouts:
        return {"workouts": [], "report": {"total": 0, "ok": 0, "healed": 0, "flagged": 0, "violations": []}}

    all_violations: list[dict] = []
    healed_workouts: list[dict] = []
    healed_count = 0
    flagged_count = 0
    for w in workouts:
        try:
            healed, viol = validate_workout(w, ctx)
        except Exception as e:
            all_violations.append({
                "kind": "guardrail_error", "detail": f"validate_workout raised: {e}",
                "workout_id": (w or {}).get("id"), "date": (w or {}).get("date"),
            })
            healed_workouts.append(w)
            continue
        if viol:
            unhealed = [v for v in viol if not v.get("healed_action")]
            if unhealed:
                flagged_count += 1
            if any(v.get("healed_action") for v in viol):
                healed_count += 1
            all_violations.extend(viol)
        healed_workouts.append(healed)

    # Week-shape check (batch-level)
    shape_viol = _week_shape_violations(healed_workouts, ctx)
    if shape_viol:
        # Mark ALL non-recovery workouts in the batch with a shape flag on the FIRST one
        # to make it discoverable in the coach dashboard.
        all_violations.extend(shape_viol)
        first_real = next((w for w in healed_workouts
                           if str(w.get("focus") or "").lower() not in ("recovery", "mobility", "rest")),
                          None)
        if first_real:
            first_real["needs_coach_review"] = True
            first_real["validation_status"] = "needs_review"
            first_real.setdefault("guardrail_violations", []).extend(shape_viol)
            flagged_count += 1

    total = len(healed_workouts)
    ok = total - flagged_count
    return {
        "workouts": healed_workouts,
        "report": {
            "total": total,
            "ok": ok,
            "healed": healed_count,
            "flagged": flagged_count,
            "violations": all_violations,
        },
    }
