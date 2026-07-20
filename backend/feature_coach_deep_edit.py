"""
feature_coach_deep_edit — Slice 3.5 of the Coach Dashboard Upgrade.

Provides coach/admin endpoints for deep-diving into a client's roster and
programme. All routes require a `coach` or `admin` role.

Endpoints:
    POST   /api/coach/workouts/{wid}/approve       — Approve a single workout
    POST   /api/coach/workouts/{wid}/lock          — Toggle coach-lock
    POST   /api/coach/workouts/{wid}/move          — Move / swap workout to a new date
    POST   /api/coach/workouts/{wid}/regenerate    — Regenerate a single workout
    PATCH  /api/coach/clients/{client_id}/roster/{rid}/day
                                                   — Edit a single roster day
    POST   /api/coach/clients/{client_id}/roster/{rid}/hotel
                                                   — Attach hotel to a day (coach view)

Every mutation writes a structured audit-log row via feature_admin_lifecycle.log_audit
and a client-visible entry to change_log so Louis (and later coaches) get full
traceability.
"""
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    logger,
    DAY_TYPES,
    HotelBody,
    _upsert_hotel,
    _generate_month,
    _merge_variants,
)
from feature_admin_lifecycle import log_audit


# ---------------------------------------------------------------------------
# Coach-or-admin gate. Coaches see everything for their assigned clients; admins
# have global reach. Deep-edit is a workflow tool, so we allow both.
# ---------------------------------------------------------------------------

async def require_coach_or_admin(user: dict = Depends(current_user)) -> dict:
    if not user:
        raise HTTPException(401, "Not authenticated")
    role = user.get("role")
    if role in ("coach", "admin") or bool(user.get("is_admin")):
        return user
    raise HTTPException(403, "Coach or admin access required")


async def _get_workout_or_404(wid: str) -> dict:
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "Workout not found")
    return w


async def _log_client_change(
    *,
    user_id: Optional[str],
    coach_id: Optional[str],
    category: str,
    title: str,
    description: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    """Small helper that mirrors feature_coach_v1's change-log format."""
    try:
        await db.change_log.insert_one({
            "id": new_id(),
            "user_id": user_id,
            "coach_id": coach_id,
            "category": category,
            "title": title,
            "description": description,
            "meta": meta or {},
            "created_at": now_iso(),
        })
    except Exception:
        logger.exception("change_log insert failed for %s / %s", user_id, title)


# ---------------------------------------------------------------------------
# Workout: approve
# ---------------------------------------------------------------------------

class ApproveWorkoutBody(BaseModel):
    note: Optional[str] = None


@api.post("/coach/workouts/{wid}/approve")
async def coach_workout_approve(
    wid: str,
    body: ApproveWorkoutBody = ApproveWorkoutBody(),
    coach: dict = Depends(require_coach_or_admin),
):
    """Approve a single workout. Marks it as `approved=True` and clears
    `needs_coach_review`. Idempotent."""
    w = await _get_workout_or_404(wid)
    already = bool(w.get("approved"))
    await db.workouts.update_one(
        {"id": wid},
        {"$set": {
            "approved": True,
            "needs_coach_review": False,
            "coach_approved_by": coach["id"],
            "coach_approved_at": now_iso(),
            "coach_approval_note": (body.note or "").strip() or None,
            "updated_at": now_iso(),
        }},
    )
    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})

    if not already:
        await log_audit(
            actor=coach, action="workout.approve",
            target_user_id=w.get("user_id"),
            after={"workout_id": wid, "date": w.get("date")},
            reason=body.note,
        )
        await _log_client_change(
            user_id=w.get("user_id"), coach_id=coach["id"],
            category="workout",
            title=f"Approved workout {w.get('title') or wid}",
            description=body.note,
            meta={"workout_id": wid, "date": w.get("date")},
        )
    return {"ok": True, "workout": fresh, "was_already_approved": already}


# ---------------------------------------------------------------------------
# Workout: lock / unlock
# ---------------------------------------------------------------------------

class LockWorkoutBody(BaseModel):
    locked: bool
    note: Optional[str] = None


@api.post("/coach/workouts/{wid}/lock")
async def coach_workout_lock(
    wid: str, body: LockWorkoutBody,
    coach: dict = Depends(require_coach_or_admin),
):
    """Toggle `coach_locked` on a workout. Locked workouts are preserved
    across regeneration and cannot be moved by client-side actions."""
    w = await _get_workout_or_404(wid)
    prev = bool(w.get("coach_locked"))
    if prev == bool(body.locked):
        return {"ok": True, "workout": w, "changed": False}

    await db.workouts.update_one(
        {"id": wid},
        {"$set": {
            "coach_locked": bool(body.locked),
            "coach_locked_by": coach["id"] if body.locked else None,
            "coach_locked_at": now_iso() if body.locked else None,
            "coach_lock_note": (body.note or "").strip() or None,
            "updated_at": now_iso(),
        }},
    )
    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})

    await log_audit(
        actor=coach,
        action="workout.lock" if body.locked else "workout.unlock",
        target_user_id=w.get("user_id"),
        before={"coach_locked": prev},
        after={"coach_locked": bool(body.locked)},
        reason=body.note,
        extra={"workout_id": wid, "date": w.get("date")},
    )
    await _log_client_change(
        user_id=w.get("user_id"), coach_id=coach["id"],
        category="workout",
        title=("Locked" if body.locked else "Unlocked") + f" workout on {w.get('date')}",
        description=body.note,
        meta={"workout_id": wid, "date": w.get("date")},
    )
    return {"ok": True, "workout": fresh, "changed": True}


# ---------------------------------------------------------------------------
# Workout: move / swap
# ---------------------------------------------------------------------------

class MoveWorkoutBody(BaseModel):
    to_date: str
    swap_with_existing: bool = True
    note: Optional[str] = None


@api.post("/coach/workouts/{wid}/move")
async def coach_workout_move(
    wid: str, body: MoveWorkoutBody,
    coach: dict = Depends(require_coach_or_admin),
):
    """Move a workout to a new date. If `swap_with_existing=True` (default)
    and another workout occupies that day for the same client, the two are
    swapped. Otherwise the destination workout is preserved and this move
    fails with 409."""
    w = await _get_workout_or_404(wid)
    from_date = w.get("date")
    to_date = (body.to_date or "").strip()
    if not to_date:
        raise HTTPException(400, "to_date required")
    if to_date == from_date:
        return {"ok": True, "workout": w, "changed": False}

    if w.get("completed"):
        raise HTTPException(400, "Cannot move a completed workout")

    other = await db.workouts.find_one(
        {"user_id": w.get("user_id"), "date": to_date},
    )

    if other and not body.swap_with_existing:
        raise HTTPException(409, "Destination has a workout — enable swap to proceed")

    if other and (other.get("completed") or other.get("coach_locked")):
        raise HTTPException(
            409,
            "Destination has a completed or coach-locked workout — cannot swap",
        )

    # Perform swap or move atomically. We overwrite the date field only.
    if other:
        # Use temp placeholder to avoid unique-index conflicts if any.
        temp_marker = f"__swap_{new_id()[:8]}"
        await db.workouts.update_one({"id": other["id"]}, {"$set": {"date": temp_marker, "updated_at": now_iso()}})
        await db.workouts.update_one({"id": wid}, {"$set": {"date": to_date, "updated_at": now_iso()}})
        await db.workouts.update_one({"id": other["id"]}, {"$set": {"date": from_date, "updated_at": now_iso()}})
    else:
        await db.workouts.update_one({"id": wid}, {"$set": {"date": to_date, "updated_at": now_iso()}})

    fresh = await db.workouts.find_one({"id": wid}, {"_id": 0})

    await log_audit(
        actor=coach, action="workout.move",
        target_user_id=w.get("user_id"),
        before={"date": from_date, "swapped_with": other.get("id") if other else None},
        after={"date": to_date},
        reason=body.note,
        extra={"workout_id": wid, "swap": bool(other)},
    )
    await _log_client_change(
        user_id=w.get("user_id"), coach_id=coach["id"],
        category="workout",
        title=f"Moved workout {from_date} → {to_date}",
        description=body.note,
        meta={"workout_id": wid, "swap": bool(other)},
    )
    return {"ok": True, "workout": fresh, "swapped": bool(other), "changed": True}


# ---------------------------------------------------------------------------
# Workout: regenerate a single day
# ---------------------------------------------------------------------------

class RegenSingleBody(BaseModel):
    note: Optional[str] = None


@api.post("/coach/workouts/{wid}/regenerate")
async def coach_workout_regenerate_single(
    wid: str,
    body: RegenSingleBody = RegenSingleBody(),
    coach: dict = Depends(require_coach_or_admin),
):
    """Regenerate a single workout by rebuilding via the same pipeline used
    for full-week regen, scoped to this one date. Preserves nothing on the
    old workout except its `id` slot (a new record replaces it in place).
    Locked or completed workouts are refused."""
    w = await _get_workout_or_404(wid)
    if w.get("coach_locked"):
        raise HTTPException(400, "Workout is coach-locked; unlock first to regenerate")
    if w.get("completed"):
        raise HTTPException(400, "Workout is completed; cannot regenerate")

    client_id = w.get("user_id")
    roster_id = w.get("roster_id")
    date = w.get("date")
    if not (client_id and date):
        raise HTTPException(400, "Workout is missing required client or date fields")

    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "Client not found")

    roster = None
    if roster_id:
        roster = await db.rosters.find_one({"id": roster_id, "user_id": client_id}, {"_id": 0})
    if not roster:
        # Fall back to the client's active roster
        roster = await db.rosters.find_one(
            {"user_id": client_id, "is_active": True},
            {"_id": 0},
            sort=[("created_at", -1)],
        )
    if not roster:
        raise HTTPException(404, "No active roster to regenerate from")

    sub_days = [d for d in (roster.get("days") or []) if d.get("date") == date]
    if not sub_days:
        raise HTTPException(400, f"Date {date} not found on the active roster")

    sub_roster = {**roster, "days": sub_days}

    try:
        workouts = await _generate_month(client, sub_roster)
    except Exception as e:
        logger.exception("coach regenerate single failed: %s", e)
        raise HTTPException(500, f"Regeneration failed: {e}")

    if not workouts:
        raise HTTPException(500, "Regeneration produced no workout")

    new_w = workouts[0]
    existing = await db.workouts.find_one(
        {"user_id": client_id, "roster_id": roster["id"], "date": date},
        {"_id": 0},
    )
    doc = {
        "id": existing["id"] if existing else new_id(),
        "user_id": client_id, "roster_id": roster["id"], "date": date,
        "day_load": new_w.get("day_load", "green"),
        "title": new_w.get("title", "Session"),
        "location": new_w.get("location", "Home Workout"),
        "duration_min": new_w.get("duration_min", 40),
        "focus": new_w.get("focus", "full"),
        "warmup": new_w.get("warmup", []),
        "exercises": new_w.get("exercises", []),
        "alternatives": new_w.get("alternatives", {}),
        "rationale": new_w.get("rationale", ""),
        "key_session": bool(new_w.get("key_session", False)),
        "event_phase": new_w.get("event_phase"),
        "source": "coach_regen_single",
        "needs_coach_review": False,
        "variants": _merge_variants(new_w, existing),
        "approved": False,
        "completed": False,
        "coach_notes": existing.get("coach_notes", "") if existing else "",
        "coach_locked": False,
        "coach_regen_note": (body.note or "").strip() or None,
        "created_at": existing.get("created_at", now_iso()) if existing else now_iso(),
        "updated_at": now_iso(),
    }
    await db.workouts.delete_many({"user_id": client_id, "date": date})
    await db.workouts.insert_one(doc)
    fresh = await db.workouts.find_one({"id": doc["id"]}, {"_id": 0})

    await log_audit(
        actor=coach, action="workout.regenerate_single",
        target_user_id=client_id,
        before={"workout_id": wid, "date": date, "title": w.get("title")},
        after={"workout_id": doc["id"], "title": doc["title"]},
        reason=body.note,
    )
    await _log_client_change(
        user_id=client_id, coach_id=coach["id"],
        category="workout",
        title=f"Regenerated workout on {date}",
        description=body.note,
        meta={"workout_id": doc["id"], "date": date},
    )
    return {"ok": True, "workout": fresh}


# ---------------------------------------------------------------------------
# Roster: edit a single day
# ---------------------------------------------------------------------------

class RosterDayPatch(BaseModel):
    date: str
    day_type: Optional[str] = None
    load: Optional[str] = None
    notes: Optional[str] = None
    home_or_away: Optional[str] = None
    layover_city: Optional[str] = None
    layover_country: Optional[str] = None
    clear_hotel: bool = False


VALID_LOADS = {"green", "amber", "red", "blue", "purple", "grey"}


@api.patch("/coach/clients/{client_id}/roster/{rid}/day")
async def coach_edit_roster_day(
    client_id: str, rid: str, body: RosterDayPatch,
    coach: dict = Depends(require_coach_or_admin),
):
    """Edit a specific day on a client's roster. Coach can adjust duty type,
    load, notes, layover metadata, and clear the attached hotel."""
    roster = await db.rosters.find_one({"id": rid, "user_id": client_id})
    if not roster:
        raise HTTPException(404, "Roster not found")

    days = list(roster.get("days") or [])
    idx = next((i for i, d in enumerate(days) if d.get("date") == body.date), -1)
    if idx < 0:
        raise HTTPException(404, "Date not on roster")

    before = dict(days[idx])
    day = dict(before)

    if body.day_type is not None:
        if body.day_type not in DAY_TYPES:
            raise HTTPException(400, f"Unknown day_type — must be one of the standard {len(DAY_TYPES)} types")
        day["day_type"] = body.day_type
        # Update home_or_away hint if not overridden
        if body.home_or_away is None:
            lower = body.day_type.lower()
            if "home" in lower or "rest" in lower or "recovery" in lower:
                day["home_or_away"] = "home"
            elif "layover" in lower:
                day["home_or_away"] = "away"

    if body.load is not None:
        if body.load not in VALID_LOADS:
            raise HTTPException(400, f"Invalid load; must be one of {sorted(VALID_LOADS)}")
        day["load"] = body.load

    if body.notes is not None:
        day["notes"] = body.notes.strip() or None

    if body.home_or_away in ("home", "away", "unknown"):
        day["home_or_away"] = body.home_or_away

    if body.layover_city is not None:
        day["layover_city"] = body.layover_city.strip() or None
    if body.layover_country is not None:
        day["layover_country"] = body.layover_country.strip() or None

    if body.clear_hotel:
        day["hotel_id"] = None
        day["hotel_name"] = None

    day["last_edited_by"] = "coach"
    day["last_edited_by_id"] = coach["id"]
    day["last_edited_at"] = now_iso()

    days[idx] = day
    await db.rosters.update_one({"id": rid}, {"$set": {"days": days, "updated_at": now_iso()}})

    await log_audit(
        actor=coach, action="roster.day_edit",
        target_user_id=client_id,
        before=before, after=day,
        extra={"roster_id": rid, "date": body.date},
    )
    await _log_client_change(
        user_id=client_id, coach_id=coach["id"],
        category="programme",
        title=f"Edited roster day {body.date}",
        description=(day.get("day_type") or "").strip() or None,
        meta={"roster_id": rid, "date": body.date},
    )
    return {"ok": True, "day": day}


# ---------------------------------------------------------------------------
# Roster: attach hotel from coach view
# ---------------------------------------------------------------------------

class CoachHotelAttach(BaseModel):
    date: str
    hotel: HotelBody


@api.post("/coach/clients/{client_id}/roster/{rid}/hotel")
async def coach_attach_hotel(
    client_id: str, rid: str, body: CoachHotelAttach,
    coach: dict = Depends(require_coach_or_admin),
):
    """Coach-side hotel attachment. Upserts the hotel in the shared community
    DB and links it to the specified day on this client's roster."""
    roster = await db.rosters.find_one({"id": rid, "user_id": client_id})
    if not roster:
        raise HTTPException(404, "Roster not found")

    days = list(roster.get("days") or [])
    idx = next((i for i, d in enumerate(days) if d.get("date") == body.date), -1)
    if idx < 0:
        raise HTTPException(404, "Date not on roster")

    hotel = await _upsert_hotel(body.hotel, coach["id"])
    before = dict(days[idx])
    days[idx]["hotel_id"] = hotel["id"]
    days[idx]["hotel_name"] = hotel["name"]
    days[idx]["last_edited_by"] = "coach"
    days[idx]["last_edited_at"] = now_iso()
    await db.rosters.update_one({"id": rid}, {"$set": {"days": days, "updated_at": now_iso()}})

    await log_audit(
        actor=coach, action="roster.hotel_attach",
        target_user_id=client_id,
        before={"hotel_id": before.get("hotel_id"), "hotel_name": before.get("hotel_name")},
        after={"hotel_id": hotel["id"], "hotel_name": hotel["name"]},
        extra={"roster_id": rid, "date": body.date},
    )
    await _log_client_change(
        user_id=client_id, coach_id=coach["id"],
        category="programme",
        title=f"Attached hotel {hotel['name']} on {body.date}",
        meta={"roster_id": rid, "date": body.date, "hotel_id": hotel["id"]},
    )
    return {"ok": True, "day": days[idx], "hotel": hotel}
