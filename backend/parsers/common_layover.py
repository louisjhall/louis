"""parsers.common_layover — shared logic for classifying layover vs
midnight-crossing / short-turn flights across every airline parser.

Iter199 · Extracted from the Etihad-specific fix so the same gate can be
applied to Emirates, BA, and any future adapter. See
`docs/roster-audit-september.md` for the rationale — TL;DR: `is_out_of_base`
based on the last sector's destination is not sufficient to prove a hotel
layover happened; we also need to see enough dwell time at the outstation.

Public API:
    * ``MIN_LAYOVER_GROUND_HOURS`` — conservative floor (8h). Regulator
      minimum crew rest is typically 10h; 8h is a safety margin that
      keeps genuine "reduced-rest" layovers on the layover side.
    * ``outstation_ground_hours(prev, nxt)`` — computes the dwell time
      between the last sector arrival at ``prev.end_location`` and the
      first sector departure from that same city on the next day.
      Returns ``None`` when either half is unparseable — callers should
      bias to false-positive (i.e., keep today's permissive behaviour)
      rather than silently downgrading a real layover.
    * ``classify_transition(prev, nxt)`` — small helper that turns the
      gap into one of the day_type verdicts (``"layover"``,
      ``"midnight_crossing"``, ``"short_turn"``, ``"unknown"``).

Design intent
=============
The helpers are deliberately duck-typed on ``prev`` / ``nxt`` — they
read a small subset of fields that every parser already exposes on its
day dataclass:

    * ``date``            : ISO ``YYYY-MM-DD`` string (required).
    * ``end_location``    : IATA of the last sector's destination.
    * ``release_time``    : ``HH:MM`` string of the last sector arrival,
                            OR fall back to the last ``Sector.arrival_time``.
    * ``sectors``         : list of ``Sector`` objects; each must have at
                            least ``origin``, ``destination`` and either
                            ``departure_time`` or ``report_time`` for the
                            *next* day's leg.

This lets us extract a shared helper without forcing every parser to
share a data class.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional


# --- Constants --------------------------------------------------------------

MIN_LAYOVER_GROUND_HOURS: float = 8.0
"""Below this dwell time at the outstation, treat the pairing as a
short-turn or midnight-crossing (not a hotel layover).

Rationale: real regulator crew-rest floors are ~10h; picking 8h leaves
margin for "reduced-rest" layovers that DO have hotel + bunk time. Any
dwell below 8h is functionally a crew-change or tech-stop — the crew
did not rest, and downstream fatigue coaching should treat it as red-
day training impact, not a rested layover.
"""


# --- Time helpers -----------------------------------------------------------

def _parse_hhmm(s: Optional[str]) -> Optional[tuple[int, int]]:
    """Extract ``(H, M)`` from strings like ``"07:30"`` or ``"0730"``.
    Returns ``None`` when the input is empty or malformed."""
    if not s:
        return None
    txt = str(s).strip()
    # Strip trailing "↓" / "↑" markers that some parsers keep on times.
    txt = txt.replace("↓", "").replace("↑", "").strip()
    if len(txt) == 4 and txt.isdigit():                 # "0730"
        h, m = int(txt[:2]), int(txt[2:])
    elif ":" in txt:
        try:
            hh, mm = txt.split(":", 1)
            h, m = int(hh), int(mm[:2])
        except ValueError:
            return None
    else:
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h, m


def _parse_iso_date(s: Optional[str]) -> Optional[datetime]:
    """Accept ``YYYY-MM-DD`` or ``DD/MM/YYYY``. Returns midnight-anchored."""
    if not s:
        return None
    txt = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def _combine(date_str: Optional[str], hhmm: Optional[str]) -> Optional[datetime]:
    d = _parse_iso_date(date_str)
    t = _parse_hhmm(hhmm)
    if not d or not t:
        return None
    return d.replace(hour=t[0], minute=t[1])


# --- Field probes -----------------------------------------------------------

def _last_arrival_dt(prev: Any) -> Optional[datetime]:
    """Datetime of the last sector's arrival on ``prev``.

    Strategy (first hit wins):
        1. ``prev.sectors[-1].arrival_time`` with the sector's own
           ``arrival_date`` if the sector carries one (some parsers set
           this when they detect a midnight cross).
        2. ``prev.release_time`` combined with ``prev.date`` — but if
           the release time is EARLIER than the last sector's departure
           time we assume the arrival is on ``prev.date + 1`` (i.e. the
           sector crossed midnight — same rule the ↓ arrow encodes).
        3. Give up and return ``None`` so the caller keeps its legacy
           permissive behaviour.
    """
    sectors = getattr(prev, "sectors", None) or []
    prev_date = getattr(prev, "date", None)
    last = sectors[-1] if sectors else None

    # Case 1: sector carries its own arrival date/time.
    if last is not None:
        sect_arr_date = getattr(last, "arrival_date", None)
        sect_arr_time = getattr(last, "arrival_time", None)
        combined = _combine(sect_arr_date, sect_arr_time)
        if combined:
            return combined

    # Case 2: fall back to the day-level release_time + date.
    release = getattr(prev, "release_time", None)
    if release and prev_date:
        base = _combine(prev_date, release)
        if base is None:
            return None
        # If the last sector departed later than the release, the
        # release must be on day+1 (crossed midnight).
        if last is not None:
            dep = _parse_hhmm(getattr(last, "departure_time", None) or getattr(last, "report_time", None))
            rel = _parse_hhmm(release)
            if dep and rel and (rel[0] * 60 + rel[1]) < (dep[0] * 60 + dep[1]):
                base = base + timedelta(days=1)
        return base

    return None


def _first_departure_dt(nxt: Any, from_city: Optional[str]) -> Optional[datetime]:
    """Datetime of the earliest sector on ``nxt`` whose origin is
    ``from_city``. Falls back to ``nxt.report_time`` when no such sector
    is found (matches the parser's "report + first flight from OUT"
    assumption)."""
    if not from_city:
        return None
    sectors = getattr(nxt, "sectors", None) or []
    nxt_date = getattr(nxt, "date", None)
    for s in sectors:
        origin = getattr(s, "origin", None)
        if origin and origin == from_city:
            combined = _combine(
                getattr(s, "departure_date", None) or nxt_date,
                getattr(s, "departure_time", None) or getattr(s, "report_time", None),
            )
            if combined:
                return combined
    # Fallback: day-level report_time — only meaningful if the day's
    # start_location matches from_city (otherwise the report is for a
    # positioning leg back at base).
    start_loc = getattr(nxt, "start_location", None)
    if start_loc and start_loc == from_city:
        report = getattr(nxt, "report_time", None)
        return _combine(nxt_date, report)
    return None


# --- Public API -------------------------------------------------------------

def outstation_ground_hours(prev: Any, nxt: Optional[Any]) -> Optional[float]:
    """Compute dwell time (hours) between ``prev.end_location`` last
    arrival and ``nxt``'s first departure from that same city.

    Contract:
        * Returns a positive float on success.
        * Returns ``None`` when either datetime cannot be resolved from
          the available fields — the caller MUST treat this as "unknown"
          and fall back to legacy behaviour.
        * Returns a *negative* number in the pathological case where
          the next departure is earlier than the previous arrival —
          callers can treat this as ``None`` (parse error), but keeping
          it visible aids test debug output.
    """
    if not prev or not nxt:
        return None
    out_city = getattr(prev, "end_location", None)
    if not out_city:
        return None
    arr = _last_arrival_dt(prev)
    dep = _first_departure_dt(nxt, out_city)
    if not arr or not dep:
        return None
    delta = dep - arr
    return delta.total_seconds() / 3600.0


def classify_transition(prev: Any, nxt: Optional[Any]) -> str:
    """High-level verdict wrapper — returns one of
    ``"layover"`` | ``"midnight_crossing"`` | ``"short_turn"`` |
    ``"unknown"``.

    * ``"layover"``           — ground time >= MIN_LAYOVER_GROUND_HOURS.
    * ``"midnight_crossing"`` — ground time < floor AND the day pair
                                straddles midnight (i.e., the previous
                                day's arrival timestamp falls on the
                                next calendar day).
    * ``"short_turn"``        — ground time < floor but the arrival is
                                on the same calendar day as departure
                                (rare for AUH night flights but common
                                for European short-haul).
    * ``"unknown"``           — either datetime unavailable; caller
                                should fall back to legacy behaviour.
    """
    hours = outstation_ground_hours(prev, nxt)
    if hours is None:
        return "unknown"
    if hours >= MIN_LAYOVER_GROUND_HOURS:
        return "layover"
    arr = _last_arrival_dt(prev)
    prev_date = _parse_iso_date(getattr(prev, "date", None))
    if arr and prev_date and arr.date() > prev_date.date():
        return "midnight_crossing"
    return "short_turn"


__all__ = [
    "MIN_LAYOVER_GROUND_HOURS",
    "outstation_ground_hours",
    "classify_transition",
]
