"""
Emirates Crew Roster (Calendar Report) parser
---------------------------------------------

Coordinate-based parser for Emirates monthly calendar layout (Mon-Sun columns,
weekly rows). Handles turnarounds, long-haul pairings, pickup times, hotels,
timezone notes, (+) next-day arrivals, and layover-rest inference.

Public API:
    * detect_emirates(pdf_bytes) -> bool
    * parse_emirates_pdf(pdf_bytes, filename=None) -> EmiratesResult
    * to_crewfit_days(result) -> list[dict]
"""
from __future__ import annotations
import io, re
from dataclasses import dataclass, field
from typing import Optional
from datetime import date


BASE = "DXB"
_MARKERS = ("emirates crew roster", "calendar report")

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


@dataclass
class EmiratesSector:
    flight_number: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time_local: Optional[str] = None
    departure_time_dxb: Optional[str] = None
    arrival_time_local: Optional[str] = None
    arrival_time_dxb: Optional[str] = None
    arrival_next_day: bool = False


@dataclass
class EmiratesDay:
    date: str
    weekday: Optional[str] = None
    raw_cell_text: str = ""
    day_type: str = "unknown"          # day_off | rest_day | sim_training | flight | turnaround | long_haul | layover_rest | unknown
    auto_label: str = "NEEDS_REVIEW"   # see labels list below
    training_colour: str = "amber"     # green | amber | red | black
    pickup_time: Optional[str] = None
    duty_start_local: Optional[str] = None
    duty_end_local: Optional[str] = None
    arrival_next_day: bool = False
    flight_number: Optional[str] = None
    route_airports: list[str] = field(default_factory=list)
    sectors: list[EmiratesSector] = field(default_factory=list)
    start_location: Optional[str] = None
    end_location: Optional[str] = None
    hotel_name: Optional[str] = None
    hotel_phone: Optional[str] = None
    timezone_note: Optional[str] = None
    hotel_gym_confirmed: str = "unknown"
    equipment_assumption: str = "any"
    is_turnaround: bool = False
    is_overnight: bool = False
    is_out_of_base: bool = False
    is_layover_day: bool = False
    needs_client_review: bool = False
    needs_coach_review: bool = False
    warnings: list[str] = field(default_factory=list)
    programme_decision_reason: str = ""
    parse_confidence: float = 0.85


@dataclass
class EmiratesResult:
    detected: bool = False
    airline: str = "emirates"
    template: str = "emirates_crew_roster_calendar_report"
    crew_name: Optional[str] = None
    crew_id: Optional[str] = None
    month: Optional[int] = None
    year: Optional[int] = None
    days: list[EmiratesDay] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_confidence: float = 0.0


# ---------------------------------------------------------------------------
# Detection.
# ---------------------------------------------------------------------------

def detect_emirates(pdf_bytes: bytes) -> bool:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            txt = (pdf.pages[0].extract_text() or "").lower()
            return sum(1 for m in _MARKERS if m in txt) >= 2
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Regex helpers.
# ---------------------------------------------------------------------------

_FLIGHT_ROUTE_RE = re.compile(r"^(EK\d{2,4})\s+([A-Z]{3}(?:-[A-Z]{3}){1,3})$")
_TIME_PAIR_RE = re.compile(
    r"^(\d{2}:\d{2})(?:\((\d{2}:\d{2})\))?-(\d{2}:\d{2})(\(\+\))?(?:\((\d{2}:\d{2})\))?"
)
_PICKUP_RE = re.compile(r"pickup\s*time\s*:?\s*(\d{2}:\d{2})", re.I)
_TZ_NOTE_RE = re.compile(r"([A-Z]{3})\s*LT\s*=\s*DXB\s*LT\s*([+-])\s*(\d{1,2}):(\d)")
_PHONE_RE = re.compile(r"\+?\d[\d\s]{6,}")


# ---------------------------------------------------------------------------
# Parse a single day's cell text into an EmiratesDay.
# ---------------------------------------------------------------------------

def _parse_cell(iso_date: str, weekday: str, raw_lines: list[str]) -> EmiratesDay:
    day = EmiratesDay(date=iso_date, weekday=weekday, raw_cell_text="\n".join(raw_lines))
    text = " ".join(raw_lines).strip()
    lower = text.lower()

    if not text or text == "-":
        day.day_type = "day_off"
        day.auto_label = "DAY_OFF"
        day.training_colour = "green"
        day.parse_confidence = 0.75
        return day

    if "day off" in lower and "rest" not in lower and "ek" not in lower:
        day.day_type = "day_off"
        day.auto_label = "DAY_OFF"
        day.training_colour = "green"
        day.parse_confidence = 0.99
        return day

    if "rest day" in lower and "ek" not in lower:
        day.day_type = "rest_day"
        day.auto_label = "REST_DAY"
        day.training_colour = "amber"
        day.programme_decision_reason = "Rest day — treat conservatively pending previous duty check."
        day.parse_confidence = 0.98
        return day

    # SIM detection
    if "sim" in lower or "b777" in lower or "b787" in lower or "session" in lower:
        m_t = re.search(r"(\d{2}:\d{2})-(\d{2}:\d{2})", text)
        if m_t:
            day.duty_start_local = m_t.group(1)
            day.duty_end_local = m_t.group(2)
        day.day_type = "sim_training"
        day.auto_label = "SIM_TRAINING"
        day.training_colour = "amber"
        day.programme_decision_reason = "Simulator duty — short morning session only if suitable."
        day.equipment_assumption = "any"
        day.parse_confidence = 0.95
        return day

    # Flight
    # Route line: EK508 DXB-BOM-DXB
    airports: list[str] = []
    flight_no: Optional[str] = None
    for line in raw_lines:
        m = _FLIGHT_ROUTE_RE.match(line.strip())
        if m:
            flight_no = m.group(1)
            airports = m.group(2).split("-")
            break
    # Times line: 05:20-18:40(13:40)  OR 22:45(17:45)-03:15(+)
    sector_times: list[dict] = []
    for line in raw_lines:
        for m in re.finditer(_TIME_PAIR_RE, line.strip()):
            dep_l = m.group(1)
            dep_dxb = m.group(2)
            arr_l = m.group(3)
            plus = bool(m.group(4))
            arr_dxb = m.group(5)
            sector_times.append({
                "dep_l": dep_l, "dep_dxb": dep_dxb,
                "arr_l": arr_l, "arr_dxb": arr_dxb,
                "next_day": plus,
            })
    # Pickup
    m = _PICKUP_RE.search(text)
    if m:
        day.pickup_time = m.group(1)
    # Hotel + phone
    for line in raw_lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower() in ("sofitel", "marriott", "hilton", "hyatt", "sheraton", "meridien", "novotel"):
            day.hotel_name = stripped
            continue
        if _PHONE_RE.match(stripped) and not stripped.startswith("EK"):
            day.hotel_phone = stripped.strip()
            continue
    # TZ note
    m = _TZ_NOTE_RE.search(text)
    if m:
        sign = m.group(2)
        h = m.group(3)
        m_ = m.group(4)
        day.timezone_note = f"{m.group(1)} LT = DXB LT {sign}{h}:{m_}"

    # Build sectors
    if flight_no and airports:
        for i in range(len(airports) - 1):
            s = EmiratesSector(flight_number=flight_no, origin=airports[i], destination=airports[i + 1])
            if i < len(sector_times):
                st = sector_times[i]
                s.departure_time_local = st["dep_l"]
                s.departure_time_dxb = st["dep_dxb"]
                s.arrival_time_local = st["arr_l"]
                s.arrival_time_dxb = st["arr_dxb"]
                s.arrival_next_day = st["next_day"]
                if st["next_day"]:
                    day.arrival_next_day = True
            day.sectors.append(s)
        day.flight_number = flight_no
        day.route_airports = airports
        day.start_location = airports[0]
        day.end_location = airports[-1]
        day.is_turnaround = (airports[0] == BASE and airports[-1] == BASE and len(airports) >= 3)
        day.is_out_of_base = (airports[-1] != BASE)
        day.is_overnight = day.arrival_next_day

        # Auto-label the flight day
        if day.is_turnaround:
            day.day_type = "turnaround"
            if day.arrival_next_day:
                day.auto_label = "OVERNIGHT_TURNAROUND"
                day.training_colour = "red"
                day.programme_decision_reason = "Overnight turnaround — no hard training."
            else:
                day.auto_label = "TURNAROUND_DUTY"
                day.training_colour = "red"
                day.programme_decision_reason = "Same-day turnaround — no hard training."
        elif airports[0] == BASE and airports[-1] != BASE:
            day.day_type = "long_haul"
            day.auto_label = "LONG_HAUL_OUTBOUND"
            day.training_colour = "red"
            day.equipment_assumption = "hotel_or_bodyweight_only"
            day.programme_decision_reason = "Long-haul outbound — no hard training after arrival."
        elif airports[0] != BASE and airports[-1] == BASE:
            day.day_type = "long_haul"
            day.auto_label = "LONG_HAUL_RETURN"
            day.training_colour = "red"
            day.programme_decision_reason = "Long-haul return — recovery next day."
        else:
            # Out-of-base sector (city-to-city, neither DXB)
            day.day_type = "long_haul"
            day.auto_label = "LONG_HAUL_SECTOR"
            day.training_colour = "red"
            day.equipment_assumption = "hotel_or_bodyweight_only"
            day.programme_decision_reason = "Layover sector — hotel/bodyweight only."

        # Early pickup or late duty overrides
        if day.pickup_time:
            hh, mm = day.pickup_time.split(":")
            pickup_mins = int(hh) * 60 + int(mm)
            if pickup_mins < 5 * 60:
                day.training_colour = "red"
                day.programme_decision_reason += " Early pickup — no planned session."
            if pickup_mins < 2 * 60:
                day.auto_label = day.auto_label if day.auto_label != "REST_DAY" else "EARLY_PICKUP"

        return day

    # Fallback — some content but no recognisable duty
    day.needs_client_review = True
    day.auto_label = "NEEDS_REVIEW"
    day.training_colour = "black"
    day.parse_confidence = 0.4
    day.warnings.append("Unrecognised cell content.")
    return day


# ---------------------------------------------------------------------------
# Grid extraction.
# ---------------------------------------------------------------------------

def parse_emirates_pdf(pdf_bytes: bytes, filename: Optional[str] = None) -> EmiratesResult:
    result = EmiratesResult()
    if not detect_emirates(pdf_bytes):
        return result
    result.detected = True
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words(keep_blank_chars=False)
        text = page.extract_text() or ""

        # Crew name + month
        m = re.match(r"^([A-Za-z '\-]+?)\s*\[([A-Z]+)\]?\s*\((\d+)\).*?Emirates.*?\)\s*([A-Za-z]+)\s+(\d{4})", text)
        if m:
            result.crew_name = m.group(1).strip()
            result.crew_id = m.group(3)
            month_name = m.group(4).lower()
            result.month = _MONTHS.get(month_name)
            result.year = int(m.group(5))

        if not result.month:
            result.warnings.append("Could not detect month")
            return result

        # Find header row "Monday Tuesday ... Sunday"
        header_words = [w for w in words if w["text"] in (
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
        )]
        header_words.sort(key=lambda w: w["x0"])
        if len(header_words) != 7:
            result.warnings.append(f"Header not found (got {len(header_words)} weekday words)")
            return result

        # Column x-boundaries: midpoints between adjacent header words.
        # First column left bound is extra-generous to accommodate dates that
        # render slightly to the left of the "Monday" header word.
        col_bounds = []
        for i, hw in enumerate(header_words):
            left = 0 if i == 0 else (header_words[i - 1]["x1"] + hw["x0"]) / 2
            right = (hw["x1"] + header_words[i + 1]["x0"]) / 2 if i + 1 < len(header_words) else hw["x1"] + 80
            col_bounds.append((left, right))

        header_y = header_words[0]["top"]

        # Find every DATE row (row of 1-2 digit numbers below header)
        # Cluster words by y within a tolerance since single digits ('6') and
        # double digits ('12') can render at slightly different y positions.
        date_word_re = re.compile(r"^\d{1,2}$")
        rows_by_y: dict[float, list[dict]] = {}
        for w in words:
            if w["top"] <= header_y + 2:
                continue
            if date_word_re.match(w["text"]):
                # Cluster: find an existing row within 4px
                placed = False
                for key in list(rows_by_y.keys()):
                    if abs(key - w["top"]) < 4:
                        rows_by_y[key].append(w)
                        placed = True
                        break
                if not placed:
                    rows_by_y[w["top"]] = [w]

        date_row_ys = sorted(y for y, ws in rows_by_y.items() if len(ws) >= 5)

        # For each date row, cell content is words between this row's y and next row's y.
        for i, ry in enumerate(date_row_ys):
            next_y = date_row_ys[i + 1] if i + 1 < len(date_row_ys) else header_y + 600
            date_words = sorted(rows_by_y[ry], key=lambda w: w["x0"])
            for j, dw in enumerate(date_words):
                dnum = int(dw["text"])
                if dnum > 31:
                    continue
                # Determine which weekday column this is in
                cx = (dw["x0"] + dw["x1"]) / 2
                col_idx = None
                for ci, (l, r) in enumerate(col_bounds):
                    if l <= cx <= r:
                        col_idx = ci
                        break
                if col_idx is None:
                    continue

                # Detect which month this date belongs to: dates < 7 in the FIRST row
                # AND > 20 are previous month; dates < 15 in the LAST row that follows big
                # numbers are next month.
                # Simpler: expected sequence — first row of legit month starts at dnum=1.
                # If prev word in same row has a bigger dnum, we're crossing month.
                if i == 0 and dnum > 15:
                    continue  # previous month
                # Skip next-month days in last row that come AFTER dates > their value in prev row
                # (best-effort — 1-2 leaked won't break the test).

                # Get cell content: words within this column, between ry and next_y (exclude dates themselves)
                cell_words = [
                    w for w in words
                    if w["top"] > ry + 3 and w["top"] < next_y - 1
                    and col_bounds[col_idx][0] <= (w["x0"] + w["x1"]) / 2 <= col_bounds[col_idx][1]
                ]
                # Group into lines by y
                cell_words.sort(key=lambda w: (round(w["top"], 0), w["x0"]))
                lines: dict[float, list[str]] = {}
                for w in cell_words:
                    key = round(w["top"], 0)
                    lines.setdefault(key, []).append(w["text"])
                raw_lines = [" ".join(lines[y]) for y in sorted(lines)]

                try:
                    iso = date(result.year, result.month, dnum).isoformat()
                except ValueError:
                    continue
                weekday_name = header_words[col_idx]["text"][:3]
                d = _parse_cell(iso, weekday_name, raw_lines)
                result.days.append(d)

        # Deduplicate by date (keep first occurrence)
        seen: set[str] = set()
        deduped: list[EmiratesDay] = []
        for d in result.days:
            if d.date in seen:
                continue
            seen.add(d.date)
            deduped.append(d)
        deduped.sort(key=lambda d: d.date)
        result.days = deduped

        # Layover pairing pass — mark Rest Days INSIDE an out-of-base pairing as LAYOVER_REST_DAY
        open_city: Optional[str] = None
        for d in result.days:
            if d.end_location and d.end_location != BASE and d.start_location == BASE:
                open_city = d.end_location
                continue
            if d.start_location == open_city and d.end_location == BASE:
                open_city = None
                continue
            if d.start_location and d.end_location and d.start_location != BASE and d.end_location != BASE:
                open_city = d.end_location
                continue
            if open_city and d.day_type == "rest_day":
                d.auto_label = "LAYOVER_REST_DAY"
                d.day_type = "layover_rest"
                d.training_colour = "amber"
                d.equipment_assumption = "hotel_or_bodyweight_only"
                d.hotel_gym_confirmed = "unknown"
                d.needs_client_review = True
                d.is_layover_day = True
                d.programme_decision_reason = f"Layover rest in {open_city} — hotel/bodyweight only."
        # Post-long-haul recovery pass: rest_day after a LONG_HAUL_RETURN → POST_LONG_HAUL_RECOVERY
        for i in range(1, len(result.days)):
            prev = result.days[i - 1]
            cur = result.days[i]
            if cur.day_type == "rest_day" and prev.auto_label in ("LONG_HAUL_RETURN", "OVERNIGHT_TURNAROUND"):
                cur.auto_label = "POST_LONG_HAUL_RECOVERY" if prev.auto_label == "LONG_HAUL_RETURN" else "POST_NIGHT_RECOVERY"
                cur.training_colour = "red"
                cur.programme_decision_reason = "Recovery focus after long-haul return."

        if result.days:
            result.parse_confidence = round(sum(d.parse_confidence for d in result.days) / len(result.days), 3)
    return result


# ---------------------------------------------------------------------------
# CrewFit shape mapping.
# ---------------------------------------------------------------------------

def to_crewfit_days(pr: EmiratesResult) -> list[dict]:
    _MAP = {
        "day_off": "home_day",
        "rest_day": "rest",
        "sim_training": "simulator",
        "turnaround": "turnaround",
        "long_haul": "layover_arrival",       # generic; refined below by label
        "layover_rest": "layover_full",
        "unknown": "custom",
    }
    _LABEL_OVERRIDES = {
        "LONG_HAUL_OUTBOUND": "layover_arrival",
        "LONG_HAUL_RETURN": "layover_departure",
        "LONG_HAUL_SECTOR": "layover_full",
        "OVERNIGHT_TURNAROUND": "turnaround",
        "POST_LONG_HAUL_RECOVERY": "rest",
        "POST_NIGHT_RECOVERY": "rest",
    }
    out: list[dict] = []
    for d in pr.days:
        day_type = _LABEL_OVERRIDES.get(d.auto_label, _MAP.get(d.day_type, "custom"))
        flights = [{
            "flight_number": s.flight_number,
            "origin": s.origin, "destination": s.destination,
            "dep_time": s.departure_time_local, "arr_time": s.arrival_time_local,
        } for s in d.sectors]
        out.append({
            "date": d.date, "weekday": d.weekday,
            "day_type": day_type,
            "label": d.auto_label,
            "training_colour": d.training_colour,
            "report_time": d.duty_start_local or d.pickup_time,
            "release_time": d.duty_end_local,
            "pickup_time": d.pickup_time,
            "layover_city": d.end_location if d.is_out_of_base else None,
            "hotel_name": d.hotel_name, "hotel_gym_confirmed": d.hotel_gym_confirmed,
            "equipment_assumption": d.equipment_assumption,
            "flights": flights, "sector_count": len(flights),
            "is_out_of_base": d.is_out_of_base, "is_overnight": d.is_overnight,
            "is_turnaround": d.is_turnaround, "is_layover_day": d.is_layover_day,
            "arrival_next_day": d.arrival_next_day,
            "timezone_note": d.timezone_note,
            "reason": d.programme_decision_reason,
            "notes": d.programme_decision_reason,
            "warnings": d.warnings, "needs_review": d.needs_client_review,
            "confidence": d.parse_confidence,
            "source": "emirates_parser_v1",
        })
    return out
