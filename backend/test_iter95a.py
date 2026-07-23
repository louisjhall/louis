"""Iter 95a smoke tests — weekly review dedupe + dual-session eligibility.

Run:
    cd /app/backend && python3 -m pytest test_iter95a.py -v
"""
from __future__ import annotations
import pytest
from feature_dual_session import evaluate_day, _airport_gap_hours


def _prof(ft="short_haul"): return {"flying_type": ft}


def test_gap_hours_basic():
    flights = [{"dep": "06:00", "arr": "07:30"}, {"dep": "11:00", "arr": "12:30"}]
    assert _airport_gap_hours(flights) == 3.5


def test_gap_hours_over_midnight():
    flights = [{"dep": "22:00", "arr": "23:30"}, {"dep": "03:00", "arr": "04:30"}]
    # 23:30 → 03:00 = 3.5h
    assert _airport_gap_hours(flights) == 3.5


def test_eligible_short_haul_with_gap_and_hotel():
    day = {
        "date": "2026-07-24",
        "day_type": "Short-haul",
        "duty_hours": 9,
        "hotel_id": "h1",
        "flights": [{"dep": "06:00", "arr": "07:30"}, {"dep": "11:30", "arr": "13:00"}],
    }
    res = evaluate_day(day, None, _prof("short_haul"))
    assert res["eligible"] is True
    assert res["gap_hours"] == 4.0
    assert res["pattern"] == "airport_activation_plus_hotel"


def test_ineligible_long_haul():
    day = {
        "date": "2026-07-24", "day_type": "Long-haul", "duty_hours": 12,
        "flights": [{"dep": "06:00", "arr": "18:00"}],
    }
    res = evaluate_day(day, None, _prof("long_haul"))
    assert res["eligible"] is False


def test_ineligible_off_day():
    day = {"date": "2026-07-24", "day_type": "Home Day", "flights": []}
    res = evaluate_day(day, None, _prof("short_haul"))
    assert res["eligible"] is False


def test_ineligible_duty_too_long():
    day = {"date": "2026-07-24", "day_type": "Short-haul", "duty_hours": 13,
           "hotel_id": "h1",
           "flights": [{"dep": "06:00", "arr": "07:30"}, {"dep": "11:30", "arr": "13:00"}]}
    res = evaluate_day(day, None, _prof("short_haul"))
    assert res["eligible"] is False


def test_ineligible_no_hotel_no_layover():
    day = {"date": "2026-07-24", "day_type": "Short-haul", "duty_hours": 8,
           "flights": [{"dep": "06:00", "arr": "07:30"}, {"dep": "11:30", "arr": "13:00"}]}
    res = evaluate_day(day, None, _prof("short_haul"))
    assert res["eligible"] is False   # no hotel + no next-day rest


def test_eligible_three_sectors_even_with_smaller_gap():
    day = {
        "date": "2026-07-24", "day_type": "Short-haul", "duty_hours": 10,
        "hotel_id": "h1",
        "flights": [
            {"dep": "06:00", "arr": "07:00"},
            {"dep": "08:30", "arr": "09:30"},
            {"dep": "11:00", "arr": "12:00"},
        ],
    }
    res = evaluate_day(day, None, _prof("short_haul"))
    assert res["eligible"] is True   # 3 sectors + hotel = eligible


def test_mixed_flying_type_also_eligible():
    day = {
        "date": "2026-07-24", "day_type": "Short-haul", "duty_hours": 8,
        "hotel_id": "h1",
        "flights": [{"dep": "06:00", "arr": "07:30"}, {"dep": "11:30", "arr": "13:00"}],
    }
    res = evaluate_day(day, None, _prof("mixed"))
    assert res["eligible"] is True


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
