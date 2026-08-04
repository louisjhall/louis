"""
feature_ba_roster_adapter — British Airways iOS-calendar roster adapter.

Purpose
-------
Some BA crew share their roster as a screenshot of the native iOS Calendar
app in *month view*. The trip bars use BA-specific text that other airline
parsers do not recognise:

    "MCO - Rpt:05:50z LHRx-MCO-LHR"    -> multi-day trip Aug 6 → Aug 9
    "ends 08:15"                        -> displayed on the last day
    "LEAVE" / "Leave (Wraps After)"     -> leave label + duplicated helpers

This module is an ISOLATED post-processor that runs AFTER the shared LLM
extractor. It looks at the LLM's output, detects BA calendar signatures,
and if confident, replaces the days with a deterministic BA re-parse.

Design rules
------------
* Zero effect on non-BA rosters — if signatures don't cross the confidence
  threshold, the function returns the original days untouched.
* Emirates / RAK / easyJet / Ryanair / Qatar are unaffected — this module
  is a pure post-processor gated by a strict detector.
* Never invents flight numbers, hotels, positioning sectors, or timezones.
* Preserves the raw route string exactly (including trailing "x" chars).
* End times without timezone stay `timezone: "unspecified_local"`; report
  times marked "Rpt:HH:MMz" become `timezone: "utc"`.
* Leave helpers ("Leave (Wraps After)") are deduplicated into one block.

Public API
----------
* detect_ba_calendar(days) -> dict — confidence + evidence.
* parse_ba_calendar(days) -> dict — deterministic BA days + trips.
* maybe_apply(days, raw_text=None) -> dict — safe wrapper returning either
  {"applied": True, "days": [...], "trips": [...], "detection": {...}}
  or {"applied": False, "days": <original>, "detection": {...}}.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# BA signature regexes
# ---------------------------------------------------------------------------

# Report time in Zulu: "Rpt:05:50z"
RE_RPT_ZULU = re.compile(r"\bRpt:\s*(\d{1,2}):(\d{2})\s*z\b", re.IGNORECASE)

# End time footer (no timezone provided): "ends 08:15"
RE_ENDS = re.compile(r"\bends?\s+(\d{1,2}):(\d{2})\b", re.IGNORECASE)

# BA route shape — starts with LHR/LGW/LCY/BHX/EDI/MAN (BA UK bases),
# optional "x" suffix, hyphenated segments, second and third segments are
# 3-4 uppercase letters possibly with an "x" tail.
RE_BA_ROUTE = re.compile(
    r"\b(LHR|LGW|LCY|BHX|EDI|MAN|GLA|NCL|ABZ|BFS)x?-[A-Z]{3,4}-[A-Z]{3,4}x?\b"
)

# Destination-first trip bar: "MCO - Rpt:12:00z LGWx-MCO-LGWx"
RE_TRIP_BAR = re.compile(
    r"^\s*(?P<dest>[A-Z]{3})\s*-\s*Rpt:\s*(?P<h>\d{1,2}):(?P<m>\d{2})\s*z\s+"
    r"(?P<route>(?:LHR|LGW|LCY|BHX|EDI|MAN|GLA|NCL|ABZ|BFS)x?-[A-Z]{3,4}-[A-Z]{3,4}x?)"
    r"\s*$",
    re.IGNORECASE,
)

# Leave labels
_LEAVE_LABELS = {"LEAVE", "LEAVE (WRAPS AFTER)", "AL", "ANNUAL LEAVE"}


# ---------------------------------------------------------------------------
# Field-extraction helpers (act on whatever text the LLM/upstream captured)
# ---------------------------------------------------------------------------

def _title_of(day: dict) -> str:
    """Best-effort title/label for a day. Callers may have stashed the raw
    calendar-bar text in a variety of fields depending on which upstream
    extractor produced the input."""
    for k in ("label", "title", "raw", "raw_text", "notes", "text", "duty_text"):
        v = day.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _all_text(days: Iterable[dict], raw_text: str | None = None) -> str:
    parts: list[str] = []
    if raw_text:
        parts.append(raw_text)
    for d in days or []:
        parts.append(_title_of(d))
        for f in (d.get("flights") or []):
            if isinstance(f, dict):
                parts.append(" ".join(str(x) for x in f.values() if x))
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# BA detection
# ---------------------------------------------------------------------------

def detect_ba_calendar(days: list[dict], raw_text: str | None = None) -> dict:
    """Return a confidence report for whether these days look like a BA
    iOS-calendar screenshot.

    Confidence >= 0.6 → run BA parser.
    """
    text = _all_text(days or [], raw_text)
    if not text:
        return {"confidence": 0.0, "reasons": ["no text captured"], "indicators": {}}

    zulu = RE_RPT_ZULU.findall(text)
    ends = RE_ENDS.findall(text)
    routes = RE_BA_ROUTE.findall(text)
    trip_bars = [m.group(0) for m in RE_TRIP_BAR.finditer(text)]

    indicators = {
        "zulu_report_matches": len(zulu),
        "ends_matches": len(ends),
        "ba_route_matches": len(routes),
        "trip_bar_matches": len(trip_bars),
    }

    score = 0.0
    reasons: list[str] = []
    # BA's Zulu report notation is a very strong signature.
    if zulu:
        score += min(0.5, 0.2 + 0.1 * len(zulu))
        reasons.append(f"Rpt:HH:MMz found ×{len(zulu)}")
    if ends:
        score += min(0.25, 0.1 * len(ends))
        reasons.append(f"ends HH:MM found ×{len(ends)}")
    if routes:
        score += min(0.25, 0.1 * len(routes))
        reasons.append(f"BA route pattern ×{len(routes)}")
    if trip_bars:
        score += 0.15
        reasons.append(f"destination-first bar ×{len(trip_bars)}")

    # Presence of Emirates/RAK signatures nearby actively lowers confidence
    # so this adapter can't accidentally hijack a non-BA roster.
    if re.search(r"\bEK\d{3,4}\b|\bDXB\s+LT\b|Pickup Time", text):
        score -= 0.4
        reasons.append("Emirates/RAK signature detected — de-prioritising BA")

    score = max(0.0, min(1.0, score))
    return {
        "confidence": round(score, 3),
        "reasons": reasons,
        "indicators": indicators,
    }


# ---------------------------------------------------------------------------
# BA parser — deterministic
# ---------------------------------------------------------------------------

def _parse_iso_date(s: str) -> _dt.date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return _dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def parse_ba_calendar(days: list[dict], raw_text: str | None = None) -> dict:
    """Deterministic reshape of BA calendar days.

    Groups days that belong to the same trip (contiguous dates with the
    same trip-bar text), extracts destination/report/end/route from the
    bar, and rolls out one day-record per date in the trip range.
    """
    # Index the incoming days by date so we can join by trip title.
    day_map: dict[str, dict] = {}
    dates_seen: set[str] = set()
    dates_sorted: list[str] = []
    for d in (days or []):
        date = d.get("date")
        if not date:
            continue
        # Later rows for the same date overwrite earlier ones (this is how
        # helper labels like "Leave (Wraps After)" replace the earlier
        # "LEAVE" — dedup happens implicitly at the day_map level).
        day_map[date] = d
        if date not in dates_seen:
            dates_seen.add(date)
            dates_sorted.append(date)
    dates_sorted.sort()

    trips: list[dict] = []
    leave_blocks: list[dict] = []
    handled_dates: set[str] = set()

    # ---- Trip aggregation --------------------------------------------------
    # Group contiguous dates sharing the same trip-bar title.
    cur_group: list[str] = []
    cur_title = ""

    def _flush_group(group_dates: list[str], title: str):
        if not group_dates or not title:
            return
        m = RE_TRIP_BAR.match(title)
        if not m:
            return
        dest = m.group("dest").upper()
        report_h = int(m.group("h")); report_m = int(m.group("m"))
        report_time = f"{report_h:02d}:{report_m:02d}"
        raw_route = m.group("route")

        # Find the "ends HH:MM" text on the last day of the group, if present.
        end_time = None
        end_source_date = None
        for date in reversed(group_dates):
            t = _title_of(day_map.get(date, {}))
            em = RE_ENDS.search(t)
            if em:
                end_time = f"{int(em.group(1)):02d}:{int(em.group(2)):02d}"
                end_source_date = date
                break
        # Also search raw_text for a plain "ends HH:MM" attached to the group
        if not end_time and raw_text:
            for m2 in RE_ENDS.finditer(raw_text):
                end_time = f"{int(m2.group(1)):02d}:{int(m2.group(2)):02d}"
                break

        trip = {
            "trip_id": f"ba-{group_dates[0]}-{dest}",
            "start_date": group_dates[0],
            "end_date": group_dates[-1],
            "destination": dest,
            "report_time": report_time,
            "report_time_timezone": "utc",  # z suffix = Zulu
            "end_display_time": end_time,
            "end_time_timezone": "unspecified_local" if end_time else None,
            "end_date_of_time": end_source_date,
            "raw_route": raw_route,
            "raw_label": title.strip(),
            "type": "flight",
            "source_format": "ba_ios_calendar",
            "needs_confirmation": False,
            "notes": (
                "Flight numbers, positioning sectors, hotel and per-sector "
                "times are not shown in a month-view calendar and have not "
                "been invented."
            ),
        }
        trips.append(trip)
        handled_dates.update(group_dates)

    for d in dates_sorted:
        title = _title_of(day_map[d])
        # Ignore "ends HH:MM" trailing lines that appear on their own
        # (they belong to the current trip's title).
        if RE_TRIP_BAR.match(title):
            if title == cur_title and cur_group and _is_contiguous(cur_group[-1], d):
                cur_group.append(d)
            else:
                _flush_group(cur_group, cur_title)
                cur_title = title
                cur_group = [d]
        elif cur_group and (RE_ENDS.search(title) or not title):
            # Continuation of current trip (a day that only shows "ends HH:MM"
            # or is a middle day with no separate label re-print in the LLM
            # output). Only accept if contiguous.
            if _is_contiguous(cur_group[-1], d):
                cur_group.append(d)
            else:
                _flush_group(cur_group, cur_title)
                cur_group = []; cur_title = ""

    _flush_group(cur_group, cur_title)

    # ---- Leave aggregation (dedupe helpers) --------------------------------
    leave_dates: list[str] = []
    for d in dates_sorted:
        if d in handled_dates:
            continue
        t = _title_of(day_map[d]).upper().strip()
        if not t:
            continue
        # A day whose title contains any of the leave labels is a leave day.
        if any(lbl in t for lbl in _LEAVE_LABELS):
            leave_dates.append(d)

    if leave_dates:
        # Group into contiguous runs so overlapping helpers dedupe.
        runs: list[list[str]] = []
        for d in leave_dates:
            if runs and _is_contiguous(runs[-1][-1], d):
                runs[-1].append(d)
            else:
                runs.append([d])
        for run in runs:
            leave_blocks.append({
                "type": "leave",
                "start_date": run[0],
                "end_date": run[-1],
                "raw_label": "LEAVE",
                "source_format": "ba_ios_calendar",
                "needs_confirmation": False,
                "notes": "Grouped from LEAVE + Leave (Wraps After) helper labels.",
            })
            handled_dates.update(run)

    # ---- Roll out per-day entries ------------------------------------------
    out_days: list[dict] = []
    for trip in trips:
        s = _parse_iso_date(trip["start_date"])
        e = _parse_iso_date(trip["end_date"])
        if not s or not e:
            continue
        cur = s
        while cur <= e:
            iso = cur.isoformat()
            is_start = (cur == s)
            is_end = (cur == e)
            multi = (e > s)
            out_days.append({
                "date": iso,
                "day_type": "flight",
                "day_of_week": cur.strftime("%a"),
                "home_or_away": "away" if not is_start else "away",
                "report_time": trip["report_time"] if is_start else None,
                "report_time_timezone": "utc" if is_start else None,
                "release_time": trip["end_display_time"] if is_end else None,
                "release_time_timezone": "unspecified_local" if (is_end and trip["end_display_time"]) else None,
                "duty_end_time": trip["end_display_time"] if is_end else None,
                # Do NOT invent flight numbers.
                "flights": [],
                "sector_count": None,
                # Layover context — destination is the trip destination.
                "layover_city": trip["destination"] if multi else None,
                "hotel_name": None,
                "is_out_of_base": is_start or (not is_end and multi),
                "is_overnight": multi,
                "is_turnaround": (not multi),
                "is_layover_day": multi and not (is_start or is_end),
                "arrival_next_day": False,  # unknown from month view
                "layover_nights": max(0, (e - s).days) if multi else 0,
                # BA-specific fields for the coach UI
                "trip_id": trip["trip_id"],
                "raw_route": trip["raw_route"],
                "raw_label": trip["raw_label"],
                "destination": trip["destination"],
                "confidence": 0.85,
                "warnings": [
                    "Flight numbers not shown in month-view calendar.",
                    "End time timezone not specified — preserved as displayed.",
                    "Positioning sectors, hotel and per-sector times require a detailed roster upload.",
                ],
                "source_format": "ba_ios_calendar",
                "needs_confirmation": False,
                "notes": trip["notes"],
            })
            cur += _dt.timedelta(days=1)

    for block in leave_blocks:
        s = _parse_iso_date(block["start_date"])
        e = _parse_iso_date(block["end_date"])
        if not s or not e:
            continue
        cur = s
        while cur <= e:
            out_days.append({
                "date": cur.isoformat(),
                "day_type": "Annual Leave",
                "day_of_week": cur.strftime("%a"),
                "home_or_away": "home",
                "flights": [],
                "layover_city": None,
                "raw_label": "LEAVE",
                "confidence": 0.9,
                "source_format": "ba_ios_calendar",
                "needs_confirmation": False,
                "notes": block["notes"],
            })
            cur += _dt.timedelta(days=1)

    # Preserve any input days the adapter did NOT claim (e.g. rest/home days
    # the LLM extracted that don't belong to any trip). They pass through.
    for d in dates_sorted:
        if d in handled_dates:
            continue
        # Only pass through days the LLM already classified — otherwise omit.
        if day_map[d].get("day_type"):
            out_days.append(dict(day_map[d]))

    out_days.sort(key=lambda x: x.get("date") or "")
    return {"days": out_days, "trips": trips, "leave_blocks": leave_blocks}


def _is_contiguous(a: str, b: str) -> bool:
    """Return True if b == a + 1 day (ISO dates)."""
    da = _parse_iso_date(a); db = _parse_iso_date(b)
    if not da or not db:
        return False
    return (db - da).days == 1


# ---------------------------------------------------------------------------
# Public entrypoint used by the roster pipeline
# ---------------------------------------------------------------------------

def maybe_apply(
    days: list[dict],
    raw_text: str | None = None,
    min_confidence: float = 0.6,
) -> dict:
    """Detect + optionally apply the BA parser.

    Returns:
      {"applied": True/False, "days": [...], "trips": [...] (if applied),
       "leave_blocks": [...] (if applied), "detection": {...}, "reason": str}

    Fully idempotent and side-effect free. Callers can safely swap in
    `result["days"]` when `applied=True` and keep the original otherwise.
    """
    detection = detect_ba_calendar(days or [], raw_text)
    if detection["confidence"] < min_confidence:
        return {
            "applied": False,
            "days": days or [],
            "detection": detection,
            "reason": f"confidence {detection['confidence']} below threshold {min_confidence}",
        }
    try:
        parsed = parse_ba_calendar(days or [], raw_text)
    except Exception as e:  # never explode — always fall through
        return {
            "applied": False,
            "days": days or [],
            "detection": detection,
            "reason": f"parser exception: {e}",
        }
    # Guardrail — if the parser produced no trips AND no leave, don't clobber.
    if not parsed["trips"] and not parsed["leave_blocks"]:
        return {
            "applied": False,
            "days": days or [],
            "detection": detection,
            "reason": "no trips or leave extracted",
        }
    return {
        "applied": True,
        "days": parsed["days"],
        "trips": parsed["trips"],
        "leave_blocks": parsed["leave_blocks"],
        "detection": detection,
        "reason": "BA calendar signatures detected — deterministic re-parse applied",
    }
