"""Regression tests for Iter199 — night-flight vs layover disambiguation.

Covers both:
  * The shared helper `parsers.common_layover.outstation_ground_hours`
    (unit-tested with synthetic day/sector objects).
  * The Etihad post-processor's new gate, replayed against the September
    Etihad roster (AUH) as the acceptance golden.

Design note: because these tests need to run without pulling the whole
FastAPI app (which does heavy startup migrations), the imports are
deliberately narrow — only the parser + helper modules.
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Make `parsers.*` importable when running via `pytest tests/…` from
# /app/backend without an installed package.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from parsers.common_layover import (        # noqa: E402
    MIN_LAYOVER_GROUND_HOURS,
    outstation_ground_hours,
    classify_transition,
)


# ---------------------------------------------------------------------------
# Duck-typed test doubles — mirror the fields the helper reads.
# ---------------------------------------------------------------------------

@dataclass
class _S:
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    report_time: Optional[str] = None
    departure_date: Optional[str] = None
    arrival_date: Optional[str] = None


@dataclass
class _D:
    date: Optional[str] = None
    end_location: Optional[str] = None
    start_location: Optional[str] = None
    release_time: Optional[str] = None
    report_time: Optional[str] = None
    sectors: list[_S] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Unit tests — outstation_ground_hours
# ---------------------------------------------------------------------------

def test_ground_hours_same_day_two_hours():
    """Prev ends LHR 05:00, next departs LHR 07:00 → 2h."""
    prev = _D(
        date="2026-09-13", end_location="LHR",
        release_time="05:00",
        sectors=[_S(origin="AUH", destination="LHR", departure_time="00:00", arrival_time="05:00")],
    )
    nxt = _D(
        date="2026-09-13", start_location="LHR",
        report_time="06:30",
        sectors=[_S(origin="LHR", destination="AUH", departure_time="07:00")],
    )
    h = outstation_ground_hours(prev, nxt)
    assert h is not None and abs(h - 2.0) < 1e-6, f"expected 2.0h, got {h}"


def test_ground_hours_crosses_midnight_ZRH():
    """Prev ends ZRH day N+1 00:20 (via ↓), next departs 02:55 → 2h35m.

    This replays the 13→14 Sep ZRH case from the audit — release_time
    on prev is earlier than the sector's departure_time, so the helper
    must roll the arrival to prev.date + 1.
    """
    prev = _D(
        date="2026-09-13", end_location="ZRH",
        release_time="00:20",   # ↓ next-day arrival
        sectors=[_S(origin="AUH", destination="ZRH", departure_time="07:30", arrival_time="00:20", arrival_date="2026-09-14")],
    )
    nxt = _D(
        date="2026-09-14", start_location="ZRH",
        report_time="02:00",
        sectors=[_S(origin="ZRH", destination="AUH", departure_time="02:55")],
    )
    h = outstation_ground_hours(prev, nxt)
    assert h is not None
    assert 2.5 < h < 2.7, f"expected ~2h35m, got {h:.2f}"


def test_ground_hours_missing_release_returns_none():
    """When neither the last sector's arrival_time nor prev.release_time
    are parseable, the helper must return None so callers keep the
    legacy permissive behaviour."""
    prev = _D(
        date="2026-09-13", end_location="LHR",
        release_time=None,
        sectors=[_S(origin="AUH", destination="LHR")],
    )
    nxt = _D(
        date="2026-09-14", start_location="LHR",
        sectors=[_S(origin="LHR", destination="AUH", departure_time="07:00")],
    )
    assert outstation_ground_hours(prev, nxt) is None


def test_ground_hours_no_matching_next_sector_returns_none():
    """If next day has no sector originating at prev.end_location, the
    helper cannot compute a dwell time."""
    prev = _D(
        date="2026-09-13", end_location="LHR",
        release_time="05:00",
        sectors=[_S(origin="AUH", destination="LHR", arrival_time="05:00")],
    )
    nxt = _D(
        date="2026-09-14",
        sectors=[_S(origin="AUH", destination="JFK", departure_time="07:00")],
    )
    assert outstation_ground_hours(prev, nxt) is None


def test_ground_hours_boundary_just_below_floor():
    """7h 59m must NOT be treated as a layover (helper returns 7.98..)."""
    prev = _D(
        date="2026-09-01", end_location="CMB",
        release_time="00:00",
        sectors=[_S(origin="AUH", destination="CMB", arrival_time="00:00")],
    )
    nxt = _D(
        date="2026-09-01", start_location="CMB",
        sectors=[_S(origin="CMB", destination="AUH", departure_time="07:59")],
    )
    h = outstation_ground_hours(prev, nxt)
    assert h is not None and h < MIN_LAYOVER_GROUND_HOURS
    assert classify_transition(prev, nxt) in ("short_turn", "midnight_crossing")


def test_ground_hours_boundary_just_above_floor():
    """8h 01m must be treated as a layover."""
    prev = _D(
        date="2026-09-01", end_location="CMB",
        release_time="00:00",
        sectors=[_S(origin="AUH", destination="CMB", arrival_time="00:00")],
    )
    nxt = _D(
        date="2026-09-01", start_location="CMB",
        sectors=[_S(origin="CMB", destination="AUH", departure_time="08:01")],
    )
    h = outstation_ground_hours(prev, nxt)
    assert h is not None and h >= MIN_LAYOVER_GROUND_HOURS
    assert classify_transition(prev, nxt) == "layover"


def test_ground_hours_boundary_exactly_floor_is_layover():
    """8h exactly → layover (>= boundary in classifier)."""
    prev = _D(
        date="2026-09-01", end_location="CMB",
        release_time="00:00",
        sectors=[_S(origin="AUH", destination="CMB", arrival_time="00:00")],
    )
    nxt = _D(
        date="2026-09-01", start_location="CMB",
        sectors=[_S(origin="CMB", destination="AUH", departure_time="08:00")],
    )
    assert classify_transition(prev, nxt) == "layover"


def test_true_hotel_layover_still_classified():
    """AUH→BKK arrive 23:55 day N, depart 12:00 day N+1 → ~12h → layover."""
    prev = _D(
        date="2026-09-05", end_location="BKK",
        release_time="23:55",
        sectors=[_S(origin="AUH", destination="BKK", departure_time="18:00", arrival_time="23:55")],
    )
    nxt = _D(
        date="2026-09-06", start_location="BKK",
        report_time="10:30",
        sectors=[_S(origin="BKK", destination="AUH", departure_time="12:00")],
    )
    h = outstation_ground_hours(prev, nxt)
    assert h is not None and h >= MIN_LAYOVER_GROUND_HOURS
    assert classify_transition(prev, nxt) == "layover"


# ---------------------------------------------------------------------------
# End-to-end test — feed the Etihad `_post_process` a synthetic version
# of the September roster and assert every day's verdict.
# ---------------------------------------------------------------------------

def _make_september_days():
    """Build a minimal list of ParsedDay objects mirroring the September
    Etihad roster (AUH) — one row per sector as it appears in the PDF.

    We stub only the fields `_post_process` reads. The intent is a
    "golden" acceptance test: the 3 real hotel layovers stay classified
    as layovers, and every misclassified night flight flips to a
    midnight-crossing / short-turn type with no layover_city.
    """
    from parsers.etihad import ParsedDay, Sector

    def _mk(date_iso, sectors, is_out=False, is_over=False,
            report=None, release=None, day_type=None,
            start_loc=None, end_loc=None):
        d = ParsedDay(date=date_iso)
        d.sectors = sectors
        d.sector_count = len(sectors)
        d.start_location = start_loc or (sectors[0].origin if sectors else None)
        d.end_location = end_loc or (sectors[-1].destination if sectors else None)
        d.report_time = report
        d.release_time = release
        d.is_out_of_base = bool(is_out or (d.end_location and d.end_location != "AUH"))
        d.is_overnight = is_over
        d.day_type = day_type or ("flight" if sectors else "off")
        return d

    S = Sector
    days = [
        # 13 Sep — AUH→ZRH departs 07:30 arrives 00:20 next day (↓)
        _mk("2026-09-13", [S(flight_number="140", origin="AUH", destination="ZRH",
                             departure_time="07:30", arrival_time="00:20")],
            report="06:30", release="00:20"),
        # 14 Sep — ZRH→AUH departs 02:55 (↓ overnight continuation)
        _mk("2026-09-14", [S(flight_number="140", origin="ZRH", destination="AUH",
                             departure_time="02:55", arrival_time="08:45")],
            report="02:00", release="08:45", is_over=True),

        # 17 Sep — AUH→TLV departs 14:40 arrives 00:50 next day (↓)
        _mk("2026-09-17", [S(flight_number="363", origin="AUH", destination="TLV",
                             departure_time="14:40", arrival_time="00:50")],
            report="13:40", release="00:50"),
        # 18 Sep — TLV→AUH departs 08:35
        _mk("2026-09-18", [S(flight_number="363", origin="TLV", destination="AUH",
                             departure_time="08:35", arrival_time="13:00")],
            report="07:35", release="13:00", is_over=True),

        # 19 Sep — AUH→TLV depart 13:50 arrive 21:20 (TRUE 17h layover)
        _mk("2026-09-19", [S(flight_number="594", origin="AUH", destination="TLV",
                             departure_time="13:50", arrival_time="21:20")],
            report="12:50", release="21:20"),
        # 20 Sep — TLV→AUH depart 15:05 → 17h45m dwell
        _mk("2026-09-20", [S(flight_number="594", origin="TLV", destination="AUH",
                             departure_time="15:05", arrival_time="19:15")],
            report="14:05", release="19:15"),

        # 23 Sep — AUH→MAA depart 18:00 arrive 02:00 next day (↓)
        _mk("2026-09-23", [S(flight_number="346", origin="AUH", destination="MAA",
                             departure_time="18:00", arrival_time="02:00")],
            report="17:00", release="02:00"),
        # 24 Sep — MAA→AUH depart 02:00 (effectively zero ground time)
        _mk("2026-09-24", [S(flight_number="346", origin="MAA", destination="AUH",
                             departure_time="02:00", arrival_time="14:20")],
            report="01:00", release="14:20", is_over=True),

        # 05 Sep — AUH→KHI depart 06:30 arrive 07:45 (TRUE 22h layover)
        _mk("2026-09-05", [S(flight_number="320", origin="AUH", destination="KHI",
                             departure_time="06:30", arrival_time="07:45")],
            report="05:30", release="07:45"),
        # 06 Sep — KHI→AUH depart 07:45 next day = ~24h - not 22 but well over floor
        _mk("2026-09-06", [S(flight_number="320", origin="KHI", destination="AUH",
                             departure_time="07:45", arrival_time="18:30")],
            report="06:45", release="18:30"),

        # 29 Sep — AUH→XX depart 13:05 arrive 21:55 (TRUE 17h layover)
        _mk("2026-09-29", [S(flight_number="347", origin="AUH", destination="XXX",
                             departure_time="13:05", arrival_time="21:55")],
            report="12:05", release="21:55"),
        # 30 Sep — XX→AUH depart 15:10
        _mk("2026-09-30", [S(flight_number="347", origin="XXX", destination="AUH",
                             departure_time="15:10", arrival_time="18:00")],
            report="14:10", release="18:00"),
    ]
    # Bubble the ↓ flag onto the returning halves of each midnight-cross.
    days[1].is_overnight = True
    days[3].is_overnight = True
    days[7].is_overnight = True
    return days


def _by_date(days, iso):
    for d in days:
        if d.date == iso:
            return d
    raise AssertionError(f"day {iso} missing")


def test_september_acceptance():
    """Feed the synthetic September roster through the parser's
    `_post_process` and assert every day's verdict.

    Acceptance criteria from the audit:
      * 3 real hotel layovers (KHI 05-06, TLV 19-20, XX 29-30) → layover
      * 3 midnight-crossing turnarounds (ZRH 13-14, TLV 17-18, MAA 23-24)
        → midnight_crossing_flight + midnight_crossing_return, layover_city=None
    """
    from parsers.etihad import _post_process
    days = _make_september_days()
    processed = _post_process(days)

    # --- Midnight-crossing pairs — must NOT be layovers -----------------
    zrh1 = _by_date(processed, "2026-09-13")
    zrh2 = _by_date(processed, "2026-09-14")
    assert zrh1.day_type == "midnight_crossing_flight", f"ZRH 13 Sep got {zrh1.day_type}"
    assert zrh2.day_type == "midnight_crossing_return", f"ZRH 14 Sep got {zrh2.day_type}"
    assert zrh1.layover_city is None and zrh2.layover_city is None

    tlv1 = _by_date(processed, "2026-09-17")
    tlv2 = _by_date(processed, "2026-09-18")
    assert tlv1.day_type == "midnight_crossing_flight", f"TLV 17 Sep got {tlv1.day_type}"
    assert tlv2.day_type == "midnight_crossing_return", f"TLV 18 Sep got {tlv2.day_type}"
    assert tlv1.layover_city is None and tlv2.layover_city is None

    maa1 = _by_date(processed, "2026-09-23")
    maa2 = _by_date(processed, "2026-09-24")
    assert maa1.day_type == "midnight_crossing_flight", f"MAA 23 Sep got {maa1.day_type}"
    assert maa2.day_type == "midnight_crossing_return", f"MAA 24 Sep got {maa2.day_type}"
    assert maa1.layover_city is None and maa2.layover_city is None

    # --- True hotel layovers — MUST stay classified as layovers ---------
    khi1 = _by_date(processed, "2026-09-05")
    khi2 = _by_date(processed, "2026-09-06")
    assert khi1.day_type == "flight_to_layover", f"KHI 05 Sep got {khi1.day_type}"
    assert khi2.day_type == "return_from_layover", f"KHI 06 Sep got {khi2.day_type}"
    assert khi1.layover_city == "KHI"

    tlv_true1 = _by_date(processed, "2026-09-19")
    tlv_true2 = _by_date(processed, "2026-09-20")
    assert tlv_true1.day_type == "flight_to_layover", f"TLV 19 Sep got {tlv_true1.day_type}"
    assert tlv_true2.day_type == "return_from_layover", f"TLV 20 Sep got {tlv_true2.day_type}"
    assert tlv_true1.layover_city == "TLV"

    xx1 = _by_date(processed, "2026-09-29")
    xx2 = _by_date(processed, "2026-09-30")
    assert xx1.day_type == "flight_to_layover", f"XX 29 Sep got {xx1.day_type}"
    assert xx2.day_type == "return_from_layover", f"XX 30 Sep got {xx2.day_type}"
    assert xx1.layover_city == "XXX"


def test_missing_times_fallback_to_legacy_behaviour():
    """When we can't parse the times, the parser must NOT reclassify a
    would-be layover as a midnight-crossing — biasing to false-positive
    keeps genuine layovers safe."""
    from parsers.etihad import ParsedDay, Sector, _post_process
    d1 = ParsedDay(date="2026-09-05")
    d1.sectors = [Sector(flight_number="320", origin="AUH", destination="KHI")]
    d1.start_location = "AUH"; d1.end_location = "KHI"
    d1.is_out_of_base = True
    d1.day_type = "flight"
    d2 = ParsedDay(date="2026-09-06")
    d2.sectors = [Sector(flight_number="320", origin="KHI", destination="AUH")]
    d2.start_location = "KHI"; d2.end_location = "AUH"
    d2.day_type = "flight"

    processed = _post_process([d1, d2])
    # Times are all None → helper returns None → parser keeps legacy path
    # → still classified as a layover.
    assert processed[0].day_type == "flight_to_layover"
    assert processed[1].day_type == "return_from_layover"
    assert processed[0].layover_city == "KHI"


def test_blank_day_inside_pairing_still_becomes_layover_day():
    """A 3-day out-of-base tour (flight → blank → return) must still
    stamp the blank day as `layover_day` even after Iter199."""
    from parsers.etihad import ParsedDay, Sector, _post_process
    d1 = ParsedDay(date="2026-09-05")
    d1.sectors = [Sector(flight_number="1", origin="AUH", destination="JFK",
                         departure_time="09:00", arrival_time="15:00")]
    d1.start_location = "AUH"; d1.end_location = "JFK"
    d1.release_time = "15:00"
    d1.is_out_of_base = True
    d1.day_type = "flight"

    d2 = ParsedDay(date="2026-09-06")            # blank rest day at JFK
    d2.day_type = "off"

    d3 = ParsedDay(date="2026-09-07")
    d3.sectors = [Sector(flight_number="2", origin="JFK", destination="AUH",
                         departure_time="20:00", arrival_time="09:00")]
    d3.start_location = "JFK"; d3.end_location = "AUH"
    d3.report_time = "19:00"; d3.release_time = "09:00"
    d3.day_type = "flight"

    processed = _post_process([d1, d2, d3])
    assert processed[0].day_type == "flight_to_layover"
    assert processed[1].day_type == "layover_day"
    assert processed[1].layover_city == "JFK"
    assert processed[2].day_type == "return_from_layover"
