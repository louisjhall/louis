"""
Coach Live Feed — Phase 2.

The main coach dashboard needs a real-time cross-client view of upcoming
workouts so Louis can quickly review, edit, swap, or fix issues without
opening each client one by one.

Endpoints:
    * GET /api/coach/live-feed
        ?days=5              — window (default 5, max 14)
        &filter=all|needs_review|needs_media|heavy_duty|layover
              |post_night|missed|today
        &colour=green|amber|red|black
        &client=<user_id>
        &airline=etihad|emirates

Returns:
    {
      "generated_at": "...",
      "range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 5},
      "summary": {
        "total": 12, "today": 4, "tomorrow": 3,
        "needs_review": 2, "needs_media": 5,
        "heavy_duty": 3, "layover_sessions": 2,
        "post_night_recovery": 1, "missed": 0,
        "by_client": {"Pietro Sangermano": 6, ...},
        "by_airline": {"Etihad": 8, "Emirates": 4},
        "by_colour": {"green": 4, "amber": 5, "red": 3, "black": 0},
      },
      "items": [
        {
          "workout_id": ...,
          "client": {"id":..., "name":..., "photo_url":..., "email":...,
                     "airline":..., "role":...},
          "date": "2026-08-13",
          "day_offset": 0,  // 0=today, 1=tomorrow, etc
          "day_offset_label": "Today",
          "roster_day": {
            "day_type":..., "client_label":..., "training_colour":...,
            "blocked":[...], "equipment_assumption":..., "reason":...,
            "layover_city":..., "hotel_name":..., "flights":[...],
            "report_time":..., "release_time":..., "needs_review":...,
          },
          "workout": {
            "title":..., "focus":..., "duration_min":...,
            "day_load":..., "exercise_count":..., "missing_media_count":...,
            "approved":..., "coach_locked":..., "completed":...,
            "rationale":..., "parser_enforced":...,
          },
          "flags": ["today","needs_media","heavy_duty",...],
          "priority": 87,   // higher = more urgent
        },
        ...
      ]
    }
"""
from __future__ import annotations
import datetime as _dt
from collections import Counter
from typing import Any, Optional

from fastapi import Depends, Query
from server import api, db, require_role
import logging
logger = logging.getLogger("crewfit.live_feed")


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------

# Each flag contributes points. Higher = shows first. Weights tuned so the
# priority ranking honours the coach spec:
#   1. Today missing media
#   2. Today needs review
#   3. Roster uncertain
#   4. RED / heavy duty
#   5. Layover unknown equipment
#   6. Tomorrow needs review
#   7. Regular upcoming
_FLAG_WEIGHTS: dict[str, int] = {
    "missed": 100,
    "today_missing_media": 90,
    "today_needs_review": 85,
    "roster_uncertain": 78,
    "heavy_duty": 70,
    "layover_unknown_equip": 55,
    "today": 55,
    "tomorrow_needs_review": 45,
    "tomorrow": 30,
    "needs_media": 25,
    "needs_review": 20,
    "layover": 10,
    "post_night_recovery": 8,
    "hotel_gym_unknown": 5,
    "edited_by_louis": 3,
    "ready": 1,
}


def _colour_of(day: dict) -> str:
    c = str(day.get("training_colour") or "green").lower()
    if c not in ("green", "amber", "red", "black"):
        return "green"
    return c


def _airline_of(client: dict, roster: dict | None) -> str:
    if roster:
        src = str(roster.get("parser_source") or "").lower()
        if "etihad" in src: return "Etihad"
        if "emirates" in src: return "Emirates"
    prof = client.get("profile") or {}
    return prof.get("airline") or "Airline"


def _missing_media_count(workout: dict) -> int:
    n = 0
    for ex in (workout.get("exercises") or []):
        img = ex.get("image_url") or ex.get("thumb_url") or ex.get("image")
        vid = ex.get("video_url") or ex.get("clip_url") or ex.get("video")
        if not img and not vid:
            n += 1
    return n


def _day_offset_label(offset: int) -> str:
    if offset == 0: return "Today"
    if offset == 1: return "Tomorrow"
    if offset < 0: return f"{abs(offset)}d ago"
    return f"In {offset}d"


def _flag_workout(
    day: dict, workout: dict, offset: int,
    roster: dict | None,
) -> list[str]:
    flags: list[str] = []
    colour = _colour_of(day)
    label = str(day.get("label") or day.get("auto_label") or "").upper()
    dtype = str(day.get("day_type") or "").lower()
    equipment = str(day.get("equipment_assumption") or "any").lower()
    blocked = day.get("blocked") or []
    needs_review_day = bool(day.get("needs_review") or day.get("_needs_review"))
    missing_media = _missing_media_count(workout)

    # Timing flags
    if offset == 0:
        flags.append("today")
    elif offset == 1:
        flags.append("tomorrow")

    # Missed
    completed = bool(workout.get("completed"))
    if offset < 0 and not completed:
        flags.append("missed")

    # Media
    if missing_media > 0:
        flags.append("needs_media")
        if offset == 0:
            flags.append("today_missing_media")

    # Review needs
    if (workout.get("needs_review") or workout.get("needs_coach_review")
            or needs_review_day):
        flags.append("needs_review")
        if offset == 0:
            flags.append("today_needs_review")
        elif offset == 1:
            flags.append("tomorrow_needs_review")

    # Roster uncertainty (low confidence or black)
    if colour == "black":
        flags.append("roster_uncertain")
    if roster and (roster.get("confidence_avg") or 1.0) < 0.55:
        flags.append("roster_uncertain")

    # Heavy duty (red colour or long-haul labels)
    heavy_labels = {
        "LONG_DUTY", "LONG_HAUL_OUTBOUND", "LONG_HAUL_RETURN",
        "LONG_HAUL_SECTOR", "OVERNIGHT_DUTY", "OVERNIGHT_TURNAROUND",
        "MULTI_SECTOR_DUTY", "NIGHT_DUTY",
    }
    if colour == "red" or label in heavy_labels:
        flags.append("heavy_duty")

    # Layover
    if ("layover" in dtype
            or label in ("LAYOVER_OUTBOUND", "LAYOVER_DAY", "LAYOVER_RETURN",
                         "LAYOVER_REST_DAY", "LONG_HAUL_SECTOR")):
        flags.append("layover")
        if equipment in ("hotel_or_bodyweight", "hotel_or_bodyweight_only",
                         "needs_confirmation"):
            flags.append("layover_unknown_equip")
        if not day.get("hotel_id"):
            flags.append("hotel_gym_unknown")

    # Post-night recovery
    if label in ("POST_NIGHT_RECOVERY", "POST_LONG_DUTY_RECOVERY",
                 "POST_LONG_HAUL_RECOVERY"):
        flags.append("post_night_recovery")

    # Coach-edited
    if workout.get("coach_locked") or workout.get("edited_by_coach"):
        flags.append("edited_by_louis")

    if workout.get("approved") and not flags:
        flags.append("ready")

    return flags


def _priority_of(flags: list[str]) -> int:
    return sum(_FLAG_WEIGHTS.get(f, 0) for f in flags)


# ---------------------------------------------------------------------------
# Assembly helpers
# ---------------------------------------------------------------------------

def _summarise_workout(w: dict) -> dict:
    return {
        "id": w.get("id"),
        "title": w.get("title"),
        "focus": w.get("focus"),
        "duration_min": w.get("duration_min"),
        "day_load": w.get("day_load"),
        "location": w.get("location"),
        "exercise_count": len(w.get("exercises") or []),
        "missing_media_count": _missing_media_count(w),
        "approved": bool(w.get("approved")),
        "coach_locked": bool(w.get("coach_locked")),
        "completed": bool(w.get("completed")),
        "rationale": (w.get("rationale") or "")[:220],
        "parser_enforced": bool(w.get("parser_enforced") or w.get("parser_moderated")),
    }


def _summarise_roster_day(day: dict) -> dict:
    return {
        "day_type": day.get("day_type"),
        "client_label": day.get("client_label"),
        "training_colour": _colour_of(day),
        "label": day.get("label") or day.get("auto_label"),
        "blocked": day.get("blocked") or [],
        "equipment_assumption": day.get("equipment_assumption") or "any",
        "reason": day.get("reason") or "",
        "layover_city": day.get("layover_city"),
        "hotel_name": day.get("hotel_name"),
        "flights": day.get("flights") or [],
        "report_time": day.get("report_time"),
        "release_time": day.get("release_time") or day.get("duty_end_time"),
        "needs_review": bool(day.get("needs_review") or day.get("_needs_review")),
        "source": day.get("source"),
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@api.get("/coach/live-feed")
async def coach_live_feed(
    days: int = Query(5, ge=1, le=14),
    filter: Optional[str] = Query(None),
    colour: Optional[str] = Query(None),
    client: Optional[str] = Query(None),
    airline: Optional[str] = Query(None),
    include_missed: bool = Query(True),
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Aggregate every client's upcoming workouts (± missed) into a single
    priority-sorted feed for the main coach dashboard."""
    today = _dt.date.today()
    # Window = missed yesterday + today + N-1 forward days
    start = today - _dt.timedelta(days=1) if include_missed else today
    end = today + _dt.timedelta(days=days - 1)
    date_strs = [(start + _dt.timedelta(days=i)).isoformat()
                 for i in range((end - start).days + 1)]

    # Fetch all clients (assigned to this coach OR all if primary/admin)
    q: dict[str, Any] = {"role": "client"}
    coach_id = coach.get("id")
    is_primary = coach.get("is_primary_coach") or coach.get("is_admin")
    if coach_id and not is_primary:
        q["assigned_coach_id"] = coach_id
    users = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(500)

    if client:
        users = [u for u in users if u.get("id") == client]

    items: list[dict] = []
    for u in users:
        cid = u["id"]
        # Latest active roster (fallback to latest of any status)
        roster = await db.rosters.find_one(
            {"user_id": cid, "is_active": True}, {"_id": 0, "raw_response": 0},
            sort=[("created_at", -1)],
        )
        if not roster:
            roster = await db.rosters.find_one(
                {"user_id": cid}, {"_id": 0, "raw_response": 0},
                sort=[("created_at", -1)],
            )
        day_map: dict[str, dict] = {
            d["date"]: d for d in (roster or {}).get("days", []) if d.get("date")
        }

        # Filter by airline if requested
        if airline:
            if _airline_of(u, roster).lower() != airline.lower():
                continue

        # Pull workouts in the window
        wkts = await db.workouts.find(
            {"user_id": cid, "date": {"$in": date_strs}},
            {"_id": 0},
        ).to_list(200)

        for w in wkts:
            dt = w.get("date")
            if not dt:
                continue
            try:
                offset = (_dt.date.fromisoformat(dt) - today).days
            except Exception:
                continue
            day = day_map.get(dt) or {}
            flags = _flag_workout(day, w, offset, roster)

            # Colour filter
            if colour and _colour_of(day) != colour.lower():
                continue

            item = {
                "workout_id": w.get("id"),
                "client": {
                    "id": cid,
                    "name": u.get("name") or u.get("email"),
                    "photo_url": u.get("photo_url") or u.get("avatar_url"),
                    "email": u.get("email"),
                    "airline": _airline_of(u, roster),
                    "role": (u.get("profile") or {}).get("role")
                            or (u.get("profile") or {}).get("job_title"),
                },
                "date": dt,
                "day_offset": offset,
                "day_offset_label": _day_offset_label(offset),
                "roster_day": _summarise_roster_day(day),
                "workout": _summarise_workout(w),
                "flags": flags,
                "priority": _priority_of(flags),
            }
            items.append(item)

    # Apply filter param
    if filter:
        fmap = {
            "needs_review": lambda i: "needs_review" in i["flags"],
            "needs_media": lambda i: "needs_media" in i["flags"],
            "heavy_duty": lambda i: "heavy_duty" in i["flags"],
            "layover": lambda i: "layover" in i["flags"],
            "post_night": lambda i: "post_night_recovery" in i["flags"],
            "missed": lambda i: "missed" in i["flags"],
            "today": lambda i: i["day_offset"] == 0,
            "all": lambda i: True,
        }
        pred = fmap.get(filter)
        if pred is not None:
            items = [i for i in items if pred(i)]

    # Sort: priority desc, then date asc, then client name
    items.sort(key=lambda i: (
        -i["priority"], i["date"], (i["client"].get("name") or "").lower()
    ))

    # Summary counts across the RAW window (post client/airline/colour filter
    # but pre `filter=` param, since those toggle the visible list not the
    # ambient counts).
    def _has(f: str) -> int:
        return sum(1 for i in items if f in i["flags"])

    by_client = Counter((i["client"].get("name") or "?") for i in items)
    by_airline = Counter(i["client"].get("airline") or "?" for i in items)
    by_colour = Counter(i["roster_day"].get("training_colour") or "green" for i in items)

    summary = {
        "total": len(items),
        "today": sum(1 for i in items if i["day_offset"] == 0),
        "tomorrow": sum(1 for i in items if i["day_offset"] == 1),
        "needs_review": _has("needs_review"),
        "needs_media": _has("needs_media"),
        "heavy_duty": _has("heavy_duty"),
        "layover_sessions": _has("layover"),
        "post_night_recovery": _has("post_night_recovery"),
        "missed": _has("missed"),
        "roster_uncertain": _has("roster_uncertain"),
        "by_client": dict(by_client.most_common(20)),
        "by_airline": dict(by_airline),
        "by_colour": dict(by_colour),
    }

    return {
        "generated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "include_missed": include_missed,
        },
        "summary": summary,
        "items": items,
    }
