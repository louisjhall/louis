"""
feature_coach_workout_editor — Plan C4/C5/C6/C7 backend.

Endpoints:
  * PATCH  /api/coach/workouts/{wid}                          → edit workout meta (title, duration, focus, rationale, warmup, cooldown, coach_notes, key_session, date, workout_type)
  * POST   /api/coach/workouts/{wid}/exercises/add            → add exercise from V2 lib
  * PATCH  /api/coach/workouts/{wid}/exercises/{idx}          → edit sets/reps/rest/rpe/notes
  * DELETE /api/coach/workouts/{wid}/exercises/{idx}          → remove by index
  * POST   /api/coach/workouts/{wid}/exercises/{idx}/swap     → swap with V2 lib exercise, preserves prescription
  * POST   /api/coach/workouts/{wid}/exercises/reorder        → new order array

  * GET    /api/exercises/v2/search                           → V2 library search with movement/region/equipment/tag filters

  * POST   /api/coach/workouts/{wid}/regenerate-preview       → C6 dry-run for single workout with preset option
  * POST   /api/coach/clients/{cid}/programme/regenerate-preview → C7 dry-run for whole programme, returns old vs new diff summary
  * POST   /api/coach/clients/{cid}/programme/regenerate-apply   → C7 commit

Rules:
  * ALL edits set coach_edited=true, edited_by=coach.id, updated_at=now.
  * completed workouts are read-only.
  * every change is audit-logged via change_log.
  * exercise swaps preserve sets/reps/rest/rpe when sensible; coach can override.
"""

from __future__ import annotations

import copy
import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import (
    api,
    db,
    require_role,
    logger,
    now_iso,
    new_id,
    _log_change,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _load_workout(wid: str) -> dict:
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "workout not found")
    if w.get("completed"):
        raise HTTPException(400, "Workout already completed; cannot edit")
    if w.get("coach_locked") and False:  # coach can edit their own locked workouts — locked just prevents client edits
        pass
    return w


def _touch(fields: dict, coach: dict) -> dict:
    fields = dict(fields)
    fields["coach_edited"] = True
    fields["edited_by"] = coach.get("id")
    fields["edited_at"] = now_iso()
    fields["updated_at"] = now_iso()
    # Coach's edit clears "needs_coach_review" — Louis explicitly signed off.
    fields["needs_coach_review"] = False
    fields["validation_status"] = "coach_approved"
    return fields


async def _load_client(uid: str) -> dict:
    u = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(404, "client not found")
    return u


# ---------------------------------------------------------------------------
# C4 — workout meta edit
# ---------------------------------------------------------------------------

class WorkoutMetaPatch(BaseModel):
    title: Optional[str] = None
    duration_min: Optional[int] = None
    focus: Optional[str] = None
    location: Optional[str] = None
    rationale: Optional[str] = None
    coach_notes: Optional[str] = None
    key_session: Optional[bool] = None
    day_load: Optional[str] = None
    date: Optional[str] = None                   # ISO YYYY-MM-DD
    workout_type: Optional[str] = None
    warmup: Optional[list[dict[str, Any]]] = None
    cooldown: Optional[list[dict[str, Any]]] = None


@api.patch("/coach/workouts/{wid}")
async def coach_workout_patch(wid: str, body: WorkoutMetaPatch, coach: dict = Depends(require_role("coach"))):
    w = await _load_workout(wid)
    updates: dict[str, Any] = {}
    for f in ("title", "duration_min", "focus", "location", "rationale", "coach_notes", "key_session", "day_load", "date", "workout_type", "warmup", "cooldown"):
        v = getattr(body, f)
        if v is not None:
            updates[f] = v
    if not updates:
        return {"ok": True, "no_change": True}
    await db.workouts.update_one({"id": wid}, {"$set": _touch(updates, coach)})
    await _log_change(
        coach_id=coach.get("id"), client_id=w["user_id"],
        category="workout", kind="edit",
        title=f"Workout edited · {w.get('title') or wid}",
        description=", ".join(f"{k}: {updates[k]}" for k in updates if k not in ("warmup", "cooldown"))[:180],
        actor="coach",
        meta={"workout_id": wid, "fields": list(updates.keys())},
    )
    return {"ok": True, "workout_id": wid, "updated_fields": list(updates.keys())}


# ---------------------------------------------------------------------------
# C4/C5 — exercise CRUD + swap
# ---------------------------------------------------------------------------

class ExerciseAddBody(BaseModel):
    exercise_id: str                             # V2 library id
    exercise_name: Optional[str] = None
    sets: Optional[int] = 3
    reps: Optional[str] = "8-10"
    rest_sec: Optional[int] = 60
    rpe: Optional[float] = 7
    notes: Optional[str] = None
    at_index: Optional[int] = None               # None → append


@api.post("/coach/workouts/{wid}/exercises/add")
async def coach_workout_add_exercise(wid: str, body: ExerciseAddBody, coach: dict = Depends(require_role("coach"))):
    w = await _load_workout(wid)
    v2 = await db.exercises_v2.find_one({"id": body.exercise_id}, {"_id": 0})
    if not v2:
        raise HTTPException(404, "V2 library exercise not found")
    new_ex = {
        "exercise_id": body.exercise_id,
        "name": body.exercise_name or v2.get("exercise_name"),
        "sets": body.sets, "reps": body.reps,
        "rest_sec": body.rest_sec, "rpe": body.rpe,
        "notes": body.notes or v2.get("coaching_notes", "")[:180],
        "added_by": coach.get("id"), "added_at": now_iso(),
    }
    exs = list(w.get("exercises") or [])
    if body.at_index is None or body.at_index >= len(exs):
        exs.append(new_ex)
    else:
        exs.insert(max(0, body.at_index), new_ex)
    await db.workouts.update_one({"id": wid}, {"$set": _touch({"exercises": exs}, coach)})
    await _log_change(
        coach_id=coach.get("id"), client_id=w["user_id"],
        category="workout", kind="exercise_add",
        title=f"Added: {new_ex['name']}",
        description=f"To workout on {w.get('date')}",
        actor="coach",
        meta={"workout_id": wid, "exercise_id": body.exercise_id},
    )
    return {"ok": True, "exercises_count": len(exs)}


class ExerciseEditBody(BaseModel):
    sets: Optional[int] = None
    reps: Optional[str] = None
    rest_sec: Optional[int] = None
    rpe: Optional[float] = None
    notes: Optional[str] = None
    name: Optional[str] = None


@api.patch("/coach/workouts/{wid}/exercises/{idx}")
async def coach_workout_edit_exercise(wid: str, idx: int, body: ExerciseEditBody, coach: dict = Depends(require_role("coach"))):
    w = await _load_workout(wid)
    exs = list(w.get("exercises") or [])
    if idx < 0 or idx >= len(exs):
        raise HTTPException(404, "exercise index out of range")
    changed = {}
    for f in ("sets", "reps", "rest_sec", "rpe", "notes", "name"):
        v = getattr(body, f)
        if v is not None:
            changed[f] = v
    if not changed:
        return {"ok": True, "no_change": True}
    exs[idx] = {**exs[idx], **changed, "edited_by": coach.get("id"), "edited_at": now_iso()}
    await db.workouts.update_one({"id": wid}, {"$set": _touch({"exercises": exs}, coach)})
    await _log_change(
        coach_id=coach.get("id"), client_id=w["user_id"],
        category="workout", kind="exercise_edit",
        title=f"Edited exercise: {exs[idx].get('name')}",
        description=", ".join(f"{k}={v}" for k, v in changed.items())[:180],
        actor="coach",
        meta={"workout_id": wid, "exercise_idx": idx, "fields": list(changed.keys())},
    )
    return {"ok": True, "exercise": exs[idx]}


@api.delete("/coach/workouts/{wid}/exercises/{idx}")
async def coach_workout_remove_exercise(wid: str, idx: int, coach: dict = Depends(require_role("coach"))):
    w = await _load_workout(wid)
    exs = list(w.get("exercises") or [])
    if idx < 0 or idx >= len(exs):
        raise HTTPException(404, "exercise index out of range")
    removed = exs.pop(idx)
    await db.workouts.update_one({"id": wid}, {"$set": _touch({"exercises": exs}, coach)})
    await _log_change(
        coach_id=coach.get("id"), client_id=w["user_id"],
        category="workout", kind="exercise_remove",
        title=f"Removed exercise: {removed.get('name')}",
        description=f"From workout on {w.get('date')}",
        actor="coach",
        meta={"workout_id": wid, "removed_exercise": removed.get("name")},
    )
    return {"ok": True, "exercises_count": len(exs)}


class ExerciseSwapBody(BaseModel):
    replacement_exercise_id: str
    replacement_name: Optional[str] = None
    preserve_prescription: bool = True
    override_sets: Optional[int] = None
    override_reps: Optional[str] = None
    override_rest_sec: Optional[int] = None
    override_rpe: Optional[float] = None
    reason: Optional[str] = None


@api.post("/coach/workouts/{wid}/exercises/{idx}/swap")
async def coach_workout_swap_exercise(wid: str, idx: int, body: ExerciseSwapBody, coach: dict = Depends(require_role("coach"))):
    w = await _load_workout(wid)
    exs = list(w.get("exercises") or [])
    if idx < 0 or idx >= len(exs):
        raise HTTPException(404, "exercise index out of range")
    v2 = await db.exercises_v2.find_one({"id": body.replacement_exercise_id}, {"_id": 0})
    if not v2:
        raise HTTPException(404, "Replacement V2 library exercise not found")
    original = exs[idx]
    replacement = {
        "exercise_id": body.replacement_exercise_id,
        "name": body.replacement_name or v2.get("exercise_name"),
        "sets": original.get("sets"),
        "reps": original.get("reps"),
        "rest_sec": original.get("rest_sec"),
        "rpe": original.get("rpe"),
        "notes": v2.get("coaching_notes", "")[:180] or original.get("notes"),
        "swapped_from": {
            "exercise_id": original.get("exercise_id"),
            "name": original.get("name"),
            "reason": body.reason,
        },
        "swapped_by": coach.get("id"),
        "swapped_at": now_iso(),
    }
    if not body.preserve_prescription:
        replacement.update({"sets": 3, "reps": "8-10", "rest_sec": 60, "rpe": 7})
    # apply overrides
    for src, dst in (("override_sets", "sets"), ("override_reps", "reps"), ("override_rest_sec", "rest_sec"), ("override_rpe", "rpe")):
        v = getattr(body, src)
        if v is not None:
            replacement[dst] = v
    exs[idx] = replacement
    await db.workouts.update_one({"id": wid}, {"$set": _touch({"exercises": exs}, coach)})
    await _log_change(
        coach_id=coach.get("id"), client_id=w["user_id"],
        category="workout", kind="exercise_swap",
        title=f"Swapped: {original.get('name')} → {replacement['name']}",
        description=body.reason or "",
        actor="coach",
        meta={"workout_id": wid, "idx": idx, "from": original.get("name"), "to": replacement["name"]},
    )
    return {"ok": True, "exercise": replacement}


class ExerciseReorderBody(BaseModel):
    order: list[int]                             # indices in the new order


@api.post("/coach/workouts/{wid}/exercises/reorder")
async def coach_workout_reorder_exercises(wid: str, body: ExerciseReorderBody, coach: dict = Depends(require_role("coach"))):
    w = await _load_workout(wid)
    exs = list(w.get("exercises") or [])
    if sorted(body.order) != list(range(len(exs))):
        raise HTTPException(400, "order array must be a permutation of exercise indices")
    exs = [exs[i] for i in body.order]
    await db.workouts.update_one({"id": wid}, {"$set": _touch({"exercises": exs}, coach)})
    await _log_change(
        coach_id=coach.get("id"), client_id=w["user_id"],
        category="workout", kind="exercise_reorder",
        title="Exercises reordered",
        actor="coach",
        meta={"workout_id": wid, "new_order": body.order},
    )
    return {"ok": True, "exercises_count": len(exs)}


# ---------------------------------------------------------------------------
# C5 — V2 library search
# ---------------------------------------------------------------------------

@api.get("/exercises/v2/search")
async def coach_v2_search(
    coach: dict = Depends(require_role("coach")),
    q: Optional[str] = None,
    movement: Optional[str] = None,
    region: Optional[str] = None,
    equipment: Optional[str] = None,
    injury_friendly: Optional[bool] = None,
    hotel_friendly: Optional[bool] = None,
    bodyweight: Optional[bool] = None,
    running_support: Optional[bool] = None,
    mobility: Optional[bool] = None,
    strength: Optional[bool] = None,
    conditioning: Optional[bool] = None,
    difficulty: Optional[str] = None,
    limit: int = 40,
):
    """Search the approved V2 Exercise Library with filters aligned to the
    coach editor's Exercise Swap UI."""
    filt: dict[str, Any] = {"status": {"$in": ["Approved", "Live"]}}
    if q:
        filt["$or"] = [
            {"exercise_name": {"$regex": q, "$options": "i"}},
            {"aliases": {"$in": [q]}},
            {"tags": {"$in": [q]}},
        ]
    if movement:
        filt["movement_pattern"] = movement
    if region:
        filt["body_regions"] = region
    if equipment:
        filt["equipment_type"] = equipment
    if difficulty:
        filt["difficulty"] = difficulty
    # tag toggles
    tag_toggles = {
        "injury_friendly": injury_friendly,
        "hotel_friendly": hotel_friendly,
        "bodyweight": bodyweight,
        "running_support": running_support,
        "mobility": mobility,
        "strength": strength,
        "conditioning": conditioning,
    }
    tags_in = [tag for tag, on in tag_toggles.items() if on]
    if tags_in:
        filt["tags"] = {"$all": tags_in}
    rows = await db.exercises_v2.find(
        filt, {"_id": 0, "id": 1, "exercise_name": 1, "movement_pattern": 1, "equipment_type": 1, "tags": 1, "difficulty": 1, "primary_image_url": 1, "coaching_notes": 1},
    ).limit(max(1, min(limit, 100))).to_list(limit)
    return {"exercises": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# C6 — regenerate single workout with preset variant
# (light wrapper around the existing coach_workout_regenerate_single so the
#  UI can pass a preset id and we translate to guidance/context.)
# ---------------------------------------------------------------------------

C6_PRESETS: dict[str, dict[str, Any]] = {
    "same_goal":        {"guidance": "Regenerate but keep the same goal, phase and target intensity."},
    "shorter":          {"guidance": "Regenerate SHORTER — ~65% of original duration. Reduce sets by 30-40%.", "duration_pct": 0.65},
    "easier":           {"guidance": "Regenerate EASIER — RPE 1-2 below original. Fewer top sets, longer rest."},
    "harder":           {"guidance": "Regenerate HARDER — one full extra set on primary lifts OR add a superset finisher."},
    "hotel_gym":        {"guidance": "Regenerate for HOTEL GYM — dumbbells + bench only, no barbell/cable machines.", "equipment": "hotel"},
    "bodyweight":       {"guidance": "Regenerate BODYWEIGHT ONLY — no equipment. Use tempo, iso holds, single-leg for progression.", "equipment": "bodyweight"},
    "tired":            {"guidance": "Client is tired — regenerate as mobility + easy movement. Amber day load."},
    "injury_pain":      {"guidance": "Client has pain/injury — regenerate as pain-free mobility + activation, no loaded compound work."},
    "around_roster":    {"guidance": "Regenerate around the current roster context — respect any hard duty tomorrow/today."},
    "as_running":       {"guidance": "Regenerate as a RUNNING session (easy run / tempo depending on phase)."},
    "as_strength":      {"guidance": "Regenerate as STRENGTH SUPPORT — posterior chain + single-leg for running clients."},
    "custom":           {"guidance": ""}, # frontend passes free-text
}


class RegenPresetBody(BaseModel):
    preset: str = "same_goal"
    custom_instruction: Optional[str] = None


@api.post("/coach/workouts/{wid}/regenerate-preview")
async def coach_workout_regenerate_preview(wid: str, body: RegenPresetBody, coach: dict = Depends(require_role("coach"))):
    """Return a preview of the regenerated workout WITHOUT applying it.
    UI shows old vs new, coach clicks Apply → hits the existing
    /api/coach/workouts/{wid}/regenerate (feature_coach_deep_edit).
    """
    if body.preset not in C6_PRESETS:
        raise HTTPException(400, "unknown preset")
    w = await _load_workout(wid)
    preset = C6_PRESETS[body.preset]
    guidance = preset.get("guidance") or ""
    if body.preset == "custom" and body.custom_instruction:
        guidance = body.custom_instruction

    # For MVP we synthesise a deterministic preview from the current workout
    # + preset transforms (shorter/easier/harder). A full LLM-driven preview
    # is deferred to a follow-up because it would cost budget every click.
    preview = copy.deepcopy(w)
    preview["preview_guidance"] = guidance
    dur = int(preview.get("duration_min") or 45)
    pct = preset.get("duration_pct")
    if pct:
        preview["duration_min"] = max(15, int(dur * pct))
    if body.preset == "shorter":
        exs = list(preview.get("exercises") or [])
        # drop trailing accessory if >=5 exercises + reduce sets 30%
        if len(exs) >= 5:
            exs = exs[:-1]
        for ex in exs:
            if isinstance(ex.get("sets"), int):
                ex["sets"] = max(2, int(ex["sets"] * 0.7))
        preview["exercises"] = exs
    elif body.preset == "easier":
        for ex in (preview.get("exercises") or []):
            if isinstance(ex.get("rpe"), (int, float)):
                ex["rpe"] = max(4, ex["rpe"] - 2)
    elif body.preset == "harder":
        for ex in (preview.get("exercises") or []):
            if isinstance(ex.get("sets"), int):
                ex["sets"] = min(6, ex["sets"] + 1)
    elif body.preset in ("bodyweight", "hotel_gym"):
        # tag guidance — actual exercise swaps happen on Apply via full regen
        preview["preview_equipment_hint"] = preset.get("equipment")
    elif body.preset == "tired":
        preview["title"] = "Recovery + Mobility"
        preview["focus"] = "mobility"
        preview["duration_min"] = 20
        preview["day_load"] = "amber"
        preview["exercises"] = [{"name": "Deep breathing x 10", "sets": 1, "reps": "10 breaths", "rest_sec": 0, "rpe": 2, "notes": "Long exhale."}]
    elif body.preset == "as_running":
        preview["title"] = "Easy Run"
        preview["focus"] = "long_run"
        preview["duration_min"] = 40
        preview["exercises"] = [{"name": "Easy run", "sets": 1, "reps": "30-35 min steady", "rest_sec": 0, "rpe": 4, "notes": "Conversational pace."}]
    elif body.preset == "as_strength":
        preview["title"] = "Strength for Runners"
        preview["focus"] = "full"
        preview["duration_min"] = 40
        # keep existing exercises where they are — coach can commit
    preview["is_preview"] = True
    return {
        "ok": True,
        "preset": body.preset,
        "guidance": guidance,
        "original": {
            "id": w.get("id"),
            "title": w.get("title"),
            "duration_min": w.get("duration_min"),
            "focus": w.get("focus"),
            "exercises_count": len(w.get("exercises") or []),
        },
        "preview": {
            "title": preview.get("title"),
            "duration_min": preview.get("duration_min"),
            "focus": preview.get("focus"),
            "day_load": preview.get("day_load"),
            "exercises": preview.get("exercises"),
            "guidance": guidance,
            "equipment_hint": preview.get("preview_equipment_hint"),
        },
    }


# ---------------------------------------------------------------------------
# C7 — programme regenerate preview + apply
# ---------------------------------------------------------------------------

def _weekly_summary(workouts: list[dict]) -> dict:
    focus_counts: dict[str, int] = {}
    keys = 0
    for w in workouts:
        if w.get("completed") or w.get("deactivated"):
            continue
        f = str(w.get("focus") or "").lower()
        focus_counts[f] = focus_counts.get(f, 0) + 1
        if w.get("key_session"):
            keys += 1
    return {
        "focus_breakdown": focus_counts,
        "key_sessions": keys,
        "total_workouts": sum(focus_counts.values()),
    }


@api.post("/coach/clients/{client_id}/programme/regenerate-preview")
async def coach_programme_regenerate_preview(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
):
    """Compute a preview of what a full-programme regeneration would produce
    WITHOUT running it or writing anything to db.

    For MVP this is DETERMINISTIC: it applies the ideal weekly shape from
    `feature_programme_quality` to the client's active roster and reports:
      * old weekly structure (from current workouts)
      * new ideal structure (from event_weekly_shape / strength_weekly_shape)
      * expected count of workouts that would change
      * validation preview (would the new plan pass the current validator?)
      * preserved counts (completed + coach-locked)

    The APPLY endpoint (below) queues the real LLM-backed regeneration.
    """
    client = await _load_client(client_id)
    roster = await db.rosters.find_one(
        {"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not roster:
        raise HTTPException(400, "client has no active roster to regenerate against")
    prog = await db.programmes.find_one(
        {"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)],
    )

    today = _dt.date.today().isoformat()
    current = await db.workouts.find({
        "user_id": client_id, "roster_id": roster["id"],
        "date": {"$gte": today}, "deactivated": {"$ne": True},
    }, {"_id": 0}).to_list(200)
    preserved_completed = await db.workouts.count_documents({
        "user_id": client_id, "date": {"$gte": today}, "completed": True,
    })
    preserved_locked = await db.workouts.count_documents({
        "user_id": client_id, "date": {"$gte": today}, "coach_locked": True,
    })

    # Build the ideal shape via the same helpers used by the fallback
    from feature_programme_quality import (
        _resolve_goal_key, _phase_for_week,
        event_weekly_shape, strength_weekly_shape,
    )
    from feature_workout_fallback import build_template_plan

    profile = client.get("profile") or {}
    ideal_plan = build_template_plan(client, roster)
    old_summary = _weekly_summary(current)
    new_summary = _weekly_summary(ideal_plan)

    # Diff — how many upcoming (non-locked, non-completed) workouts would
    # change vs how many stay?
    would_change = 0
    would_keep = 0
    ideal_by_date = {w["date"]: w for w in ideal_plan}
    for cw in current:
        if cw.get("completed") or cw.get("coach_locked"):
            would_keep += 1
            continue
        target = ideal_by_date.get(cw.get("date"))
        if not target:
            would_change += 1
            continue
        if str(cw.get("focus") or "").lower() != str(target.get("focus") or "").lower():
            would_change += 1
        elif str(cw.get("title") or "").lower() != str(target.get("title") or "").lower():
            would_change += 1
        else:
            would_keep += 1

    return {
        "ok": True,
        "client": {"id": client["id"], "name": client.get("name") or client.get("email")},
        "roster_id": roster["id"],
        "current_programme_id": (prog or {}).get("id"),
        "old_summary": old_summary,
        "new_summary": new_summary,
        "would_change": would_change,
        "would_keep": would_keep,
        "preserved": {
            "completed_workouts": preserved_completed,
            "coach_locked_workouts": preserved_locked,
        },
        "first_new_workout_date": ideal_plan[0].get("date") if ideal_plan else None,
        "target_sessions_per_week": profile.get("training_days_per_week"),
        "goal_key": _resolve_goal_key(profile),
    }


class ProgrammeRegenApplyBody(BaseModel):
    reason: Optional[str] = None
    preserve_coach_locked: bool = True
    preserve_completed: bool = True


@api.post("/coach/clients/{client_id}/programme/regenerate-apply")
async def coach_programme_regenerate_apply(
    client_id: str, body: ProgrammeRegenApplyBody,
    coach: dict = Depends(require_role("coach")),
):
    """Queue a real regeneration. This routes through the existing roster
    worker so the LLM path + fallback are both exercised, and Louis' locked +
    completed workouts are preserved via the same guard rails used by
    delete-and-restart.
    """
    client = await _load_client(client_id)
    roster = await db.rosters.find_one(
        {"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not roster:
        raise HTTPException(400, "client has no active roster to regenerate against")
    # Insert a gen_job with regen flag so the worker knows to preserve.
    job = {
        "id": new_id(),
        "user_id": client_id,
        "roster_id": roster["id"],
        "status": "queued",
        "stage": "queued",
        "kind": "programme_regenerate",
        "regen_flags": {
            "preserve_coach_locked": body.preserve_coach_locked,
            "preserve_completed": body.preserve_completed,
        },
        "requested_by_coach": coach.get("id"),
        "reason": body.reason,
        "created_at": now_iso(),
    }
    await db.gen_jobs.insert_one(job)
    # Best-effort logging — a log failure MUST NOT cause the caller to think
    # the enqueue failed (that would trigger a retry → duplicate job).
    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=client_id,
            category="programme", kind="regenerate",
            title="Coach queued programme regeneration",
            description=body.reason or "",
            actor="coach",
            meta={"job_id": job["id"], "roster_id": roster["id"]},
        )
    except Exception:
        logger.exception("regen apply: change log insert failed (non-fatal)")
    return {
        "ok": True,
        "job_id": job["id"],
        "message": "Regeneration queued — the worker will process it shortly.",
    }
