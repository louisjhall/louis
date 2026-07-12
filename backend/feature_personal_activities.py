"""
feature_personal_activities — Personal Activity Planner (V1 / beta).

Lets clients add their own sports/hobbies (tennis, padel, football, diving,
running, cycling, swimming, hiking, skiing, golf, martial arts, climbing,
yoga, pilates, custom) into their CrewFit schedule so Atlas can plan gym
training around them.

DESIGN NOTES
------------
* Endpoints live under /api/personal-activities/* and /api/coach/clients/{id}/personal-activities.
* Suggestions are RULE-BASED (deterministic, no LLM cost) — safe for V1.
* Recurrence is expanded on write up to 12 weeks ahead. Each occurrence has its
  own doc so calendar/today reads stay simple and edits per-occurrence work
  naturally.
* Adjustment actions (keep/move/reduce/ask_coach) route into the existing
  workouts + coach_tasks tables — no new pipelines.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    logger,
    _create_coach_task,
    _log_change,
)

# ---------------------------------------------------------------------------
# Activity catalog — deterministic load estimates. Keep language plain.
# ---------------------------------------------------------------------------

ACTIVITY_PRESETS: list[dict[str, Any]] = [
    {
        "key": "tennis", "label": "Tennis", "icon": "tennisball",
        "default_intensity": "moderate", "default_duration_min": 60,
        "load_areas": ["lower", "rotation", "shoulders"], "load_score": 6,
        "note": "Repeated acceleration and rotation — moderate-to-high lower-body and shoulder load.",
    },
    {
        "key": "padel", "label": "Padel", "icon": "tennisball",
        "default_intensity": "moderate", "default_duration_min": 60,
        "load_areas": ["lower", "rotation", "shoulders"], "load_score": 5,
        "note": "Similar demands to tennis with more doubles and shorter court.",
    },
    {
        "key": "football", "label": "Football", "icon": "football",
        "default_intensity": "hard", "default_duration_min": 90,
        "load_areas": ["lower", "cardio"], "load_score": 8,
        "note": "High lower-body load, sprints, change of direction.",
    },
    {
        "key": "running", "label": "Running", "icon": "walk",
        "default_intensity": "moderate", "default_duration_min": 45,
        "load_areas": ["lower", "cardio"], "load_score": 6,
        "note": "Aerobic and lower-body load, scales with pace and duration.",
    },
    {
        "key": "cycling", "label": "Cycling", "icon": "bicycle",
        "default_intensity": "moderate", "default_duration_min": 60,
        "load_areas": ["lower", "cardio"], "load_score": 5,
        "note": "Endurance-focused lower-body load, low impact.",
    },
    {
        "key": "swimming", "label": "Swimming", "icon": "water",
        "default_intensity": "moderate", "default_duration_min": 45,
        "load_areas": ["upper", "cardio"], "load_score": 5,
        "note": "Full-body low-impact aerobic work with shoulder emphasis.",
    },
    {
        "key": "diving", "label": "Diving", "icon": "water",
        "default_intensity": "light", "default_duration_min": 90,
        "load_areas": ["recovery"], "load_score": 3,
        "note": "Low-to-moderate physical load but consider fatigue, travel and equipment carrying.",
        "safety_note": "CrewFit can help plan training load around this activity — it does not replace certified dive instruction, medical clearance or safety guidance.",
    },
    {
        "key": "surfing", "label": "Surfing", "icon": "water",
        "default_intensity": "moderate", "default_duration_min": 90,
        "load_areas": ["upper", "core", "cardio"], "load_score": 6,
        "note": "Paddling and pop-ups load shoulders and core; scales with wave count.",
    },
    {
        "key": "hiking", "label": "Hiking", "icon": "trail-sign",
        "default_intensity": "moderate", "default_duration_min": 120,
        "load_areas": ["lower", "endurance"], "load_score": 6,
        "note": "Duration-dependent lower-body and endurance load, especially with a pack.",
    },
    {
        "key": "skiing", "label": "Skiing", "icon": "snow",
        "default_intensity": "hard", "default_duration_min": 240,
        "load_areas": ["lower", "core"], "load_score": 8,
        "note": "Prolonged eccentric lower-body load, especially quads and glutes.",
        "safety_note": "Follow local piste safety and take professional instruction where needed.",
    },
    {
        "key": "golf", "label": "Golf", "icon": "golf",
        "default_intensity": "light", "default_duration_min": 240,
        "load_areas": ["rotation", "walking"], "load_score": 3,
        "note": "Long walk plus rotational load through hips and thoracic spine.",
    },
    {
        "key": "martial_arts", "label": "Martial Arts", "icon": "flame",
        "default_intensity": "hard", "default_duration_min": 75,
        "load_areas": ["full_body", "cardio"], "load_score": 8,
        "note": "High full-body demand — sparring days significantly raise weekly load.",
        "safety_note": "Follow your instructor's guidance for contact and safety.",
    },
    {
        "key": "climbing", "label": "Climbing", "icon": "trending-up",
        "default_intensity": "hard", "default_duration_min": 90,
        "load_areas": ["upper", "grip", "core"], "load_score": 7,
        "note": "High upper-body, grip and core demand.",
        "safety_note": "Follow gym / crag safety procedures; CrewFit is not a substitute for climbing instruction.",
    },
    {
        "key": "yoga", "label": "Yoga", "icon": "leaf",
        "default_intensity": "light", "default_duration_min": 60,
        "load_areas": ["mobility"], "load_score": 2,
        "note": "Mobility and recovery focused — pairs well with harder training days.",
    },
    {
        "key": "pilates", "label": "Pilates", "icon": "body",
        "default_intensity": "light", "default_duration_min": 55,
        "load_areas": ["core", "mobility"], "load_score": 3,
        "note": "Core stability and controlled movement.",
    },
    {
        "key": "running_club", "label": "Running Club", "icon": "people",
        "default_intensity": "moderate", "default_duration_min": 60,
        "load_areas": ["lower", "cardio"], "load_score": 6,
        "note": "Group running — often quicker than solo tempo.",
    },
    {
        "key": "custom", "label": "Custom", "icon": "add-circle",
        "default_intensity": "moderate", "default_duration_min": 60,
        "load_areas": [], "load_score": 4,
        "note": "Custom activity — Atlas will use your intensity + duration.",
    },
]

_PRESET_BY_KEY: dict[str, dict[str, Any]] = {p["key"]: p for p in ACTIVITY_PRESETS}

INTENSITY_SCORE = {"light": 2, "moderate": 5, "hard": 7, "very_hard": 9}
VALID_INTENSITIES = ("light", "moderate", "hard", "very_hard", "not_sure")
VALID_PLANNING_MODES = ("protect", "count_as_training", "note_only", "ask_coach")
VALID_RECURRENCE = ("once", "weekly", "biweekly", "monthly")
VALID_STATUS = ("planned", "completed", "partial", "skipped", "cancelled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_local_str(user: dict) -> str:
    tz = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    try:
        return _dt.datetime.now(ZoneInfo(tz)).date().isoformat()
    except Exception:
        return _dt.datetime.utcnow().date().isoformat()


def _clean(row: dict) -> dict:
    row.pop("_id", None)
    return row


def _preset_for(activity_type: str) -> dict[str, Any]:
    return _PRESET_BY_KEY.get(activity_type) or _PRESET_BY_KEY["custom"]


def _intensity_score(intensity: str, activity_type: str) -> int:
    if intensity in INTENSITY_SCORE:
        return INTENSITY_SCORE[intensity]
    # "not_sure" → fall back to preset
    return int(_preset_for(activity_type).get("load_score") or 4)


def _load_overlaps(preset_areas: list[str], workout_focus: str) -> bool:
    """Return True if a workout's focus overlaps with the activity's load areas."""
    f = (workout_focus or "").lower()
    if not preset_areas:
        return False
    if "lower" in preset_areas and any(k in f for k in ("legs", "lower", "glute", "squat", "quad")):
        return True
    if "upper" in preset_areas and any(k in f for k in ("upper", "push", "pull", "chest", "back", "shoulders")):
        return True
    if any(k in preset_areas for k in ("cardio", "endurance")) and any(k in f for k in ("cardio", "conditioning", "interval", "run", "cycle", "endurance")):
        return True
    if "core" in preset_areas and "core" in f:
        return True
    if "rotation" in preset_areas and any(k in f for k in ("rotation", "core", "oblique")):
        return True
    return False


async def _neighbouring_workouts(user_id: str, date_local: str) -> dict[str, Optional[dict]]:
    """Fetch workouts on (day-1, day, day+1) in local ISO for suggestion logic."""
    try:
        base = _dt.date.fromisoformat(date_local)
    except Exception:
        return {"prev": None, "same": None, "next": None}
    dates = {
        "prev": (base - _dt.timedelta(days=1)).isoformat(),
        "same": date_local,
        "next": (base + _dt.timedelta(days=1)).isoformat(),
    }
    rows = await db.workouts.find(
        {"user_id": user_id, "date": {"$in": list(dates.values())}},
        {"_id": 0, "id": 1, "date": 1, "title": 1, "focus": 1, "day_load": 1, "coach_locked": 1, "completed": 1, "approved": 1},
    ).to_list(20)
    by_date = {w["date"]: w for w in rows}
    return {k: by_date.get(v) for k, v in dates.items()}


def _build_suggestion(activity: dict, neighbours: dict[str, Optional[dict]]) -> dict[str, Any]:
    """
    Deterministic Atlas-style suggestion. Returns:
      { headline, body, recommended_action, actions: [ {id, label, kind} ], conflict_level }

    kinds recognised by /apply-suggestion:
      keep | move_workout | reduce_workout | ask_coach | replace_workout
    """
    ptype = activity["activity_type"]
    preset = _preset_for(ptype)
    intensity = activity.get("intensity") or preset.get("default_intensity") or "moderate"
    iscore = _intensity_score(intensity, ptype)
    planning = activity.get("planning_mode") or "count_as_training"
    same = neighbours.get("same")
    prev_ = neighbours.get("prev")
    next_ = neighbours.get("next")

    # Base narrative — one short paragraph, plain English.
    label = preset["label"]
    body_parts: list[str] = []
    body_parts.append(preset.get("note") or f"You've planned {label.lower()}.")

    conflict_level = "none"
    recommended = "keep"
    actions: list[dict[str, str]] = []

    # Note-only mode → never suggest workout changes.
    if planning == "note_only":
        return {
            "headline": f"{label} added to your calendar",
            "body": body_parts[0] + " CrewFit will show this on your schedule but won't adjust your training.",
            "recommended_action": "keep",
            "actions": [{"id": "keep", "label": "OK", "kind": "keep"}],
            "conflict_level": "none",
        }

    # Ask coach mode → always create coach task.
    if planning == "ask_coach":
        return {
            "headline": f"Louis will review this {label.lower()} plan",
            "body": body_parts[0] + " CrewFit has flagged this for your coach to check.",
            "recommended_action": "ask_coach",
            "actions": [
                {"id": "ask_coach", "label": "Ask Louis to review", "kind": "ask_coach"},
                {"id": "keep", "label": "Skip", "kind": "keep"},
            ],
            "conflict_level": "review",
        }

    same_overlap = bool(same) and _load_overlaps(preset.get("load_areas") or [], same.get("focus", ""))
    next_overlap = bool(next_) and _load_overlaps(preset.get("load_areas") or [], next_.get("focus", ""))

    hard_activity = iscore >= 7

    # ── Same-day conflict ──
    if same and (same_overlap or hard_activity):
        conflict_level = "high" if hard_activity and same_overlap else "medium"
        if planning == "protect":
            body_parts.append(
                f"You've asked CrewFit to protect this session, so we'd suggest moving your "
                f"{same.get('title') or 'gym workout'} away from {activity['date_local']}."
            )
            recommended = "move_workout"
        else:
            body_parts.append(
                f"Because {label.lower()} loads similar areas to your planned "
                f"{same.get('title') or 'session'}, consider swapping the gym session for mobility "
                f"or moving it to another day."
            )
            recommended = "reduce_workout"
        actions = [
            {"id": "move", "label": "Move workout", "kind": "move_workout"},
            {"id": "reduce", "label": "Switch to mobility", "kind": "reduce_workout"},
            {"id": "keep", "label": "Keep as planned", "kind": "keep"},
            {"id": "ask_coach", "label": "Ask Louis to review", "kind": "ask_coach"},
        ]
    # ── Next-day fatigue risk after hard activity ──
    elif next_ and hard_activity and next_overlap:
        conflict_level = "medium"
        body_parts.append(
            f"{label} is a hard session — CrewFit suggests reducing the next day's "
            f"{next_.get('title') or 'workout'} intensity."
        )
        recommended = "reduce_workout"
        actions = [
            {"id": "reduce", "label": "Reduce next day", "kind": "reduce_workout", "target_date": next_["date"]},
            {"id": "keep", "label": "Keep as planned", "kind": "keep"},
        ]
    # ── Prev-day fatigue: if yesterday was hard and today is another hard activity ──
    elif prev_ and hard_activity and (prev_.get("day_load") in ("red", "orange", "amber")):
        conflict_level = "medium"
        body_parts.append(
            f"You had a hard session yesterday — consider a lighter warm-up before {label.lower()}."
        )
        recommended = "keep"
        actions = [
            {"id": "keep", "label": "OK", "kind": "keep"},
            {"id": "ask_coach", "label": "Ask Louis to review", "kind": "ask_coach"},
        ]
    # ── Count-as-training with no conflicts ──
    elif planning == "count_as_training":
        body_parts.append(
            f"CrewFit will count this {label.lower()} as part of your weekly training load."
        )
        actions = [{"id": "keep", "label": "OK", "kind": "keep"}]
    else:
        # protect with no conflicts
        body_parts.append("No workout conflicts detected — enjoy the session.")
        actions = [{"id": "keep", "label": "OK", "kind": "keep"}]

    # Safety disclaimers for select activities.
    safety = preset.get("safety_note")
    if safety:
        body_parts.append(safety)

    return {
        "headline": f"{label} · {intensity.replace('_', ' ')}",
        "body": " ".join(body_parts),
        "recommended_action": recommended,
        "actions": actions,
        "conflict_level": conflict_level,
    }


async def _rebuild_suggestion(activity_id: str) -> Optional[dict]:
    row = await db.personal_activities.find_one({"id": activity_id}, {"_id": 0})
    if not row:
        return None
    neighbours = await _neighbouring_workouts(row["user_id"], row["date_local"])
    sug = _build_suggestion(row, neighbours)
    await db.personal_activities.update_one(
        {"id": activity_id},
        {"$set": {"atlas_suggestion": sug, "updated_at": now_iso()}},
    )
    row["atlas_suggestion"] = sug
    return row


def _expand_recurrence(base_date: str, rule: str) -> list[str]:
    """Expand a recurring activity into occurrence dates. Cap at 12 weeks ahead."""
    try:
        d0 = _dt.date.fromisoformat(base_date)
    except Exception:
        return [base_date]
    out = [d0.isoformat()]
    horizon = d0 + _dt.timedelta(weeks=12)
    step: Optional[_dt.timedelta] = None
    months = 0
    if rule == "weekly":
        step = _dt.timedelta(weeks=1)
    elif rule == "biweekly":
        step = _dt.timedelta(weeks=2)
    elif rule == "monthly":
        months = 1
    else:
        return out
    if step:
        cur = d0 + step
        while cur <= horizon:
            out.append(cur.isoformat())
            cur += step
    else:
        # monthly — approximate by same day-of-month, skipping invalid days.
        for i in range(1, 4):  # 3 more months
            year = d0.year + ((d0.month - 1 + i * months) // 12)
            month = ((d0.month - 1 + i * months) % 12) + 1
            try:
                nxt = _dt.date(year, month, d0.day)
            except ValueError:
                # Fallback to last day of that month
                if month == 12:
                    nxt = _dt.date(year, 12, 31)
                else:
                    nxt = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
            out.append(nxt.isoformat())
    return out


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class ActivityCreateBody(BaseModel):
    activity_type: str
    activity_name: Optional[str] = None
    date_local: str
    start_time: Optional[str] = None
    duration_minutes: int = Field(default=60, ge=5, le=720)
    intensity: str = "moderate"
    recurrence: str = "once"
    planning_mode: str = "count_as_training"
    notes: Optional[str] = None
    location: Optional[str] = None
    importance: Optional[str] = None
    is_competition: bool = False
    is_flexible: bool = True


class ActivityUpdateBody(BaseModel):
    activity_name: Optional[str] = None
    date_local: Optional[str] = None
    start_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    intensity: Optional[str] = None
    planning_mode: Optional[str] = None
    notes: Optional[str] = None
    location: Optional[str] = None
    importance: Optional[str] = None
    is_competition: Optional[bool] = None
    is_flexible: Optional[bool] = None


class ActivityCompleteBody(BaseModel):
    status: str = "completed"  # completed | partial | skipped | cancelled
    perceived_effort: Optional[str] = None  # easy | moderate | hard | very_hard


class ActivityApplyBody(BaseModel):
    action: str  # keep | move_workout | reduce_workout | ask_coach | replace_workout
    workout_id: Optional[str] = None
    target_date: Optional[str] = None  # for move


# ---------------------------------------------------------------------------
# Presets endpoint
# ---------------------------------------------------------------------------

@api.get("/personal-activities/presets")
async def personal_activities_presets(_: dict = Depends(current_user)):
    return {"presets": ACTIVITY_PRESETS, "intensities": list(VALID_INTENSITIES), "recurrence": list(VALID_RECURRENCE), "planning_modes": list(VALID_PLANNING_MODES)}


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------

@api.post("/personal-activities")
async def personal_activity_create(body: ActivityCreateBody, user: dict = Depends(current_user)):
    if body.intensity not in VALID_INTENSITIES:
        raise HTTPException(400, f"invalid intensity — must be one of {VALID_INTENSITIES}")
    if body.planning_mode not in VALID_PLANNING_MODES:
        raise HTTPException(400, f"invalid planning_mode — must be one of {VALID_PLANNING_MODES}")
    if body.recurrence not in VALID_RECURRENCE:
        raise HTTPException(400, f"invalid recurrence — must be one of {VALID_RECURRENCE}")
    try:
        _dt.date.fromisoformat(body.date_local)
    except Exception:
        raise HTTPException(400, "date_local must be YYYY-MM-DD")

    preset = _preset_for(body.activity_type)
    display_name = (body.activity_name or preset["label"]).strip()[:80]
    now = now_iso()
    series_id = new_id() if body.recurrence != "once" else None

    dates = _expand_recurrence(body.date_local, body.recurrence)
    created: list[dict] = []
    for d in dates:
        doc = {
            "id": new_id(),
            "user_id": user["id"],
            "activity_name": display_name,
            "activity_type": body.activity_type,
            "date_local": d,
            "start_time": body.start_time,
            "duration_minutes": body.duration_minutes,
            "intensity": body.intensity,
            "recurrence": body.recurrence,
            "series_id": series_id,
            "planning_mode": body.planning_mode,
            "notes": (body.notes or "")[:500],
            "location": (body.location or "")[:120],
            "importance": body.importance,
            "is_competition": bool(body.is_competition),
            "is_flexible": bool(body.is_flexible),
            "affects_training": body.planning_mode != "note_only",
            "coach_review_required": body.planning_mode == "ask_coach",
            "atlas_suggestion": None,
            "linked_workout_id": None,
            "status": "planned",
            "perceived_effort": None,
            "created_by": "client",
            "created_at": now,
            "updated_at": now,
        }
        neighbours = await _neighbouring_workouts(user["id"], d)
        doc["atlas_suggestion"] = _build_suggestion(doc, neighbours)
        await db.personal_activities.insert_one(doc)
        created.append(_clean(doc))

        # Coach task if ask_coach OR conflict is high
        try:
            sug = doc["atlas_suggestion"] or {}
            if body.planning_mode == "ask_coach" or sug.get("conflict_level") == "high":
                await _create_coach_task(
                    user,
                    "personal_activity_conflict" if sug.get("conflict_level") == "high" else "personal_activity_review",
                    f"{user.get('name') or user.get('email')} added {display_name} on {d}",
                    (sug.get("body") or "")[:220],
                    priority="high" if sug.get("conflict_level") == "high" else "normal",
                    risk_level="medium" if sug.get("conflict_level") == "high" else "low",
                    category="programme",
                    payload={"personal_activity_id": doc["id"], "date_local": d},
                )
        except Exception:
            logger.exception("coach task for personal activity failed")

        # Change-log for the first occurrence only to avoid log spam.
        if d == dates[0]:
            try:
                await _log_change(
                    None,
                    user["id"],
                    "programme",
                    f"Client added personal activity: {display_name} on {d}"
                    + (f" (recurring {body.recurrence})" if body.recurrence != "once" else ""),
                    doc["atlas_suggestion"].get("body", ""),
                    actor="client",
                    meta={"personal_activity_id": doc["id"], "activity_type": body.activity_type},
                )
            except Exception:
                pass

    return {"activities": created, "count": len(created), "series_id": series_id}


@api.get("/personal-activities")
async def personal_activities_list(
    user: dict = Depends(current_user),
    start: Optional[str] = None,
    end: Optional[str] = None,
    include_past: bool = True,
):
    q: dict[str, Any] = {"user_id": user["id"]}
    if start or end:
        rng: dict[str, str] = {}
        if start: rng["$gte"] = start
        if end: rng["$lte"] = end
        q["date_local"] = rng
    elif not include_past:
        q["date_local"] = {"$gte": _today_local_str(user)}
    rows = await db.personal_activities.find(q, {"_id": 0}).sort("date_local", 1).to_list(500)
    return {"activities": rows, "count": len(rows)}


@api.get("/personal-activities/today")
async def personal_activities_today(user: dict = Depends(current_user)):
    today = _today_local_str(user)
    rows = await db.personal_activities.find(
        {"user_id": user["id"], "date_local": today}, {"_id": 0},
    ).sort("start_time", 1).to_list(20)
    return {"activities": rows, "date_local": today}


@api.get("/personal-activities/{activity_id}")
async def personal_activity_get(activity_id: str, user: dict = Depends(current_user)):
    row = await db.personal_activities.find_one(
        {"id": activity_id, "user_id": user["id"]}, {"_id": 0},
    )
    if not row:
        raise HTTPException(404, "activity not found")
    return {"activity": row}


@api.patch("/personal-activities/{activity_id}")
async def personal_activity_patch(activity_id: str, body: ActivityUpdateBody, user: dict = Depends(current_user)):
    row = await db.personal_activities.find_one({"id": activity_id, "user_id": user["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "activity not found")
    updates: dict[str, Any] = {"updated_at": now_iso()}
    for k in ("activity_name", "date_local", "start_time", "duration_minutes", "intensity",
              "planning_mode", "notes", "location", "importance", "is_competition", "is_flexible"):
        v = getattr(body, k)
        if v is not None:
            if k == "intensity" and v not in VALID_INTENSITIES:
                raise HTTPException(400, "invalid intensity")
            if k == "planning_mode" and v not in VALID_PLANNING_MODES:
                raise HTTPException(400, "invalid planning_mode")
            updates[k] = v
    if len(updates) == 1:
        raise HTTPException(400, "no updates")
    if "planning_mode" in updates:
        updates["affects_training"] = updates["planning_mode"] != "note_only"
        updates["coach_review_required"] = updates["planning_mode"] == "ask_coach"
    await db.personal_activities.update_one({"id": activity_id}, {"$set": updates})
    saved = await _rebuild_suggestion(activity_id)
    return {"activity": saved}


@api.delete("/personal-activities/{activity_id}")
async def personal_activity_delete(activity_id: str, scope: str = "one", user: dict = Depends(current_user)):
    row = await db.personal_activities.find_one({"id": activity_id, "user_id": user["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "activity not found")
    if scope == "series" and row.get("series_id"):
        r = await db.personal_activities.delete_many({"series_id": row["series_id"], "user_id": user["id"]})
        return {"deleted": r.deleted_count, "scope": "series"}
    await db.personal_activities.delete_one({"id": activity_id})
    return {"deleted": 1, "scope": "one"}


@api.post("/personal-activities/{activity_id}/complete")
async def personal_activity_complete(activity_id: str, body: ActivityCompleteBody, user: dict = Depends(current_user)):
    if body.status not in VALID_STATUS:
        raise HTTPException(400, f"invalid status — must be one of {VALID_STATUS}")
    row = await db.personal_activities.find_one({"id": activity_id, "user_id": user["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "activity not found")
    now = now_iso()
    updates = {
        "status": body.status,
        "perceived_effort": body.perceived_effort,
        "completed_at": now,
        "updated_at": now,
    }
    await db.personal_activities.update_one({"id": activity_id}, {"$set": updates})
    saved = await db.personal_activities.find_one({"id": activity_id}, {"_id": 0})
    return {"activity": saved}


@api.post("/personal-activities/{activity_id}/apply-suggestion")
async def personal_activity_apply(activity_id: str, body: ActivityApplyBody, user: dict = Depends(current_user)):
    """Take a suggested action and route it to workouts / coach_tasks."""
    row = await db.personal_activities.find_one({"id": activity_id, "user_id": user["id"]}, {"_id": 0})
    if not row:
        raise HTTPException(404, "activity not found")
    action = body.action
    result: dict[str, Any] = {"action": action}
    now = now_iso()

    if action == "keep":
        result["applied"] = True

    elif action == "ask_coach":
        try:
            await _create_coach_task(
                user,
                "personal_activity_review",
                f"Client requested review of {row['activity_name']} on {row['date_local']}",
                (row.get("atlas_suggestion") or {}).get("body", "")[:220],
                priority="normal",
                risk_level="low",
                category="programme",
                payload={"personal_activity_id": row["id"], "date_local": row["date_local"]},
            )
        except Exception:
            logger.exception("apply-suggestion ask_coach failed")
        result["applied"] = True

    elif action == "move_workout":
        wid = body.workout_id
        tgt = body.target_date
        if not wid:
            # Default: find same-day workout to move.
            same = await db.workouts.find_one({"user_id": user["id"], "date": row["date_local"]}, {"_id": 0, "id": 1, "coach_locked": 1})
            if not same:
                raise HTTPException(400, "no workout on this date to move")
            if same.get("coach_locked"):
                raise HTTPException(400, "workout is coach-locked — ask coach to review")
            wid = same["id"]
        if not tgt:
            # Try to find next non-workout day within +/- 3 days.
            base = _dt.date.fromisoformat(row["date_local"])
            for delta in (1, -1, 2, -2, 3, -3):
                cand = (base + _dt.timedelta(days=delta)).isoformat()
                existing = await db.workouts.find_one({"user_id": user["id"], "date": cand}, {"_id": 0, "id": 1})
                if not existing:
                    tgt = cand
                    break
            if not tgt:
                raise HTTPException(400, "no free day to move workout to — please pick a date")
        await db.workouts.update_one(
            {"id": wid, "user_id": user["id"]},
            {"$set": {"date": tgt, "override_applied": True, "updated_at": now, "moved_for_activity_id": row["id"]}},
        )
        result.update({"applied": True, "workout_id": wid, "moved_to": tgt})
        try:
            await _log_change(None, user["id"], "programme",
                              f"Workout moved to {tgt} because of {row['activity_name']}", "",
                              actor="client", meta={"personal_activity_id": row["id"], "workout_id": wid})
        except Exception:
            pass

    elif action == "reduce_workout":
        target_date = body.target_date or row["date_local"]
        w = await db.workouts.find_one({"user_id": user["id"], "date": target_date}, {"_id": 0, "id": 1, "coach_locked": 1})
        if not w:
            raise HTTPException(400, "no workout on target date to reduce")
        if w.get("coach_locked"):
            raise HTTPException(400, "workout is coach-locked — ask coach to review")
        await db.workouts.update_one(
            {"id": w["id"]},
            {"$set": {
                "focus": "mobility",
                "title": "MOBILITY & RECOVERY",
                "duration_min": 25,
                "day_load": "green",
                "override_applied": True,
                "updated_at": now,
                "reduced_for_activity_id": row["id"],
            }},
        )
        result.update({"applied": True, "workout_id": w["id"], "reduced_to": "mobility"})
        try:
            await _log_change(None, user["id"], "programme",
                              f"Workout reduced to mobility on {target_date} because of {row['activity_name']}", "",
                              actor="client", meta={"personal_activity_id": row["id"], "workout_id": w["id"]})
        except Exception:
            pass

    elif action == "replace_workout":
        w = await db.workouts.find_one({"user_id": user["id"], "date": row["date_local"]}, {"_id": 0, "id": 1, "coach_locked": 1})
        if w and not w.get("coach_locked"):
            await db.workouts.update_one(
                {"id": w["id"]},
                {"$set": {
                    "focus": "activity",
                    "title": row["activity_name"].upper(),
                    "duration_min": row.get("duration_minutes") or 60,
                    "day_load": "amber",
                    "override_applied": True,
                    "replaced_by_activity_id": row["id"],
                    "updated_at": now,
                }},
            )
            result.update({"applied": True, "workout_id": w["id"], "replaced_with": row["activity_name"]})
        else:
            result.update({"applied": False, "reason": "no eligible workout to replace"})

    else:
        raise HTTPException(400, f"unknown action: {action}")

    await db.personal_activities.update_one(
        {"id": row["id"]},
        {"$set": {"applied_action": action, "applied_at": now, "updated_at": now}},
    )
    saved = await db.personal_activities.find_one({"id": row["id"]}, {"_id": 0})
    result["activity"] = saved
    return result


# ---------------------------------------------------------------------------
# Coach visibility
# ---------------------------------------------------------------------------

@api.get("/coach/clients/{client_id}/personal-activities")
async def coach_personal_activities(client_id: str, coach: dict = Depends(require_role("coach")), start: Optional[str] = None, end: Optional[str] = None):
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")
    q: dict[str, Any] = {"user_id": client_id}
    if start or end:
        rng: dict[str, str] = {}
        if start: rng["$gte"] = start
        if end: rng["$lte"] = end
        q["date_local"] = rng
    rows = await db.personal_activities.find(q, {"_id": 0}).sort("date_local", 1).to_list(400)
    # Compute simple weekly load contribution across the last 4 weeks + next 4 weeks
    today = _today_local_str(client)
    d0 = _dt.date.fromisoformat(today) - _dt.timedelta(days=28)
    d1 = _dt.date.fromisoformat(today) + _dt.timedelta(days=28)
    range_rows = [r for r in rows if d0.isoformat() <= r["date_local"] <= d1.isoformat()]
    total_load = 0
    conflicts = 0
    for r in range_rows:
        total_load += _intensity_score(r.get("intensity") or "moderate", r.get("activity_type") or "custom")
        if (r.get("atlas_suggestion") or {}).get("conflict_level") in ("high", "medium"):
            conflicts += 1
    return {
        "activities": rows,
        "range_load_score": total_load,
        "range_conflicts": conflicts,
        "count": len(rows),
    }


@api.get("/coach/personal-activities/conflicts")
async def coach_personal_activity_conflicts(coach: dict = Depends(require_role("coach")), limit: int = 50):
    """Cross-client feed of upcoming personal activities with medium/high conflict."""
    today = _dt.date.today().isoformat()
    horizon = (_dt.date.today() + _dt.timedelta(days=21)).isoformat()
    rows = await db.personal_activities.find(
        {
            "date_local": {"$gte": today, "$lte": horizon},
            "atlas_suggestion.conflict_level": {"$in": ["high", "medium", "review"]},
            "status": "planned",
        },
        {"_id": 0},
    ).sort("date_local", 1).to_list(limit)
    # Attach client display name
    uids = list({r["user_id"] for r in rows})
    users = await db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "name": 1, "email": 1}).to_list(len(uids))
    umap = {u["id"]: u for u in users}
    for r in rows:
        u = umap.get(r["user_id"]) or {}
        r["client_name"] = u.get("name") or u.get("email") or "Client"
    return {"conflicts": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Profile: regular sports & hobbies preferences
# ---------------------------------------------------------------------------

class RegularSportsBody(BaseModel):
    sports: list[dict[str, Any]] = Field(default_factory=list)
    # Each item: { activity_type, frequency, importance, injury_notes?, protect? }


@api.get("/personal-activities/profile/sports")
async def profile_sports_get(user: dict = Depends(current_user)):
    doc = await db.users.find_one({"id": user["id"]}, {"_id": 0, "regular_sports": 1})
    return {"sports": (doc or {}).get("regular_sports") or []}


@api.put("/personal-activities/profile/sports")
async def profile_sports_put(body: RegularSportsBody, user: dict = Depends(current_user)):
    cleaned: list[dict[str, Any]] = []
    for s in (body.sports or []):
        if not isinstance(s, dict):
            continue
        atype = s.get("activity_type") or s.get("type")
        if not atype:
            continue
        cleaned.append({
            "activity_type": atype,
            "label": _preset_for(atype)["label"],
            "frequency": s.get("frequency") or "weekly",
            "importance": s.get("importance") or "medium",
            "injury_notes": (s.get("injury_notes") or "")[:400],
            "protect": bool(s.get("protect", False)),
        })
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"regular_sports": cleaned, "regular_sports_updated_at": now_iso()}},
    )
    return {"sports": cleaned}
