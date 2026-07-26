"""Unit tests for feature_coach_live_feed pure helpers."""
import sys, os, importlib.util, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub server so the module can import without a full stack.
_fake_server = types.ModuleType("server")
_fake_server.api = types.SimpleNamespace(get=lambda *a, **k: (lambda f: f))
_fake_server.db = None
_fake_server.require_role = lambda role: lambda: {"id": "coach"}
sys.modules["server"] = _fake_server

spec = importlib.util.spec_from_file_location(
    "_lf_test", os.path.join(os.path.dirname(__file__), "..", "feature_coach_live_feed.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_colour_of_defaults_green():
    assert mod._colour_of({}) == "green"
    assert mod._colour_of({"training_colour": "Amber"}) == "amber"
    assert mod._colour_of({"training_colour": "bogus"}) == "green"


def test_airline_of_from_parser():
    assert mod._airline_of({}, {"parser_source": "etihad_parser_v1"}) == "Etihad"
    assert mod._airline_of({}, {"parser_source": "emirates_parser_v1"}) == "Emirates"


def test_airline_of_from_profile_fallback():
    assert mod._airline_of({"profile": {"airline": "British Airways"}}, None) == "British Airways"


def test_missing_media_count():
    w = {"exercises": [
        {"name": "a"},
        {"name": "b", "image_url": "http://x"},
        {"name": "c", "video_url": "http://y"},
        {"name": "d", "image_url": "", "video_url": ""},
    ]}
    assert mod._missing_media_count(w) == 2


def test_day_offset_label():
    assert mod._day_offset_label(0) == "Today"
    assert mod._day_offset_label(1) == "Tomorrow"
    assert mod._day_offset_label(-2) == "2d ago"
    assert mod._day_offset_label(4) == "In 4d"


def test_flag_workout_today_missing_media_wins_priority():
    day = {"training_colour": "green"}
    w = {"exercises": [{"name": "x"}, {"name": "y"}]}
    flags = mod._flag_workout(day, w, 0, None)
    assert "today" in flags
    assert "needs_media" in flags
    assert "today_missing_media" in flags
    p = mod._priority_of(flags)
    assert p >= 90  # today_missing_media weighted 90


def test_flag_workout_missed_yesterday():
    day = {"training_colour": "green"}
    w = {"exercises": [], "completed": False}
    flags = mod._flag_workout(day, w, -1, None)
    assert "missed" in flags
    assert mod._priority_of(flags) >= 100


def test_flag_workout_red_heavy_duty():
    day = {"training_colour": "red", "label": "LONG_HAUL_RETURN"}
    w = {"exercises": [{"name": "x", "image_url": "u"}]}
    flags = mod._flag_workout(day, w, 2, None)
    assert "heavy_duty" in flags
    assert "needs_media" not in flags


def test_flag_workout_layover_unknown_equipment():
    day = {
        "training_colour": "amber",
        "label": "LAYOVER_REST_DAY",
        "day_type": "layover_day",
        "equipment_assumption": "hotel_or_bodyweight_only",
    }
    w = {"exercises": [{"name": "x", "image_url": "u"}]}
    flags = mod._flag_workout(day, w, 2, None)
    assert "layover" in flags
    assert "layover_unknown_equip" in flags
    assert "hotel_gym_unknown" in flags


def test_flag_workout_post_night_recovery():
    day = {"training_colour": "amber", "label": "POST_NIGHT_RECOVERY"}
    w = {"exercises": [{"name": "x", "image_url": "u"}]}
    flags = mod._flag_workout(day, w, 1, None)
    assert "post_night_recovery" in flags
    assert "tomorrow" in flags


def test_priority_sorting_matches_spec():
    """Per spec priority order:
       1. Today missing media
       2. Today needs review
       3. Roster uncertain
       4. RED heavy duty (today)
       5. Layover unknown equipment (today)
       6. Tomorrow needs review
       7. Regular upcoming
    """
    scores = [
        mod._priority_of(["today", "today_missing_media", "needs_media"]),  # 1
        mod._priority_of(["today", "today_needs_review", "needs_review"]),  # 2
        mod._priority_of(["today", "roster_uncertain"]),                    # 3
        mod._priority_of(["today", "heavy_duty"]),                          # 4
        mod._priority_of(["today", "layover", "layover_unknown_equip"]),    # 5
        mod._priority_of(["tomorrow", "tomorrow_needs_review", "needs_review"]),  # 6
        mod._priority_of(["ready"]),                                        # 7
    ]
    for i in range(len(scores) - 1):
        assert scores[i] > scores[i + 1], f"Rank {i} not > {i+1}: {scores}"


def test_missed_boost():
    # Missed workouts should still get significant priority
    assert mod._priority_of(["missed"]) >= 100


def test_summarise_workout_carries_all_fields():
    w = {
        "id": "w1", "title": "Recovery", "focus": "mobility",
        "duration_min": 20, "day_load": "amber",
        "exercises": [{"name": "x"}, {"name": "y", "image_url": "u"}],
        "approved": True, "coach_locked": False, "completed": False,
        "rationale": "test", "parser_enforced": True,
    }
    s = mod._summarise_workout(w)
    assert s["id"] == "w1"
    assert s["exercise_count"] == 2
    assert s["missing_media_count"] == 1
    assert s["parser_enforced"] is True


def test_summarise_roster_day_defaults():
    s = mod._summarise_roster_day({})
    assert s["training_colour"] == "green"
    assert s["equipment_assumption"] == "any"
    assert s["blocked"] == []


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
