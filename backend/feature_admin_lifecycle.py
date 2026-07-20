"""
feature_admin_lifecycle — Slice 1 of the Coach Dashboard Upgrade.

Client lifecycle + audit log. Provides admin-only endpoints for:

  * Archive / Restore   (soft, reversible; data preserved)
  * Pause  / Resume     (login disabled; data preserved)
  * Soft Delete         (status='deletion_pending', login disabled, data retained temporarily)
  * Permanent Delete    (anonymises client data — GDPR Option B, safer for audit)
  * Audit log stream    (every important admin action recorded)

Only users with `role='admin'` OR `is_admin=True` on their user doc can call these.
Louis Hall (louis@crewfit.net) is the default admin; a startup migration in
server.py ensures his flag is set.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api,
    db,
    current_user,
    new_id,
    now_iso,
    logger,
)


LIFECYCLE_STATUSES = ("active", "archived", "paused", "deletion_pending", "deleted")


# ---------------------------------------------------------------------------
# Admin permission dependency
# ---------------------------------------------------------------------------

async def require_admin(user: dict = Depends(current_user)) -> dict:
    """Only users with `role='admin'` OR `is_admin=True` can proceed.
    Regular coaches can view their assigned clients but cannot archive/delete."""
    if not user:
        raise HTTPException(401, "Not authenticated")
    if user.get("role") == "admin" or bool(user.get("is_admin")):
        return user
    raise HTTPException(403, "Admin access required")


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

async def log_audit(
    *,
    actor: dict,
    action: str,
    target_user_id: Optional[str] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    reason: Optional[str] = None,
    extra: Optional[dict] = None,
) -> str:
    """Insert a single audit-log row. Non-fatal on error (never blocks the
    caller). Returns the new row id."""
    try:
        rid = new_id()
        doc = {
            "id": rid,
            "actor_id": actor.get("id"),
            "actor_name": actor.get("name") or actor.get("email"),
            "actor_email": actor.get("email"),
            "actor_role": actor.get("role"),
            "action": action,
            "target_user_id": target_user_id,
            "before": before,
            "after": after,
            "reason": reason,
            "extra": extra,
            "timestamp": now_iso(),
        }
        await db.audit_logs.insert_one(doc)
        return rid
    except Exception:
        logger.exception("audit log insert failed for action=%s", action)
        return ""


async def _snap(client_id: str) -> Optional[dict]:
    """Small profile snapshot for before/after audit rows."""
    u = await db.users.find_one(
        {"id": client_id},
        {"_id": 0, "password_hash": 0, "coaching_dna": 0},
    )
    if not u:
        return None
    return {
        "id": u.get("id"),
        "email": u.get("email"),
        "name": u.get("name"),
        "status": u.get("status") or "active",
        "role": u.get("role"),
        "assigned_coach_id": u.get("assigned_coach_id"),
    }


# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------

class ArchiveBody(BaseModel):
    mode: str = "archive_only"   # "archive_only" (keep login) | "archive_pause" (disable login)
    reason: Optional[str] = None


class RestoreBody(BaseModel):
    reason: Optional[str] = None


class SoftDeleteBody(BaseModel):
    reason: Optional[str] = None


class PermanentDeleteBody(BaseModel):
    confirmation: str            # must equal "DELETE" verbatim
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_client(client_id: str) -> dict:
    c = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Client not found")
    if c.get("role") == "admin" or bool(c.get("is_admin")):
        raise HTTPException(400, "Cannot modify an admin account this way. Change role first.")
    return c


# ---------------------------------------------------------------------------
# ARCHIVE
# ---------------------------------------------------------------------------

@api.post("/admin/clients/{client_id}/archive")
async def archive_client(
    client_id: str,
    body: ArchiveBody,
    admin: dict = Depends(require_admin),
):
    if body.mode not in ("archive_only", "archive_pause"):
        raise HTTPException(400, "mode must be 'archive_only' or 'archive_pause'")
    before = await _snap(client_id)
    _ = await _fetch_client(client_id)

    now = now_iso()
    new_status = "paused" if body.mode == "archive_pause" else "archived"
    await db.users.update_one(
        {"id": client_id},
        {"$set": {
            "status": new_status,
            "archived_at": now,
            "archived_by": admin["id"],
            "archived_mode": body.mode,
            "archived_reason": body.reason,
            "updated_at": now,
        }},
    )
    after = await _snap(client_id)
    await log_audit(actor=admin, action="client.archive", target_user_id=client_id,
                    before=before, after=after, reason=body.reason,
                    extra={"mode": body.mode})
    return {"ok": True, "status": new_status}


# ---------------------------------------------------------------------------
# RESTORE
# ---------------------------------------------------------------------------

@api.post("/admin/clients/{client_id}/restore")
async def restore_client(
    client_id: str,
    body: RestoreBody = RestoreBody(),
    admin: dict = Depends(require_admin),
):
    before = await _snap(client_id)
    c = await _fetch_client(client_id)
    prev_status = str(c.get("status") or "active").lower()
    if prev_status not in ("archived", "paused", "deletion_pending"):
        raise HTTPException(400, f"Cannot restore a client with status={prev_status}")

    now = now_iso()
    await db.users.update_one(
        {"id": client_id},
        {"$set": {
            "status": "active",
            "restored_at": now,
            "restored_by": admin["id"],
            "restored_reason": body.reason,
            "updated_at": now,
        }, "$unset": {"archived_mode": ""}},
    )
    after = await _snap(client_id)
    await log_audit(actor=admin, action="client.restore", target_user_id=client_id,
                    before=before, after=after, reason=body.reason)
    return {"ok": True, "status": "active"}


# ---------------------------------------------------------------------------
# SOFT DELETE
# ---------------------------------------------------------------------------

@api.post("/admin/clients/{client_id}/soft-delete")
async def soft_delete_client(
    client_id: str,
    body: SoftDeleteBody = SoftDeleteBody(),
    admin: dict = Depends(require_admin),
):
    before = await _snap(client_id)
    _ = await _fetch_client(client_id)
    now = now_iso()
    await db.users.update_one(
        {"id": client_id},
        {"$set": {
            "status": "deletion_pending",
            "deletion_pending_at": now,
            "deletion_pending_by": admin["id"],
            "deletion_reason": body.reason,
            "updated_at": now,
        }},
    )
    after = await _snap(client_id)
    await log_audit(actor=admin, action="client.soft_delete", target_user_id=client_id,
                    before=before, after=after, reason=body.reason)
    return {"ok": True, "status": "deletion_pending"}


# ---------------------------------------------------------------------------
# PERMANENT DELETE (anonymise — GDPR Option B)
# ---------------------------------------------------------------------------

@api.post("/admin/clients/{client_id}/permanent-delete")
async def permanent_delete_client(
    client_id: str,
    body: PermanentDeleteBody,
    admin: dict = Depends(require_admin),
):
    """Anonymise the client's PII while keeping business/audit rows intact.

    - `users` doc: email/name/phone/profile scrubbed, status='deleted'.
    - Content collections (rosters/workouts/programmes/messages/check-ins/etc.)
      are left in place but keyed to the tombstoned id so audit trails work.
    """
    if body.confirmation != "DELETE":
        raise HTTPException(400, "confirmation must equal 'DELETE' exactly")

    before = await _snap(client_id)
    c = await _fetch_client(client_id)

    now = now_iso()
    tombstone_email = f"deleted+{client_id[:8]}@crewfit.deleted"
    tombstone_name = f"[deleted client {client_id[:8]}]"
    scrubbed: dict[str, Any] = {
        "email": tombstone_email,
        "name": tombstone_name,
        "phone": None,
        "profile": {
            "airline": None, "home_base": None, "aircraft_type": None,
            "route_focus": None, "job_title": None, "position": None,
            "height_cm": None, "weight_kg": None, "goal": None,
            "main_goal_key": None, "injuries": None, "disliked_exercises": None,
        },
        "coaching_dna": None,
        "avatar": None,
        "onboarded": False,
        "status": "deleted",
        "deleted_at": now,
        "deleted_by": admin["id"],
        "deletion_reason": body.reason,
        "updated_at": now,
        # Random password so any residual credentials become invalid.
        "password_hash": "$2b$12$deleted." + new_id(),
    }
    await db.users.update_one({"id": client_id}, {"$set": scrubbed})

    # Sensitive linked collections: purge messages content, keep skeleton for
    # audit. Anything else stays as-is (workouts don't contain PII beyond user_id).
    try:
        await db.messages.update_many(
            {"$or": [{"from_user_id": client_id}, {"to_user_id": client_id}]},
            {"$set": {"body": "[redacted]", "attachments": [], "redacted_at": now}},
        )
    except Exception:
        pass

    after = await _snap(client_id)
    await log_audit(actor=admin, action="client.permanent_delete", target_user_id=client_id,
                    before=before, after=after, reason=body.reason)
    return {"ok": True, "status": "deleted"}


# ---------------------------------------------------------------------------
# AUDIT LOG READ
# ---------------------------------------------------------------------------

@api.get("/admin/clients/{client_id}/audit-log")
async def client_audit_log(
    client_id: str,
    limit: int = 100,
    admin: dict = Depends(require_admin),
):
    rows = await db.audit_logs.find(
        {"target_user_id": client_id}, {"_id": 0},
    ).sort("timestamp", -1).to_list(limit)
    return {"entries": rows, "count": len(rows)}


@api.get("/admin/audit-log")
async def global_audit_log(
    limit: int = 200,
    action: Optional[str] = None,
    admin: dict = Depends(require_admin),
):
    q: dict[str, Any] = {}
    if action:
        q["action"] = action
    rows = await db.audit_logs.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return {"entries": rows, "count": len(rows)}
