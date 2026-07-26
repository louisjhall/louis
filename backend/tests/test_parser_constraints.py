"""Unit tests for parser_constraints — the Phase 2 safety net that ensures
LLM workouts respect the parser-generated per-day training_colour /
blocked[] / equipment_assumption / action fields.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parser_constraints import (
    constraints_for_day, violates_constraints,
    sanitize_workout_for_day, enforce_constraints_on_workouts,
    constraint_block_for_prompt,
)


# ---------------------------------------------------------------------------
# constraints_for_day
# ---------------------------------------------------------------------------

def test_black_day_becomes_rest_only():
    day = {"date": "2026-06-10", "training_colour": "black",
           "label": "NEEDS_REVIEW", "client_label": "Unclear — needs your check",
           "blocked": ["main_strength", "long_run"], "source": "etihad_parser_v1"}
    p = constraints_for_day(day)
    assert p.action == "rest_only"
    assert p.max_duration_min == 0
    assert p.from_parser is True


def test_red_day_becomes_recovery_only():
    day = {"date": "2026-06-11", "training_colour": "red",
           "label": "LONG_HAUL_RETURN", "client_label": "Return from JFK",
           "blocked": ["main_strength", "long_run", "intervals"],
           "source": "etihad_parser_v1"}
    p = constraints_for_day(day)
    assert p.action == "recovery_only"
    assert p.max_duration_min == 25


def test_amber_day_becomes_moderated():
    day = {"date": "2026-06-12", "training_colour": "amber",
           "label": "LAYOVER_DAY", "client_label": "Layover in NBO",
           "blocked": ["main_strength"], "equipment_assumption": "hotel_or_bodyweight",
           "source": "etihad_parser_v1"}
    p = constraints_for_day(day)
    assert p.action == "moderated"
    assert p.max_duration_min == 45
    assert p.equipment == "hotel_or_bodyweight"


def test_green_day_full_session():
    day = {"date": "2026-06-13", "training_colour": "green",
           "label": "OFF_DAY", "client_label": "Free day",
           "source": "etihad_parser_v1"}
    p = constraints_for_day(day)
    assert p.action == "full_session"
    assert p.max_duration_min is None


def test_day_without_parser_defaults_to_green():
    p = constraints_for_day({"date": "2026-06-14"})
    assert p.colour == "green"
    assert p.action == "full_session"
    assert p.from_parser is False


# ---------------------------------------------------------------------------
# violates_constraints
# ---------------------------------------------------------------------------

def test_strength_on_red_day_violates():
    day = {"date": "2026-06-11", "training_colour": "red",
           "client_label": "Return from JFK",
           "blocked": ["main_strength", "long_run", "intervals"],
           "source": "etihad_parser_v1"}
    w = {"date": "2026-06-11", "focus": "strength",
         "title": "Lower Body Strength", "duration_min": 60}
    viol, reason = violates_constraints(w, day)
    assert viol is True
    assert "recovery" in reason.lower() or "blocked" in reason.lower()


def test_mobility_on_red_day_ok():
    day = {"date": "2026-06-11", "training_colour": "red",
           "client_label": "Return from JFK",
           "blocked": ["main_strength", "long_run", "intervals"],
           "source": "etihad_parser_v1"}
    w = {"date": "2026-06-11", "focus": "mobility",
         "title": "Recovery Flow", "duration_min": 15}
    viol, _ = violates_constraints(w, day)
    assert viol is False


def test_gym_on_hotel_only_equipment_violates():
    day = {"date": "2026-06-12", "training_colour": "amber",
           "client_label": "Layover in JFK",
           "equipment_assumption": "hotel_or_bodyweight_only",
           "source": "emirates_parser_v1"}
    w = {"date": "2026-06-12", "focus": "strength",
         "title": "Barbell Squat Day", "duration_min": 45}
    viol, _ = violates_constraints(w, day)
    assert viol is True


def test_long_duration_on_amber_day_flagged():
    day = {"date": "2026-06-12", "training_colour": "amber",
           "client_label": "Standby", "source": "etihad_parser_v1"}
    w = {"date": "2026-06-12", "focus": "easy_run",
         "title": "Easy Run", "duration_min": 90}
    viol, _ = violates_constraints(w, day)
    assert viol is True


# ---------------------------------------------------------------------------
# sanitize_workout_for_day
# ---------------------------------------------------------------------------

def test_sanitize_replaces_strength_on_red():
    day = {"date": "2026-06-11", "training_colour": "red",
           "client_label": "Return from JFK",
           "blocked": ["main_strength", "long_run", "intervals"],
           "source": "etihad_parser_v1"}
    w = {"date": "2026-06-11", "focus": "strength",
         "title": "Lower Body", "duration_min": 60,
         "exercises": [{"name": "Back Squat", "sets": 4, "reps": "6"}]}
    out, changed, _ = sanitize_workout_for_day(w, day)
    assert changed is True
    assert out.get("focus") in ("mobility", "recovery")
    assert out.get("parser_enforced") is True


def test_sanitize_replaces_with_rest_on_black():
    day = {"date": "2026-06-10", "training_colour": "black",
           "client_label": "Unclear — needs your check",
           "blocked": ["main_strength"], "source": "etihad_parser_v1"}
    w = {"date": "2026-06-10", "focus": "cardio",
         "title": "Zone 2 Run", "duration_min": 40}
    out, changed, _ = sanitize_workout_for_day(w, day)
    assert changed is True
    assert out.get("focus") == "rest"


def test_sanitize_moderates_amber_duration():
    day = {"date": "2026-06-12", "training_colour": "amber",
           "client_label": "Layover in NBO",
           "blocked": [], "source": "etihad_parser_v1"}
    w = {"date": "2026-06-12", "focus": "easy_run",
         "title": "Easy Run", "duration_min": 90,
         "exercises": [{"name": "Easy Zone 2", "sets": 1, "reps": "60min"}]}
    out, changed, _ = sanitize_workout_for_day(w, day)
    assert changed is True
    # Should be moderated to fit within amber cap (45m)
    assert out.get("duration_min") == 45
    assert out.get("parser_moderated") is True


def test_sanitize_builds_missing_rest():
    day = {"date": "2026-06-10", "training_colour": "black",
           "client_label": "Unclear", "source": "etihad_parser_v1"}
    out, changed, _ = sanitize_workout_for_day(None, day)
    assert changed is True
    assert out.get("focus") == "rest"


def test_sanitize_leaves_green_alone():
    day = {"date": "2026-06-13", "training_colour": "green",
           "label": "OFF_DAY", "client_label": "Free day",
           "source": "etihad_parser_v1"}
    w = {"date": "2026-06-13", "focus": "strength",
         "title": "Full Body", "duration_min": 45,
         "exercises": [{"name": "Squat", "sets": 3}]}
    out, changed, _ = sanitize_workout_for_day(w, day)
    assert changed is False
    assert out == w


# ---------------------------------------------------------------------------
# enforce_constraints_on_workouts
# ---------------------------------------------------------------------------

def test_enforce_batch_replaces_and_adds():
    days = [
        {"date": "2026-06-10", "training_colour": "black",
         "client_label": "Unclear", "source": "etihad_parser_v1"},
        {"date": "2026-06-11", "training_colour": "red",
         "client_label": "Return from JFK",
         "blocked": ["main_strength", "long_run", "intervals"],
         "source": "etihad_parser_v1"},
        {"date": "2026-06-12", "training_colour": "green",
         "client_label": "Free day", "source": "etihad_parser_v1"},
    ]
    workouts = [
        {"date": "2026-06-10", "focus": "strength",
         "title": "Deadlift Day", "duration_min": 60},
        # 2026-06-11 missing - should be added
        {"date": "2026-06-12", "focus": "strength",
         "title": "Full Body", "duration_min": 45,
         "exercises": [{"name": "Squat", "sets": 3}]},
    ]
    stats = enforce_constraints_on_workouts(workouts, days)
    assert stats["checked"] == 2
    assert stats["replaced"] >= 1
    assert stats["added"] == 1
    # The strength day is now rest
    by_date = {w["date"]: w for w in workouts}
    assert by_date["2026-06-10"]["focus"] == "rest"
    assert by_date["2026-06-11"]["focus"] in ("mobility", "recovery")
    assert by_date["2026-06-12"]["focus"] == "strength"


def test_enforce_no_op_when_all_green():
    days = [
        {"date": "2026-06-13", "training_colour": "green",
         "client_label": "Free day", "source": "etihad_parser_v1"},
    ]
    workouts = [{"date": "2026-06-13", "focus": "strength", "duration_min": 45}]
    stats = enforce_constraints_on_workouts(workouts, days)
    assert stats["replaced"] == 0
    assert stats["moderated"] == 0
    assert stats["added"] == 0


# ---------------------------------------------------------------------------
# constraint_block_for_prompt
# ---------------------------------------------------------------------------

def test_prompt_block_includes_parser_days():
    days = [
        {"date": "2026-06-10", "training_colour": "black",
         "client_label": "Unclear", "source": "etihad_parser_v1",
         "blocked": ["main_strength"]},
        {"date": "2026-06-13", "training_colour": "green",
         "client_label": "Free day", "source": "etihad_parser_v1"},
        {"date": "2026-06-14"},  # no parser — should be skipped
    ]
    block = constraint_block_for_prompt(days)
    dates = {b["date"] for b in block}
    assert "2026-06-10" in dates
    assert "2026-06-13" in dates
    assert "2026-06-14" not in dates
    # First day has action rest_only, blocked non-empty, colour black
    d0 = next(b for b in block if b["date"] == "2026-06-10")
    assert d0["action"] == "rest_only"
    assert "main_strength" in d0["blocked"]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
