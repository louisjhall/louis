"""
Iter 94t (Phase 1) — Exercise media reconciliation.

Scans upcoming workouts for missing exercise content (empty exercises list,
missing images/videos/instructions, empty pre/post-flight mobility, empty
warm-up etc.) and creates `exercise_media_review` coach tasks so Louis can
fix content live without a new app build.

Endpoints:
  POST /admin/media/reconcile   — trigger a reconciliation pass (admin/coach).
  GET  /admin/media/todos       — list open exercise_media_review tasks.

Runs opportunistically inside GET /workouts/week too (best-effort, silent).
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

from fastapi import Depends

from server import (
    api, current_user, require_role, db, new_id, now_iso, _create_coach_task,
)

logger = logging.getLogger("crewfit.media_reconcile")

TARGET_SESSION_TYPES = {
    "pre_flight_mobility", "post_flight_mobility",
    "mobility", "cooldown", "warmup", "warm_up",
    "hotel_circuit", "layover_workout",
    "strength_lower", "strength_upper", "strength_full", "strength_support",
    "hard_conditioning", "conditioning", "hyrox",
    "long_run", "easy_run", "intervals", "tempo",
    "recovery_flow", "guided_flow",
}


def _exercise_missing_fields(ex: dict) -> list[str]:
    missing: list[str] = []
    if not ex:
        return ["exercise_empty"]
    if not ex.get("name"):
        missing.append("name")
    # Media
    has_image = bool(ex.get("image") or ex.get("images") or ex.get("image_url") or ex.get("photo_url"))
    has_video = bool(ex.get("video") or ex.get("video_url"))
    if not has_image and not has_video:
        missing.append("media")
    # Instructions or coaching points
    has_instr = bool((ex.get("instructions") or ex.get("cues") or ex.get("notes") or "").strip())
    if not has_instr:
        missing.append("instructions")
    return missing


def _classify_missing(w: dict) -> Optional[dict]:
    """Return { level, sections, first_missing } if the workout has missing
    media, else None. `level` ∈ {"empty", "partial", "text_only"}."""
    exercises = w.get("exercises") or []
    if not exercises:
        return {"level": "empty", "sections": ["all"], "first_missing": None}
    text_only_count = 0
    partial_count = 0
    first_missing_name = None
    for ex in exercises:
        miss = _exercise_missing_fields(ex)
        if not miss:
            continue
        first_missing_name = first_missing_name or ex.get("name") or "Exercise"
        if "media" in miss:
            partial_count += 1
        if "instructions" in miss and "media" in miss:
            text_only_count += 1
    if text_only_count == len(exercises) and text_only_count > 0:
        return {"level": "text_only", "sections": ["all"], "first_missing": first_missing_name}
    if partial_count > 0:
        return {"level": "partial", "sections": ["media"], "first_missing": first_missing_name}
    return None


def _priority_for(days_until: int) -> str:
    if days_until <= 1:
        return "urgent"
    if days_until <= 7:
        return "high"
    if days_until <= 30:
        return "medium"
    return "low"


async def _existing_task(user_id: str, workout_id: str) -> Optional[dict]:
    return await db.coach_tasks.find_one({
        "user_id": user_id,
        "task_type": "exercise_media_review",
        "status": "todo",
        "payload.workout_id": workout_id,
    }, {"_id": 0, "id": 1})


async def reconcile_media_for_user(user: dict, horizon_days: int = 30) -> dict:
    """Scan next N days of workouts for the user and open coach tasks for any
    with missing media. Idempotent — never opens duplicate tasks for a workout
    that already has an open review task."""
    today = _dt.date.today()
    horizon = today + _dt.timedelta(days=horizon_days)
    rows = await db.workouts.find({
        "user_id": user["id"],
        "date": {"$gte": today.isoformat(), "$lte": horizon.isoformat()},
        "completed": {"$ne": True},
        "skipped": {"$ne": True},
    }, {"_id": 0}).sort("date", 1).to_list(200)

    opened, skipped_existing, healthy = 0, 0, 0
    for w in rows:
        st = str(w.get("session_type") or "").lower()
        title = str(w.get("title") or "").lower()
        # Only reconcile session types where we expect content
        if st not in TARGET_SESSION_TYPES and "rest" in title:
            continue
        cls = _classify_missing(w)
        if not cls:
            healthy += 1
            continue
        if await _existing_task(user["id"], w.get("id")):
            skipped_existing += 1
            continue
        # Days until workout
        try:
            d = _dt.date.fromisoformat(str(w.get("date"))[:10])
            days_until = max(0, (d - today).days)
        except Exception:
            days_until = 0
        priority = _priority_for(days_until)
        section = "warm-up" if "warm" in st or "warm" in title else (
            "mobility" if "mobility" in st or "mobility" in title else (
            "cooldown" if "cool" in st or "cool" in title else "main"
        ))
        title_short = w.get("title") or st or "Session"
        desc_bits = [
            f"Session: {title_short}",
            f"Date: {w.get('date')}",
            f"Section: {section}",
            f"Missing: {cls['level']} — {cls.get('first_missing') or 'multiple items'}",
        ]
        try:
            await _create_coach_task(
                user, "exercise_media_review",
                f"Exercise media needed: {cls.get('first_missing') or title_short}",
                " · ".join(desc_bits),
                priority=priority,
                category="content_review",
                payload={
                    "workout_id": w.get("id"),
                    "user_id": user["id"],
                    "date": w.get("date"),
                    "section": section,
                    "missing_level": cls["level"],
                    "session_type": st,
                    "days_until": days_until,
                },
            )
            opened += 1
        except Exception:
            logger.exception("failed to open exercise_media_review task for %s", w.get("id"))
    return {"opened": opened, "skipped_existing": skipped_existing, "healthy": healthy, "scanned": len(rows)}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.post("/admin/media/reconcile")
async def admin_media_reconcile(user: dict = Depends(require_role("coach"))):
    """Scan every client's upcoming workouts. Returns a per-client summary."""
    clients = await db.users.find({"role": "client", "status": {"$ne": "deleted"}}, {"_id": 0, "id": 1, "email": 1, "name": 1}).to_list(500)
    summary = []
    total_opened = 0
    for c in clients:
        r = await reconcile_media_for_user(c, horizon_days=30)
        if r["opened"] or r["scanned"]:
            summary.append({"user_id": c["id"], "email": c.get("email"), **r})
        total_opened += r["opened"]
    return {"ok": True, "total_opened": total_opened, "clients_scanned": len(clients), "summary": summary[:50]}


@api.get("/admin/media/todos")
async def admin_media_todos(user: dict = Depends(require_role("coach"))):
    rows = await db.coach_tasks.find(
        {"task_type": "exercise_media_review", "status": "todo"}, {"_id": 0},
    ).sort([("priority", 1), ("created_at", -1)]).to_list(200)
    return {"todos": rows or [], "count": len(rows or [])}
