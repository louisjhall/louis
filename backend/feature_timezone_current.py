"""
Iter 94m — Current timezone card + endpoints.

Owns three responsibilities:

1. `resolve_current_timezone(user, roster_day)` — priority chain:
     1. Roster-confirmed timezone for today's duty (highest)
     2. Client-confirmed `profile.current_timezone`
     3. Device timezone (only if the client sent it on request)
     4. Home base timezone (`profile.home_timezone`)
     5. Unknown → prompt

2. `GET /profile/timezone-status` — returns the resolved view for the
   client home card. Accepts optional `?device_tz=Europe/London` query so
   the frontend can pass what its device thinks the timezone is.

3. `POST /profile/timezone-confirm` — client confirms their current
   timezone (IANA + city label). Also lets them set/reset home base timezone.

No GPS permission needed. No AI wording. Home base and current are cleanly
distinguished throughout.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel

from server import (
    api, current_user, db, now_iso,
)

logger = logging.getLogger("crewfit.timezone")


# ---------------------------------------------------------------------------
# IANA validation + city-label helpers
# ---------------------------------------------------------------------------

# A curated shortlist of common crew hubs → IANA. Full IANA list is validated
# via `zoneinfo.available_timezones()` at import.
_CITY_TO_IANA: dict[str, str] = {
    "dubai": "Asia/Dubai",
    "doha": "Asia/Qatar",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "amsterdam": "Europe/Amsterdam",
    "frankfurt": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "rome": "Europe/Rome",
    "istanbul": "Europe/Istanbul",
    "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong",
    "tokyo": "Asia/Tokyo",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "auckland": "Pacific/Auckland",
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "miami": "America/New_York",
    "toronto": "America/Toronto",
    "sao paulo": "America/Sao_Paulo",
    "johannesburg": "Africa/Johannesburg",
    "cairo": "Africa/Cairo",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "bangkok": "Asia/Bangkok",
    "seoul": "Asia/Seoul",
    "shanghai": "Asia/Shanghai",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "manila": "Asia/Manila",
}

# Airport codes (IATA/ICAO) → IANA. Only the biggest crew hubs.
_AIRPORT_TO_IANA: dict[str, str] = {
    "DXB": "Asia/Dubai",  "OMDB": "Asia/Dubai",
    "DOH": "Asia/Qatar",  "OTHH": "Asia/Qatar",
    "LHR": "Europe/London", "LGW": "Europe/London", "STN": "Europe/London",
    "EGLL": "Europe/London",
    "CDG": "Europe/Paris", "ORY": "Europe/Paris", "LFPG": "Europe/Paris",
    "AMS": "Europe/Amsterdam", "EHAM": "Europe/Amsterdam",
    "FRA": "Europe/Berlin", "MUC": "Europe/Berlin", "EDDF": "Europe/Berlin",
    "MAD": "Europe/Madrid", "LEMD": "Europe/Madrid",
    "FCO": "Europe/Rome", "LIRF": "Europe/Rome",
    "IST": "Europe/Istanbul", "LTFM": "Europe/Istanbul",
    "SIN": "Asia/Singapore", "WSSS": "Asia/Singapore",
    "HKG": "Asia/Hong_Kong", "VHHH": "Asia/Hong_Kong",
    "NRT": "Asia/Tokyo", "HND": "Asia/Tokyo", "RJAA": "Asia/Tokyo", "RJTT": "Asia/Tokyo",
    "SYD": "Australia/Sydney", "YSSY": "Australia/Sydney",
    "MEL": "Australia/Melbourne", "YMML": "Australia/Melbourne",
    "AKL": "Pacific/Auckland", "NZAA": "Pacific/Auckland",
    "JFK": "America/New_York", "LGA": "America/New_York", "EWR": "America/New_York",
    "KJFK": "America/New_York", "KLGA": "America/New_York", "KEWR": "America/New_York",
    "LAX": "America/Los_Angeles", "KLAX": "America/Los_Angeles",
    "SFO": "America/Los_Angeles", "KSFO": "America/Los_Angeles",
    "ORD": "America/Chicago", "KORD": "America/Chicago",
    "MIA": "America/New_York", "KMIA": "America/New_York",
    "YYZ": "America/Toronto", "CYYZ": "America/Toronto",
    "GRU": "America/Sao_Paulo",
    "JNB": "Africa/Johannesburg",
    "CAI": "Africa/Cairo",
    "BOM": "Asia/Kolkata", "DEL": "Asia/Kolkata",
    "BKK": "Asia/Bangkok",
    "ICN": "Asia/Seoul", "GMP": "Asia/Seoul",
    "PVG": "Asia/Shanghai", "SHA": "Asia/Shanghai",
    "KUL": "Asia/Kuala_Lumpur",
    "MNL": "Asia/Manila",
}


def _valid_iana(tz: str) -> bool:
    try:
        from zoneinfo import ZoneInfo, available_timezones  # type: ignore
        return tz in available_timezones() or (ZoneInfo(tz) is not None)
    except Exception:
        return False


def _city_label_for(iana: str) -> Optional[str]:
    """Return a friendly city label for an IANA tz, or None."""
    if not iana:
        return None
    # Reverse map (first match wins).
    for city, tz in _CITY_TO_IANA.items():
        if tz == iana:
            return city.title()
    # Fallback: pull the last segment ("Europe/London" → "London").
    tail = iana.split("/")[-1].replace("_", " ")
    return tail


def _infer_from_string(s: str) -> Optional[str]:
    """Best-effort inference from a free-text place / airport code."""
    if not s:
        return None
    up = str(s).strip().upper()
    if up in _AIRPORT_TO_IANA:
        return _AIRPORT_TO_IANA[up]
    lo = str(s).strip().lower()
    if lo in _CITY_TO_IANA:
        return _CITY_TO_IANA[lo]
    # `Dubai (DXB)` style → try each token
    for token in lo.replace("(", " ").replace(")", " ").replace(",", " ").split():
        if token in _CITY_TO_IANA:
            return _CITY_TO_IANA[token]
        if token.upper() in _AIRPORT_TO_IANA:
            return _AIRPORT_TO_IANA[token.upper()]
    return None


# ---------------------------------------------------------------------------
# Priority-chain resolver
# ---------------------------------------------------------------------------

async def _todays_roster_row(user_id: str) -> Optional[dict]:
    today_iso = _dt.date.today().isoformat()
    try:
        roster = await db.rosters.find_one(
            {"user_id": user_id, "status": "active"},
            {"_id": 0}, sort=[("created_at", -1)],
        )
    except Exception:
        roster = None
    if not roster:
        return None
    for d in (roster.get("days") or []):
        if str(d.get("date"))[:10] == today_iso:
            return d
    return None


async def resolve_current_timezone(
    user: dict, device_tz: Optional[str] = None,
) -> dict:
    """Return the full resolved status the client home + coach see.

    Response shape:
      {
        "home_base": "Dubai",
        "home_timezone": "Asia/Dubai",
        "current_timezone": "Europe/London",
        "current_timezone_city": "London",
        "current_timezone_source": "roster" | "client_confirmed" | "device" | "home_base" | "unknown",
        "current_timezone_confidence": "high" | "medium" | "low",
        "reason": "Layover in London",
        "needs_confirmation": bool,
        "updated_at": iso | None,
      }
    """
    profile = (user or {}).get("profile") or {}
    home_base = profile.get("home_base_city") or profile.get("home_base") or None
    home_tz = profile.get("home_timezone") or (
        _infer_from_string(home_base) if home_base else None
    )
    home_city = _city_label_for(home_tz) if home_tz else (home_base or None)

    # Priority 1 — roster row for today
    row = await _todays_roster_row(user["id"])
    if row:
        for field in ("timezone", "current_timezone", "layover_timezone",
                      "arrival_timezone", "duty_timezone"):
            tz = row.get(field)
            if tz and _valid_iana(tz):
                return {
                    "home_base": home_city,
                    "home_timezone": home_tz,
                    "current_timezone": tz,
                    "current_timezone_city": _city_label_for(tz),
                    "current_timezone_source": "roster",
                    "current_timezone_confidence": "high",
                    "reason": row.get("day_type") or None,
                    "needs_confirmation": False,
                    "updated_at": row.get("date"),
                }
        # Try to infer from a city / airport code on the row.
        for field in ("layover_city", "arrival", "arrival_city", "destination",
                      "arrival_airport", "hotel_city"):
            inf = _infer_from_string(str(row.get(field) or ""))
            if inf:
                return {
                    "home_base": home_city,
                    "home_timezone": home_tz,
                    "current_timezone": inf,
                    "current_timezone_city": _city_label_for(inf),
                    "current_timezone_source": "roster",
                    "current_timezone_confidence": "medium",
                    "reason": (f"Layover in {row.get(field)}"
                               if "layover" in field else
                               f"{row.get(field)}"),
                    "needs_confirmation": False,
                    "updated_at": row.get("date"),
                }

    # Priority 2 — client-confirmed current_timezone
    cct = profile.get("current_timezone")
    if cct and _valid_iana(cct):
        # Stale after 7 days = medium confidence
        confirmed_at = profile.get("current_timezone_confirmed_at") or ""
        try:
            confirmed_dt = _dt.datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
            age_days = (_dt.datetime.now(_dt.timezone.utc) - confirmed_dt).days
        except Exception:
            age_days = 0
        conf = "high" if age_days <= 3 else ("medium" if age_days <= 14 else "low")
        return {
            "home_base": home_city,
            "home_timezone": home_tz,
            "current_timezone": cct,
            "current_timezone_city": _city_label_for(cct),
            "current_timezone_source": "client_confirmed",
            "current_timezone_confidence": conf,
            "reason": None,
            "needs_confirmation": conf == "low",
            "updated_at": profile.get("current_timezone_confirmed_at"),
        }

    # Priority 3 — device timezone (only if the frontend passed it)
    if device_tz and _valid_iana(device_tz):
        return {
            "home_base": home_city,
            "home_timezone": home_tz,
            "current_timezone": device_tz,
            "current_timezone_city": _city_label_for(device_tz),
            "current_timezone_source": "device",
            "current_timezone_confidence": "medium",
            "reason": None,
            "needs_confirmation": False,
            "updated_at": None,
        }

    # Priority 4 — home base timezone
    if home_tz and _valid_iana(home_tz):
        return {
            "home_base": home_city,
            "home_timezone": home_tz,
            "current_timezone": home_tz,
            "current_timezone_city": home_city,
            "current_timezone_source": "home_base",
            "current_timezone_confidence": "low",
            "reason": None,
            "needs_confirmation": True,
            "updated_at": None,
        }

    # Priority 5 — unknown
    return {
        "home_base": home_city,
        "home_timezone": home_tz,
        "current_timezone": None,
        "current_timezone_city": None,
        "current_timezone_source": "unknown",
        "current_timezone_confidence": "low",
        "reason": None,
        "needs_confirmation": True,
        "updated_at": None,
    }


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@api.get("/profile/timezone-status")
async def profile_timezone_status(
    device_tz: Optional[str] = Query(None, description="Device timezone if the app knows it"),
    user: dict = Depends(current_user),
):
    return await resolve_current_timezone(user, device_tz=device_tz)


class TimezoneConfirmBody(BaseModel):
    current_timezone: Optional[str] = None
    home_timezone: Optional[str] = None
    home_base_city: Optional[str] = None


@api.post("/profile/timezone-confirm")
async def profile_timezone_confirm(body: TimezoneConfirmBody, user: dict = Depends(current_user)):
    updates: dict = {}
    if body.current_timezone:
        if not _valid_iana(body.current_timezone):
            raise HTTPException(400, f"invalid IANA timezone: {body.current_timezone}")
        updates["profile.current_timezone"] = body.current_timezone
        updates["profile.current_timezone_source"] = "client_confirmed"
        updates["profile.current_timezone_confirmed_at"] = now_iso()
    if body.home_timezone:
        if not _valid_iana(body.home_timezone):
            raise HTTPException(400, f"invalid IANA timezone: {body.home_timezone}")
        updates["profile.home_timezone"] = body.home_timezone
    if body.home_base_city:
        updates["profile.home_base_city"] = body.home_base_city
        # Auto-populate home_timezone if the city maps to one we know.
        inferred = _infer_from_string(body.home_base_city)
        if inferred and not body.home_timezone:
            updates["profile.home_timezone"] = inferred

    if not updates:
        raise HTTPException(400, "provide at least one of current_timezone, home_timezone, home_base_city")

    await db.users.update_one({"id": user["id"]}, {"$set": updates})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return await resolve_current_timezone(fresh)
