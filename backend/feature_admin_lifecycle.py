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


# ---------------------------------------------------------------------------
# Slice 2: Coach management + client assignment + role hierarchy
# ---------------------------------------------------------------------------

COACH_TIERS = ("admin", "full", "assistant")


def _coach_public(u: dict) -> dict:
    """Public/coach-list projection — strips password hash and sensitive DNA."""
    return {
        "id": u.get("id"),
        "email": u.get("email"),
        "name": u.get("name"),
        "role": u.get("role"),
        "is_admin": bool(u.get("is_admin")),
        "coach_tier": u.get("coach_tier") or ("admin" if u.get("is_admin") else "full"),
        "status": u.get("status") or "active",
        "created_at": u.get("created_at"),
        "last_login": u.get("last_login"),
        "phone": u.get("phone"),
    }


async def _default_coach_id() -> Optional[str]:
    """Louis is the default fallback if no explicit assignment is set."""
    louis = await db.users.find_one({"email": "louis@crewfit.net"}, {"_id": 0, "id": 1})
    return (louis or {}).get("id")


class CoachInviteBody(BaseModel):
    email: str
    name: str
    tier: str = "full"          # "full" | "assistant"
    phone: Optional[str] = None


class CoachPatchBody(BaseModel):
    tier: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    is_admin: Optional[bool] = None


class CoachStatusBody(BaseModel):
    active: bool = True         # False = deactivate (status='paused')


class AssignCoachBody(BaseModel):
    coach_id: str
    reason: Optional[str] = None


@api.get("/admin/coaches")
async def list_coaches(admin: dict = Depends(require_admin)):
    """List all coach accounts with workload counts."""
    coaches = await db.users.find({"role": "coach"}, {"_id": 0}).to_list(200)
    out: list[dict] = []
    for c in coaches:
        pub = _coach_public(c)
        pub["assigned_clients"] = await db.users.count_documents({
            "role": "client",
            "assigned_coach_id": c["id"],
            "status": {"$nin": ["deleted", "deletion_pending"]},
        })
        out.append(pub)
    # Sort admins first, then by name.
    out.sort(key=lambda r: (not r["is_admin"], (r["name"] or "").lower()))
    return {"coaches": out, "count": len(out)}


@api.post("/admin/coaches/invite")
async def invite_coach(body: CoachInviteBody, admin: dict = Depends(require_admin)):
    """Create a coach account with a random one-time password. In production
    this returns a magic-link; for the MVP the temp password is returned so
    Louis can share it manually.

    Constraints:
      - tier must be 'full' or 'assistant'
      - email must be unique
    """
    if body.tier not in ("full", "assistant"):
        raise HTTPException(400, "tier must be 'full' or 'assistant'")
    email = body.email.lower().strip()
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email")
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(400, "A user with this email already exists")

    from server import hash_pw  # local import to avoid circular deps
    import secrets
    temp_password = secrets.token_urlsafe(10)
    now = now_iso()
    coach_id = new_id()
    await db.users.insert_one({
        "id": coach_id,
        "email": email,
        "name": body.name.strip() or email.split("@")[0],
        "phone": body.phone,
        "password_hash": hash_pw(temp_password),
        "role": "coach",
        "coach_tier": body.tier,
        "is_admin": False,
        "status": "active",
        "must_change_password": True,
        "created_at": now,
        "updated_at": now,
        "invited_by": admin["id"],
    })
    await log_audit(actor=admin, action="coach.invite", target_user_id=coach_id,
                    after={"email": email, "tier": body.tier, "name": body.name})
    return {"coach_id": coach_id, "email": email, "temp_password": temp_password, "tier": body.tier}


@api.patch("/admin/coaches/{coach_id}")
async def patch_coach(coach_id: str, body: CoachPatchBody, admin: dict = Depends(require_admin)):
    c = await db.users.find_one({"id": coach_id, "role": "coach"}, {"_id": 0})
    if not c:
        raise HTTPException(404, "Coach not found")
    if bool(c.get("is_admin")) and body.is_admin is False:
        # Guard: never demote the last admin.
        admin_count = await db.users.count_documents({"role": "coach", "is_admin": True})
        if admin_count <= 1:
            raise HTTPException(400, "Cannot demote the last admin. Promote another coach first.")
    before = _coach_public(c)
    updates: dict[str, Any] = {}
    if body.tier is not None:
        if body.tier not in COACH_TIERS:
            raise HTTPException(400, f"tier must be one of {COACH_TIERS}")
        updates["coach_tier"] = body.tier
        if body.tier == "admin":
            updates["is_admin"] = True
    if body.name is not None: updates["name"] = body.name.strip()
    if body.phone is not None: updates["phone"] = body.phone
    if body.is_admin is not None: updates["is_admin"] = bool(body.is_admin)
    updates["updated_at"] = now_iso()
    await db.users.update_one({"id": coach_id}, {"$set": updates})
    c2 = await db.users.find_one({"id": coach_id}, {"_id": 0})
    await log_audit(actor=admin, action="coach.patch", target_user_id=coach_id,
                    before=before, after=_coach_public(c2))
    return _coach_public(c2)


@api.post("/admin/coaches/{coach_id}/activate")
async def activate_coach(coach_id: str, admin: dict = Depends(require_admin)):
    c = await db.users.find_one({"id": coach_id, "role": "coach"}, {"_id": 0})
    if not c: raise HTTPException(404, "Coach not found")
    await db.users.update_one({"id": coach_id}, {"$set": {"status": "active", "updated_at": now_iso()}})
    await log_audit(actor=admin, action="coach.activate", target_user_id=coach_id)
    return {"ok": True}


@api.post("/admin/coaches/{coach_id}/deactivate")
async def deactivate_coach(coach_id: str, admin: dict = Depends(require_admin)):
    c = await db.users.find_one({"id": coach_id, "role": "coach"}, {"_id": 0})
    if not c: raise HTTPException(404, "Coach not found")
    if bool(c.get("is_admin")):
        raise HTTPException(400, "Cannot deactivate an admin account. Demote first.")
    await db.users.update_one({"id": coach_id}, {"$set": {"status": "paused", "updated_at": now_iso()}})
    await log_audit(actor=admin, action="coach.deactivate", target_user_id=coach_id)
    return {"ok": True}


@api.post("/admin/clients/{client_id}/assign-coach")
async def assign_client_coach(client_id: str, body: AssignCoachBody, admin: dict = Depends(require_admin)):
    """Assign or reassign a client to a coach. Records the change in the
    audit log and updates the client's user doc."""
    coach = await db.users.find_one({"id": body.coach_id, "role": "coach"}, {"_id": 0})
    if not coach:
        raise HTTPException(404, "Coach not found")
    if coach.get("status") not in (None, "active"):
        raise HTTPException(400, "Coach is not active")
    client = await db.users.find_one({"id": client_id, "role": "client"}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")
    before = {"assigned_coach_id": client.get("assigned_coach_id")}
    await db.users.update_one(
        {"id": client_id},
        {"$set": {
            "assigned_coach_id": coach["id"],
            "assigned_coach_name": coach.get("name"),
            "assigned_at": now_iso(),
            "assigned_by": admin["id"],
            "updated_at": now_iso(),
        }},
    )
    await log_audit(
        actor=admin,
        action="client.assign_coach",
        target_user_id=client_id,
        before=before,
        after={"assigned_coach_id": coach["id"], "assigned_coach_name": coach.get("name")},
        reason=body.reason,
    )
    return {"ok": True, "assigned_coach_id": coach["id"], "assigned_coach_name": coach.get("name")}


@api.get("/admin/coaches/{coach_id}/workload")
async def coach_workload(coach_id: str, admin: dict = Depends(require_admin)):
    c = await db.users.find_one({"id": coach_id, "role": "coach"}, {"_id": 0})
    if not c: raise HTTPException(404, "Coach not found")
    assigned = await db.users.count_documents({
        "role": "client", "assigned_coach_id": coach_id,
        "status": {"$nin": ["deleted", "deletion_pending", "archived", "paused"]},
    })
    archived = await db.users.count_documents({
        "role": "client", "assigned_coach_id": coach_id,
        "status": {"$in": ["archived", "paused"]},
    })
    return {
        "coach": _coach_public(c),
        "assigned_active": assigned,
        "assigned_archived": archived,
    }


# Client-facing helper: which coach do I message?
@api.get("/me/coach")
async def my_coach(user: dict = Depends(current_user)):
    """Small helper the client uses to render 'Message <first name>' correctly.
    Falls back to Louis if the client has no explicit assignment."""
    if user.get("role") != "client":
        return {"coach": None}
    coach_id = user.get("assigned_coach_id") or await _default_coach_id()
    if not coach_id:
        return {"coach": None}
    coach = await db.users.find_one({"id": coach_id, "role": "coach"}, {"_id": 0, "password_hash": 0})
    if not coach:
        return {"coach": None}
    return {"coach": {
        "id": coach["id"],
        "name": coach.get("name"),
        "first_name": (coach.get("name") or "").split(" ")[0] or None,
        "email": coach.get("email"),
        "coach_tier": coach.get("coach_tier"),
        "is_admin": bool(coach.get("is_admin")),
    }}
