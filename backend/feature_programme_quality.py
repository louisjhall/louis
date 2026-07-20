"""
feature_programme_quality — V1 programme structure, periodisation and validation.

Goal: make CrewFit's roster-driven workout generation feel like a real coaching
programme — not random sessions.

This module is deliberately non-invasive:

* `programme_context_for_llm(user, roster)` returns a compact JSON blob to inject
  into the existing Claude prompt inside `_generate_month`. It carries:
    - client's main_goal
    - suggested weekly session target
    - current periodisation phase (Foundation → Build → Peak → Deload)
    - progression note for THIS week
    - preferred weekly movement-pattern mix
    - deload / recovery guidance
    - roster-context summary (heavy days, long-haul flags, standby)

* `validate_programme(user, roster, workouts)` runs after generation. Returns
  `(ok, errors, summary)`. Called from the roster worker so we can:
    - open a HIGH-priority coach task if the plan is empty / random / unsafe
    - persist a `programme_summary` for the coach dashboard

* `persist_programme_record(user, roster, workouts, validation)` writes a
  lightweight `programmes` collection row for versioning / coach visibility.

No changes to the workouts collection schema — we only ADD documents to the
new `programmes` collection.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    logger,
)


# ---------------------------------------------------------------------------
# Goal → weekly structure catalog
# ---------------------------------------------------------------------------

GOAL_MATRIX: dict[str, dict[str, Any]] = {
    "lose_fat": {
        "label": "Fat loss",
        "target_sessions_per_week": 3,
        "session_style": "full-body strength + moderate conditioning",
        "movement_mix": {"push": 1, "pull": 1, "hinge": 1, "squat": 1, "core": 2, "conditioning": 1, "mobility": 1},
        "avoid": ["excessive fatigue back-to-back", "same-day double sessions"],
        "focus_copy": "Build the habit of consistent full-body training with moderate conditioning. Keep weekly load sustainable and protect recovery so nutrition + steps do the heavy lifting.",
    },
    "build_muscle": {
        "label": "Build strength / muscle",
        "target_sessions_per_week": 4,
        "session_style": "progressive strength on the big lifts",
        "movement_mix": {"push": 2, "pull": 2, "hinge": 1, "squat": 1, "core": 2, "mobility": 1},
        "avoid": ["heavy conditioning that steals recovery", "repeated hard leg days"],
        "focus_copy": "Progressive overload on the primary lifts. Keep conditioning short and low-intensity. Every session should include one primary movement pattern with clear rep/RPE targets.",
    },
    "general_fitness": {
        "label": "General fitness",
        "target_sessions_per_week": 3,
        "session_style": "balanced strength, conditioning and mobility",
        "movement_mix": {"push": 1, "pull": 1, "hinge": 1, "squat": 1, "core": 1, "conditioning": 1, "mobility": 1},
        "avoid": ["monotonous single-modality weeks"],
        "focus_copy": "Balanced weekly mix: 1–2 strength, 1 conditioning, 1 mobility/recovery. Optimise for consistency around the roster.",
    },
    "health_markers": {
        "label": "Health markers / medical",
        "target_sessions_per_week": 3,
        "session_style": "moderate strength + aerobic base + mobility",
        "movement_mix": {"push": 1, "pull": 1, "hinge": 1, "squat": 1, "core": 1, "conditioning": 1, "mobility": 2},
        "avoid": ["high-intensity extremes", "prolonged very-hard sessions"],
        "focus_copy": "Sustainable moderate training that supports blood pressure, sleep and long-term consistency. Avoid extreme intensity — CrewFit supports healthier habits but does not replace medical guidance.",
    },
    "event": {
        "label": "Event training",
        "target_sessions_per_week": 4,
        "session_style": "event-specific progression + protected key sessions",
        "movement_mix": {"long": 1, "intervals": 1, "tempo": 1, "strength": 1, "mobility": 1, "recovery": 1},
        "avoid": ["hard leg strength within 48h of a long endurance session"],
        "focus_copy": "Protect the key session each week. Recovery + taper logic applies as the event nears.",
    },
    "aviation_consistency": {
        "label": "Aviation consistency",
        "target_sessions_per_week": 3,
        "session_style": "minimum effective dose, roster-aware",
        "movement_mix": {"push": 1, "pull": 1, "hinge": 1, "squat": 1, "core": 1, "mobility": 2},
        "avoid": ["hard sessions after long-haul / night duty"],
        "focus_copy": "Minimum effective dose: 2–3 short strength sessions plus mobility around demanding duties. Hotel/bodyweight versions ready for turnarounds.",
    },
    "improve_energy": {
        "label": "Improve energy",
        "target_sessions_per_week": 3,
        "session_style": "aerobic base + mobility + light strength",
        "movement_mix": {"conditioning": 1, "mobility": 2, "strength": 1, "recovery": 1},
        "avoid": ["fatigue-driving intensity late in the week"],
        "focus_copy": "Build an aerobic base and prioritise mobility. Keep intensity manageable and sleep + steps consistent.",
    },
    "return_to_training": {
        "label": "Return to training",
        "target_sessions_per_week": 2,
        "session_style": "rebuild volume gently",
        "movement_mix": {"push": 1, "pull": 1, "hinge": 1, "squat": 1, "core": 1, "mobility": 2},
        "avoid": ["heavy loading in week 1", "sudden volume jumps"],
        "focus_copy": "Ramp gradually. First two weeks = movement quality + baseline volume. Watch DOMS and adjust before adding intensity.",
    },
}

DEFAULT_GOAL_KEY = "general_fitness"


# ---------------------------------------------------------------------------
# 4-week periodisation
# ---------------------------------------------------------------------------

PHASES = [
    {"key": "foundation", "label": "Foundation", "note": "Baseline movement quality; slightly conservative loads."},
    {"key": "build",       "label": "Build",       "note": "Small progression on sets/reps/load."},
    {"key": "peak",        "label": "Peak",        "note": "Strongest week — highest quality effort, still within recovery capacity."},
    {"key": "deload",      "label": "Deload",      "note": "Reduce volume by 30–40%; keep movement quality high."},
]


def _phase_for_week(week_index: int) -> dict[str, str]:
    return PHASES[week_index % 4]


def _resolve_goal_key(profile: dict) -> str:
    """Best-effort map from onboarding/assessment fields to a goal key.

    Priority order:
    1. Structured `main_goal_key` set by the Basic Profile Setup step (must
       match a key in GOAL_MATRIX exactly).
    2. Free-text `main_goal` / `primary_goal` — keyword-matched.
    3. Fallback: DEFAULT_GOAL_KEY.
    """
    structured = str(profile.get("main_goal_key") or "").strip().lower()
    if structured and structured in GOAL_MATRIX:
        return structured
    raw = str(profile.get("main_goal") or profile.get("primary_goal") or profile.get("goal") or "").lower()
    if not raw:
        return DEFAULT_GOAL_KEY
    if any(k in raw for k in ("fat", "weight loss", "lose")):
        return "lose_fat"
    if any(k in raw for k in ("muscle", "build", "strength", "hypertrophy")):
        return "build_muscle"
    if any(k in raw for k in ("event", "race", "marathon", "triathlon", "ironman", "hyrox", "5k", "10k")):
        return "event"
    if any(k in raw for k in ("health", "medical", "blood pressure", "cholesterol")):
        return "health_markers"
    if any(k in raw for k in ("energy", "vitality")):
        return "improve_energy"
    if any(k in raw for k in ("return", "come back", "post-injury", "rehab")):
        return "return_to_training"
    if any(k in raw for k in ("consist", "roster", "aviation", "flying")):
        return "aviation_consistency"
    if "fitness" in raw:
        return "general_fitness"
    return DEFAULT_GOAL_KEY


def _roster_summary(roster: dict) -> dict[str, Any]:
    """Compact context passed to the LLM about the roster."""
    days = roster.get("days") or []
    types: dict[str, int] = {}
    for d in days:
        t = (d.get("day_type") or d.get("type") or "unknown")
        types[t] = types.get(t, 0) + 1
    long_haul = sum(1 for d in days if float(d.get("duty_hours") or 0) >= 10 or "long" in (d.get("day_type") or "").lower())
    night_or_overnight = sum(1 for d in days if any(k in (d.get("day_type") or "").lower() for k in ("night", "overnight", "red_eye", "red-eye")))
    return {
        "total_days": len(days),
        "type_counts": types,
        "long_haul_days": long_haul,
        "night_or_overnight_days": night_or_overnight,
    }


# ---------------------------------------------------------------------------
# Programme context builder — the piece injected into the LLM prompt
# ---------------------------------------------------------------------------

async def programme_context_for_llm(user: dict, roster: dict) -> dict[str, Any]:
    """Build a small JSON blob describing the client's programme intent for the
    workout generator. Safe: fully deterministic, no LLM calls."""
    profile = user.get("profile") or {}
    goal_key = _resolve_goal_key(profile)
    goal_meta = GOAL_MATRIX.get(goal_key) or GOAL_MATRIX[DEFAULT_GOAL_KEY]

    # Compute this ROSTER'S start date + working week index.
    days = roster.get("days") or []
    start_iso = (days[0].get("date") if days else None) or _dt.date.today().isoformat()
    try:
        start_date = _dt.date.fromisoformat(start_iso[:10])
    except Exception:
        start_date = _dt.date.today()
    # How many complete 7-day windows since programme start? Look at prior
    # programme rows for this user so we resume periodisation rather than
    # restarting at Foundation every roster.
    # If a programme record already exists for THIS roster (e.g. this is a
    # retry), reuse its week_index so periodisation stays stable across retries.
    roster_id = roster.get("id")
    existing_for_roster = None
    if roster_id:
        existing_for_roster = await db.programmes.find_one(
            {"user_id": user["id"], "roster_id": roster_id}, {"_id": 0}
        )
    if existing_for_roster and existing_for_roster.get("week_index"):
        week_index = int(existing_for_roster["week_index"])
    else:
        last_prog = await db.programmes.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)])
        prior_week = int((last_prog or {}).get("week_index") or 0)
        week_index = prior_week + 1
    phase = _phase_for_week(week_index - 1)  # 0-indexed for phase lookup

    # Weekly target — bounded by experience.
    # `experience_level` is what the onboarding form writes;
    # `experience` is the legacy shorter key. Accept both.
    experience = str(profile.get("experience_level") or profile.get("experience") or "").lower()
    target = goal_meta["target_sessions_per_week"]
    if experience == "beginner":
        target = min(target, 3)
    if experience == "advanced" and goal_key in ("build_muscle", "event"):
        target = min(target + 1, 5)

    # Days available (skip long-haul + night days as candidates for hard sessions)
    hard_capable_days = [d for d in days if not any(k in (d.get("day_type") or "").lower() for k in ("long_haul", "long-haul", "night_flight", "night-flight", "overnight", "red_eye"))]

    ctx = {
        "goal_key": goal_key,
        "goal_label": goal_meta["label"],
        "focus_copy": goal_meta["focus_copy"],
        "target_sessions_per_week": target,
        "session_style": goal_meta["session_style"],
        "movement_mix_hint": goal_meta["movement_mix"],
        "avoid": goal_meta["avoid"],
        "week_index": week_index,
        "phase": phase,
        "phase_progression_note": phase["note"],
        "roster_summary": _roster_summary(roster),
        "hard_capable_day_count": len(hard_capable_days),
        "start_date": start_iso[:10],
        "profile_snapshot": {
            "role": profile.get("role") or profile.get("position"),
            "job_title": profile.get("job_title"),
            "airline": profile.get("airline"),
            "home_base": profile.get("home_base"),
            "route_focus": profile.get("route_focus"),
            "aircraft_type": profile.get("aircraft_type"),
            "experience": experience,
            "hotel_gyms": profile.get("hotel_gyms"),
            "training_days_per_week": profile.get("training_days_per_week"),
            "injury_notes": profile.get("injury_notes") or profile.get("injuries"),
            "main_goal_key": profile.get("main_goal_key"),
            "main_goal_raw": profile.get("main_goal") or profile.get("primary_goal") or profile.get("goal"),
        },
    }
    return ctx


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------

def validate_programme(
    user: dict,
    roster: dict,
    workouts: list[dict],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Run the deterministic quality gate over a batch of freshly generated
    workouts. Returns:
        {
          "ok": bool,
          "errors": [str, ...],           # hard failures
          "warnings": [str, ...],         # soft issues (for coach visibility)
          "summary": {
              "workouts_next_7_days": int,
              "workouts_total": int,
              "sessions_this_week": int,
              "target_sessions_per_week": int,
              "movement_pattern_counts": {...},
          },
        }
    """
    errors: list[str] = []
    warnings: list[str] = []

    today = _dt.date.today().isoformat()
    horizon = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
    next7 = [w for w in workouts if today <= (w.get("date") or "") <= horizon]
    actual_sessions_next7 = [w for w in next7 if w.get("focus") not in ("recovery", "mobility", "rest")]

    if not workouts:
        errors.append("no workouts generated")
    else:
        # 1. At least ONE real workout in next 7 days (unless all 7 are heavy roster).
        heavy_days_next7 = 0
        rd = {d.get("date"): d for d in (roster.get("days") or [])}
        for i in range(8):
            iso = (_dt.date.today() + _dt.timedelta(days=i)).isoformat()
            drow = rd.get(iso)
            dtype = str((drow or {}).get("day_type") or "").lower()
            if any(k in dtype for k in ("long_haul", "long-haul", "night_flight", "night-flight", "overnight", "red_eye")):
                heavy_days_next7 += 1
        if not actual_sessions_next7 and heavy_days_next7 < 6:
            errors.append("no real training sessions in the next 7 days")
        elif len(actual_sessions_next7) < 1:
            warnings.append("light training week — mostly recovery only")

        # 2. Every workout must have at least ONE exercise item (unless recovery/rest).
        empty = 0
        for w in workouts:
            fx = (w.get("focus") or "").lower()
            if fx in ("recovery", "mobility", "rest"):
                continue
            if not (w.get("exercises") or w.get("warmup")):
                empty += 1
        if empty:
            errors.append(f"{empty} workout(s) had no exercises")

        # 3. Movement-pattern balance — best-effort keyword match on titles/focus.
        pat_counts = {"push": 0, "pull": 0, "hinge": 0, "squat": 0, "core": 0, "mobility": 0, "conditioning": 0, "long": 0}
        for w in workouts:
            t = f"{w.get('title', '')} {w.get('focus', '')}".lower()
            if any(k in t for k in ("push", "chest", "press")): pat_counts["push"] += 1
            if any(k in t for k in ("pull", "row", "chin", "back")): pat_counts["pull"] += 1
            if any(k in t for k in ("hinge", "deadlift", "hip")): pat_counts["hinge"] += 1
            if any(k in t for k in ("squat", "leg", "lower")): pat_counts["squat"] += 1
            if "core" in t: pat_counts["core"] += 1
            if any(k in t for k in ("mobility", "recovery", "flow")): pat_counts["mobility"] += 1
            if any(k in t for k in ("cardio", "conditioning", "intervals", "tempo", "zone")): pat_counts["conditioning"] += 1
            if "long_run" in t or "long run" in t: pat_counts["long"] += 1

        # Warn (not error) if the mix is very lopsided.
        strength_pats = pat_counts["push"] + pat_counts["pull"] + pat_counts["hinge"] + pat_counts["squat"]
        if strength_pats and strength_pats > 0:
            max_pat = max(pat_counts["push"], pat_counts["pull"], pat_counts["hinge"], pat_counts["squat"])
            if max_pat > strength_pats * 0.7:
                warnings.append("strength pattern imbalance — one pattern dominates the week")

        # 4. First workout not on today (respected setup-day gate).
        first_iso = min([w.get("date") for w in workouts if w.get("date")], default=None)
        if first_iso == today:
            warnings.append("first workout landed on signup/setup day")

        # 5. Every session should have a rationale — soft requirement.
        no_rationale = sum(1 for w in workouts if not (w.get("rationale") or "").strip())
        if no_rationale and workouts:
            pct = no_rationale / len(workouts)
            if pct > 0.5:
                warnings.append(f"{no_rationale}/{len(workouts)} workouts have no 'why this session' rationale")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "workouts_total": len(workouts),
            "workouts_next_7_days": len(next7),
            "real_sessions_next_7_days": len(actual_sessions_next7),
            "target_sessions_per_week": context.get("target_sessions_per_week"),
            "phase": (context.get("phase") or {}).get("key"),
            "goal_key": context.get("goal_key"),
            "goal_label": context.get("goal_label"),
        },
    }


# ---------------------------------------------------------------------------
# Persistence: lightweight programmes collection
# ---------------------------------------------------------------------------

async def persist_programme_record(
    user: dict,
    roster: dict,
    workouts: list[dict],
    context: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    """Store a versioned programme row so the coach dashboard can review it.

    Idempotent per (user_id, roster_id): a retry on the same roster UPDATES the
    existing row instead of creating a duplicate. This keeps the invariant
    "one programme record per user per month/roster" clean.
    """
    days = roster.get("days") or []
    start_iso = (days[0].get("date") if days else None)
    end_iso = (days[-1].get("date") if days else None)
    roster_id = roster.get("id")

    # If a row already exists for this (user_id, roster_id), we upsert-update it
    # rather than allocating a fresh version_number.
    existing = None
    if roster_id:
        existing = await db.programmes.find_one({"user_id": user["id"], "roster_id": roster_id}, {"_id": 0})

    if existing:
        pid = existing.get("id") or new_id()
        version_number = int(existing.get("version_number") or 1)
    else:
        last = await db.programmes.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)])
        version_number = int((last or {}).get("version_number") or 0) + 1
        pid = new_id()

    doc = {
        "id": pid,
        "user_id": user["id"],
        "roster_id": roster_id,
        "version_number": version_number,
        "week_index": context.get("week_index"),
        "goal_key": context.get("goal_key"),
        "goal_label": context.get("goal_label"),
        "focus_copy": context.get("focus_copy"),
        "phase": context.get("phase"),
        "target_sessions_per_week": context.get("target_sessions_per_week"),
        "session_style": context.get("session_style"),
        "movement_mix_hint": context.get("movement_mix_hint"),
        "start_date": start_iso,
        "end_date": end_iso,
        "roster_context_summary": context.get("roster_summary"),
        "generated_reasoning": validation.get("summary"),
        "validation_status": "ok" if validation.get("ok") else "needs_review",
        "validation_errors": validation.get("errors") or [],
        "validation_warnings": validation.get("warnings") or [],
        "coach_approved": bool(existing.get("coach_approved")) if existing else False,
        "created_at": (existing or {}).get("created_at") or now_iso(),
        "updated_at": now_iso(),
    }
    if existing:
        await db.programmes.update_one({"id": pid}, {"$set": doc})
    else:
        await db.programmes.insert_one(doc)
    return pid


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@api.get("/programme/current")
async def programme_current(user: dict = Depends(current_user)):
    p = await db.programmes.find_one({"user_id": user["id"]}, {"_id": 0}, sort=[("created_at", -1)])
    return p or {}


@api.get("/coach/clients/{client_id}/programme")
async def coach_programme_for_client(client_id: str, coach: dict = Depends(require_role("coach"))):
    """Coach visibility into the client's most recent programme + validation."""
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")
    p = await db.programmes.find_one({"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)])
    if not p:
        return {"programme": None}
    # Attach next-7-days preview from the workouts collection.
    today = _dt.date.today().isoformat()
    horizon = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
    preview = await db.workouts.find(
        {"user_id": client_id, "date": {"$gte": today, "$lte": horizon}},
        {"_id": 0, "id": 1, "date": 1, "title": 1, "focus": 1, "day_load": 1, "duration_min": 1, "rationale": 1},
    ).sort("date", 1).to_list(20)
    return {"programme": p, "next_7_days": preview}


@api.get("/coach/clients/{client_id}/programme/history")
async def coach_programme_history(client_id: str, coach: dict = Depends(require_role("coach"))):
    rows = await db.programmes.find({"user_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return {"programmes": rows, "count": len(rows)}
