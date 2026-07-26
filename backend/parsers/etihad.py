"""
Etihad Personal Crew Schedule parser
------------------------------------

Airline-specific parser for Etihad's monthly grid roster PDF. Uses
coordinate-based text extraction (via pdfplumber) rather than linear text
so we can reliably split the horizontal monthly grid into 31 day columns.

Why: the previous LLM-only parser conflates duties across days because
Etihad's format is a horizontal calendar grid — each day is a narrow
column with duty tokens stacked vertically. Reading the PDF as linear
text mixes days together.

Public API:
    * detect_etihad(pdf_bytes) -> bool
    * parse_etihad_pdf(pdf_bytes, filename=None) -> ParseResult

Design principles (from Louis's brief):
    * Bad data > No data → block auto workout generation if confidence low
    * No client-facing "AI" wording
    * Column-first parsing, not linear text
    * Multi-sector days preserved (do not dedup repeated flight numbers)
    * Blank days INSIDE an out-of-base pairing => layover_day, NOT off
    * ↓ arrow at start of a column => overnight continuation from previous
    * XX => unknown/unavailable, needs review
    * A02:32 => strip "A" prefix (actual time), keep 02:32
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Small typed structures.
# ---------------------------------------------------------------------------

@dataclass
class Sector:
    flight_number: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    arrival_date: Optional[str] = None      # only set for overnight arrivals
    aircraft: Optional[str] = None


@dataclass
class ParsedDay:
    date: str
    weekday: Optional[str] = None
    raw_column_text: str = ""

    day_type: str = "unknown"               # off | rest | rostered_off | standby | flight | multi_sector_flight | flight_to_layover | layover_day | return_from_layover | overnight_flight | turnaround | unknown

    report_time: Optional[str] = None
    release_time: Optional[str] = None
    standby_start: Optional[str] = None
    standby_end: Optional[str] = None

    base: str = "AUH"
    start_location: Optional[str] = None
    end_location: Optional[str] = None
    layover_city: Optional[str] = None

    sectors: list[Sector] = field(default_factory=list)
    sector_count: int = 0

    is_overnight: bool = False
    is_layover_day: bool = False
    is_turnaround: bool = False
    is_out_of_base: bool = False

    notes: list[str] = field(default_factory=list)
    parse_confidence: float = 0.7
    warnings: list[str] = field(default_factory=list)
    needs_client_review: bool = False
    needs_coach_review: bool = False

    training_impact: str = "green"          # green | amber | red | recovery | unavailable


@dataclass
class ParseResult:
    detected: bool
    airline: str = "etihad"
    template: str = "etihad_personal_crew_schedule"
    crew_id: Optional[str] = None
    crew_name: Optional[str] = None
    crew_base: str = "AUH"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    days: list[ParsedDay] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_confidence: float = 0.0
    reported_totals: dict = field(default_factory=dict)     # from Total Hours / Statistics table


# ---------------------------------------------------------------------------
# Detection.
# ---------------------------------------------------------------------------

_ETIHAD_MARKERS = (
    "etihad",
    "personal crew schedule",
    "all times in local station",
)


def detect_etihad(pdf_bytes: bytes) -> bool:
    """Return True if the PDF is an Etihad Personal Crew Schedule Report."""
    try:
        import pdfplumber
    except Exception:
        return False
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                return False
            txt = (pdf.pages[0].extract_text() or "").lower()
            hits = sum(1 for m in _ETIHAD_MARKERS if m in txt)
            return hits >= 2
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Regex helpers.
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^A?(\d{1,2}):(\d{2})$")   # accepts A02:32 too
_AIRPORT_RE = re.compile(r"^[A-Z]{3}$")           # 3-letter IATA
_AIRCRAFT_BRACKETED_RE = re.compile(r"^\[([0-9A-Z]{3,4})\]$")
_FLIGHT_NO_RE = re.compile(r"^\d{2,4}$")          # 200-9999 (Etihad flight numbers)
_DELAY_HHMM_RE = re.compile(r"^\d{1,2}:\d{2}$")
_STATUS_TOKENS = {"OFF", "SBY", "REST", "ROFF", "XX", "DELAY"}
_ARROW_TOKENS = {"→", "↓", "↑", "←"}


def _norm_time(tok: str) -> Optional[str]:
    """Normalise 'A02:32' -> '02:32'. Returns None if not a time."""
    m = _TIME_RE.match(tok)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh > 23 or mm > 59:
        return None
    return f"{hh:02d}:{mm:02d}"


def _clean_token(t: str) -> str:
    """Etihad PDFs sprinkle U+200B (zero-width space) and other invisible
    characters into tokens. Strip them."""
    return t.replace("\u200b", "").replace("\u200e", "").replace("\u200f", "").strip()


# ---------------------------------------------------------------------------
# Column extraction.
# ---------------------------------------------------------------------------

def _extract_columns(pdf_bytes: bytes) -> tuple[dict, list[list[str]], list[dict]]:
    """Break the PDF into 31 day columns.

    Returns
    -------
    meta : dict with month/year/crew info
    column_tokens : list[list[str]] — one list per day column (top-to-bottom)
    warnings : list[dict] — page-level warnings
    """
    import pdfplumber

    meta: dict = {"warnings": []}
    all_days: list[list[str]] = [[] for _ in range(31)]
    non_column_lines: list[str] = []      # for totals / statistics extraction

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
        words = [{
            "text": _clean_token(w["text"]),
            "x0": w["x0"],
            "x1": w["x1"],
            "top": w["top"],
        } for w in words if _clean_token(w["text"])]

        # ---- Locate the date header row (row of "DD/MM" tokens) ----
        date_regex = re.compile(r"^(\d{2})/(\d{2})$")
        date_rows: dict[float, list[dict]] = {}
        for w in words:
            m = date_regex.match(w["text"])
            if m:
                key = round(w["top"], 0)
                date_rows.setdefault(key, []).append(w)

        # The date header row is the row with the most DD/MM tokens (typically 28–31).
        header_row_y = None
        best_count = 0
        for y, ws in date_rows.items():
            if len(ws) > best_count and len(ws) >= 20:
                best_count = len(ws)
                header_row_y = y
        if header_row_y is None:
            meta["warnings"].append({"code": "no_date_header", "message": "Could not locate the monthly grid date header."})
            return meta, all_days, meta["warnings"]

        header_words = sorted(date_rows[header_row_y], key=lambda w: w["x0"])
        # Etihad rosters always show all 31 columns for months with fewer days
        # (e.g. June shows 30 valid + 1 placeholder). Some months genuinely
        # have 31 columns. We keep up to 31.
        month = int(date_regex.match(header_words[0]["text"]).group(2))
        # Deduce year from any full date on the page.
        year: Optional[int] = None
        full_date_re = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
        for w in words:
            m2 = full_date_re.match(w["text"])
            if m2 and int(m2.group(2)) == month:
                year = int(m2.group(3))
                break
        if year is None:
            year = date.today().year
        meta["month"] = month
        meta["year"] = year

        # Column x-bounds: midpoints between adjacent date headers.
        col_bounds: list[tuple[float, float]] = []
        for i, w in enumerate(header_words):
            left = w["x0"] - 6 if i == 0 else (header_words[i - 1]["x1"] + w["x0"]) / 2
            right = (w["x1"] + header_words[i + 1]["x0"]) / 2 if i + 1 < len(header_words) else w["x1"] + 8
            col_bounds.append((left, right))

        # Weekday row is immediately below the date header row.
        weekday_row_y = None
        row_ys = sorted(set(round(w["top"], 0) for w in words if round(w["top"], 0) > header_row_y))
        if row_ys:
            weekday_row_y = row_ys[0]
        meta["column_dates"] = []
        weekdays: list[Optional[str]] = [None] * len(header_words)
        for i, hw in enumerate(header_words):
            m = date_regex.match(hw["text"])
            day = int(m.group(1))
            try:
                dt = date(year, month, day)
                meta["column_dates"].append(dt.isoformat())
            except ValueError:
                meta["column_dates"].append(None)
        if weekday_row_y is not None:
            weekday_words = [w for w in words if round(w["top"], 0) == weekday_row_y]
            for ww in weekday_words:
                cx = (ww["x0"] + ww["x1"]) / 2
                for i, (l, r) in enumerate(col_bounds):
                    if l <= cx <= r:
                        weekdays[i] = ww["text"]
                        break
        meta["weekdays"] = weekdays

        # ---- Duty content area is anything BELOW the weekday row ----
        duty_y0 = (weekday_row_y or header_row_y) + 4
        # A "Total Hours"/"Statistics"/"Other Crew" section starts LATER on
        # the page — detect its start Y so we can ignore rows below it.
        total_y = None
        for w in words:
            t = w["text"].lower()
            if t in ("total", "statistics", "hours", "days") and w["top"] > duty_y0:
                # Only trigger if there's a "Total Hours"/"Statistics" label alongside.
                nearby = [x for x in words
                          if abs(x["top"] - w["top"]) < 3
                          and x["x0"] > w["x1"] - 40 and x["x0"] < w["x1"] + 220]
                nearby_text = " ".join(x["text"].lower() for x in nearby)
                if "total" in nearby_text and ("hours" in nearby_text or "statistics" in nearby_text):
                    total_y = w["top"]
                    break
        if total_y is None:
            # Fallback: everything above 500 is the calendar, below is footer/statistics.
            total_y = 480

        # Collect the calendar-area words into their columns.
        col_words: list[list[dict]] = [[] for _ in range(len(header_words))]
        for w in words:
            if w["top"] < duty_y0 or w["top"] >= total_y:
                continue
            cx = (w["x0"] + w["x1"]) / 2
            for i, (l, r) in enumerate(col_bounds):
                if l <= cx <= r:
                    col_words[i].append(w)
                    break

        # Sort each column top-to-bottom; produce tokens list.
        for i, ws in enumerate(col_words):
            ws.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
            all_days[i] = [w["text"] for w in ws]

        # Reported totals from the footer table (best-effort).
        totals: dict = {}
        for w in words:
            if w["top"] < total_y:
                continue
            non_column_lines.append(w["text"])
        footer = " ".join(non_column_lines).lower()
        # Extract simple integers next to known labels.
        def _grab_int(after_label: str) -> Optional[int]:
            m = re.search(rf"{after_label}[\s:]+(\d+)", footer)
            return int(m.group(1)) if m else None
        totals["flight_days"] = _grab_int("flight days")
        totals["off_days"] = _grab_int("off days")
        totals["standby_days"] = _grab_int("standby days")
        totals["rest_days"] = _grab_int("rest days") or _grab_int("roff")
        meta["reported_totals"] = totals

        # Return up to 31 columns even if the actual month has fewer valid dates.
        return meta, all_days[: len(header_words)], meta["warnings"]


# ---------------------------------------------------------------------------
# Per-column parsing (tokens -> ParsedDay).
# ---------------------------------------------------------------------------

def _parse_day(iso_date: str, weekday: Optional[str], tokens: list[str]) -> ParsedDay:
    """Interpret a single day's ordered tokens into a ParsedDay object."""
    day = ParsedDay(date=iso_date, weekday=weekday, raw_column_text=" | ".join(tokens))

    cleaned = [_clean_token(t) for t in tokens if _clean_token(t)]
    if not cleaned:
        day.day_type = "off"
        day.parse_confidence = 0.6
        day.notes.append("Blank column — may be OFF or an implicit layover day (see layover inference).")
        return day

    upper_tokens = [t.upper() for t in cleaned]

    # ---- Status-only column ----
    if len(upper_tokens) <= 3 and any(t in _STATUS_TOKENS for t in upper_tokens):
        first = upper_tokens[0]
        if first == "OFF":
            day.day_type = "off"
            day.parse_confidence = 0.98
            day.training_impact = "green"
            return day
        if first == "REST":
            day.day_type = "rest"
            day.parse_confidence = 0.98
            day.training_impact = "recovery"
            return day
        if first == "ROFF":
            day.day_type = "rostered_off"
            day.parse_confidence = 0.98
            day.training_impact = "green"
            return day
        if first == "XX":
            day.day_type = "unknown"
            day.parse_confidence = 0.4
            day.needs_client_review = True
            day.warnings.append("Roster shows XX — needs Pietro to confirm.")
            day.training_impact = "unavailable"
            return day

    # ---- Standby ----
    if "SBY" in upper_tokens:
        day.day_type = "standby"
        times = [t for t in cleaned if _norm_time(t)]
        if len(times) >= 2:
            day.standby_start = _norm_time(times[0])
            day.standby_end = _norm_time(times[1])
        elif len(times) == 1:
            day.standby_start = _norm_time(times[0])
            day.warnings.append("Standby end time not detected — check with roster.")
            day.needs_client_review = True
        day.training_impact = "amber"
        day.parse_confidence = 0.95 if len(times) >= 2 else 0.7
        return day

    # ---- Flight day ----
    times = [t for t in cleaned if _norm_time(t) is not None]
    airports = [t for t in cleaned if _AIRPORT_RE.match(t)]
    aircraft = [_AIRCRAFT_BRACKETED_RE.match(t).group(1)
                for t in cleaned if _AIRCRAFT_BRACKETED_RE.match(t)]
    flight_nos = [t for t in cleaned if _FLIGHT_NO_RE.match(t) and t not in [t2 for t2 in cleaned if _norm_time(t2)]]
    has_arrow = any(t in _ARROW_TOKENS for t in cleaned)
    starts_with_arrow = cleaned[0] in _ARROW_TOKENS if cleaned else False

    if not (times or airports or flight_nos):
        # Content but no recognisable duty — mark for review.
        day.day_type = "unknown"
        day.parse_confidence = 0.3
        day.needs_client_review = True
        day.warnings.append("Content present but no clear duty pattern found.")
        return day

    # Etihad column layout (top-to-bottom):
    #   [report_time] [flight_no] [dep_time] [origin] [dest] [arr_time] [aircraft]
    #   ...repeat for each sector...
    #   [release_time]
    #
    # Sectors are detected by grouping flight_no + (dep_time OR times) +
    # (origin+dest OR two airports) + arr_time + aircraft. Because tokens
    # are already in vertical order, we walk them left-to-right and pair
    # them into sectors.

    day.day_type = "flight"
    day.report_time = _norm_time(times[0]) if times else None
    day.release_time = _norm_time(times[-1]) if len(times) >= 2 else None

    # Walk the tokens and pull out sector groups.
    sectors: list[Sector] = []
    i = 0
    # Report time is usually the very first token; skip it.
    if times and cleaned and cleaned[0] == times[0]:
        i = 1

    while i < len(cleaned):
        tok = cleaned[i]
        # A sector starts with a flight number.
        if _FLIGHT_NO_RE.match(tok):
            s = Sector(flight_number=tok)
            # Collect the next few tokens as candidates.
            slice_ = cleaned[i + 1 : i + 8]
            slice_times = [_norm_time(t) for t in slice_ if _norm_time(t)]
            slice_airports = [t for t in slice_ if _AIRPORT_RE.match(t)]
            slice_aircraft = [_AIRCRAFT_BRACKETED_RE.match(t).group(1)
                              for t in slice_ if _AIRCRAFT_BRACKETED_RE.match(t)]
            if slice_times:
                s.departure_time = slice_times[0]
            if len(slice_times) >= 2:
                s.arrival_time = slice_times[1]
            if slice_airports:
                s.origin = slice_airports[0]
            if len(slice_airports) >= 2:
                s.destination = slice_airports[1]
            if slice_aircraft:
                s.aircraft = slice_aircraft[0]
            sectors.append(s)
            # Advance past this sector's expected tokens.
            step = 1
            for t in slice_:
                if _FLIGHT_NO_RE.match(t):
                    break
                step += 1
            i += step
            continue
        i += 1

    # Filter out sectors that clearly have no useful info.
    sectors = [s for s in sectors if s.flight_number and (s.origin or s.destination or s.departure_time)]
    day.sectors = sectors
    day.sector_count = len(sectors)

    if len(sectors) >= 2:
        day.day_type = "multi_sector_flight"

    if sectors:
        day.start_location = sectors[0].origin
        day.end_location = sectors[-1].destination
        day.is_turnaround = (
            day.start_location == "AUH" and day.end_location == "AUH" and len(sectors) >= 2
        )
        day.is_out_of_base = day.end_location and day.end_location != "AUH"

    if starts_with_arrow:
        day.is_overnight = True
        day.notes.append("Overnight continuation from previous day (arrow marker detected).")

    # Right-arrow at end of column => flight continues into next day.
    if any(t == "→" for t in cleaned):
        day.is_overnight = True
        day.is_out_of_base = True
        day.notes.append("Flight continues into next day (→ marker detected).")
        if day.day_type == "flight" and day.sectors:
            day.day_type = "overnight_flight"

    # ---- Warnings / confidence heuristics ----
    if not day.report_time or not day.release_time:
        day.warnings.append("Missing report or release time.")
        day.needs_client_review = True
    if any(s.origin is None or s.destination is None for s in sectors):
        day.warnings.append("A sector is missing origin/destination airport.")
        day.needs_client_review = True

    # Delay note?
    if any(t.lower() == "delay" for t in cleaned):
        day.notes.append("Delay note present.")

    # Training impact.
    if day.is_turnaround or day.day_type == "multi_sector_flight":
        day.training_impact = "red"
    elif day.day_type == "flight":
        day.training_impact = "amber"

    day.parse_confidence = 0.9 if sectors and day.report_time and day.release_time else 0.65
    return day


# ---------------------------------------------------------------------------
# Second-pass rules: layover inference, overnight continuation, closing pairings.
# ---------------------------------------------------------------------------

def _post_process(days: list[ParsedDay]) -> list[ParsedDay]:
    """Apply structural rules across days: layover inference + overnight merge."""
    # Overnight continuation: if day N starts with ↓ and day N-1 ends out-of-base,
    # treat day N-1 + N as one duty. Attach day N's sectors to a shared pairing.
    for i, d in enumerate(days):
        if d.is_overnight and i > 0 and days[i - 1].is_out_of_base:
            prev = days[i - 1]
            prev.day_type = "overnight_flight"
            prev.notes.append(f"Continues into next day ({d.date}).")
            # Merge d's sectors into prev? Keep them on d as well but flag as
            # continuation. We DON'T re-write d's date, but we mark it clearly.
            d.day_type = "return_from_layover" if (d.sectors and d.end_location == "AUH") else "overnight_flight"
            d.notes.append(f"Started as overnight from {prev.date}.")

    # Layover inference: track open out-of-base pairings across the month.
    open_since: Optional[int] = None
    open_city: Optional[str] = None
    for i, d in enumerate(days):
        if d.is_out_of_base and open_since is None and d.day_type in ("flight", "multi_sector_flight", "overnight_flight"):
            open_since = i
            open_city = d.end_location
            d.day_type = d.day_type if d.day_type == "overnight_flight" else "flight_to_layover"
            d.layover_city = open_city
            continue

        if open_since is not None:
            # Return day: sectors starting at open_city and ending AUH.
            starts_at_layover = bool(d.sectors) and d.start_location == open_city
            ends_at_auh = bool(d.sectors) and d.end_location == "AUH"
            if starts_at_layover and ends_at_auh:
                d.day_type = "return_from_layover"
                d.layover_city = open_city
                open_since = None
                open_city = None
                continue
            # Blank day inside a pairing => layover day.
            if not d.sectors and d.day_type in ("off", "unknown"):
                d.day_type = "layover_day"
                d.is_layover_day = True
                d.layover_city = open_city
                d.training_impact = "amber"
                d.notes.append(f"Blank day inside an out-of-base pairing → inferred layover in {open_city}.")
                d.parse_confidence = min(d.parse_confidence, 0.75)
                d.needs_client_review = True
                continue

    return days


# ---------------------------------------------------------------------------
# Top-level parse.
# ---------------------------------------------------------------------------

def parse_etihad_pdf(pdf_bytes: bytes, filename: Optional[str] = None) -> ParseResult:
    result = ParseResult(detected=False)
    if not detect_etihad(pdf_bytes):
        return result
    result.detected = True

    meta, columns, warnings = _extract_columns(pdf_bytes)
    for w in warnings:
        result.warnings.append(w.get("message", ""))

    days: list[ParsedDay] = []
    for i, col_tokens in enumerate(columns):
        iso = meta["column_dates"][i] if i < len(meta.get("column_dates", [])) else None
        weekday = meta.get("weekdays", [None] * 31)[i] if i < len(meta.get("weekdays", [])) else None
        if not iso:
            continue
        days.append(_parse_day(iso, weekday, col_tokens))

    days = _post_process(days)
    result.days = days
    if days:
        result.start_date = days[0].date
        result.end_date = days[-1].date
    result.parse_confidence = round(
        sum(d.parse_confidence for d in days) / max(1, len(days)), 3
    )
    result.reported_totals = meta.get("reported_totals", {})
    return result


# ---------------------------------------------------------------------------
# Conversion helper for the wider CrewFit pipeline.
# ---------------------------------------------------------------------------

def to_crewfit_days(pr: ParseResult) -> list[dict]:
    """Convert ParseResult to the app-native day list expected by the rest of
    the CrewFit roster pipeline (matches the shape produced by the LLM
    parser)."""
    # CrewFit VALID_DAY_TYPES (server.py line 5450):
    #   home_day, turnaround, layover_arrival, layover_full, layover_departure,
    #   standby, reserve, simulator, annual_leave, holiday, sick, injury,
    #   family, busy, rest, custom
    # Any other value is treated as "unknown" by the plan generator, causing
    # sessions to be skipped. Map every Etihad-parser type to a valid one.
    _MAP = {
        "off": "home_day",              # OFF day at base
        "rest": "rest",
        "rostered_off": "home_day",     # ROFF = rostered off, treat as free/home day
        "standby": "standby",
        "flight": "turnaround",         # single-sector day, usually AUH→X→AUH
        "multi_sector_flight": "turnaround",
        "flight_to_layover": "layover_arrival",
        "layover_day": "layover_full",  # inferred blank day inside a pairing
        "return_from_layover": "layover_departure",
        "overnight_flight": "layover_arrival",  # starts at base, ends out
        "turnaround": "turnaround",
        "unknown": "custom",            # blocks auto-gen until confirmed
    }
    out: list[dict] = []
    for d in pr.days:
        flights = []
        for s in d.sectors:
            flights.append({
                "flight_number": s.flight_number,
                "origin": s.origin,
                "destination": s.destination,
                "dep_time": s.departure_time,
                "arr_time": s.arrival_time,
                "aircraft": s.aircraft,
            })
        out.append({
            "date": d.date,
            "weekday": d.weekday,
            "day_type": _MAP.get(d.day_type, "unknown"),
            "report_time": d.report_time,
            "release_time": d.release_time,
            "standby_start": d.standby_start,
            "standby_end": d.standby_end,
            "layover_city": d.layover_city,
            "flights": flights,
            "sector_count": d.sector_count,
            "is_out_of_base": d.is_out_of_base,
            "is_overnight": d.is_overnight,
            "is_turnaround": d.is_turnaround,
            "is_layover_day": d.is_layover_day,
            "training_impact": d.training_impact,
            "confidence": d.parse_confidence,
            "notes": " ".join(d.notes) if d.notes else None,
            "warnings": d.warnings,
            "needs_review": d.needs_client_review or d.needs_coach_review,
            "source": "etihad_parser_v1",
        })
    return out
