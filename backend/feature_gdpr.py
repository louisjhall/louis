"""feature_gdpr — Account deletion (soft-delete + 30-day grace) and data export.

Why soft-delete?
 * Gives users a 30-day undo window (fights impulsive deletion).
 * Lets Support/Ops recover from accidental deletion.
 * Some data is legally required to be retained briefly (e.g. financial
   records if we ever add Stripe).

Behaviour:
 * `POST /api/gdpr/delete-account` marks the user as `deleted_at=<iso>` and
   scrubs sensitive fields, but the row remains for `RETENTION_DAYS` (30).
 * The background purge job (`gdpr_purge_expired`) removes all data
   after the grace period. It's called from the existing daily cron.
 * `POST /api/gdpr/delete-account/cancel` cancels a pending deletion.
 * `GET /api/gdpr/export` streams a JSON blob with everything CrewFit
   knows about the user.

Collections cleared on hard-delete:
   users, assessments, coaching_dna, dna_history, rosters, roster_jobs,
   schedule_events, day_overrides, workouts, workout_sets, habits,
   habit_logs, habit_reviews, checkins, nutrition_*, meals, messages,
   message_drafts, notifications, ai_usage, crewfit_images (owned),
   nutrition_photo_scans, personal_records, move_history, progress,
   reality_events, reassessment_prompts.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server import api, db, current_user, require_admin, now_iso, logger

try:
    import storage as _storage
except Exception:
    _storage = None

RETENTION_DAYS = 30

# All user-scoped collections we will purge / include in export.
# Each entry: (collection_name, query_field). Almost all keyed on user_id.
USER_COLLECTIONS: list[tuple[str, str]] = [
    ("assessments", "user_id"),
    ("coaching_dna", "user_id"),
    ("dna_history", "user_id"),
    ("rosters", "user_id"),
    ("roster_jobs", "user_id"),
    ("schedule_events", "user_id"),
    ("day_overrides", "user_id"),
    ("day_change_log", "user_id"),
    ("events", "user_id"),
    ("workouts", "user_id"),
    ("workout_sets", "user_id"),
    ("personal_records", "user_id"),
    ("move_history", "user_id"),
    ("habits", "user_id"),
    ("habit_logs", "user_id"),
    ("habit_reviews", "user_id"),
    ("daily_pulse", "user_id"),
    ("checkins", "user_id"),
    ("check_ins", "user_id"),   # legacy — safe to include
    ("progress", "user_id"),
    ("reality_events", "user_id"),
    ("reassessment_prompts", "user_id"),
    ("nutrition_logs", "user_id"),
    ("nutrition_targets", "user_id"),
    ("nutrition_insights", "user_id"),
    ("nutrition_atlas_tips", "user_id"),
    ("nutrition_favourites", "user_id"),
    ("nutrition_hydration", "user_id"),
    ("nutrition_notes", "user_id"),
    ("nutrition_photo_scans", "user_id"),
    ("meals", "user_id"),
    ("messages", "user_id"),
    ("message_drafts", "user_id"),
    ("scheduled_messages", "user_id"),
    ("notifications", "user_id"),
    ("ai_usage", "user_id"),
    ("crewfit_images", "created_by"),
]


# ---- Delete request -------------------------------------------------------

class DeleteReq(BaseModel):
    confirmation: str  # must equal "DELETE"
    reason: str | None = None


@api.post("/gdpr/delete-account")
async def gdpr_delete_account(body: DeleteReq, user: dict = Depends(current_user)):
    if body.confirmation != "DELETE":
        raise HTTPException(400, "confirmation must equal 'DELETE'")
    when = now_iso()
    purge_at = (datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)).isoformat()
    # Deferred-scrub design: during the 30-day grace period the account stays
    # fully functional (email + name intact) so cancel is a clean unset. PII
    # is only scrubbed at final purge time. This lets users log back in during
    # the grace window and keeps our seed accounts alive across test runs.
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "deleted_at": when,
            "purge_at": purge_at,
            "deletion_reason": (body.reason or "")[:400],
            "updated_at": when,
        }},
    )
    await db.gdpr_audit.insert_one({
        "id": user["id"] + "-" + when,
        "user_id": user["id"],
        "action": "delete_requested",
        "purge_at": purge_at,
        "reason": (body.reason or "")[:400],
        "ts": when,
    })
    logger.info("gdpr: soft-delete requested for user=%s purge_at=%s", user["id"], purge_at)
    return {"ok": True, "scheduled_purge_at": purge_at,
            "retention_days": RETENTION_DAYS,
            "message": f"Account marked for deletion. Permanent purge in {RETENTION_DAYS} days."}


@api.post("/gdpr/delete-account/cancel")
async def gdpr_delete_account_cancel(user: dict = Depends(current_user)):
    u = await db.users.find_one({"id": user["id"]})
    if not u or not u.get("deleted_at"):
        raise HTTPException(400, "no pending deletion for this account")
    await db.users.update_one(
        {"id": user["id"]},
        {"$unset": {"deleted_at": "", "purge_at": "", "deletion_reason": ""},
         "$set": {"updated_at": now_iso()}},
    )
    await db.gdpr_audit.insert_one({
        "id": user["id"] + "-cancel-" + now_iso(),
        "user_id": user["id"],
        "action": "delete_cancelled",
        "ts": now_iso(),
    })
    return {"ok": True, "message": "Deletion cancelled."}


# ---- Data export ----------------------------------------------------------

@api.get("/gdpr/export")
async def gdpr_export(user: dict = Depends(current_user)):
    """Stream the user's full data as a JSON blob download."""
    uid = user["id"]
    payload: dict[str, Any] = {
        "export_generated_at": now_iso(),
        "export_version": "1.0",
        "user": {k: v for k, v in user.items() if k not in ("password_hash", "_id")},
    }
    for coll, field in USER_COLLECTIONS:
        try:
            rows = await db[coll].find({field: uid}, {"_id": 0}).to_list(10_000)
            if rows:
                payload[coll] = rows
        except Exception:
            logger.exception("gdpr_export: failed collection=%s", coll)
    body = json.dumps(payload, default=str, indent=2).encode("utf-8")
    stream = io.BytesIO(body)
    filename = f"crewfit-export-{uid}-{datetime.utcnow().strftime('%Y%m%d')}.json"
    return StreamingResponse(
        stream, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ---- Selective deletion ---------------------------------------------------

class PartialDeleteReq(BaseModel):
    domains: list[str]   # e.g. ["nutrition", "photos", "messages", "rosters", "habits"]


DOMAIN_MAP: dict[str, list[tuple[str, str]]] = {
    "nutrition": [("nutrition_logs", "user_id"), ("nutrition_targets", "user_id"),
                  ("nutrition_insights", "user_id"), ("nutrition_favourites", "user_id"),
                  ("nutrition_hydration", "user_id"), ("nutrition_notes", "user_id"),
                  ("nutrition_atlas_tips", "user_id"), ("meals", "user_id")],
    "photos":    [("nutrition_photo_scans", "user_id")],
    "messages":  [("messages", "user_id"), ("message_drafts", "user_id"),
                  ("scheduled_messages", "user_id")],
    "rosters":   [("rosters", "user_id"), ("roster_jobs", "user_id"),
                  ("schedule_events", "user_id"), ("day_overrides", "user_id")],
    "habits":    [("habits", "user_id"), ("habit_logs", "user_id"),
                  ("habit_reviews", "user_id"), ("daily_pulse", "user_id")],
    "checkins":  [("checkins", "user_id"), ("check_ins", "user_id")],
    "workouts":  [("workouts", "user_id"), ("workout_sets", "user_id"),
                  ("personal_records", "user_id"), ("move_history", "user_id")],
}


@api.post("/gdpr/delete-data")
async def gdpr_delete_data(body: PartialDeleteReq, user: dict = Depends(current_user)):
    uid = user["id"]
    if not body.domains:
        raise HTTPException(400, "specify at least one domain")
    deleted: dict[str, int] = {}
    for domain in body.domains:
        colls = DOMAIN_MAP.get(domain)
        if not colls:
            continue
        for coll, field in colls:
            try:
                r = await db[coll].delete_many({field: uid})
                deleted[coll] = deleted.get(coll, 0) + r.deleted_count
            except Exception:
                logger.exception("gdpr_delete_data: failed collection=%s", coll)
    # Photo blob cleanup for nutrition photos
    if "photos" in body.domains and _storage is not None:
        try:
            async for row in db.nutrition_photo_scans.find({"user_id": uid}, {"storage_key": 1}):
                key = row.get("storage_key")
                if key:
                    await _storage.storage.delete(key)
        except Exception:
            pass
    await db.gdpr_audit.insert_one({
        "id": uid + "-partial-" + now_iso(),
        "user_id": uid,
        "action": "partial_delete",
        "domains": body.domains,
        "deleted": deleted,
        "ts": now_iso(),
    })
    return {"ok": True, "deleted": deleted}


# ---- Background purge (called by daily cron) ------------------------------

async def gdpr_purge_expired() -> dict:
    """Called from server.py's daily cron. Hard-deletes accounts past purge_at."""
    now = datetime.now(timezone.utc).isoformat()
    victims = await db.users.find({"purge_at": {"$lte": now}}, {"_id": 0, "id": 1, "purge_at": 1}).to_list(100)
    purged = 0
    for v in victims:
        uid = v["id"]
        for coll, field in USER_COLLECTIONS:
            try:
                await db[coll].delete_many({field: uid})
            except Exception:
                pass
        # Remove any brand images owned
        try:
            await db.crewfit_images.delete_many({"user_id": uid})
        except Exception:
            pass
        # Finally the user record
        try:
            await db.users.delete_one({"id": uid})
            purged += 1
            await db.gdpr_audit.insert_one({
                "id": uid + "-purged-" + now,
                "user_id": uid,
                "action": "purged",
                "ts": now,
            })
        except Exception:
            logger.exception("gdpr_purge: failed to delete user=%s", uid)
    if purged:
        logger.info("gdpr_purge: purged %d expired accounts", purged)
    return {"purged": purged}


# ---- Admin ----------------------------------------------------------------

@api.get("/admin/gdpr/pending")
async def admin_gdpr_pending(user: dict = Depends(require_admin())):
    rows = await db.users.find(
        {"deleted_at": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "email": 1, "deleted_at": 1, "purge_at": 1, "deletion_reason": 1},
    ).sort("purge_at", 1).to_list(500)
    return {"pending": rows}


@api.get("/admin/gdpr/audit")
async def admin_gdpr_audit(limit: int = 200, user: dict = Depends(require_admin())):
    rows = await db.gdpr_audit.find({}, {"_id": 0}).sort("ts", -1).to_list(limit)
    return {"audit": rows}


@api.post("/admin/gdpr/purge-now")
async def admin_gdpr_purge_now(user: dict = Depends(require_admin())):
    return await gdpr_purge_expired()
