"""
feature_flight_support_notifier.py — Iter 127

Duty-aware Flight Support push scheduler.

Fires push + in-app notifications for:
  - flight_support_pre_flight     ~90 min before report_time (origin airport TZ)
  - flight_support_post_flight    ~30 min after release_time (destination TZ)
  - flight_support_layover        first reasonable local time on layover day
  - flight_support_turnaround     if turnaround gap >= 90 min

All notifications:
  * are gated by user.notification_settings.flight_support (default True)
  * are suppressed during the active-flight safety window
    [first_dep_utc - 45m, last_arr_utc + 15m]
  * are quiet-hours aware (via existing create_notification helper)
  * are deduped by fs:{user_id}:{date}:{event_type}:{flight_or_day_id}
  * deep-link to /(client)/home?flight_support=<intervention_id>

No GPS, no expo-location. Uses roster event → IATA → IANA → UTC only.

Reuses:
  - feature_timezone_current._AIRPORT_TO_IANA (~80 codes; falls back gracefully)
  - feature_notifications.create_notification (dedup, category gate, quiet hours)
  - feature_aviation_support.build_flight_support_for_date (protocol lookup)
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("crewfit.flight_support_notifier")

# ---------------------------------------------------------------------------
# Airport → IANA (reuses the existing map)
# ---------------------------------------------------------------------------
try:
    from feature_timezone_current import _AIRPORT_TO_IANA  # type: ignore
except Exception:
    _AIRPORT_TO_IANA = {}


def _airport_iana(code: Optional[str], fallback: str = "UTC") -> str:
    if not code:
        return fallback
    return _AIRPORT_TO_IANA.get(str(code).strip().upper(), fallback)


def _parse_hhmm(s: Optional[str]) -> Optional[tuple[int, int]]:
    if not s or not isinstance(s, str) or ":" not in s:
        return None
    try:
        h, m = s.split(":")[:2]
        return int(h), int(m)
    except Exception:
        return None


def _local_to_utc(date_str: str, hhmm: str, iana: str) -> Optional[_dt.datetime]:
    """Combine YYYY-MM-DD + HH:MM in `iana` → aware UTC datetime."""
    hm = _parse_hhmm(hhmm)
    if not hm:
        return None
    try:
        tz = ZoneInfo(iana)
    except Exception:
        tz = ZoneInfo("UTC")
    try:
        d = _dt.date.fromisoformat(date_str)
    except Exception:
        return None
    local = _dt.datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=tz)
    return local.astimezone(_dt.timezone.utc)


# ---------------------------------------------------------------------------
# Active flight window — safety-critical suppression
# ---------------------------------------------------------------------------
async def _sector_utc_windows(day: dict) -> list[tuple[_dt.datetime, _dt.datetime]]:
    """Return list of (dep_utc, arr_utc) tuples for today's sectors."""
    out: list[tuple[_dt.datetime, _dt.datetime]] = []
    date_str = day.get("date")
    if not date_str:
        return out
    for f in (day.get("flights") or []):
        dep_iana = _airport_iana(f.get("origin"))
        arr_iana = _airport_iana(f.get("destination"))
        dep_utc = _local_to_utc(date_str, f.get("dep_time"), dep_iana)
        arr_utc = _local_to_utc(date_str, f.get("arr_time"), arr_iana)
        if dep_utc and arr_utc:
            # Sectors that cross midnight in local time — bump arrival by 1 day
            # if it lands before dep (rare but possible for overnight red-eyes).
            if arr_utc < dep_utc:
                arr_utc = arr_utc + _dt.timedelta(days=1)
            out.append((dep_utc, arr_utc))
    return out


async def in_active_flight_window(db, user_id: str, when_utc: _dt.datetime) -> bool:
    """True if `when_utc` falls inside any sector's [dep-45m, arr+15m] window."""
    date_today = when_utc.astimezone(_dt.timezone.utc).date().isoformat()
    date_yday  = (when_utc.astimezone(_dt.timezone.utc) - _dt.timedelta(days=1)).date().isoformat()
    roster = await db.rosters.find_one(
        {"user_id": user_id, "is_active": True, "confirmed": True},
        {"days": 1},
    )
    if not roster:
        return False
    for d in (roster.get("days") or []):
        if d.get("date") not in (date_today, date_yday):
            continue
        for (dep_utc, arr_utc) in await _sector_utc_windows(d):
            start = dep_utc - _dt.timedelta(minutes=45)
            end = arr_utc + _dt.timedelta(minutes=15)
            if start <= when_utc <= end:
                return True
    return False


# ---------------------------------------------------------------------------
# Per-day event planner — returns list of (event_type, fire_utc, meta)
# ---------------------------------------------------------------------------
def _plan_day_events(day: dict) -> list[tuple[str, _dt.datetime, dict]]:
    date_str = day.get("date")
    if not date_str:
        return []
    day_type = (day.get("day_type") or "").lower()
    flights = day.get("flights") or []
    events: list[tuple[str, _dt.datetime, dict]] = []

    # Pre-flight — 90 min before report_time at first sector's origin TZ
    report = day.get("report_time")
    if report and flights:
        origin = flights[0].get("origin")
        report_utc = _local_to_utc(date_str, report, _airport_iana(origin))
        if report_utc:
            pre_utc = report_utc - _dt.timedelta(minutes=90)
            events.append(("flight_support_pre_flight", pre_utc, {
                "flight_no": flights[0].get("flight_number") or "",
                "origin": origin or "",
                "report_time": report,
            }))

    # Post-flight — 30 min after release_time at last sector's destination TZ
    release = day.get("release_time")
    if release and flights:
        dest = flights[-1].get("destination")
        release_utc = _local_to_utc(date_str, release, _airport_iana(dest))
        if release_utc:
            post_utc = release_utc + _dt.timedelta(minutes=30)
            events.append(("flight_support_post_flight", post_utc, {
                "flight_no": flights[-1].get("flight_number") or "",
                "destination": dest or "",
                "release_time": release,
            }))

    # Layover — first sensible local time on layover_arrival day
    if day_type == "layover_arrival" and flights:
        dest = flights[-1].get("destination")
        arr = flights[-1].get("arr_time")
        arr_utc = _local_to_utc(date_str, arr, _airport_iana(dest))
        if arr_utc:
            # If arrival is between 06:00 and 20:00 local → +3 hours.
            # If overnight arrival → 09:00 local the next day.
            iana = _airport_iana(dest)
            try:
                arr_local = arr_utc.astimezone(ZoneInfo(iana))
            except Exception:
                arr_local = arr_utc
            if 6 <= arr_local.hour < 20:
                fire_local = arr_local + _dt.timedelta(hours=3)
            else:
                fire_local = arr_local.replace(hour=9, minute=0, second=0, microsecond=0)
                if fire_local <= arr_local:
                    fire_local = fire_local + _dt.timedelta(days=1)
            events.append(("flight_support_layover", fire_local.astimezone(_dt.timezone.utc), {
                "destination": dest or "",
                "layover_city": day.get("layover_city") or "",
                "arr_time": arr,
            }))

    # Turnaround — only when gap between last arr and next dep is >= 90 min
    # (checked in the multi-sector case). Fires 20 min before next dep.
    if len(flights) >= 2:
        for i in range(len(flights) - 1):
            arr = flights[i].get("arr_time")
            next_dep = flights[i + 1].get("dep_time")
            arr_utc = _local_to_utc(date_str, arr, _airport_iana(flights[i].get("destination")))
            dep_utc = _local_to_utc(date_str, next_dep, _airport_iana(flights[i + 1].get("origin")))
            if not (arr_utc and dep_utc):
                continue
            gap_min = int((dep_utc - arr_utc).total_seconds() // 60)
            if gap_min >= 90:
                fire_utc = dep_utc - _dt.timedelta(minutes=20)
                events.append(("flight_support_turnaround", fire_utc, {
                    "flight_no": flights[i + 1].get("flight_number") or "",
                    "turnaround_gap_min": gap_min,
                }))
    return events


# ---------------------------------------------------------------------------
# Copy templates
# ---------------------------------------------------------------------------
_TITLES = {
    "flight_support_pre_flight":  "Pre-Flight Reset",
    "flight_support_post_flight": "Post-Flight Reset",
    "flight_support_layover":     "Layover Recovery",
    "flight_support_turnaround":  "Turnaround Reset",
}
_BODIES = {
    "flight_support_pre_flight":
        "Your 6-minute pre-flight reset is ready before duty. Do it when it fits.",
    "flight_support_post_flight":
        "You’ve landed. Your recovery reset is ready when you're off duty and settled.",
    "flight_support_layover":
        "Your layover recovery protocol is ready. No rush — use it when you're settled.",
    "flight_support_turnaround":
        "Turnaround reset is ready. A quick 3–4 minute movement break if you have time.",
}


# ---------------------------------------------------------------------------
# Main scheduler tick — call every 5 minutes from server.py
# ---------------------------------------------------------------------------
async def flight_support_scheduler_tick(db, create_notification, send_push=None) -> dict:
    """One tick: enqueue Flight Support push notifications whose fire_utc is
    inside the next 5-minute window from now. Deduped by canonical key.

    Returns a small summary dict for observability. Safe to call repeatedly
    — dedup is enforced at the create_notification layer.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    horizon = now + _dt.timedelta(minutes=5)
    summary = {"scanned_rosters": 0, "queued": 0, "suppressed_flight": 0, "already": 0}

    cursor = db.rosters.find(
        {"is_active": True, "confirmed": True},
        {"user_id": 1, "days": 1},
    )
    async for r in cursor:
        summary["scanned_rosters"] += 1
        uid = r.get("user_id")
        if not uid:
            continue
        user = await db.users.find_one({"id": uid}, {"notification_settings": 1, "current_time_zone": 1, "home_time_zone": 1, "profile": 1})
        if not user:
            continue
        # Only pilots (aviation category is pilot-only for beta)
        role = (user.get("profile") or {}).get("crew_role") or ""
        if role != "pilot":
            continue

        for d in (r.get("days") or []):
            for (etype, fire_utc, meta) in _plan_day_events(d):
                if not (now <= fire_utc <= horizon):
                    continue
                # Safety window suppression
                if await in_active_flight_window(db, uid, fire_utc):
                    summary["suppressed_flight"] += 1
                    continue
                # Dedup key
                flight_id = meta.get("flight_no") or d.get("date") or "day"
                dedupe_key = f"fs:{uid}:{d.get('date')}:{etype}:{flight_id}"
                action_url = f"/(client)/home?flight_support={etype}&date={d.get('date')}"
                try:
                    created = await create_notification(
                        user_id=uid,
                        notif_type=etype,
                        title=_TITLES[etype],
                        body=_BODIES[etype],
                        related_id=d.get("date"),
                        dedupe_key=dedupe_key,
                        action_url=action_url,
                        respect_quiet_hours=True,
                        send_push_now=True,
                    )
                    if created and created.get("created_at") == created.get("updated_at"):
                        summary["queued"] += 1
                    else:
                        summary["already"] += 1
                except Exception as e:
                    logger.exception("flight_support enqueue failed: %s", e)
    return summary
