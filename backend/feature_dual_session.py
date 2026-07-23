"""
Iter 95a — Dual-Session Rule for Short-Haul Crew.

Short-haul cabin crew and pilots often work two-, three- or four-sector
turnarounds with genuine airport gaps between duties. Where duty is light
enough and the day ends with a hotel stay (or a home night with enough
window before sleep), the crew can safely fit:

  * a short "airport activation" session earlier in the day (mobility +
    a few bodyweight sets to counter sitting/standing) AND
  * a light hotel-evening session later.

This module is **additive only**: it never touches the planned workout
document. It exposes two endpoints:

  * GET  /dual-session/today        → optional secondary session for today
  * GET  /dual-session/upcoming     → next 7 days of eligibility hints

The frontend surfaces these as an *Optional Activation* nudge on Home.
Everything is gated by the `dual_session_enabled` feature flag so Louis
can turn the whole thing off remotely without an App Store push.

No AI wording anywhere — copy is Louis-voiced.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

from fastapi import Depends, HTTPException
from server import api, current_user, db, now_iso

logger = logging.getLogger("crewfit.dual_session")


# ---------------------------------------------------------------------------
# Eligibility logic
# ---------------------------------------------------------------------------

# Only these flying types are ever considered for the dual-session pattern.
_SHORT_HAUL_TYPES: frozenset[str] = frozenset({"short_haul", "mixed", "charter"})

# Minimum airport gap (hours) between two consecutive legs to earn the
# "activation" window. Below this, crew are actively boarding/refuelling.
_MIN_GAP_HOURS: float = 3.0

# Duty ceiling — above this we defer to the flight-recovery template instead.
_DUTY_CEILING_HOURS: float = 11.5


def _parse_hhmm(v: Optional[str]) -> Optional[float]:
    if not v: return None
    s = str(v).strip()
    if ":" not in s: return None
    try:
        h, m = s.split(":", 1)
        return int(h) + int(m) / 60.0
    except Exception:
        return None


def _airport_gap_hours(flights: list[dict]) -> float:
    """Longest gap between the arrival of leg N and the departure of leg N+1."""
    if not flights or len(flights) < 2: return 0.0
    best = 0.0
    for i in range(len(flights) - 1):
        arr = _parse_hhmm(flights[i].get("arr") or flights[i].get("arrival"))
        dep = _parse_hhmm(flights[i + 1].get("dep") or flights[i + 1].get("departure"))
        if arr is None or dep is None: continue
        gap = dep - arr
        if gap < 0: gap += 24  # over midnight
        if gap > best: best = gap
    return round(best, 2)


def _ends_at_hotel(day: dict, next_day: Optional[dict]) -> bool:
    """True if the crew have a hotel available at end of duty."""
    if day.get("hotel_id"): return True
    dtype = str(day.get("day_type") or "").lower()
    if "layover" in dtype: return True
    if next_day:
        n = str(next_day.get("day_type") or "").lower()
        if "layover" in n or n in ("rest", "off"):
            # Next day is a rest — safe to programme evening session at home too
            return True
    return False


def evaluate_day(day: dict, next_day: Optional[dict], profile: dict) -> dict:
    """Pure eligibility evaluator.

    Returns a dict:
      {
        eligible: bool,
        reason: str,           # human-readable, coach-voiced
        gap_hours: float,
        duty_hours: float|None,
        flight_count: int,
        pattern: "airport_activation_plus_hotel" | "none",
      }
    """
    ft = str(profile.get("flying_type") or profile.get("route_focus") or "").lower()
    if ft and ft not in _SHORT_HAUL_TYPES:
        return {"eligible": False, "reason": "Long-haul day — one focused session is enough.",
                "gap_hours": 0.0, "duty_hours": day.get("duty_hours"),
                "flight_count": len(day.get("flights") or []),
                "pattern": "none"}

    dtype = str(day.get("day_type") or "").lower()
    if "off" in dtype or "home day" in dtype or "annual" in dtype or "sick" in dtype:
        return {"eligible": False, "reason": "Off / home day — no dual session needed.",
                "gap_hours": 0.0, "duty_hours": day.get("duty_hours"),
                "flight_count": 0, "pattern": "none"}

    try:
        duty = float(day.get("duty_hours") or 0)
    except Exception:
        duty = 0.0
    if duty and duty > _DUTY_CEILING_HOURS:
        return {"eligible": False, "reason": "Duty is too long — one recovery session only.",
                "gap_hours": 0.0, "duty_hours": duty, "flight_count": len(day.get("flights") or []),
                "pattern": "none"}

    flights = day.get("flights") or []
    gap = _airport_gap_hours(flights)
    ends_hotel = _ends_at_hotel(day, next_day)

    # Two paths to eligibility:
    # A) Clear airport gap of ≥3h between short-haul legs.
    # B) 3+ legs (there's always an activation window even without a giant single gap)
    #    AND day ends at a hotel or a rest/off day.
    if gap >= _MIN_GAP_HOURS and ends_hotel:
        return {"eligible": True,
                "reason": f"You've got a {gap:.1f}-hour airport gap and a hotel tonight — perfect for a light activation, then something short at the hotel.",
                "gap_hours": gap, "duty_hours": duty,
                "flight_count": len(flights),
                "pattern": "airport_activation_plus_hotel"}
    if len(flights) >= 3 and ends_hotel:
        return {"eligible": True,
                "reason": "Three sectors in the day — an 8-minute airport reset now and a light hotel session tonight will keep you moving without burning you out.",
                "gap_hours": gap, "duty_hours": duty,
                "flight_count": len(flights),
                "pattern": "airport_activation_plus_hotel"}

    return {"eligible": False,
            "reason": "No safe activation window today — keep the planned session as-is.",
            "gap_hours": gap, "duty_hours": duty,
            "flight_count": len(flights), "pattern": "none"}


# ---------------------------------------------------------------------------
# Session template — the "airport activation" itself (safe everywhere)
# ---------------------------------------------------------------------------

AIRPORT_ACTIVATION_TEMPLATE: dict[str, Any] = {
    "title": "Airport Activation",
    "duration_min": 8,
    "location": "Airport / Crew Room",
    "load": "green",
    "focus": "mobility",
    "intensity": "RPE 3–4 — wake the body up, no sweat.",
    "warmup": [
        {"name": "Neck rolls + shoulder circles", "duration_sec": 45, "notes": "Slow and controlled."},
        {"name": "Standing hip openers", "duration_sec": 45, "notes": "One leg then the other."},
    ],
    "exercises": [
        {"name": "Wall-supported thoracic rotations", "sets": 2, "reps": "8/side", "rest_sec": 20, "rpe": 3,
         "notes": "Open the chest — great after the flight deck / galley."},
        {"name": "Standing calf raises", "sets": 2, "reps": "15", "rest_sec": 20, "rpe": 4,
         "notes": "Pump the calves — helps circulation for the next sector."},
        {"name": "Bodyweight hinge (RDL pattern)", "sets": 2, "reps": "10", "rest_sec": 25, "rpe": 4,
         "notes": "Reset the posterior chain from the seat."},
        {"name": "Walking or step-ups (concourse)", "sets": 1, "reps": "3–5 min brisk", "rpe": 4,
         "notes": "Get your heart rate up gently."},
    ],
    "cooldown": [
        {"name": "Deep breathing — box 4-4-4-4", "duration_sec": 90, "notes": "Downregulate before the next duty."},
    ],
    "rationale": "A short reset between sectors. Keeps the hips, shoulders and calves fresh without touching the tank you need for the day.",
    "change_reason": "Optional bonus session — your main plan for tonight still stands.",
}


def build_secondary_session(day: dict, evaluation: dict) -> dict:
    """Wrap the airport-activation template with per-day metadata."""
    return {
        **AIRPORT_ACTIVATION_TEMPLATE,
        "date": day.get("date"),
        "secondary": True,
        "eligibility": {
            "pattern": evaluation.get("pattern"),
            "gap_hours": evaluation.get("gap_hours"),
            "duty_hours": evaluation.get("duty_hours"),
            "flight_count": evaluation.get("flight_count"),
        },
        "coach_note": evaluation.get("reason"),
    }


# ---------------------------------------------------------------------------
# Helpers to fetch roster context for a user + date
# ---------------------------------------------------------------------------

async def _load_flag() -> bool:
    doc = await db.app_config.find_one({"key": "dual_session_enabled"}, {"_id": 0, "value": 1})
    if not doc: return True   # default ON per seed
    v = doc.get("value")
    return bool(v) if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")


async def _roster_days_for_user(uid: str, from_date: _dt.date, to_date: _dt.date) -> list[dict]:
    rosters = db.rosters.find(
        {"user_id": uid,
         "days.date": {"$gte": from_date.isoformat(), "$lte": to_date.isoformat()}},
        {"_id": 0, "days": 1},
    )
    out: list[dict] = []
    async for r in rosters:
        for d in (r.get("days") or []):
            date_s = d.get("date")
            if not date_s: continue
            try:
                dd = _dt.date.fromisoformat(date_s)
            except Exception:
                continue
            if from_date <= dd <= to_date:
                out.append(d)
    out.sort(key=lambda d: str(d.get("date") or ""))
    return out


# ---------------------------------------------------------------------------
# API — client-facing
# ---------------------------------------------------------------------------

@api.get("/dual-session/today")
async def dual_session_today(user: dict = Depends(current_user)):
    if not await _load_flag():
        return {"enabled": False, "eligible": False}
    today = _dt.date.today()
    days = await _roster_days_for_user(user["id"], today, today + _dt.timedelta(days=1))
    if not days:
        return {"enabled": True, "eligible": False, "reason": "No roster loaded for today."}
    day = next((d for d in days if d.get("date") == today.isoformat()), None)
    if not day:
        return {"enabled": True, "eligible": False, "reason": "No duty scheduled today."}
    next_day = next((d for d in days if d.get("date") == (today + _dt.timedelta(days=1)).isoformat()), None)
    profile = user.get("profile") or {}
    ev = evaluate_day(day, next_day, profile)
    if not ev["eligible"]:
        return {"enabled": True, "eligible": False, "reason": ev["reason"],
                "evaluation": ev, "date": today.isoformat()}
    session = build_secondary_session(day, ev)
    return {
        "enabled": True, "eligible": True, "date": today.isoformat(),
        "evaluation": ev, "session": session,
        "coach": {"name": "Louis Hall", "role": "CrewFit Coach"},
    }


@api.get("/dual-session/upcoming")
async def dual_session_upcoming(days: int = 7, user: dict = Depends(current_user)):
    if not await _load_flag():
        return {"enabled": False, "items": []}
    try:
        n = max(1, min(21, int(days)))
    except Exception:
        n = 7
    start = _dt.date.today()
    end = start + _dt.timedelta(days=n)
    profile = user.get("profile") or {}
    ds = await _roster_days_for_user(user["id"], start, end + _dt.timedelta(days=1))
    by_date = {d.get("date"): d for d in ds}
    items: list[dict] = []
    for i in range(n):
        dd = start + _dt.timedelta(days=i)
        key = dd.isoformat()
        day = by_date.get(key)
        if not day: continue
        nxt = by_date.get((dd + _dt.timedelta(days=1)).isoformat())
        ev = evaluate_day(day, nxt, profile)
        if ev["eligible"]:
            items.append({
                "date": key,
                "day_type": day.get("day_type"),
                "flight_count": ev["flight_count"],
                "gap_hours": ev["gap_hours"],
                "reason": ev["reason"],
            })
    return {"enabled": True, "count": len(items), "items": items,
            "generated_at": now_iso()}


# ---------------------------------------------------------------------------
# Coach-facing debug (safe: read-only)
# ---------------------------------------------------------------------------

@api.get("/dual-session/debug/{user_id}")
async def dual_session_debug(user_id: str, user: dict = Depends(current_user)):
    if user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Coach only")
    target = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    start = _dt.date.today()
    end = start + _dt.timedelta(days=14)
    ds = await _roster_days_for_user(user_id, start, end + _dt.timedelta(days=1))
    by_date = {d.get("date"): d for d in ds}
    profile = target.get("profile") or {}
    out: list[dict] = []
    for d in ds:
        if d.get("date") is None: continue
        try:
            dd = _dt.date.fromisoformat(d["date"])
        except Exception:
            continue
        if not (start <= dd <= end): continue
        nxt = by_date.get((dd + _dt.timedelta(days=1)).isoformat())
        ev = evaluate_day(d, nxt, profile)
        out.append({"date": d["date"], "evaluation": ev, "day_type": d.get("day_type"),
                    "flights": (d.get("flights") or [])[:6]})
    return {"user_id": user_id, "flying_type": profile.get("flying_type") or profile.get("route_focus"),
            "days_checked": len(out), "days": out}
