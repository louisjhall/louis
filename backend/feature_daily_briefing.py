"""
Iter 94u — Daily Briefing from Louis + coach profile.

Owns:

1. GET  /coach-profile              — Louis Hall's coach card (name, role,
                                       image path, whatsapp link).
2. GET  /daily-briefing/today       — today's briefing computed for the caller.
3. POST /daily-briefing/dismiss     — mark today's briefing dismissed so it
                                       doesn't reopen on the next launch.
4. GET  /daily-briefing/preferences — the client's current preferences.
5. POST /daily-briefing/preferences — toggle in-app pop-up / push / off,
                                       tone, etc.
6. POST /daily-briefing/regenerate  — regenerate today's briefing (client or coach).

Design:
- Idempotent per (user_id, date_local). Reading /today twice returns the same
  briefing so refreshes on the client don't multiply DB rows.
- Timezone comes from the client's current timezone status (roster > confirmed
  > device > home base). All local-time decisions use that TZ.
- Wording is Louis-voiced. No "AI", no "generated", no "content missing".
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api, current_user, db, new_id, now_iso,
)

logger = logging.getLogger("crewfit.daily_briefing")

# ---------------------------------------------------------------------------
# Coach profile — Louis Hall is the single source of truth.
# ---------------------------------------------------------------------------

LOUIS = {
    "coach_id": "louis-hall",
    "name": "Louis Hall",
    "role": "CrewFit Coach",
    "email": "louis@crewfit.net",
    "profile_image": "louis",          # frontend maps this to a bundled asset
    "whatsapp_url": "https://wa.link/k9x12s",
    "active": True,
}


@api.get("/coach-profile")
async def coach_profile(user: dict = Depends(current_user)):
    _ = user  # auth only
    return LOUIS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _user_timezone(user_id: str) -> tuple[str, str]:
    """Return (tz_iana, source). Falls back to UTC when nothing is known."""
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    profile = (u or {}).get("profile") or {}
    tz = profile.get("current_timezone") or profile.get("home_timezone") or "UTC"
    src = "current" if profile.get("current_timezone") else (
        "home_base" if profile.get("home_timezone") else "utc"
    )
    return tz, src


def _local_today(tz_iana: str) -> _dt.date:
    try:
        return _dt.datetime.now(ZoneInfo(tz_iana)).date()
    except Exception:
        return _dt.date.today()


def _local_now(tz_iana: str) -> _dt.datetime:
    try:
        return _dt.datetime.now(ZoneInfo(tz_iana))
    except Exception:
        return _dt.datetime.utcnow()


def _time_of_day(dt: _dt.datetime) -> str:
    h = dt.hour
    if h < 5:  return "night"
    if h < 12: return "morning"
    if h < 17: return "afternoon"
    if h < 21: return "evening"
    return "night"


def _greeting(name: str, tod: str) -> str:
    first = (name or "").strip().split(" ")[0] if name else ""
    prefix = {"morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "night": "Hi"}.get(tod, "Hi")
    return f"{prefix} {first}," if first else f"{prefix},"


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


# ---------------------------------------------------------------------------
# Contextual advice snippets — all Louis-voiced.
# ---------------------------------------------------------------------------

def _workout_focus(wo: Optional[dict]) -> str:
    if not wo:
        return "No session scheduled today. A short walk or mobility reset still counts."
    if wo.get("completed"):
        return "Nice — today's session is already done. Keep protein and hydration up."
    title = wo.get("title") or "your session"
    dur = wo.get("estimated_minutes") or wo.get("duration_min")
    load = str(wo.get("day_load") or "").lower()
    if load in {"red", "amber"}:
        return f"{title} today — fuel it properly and warm up before you start."
    if dur:
        return f"{title} today — around {dur} minutes."
    return f"{title} today."


def _nutrition_focus(totals: dict, target: dict, goal: str, tod: str) -> str:
    cal = float((totals or {}).get("calories") or 0)
    pro = float((totals or {}).get("protein_g") or 0)
    tgt_pro = float((target or {}).get("protein_g") or 0)
    tgt_cal = float((target or {}).get("calories") or 0)
    logged = (totals or {}).get("count") or 0
    if logged == 0:
        if tod in ("morning", "night"):
            return "No meals logged yet. Get a protein-forward breakfast in and log it so we can see the day."
        return "Nothing logged yet — try to log your next meal so we can see calories and protein."
    if tgt_pro and pro < tgt_pro * 0.4 and tod in ("afternoon", "evening"):
        return f"Protein is running low — you've logged {int(pro)}g against a {int(tgt_pro)}g target. Grab a protein option with your next meal."
    if goal == "fat_loss" and tgt_cal and cal >= tgt_cal:
        return "You've already hit your calorie target — keep the rest of the day protein and veg focused."
    if goal == "running" and tgt_cal and cal < tgt_cal * 0.4 and tod == "afternoon":
        return "Calories are low ahead of training — a simple carb + protein meal will support the session."
    return "Nutrition looks on track — keep going."


def _recovery_focus(tod: str, roster_type: str, goal: str) -> str:
    rt = (roster_type or "").lower()
    if "night" in rt or "red_eye" in rt:
        return "Night duty later — keep caffeine early, protect your sleep window when you're back."
    if "long_haul" in rt:
        return "Long-haul today — hydrate, walk when you can, and keep the session short if fatigue is high."
    if tod == "evening":
        return "Wind down: reduce caffeine, light meal if sleeping soon, short mobility before bed."
    if tod == "morning":
        return "Get some daylight if you can and hydrate before your first coffee."
    if goal == "return_to_training":
        return "Easy movement wins. Message Louis if pain is up."
    return "Keep it simple — small habits stack over the week."


def _layover_advice(layover_city: Optional[str], roster_type: str) -> Optional[str]:
    if not layover_city:
        return None
    city = str(layover_city).strip().title()
    return f"You're on a {city} layover today, so keep this simple. Confirm your hotel equipment when you get chance."


def _main_action(wo: Optional[dict], totals: dict, roster_type: str, layover: Optional[str]) -> tuple[str, str]:
    """Return (label, route). One clear next action for today."""
    if wo and not wo.get("completed"):
        return ("Start today's session", f"/workout/{wo.get('id')}")
    if (totals or {}).get("count", 0) == 0:
        return ("Log your first meal", "/nutrition")
    if layover:
        return ("Confirm hotel equipment", "/roster")
    if "night" in (roster_type or "").lower():
        return ("Review recovery focus", "/habits")
    return ("View today", "/")


# ---------------------------------------------------------------------------
# Habits helper
# ---------------------------------------------------------------------------

async def _todays_habits(user_id: str, date_local: str) -> list[dict]:
    if not hasattr(db, "habits_daily"):
        return []
    rows = await db.habits_daily.find(
        {"user_id": user_id, "date": date_local}, {"_id": 0},
    ).limit(6).to_list(6) if hasattr(db, "habits_daily") else []
    if rows:
        return [{"title": r.get("title"), "done": bool(r.get("completed"))} for r in rows if r.get("title")]
    # Fallback: pick the user's active daily habit templates
    tpl = await db.habits.find(
        {"user_id": user_id, "cadence": "daily", "active": {"$ne": False}}, {"_id": 0},
    ).limit(3).to_list(3) if hasattr(db, "habits") else []
    return [{"title": t.get("title") or t.get("name"), "done": False} for t in tpl if t.get("title") or t.get("name")]


async def _todays_workout(user_id: str, date_local: str) -> Optional[dict]:
    return await db.workouts.find_one(
        {"user_id": user_id, "date": date_local}, {"_id": 0},
    )


async def _todays_roster_day(user_id: str, date_local: str) -> Optional[dict]:
    r = await db.rosters.find_one(
        {"user_id": user_id, "status": "active"}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not r:
        return None
    for d in (r.get("days") or []):
        if str(d.get("date") or "")[:10] == date_local:
            return d
    return None


async def _nutrition_today(user_id: str, date_local: str) -> tuple[dict, dict]:
    rows = await db.nutrition_logs.find(
        {"user_id": user_id, "date_local": date_local}, {"_id": 0},
    ).to_list(200) if hasattr(db, "nutrition_logs") else []
    totals = {"calories": 0.0, "protein_g": 0.0, "count": 0}
    for r in rows:
        totals["calories"] += float(r.get("calories") or 0)
        totals["protein_g"] += float(r.get("protein_g") or 0)
        totals["count"] += 1
    tgt = await db.nutrition_targets.find_one({"user_id": user_id}, {"_id": 0}) if hasattr(db, "nutrition_targets") else None
    return totals, (tgt or {})


async def _missed_yesterday(user_id: str, tz_iana: str) -> Optional[dict]:
    y = (_local_today(tz_iana) - _dt.timedelta(days=1)).isoformat()
    w = await db.workouts.find_one(
        {"user_id": user_id, "date": y, "completed": {"$ne": True}, "skipped": {"$ne": True}},
        {"_id": 0},
    )
    if not w:
        return None
    if str(w.get("title") or "").lower().startswith(("rest", "off")):
        return None
    return {"id": w.get("id"), "title": w.get("title"), "date": w.get("date"), "key_session": bool(w.get("key_session"))}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class PrefsBody(BaseModel):
    daily_summary_enabled: Optional[bool] = None
    daily_summary_push_enabled: Optional[bool] = None
    daily_summary_tone: Optional[str] = None  # "gentle" | "direct" | "minimal"


@api.get("/daily-briefing/preferences")
async def get_prefs(user: dict = Depends(current_user)):
    doc = await db.daily_briefing_prefs.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    return {
        "daily_summary_enabled": doc.get("daily_summary_enabled", True),
        "daily_summary_push_enabled": doc.get("daily_summary_push_enabled", False),
        "daily_summary_tone": doc.get("daily_summary_tone", "gentle"),
    }


@api.post("/daily-briefing/preferences")
async def set_prefs(body: PrefsBody, user: dict = Depends(current_user)):
    updates = {"user_id": user["id"], "updated_at": now_iso()}
    if body.daily_summary_enabled is not None:
        updates["daily_summary_enabled"] = body.daily_summary_enabled
    if body.daily_summary_push_enabled is not None:
        updates["daily_summary_push_enabled"] = body.daily_summary_push_enabled
    if body.daily_summary_tone is not None:
        if body.daily_summary_tone not in {"gentle", "direct", "minimal"}:
            raise HTTPException(400, "invalid tone")
        updates["daily_summary_tone"] = body.daily_summary_tone
    await db.daily_briefing_prefs.update_one({"user_id": user["id"]}, {"$set": updates}, upsert=True)
    fresh = await db.daily_briefing_prefs.find_one({"user_id": user["id"]}, {"_id": 0})
    return {"ok": True, "prefs": fresh}


# ---------------------------------------------------------------------------
# Build + persist a briefing.
# ---------------------------------------------------------------------------

async def _build_briefing(user: dict) -> dict:
    tz, tz_source = await _user_timezone(user["id"])
    today = _local_today(tz)
    now = _local_now(tz)
    tod = _time_of_day(now)
    profile = user.get("profile") or {}
    goal = _detect_goal(profile)

    wo = await _todays_workout(user["id"], today.isoformat())
    roster_day = await _todays_roster_day(user["id"], today.isoformat())
    totals, target = await _nutrition_today(user["id"], today.isoformat())
    habits = await _todays_habits(user["id"], today.isoformat())
    missed = await _missed_yesterday(user["id"], tz)

    roster_type = str((roster_day or {}).get("day_type") or "")
    layover_city = (roster_day or {}).get("layover_city")

    workout_focus = _workout_focus(wo)
    nutrition_focus = _nutrition_focus(totals, target, goal, tod)
    recovery_focus = _recovery_focus(tod, roster_type, goal)
    layover_focus = _layover_advice(layover_city, roster_type)
    action_label, action_route = _main_action(wo, totals, roster_type, layover_city)

    title = "Today's Briefing"
    if layover_city:
        title = f"{str(layover_city).title()} Layover Focus"

    body_lines: list[str] = []
    body_lines.append(_greeting(user.get("name") or "", tod))
    if layover_focus:
        body_lines.append(layover_focus)
    body_lines.append("")
    body_lines.append("Workout:")
    body_lines.append(workout_focus)
    body_lines.append("")
    body_lines.append("Nutrition:")
    body_lines.append(nutrition_focus)
    body_lines.append("")
    body_lines.append("Recovery:")
    body_lines.append(recovery_focus)
    if missed:
        body_lines.append("")
        body_lines.append(
            f"You missed yesterday's {missed.get('title') or 'session'} — no stress, roster gets in the way. "
            f"Recover it today if it fits, or continue with the next planned session."
        )

    doc = {
        "user_id": user["id"],
        "date_local": today.isoformat(),
        "timezone": tz,
        "timezone_source": tz_source,
        "city": layover_city,
        "roster_day_type": roster_type or None,
        "goal_class": goal,
        "time_of_day": tod,
        "title": title,
        "greeting": body_lines[0],
        "body_lines": [l for l in body_lines if l is not None],
        "workout_focus": workout_focus,
        "nutrition_focus": nutrition_focus,
        "recovery_focus": recovery_focus,
        "layover_focus": layover_focus,
        "main_action": {"label": action_label, "route": action_route},
        "habits": habits,
        "missed_yesterday": missed,
        "coach": LOUIS,
        "updated_at": now_iso(),
    }
    return doc


async def _get_or_build_today(user: dict) -> dict:
    tz, _ = await _user_timezone(user["id"])
    date_local = _local_today(tz).isoformat()
    existing = await db.daily_briefings.find_one(
        {"user_id": user["id"], "date_local": date_local}, {"_id": 0},
    )
    if existing:
        return existing
    doc = await _build_briefing(user)
    doc["id"] = new_id()
    doc["created_at"] = now_iso()
    doc["shown_at"] = None
    doc["dismissed_at"] = None
    await db.daily_briefings.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.get("/daily-briefing/today")
async def daily_briefing_today(user: dict = Depends(current_user)):
    prefs = await db.daily_briefing_prefs.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    enabled = prefs.get("daily_summary_enabled", True)
    doc = await _get_or_build_today(user)
    # Auto-record first read as shown_at
    if not doc.get("shown_at"):
        await db.daily_briefings.update_one(
            {"user_id": user["id"], "date_local": doc["date_local"]},
            {"$set": {"shown_at": now_iso()}},
        )
        doc["shown_at"] = now_iso()
    return {
        "briefing": doc,
        "enabled": enabled,
        "should_show_modal": bool(enabled and not doc.get("dismissed_at")),
    }


class DismissBody(BaseModel):
    reason: Optional[str] = None


@api.post("/daily-briefing/dismiss")
async def dismiss_briefing(body: DismissBody, user: dict = Depends(current_user)):
    # Ensure today's briefing exists before recording dismissal so we never
    # write a stub row missing content.
    doc = await _get_or_build_today(user)
    await db.daily_briefings.update_one(
        {"user_id": user["id"], "date_local": doc["date_local"]},
        {"$set": {"dismissed_at": now_iso(), "dismiss_reason": body.reason}},
    )
    return {"ok": True}


@api.post("/daily-briefing/regenerate")
async def regenerate_briefing(user: dict = Depends(current_user)):
    tz, _ = await _user_timezone(user["id"])
    date_local = _local_today(tz).isoformat()
    await db.daily_briefings.delete_one({"user_id": user["id"], "date_local": date_local})
    doc = await _get_or_build_today(user)
    return {"ok": True, "briefing": doc}
