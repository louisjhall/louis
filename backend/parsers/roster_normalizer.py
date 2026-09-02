"""parsers.roster_normalizer — UNIVERSAL post-parse layer.

Runs AFTER the airline-specific parser or the LLM extractor. Consumes
whatever `days[]` was produced (each day is a plain dict with `date`,
`day_type`, `flights[]`, optional `report_time`, `duty_end_time`,
`layover_city`, `home_or_away`, `confidence`, `notes`, ...) and applies
one shared set of rules so we get the same behaviour across Etihad,
Emirates, BA and every future airline.

Design goals (Bucket 2, Iter200):
  • ONE file, no new services, no DB migration.
  • Idempotent — safe to run twice on the same day list.
  • Backwards-compatible day_type strings: we NEVER emit a brand-new
    type without also stamping a legacy fallback so downstream code
    (workout generator, coach dashboard, training colour) keeps working.
  • Duck-typed input: reads whatever fields exist; leaves unknown days
    with `needs_review=True` rather than inventing data.

Public API:
    normalize_roster(
        days: list[dict],
        home_base: str | None = None,
        month_range: tuple[str, str] | None = None,
    ) -> dict

Returns:
    {
      "days": [ ... cleaned days ... ],
      "dropped": [ ... days clipped by month_range or dedupe ... ],
      "audit": {
        "clipped_month_boundary": int,
        "deduped_dates": int,
        "downgraded_midnight_crossings": int,
        "preserved_off_days": int,
        "fixed_standby_equipment": int,
        "flagged_needs_review": int,
      },
    }

Key rules enforced:
  1. Month clip — days outside `month_range` are moved to `dropped[]`.
  2. Date dedupe — same-date entries collapsed (richest one wins).
  3. Duty reconstruction — sectors sharing a duty envelope, including
     across midnight, are grouped by (start_airport, end_airport,
     dwell_at_outstation).
  4. Layover gate — a layover requires:
       duty ended away_from_base
       AND next duty starts from the same outstation on a LATER date
       AND ground time at outstation >= MIN_LAYOVER_GROUND_HOURS (8h).
     Below the gate → `night_flight` or `turnaround` (not a layover).
  5. OFF preservation — source-labelled OFF stays OFF unless later
     evidence PROVES genuine outstation rest (sector on the next day
     starting at that same outstation).
  6. Standby equipment fix — home-based standby → equipment "any".
     Only confirmed outstation layovers get "hotel_or_bodyweight".
  7. "Layover in None" fix — when we can't resolve the outstation city
     for what looks like a layover, downgrade to `needs_review` with
     label "Away from base — location TBC" instead of pretending.
  8. Presenter — always populates `client_label` (customer-friendly
     string) alongside the internal `day_type`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Any, Optional


# --- Constants --------------------------------------------------------------

MIN_LAYOVER_GROUND_HOURS: float = 8.0
"""Below this dwell at the outstation → not a hotel layover."""


# Internal day_type vocabulary the normalizer emits/preserves. Everything
# else is passed through unchanged (backwards-compat).
INTERNAL_TYPES = {
    # duty
    "flight",
    "multi_sector_flight",
    "turnaround",
    "night_flight",           # NEW — replaces LLM's "Layover Arrival" for cross-midnight roundtrips
    "flight_to_layover",
    "layover_day",
    "return_from_layover",
    "overnight_flight",
    # non-duty
    "day_off",
    "rest_day",
    "home_day",
    "standby",
    "sim_training",
    "annual_leave",
    "sickness",
    # ambiguous
    "needs_review",
    "unknown",
}


# --- Time / date helpers ----------------------------------------------------

def _parse_hhmm(s: Optional[str]) -> Optional[tuple[int, int]]:
    if not s:
        return None
    txt = str(s).strip().replace("↓", "").replace("↑", "").replace("Z", "").strip()
    if not txt:
        return None
    if len(txt) == 4 and txt.isdigit():
        h, m = int(txt[:2]), int(txt[2:])
    elif ":" in txt:
        try:
            hh, mm = txt.split(":", 1)
            h = int(hh)
            m = int(mm[:2])
        except (ValueError, IndexError):
            return None
    else:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h, m


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    txt = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def _combine_dt(d: Optional[date], hhmm: Optional[str]) -> Optional[datetime]:
    if not d:
        return None
    t = _parse_hhmm(hhmm)
    if not t:
        return None
    return datetime(d.year, d.month, d.day, t[0], t[1])


# --- Flight helpers ---------------------------------------------------------

def _flights(day: dict) -> list[dict]:
    return day.get("flights") or []


def _first_flight(day: dict) -> Optional[dict]:
    fs = _flights(day)
    return fs[0] if fs else None


def _last_flight(day: dict) -> Optional[dict]:
    fs = _flights(day)
    return fs[-1] if fs else None


def _start_airport(day: dict) -> Optional[str]:
    f = _first_flight(day)
    return (f or {}).get("from")


def _end_airport(day: dict) -> Optional[str]:
    f = _last_flight(day)
    return (f or {}).get("to")


def _last_arrival_dt(day: dict) -> Optional[datetime]:
    """Datetime of the last sector's arrival on this day.

    Falls back to `duty_end_time` on the day. If the arrival HH:MM is
    earlier than the departure HH:MM, we roll the arrival to the next
    calendar day (the sector crossed midnight).
    """
    fs = _flights(day)
    d_ = _parse_iso_date(day.get("date"))
    if not d_:
        return None
    if fs:
        last = fs[-1]
        arr_hhmm = last.get("arr")
        dep_hhmm = last.get("dep")
        if arr_hhmm:
            arr_dt = _combine_dt(d_, arr_hhmm)
            dep_dt = _combine_dt(d_, dep_hhmm) if dep_hhmm else None
            if arr_dt and dep_dt and arr_dt < dep_dt:
                # last sector crossed midnight
                arr_dt = arr_dt + timedelta(days=1)
            if arr_dt:
                return arr_dt
    # Fallback: day-level duty_end_time
    end_hhmm = day.get("duty_end_time")
    if end_hhmm:
        end_dt = _combine_dt(d_, end_hhmm)
        report_dt = _combine_dt(d_, day.get("report_time"))
        if end_dt and report_dt and end_dt < report_dt:
            end_dt = end_dt + timedelta(days=1)
        return end_dt
    return None


def _first_departure_dt(day: dict, from_airport: str) -> Optional[datetime]:
    """Datetime of the earliest sector originating at `from_airport` on
    this day. Falls back to `report_time` if the day starts at
    `from_airport`."""
    if not from_airport:
        return None
    d_ = _parse_iso_date(day.get("date"))
    if not d_:
        return None
    for f in _flights(day):
        if f.get("from") == from_airport:
            dep = f.get("dep")
            if dep:
                return _combine_dt(d_, dep)
    # Fallback: day report time — only if start airport matches.
    if _start_airport(day) == from_airport:
        return _combine_dt(d_, day.get("report_time"))
    return None


def _ground_hours(prev: dict, nxt: Optional[dict]) -> Optional[float]:
    if not nxt:
        return None
    end = _end_airport(prev)
    if not end:
        return None
    arr = _last_arrival_dt(prev)
    dep = _first_departure_dt(nxt, end)
    if not arr or not dep:
        return None
    return (dep - arr).total_seconds() / 3600.0


# --- Home-base inference ----------------------------------------------------

def _infer_home_base(days: list[dict], hint: Optional[str]) -> set[str]:
    """Return the SET of airports that appear to be the crew's home
    base(s). Multi-base airlines (BA: LHR+LGW, EK: DXB) supported.

    Heuristic: a home base is where the crew starts a FRESH duty — i.e.
    a duty whose PREVIOUS day was NOT itself a flight duty (rest / OFF /
    standby / annual leave / start of roster). Layover outstations get
    flown out of but the day before is always an outbound flight OR a
    layover_day, so they never qualify as a fresh-duty start.

    Strategy:
      1. Start with the hint if provided.
      2. Add any airport that is the start of >=1 "fresh duty" and
         starts more fresh duties than any other airport that only
         appears as a returning airport.
      3. If nothing qualifies, fall back to the most-common start.
    """
    bases: set[str] = set()
    if hint:
        bases.add(hint.upper())

    fresh_starts: dict[str, int] = {}
    all_starts: dict[str, int] = {}
    for i, d in enumerate(days):
        s = _start_airport(d)
        if not s:
            continue
        s = s.upper()
        all_starts[s] = all_starts.get(s, 0) + 1

        # Walk backwards over blank / layover-middle days to find the
        # PREVIOUS day that had actual flight sectors. If that last
        # flight ended at the SAME airport we're starting from, this is
        # a continuation of a layover pairing (return leg), NOT a fresh
        # duty from a home base.
        prev_flight_day = None
        for lb in range(i - 1, -1, -1):
            if _flights(days[lb]):
                prev_flight_day = days[lb]
                break
        prev_ended_here = (
            prev_flight_day is not None
            and _end_airport(prev_flight_day) == s
        )
        # A fresh duty is one where either:
        #   - there is no prior flight (start of roster / first duty), OR
        #   - the prior flight ended somewhere OTHER than here.
        # Additionally the DIRECTLY prior day should not itself be a
        # duty (has_flight or explicitly a layover-middle).
        prev = days[i - 1] if i > 0 else None
        prev_has_flight = bool(_flights(prev)) if prev else False
        prev_is_layover_middle = (
            prev is not None
            and (prev.get("day_type") or "").lower() in
                ("layover full day", "layover_day", "layover full",
                 "layover_full", "layover_full_day", "layover rest",
                 "layover_rest")
        )
        if prev_ended_here:
            continue  # continuation of a pairing — never counts as fresh
        if not prev_has_flight and not prev_is_layover_middle:
            fresh_starts[s] = fresh_starts.get(s, 0) + 1

    for airport, n in fresh_starts.items():
        if n >= 1:
            bases.add(airport)

    if not bases and all_starts:
        bases.add(max(all_starts.items(), key=lambda kv: kv[1])[0])
    return bases


def _is_home(airport: Optional[str], bases: set[str]) -> bool:
    if not airport or not bases:
        return False
    return airport.upper() in bases


# --- Source day_type parsing ------------------------------------------------

_OFF_TOKENS = {"off", "day off", "day_off", "day-off", "d/o", "rest", "rest day",
               "rest_day", "home day", "home_day", "home", "free", "rst"}
_STANDBY_TOKENS = {"standby", "sby", "stby", "reserve", "res", "rsv", "sc", "lc",
                   "hsby", "asby", "airport standby", "home standby"}
_LAYOVER_TOKENS = {"layover", "layover_arrival", "layover_departure", "layover_full",
                   "layover_arrival_day", "layover_full_day", "layover_departure_day",
                   "layover_rest", "layover_day"}
_TURNAROUND_TOKENS = {"turnaround", "turnaround duty", "turnaround_duty",
                      "short-haul turnaround", "long-haul turnaround"}
_SIM_TOKENS = {"sim", "simulator", "simulator/training day", "sim_training",
               "training", "cbt", "recurrent"}
_ANNUAL_LEAVE_TOKENS = {"annual leave", "annual_leave", "al", "leave", "vac",
                        "vacation", "url"}


def _source_class(day: dict) -> str:
    """Return a coarse classification of what the SOURCE parser said:
       'off' | 'standby' | 'layover' | 'turnaround' | 'flight' | 'sim' |
       'annual_leave' | 'unknown'."""
    dt = (day.get("day_type") or "").strip().lower()
    if not dt:
        return "unknown"
    # exact-match tokens first
    if dt in _OFF_TOKENS:
        return "off"
    if dt in _STANDBY_TOKENS or "standby" in dt or "reserve" in dt:
        return "standby"
    if any(tok in dt for tok in _LAYOVER_TOKENS):
        return "layover"
    if "turnaround" in dt or dt in _TURNAROUND_TOKENS:
        return "turnaround"
    if dt in _SIM_TOKENS or "sim" in dt or "training" in dt or "recurrent" in dt:
        return "sim"
    if dt in _ANNUAL_LEAVE_TOKENS or "leave" in dt or "vac" in dt:
        return "annual_leave"
    if _flights(day):
        return "flight"
    if "night" in dt or "overnight" in dt:
        return "flight"
    if "unknown" in dt or "needs confirmation" in dt or "needs_confirmation" in dt:
        return "unknown"
    return "unknown"


# --- Presenter --------------------------------------------------------------

def _route_str(day: dict) -> str:
    """Compact route string like 'AUH → JAI → AUH' from flight list."""
    fs = _flights(day)
    if not fs:
        return ""
    parts = [fs[0].get("from")] + [f.get("to") for f in fs]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return " → ".join(parts)


def _fmt_time(hhmm: Optional[str]) -> str:
    t = _parse_hhmm(hhmm)
    return f"{t[0]:02d}:{t[1]:02d}" if t else ""


def _standby_window(day: dict) -> str:
    s = day.get("standby_start_time") or day.get("report_time")
    e = day.get("standby_end_time") or day.get("duty_end_time")
    s_ = _fmt_time(s)
    e_ = _fmt_time(e)
    if s_ and e_:
        return f"{s_}–{e_}"
    if s_:
        return f"from {s_}"
    return ""


def _customer_label(day: dict) -> str:
    """Iter200-b/g · Human-friendly one-line label per user's spec.

    RULES:
      • Plain type names ONLY: "Night flight", "Layover", "Rest day",
        "Standby", "Flying day". Never parser type names.
      • Report time between 00:00 and 05:00 → always "Night flight" (overrides
        "Flying day" / "Heavy flying day" that other layers might set).
      • Layover cards show city when available: "Layover — Karachi".
        If no city: "Layover" only. Never "Layover in None".
      • Standby cards show the window when available:
        "Standby 06:00–14:00". Otherwise just "Standby".
      • Route (short) is shown alongside where it exists, e.g.
        "Flying day — AUH → DXB", kept SHORT.
      • "Return from layover" is shown as "Return flight — ROUTE".
      • "Flying to layover" is shown as "Layover".
    """
    internal = (day.get("day_type") or "").lower()
    route = _route_str(day)
    city = day.get("layover_city")

    # Iter200-g · Early-morning report rule: any duty with a sector
    # departing between 00:00 and 05:00 must display as "Night flight",
    # overriding stale "Flying day" / "Heavy flying day" labels.
    # Applied BEFORE the internal-type switch so it wins uniformly.
    # EXCEPT for resolved layover types — a genuine layover trip
    # (AUH → CMB → hotel → AUH) still reads as "Layover — CMB" even
    # if the outbound sector left at 01:10.
    fs = _flights(day)
    _LAYOVER_LIKE = {"flight_to_layover", "return_from_layover", "layover_day"}
    _NON_FLIGHT = {"standby", "day_off", "home_day", "rest_day",
                   "sim_training", "annual_leave", "sickness", "needs_review"}
    if fs and internal not in _LAYOVER_LIKE and internal not in _NON_FLIGHT:
        first_dep_hhmm = (fs[0] or {}).get("dep") or day.get("report_time")
        first_dep = _parse_hhmm(first_dep_hhmm)
        if first_dep is not None and first_dep[0] < 5:
            return f"Night flight — {route}" if route else "Night flight"

    if internal in ("day_off", "home_day"):
        return "Rest day"
    if internal == "rest_day":
        return "Rest day"
    if internal == "standby":
        win = _standby_window(day)
        return f"Standby {win}" if win else "Standby"
    if internal == "sim_training":
        return "Simulator"
    if internal == "annual_leave":
        return "Annual leave"
    if internal == "sickness":
        return "Off sick"
    if internal == "needs_review":
        return "Needs your check"

    if internal == "night_flight":
        return f"Night flight — {route}" if route else "Night flight"
    if internal == "turnaround":
        return f"Flying day — {route}" if route else "Flying day"
    if internal == "flight" or internal == "multi_sector_flight":
        return f"Flying day — {route}" if route else "Flying day"

    if internal == "flight_to_layover":
        # Iter200-g · Renamed from "Flying to layover" → "Layover".
        if city:
            return f"Layover — {city}"
        return "Layover"
    if internal == "return_from_layover":
        # Iter200-g · Renamed from "Return from layover" → "Return flight".
        if route:
            return f"Return flight — {route}"
        return "Return flight"
    if internal == "layover_day":
        if city:
            return f"Layover — {city}"
        return "Layover"
    if internal == "overnight_flight":
        return f"Night flight — {route}" if route else "Night flight"

    # Fallback — keep raw
    return day.get("day_type") or "Duty"


# --- Core normalization ------------------------------------------------------

def _month_clip(days: list[dict], mrange: Optional[tuple[str, str]]) -> tuple[list[dict], list[dict]]:
    if not mrange:
        return days, []
    lo = _parse_iso_date(mrange[0])
    hi = _parse_iso_date(mrange[1])
    if not lo or not hi:
        return days, []
    kept, dropped = [], []
    for d in days:
        dt = _parse_iso_date(d.get("date"))
        if dt and lo <= dt <= hi:
            kept.append(d)
        else:
            dropped.append({**d, "_drop_reason": "outside_month_range"})
    return kept, dropped


def _dedupe(days: list[dict]) -> tuple[list[dict], int]:
    """Collapse duplicate dates.

    Preference order when two rows share a date:
      1. A row that resolves to a duty (turnaround / night_flight /
         flight / flight_to_layover) beats a bare 'layover' row from
         the LLM — this fixes the specific bug where the LLM emitted a
         same-date `layover_arrival` alongside the already-resolved
         turnaround.
      2. More sectors wins.
      3. Higher confidence wins.
      4. Otherwise the first row wins.
    """
    _DUTY_TYPES_PREFERRED = {
        "turnaround", "night_flight", "flight", "multi_sector_flight",
        "flight_to_layover", "return_from_layover", "overnight_flight",
        "standby", "day_off", "rest_day", "home_day", "sim_training",
        "annual_leave",
    }

    def _rank(d: dict) -> tuple:
        dt = (d.get("day_type") or "").lower()
        already_normalized = 1 if dt in _DUTY_TYPES_PREFERRED else 0
        return (already_normalized, len(_flights(d)), float(d.get("confidence", 0.5)))

    by_date: dict[str, dict] = {}
    dupes = 0
    for d in days:
        k = d.get("date") or ""
        if not k:
            continue
        if k in by_date:
            dupes += 1
            if _rank(d) > _rank(by_date[k]):
                by_date[k] = d
        else:
            by_date[k] = d
    kept = [by_date[k] for k in sorted(by_date.keys())]
    return kept, dupes


def _next_flight_day(days: list[dict], start_idx: int) -> Optional[tuple[int, dict]]:
    for j in range(start_idx + 1, len(days)):
        if _flights(days[j]):
            return j, days[j]
    return None


def normalize_roster(
    days: list[dict],
    home_base: Optional[str] = None,
    month_range: Optional[tuple[str, str]] = None,
) -> dict:
    """Apply universal post-parse rules. See module docstring."""
    audit = {
        "clipped_month_boundary": 0,
        "deduped_dates": 0,
        "downgraded_midnight_crossings": 0,
        "preserved_off_days": 0,
        "fixed_standby_equipment": 0,
        "flagged_needs_review": 0,
        "fixed_layover_in_none": 0,
    }

    # 1) Month clip
    days, dropped_month = _month_clip(days or [], month_range)
    audit["clipped_month_boundary"] = len(dropped_month)

    # 2) Date dedupe
    days, dupes = _dedupe(days)
    audit["deduped_dates"] = dupes

    # 3) Sort chronologically
    days.sort(key=lambda d: d.get("date") or "")

    # 4) Home-base inference
    hb = _infer_home_base(days, home_base)

    # 5) Per-day universal rules
    for i, d in enumerate(days):
        # Skip days already resolved by an earlier pair-fix in the same pass
        # (e.g. the return leg of a night_flight we downgraded when processing
        # its outbound half).
        if d.get("_normalized"):
            continue
        src = _source_class(d)
        fs = _flights(d)
        end = _end_airport(d)
        start = _start_airport(d)

        # --- 5a) Explicit OFF → preserve as day_off (never invent layover)
        if src == "off":
            d["day_type"] = "day_off"
            d["home_or_away"] = "home"
            # source OFF is HIGH confidence; strip any leaked layover fields
            d.pop("layover_city", None)
            d.pop("layover_country", None)
            d.pop("layover_nights", None)
            _set_equipment(d, "any")
            audit["preserved_off_days"] += 1
            continue

        # --- 5b) Standby → equipment always "any" at home base
        if src == "standby":
            d["day_type"] = "standby"
            # Standby is at home unless the source explicitly located it away.
            loc = (d.get("standby_location") or "").lower()
            if loc not in ("hotel", "away", "outstation"):
                d["home_or_away"] = "home"
                _set_equipment(d, "any")
                audit["fixed_standby_equipment"] += 1
            continue

        # --- 5c) Sim / annual leave / sickness — passthrough with normal fields
        if src == "sim":
            d["day_type"] = "sim_training"
            d["home_or_away"] = "home"
            _set_equipment(d, "any")
            continue
        if src == "annual_leave":
            d["day_type"] = "annual_leave"
            d["home_or_away"] = "home"
            _set_equipment(d, "any")
            continue

        # Iter200-g · A blank day (no sectors) sitting BETWEEN a
        # resolved flight_to_layover (or prior layover_day) and a
        # future return leg from the same outstation must be classified
        # as a layover_day, regardless of what the LLM labelled it
        # (unknown / rest / flying day / blank column). This runs
        # BEFORE the generic rest_day fallback so it wins uniformly.
        if not fs:
            prev = days[i - 1] if i > 0 else None
            prev_type = (prev or {}).get("day_type") if prev else None
            prev_end_airport = _end_airport(prev) if prev else None
            prev_city = (prev or {}).get("layover_city") if prev else None
            if prev_type in ("flight_to_layover", "layover_day"):
                match_airport = prev_end_airport
                if not match_airport and prev_type == "layover_day":
                    for lb in range(i - 1, -1, -1):
                        if days[lb].get("day_type") == "flight_to_layover":
                            match_airport = _end_airport(days[lb])
                            break
                has_return = False
                if match_airport:
                    for k in range(i + 1, len(days)):
                        if _start_airport(days[k]) == match_airport:
                            has_return = True
                            break
                if has_return:
                    d["day_type"] = "layover_day"
                    d["layover_city"] = prev_city or match_airport
                    _set_equipment(d, "hotel_or_bodyweight")
                    d["_normalized"] = True
                    continue

        # --- 5d) Flights / layovers / turnarounds
        if not fs and src not in ("layover",):
            # No sectors and no explicit layover token.
            # Iter200-b · Blank day with no destination city and no
            # pairing evidence → classify as rest day (per user spec).
            if src == "unknown":
                d["day_type"] = "rest_day"
                d["home_or_away"] = "home"
                _set_equipment(d, "any")
            continue

        # We have sectors OR the source called it a layover.
        # Look for a LATER duty starting from `end` — this is the key
        # test for whether a layover really exists.
        next_hit = _next_flight_day(days, i)
        gap_h: Optional[float] = None
        if next_hit and end:
            j, ndx = next_hit
            if _start_airport(ndx) == end:
                gap_h = _ground_hours(d, ndx)

        ended_away = bool(end) and not _is_home(end, hb)
        started_at_home = bool(start) and _is_home(start, hb)
        ended_home = bool(end) and _is_home(end, hb)

        # Iter200 · Middle-of-layover day: source said Layover Full /
        # Layover Rest / similar AND no sectors. Only accept as
        # layover_day when the PREVIOUS day is a resolved
        # flight_to_layover OR another layover_day, AND some later day
        # returns from that same outstation airport. This preserves
        # genuine multi-day layovers without inventing new ones from
        # stray labels.
        if not fs and src == "layover":
            prev = days[i - 1] if i > 0 else None
            prev_type = (prev or {}).get("day_type") if prev else None
            # Use the AIRPORT code (end of prev's flights) as the join
            # key — layover_city may be a friendly name ("Orlando") while
            # the next-day departure will use the IATA code ("MCO").
            prev_end_airport = _end_airport(prev) if prev else None
            prev_city = (prev or {}).get("layover_city") if prev else None
            if prev_type in ("flight_to_layover", "layover_day"):
                # verify a later return leg exists from the same outstation
                match_airport = prev_end_airport
                # For layover_day chained cases, walk further back.
                if not match_airport and prev_type == "layover_day":
                    for lb in range(i - 1, -1, -1):
                        if days[lb].get("day_type") == "flight_to_layover":
                            match_airport = _end_airport(days[lb])
                            break
                has_return = False
                if match_airport:
                    for k in range(i + 1, len(days)):
                        if _start_airport(days[k]) == match_airport:
                            has_return = True
                            break
                if has_return:
                    d["day_type"] = "layover_day"
                    d["layover_city"] = prev_city or match_airport
                    _set_equipment(d, "hotel_or_bodyweight")
                    d["_normalized"] = True
                    continue
            # Iter200-h · The source called it a layover but there is
            # no destination city AND no pairing evidence. Per user
            # spec: "Do not promote a blank day to a layover day when
            # no destination city is present — classify it as a rest
            # day instead." This is safer than needs_review because it
            # produces a usable card for the customer (a rest day is a
            # sensible default when the parser was ambiguous).
            if not d.get("layover_city"):
                d["day_type"] = "rest_day"
                d["home_or_away"] = "home"
                _set_equipment(d, "any")
                d.pop("needs_review", None)
                continue
            # We have a stated layover_city but no pairing — trust the
            # source and keep it as a layover_day, just with reduced
            # confidence so the review screen flags it.
            d["day_type"] = "layover_day"
            _set_equipment(d, "hotel_or_bodyweight")
            d["confidence"] = min(float(d.get("confidence", 0.6)), 0.6)
            continue

        # Same-day roundtrip HOME → X → HOME → turnaround (never layover)
        # even if it crosses midnight.
        if started_at_home and ended_home and len(fs) >= 2:
            d["day_type"] = "turnaround"
            d.pop("layover_city", None)
            _set_equipment(d, "any")
            continue

        # Iter200-d · Explicit night-flight safety net.
        # If the SOURCE explicitly labelled the day "Night flight" /
        # "Overnight" / "Red-eye" and there are sectors, always classify
        # as night_flight regardless of what the calendar-date crossing
        # looks like. Prevents any downstream branch from re-classifying
        # a labelled night flight as a layover.
        _src_lc = (d.get("day_type") or "").lower()
        _is_source_night = fs and (
            "night flight" in _src_lc
            or "overnight" in _src_lc
            or "red-eye" in _src_lc
            or "red eye" in _src_lc
        )
        if _is_source_night:
            d["day_type"] = "night_flight"
            d.pop("layover_city", None)
            _set_equipment(d, "any")
            d["_normalized"] = True
            continue

        # Ended away — is it a genuine layover?
        if ended_away and fs:
            # Iter200-b · Early-morning-departure rule.
            # If the FIRST sector of THIS day departs between 00:00 and
            # 05:00 AND the previous day (which must have ended at the
            # same outstation) had a ground gap < 8h, this is the
            # RETURN leg of a night turnaround, not a fresh layover
            # departure. Downgrade both days to night_flight.
            first_dep = _parse_hhmm((fs[0] or {}).get("dep"))
            if first_dep is not None and first_dep[0] < 5:
                prev = days[i - 1] if i > 0 else None
                if (prev and _end_airport(prev) and _end_airport(prev) == start
                        and _flights(prev)):
                    gap_back = _ground_hours(prev, d)
                    if gap_back is not None and gap_back < MIN_LAYOVER_GROUND_HOURS:
                        # Downgrade the previous outbound day AND this
                        # return day to night_flight.
                        prev["day_type"] = "night_flight"
                        prev.pop("layover_city", None)
                        _set_equipment(prev, "any")
                        prev["_normalized"] = True
                        d["day_type"] = "night_flight"
                        d.pop("layover_city", None)
                        _set_equipment(d, "any")
                        d["_normalized"] = True
                        audit["downgraded_midnight_crossings"] += 1
                        continue
            # Rule: layover requires next duty from same outstation on a
            # LATER calendar day AND gap >= floor.
            genuine_layover = False
            if next_hit and gap_h is not None:
                j, ndx = next_hit
                same_city = _start_airport(ndx) == end
                # dates must be different (later day)
                d_this = _parse_iso_date(d.get("date"))
                d_next = _parse_iso_date(ndx.get("date"))
                later = (d_this and d_next and d_next > d_this)
                if same_city and later and gap_h >= MIN_LAYOVER_GROUND_HOURS:
                    genuine_layover = True
                elif same_city and gap_h < MIN_LAYOVER_GROUND_HOURS:
                    # Cross-midnight roundtrip: HOME → X (arr next day) → HOME
                    # within one continuous duty → night flight, not layover.
                    d["day_type"] = "night_flight"
                    d.pop("layover_city", None)
                    _set_equipment(d, "any")
                    d["_normalized"] = True
                    audit["downgraded_midnight_crossings"] += 1
                    # Also downgrade the "return" day the LLM likely
                    # tagged as layover_departure.
                    if ndx and _source_class(ndx) in ("layover", "flight"):
                        # tag the return side too — even without a new
                        # sector it's the return LEG of the same duty.
                        if _end_airport(ndx) and _is_home(_end_airport(ndx), hb):
                            ndx["day_type"] = "night_flight"
                            ndx.pop("layover_city", None)
                            _set_equipment(ndx, "any")
                            ndx["_normalized"] = True
                    continue
            elif next_hit is None:
                # No next duty visible — end of roster window. The source
                # said "layover" or the LLM said it. Keep as layover ONLY
                # if the source explicitly said so AND we have a city.
                if src == "layover" and d.get("layover_city"):
                    genuine_layover = True

            if genuine_layover:
                d["day_type"] = "flight_to_layover"
                # ensure layover_city is populated — from source or from `end`
                if not d.get("layover_city"):
                    d["layover_city"] = end
                _set_equipment(d, "hotel_or_bodyweight")
                continue

            # Ended away, no genuine-layover proof — needs_review or night_flight
            if src == "layover" and not d.get("layover_city"):
                # LLM said layover but no city — fix "Layover in None"
                d["day_type"] = "needs_review"
                d["confidence"] = 0.35
                _flag_review(d, audit, reason="Layover claimed with no location — please confirm")
                audit["fixed_layover_in_none"] += 1
                continue
            # Fallthrough: keep the LLM's shape but mark for review
            if src == "layover":
                # e.g. "Layover Arrival Day" with city populated but
                # no next-duty evidence — trust the source, keep it.
                d["day_type"] = "flight_to_layover"
                _set_equipment(d, "hotel_or_bodyweight")
                continue

            # Sectors present, ended away, no next duty evidence → keep as
            # multi_sector_flight and mark for review.
            d["day_type"] = "flight_to_layover" if src == "layover" else "flight"
            # Only cap confidence when we really can't tell what happened —
            # i.e. flight ended away with no next duty AND source didn't
            # explicitly claim a layover.
            if not d.get("layover_city") and src != "layover":
                d["confidence"] = min(float(d.get("confidence", 0.5)), 0.6)
            continue

        # Ended at home OR unresolved
        if fs and started_at_home and ended_home:
            d["day_type"] = "turnaround" if len(fs) >= 2 else "flight"
            d.pop("layover_city", None)
            _set_equipment(d, "any")
            continue

        # Return-from-layover: started away, ended home, and the PREVIOUS
        # day was either a flight_to_layover OR a layover_day (multi-day case).
        if fs and not started_at_home and ended_home:
            prev = days[i - 1] if i > 0 else None
            prev_type = (prev or {}).get("day_type") if prev else None
            if prev_type in ("flight_to_layover", "layover_day"):
                d["day_type"] = "return_from_layover"
                d["layover_city"] = (prev or {}).get("layover_city") or start
                _set_equipment(d, "hotel_or_bodyweight")
                continue
            d["day_type"] = "flight"
            continue

        # Layover-day (blank inside a resolved pairing) — only when
        # PREV was flight_to_layover AND NEXT is a return leg from same city.
        if not fs and src == "unknown":
            prev = days[i - 1] if i > 0 else None
            nxt = _next_flight_day(days, i)
            if (prev and prev.get("day_type") == "flight_to_layover"
                    and prev.get("layover_city")
                    and nxt and _start_airport(nxt[1]) == prev.get("layover_city")):
                d["day_type"] = "layover_day"
                d["layover_city"] = prev.get("layover_city")
                _set_equipment(d, "hotel_or_bodyweight")
                continue
            # Iter200-b · Blank day with NO destination city and no
            # resolved pairing — classify as a rest day (safer default
            # than needs_review, and matches the user's spec that "a
            # blank day must never be promoted to a layover day when no
            # destination city is present").
            d["day_type"] = "rest_day"
            d["home_or_away"] = "home"
            _set_equipment(d, "any")
            continue

    # Iter200-b · SECOND-PASS DEDUPE — the LLM occasionally emits both a
    # `turnaround` row AND a `layover_arrival` row for the same date.
    # The first-pass dedupe (before classification) can't tell which is
    # more authoritative because neither has been normalized yet. Now
    # that classification has run, we know which rows resolved to real
    # duties and can safely collapse any remaining same-date twins.
    _pre = len(days)
    days, dupes2 = _dedupe(days)
    if dupes2:
        audit["deduped_dates"] += dupes2

    # 6) Presenter pass — populate customer-facing client_label + strip
    # raw parser notes so the customer never sees them.
    for d in days:
        d["client_label"] = _customer_label(d)
        # Retain internal notes for audit but hide from customer-visible list
        raw_notes = d.get("notes") or ""
        if _looks_like_internal_note(raw_notes):
            d["_internal_notes"] = raw_notes
            d["notes"] = ""

    return {"days": days, "dropped": dropped_month, "audit": audit}


# --- Small helpers used by the pass -----------------------------------------

def _set_equipment(day: dict, val: str) -> None:
    day["equipment_assumption"] = val


def _flag_review(day: dict, audit: dict, reason: str) -> None:
    day["needs_review"] = True
    day["review_reason"] = reason
    audit["flagged_needs_review"] += 1


_INTERNAL_NOTE_TOKENS = (
    "blank day inside",
    "out-of-base pairing",
    "arrow marker detected",
    "inferred layover",
    "started as overnight",
    "continuation block",
    "midnight_crossing",
    "→ inferred",
    "not a layover.",
    # Iter200-g · Additional debug/parser strings that must never
    # leak to the customer.
    "flight continues into next day",
    "marker detected",
    "continues into next day",
    "overnight continuation from previous day",
    "blank column",
    "layover inference",
)


def _looks_like_internal_note(text: str) -> bool:
    if not text:
        return False
    lo = text.lower()
    return any(tok in lo for tok in _INTERNAL_NOTE_TOKENS)


__all__ = [
    "MIN_LAYOVER_GROUND_HOURS",
    "normalize_roster",
    "refresh_client_label",
]


def refresh_client_label(day: dict) -> str:
    """Regenerate ONLY the customer-facing `client_label` for a single
    day without re-running classification. Use this from the PATCH
    handler so a user-confirmed pick (e.g. member manually chose
    Layover on a Flying Day) is respected — we don't re-classify, we
    only refresh the label the customer sees.

    Also translates legacy chip keys ("Layover", "Flight", "Off", ...)
    to the internal type vocabulary so downstream code (icons, generator,
    burden math) stays consistent.
    """
    raw = (day.get("day_type") or "").strip().lower()
    _CHIP_TO_INTERNAL = {
        "flight": "turnaround",
        "flight (turnaround)": "turnaround",
        "direct flight": "flight",
        "direct": "flight",
        "layover": "flight_to_layover",
        "standby": "standby",
        "off": "day_off",
        "off duty": "day_off",
        "home": "home_day",
        "sim / training": "sim_training",
        "sim": "sim_training",
        "sick": "sickness",
        "annual leave": "annual_leave",
        "unknown/needs confirmation": "needs_review",
        "not sure yet": "needs_review",
    }
    if raw in _CHIP_TO_INTERNAL:
        day["day_type"] = _CHIP_TO_INTERNAL[raw]
    day["client_label"] = _customer_label(day)
    return day["client_label"]
