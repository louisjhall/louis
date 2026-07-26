"""Automated tests for the Emirates parser against Joel July fixture."""
import sys
from pathlib import Path
sys.path.insert(0, "/app/backend")
from parsers.emirates import detect_emirates, parse_emirates_pdf, to_crewfit_days

FIX = Path("/app/backend/tests/fixtures/joel_july.pdf")


def _r():
    return parse_emirates_pdf(FIX.read_bytes())


def _by_date(r, iso):
    for d in r.days:
        if d.date == iso:
            return d
    raise AssertionError(f"{iso} not found in {[d.date for d in r.days]}")


def test_detection():
    assert detect_emirates(FIX.read_bytes()) is True


def test_top_level():
    r = _r()
    assert r.detected
    assert r.month == 7
    assert r.year == 2026
    assert r.crew_name and "joel" in r.crew_name.lower()
    # Should have 31 days (July)
    dates = [d.date for d in r.days]
    assert "2026-07-01" in dates
    assert "2026-07-31" in dates


def test_day_off_days():
    r = _r()
    for iso in ("2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"):
        d = _by_date(r, iso)
        assert d.auto_label == "DAY_OFF", f"{iso}: {d.auto_label}"
        assert d.training_colour == "green"


def test_jul5_turnaround():
    r = _r()
    d = _by_date(r, "2026-07-05")
    assert d.flight_number == "EK508"
    assert d.route_airports == ["DXB", "BOM", "DXB"]
    assert d.is_turnaround
    assert d.auto_label == "TURNAROUND_DUTY"
    assert d.training_colour == "red"
    assert d.pickup_time == "13:45"


def test_jul7_sim():
    r = _r()
    d = _by_date(r, "2026-07-07")
    assert d.auto_label == "SIM_TRAINING"
    assert d.day_type == "sim_training"
    assert d.duty_start_local == "15:00"
    assert d.duty_end_local == "21:00"
    assert d.training_colour == "amber"


def test_jul13_overnight_turnaround():
    r = _r()
    d = _by_date(r, "2026-07-13")
    assert d.flight_number == "EK524"
    assert d.route_airports == ["DXB", "HYD", "DXB"]
    assert d.is_turnaround
    assert d.arrival_next_day
    assert d.auto_label == "OVERNIGHT_TURNAROUND"
    assert d.pickup_time == "19:35"


def test_jul14_post_night_recovery():
    r = _r()
    d = _by_date(r, "2026-07-14")
    # Rest day following an overnight turnaround
    assert d.auto_label in ("POST_NIGHT_RECOVERY", "REST_DAY")
    assert d.training_colour in ("red", "amber")


def test_jul20_long_haul_outbound():
    r = _r()
    d = _by_date(r, "2026-07-20")
    assert d.flight_number == "EK324"
    assert d.route_airports == ["DXB", "ICN"]
    assert d.auto_label == "LONG_HAUL_OUTBOUND"
    assert d.training_colour == "red"
    assert d.pickup_time == "03:05"
    assert d.hotel_name and d.hotel_name.lower() == "sofitel"
    assert d.timezone_note and "ICN" in d.timezone_note


def test_jul21_layover_rest_in_icn():
    r = _r()
    d = _by_date(r, "2026-07-21")
    assert d.auto_label == "LAYOVER_REST_DAY"
    assert d.training_colour == "amber"
    assert d.equipment_assumption == "hotel_or_bodyweight_only"
    assert d.needs_client_review


def test_jul22_long_haul_return():
    r = _r()
    d = _by_date(r, "2026-07-22")
    assert d.flight_number == "EK325"
    assert d.route_airports == ["ICN", "DXB"]
    assert d.auto_label == "LONG_HAUL_RETURN"
    assert d.arrival_next_day
    assert d.training_colour == "red"


def test_jul23_post_long_haul_recovery():
    r = _r()
    d = _by_date(r, "2026-07-23")
    assert d.auto_label == "POST_LONG_HAUL_RECOVERY"
    assert d.training_colour in ("red", "amber")


def test_jul27_long_haul_outbound_bcn():
    r = _r()
    d = _by_date(r, "2026-07-27")
    assert d.flight_number == "EK255"
    assert d.route_airports == ["DXB", "BCN"]
    assert d.auto_label == "LONG_HAUL_OUTBOUND"
    assert d.pickup_time == "00:55"


def test_jul28_multi_city_sector():
    r = _r()
    d = _by_date(r, "2026-07-28")
    assert d.route_airports == ["BCN", "MEX"]
    assert d.auto_label == "LONG_HAUL_SECTOR"
    assert d.training_colour == "red"
    assert d.hotel_name and d.hotel_name.lower() == "marriott"


def test_jul29_multi_city_return_partial():
    r = _r()
    d = _by_date(r, "2026-07-29")
    assert d.route_airports == ["MEX", "BCN"]
    assert d.auto_label == "LONG_HAUL_SECTOR"


def test_jul30_layover_rest_in_bcn():
    r = _r()
    d = _by_date(r, "2026-07-30")
    assert d.auto_label == "LAYOVER_REST_DAY"
    assert d.equipment_assumption == "hotel_or_bodyweight_only"


def test_jul31_long_haul_return_bcn():
    r = _r()
    d = _by_date(r, "2026-07-31")
    assert d.route_airports == ["BCN", "DXB"]
    assert d.auto_label == "LONG_HAUL_RETURN"
    assert d.arrival_next_day


def test_crewfit_shape_valid_day_types():
    valid = {
        "home_day", "turnaround", "layover_arrival", "layover_full", "layover_departure",
        "standby", "reserve", "simulator", "annual_leave", "holiday", "sick", "injury",
        "family", "busy", "rest", "custom",
    }
    for d in to_crewfit_days(_r()):
        assert d["day_type"] in valid, f"{d['date']}: {d['day_type']}"
