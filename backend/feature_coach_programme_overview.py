"""
feature_coach_programme_overview — Plan C3.

Read-only endpoints that power the coach's Programme Overview + Timeline
screens without re-generating anything.

Overview:
  GET /api/coach/clients/{cid}/programme-overview
    → summary card: goal, phase, week_index, target, planned/completed/missed
      this week, current progression rule, roster context, validation status,
      source (llm/template/coach-edited), needs_coach_review flag, and quick
      pointers to key session + related coach tasks.

Timeline:
  GET /api/coach/clients/{cid}/programme-timeline?limit=200
    → merged timeline of lifecycle events (onboarding, DNA, roster, programme,
      workout completions, exercise swaps, coach edits, regenerations, check-ins,
      progression changes, roster audit).

No LLM. No writes. Fully deterministic aggregation.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException

from server import api, db, require_role, now_iso


# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------

@api.get("/coach/clients/{client_id}/programme-overview")
async def coach_programme_overview(client_id: str, coach: dict = Depends(require_role("coach"))):
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")

    p = await db.programmes.find_one(
        {"user_id": client_id, "$or": [{"deactivated": {"$ne": True}}, {"deactivated": {"$exists": False}}]},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not p:
        # Attempt to fall back to the most recent programme even if deactivated
        p = await db.programmes.find_one({"user_id": client_id}, {"_id": 0}, sort=[("created_at", -1)])

    today = _dt.date.today()
    monday = today - _dt.timedelta(days=today.weekday())
    sunday = monday + _dt.timedelta(days=6)
    horizon14 = today + _dt.timedelta(days=14)

    # This week's workouts + counts (real training vs recovery/mobility)
    this_week = await db.workouts.find({
        "user_id": client_id,
        "date": {"$gte": monday.isoformat(), "$lte": sunday.isoformat()},
        "deactivated": {"$ne": True},
    }, {"_id": 0}).sort("date", 1).to_list(30)
    real_this = [w for w in this_week if str(w.get("focus") or "").lower() not in ("recovery", "mobility", "rest")]
    completed_this = [w for w in real_this if w.get("completed")]
    missed_this = [
        w for w in real_this
        if not w.get("completed") and w.get("date") < today.isoformat()
    ]
    planned_this = len(real_this)

    # Sources breakdown
    all_upcoming = await db.workouts.find({
        "user_id": client_id,
        "date": {"$gte": today.isoformat(), "$lte": horizon14.isoformat()},
        "deactivated": {"$ne": True},
    }, {"_id": 0, "source": 1, "needs_coach_review": 1, "validation_status": 1, "coach_locked": 1, "date": 1, "title": 1, "focus": 1, "id": 1, "key_session": 1}).sort("date", 1).to_list(60)
    template_count = sum(1 for w in all_upcoming if w.get("source") == "template")
    review_count = sum(1 for w in all_upcoming if w.get("needs_coach_review"))
    locked_count = sum(1 for w in all_upcoming if w.get("coach_locked"))
    incomplete_count = sum(1 for w in all_upcoming if w.get("validation_status") == "incomplete_content")

    # Next key session in the upcoming window
    next_key = next(
        (w for w in all_upcoming if w.get("key_session") and w.get("focus") not in ("recovery", "mobility", "rest")),
        None,
    )

    # Active roster
    roster = await db.rosters.find_one(
        {"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)],
    )

    # Open coach tasks that reference this client
    open_tasks = await db.coach_tasks.count_documents({
        "client_id": client_id, "status": {"$in": ["todo", "in_progress", "snoozed"]},
    })

    # Compute source label
    if p and p.get("coach_edited"):
        source_label = "coach_edited"
    elif p and (template_count > 0.5 * max(1, len(all_upcoming))):
        source_label = "template_fallback"
    elif p:
        source_label = "full_planning"
    else:
        source_label = "awaiting_generation"

    return {
        "client": {
            "id": client["id"],
            "name": client.get("name") or client.get("email"),
            "email": client.get("email"),
            "avatar_url": client.get("avatar_url"),
        },
        "programme": p or {},
        "roster": roster,
        "week_counts": {
            "planned": planned_this,
            "completed": len(completed_this),
            "missed": len(missed_this),
            "target": (p or {}).get("target_sessions_per_week"),
        },
        "upcoming": {
            "total_14d": len(all_upcoming),
            "template_count": template_count,
            "needs_coach_review": review_count,
            "coach_locked": locked_count,
            "incomplete_content": incomplete_count,
        },
        "next_key_session": next_key,
        "source": source_label,
        "needs_coach_review": bool(review_count or incomplete_count or (p and p.get("validation_status") != "ok")),
        "open_coach_tasks_for_client": open_tasks,
        "at": now_iso(),
    }


# ---------------------------------------------------------------------------
# TIMELINE
# ---------------------------------------------------------------------------

@api.get("/coach/clients/{client_id}/programme-timeline")
async def coach_programme_timeline(
    client_id: str,
    limit: int = 200,
    coach: dict = Depends(require_role("coach")),
):
    """Merge programme lifecycle events from multiple collections into one
    chronologically-sorted timeline.

    Sources:
      * users.created_at + onboarded_at            → onboarding, profile_setup
      * coaching_dna                               → dna_created, dna_updated
      * rosters                                    → roster_uploaded, roster_confirmed
      * roster_audit_log                           → roster.deleted, roster.replacement_uploaded, etc.
      * programmes                                 → programme_generated, programme_regenerated
      * workouts (completed=true)                  → workout_completed
      * workouts (needs_coach_review + edited_by)  → workout_edited
      * exercise_swaps (if collection exists)      → exercise_swapped
      * checkins                                   → checkin_completed
      * change_log                                 → coach_note_added
    """
    if not await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "client not found")

    events: list[dict[str, Any]] = []

    # users → onboarding milestones
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if user:
        if user.get("created_at"):
            events.append({
                "at": user["created_at"], "kind": "onboarding.started",
                "actor": "client",
                "title": "Client onboarded",
                "detail": "Account created + welcome flow completed.",
            })
        if user.get("onboarded_at"):
            events.append({
                "at": user["onboarded_at"], "kind": "assessment.completed",
                "actor": "client",
                "title": "Coaching DNA assessment completed",
                "detail": "Adaptive assessment finalised — profile handoff applied.",
            })

    # coaching_dna versions
    async for dna in db.coaching_dna.find({"user_id": client_id}, {"_id": 0}).sort("created_at", 1):
        events.append({
            "at": dna.get("created_at") or dna.get("updated_at"),
            "kind": "dna.version",
            "actor": dna.get("generated_by") or "system",
            "title": f"Coaching DNA v{dna.get('version') or 1} created",
            "detail": dna.get("primary_goal") or dna.get("motivation_style") or "",
            "meta": {"dna_id": dna.get("id"), "version": dna.get("version")},
        })

    # rosters
    async for r in db.rosters.find({"user_id": client_id}, {"_id": 0}).sort("created_at", 1):
        events.append({
            "at": r.get("created_at"),
            "kind": "roster.uploaded",
            "actor": "client",
            "title": f"Roster uploaded (v{r.get('version') or 1})",
            "detail": f"{r.get('week_start') or r.get('start_date') or '?'} → {r.get('week_end') or r.get('end_date') or '?'}",
            "meta": {"roster_id": r.get("id"), "status": r.get("status")},
        })
        if r.get("confirmed_at"):
            events.append({
                "at": r["confirmed_at"], "kind": "roster.confirmed",
                "actor": "client",
                "title": "Roster confirmed",
                "detail": "Programme generation authorised.",
                "meta": {"roster_id": r.get("id")},
            })

    # roster audit log
    async for a in db.roster_audit_log.find({"user_id": client_id}, {"_id": 0}).sort("at", 1):
        events.append({
            "at": a.get("at"),
            "kind": f"roster.{a.get('event', 'audit')}",
            "actor": a.get("actor") or "client",
            "title": (a.get("event") or "roster event").replace(".", " · ").title(),
            "detail": ", ".join([f"{k}: {v}" for k, v in (a.get("meta") or {}).items()][:4]) or "",
            "meta": a.get("meta"),
        })

    # programmes
    async for p in db.programmes.find({"user_id": client_id}, {"_id": 0}).sort("created_at", 1):
        events.append({
            "at": p.get("created_at"),
            "kind": "programme.generated",
            "actor": "system",
            "title": f"Programme generated — {p.get('goal_label') or p.get('goal_key') or 'plan'} · v{p.get('version_number') or 1}",
            "detail": f"phase: {(p.get('phase') or {}).get('label') or (p.get('phase') or {}).get('key') or '—'} · target: {p.get('target_sessions_per_week') or '?'}/wk",
            "meta": {"programme_id": p.get("id"), "validation_status": p.get("validation_status")},
        })
        if p.get("validation_status") and p.get("validation_status") != "ok":
            events.append({
                "at": p.get("created_at"),
                "kind": "programme.validation_flag",
                "actor": "system",
                "title": "Programme validation flag",
                "detail": ", ".join(p.get("validation_errors") or [])[:180] or ", ".join(p.get("validation_warnings") or [])[:180],
                "meta": {"programme_id": p.get("id")},
            })

    # workouts — completed
    async for w in db.workouts.find({"user_id": client_id, "completed": True}, {"_id": 0}).sort("date", 1).limit(200):
        events.append({
            "at": w.get("completed_at") or w.get("date"),
            "kind": "workout.completed",
            "actor": "client",
            "title": f"Completed · {w.get('title') or 'Workout'}",
            "detail": f"{w.get('focus') or ''} · {w.get('duration_min') or 0}min",
            "meta": {"workout_id": w.get("id"), "focus": w.get("focus")},
        })

    # workouts — coach-edited (from change_log)
    async for c in db.change_log.find(
        {"client_id": client_id, "category": {"$in": ["workout", "programme", "roster", "coach_note"]}},
        {"_id": 0},
    ).sort("at", 1).limit(200):
        events.append({
            "at": c.get("at"),
            "kind": f"{c.get('category')}.{c.get('kind') or 'edit'}",
            "actor": c.get("actor") or "coach",
            "title": c.get("title") or "Coach change",
            "detail": c.get("description") or "",
            "meta": c.get("meta"),
        })

    # checkins
    async for c in db.checkins.find({"user_id": client_id}, {"_id": 0}).sort("created_at", 1).limit(60):
        events.append({
            "at": c.get("created_at"),
            "kind": "checkin.completed",
            "actor": "client",
            "title": "Weekly check-in submitted",
            "detail": (c.get("summary") or "")[:180],
            "meta": {"checkin_id": c.get("id")},
        })

    # Sort DESC by `at`
    def _key(e: dict) -> str:
        return str(e.get("at") or "")

    events.sort(key=_key, reverse=True)
    events = [e for e in events if e.get("at")][:limit]

    return {"timeline": events, "count": len(events)}
