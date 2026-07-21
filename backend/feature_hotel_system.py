"""
feature_hotel_system — Hotel profiles, Layover vs Turnaround detection,
and bodyweight-safe fallbacks for unknown gyms.

Design goals:
  * A client on a layover with a known hotel gets a workout that MATCHES the
    equipment we actually have on file for that hotel.
  * A client on a layover with an UNKNOWN hotel gets a bodyweight-safe session
    (never a fake barbell workout on a phantom bench).
  * A client on a turnaround (<18h between duties) gets a mobility / recovery
    session — no strength training.

Public helpers used by:
  * feature_workout_fallback.build_template_plan (roster context injection)
  * server.py hotel endpoints (client confirms + coach review queue)
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

# 18h threshold — confirmed with product. Anything below is Turnaround.
LAYOVER_THRESHOLD_HOURS = 18

# Canonical gym types. Kept small so the client picker is <10 taps.
GYM_TYPES = ("full_gym", "cardio_only", "basic", "bodyweight_only", "none", "unknown")

# Equipment field keys — MUST match HOTEL_EQUIPMENT_FIELDS in server.py.
# These are the equipment items we consider when matching exercises.
HOTEL_EQUIPMENT_KEYS = (
    "dumbbells", "adjustable_dumbbells", "barbell", "bench", "cable_stack",
    "smith_machine", "treadmill", "stationary_bike", "rowing_machine",
    "kettlebell", "resistance_bands", "pull_up_bar", "medicine_ball",
    "trx", "yoga_mat", "foam_roller", "pool",
)

# Presets by gym_type — used when a client only knows the gym_type but not the
# specific equipment list. These are conservative defaults.
GYM_TYPE_PRESETS: dict[str, dict[str, bool]] = {
    "full_gym": {
        "dumbbells": True, "barbell": True, "bench": True, "cable_stack": True,
        "treadmill": True, "stationary_bike": True, "kettlebell": True,
        "pull_up_bar": True, "yoga_mat": True,
    },
    "cardio_only": {
        "treadmill": True, "stationary_bike": True, "rowing_machine": True,
        "yoga_mat": True,
    },
    "basic": {
        "dumbbells": True, "yoga_mat": True, "resistance_bands": True,
    },
    "bodyweight_only": {"yoga_mat": True},
    "none": {},
    "unknown": {},
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _parse_time_hhmm(t: Optional[str]) -> Optional[tuple[int, int]]:
    """Parse '08:30' / '8:30' / '08:30Z' / '2030' into (h, m). Returns None if unparseable."""
    if not t:
        return None
    s = str(t).strip().upper().replace("Z", "").replace("LT", "").strip()
    m = re.match(r"^(\d{1,2}):?(\d{2})$", s)
    if not m:
        return None
    h = int(m.group(1))
    mm = int(m.group(2))
    if 0 <= h <= 23 and 0 <= mm <= 59:
        return (h, mm)
    return None


def _parse_date(date_str: Optional[str]) -> Optional[_dt.date]:
    if not date_str:
        return None
    try:
        return _dt.date.fromisoformat(str(date_str)[:10])
    except Exception:
        return None


def compute_layover_hours(day: dict[str, Any], next_day: Optional[dict[str, Any]]) -> Optional[float]:
    """
    Estimate the free layover window between the END of today's duty and the
    START of the next duty. Returns hours as float, or None if we can't tell.

    Reads:
      day.duty_end_time  (HH:MM local — end of today's flight/duty)
      next_day.report_time (HH:MM local — pickup / report for next duty)
      day.date, next_day.date
    """
    if not day or not next_day:
        return None
    d_today = _parse_date(day.get("date"))
    d_next = _parse_date(next_day.get("date"))
    end_hm = _parse_time_hhmm(day.get("duty_end_time"))
    rep_hm = _parse_time_hhmm(next_day.get("report_time"))
    if not (d_today and d_next and end_hm and rep_hm):
        return None
    end_dt = _dt.datetime.combine(d_today, _dt.time(end_hm[0], end_hm[1]))
    rep_dt = _dt.datetime.combine(d_next, _dt.time(rep_hm[0], rep_hm[1]))
    delta_h = (rep_dt - end_dt).total_seconds() / 3600.0
    if delta_h < 0:
        return None
    return round(delta_h, 1)


def classify_stay(
    day: dict[str, Any],
    next_day: Optional[dict[str, Any]] = None,
    threshold_hours: float = LAYOVER_THRESHOLD_HOURS,
) -> str:
    """
    Classify a roster day into one of:
      * "layover"    — ≥ 18h free, hotel training window open
      * "turnaround" — < 18h between duties, mobility / recovery only
      * "home"       — home-base day, full training
      * "off"        — annual leave / rest / off day
      * "flight"     — a flying duty with no clear layover after (e.g., day trip)
      * "unknown"    — insufficient signal to decide
    """
    dtype = str(day.get("day_type") or day.get("type") or "").lower()

    if dtype in ("rest", "off", "annual_leave", "leave", "day_off"):
        return "off"

    # Explicit layover markers in the roster take priority
    if "layover" in dtype or "hotel" in dtype:
        # If we can measure hours, downgrade short ones to turnaround
        hours = compute_layover_hours(day, next_day)
        if hours is not None and hours < threshold_hours:
            return "turnaround"
        return "layover"

    # Turnaround = short overnight or same-day flight sequence
    if "turnaround" in dtype or "day_trip" in dtype:
        return "turnaround"

    # Any flying / duty day
    if "flight" in dtype or "duty" in dtype or "sector" in dtype:
        hours = compute_layover_hours(day, next_day)
        if hours is not None:
            if hours >= threshold_hours:
                return "layover"
            return "turnaround"
        return "flight"

    if "home" in dtype or "base" in dtype or dtype in ("training", "sim"):
        return "home"

    if not dtype or dtype in ("unknown/needs confirmation", "unknown"):
        return "unknown"

    return "home"


# ---------------------------------------------------------------------------
# Hotel profile helpers
# ---------------------------------------------------------------------------

def resolve_gym_equipment(hotel_doc: Optional[dict[str, Any]]) -> dict[str, bool]:
    """
    Given a hotel_profiles document (or None), return a normalised equipment
    boolean dict. If hotel_doc is None → returns {} (unknown = bodyweight only).
    """
    if not hotel_doc:
        return {}
    # If explicit equipment was set, prefer it.
    eq = hotel_doc.get("equipment") or {}
    if isinstance(eq, dict) and eq:
        return {k: bool(v) for k, v in eq.items() if k in HOTEL_EQUIPMENT_KEYS}
    # Fallback to gym_type preset
    gt = str(hotel_doc.get("gym_type") or "unknown").lower()
    return dict(GYM_TYPE_PRESETS.get(gt, {}))


def is_bodyweight_only(hotel_doc: Optional[dict[str, Any]]) -> bool:
    """
    True if we should route this workout to bodyweight-safe templates:
      * no hotel doc / hotel_id at all → unknown
      * gym_type == "none" or "bodyweight_only"
      * gym_available == False
      * empty equipment dict AND gym_type == "unknown"
    """
    if not hotel_doc:
        return True
    if hotel_doc.get("gym_available") is False:
        return True
    gt = str(hotel_doc.get("gym_type") or "").lower()
    if gt in ("none", "bodyweight_only"):
        return True
    if gt in ("", "unknown"):
        eq = hotel_doc.get("equipment") or {}
        if not any(bool(v) for v in eq.values() if isinstance(v, bool) or v is True):
            return True
    return False


def confidence_score(hotel_doc: dict[str, Any]) -> float:
    """
    Confidence in the hotel profile: 0.0 - 1.0.
      * 0.0 = never confirmed
      * 0.5 = first submission
      * +0.15 per subsequent confirmation (capped at 1.0)
      * +0.2 for coach-verified
    """
    if not hotel_doc:
        return 0.0
    base = float(hotel_doc.get("confidence") or 0.0)
    if hotel_doc.get("verified_by_coach"):
        base = min(1.0, base + 0.2)
    return round(min(1.0, base), 2)


def is_low_confidence(hotel_doc: dict[str, Any], threshold: float = 0.6) -> bool:
    """True if the hotel profile needs coach review."""
    return confidence_score(hotel_doc) < threshold


async def load_hotel_lookup_for_roster(db, roster: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Preload all hotel_profiles referenced by the roster days.
    Returns {hotel_id: hotel_doc}. Missing IDs are simply absent.
    """
    if not roster:
        return {}
    ids = list({d.get("hotel_id") for d in (roster.get("days") or []) if d.get("hotel_id")})
    if not ids:
        return {}
    docs = await db.hotels.find({"id": {"$in": ids}}, {"_id": 0}).to_list(len(ids))
    return {h["id"]: h for h in docs if h.get("id")}


# ---------------------------------------------------------------------------
# Public reason strings — for "Why this changed" UI
# ---------------------------------------------------------------------------

REASON_STRINGS = {
    "hotel_unknown": (
        "This session is bodyweight-safe because we don't yet know what "
        "equipment is available at your hotel. Confirm the gym setup to unlock "
        "a stronger plan."
    ),
    "hotel_bodyweight_only": (
        "Your hotel has no gym — this session uses your bodyweight only, "
        "designed to work in a hotel room."
    ),
    "hotel_confirmed": (
        "Session matched to the equipment you confirmed at this hotel."
    ),
    "turnaround_short": (
        "Short turnaround (<18h between duties) — swapped to mobility only "
        "so you arrive rested for your next flight."
    ),
    "layover_long": (
        "Long layover — full training window open."
    ),
    "hotel_needs_confirm": (
        "This hotel is in our database from other crew — confirm the "
        "equipment is still accurate before training."
    ),
}


def reason_for(day: dict[str, Any], hotel_doc: Optional[dict[str, Any]],
               next_day: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Return a short client-facing reason string for the current day's session."""
    kind = classify_stay(day, next_day)
    if kind == "turnaround":
        return REASON_STRINGS["turnaround_short"]
    if kind == "layover":
        if not hotel_doc:
            return REASON_STRINGS["hotel_unknown"]
        if is_bodyweight_only(hotel_doc):
            return REASON_STRINGS["hotel_bodyweight_only"]
        if is_low_confidence(hotel_doc):
            return REASON_STRINGS["hotel_needs_confirm"]
        return REASON_STRINGS["hotel_confirmed"]
    return None
