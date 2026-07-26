"""
Coach Roster Months — monthly programme control centre for the coach.

Aggregates a client's rosters and workouts into per-month buckets so the
coach dashboard can render a month-tab view with attached workouts.

Endpoints:
    * GET  /api/coach/clients/{client_id}/roster/months
    * GET  /api/coach/clients/{client_id}/roster/months/{yyyy_mm}

The response is deliberately verbose per day so the UI can render everything
without additional round-trips.
"""
from __future__ import annotations
import calendar
from datetime import date as _date, datetime as _datetime
from collections import defaultdict
from typing import Any

from fastapi import Depends, HTTPException

from server import api, db, require_role
import logging
logger = logging.getLogger("crewfit.coach_roster_months")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_key(d: str) -> str:
    """'2026-07-13' → '2026-07'."""
    if not d or len(d) < 7:
        return ""
    return d[:7]


def _month_label(key: str) -> str:
    if not key or len(key) != 7:
        return key or "Unknown"
    try:
        y, m = key.split("-")
        return f"{calendar.month_name[int(m)]} {y}"
    except Exception:
        return key


def _roster_month_span(r: dict) -> list[str]:
    """Return sorted list of month keys covered by this roster's days."""
    keys: set[str] = set()
    for d in r.get("days") or []:
        k = _month_key(d.get("date") or "")
        if k:
            keys.add(k)
    return sorted(keys)


def _airline_of(r: dict) -> str:
    src = str(r.get("parser_source") or "").lower()
    if "etihad" in src:
        return "Etihad"
    if "emirates" in src:
        return "Emirates"
    return r.get("airline") or (r.get("client_meta", {}) or {}).get("airline") or "Airline"


def _status_of(r: dict) -> str:
    """Roster status token used by the coach UI."""
    if r.get("status") == "pending_confirmation":
        return "needs_client_review"
    if r.get("status") == "expired":
        return "superseded"
    if not r.get("confirmed"):
        return "uploaded"
    if (r.get("review_flags") or {}).get("black_day_count", 0) > 0:
        return "needs_coach_review"
    if not r.get("is_active"):
        return "confirmed"
    return "programme_generated"


def _needs_review(r: dict) -> bool:
    rf = r.get("review_flags") or {}
    if rf.get("black_day_count", 0) > 0:
        return True
    if rf.get("low_confidence_count", 0) >= 3:
        return True
    if (r.get("confidence_avg") or 1.0) < 0.55:
        return True
    return False


def _summarise_workout(w: dict) -> dict:
    """Compact workout view for the day-card renderer."""
    if not w:
        return {}
    ex_count = len(w.get("exercises") or [])
    # Missing media = any exercise where image_url and video_url are both empty
    missing_media = 0
    for ex in (w.get("exercises") or []):
        img = ex.get("image_url") or ex.get("thumb_url") or ex.get("image")
        vid = ex.get("video_url") or ex.get("clip_url") or ex.get("video")
        if not img and not vid:
            missing_media += 1
    return {
        "id": w.get("id"),
        "date": w.get("date"),
        "title": w.get("title"),
        "focus": w.get("focus"),
        "duration_min": w.get("duration_min"),
        "day_load": w.get("day_load"),
        "location": w.get("location"),
        "exercise_count": ex_count,
        "missing_media_count": missing_media,
        "approved": bool(w.get("approved")),
        "coach_locked": bool(w.get("coach_locked")),
        "completed": bool(w.get("completed")),
        "rationale": (w.get("rationale") or "")[:220],
        "parser_enforced": bool(w.get("parser_enforced") or w.get("parser_moderated")),
    }


def _summarise_day(d: dict, workout: dict | None) -> dict:
    """Compact roster-day + workout view for the client month tab."""
    return {
        "date": d.get("date"),
        "weekday": d.get("weekday"),
        "day_type": d.get("day_type") or "Unknown",
        "client_label": d.get("client_label") or "",
        "training_colour": d.get("training_colour") or "green",
        "label": d.get("label") or d.get("auto_label") or "",
        "blocked": d.get("blocked") or [],
        "equipment_assumption": d.get("equipment_assumption") or "any",
        "layover_city": d.get("layover_city"),
        "layover_nights": d.get("layover_nights"),
        "report_time": d.get("report_time"),
        "release_time": d.get("release_time") or d.get("duty_end_time"),
        "hotel_name": d.get("hotel_name"),
        "hotel_id": d.get("hotel_id"),
        "flights": d.get("flights") or [],
        "confidence": d.get("confidence"),
        "needs_review": bool(d.get("needs_review")) or bool(d.get("_needs_review")),
        "reason": d.get("reason") or "",
        "source": d.get("source"),
        "workout": _summarise_workout(workout) if workout else None,
    }


def _summarise_workout_with_visibility(w: dict) -> dict:
    s = _summarise_workout(w)
    # Attach client-visibility flag so the coach UI can badge hidden items.
    vf = w.get("visible_from")
    if vf:
        try:
            from datetime import datetime as _dtv, timezone as _tzv
            due = _dtv.fromisoformat(vf.replace("Z", "+00:00"))
            now = _dtv.now(_tzv.utc)
            hidden = due > now
            s["client_hidden"] = hidden
            if hidden:
                s["client_visible_at"] = vf
                remaining = int((due - now).total_seconds() // 60)
                s["client_visible_in_min"] = max(0, remaining)
                s["client_hidden_reason"] = w.get("visible_from_reason") or "review_delay"
            else:
                s["client_hidden"] = False
        except Exception:
            pass
    else:
        s["client_hidden"] = False
    return s


# ---------------------------------------------------------------------------
# Endpoint 1 — list months summary
# ---------------------------------------------------------------------------

@api.get("/coach/clients/{client_id}/roster/months")
async def coach_client_roster_months(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return every roster the client has, grouped by month, with a compact
    summary suitable for rendering month tabs.
    """
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(404, "Client not found")

    rosters = await db.rosters.find(
        {"user_id": client_id},
        {"_id": 0, "raw_response": 0},
    ).sort("created_at", -1).to_list(60)

    # Group rosters by month
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in rosters:
        for k in _roster_month_span(r):
            by_month[k].append(r)

    # For each month, pick the CANONICAL roster (active > confirmed > most recent)
    def _rank(r: dict) -> tuple[int, str]:
        # Higher rank = preferred
        if r.get("is_active") and r.get("confirmed"):
            score = 4
        elif r.get("confirmed"):
            score = 3
        elif r.get("status") == "pending_confirmation":
            score = 2
        else:
            score = 1
        return (score, str(r.get("created_at") or ""))

    months_out: list[dict] = []
    for k in sorted(by_month.keys()):
        candidates = sorted(by_month[k], key=_rank, reverse=True)
        primary = candidates[0]
        others = candidates[1:]
        # Day count for THIS month only.
        primary_days = [d for d in (primary.get("days") or []) if _month_key(d.get("date") or "") == k]
        colour_counts = {"green": 0, "amber": 0, "red": 0, "black": 0}
        for d in primary_days:
            c = d.get("training_colour") or "green"
            colour_counts[c] = colour_counts.get(c, 0) + 1

        months_out.append({
            "month_key": k,
            "month_label": _month_label(k),
            "primary_roster_id": primary.get("id"),
            "airline": _airline_of(primary),
            "day_count": len(primary_days),
            "confidence_avg": primary.get("confidence_avg"),
            "status": _status_of(primary),
            "confirmed": bool(primary.get("confirmed")),
            "is_active": bool(primary.get("is_active")),
            "needs_review": _needs_review(primary),
            "review_flags": primary.get("review_flags") or {},
            "colour_counts": colour_counts,
            "label_summary": primary.get("label_summary"),
            "parser_source": primary.get("parser_source"),
            "source_filename": primary.get("source_filename"),
            "start_date": primary.get("start_date"),
            "end_date": primary.get("end_date"),
            "created_at": primary.get("created_at"),
            "version_count": len(candidates),
            "other_versions": [
                {
                    "id": r.get("id"),
                    "confirmed": bool(r.get("confirmed")),
                    "is_active": bool(r.get("is_active")),
                    "status": _status_of(r),
                    "created_at": r.get("created_at"),
                    "source_filename": r.get("source_filename"),
                    "day_count": r.get("day_count"),
                }
                for r in others
            ],
        })

    # Current month key (used by the UI to auto-select the default tab).
    today = _date.today()
    today_key = f"{today.year:04d}-{today.month:02d}"
    default_key: str = today_key
    keys_available = [m["month_key"] for m in months_out]
    if today_key not in keys_available and keys_available:
        # fall back to the earliest key not older than today, else latest
        future = [k for k in keys_available if k >= today_key]
        default_key = future[0] if future else keys_available[-1]

    return {
        "client": {"id": user["id"], "name": user.get("name"), "email": user.get("email"),
                   "photo_url": user.get("photo_url"), "airline": (user.get("profile") or {}).get("airline")},
        "months": months_out,
        "default_month_key": default_key,
        "today": today.isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoint 2 — month detail with days + workouts
# ---------------------------------------------------------------------------

@api.get("/coach/clients/{client_id}/roster/months/{yyyy_mm}")
async def coach_client_roster_month_detail(
    client_id: str,
    yyyy_mm: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return the full day-by-day view of ONE month, with each day's
    attached workout inlined. Used by the coach client Programme tab.
    """
    if not (len(yyyy_mm) == 7 and yyyy_mm[4] == "-"):
        raise HTTPException(400, "Month must be YYYY-MM")

    user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(404, "Client not found")

    # Find every roster that covers this month
    rosters = await db.rosters.find(
        {"user_id": client_id},
        {"_id": 0, "raw_response": 0},
    ).sort("created_at", -1).to_list(60)

    matching = [r for r in rosters if yyyy_mm in _roster_month_span(r)]
    if not matching:
        return {
            "client": {"id": user["id"], "name": user.get("name")},
            "month_key": yyyy_mm,
            "month_label": _month_label(yyyy_mm),
            "primary_roster": None,
            "days": [],
            "versions": [],
        }

    def _rank(r: dict) -> tuple[int, str]:
        if r.get("is_active") and r.get("confirmed"):
            score = 4
        elif r.get("confirmed"):
            score = 3
        elif r.get("status") == "pending_confirmation":
            score = 2
        else:
            score = 1
        return (score, str(r.get("created_at") or ""))

    ordered = sorted(matching, key=_rank, reverse=True)
    primary = ordered[0]
    other_versions = ordered[1:]

    # Filter days to just the requested month, sorted by date
    primary_days = [d for d in (primary.get("days") or [])
                    if _month_key(d.get("date") or "") == yyyy_mm]
    primary_days.sort(key=lambda x: x.get("date") or "")

    # Fetch workouts for those dates.
    dates = [d.get("date") for d in primary_days if d.get("date")]
    workouts = await db.workouts.find(
        {"user_id": client_id, "date": {"$in": dates}},
        {"_id": 0},
    ).to_list(200)
    wk_map: dict[str, dict] = {w.get("date"): w for w in workouts if w.get("date")}

    days_out = [
        {**_summarise_day(d, wk_map.get(d.get("date") or "")),
         "workout": _summarise_workout_with_visibility(wk_map[d["date"]])
                    if wk_map.get(d.get("date") or "") else None}
        for d in primary_days
    ]

    return {
        "client": {"id": user["id"], "name": user.get("name"),
                   "email": user.get("email"),
                   "photo_url": user.get("photo_url")},
        "month_key": yyyy_mm,
        "month_label": _month_label(yyyy_mm),
        "primary_roster": {
            "id": primary.get("id"),
            "airline": _airline_of(primary),
            "status": _status_of(primary),
            "confirmed": bool(primary.get("confirmed")),
            "is_active": bool(primary.get("is_active")),
            "needs_review": _needs_review(primary),
            "review_flags": primary.get("review_flags") or {},
            "confidence_avg": primary.get("confidence_avg"),
            "label_summary": primary.get("label_summary"),
            "parser_source": primary.get("parser_source"),
            "source_filename": primary.get("source_filename"),
            "start_date": primary.get("start_date"),
            "end_date": primary.get("end_date"),
            "created_at": primary.get("created_at"),
        },
        "days": days_out,
        "versions": [
            {
                "id": r.get("id"),
                "confirmed": bool(r.get("confirmed")),
                "is_active": bool(r.get("is_active")),
                "status": _status_of(r),
                "created_at": r.get("created_at"),
                "source_filename": r.get("source_filename"),
                "day_count": r.get("day_count"),
            }
            for r in other_versions
        ],
    }
