"""
Coach Workout Swap Suggestions — Phase 5.

Endpoint:
    GET  /api/coach/workouts/{wid}/swap-suggestions
        Returns 3 curated alternative session presets whose training focus
        is SAFE for the workout's date (respects parser training_colour,
        blocked[], equipment_assumption).

    POST /api/coach/workouts/{wid}/apply-swap
        body: {preset_id: "..."}
        Replaces the workout content with the chosen preset. Persists
        `coach_swap_from` audit fields so we can roll back / show diff.
"""
from __future__ import annotations
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso
import logging
logger = logging.getLogger("crewfit.coach_workout_swap")


# ---------------------------------------------------------------------------
# Preset catalogue — small, curated, coach-voice.
# Each preset knows which parser categories it maps to so we can filter by
# the day's blocked[] list.
# ---------------------------------------------------------------------------

_PRESETS: list[dict] = [
    {
        "id": "hotel_mobility_15",
        "title": "Hotel Mobility Flow",
        "focus": "mobility",
        "categories": ["mobility"],
        "duration_min": 15,
        "location": "Hotel Room",
        "rationale": "Gentle mobility + breath work — perfect for a rest, layover or post-flight day.",
        "exercises": [
            {"name": "World's greatest stretch", "sets": 1, "reps": "6/side"},
            {"name": "90/90 hip switches", "sets": 1, "reps": "10/side"},
            {"name": "Cat-cow flow", "sets": 1, "reps": "10"},
            {"name": "Down-dog to cobra", "sets": 1, "reps": "8"},
            {"name": "Child's pose hold", "sets": 1, "reps": "60s"},
        ],
    },
    {
        "id": "recovery_walk_25",
        "title": "Easy Recovery Walk",
        "focus": "recovery",
        "categories": ["recovery_walk", "steps_only"],
        "duration_min": 25,
        "location": "Outdoors",
        "rationale": "Zone-1 walk to flush the legs and reset the nervous system.",
        "exercises": [
            {"name": "Nasal-breathing walk", "sets": 1, "reps": "25 min"},
            {"name": "Diaphragm reset breaths", "sets": 1, "reps": "10 rounds"},
        ],
    },
    {
        "id": "bodyweight_full_35",
        "title": "Bodyweight Full Body",
        "focus": "bodyweight",
        "categories": ["bodyweight", "hotel_strength"],
        "duration_min": 35,
        "location": "Hotel Room / Home",
        "rationale": "No-equipment full-body session — great for hotel rooms.",
        "exercises": [
            {"name": "Bodyweight squat", "sets": 4, "reps": "12"},
            {"name": "Push-up", "sets": 4, "reps": "10-15"},
            {"name": "Reverse lunge", "sets": 3, "reps": "10/side"},
            {"name": "Bird dog", "sets": 3, "reps": "8/side"},
            {"name": "Plank hold", "sets": 3, "reps": "45s"},
        ],
    },
    {
        "id": "easy_run_40",
        "title": "Easy Aerobic Run",
        "focus": "easy_run",
        "categories": ["easy_run"],
        "duration_min": 40,
        "location": "Outdoors / Treadmill",
        "rationale": "Zone-2 conversational-pace run — keeps aerobic base ticking.",
        "exercises": [
            {"name": "Zone 2 easy run", "sets": 1, "reps": "40 min conversational"},
        ],
    },
    {
        "id": "gym_strength_50",
        "title": "Full-Gym Strength",
        "focus": "strength",
        "categories": ["main_strength"],
        "duration_min": 50,
        "location": "Full Gym",
        "rationale": "Compound-lift session — squat/hinge/push/pull.",
        "exercises": [
            {"name": "Back squat", "sets": 4, "reps": "6"},
            {"name": "Romanian deadlift", "sets": 3, "reps": "8"},
            {"name": "Bench press", "sets": 4, "reps": "8"},
            {"name": "Barbell row", "sets": 3, "reps": "10"},
            {"name": "Farmer carry", "sets": 3, "reps": "40m"},
        ],
    },
    {
        "id": "intervals_30",
        "title": "Short Intervals",
        "focus": "intervals",
        "categories": ["intervals"],
        "duration_min": 30,
        "location": "Outdoors / Track / Treadmill",
        "rationale": "5×3 min hard, 2 min easy — VO2 stimulus for a green day.",
        "exercises": [
            {"name": "Warm-up jog", "sets": 1, "reps": "10 min"},
            {"name": "3-min hard interval", "sets": 5, "reps": "2 min easy between"},
            {"name": "Cool-down jog", "sets": 1, "reps": "5 min"},
        ],
    },
]


def _rank_presets(day: dict) -> list[dict]:
    """Rank presets for a given day. Filters out blocked categories.
    Returns list with a `fit_score` (0-100)."""
    try:
        from parser_constraints import constraints_for_day
        prof = constraints_for_day(day or {})
    except Exception:
        prof = None

    ranked: list[dict] = []
    for p in _PRESETS:
        cats = set(p.get("categories") or [])
        # Hard filter: any category in the blocked list → skip.
        if prof and prof.blocked and (cats & set(prof.blocked)):
            continue
        score = 50
        # Colour affinity
        if prof:
            if prof.colour == "black":
                # Everything blocked — only pure rest survives.
                if "mobility" not in cats and "steps_only" not in cats:
                    continue
                score = 100 if "mobility" in cats else 60
            elif prof.colour == "red":
                if p["focus"] in ("mobility", "recovery"):
                    score = 100
                elif p["focus"] in ("bodyweight", "easy_run"):
                    score = 40
                else:
                    score = 10
            elif prof.colour == "amber":
                if p["focus"] in ("mobility", "recovery", "bodyweight", "easy_run"):
                    score = 90
                elif p["focus"] == "strength":
                    score = 55
                else:
                    score = 40
            else:  # green
                if p["focus"] in ("strength", "easy_run", "intervals"):
                    score = 95
                elif p["focus"] in ("bodyweight", "recovery"):
                    score = 60
                else:
                    score = 45
        # Equipment affinity
        if prof and prof.equipment == "hotel_or_bodyweight":
            if p["focus"] == "strength":
                score = min(score, 30)
            if p["focus"] in ("bodyweight", "mobility"):
                score = max(score, 70)
        # Duration cap
        if prof and prof.max_duration_min:
            if p["duration_min"] > prof.max_duration_min + 15:
                score = min(score, 25)
        ranked.append({**p, "fit_score": score})
    ranked.sort(key=lambda p: -p["fit_score"])
    return ranked


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.get("/coach/workouts/{wid}/swap-suggestions")
async def coach_workout_swap_suggestions(
    wid: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    workout = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not workout:
        raise HTTPException(404, "Workout not found")
    # Find the roster day for this workout's date
    uid = workout.get("user_id")
    dt = workout.get("date")
    day: dict = {}
    if uid and dt:
        roster = await db.rosters.find_one(
            {"user_id": uid, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)]
        )
        for d in (roster or {}).get("days", []):
            if d.get("date") == dt:
                day = d
                break
    ranked = _rank_presets(day)
    return {
        "workout_id": wid,
        "date": dt,
        "day": {
            "training_colour": day.get("training_colour"),
            "client_label": day.get("client_label"),
            "blocked": day.get("blocked") or [],
            "equipment_assumption": day.get("equipment_assumption"),
        },
        "suggestions": ranked[:5],
    }


class ApplySwapBody(BaseModel):
    preset_id: str
    reason: Optional[str] = None


@api.post("/coach/workouts/{wid}/apply-swap")
async def coach_workout_apply_swap(
    wid: str,
    body: ApplySwapBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    workout = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not workout:
        raise HTTPException(404, "Workout not found")
    preset = next((p for p in _PRESETS if p["id"] == body.preset_id), None)
    if not preset:
        raise HTTPException(400, f"Unknown preset_id '{body.preset_id}'")

    # Iter 142 — every preset exercise MUST route through the unified
    # Exercise Library pipeline. Phase B fuzzy dedup reuses approved rows;
    # unknown names file a draft. Plain-text exercise names are NEVER
    # written to `db.workouts` any more.
    from feature_media_queue import resolve_or_draft_exercise

    owner = await db.users.find_one({"id": workout.get("user_id")}, {"_id": 0}) or {}
    resolved_exercises: list[dict] = []
    library_summary = {"reused_approved": 0, "matched_fuzzy": 0, "drafts_created": 0, "unresolved": 0}
    for raw in (preset.get("exercises") or []):
        item = dict(raw)
        name = item.get("name") or item.get("exercise_name")
        if not name:
            continue
        try:
            ex_id = await resolve_or_draft_exercise(
                name,
                user=owner or {"id": coach.get("id"), "role": "coach"},
                reason=f"coach_preset_swap:{body.preset_id}",
                workout_id=wid,
            )
        except Exception:
            logger.exception("apply-swap: resolve_or_draft failed for %r", name)
            ex_id = None
        item["exercise_name"] = name
        if ex_id:
            item["exercise_id"] = ex_id
            row = await db.exercises_v2.find_one(
                {"id": ex_id},
                {"_id": 0, "status": 1, "approval_status": 1, "exercise_name": 1},
            ) or {}
            item["library_source"] = (
                "approved_match"
                if str(row.get("status")) in ("Approved", "Live")
                or str(row.get("approval_status")).lower() == "approved"
                else "draft"
            )
            # Display the canonical library name if it differs — coach
            # sees the actual library entry, not the preset alias.
            if row.get("exercise_name"):
                item["exercise_name_display"] = row["exercise_name"]
            if item["library_source"] == "approved_match":
                library_summary["reused_approved"] += 1
            else:
                library_summary["drafts_created"] += 1
        else:
            item["library_source"] = "unresolved"
            library_summary["unresolved"] += 1
            logger.warning("apply-swap: could not resolve %r for wid=%s", name, wid)
        resolved_exercises.append(item)

    # Preserve identity fields; replace content with library-linked rows.
    patch = {
        "title": preset["title"],
        "focus": preset["focus"],
        "duration_min": preset["duration_min"],
        "location": preset["location"],
        "rationale": preset["rationale"],
        "exercises": resolved_exercises,
        "warmup": workout.get("warmup") or [],
        "updated_at": now_iso(),
        "coach_swap_from": {
            "title": workout.get("title"),
            "focus": workout.get("focus"),
            "duration_min": workout.get("duration_min"),
        },
        "coach_swap_preset": body.preset_id,
        "coach_swap_reason": body.reason,
        "coach_swap_library_summary": library_summary,
        "coach_swap_at": now_iso(),
        "coach_swap_by": coach.get("id"),
        # Reset approval so the new content flows through the normal review.
        "approved": False,
    }
    # Add a jittered 2-8 min client delay so the swap doesn't appear
    # instantaneous. Coach sees it immediately.
    try:
        import random as _rnd
        from datetime import datetime as _dt2, timedelta as _td2, timezone as _tz2
        delay_s = _rnd.randint(2 * 60, 8 * 60)
        patch["visible_from"] = (_dt2.now(_tz2.utc) + _td2(seconds=delay_s)).isoformat()
        patch["visible_from_reason"] = "coach_swapped"
    except Exception:
        logger.exception("Failed to attach coach-swap visible_from delay (non-fatal)")
    await db.workouts.update_one({"id": wid}, {"$set": patch})
    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})
    return {"ok": True, "workout": fresh, "preset_id": body.preset_id}
