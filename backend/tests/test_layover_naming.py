"""
tests/test_layover_naming.py — Iter 102

Deterministic tests confirming that workouts on layover days receive titles
that include the detected destination, respect hotel-gym state, degrade
gracefully when the destination is unclear, and never touch coach-edited
titles.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from feature_layover_naming import apply_layover_naming  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _roster(days):
    return {"days": days}


def _day(date, day_type="Layover", layover_city=None, flights=None,
         hotel=None):
    d = {"date": date, "day_type": day_type}
    if layover_city is not None:
        d["layover_city"] = layover_city
    if flights is not None:
        d["flights"] = flights
    if hotel is not None:
        d["hotel"] = hotel
    return d


def _wkt(date, title, focus=None, **extra):
    w = {"date": date, "title": title}
    if focus is not None:
        w["focus"] = focus
    w.update(extra)
    return w


# ---------------------------------------------------------------------------
# 1. HAPPY PATH — DESTINATION FROM layover_city (IATA)
# ---------------------------------------------------------------------------

def test_iata_from_layover_city_strength_confirmed_gym():
    roster = _roster([
        _day("2026-08-01", day_type="Layover", layover_city="ICN",
             hotel={"gym_available": True}),
    ])
    workouts = [_wkt("2026-08-01", "Hotel Gym Strength", focus="strength")]

    stats = apply_layover_naming(workouts, roster)

    assert stats["renamed"] == 1
    assert workouts[0]["title"] == "ICN Layover Hotel Gym Strength"
    lc = workouts[0]["layover_context"]
    assert lc["destination"] == "ICN"
    assert lc["hotel_gym_state"] == "confirmed"
    assert lc["needs_destination_review"] is False
    assert "ICN" in lc["client_reason"]
    assert "hotel gym" in lc["client_reason"].lower()


def test_iata_from_layover_city_bodyweight_when_gym_unavailable():
    roster = _roster([
        _day("2026-08-02", day_type="Layover", layover_city="BCN",
             hotel={"gym_available": False}),
    ])
    workouts = [_wkt("2026-08-02", "Bodyweight Mobility", focus="mobility")]

    apply_layover_naming(workouts, roster)

    # mobility takes precedence over the hotel/bodyweight signal
    assert workouts[0]["title"] == "BCN Layover Mobility"
    assert workouts[0]["layover_context"]["destination"] == "BCN"
    assert workouts[0]["layover_context"]["hotel_gym_state"] == "unavailable"


def test_recovery_focus_becomes_layover_recovery():
    roster = _roster([
        _day("2026-08-03", day_type="Layover", layover_city="NBO",
             hotel={"gym_available": True}),
    ])
    workouts = [_wkt("2026-08-03", "Recovery Session", focus="recovery")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "NBO Layover Recovery"


def test_stretch_focus_maps_to_mobility():
    roster = _roster([
        _day("2026-08-04", day_type="Layover", layover_city="CMB"),
    ])
    workouts = [_wkt("2026-08-04", "Stretch & Reset", focus="stretch")]

    apply_layover_naming(workouts, roster)

    # No hotel data → unknown gym state, but mobility is location-independent.
    assert workouts[0]["title"] == "CMB Layover Mobility"


# ---------------------------------------------------------------------------
# 2. HOTEL GYM STATE VARIANTS
# ---------------------------------------------------------------------------

def test_unknown_hotel_gym_uses_hotel_slash_bodyweight():
    roster = _roster([
        _day("2026-08-05", day_type="Layover", layover_city="ICN"),
    ])
    workouts = [_wkt("2026-08-05", "Hotel Gym Strength", focus="strength")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "ICN Layover Hotel/Bodyweight Strength"
    lc = workouts[0]["layover_context"]
    assert lc["hotel_gym_state"] == "unknown"
    assert "hotel/bodyweight" in lc["client_reason"].lower()


def test_unknown_hotel_gym_generic_session():
    roster = _roster([
        _day("2026-08-06", day_type="Layover", layover_city="MEX"),
    ])
    # Vague title / focus — should default to Hotel/Bodyweight Session
    workouts = [_wkt("2026-08-06", "Session", focus="training")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "MEX Layover Hotel/Bodyweight Session"


def test_confirmed_gym_generic_becomes_hotel_gym_session():
    roster = _roster([
        _day("2026-08-07", day_type="Layover", layover_city="DXB",
             hotel={"gym_available": True}),
    ])
    workouts = [_wkt("2026-08-07", "Session", focus="training")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "DXB Layover Hotel Gym Session"


# ---------------------------------------------------------------------------
# 3. DESTINATION FALLBACK CHAIN — flight.to → city name
# ---------------------------------------------------------------------------

def test_falls_back_to_flight_destination_when_city_missing():
    roster = _roster([
        _day("2026-08-08", day_type="Layover",
             flights=[{"number": "EK4", "from": "LHR", "to": "SIN"}]),
    ])
    workouts = [_wkt("2026-08-08", "Bodyweight Mobility", focus="mobility")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "SIN Layover Mobility"


def test_falls_back_to_short_city_name_when_no_iata():
    roster = _roster([
        _day("2026-08-09", day_type="Layover", layover_city="Rome"),
    ])
    workouts = [_wkt("2026-08-09", "Recovery Session", focus="recovery")]

    apply_layover_naming(workouts, roster)

    # short city name is uppercased and used verbatim
    assert workouts[0]["title"] == "ROME Layover Recovery"


# ---------------------------------------------------------------------------
# 4. FALLBACK RULE — destination unclear
# ---------------------------------------------------------------------------

def test_unclear_destination_generic_and_flag_review():
    roster = _roster([
        _day("2026-08-10", day_type="Layover"),  # no city, no flights
    ])
    workouts = [_wkt("2026-08-10", "Hotel Gym Strength", focus="strength")]

    stats = apply_layover_naming(workouts, roster)

    assert workouts[0]["title"].startswith("Layover ")  # NO destination prefix
    assert "Layover" in workouts[0]["title"]
    lc = workouts[0]["layover_context"]
    assert lc["destination"] is None
    assert lc["needs_destination_review"] is True
    assert stats["needs_review"] == 1


def test_unclear_destination_recovery_stays_recovery():
    roster = _roster([
        _day("2026-08-11", day_type="Layover"),
    ])
    workouts = [_wkt("2026-08-11", "Recovery Walk", focus="recovery")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "Layover Recovery"


def test_long_city_name_is_rejected_as_dest_and_flagged():
    """Layover_city that's too long to fit in the title tightly falls
    through to needs_review — better to be honest than to slap 'BUENOS_AIRES'
    into the title."""
    roster = _roster([
        _day("2026-08-12", day_type="Layover", layover_city="Buenos Aires"),
    ])
    workouts = [_wkt("2026-08-12", "Hotel Gym Strength", focus="strength")]

    apply_layover_naming(workouts, roster)

    lc = workouts[0]["layover_context"]
    assert lc["destination"] is None
    assert lc["needs_destination_review"] is True


# ---------------------------------------------------------------------------
# 5. NON-LAYOVER DAYS ARE UNTOUCHED
# ---------------------------------------------------------------------------

def test_non_layover_day_title_untouched():
    roster = _roster([
        _day("2026-08-13", day_type="Home"),
    ])
    workouts = [_wkt("2026-08-13", "Full Body Strength", focus="strength")]

    stats = apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "Full Body Strength"
    assert "layover_context" not in workouts[0]
    assert stats["renamed"] == 0


def test_turnaround_day_untouched():
    roster = _roster([
        _day("2026-08-14", day_type="Turnaround"),
    ])
    workouts = [_wkt("2026-08-14", "Full Body Strength", focus="strength")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "Full Body Strength"


def test_rest_day_workout_untouched_even_on_layover():
    """If a workout has focus='rest' we skip it — a rest card should not
    be renamed as a layover workout."""
    roster = _roster([
        _day("2026-08-15", day_type="Layover", layover_city="ICN"),
    ])
    workouts = [_wkt("2026-08-15", "Rest Day", focus="rest")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "Rest Day"


# ---------------------------------------------------------------------------
# 6. COACH MANUAL EDITS ARE RESPECTED
# ---------------------------------------------------------------------------

def test_coach_edited_title_not_overwritten():
    roster = _roster([
        _day("2026-08-16", day_type="Layover", layover_city="ICN",
             hotel={"gym_available": True}),
    ])
    workouts = [_wkt("2026-08-16", "Louis Special Session",
                     focus="strength", title_manually_edited_by_coach=True)]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"] == "Louis Special Session"


# ---------------------------------------------------------------------------
# 7. CROSS-AIRLINE APPLICATION
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("airline", ["Emirates", "Etihad", "British Airways", None])
def test_naming_applies_regardless_of_airline(airline):
    roster = _roster([
        _day("2026-08-17", day_type="Layover", layover_city="ICN"),
    ])
    workouts = [_wkt("2026-08-17", "Hotel Gym Strength", focus="strength")]

    apply_layover_naming(workouts, roster, airline=airline)

    assert workouts[0]["title"] == "ICN Layover Hotel/Bodyweight Strength"
    if airline:
        assert airline in workouts[0]["layover_context"]["coach_reason"]


# ---------------------------------------------------------------------------
# 8. DAY-LABEL VARIANTS
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("day_type", [
    "Layover", "layover", "LAYOVER",
    "Layover Arrival Day", "Layover Full Day", "Layover Departure Day",
    "Long_haul_layover", "layover_rest_day",
])
def test_various_layover_labels_are_detected(day_type):
    roster = _roster([
        _day("2026-08-18", day_type=day_type, layover_city="ICN"),
    ])
    workouts = [_wkt("2026-08-18", "Hotel Gym Strength", focus="strength")]

    apply_layover_naming(workouts, roster)

    assert workouts[0]["title"].startswith("ICN Layover")


# ---------------------------------------------------------------------------
# 9. IDEMPOTENCY — repeat calls don't stack prefixes
# ---------------------------------------------------------------------------

def test_repeat_apply_does_not_stack_prefix():
    roster = _roster([
        _day("2026-08-19", day_type="Layover", layover_city="ICN",
             hotel={"gym_available": True}),
    ])
    workouts = [_wkt("2026-08-19", "Hotel Gym Strength", focus="strength")]

    apply_layover_naming(workouts, roster)
    first_title = workouts[0]["title"]
    apply_layover_naming(workouts, roster)
    second_title = workouts[0]["title"]

    # After two calls, title still reads "ICN Layover Hotel Gym Strength"
    # (no "ICN Layover ICN Layover ..." double-prefix).
    assert first_title == second_title
    assert workouts[0]["title"].count("Layover") == 1


# ---------------------------------------------------------------------------
# 10. STATS DICT
# ---------------------------------------------------------------------------

def test_stats_counts_renamed_and_needs_review():
    roster = _roster([
        _day("2026-08-20", day_type="Layover", layover_city="ICN"),
        _day("2026-08-21", day_type="Layover"),  # no dest
        _day("2026-08-22", day_type="Home"),      # skip
    ])
    workouts = [
        _wkt("2026-08-20", "Hotel Gym Strength", focus="strength"),
        _wkt("2026-08-21", "Hotel Gym Strength", focus="strength"),
        _wkt("2026-08-22", "Full Body", focus="strength"),
    ]

    stats = apply_layover_naming(workouts, roster)

    assert stats["renamed"] == 2
    assert stats["needs_review"] == 1
