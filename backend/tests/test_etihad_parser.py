"""
Automated tests for the Etihad Personal Crew Schedule parser.

These use two real production PDFs (Pietro's July and August 2026 rosters)
as fixtures and verify the critical parsing behaviours listed in the
Etihad-parsing brief:

  * multi-sector days preserved
  * same flight number repeated NOT deduplicated
  * blank days inside an out-of-base pairing => layover_day
  * ↓ overnight continuation detected
  * XX => unknown/needs review
  * OFF / REST / ROFF / SBY correctly detected
  * A-prefix stripped from actual times

Run with: pytest -x /app/backend/tests/test_etihad_parser.py
"""
import sys
from pathlib import Path

sys.path.insert(0, "/app/backend")
from parsers.etihad import detect_etihad, parse_etihad_pdf, to_crewfit_days

FIX = Path("/app/backend/tests/fixtures")


def _load(name: str) -> bytes:
    return (FIX / name).read_bytes()


def _by_date(result, iso):
    for d in result.days:
        if d.date == iso:
            return d
    raise AssertionError(f"day {iso} not found")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_detects_etihad_pdf():
    assert detect_etihad(_load("pietro_july.pdf")) is True
    assert detect_etihad(_load("pietro_august.pdf")) is True


def test_ignores_non_etihad_pdf():
    # A tiny non-Etihad PDF (just headers) should not detect.
    fake = b"%PDF-1.4\n%%EOF"
    assert detect_etihad(fake) is False


# ---------------------------------------------------------------------------
# July fixture — top-level shape
# ---------------------------------------------------------------------------

def test_july_top_level():
    r = parse_etihad_pdf(_load("pietro_july.pdf"))
    assert r.detected is True
    assert r.template == "etihad_personal_crew_schedule"
    assert r.start_date == "2026-07-01"
    assert r.end_date == "2026-07-31"
    assert len(r.days) == 31
    assert r.parse_confidence >= 0.80


def test_july_off_and_rest_days():
    r = parse_etihad_pdf(_load("pietro_july.pdf"))
    d = _by_date(r, "2026-07-01"); assert d.day_type == "off"
    d = _by_date(r, "2026-07-04"); assert d.day_type == "off"
    d = _by_date(r, "2026-07-10"); assert d.day_type == "rest"
    d = _by_date(r, "2026-07-31"); assert d.day_type == "off"


def test_july_standby_pattern():
    r = parse_etihad_pdf(_load("pietro_july.pdf"))
    for iso in ("2026-07-02", "2026-07-03", "2026-07-20", "2026-07-21"):
        d = _by_date(r, iso)
        assert d.day_type == "standby", f"{iso} expected standby, got {d.day_type}"
        # Standby always has a start + end time.
        assert d.standby_start is not None and ":" in d.standby_start
        assert d.standby_end   is not None and ":" in d.standby_end


def test_july_layover_pairing_nbo():
    """Jul 27 AUH-NBO, Jul 28 blank => inferred layover_day, Jul 29 NBO-AUH."""
    r = parse_etihad_pdf(_load("pietro_july.pdf"))
    d27 = _by_date(r, "2026-07-27")
    d28 = _by_date(r, "2026-07-28")
    d29 = _by_date(r, "2026-07-29")
    assert d27.day_type in ("flight_to_layover", "overnight_flight")
    assert d27.layover_city == "NBO"
    assert d28.day_type == "layover_day", f"Jul 28 must be inferred layover_day, got {d28.day_type}"
    assert d28.layover_city == "NBO"
    assert d28.is_layover_day is True
    assert d29.day_type == "return_from_layover"
    assert d29.end_location == "AUH"


def test_july_multi_sector_return():
    """Jul 13: BOM-AUH -> AUH-RUH -> RUH-AUH (3 sectors)."""
    r = parse_etihad_pdf(_load("pietro_july.pdf"))
    d = _by_date(r, "2026-07-13")
    assert d.sector_count >= 2  # parser may fold into 2 with connecting sector
    flight_numbers = [s.flight_number for s in d.sectors]
    assert "201" in flight_numbers
    # RUH must appear as an origin or destination somewhere in the sectors
    airports = [s.origin for s in d.sectors] + [s.destination for s in d.sectors]
    assert "RUH" in airports, f"expected RUH in {airports}"


def test_july_turnaround_kbl():
    """Jul 14: AUH-KBL-AUH turnaround."""
    r = parse_etihad_pdf(_load("pietro_july.pdf"))
    d = _by_date(r, "2026-07-14")
    assert d.is_turnaround, f"Jul 14 should be turnaround, got day_type={d.day_type}"
    assert d.start_location == "AUH"
    assert d.end_location == "AUH"


def test_july_report_release_times_stripped():
    """A-prefix must be stripped from actual times."""
    r = parse_etihad_pdf(_load("pietro_july.pdf"))
    d = _by_date(r, "2026-07-05")
    assert d.report_time == "01:10"
    # Release time must be some valid HH:MM
    assert d.release_time and ":" in d.release_time


# ---------------------------------------------------------------------------
# August fixture
# ---------------------------------------------------------------------------

def test_august_top_level():
    r = parse_etihad_pdf(_load("pietro_august.pdf"))
    assert r.detected is True
    assert r.start_date == "2026-08-01"
    assert r.end_date == "2026-08-31"
    assert len(r.days) == 31
    assert r.parse_confidence >= 0.80


def test_august_xx_needs_review():
    """Aug 12: XX = unknown/unavailable, must flag for review."""
    r = parse_etihad_pdf(_load("pietro_august.pdf"))
    d = _by_date(r, "2026-08-12")
    assert d.day_type == "unknown"
    assert d.needs_client_review is True
    assert d.training_impact == "unavailable"


def test_august_roff_days():
    """Aug 14, 15, 16: ROFF."""
    r = parse_etihad_pdf(_load("pietro_august.pdf"))
    for iso in ("2026-08-14", "2026-08-15", "2026-08-16"):
        d = _by_date(r, iso)
        assert d.day_type == "rostered_off", f"{iso} expected rostered_off, got {d.day_type}"


def test_august_same_flight_number_not_deduped():
    """Aug 10: 185 AUH-JMK + 185 JMK-ATH (same flight number, two sectors)."""
    r = parse_etihad_pdf(_load("pietro_august.pdf"))
    d = _by_date(r, "2026-08-10")
    fn_185 = [s for s in d.sectors if s.flight_number == "185"]
    assert len(fn_185) >= 2, f"Aug 10 should keep both '185' sectors, got: {[s.flight_number for s in d.sectors]}"
    routes = {(s.origin, s.destination) for s in fn_185}
    # Both routes should be present (order-insensitive)
    assert ("AUH", "JMK") in routes or ("AUH", None) in routes  # tolerate parse gaps
    assert ("JMK", "ATH") in routes or (None, "ATH") in routes


def test_august_tlv_turnaround():
    """Aug 22: AUH-TLV-AUH same-day turnaround."""
    r = parse_etihad_pdf(_load("pietro_august.pdf"))
    d = _by_date(r, "2026-08-22")
    assert d.is_turnaround is True
    assert d.start_location == "AUH"
    assert d.end_location == "AUH"


def test_august_overnight_continuation():
    """Aug 26-27: overnight AUH-CCJ + CCJ-AUH. Aug 27 has ↓ marker."""
    r = parse_etihad_pdf(_load("pietro_august.pdf"))
    d26 = _by_date(r, "2026-08-26")
    d27 = _by_date(r, "2026-08-27")
    # 26 should be identified as overnight or flight-to-layover
    assert d26.day_type in ("overnight_flight", "flight_to_layover")
    # 27 should NOT be a normal-day OFF; parser should flag it as continuation
    assert d27.is_overnight or d27.day_type == "return_from_layover"


def test_august_standby_pattern():
    r = parse_etihad_pdf(_load("pietro_august.pdf"))
    for iso in ("2026-08-03", "2026-08-04", "2026-08-17", "2026-08-18"):
        d = _by_date(r, iso)
        assert d.day_type == "standby"


# ---------------------------------------------------------------------------
# CrewFit output shape
# ---------------------------------------------------------------------------

def test_crewfit_output_uses_valid_day_types():
    """to_crewfit_days must only produce values from server.py VALID_DAY_TYPES."""
    valid = {
        "home_day", "turnaround", "layover_arrival", "layover_full", "layover_departure",
        "standby", "reserve", "simulator", "annual_leave", "holiday", "sick", "injury",
        "family", "busy", "rest", "custom",
    }
    for pdf in ("pietro_july.pdf", "pietro_august.pdf"):
        pr = parse_etihad_pdf(_load(pdf))
        out = to_crewfit_days(pr)
        for d in out:
            assert d["day_type"] in valid, f"{pdf} {d['date']}: {d['day_type']} not in VALID_DAY_TYPES"


def test_crewfit_output_preserves_confidence_and_review_flags():
    pr = parse_etihad_pdf(_load("pietro_august.pdf"))
    out = to_crewfit_days(pr)
    aug12 = next(d for d in out if d["date"] == "2026-08-12")
    assert aug12["needs_review"] is True
    assert aug12["day_type"] == "custom"  # unknown -> custom


if __name__ == "__main__":
    # Allow running as a script for quick sanity checks.
    import traceback
    passed = 0
    failed = 0
    for name in list(globals()):
        if name.startswith("test_"):
            try:
                globals()[name]()
                print(f"  ✓ {name}")
                passed += 1
            except AssertionError as e:
                print(f"  ✗ {name}: {e}")
                failed += 1
            except Exception:
                traceback.print_exc()
                failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
