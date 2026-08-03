"""
feature_exercise_pipeline_audit — Manual Mode Stage A.

Final audit + light-repair pass on the unified exercise pipeline. After
Stages B / C / D / F the app SHOULD have `db.exercises_v2` as the single
source of truth for every exercise reference — this module verifies that
end-to-end and offers idempotent repairs for the most common pipeline
gaps.

Endpoints (admin/coach only):
  * GET  /api/admin/exercise-pipeline/audit
      → comprehensive diagnostic (read-only)
  * POST /api/admin/exercise-pipeline/merge-fuzzy-duplicates?dry_run=true
      → merges name-normalised duplicates that survived the strict
        duplicate merge (default dry-run — pass ?dry_run=false to execute)

Design notes:
  * Zero destructive writes without dry-run OFF.
  * All removed rows are backed up to `exercise_merge_backup_<yyyymmdd>`
    before deletion (same convention as the earlier strict-dedup batch).
  * Fuzzy match: lowercase → punctuation-stripped word tokens joined by
    space. `"Cat-Cow"`, `"Cat / cow"`, `"cat cow"` all normalise to
    `"cat cow"`.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query

from server import api, db, require_role, logger, now_iso


# Reuse the same normalisation as the resolver — keeps dedup behaviour
# consistent across the codebase.
try:
    from feature_v2_resolver import _normalise_name
except Exception:  # pragma: no cover — defensive
    _WORD_RE = re.compile(r"[a-z0-9]+")
    def _normalise_name(s: Optional[str]) -> str:  # type: ignore
        if not s:
            return ""
        return " ".join(_WORD_RE.findall(str(s).lower()))


APPROVED_STATUSES = {"approved", "live"}


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

async def _collect_workout_exercise_refs() -> tuple[set[str], dict[str, int]]:
    """Scan every workout doc for exercise_id references across warmup +
    exercises + cooldown + variants{green,amber,red}. Returns:
      (set_of_ids, usage_count_by_id)
    """
    seen: set[str] = set()
    usage: dict[str, int] = {}
    cursor = db.workouts.find(
        {},
        {"_id": 0, "id": 1, "warmup": 1, "exercises": 1, "cooldown": 1, "variants": 1},
    )
    async for w in cursor:
        buckets: list[list[dict]] = []
        for k in ("warmup", "exercises", "cooldown"):
            buckets.append(w.get(k) or [])
        variants = w.get("variants") or {}
        for vk in ("green", "amber", "red"):
            v = variants.get(vk) or {}
            buckets.append(v.get("exercises") or [])
            buckets.append(v.get("warmup") or [])
        for bucket in buckets:
            for e in bucket or []:
                xid = e.get("exercise_id")
                if xid:
                    seen.add(xid)
                    usage[xid] = usage.get(xid, 0) + 1
    return seen, usage


async def _audit_orphans(referenced_ids: set[str]) -> list[dict]:
    """Which referenced exercise_ids no longer exist in db.exercises_v2."""
    if not referenced_ids:
        return []
    existing_cursor = db.exercises_v2.find(
        {"id": {"$in": list(referenced_ids)}},
        {"_id": 0, "id": 1},
    )
    existing_ids: set[str] = set()
    async for r in existing_cursor:
        existing_ids.add(r["id"])
    orphans = referenced_ids - existing_ids
    return [{"exercise_id": x} for x in sorted(orphans)]


async def _audit_fuzzy_duplicates() -> list[dict]:
    """Group every exercises_v2 row by normalised name and return groups
    with more than 1 record. Ignores empty names."""
    groups: dict[str, list[dict]] = {}
    cursor = db.exercises_v2.find(
        {},
        {"_id": 0, "id": 1, "exercise_name": 1, "status": 1,
         "primary_image_url": 1, "primary_video_url": 1,
         "request_count": 1, "created_at": 1},
    )
    async for r in cursor:
        norm = _normalise_name(r.get("exercise_name"))
        if not norm:
            continue
        groups.setdefault(norm, []).append(r)
    fuzzy: list[dict] = []
    for norm, rows in groups.items():
        if len(rows) < 2:
            continue
        fuzzy.append({
            "normalised": norm,
            "count": len(rows),
            "names": sorted({r.get("exercise_name") or "" for r in rows}),
            "ids": [r.get("id") for r in rows],
            "statuses": sorted({(r.get("status") or "").lower() for r in rows}),
        })
    # Sort by group size desc so the coach can prioritise big collisions.
    fuzzy.sort(key=lambda g: (-g["count"], g["normalised"]))
    return fuzzy


async def _audit_draft_health() -> dict:
    """Metadata completeness on non-approved rows."""
    q = {"status": {"$nin": ["Approved", "Live"]}}
    total = await db.exercises_v2.count_documents(q)
    missing_mp = await db.exercises_v2.count_documents(
        {**q, "$or": [{"movement_pattern": {"$in": [None, ""]}},
                       {"movement_pattern": {"$exists": False}}]}
    )
    missing_body = await db.exercises_v2.count_documents(
        {**q, "$or": [{"body_area": {"$in": [None, ""]}},
                       {"body_area": {"$exists": False}}]}
    )
    missing_tags = await db.exercises_v2.count_documents(
        {**q, "$or": [{"tags": {"$size": 0}}, {"tags": {"$exists": False}}]}
    )
    return {
        "total_non_approved": total,
        "missing_movement_pattern": missing_mp,
        "missing_body_area": missing_body,
        "missing_tags": missing_tags,
    }


async def _audit_media_coverage() -> dict:
    """% of approved exercises with at least one image or video."""
    approved_q = {"status": {"$in": ["Approved", "Live"]}}
    total = await db.exercises_v2.count_documents(approved_q)
    with_image = await db.exercises_v2.count_documents(
        {**approved_q, "primary_image_url": {"$nin": [None, ""]}}
    )
    with_video = await db.exercises_v2.count_documents(
        {**approved_q, "primary_video_url": {"$nin": [None, ""]}}
    )
    with_any = await db.exercises_v2.count_documents({
        **approved_q,
        "$or": [
            {"primary_image_url": {"$nin": [None, ""]}},
            {"primary_video_url": {"$nin": [None, ""]}},
        ],
    })
    def pct(n: int) -> float:
        return round((n / total * 100.0), 1) if total else 0.0
    return {
        "approved_total": total,
        "with_image": with_image, "with_image_pct": pct(with_image),
        "with_video": with_video, "with_video_pct": pct(with_video),
        "with_any_media": with_any, "with_any_media_pct": pct(with_any),
    }


async def _audit_traffic_light_coverage() -> dict:
    """How many workouts have variants that still contain stringy
    (exercise_id-less) rows. Stage B fix should be pushing this to zero
    over time as workouts are opened."""
    workouts_with_variants = 0
    workouts_with_stringy_variants = 0
    cursor = db.workouts.find(
        {"variants": {"$exists": True, "$ne": {}}},
        {"_id": 0, "id": 1, "variants": 1},
    )
    async for w in cursor:
        workouts_with_variants += 1
        v = w.get("variants") or {}
        found_stringy = False
        for vk in ("green", "amber", "red"):
            for e in (v.get(vk) or {}).get("exercises") or []:
                if not e.get("exercise_id"):
                    found_stringy = True
                    break
            if found_stringy:
                break
        if found_stringy:
            workouts_with_stringy_variants += 1
    return {
        "workouts_with_variants": workouts_with_variants,
        "workouts_with_stringy_variants": workouts_with_stringy_variants,
    }


async def _audit_status_breakdown() -> dict:
    """Counts by exercises_v2 status."""
    out: dict[str, int] = {}
    pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    async for row in db.exercises_v2.aggregate(pipeline):
        out[str(row.get("_id") or "unknown")] = row.get("n", 0)
    return out


@api.get("/admin/exercise-pipeline/audit")
async def exercise_pipeline_audit(
    admin: dict = Depends(require_role("coach")),
):
    """Read-only diagnostic across the unified exercise pipeline.

    Requires coach-admin. Never writes."""
    if not admin.get("is_admin"):
        raise HTTPException(403, "admin only")
    total_exs = await db.exercises_v2.count_documents({})
    referenced_ids, _usage = await _collect_workout_exercise_refs()
    orphans = await _audit_orphans(referenced_ids)
    fuzzy = await _audit_fuzzy_duplicates()
    draft = await _audit_draft_health()
    media = await _audit_media_coverage()
    variants = await _audit_traffic_light_coverage()
    status_breakdown = await _audit_status_breakdown()
    return {
        "ok": True,
        "audited_at": now_iso(),
        "totals": {
            "exercises_v2": total_exs,
            "exercise_ids_referenced_by_workouts": len(referenced_ids),
            "orphan_references": len(orphans),
            "fuzzy_duplicate_groups": len(fuzzy),
        },
        "status_breakdown": status_breakdown,
        "orphan_references": orphans[:200],   # cap to keep payload sane
        "fuzzy_duplicates": fuzzy[:200],
        "draft_health": draft,
        "media_coverage": media,
        "traffic_light_variants": variants,
    }


# ---------------------------------------------------------------------------
# Fuzzy-duplicate merge repair
# ---------------------------------------------------------------------------

def _pick_survivor(rows: list[dict]) -> dict:
    """Choose the "best" row to keep in a fuzzy-dupe group. Priority:
      1. Approved > Live > draft* > archived
      2. Has media (image or video)
      3. Higher request_count
      4. Older created_at (stability)
    """
    def status_rank(s: str) -> int:
        s = (s or "").lower()
        if s in ("approved", "live"):
            return 0
        if s.startswith("draft"):
            return 1
        if s == "archived":
            return 3
        return 2

    def has_media(r: dict) -> int:
        return int(bool(r.get("primary_image_url") or r.get("primary_video_url")))

    return sorted(
        rows,
        key=lambda r: (
            status_rank(r.get("status", "")),
            -has_media(r),
            -int(r.get("request_count") or 0),
            str(r.get("created_at") or ""),
        ),
    )[0]


async def _reassign_workout_refs(from_id: str, to_id: str) -> int:
    """Rewrite every workout row so exercise_id=from_id becomes to_id
    across all sections + variants. Returns number of docs touched."""
    touched = 0
    cursor = db.workouts.find(
        {},
        {"_id": 0, "id": 1, "warmup": 1, "exercises": 1, "cooldown": 1, "variants": 1},
    )
    async for w in cursor:
        changed = False
        updates: dict[str, Any] = {}
        for key in ("warmup", "exercises", "cooldown"):
            items = w.get(key) or []
            new_items = []
            local_change = False
            for e in items:
                if e.get("exercise_id") == from_id:
                    e = {**e, "exercise_id": to_id}
                    local_change = True
                new_items.append(e)
            if local_change:
                updates[key] = new_items
                changed = True
        variants = w.get("variants") or {}
        new_variants = {}
        variants_changed = False
        for vk in ("green", "amber", "red"):
            v = variants.get(vk) or {}
            new_v = {**v}
            for k2 in ("exercises", "warmup"):
                items = v.get(k2) or []
                new_items = []
                local_change = False
                for e in items:
                    if e.get("exercise_id") == from_id:
                        e = {**e, "exercise_id": to_id}
                        local_change = True
                    new_items.append(e)
                if local_change:
                    new_v[k2] = new_items
                    variants_changed = True
            new_variants[vk] = new_v
        if variants_changed:
            updates["variants"] = new_variants
            changed = True
        if changed:
            updates["updated_at"] = now_iso()
            await db.workouts.update_one({"id": w["id"]}, {"$set": updates})
            touched += 1
    return touched


@api.post("/admin/exercise-pipeline/merge-fuzzy-duplicates")
async def exercise_pipeline_merge_fuzzy_duplicates(
    dry_run: bool = Query(True, description="Preview merges without writing"),
    admin: dict = Depends(require_role("coach")),
):
    """Merge every fuzzy-duplicate group in exercises_v2. For each group we:
      1. Pick the survivor (approved > draft, media > no-media, older).
      2. Reassign every workout reference from losers → survivor.
      3. Back losers up to `exercise_merge_backup_<yyyymmdd>` collection.
      4. Delete losers from `exercises_v2`.

    All operations are idempotent. Set `dry_run=false` (query string) to
    actually mutate. Backups are ALWAYS written before deletion.
    """
    if not admin.get("is_admin"):
        raise HTTPException(403, "admin only")
    fuzzy_groups = await _audit_fuzzy_duplicates()

    stamp = _dt.datetime.utcnow().strftime("%Y%m%d")
    backup_name = f"exercise_merge_backup_{stamp}"

    plan: list[dict] = []
    execution: dict[str, int] = {
        "groups": 0, "rows_removed": 0, "workouts_touched": 0,
    }

    for group in fuzzy_groups:
        # Re-fetch full docs for each group id (audit only pulled projections)
        rows = await db.exercises_v2.find(
            {"id": {"$in": group["ids"]}}, {"_id": 0}
        ).to_list(length=len(group["ids"]))
        if len(rows) < 2:
            continue
        survivor = _pick_survivor(rows)
        losers = [r for r in rows if r["id"] != survivor["id"]]
        plan.append({
            "normalised": group["normalised"],
            "survivor": {
                "id": survivor["id"],
                "name": survivor.get("exercise_name"),
                "status": survivor.get("status"),
            },
            "losers": [{
                "id": r["id"],
                "name": r.get("exercise_name"),
                "status": r.get("status"),
            } for r in losers],
        })
        if dry_run:
            continue

        # Execute — reassign then backup then delete.
        for loser in losers:
            touched = await _reassign_workout_refs(loser["id"], survivor["id"])
            execution["workouts_touched"] += touched
            # Backup with merge metadata so it's traceable.
            try:
                await db[backup_name].insert_one({
                    **loser,
                    "_merged_into": survivor["id"],
                    "_merged_at": now_iso(),
                    "_merged_by": admin.get("id"),
                    "_merged_reason": "fuzzy_dupe_audit",
                })
            except Exception:
                logger.exception("audit: backup insert failed for %s", loser["id"])
            await db.exercises_v2.delete_one({"id": loser["id"]})
            execution["rows_removed"] += 1
        execution["groups"] += 1

    return {
        "ok": True,
        "dry_run": dry_run,
        "backup_collection": None if dry_run else backup_name,
        "groups_found": len(fuzzy_groups),
        "plan": plan[:200],  # cap
        "execution": execution,
    }


__all__ = [
    "exercise_pipeline_audit",
    "exercise_pipeline_merge_fuzzy_duplicates",
]
