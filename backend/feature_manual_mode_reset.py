"""
Phase 1B — Programme reset endpoints.

Two admin endpoints:
  * POST /api/admin/programme-reset/dry-run  → returns exact per-collection
    counts that WOULD be deleted. Zero mutations.
  * POST /api/admin/programme-reset/execute → snapshots affected records to
    `programme_reset_backup_{iso_ts}` collections, then deletes. Requires the
    dry-run token (SHA-256 of the counts) as body param `expected_token` so a
    stale dry-run cannot execute against a changed dataset.

Both endpoints are coach-only (require_role("coach")). Flight Support and
client-profile collections are NEVER touched.

Reversible: if a mistake happens, the caller can copy documents back from
`programme_reset_backup_{ts}.*` into their source collections.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
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

    return {
        "ok": True,
        "mode": "dry_run",
        "generated_at": now_iso(),
        "counts_to_clear": counts,
        "total_documents_to_clear": sum(v for v in counts.values() if v >= 0),
        "protected_collections": _PROTECTED_COLLECTIONS,
        "flight_support_preview": fs,
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
