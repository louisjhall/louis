"""
feature_workout_fallback — Deterministic template workouts.

Purpose: when the LLM (Claude via Emergent) fails for ANY reason — budget
exceeded, rate limit, timeout, network error — the user should NEVER be left
with an empty week. This module produces a sensible starter plan based on:
  * the client's main goal (from profile)
  * the roster day types
  * available equipment (hotel gym / home gym / bodyweight)
  * the setup-day gate (first workout starts tomorrow)

No Claude calls, no image generation, no ML — just a well-thought-out template
that gives the client a real starting programme they can follow, and a coach
task so Louis can review + upgrade later.

Structure (repeats over the roster):
  * Home / off-day  → Full-body strength or Push/Pull/Legs split
  * Layover / hotel → Bodyweight or hotel-gym workout
  * Flight / duty   → Short mobility (10-20 min)
  * Standby         → Amber short activation
  * Rest day        → Rest (no workout)

Each generated workout has a plain-English rationale so the client understands
why it's on that day.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any


# ---------------------------------------------------------------------------
# Exercise templates by session type. Kept intentionally simple and safe.
# ---------------------------------------------------------------------------

FULL_BODY_STRENGTH = [
    {"name": "Goblet squat",              "sets": 3, "reps": "10-12", "rest_sec": 60, "rpe": 7, "notes": "Chest up, knees tracking over toes."},
    {"name": "Dumbbell Romanian deadlift", "sets": 3, "reps": "8-10",  "rest_sec": 75, "rpe": 7, "notes": "Slight knee bend, hinge from hips."},
    {"name": "Dumbbell bench press or floor press", "sets": 3, "reps": "8-10", "rest_sec": 60, "rpe": 7, "notes": "Elbows around 45°."},
    {"name": "One-arm dumbbell row",      "sets": 3, "reps": "10 each side", "rest_sec": 60, "rpe": 7, "notes": "Drive elbow to hip."},
    {"name": "Plank",                     "sets": 3, "reps": "40s hold", "rest_sec": 45, "rpe": 6, "notes": "Ribs down, glutes on."},
]

BODYWEIGHT_LAYOVER = [
    {"name": "Bodyweight squat",          "sets": 3, "reps": "15",     "rest_sec": 45, "rpe": 6, "notes": "Slow eccentric, controlled."},
    {"name": "Push-up (or incline push-up)", "sets": 3, "reps": "10-15", "rest_sec": 45, "rpe": 7, "notes": "Use hotel bed/desk to scale."},
    {"name": "Reverse lunge",             "sets": 3, "reps": "10 each leg", "rest_sec": 45, "rpe": 6, "notes": "Long step back."},
    {"name": "Superman / prone Y-T-W",    "sets": 3, "reps": "12",     "rest_sec": 40, "rpe": 6, "notes": "Squeeze upper back."},
    {"name": "Hollow hold",               "sets": 3, "reps": "30s",    "rest_sec": 40, "rpe": 6, "notes": "Lower back pressed down."},
]

HOTEL_GYM = [
    {"name": "Dumbbell goblet squat",     "sets": 4, "reps": "10",     "rest_sec": 75, "rpe": 7, "notes": "Focus on control."},
    {"name": "Dumbbell shoulder press",   "sets": 3, "reps": "8-10",   "rest_sec": 60, "rpe": 7, "notes": "Neutral grip, ribs down."},
    {"name": "Dumbbell romanian deadlift", "sets": 3, "reps": "10",    "rest_sec": 60, "rpe": 7, "notes": "Push hips back."},
    {"name": "Assisted pull-up or lat pulldown (if available) or DB row", "sets": 3, "reps": "8-10", "rest_sec": 60, "rpe": 7, "notes": "Whichever is available."},
    {"name": "Side plank",                "sets": 2, "reps": "30s each side", "rest_sec": 40, "rpe": 6, "notes": "Stack hips."},
]

FLIGHT_RECOVERY_MOBILITY = [
    {"name": "Hip flexor stretch",        "sets": 2, "reps": "45s each side", "rest_sec": 20, "rpe": 3, "notes": "Ease into the stretch."},
    {"name": "Cat-cow",                   "sets": 2, "reps": "8 slow",  "rest_sec": 20, "rpe": 3, "notes": "Follow the breath."},
    {"name": "World's greatest stretch",  "sets": 2, "reps": "5 each side", "rest_sec": 20, "rpe": 3, "notes": "Rotate thoracic spine."},
    {"name": "90/90 hip rotations",       "sets": 2, "reps": "8 each side", "rest_sec": 20, "rpe": 3, "notes": "Move slowly, no pain."},
    {"name": "Diaphragmatic breathing",   "sets": 1, "reps": "10 breaths", "rest_sec": 0, "rpe": 2, "notes": "Long exhale to help recovery."},
]

STANDBY_ACTIVATION = [
    {"name": "Bodyweight squat + calf raise", "sets": 2, "reps": "12", "rest_sec": 30, "rpe": 5, "notes": "Wake the legs up."},
    {"name": "Band pull-apart or shoulder pass-through", "sets": 2, "reps": "12", "rest_sec": 30, "rpe": 5, "notes": "Improve shoulder position."},
    {"name": "Glute bridge",              "sets": 2, "reps": "12",     "rest_sec": 30, "rpe": 5, "notes": "Squeeze the glutes."},
    {"name": "Dead bug",                  "sets": 2, "reps": "8 each side", "rest_sec": 30, "rpe": 5, "notes": "Ribs down."},
]

WARMUP_GENERAL = [
    {"name": "5 min light cardio",        "duration_sec": 300},
    {"name": "Cat-cow x 5",               "duration_sec": 45},
    {"name": "World's greatest stretch x 4 each side", "duration_sec": 90},
    {"name": "Bodyweight squat x 10",     "duration_sec": 45},
]

WARMUP_MOBILITY = [
    {"name": "Deep breathing x 5",        "duration_sec": 45},
    {"name": "Cat-cow x 6",               "duration_sec": 45},
]


def _classify_day(day: dict[str, Any]) -> str:
    """Map a roster day into one of the workout templates."""
    dtype = str(day.get("day_type") or day.get("type") or "").lower()
    # Explicit rest
    if dtype in ("rest", "off", "annual_leave", "leave"):
        return "off"
    # Flight duties
    if any(k in dtype for k in ("night_flight", "night-flight", "overnight", "red_eye", "red-eye", "long_haul", "long-haul")):
        return "flight_heavy"
    if "flight" in dtype or "duty" in dtype:
        return "flight_light"
    if "layover" in dtype or "hotel" in dtype:
        return "layover"
    if "standby" in dtype or "reserve" in dtype:
        return "standby"
    if any(k in dtype for k in ("sim", "training", "line_check")):
        return "activation"
    # Default = home training day
    return "home"


def _build_workout_for_day(day: dict[str, Any], goal_focus: str) -> dict[str, Any] | None:
    """Return a single workout doc for one roster day, or None for a rest day."""
    kind = _classify_day(day)
    date = day.get("date")
    if not date:
        return None

    if kind == "off":
        # Explicit rest — return nothing so the day shows as a natural rest.
        return None

    if kind == "flight_heavy":
        return {
            "date": date,
            "day_load": "red",
            "title": "Flight Recovery Mobility",
            "location": "Post-Flight Mobility",
            "duration_min": 15,
            "focus": "recovery",
            "warmup": WARMUP_MOBILITY,
            "exercises": FLIGHT_RECOVERY_MOBILITY,
            "alternatives": {
                "home": "Same mobility flow in your bedroom.",
                "hotel": "Same mobility flow in your hotel room.",
                "no_equipment": "All bodyweight — no equipment needed.",
                "easier": "Shorten to 10 minutes and skip the last two moves.",
                "harder": "Add 10 minutes of walking after the flow.",
            },
            "rationale": "Placed after a heavy flying duty. Keep the session short and focused on hips, thoracic spine and breathing so you can down-regulate and sleep well.",
            "key_session": False,
            "event_phase": None,
        }

    if kind == "flight_light":
        return {
            "date": date,
            "day_load": "amber",
            "title": "Pre/Post-Flight Mobility",
            "location": "Pre-Flight Mobility",
            "duration_min": 12,
            "focus": "mobility",
            "warmup": WARMUP_MOBILITY,
            "exercises": FLIGHT_RECOVERY_MOBILITY,
            "alternatives": {
                "home": "Same mobility flow.",
                "hotel": "Same mobility flow.",
                "no_equipment": "All bodyweight.",
                "easier": "Halve the reps.",
                "harder": "Add a 10-minute walk.",
            },
            "rationale": "Short mobility session around a flying duty — improve hip and shoulder position without adding fatigue.",
            "key_session": False,
            "event_phase": None,
        }

    if kind == "layover":
        return {
            "date": date,
            "day_load": "amber",
            "title": "Hotel / Bodyweight Session",
            "location": "Bodyweight Layover Workout",
            "duration_min": 30,
            "focus": "full",
            "warmup": WARMUP_GENERAL,
            "exercises": BODYWEIGHT_LAYOVER,
            "alternatives": {
                "home": "Same session at home.",
                "hotel": "This is the hotel version.",
                "no_equipment": "Already bodyweight-only.",
                "easier": "3 rounds instead of 3 x sets, longer rest.",
                "harder": "Add push-up + squat superset for 3 rounds.",
            },
            "rationale": "You're on a layover — a short, controlled bodyweight session keeps consistency without fatigue.",
            "key_session": False,
            "event_phase": None,
        }

    if kind == "standby":
        return {
            "date": date,
            "day_load": "amber",
            "title": "Standby Activation",
            "location": "Home Workout",
            "duration_min": 20,
            "focus": "mobility",
            "warmup": WARMUP_MOBILITY,
            "exercises": STANDBY_ACTIVATION,
            "alternatives": {
                "home": "Same short activation.",
                "hotel": "Same short activation.",
                "no_equipment": "Fully bodyweight.",
                "easier": "Just do the mobility warm-up.",
                "harder": "Add 10 minutes of light walking.",
            },
            "rationale": "You're on standby, so a short activation keeps you ready without spending real energy.",
            "key_session": False,
            "event_phase": None,
        }

    if kind == "activation":
        return {
            "date": date,
            "day_load": "amber",
            "title": "Light Activation",
            "location": "Home Workout",
            "duration_min": 20,
            "focus": "mobility",
            "warmup": WARMUP_MOBILITY,
            "exercises": STANDBY_ACTIVATION,
            "alternatives": {"home": "Same session.", "hotel": "Same session.", "no_equipment": "Bodyweight-only.", "easier": "Skip the last 2 moves.", "harder": "Add 10 min walking."},
            "rationale": "Simulator / training day — keep your body warm without adding fatigue that could impact your assessment.",
            "key_session": False,
            "event_phase": None,
        }

    # home
    if goal_focus == "bodyweight":
        exs, title, loc, dur = BODYWEIGHT_LAYOVER, "Full Body Bodyweight", "Home Workout", 35
    elif goal_focus == "hotel":
        exs, title, loc, dur = HOTEL_GYM, "Full Body Hotel Gym", "Hotel Gym Workout", 40
    else:
        exs, title, loc, dur = FULL_BODY_STRENGTH, "Full Body Strength", "Home Workout", 45

    return {
        "date": date,
        "day_load": "green",
        "title": title,
        "location": loc,
        "duration_min": dur,
        "focus": "full",
        "warmup": WARMUP_GENERAL,
        "exercises": exs,
        "alternatives": {
            "home": "Use dumbbells, kettlebells or a band.",
            "hotel": "Sub in bodyweight equivalents.",
            "no_equipment": "Do the bodyweight version listed above.",
            "easier": "Drop to 2 sets, add 30s extra rest.",
            "harder": "Add a 4th set of the first two lifts, or superset the last two.",
        },
        "rationale": "Home / off-duty day — the best window to progress strength without competing with roster fatigue.",
        "key_session": False,
        "event_phase": None,
    }


def build_template_plan(user: dict[str, Any], roster: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic fallback plan for the whole roster window."""
    profile = user.get("profile") or {}
    hotel_pref = str(profile.get("hotel_gyms") or "").lower()
    if hotel_pref in ("never", "rare"):
        goal_focus = "bodyweight"
    elif hotel_pref in ("always", "often"):
        goal_focus = "hotel"
    else:
        goal_focus = "home"

    out: list[dict[str, Any]] = []
    for d in (roster.get("days") or []):
        w = _build_workout_for_day(d, goal_focus)
        if w:
            out.append(w)
    return out


def is_empty_or_llm_failure(workouts: list[dict[str, Any]]) -> bool:
    """True if the LLM returned nothing useful."""
    return not workouts or all(not (w.get("exercises") or w.get("warmup")) for w in workouts)
