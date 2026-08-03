"""
feature_roster_duty_details — data-exposure helper.

Extends the existing coach workspace API by attaching flight/duty/hotel
details to each schedule day. Does NOT parse or write anything: it only
reads existing roster data already produced by the roster parser and
surfaces it to the frontend so the coach can plan workouts around the
real duty pattern instead of just seeing a broad classification.

Data sources (all pre-existing):
  * db.rosters.days[]              parsed V1 roster days (source of truth for
                                   flight numbers, times, hotel, layover).
  * db.schedule_days.derived       V2 derived facets (burden, opportunity,
                                   overnight_location).
  * db.hotels                      shared hotel library (gym/equipment info).

Flight Support is untouched — it consumes the same underlying roster.
"""
from __future__ import annotations

from typing import Any, Optional

from server import db, logger


# ---------------------------------------------------------------------------
# Public helpers used by feature_v2_coach_dashboard.workspace_month
# ---------------------------------------------------------------------------

async def build_duty_details_map(
    client_id: str, sd_str: str, ed_str: str,
) -> dict[str, dict]:
    """Return { "YYYY-MM-DD" -> { flights:[...], report_time, release_time,
        pickup_time, hotel:{name,gym,equipment,city}, layover_city,
        sector_count, is_overnight, is_turnaround, is_layover_day,
        arrival_next_day, is_out_of_base, timezone_note, day_type_raw,
        needs_review, client_label, warnings, duty_duration_min } }

    Merges every active roster overlapping the month window. If a date
    appears in multiple rosters the most-recent one wins (rosters are
    fetched newest-first).
    """
    out: dict[str, dict] = {}

    # Newest first so older rosters can only fill dates not yet claimed.
    async for r in db.rosters.find(
        {"user_id": client_id, "is_active": True},
        {"_id": 0, "days": 1, "created_at": 1},
        sort=[("created_at", -1)],
    ):
        for d in (r.get("days") or []):
            date = d.get("date")
            if not date or not (sd_str <= date <= ed_str):
                continue
            if date in out:
                continue

            flights_norm = _normalise_flights(d.get("flights"))
            layover_city = d.get("layover_city") or d.get("overnight_location") or None
            hotel_name = d.get("hotel_name")

            duty_min = _compute_duty_duration_min(
                d.get("report_time"), d.get("release_time"),
            )

            hotel_block = None
            if hotel_name or layover_city:
                hotel_block = await _resolve_hotel_block(hotel_name, layover_city, d)

            out[date] = {
                "flights": flights_norm,
                "report_time": d.get("report_time"),
                "release_time": d.get("release_time"),
                "pickup_time": d.get("pickup_time"),
                "duty_duration_min": duty_min,
                "layover_city": layover_city,
                "hotel": hotel_block,
                "sector_count": d.get("sector_count") or len(flights_norm),
                "is_overnight": bool(d.get("is_overnight")),
                "is_turnaround": bool(d.get("is_turnaround")),
                "is_layover_day": bool(d.get("is_layover_day")),
                "arrival_next_day": bool(d.get("arrival_next_day")),
                "is_out_of_base": bool(d.get("is_out_of_base")),
                "timezone_note": d.get("timezone_note"),
                "day_type_raw": d.get("day_type"),
                "needs_review": bool(d.get("needs_review")) or d.get("day_type") == "Unknown/Needs Confirmation",
                "client_label": d.get("client_label") or d.get("label"),
                "warnings": d.get("warnings") or [],
                "reason": d.get("reason"),
                "confidence": d.get("confidence"),
            }

    return out


def enrich_schedule_with_duty(
    schedule: Optional[dict], duty: Optional[dict],
) -> Optional[dict]:
    """Attach the duty details onto the schedule dict returned by the
    workspace endpoint. Also refines the `classification_label` when the
    raw roster is more specific than the derived classification (e.g.
    'Unknown/Needs Confirmation' but the day actually contains flights).
    """
    if not schedule:
        # Even without a V2 schedule row, if there are flights we should
        # expose them so the coach still sees the sector list.
        if duty and (duty.get("flights") or duty.get("day_type_raw")):
            return {
                "classification": "flight" if duty.get("flights") else "unknown",
                "classification_label": _duty_label_from(duty),
                "duty": duty,
                "needs_review": bool(duty.get("needs_review")),
                "v1_source": True,
            }
        return schedule

    if not duty:
        return schedule

    schedule["duty"] = duty
    if duty.get("needs_review"):
        schedule["needs_review"] = True

    # If the derived classification looks generic ("custom"/"unknown") but
    # we actually have flights, upgrade the visible label so the coach
    # doesn't lose useful sector info to a placeholder.
    cls = str(schedule.get("classification") or "").lower()
    if duty.get("flights") and cls in ("", "custom", "unknown", "other", "home", "home_day"):
        schedule["classification_label"] = _duty_label_from(duty)

    return schedule


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _normalise_flights(raw: Any) -> list[dict]:
    """Accept both roster parser shapes:
      * new/rich: {flight_number, origin, destination, dep_time, arr_time}
      * legacy:   {number, from, to}
    Return a list of dicts with the rich shape (empty string when unknown).
    """
    if not raw or not isinstance(raw, list):
        return []
    out: list[dict] = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        num = f.get("flight_number") or f.get("number") or ""
        org = f.get("origin") or f.get("from") or ""
        dst = f.get("destination") or f.get("to") or ""
        out.append({
            "flight_number": str(num).strip().upper() if num else "",
            "origin": str(org).strip().upper() if org else "",
            "destination": str(dst).strip().upper() if dst else "",
            "dep_time": f.get("dep_time") or f.get("departure_time") or None,
            "arr_time": f.get("arr_time") or f.get("arrival_time") or None,
            "positioning": bool(f.get("positioning") or f.get("deadhead")),
        })
    return out


def _compute_duty_duration_min(report: Optional[str], release: Optional[str]) -> Optional[int]:
    """Parse 'HH:MM' and return duration in minutes. Handles wrap-around."""
    def _hm(s: Any) -> Optional[int]:
        if not s or not isinstance(s, str) or ":" not in s:
            return None
        try:
            h, m = s.split(":", 1)
            return int(h) * 60 + int(m[:2])
        except Exception:
            return None

    a = _hm(report); b = _hm(release)
    if a is None or b is None:
        return None
    diff = b - a
    if diff < 0:
        diff += 24 * 60
    return diff


async def _resolve_hotel_block(
    hotel_name: Optional[str], layover_city: Optional[str], day: dict,
) -> Optional[dict]:
    """Attach hotel info from db.hotels library where available. Never
    invents a hotel — returns 'confirmed=False' when city is known but
    the hotel is not."""
    name = (hotel_name or "").strip()
    city = (layover_city or "").strip()
    if not name and not city:
        return None

    # Try to look up a stored hotel by (name, city) or just (city).
    doc = None
    try:
        if name:
            doc = await db.hotels.find_one(
                {"name_lower": name.lower(), "city_lower": city.lower()} if city
                else {"name_lower": name.lower()},
                {"_id": 0},
            )
        if not doc and city:
            doc = await db.hotels.find_one(
                {"city_lower": city.lower(), "confidence": {"$gte": 0.8}},
                {"_id": 0}, sort=[("submissions", -1)],
            )
    except Exception as e:
        logger.warning(f"hotel lookup failed: {e}")

    if name:
        return {
            "name": name if doc is None else (doc.get("name") or name),
            "city": city or (doc or {}).get("city"),
            "confirmed": True,
            "gym_available": (doc or {}).get("gym_available"),
            "equipment": (doc or {}).get("equipment") or {},
            "pool": (doc or {}).get("pool"),
            "outdoor_safe": (doc or {}).get("outdoor_safe"),
            "opening_hours": (doc or {}).get("opening_hours"),
            "gym_confirmed_by_client": day.get("hotel_gym_confirmed"),
        }

    # No hotel name → do not invent one. Just expose city + confirmed=False.
    return {
        "name": None,
        "city": city,
        "confirmed": False,
        "gym_available": None,
        "equipment": {},
        "gym_confirmed_by_client": day.get("hotel_gym_confirmed"),
    }


def _duty_label_from(duty: dict) -> str:
    """Build a compact, useful title from duty data.
    Examples:
      * 'BA113 · LHR → DXB'
      * 'EK401 · MEL → SIN + 1 more'
      * 'Layover · Dubai'   (no flights but layover info)
      * 'Needs review'      (raw Unknown/Needs Confirmation and no flights)
    """
    fs = duty.get("flights") or []
    if fs:
        first = fs[0]
        route = f"{first.get('origin') or '?'} → {first.get('destination') or '?'}"
        num = first.get("flight_number") or ""
        extra = f" + {len(fs)-1} more" if len(fs) > 1 else ""
        return f"{num + ' · ' if num else ''}{route}{extra}".strip()
    if duty.get("layover_city"):
        return f"Layover · {duty['layover_city']}"
    if duty.get("day_type_raw") == "Unknown/Needs Confirmation":
        return "Needs review"
    return duty.get("client_label") or duty.get("day_type_raw") or "Duty"
