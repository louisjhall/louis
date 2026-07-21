"""
feature_exercise_request_tasks — Plan D1/D2/D3.

Bridges the V2 Exercise Library draft flow to Louis' coach To-Do list.

Rules:
  * Every draft exercise (`db.exercises_v2` with `status = draft_requested`
    and `needs_louis_review = true`) MUST have at least one open coach task
    of `task_type = exercise_library_review`.
  * If a client's programme wants an unresolved exercise again, we bump the
    existing task (increment request_count, add clients_affected, escalate
    priority if urgent) instead of creating a duplicate.
  * If Louis loads the coach dashboard and there's an orphaned draft with
    no open task, reconcile: create the missing task and flag as recovered.
  * Counter endpoint `/api/coach/exercise-reviews/counts` powers the sidebar
    badge.

Endpoints:
  * POST /api/coach/exercise-reviews/reconcile → run reconciliation now
  * GET  /api/coach/exercise-reviews/counts    → { unresolved, needed_soon,
                                                    media_needed, awaiting_review }

Wiring:
  * `hook_exercise_request_task(exercise, user, next_scheduled_iso)` is
    called from `feature_v2_resolver.create_exercise_request_if_missing`
    after the draft is upserted. Idempotent — safe to call repeatedly.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException

from server import (
    api,
    db,
    require_role,
    new_id,
    now_iso,
    logger,
    _create_coach_task,
)


TASK_TYPE = "exercise_library_review"


# ---------------------------------------------------------------------------
# Urgency computation
# ---------------------------------------------------------------------------

def _priority_for_days(days_until_needed: Optional[int]) -> str:
    if days_until_needed is None:
        return "normal"
    if days_until_needed <= 1:
        return "urgent"
    if days_until_needed <= 7:
        return "high"
    if days_until_needed <= 30:
        return "normal"
    return "low"


async def _next_scheduled_use_for_exercise(exercise_v2_id: str) -> Optional[str]:
    """Look at all upcoming workouts using this exercise. Return earliest date
    (ISO). None if no upcoming use."""
    today = _dt.date.today().isoformat()
    row = await db.workouts.find_one(
        {"exercises.exercise_id": exercise_v2_id, "date": {"$gte": today}, "completed": {"$ne": True}},
        {"_id": 0, "date": 1},
        sort=[("date", 1)],
    )
    return (row or {}).get("date")


def _days_until(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        d = _dt.date.fromisoformat(iso[:10])
        return (d - _dt.date.today()).days
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Hook — called from create_exercise_request_if_missing
# ---------------------------------------------------------------------------

async def hook_exercise_request_task(
    exercise: dict,
    user: dict,
    programme_id: Optional[str] = None,
    workout_id: Optional[str] = None,
) -> Optional[str]:
    """Ensure there is an open exercise_library_review task for this draft.

    Idempotent:
      * If an open task exists for the same exercise_v2_id, bump its
        `clients_affected` / `request_count` / `next_scheduled_need` and
        escalate `priority` if the exercise is now needed sooner.
      * Otherwise create a fresh task.

    Returns the coach_task id (existing or new). Silent on failure.
    """
    ex_id = exercise.get("id")
    if not ex_id:
        return None
    ex_name = exercise.get("exercise_name") or exercise.get("requested_name") or "Unknown exercise"

    # Determine next scheduled need — soonest upcoming workout using this exercise
    next_iso = await _next_scheduled_use_for_exercise(ex_id)
    days_until = _days_until(next_iso)
    priority = _priority_for_days(days_until)

    # Look up an existing open task for this exercise.
    existing_task = await db.coach_tasks.find_one({
        "task_type": TASK_TYPE,
        "payload.exercise_id": ex_id,
        "status": {"$in": ["todo", "in_progress", "snoozed"]},
    }, {"_id": 0})

    client_ref = {
        "id": user.get("id"),
        "name": user.get("name") or user.get("email"),
    }
    programme_ref = programme_id
    workout_ref = workout_id

    if existing_task:
        # Bump payload counters + affected clients / programmes / workouts.
        payload = existing_task.get("payload") or {}
        clients_affected = list({*(payload.get("clients_affected") or []), user.get("id")})
        programmes_affected = list({*(payload.get("programmes_affected") or []), programme_id} - {None})
        workouts_affected = list({*(payload.get("workouts_affected") or []), workout_id} - {None})
        payload.update({
            "exercise_id": ex_id,
            "exercise_name": ex_name,
            "clients_affected": clients_affected,
            "programmes_affected": programmes_affected,
            "workouts_affected": workouts_affected,
            "next_scheduled_need": next_iso,
            "days_until_needed": days_until,
            "request_count": (payload.get("request_count") or 0) + 1,
        })
        prev_priority = existing_task.get("priority") or "normal"
        # Escalate only (never demote) — new priority wins if stricter
        rank = {"low": 0, "normal": 1, "high": 2, "urgent": 3}
        new_priority = priority if rank[priority] > rank.get(prev_priority, 1) else prev_priority
        await db.coach_tasks.update_one(
            {"id": existing_task["id"]},
            {"$set": {
                "payload": payload,
                "priority": new_priority,
                "updated_at": now_iso(),
            }},
        )
        return existing_task["id"]

    # No open task → create fresh
    description = (
        f"Draft exercise needs coach review before it can be used in client programmes.\n"
        f"Requested by: {client_ref['name']}\n"
    )
    if programme_id:
        description += f"Programme: {programme_id}\n"
    if workout_id:
        description += f"Next scheduled use: {next_iso or 'unscheduled'}\n"
    description += (
        "Review the exercise, confirm coaching notes + media, then approve / edit / reject / merge."
    )
    task_id = await _create_coach_task(
        user,
        task_type=TASK_TYPE,
        title=f"Review new exercise: {ex_name}",
        description=description,
        priority=priority,
        category="exercise_library",
        payload={
            "exercise_id": ex_id,
            "exercise_name": ex_name,
            "movement_pattern": exercise.get("movement_pattern"),
            "equipment_type": exercise.get("equipment_type"),
            "clients_affected": [user.get("id")],
            "programmes_affected": [programme_id] if programme_id else [],
            "workouts_affected": [workout_id] if workout_id else [],
            "next_scheduled_need": next_iso,
            "days_until_needed": days_until,
            "request_count": exercise.get("request_count") or 1,
            "source": "hook_exercise_request_task",
        },
    )
    return task_id


# ---------------------------------------------------------------------------
# D2 — Reconciliation: find orphaned draft rows, create the missing task
# ---------------------------------------------------------------------------

async def reconcile_exercise_review_tasks() -> dict[str, Any]:
    """Scan draft V2 rows and ensure each has an open coach task.

    Runs quickly (bounded query on exercises_v2). Returns a summary.
    """
    orphans_fixed = 0
    checked = 0
    q = {
        "$or": [
            {"status": "draft_requested"},
            {"needs_louis_review": True},
        ],
    }
    async for ex in db.exercises_v2.find(q, {"_id": 0}).limit(500):
        checked += 1
        ex_id = ex.get("id")
        if not ex_id:
            continue
        has_task = await db.coach_tasks.find_one({
            "task_type": TASK_TYPE,
            "payload.exercise_id": ex_id,
            "status": {"$in": ["todo", "in_progress", "snoozed"]},
        }, {"_id": 0, "id": 1})
        if has_task:
            continue
        # Recover — synthesise a user reference from client_context_summary
        cctx = ex.get("client_context_summary") or {}
        stub_user = {
            "id": cctx.get("user_id") or "reconciliation",
            "name": "Reconciled (orphan)",
            "email": "reconciled",
        }
        # Find latest scheduled workout use to gauge urgency
        next_iso = await _next_scheduled_use_for_exercise(ex_id)
        days_until = _days_until(next_iso)
        try:
            await _create_coach_task(
                stub_user,
                task_type=TASK_TYPE,
                title=f"Review new exercise: {ex.get('exercise_name') or 'Unknown'}",
                description=(
                    f"Recovered orphan draft — this exercise had no open coach task.\n"
                    f"Requested {ex.get('request_count') or 1} time(s).\n"
                    f"Next scheduled use: {next_iso or 'unscheduled'}."
                ),
                priority=_priority_for_days(days_until),
                category="exercise_library",
                payload={
                    "exercise_id": ex_id,
                    "exercise_name": ex.get("exercise_name"),
                    "movement_pattern": ex.get("movement_pattern"),
                    "equipment_type": ex.get("equipment_type"),
                    "clients_affected": ex.get("requested_for_user_ids") or [],
                    "programmes_affected": ex.get("requested_for_programme_ids") or [],
                    "workouts_affected": ex.get("requested_for_workout_ids") or [],
                    "next_scheduled_need": next_iso,
                    "days_until_needed": days_until,
                    "request_count": ex.get("request_count") or 1,
                    "source": "reconciliation",
                    "recovered": True,
                    "recovered_at": now_iso(),
                },
            )
            orphans_fixed += 1
        except Exception:
            logger.exception("reconcile: task creation failed for ex=%s (non-fatal)", ex_id)

    return {"checked": checked, "orphans_fixed": orphans_fixed, "at": now_iso()}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.post("/coach/exercise-reviews/reconcile")
async def coach_exercise_reviews_reconcile(coach: dict = Depends(require_role("coach"))):
    return await reconcile_exercise_review_tasks()


@api.get("/coach/exercise-reviews/counts")
async def coach_exercise_reviews_counts(coach: dict = Depends(require_role("coach"))):
    """Counter for the sidebar Exercise Reviews badge."""
    q_open = {
        "task_type": TASK_TYPE,
        "status": {"$in": ["todo", "in_progress", "snoozed"]},
    }
    unresolved = await db.coach_tasks.count_documents(q_open)

    today = _dt.date.today()
    horizon = today + _dt.timedelta(days=7)
    needed_soon = await db.coach_tasks.count_documents({
        **q_open,
        "payload.next_scheduled_need": {"$gte": today.isoformat(), "$lte": horizon.isoformat()},
    })
    urgent = await db.coach_tasks.count_documents({**q_open, "priority": "urgent"})
    high = await db.coach_tasks.count_documents({**q_open, "priority": "high"})
    media_needed = await db.coach_tasks.count_documents({
        "task_type": "exercise_media_needed",
        "status": {"$in": ["todo", "in_progress"]},
    })
    return {
        "unresolved": unresolved,
        "needed_soon": needed_soon,
        "urgent": urgent,
        "high": high,
        "media_needed": media_needed,
        "at": now_iso(),
    }


@api.get("/coach/exercise-reviews/list")
async def coach_exercise_reviews_list(
    coach: dict = Depends(require_role("coach")),
    filter_bucket: Optional[str] = None,
):
    """List exercise-review tasks with optional bucket filter.

    Buckets:
      * needed_soon      — next_scheduled_need within 7 days
      * drafts_waiting   — all open tasks
      * media_needed     — media follow-ups
      * ready_for_approval — draft with all fields, awaiting Louis' click
      * history          — completed/rejected/merged (last 60 days)
    """
    today = _dt.date.today()
    horizon = today + _dt.timedelta(days=7)

    if filter_bucket == "history":
        rows = await db.coach_tasks.find(
            {"task_type": TASK_TYPE, "status": {"$in": ["done", "dismissed"]}},
            {"_id": 0},
        ).sort("completed_at", -1).limit(60).to_list(60)
        return {"tasks": rows}

    q: dict[str, Any] = {"task_type": TASK_TYPE, "status": {"$in": ["todo", "in_progress", "snoozed"]}}
    if filter_bucket == "needed_soon":
        q["payload.next_scheduled_need"] = {"$gte": today.isoformat(), "$lte": horizon.isoformat()}
    if filter_bucket == "media_needed":
        q = {"task_type": "exercise_media_needed", "status": {"$in": ["todo", "in_progress"]}}

    rows = await db.coach_tasks.find(q, {"_id": 0}).sort([
        ("priority", -1),
        ("payload.next_scheduled_need", 1),
        ("created_at", 1),
    ]).to_list(200)
    return {"tasks": rows, "count": len(rows)}


# Also expose the hook publicly so v2_resolver can import it cheaply.
__all__ = [
    "hook_exercise_request_task",
    "reconcile_exercise_review_tasks",
    "TASK_TYPE",
]
