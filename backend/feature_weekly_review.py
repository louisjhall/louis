"""
Iter 94w — Sunday Weekly Review from Louis.

Endpoints:
  GET  /weekly-review/current            — this week's review payload (auto-built if missing).
  POST /weekly-review/checkin-complete   — mark check-in done.
  POST /weekly-review/progress-complete  — mark progress-tab update done.
  POST /weekly-review/regenerate         — rebuild the message (client or coach).
  GET  /admin/weekly-reviews             — coach list of this week's reviews across all clients.

The review computes real training / nutrition / habit / progress stats,
builds a Louis-voiced message, and — when the client marks BOTH check-in
and progress complete — opens an `exercise_media_review`-style coach task
titled "Weekly video review ready: <Client>".

All copy is supportive, no shaming, no AI wording.
"""
from __future__ import annotations
import datetime as _dt
import logging
from typing import Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from server import (
    api, current_user, require_role, db, new_id, now_iso, _create_coach_task,
)

logger = logging.getLogger("crewfit.weekly_review")


def _first_name(name: Optional[str]) -> str:
    n = (name or "").strip().split(" ")[0] if name else ""
    return n or "there"


def _week_bounds(today: _dt.date) -> tuple[_dt.date, _dt.date]:
    """ISO week: Monday → Sunday. `today` inclusive."""
    monday = today - _dt.timedelta(days=today.weekday())
    return monday, monday + _dt.timedelta(days=6)


def _detect_goal(profile: dict) -> str:
    hay = " ".join([
        str(profile.get("main_goal_key") or ""),
        str(profile.get("primary_goal") or ""),
    ]).lower()
    if any(k in hay for k in ("fat_loss", "weight_loss", "body_composition", "recomp")):
        return "fat_loss"
    if any(k in hay for k in ("running", "run", "marathon", "endurance")):
        return "running"
    if any(k in hay for k in ("strength", "muscle", "hypertrophy")):
        return "strength"
    if any(k in hay for k in ("return_to_training", "injury")):
        return "return_to_training"
    return "health"


async def _training_stats(uid: str, ws: _dt.date, we: _dt.date) -> dict:
    q = {"user_id": uid, "date": {"$gte": ws.isoformat(), "$lte": we.isoformat()}}
    planned = await db.workouts.count_documents(q)
    completed = await db.workouts.count_documents({**q, "completed": True})
    skipped = await db.workouts.count_documents({**q, "skipped": True})
    missed = await db.workouts.count_documents({
        **q, "completed": {"$ne": True}, "skipped": {"$ne": True},
        "date": {"$gte": ws.isoformat(), "$lt": _dt.date.today().isoformat()},
    }) if ws <= _dt.date.today() else 0
    recovered = await db.workouts.count_documents({**q, "recovered_from_date": {"$exists": True, "$ne": None}})
    key_planned = await db.workouts.count_documents({**q, "key_session": True})
    key_done = await db.workouts.count_documents({**q, "key_session": True, "completed": True})
    adherence = round((completed / planned) * 100) if planned else None
    return {
        "planned": planned, "completed": completed, "missed": missed,
        "skipped": skipped, "recovered": recovered,
        "key_planned": key_planned, "key_completed": key_done,
        "adherence_pct": adherence,
    }


async def _nutrition_stats(uid: str, ws: _dt.date, we: _dt.date) -> dict:
    if not hasattr(db, "nutrition_logs"):
        return {"days_logged": 0, "avg_calories": 0, "avg_protein_g": 0, "days_hit_protein": 0}
    rows = await db.nutrition_logs.find({
        "user_id": uid, "date_local": {"$gte": ws.isoformat(), "$lte": we.isoformat()},
    }, {"_id": 0}).to_list(2000)
    by_date: dict[str, dict] = {}
    for r in rows:
        d = r.get("date_local")
        by_date.setdefault(d, {"cal": 0.0, "pro": 0.0})
        by_date[d]["cal"] += float(r.get("calories") or 0)
        by_date[d]["pro"] += float(r.get("protein_g") or 0)
    days_logged = len(by_date)
    tgt = await db.nutrition_targets.find_one({"user_id": uid}, {"_id": 0}) if hasattr(db, "nutrition_targets") else None
    pro_tgt = float((tgt or {}).get("protein_g") or 0)
    days_hit = sum(1 for v in by_date.values() if pro_tgt and v["pro"] >= pro_tgt * 0.9)
    return {
        "days_logged": days_logged,
        "avg_calories": round(sum(v["cal"] for v in by_date.values()) / days_logged) if days_logged else 0,
        "avg_protein_g": round(sum(v["pro"] for v in by_date.values()) / days_logged) if days_logged else 0,
        "days_hit_protein": days_hit,
    }


async def _habit_stats(uid: str, ws: _dt.date, we: _dt.date) -> dict:
    if not hasattr(db, "habits_daily"):
        return {"completed": 0, "planned": 0, "pct": None}
    planned = await db.habits_daily.count_documents({
        "user_id": uid, "date": {"$gte": ws.isoformat(), "$lte": we.isoformat()},
    })
    completed = await db.habits_daily.count_documents({
        "user_id": uid, "date": {"$gte": ws.isoformat(), "$lte": we.isoformat()}, "completed": True,
    })
    pct = round((completed / planned) * 100) if planned else None
    return {"completed": completed, "planned": planned, "pct": pct}


async def _roster_summary(uid: str, ws: _dt.date, we: _dt.date) -> str:
    r = await db.rosters.find_one({"user_id": uid, "status": "active"}, {"_id": 0}, sort=[("created_at", -1)])
    if not r:
        return ""
    layovers, nights, long_haul = [], 0, 0
    for d in (r.get("days") or []):
        ds = str(d.get("date") or "")[:10]
        try:
            dd = _dt.date.fromisoformat(ds)
        except Exception:
            continue
        if not (ws <= dd <= we):
            continue
        dt = str(d.get("day_type") or "").lower()
        if "night" in dt or "red_eye" in dt: nights += 1
        if "long_haul" in dt: long_haul += 1
        if d.get("layover_city"): layovers.append(d.get("layover_city"))
    bits = []
    if long_haul: bits.append(f"{long_haul} long-haul day{'s' if long_haul != 1 else ''}")
    if nights: bits.append(f"{nights} night duty{'ies' if nights != 1 else ''}")
    if layovers: bits.append(f"layover in {layovers[0]}")
    return "Your roster included " + ", ".join(bits) + "." if bits else ""


def _training_line(t: dict, goal: str) -> str:
    if not t["planned"]:
        return "No sessions planned this week."
    base = f"You completed {t['completed']} of {t['planned']} planned sessions this week."
    if t["adherence_pct"] is not None and t["adherence_pct"] >= 90:
        base += " Really solid week."
    elif t["missed"] and t["key_planned"] and t["key_completed"] < t["key_planned"]:
        miss_key = t["key_planned"] - t["key_completed"]
        base += f" You missed {miss_key} key session{'s' if miss_key != 1 else ''}, but roster can get in the way — we'll take that into account."
    if goal == "running" and t["completed"]:
        base += " Nice work getting the runs in around your roster."
    return base


def _nutrition_line(n: dict, goal: str) -> str:
    if n["days_logged"] == 0:
        return "You haven't logged food this week yet — logging even a few days gives me useful data to review."
    line = f"You logged food on {n['days_logged']} day{'s' if n['days_logged'] != 1 else ''}."
    if n["avg_protein_g"]:
        line += f" Protein averaged {n['avg_protein_g']}g/day."
    if goal == "fat_loss" and n["days_logged"] < 5:
        line += " Aim for a couple more logged days next week — that's the biggest lever."
    if goal == "strength" and n["days_hit_protein"] < 3:
        line += " Protein target was hit on fewer days than ideal — worth focusing on next week."
    return line


def _habit_line(h: dict) -> str:
    if not h["planned"]:
        return ""
    if h["pct"] is None:
        return ""
    return f"You completed {h['pct']}% of your daily habits."


def _progress_line(has_progress: bool) -> str:
    if has_progress:
        return "Progress data is up to date — thanks."
    return "I need your progress update before I can review the full picture."


async def _has_progress_this_week(uid: str, ws: _dt.date, we: _dt.date) -> bool:
    collections = ["body_metrics", "progress_photos", "running_metrics", "strength_metrics"]
    for c in collections:
        col = getattr(db, c, None)
        if col is None: continue
        cnt = await col.count_documents({
            "user_id": uid, "date": {"$gte": ws.isoformat(), "$lte": we.isoformat()},
        })
        if cnt: return True
    return False


async def _build_review(user: dict, ws: _dt.date, we: _dt.date) -> dict:
    profile = user.get("profile") or {}
    goal = _detect_goal(profile)
    t = await _training_stats(user["id"], ws, we)
    n = await _nutrition_stats(user["id"], ws, we)
    h = await _habit_stats(user["id"], ws, we)
    roster = await _roster_summary(user["id"], ws, we)
    has_progress = await _has_progress_this_week(user["id"], ws, we)

    low_data = t["planned"] == 0 and n["days_logged"] == 0 and (h["planned"] or 0) == 0
    lines: list[str] = []
    lines.append(f"Hi {_first_name(user.get('name'))}, here's your CrewFit weekly review so far.")
    lines.append("")
    if low_data:
        lines.append("I don't have enough data logged yet to properly review your training, nutrition and progress this week.")
    else:
        lines.append("Training:")
        lines.append(_training_line(t, goal))
        lines.append("")
        lines.append("Nutrition:")
        lines.append(_nutrition_line(n, goal))
        hl = _habit_line(h)
        if hl:
            lines.append("")
            lines.append("Habits:")
            lines.append(hl)
        if roster:
            lines.append("")
            lines.append("Roster:")
            lines.append(roster)
        lines.append("")
        lines.append("Progress:")
        lines.append(_progress_line(has_progress))
    lines.append("")
    lines.append("Please complete your weekly check-in and update your Progress tab today.")
    lines.append("Once that's done, I'll review your week properly and come back with a short video for you.")
    lines.append("")
    lines.append("Louis")

    return {
        "user_id": user["id"],
        "week_start": ws.isoformat(),
        "week_end": we.isoformat(),
        "goal_class": goal,
        "training": t,
        "nutrition": n,
        "habits": h,
        "roster_summary": roster,
        "has_progress": has_progress,
        "message_lines": lines,
        "checkin_status": "incomplete",
        "progress_status": "complete" if has_progress else "incomplete",
        "review_ready_for_louis": False,
        "video_review_status": "not_ready",
        "coach": {"name": "Louis Hall", "role": "CrewFit Coach"},
        "updated_at": now_iso(),
    }


async def _get_or_build(user: dict) -> dict:
    today = _dt.date.today()
    ws, we = _week_bounds(today)
    existing = await db.weekly_reviews.find_one(
        {"user_id": user["id"], "week_start": ws.isoformat()}, {"_id": 0},
    )
    if existing:
        # Refresh derived data (progress may have changed) but preserve statuses.
        cand = await _build_review(user, ws, we)
        merged = {**existing, **{
            "training": cand["training"], "nutrition": cand["nutrition"], "habits": cand["habits"],
            "roster_summary": cand["roster_summary"], "has_progress": cand["has_progress"],
            "message_lines": cand["message_lines"], "updated_at": now_iso(),
        }}
        await db.weekly_reviews.update_one({"user_id": user["id"], "week_start": ws.isoformat()}, {"$set": merged})
        return merged
    doc = await _build_review(user, ws, we)
    doc["id"] = new_id()
    doc["created_at"] = now_iso()
    await db.weekly_reviews.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _maybe_create_video_task(user: dict, review: dict) -> Optional[str]:
    """Create or reuse the weekly-video-review coach task.

    Returns the actual coach-task id (new or existing) so the frontend
    can deep-link into it. Idempotent: if the review already has a
    stored `video_task_id` that points to a live coach task, we reuse it;
    if the stored id is stale/missing but an open task exists for the
    same week we adopt it; otherwise we create a fresh task.
    """
    if review.get("checkin_status") != "complete": return None
    if review.get("progress_status") != "complete": return None

    uid = user["id"]
    week_start = review["week_start"]

    # 1) Fast-path: stored task id → verify it still exists.
    stored = review.get("video_task_id")
    if isinstance(stored, str) and stored:
        exists = await db.coach_tasks.find_one({"id": stored}, {"id": 1})
        if exists:
            return stored

    # 2) Look for any live task for this client + week (adopt / dedupe).
    live = await db.coach_tasks.find_one(
        {
            "user_id": uid,
            "task_type": "weekly_video_review",
            "payload.week_start": week_start,
            "status": {"$in": ["todo", "in_progress", "snoozed"]},
        },
        {"id": 1},
    )
    if live and live.get("id"):
        task_id = live["id"]
        await db.weekly_reviews.update_one(
            {"user_id": uid, "week_start": week_start},
            {"$set": {
                "video_task_id": task_id,
                "video_review_status": "ready",
                "review_ready_for_louis": True,
                "review_ready_at": review.get("review_ready_at") or now_iso(),
            }},
        )
        return task_id

    # 3) Create a fresh task and store its id.
    try:
        task_id = await _create_coach_task(
            user, "weekly_video_review",
            f"Weekly video review ready: {user.get('name') or user.get('email')}",
            f"Both check-in and progress are complete. Adherence: {review['training'].get('adherence_pct')}%. Nutrition days: {review['nutrition'].get('days_logged')}.",
            priority="normal",
            category="weekly_review",
            payload={
                "user_id": uid,
                "week_start": week_start,
                "training": review["training"], "nutrition": review["nutrition"],
                "habits": review["habits"], "goal_class": review.get("goal_class"),
            },
        )
        await db.weekly_reviews.update_one(
            {"user_id": uid, "week_start": week_start},
            {"$set": {
                "video_task_id": task_id,
                "video_review_status": "ready",
                "review_ready_for_louis": True,
                "review_ready_at": now_iso(),
            }},
        )
        return task_id
    except Exception:
        logger.exception("failed to create weekly video task")
        return None


@api.get("/weekly-review/current")
async def weekly_review_current(user: dict = Depends(current_user)):
    # Iter 145 — unified read: if this week's check-in already carries a
    # weekly_review_snapshot, serve that as the primary record. Falls back
    # to the legacy weekly_reviews collection for pre-unification weeks.
    # No new writes are made to `weekly_reviews` from this path — new
    # aggregations are written directly onto the check-in row at submit
    # time. Historical rows remain readable via /admin/weekly-reviews.
    today = _dt.date.today()
    ws, we = _week_bounds(today)
    ci = await db.check_ins.find_one(
        {"user_id": user["id"], "week_start": ws.isoformat()},
        {"_id": 0},
    )
    snap = (ci or {}).get("weekly_review_snapshot") if ci else None
    if ci and snap:
        return {
            "id": ci.get("id"),
            "user_id": user["id"],
            "week_start": ci.get("week_start"),
            "week_end": ci.get("week_end"),
            "training": snap.get("training"),
            "nutrition": snap.get("nutrition"),
            "habits": snap.get("habits"),
            "roster_summary": snap.get("roster_summary"),
            "has_progress": snap.get("has_progress"),
            "checkin_status": "complete",
            "atlas_client_summary": ci.get("atlas_client_summary"),
            "next_week_focus": ci.get("next_week_focus"),
            "weekly_video_status": ci.get("weekly_video_status"),
            "weekly_video_id": ci.get("weekly_video_id"),
            "source": "unified_check_in",
            "created_at": ci.get("submitted_at"),
            "updated_at": snap.get("generated_at"),
        }
    # Legacy fallback — historical weeks / clients who haven't checked in
    doc = await _get_or_build(user)
    return doc


class MarkBody(BaseModel):
    note: Optional[str] = None


@api.post("/weekly-review/checkin-complete")
async def mark_checkin_complete(body: MarkBody, user: dict = Depends(current_user)):
    doc = await _get_or_build(user)
    await db.weekly_reviews.update_one(
        {"user_id": user["id"], "week_start": doc["week_start"]},
        {"$set": {
            "checkin_status": "complete",
            "checkin_completed_at": now_iso(),
            "checkin_note": body.note,
            "updated_at": now_iso(),
        }},
    )
    doc = await db.weekly_reviews.find_one({"user_id": user["id"], "week_start": doc["week_start"]}, {"_id": 0})
    await _maybe_create_video_task(user, doc)
    doc = await db.weekly_reviews.find_one({"user_id": user["id"], "week_start": doc["week_start"]}, {"_id": 0})
    return {"ok": True, "review": doc}


@api.post("/weekly-review/progress-complete")
async def mark_progress_complete(body: MarkBody, user: dict = Depends(current_user)):
    doc = await _get_or_build(user)
    await db.weekly_reviews.update_one(
        {"user_id": user["id"], "week_start": doc["week_start"]},
        {"$set": {
            "progress_status": "complete",
            "progress_updated_at": now_iso(),
            "progress_note": body.note,
            "updated_at": now_iso(),
        }},
    )
    doc = await db.weekly_reviews.find_one({"user_id": user["id"], "week_start": doc["week_start"]}, {"_id": 0})
    await _maybe_create_video_task(user, doc)
    doc = await db.weekly_reviews.find_one({"user_id": user["id"], "week_start": doc["week_start"]}, {"_id": 0})
    return {"ok": True, "review": doc}


@api.post("/weekly-review/regenerate")
async def regenerate_review(user: dict = Depends(current_user)):
    today = _dt.date.today()
    ws, we = _week_bounds(today)
    existing = await db.weekly_reviews.find_one({"user_id": user["id"], "week_start": ws.isoformat()}, {"_id": 0})
    doc = await _build_review(user, ws, we)
    if existing:
        # Keep the statuses + timestamps the client has already earned.
        for k in ("id", "created_at", "checkin_status", "checkin_completed_at", "checkin_note",
                  "progress_status", "progress_updated_at", "progress_note",
                  "video_task_id", "video_review_status", "review_ready_for_louis", "review_ready_at"):
            if k in existing:
                doc[k] = existing[k]
        await db.weekly_reviews.update_one({"user_id": user["id"], "week_start": ws.isoformat()}, {"$set": doc})
    else:
        doc["id"] = new_id()
        doc["created_at"] = now_iso()
        await db.weekly_reviews.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "review": doc}


@api.get("/admin/weekly-reviews")
async def admin_weekly_reviews(user: dict = Depends(require_role("coach"))):
    today = _dt.date.today()
    ws, _we = _week_bounds(today)
    rows = await db.weekly_reviews.find({"week_start": ws.isoformat()}, {"_id": 0}).to_list(500)
    ids = list({r.get("user_id") for r in rows})
    users = {u["id"]: u async for u in db.users.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "email": 1})}
    for r in rows:
        c = users.get(r.get("user_id")) or {}
        r["client_name"] = c.get("name")
        r["client_email"] = c.get("email")
    return {"reviews": rows or [], "count": len(rows or []), "week_start": ws.isoformat()}
