"""Unit tests for parsers.emirates_labels — client_label + blocked enrichment."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parsers.emirates_labels import enrich_emirates_days


def test_enrich_day_off():
    days = [{"date": "2026-06-01", "source": "emirates_parser_v1",
             "training_colour": "green", "label": "DAY_OFF", "day_type": "day_off"}]
    enrich_emirates_days(days)
    assert days[0]["client_label"] == "Free day"
    assert days[0]["blocked"] == []


def test_enrich_long_haul_return():
    days = [{"date": "2026-06-02", "source": "emirates_parser_v1",
             "training_colour": "red", "label": "LONG_HAUL_RETURN",
             "layover_city": "SYD"}]
    enrich_emirates_days(days)
    assert "Return from SYD" in days[0]["client_label"]
    assert "main_strength" in days[0]["blocked"]
    assert "tempo" in days[0]["blocked"]


def test_enrich_layover_hotel_only():
    days = [{"date": "2026-06-03", "source": "emirates_parser_v1",
             "training_colour": "amber", "label": "LAYOVER_REST_DAY",
             "layover_city": "JFK",
             "equipment_assumption": "hotel_or_bodyweight_only"}]
    enrich_emirates_days(days)
    assert "JFK" in days[0]["client_label"]
    assert "main_strength" in days[0]["blocked"]


def test_enrich_needs_review_blocks_everything():
    days = [{"date": "2026-06-04", "source": "emirates_parser_v1",
             "training_colour": "black", "label": "NEEDS_REVIEW"}]
    enrich_emirates_days(days)
    assert "check" in days[0]["client_label"].lower()
    assert "main_strength" in days[0]["blocked"]
    assert "long_run" in days[0]["blocked"]


def test_enrich_sim_training():
    days = [{"date": "2026-06-05", "source": "emirates_parser_v1",
             "training_colour": "amber", "label": "SIM_TRAINING"}]
    enrich_emirates_days(days)
    assert days[0]["client_label"] == "SIM training"
    assert "main_strength" in days[0]["blocked"]


def test_enrich_skips_non_emirates():
    days = [{"date": "2026-06-06", "source": "etihad_parser_v1",
             "training_colour": "red", "label": "OVERNIGHT_DUTY"}]
    enrich_emirates_days(days)
    # Should not set client_label since source != emirates
    assert "client_label" not in days[0]
    assert "blocked" not in days[0]


def test_enrich_does_not_overwrite_existing():
    days = [{"date": "2026-06-07", "source": "emirates_parser_v1",
             "training_colour": "amber", "label": "LAYOVER_REST_DAY",
             "client_label": "Custom coach label", "blocked": ["intervals"]}]
    enrich_emirates_days(days)
    assert days[0]["client_label"] == "Custom coach label"
    assert days[0]["blocked"] == ["intervals"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
