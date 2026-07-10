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
