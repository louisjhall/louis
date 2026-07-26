"""
Coach Reset — Phase 6 utility.

Endpoint:
    POST /api/coach/clients/{cid}/reset-programme
        body: {
          rosters: bool = True,
          workouts: bool = True,
          coach_notes: bool = False,
          coach_tasks: bool = False,
          confirm: str  (must equal client's email or id — safety token),
        }

    Wipes selected data for the client. Coach-only. Idempotent.
    Returns counts of removed docs.
"""
from __future__ import annotations
from typing import Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from server import api, db, require_role, now_iso
import logging
logger = logging.getLogger("crewfit.coach_reset")


class ResetBody(BaseModel):
    rosters: bool = True
    workouts: bool = True
    coach_notes: bool = False
    coach_tasks: bool = False
    confirm: str = ""  # safety: must match client's email or id


@api.post("/coach/clients/{client_id}/reset-programme")
async def coach_reset_programme(
    client_id: str,
    body: ResetBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Client not found")

    # Safety: coach must type the client's email OR id to confirm.
    if body.confirm not in (user.get("email") or "", user.get("id") or ""):
        raise HTTPException(400, "Confirmation token must equal the client's email or id.")

    stats = {"rosters": 0, "workouts": 0, "coach_notes": 0, "coach_tasks": 0}
    now = now_iso()

    if body.rosters:
        r = await db.rosters.delete_many({"user_id": client_id})
        stats["rosters"] = r.deleted_count
        # Also nuke any queued jobs
        try:
            await db.roster_jobs.delete_many({"user_id": client_id})
        except Exception:
            pass

    if body.workouts:
        r = await db.workouts.delete_many({"user_id": client_id})
        stats["workouts"] = r.deleted_count
        try:
            await db.workout_exercise_swaps.delete_many({"user_id": client_id})
        except Exception:
            pass

    if body.coach_notes:
        await db.users.update_one({"id": client_id}, {"$unset": {"coach_notes": ""}})
        stats["coach_notes"] = 1
        try:
            await db.coach_notes_history.delete_many({"user_id": client_id})
        except Exception:
            pass

    if body.coach_tasks:
        try:
            r = await db.coach_tasks.delete_many({"user_id": client_id})
            stats["coach_tasks"] = r.deleted_count
        except Exception:
            pass

    # Audit
    try:
        await db.coach_reset_audit.insert_one({
            "user_id": client_id,
            "coach_id": coach.get("id"),
            "at": now,
            "stats": stats,
            "options": body.model_dump(),
        })
    except Exception:
        logger.exception("Failed to write coach_reset_audit (non-fatal)")

    return {"ok": True, "stats": stats, "client": {"id": client_id, "name": user.get("name") or user.get("email")}}
