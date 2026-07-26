"""
Parser Constraints — unified interpreter of parser-generated day labels.

This module reads the fields set by the Etihad (`parsers/etihad_labels.py`)
and Emirates (`parsers/emirates_labels.py`) engines on each roster day and
produces enforceable rules for the plan generator:

    * `training_colour`      — "green" | "amber" | "red" | "black"
    * `equipment_assumption` — "any" | "hotel_or_bodyweight" | "hotel_or_bodyweight_only"
                              | "needs_confirmation" | "none"
    * `blocked`              — list[str] of session categories (e.g.
                              "main_strength", "long_run", "intervals")
    * `client_label`         — human-friendly one-liner ("Heavy flying day")

Public API:
    * constraints_for_day(day)          -> ConstraintProfile
    * violates_constraints(w, day)      -> (bool, reason)
    * sanitize_workout_for_day(w, day)  -> possibly-replaced workout dict
    * enforce_constraints_on_workouts(workouts, roster_days)
                                        -> stats dict

Design principle:
    Parser output is the SOURCE OF TRUTH for what a body can safely do that
    day. The LLM is instructed to respect it, but this module runs
    afterwards as a DETERMINISTIC SAFETY NET so aviation crew never receive
    a heavy squat session on the tarmac of a 14h ULR return.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Session categories emitted by the parser labellers.
SESSION_CATS = {
    "main_strength", "hotel_strength", "bodyweight",
    "long_run", "easy_run", "intervals", "tempo",
    "mobility", "recovery_walk", "rest",
    "steps_only",
}

# Map from workout `focus` (as emitted by the LLM / library) to session
# category tokens the parser vocabulary uses. Multiple focus values can map
# to the same category; the check is "any category token matches".
FOCUS_TO_CATEGORIES: dict[str, set[str]] = {
    # Strength family
    "strength": {"main_strength"},
    "gym": {"main_strength"},
    "lower_body": {"main_strength"},
    "upper_body": {"main_strength"},
    "push": {"main_strength"},
    "pull": {"main_strength"},
    "full_body": {"main_strength"},
    "hotel_strength": {"hotel_strength"},
    "bodyweight": {"bodyweight"},
    # Running family
    "long_run": {"long_run"},
    "easy_run": {"easy_run"},
    "run": {"easy_run"},
    "cardio": {"easy_run"},
    "intervals": {"intervals"},
    "tempo": {"tempo"},
    "hiit": {"intervals"},
    # Recovery family
    "mobility": {"mobility"},
    "recovery": {"mobility", "recovery_walk"},
    "walk": {"recovery_walk"},
    "steps": {"steps_only"},
    "rest": {"rest"},
    "off": {"rest"},
}

# Categories in decreasing "load". Higher-load categories dropped when a
# lower-tier equipment/colour rules the day.
CATEGORY_LOAD_ORDER = [
    "long_run", "intervals", "tempo",
    "main_strength", "hotel_strength",
    "easy_run", "bodyweight",
    "recovery_walk", "mobility", "steps_only", "rest",
]

# Colours ordered by severity; deeper colours override lighter ones.
COLOUR_RANK = {"green": 0, "amber": 1, "red": 2, "black": 3}


# ---------------------------------------------------------------------------
# Constraint profile
# ---------------------------------------------------------------------------

@dataclass
class ConstraintProfile:
    date: str
    colour: str = "green"                    # green | amber | red | black
    client_label: str = ""
    blocked: list[str] = field(default_factory=list)
    equipment: str = "any"                   # any | hotel_or_bodyweight | none | needs_confirmation
    action: str = "full_session"             # full_session | moderated | recovery_only | rest_only
    reason: str = ""
    recovery_risk: float = 0.1
    max_duration_min: Optional[int] = None
    parser_source: Optional[str] = None
    from_parser: bool = False                # whether we actually got parser labels vs defaults

    def summary(self) -> dict:
        return {
            "date": self.date, "colour": self.colour,
            "client_label": self.client_label, "action": self.action,
            "blocked": self.blocked, "equipment": self.equipment,
            "reason": self.reason, "from_parser": self.from_parser,
        }


def _equipment_normalised(eq: Any) -> str:
    if not eq:
        return "any"
    v = str(eq).strip().lower()
    if v in ("any", "unknown", ""):
        return "any"
    if v in ("hotel_or_bodyweight", "hotel_or_bodyweight_only", "bodyweight",
             "bodyweight_only", "hotel_only", "hotel", "bodyweight_or_hotel"):
        return "hotel_or_bodyweight"
    if v in ("none", "no_equipment", "unavailable"):
        return "none"
    if v in ("needs_confirmation", "needs_review", "confirm"):
        return "needs_confirmation"
    return "any"


def constraints_for_day(day: dict) -> ConstraintProfile:
    """Read a roster day (post parser enrichment) and produce a
    deterministic ConstraintProfile that the plan generator + fallback
    engines can enforce.
    """
    date = day.get("date") or ""
    colour = str(day.get("training_colour") or "").lower().strip() or "green"
    if colour not in COLOUR_RANK:
        colour = "green"
    client_label = str(day.get("client_label") or day.get("label") or "").strip()
    blocked_raw = day.get("blocked") or []
    if isinstance(blocked_raw, str):
        blocked_raw = [blocked_raw]
    blocked = [b for b in (str(x).strip() for x in blocked_raw) if b]
    equipment = _equipment_normalised(day.get("equipment_assumption"))
    reason = str(day.get("reason") or "").strip()
    parser_source = day.get("source")

    prof = ConstraintProfile(
        date=date, colour=colour, client_label=client_label,
        blocked=blocked, equipment=equipment,
        reason=reason, parser_source=parser_source,
        from_parser=bool(parser_source and parser_source != "llm"),
    )

    # ---- Action & max duration derived from colour --------------------
    if colour == "black":
        prof.action = "rest_only"
        prof.max_duration_min = 0
        prof.recovery_risk = 0.8
    elif colour == "red":
        prof.action = "recovery_only"
        prof.max_duration_min = 25
        prof.recovery_risk = 0.7
    elif colour == "amber":
        prof.action = "moderated"
        prof.max_duration_min = 45
        prof.recovery_risk = 0.4
    else:  # green
        prof.action = "full_session"
        prof.max_duration_min = None
        prof.recovery_risk = 0.15

    # If the day_type is an explicit off/rest, force rest regardless of
    # colour (some parsers leave colour=green for OFF_DAY).
    dtype = str(day.get("day_type") or "").lower()
    if dtype in ("off", "rest") or any(k in dtype for k in ("rostered_off", "annual_leave")):
        prof.action = "rest_only"
        prof.max_duration_min = 0

    return prof


# ---------------------------------------------------------------------------
# Violation detection
# ---------------------------------------------------------------------------

def _workout_categories(workout: dict) -> set[str]:
    focus = str(workout.get("focus") or "").lower().strip()
    cats = set(FOCUS_TO_CATEGORIES.get(focus, set()))
    # Also inspect title tokens as a fallback heuristic.
    title = str(workout.get("title") or "").lower()
    for kw, group in (
        ("long run", {"long_run"}),
        ("interval", {"intervals"}),
        ("tempo", {"tempo"}),
        ("strength", {"main_strength"}),
        ("gym", {"main_strength"}),
        ("hotel gym", {"hotel_strength"}),
        ("mobility", {"mobility"}),
        ("recovery walk", {"recovery_walk"}),
        ("stretch", {"mobility"}),
        ("bodyweight", {"bodyweight"}),
    ):
        if kw in title:
            cats |= group
    return cats


def violates_constraints(workout: dict, day: dict, prof: Optional[ConstraintProfile] = None) -> tuple[bool, str]:
    """Return (violated, reason). Reason is a short client-safe string."""
    prof = prof or constraints_for_day(day)
    focus = str(workout.get("focus") or "").lower().strip()

    # 1. Rest-only day — anything non-rest is a violation.
    if prof.action == "rest_only" and focus not in ("rest", "off"):
        return True, f"Rest day ({prof.client_label or 'off'}) — no session scheduled."

    # 2. Recovery-only day — allow only mobility/recovery.
    if prof.action == "recovery_only":
        cats = _workout_categories(workout)
        allowed = {"mobility", "recovery_walk", "steps_only", "rest"}
        if not cats or not (cats & allowed):
            return True, f"Recovery day ({prof.client_label or 'high fatigue'}) — mobility & breath work only."

    # 3. Blocked categories from parser.
    if prof.blocked:
        cats = _workout_categories(workout)
        overlap = cats & set(prof.blocked)
        if overlap:
            first = sorted(overlap)[0]
            return True, f"Parser blocked '{first}' on this day ({prof.client_label or prof.reason or 'roster context'})."

    # 4. Duration cap — flag but don't hard block (soft violation).
    if prof.max_duration_min is not None:
        dur = int(workout.get("duration_min") or 0)
        if dur > prof.max_duration_min + 15:
            return True, f"Session too long for this day (cap {prof.max_duration_min}m, got {dur}m)."

    # 5. Equipment sanity — only hotel/bodyweight allowed but focus is gym-heavy.
    if prof.equipment == "hotel_or_bodyweight":
        cats = _workout_categories(workout)
        if "main_strength" in cats:
            return True, "Only hotel or bodyweight equipment available on this day."

    return False, ""


# ---------------------------------------------------------------------------
# Sanitiser — replace violating workouts with safe alternatives
# ---------------------------------------------------------------------------

def _fallback_rest(date: str, reason: str) -> dict:
    return {
        "date": date,
        "day_load": "green",
        "title": "Rest & Recovery",
        "location": "Home",
        "duration_min": 0,
        "focus": "rest",
        "warmup": [],
        "exercises": [],
        "alternatives": {},
        "rationale": reason,
        "key_session": False,
        "override_generated": True,
        "override_reason": reason,
        "parser_enforced": True,
    }


def _fallback_mobility(date: str, reason: str, minutes: int = 15) -> dict:
    return {
        "date": date,
        "day_load": "green",
        "title": "Light Mobility & Breath Work",
        "location": "Home / Hotel",
        "duration_min": minutes,
        "focus": "mobility",
        "warmup": [
            {"name": "Neck rolls", "duration_sec": 30},
            {"name": "Shoulder circles", "duration_sec": 30},
        ],
        "exercises": [
            {"name": "Cat-cow stretch", "sets": 1, "reps": "10", "notes": "Slow breathing"},
            {"name": "World's greatest stretch", "sets": 1, "reps": "6/side"},
            {"name": "90/90 hip switches", "sets": 1, "reps": "10/side"},
            {"name": "Child's pose", "sets": 1, "reps": "60s hold"},
            {"name": "Box breathing (4-4-4-4)", "sets": 1, "reps": "8 rounds"},
        ],
        "alternatives": {},
        "rationale": reason,
        "key_session": False,
        "override_generated": True,
        "override_reason": reason,
        "parser_enforced": True,
    }


def _reduce_workout(w: dict, prof: ConstraintProfile) -> dict:
    """Trim sets/duration on an existing workout to fit the day's cap.
    Non-destructive: returns a copy."""
    out = dict(w)
    # Cap duration
    if prof.max_duration_min is not None:
        try:
            dur = int(out.get("duration_min") or 0)
            if dur > prof.max_duration_min:
                out["duration_min"] = prof.max_duration_min
        except Exception:
            pass
    # Trim one set from every multi-set exercise
    ex_out: list[dict] = []
    for e in (out.get("exercises") or []):
        e2 = dict(e)
        try:
            sets = int(e2.get("sets") or 0)
            if sets > 1:
                e2["sets"] = max(1, sets - 1)
        except Exception:
            pass
        ex_out.append(e2)
    out["exercises"] = ex_out
    # Nudge day_load down one notch
    if out.get("day_load") == "red":
        out["day_load"] = "amber"
    out["parser_moderated"] = True
    out["override_generated"] = True
    out["override_reason"] = (
        f"Moderated to match roster: {prof.client_label or 'fatigue-aware day'}."
    )
    # Append transparent rationale (no AI wording)
    prev = str(out.get("rationale") or "").strip()
    note = f"Louis dialled this back to fit today's roster: {prof.client_label or 'higher-fatigue day'}."
    if note not in prev:
        out["rationale"] = (prev + "  |  " + note).strip(" |")
    return out


def sanitize_workout_for_day(workout: Optional[dict], day: dict) -> tuple[dict, bool, str]:
    """Given the LLM's workout for a specific day, ensure it respects the
    parser constraints. Returns (workout, changed, reason).

    * If the workout violates a HARD rule (rest-only day, blocked category,
      recovery-only day) it is REPLACED with a safe alternative.
    * If it violates SOFT rules (duration cap, equipment cap) it is
      moderated in-place.
    """
    prof = constraints_for_day(day)
    date = day.get("date") or ""

    # No LLM workout → build a sensible one from the constraint profile.
    if not workout or not isinstance(workout, dict):
        if prof.action == "rest_only":
            return _fallback_rest(date, f"Rest day: {prof.client_label or prof.reason or 'off duty'}."), True, "built_rest"
        if prof.action == "recovery_only":
            return _fallback_mobility(date, f"Recovery day: {prof.client_label or 'high-fatigue duty'}. Louis kept this to mobility + breath.", minutes=prof.max_duration_min or 15), True, "built_mobility"
        return _fallback_mobility(date, "Placeholder mobility session — Louis will refresh this on your next open.", minutes=15), True, "built_placeholder"

    violated, reason = violates_constraints(workout, day, prof)
    if not violated:
        return workout, False, ""

    # HARD replacements
    if prof.action == "rest_only":
        return _fallback_rest(date, f"Rest day: {prof.client_label or 'off duty'}."), True, reason
    if prof.action == "recovery_only":
        return _fallback_mobility(
            date,
            f"Louis dropped the planned session — {prof.client_label or 'high fatigue after this duty'}. Mobility + breath only today.",
            minutes=prof.max_duration_min or 15,
        ), True, reason

    # Blocked categories on an amber day → downgrade to mobility if the
    # ONLY thing they had was a blocked category; otherwise moderate.
    cats = _workout_categories(workout)
    if prof.blocked and (cats & set(prof.blocked)):
        # If the whole workout maps to a blocked category with nothing else,
        # replace with mobility. Otherwise moderate + strip the blocked
        # exercises would be more work — mobility is safest.
        return _fallback_mobility(
            date,
            f"Louis swapped today's plan — {prof.client_label or 'roster context makes this too heavy'}. Mobility session instead.",
            minutes=min(prof.max_duration_min or 20, 25),
        ), True, reason

    # SOFT: equipment cap or duration cap → moderate in place.
    return _reduce_workout(workout, prof), True, reason


# ---------------------------------------------------------------------------
# Batch enforcement
# ---------------------------------------------------------------------------

def enforce_constraints_on_workouts(
    workouts: list[dict],
    roster_days: list[dict],
) -> dict:
    """Mutate `workouts` in-place (list reference). Ensures every LLM
    workout respects the parser's constraints for its date. Returns stats.

    * Adds missing rest/mobility cards for dates in the roster the LLM
      skipped BUT ONLY when the day's parser constraint says something
      concrete (rest_only / recovery_only). Otherwise we leave gaps alone
      (the days-cap logic in server.py already handles overshoot).
    * Never removes workouts — only replaces or moderates them.
    """
    day_by_date: dict[str, dict] = {}
    for d in roster_days or []:
        dt = d.get("date")
        if dt:
            day_by_date[dt] = d

    stats = {
        "checked": 0, "replaced": 0, "moderated": 0,
        "added": 0, "unchanged": 0,
        "reasons": [],
    }

    seen_dates: set[str] = set()
    for i, w in enumerate(workouts or []):
        stats["checked"] += 1
        dt = w.get("date")
        seen_dates.add(dt or "")
        day = day_by_date.get(dt or "")
        if not day:
            stats["unchanged"] += 1
            continue
        new_w, changed, reason = sanitize_workout_for_day(w, day)
        if not changed:
            stats["unchanged"] += 1
            continue
        if new_w.get("parser_moderated"):
            stats["moderated"] += 1
        else:
            stats["replaced"] += 1
        stats["reasons"].append({"date": dt, "reason": reason})
        workouts[i] = new_w

    # Fill critical missing dates (parser said rest/recovery, LLM skipped)
    for dt, day in day_by_date.items():
        if dt in seen_dates:
            continue
        prof = constraints_for_day(day)
        if prof.action == "rest_only":
            workouts.append(_fallback_rest(dt, f"Rest day: {prof.client_label or 'off duty'}."))
            stats["added"] += 1
            stats["reasons"].append({"date": dt, "reason": "missing_rest_filled"})
        elif prof.action == "recovery_only":
            workouts.append(_fallback_mobility(
                dt,
                f"Recovery day: {prof.client_label or 'high fatigue'}. Louis kept this to mobility.",
                minutes=prof.max_duration_min or 15,
            ))
            stats["added"] += 1
            stats["reasons"].append({"date": dt, "reason": "missing_recovery_filled"})

    # Keep workouts sorted by date (helps calendar rendering)
    try:
        workouts.sort(key=lambda x: x.get("date") or "")
    except Exception:
        pass

    return stats


# ---------------------------------------------------------------------------
# LLM prompt helper — export a compact JSON block for injection
# ---------------------------------------------------------------------------

def constraint_block_for_prompt(days: list[dict]) -> list[dict]:
    """Return the list of ConstraintProfile summaries to inject into the
    workout-generation LLM prompt. Only includes dates whose parser
    labels are meaningful (colour != green OR blocked non-empty OR client
    label present)."""
    out: list[dict] = []
    for d in days or []:
        prof = constraints_for_day(d)
        # Include everything the parser actually populated so the LLM has
        # full visibility.
        if not (prof.from_parser or prof.blocked or prof.client_label
                or prof.colour != "green"):
            continue
        out.append({
            "date": prof.date,
            "client_label": prof.client_label,
            "training_colour": prof.colour,
            "action": prof.action,
            "blocked": prof.blocked,
            "equipment": prof.equipment,
            "max_duration_min": prof.max_duration_min,
        })
    return out
