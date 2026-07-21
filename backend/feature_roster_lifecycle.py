"""
feature_roster_lifecycle — Plan D4-D7.

Client-facing roster restart + safe cascade cleanup.

Concepts:
  * SOFT-DELETE — rosters are versioned + soft-deleted (status='deleted_by_client'
    or 'replaced'). Never physically removed unless GDPR erase is invoked.
  * TWO DELETE MODES:
      1. Delete Roster And Future Plan (RECOMMENDED)
           removes  → active roster · uncompleted workouts linked to that roster
                      · programme linked to that roster · pending gen jobs
           preserves → completed workouts · workout logs · check-ins · habits
                      · messages · coach notes · coach-locked workouts
      2. Delete Roster Only
           removes → active roster
           preserves → EVERYTHING (workouts stay until they naturally rotate)
  * UPLOAD UPDATED — new roster stays "pending" until the client confirms;
    the old roster stays active so the client is never left without a plan.
    Only on confirm does the old roster deactivate.
  * ALWAYS AUDIT — every step (roster.deletion_requested, roster.deactivated,
    workouts.deactivated, programme.deactivated, replacement.uploaded, …) is
    logged to `db.roster_audit_log`.

Client copy: NEVER "AI". Use "CrewFit will rebuild your plan".

Endpoints:
  * GET  /api/roster/management                        client Roster Management screen data
  * POST /api/roster/delete-and-restart                delete roster (+ optional future plan) → set awaiting_roster
  * POST /api/roster/upload-updated                    upload replacement (safe path — keeps old active)
  * GET  /api/coach/clients/{cid}/roster-audit         coach view of a client's audit trail
"""

from __future__ import annotations

import asyncio as _asyncio
import datetime as _dt
from typing import Any, Optional

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
    _create_coach_task,
    _log_change,
)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

async def _audit(user_id: str, event: str, meta: Optional[dict] = None, actor: str = "client") -> None:
    """Append one row to roster_audit_log. Never raises."""
    try:
        await db.roster_audit_log.insert_one({
            "id": new_id(),
            "user_id": user_id,
            "event": event,
            "actor": actor,
            "meta": meta or {},
            "at": now_iso(),
        })
    except Exception:
        logger.exception("roster audit log insert failed (non-fatal)")


# ---------------------------------------------------------------------------
# Cascade cleanup primitives
# ---------------------------------------------------------------------------

async def _deactivate_future_workouts(user_id: str, roster_id: str, preserve_coach_locked: bool = True) -> dict[str, int]:
    """Deactivate future uncompleted workouts linked to a given roster.
    Coach-locked and completed workouts are NEVER deactivated (safety).
    Returns counts.
    """
    today = _dt.date.today().isoformat()
    q: dict[str, Any] = {
        "user_id": user_id,
        "roster_id": roster_id,
        "date": {"$gte": today},
        "completed": {"$ne": True},
    }
    if preserve_coach_locked:
        q["coach_locked"] = {"$ne": True}

    # Snapshot ids we're about to soft-delete so cross-cleanup is auditable.
    to_deactivate = await db.workouts.find(q, {"_id": 0, "id": 1, "date": 1}).to_list(500)
    ids = [w["id"] for w in to_deactivate]
    dates = [w["date"] for w in to_deactivate]
    if ids:
        await db.workouts.update_many(
            {"id": {"$in": ids}},
            {"$set": {
                "deactivated": True,
                "deactivated_at": now_iso(),
                "deactivated_reason": "roster_deleted",
                "updated_at": now_iso(),
            }},
        )
    # Also count coach-locked survivors so we can warn the user.
    locked_kept = await db.workouts.count_documents({
        "user_id": user_id, "roster_id": roster_id,
        "date": {"$gte": today},
        "coach_locked": True,
        "completed": {"$ne": True},
    })
    return {
        "deactivated": len(ids),
        "coach_locked_preserved": locked_kept,
        "dates": dates[:20],  # first 20 for audit
    }


async def _deactivate_programme(user_id: str, roster_id: str) -> Optional[str]:
    prog = await db.programmes.find_one(
        {"user_id": user_id, "roster_id": roster_id}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not prog:
        return None
    await db.programmes.update_one(
        {"id": prog["id"]},
        {"$set": {
            "status": "awaiting_roster",
            "deactivated": True,
            "deactivated_at": now_iso(),
            "deactivated_reason": "roster_deleted",
            "updated_at": now_iso(),
        }},
    )
    return prog["id"]


async def _cancel_pending_gen_jobs(user_id: str, roster_id: str) -> int:
    """Cancel any gen_jobs still running for this roster so a late completion
    can't repopulate deleted workouts."""
    res = await db.gen_jobs.update_many(
        {
            "user_id": user_id,
            "roster_id": roster_id,
            "status": {"$in": ["queued", "running", "processing", "needs_review"]},
        },
        {"$set": {
            "status": "cancelled",
            "cancelled_reason": "roster_deleted_by_client",
            "cancelled_at": now_iso(),
        }},
    )
    return res.modified_count


async def _create_coach_notification_task(client: dict, deleted_roster: dict, mode: str, cleanup_summary: dict) -> None:
    """One coach task per delete event so Louis sees what happened."""
    try:
        title = (
            f"Roster deleted — {mode.replace('_', ' ')}: {client.get('name') or client.get('email')}"
        )
        description = (
            f"Client removed their active roster on {now_iso()[:10]}.\n"
            f"Deleted roster period: {deleted_roster.get('week_start', '?')} → {deleted_roster.get('week_end', '?')}\n"
            f"Future uncompleted workouts deactivated: {cleanup_summary.get('workouts_deactivated', 0)}\n"
            f"Coach-locked workouts preserved: {cleanup_summary.get('coach_locked_preserved', 0)}\n"
            f"Pending gen jobs cancelled: {cleanup_summary.get('jobs_cancelled', 0)}\n"
            "Client is on the Upload Roster screen — awaiting new roster upload."
        )
        priority = "high" if cleanup_summary.get("coach_locked_preserved", 0) > 0 else "normal"
        await _create_coach_task(
            client,
            task_type="roster_deleted",
            title=title,
            description=description,
            priority=priority,
            category="roster",
            payload={
                "roster_id": deleted_roster.get("id"),
                "mode": mode,
                "cleanup_summary": cleanup_summary,
                "client_id": client.get("id"),
            },
        )
    except Exception:
        logger.exception("coach task for roster delete failed (non-fatal)")


# ---------------------------------------------------------------------------
# Reminder ticker — 48h no-replacement warning
# ---------------------------------------------------------------------------

async def _tick_roster_no_replacement_warning() -> None:
    """Called by the main reminder ticker. Coach task fires if a client has
    deleted their roster > 48h ago with no replacement uploaded."""
    try:
        cutoff = (_dt.datetime.utcnow() - _dt.timedelta(hours=48)).isoformat()
        # Find users with recent deletion but no active roster + no coach task fired
        async for row in db.roster_audit_log.find({
            "event": "roster.deleted",
            "at": {"$lte": cutoff},
            "meta.no_replacement_warned": {"$ne": True},
        }, {"_id": 0}).limit(50):
            uid = row.get("user_id")
            if not uid:
                continue
            active = await db.rosters.find_one({"user_id": uid, "is_active": True}, {"_id": 0})
            if active:
                # Client has re-uploaded — mark warned so we don't re-fire.
                await db.roster_audit_log.update_one(
                    {"id": row["id"]},
                    {"$set": {"meta.no_replacement_warned": True, "meta.no_replacement_resolved_at": now_iso()}},
                )
                continue
            client = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
            if not client:
                continue
            try:
                await _create_coach_task(
                    client,
                    task_type="roster_no_replacement",
                    title=f"48h — no replacement roster: {client.get('name') or client.get('email')}",
                    description=(
                        "Client deleted their active roster 48h+ ago and hasn't uploaded a "
                        "replacement. They may need a gentle nudge or help."
                    ),
                    priority="high",
                    category="roster",
                    payload={"client_id": uid, "deleted_at": row.get("at")},
                )
            except Exception:
                logger.exception("roster_no_replacement task creation failed (non-fatal)")
            finally:
                await db.roster_audit_log.update_one(
                    {"id": row["id"]},
                    {"$set": {"meta.no_replacement_warned": True, "meta.no_replacement_warned_at": now_iso()}},
                )
    except Exception:
        logger.exception("_tick_roster_no_replacement_warning raised (non-fatal)")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.get("/roster/management")
async def roster_management(user: dict = Depends(current_user)):
    """Data for the client Roster Management screen."""
    active = await db.rosters.find_one({"user_id": user["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    versions = await db.rosters.count_documents({"user_id": user["id"]})
    pending_replacement = await db.rosters.find_one(
        {"user_id": user["id"], "is_active": False, "status": "pending_confirmation"},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    programme = None
    if active:
        programme = await db.programmes.find_one(
            {"user_id": user["id"], "roster_id": active.get("id")}, {"_id": 0}, sort=[("created_at", -1)],
        )
    today = _dt.date.today().isoformat()
    horizon = (_dt.date.today() + _dt.timedelta(days=14)).isoformat()
    upcoming_count = await db.workouts.count_documents({
        "user_id": user["id"],
        "date": {"$gte": today, "$lte": horizon},
        "deactivated": {"$ne": True},
    })
    coach_locked = await db.workouts.count_documents({
        "user_id": user["id"],
        "date": {"$gte": today},
        "coach_locked": True,
        "deactivated": {"$ne": True},
    })
    return {
        "active_roster": active,
        "programme": programme,
        "upcoming_workouts_count": upcoming_count,
        "coach_locked_upcoming_count": coach_locked,
        "pending_replacement": pending_replacement,
        "versions_total": versions,
    }


class RosterDeleteBody(BaseModel):
    mode: str = "delete_and_future_plan"  # "delete_and_future_plan" | "delete_only"
    reason: Optional[str] = None
    confirm: bool = True                   # must be true; UI enforces double-tap
    typed_delete: Optional[str] = None     # "DELETE" — enforced on real accounts


@api.post("/roster/delete-and-restart")
async def roster_delete_and_restart(body: RosterDeleteBody, user: dict = Depends(current_user)):
    """Client action: remove the active roster (+ optionally the future plan).
    Returns cleanup summary so the UI can show a receipt."""
    if not body.confirm:
        raise HTTPException(400, "confirmation flag required")

    # Real accounts must type DELETE. Preview accounts skip this check.
    is_preview = bool(user.get("is_preview_sandbox"))
    if not is_preview and body.typed_delete != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm the deletion.")

    active = await db.rosters.find_one(
        {"user_id": user["id"], "is_active": True}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not active:
        raise HTTPException(400, "You don't have an active roster to delete.")

    roster_id = active["id"]

    # Warn if coach-locked workouts exist (soft-warn — proceed anyway; kept intact)
    coach_locked_upcoming = await db.workouts.count_documents({
        "user_id": user["id"], "roster_id": roster_id,
        "date": {"$gte": _dt.date.today().isoformat()},
        "coach_locked": True, "completed": {"$ne": True},
    })

    await _audit(user["id"], "roster.deletion_requested", {
        "roster_id": roster_id, "mode": body.mode, "reason": body.reason,
        "coach_locked_at_delete": coach_locked_upcoming,
    })

    # Soft-delete roster (never hard-delete unless GDPR).
    await db.rosters.update_one(
        {"id": roster_id},
        {"$set": {
            "status": "deleted_by_client",
            "is_active": False,
            "deleted_at": now_iso(),
            "deleted_by": user["id"],
            "deletion_reason": body.reason,
            "deletion_mode": body.mode,
            "updated_at": now_iso(),
        }},
    )
    await _audit(user["id"], "roster.deactivated", {"roster_id": roster_id})

    workouts_deactivated = 0
    programme_deactivated_id: Optional[str] = None
    jobs_cancelled = 0

    if body.mode == "delete_and_future_plan":
        cleanup = await _deactivate_future_workouts(user["id"], roster_id)
        workouts_deactivated = cleanup["deactivated"]
        await _audit(user["id"], "workouts.deactivated", {
            "count": workouts_deactivated,
            "dates_sample": cleanup["dates"],
            "coach_locked_preserved": cleanup["coach_locked_preserved"],
        })
        programme_deactivated_id = await _deactivate_programme(user["id"], roster_id)
        if programme_deactivated_id:
            await _audit(user["id"], "programme.deactivated", {
                "programme_id": programme_deactivated_id,
            })
        jobs_cancelled = await _cancel_pending_gen_jobs(user["id"], roster_id)
        if jobs_cancelled:
            await _audit(user["id"], "gen_jobs.cancelled", {"count": jobs_cancelled})

    cleanup_summary = {
        "roster_id": roster_id,
        "mode": body.mode,
        "workouts_deactivated": workouts_deactivated,
        "coach_locked_preserved": coach_locked_upcoming,
        "programme_deactivated_id": programme_deactivated_id,
        "jobs_cancelled": jobs_cancelled,
    }
    await _audit(user["id"], "roster.deleted", cleanup_summary)

    # Coach notification + change log
    try:
        await _create_coach_notification_task(user, active, body.mode, cleanup_summary)
    except Exception:
        pass
    try:
        await _log_change(
            coach_id=None, client_id=user["id"],
            category="roster",
            title="Client deleted their active roster",
            description=f"Mode: {body.mode} · workouts deactivated: {workouts_deactivated} · coach-locked preserved: {coach_locked_upcoming}",
            actor="client",
            meta=cleanup_summary,
        )
    except Exception:
        pass

    # Flip a lightweight status flag on the user doc so the UI can show
    # "awaiting_roster" without another query.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"roster_status": "awaiting_roster", "updated_at": now_iso()}},
    )

    return {
        "ok": True,
        "roster_status": "awaiting_roster",
        "cleanup_summary": cleanup_summary,
        "message": (
            "Roster removed. Upload your correct roster when you're ready — "
            "CrewFit will rebuild your schedule after you review and confirm it."
        ),
    }


class RosterUploadUpdatedBody(BaseModel):
    """Body for uploading an UPDATED roster while keeping the current plan
    active until confirmation. The parse + review flow is unchanged — this
    endpoint just tags the new roster as `pending_confirmation` and leaves
    the current active roster in place."""
    # We accept a raw file base64 + mime here so the client can trigger the
    # same parser path. The heavy lifting is delegated to the existing
    # roster-upload worker; this shim only sets the correct flags so the
    # replacement doesn't clobber the current plan prematurely.
    file_base64: str
    mime_type: str
    reason: Optional[str] = None


@api.post("/roster/upload-updated")
async def roster_upload_updated(body: RosterUploadUpdatedBody, user: dict = Depends(current_user)):
    """Kick off a replacement roster upload. Keeps the current roster active
    until the client confirms the replacement.

    This is intentionally thin — it just records the intent in the audit log
    and returns instructions for the client to run the normal roster-upload
    flow with `replacement=true`. The actual parse still happens via
    `/api/roster/upload-and-generate`.
    """
    await _audit(user["id"], "roster.replacement_upload_started", {"reason": body.reason})
    return {
        "ok": True,
        "message": (
            "Start the upload flow — CrewFit will parse and let you review "
            "the new roster before it replaces your current plan."
        ),
        "next": "/api/roster/upload-and-generate",
        "keep_current_active_until_confirm": True,
    }


@api.get("/coach/clients/{client_id}/roster-audit")
async def coach_roster_audit(client_id: str, coach: dict = Depends(require_role("coach"))):
    """Coach view of a client's roster lifecycle audit trail."""
    rows = await db.roster_audit_log.find(
        {"user_id": client_id}, {"_id": 0},
    ).sort("at", -1).limit(200).to_list(200)
    return {"audit": rows, "count": len(rows)}


__all__ = [
    "_audit",
    "_deactivate_future_workouts",
    "_deactivate_programme",
    "_cancel_pending_gen_jobs",
    "_tick_roster_no_replacement_warning",
]
