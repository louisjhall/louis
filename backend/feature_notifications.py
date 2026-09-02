"""
feature_notifications — extracted from server.py.
"""
# ---------------------------------------------------------------------------
# Auto-extracted from server.py during 2026-07 refactor.
# Endpoint contracts are IDENTICAL to the pre-refactor version.
# Imports happen from `server` after all shared symbols are defined
# (server imports this module at the very bottom).
# ---------------------------------------------------------------------------

from fastapi import Depends, HTTPException
from typing import Any, Optional
from zoneinfo import ZoneInfo
import datetime as _dt

from server import (
    api,
    db,
    current_user,
    logger,
    new_id,
    now_iso,
    send_push,
    _in_quiet_hours,
    _create_coach_task,
    _current_week_bounds,
    NotificationPermissionBody,
    NotificationSettingsBody,
)

# --- ORIGINAL SOURCE ---

# ============================================================================
# NOTIFICATIONS + REMINDERS V1
#
# Collections:
#   notifications      — in-app notification centre (bell)
#   scheduled_messages — reminder queue (existing)
#
# Rules:
#   * Every enqueue also writes an in-app notification (fallback when push is off).
#   * Deduplicate on (user_id, notif_type, related_id, dedupe_key).
#   * Respect quiet hours + notification_settings toggles + flight duty context.
#   * Never break existing scheduling. Extend _tick_reminders in place.
# ============================================================================

DEFAULT_NOTIFICATION_SETTINGS = {
    "check_ins": True,
    "habits": True,
    "workouts": True,
    "coach_messages": True,
    "weekly_videos": True,
    "roster": True,
    "programme_updates": True,
    "flight_support": True,
    "crew_base": True,
    "quiet_hours_start": "21:00",
    "quiet_hours_end": "07:00",
    "preferred_reminder_time": "07:30",
    "travel_use_current_tz": True,
    "permission_status": "not_requested",
}

# Map notif_type → category key inside notification_settings
NOTIF_CATEGORY: dict[str, str] = {
    "weekly_check_in_available": "check_ins",
    "reminder_1": "check_ins",
    "reminder_2": "check_ins",
    "reminder_last": "check_ins",
    "missed_check_in": "check_ins",
    "habit_daily": "habits",
    "workout_today": "workouts",
    "coach_message": "coach_messages",
    "coach_draft_ready": "coach_messages",
    "weekly_video_ready": "weekly_videos",
    "programme_updated": "programme_updates",
    "roster_low": "roster",
    "roster_due": "roster",
    "roster_expired": "roster",
    # Iter 123 — standby availability requests / applied standby sessions
    # are aviation-duty adjacent → route through the Roster preference.
    "standby_available": "roster",
    "standby_applied":   "roster",
    # Iter 127 — Flight Support push category (dedicated aviation toggle).
    "flight_support_pre_flight":  "flight_support",
    "flight_support_post_flight": "flight_support",
    "flight_support_layover":     "flight_support",
    "flight_support_turnaround":  "flight_support",
    # Iter 129 — Crew Base (community) push category. Independent of every
    # other toggle so clients can silence community pings without losing
    # workout / roster / flight support / messages notifications.
    "crew_base_new_post": "crew_base",
    "crew_base_reply":    "crew_base",
}


def _get_notif_settings(user: dict) -> dict:
    stored = user.get("notification_settings") or {}
    out = {**DEFAULT_NOTIFICATION_SETTINGS, **stored}
    # top-level quiet_hours override (older schema)
    if user.get("quiet_hours_start"): out["quiet_hours_start"] = user["quiet_hours_start"]
    if user.get("quiet_hours_end"):   out["quiet_hours_end"]   = user["quiet_hours_end"]
    return out


def _user_local_now(user: dict) -> tuple[_dt.datetime, str]:
    tz_name = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/London")
        tz_name = "Europe/London"
    return _dt.datetime.now(tz), tz_name


async def _is_on_duty_now(user_id: str, today: str) -> bool:
    """Heuristic — active flight/duty from today's roster row or today's workout day_type."""
    from feature_habits import _is_flight_day  # deferred to break circular import
    wk = await db.workouts.find_one({"user_id": user_id, "date": today}, {"_id": 0, "day_type": 1})
    if wk and _is_flight_day(wk.get("day_type")):
        return True
    roster = await db.rosters.find_one({"user_id": user_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if roster:
        for d in roster.get("days", []):
            if d.get("date") == today:
                dt = (d.get("type") or d.get("day_type") or "").lower()
                return any(k in dt for k in ("flight", "duty", "standby"))
    return False


def _duty_safe_body(body: str) -> str:
    """Soften copy for clients on duty."""
    return body + " (when you're off duty and settled.)"


async def enqueue_notification(
    user_id: str,
    notif_type: str,
    title: str,
    body: str,
    *,
    action_url: Optional[str] = None,
    related_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    respect_settings: bool = True,
    respect_quiet_hours: bool = False,      # in-app rows can be created any time; push may be delayed
    send_push_now: bool = True,
    idempotency_key: Optional[str] = None,
) -> Optional[dict]:
    """Create an in-app notification, dedupe by (user_id, notif_type, related_id, dedupe_key).
    Also attempts to send a push if the user granted permission and category is enabled.
    Never raises — push failure only downgrades to in-app.
    """
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        return None
    settings = _get_notif_settings(user)
    cat = NOTIF_CATEGORY.get(notif_type)
    category_enabled = True
    if respect_settings and cat and cat in settings:
        category_enabled = bool(settings.get(cat, True))
    # Dedupe query
    dedupe_query: dict[str, Any] = {"user_id": user_id, "notif_type": notif_type}
    if related_id: dedupe_query["related_id"] = related_id
    if dedupe_key: dedupe_query["dedupe_key"] = dedupe_key
    existing = await db.notifications.find_one(dedupe_query, {"_id": 0})
    if existing:
        # Refresh body/title if changed but keep read state
        await db.notifications.update_one(
            {"id": existing["id"]},
            {"$set": {"title": title, "body": body, "action_url": action_url, "updated_at": now_iso()}},
        )
        existing.update({"title": title, "body": body, "action_url": action_url, "updated_at": now_iso()})
        return existing
    # Flight-duty rewording
    on_duty = False
    if notif_type in ("workout_today", "habit_daily", "reminder_1", "reminder_2", "weekly_check_in_available"):
        try:
            local_now, _ = _user_local_now(user)
            today = local_now.date().isoformat()
            on_duty = await _is_on_duty_now(user_id, today)
        except Exception:
            on_duty = False
    final_body = _duty_safe_body(body) if on_duty else body
    doc = {
        "id": new_id(),
        "user_id": user_id,
        "notif_type": notif_type,
        "category": cat,
        "title": title,
        "body": final_body,
        "action_url": action_url,
        "related_id": related_id,
        "dedupe_key": dedupe_key,
        "flight_duty_safe": on_duty,
        "created_at": now_iso(),
        "read_at": None,
        "updated_at": now_iso(),
    }
    await db.notifications.insert_one(doc)
    doc.pop("_id", None)
    # Push (best-effort, non-blocking)
    if send_push_now and category_enabled and settings.get("permission_status") == "granted":
        try:
            await send_push(
                recipients=[user_id],
                data={"title": title, "message": final_body, **({"action_url": action_url} if action_url else {})},
                idempotency_key=idempotency_key,
            )
        except Exception as e:
            logger.warning("push failed (in-app still created): %s", e)
            await db.notifications.update_one({"id": doc["id"]}, {"$set": {"push_error": str(e)[:180]}})
    return doc


# ---- Endpoints -------------------------------------------------------------

@api.get("/notifications")
async def notifications_list(user: dict = Depends(current_user), unread_only: bool = False, limit: int = 60):
    q: dict[str, Any] = {"user_id": user["id"]}
    if unread_only:
        q["read_at"] = None
    rows = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    unread = await db.notifications.count_documents({"user_id": user["id"], "read_at": None})
    return {"notifications": rows, "unread": unread}


@api.get("/notifications/unread-count")
async def notifications_unread_count(user: dict = Depends(current_user)):
    n = await db.notifications.count_documents({"user_id": user["id"], "read_at": None})
    return {"unread": n}


@api.post("/notifications/{notif_id}/read")
async def notifications_read(notif_id: str, user: dict = Depends(current_user)):
    r = await db.notifications.update_one(
        {"id": notif_id, "user_id": user["id"]},
        {"$set": {"read_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "notification not found")
    return {"ok": True}


@api.post("/notifications/read-all")
async def notifications_read_all(user: dict = Depends(current_user)):
    now = now_iso()
    r = await db.notifications.update_many(
        {"user_id": user["id"], "read_at": None},
        {"$set": {"read_at": now}},
    )
    return {"marked": r.modified_count}


@api.get("/notifications/settings")
async def notifications_settings_get(user: dict = Depends(current_user)):
    return {"settings": _get_notif_settings(user), "defaults": DEFAULT_NOTIFICATION_SETTINGS}


@api.put("/notifications/settings")
async def notifications_settings_put(body: NotificationSettingsBody, user: dict = Depends(current_user)):
    stored = user.get("notification_settings") or {}
    updates: dict[str, Any] = {}
    for k in ("check_ins", "habits", "workouts", "coach_messages", "weekly_videos", "roster", "programme_updates", "flight_support",
              "quiet_hours_start", "quiet_hours_end", "preferred_reminder_time", "travel_use_current_tz"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v
    if not updates:
        raise HTTPException(400, "no updates")
    merged = {**stored, **updates}
    top_level: dict[str, Any] = {"notification_settings": merged}
    # Mirror quiet hours to top-level for backwards compatibility with _tick_reminders
    if "quiet_hours_start" in updates: top_level["quiet_hours_start"] = updates["quiet_hours_start"]
    if "quiet_hours_end" in updates:   top_level["quiet_hours_end"]   = updates["quiet_hours_end"]
    await db.users.update_one({"id": user["id"]}, {"$set": top_level})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {"settings": _get_notif_settings(fresh)}


@api.post("/notifications/permission")
async def notifications_permission(body: NotificationPermissionBody, user: dict = Depends(current_user)):
    if body.status not in ("granted", "denied", "not_requested"):
        raise HTTPException(400, "invalid status")
    stored = user.get("notification_settings") or {}
    stored["permission_status"] = body.status
    stored["permission_updated_at"] = now_iso()
    if body.platform:
        stored["last_platform"] = body.platform
    if body.device_info:
        stored["last_device_info"] = body.device_info
    await db.users.update_one({"id": user["id"]}, {"$set": {"notification_settings": stored}})
    return {"status": body.status}


# ---- Additional scheduled reminder ticks -----------------------------------

async def _tick_roster_and_workout_reminders() -> None:
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(2000)
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    for u in users:
        try:
            settings = _get_notif_settings(u)
            tz_name = u.get("current_time_zone") or u.get("home_time_zone") or "Europe/London"
            try: tz = ZoneInfo(tz_name)
            except Exception: continue
            local_now = now_utc.astimezone(tz)
            in_quiet = _in_quiet_hours(local_now, settings.get("quiet_hours_start", "21:00"), settings.get("quiet_hours_end", "07:00"))
            today = local_now.date().isoformat()

            # ---- Roster expiry ----
            if settings.get("roster", True) and not in_quiet:
                roster = await db.rosters.find_one({"user_id": u["id"], "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
                if roster:
                    last_dates = sorted([d.get("date") for d in roster.get("days", []) if d.get("date")])
                    if last_dates:
                        last = last_dates[-1]
                        try:
                            last_dt = _dt.date.fromisoformat(last)
                            delta = (last_dt - local_now.date()).days
                        except Exception:
                            delta = None
                        if delta is not None:
                            plan: Optional[tuple[str, str, str]] = None
                            if delta == 7:
                                plan = ("roster_low", "Roster running low",
                                        "Your roster is running low. Upload your next roster when you can.")
                            elif delta == 3:
                                plan = ("roster_due", "Roster nearly due",
                                        "Your next roster is nearly due.")
                            elif delta == 1:
                                plan = ("roster_due", "Upload your roster",
                                        "Upload your next roster so CrewFit can keep your training accurate.")
                            elif delta < 0:
                                plan = ("roster_expired", "Roster expired",
                                        "Your roster has expired. Upload your latest roster to keep your programme aligned.")
                            if plan and local_now.hour == 9 and local_now.minute < 10:
                                dedupe = f"{plan[0]}::{today}"
                                await enqueue_notification(u["id"], plan[0], plan[1], plan[2],
                                                            action_url="/roster-upload",
                                                            related_id=roster.get("id"),
                                                            dedupe_key=dedupe)

            # ---- Workout reminder ----
            if settings.get("workouts", True) and not in_quiet:
                preferred = settings.get("preferred_reminder_time") or "07:30"
                try:
                    hh, mm = int(preferred.split(":")[0]), int(preferred.split(":")[1])
                except Exception:
                    hh, mm = 7, 30
                if local_now.hour == hh and (mm <= local_now.minute < mm + 10):
                    todays_wk = await db.workouts.find_one({"user_id": u["id"], "date": today}, {"_id": 0, "id": 1, "completed": 1, "skipped": 1, "status": 1})
                    if todays_wk and not todays_wk.get("completed") and not todays_wk.get("skipped") and todays_wk.get("status") != "coach_review":
                        dedupe = f"workout_today::{today}"
                        await enqueue_notification(u["id"], "workout_today",
                                                    "CrewFit session ready",
                                                    "Your CrewFit session is ready for today.",
                                                    action_url=f"/workout/{todays_wk['id']}",
                                                    related_id=todays_wk["id"],
                                                    dedupe_key=dedupe)

            # ---- Missed check-in coach task on Tuesday morning ----
            # weekday: Monday=0, Tuesday=1
            if local_now.weekday() == 1 and local_now.hour == 9 and local_now.minute < 10:
                ws, _we = _current_week_bounds(u)
                # Compute *previous* week's start (checkins reference the just-completed week)
                try:
                    ws_prev = (_dt.date.fromisoformat(ws) - _dt.timedelta(days=7)).isoformat()
                except Exception:
                    ws_prev = ws
                already_task = await db.coach_tasks.find_one({"user_id": u["id"], "task_type": "missed_check_in",
                                                              "payload.week_start": ws_prev})
                completed = await db.check_ins.find_one({"user_id": u["id"], "week_start": ws_prev}, {"id": 1})
                if not completed and not already_task:
                    await _create_coach_task(u, "missed_check_in",
                                              f"Missed check-in · {u.get('name') or u.get('email')}",
                                              f"No check-in submitted for the week starting {ws_prev}.",
                                              priority="high",
                                              risk_level="medium",
                                              category="reviews",
                                              payload={"week_start": ws_prev})

            # Iter 145 — unified weekly check-in reminder schedule ------------
            # Client-local times, respecting quiet hours and notif toggles.
            # Dedupe keys prevent duplicate delivery on any 10-minute tick.
            # Reminders stop the moment a submission exists.
            if settings.get("check_ins", True) and not in_quiet:
                ws_this, _we_this = _current_week_bounds(u)
                submitted = await db.check_ins.find_one(
                    {"user_id": u["id"], "week_start": ws_this}, {"id": 1},
                )
                if not submitted:
                    weekday = local_now.weekday()  # Sun=6, Mon=0
                    hh = local_now.hour
                    mm = local_now.minute
                    plan_reminder: Optional[tuple[str, str, str]] = None
                    # Sunday 08:00 — "your check-in is ready"
                    if weekday == 6 and hh == 8 and mm < 10:
                        plan_reminder = ("weekly_check_in_available",
                                         "Weekly Check-in ready",
                                         "Your weekly review is ready. Takes 90 seconds — tap to complete.")
                    # Sunday 20:00 — first reminder if still incomplete
                    elif weekday == 6 and hh == 20 and mm < 10:
                        plan_reminder = ("reminder_1",
                                         "Weekly Check-in reminder",
                                         "Quick reminder — your weekly check-in is still waiting.")
                    # Monday 09:00 — final reminder
                    elif weekday == 0 and hh == 9 and mm < 10:
                        plan_reminder = ("reminder_last",
                                         "Last chance — Weekly Check-in",
                                         "Final nudge: complete your weekly check-in so Louis can prepare your video.")
                    if plan_reminder:
                        dedupe = f"{plan_reminder[0]}::{ws_this}"
                        await enqueue_notification(u["id"], plan_reminder[0],
                                                   plan_reminder[1], plan_reminder[2],
                                                   action_url="/checkin",
                                                   related_id=ws_this,
                                                   dedupe_key=dedupe)

            # ---- Coach reminder: video unrecorded for 24h ------------------
            # For every check-in with weekly_video_status == 'script_ready'
            # that was submitted > 24h ago and doesn't yet have a video row,
            # nudge the coach once (dedupe by check-in id).
            if local_now.hour == 10 and local_now.minute < 10:
                stale_cutoff = (now_utc - _dt.timedelta(hours=24)).isoformat()
                stale = await db.check_ins.find_one({
                    "user_id": u["id"],
                    "submitted_at": {"$lt": stale_cutoff},
                    "weekly_video_status": "script_ready",
                    "weekly_video_id": None,
                }, {"_id": 0, "id": 1, "user_name": 1})
                if stale:
                    ci_id = stale["id"]
                    already = await db.coach_tasks.find_one({
                        "check_in_id": ci_id,
                        "task_type": "record_weekly_video_reminder",
                    })
                    if not already:
                        await _create_coach_task(
                            u, "record_weekly_video_reminder",
                            f"Weekly video overdue · {stale.get('user_name')}",
                            "Client checked in more than 24h ago and no video has been recorded yet.",
                            priority="high",
                            category="reviews",
                            check_in_id=ci_id,
                        )
        except Exception:
            logger.exception("_tick_roster_and_workout_reminders failed for a user")


_ORIGINAL_TICK_2 = None  # removed post-refactor


# ---- Hook helpers used by other endpoints (message send, video sent, etc.) ---

async def notify_coach_message(from_user_id: str, to_user_id: str, text: str, source_message_id: Optional[str] = None) -> None:
    from_user = await db.users.find_one({"id": from_user_id}, {"_id": 0, "name": 1, "role": 1})
    if not from_user or from_user.get("role") != "coach":
        return
    await enqueue_notification(
        to_user_id, "coach_message",
        f"Message from {from_user.get('name', 'Louis')}",
        text[:120],
        action_url="/(client)/messages",
        related_id=source_message_id,
        dedupe_key=(f"coach_msg::{source_message_id}" if source_message_id else f"coach_msg::{now_iso()}"),
    )


async def notify_weekly_video_ready(
    user_id: str,
    video_id: Optional[str] = None,
    video_kind: str = "weekly",
) -> None:
    """Push + in-app when a coach sends a video to a client.

    Iter187 · Now branches on ``video_kind`` so a welcome recording gets
    'Welcome Video from Your Coach' instead of the weekly-review copy.
    Falls back to weekly for any unknown / legacy kind so existing call
    sites remain safe.
    """
    kind = (video_kind or "weekly").strip().lower()
    if kind == "welcome":
        title = "Welcome Video from Your Coach"
        body = "Your coach recorded a welcome video for you — tap to watch."
    else:
        title = "Weekly review from Louis"
        body = "Your weekly coaching review from Louis is ready."
    await enqueue_notification(
        user_id, "weekly_video_ready",
        title,
        body,
        action_url=f"/video/{video_id}" if video_id else "/(client)/home",
        related_id=video_id,
        dedupe_key=f"weekly_video::{video_id or ''}",
    )


async def notify_roster_approved(user_id: str, roster_id: Optional[str] = None) -> None:
    """Iter187 · Push + in-app when a coach approves a client's roster.

    Fires from `_do_approve` in feature_roster_coach_review. Uses the
    `programme_updated` category so it respects the same client toggle
    as other programme-life events (approvals ARE a programme-life event
    from the client's POV — "your plan is now live").
    """
    await enqueue_notification(
        user_id,
        "programme_updated",
        "Your programme is live",
        "Your programme is live — let's get to work.",
        action_url="/(client)/calendar",
        related_id=roster_id,
        dedupe_key=f"roster_approved::{roster_id or ''}",
    )


async def notify_programme_updated(user_id: str, meta: Optional[dict] = None) -> None:
    key = f"programme::{(meta or {}).get('week_start') or _dt.date.today().isoformat()}"
    await enqueue_notification(
        user_id, "programme_updated",
        "Programme updated",
        "Louis has reviewed your week and updated your plan.",
        action_url="/(client)/schedule",
        related_id=(meta or {}).get("workout_id"),
        dedupe_key=key,
    )


async def notify_coach_draft_ready(coach_id: str, client_name: str, draft_id: str) -> None:
    """In-app notification for the coach when Atlas produces a draft (V1: in-app only)."""
    await enqueue_notification(
        coach_id, "coach_draft_ready",
        f"Draft ready · {client_name}",
        "Atlas has drafted a reply. Review, edit and send.",
        action_url=f"/coach/draft/{draft_id}",
        related_id=draft_id,
        dedupe_key=f"draft::{draft_id}",
        respect_settings=False,   # coaches always see these
    )



