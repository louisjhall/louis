"""Iter 95g — prove the run + mobility passthrough and the pattern-rotation dedup."""
from feature_workout_fallback_v2 import (
    bodyweight_substitute_for,
    _is_endurance_item,
    _is_mobility_item,
)


def test_easy_run_passes_through_unchanged():
    item = {"name": "Easy Run", "sets": 1, "reps": "25-35 min steady", "rpe": 4}
    out = bodyweight_substitute_for(item)
    assert out["name"] == "Easy Run"
    assert "High-Knee" not in out["name"]
    assert out["source"] == "endurance_mobility_passthrough"


def test_long_run_passes_through():
    item = {"name": "Long Run", "sets": 1, "reps": "60-90 min steady"}
    out = bodyweight_substitute_for(item)
    assert out["name"] == "Long Run"


def test_diaphragmatic_breathing_passes_through():
    item = {"name": "Diaphragmatic breathing", "sets": 1, "reps": "10 breaths", "rpe": 2}
    out = bodyweight_substitute_for(item)
    assert out["name"] == "Diaphragmatic breathing"
    assert "Bodyweight Squat" not in out["name"]


def test_worlds_greatest_stretch_passes_through():
    item = {"name": "World's greatest stretch", "sets": 2, "reps": "5 each side"}
    out = bodyweight_substitute_for(item)
    assert "greatest" in out["name"]


def test_90_90_hip_rotations_passes_through():
    item = {"name": "90/90 hip rotations", "sets": 2, "reps": "8 each side"}
    out = bodyweight_substitute_for(item)
    assert "90/90" in out["name"]


def test_downward_dog_passes_through():
    item = {"name": "Downward dog to cobra flow", "sets": 2, "reps": "6"}
    out = bodyweight_substitute_for(item)
    assert "downward" in out["name"].lower() or "cobra" in out["name"].lower()


def test_pattern_hint_forces_alternative():
    """When two chest-press items are dropped, the second must NOT come back
    as another Push-up — the resolver's pattern rotation should kick in."""
    item = {"name": "Chest press", "_pattern_hint": "hinge"}
    out = bodyweight_substitute_for(item)
    assert "Good Morning" in out["name"] or "hinge" in out.get("movement_pattern", "")


def test_endurance_and_mobility_detectors():
    assert _is_endurance_item({"name": "Easy Run"})
    assert _is_endurance_item({"name": "Long Run"})
    assert _is_endurance_item({"name": "Tempo Run"})
    assert _is_endurance_item({"name": "Bike ride 30min"})
    assert _is_mobility_item({"name": "Cat-cow"})
    assert _is_mobility_item({"name": "Diaphragmatic breathing"})
    assert _is_mobility_item({"name": "Downward dog to cobra flow"})
    assert not _is_endurance_item({"name": "Bench Press"})
    assert not _is_mobility_item({"name": "Squat"})


def test_squat_still_gets_bodyweight_squat():
    """Sanity check: a real squat request that fails to resolve should
    still fall back to Bodyweight Squat, we only guard the endurance
    and mobility classes."""
    item = {"name": "Barbell back squat"}
    out = bodyweight_substitute_for(item)
    assert "Bodyweight Squat" == out["name"]


if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-v"]))
