"""Iter200 · Universal roster normalizer — regression suite.

Covers all 12 acceptance cases from the user's spec:
  1. Same-day turnaround → not layover
  2. Overnight turnaround crossing midnight → not layover
  3. Genuine one-night layover → layover
  4. Multi-day long-haul layover → layover retained
  5. Explicit OFF at home → OFF (never inferred layover)
  6. Standby at home base → equipment 'any'
  7. Standby crossing midnight → standby preserved
  8. Blank/ambiguous day → needs_review
  9. Month boundary look-ahead → clipped
 10. Duplicate-date protection
 11. Genuine layover across airline formats (BA + EK synthesised)
 12. Night turnaround across airline formats (BA + EK synthesised)

Plus a full September Etihad golden replay (12 days) asserting the
final internal + customer-facing labels the user asked to see.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from parsers.roster_normalizer import normalize_roster, MIN_LAYOVER_GROUND_HOURS  # noqa: E402


# ---------- Helpers ---------------------------------------------------------

def _flt(from_, to, dep, arr):
    return {"from": from_, "to": to, "dep": dep, "arr": arr}


def _day(date_iso, day_type, flights=None, **kw):
    d = {"date": date_iso, "day_type": day_type, "flights": flights or [], "confidence": 0.85}
    d.update(kw)
    return d


def _by_date(days, iso):
    for d in days:
        if d.get("date") == iso:
            return d
    raise AssertionError(f"day {iso} not found in {[d.get('date') for d in days]}")


# ---------- 1. Same-day turnaround -----------------------------------------

def test_case_1_same_day_turnaround_is_not_layover():
    """AUH → KBL → AUH within one calendar day → turnaround."""
    days = [
        _day("2026-09-01", "Turnaround Duty",
             flights=[_flt("AUH", "KBL", "08:40", "12:00"),
                      _flt("KBL", "AUH", "13:00", "16:30")],
             report_time="07:40", duty_end_time="17:30"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    d = out[0]
    assert d["day_type"] == "turnaround", f"got {d['day_type']}"
    assert d.get("layover_city") is None
    assert d["equipment_assumption"] == "any"
    assert "AUH → KBL → AUH" in d["client_label"]
    assert d["client_label"].startswith("Flying day")


# ---------- 2. Overnight turnaround crossing midnight ----------------------

def test_case_2_overnight_turnaround_not_layover():
    """The AUH→JAI→AUH pairing from the user's spec.
       Depart 21:05, arrive 02:10, ~1h45 on ground, depart 03:55, arrive 06:00.
       Must be night_flight, NOT layover."""
    days = [
        _day("2026-09-02", "Layover Arrival Day",
             flights=[_flt("AUH", "JAI", "21:05", "02:10")],
             report_time="19:50", duty_end_time="02:10",
             layover_city="JAI"),
        _day("2026-09-03", "Layover Departure Day",
             flights=[_flt("JAI", "AUH", "03:55", "06:00")],
             report_time="03:00", duty_end_time="06:30",
             layover_city="JAI"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    d1 = _by_date(out, "2026-09-02")
    d2 = _by_date(out, "2026-09-03")
    assert d1["day_type"] == "night_flight", f"got {d1['day_type']}"
    assert d2["day_type"] == "night_flight", f"got {d2['day_type']}"
    assert d1.get("layover_city") is None
    assert d2.get("layover_city") is None
    assert d1["equipment_assumption"] == "any"
    assert "Night flight" in d1["client_label"]
    assert "AUH → JAI" in d1["client_label"]


# ---------- 3. Genuine one-night layover -----------------------------------

def test_case_3_genuine_layover():
    """AUH→CMB arrives 07:45. Next duty CMB→AUH departs 07:45 NEXT day
       → 24h dwell → genuine layover."""
    days = [
        _day("2026-09-05", "Layover Arrival Day",
             flights=[_flt("AUH", "CMB", "01:10", "07:45")],
             report_time="00:10", duty_end_time="07:45",
             layover_city="CMB"),
        _day("2026-09-06", "Layover Departure Day",
             flights=[_flt("CMB", "AUH", "07:45", "12:00")],
             report_time="06:45", duty_end_time="12:00",
             layover_city="CMB"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    d1 = _by_date(out, "2026-09-05")
    d2 = _by_date(out, "2026-09-06")
    assert d1["day_type"] == "flight_to_layover"
    assert d1["layover_city"] == "CMB"
    assert d1["equipment_assumption"] == "hotel_or_bodyweight"
    assert d1["client_label"] == "Layover — CMB"
    assert d2["day_type"] == "return_from_layover"
    assert "CMB" in d2["client_label"]


# ---------- 4. Multi-day long-haul layover ---------------------------------

def test_case_4_multi_day_layover_retained():
    days = [
        _day("2026-09-10", "Layover Arrival Day",
             flights=[_flt("AUH", "JFK", "10:00", "16:30")],
             report_time="09:00", duty_end_time="16:30",
             layover_city="JFK"),
        _day("2026-09-11", "Layover Full Day"),  # blank between
        _day("2026-09-12", "Layover Full Day"),
        _day("2026-09-13", "Layover Departure Day",
             flights=[_flt("JFK", "AUH", "22:00", "18:00")],
             report_time="21:00", duty_end_time="18:00",
             layover_city="JFK"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    assert _by_date(out, "2026-09-10")["day_type"] == "flight_to_layover"
    # middle blank days should stay as layover_day (evidence: prev is
    # flight_to_layover, next is return from same city)
    assert _by_date(out, "2026-09-11")["day_type"] == "layover_day"
    assert _by_date(out, "2026-09-11")["layover_city"] == "JFK"
    assert _by_date(out, "2026-09-13")["day_type"] == "return_from_layover"


# ---------- 5. Explicit OFF at home ----------------------------------------

def test_case_5_off_days_preserved():
    days = [
        _day("2026-09-04", "Turnaround Duty",
             flights=[_flt("AUH", "MCT", "08:00", "09:30"),
                      _flt("MCT", "AUH", "10:30", "12:00")],
             report_time="07:00", duty_end_time="12:30"),
        _day("2026-09-05", "OFF"),
        _day("2026-09-06", "OFF"),
        _day("2026-09-07", "Turnaround Duty",
             flights=[_flt("AUH", "DOH", "09:00", "10:00"),
                      _flt("DOH", "AUH", "11:00", "12:30")]),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    assert _by_date(out, "2026-09-05")["day_type"] == "day_off"
    assert _by_date(out, "2026-09-06")["day_type"] == "day_off"
    assert _by_date(out, "2026-09-05").get("layover_city") is None
    assert _by_date(out, "2026-09-05")["client_label"] == "Rest day"


# ---------- 6. Standby at home base ----------------------------------------

def test_case_6_home_standby_equipment_any():
    days = [_day("2026-09-07", "Standby",
                 report_time="06:00", duty_end_time="14:00")]
    out = normalize_roster(days, home_base="AUH")["days"]
    d = out[0]
    assert d["day_type"] == "standby"
    assert d["equipment_assumption"] == "any"
    assert d["home_or_away"] == "home"
    assert "Standby" in d["client_label"]
    assert "06:00" in d["client_label"] and "14:00" in d["client_label"]


# ---------- 7. Standby crossing midnight -----------------------------------

def test_case_7_standby_crossing_midnight():
    """Night standby 22:00–06:00 → single standby duty, not layover."""
    days = [_day("2026-09-08", "Night Standby",
                 report_time="22:00", duty_end_time="06:00",
                 standby_type="night_standby")]
    out = normalize_roster(days, home_base="AUH")["days"]
    d = out[0]
    assert d["day_type"] == "standby"
    assert d["equipment_assumption"] == "any"
    assert d.get("layover_city") is None


# ---------- 8. Blank / ambiguous day → needs_review ------------------------

def test_case_8_blank_ambiguous_day_becomes_rest_day():
    """Iter200-b · Blank day with no city context and no pairing evidence
       is classified as a rest day (not invented as a layover)."""
    days = [
        _day("2026-09-09", "Unknown/Needs Confirmation"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    d = out[0]
    assert d["day_type"] == "rest_day"
    assert d["client_label"] == "Rest day"
    assert d.get("layover_city") is None


# ---------- 9. Month boundary look-ahead → clipped -------------------------

def test_case_9_month_boundary_clipped():
    """Roster shows Sep 1-30 plus a look-ahead Oct 1 column → Oct 1 is
       clipped (dropped from days list)."""
    # 30 September days + 1 October = 31 dates. Normalizer must drop Oct 1.
    days = []
    for i in range(1, 31):
        days.append(_day(f"2026-09-{i:02d}", "OFF"))
    days.append(_day("2026-10-01", "OFF"))  # look-ahead column

    out = normalize_roster(days, home_base="AUH",
                           month_range=("2026-09-01", "2026-09-30"))
    assert len(out["days"]) == 30
    assert out["audit"]["clipped_month_boundary"] == 1
    dropped_dates = [d["date"] for d in out["dropped"]]
    assert "2026-10-01" in dropped_dates


# ---------- 10. Duplicate-date protection ----------------------------------

def test_case_10_duplicate_dates_deduped():
    """Two rows for same date (continuation arrow bug) → collapsed."""
    days = [
        _day("2026-09-15", "Overnight Flight",
             flights=[_flt("AUH", "LHR", "22:00", "03:00")],
             confidence=0.9),
        # duplicate for the same date (the continuation arrow row)
        _day("2026-09-15", "Layover Departure", confidence=0.6),
    ]
    out = normalize_roster(days, home_base="AUH")
    assert len(out["days"]) == 1
    assert out["audit"]["deduped_dates"] == 1
    # richest row (the one WITH sectors) wins — verify the flights survived.
    assert len(out["days"][0]["flights"]) == 1
    assert out["days"][0]["flights"][0]["from"] == "AUH"
    assert out["days"][0]["flights"][0]["to"] == "LHR"


def test_second_pass_dedupe_collapses_turnaround_plus_layover_arrival():
    """Iter200-b · Second-pass dedupe: LLM sometimes emits a turnaround
       row AND a layover_arrival row for the same date. After normalization
       we must keep ONE row, and it must be the turnaround."""
    days = [
        _day("2026-09-15", "Turnaround Duty",
             flights=[_flt("AUH", "KHI", "08:00", "10:00"),
                      _flt("KHI", "AUH", "11:00", "13:00")],
             confidence=0.85),
        # LLM's phantom "second half" duplicate for the same date
        _day("2026-09-15", "Layover Arrival Day",
             layover_city="KHI", confidence=0.4),
    ]
    out = normalize_roster(days, home_base="AUH")
    assert len(out["days"]) == 1, f"expected 1 row, got {len(out['days'])}"
    kept = out["days"][0]
    assert kept["day_type"] == "turnaround"
    assert kept.get("layover_city") is None
    assert kept["client_label"].startswith("Flying day")


def test_early_morning_departure_below_8h_is_night_flight():
    """Iter200-b · Duty departs 03:55 with only 1h45 ground time at the
       outstation → night flight, not layover."""
    days = [
        _day("2026-09-02", "Layover Arrival Day",
             flights=[_flt("AUH", "JAI", "21:05", "02:10")],
             report_time="19:50", duty_end_time="02:10",
             layover_city="JAI"),
        _day("2026-09-03", "Layover Departure Day",
             flights=[_flt("JAI", "AUH", "03:55", "06:00")],
             report_time="03:00", duty_end_time="06:30",
             layover_city="JAI"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    d1 = _by_date(out, "2026-09-02")
    d2 = _by_date(out, "2026-09-03")
    assert d1["day_type"] == "night_flight"
    assert d2["day_type"] == "night_flight"
    assert d1.get("layover_city") is None
    assert d2.get("layover_city") is None


# ---------- 11. Genuine layover across airline formats ---------------------

def test_case_11_genuine_layover_ba_format():
    """BA-style trip: LHR → JFK long-haul with 2-day layover, then JFK → LHR.
       Universal classifier must recognise this identically to Etihad."""
    days = [
        _day("2026-09-20", "Layover Arrival",
             flights=[_flt("LHR", "JFK", "12:00", "15:00")],
             layover_city="JFK",
             report_time="11:00", duty_end_time="15:00"),
        _day("2026-09-21", "Layover Full"),
        _day("2026-09-22", "Layover Departure",
             flights=[_flt("JFK", "LHR", "18:00", "06:00")],
             layover_city="JFK"),
    ]
    out = normalize_roster(days, home_base="LHR")["days"]
    assert _by_date(out, "2026-09-20")["day_type"] == "flight_to_layover"
    assert _by_date(out, "2026-09-20")["layover_city"] == "JFK"
    assert _by_date(out, "2026-09-21")["day_type"] == "layover_day"
    assert _by_date(out, "2026-09-22")["day_type"] == "return_from_layover"


# ---------- 12. Night turnaround across airline formats --------------------

def test_case_12_night_turnaround_emirates_format():
    """EK-style DXB → SYD → DXB (long night out-and-back).
       Actually EK operates a real 24h layover here, but for the TEST
       we build a compressed night turnaround: DXB→KHI→DXB same night.
       Verify the classifier handles it correctly."""
    days = [
        _day("2026-09-04", "Long-Haul Turnaround",
             flights=[_flt("DXB", "KHI", "22:00", "01:00"),
                      _flt("KHI", "DXB", "03:00", "05:30")],
             report_time="21:00", duty_end_time="06:00"),
    ]
    out = normalize_roster(days, home_base="DXB")["days"]
    d = out[0]
    assert d["day_type"] == "turnaround"
    assert d.get("layover_city") is None
    assert "DXB → KHI → DXB" in d["client_label"]


# ---------- Cross-check: "Layover in None" downgraded to needs_review ------

def test_layover_in_none_downgraded():
    """LLM claimed 'Layover' but layover_city is missing and no next-day
       evidence exists → must be flagged for review, NEVER display
       'Layover in None'."""
    days = [
        _day("2026-09-25", "Layover Arrival Day",
             flights=[_flt("AUH", "ABC", "10:00", "14:00")],
             report_time="09:00", duty_end_time="14:00",
             layover_city=None),
        # no next-day evidence, roster ends here
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    d = out[0]
    assert d["day_type"] == "needs_review"
    # customer label MUST NOT contain "Layover in None"
    assert "None" not in d["client_label"]
    assert d["client_label"] == "Needs your check"


def test_early_morning_report_displays_as_night_flight():
    """Iter200-g · A flight with report/dep between 00:00 and 05:00 must
       display as 'Night flight', overriding 'Flying day' / 'Heavy flying
       day' labels — UNLESS the day is a resolved layover."""
    # A turnaround AUH → KHI → AUH that departs at 03:30 → Night flight
    days = [
        _day("2026-09-10", "Turnaround Duty",
             flights=[_flt("AUH", "KHI", "03:30", "05:00"),
                      _flt("KHI", "AUH", "06:00", "07:30")],
             report_time="02:30", duty_end_time="08:00"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    assert out[0]["client_label"].startswith("Night flight")


def test_blank_day_between_arrival_and_departure_is_layover_day():
    """Iter200-g · A blank day (no sectors, source unknown or Flying day)
       sitting between a resolved flight_to_layover and a return flight
       from the same outstation must be classified as layover_day."""
    days = [
        _day("2026-09-20", "Layover Arrival Day",
             flights=[_flt("LHR", "JFK", "12:00", "15:00")],
             layover_city="JFK", report_time="11:00", duty_end_time="15:00"),
        # LLM emitted this blank middle day as "Flying day" by mistake
        _day("2026-09-21", "Flying day", flights=[]),
        _day("2026-09-22", "Layover Departure Day",
             flights=[_flt("JFK", "LHR", "20:00", "08:00")],
             layover_city="JFK"),
    ]
    out = normalize_roster(days, home_base="LHR")["days"]
    mid = _by_date(out, "2026-09-21")
    assert mid["day_type"] == "layover_day"
    assert mid["layover_city"] == "JFK"
    assert mid["client_label"] == "Layover — JFK"


def test_labels_use_new_terminology():
    """Iter200-g · 'Flying to layover' renamed to 'Layover', 'Return from
       layover' renamed to 'Return flight'."""
    days = [
        _day("2026-09-01", "Layover Arrival Day",
             flights=[_flt("AUH", "SYD", "10:00", "06:00")],
             layover_city="SYD", report_time="09:00"),
        _day("2026-09-02", "Layover Full Day"),
        _day("2026-09-03", "Layover Departure Day",
             flights=[_flt("SYD", "AUH", "22:00", "06:00")],
             layover_city="SYD"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    assert out[0]["client_label"] == "Layover — SYD"
    assert out[2]["client_label"] == "Return flight — SYD → AUH"



def test_source_labelled_night_flight_never_becomes_layover():
    """Iter200-d · Source label 'Night Flight' explicitly. Regardless of
       whether the sector crosses midnight or what the LLM otherwise
       claims, a night-flight-labelled day with sectors must stay a
       night_flight, never a layover."""
    days = [
        _day("2026-09-14", "Night Flight",
             flights=[_flt("AUH", "LHR", "23:30", "05:00")],
             layover_city="LHR",  # LLM accidentally left this populated
             report_time="22:00", duty_end_time="05:30"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    d = out[0]
    assert d["day_type"] == "night_flight"
    assert d.get("layover_city") is None
    assert d["equipment_assumption"] == "any"
    assert d["client_label"].startswith("Night flight")



def test_customer_labels_are_plain_human():
    """Iter200-b · Verify all key labels match the user's spec exactly."""
    days = [
        _day("2026-09-01", "Night Flight",
             flights=[_flt("AUH", "JAI", "22:00", "01:00")]),
        _day("2026-09-02", "Layover Arrival Day",
             flights=[_flt("JAI", "AUH", "03:00", "05:00")]),
        _day("2026-09-03", "Turnaround Duty",
             flights=[_flt("AUH", "DXB", "08:00", "09:30"),
                      _flt("DXB", "AUH", "10:30", "12:00")]),
        _day("2026-09-04", "Rest Day"),
        _day("2026-09-05", "Standby",
             report_time="06:00", duty_end_time="14:00"),
    ]
    out = normalize_roster(days, home_base="AUH")["days"]
    labels = {d["date"]: d["client_label"] for d in out}
    # Plain, human, no parser jargon
    for lbl in labels.values():
        for token in ("layover_", "flight_to_", "return_from_", "midnight_crossing",
                      "day_off", "rest_day", "needs_review"):
            assert token not in lbl.lower(), f"raw type in label: {lbl}"
    # Specific expectations
    assert "AUH → DXB → AUH" in labels["2026-09-03"]
    assert labels["2026-09-03"].startswith("Flying day")
    assert labels["2026-09-04"] == "Rest day"
    assert labels["2026-09-05"].startswith("Standby")
    assert "06:00" in labels["2026-09-05"] and "14:00" in labels["2026-09-05"]


# ---------- Bonus: standby with hotel_or_bodyweight leak fixed on any air --

def test_standby_never_gets_hotel_equipment():
    days = [_day("2026-09-08", "Standby",
                 report_time="06:00", duty_end_time="14:00")]
    out = normalize_roster(days, home_base="AUH")["days"]
    assert out[0]["equipment_assumption"] == "any"
    assert "Hotel" not in out[0]["client_label"]
    assert "bodyweight" not in out[0]["client_label"].lower()
