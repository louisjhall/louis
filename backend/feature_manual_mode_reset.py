"""
Phase 1B — Programme reset endpoints.

Two admin endpoints:
  * POST /api/admin/programme-reset/dry-run  → returns exact per-collection
    counts that WOULD be deleted. Zero mutations.
  * POST /api/admin/programme-reset/execute → snapshots affected records to
    `programme_reset_backup_{iso_ts}` collections, then deletes. Requires the
    dry-run token (SHA-256 of the counts) as body param `expected_token` so a
    stale dry-run cannot execute against a changed dataset.

Phase 1C — Full client-data reset (added after programme reset).
  * POST /api/admin/client-reset/dry-run → identifies which USER accounts
    will be deleted and every client-linked record across all collections.
  * POST /api/admin/client-reset/execute → snapshots + deletes.

Both endpoints are coach-only (require_role("coach")). Flight Support and
client-profile collections are NEVER touched.

Reversible: if a mistake happens, the caller can copy documents back from
`programme_reset_backup_{ts}.*` into their source collections.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from typing import Any

from fastapi import Depends, HTTPException

from server import db, api, require_role, logger, now_iso


# Collections we CLEAR completely.
# Rationale: every entry in these collections is programme/schedule/plan
# generation state. None of them hold flight-support, client-profile,
# roster, DNA, or exercise-library data.
_CLEAR_COLLECTIONS = [
    "workouts",                       # V1 + V2 + manual + template — all
    "plan_drafts_v2",
    "plan_live_v2",
    "plan_live_v2_exercise_swaps",
    "plan_live_v2_implementations",
    "programmes_v2",
    "programme_phases_v2",
    "programmes",
    "programme_timeline",
    "gen_jobs",
    "roster_jobs",
    "workout_assignments",
    "workout_implementations",
    "plan_snapshots",
    "plan_shadows",
    "plan_versions",
    "schedule_days",
    "planning_windows",
    "coach_day_overrides",
    "move_history",
    "day_change_log",
    "workout_exercise_swaps",
    "workout_sets",
    "workouts_archive",
]

# Collections we NEVER touch (belt-and-braces documentation).
_PROTECTED_COLLECTIONS = [
    "users", "clients", "auth_sessions", "auth_password_reset",
    "coaching_dna", "dna_history", "dna_profiles", "dna_intake_answers",
    "assessments", "check_ins", "progress", "weekly_reviews",
    "rosters", "roster_stub", "duties", "flight_sectors", "hotels",
    "flight_support_overrides", "flight_support_activity",  # ← Flight Support
    "exercises", "exercises_v2", "exercise_content",
    "exercise_content_images", "exercise_content_log",
    "exercise_videos", "exercise_video_blobs",
    "media_queue", "coach_notes_history", "coach_alerts",
    "coach_tasks", "coach_scripts", "messages", "message_drafts",
    "notifications", "app_config", "app_config_audit", "ai_usage",
]


def _counts_token(counts: dict[str, int]) -> str:
    """Deterministic token computed over the dry-run counts. The execute
    endpoint requires this exact token, so a stale dry-run against a
    later dataset cannot execute unnoticed."""
    payload = json.dumps(counts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


async def _gather_counts() -> dict[str, int]:
    """Read-only. Returns a per-collection count for the reset scope."""
    counts: dict[str, int] = {}
    for name in _CLEAR_COLLECTIONS:
        try:
            counts[name] = await db.get_collection(name).count_documents({})
        except Exception as e:
            logger.warning("programme-reset dry-run: %s count failed: %s", name, e)
            counts[name] = -1
    return counts


@api.post("/admin/programme-reset/dry-run")
async def programme_reset_dry_run(coach: dict = Depends(require_role("coach"))) -> dict:
    """Read-only. Returns exact counts + a token to pass into execute."""
    counts = await _gather_counts()
    token = _counts_token(counts)

    # Also verify Flight Support tables are populated (so caller can see
    # they are being preserved). These are NOT touched by any delete.
    fs = {}
    for name in ("flight_support_overrides", "flight_support_activity"):
        try:
            fs[name] = await db.get_collection(name).count_documents({})
        except Exception:
            fs[name] = -1

    # Reassurance-only counts — NOT part of the delete set. Coach can
    # confirm client/roster/flight-sector data still exists after execute.
    reassure = {}
    for name in ("users", "clients", "rosters", "duties", "flight_sectors",
                 "coaching_dna", "assessments", "check_ins",
                 "exercises_v2", "exercise_content"):
        try:
            reassure[name] = await db.get_collection(name).count_documents({})
        except Exception:
            reassure[name] = -1

    return {
        "ok": True,
        "mode": "dry_run",
        "generated_at": now_iso(),
        "counts_to_clear": counts,
        "total_documents_to_clear": sum(v for v in counts.values() if v >= 0),
        "protected_collections": _PROTECTED_COLLECTIONS,
        "flight_support_preview": fs,
        "reassurance_counts_not_deleted": reassure,
        "expected_token": token,
        "next_step": (
            "Review counts above. If correct, call POST "
            "/api/admin/programme-reset/execute with body "
            "{ 'expected_token': '<value above>', 'confirm': 'DELETE ALL PROGRAMMES' }"
        ),
    }


@api.post("/admin/programme-reset/execute")
async def programme_reset_execute(
    body: dict,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Snapshot each affected collection into
    `programme_reset_backup_{ts}_{name}` then delete_many({})."""
    if body.get("confirm") != "DELETE ALL PROGRAMMES":
        raise HTTPException(
            400,
            "Missing confirmation. Send body { expected_token, confirm: 'DELETE ALL PROGRAMMES' }",
        )
    expected_token = body.get("expected_token") or ""
    counts_now = await _gather_counts()
    actual_token = _counts_token(counts_now)
    if expected_token != actual_token:
        raise HTTPException(
            409,
            {
                "code": "stale_token",
                "message": "Data has changed since dry-run. Run dry-run again and re-submit with the fresh token.",
                "expected_token_sent": expected_token,
                "actual_token_now": actual_token,
                "counts_now": counts_now,
            },
        )

    ts = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    per_collection: list[dict] = []
    total_backed_up = 0
    total_deleted = 0

    for name in _CLEAR_COLLECTIONS:
        try:
            src = db.get_collection(name)
            before = counts_now.get(name, 0)
            if before <= 0:
                per_collection.append({
                    "collection": name, "backed_up": 0, "deleted": 0, "note": "empty",
                })
                continue

            # 1. Snapshot everything into a backup collection.
            backup_name = f"programme_reset_backup_{ts}_{name}"
            docs = []
            async for d in src.find({}):
                docs.append(d)
            if docs:
                await db.get_collection(backup_name).insert_many(docs)

            # 2. Delete_many.
            res = await src.delete_many({})
            per_collection.append({
                "collection": name,
                "backed_up_to": backup_name,
                "backed_up": len(docs),
                "deleted": res.deleted_count,
            })
            total_backed_up += len(docs)
            total_deleted += res.deleted_count
        except Exception as e:
            logger.exception("programme-reset execute failed on %s", name)
            per_collection.append({
                "collection": name, "error": str(e), "aborted": True,
            })

    # Audit
    try:
        await db.get_collection("programme_reset_audit").insert_one({
            "id": f"reset_{ts}",
            "executed_at": now_iso(),
            "coach_id": coach.get("id"),
            "coach_email": coach.get("email"),
            "token": expected_token,
            "total_backed_up": total_backed_up,
            "total_deleted": total_deleted,
            "per_collection": per_collection,
        })
    except Exception as e:
        logger.warning("programme_reset_audit write failed: %s", e)

    return {
        "ok": True,
        "mode": "execute",
        "executed_at": now_iso(),
        "backup_prefix": f"programme_reset_backup_{ts}_",
        "total_backed_up": total_backed_up,
        "total_deleted": total_deleted,
        "per_collection": per_collection,
        "rollback_hint": (
            "To rollback: for each entry in per_collection, copy documents "
            "from backup_prefix + collection back into the original collection."
        ),
    }

# ============================================================================
# Phase 1C — Full Client-Data Reset
# ============================================================================
#
# Deletes every user with role="client" (except those the operator has
# explicitly protected via env or default patterns), and cascades to remove
# every record in any collection that references those user IDs.
#
# NEVER touched: exercises_v2, exercise_content, exercise_content_images,
# exercise_videos, exercise_video_blobs, exercises, media_queue, hotels,
# app_config, ai_usage, auth_password_reset, and coach/admin user rows.

# Default protected email patterns (case-insensitive substring match).
# These typically catch review accounts required for App Store / Play Store.
_DEFAULT_PROTECTED_EMAIL_PATTERNS = [
    "reviewer", "review-", "apple-review", "google-review",
    "appstore", "playstore", "testflight", "app-review",
]

# Extra protected emails supplied via env (comma-separated).
def _extra_protected_emails() -> list[str]:
    raw = os.getenv("PROTECTED_CLIENT_EMAILS", "").strip()
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def _email_looks_protected(email: str | None) -> bool:
    if not email:
        return False
    e = email.lower()
    if e in _extra_protected_emails():
        return True
    return any(p in e for p in _DEFAULT_PROTECTED_EMAIL_PATTERNS)


# Map of collection name -> list of fields that reference a user_id/client_id.
# Any doc where ANY of these fields ∈ target_user_ids is client-linked.
# Determined by reading a sample doc from each collection (2026-08-03).
_CLIENT_LINKED_COLLECTIONS: dict[str, list[str]] = {
    # Programme data
    "workouts":                       ["user_id"],
    "plan_drafts_v2":                 ["user_id", "client_id"],
    "plan_live_v2":                   ["user_id", "client_id"],
    "plan_live_v2_exercise_swaps":    ["user_id", "client_id"],
    "plan_live_v2_implementations":   ["user_id", "client_id"],
    "programmes_v2":                  ["user_id", "client_id"],
    "programme_phases_v2":            ["user_id", "client_id"],
    "programmes":                     ["user_id"],
    "programme_timeline":             ["user_id"],
    "gen_jobs":                       ["user_id"],
    "roster_jobs":                    ["user_id"],
    "workout_assignments":            ["user_id", "client_id"],
    "workout_implementations":        ["user_id", "client_id"],
    "plan_snapshots":                 ["user_id", "client_id"],
    "plan_shadows":                   ["user_id", "client_id"],
    "plan_versions":                  ["user_id", "client_id"],
    "schedule_days":                  ["user_id", "client_id"],
    "planning_windows":               ["user_id", "client_id"],
    "coach_day_overrides":            ["client_id", "user_id"],
    "move_history":                   ["user_id"],
    "day_change_log":                 ["user_id"],
    "workout_exercise_swaps":         ["user_id"],
    "workout_sets":                   ["user_id"],
    "workouts_archive":               ["user_id"],
    # Roster / duties / flight support (all client-linked, not shared refs)
    "rosters":                        ["user_id"],
    "roster_stub":                    ["user_id"],
    "duties":                         ["user_id"],
    "flight_sectors":                 ["user_id"],
    "flight_support_overrides":       ["user_id", "client_id"],
    "flight_support_activity":        ["user_id", "client_id"],
    # DNA / assessments / progress
    "coaching_dna":                   ["user_id"],
    "dna_history":                    ["user_id"],
    "dna_profiles":                   ["user_id"],
    "dna_intake_answers":             ["user_id"],
    "assessments":                    ["user_id"],
    "check_ins":                      ["user_id"],
    "progress":                       ["user_id"],
    "weekly_reviews":                 ["user_id"],
    "goals":                          ["user_id"],
    # Coach tooling (only rows linked to a client user)
    "coach_notes_history":            ["user_id", "client_id"],
    "coach_alerts":                   ["client_id"],
    "coach_tasks":                    ["user_id", "client_id"],
    "coach_scripts":                  ["client_id"],
    "message_drafts":                 ["client_id"],
    "notifications":                  ["user_id"],
}

# Messages need special handling: rows where EITHER from_user_id OR to_user_id
# is a target client are client-linked. Handled separately below.
_MESSAGES_COLLECTION = "messages"
_MESSAGES_FIELDS = ["from_user_id", "to_user_id"]

# Preserved (never queried by delete_many): exercise library, media, hotels,
# app config, auth infra, coach accounts.
_PRESERVED_FOR_CLIENT_RESET = [
    "exercises", "exercises_v2", "exercise_content",
    "exercise_content_images", "exercise_content_log",
    "exercise_videos", "exercise_video_blobs",
    "media_queue", "hotels", "app_config", "app_config_audit",
    "ai_usage", "auth_password_reset",
]


async def _identify_users() -> dict:
    """Return {protected: [...], targets: [...]} of user documents."""
    protected: list[dict] = []
    targets: list[dict] = []
    async for u in db.users.find({}, {"_id": 0, "id": 1, "email": 1, "role": 1}):
        role = (u.get("role") or "").lower()
        email = u.get("email")
        # 1. Any coach/admin/super_admin role is protected.
        if role in ("coach", "admin", "super_admin", "superadmin"):
            protected.append(u)
            continue
        # 2. Any user whose email matches a review pattern is protected.
        if _email_looks_protected(email):
            protected.append(u)
            continue
        # 3. Anyone else (typically role=client) is a target for deletion.
        if role == "client" or role == "":
            targets.append(u)
        else:
            # Unknown role — err on the side of preservation.
            protected.append({**u, "note": f"unknown role '{role}' preserved"})
    return {"protected": protected, "targets": targets}


async def _count_client_linked(target_ids: list[str]) -> dict:
    """Count docs in every client-linked collection whose link fields
    reference any of target_ids. Read-only."""
    counts: dict[str, int] = {}
    if not target_ids:
        for c in _CLIENT_LINKED_COLLECTIONS:
            counts[c] = 0
        counts[_MESSAGES_COLLECTION] = 0
        return counts

    for c, fields in _CLIENT_LINKED_COLLECTIONS.items():
        try:
            or_clauses = [{f: {"$in": target_ids}} for f in fields]
            n = await db.get_collection(c).count_documents({"$or": or_clauses})
            counts[c] = n
        except Exception as e:
            logger.warning("client-reset dry-run: %s count failed: %s", c, e)
            counts[c] = -1

    # Messages — either endpoint of the conversation is a target.
    try:
        or_clauses = [{f: {"$in": target_ids}} for f in _MESSAGES_FIELDS]
        counts[_MESSAGES_COLLECTION] = await db.messages.count_documents(
            {"$or": or_clauses}
        )
    except Exception:
        counts[_MESSAGES_COLLECTION] = -1
    return counts


def _client_token(payload: dict) -> str:
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@api.post("/admin/client-reset/dry-run")
async def client_reset_dry_run(coach: dict = Depends(require_role("coach"))) -> dict:
    """Read-only. Returns which users would be deleted, per-collection
    client-linked counts, and preserved-collection counts."""
    ids = await _identify_users()
    protected = ids["protected"]
    targets = ids["targets"]
    target_ids = [u["id"] for u in targets if u.get("id")]

    counts = await _count_client_linked(target_ids)

    # Preserved-collection counts (should not change after execute).
    preserved: dict[str, int] = {}
    for name in _PRESERVED_FOR_CLIENT_RESET:
        try:
            preserved[name] = await db.get_collection(name).count_documents({})
        except Exception:
            preserved[name] = -1

    # Coach/admin protected user rows are also counted.
    preserved["users_protected"] = len(protected)

    total_linked_docs = sum(v for v in counts.values() if v >= 0)
    total_users_to_delete = len(target_ids)

    # Token binds targets + counts so a stale dry-run cannot execute against
    # a changed dataset (e.g. new client signed up in between).
    token_payload = {
        "target_ids": sorted(target_ids),
        "counts": counts,
        "protected_ids": sorted([u["id"] for u in protected if u.get("id")]),
    }
    token = _client_token(token_payload)

    return {
        "ok": True,
        "mode": "client_reset_dry_run",
        "generated_at": now_iso(),
        "protected_accounts": [
            {"id": u.get("id"), "email": u.get("email"), "role": u.get("role"),
             "note": u.get("note")}
            for u in protected
        ],
        "client_accounts_to_delete": [
            {"id": u.get("id"), "email": u.get("email"), "role": u.get("role")}
            for u in targets
        ],
        "total_users_to_delete": total_users_to_delete,
        "client_linked_counts_by_collection": counts,
        "total_client_linked_docs": total_linked_docs,
        "preserved_counts_will_not_change": preserved,
        "preserved_collections": _PRESERVED_FOR_CLIENT_RESET,
        "backup_prefix_pattern": (
            "client_reset_backup_{iso_utc_ts}_{collection_name}"
        ),
        "expected_token": token,
        "next_step": (
            "Review carefully. If correct, call POST "
            "/api/admin/client-reset/execute with body { expected_token, "
            "confirm: 'DELETE ALL CLIENT DATA' }"
        ),
    }


@api.post("/admin/client-reset/execute")
async def client_reset_execute(
    body: dict,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Snapshot then delete every client-linked record + the client user
    accounts themselves. Preserved collections are never touched."""
    if body.get("confirm") != "DELETE ALL CLIENT DATA":
        raise HTTPException(
            400,
            "Missing confirmation. Send body { expected_token, confirm: 'DELETE ALL CLIENT DATA' }",
        )
    expected_token = body.get("expected_token") or ""

    # Re-compute token now — must match what was shown at dry-run.
    ids = await _identify_users()
    protected = ids["protected"]
    targets = ids["targets"]
    target_ids = [u["id"] for u in targets if u.get("id")]
    counts_now = await _count_client_linked(target_ids)
    token_payload_now = {
        "target_ids": sorted(target_ids),
        "counts": counts_now,
        "protected_ids": sorted([u["id"] for u in protected if u.get("id")]),
    }
    actual_token = _client_token(token_payload_now)
    if expected_token != actual_token:
        raise HTTPException(
            409,
            {
                "code": "stale_token",
                "message": "Users or counts changed since dry-run. Re-run dry-run and resubmit.",
                "expected_token_sent": expected_token,
                "actual_token_now": actual_token,
                "target_ids_now": target_ids,
                "counts_now": counts_now,
            },
        )

    ts = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    per_collection: list[dict] = []
    total_backed_up = 0
    total_deleted = 0

    async def _snapshot_and_delete(col_name: str, filter_q: dict) -> tuple[int, int, str]:
        src = db.get_collection(col_name)
        docs: list[dict] = []
        async for d in src.find(filter_q):
            docs.append(d)
        backup_name = f"client_reset_backup_{ts}_{col_name}"
        if docs:
            await db.get_collection(backup_name).insert_many(docs)
        res = await src.delete_many(filter_q)
        return (len(docs), res.deleted_count, backup_name)

    if not target_ids:
        return {
            "ok": True,
            "mode": "client_reset_execute",
            "executed_at": now_iso(),
            "note": "No client users to delete — nothing changed.",
            "protected_accounts": protected,
        }

    # 1. Delete client-linked records across all collections.
    for c, fields in _CLIENT_LINKED_COLLECTIONS.items():
        if counts_now.get(c, 0) == 0:
            per_collection.append({"collection": c, "backed_up": 0, "deleted": 0, "note": "empty"})
            continue
        try:
            filter_q = {"$or": [{f: {"$in": target_ids}} for f in fields]}
            b, d, bn = await _snapshot_and_delete(c, filter_q)
            per_collection.append({"collection": c, "backed_up_to": bn, "backed_up": b, "deleted": d})
            total_backed_up += b
            total_deleted += d
        except Exception as e:
            logger.exception("client-reset execute failed on %s", c)
            per_collection.append({"collection": c, "error": str(e), "aborted": True})

    # 2. Messages (either endpoint is a target).
    try:
        filter_q = {"$or": [{f: {"$in": target_ids}} for f in _MESSAGES_FIELDS]}
        b, d, bn = await _snapshot_and_delete(_MESSAGES_COLLECTION, filter_q)
        per_collection.append({"collection": _MESSAGES_COLLECTION, "backed_up_to": bn, "backed_up": b, "deleted": d})
        total_backed_up += b; total_deleted += d
    except Exception as e:
        per_collection.append({"collection": _MESSAGES_COLLECTION, "error": str(e), "aborted": True})

    # 3. Finally, delete the client user rows themselves (also snapshotted).
    try:
        filter_q = {"id": {"$in": target_ids}}
        b, d, bn = await _snapshot_and_delete("users", filter_q)
        per_collection.append({"collection": "users", "backed_up_to": bn, "backed_up": b, "deleted": d})
        total_backed_up += b; total_deleted += d
    except Exception as e:
        per_collection.append({"collection": "users", "error": str(e), "aborted": True})

    # 4. Audit.
    try:
        await db.get_collection("client_reset_audit").insert_one({
            "id": f"client_reset_{ts}",
            "executed_at": now_iso(),
            "coach_id": coach.get("id"),
            "coach_email": coach.get("email"),
            "protected_accounts": protected,
            "deleted_user_ids": target_ids,
            "deleted_user_emails": [u.get("email") for u in targets],
            "total_backed_up": total_backed_up,
            "total_deleted": total_deleted,
            "per_collection": per_collection,
            "token": expected_token,
        })
    except Exception as e:
        logger.warning("client_reset_audit write failed: %s", e)

    return {
        "ok": True,
        "mode": "client_reset_execute",
        "executed_at": now_iso(),
        "backup_prefix": f"client_reset_backup_{ts}_",
        "protected_accounts": [
            {"id": u.get("id"), "email": u.get("email"), "role": u.get("role")}
            for u in protected
        ],
        "deleted_user_ids": target_ids,
        "deleted_user_emails": [u.get("email") for u in targets],
        "total_users_deleted": len(target_ids),
        "total_backed_up": total_backed_up,
        "total_deleted": total_deleted,
        "per_collection": per_collection,
        "rollback_hint": (
            "To rollback: for each entry in per_collection, copy documents "
            "from backup_prefix + collection back into the original collection."
        ),
    }

