"""
feature_setup_day — First workout starts TOMORROW rule.

When a brand-new client's first programme is generated, we do NOT schedule a
workout for today. Today is treated as their SETUP DAY (welcome + profile +
roster upload) and the first official workout lands on the next suitable day —
tomorrow by default, or the next non-heavy roster day if tomorrow is a
long-haul flight / night flight / overnight duty.

This module is intentionally minimal and layered:
  * `_gate_for` picks the earliest date the first workout may fall on.
  * `_is_new_client_first_programme` checks whether the gate should apply.
  * `filter_new_client_workouts` returns a filtered list + records status on
    the user doc.

The existing generate/regenerate workers call `filter_new_client_workouts`
before persisting. Existing clients pass through untouched.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    logger,
    _log_change,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HEAVY_DAY_TAGS = (
    "long_haul", "long-haul", "longhaul",
    "night_flight", "night-flight",
    "overnight", "night duty",
    "red_eye", "red-eye",
)


def _today_local_str(user: dict) -> str:
    tz = user.get("current_time_zone") or user.get("home_time_zone") or "Europe/London"
    try:
        return _dt.datetime.now(ZoneInfo(tz)).date().isoformat()
    except Exception:
        return _dt.datetime.utcnow().date().isoformat()


def _daytype_for(roster: dict, date_iso: str) -> str:
    for d in (roster.get("days") or []):
        if d.get("date") == date_iso:
            return str(d.get("day_type") or d.get("type") or "").lower()
    return ""


def _is_heavy_first_day(daytype: str, day: dict | None) -> bool:
    if not daytype and not day:
        return False
    if any(k in daytype for k in _HEAVY_DAY_TAGS):
        return True
    # Fallback: long duty (>= 10h) counts as heavy
    try:
        dh = float((day or {}).get("duty_hours") or 0)
        if dh >= 10:
            return True
    except Exception:
        pass
    return False


def _find_day(roster: dict, date_iso: str) -> Optional[dict]:
    for d in (roster.get("days") or []):
        if d.get("date") == date_iso:
            return d
    return None


def _gate_for(user: dict, roster: dict, today_local: str) -> tuple[str, Optional[str]]:
    """Return (first_allowed_date_iso, reason_if_skipped)."""
    try:
        today = _dt.date.fromisoformat(today_local)
    except Exception:
        today = _dt.date.today()
    candidate = today + _dt.timedelta(days=1)
    reason: Optional[str] = None
    # Look at up to 7 days ahead. If tomorrow is heavy, advance.
    for _ in range(7):
        iso = candidate.isoformat()
        dtype = _daytype_for(roster, iso)
        day_row = _find_day(roster, iso)
        if not _is_heavy_first_day(dtype, day_row):
            return iso, reason
        # Skip this day, record reason for the first skip only.
        if reason is None:
            pretty = (dtype or "long duty").replace("_", " ").replace("-", " ").strip()
            reason = f"tomorrow is marked as {pretty}"
        candidate = candidate + _dt.timedelta(days=1)
    return candidate.isoformat(), reason or "no suitable start day found nearby"


async def _is_new_client_first_programme(user_id: str, roster_id: str) -> bool:
    """True only when this is the client's very first programme.
    Detects using:
      * No prior COMPLETED workouts.
      * No workouts under any OTHER roster.
    """
    completed = await db.workouts.count_documents({"user_id": user_id, "completed": True})
    if completed:
        return False
    other_roster_wk = await db.workouts.count_documents({
        "user_id": user_id,
        "roster_id": {"$nin": [None, roster_id]},
    })
    if other_roster_wk:
        return False
    return True


async def filter_new_client_workouts(
    user: dict,
    roster: dict,
    workouts: list[dict],
) -> tuple[list[dict], dict[str, Any]]:
    """
    Given the LLM-planned workouts, filter out any that fall on or before the
    setup-day gate for a new client. For existing clients pass through untouched.

    Returns (filtered_workouts, meta) where meta may contain:
      { "setup_gate": {"first_workout_date": ..., "reason": ...} }
    """
    user_id = user["id"]
    roster_id = roster.get("id")
    if not roster_id:
        return workouts, {}
    is_new = await _is_new_client_first_programme(user_id, roster_id)
    if not is_new:
        return workouts, {}
    # Respect any manual admin override that says "start today anyway".
    if user.get("setup_day_override") is True:
        return workouts, {}
    today_local = _today_local_str(user)
    gate_iso, reason = _gate_for(user, roster, today_local)
    kept: list[dict] = []
    dropped: list[str] = []
    for w in workouts:
        d = (w.get("date") or "")[:10]
        if d and d < gate_iso:
            dropped.append(d)
            continue
        kept.append(w)
    meta = {
        "setup_gate": {
            "first_workout_date": gate_iso,
            "reason": reason,
            "dropped_dates": dropped,
        },
    }
    try:
        await db.users.update_one(
            {"id": user_id},
            {"$set": {
                "first_workout_date": gate_iso,
                "setup_day_reason": reason,
                "setup_day_gate_applied_at": now_iso(),
                "setup_day_today_local": today_local,
            }},
        )
        await _log_change(
            None, user_id, "programme",
            f"Setup day applied — first workout scheduled for {gate_iso}",
            reason or "", actor="atlas",
            meta={"gate": gate_iso, "dropped_dates": dropped, "reason": reason},
        )
    except Exception:
        logger.exception("filter_new_client_workouts: could not persist gate meta")
    return kept, meta


# ---------------------------------------------------------------------------
# Client-facing status
# ---------------------------------------------------------------------------

@api.get("/setup-day/status")
async def setup_day_status(user: dict = Depends(current_user)):
    """
    Returns whether TODAY is a setup day for this client.
    Frontend uses this to render the Setup Day card on Home.
    """
    today = _today_local_str(user)
    gate = user.get("first_workout_date") or ""
    reason = user.get("setup_day_reason")
    override = bool(user.get("setup_day_override"))
    # Only setup day if:
    #   - a gate exists and is strictly after today
    #   - user has NO completed workouts (once they train, they leave setup mode)
    #   - override is False
    completed = await db.workouts.count_documents({"user_id": user["id"], "completed": True})
    is_setup = bool(gate) and gate > today and not override and completed == 0
    return {
        "is_setup_day": is_setup,
        "today_local": today,
        "first_workout_date": gate or None,
        "reason": reason,
        "override": override,
    }


# ---------------------------------------------------------------------------
# Coach override
# ---------------------------------------------------------------------------

@api.post("/coach/clients/{client_id}/programme/start-today")
async def coach_start_programme_today(client_id: str, coach: dict = Depends(require_role("coach"))):
    """Louis / admin can override the setup-day gate for a specific client so
    their first workout is allowed to schedule today."""
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")
    await db.users.update_one(
        {"id": client_id},
        {"$set": {
            "setup_day_override": True,
            "setup_day_override_by": coach["id"],
            "setup_day_override_at": now_iso(),
        }},
    )
    try:
        await _log_change(coach["id"], client_id, "programme",
                          "Coach overrode setup day — programme may start today",
                          "", actor="coach", meta={})
    except Exception:
        pass
    return {"ok": True, "override": True}


@api.post("/coach/clients/{client_id}/programme/clear-override")
async def coach_clear_start_override(client_id: str, coach: dict = Depends(require_role("coach"))):
    """Undo the manual override (restore the default 'first workout tomorrow' behaviour)."""
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(404, "client not found")
    await db.users.update_one(
        {"id": client_id},
        {"$set": {"setup_day_override": False}, "$unset": {"setup_day_override_by": "", "setup_day_override_at": ""}},
    )
    return {"ok": True, "override": False}
