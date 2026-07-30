"""
Iter 130b — Emirates Detailed Report parser + roster router regression tests
============================================================================

Ensures:
1. Detection is airline+format specific, with no fall-through guessing.
2. All 4 real fixtures route to the correct parser.
3. The new Emirates Detailed Report parser produces exactly one row per
   calendar date, correctly classifies every duty type, respects (+)
   overnight markers, and never coerces a non-flight into a flight.
4. Existing Emirates Calendar and Etihad parsers are unaffected.

Fixtures live outside the repo (under /tmp/rosters/ populated by the agent
at task time). The tests skip cleanly if the fixture PDFs are not present,
so CI won't red-flag machines without them.
"""
import os
import pytest

FIX_DIR = "/tmp/rosters"
FIX = {
    "emirates_detailed_aug": os.path.join(FIX_DIR, "joel_august_detailed.pdf"),
    "emirates_calendar_jul": os.path.join(FIX_DIR, "joel_july.pdf"),
    "etihad_jul":            os.path.join(FIX_DIR, "pietro_july.pdf"),
    "etihad_aug":            os.path.join(FIX_DIR, "pietro_aug.pdf"),
}

skip_if_missing = pytest.mark.skipif(
    not all(os.path.exists(p) for p in FIX.values()),
    reason="Roster fixture PDFs not present under /tmp/rosters/",
)


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _route(pdf_bytes: bytes) -> str:
    """Mirror the router priority used by feature_coach_roster_upload.py and
    feature_roster_confirmation.py. Kept in a tiny helper so the test acts
    as an executable spec for the routing contract."""
    from parsers.etihad import detect_etihad
    from parsers.emirates import detect_emirates
    from parsers.emirates_detailed import detect_emirates_detailed

    if detect_etihad(pdf_bytes):
        return "etihad"
    if detect_emirates_detailed(pdf_bytes):
        return "emirates_detailed"
    if detect_emirates(pdf_bytes):
        return "emirates_calendar"
    return "unknown"


# ---------------------------------------------------------------------------
# Router / detection tests.
# ---------------------------------------------------------------------------

@skip_if_missing
def test_router_emirates_detailed():
    assert _route(_read(FIX["emirates_detailed_aug"])) == "emirates_detailed"


@skip_if_missing
def test_router_emirates_calendar_still_calendar():
    """A Calendar Report must NOT be picked up by the Detailed detector."""
    assert _route(_read(FIX["emirates_calendar_jul"])) == "emirates_calendar"


@skip_if_missing
def test_router_etihad_stays_etihad():
    """Etihad rosters must never be routed to Emirates just because of
    similar flight-code terminology."""
    for key in ("etihad_jul", "etihad_aug"):
        assert _route(_read(FIX[key])) == "etihad", key


def test_router_rejects_unknown():
    """No fall-through guessing: unrecognised PDF stays 'unknown'."""
    garbage = b"%PDF-1.4\n%not-a-real-roster\n%%EOF\n"
    assert _route(garbage) == "unknown"


# ---------------------------------------------------------------------------
# Detailed Report content correctness.
# ---------------------------------------------------------------------------

@skip_if_missing
def test_detailed_parses_full_month():
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    assert r.detected is True
    assert r.template == "emirates_crew_roster_detailed_report"
    assert r.crew_id == "448473"
    assert r.crew_name == "Joel Van Dieren"
    assert r.month == 8 and r.year == 2026
    # Every calendar date exactly once
    dates = [d.date for d in r.days]
    assert len(dates) == 31
    assert len(set(dates)) == 31


@skip_if_missing
def test_detailed_classifies_all_duty_types():
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    counts: dict[str, int] = {}
    for d in r.days:
        counts[d.day_type] = counts.get(d.day_type, 0) + 1
    # 8 flights (Aug 5,7,8,10,20,21,29,30 — includes codeshare AC8909)
    assert counts.get("flight") == 8, counts
    assert counts.get("sim_training") == 1, counts
    assert counts.get("available_duty") == 2, counts
    # Rest days can be reclassified as layover_rest during pairings
    assert (counts.get("rest_day", 0) + counts.get("layover_rest", 0)) >= 4
    assert counts.get("day_off", 0) >= 10


@skip_if_missing
def test_detailed_never_coerces_non_flight_into_flight():
    """Every non-flight day MUST NOT carry a flight_number."""
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    for d in r.days:
        if d.day_type != "flight":
            assert d.flight_number is None, (d.date, d.day_type, d.flight_number)
            assert not d.sectors, (d.date, d.day_type)


@skip_if_missing
def test_detailed_respects_overnight_plus_marker():
    """Long-haul returns with `(+)` must set arrival_next_day=True."""
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    overnights = [d for d in r.days if d.arrival_next_day]
    # Aug 10 (ORD-DWC), Aug 21 (BOS-DXB), Aug 30 (AMS-DXB) all cross midnight
    overnight_dates = {d.date for d in overnights}
    assert "2026-08-10" in overnight_dates
    assert "2026-08-21" in overnight_dates
    assert "2026-08-30" in overnight_dates


@skip_if_missing
def test_detailed_flight_route_extraction():
    """Sample the two most-important rows from the spec."""
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    by_date = {d.date: d for d in r.days}

    d20 = by_date["2026-08-20"]
    assert d20.day_type == "flight"
    assert d20.flight_number == "EK237"
    assert d20.start_location == "DXB" and d20.end_location == "BOS"
    assert d20.duty_start_local == "06:55"
    assert d20.duty_end_local == "15:15"
    assert d20.arrival_next_day is False

    d21 = by_date["2026-08-21"]
    assert d21.day_type == "flight"
    assert d21.flight_number == "EK238"
    assert d21.start_location == "BOS" and d21.end_location == "DXB"
    assert d21.duty_start_local == "21:45"
    assert d21.duty_end_local == "20:30"
    assert d21.arrival_next_day is True


@skip_if_missing
def test_detailed_sim_row_captured_correctly():
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    d17 = next(d for d in r.days if d.date == "2026-08-17")
    assert d17.day_type == "sim_training"
    assert d17.auto_label == "SIM_TRAINING"
    assert d17.duty_start_local == "03:00"
    assert d17.duty_end_local == "08:30"
    assert d17.flight_number is None


@skip_if_missing
def test_detailed_avd_row_captured_correctly():
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    for iso in ("2026-08-26", "2026-08-27"):
        d = next(x for x in r.days if x.date == iso)
        assert d.day_type == "available_duty", iso
        assert d.duty_start_local == "07:00", iso
        assert d.duty_end_local == "15:00", iso


@skip_if_missing
def test_detailed_codeshare_flight_still_captured():
    """AC8909 [YYZ-ORD] is an Air Canada codeshare row inside the Emirates
    roster — the parser must still capture it as a flight sector."""
    from parsers.emirates_detailed import parse_emirates_detailed
    r = parse_emirates_detailed(_read(FIX["emirates_detailed_aug"]))
    d = next(x for x in r.days if x.date == "2026-08-08")
    assert d.day_type == "flight"
    assert d.flight_number == "AC8909"
    assert d.start_location == "YYZ" and d.end_location == "ORD"


# ---------------------------------------------------------------------------
# Guard: the addition of Detailed support must NOT change existing parsers.
# ---------------------------------------------------------------------------

@skip_if_missing
def test_calendar_parser_still_produces_days():
    """Existing Emirates Calendar parser output stays healthy."""
    from parsers.emirates import parse_emirates_pdf
    r = parse_emirates_pdf(_read(FIX["emirates_calendar_jul"]))
    assert r.detected is True
    assert r.month == 7 and r.year == 2026
    assert len(r.days) >= 28   # July has 31 days; small tolerance for leaks


@skip_if_missing
def test_etihad_parser_untouched():
    from parsers.etihad import parse_etihad_pdf
    r = parse_etihad_pdf(_read(FIX["etihad_jul"]))
    assert r.detected is True
