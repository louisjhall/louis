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

# Iter199 · Shared "is this dwell time long enough to be a hotel layover?"
# gate — extracted into parsers.common_layover so every airline parser
# (Etihad, Emirates, BA, …) can share exactly the same classifier.
from parsers.common_layover import (
    MIN_LAYOVER_GROUND_HOURS,
    outstation_ground_hours,
)


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

    day_type: str = "unknown"               # off | rest | rostered_off | standby | flight | multi_sector_flight | flight_to_layover | layover_day | return_from_layover | overnight_flight | turnaround | midnight_crossing_flight | midnight_crossing_return | short_turn | unknown

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
    """Apply structural rules across days: layover inference + overnight merge.

    Iter199 · Every "this is a layover" verdict is now gated on the
    actual outstation dwell time via
    ``parsers.common_layover.outstation_ground_hours``. A ↓-arrow
    continuation or an out-of-base end no longer implies a hotel stay
    on its own — we require ≥ ``MIN_LAYOVER_GROUND_HOURS`` at the
    outstation before opening a layover pairing. When the gap is
    below the floor the day pair is stamped with the new
    ``midnight_crossing_flight`` / ``midnight_crossing_return`` /
    ``short_turn`` types instead, and no ``layover_city`` is set so
    downstream copy (calendar labels, coach summary, notifications)
    never markets a hotel that didn't happen.

    Fallback: when the helper returns ``None`` (unparseable times) we
    keep the legacy permissive behaviour — biasing to false-positive is
    safer than silently converting a genuine layover.
    """
    # ------------------------------------------------------------------
    # Pass 1 — overnight (↓) continuation from prev day.
    # ------------------------------------------------------------------
    for i, d in enumerate(days):
        if d.is_overnight and i > 0 and days[i - 1].is_out_of_base:
            prev = days[i - 1]
            gap = outstation_ground_hours(prev, d)
            # Below-floor OR the prev already stamped as an overnight
            # continuation (arrow at end of prev's column) → treat both
            # halves as one duty that crossed midnight, NOT a layover.
            if gap is not None and gap < MIN_LAYOVER_GROUND_HOURS:
                prev.day_type = "midnight_crossing_flight"
                prev.notes.append(
                    f"Duty crosses midnight; ~{gap:.1f}h at {prev.end_location} — not a layover."
                )
                # d is the return half — either lands back at AUH or
                # continues elsewhere. Only stamp as a "return" when it
                # actually gets home; otherwise keep it as a crossing.
                if d.sectors and d.end_location == "AUH":
                    d.day_type = "midnight_crossing_return"
                    d.notes.append(
                        f"Return leg of a midnight-crossing duty from {prev.date} "
                        f"(~{gap:.1f}h at {prev.end_location})."
                    )
                else:
                    d.day_type = "midnight_crossing_flight"
                    d.notes.append(
                        f"Started as overnight from {prev.date}; ~{gap:.1f}h at {prev.end_location}."
                    )
                # Fatigue impact — both halves are red.
                prev.training_impact = "red"
                d.training_impact = "red"
                # Belt & braces: layover_city MUST stay None.
                prev.layover_city = None
                d.layover_city = None
                continue

            # Legacy path — either the gap is >= floor (real layover)
            # or unknown (fall back to permissive behaviour).
            prev.day_type = "overnight_flight"
            prev.notes.append(f"Continues into next day ({d.date}).")
            d.day_type = "return_from_layover" if (d.sectors and d.end_location == "AUH") else "overnight_flight"
            d.notes.append(f"Started as overnight from {prev.date}.")

    # ------------------------------------------------------------------
    # Pass 2 — layover inference across contiguous out-of-base days.
    # ------------------------------------------------------------------
    open_since: Optional[int] = None
    open_city: Optional[str] = None
    for i, d in enumerate(days):
        # Iter199 · Skip days that Pass 1 already resolved as midnight-
        # crossing — they must NOT open a layover pairing.
        if d.day_type in ("midnight_crossing_flight", "midnight_crossing_return"):
            continue

        if d.is_out_of_base and open_since is None and d.day_type in (
            "flight", "multi_sector_flight", "overnight_flight",
        ):
            # Gate the pairing open on actual dwell time at the outstation.
            # Peek at the next day (if any) that has a sector starting at
            # d.end_location.
            nxt = days[i + 1] if i + 1 < len(days) else None
            gap = outstation_ground_hours(d, nxt)
            if gap is not None and gap < MIN_LAYOVER_GROUND_HOURS:
                # Sub-classify: crossed-midnight vs same-day short-turn.
                # Fatigue impact is red either way; layover_city stays None.
                arr_hh = _extract_last_arrival_hour(d)
                is_crossing = arr_hh is not None and arr_hh < 6      # arrived early AM
                d.day_type = "midnight_crossing_flight" if is_crossing else "short_turn"
                d.notes.append(
                    f"Out-of-base end at {d.end_location} but only ~{gap:.1f}h "
                    f"before the next departure — not a layover."
                )
                d.training_impact = "red"
                d.layover_city = None
                # If the return leg is on the same day (rare) we're done;
                # otherwise tag next day's return so it doesn't get called
                # a "return_from_layover".
                if nxt is not None and nxt.day_type not in (
                    "midnight_crossing_return", "midnight_crossing_flight",
                ) and nxt.sectors and nxt.end_location == "AUH":
                    nxt.day_type = "midnight_crossing_return"
                    nxt.layover_city = None
                    nxt.training_impact = "red"
                    nxt.notes.append(
                        f"Return leg of a short-turn/midnight-crossing from {d.date}."
                    )
                continue
            # Real layover — open pairing as before.
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
            # (Structured parser: an "off" cell here is the etihad
            # parser's placeholder for a blank column between two
            # resolved sectors — this IS the pairing's middle rest day.
            # The universal normalizer in `roster_normalizer.py` provides
            # a second layer of protection at the roster level to catch
            # any case where OFF should have been preserved.)
            if not d.sectors and d.day_type in ("off", "unknown"):
                d.day_type = "layover_day"
                d.is_layover_day = True
                d.layover_city = open_city
                d.training_impact = "amber"
                d.parse_confidence = min(d.parse_confidence, 0.75)
                d.needs_client_review = True
                continue

    return days


def _extract_last_arrival_hour(d: ParsedDay) -> Optional[int]:
    """Small helper for Pass 2 sub-classification — returns the hour
    (0-23) of the last sector's arrival on ``d``. Used to distinguish
    "midnight-crossing" from same-day "short_turn"."""
    if not d.sectors:
        return None
    last = d.sectors[-1]
    txt = getattr(last, "arrival_time", None) or d.release_time
    if not txt:
        return None
    s = str(txt).replace("↓", "").replace("↑", "").strip()
    if ":" in s:
        try:
            return int(s.split(":", 1)[0])
        except ValueError:
            return None
    if len(s) == 4 and s.isdigit():
        return int(s[:2])
    return None


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
    # Iter200-h · Emit CANONICAL internal type names that the universal
    # normalizer + presenter both understand. Previously we used the
    # legacy "layover_arrival" / "layover_full" / "layover_departure"
    # strings which caused downstream code to fall back to raw
    # placeholder labels ("layover_arrival") on the customer card.
    _MAP = {
        "off": "day_off",
        "rest": "rest_day",
        "rostered_off": "day_off",
        "standby": "standby",
        "flight": "turnaround",
        "multi_sector_flight": "turnaround",
        "flight_to_layover": "flight_to_layover",
        "layover_day": "layover_day",
        "return_from_layover": "return_from_layover",
        "overnight_flight": "night_flight",
        "turnaround": "turnaround",
        "unknown": "unknown",
    }
    out: list[dict] = []
    for d in pr.days:
        flights = []
        for s in d.sectors:
            # Iter200-h · Emit sectors with the canonical field names
            # (from/to/dep/arr/flight_number) that both the universal
            # normalizer and the frontend card expect. Previously we
            # used origin/destination/dep_time/arr_time which meant
            # routes never rendered on cards downstream.
            flights.append({
                "flight_number": s.flight_number,
                "from": s.origin,
                "to": s.destination,
                "dep": s.departure_time,
                "arr": s.arrival_time,
                "aircraft": s.aircraft,
                # legacy aliases (kept for any downstream code that
                # still reads the old names)
                "origin": s.origin,
                "destination": s.destination,
                "dep_time": s.departure_time,
                "arr_time": s.arrival_time,
            })
        out.append({
            "date": d.date,
            "weekday": d.weekday,
            "day_type": _MAP.get(d.day_type, "unknown"),
            "report_time": d.report_time,
            "release_time": d.release_time,
            "duty_end_time": d.release_time,
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
            # Iter200-h · notes are internal parser context — never
            # customer-facing. Persist under `_internal_notes` so audit
            # tooling can still inspect them, but leave the outward-
            # facing `notes` field empty so nothing leaks to the card.
            "notes": "",
            "_internal_notes": " ".join(d.notes) if d.notes else None,
            "warnings": d.warnings,
            "needs_review": d.needs_client_review or d.needs_coach_review,
            "source": "etihad_parser_v1",
        })
    return out
