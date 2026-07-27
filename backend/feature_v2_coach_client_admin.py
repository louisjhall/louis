"""
V2 Coach – Client Admin endpoints (delete, archive).

Route: DELETE /api/v2/coach/clients/{client_id}?confirm_email=...

Nukes a client and every reference to them across V1 and V2 collections.
Safety-gated by requiring the caller to pass the client's current email as
`confirm_email` — a typo won't wipe the wrong client.
"""

from typing import Optional
from fastapi import Depends, HTTPException, Query

from server import api, db, require_role, now_iso, logger


# Collections that reference the client by `client_id`
_CLIENT_ID_COLLECTIONS = [
    "schedule_days", "workout_assignments", "workout_implementations",
    "programmes_v2", "programme_phases_v2", "training_objectives",
    "objective_exposures", "plan_drafts", "plan_versions", "change_sets",
    "decision_records", "exceptions", "restrictions", "equipment_contexts",
    "readiness_states", "roster_days", "coach_directives",
    "workouts", "workout_sessions", "workout_ratings", "workout_swaps",
    "user_events", "nightly_checks", "metrics_events",
    "rescheduling_history", "onboarding_progress",
    "coach_tasks", "coach_change_log", "coach_alerts", "goals_v2",
    "change_log", "programme_timeline",
]

# Collections that reference the client by `user_id`
_USER_ID_COLLECTIONS = [
    "rosters", "events", "goals", "user_preferences",
    "notifications", "push_tokens", "sessions", "auth_sessions",
    "refresh_tokens", "password_resets", "auth_events",
    "user_profiles", "coach_client_assignments",
    "roster_documents", "roster_uploads", "roster_parses",
    "onboarding_steps", "welcome_video_progress",
    "chat_messages", "chat_threads",
    "programmes", "daily_briefings", "scheduled_messages",
    "habits", "coaching_dna", "roster_jobs", "assessments",
    "messages", "weekly_reviews",
]

# Field keys to sweep every remaining collection for stragglers.
_SWEEP_KEYS = ("client_id", "user_id", "owner_id", "author_id")


@api.delete("/v2/coach/clients/{client_id}")
async def delete_client(
    client_id: str,
    confirm_email: str = Query(..., description="Must match the client's current email"),
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Permanently delete a client and every associated record.

    Guardrails:
      - target user MUST be role=client (never delete a coach)
      - target user MUST NOT be the caller themselves
      - `confirm_email` MUST match the client's stored email (case-insensitive)
      - deletion is total and irreversible
    """
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Client not found")
    if user.get("role") != "client":
        raise HTTPException(409, "Only clients can be deleted via this endpoint")
    if user["id"] == coach["id"]:
        raise HTTPException(409, "You cannot delete your own account")
    stored_email = (user.get("email") or "").strip().lower()
    provided = (confirm_email or "").strip().lower()
    if not stored_email or stored_email != provided:
        raise HTTPException(
            400,
            "confirm_email does not match the client's current email — refusing to delete",
        )

    deleted_total = 0
    per_collection: dict[str, int] = {}

    # Delete by client_id
    for coll_name in _CLIENT_ID_COLLECTIONS:
        try:
            r = await db[coll_name].delete_many({"client_id": client_id})
            if r.deleted_count:
                per_collection[coll_name] = r.deleted_count
                deleted_total += r.deleted_count
        except Exception as e:
            logger.warning(f"delete_client: {coll_name} by client_id failed: {e}")

    # Delete by user_id
    for coll_name in _USER_ID_COLLECTIONS:
        try:
            r = await db[coll_name].delete_many({"user_id": client_id})
            if r.deleted_count:
                per_collection[f"{coll_name}(user_id)"] = r.deleted_count
                deleted_total += r.deleted_count
        except Exception as e:
            logger.warning(f"delete_client: {coll_name} by user_id failed: {e}")

    # Delete by email (auth-side tables)
    for coll_name in ("auth_events", "password_resets", "email_verifications", "invitations"):
        try:
            r = await db[coll_name].delete_many({"email": stored_email})
            if r.deleted_count:
                per_collection[f"{coll_name}(email)"] = r.deleted_count
                deleted_total += r.deleted_count
        except Exception:
            pass

    # Safety sweep across every remaining collection
    try:
        all_colls = await db.list_collection_names()
    except Exception:
        all_colls = []
    already_touched = set(_CLIENT_ID_COLLECTIONS) | set(_USER_ID_COLLECTIONS) | {"users"}
    for cn in all_colls:
        if cn.startswith("system.") or cn in already_touched:
            continue
        for key in _SWEEP_KEYS:
            try:
                r = await db[cn].delete_many({key: client_id})
                if r.deleted_count:
                    per_collection[f"sweep::{cn}.{key}"] = r.deleted_count
                    deleted_total += r.deleted_count
            except Exception:
                pass
        # Also try by email
        try:
            r = await db[cn].delete_many({"email": stored_email})
            if r.deleted_count:
                per_collection[f"sweep::{cn}.email"] = r.deleted_count
                deleted_total += r.deleted_count
        except Exception:
            pass

    # Finally, the user record itself
    ur = await db.users.delete_many(
        {"$or": [{"id": client_id}, {"email": stored_email}]}
    )
    per_collection["users"] = ur.deleted_count
    deleted_total += ur.deleted_count

    # Audit trail — write a decision record on the COACH's scope (client
    # scope is gone) so this deletion is discoverable in the audit log.
    try:
        await db.decision_records.insert_one({
            "id": f"del-{client_id}-{now_iso()}",
            "timestamp": now_iso(),
            "actor": "coach",
            "actor_id": coach["id"],
            "layer": "ORCHESTRATION",
            "scope_kind": "user_deletion",
            "scope_id": client_id,
            "client_id": None,   # client is gone
            "outcome": "APPLIED",
            "reason": (
                f"Coach {coach.get('email')} deleted client "
                f"{stored_email} ({client_id}). "
                f"{deleted_total} documents purged across "
                f"{len(per_collection)} collections."
            ),
        })
    except Exception:
        pass

    return {
        "ok": True,
        "client_id": client_id,
        "email": stored_email,
        "deleted_total": deleted_total,
        "per_collection": per_collection,
    }


logger.info("feature_v2_coach_client_admin: DELETE /api/v2/coach/clients/{cid} registered")
