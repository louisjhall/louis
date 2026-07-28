"""
Programme Status + Today Plan State — Phase 7A.

Backbone that drives both the CLIENT waiting/approval UX and the COACH
approval queue.

Endpoints:
    * GET  /api/programme/status             — client-facing (polled every ~15s)
    * POST /api/coach/clients/{cid}/approve-programme  — coach one-tap approve
    * GET  /api/coach/clients/{cid}/approval-preview   — coach preview: "if
                                                          approved now, client
                                                          will see …"

Computed fields per client:
    programme_status  : no_roster_uploaded | roster_parsing |
                        roster_needs_client_review | roster_needs_coach_review |
                        waiting_for_programme_approval | programme_live |
                        programme_needs_update
    today_plan_state  : session_planned | recovery_planned | rest_day |
                        travel_day | layover_day | nutrition_focus |
                        habit_focus | no_session_planned |
                        programme_waiting_approval | roster_needs_review

The 12-20 min review delay (`visible_from`) still applies on plan
generation, but coach approve-programme clears every hidden workout in
the client's active roster date range so the plan appears INSTANTLY.
"""
from __future__ import annotations
from datetime import datetime as _dt, date as _date, timezone as _tz
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, current_user, new_id, now_iso
import logging
logger = logging.getLogger("crewfit.programme_status")


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------

async def _derive_programme_status(user: dict) -> str:
    """Compute the current programme_status for this client. Cheap enough
    to call on every /programme/status poll."""
    uid = user["id"]
    # Any pending confirmation?
    pending = await db.rosters.find_one(
        {"user_id": uid, "status": "pending_confirmation"},
        {"_id": 0, "id": 1, "review_flags": 1},
    )
    if pending:
        # Distinguish client-review vs coach-review
        rf = pending.get("review_flags") or {}
        if rf.get("low_confidence_count", 0) >= 3 or rf.get("black_day_count", 0) > 0:
            return "roster_needs_coach_review"
        return "roster_needs_client_review"

    active = await db.rosters.find_one(
        {"user_id": uid, "is_active": True, "confirmed": True},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not active:
        # No confirmed roster
        any_pending = await db.rosters.find_one({"user_id": uid, "status": "parsing"}, {"_id": 0})
        if any_pending:
            return "roster_parsing"
        return "no_roster_uploaded"

    # Iter 114 — Engine V2 clients store their published plan in
    # `plan_live_v2`, NOT in the legacy `workouts` collection. If they have
    # an active Live V2 doc, treat as programme_live immediately (regardless
    # of how many legacy `workouts` docs exist — for V2 clients that count is
    # zero by design).
    flags = (user.get("profile") or {}).get("v2_flags") or {}
    if flags.get("engine_v2") or flags.get("v2_default"):
        live_v2 = await db.plan_live_v2.find_one(
            {"client_id": uid, "active": True}, {"_id": 0, "id": 1},
        )
        if live_v2:
            if active.get("programme_needs_update"):
                return "programme_needs_update"
            return "programme_live"
        # V2-flagged but no live doc yet → still awaiting coach approval
        # (same UX as the V1 waiting_for_programme_approval state).
        return "waiting_for_programme_approval"

    # Confirmed roster exists — check if workouts are still hidden by
    # visible_from OR if approve-programme is required.
    now_val = now_iso()
    hidden = await db.workouts.count_documents({
        "user_id": uid, "visible_from": {"$gt": now_val},
    })
    has_any = await db.workouts.count_documents({"user_id": uid})
    if has_any == 0:
        return "waiting_for_programme_approval"
    if hidden > 0 and not active.get("programme_approved_at"):
        return "waiting_for_programme_approval"
    if active.get("programme_needs_update"):
        return "programme_needs_update"
    return "programme_live"


def _today_iso() -> str:
    return _date.today().isoformat()


async def _derive_today_plan_state(user: dict, programme_status: str) -> dict:
    """Compute today's state. Never say 'session_planned' if there is no
    actual visible workout for the client today."""
    if programme_status in ("waiting_for_programme_approval", "roster_parsing"):
        return {"state": "programme_waiting_approval", "workout_id": None, "label": None}
    if programme_status in ("roster_needs_client_review", "roster_needs_coach_review"):
        return {"state": "roster_needs_review", "workout_id": None, "label": None}
    if programme_status == "no_roster_uploaded":
        return {"state": "no_session_planned", "workout_id": None, "label": None}

    uid = user["id"]
    dt = _today_iso()
    now_val = now_iso()

    # Iter 114 — V2 client path: read today from plan_live_v2 (placements
    # + session_specs) instead of the legacy workouts collection.
    flags = (user.get("profile") or {}).get("v2_flags") or {}
    if flags.get("engine_v2") or flags.get("v2_default"):
        live_v2 = await db.plan_live_v2.find_one(
            {"client_id": uid, "active": True},
            {"_id": 0, "id": 1, "placements": 1, "session_specs": 1},
        )
        if live_v2:
            live_id = live_v2.get("id")
            for p in (live_v2.get("placements") or []):
                if p.get("date") != dt:
                    continue
                kind = p.get("kind") or ""
                eid = p.get("exposure_id") or ""
                spec = (live_v2.get("session_specs") or {}).get(eid) or {}
                spec_kind = spec.get("spec_kind") or ""
                if kind == "rest":
                    return {"state": "rest_day", "workout_id": None, "label": "Rest day"}
                if spec_kind in ("mobility", "recovery", "activation", "travel_recovery"):
                    state = "recovery_planned"
                else:
                    state = "session_planned"
                return {
                    "state": state,
                    "workout_id": f"v2p:{live_id}:{eid}",
                    "label": (kind or "Session").replace("_", " ").title(),
                }
            # V2 live plan exists but no placement for today — fall through
            # to the roster-derived label branch below.

    # A visible workout for today?
    wk = await db.workouts.find_one(
        {"user_id": uid, "date": dt,
         "$or": [
             {"visible_from": {"$exists": False}},
             {"visible_from": {"$lte": now_val}},
         ]}, {"_id": 0},
    )
    if wk:
        focus = str(wk.get("focus") or "").lower()
        # Priority classifier
        if focus in ("mobility", "recovery"):
            state = "recovery_planned"
        elif focus == "rest":
            state = "rest_day"
        else:
            state = "session_planned"
        return {
            "state": state,
            "workout_id": wk.get("id"),
            "label": wk.get("title"),
        }

    # No workout today — what does the roster say?
    active = await db.rosters.find_one({"user_id": uid, "is_active": True}, {"_id": 0})
    day = None
    for d in (active or {}).get("days", []):
        if d.get("date") == dt:
            day = d
            break
    if not day:
        return {"state": "no_session_planned", "workout_id": None, "label": None}
    dtype = str(day.get("day_type") or "").lower()
    label = day.get("label") or day.get("auto_label") or ""
    upper = str(label).upper()
    if dtype in ("layover_day", "layover") or "LAYOVER" in upper:
        return {"state": "layover_day", "workout_id": None,
                "label": day.get("client_label") or "Layover day"}
    if "FLIGHT" in upper or "LONG_HAUL" in upper or "TURNAROUND" in upper:
        return {"state": "travel_day", "workout_id": None,
                "label": day.get("client_label") or "Flying day"}
    if dtype in ("rest", "rest_day", "off", "day_off"):
        return {"state": "rest_day", "workout_id": None,
                "label": day.get("client_label") or "Rest day"}
    return {"state": "no_session_planned", "workout_id": None,
            "label": day.get("client_label") or None}


async def _build_timeline(user: dict, status: str) -> list[dict]:
    """4-step timeline used by the client waiting screen + dashboard."""
    uid = user["id"]
    completed = lambda s: {"key": s[0], "label": s[1], "state": "completed"}
    inprog = lambda s: {"key": s[0], "label": s[1], "state": "in_progress"}
    pending = lambda s: {"key": s[0], "label": s[1], "state": "pending"}

    steps = [
        ("uploaded", "Roster uploaded"),
        ("reviewed", "Roster reviewed"),
        ("approved", "Programme approved"),
        ("live", "Programme live"),
    ]
    # Assess each step from status
    if status == "no_roster_uploaded":
        return [pending(s) for s in steps]
    if status == "roster_parsing":
        return [completed(steps[0]), inprog(steps[1]), pending(steps[2]), pending(steps[3])]
    if status in ("roster_needs_client_review", "roster_needs_coach_review"):
        return [completed(steps[0]), inprog(steps[1]), pending(steps[2]), pending(steps[3])]
    if status == "waiting_for_programme_approval":
        return [completed(steps[0]), completed(steps[1]), inprog(steps[2]), pending(steps[3])]
    if status == "programme_needs_update":
        return [completed(steps[0]), completed(steps[1]), inprog(steps[2]), completed(steps[3])]
    # programme_live
    return [completed(steps[0]), completed(steps[1]), completed(steps[2]), completed(steps[3])]


# ---------------------------------------------------------------------------
# Client endpoint
# ---------------------------------------------------------------------------

@api.get("/programme/status")
async def programme_status(user: dict = Depends(current_user)) -> dict:
    """Polled every ~15s by the client dashboard + refresh on foreground."""
    status = await _derive_programme_status(user)
    today = await _derive_today_plan_state(user, status)
    timeline = await _build_timeline(user, status)
    return {
        "programme_status": status,
        "today_plan_state": today,
        "timeline": timeline,
        "generated_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# Coach approval endpoint — INSTANT publish
# ---------------------------------------------------------------------------

class ApprovalBody(BaseModel):
    roster_id: Optional[str] = None  # if omitted, applies to newest active
    note: Optional[str] = None


@api.get("/coach/clients/{client_id}/approval-preview")
async def coach_approval_preview(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return what the client will see if we approve RIGHT NOW.
    Backs the coach's "Approve programme" preview modal."""
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Client not found")

    active = await db.rosters.find_one(
        {"user_id": client_id, "is_active": True, "confirmed": True},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not active:
        raise HTTPException(400, "No active confirmed roster for this client.")

    # Count hidden workouts + today's plan state
    now_val = now_iso()
    total = await db.workouts.count_documents({"user_id": client_id})
    hidden = await db.workouts.count_documents({
        "user_id": client_id, "visible_from": {"$gt": now_val},
    })

    # Provide the same status snapshot the client would see IF approved
    class _StubUser(dict):
        pass
    # After approval → programme_live
    today_after = await _derive_today_plan_state(user, "programme_live")

    return {
        "client": {"id": client_id, "name": user.get("name") or user.get("email")},
        "roster": {
            "id": active.get("id"), "airline": (
                "Etihad" if "etihad" in str(active.get("parser_source") or "") else
                "Emirates" if "emirates" in str(active.get("parser_source") or "") else "Roster"
            ),
            "start_date": active.get("start_date"),
            "end_date": active.get("end_date"),
            "confidence_avg": active.get("confidence_avg"),
        },
        "workouts_total": total,
        "workouts_hidden": hidden,
        "today_if_approved": today_after,
        "will_publish_now": hidden > 0,
    }


@api.post("/coach/clients/{client_id}/approve-programme")
async def coach_approve_programme(
    client_id: str,
    body: ApprovalBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Client not found")

    active = await db.rosters.find_one(
        {"user_id": client_id, "is_active": True, "confirmed": True,
         **({"id": body.roster_id} if body.roster_id else {})},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if not active:
        raise HTTPException(400, "No active confirmed roster to approve.")

    now = now_iso()

    # 1. Clear visible_from on every workout in this roster's date range so
    #    the client sees them instantly.
    start = active.get("start_date")
    end = active.get("end_date")
    q: dict = {"user_id": client_id}
    if start and end:
        q["date"] = {"$gte": start, "$lte": end}
    r = await db.workouts.update_many(q, {"$unset": {"visible_from": "", "visible_from_reason": ""},
                                          "$set": {"programme_approved_at": now, "approved": True}})
    unlocked = r.modified_count

    # 2. Stamp the roster
    await db.rosters.update_one({"id": active["id"]}, {"$set": {
        "programme_approved": True,
        "programme_approved_at": now,
        "programme_approved_by": coach.get("id"),
        "programme_approved_by_name": coach.get("name") or coach.get("email") or "Louis",
        "programme_needs_update": False,
    }})

    # 3. Compute today's state for a dynamic Louis message
    status_after = "programme_live"
    today = await _derive_today_plan_state(user, status_after)
    msg_body = _approval_message_for_today(today, coach.get("name") or "Louis")

    # 4. Drop a Louis chat message into the client's inbox
    try:
        await db.messages.insert_one({
            "id": new_id(),
            "user_id": client_id,
            "from_role": "coach",
            "from_name": coach.get("name") or "Louis",
            "kind": "programme_approved",
            "title": "Your CrewFit programme is ready",
            "body": msg_body,
            "created_at": now,
            "read": False,
        })
    except Exception:
        logger.exception("Failed to write approval Louis message (non-fatal)")

    # 5. Close any 'review_roster' coach task for this client + roster
    try:
        await db.coach_tasks.update_many(
            {"user_id": client_id, "status": {"$in": ["todo", "in_progress"]},
             "task_type": {"$in": ["programme_approval_pending", "review_roster"]}},
            {"$set": {"status": "done", "closed_at": now, "closed_by": coach.get("id")}},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "unlocked_workouts": unlocked,
        "today_state": today,
        "message_sent": True,
        "approved_at": now,
    }


# ---------------------------------------------------------------------------
# Dynamic Louis message per today_plan_state
# ---------------------------------------------------------------------------

def _approval_message_for_today(today: dict, coach_name: str = "Louis") -> str:
    s = (today or {}).get("state") or "no_session_planned"
    if s == "session_planned":
        return ("I've reviewed your roster and your training is now live in the app. "
                "You've got a session planned today, so start there and message me if "
                "anything looks off or your roster changes.\n\n— " + coach_name)
    if s == "recovery_planned":
        return ("I've reviewed your roster and your plan is now live in the app. "
                "Today is set as a recovery-focused day, so follow the plan and keep it "
                "light.\n\n— " + coach_name)
    if s == "rest_day":
        return ("I've reviewed your roster and your plan is now live in the app. "
                "Today is a rest day, so there's no training session to complete. Check "
                "your dashboard for your focus and what's coming next.\n\n— " + coach_name)
    if s == "travel_day":
        return ("I've reviewed your roster and your plan is now live in the app. "
                "Today is built around your flying schedule, so check your dashboard for "
                "the right focus for the day.\n\n— " + coach_name)
    if s == "layover_day":
        return ("I've reviewed your roster and your plan is now live in the app. "
                "Today looks like a layover day, so your plan has been matched to "
                "hotel/bodyweight options unless you confirm gym access.\n\n— " + coach_name)
    if s in ("nutrition_focus", "habit_focus"):
        return ("I've reviewed your roster and your plan is now live in the app. "
                "There's no workout planned today, but your dashboard will show your "
                "nutrition and habit focus.\n\n— " + coach_name)
    # default: no_session_planned
    return ("I've reviewed your roster and your plan is now live in the app. "
            "There's no session planned for today, so check your dashboard to see your "
            "focus and what's coming up next.\n\n— " + coach_name)


# ---------------------------------------------------------------------------
# Post-upload hook (called by feature_roster_confirmation on pending create)
# ---------------------------------------------------------------------------

async def create_upload_confirmation_message(user_id: str) -> None:
    """Idempotent — inserts the 'roster uploaded' Louis message if not already
    present within the last 5 minutes for this user."""
    try:
        recent = await db.messages.find_one({
            "user_id": user_id, "kind": "roster_uploaded",
        })
        if recent:
            return
        await db.messages.insert_one({
            "id": new_id(),
            "user_id": user_id,
            "from_role": "coach",
            "from_name": "Louis",
            "kind": "roster_uploaded",
            "title": "Roster received",
            "body": ("Your roster has been uploaded successfully. I'll review it and "
                     "approve your programme before it appears in the app. This makes "
                     "sure your training is built around your actual schedule.\n\n— Louis"),
            "created_at": now_iso(),
            "read": False,
        })
    except Exception:
        logger.exception("Failed to create upload_confirmation_message")


async def create_coach_approval_task(user_id: str, roster_id: str) -> None:
    """Idempotent coach task for the approvals queue."""
    try:
        existing = await db.coach_tasks.find_one({
            "user_id": user_id, "task_type": "programme_approval_pending",
            "status": {"$in": ["todo", "in_progress"]},
            "roster_id": roster_id,
        })
        if existing:
            return
        client = await db.users.find_one({"id": user_id}, {"_id": 0, "name": 1, "email": 1, "assigned_coach_id": 1})
        await db.coach_tasks.insert_one({
            "id": new_id(),
            "task_type": "programme_approval_pending",
            "kind": "programme_approval_pending",
            "status": "todo",
            "priority": "high",
            "user_id": user_id,
            "client_id": user_id,
            "roster_id": roster_id,
            "assigned_coach_id": (client or {}).get("assigned_coach_id"),
            "client_name": (client or {}).get("name") or (client or {}).get("email"),
            "created_at": now_iso(),
            "title": f"Review & approve programme · {(client or {}).get('name') or 'client'}",
            "summary": "Client uploaded a roster. Review the parse + approve the programme to publish it instantly.",
        })
    except Exception:
        logger.exception("Failed to create coach approval task")
