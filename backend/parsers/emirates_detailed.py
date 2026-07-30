"""
Emirates Crew Roster (Detailed Report) parser
---------------------------------------------

Parser for Emirates FOIP "Detailed Report" PDF exports. The Detailed Report
is a tabular one-row-per-day layout with these columns:

    Day/Date | Duty/Trip Code | Label | Report | Time(Dep-Arv) |
    Duty Details | A/C | End | Block Hours

Unlike the Calendar Report (mon-sun grid), each date owns exactly one row in
the detailed table at the bottom of the PDF, which makes line-oriented text
extraction reliable. We deliberately IGNORE the small calendar strip at the
top of the PDF because flight codes wrap and get truncated there — the
detailed table is the source of truth.

Public API:
    * detect_emirates_detailed(pdf_bytes) -> bool
    * parse_emirates_detailed(pdf_bytes, filename=None) -> EmiratesResult
    * to_crewfit_days(result) -> list[dict]  (delegates to parsers.emirates)

Row types recognised:
    * flight            "EK237 [DXB-BOS]" / codeshare "AC8909 [YYZ-ORD]"
    * rest_day          "Rest Day"
    * day_off           trip code "XX", "Day Off"
    * available_duty    trip code "AVD", "AVAILABLE DUTY DAY"
    * sim_training      "B777 SIM ... SESSION ..." (typically trip code "A712")
    * unknown           anything else — flagged for coach review, never
                         silently coerced into a flight.

Cross-day markers:
    "(+)"  = day after departure date (long-haul overnight)
    "(-)"  = day before departure date (rare)
Preserved on the arrival_next_day flag AND embedded on the Sector.
"""
from __future__ import annotations
import io
import re
from datetime import date
from typing import Optional

# Reuse the exact dataclasses the Calendar Report parser already exposes so
# the downstream to_crewfit_days() mapping is identical for both variants.
from .emirates import EmiratesDay, EmiratesResult, EmiratesSector, _MONTHS  # type: ignore


BASE = "DXB"
# Emirates operates out of both DXB (Dubai International) and DWC (Al Maktoum).
# Both are the crew's home base for training/programme purposes; treat them
# as equivalent when deciding outbound/return direction and layover state.
_BASE_CODES = {"DXB", "DWC"}


def _is_base(code: Optional[str]) -> bool:
    return bool(code) and code in _BASE_CODES

# Detection needs *both* markers together to avoid matching Calendar Reports
# (which say "(Calendar Report)") or unrelated Emirates internal PDFs.
_DETAILED_MARKERS = ("emirates crew roster", "(detailed report)")


# ---------------------------------------------------------------------------
# Regex library.
# ---------------------------------------------------------------------------

# Start-of-row anchor: two digits + dash + three uppercase weekday letters.
_ROW_HEAD_RE = re.compile(r"^(\d{2})-([A-Z]{3})\b")

# Header line for the detailed table — used to locate where the calendar
# strip ends and the row table begins.
_TABLE_HEADER_RE = re.compile(
    r"Day/?Date.*Label.*Report.*Time.*Duty Details.*A/?C.*End.*Block", re.I
)

_STAFF_RE = re.compile(
    r"Staff\s*:\s*(\d+)\s+Name\s*:\s*(.+?)\s+\[([A-Z]+)\]\s+([A-Za-z]+)\s+(\d{4})"
)

# Codeshare flight numbers can be 3-5 digits and may use any 2-letter airline
# code (EK, AC, QF, etc.). We keep it broad but require an IATA route
# `[XXX-YYY]` on the same row to confirm it's a flight.
_ROUTE_RE = re.compile(r"([A-Z]{2}\d{2,5})\s+\[([A-Z]{3})-([A-Z]{3})\]")
_TIME_RANGE_RE = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})(\(\+\)|\(\-\))?")
_TIME_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")

# Emirates renders block hours as "14: 25" (extra space after colon). We
# normalise to "14:25".
_BLOCK_RE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})")


# ---------------------------------------------------------------------------
# Detection.
# ---------------------------------------------------------------------------

def detect_emirates_detailed(pdf_bytes: bytes) -> bool:
    """Return True iff the PDF is an Emirates *Detailed* Report.

    Requires *both* markers so it never falsely matches the Calendar Report
    or another airline's roster.
    """
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                return False
            txt = (pdf.pages[0].extract_text() or "").lower()
            return all(m in txt for m in _DETAILED_MARKERS)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Row classification + field extraction.
# ---------------------------------------------------------------------------

def _classify_row(text: str) -> str:
    """Return one of: rest_day | day_off | available_duty | sim_training |
    flight | unknown. Never guesses — priority order matters."""
    up = text.upper()
    if "REST DAY" in up:
        return "rest_day"
    if "AVAILABLE DUTY DAY" in up or re.search(r"\bAVD\b", up):
        return "available_duty"
    if "DAY OFF" in up:
        return "day_off"
    if "SIM" in up or "SESSION" in up:
        return "sim_training"
    if _ROUTE_RE.search(text):
        return "flight"
    return "unknown"


def _normalize_block(raw: str) -> Optional[str]:
    m = _BLOCK_RE.search(raw or "")
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _parse_flight_row(text: str) -> dict:
    """Extract flight fields from a single detailed-table row. Missing fields
    return None rather than being invented."""
    out: dict = {}
    m_route = _ROUTE_RE.search(text)
    if not m_route:
        return out
    out["flight_number"] = m_route.group(1)
    out["origin"] = m_route.group(2)
    out["destination"] = m_route.group(3)

    # Tokens before the route — trip code (first non-day token) + report time
    prefix = text[: m_route.start()].strip()
    # Remove the "DD-WKD" head
    prefix = _ROW_HEAD_RE.sub("", prefix).strip()
    tokens = prefix.split()
    if tokens:
        out["trip_code"] = tokens[0]
    # Time range e.g. "10:00-15:00" or "23:00-20:00(+)"
    m_tr = _TIME_RANGE_RE.search(text)
    if m_tr:
        out["departure_time"] = m_tr.group(1)
        out["arrival_time"] = m_tr.group(2)
        out["arrival_next_day"] = m_tr.group(3) == "(+)"
        out["arrival_prev_day"] = m_tr.group(3) == "(-)"
    # Report time is the last HH:MM token before the time range (if any).
    if m_tr:
        pre_range = text[: m_tr.start()]
    else:
        pre_range = prefix
    reports = re.findall(r"\b(\d{2}:\d{2})\b", pre_range)
    if reports:
        out["report_time"] = reports[-1]

    # After the route: A/C (optional) | End time | Block hours
    tail = text[m_route.end():].strip()
    # End time can be "15:15" or "20:30 (+)"
    m_end = re.search(r"(\d{2}:\d{2})\s*(\(\+\)|\(\-\))?", tail)
    if m_end:
        out["duty_end"] = m_end.group(1)
        out["duty_end_next_day"] = m_end.group(2) == "(+)"
        # A/C is any token(s) sitting between route and end time
        ac_zone = tail[: m_end.start()].strip()
        # If ac_zone is only a "-" placeholder, treat as no A/C.
        if ac_zone and ac_zone not in ("-",):
            # Take the last token that looks like an A/C code (letters+digits)
            ac_tokens = [t for t in ac_zone.split() if re.match(r"^[A-Z0-9]{2,5}$", t)]
            if ac_tokens:
                out["aircraft"] = ac_tokens[-1]
        # Block hours after End
        block_zone = tail[m_end.end():].strip()
        blk = _normalize_block(block_zone)
        if blk:
            out["block_hours"] = blk
    return out


def _parse_sim_row(text: str) -> dict:
    """Extract sim/training fields. Handles wrapped continuation lines that
    have already been concatenated into `text`."""
    out: dict = {"duty_details": None}
    # Strip head
    body = _ROW_HEAD_RE.sub("", text).strip()
    tokens = body.split()
    if tokens:
        out["trip_code"] = tokens[0]
    # Report time: first HH:MM in body
    m_report = re.search(r"\b(\d{2}:\d{2})\b", body)
    if m_report:
        out["report_time"] = m_report.group(1)
    # End time: last HH:MM in body
    times = re.findall(r"\b(\d{2}:\d{2})\b", body)
    if len(times) >= 2:
        out["duty_end"] = times[-1]
    # Duty details: the SIM description, best-effort.
    m_desc = re.search(r"(B\d{3}\s+SIM.*?)(?:\s+\d{2}:\d{2}|$)", body, re.I)
    if m_desc:
        out["duty_details"] = m_desc.group(1).strip().rstrip(" -")
    else:
        out["duty_details"] = body
    return out


def _parse_avd_row(text: str) -> dict:
    """Extract AVD fields (available duty). Report + end time only."""
    out: dict = {"duty_details": "AVAILABLE DUTY DAY"}
    body = _ROW_HEAD_RE.sub("", text).strip()
    tokens = body.split()
    if tokens:
        out["trip_code"] = tokens[0]  # typically "AVD"
    times = re.findall(r"\b(\d{2}:\d{2})\b", body)
    if len(times) >= 1:
        out["report_time"] = times[0]
    if len(times) >= 2:
        out["duty_end"] = times[-1]
    return out


# ---------------------------------------------------------------------------
# Public parser.
# ---------------------------------------------------------------------------

def parse_emirates_detailed(pdf_bytes: bytes, filename: Optional[str] = None) -> EmiratesResult:
    """Parse an Emirates Crew Roster (Detailed Report) PDF into the shared
    EmiratesResult shape. Guarantees exactly one EmiratesDay per calendar
    date in the roster month (missing dates get flagged rather than
    fabricated)."""
    result = EmiratesResult()
    result.template = "emirates_crew_roster_detailed_report"
    if not detect_emirates_detailed(pdf_bytes):
        return result
    result.detected = True

    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        text = page.extract_text() or ""

    # Header — staff, name, rank, month, year.
    m = _STAFF_RE.search(text)
    if m:
        result.crew_id = m.group(1)
        result.crew_name = m.group(2).strip()
        result.month = _MONTHS.get(m.group(4).lower())
        result.year = int(m.group(5))
    if not result.month or not result.year:
        result.warnings.append("Could not detect month/year in Detailed Report header")
        return result

    # Locate the detailed table start (skip calendar strip at top).
    lines = text.splitlines()
    table_start = None
    for i, ln in enumerate(lines):
        if _TABLE_HEADER_RE.search(ln):
            table_start = i + 1
            break
    if table_start is None:
        # Fallback: use the first line that looks like a day row.
        for i, ln in enumerate(lines):
            if _ROW_HEAD_RE.match(ln.strip()):
                table_start = i
                break
    if table_start is None:
        result.warnings.append("Could not locate detailed table in PDF")
        return result

    # Group table rows: each starts with `DD-WKD`. Consecutive non-day lines
    # after a row are appended to that row (handles SIM description wrap
    # e.g. "BLDG A").
    grouped: list[list[str]] = []
    for ln in lines[table_start:]:
        s = ln.strip()
        if not s:
            continue
        # Stop at footer marker.
        if s.lower().startswith("total block hours") or s.lower().startswith("all times in"):
            break
        if _ROW_HEAD_RE.match(s):
            grouped.append([s])
        elif grouped:
            grouped[-1].append(s)

    seen_dates: set[str] = set()
    for row_lines in grouped:
        head = row_lines[0]
        joined = " ".join(row_lines)  # SIM wrap tolerant
        m_head = _ROW_HEAD_RE.match(head)
        if not m_head:
            continue
        dnum = int(m_head.group(1))
        wkd = m_head.group(2)
        try:
            iso = date(result.year, result.month, dnum).isoformat()
        except ValueError:
            continue

        day = EmiratesDay(date=iso, weekday=wkd, raw_cell_text=joined)
        kind = _classify_row(joined)

        if kind == "rest_day":
            day.day_type = "rest_day"
            day.auto_label = "REST_DAY"
            day.training_colour = "amber"
            day.programme_decision_reason = "Rest day — treat conservatively."
            day.parse_confidence = 0.99

        elif kind == "day_off":
            day.day_type = "day_off"
            day.auto_label = "DAY_OFF"
            day.training_colour = "green"
            day.parse_confidence = 0.99

        elif kind == "available_duty":
            fields = _parse_avd_row(joined)
            day.day_type = "available_duty"
            day.auto_label = "AVAILABLE_DUTY"
            day.training_colour = "amber"
            day.duty_start_local = fields.get("report_time")
            day.duty_end_local = fields.get("duty_end")
            day.programme_decision_reason = (
                "Available duty (AVD) — treat as light day pending assignment."
            )
            day.parse_confidence = 0.95

        elif kind == "sim_training":
            fields = _parse_sim_row(joined)
            day.day_type = "sim_training"
            day.auto_label = "SIM_TRAINING"
            day.training_colour = "amber"
            day.duty_start_local = fields.get("report_time")
            day.duty_end_local = fields.get("duty_end")
            day.programme_decision_reason = (
                "Simulator duty — short morning session only if suitable."
            )
            day.equipment_assumption = "any"
            day.parse_confidence = 0.95

        elif kind == "flight":
            fields = _parse_flight_row(joined)
            fno = fields.get("flight_number")
            orig = fields.get("origin")
            dest = fields.get("destination")
            if fno and orig and dest:
                sector = EmiratesSector(
                    flight_number=fno,
                    origin=orig,
                    destination=dest,
                    departure_time_local=fields.get("departure_time"),
                    arrival_time_local=fields.get("arrival_time"),
                    arrival_next_day=bool(fields.get("arrival_next_day")),
                )
                day.sectors.append(sector)
                day.flight_number = fno
                day.route_airports = [orig, dest]
                day.start_location = orig
                day.end_location = dest
                day.duty_start_local = fields.get("report_time") or fields.get("departure_time")
                day.duty_end_local = fields.get("duty_end")
                day.arrival_next_day = bool(fields.get("arrival_next_day"))
                day.is_out_of_base = not _is_base(dest)
                day.is_overnight = not _is_base(orig) and _is_base(dest) and bool(fields.get("arrival_next_day"))
                day.is_turnaround = _is_base(orig) and _is_base(dest)  # unlikely in detailed table
                day.day_type = "flight"
                # Refined label: outbound vs return
                if _is_base(orig) and not _is_base(dest):
                    day.auto_label = "LONG_HAUL_OUTBOUND"
                elif not _is_base(orig) and _is_base(dest):
                    day.auto_label = "LONG_HAUL_RETURN"
                else:
                    day.auto_label = "LONG_HAUL_SECTOR"
                day.training_colour = "red" if day.arrival_next_day else "amber"
                day.programme_decision_reason = (
                    f"Flight {fno} {orig}→{dest}"
                    + (" (overnight)" if day.arrival_next_day else "")
                )
                day.parse_confidence = 0.97
            else:
                day.day_type = "flight"
                day.auto_label = "NEEDS_REVIEW"
                day.needs_coach_review = True
                day.parse_confidence = 0.4
                day.warnings.append("Flight row detected but fields incomplete")

        else:  # unknown
            day.day_type = "unknown"
            day.auto_label = "NEEDS_REVIEW"
            day.training_colour = "amber"
            day.needs_coach_review = True
            day.parse_confidence = 0.3
            day.warnings.append(f"Row not classifiable: {joined[:80]}")

        if iso in seen_dates:
            day.warnings.append("Duplicate date in detailed table")
        seen_dates.add(iso)
        result.days.append(day)

    # Backfill any missing calendar dates so downstream systems always see 28-31 records
    from calendar import monthrange
    _, last_day = monthrange(result.year, result.month)
    for d_num in range(1, last_day + 1):
        iso = date(result.year, result.month, d_num).isoformat()
        if iso not in seen_dates:
            missing = EmiratesDay(
                date=iso,
                weekday=date(result.year, result.month, d_num).strftime("%a").upper(),
                day_type="unknown",
                auto_label="NEEDS_REVIEW",
                needs_coach_review=True,
                parse_confidence=0.0,
            )
            missing.warnings.append("Row missing from detailed table — flagged for review")
            result.days.append(missing)
            seen_dates.add(iso)

    result.days.sort(key=lambda d: d.date)

    # Layover pairing pass — if crew ends day in non-BASE, subsequent rest_day
    # rows before returning to BASE are LAYOVER_REST_DAY (mirrors calendar
    # parser behavior).
    open_city: Optional[str] = None
    for d in result.days:
        if d.day_type == "flight" and d.end_location and not _is_base(d.end_location):
            open_city = d.end_location
            continue
        if d.day_type == "flight" and _is_base(d.end_location):
            open_city = None
            continue
        if open_city and d.day_type == "rest_day":
            d.auto_label = "LAYOVER_REST_DAY"
            d.day_type = "layover_rest"
            d.training_colour = "amber"
            d.equipment_assumption = "hotel_or_bodyweight_only"
            d.is_layover_day = True
            d.programme_decision_reason = f"Layover rest in {open_city} — hotel/bodyweight only."

    if result.days:
        result.parse_confidence = round(
            sum(d.parse_confidence for d in result.days) / len(result.days), 3
        )
    return result


# to_crewfit_days is intentionally re-exported from the shared module so any
# downstream code that already imports it from parsers.emirates continues to
# work. The detailed parser produces exactly the same EmiratesResult shape.
from .emirates import to_crewfit_days  # noqa: E402, F401
