"""Unit tests for the workout swap ranker."""
import sys, os, importlib.util, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_fake_server = types.ModuleType("server")
_fake_server.api = types.SimpleNamespace(get=lambda *a, **k: (lambda f: f), post=lambda *a, **k: (lambda f: f))
_fake_server.db = None
_fake_server.require_role = lambda role: lambda: {"id": "coach"}
_fake_server.new_id = lambda: "id"
_fake_server.now_iso = lambda: "2026-07-26"
sys.modules["server"] = _fake_server

spec = importlib.util.spec_from_file_location(
    "_sw_test", os.path.join(os.path.dirname(__file__), "..", "feature_coach_workout_swap.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_black_day_returns_only_mobility_or_steps():
    day = {"training_colour": "black", "blocked": ["main_strength", "long_run", "intervals", "tempo", "easy_run", "hotel_strength", "bodyweight"]}
    ranked = mod._rank_presets(day)
    focuses = {p["focus"] for p in ranked}
    # No strength/running/intervals should survive
    assert "strength" not in focuses
    assert "intervals" not in focuses
    assert "easy_run" not in focuses


def test_red_day_recovery_wins():
    day = {"training_colour": "red", "blocked": ["main_strength", "long_run", "intervals", "tempo"]}
    ranked = mod._rank_presets(day)
    assert len(ranked) > 0
    top = ranked[0]
    assert top["focus"] in ("mobility", "recovery")


def test_amber_day_moderate_options():
    day = {"training_colour": "amber", "blocked": ["main_strength", "long_run"]}
    ranked = mod._rank_presets(day)
    focuses = [p["focus"] for p in ranked]
    # No strength should appear
    assert "strength" not in focuses
    # Bodyweight, mobility, easy run should
    assert any(f in focuses for f in ("bodyweight", "mobility", "recovery"))


def test_green_day_ranks_strength_or_intervals_high():
    day = {"training_colour": "green", "blocked": []}
    ranked = mod._rank_presets(day)
    top3 = [p["focus"] for p in ranked[:3]]
    assert any(f in top3 for f in ("strength", "easy_run", "intervals"))


def test_hotel_only_equipment_drops_strength():
    day = {
        "training_colour": "amber",
        "blocked": [],
        "equipment_assumption": "hotel_or_bodyweight_only",
    }
    ranked = mod._rank_presets(day)
    # Strength should be low priority
    strength_score = next((p["fit_score"] for p in ranked if p["focus"] == "strength"), None)
    bodyweight_score = next((p["fit_score"] for p in ranked if p["focus"] == "bodyweight"), None)
    if strength_score is not None and bodyweight_score is not None:
        assert bodyweight_score > strength_score


def test_no_day_still_returns_presets():
    ranked = mod._rank_presets({})
    assert len(ranked) >= 3
    for p in ranked:
        assert "fit_score" in p
        assert "title" in p


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
