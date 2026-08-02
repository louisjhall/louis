"""
feature_coach_manual_workouts — Phase 1 Manual Workout Builder.

Provides:
  * POST   /api/coach/clients/{cid}/workouts/manual          → create manual workout in db.workouts
  * PATCH  /api/coach/workouts/{wid}/manual                  → edit an existing manual workout
  * DELETE /api/coach/workouts/{wid}/manual                  → hard-delete a manual workout (with audit)
  * POST   /api/coach/clients/{cid}/day-overrides/{date}     → replace_day or suppress_day
  * DELETE /api/coach/clients/{cid}/day-overrides/{date}     → restore_day
  * GET    /api/coach/clients/{cid}/day-overrides            → list active overrides (for calendar badges)

Data model:
  * Manual workout → `db.workouts` row with
        source="coach_manual", manual_lock=True, coach_locked=True.
  * Date-level override → `db.coach_day_overrides` row with
        mode ∈ {"replace_day", "suppress_day"} and active flag.

Client resolution (see feature_v2_client_bridge + /workouts/week):
  * Active override → V2 rows for the date are dropped.
  * Legacy `db.workouts` generated rows on suppressed/replaced dates are hidden.
  * Manual (`source=coach_manual`) rows are ALWAYS visible.

Media queue: on every create/edit, call `create_exercise_request_if_missing`
for each exercise across warmup ∪ exercises ∪ cooldown to record missing
media once (dedup by name). No duplicate rows.
"""
from __future__ import annotations

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
# Helpers
# ---------------------------------------------------------------------------

_ALLOWED_TYPES = {"strength", "run", "cardio", "mobility", "recovery", "other"}
_OVERRIDE_MODES = {"replace_day", "suppress_day"}
MANUAL_SOURCE = "coach_manual"


async def _load_client(cid: str) -> dict:
    u = await db.users.find_one({"id": cid}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(404, "client not found")
    return u


async def _load_manual_workout(wid: str) -> dict:
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "workout not found")
    if w.get("source") != MANUAL_SOURCE:
        raise HTTPException(400, "not a manual workout — use the standard coach editor")
    return w


def _norm_exercise(e: dict, section: str, idx: int) -> dict:
    """Normalise a builder-shape exercise dict into the on-disk shape used
    across the workout schema. Keeps the exercise-library link + all
    prescription fields the builder supports."""
    if not isinstance(e, dict):
        raise HTTPException(400, "invalid exercise payload")
    if not e.get("exercise_id"):
        raise HTTPException(400, "every exercise must reference an exercise-library id")
    name = (e.get("name") or "").strip() or None
    return {
        "exercise_id": e.get("exercise_id"),
        "name": name,
        "sets": e.get("sets"),
        "reps": e.get("reps"),
        "duration_sec": e.get("duration_sec"),
        "load": e.get("load"),
        "rest_sec": e.get("rest_sec"),
        "tempo": e.get("tempo"),
        "rpe": e.get("rpe"),
        "notes": e.get("notes"),
        "equipment": e.get("equipment"),
        "alternative_exercise_id": e.get("alternative_exercise_id"),
        "section": section,
        "order": idx,
    }


def _normalise_sections(warmup, exercises, cooldown) -> tuple[list, list, list]:
    warm = [_norm_exercise(e, "warmup", i) for i, e in enumerate(warmup or [])]
    main = [_norm_exercise(e, "main", i) for i, e in enumerate(exercises or [])]
    cool = [_norm_exercise(e, "cooldown", i) for i, e in enumerate(cooldown or [])]
    if not main:
        raise HTTPException(400, "a manual workout must have at least one main exercise")
    return warm, main, cool


async def _scan_media_queue(client: dict, sections: dict, workout_id: str) -> list[dict]:
    """For each exercise across all sections, if the exercises_v2 row is
    missing approved media, ensure a deduped draft request exists in the
    existing media queue. Returns list of {exercise_id, name} entries that
    were queued (or bumped)."""
    try:
        from feature_v2_resolver import create_exercise_request_if_missing
    except Exception:
        return []
    queued: list[dict] = []
    seen: set[str] = set()
    for section, items in sections.items():
        for e in items or []:
            xid = e.get("exercise_id")
            if not xid or xid in seen:
                continue
            seen.add(xid)
            v2 = await db.exercises_v2.find_one({"id": xid}, {"_id": 0})
            if not v2:
                # No library record — file a fresh draft request keyed by name
                try:
                    await create_exercise_request_if_missing(
                        {"name": e.get("name") or xid},
                        user=client, programme_id=None, workout_id=workout_id,
                        reason="coach_manual_workout",
                    )
                    queued.append({"exercise_id": xid, "name": e.get("name") or xid})
                except Exception:
                    logger.exception("media queue: create_exercise_request_if_missing failed for %s", xid)
                continue
            has_image = bool(v2.get("primary_image_url"))
            has_video = bool(v2.get("primary_video_url"))
            status = (v2.get("status") or "").lower()
            approved = status in ("approved", "live")
            if approved and (has_image or has_video):
                continue
            try:
                await create_exercise_request_if_missing(
                    {"name": v2.get("exercise_name") or e.get("name") or xid,
                     "movement_pattern": v2.get("movement_pattern"),
                     "body_area": v2.get("body_area"),
                     "equipment_type": v2.get("equipment_type") or [],
                     "difficulty_level": v2.get("difficulty_level"),
                     "tags": v2.get("tags") or []},
                    user=client, programme_id=None, workout_id=workout_id,
                    reason="coach_manual_workout_missing_media",
                )
                queued.append({"exercise_id": xid,
                               "name": v2.get("exercise_name") or e.get("name") or xid})
            except Exception:
                logger.exception("media queue: create_exercise_request_if_missing failed for %s", xid)
    return queued


# ---------------------------------------------------------------------------
# Manual workout CRUD
# ---------------------------------------------------------------------------

class ManualWorkoutBody(BaseModel):
    date: str
    title: str
    workout_type: str = "other"
    duration_min: Optional[int] = None
    location: Optional[str] = None
    equipment_context: Optional[str] = None
    rpe: Optional[float] = None
    coach_notes: Optional[str] = None
    warmup: list[dict[str, Any]] = Field(default_factory=list)
    exercises: list[dict[str, Any]] = Field(default_factory=list)
    cooldown: list[dict[str, Any]] = Field(default_factory=list)
    # Optional whole-day override on save:
    override_mode: Optional[str] = None  # "replace_day" | None


@api.post("/coach/clients/{cid}/workouts/manual")
async def coach_create_manual_workout(cid: str, body: ManualWorkoutBody,
                                      coach: dict = Depends(require_role("coach"))):
    client = await _load_client(cid)
    if body.workout_type not in _ALLOWED_TYPES:
        raise HTTPException(400, f"workout_type must be one of {sorted(_ALLOWED_TYPES)}")
    warm, main, cool = _normalise_sections(body.warmup, body.exercises, body.cooldown)

    now = now_iso()
    wid = new_id()
    doc = {
        "id": wid,
        "user_id": cid,
        "date": body.date,
        "title": body.title.strip() or "Manual workout",
        "focus": body.workout_type,
        "workout_type": body.workout_type,
        "location": body.location,
        "equipment_context": body.equipment_context,
        "duration_min": body.duration_min,
        "rpe": body.rpe,
        "coach_notes": body.coach_notes,
        "warmup": warm,
        "exercises": main,
        "cooldown": cool,
        "alternatives": {},
        # Markers
        "source": MANUAL_SOURCE,
        "manual_lock": True,
        "coach_locked": True,
        "coach_locked_by": coach.get("id"),
        "coach_locked_at": now,
        "coach_id": coach.get("id"),
        "coach_edited": True,
        "edited_by": coach.get("id"),
        "edited_at": now,
        "created_at": now,
        "updated_at": now,
        "original_date": body.date,
        "audit": [{
            "action": "create",
            "by": coach.get("id"),
            "at": now,
        }],
    }
    await db.workouts.insert_one(doc)

    override_id = None
    if body.override_mode == "replace_day":
        override_id = await _upsert_day_override(
            cid=cid, coach=coach, date=body.date,
            mode="replace_day", replacement_workout_id=wid,
            reason="manual workout replaces generated day",
        )

    # Media queue scan
    missing_media = await _scan_media_queue(
        client, {"warmup": warm, "main": main, "cooldown": cool}, wid,
    )

    # Audit log entry
    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=cid,
            category="workout", kind="manual_workout_create",
            title=f"Manual workout created for {body.date}",
            description=f"{doc['title']} · {len(main)} main exercises",
            actor="coach",
            meta={"workout_id": wid, "date": body.date,
                  "override_mode": body.override_mode or None,
                  "override_id": override_id,
                  "missing_media_count": len(missing_media)},
        )
    except Exception:
        logger.exception("manual workout: _log_change failed")

    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})
    return {
        "ok": True,
        "workout": fresh,
        "override_id": override_id,
        "missing_media": missing_media,
    }


class ManualWorkoutEditBody(BaseModel):
    title: Optional[str] = None
    workout_type: Optional[str] = None
    duration_min: Optional[int] = None
    location: Optional[str] = None
    equipment_context: Optional[str] = None
    rpe: Optional[float] = None
    coach_notes: Optional[str] = None
    warmup: Optional[list[dict[str, Any]]] = None
    exercises: Optional[list[dict[str, Any]]] = None
    cooldown: Optional[list[dict[str, Any]]] = None


@api.patch("/coach/workouts/{wid}/manual")
async def coach_edit_manual_workout(wid: str, body: ManualWorkoutEditBody,
                                    coach: dict = Depends(require_role("coach"))):
    w = await _load_manual_workout(wid)
    client = await _load_client(w["user_id"])
    updates: dict[str, Any] = {}
    if body.title is not None:
        updates["title"] = body.title.strip() or w.get("title") or "Manual workout"
    if body.workout_type is not None:
        if body.workout_type not in _ALLOWED_TYPES:
            raise HTTPException(400, f"workout_type must be one of {sorted(_ALLOWED_TYPES)}")
        updates["workout_type"] = body.workout_type
        updates["focus"] = body.workout_type
    for f in ("duration_min", "location", "equipment_context", "rpe", "coach_notes"):
        v = getattr(body, f)
        if v is not None:
            updates[f] = v

    scan_sections = None
    if body.warmup is not None or body.exercises is not None or body.cooldown is not None:
        warm_in = body.warmup if body.warmup is not None else [
            {k: v for k, v in e.items() if k != "section"} for e in (w.get("warmup") or [])
        ]
        exs_in = body.exercises if body.exercises is not None else [
            {k: v for k, v in e.items() if k != "section"} for e in (w.get("exercises") or [])
        ]
        cool_in = body.cooldown if body.cooldown is not None else [
            {k: v for k, v in e.items() if k != "section"} for e in (w.get("cooldown") or [])
        ]
        warm, main, cool = _normalise_sections(warm_in, exs_in, cool_in)
        updates["warmup"] = warm
        updates["exercises"] = main
        updates["cooldown"] = cool
        scan_sections = {"warmup": warm, "main": main, "cooldown": cool}

    if not updates:
        return {"ok": True, "no_change": True, "workout": w}

    now = now_iso()
    updates["updated_at"] = now
    updates["edited_by"] = coach.get("id")
    updates["edited_at"] = now
    updates["coach_edited"] = True
    audit_entry = {"action": "edit", "by": coach.get("id"), "at": now,
                   "fields": [k for k in updates.keys()
                              if k not in ("updated_at", "edited_by", "edited_at", "coach_edited")]}
    await db.workouts.update_one(
        {"id": wid},
        {"$set": updates, "$push": {"audit": audit_entry}},
    )

    missing_media: list[dict] = []
    if scan_sections:
        missing_media = await _scan_media_queue(client, scan_sections, wid)

    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=w["user_id"],
            category="workout", kind="manual_workout_edit",
            title=f"Manual workout edited on {w.get('date')}",
            description=", ".join(audit_entry["fields"])[:180],
            actor="coach",
            meta={"workout_id": wid, "date": w.get("date"),
                  "missing_media_count": len(missing_media)},
        )
    except Exception:
        logger.exception("manual workout edit: _log_change failed")

    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})
    return {"ok": True, "workout": fresh, "missing_media": missing_media}


# ---------------------------------------------------------------------------
# Manual workout move (Phase 1.5)
# ---------------------------------------------------------------------------

class ManualMoveBody(BaseModel):
    to_date: str
    reason: Optional[str] = None
    # If target date already contains a manual workout, allow_swap must be
    # true to swap the two dates. Never silently overwrites.
    allow_swap: bool = False
    # Coach explicitly overriding a warning (available_time / equipment /
    # heavy-duty / restriction). Recorded for audit.
    warning_override: Optional[str] = None


@api.post("/coach/workouts/{wid}/manual/move")
async def coach_move_manual_workout(wid: str, body: ManualMoveBody,
                                    coach: dict = Depends(require_role("coach"))):
    w = await _load_manual_workout(wid)
    from_date = w.get("date")
    to_date = (body.to_date or "").strip()
    if not to_date:
        raise HTTPException(400, "to_date required")
    if to_date == from_date:
        return {"ok": True, "workout": w, "changed": False}

    cid = w["user_id"]
    other = await db.workouts.find_one(
        {"user_id": cid, "date": to_date, "id": {"$ne": wid}}, {"_id": 0},
    )
    # Only allow swapping with another MANUAL workout. Generated legacy rows
    # on the target date stay put — coach must use the Phase 1 whole-day
    # override tools if they want to replace them.
    swap_target = None
    if other:
        if other.get("source") != MANUAL_SOURCE:
            raise HTTPException(
                409,
                "Target date has a non-manual workout — use Phase 1 replace/suppress instead of move",
            )
        if not body.allow_swap:
            raise HTTPException(
                409,
                "Target date already has a manual workout — set allow_swap=true to swap",
            )
        if other.get("completed") or other.get("coach_locked_by_client_action"):
            raise HTTPException(409, "Cannot swap: target manual workout is completed")
        swap_target = other

    # Refuse to move a completed workout.
    if w.get("completed"):
        raise HTTPException(400, "Cannot move a completed workout")

    # If the origin date has an active replace_day override pointing at THIS
    # workout, deactivate it (the manual is moving, so the origin date should
    # return to its generated content, unless the coach explicitly wanted
    # otherwise — a follow-up can suppress the origin explicitly).
    linked_origin_override = await db.coach_day_overrides.find_one(
        {"client_id": cid, "date": from_date, "active": True,
         "replacement_workout_id": wid},
        {"_id": 0},
    )
    if linked_origin_override:
        await _deactivate_override(
            linked_origin_override["id"], coach,
            reason="manual workout moved to another date",
        )

    now = now_iso()
    move_audit = {
        "action": "move",
        "by": coach.get("id"),
        "at": now,
        "from_date": from_date,
        "to_date": to_date,
        "reason": body.reason,
        "warning_override": body.warning_override,
        "swap_with": (swap_target or {}).get("id"),
        "origin_override_deactivated": (linked_origin_override or {}).get("id"),
    }

    if swap_target:
        # Two-step swap using a temporary placeholder to avoid any unique-index
        # collision on (user_id, date).
        temp = f"__swap_{new_id()[:8]}"
        await db.workouts.update_one({"id": swap_target["id"]},
                                     {"$set": {"date": temp, "updated_at": now}})
        await db.workouts.update_one({"id": wid},
                                     {"$set": {"date": to_date, "updated_at": now,
                                               "edited_by": coach.get("id"), "edited_at": now},
                                      "$push": {"audit": move_audit}})
        await db.workouts.update_one({"id": swap_target["id"]},
                                     {"$set": {"date": from_date, "updated_at": now,
                                               "edited_by": coach.get("id"), "edited_at": now},
                                      "$push": {"audit": {"action": "swap_in",
                                                          "by": coach.get("id"), "at": now,
                                                          "from_date": to_date,
                                                          "to_date": from_date,
                                                          "swapped_with": wid}}})
    else:
        await db.workouts.update_one({"id": wid},
                                     {"$set": {"date": to_date, "updated_at": now,
                                               "edited_by": coach.get("id"), "edited_at": now},
                                      "$push": {"audit": move_audit}})

    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=cid,
            category="workout", kind="manual_workout_move",
            title=f"Moved manual workout {from_date} → {to_date}",
            description=body.reason or "",
            actor="coach",
            meta={"workout_id": wid, "from_date": from_date, "to_date": to_date,
                  "swapped_with": (swap_target or {}).get("id"),
                  "warning_override": body.warning_override},
        )
    except Exception:
        logger.exception("manual move: _log_change failed")

    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})
    swap_fresh = None
    if swap_target:
        swap_fresh = await db.workouts.find_one({"id": swap_target["id"]}, {"_id": 0})
    return {
        "ok": True,
        "workout": fresh,
        "moved_from": from_date,
        "moved_to": to_date,
        "swapped_workout": swap_fresh,
        "undo_token": {
            "workout_id": wid,
            "from_date": to_date,          # to undo, we go back
            "to_date": from_date,
            "swap_partner_id": (swap_target or {}).get("id"),
        },
    }


class ManualUndoMoveBody(BaseModel):
    # The response from /move returned an undo_token — pass it back as-is.
    undo_token: dict


@api.post("/coach/workouts/{wid}/manual/undo-move")
async def coach_undo_manual_move(wid: str, body: ManualUndoMoveBody,
                                 coach: dict = Depends(require_role("coach"))):
    w = await _load_manual_workout(wid)
    tok = body.undo_token or {}
    if tok.get("workout_id") != wid:
        raise HTTPException(400, "undo_token workout_id mismatch")
    target_date = tok.get("to_date")     # was the original date
    current_date = tok.get("from_date")  # is where the workout is now
    if not target_date or not current_date:
        raise HTTPException(400, "undo_token missing dates")
    if w.get("date") != current_date:
        # The workout has been moved again since — do NOT silently undo.
        raise HTTPException(
            409,
            "Cannot undo: workout has been changed since the move",
        )

    swap_partner_id = tok.get("swap_partner_id")
    now = now_iso()
    if swap_partner_id:
        partner = await db.workouts.find_one({"id": swap_partner_id}, {"_id": 0})
        if not partner:
            # Partner was deleted; just move this one back.
            swap_partner_id = None
        else:
            # Reverse the swap.
            temp = f"__swap_{new_id()[:8]}"
            await db.workouts.update_one({"id": swap_partner_id},
                                         {"$set": {"date": temp, "updated_at": now}})
            await db.workouts.update_one({"id": wid},
                                         {"$set": {"date": target_date, "updated_at": now},
                                          "$push": {"audit": {"action": "undo_move",
                                                              "by": coach.get("id"), "at": now,
                                                              "from_date": current_date,
                                                              "to_date": target_date,
                                                              "swap_partner_id": swap_partner_id}}})
            await db.workouts.update_one({"id": swap_partner_id},
                                         {"$set": {"date": current_date, "updated_at": now},
                                          "$push": {"audit": {"action": "undo_swap",
                                                              "by": coach.get("id"), "at": now,
                                                              "from_date": target_date,
                                                              "to_date": current_date,
                                                              "swapped_with": wid}}})
    if not swap_partner_id:
        await db.workouts.update_one({"id": wid},
                                     {"$set": {"date": target_date, "updated_at": now},
                                      "$push": {"audit": {"action": "undo_move",
                                                          "by": coach.get("id"), "at": now,
                                                          "from_date": current_date,
                                                          "to_date": target_date}}})

    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=w["user_id"],
            category="workout", kind="manual_workout_move_undo",
            title=f"Undo move: {current_date} → {target_date}",
            actor="coach",
            meta={"workout_id": wid, "from_date": current_date, "to_date": target_date,
                  "swap_partner_id": swap_partner_id},
        )
    except Exception:
        logger.exception("manual undo-move: _log_change failed")

    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})
    return {"ok": True, "workout": fresh, "restored_to": target_date}


class ManualDeleteBody(BaseModel):
    confirm: bool = False
    reason: Optional[str] = None
    # If this manual workout is linked to a replace_day override, decide
    # what to do with the override:
    then_action: Optional[str] = None  # "restore_day" | "suppress_day" | "leave_rest"


@api.delete("/coach/workouts/{wid}/manual")
async def coach_delete_manual_workout(wid: str, body: ManualDeleteBody,
                                      coach: dict = Depends(require_role("coach"))):
    if not body.confirm:
        raise HTTPException(400, "confirmation required (set confirm=true)")
    w = await _load_manual_workout(wid)
    date = w.get("date")
    cid = w.get("user_id")
    now = now_iso()

    # If this workout is the replacement of an active day override, decide
    # how the override should end.
    linked_override = await db.coach_day_overrides.find_one(
        {"client_id": cid, "date": date, "active": True,
         "replacement_workout_id": wid},
        {"_id": 0},
    )

    if linked_override:
        action = body.then_action or "restore_day"
        if action == "restore_day":
            await _deactivate_override(linked_override["id"], coach,
                                       reason=body.reason or "manual workout deleted → restore generated day")
        elif action == "suppress_day":
            # Convert to suppression (rest day) — deactivate old, create new
            await _deactivate_override(linked_override["id"], coach,
                                       reason="manual workout deleted → convert to suppress_day")
            await _upsert_day_override(
                cid=cid, coach=coach, date=date,
                mode="suppress_day", replacement_workout_id=None,
                reason=body.reason or "date suppressed after manual delete",
            )
        elif action == "leave_rest":
            # Keep replace_day pointing at nothing → treat as suppression
            await db.coach_day_overrides.update_one(
                {"id": linked_override["id"]},
                {"$set": {"mode": "suppress_day",
                          "replacement_workout_id": None,
                          "updated_at": now,
                          "reason": body.reason or "manual deleted → left as rest"},
                 "$push": {"audit": {"action": "convert_to_suppress",
                                     "by": coach.get("id"), "at": now,
                                     "reason": body.reason}}},
            )
        else:
            raise HTTPException(400, "then_action must be one of restore_day, suppress_day, leave_rest")

    # Permanent audit record BEFORE hard delete
    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=cid,
            category="workout", kind="manual_workout_delete",
            title=f"Manual workout deleted on {date}",
            description=body.reason or "coach delete",
            actor="coach",
            meta={
                "workout_id": wid, "date": date,
                "source": w.get("source"),
                "title": w.get("title"),
                "workout_type": w.get("workout_type"),
                "duration_min": w.get("duration_min"),
                "main_count": len(w.get("exercises") or []),
                "then_action": body.then_action or "restore_day" if linked_override else None,
                "override_id": (linked_override or {}).get("id"),
            },
        )
    except Exception:
        logger.exception("manual workout delete: _log_change failed")

    await db.workouts.delete_one({"id": wid})
    return {"ok": True, "deleted": True, "linked_override_id": (linked_override or {}).get("id")}


# ---------------------------------------------------------------------------
# Date-level overrides
# ---------------------------------------------------------------------------

async def _upsert_day_override(*, cid: str, coach: dict, date: str,
                               mode: str, replacement_workout_id: Optional[str],
                               reason: Optional[str]) -> str:
    if mode not in _OVERRIDE_MODES:
        raise HTTPException(400, f"mode must be one of {sorted(_OVERRIDE_MODES)}")
    now = now_iso()
    existing = await db.coach_day_overrides.find_one(
        {"client_id": cid, "date": date, "active": True}, {"_id": 0},
    )
    if existing:
        # Update in place, keep audit
        await db.coach_day_overrides.update_one(
            {"id": existing["id"]},
            {"$set": {
                "mode": mode,
                "replacement_workout_id": replacement_workout_id,
                "reason": reason,
                "updated_at": now,
                "coach_id": coach.get("id"),
            },
             "$push": {"audit": {"action": "update", "by": coach.get("id"), "at": now,
                                 "mode": mode, "reason": reason}}},
        )
        return existing["id"]
    doc = {
        "id": new_id(),
        "client_id": cid,
        "coach_id": coach.get("id"),
        "date": date,
        "mode": mode,
        "replacement_workout_id": replacement_workout_id,
        "reason": reason,
        "active": True,
        "created_at": now,
        "updated_at": now,
        "audit": [{"action": "create", "by": coach.get("id"), "at": now,
                   "mode": mode, "reason": reason}],
    }
    await db.coach_day_overrides.insert_one(doc)
    return doc["id"]


async def _deactivate_override(override_id: str, coach: dict, reason: Optional[str]) -> None:
    now = now_iso()
    await db.coach_day_overrides.update_one(
        {"id": override_id, "active": True},
        {"$set": {"active": False, "updated_at": now,
                  "deactivated_by": coach.get("id"),
                  "deactivated_at": now,
                  "deactivated_reason": reason},
         "$push": {"audit": {"action": "deactivate", "by": coach.get("id"),
                             "at": now, "reason": reason}}},
    )


class DayOverrideBody(BaseModel):
    mode: str  # "replace_day" | "suppress_day"
    replacement_workout_id: Optional[str] = None
    reason: Optional[str] = None


@api.post("/coach/clients/{cid}/day-overrides/{date}")
async def coach_set_day_override(cid: str, date: str, body: DayOverrideBody,
                                 coach: dict = Depends(require_role("coach"))):
    await _load_client(cid)
    if body.mode == "replace_day" and not body.replacement_workout_id:
        raise HTTPException(400, "replace_day requires replacement_workout_id")
    if body.replacement_workout_id:
        w = await db.workouts.find_one({"id": body.replacement_workout_id}, {"_id": 0})
        if not w or w.get("user_id") != cid or w.get("source") != MANUAL_SOURCE:
            raise HTTPException(400, "replacement_workout_id must point to a manual workout owned by this client")

    oid = await _upsert_day_override(
        cid=cid, coach=coach, date=date,
        mode=body.mode,
        replacement_workout_id=body.replacement_workout_id,
        reason=body.reason,
    )
    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=cid,
            category="programme", kind=f"day_override_{body.mode}",
            title=f"Day override ({body.mode}) on {date}",
            description=body.reason or "",
            actor="coach",
            meta={"override_id": oid, "date": date,
                  "replacement_workout_id": body.replacement_workout_id},
        )
    except Exception:
        logger.exception("day override: _log_change failed")
    fresh = await db.coach_day_overrides.find_one({"id": oid}, {"_id": 0})
    return {"ok": True, "override": fresh}


@api.delete("/coach/clients/{cid}/day-overrides/{date}")
async def coach_restore_day(cid: str, date: str,
                            coach: dict = Depends(require_role("coach"))):
    await _load_client(cid)
    existing = await db.coach_day_overrides.find_one(
        {"client_id": cid, "date": date, "active": True}, {"_id": 0},
    )
    if not existing:
        return {"ok": True, "no_change": True}
    await _deactivate_override(existing["id"], coach, reason="restore_day")
    try:
        await _log_change(
            coach_id=coach.get("id"), client_id=cid,
            category="programme", kind="day_override_restore",
            title=f"Day override restored on {date}",
            description="generated sessions returned to client view",
            actor="coach",
            meta={"override_id": existing["id"], "date": date},
        )
    except Exception:
        logger.exception("restore_day: _log_change failed")
    return {"ok": True, "restored_override_id": existing["id"]}


@api.get("/coach/clients/{cid}/day-overrides")
async def coach_list_day_overrides(cid: str,
                                   active_only: bool = True,
                                   coach: dict = Depends(require_role("coach"))):
    await _load_client(cid)
    q: dict[str, Any] = {"client_id": cid}
    if active_only:
        q["active"] = True
    rows = await db.coach_day_overrides.find(q, {"_id": 0}).sort("date", 1).to_list(500)
    return {"overrides": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Shared helper — used by the client bridge, /workouts/week filter and
# regenerate skip logic.
# ---------------------------------------------------------------------------

async def get_active_override_dates(user_id: str,
                                    start_iso: Optional[str] = None,
                                    end_iso: Optional[str] = None) -> dict[str, dict]:
    """Return { date_iso: override_row } for every active date-level override
    covering the given user in the optional [start_iso, end_iso] window."""
    q: dict[str, Any] = {"client_id": user_id, "active": True}
    if start_iso or end_iso:
        rng: dict[str, Any] = {}
        if start_iso:
            rng["$gte"] = start_iso
        if end_iso:
            rng["$lte"] = end_iso
        q["date"] = rng
    out: dict[str, dict] = {}
    async for r in db.coach_day_overrides.find(q, {"_id": 0}):
        out[r["date"]] = r
    return out
