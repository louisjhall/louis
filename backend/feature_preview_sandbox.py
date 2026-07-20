"""
feature_preview_sandbox — Persistent "New Client Preview" sandbox.

Provides a single, permanent preview client that Louis can reset over and over
to test the new-client journey. Unlike feature_preview.py's `new-client`
throwaway route (which mints a fresh purge-in-24h user every time), this
sandbox is a stable identity:

    email = "preview@crewfit.test"
    name  = "New Client Preview"
    is_preview_sandbox = True

Endpoints:
    POST /api/coach/preview/persistent
        Idempotent — creates the sandbox user if missing, returns an
        impersonation token (short-lived, 2h).

    POST /api/coach/preview/reset
        Wipes all onboarding + roster + workout + habit + nutrition + message
        data associated with the sandbox user so the very next preview run
        starts as a brand-new client. Keeps the user row + preview id itself.

    GET  /api/coach/preview/sandbox-info
        Returns the sandbox user (id, name, email, last_reset_at, current step)
        or {sandbox: null} if not seeded yet.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api, db, current_user, hash_pw, now_iso, new_id,
    JWT_SECRET, JWT_ALGO, logger,
)
from feature_admin_lifecycle import log_audit

SANDBOX_EMAIL = "preview@crewfit.test"
SANDBOX_NAME  = "New Client Preview"
SANDBOX_TTL_HOURS = 2

# Collections we scrub on every reset. Kept explicit so we never accidentally
# nuke a real coach's data if the sandbox user id ever leaked.
RESET_COLLECTIONS = [
    "rosters", "workouts", "workout_sets", "workout_exercise_swaps",
    "habits", "habit_logs", "habit_reviews", "habit_starter_recommendations",
    "nutrition_logs", "nutrition_targets", "nutrition_favourites",
    "nutrition_insights", "nutrition_travel_cache", "nutrition_checkin_answers",
    "checkins", "messages", "message_drafts", "coach_alerts",
    "day_overrides", "day_change_log", "standby_days", "sickness_days",
    "schedule_events", "events", "coaching_dna", "assessments",
    "programmes", "personal_activities", "personal_records",
    "gen_jobs", "roster_jobs", "roster_confirmations",
    "reassessment_prompts", "notification_events", "notification_settings",
    "push_tokens", "coaching_dna_answers",
]


async def _require_admin_or_coach(user: dict = Depends(current_user)) -> dict:
    if not user:
        raise HTTPException(401, "Not authenticated")
    if user.get("role") == "admin" or user.get("role") == "coach" or bool(user.get("is_admin")):
        return user
    raise HTTPException(403, "Admin/coach required")


async def _get_or_create_sandbox(actor: dict) -> dict:
    existing = await db.users.find_one({"email": SANDBOX_EMAIL}, {"_id": 0, "password_hash": 0})
    if existing:
        return existing
    now = now_iso()
    uid = new_id()
    await db.users.insert_one({
        "id": uid, "email": SANDBOX_EMAIL, "name": SANDBOX_NAME,
        "role": "client", "password_hash": hash_pw(str(uuid.uuid4())),  # unusable password
        "created_at": now,
        "onboarded": False,
        "coach_id": actor["id"],
        "assigned_coach_id": actor["id"],
        "assigned_coach_name": actor.get("name") or "Louis Hall",
        "age_confirmed": True, "age_confirmed_at": now,
        "profile": {},
        "is_preview_sandbox": True,
        "client_type": "preview_sandbox",
        "status": "preview_sandbox",
        "sandbox_created_at": now,
    })
    logger.info("preview-sandbox: seeded persistent preview client id=%s", uid)
    fresh = await db.users.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
    await log_audit(
        actor=actor, action="preview.sandbox_created",
        target_user_id=uid,
        after={"email": SANDBOX_EMAIL, "name": SANDBOX_NAME},
    )
    return fresh


@api.get("/coach/preview/sandbox-info")
async def sandbox_info(actor: dict = Depends(_require_admin_or_coach)):
    u = await db.users.find_one({"email": SANDBOX_EMAIL}, {"_id": 0, "password_hash": 0})
    if not u:
        return {"sandbox": None}
    # Compute a lightweight "current step" for the dashboard preview card.
    step = "welcome"
    if u.get("onboarded"):
        step = "home"
    elif await db.assessments.find_one({"user_id": u["id"]}):
        step = "coaching_dna_in_progress"
    elif u.get("profile", {}).get("job_title"):
        step = "profile_setup_done"
    workouts = await db.workouts.count_documents({"user_id": u["id"]})
    roster = await db.rosters.find_one({"user_id": u["id"]}, {"_id": 0, "raw_response": 0})
    return {
        "sandbox": {
            "id": u["id"], "email": u["email"], "name": u["name"],
            "onboarded": bool(u.get("onboarded")),
            "current_step": step,
            "workouts_count": workouts,
            "has_roster": bool(roster),
            "last_reset_at": u.get("last_reset_at"),
            "sandbox_created_at": u.get("sandbox_created_at"),
        }
    }


@api.post("/coach/preview/persistent")
async def preview_persistent(actor: dict = Depends(_require_admin_or_coach)):
    """Idempotently returns an impersonation token for the persistent sandbox."""
    sandbox = await _get_or_create_sandbox(actor)
    payload = {
        "sub": sandbox["id"],
        "role": "client",
        "preview": True,
        "preview_by": actor["id"],
        "preview_by_email": actor.get("email"),
        "preview_kind": "sandbox",
        "exp": datetime.now(timezone.utc) + timedelta(hours=SANDBOX_TTL_HOURS),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    await db.preview_audit.insert_one({
        "id": str(uuid.uuid4()),
        "coach_id": actor["id"],
        "target_id": sandbox["id"],
        "target_email": sandbox["email"],
        "action": "sandbox_impersonate",
        "ts": now_iso(),
    })
    await log_audit(
        actor=actor, action="preview.sandbox_impersonate",
        target_user_id=sandbox["id"],
        extra={"kind": "sandbox"},
    )
    return {
        "token": token,
        "target": {"id": sandbox["id"], "name": sandbox["name"], "email": sandbox["email"], "role": "client"},
        "expires_hours": SANDBOX_TTL_HOURS,
        "kind": "sandbox",
    }


class ResetBody(BaseModel):
    confirm: bool = True


@api.post("/coach/preview/reset")
async def preview_reset(body: ResetBody = ResetBody(), actor: dict = Depends(_require_admin_or_coach)):
    """Wipe all data on the sandbox user so it restarts as a brand-new client.
    The user row itself is preserved (id kept stable, profile blanked, onboarded
    set to False)."""
    u = await db.users.find_one({"email": SANDBOX_EMAIL})
    if not u:
        # If missing, just create a fresh one — same net effect.
        u = await _get_or_create_sandbox(actor)
    uid = u["id"]

    # Extra safety — never accept a non-sandbox account here.
    if u.get("email") != SANDBOX_EMAIL or not u.get("is_preview_sandbox"):
        raise HTTPException(400, "Refusing to reset a non-sandbox user")

    # Wipe every collection where user_id == uid.
    scrubbed: dict[str, int] = {}
    for coll in RESET_COLLECTIONS:
        try:
            r = await db[coll].delete_many({"user_id": uid})
            if r.deleted_count:
                scrubbed[coll] = r.deleted_count
        except Exception:
            logger.exception("preview-reset: failed to scrub %s", coll)

    # Reset the user row itself to brand-new state.
    now = now_iso()
    await db.users.update_one({"id": uid}, {"$set": {
        "onboarded": False,
        "profile": {},
        "coaching_dna": None,
        "beta_welcome_seen": False,
        "welcome_seen": False,
        "last_reset_at": now,
        "updated_at": now,
    }})

    await log_audit(
        actor=actor, action="preview.sandbox_reset",
        target_user_id=uid,
        extra={"scrubbed_collections": scrubbed},
    )
    logger.info("preview-sandbox reset by %s: scrubbed=%s", actor.get("email"), scrubbed)
    return {"ok": True, "sandbox_id": uid, "scrubbed": scrubbed, "last_reset_at": now}
