"""feature_admin_migrations — Ops endpoints for the two Phase 6 tasks.

    POST /api/admin/storage/backfill?dry_run=true   — walk /uploads and push
                                                       new files to R2.
    GET  /api/admin/storage/status                  — which driver is live
    POST /api/admin/exercises/migrate?dry_run=true  — merge legacy exercises
                                                       + videos into
                                                       exercise_content
    GET  /api/admin/exercises/migrate/status        — summary counts

All routes require admin/coach role.
"""
from __future__ import annotations

from fastapi import Depends, Query
from typing import Optional

from server import (
    api, db, require_admin, new_id, now_iso, logger,
)
import storage as _storage


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

@api.get("/admin/storage/status")
async def storage_status(admin: dict = Depends(require_admin())):
    return {
        "driver": _storage.storage.name,
        "is_cloud": _storage.is_cloud(),
        "upload_root": str(_storage.UPLOAD_ROOT),
    }


@api.post("/admin/storage/backfill")
async def storage_backfill(dry_run: bool = Query(True),
                            admin: dict = Depends(require_admin())):
    """One-shot uploader for existing on-disk media.  Idempotent."""
    summary = await _storage.backfill_from_disk(dry_run=dry_run)
    return summary


# ---------------------------------------------------------------------------
# Exercise migration (legacy exercises + videos → exercise_content)
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    # legacy field → new category
    "strength": "strength", "resistance": "strength",
    "mobility": "mobility", "stretch": "mobility",
    "cardio": "cardio", "hiit": "cardio",
    "warmup": "warmup", "warm_up": "warmup",
    "cooldown": "cooldown", "cool_down": "cooldown",
    "rehab": "rehab", "recovery": "rehab",
}


def _coerce_category(row: dict) -> str:
    for k in ("category", "training_type", "type", "kind"):
        v = (row.get(k) or "").strip().lower().replace(" ", "_")
        if v in _TYPE_MAP:
            return _TYPE_MAP[v]
    return "strength"


def _coerce_points(row: dict) -> list[str]:
    for k in ("coaching_points", "cues", "notes", "tips"):
        v = row.get(k)
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()][:8]
        if isinstance(v, str) and v.strip():
            # Best-effort split on newline / semicolon
            parts = [p.strip() for p in v.replace(";", "\n").split("\n") if p.strip()]
            if parts:
                return parts[:8]
    return []


async def _find_video(exercise: dict) -> Optional[dict]:
    """Look up a legacy video linked to this exercise by id or slug."""
    ex_id = exercise.get("id")
    ex_name = (exercise.get("name") or exercise.get("exercise_name") or "").strip()
    # Try id-linked first
    for query in (
        {"exercise_id": ex_id},
        {"exerciseId": ex_id},
        {"exercise": ex_name},
        {"title": ex_name},
    ):
        row = await db.videos.find_one(query, {"_id": 0})
        if row: return row
    return None


@api.get("/admin/exercises/migrate/status")
async def migrate_status(admin: dict = Depends(require_admin())):
    total_v1 = await db.exercises.count_documents({})
    total_v2 = await db.exercises_v2.count_documents({})
    total_videos = await db.videos.count_documents({})
    return {
        "exercises_v1": total_v1,
        "exercises_v2": total_v2,
        "videos": total_videos,
    }


@api.post("/admin/exercises/migrate")
async def migrate_exercises(dry_run: bool = Query(True),
                            admin: dict = Depends(require_admin())):
    """Merge legacy `exercises` (v1) and `videos` collections into the
    unified `exercise_content` collection.

    Idempotent — a v1 exercise whose `id` already exists in
    `exercise_content` will be updated in place, not duplicated.
    """
    cursor = db.exercises.find({}, {"_id": 0})
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []
    now = now_iso()

    async for old in cursor:
        try:
            ex_id = old.get("id") or new_id()
            name = (old.get("name") or old.get("exercise_name") or "").strip()
            if not name:
                skipped += 1
                continue

            existing = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
            video = await _find_video(old)

            # Compose the v2 record. When a field is unknown we leave the
            # existing value alone (via $setOnInsert vs $set below).
            image_url = old.get("image_url") or old.get("photo_url") or old.get("thumbnail")
            # Preserve the raw v1 category so the legacy Library UI keeps its
            # PUSH/PULL/LEGS filter chips working after migration.
            legacy_cat = str(
                old.get("category") or old.get("training_type") or
                old.get("type") or "strength"
            ).strip().lower()

            common = {
                "exercise_name": name,
                "category": legacy_cat if legacy_cat in {
                    "push", "pull", "legs", "core", "mobility", "cardio",
                    "warmup", "cooldown", "rehab", "strength"
                } else _coerce_category(old),
                "training_type": (old.get("training_type") or _coerce_category(old)),
                "legacy_category": legacy_cat,
                "body_area": (old.get("body_area") or old.get("primary_muscle") or None),
                "equipment_type": _as_list(old.get("equipment_type") or old.get("equipment")),
                "coaching_points": _coerce_points(old),
                "common_mistakes": _as_list(old.get("common_mistakes")),
                "alternatives": _as_list(old.get("alternatives") or old.get("swaps")),
                "client_facing_instructions": old.get("client_facing_instructions") or old.get("description"),
                "primary_image_url": image_url,
                "primary_video_url": (video or {}).get("url") or old.get("video_url"),
                "primary_video_source": (video or {}).get("source") or None,
                "approved_image_status": "pending" if image_url else "missing",
                "approved_video_status": "pending" if ((video or {}).get("url") or old.get("video_url")) else "missing",
                "approved_coaching_status": "pending" if _coerce_points(old) else "missing",
                "status": "draft",
                "migrated_from_v1": True,
                "migrated_at": now,
                "updated_at": now,
            }

            if dry_run:
                if existing: updated += 1
                else: inserted += 1
                continue

            if existing:
                await db.exercises_v2.update_one(
                    {"id": ex_id},
                    {"$set": {**common, "updated_at": now}},
                )
                updated += 1
            else:
                doc = {
                    "id": ex_id, "created_at": now,
                    "created_by": admin["id"], **common,
                }
                await db.exercises_v2.insert_one(doc)
                inserted += 1
        except Exception as e:
            logger.exception("migrate exercise failed")
            errors.append({"id": (old or {}).get("id"), "error": str(e)[:200]})

    return {
        "dry_run": dry_run,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:20],
    }


def _as_list(v) -> list[str]:
    if v is None: return []
    if isinstance(v, list): return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [p.strip() for p in v.replace(";", ",").split(",") if p.strip()]
    return []



# ---------------------------------------------------------------------------
# Check-in collection unification (checkins  ← check_ins)
# ---------------------------------------------------------------------------
#
# History: the codebase grew two collections that both hold weekly check-in
# submissions:
#   * `checkins`    — used by legacy endpoints (server.py:2968, 4824, 5126,
#                      5291, 4871).
#   * `check_ins`   — used by the newer weekly reminder + coach dashboard
#                      code (server.py:6339, 6506, 6575, 6607, 6659, 6704,
#                      6730, 6744, 6833, 6906) plus feature_coach_v1,
#                      feature_habits, feature_notifications.
#
# Chosen canonical: **`checkins`** (matches `workouts`, `habits`, `messages`).
# Strategy:
#   1. Snapshot both counts.
#   2. Copy every doc from `check_ins` → `checkins`, keyed on `id` when
#      present, else `(user_id, week_start)`.  Skip duplicates.
#   3. Rename `check_ins` → `check_ins_legacy_backup_YYYYMMDD` so the source
#      stays around for 30 days in case rollback is needed.
#   4. Report counts.
#
# After migration: code will still write to both because the source files
# reference `db.check_ins.*` and `db.checkins.*`.  A follow-up refactor will
# unify code paths.  Until then, a **read-through view** trick makes the
# migration safe:  we leave the app writing to both, but the migration only
# needs to guarantee no data is lost when the legacy collection is renamed.

@api.get("/admin/migrations/checkins/status")
async def checkins_status(admin: dict = Depends(require_admin())):
    count_new = await db.checkins.estimated_document_count()
    count_legacy = await db.check_ins.estimated_document_count()
    backup_names = [n for n in await db.list_collection_names()
                    if n.startswith("check_ins_legacy_backup_")]
    return {
        "canonical": "checkins",
        "checkins_count": count_new,
        "check_ins_count": count_legacy,
        "legacy_backups": backup_names,
    }


@api.post("/admin/migrations/checkins/unify")
async def checkins_unify(dry_run: bool = Query(True), rename_legacy: bool = Query(False),
                          admin: dict = Depends(require_admin())):
    """Merge `check_ins` documents into `checkins`.

    Args:
        dry_run: when True (default), only report what would happen.
        rename_legacy: when True (only in real run), rename `check_ins` to
            `check_ins_legacy_backup_<yyyymmdd>` afterwards. Off by default so
            you can verify the merge before losing the source.
    """
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []

    async for src in db.check_ins.find({}, {"_id": 0}):
        try:
            match = None
            if src.get("id"):
                match = {"id": src["id"]}
            elif src.get("user_id") and src.get("week_start"):
                match = {"user_id": src["user_id"], "week_start": src["week_start"]}
            if not match:
                skipped += 1
                continue
            existing = await db.checkins.find_one(match, {"_id": 0, "id": 1})
            if existing:
                # Prefer the more-recent record.
                new_ts = src.get("submitted_at") or src.get("created_at") or ""
                old_ts = existing.get("submitted_at") or existing.get("created_at") or ""
                if new_ts and new_ts > old_ts:
                    if not dry_run:
                        await db.checkins.update_one(match, {"$set": src})
                    updated += 1
                else:
                    skipped += 1
                continue
            if not dry_run:
                await db.checkins.insert_one(src)
            inserted += 1
        except Exception as e:
            logger.exception("checkin unify failed")
            errors.append({"id": src.get("id"), "error": str(e)[:200]})

    renamed = False
    if not dry_run and rename_legacy:
        import datetime as _dt
        stamp = _dt.datetime.utcnow().strftime("%Y%m%d")
        target = f"check_ins_legacy_backup_{stamp}"
        try:
            await db.check_ins.rename(target)
            renamed = True
        except Exception as e:
            errors.append({"stage": "rename", "error": str(e)[:200]})

    return {
        "dry_run": dry_run,
        "canonical": "checkins",
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "renamed_legacy": renamed,
        "errors": errors[:20],
    }
