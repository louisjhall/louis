"""Unit tests for feature_coach_roster_months helpers.

We test the pure helper functions (no DB required). End-to-end HTTP tests
of the endpoints require a coach fixture — those can be added later.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import via internal helpers directly (avoid full server startup)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "_crm_test", os.path.join(os.path.dirname(__file__), "..", "feature_coach_roster_months.py")
)
# Some of the module imports server, which requires a full stack.
# For helper tests we can bypass by inserting minimal stubs first.
import types, sys as _sys
_fake_server = types.ModuleType("server")
_fake_server.api = types.SimpleNamespace(get=lambda *a, **k: (lambda f: f))
_fake_server.db = None
_fake_server.require_role = lambda role: lambda: {"id": "coach"}
_sys.modules["server"] = _fake_server
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_month_key():
    assert mod._month_key("2026-07-13") == "2026-07"
    assert mod._month_key("2026-12-31") == "2026-12"
    assert mod._month_key("") == ""
    assert mod._month_key("2026") == ""


def test_month_label():
    assert mod._month_label("2026-07") == "July 2026"
    assert mod._month_label("2026-01") == "January 2026"
    assert mod._month_label("") == "Unknown"
    assert mod._month_label("bad") == "bad"


def test_roster_month_span_multi_month():
    r = {"days": [
        {"date": "2026-07-15"},
        {"date": "2026-07-25"},
        {"date": "2026-08-01"},
        {"date": "2026-08-15"},
    ]}
    assert mod._roster_month_span(r) == ["2026-07", "2026-08"]


def test_airline_of_etihad():
    assert mod._airline_of({"parser_source": "etihad_parser_v1"}) == "Etihad"


def test_airline_of_emirates():
    assert mod._airline_of({"parser_source": "emirates_parser_v1"}) == "Emirates"


def test_airline_of_unknown():
    assert mod._airline_of({}) == "Airline"


def test_status_of():
    assert mod._status_of({"confirmed": True, "is_active": True}) == "programme_generated"
    assert mod._status_of({"confirmed": True, "is_active": False}) == "confirmed"
    assert mod._status_of({"status": "pending_confirmation"}) == "needs_client_review"
    assert mod._status_of({"confirmed": True, "is_active": True,
                           "review_flags": {"black_day_count": 2}}) == "needs_coach_review"


def test_needs_review():
    assert mod._needs_review({"review_flags": {"black_day_count": 1}}) is True
    assert mod._needs_review({"review_flags": {"low_confidence_count": 5}}) is True
    assert mod._needs_review({"confidence_avg": 0.4}) is True
    assert mod._needs_review({"confidence_avg": 0.9, "review_flags": {}}) is False


def test_summarise_workout_counts_missing_media():
    w = {
        "id": "w1", "title": "Recovery", "focus": "mobility",
        "duration_min": 20,
        "exercises": [
            {"name": "a", "image_url": "url", "video_url": ""},
            {"name": "b", "image_url": "", "video_url": ""},
            {"name": "c"},  # missing everything
        ],
    }
    s = mod._summarise_workout(w)
    assert s["exercise_count"] == 3
    assert s["missing_media_count"] == 2


def test_summarise_day_with_no_workout():
    d = {"date": "2026-07-01", "day_type": "off",
         "client_label": "Free day", "training_colour": "green"}
    s = mod._summarise_day(d, None)
    assert s["date"] == "2026-07-01"
    assert s["workout"] is None
    assert s["client_label"] == "Free day"


def test_summarise_day_carries_parser_fields():
    d = {"date": "2026-07-15", "day_type": "flight",
         "client_label": "Return from JFK", "training_colour": "red",
         "blocked": ["main_strength", "long_run"],
         "equipment_assumption": "hotel_or_bodyweight",
         "source": "etihad_parser_v1", "reason": "Long-haul return"}
    s = mod._summarise_day(d, None)
    assert s["training_colour"] == "red"
    assert "main_strength" in s["blocked"]
    assert s["equipment_assumption"] == "hotel_or_bodyweight"
    assert s["source"] == "etihad_parser_v1"
    assert s["reason"] == "Long-haul return"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
