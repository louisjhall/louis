"""
feature_workout_fallback — Deterministic template workouts.

Purpose: when the LLM (Claude via Emergent) fails for ANY reason — budget
exceeded, rate limit, timeout, network error — the user should NEVER be left
with an empty week. This module produces a sensible starter plan based on:
  * the client's main goal (from profile.main_goal_key + event_type_pref)
  * the roster day types
  * available equipment (hotel gym / home gym / bodyweight)
  * the setup-day gate (first workout starts tomorrow)

No Claude calls, no image generation, no ML — just a well-thought-out template
that gives the client a real starting programme they can follow, and a coach
task so Louis can review + upgrade later.

Plan B2 additions:
  * Running templates (easy_run, long_run, tempo, intervals, strength_for_runners)
  * Goal-aware branching via `feature_programme_quality.event_weekly_shape` and
    `strength_weekly_shape` — the fallback now honours training_days_per_week
    and produces a running-shaped week for marathon/half/10k/5k clients.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional


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

# ---------------------------------------------------------------------------
# Iter 94d (Gap 3) — Tiered post-flight recovery templates.
# Same 5-move mobility isn't right for a 4h red-eye AND a 14h SYD ULR.
# We now pick by duty_hours:
#   SHORT   <  6h → 8-min airport mobility (concourse-friendly, no floor work)
#   MEDIUM  6-11h → 15-min classic FLIGHT_RECOVERY_MOBILITY (unchanged)
#   ULR    ≥12h → 25-min ultra-long-range protocol with hydration cues,
#                 thoracic decompression, and sleep-prep breathing.
# ---------------------------------------------------------------------------

SHORT_HAUL_AIRPORT_MOBILITY = [
    {"name": "Standing figure-4 hip open", "sets": 2, "reps": "30s each side", "rest_sec": 15, "rpe": 3,
     "notes": "Standing — grip a wall / rail. Great for concourse or gate seating."},
    {"name": "Doorway pec stretch",        "sets": 2, "reps": "30s each side", "rest_sec": 15, "rpe": 3,
     "notes": "Use a doorway or vertical post — opens the chest after seated flight."},
    {"name": "Standing thoracic rotation", "sets": 2, "reps": "8 each side",   "rest_sec": 15, "rpe": 3,
     "notes": "Feet planted. Rotate through the mid-back only, not the low back."},
    {"name": "Calf pump + ankle circles",  "sets": 2, "reps": "20 pumps + 10 circles each",
     "rest_sec": 15, "rpe": 2, "notes": "Wakes circulation up after a seated leg."},
]

ULR_RECOVERY_PROTOCOL = [
    # Phase A — decompression (thoracic + hips first)
    {"name": "Wall thoracic decompression", "sets": 2, "reps": "45s hang", "rest_sec": 30, "rpe": 3,
     "notes": "Arms on wall or door frame, hips back — decompresses the spine after 12+ hours seated."},
    {"name": "Deep hip flexor stretch (kneeling)", "sets": 2, "reps": "60s each side",
     "rest_sec": 30, "rpe": 3, "notes": "Extra hold today — hips take the brunt of ULR seat time."},
    {"name": "World's greatest stretch (slow)", "sets": 3, "reps": "5 each side",
     "rest_sec": 30, "rpe": 3, "notes": "Very slow — thoracic rotation is the priority."},

    # Phase B — activation (gentle gluteal + shoulder wake-up)
    {"name": "Glute bridge (paused)", "sets": 3, "reps": "10 slow, 2s pause at top",
     "rest_sec": 30, "rpe": 4, "notes": "Wake the glutes — they've been switched off for 14 hours."},
    {"name": "Band pull-apart",       "sets": 3, "reps": "12 slow",
     "rest_sec": 30, "rpe": 4, "notes": "If no band, use a shirt for tension. Opens the upper back."},

    # Phase C — sleep-prep breathing (parasympathetic downshift)
    {"name": "4-7-8 breathing",       "sets": 1, "reps": "4 cycles",
     "rest_sec": 0, "rpe": 1,
     "notes": "Inhale 4s • hold 7s • exhale 8s. Drops heart rate, signals sleep."},
    {"name": "Box breathing (parasympathetic)", "sets": 1, "reps": "5 min",
     "rest_sec": 0, "rpe": 1,
     "notes": "4s in, 4s hold, 4s out, 4s hold. Repeat for 5 min in bed if landing at night."},
]


def flight_recovery_template_for(duty_hours: Optional[float]) -> dict[str, Any]:
    """Iter 94d (Gap 3) — pick the right recovery template + metadata for the
    given flight length. Returns dict with keys: title, duration_min,
    exercises, rationale, tier ("short"|"medium"|"ulr"). Never raises."""
    dh: float = 0.0
    try:
        dh = float(duty_hours) if duty_hours is not None else 0.0
    except Exception:
        dh = 0.0
    if dh > 0 and dh < 6:
        return {
            "tier": "short",
            "title": "Airport Mobility",
            "duration_min": 8,
            "exercises": list(SHORT_HAUL_AIRPORT_MOBILITY),
            "rationale": (
                "Short-haul (~"
                f"{int(dh)}h) — quick concourse-friendly mobility to undo the "
                "seated posture without adding fatigue."
            ),
        }
    if dh >= 12:
        return {
            "tier": "ulr",
            "title": "ULR Recovery + Sleep Prep",
            "duration_min": 25,
            "exercises": list(ULR_RECOVERY_PROTOCOL),
            "rationale": (
                f"Ultra-long-range ({int(dh)}h) — decompress the thoracic spine, "
                "wake the glutes, then drop into 4-7-8 / box breathing to help "
                "you sleep. Hydrate before starting."
            ),
        }
    # Default: 6-11h (medium-haul) — the classic mobility block
    return {
        "tier": "medium",
        "title": "Flight Recovery Mobility",
        "duration_min": 15,
        "exercises": list(FLIGHT_RECOVERY_MOBILITY),
        "rationale": (
            "Post-duty mobility + breathing to downregulate and support sleep."
        ),
    }

STANDBY_ACTIVATION = [
    {"name": "Bodyweight squat + calf raise", "sets": 2, "reps": "12", "rest_sec": 30, "rpe": 5, "notes": "Wake the legs up."},
    {"name": "Band pull-apart or shoulder pass-through", "sets": 2, "reps": "12", "rest_sec": 30, "rpe": 5, "notes": "Improve shoulder position."},
    {"name": "Glute bridge",              "sets": 2, "reps": "12",     "rest_sec": 30, "rpe": 5, "notes": "Squeeze the glutes."},
    {"name": "Dead bug",                  "sets": 2, "reps": "8 each side", "rest_sec": 30, "rpe": 5, "notes": "Ribs down."},
]

# ---- Plan B2 — Running templates ----
EASY_RUN_MAIN = [
    {"name": "Easy Run",                  "sets": 1, "reps": "25-35 min steady",
     "rest_sec": 0, "rpe": 4, "notes": "Conversational pace — you should be able to speak in short sentences."},
]

LONG_RUN_MAIN = [
    {"name": "Long Run",                  "sets": 1, "reps": "60-90 min steady",
     "rest_sec": 0, "rpe": 5, "notes": "Steady, comfortable. Fuel + hydration if >60min. Walk breaks fine."},
]

TEMPO_RUN_MAIN = [
    {"name": "Tempo Effort",              "sets": 1, "reps": "20-25 min at RPE 7",
     "rest_sec": 0, "rpe": 7, "notes": "Comfortably hard — half-marathon race pace. Hold the effort steady."},
]

INTERVAL_RUN_MAIN = [
    {"name": "5 min warm-up jog",         "sets": 1, "reps": "5 min", "rest_sec": 0, "rpe": 4, "notes": "Progressive."},
    {"name": "Intervals: 6 x 400m at RPE 8-9", "sets": 6, "reps": "400m",
     "rest_sec": 90, "rpe": 9, "notes": "Walk-jog recovery between reps."},
]

STRENGTH_FOR_RUNNERS = [
    {"name": "Single-leg glute bridge",   "sets": 3, "reps": "10 each side", "rest_sec": 45, "rpe": 6, "notes": "Slow, controlled — drive from the glute."},
    {"name": "Dumbbell Romanian deadlift", "sets": 3, "reps": "10", "rest_sec": 60, "rpe": 7, "notes": "Hinge from hips, feel the hamstrings."},
    {"name": "Split squat (rear-foot elevated if possible)", "sets": 3, "reps": "8 each side", "rest_sec": 60, "rpe": 7, "notes": "Vertical torso, knee tracks over toes."},
    {"name": "Calf raise",                "sets": 3, "reps": "12-15", "rest_sec": 45, "rpe": 6, "notes": "Full range — pause at the top."},
    {"name": "Bird-dog",                  "sets": 3, "reps": "8 each side", "rest_sec": 45, "rpe": 5, "notes": "Slow — extend opposite arm/leg without rotating hips."},
    {"name": "Side plank",                "sets": 2, "reps": "30s each side", "rest_sec": 40, "rpe": 6, "notes": "Hips stacked, ribs down."},
]

CONDITIONING_CIRCUIT = [
    {"name": "Kettlebell / dumbbell swing", "sets": 4, "reps": "15", "rest_sec": 45, "rpe": 7, "notes": "Hinge — power from the hips, not the arms."},
    {"name": "Goblet squat",              "sets": 4, "reps": "10", "rest_sec": 45, "rpe": 7, "notes": "Chest up."},
    {"name": "Push-up",                   "sets": 4, "reps": "8-12", "rest_sec": 45, "rpe": 7, "notes": "Scale to incline if needed."},
    {"name": "Mountain climbers",         "sets": 4, "reps": "30s", "rest_sec": 30, "rpe": 8, "notes": "Steady, controlled — quality over speed."},
    {"name": "Plank",                     "sets": 4, "reps": "30s hold", "rest_sec": 30, "rpe": 6, "notes": "Ribs down, glutes on."},
]

MOBILITY_FLOW = [
    {"name": "Cat-cow",                   "sets": 2, "reps": "8 slow", "rest_sec": 20, "rpe": 2, "notes": "Follow the breath."},
    {"name": "World's greatest stretch",  "sets": 2, "reps": "5 each side", "rest_sec": 20, "rpe": 3, "notes": "Rotate thoracic spine."},
    {"name": "90/90 hip rotations",       "sets": 2, "reps": "8 each side", "rest_sec": 20, "rpe": 3, "notes": "Slow, no pain."},
    {"name": "Downward dog to cobra flow", "sets": 2, "reps": "6", "rest_sec": 20, "rpe": 3, "notes": "Move with the breath."},
    {"name": "Diaphragmatic breathing",   "sets": 1, "reps": "10 breaths", "rest_sec": 0, "rpe": 2, "notes": "Long exhale."},
]

WARMUP_GENERAL = [
    {"name": "5 min light cardio",        "duration_sec": 300},
    {"name": "Cat-cow x 5",               "duration_sec": 45},
    {"name": "World's greatest stretch x 4 each side", "duration_sec": 90},
    {"name": "Bodyweight squat x 10",     "duration_sec": 45},
]

WARMUP_RUN = [
    {"name": "3 min brisk walk",          "duration_sec": 180},
    {"name": "Leg swings x 10 each side", "duration_sec": 60},
    {"name": "Ankle circles x 10 each",   "duration_sec": 45},
    {"name": "2 min easy jog",            "duration_sec": 120},
]

WARMUP_INTERVALS = [
    {"name": "5 min easy jog",            "duration_sec": 300},
    {"name": "Leg swings x 10 each",      "duration_sec": 60},
    {"name": "4 x 30s strides",           "duration_sec": 120},
]

WARMUP_MOBILITY = [
    {"name": "Deep breathing x 5",        "duration_sec": 45},
    {"name": "Cat-cow x 6",               "duration_sec": 45},
]

COOLDOWN_RUN = [
    {"name": "5 min walk",                "duration_sec": 300},
    {"name": "Hip flexor stretch 30s each", "duration_sec": 60},
    {"name": "Calf stretch 30s each",     "duration_sec": 60},
    {"name": "Diaphragmatic breathing x 5", "duration_sec": 60},
]


# ---------------------------------------------------------------------------
# Session-type → workout stub factory (Plan B2)
# ---------------------------------------------------------------------------

def _stub_for_session_type(session_type: str, date: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Build a full workout doc from a session-type slot + roster context."""
    hotel_pref = ctx.get("hotel_pref", "home")
    day_load = ctx.get("day_load", "green")

    if session_type == "easy_run":
        return {
            "date": date, "day_load": day_load, "title": "Easy Run",
            "location": "Outdoor Run", "duration_min": 40, "focus": "long_run",
            "warmup": WARMUP_RUN, "exercises": EASY_RUN_MAIN,
            "cooldown": COOLDOWN_RUN,
            "alternatives": {
                "home": "Treadmill if outdoor isn't possible.",
                "hotel": "Treadmill or a walking loop around the hotel.",
                "no_equipment": "Just shoes.",
                "easier": "Reduce to 20-25 min.",
                "harder": "Add 4 x 30s strides at the end.",
            },
            "rationale": "Easy runs build the aerobic base — the most important adaptation for marathon prep. Conversational pace, controlled breathing.",
            "key_session": False, "event_phase": None,
        }

    if session_type == "long_run":
        # Iter 84 (Task 1.6) — km curve override. If ctx supplies `long_run_km`
        # (from the periodisation resolver), use it to size the session.
        long_km = ctx.get("long_run_km") if isinstance(ctx, dict) else None
        if isinstance(long_km, (int, float)) and long_km > 0:
            reps = f"{long_km} km at conversational pace"
            duration = max(30, int(long_km * 6))                     # ~6 min/km avg
            week_note = ctx.get("weeks_to_race") if isinstance(ctx, dict) else None
            notes = f"Weeks to race: {week_note}." if week_note is not None else ""
            exercises = [dict(LONG_RUN_MAIN[0], reps=reps, notes=notes or LONG_RUN_MAIN[0].get("notes"))]
        else:
            duration = 75
            exercises = LONG_RUN_MAIN
        return {
            "date": date, "day_load": day_load, "title": "Long Run",
            "location": "Outdoor Run", "duration_min": duration, "focus": "long_run",
            "warmup": WARMUP_RUN, "exercises": exercises,
            "cooldown": COOLDOWN_RUN,
            "alternatives": {
                "home": "Treadmill — split into 2 x 35min if needed.",
                "hotel": "Look for a park loop or long promenade.",
                "no_equipment": "Just shoes + water bottle.",
                "easier": "Reduce to 45-50 min.",
                "harder": "Add 10 min at tempo pace in the middle.",
            },
            "rationale": "The long run is the KEY session of the week for marathon prep — teaches your body to stay efficient at low intensity for longer. Steady, conversational effort.",
            "key_session": True, "event_phase": None,
        }

    if session_type == "tempo":
        return {
            "date": date, "day_load": day_load, "title": "Tempo Run",
            "location": "Outdoor Run", "duration_min": 45, "focus": "tempo",
            "warmup": WARMUP_RUN, "exercises": TEMPO_RUN_MAIN,
            "cooldown": COOLDOWN_RUN,
            "alternatives": {
                "home": "Treadmill on 1% incline.",
                "hotel": "Treadmill.",
                "no_equipment": "Just shoes.",
                "easier": "Reduce tempo portion to 12-15 min.",
                "harder": "Split into 2 x 15 min tempo with 3 min jog.",
            },
            "rationale": "Tempo work lifts your lactate threshold — the pace you can hold before form breaks down. Comfortably hard, sustainable.",
            "key_session": False, "event_phase": None,
        }

    if session_type == "intervals":
        return {
            "date": date, "day_load": day_load, "title": "Interval Session",
            "location": "Outdoor Run", "duration_min": 45, "focus": "intervals",
            "warmup": WARMUP_INTERVALS, "exercises": INTERVAL_RUN_MAIN,
            "cooldown": COOLDOWN_RUN,
            "alternatives": {
                "home": "Treadmill — alternate 1 min hard / 90s easy for the interval block.",
                "hotel": "Local track or a straight 400m road segment.",
                "no_equipment": "Just shoes.",
                "easier": "4 x 400m instead of 6.",
                "harder": "8 x 400m or 6 x 500m.",
            },
            "rationale": "Intervals sharpen your VO2 max and running economy. Full effort on reps, easy recovery — quality over quantity.",
            "key_session": False, "event_phase": None,
        }

    if session_type == "strength_support":
        # Use hotel/bodyweight equivalent if roster is a layover
        exs = STRENGTH_FOR_RUNNERS
        loc = "Home Workout"
        if hotel_pref == "hotel":
            loc = "Hotel Gym Workout"
        elif hotel_pref == "bodyweight":
            # Bodyweight-only substitute — no dumbbells, no equipment
            exs = [
                {"name": "Single-leg glute bridge",   "sets": 3, "reps": "10 each side", "rest_sec": 45, "rpe": 6, "notes": "Slow, drive from the glute."},
                {"name": "Reverse lunge",             "sets": 3, "reps": "10 each leg", "rest_sec": 45, "rpe": 6, "notes": "Long step back — vertical torso."},
                {"name": "Push-up (or incline push-up)", "sets": 3, "reps": "8-15", "rest_sec": 45, "rpe": 7, "notes": "Scale to bed/desk edge."},
                {"name": "Calf raise",                "sets": 3, "reps": "15", "rest_sec": 40, "rpe": 6, "notes": "Slow, full range, pause at top."},
                {"name": "Bird-dog",                  "sets": 3, "reps": "8 each side", "rest_sec": 40, "rpe": 5, "notes": "Extend opposite arm/leg without twisting."},
                {"name": "Side plank",                "sets": 2, "reps": "30s each side", "rest_sec": 40, "rpe": 6, "notes": "Hips stacked, ribs down."},
            ]
            loc = "Hotel Room Workout"
        return {
            "date": date, "day_load": day_load, "title": "Strength for Runners",
            "location": loc, "duration_min": 40, "focus": "full",
            "warmup": WARMUP_GENERAL, "exercises": exs,
            "alternatives": {
                "home": "Full home version.",
                "hotel": "Bodyweight version — split squats + push-ups + planks.",
                "no_equipment": "Bodyweight only.",
                "easier": "Drop to 2 sets, longer rest.",
                "harder": "Add a 4th set on the primary lifts.",
            },
            "rationale": "Strength support for runners — glutes, hamstrings, calves + core. Injury-prevention insurance that keeps you consistent on the road.",
            "key_session": False, "event_phase": None,
        }

    if session_type in ("push_strength", "pull_strength", "upper_strength"):
        return {
            "date": date, "day_load": day_load,
            "title": {"push_strength": "Upper Push + Core", "pull_strength": "Upper Pull + Core", "upper_strength": "Upper Body Strength"}[session_type],
            "location": "Home Workout", "duration_min": 45,
            "focus": "push" if session_type == "push_strength" else ("pull" if session_type == "pull_strength" else "push"),
            "warmup": WARMUP_GENERAL,
            "exercises": FULL_BODY_STRENGTH if session_type == "upper_strength" else FULL_BODY_STRENGTH[:5],
            "alternatives": {
                "home": "Full home version.",
                "hotel": "Bodyweight version.",
                "no_equipment": "Push-ups + row variations.",
                "easier": "Drop to 2 sets.",
                "harder": "Add a superset at the end.",
            },
            "rationale": "Upper-body strength keeps posture healthy on long-haul flights and around the roster.",
            "key_session": False, "event_phase": None,
        }

    if session_type in ("leg_strength", "lower_strength"):
        return {
            "date": date, "day_load": day_load, "title": "Lower Body Strength",
            "location": "Home Workout", "duration_min": 50, "focus": "legs",
            "warmup": WARMUP_GENERAL, "exercises": FULL_BODY_STRENGTH,
            "alternatives": {
                "home": "Full home version.",
                "hotel": "Bodyweight version.",
                "no_equipment": "Bodyweight squat + reverse lunge + glute bridge.",
                "easier": "Drop to 2 sets, longer rest.",
                "harder": "Add tempo work to the primary lifts.",
            },
            "rationale": "Lower body strength — protect the knees and hips from long-standing / heavy walking on rotations.",
            "key_session": False, "event_phase": None,
        }

    if session_type == "conditioning":
        return {
            "date": date, "day_load": day_load, "title": "Conditioning Circuit",
            "location": "Home Workout", "duration_min": 30, "focus": "conditioning",
            "warmup": WARMUP_GENERAL, "exercises": CONDITIONING_CIRCUIT,
            "alternatives": {
                "home": "Full home version.",
                "hotel": "Bodyweight substitute — squats + push-ups + mountain climbers + planks.",
                "no_equipment": "Bodyweight version.",
                "easier": "3 sets instead of 4.",
                "harder": "Add a 5th round of the first 3 exercises.",
            },
            "rationale": "Short conditioning to keep heart-rate variability high and support fat-loss / general fitness without stealing recovery.",
            "key_session": False, "event_phase": None,
        }

    if session_type == "mobility":
        return {
            "date": date, "day_load": "amber", "title": "Mobility Flow",
            "location": "Home Workout", "duration_min": 20, "focus": "mobility",
            "warmup": WARMUP_MOBILITY, "exercises": MOBILITY_FLOW,
            "alternatives": {
                "home": "Same flow.", "hotel": "Same flow.", "no_equipment": "Fully bodyweight.",
                "easier": "Halve the reps.", "harder": "Add 5 minutes of easy walking after.",
            },
            "rationale": "Mobility flow — release tissue that flying + strength / running loads up. Best after a run or on off days.",
            "key_session": False, "event_phase": None,
        }

    if session_type == "recovery":
        return {
            "date": date, "day_load": "amber", "title": "Optional Recovery Walk",
            "location": "Outdoor Run", "duration_min": 25, "focus": "recovery",
            "warmup": WARMUP_MOBILITY, "exercises": [],
            "alternatives": {"home": "Walk outside.", "hotel": "Walk the hotel neighbourhood.", "no_equipment": "Just shoes.", "easier": "10 min walk.", "harder": "Add 5 min of easy jog."},
            "rationale": "Recovery walk — active recovery is optional. Skip it if you're tired; do it if you're moving well.",
            "key_session": False, "event_phase": None, "optional": True,
        }

    if session_type == "swim":
        return {
            "date": date, "day_load": day_load, "title": "Swim",
            "location": "Pool Swim", "duration_min": 45, "focus": "swim",
            "warmup": [{"name": "200m easy swim", "duration_sec": 300}],
            "exercises": [{"name": "Main swim set", "sets": 1, "reps": "1500m technique + steady", "rest_sec": 0, "rpe": 5, "notes": "Focus on stroke technique."}],
            "alternatives": {"home": "Skip if no pool — replace with 40min easy bike or run.", "hotel": "Hotel pool if available.", "no_equipment": "Swap for cycling or running.", "easier": "800m only.", "harder": "2000m with some tempo 100s."},
            "rationale": "Triathlon-focused swim session — technique-first, steady effort.",
            "key_session": False, "event_phase": None,
        }

    if session_type in ("easy_bike", "long_bike"):
        long = session_type == "long_bike"
        return {
            "date": date, "day_load": day_load, "title": "Long Ride" if long else "Easy Ride",
            "location": "Bike Session", "duration_min": 90 if long else 60, "focus": "bike",
            "warmup": [{"name": "10 min easy spin", "duration_sec": 600}],
            "exercises": [{"name": "Ride", "sets": 1, "reps": ("70-80 min steady" if long else "45-50 min steady"), "rest_sec": 0, "rpe": 5, "notes": "Conversational pace."}],
            "alternatives": {"home": "Indoor trainer.", "hotel": "Skip or replace with a run.", "no_equipment": "Swap for a run of similar duration.", "easier": "Reduce by 15 min.", "harder": "Add 15 min tempo effort mid-ride."},
            "rationale": "Bike session — protects joints while building aerobic capacity. Long ride is the key session in triathlon prep.",
            "key_session": long, "event_phase": None,
        }

    if session_type == "brick":
        return {
            "date": date, "day_load": day_load, "title": "Brick (Bike → Run)",
            "location": "Bike Session", "duration_min": 60, "focus": "brick",
            "warmup": [{"name": "5 min easy spin", "duration_sec": 300}],
            "exercises": [
                {"name": "45 min bike at RPE 6", "sets": 1, "reps": "45 min", "rest_sec": 0, "rpe": 6, "notes": "Steady effort."},
                {"name": "Transition + 15 min easy run", "sets": 1, "reps": "15 min", "rest_sec": 0, "rpe": 5, "notes": "Get used to running off the bike."},
            ],
            "alternatives": {"home": "Indoor trainer + treadmill.", "hotel": "Skip or split into 2 sessions.", "no_equipment": "Skip bike, do 45 min run.", "easier": "30 min bike + 10 min run.", "harder": "60 min bike + 20 min run."},
            "rationale": "Brick session — race-specific practice of running off the bike. Legs feel heavy the first km — that's normal.",
            "key_session": False, "event_phase": None,
        }

    # Unknown session type — return None so caller can skip
    return None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Roster day → session-type override rules (aviation safety)
# ---------------------------------------------------------------------------

def _classify_day(day: dict[str, Any]) -> str:
    """Map a roster day into one of the workout templates."""
    dtype = str(day.get("day_type") or day.get("type") or "").lower()
    if dtype in ("rest", "off", "annual_leave", "leave"):
        return "off"
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
    return "home"


def _override_for_duty(kind: str, date: str, duty_hours: Optional[float] = None) -> Any:
    """If the roster day forces a specific stub (safety), return it. Else None.

    Iter 94d (Gap 3) — flight_heavy override is now tiered by duty_hours:
      * <6h duty → 8-min airport mobility (short-haul)
      * 6-11h  → 15-min classic recovery mobility (medium-haul)
      * ≥12h   → 25-min ULR recovery + sleep prep protocol
    """
    if kind == "off":
        return None  # explicit rest — no card
    if kind == "flight_heavy":
        tpl = flight_recovery_template_for(duty_hours)
        # ULR is red load (sleep is the priority); shorter durations sit amber.
        load = "red" if tpl["tier"] == "ulr" or (duty_hours or 0) >= 10 else "amber"
        return {
            "date": date, "day_load": load, "title": tpl["title"],
            "location": "Post-Flight Mobility", "duration_min": tpl["duration_min"],
            "focus": "recovery",
            "warmup": WARMUP_MOBILITY, "exercises": tpl["exercises"],
            "alternatives": {"home": "Same flow.", "hotel": "Same flow.",
                             "no_equipment": "Bodyweight only.",
                             "easier": "Halve the reps.", "harder": "Add 10 min easy walk."},
            "rationale": tpl["rationale"],
            "recovery_tier": tpl["tier"],
            "duty_hours": duty_hours,
            "key_session": False, "event_phase": None, "optional": tpl["tier"] != "ulr",
        }
    if kind == "flight_light":
        return {
            "date": date, "day_load": "amber", "title": "Pre/Post-Flight Mobility",
            "location": "Pre-Flight Mobility", "duration_min": 12, "focus": "mobility",
            "warmup": WARMUP_MOBILITY, "exercises": FLIGHT_RECOVERY_MOBILITY,
            "alternatives": {"home": "Same flow.", "hotel": "Same flow.", "no_equipment": "Bodyweight only.", "easier": "Halve the reps.", "harder": "Add 10 min walk."},
            "rationale": "Short mobility around a flying duty — improve hip / shoulder position without adding fatigue.",
            "key_session": False, "event_phase": None,
        }
    if kind == "standby":
        return {
            "date": date, "day_load": "amber", "title": "Standby Activation",
            "location": "Home Workout", "duration_min": 20, "focus": "mobility",
            "warmup": WARMUP_MOBILITY, "exercises": STANDBY_ACTIVATION,
            "alternatives": {"home": "Same activation.", "hotel": "Same activation.", "no_equipment": "Fully bodyweight.", "easier": "Just the mobility warm-up.", "harder": "Add 10 min walking."},
            "rationale": "Standby — short activation keeps you ready without spending real energy.",
            "key_session": False, "event_phase": None,
        }
    if kind == "activation":
        return {
            "date": date, "day_load": "amber", "title": "Light Activation",
            "location": "Home Workout", "duration_min": 20, "focus": "mobility",
            "warmup": WARMUP_MOBILITY, "exercises": STANDBY_ACTIVATION,
            "alternatives": {"home": "Same session.", "hotel": "Same session.", "no_equipment": "Bodyweight-only.", "easier": "Skip the last 2 moves.", "harder": "Add 10 min walking."},
            "rationale": "Simulator / training day — keep the body warm without adding fatigue that could impact assessment.",
            "key_session": False, "event_phase": None,
        }
    # layover / home = no override — the goal-aware planner picks the session type
    return None


# ---------------------------------------------------------------------------
# Public: goal-aware plan builder (Plan B2)
# ---------------------------------------------------------------------------

def build_template_plan(user: dict[str, Any], roster: dict[str, Any],
                       hotel_lookup: dict[str, dict[str, Any]] | None = None,
                       progression_status: str | None = None,
                       effective_goal: dict[str, Any] | None = None,
                       live_state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Deterministic fallback plan for the whole roster window.

    NEW (Plan B2): goal-aware. Reads `profile.main_goal_key` and
    `profile.event_type_pref` to pick an ideal weekly shape from
    `feature_programme_quality.event_weekly_shape` or `strength_weekly_shape`.
    Runs, long runs, and strength-for-runners now appear for marathon clients.

    NEW (Phase 1 Hotel System): if `hotel_lookup` is provided (dict of
    hotel_id -> hotel_doc), each layover day is inspected:
      * Turnaround (<18h) → forced mobility (no strength / no long runs)
      * Layover w/ unknown hotel → forced bodyweight fallback
      * Layover w/ bodyweight-only hotel → forced bodyweight fallback
      * Layover w/ known gym → normal hotel gym stub

    NEW (Phase 5 Progression-Aware Marathon): if `progression_status` is
    provided (one of progressing_well / maintain / reduce_load / deload),
    long_run / tempo / intervals / easy_run sessions get their duration
    and reps scaled up or down accordingly, with a `change_reason` explaining
    the adjustment for the client "Why this changed" UI.

    NEW (Iter 94 · Phase 3.5): live_state wire-back. If `live_state` is
    provided, honour the same rules that gate the LLM path:
      * `auto_deload_trigger=True` → override phase to deload BEFORE resolving
        the weekly shape, cutting real strength/hard-run slots and adding
        recovery/mobility to fill.
      * `avoid_movement_patterns` → downstream guardrail pass will substitute,
        BUT we also short-circuit here by demoting a strength_support slot to
        recovery_walk when overhead_press / deep_squat is on the avoid list
        AND the phase isn't already deload (so we skip landing the risky
        template in the first place).
    """
    from feature_hotel_system import (
        classify_stay, is_bodyweight_only, reason_for,
    )
    from feature_progression import scale_endurance_session

    profile = user.get("profile") or {}
    hotel_pref = str(profile.get("hotel_gyms") or "").lower()
    if hotel_pref in ("never", "rare"):
        equip_pref = "bodyweight"
    elif hotel_pref in ("always", "often", "hotel_gym_reliable"):
        equip_pref = "hotel"
    else:
        equip_pref = "home"

    # Import lazily to avoid a cycle at module load
    from feature_programme_quality import (
        _resolve_goal_key, _phase_for_week, _phase_for_weeks_to_race,
        _long_run_km_for_week, _is_cutback_week,
        event_weekly_shape, strength_weekly_shape,
    )
    # Iter 84 (Task 1.5) — Effective-goal reconciliation. If the caller pre-
    # resolved an "effective goal" that considers registered events (e.g.
    # primary_goal=lose_fat + marathon in 14 weeks → goal_key=event,
    # ev_type=marathon), use it. Falls back to profile-only resolution.
    eff = effective_goal if isinstance(effective_goal, dict) else None
    if eff:
        goal_key = eff.get("goal_key") or _resolve_goal_key(profile)
        ev_type = eff.get("event_type") or profile.get("event_type_pref")
        volume_bias = eff.get("volume_bias") or "neutral"
        weeks_to_race = eff.get("weeks_to_event")
    else:
        goal_key = _resolve_goal_key(profile)
        ev_type = profile.get("event_type_pref")
        volume_bias = "neutral"
        weeks_to_race = None
    try:
        target_sessions = int(profile.get("training_days_per_week") or 4)
    except Exception:
        target_sessions = 4
    target_sessions = max(1, min(7, target_sessions))

    # Iter 84 (Task 1.6) — Phase resolution:
    #   Event mode → phase from weeks_to_race (base/build/peak/taper/race_week)
    #   Non-event  → legacy 4-week modulo
    if goal_key == "event" and ev_type:
        phase = _phase_for_weeks_to_race(weeks_to_race)
        long_km = _long_run_km_for_week(ev_type, weeks_to_race, cutback=_is_cutback_week(weeks_to_race))
    else:
        phase = _phase_for_week(0)
        long_km = None

    # Iter 94 (Phase 3.5) — Live-state wire-back for the deterministic fallback.
    # If check-ins fired the auto-deload rule, we OVERRIDE the phase before
    # picking the weekly shape so the whole week gets built as a deload.
    ls = live_state or {}
    live_avoid = list(ls.get("avoid_movement_patterns") or [])
    if ls.get("auto_deload_trigger") and phase.get("key") != "deload":
        phase = {"key": "deload", "label": "Deload (auto)",
                 "note": f"Auto-deload triggered — {ls.get('auto_deload_reason') or 'adherence + RPE'}"}
        # Also dial down long_km for endurance clients: use a cutback profile.
        if long_km is not None:
            long_km = round(long_km * 0.65, 1)

    if goal_key == "event" and ev_type:
        shape = event_weekly_shape(ev_type, phase["key"], target_sessions, weeks_to_race=weeks_to_race)
        # Iter 84 (Task 1.5) — volume_bias overlay: replace or drop sessions to
        # honour the client's primary non-endurance goal alongside the event.
        if volume_bias == "deficit" and target_sessions >= 4 and phase["key"] != "race_week":
            for i, s in enumerate(shape):
                if s == "strength_support":
                    shape[i] = "recovery_walk"
                    break
        elif volume_bias == "surplus" and target_sessions >= 4 and phase["key"] != "race_week":
            for i, s in enumerate(shape):
                if s == "easy_run":
                    shape[i] = "strength_support"
                    break
    else:
        shape = strength_weekly_shape(goal_key, target_sessions)

    # Iter 94 (Phase 3.5) — Auto-deload: cut ~35% of hard slots to recovery.
    if ls.get("auto_deload_trigger"):
        hard_slot_names = {
            "push_strength", "pull_strength", "upper_strength", "lower_strength",
            "leg_strength", "full_body_strength", "tempo", "intervals", "hyrox_wod",
            "long_run", "strength_support",
        }
        hard_indices = [i for i, s in enumerate(shape) if s in hard_slot_names]
        cut_n = max(1, len(hard_indices) // 3)  # drop ~1/3 to recovery
        # Prefer to demote the LAST hard slots (keep the first key session)
        for idx in reversed(hard_indices[-cut_n:]):
            shape[idx] = "recovery"

    # Iter 94 (Phase 3.5) — Pain-avoid short-circuit: if any pattern on the
    # avoid list matches upper-body pressing/pulling, demote a corresponding
    # strength slot to mobility so we never serve a risky stub. The downstream
    # guardrail will still catch anything that slips through at exercise level.
    if live_avoid and phase.get("key") != "deload":
        risky_upper = any(p in live_avoid for p in
                          ("overhead_press", "military_press", "handstand",
                           "close_grip_press", "chin_up", "heavy_pull"))
        risky_lower = any(p in live_avoid for p in
                          ("deep_squat", "pistol_squat", "box_jump",
                           "heavy_squat", "long_lunges"))
        risky_hinge = any(p in live_avoid for p in
                          ("deadlift", "hinge", "loaded_carry"))
        if risky_upper:
            for i, s in enumerate(shape):
                if s in ("push_strength", "upper_strength", "pull_strength"):
                    shape[i] = "mobility"
                    break
        if risky_lower:
            for i, s in enumerate(shape):
                if s in ("leg_strength", "lower_strength"):
                    shape[i] = "mobility"
                    break
        if risky_hinge:
            for i, s in enumerate(shape):
                if s in ("full_body_strength",):
                    shape[i] = "mobility"
                    break

    days = list(roster.get("days") or [])
    if not days:
        return []

    # Ensure days are in chronological order for layover-hour computation
    days.sort(key=lambda d: str(d.get("date") or ""))

    out: list[dict[str, Any]] = []
    # Iter 84 (Task 1.6) — inject long-run km + weeks-to-race so the long_run
    # stub can size the session accordingly (progressive volume curve).
    ctx_stub = {"hotel_pref": equip_pref, "long_run_km": long_km, "weeks_to_race": weeks_to_race}
    hotel_lookup = hotel_lookup or {}

    for wk_start in range(0, len(days), 7):
        week = days[wk_start: wk_start + 7]
        real_slots = [s for s in shape if s not in ("mobility", "recovery")]
        light_slots = [s for s in shape if s in ("mobility", "recovery")]
        while len(real_slots) + len(light_slots) < len(week):
            light_slots.append("recovery")

        queue = list(real_slots) + list(light_slots)

        for i, d in enumerate(week):
            date = d.get("date")
            if not date:
                continue
            # Use the NEXT day (across week boundary if needed) for layover-hours
            global_idx = wk_start + i
            next_d = days[global_idx + 1] if global_idx + 1 < len(days) else None
            stay = classify_stay(d, next_d)
            kind = _classify_day(d)  # legacy classifier for the safety overrides
            # Iter 94c (Gap 1) — the legacy classifier will force a 15-min
            # flight_heavy mobility even when the crew have 18h+ in the layover
            # destination. That wastes the layover training window. When both
            # classifiers agree it's a long-haul that leads INTO a real layover,
            # skip the safety override and let the goal-aware planner run — but
            # cap the session intensity, prepend the recovery mobility, and mark
            # the workout as `recovery_first`.
            recovery_first = False
            if kind == "flight_heavy":
                # Also true if the NEXT roster day is an explicit layover /
                # rest-at-hotel day (i.e., the crew are sleeping in destination
                # then flying home later). classify_stay's hour check is optional.
                next_is_layover_day = False
                if next_d:
                    _next_type = str(next_d.get("day_type") or "").lower()
                    if "layover" in _next_type or _next_type in ("rest", "off"):
                        # rest/off after a long-haul at a station is effectively a layover
                        # when the current day has a hotel_id.
                        next_is_layover_day = True
                _hid = d.get("hotel_id")
                _hdoc = hotel_lookup.get(_hid) if _hid else None
                if _hdoc and (stay == "layover" or next_is_layover_day):
                    kind = "layover"   # downgrade so the override below is bypassed
                    recovery_first = True
                # If no hotel doc, we keep flight_heavy — safer to force mobility.
            override = _override_for_duty(kind, date, duty_hours=d.get("duty_hours"))
            if override is not None:
                out.append(override)
                for j in range(len(queue) - 1, -1, -1):
                    if queue[j] in ("mobility", "recovery"):
                        queue.pop(j)
                        break
                else:
                    if queue:
                        queue.pop()
                continue
            if kind == "off":
                continue

            # PHASE 1 HOTEL SYSTEM — hard classification override for turnaround
            if stay == "turnaround":
                # Force mobility session — never long run / heavy strength
                w = _stub_for_session_type("mobility", date, dict(ctx_stub))
                if w:
                    w["hotel_stay_kind"] = "turnaround"
                    w["change_reason"] = reason_for(d, None, next_d)
                    out.append(w)
                # Consume a queue slot to keep totals aligned
                if queue:
                    queue.pop(0)
                continue

            if not queue:
                continue
            slot = queue.pop(0)
            # Iter 94c (Gap 1) — recovery_first long-haul → layover: never pick
            # a top-tier session for that slot. Down-shift to easy work.
            if recovery_first:
                if slot in ("long_run", "tempo", "intervals"):
                    slot = "easy_run"
                elif slot in ("push_strength", "pull_strength", "upper_strength",
                              "lower_strength", "leg_strength", "full_body_strength",
                              "hyrox_wod"):
                    slot = "strength_support"
            local_ctx = dict(ctx_stub)
            hotel_doc = None
            change_reason = None
            if stay == "layover":
                hid = d.get("hotel_id")
                hotel_doc = hotel_lookup.get(hid) if hid else None
                if is_bodyweight_only(hotel_doc):
                    # Unknown or bodyweight-only hotel → force bodyweight
                    local_ctx["hotel_pref"] = "bodyweight"
                    # Route strength slots to a bodyweight-safe strength session
                    if slot in ("push_strength", "pull_strength", "upper_strength",
                                "leg_strength", "lower_strength", "strength_support"):
                        slot = "strength_support"  # bodyweight-first template
                else:
                    local_ctx["hotel_pref"] = "hotel"
                change_reason = reason_for(d, hotel_doc, next_d)

            w = _stub_for_session_type(slot, date, local_ctx)
            if w:
                if stay == "layover":
                    w["hotel_stay_kind"] = "layover"
                    if hotel_doc:
                        w["hotel_id"] = hotel_doc.get("id")
                        w["hotel_name"] = hotel_doc.get("name")
                    if change_reason:
                        w["change_reason"] = change_reason
                # Iter 94c (Gap 1) — recovery-first layover: prepend the flight
                # recovery mobility as warm-up, cap intensity, downgrade load.
                if recovery_first:
                    w["recovery_first"] = True
                    w["day_load"] = "amber"
                    existing_warm = list(w.get("warmup") or [])
                    w["warmup"] = list(FLIGHT_RECOVERY_MOBILITY) + existing_warm
                    # Cap RPE on the main lifts.
                    for _ex in (w.get("exercises") or []):
                        try:
                            r = _ex.get("rpe")
                            if isinstance(r, (int, float)) and r > 7:
                                _ex["rpe"] = 7
                        except Exception:
                            pass
                    w.setdefault("change_reason",
                                 "Long-haul into layover — recovery mobility first, then a moderated session.")
                # Phase 5 — scale endurance sessions by progression_status
                if progression_status and slot in ("long_run", "tempo", "intervals", "easy_run"):
                    scale_endurance_session(w, progression_status, session_type=slot)
                # Iter 94 (Phase 3.5) — stamp auto-deload provenance
                if ls.get("auto_deload_trigger"):
                    w["auto_deload"] = True
                    w.setdefault("change_reason",
                                 "Auto-deload week — reduced load in response to your check-ins.")
                out.append(w)

    return out


def is_empty_or_llm_failure(workouts: list[dict[str, Any]]) -> bool:
    """True if the LLM returned nothing useful."""
    return not workouts or all(not (w.get("exercises") or w.get("warmup")) for w in workouts)
