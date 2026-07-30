"""
Iter 128m — Full Commercial Gym preset tests.

Read-only unit tests against `feature_equipment_matcher.normalise_available`
and `FULL_COMMERCIAL_GYM_EXPANSION`. No programme generation, no LLM.
"""
from feature_equipment_matcher import (
    normalise_available,
    FULL_COMMERCIAL_GYM_EXPANSION,
    FULL_GYM_EXPANSION,
)


# ---------------------------------------------------------------------------
# Preset shape
# ---------------------------------------------------------------------------

def test_commercial_gym_preset_includes_common_equipment():
    """§2 — the preset lists commonly-available commercial gym equipment."""
    must_have = {
        "dumbbells", "barbell", "bench", "adjustable_bench",
        "smith_machine", "cable_stack",
        "leg_press", "leg_extension", "leg_curl",
        "chest_press_machine", "shoulder_press_machine",
        "lat_pulldown", "seated_cable_row",
        "pull_up_bar", "resistance_bands", "kettlebell",
        "treadmill", "stationary_bike", "rowing_machine", "elliptical",
    }
    missing = must_have - FULL_COMMERCIAL_GYM_EXPANSION
    assert not missing, f"preset missing expected items: {missing}"


def test_commercial_gym_preset_excludes_niche_specialist_equipment():
    """§3 — no specialist / bodybuilding equipment auto-included."""
    forbidden = {
        "hack_squat", "pendulum_squat", "belt_squat", "ghd", "reverse_hyper",
        "safety_squat_bar", "trap_bar", "hip_thrust_machine",
        "sled", "turf", "skierg", "assault_bike", "specialty_bars",
    }
    leaked = forbidden & FULL_COMMERCIAL_GYM_EXPANSION
    assert not leaked, f"preset leaked niche equipment: {leaked}"


def test_commercial_gym_marker_expands_via_normalise():
    """§14/§18 — normalise_available expands the marker into the preset."""
    resolved = normalise_available(["commercial_gym_standard"])
    # normalise_available always adds "bodyweight" implicitly.
    assert resolved == FULL_COMMERCIAL_GYM_EXPANSION | {"bodyweight"}


def test_alias_full_commercial_gym_also_expands():
    for alias in ("Full Commercial Gym", "commercial gym", "full_commercial_gym"):
        resolved = normalise_available([alias])
        assert resolved == FULL_COMMERCIAL_GYM_EXPANSION | {"bodyweight"}, f"alias failed: {alias!r}"


def test_explicit_additions_stack_on_top_of_preset():
    """§17 — client can add specific extras (e.g. trap_bar) explicitly."""
    resolved = normalise_available(["commercial_gym_standard", "trap_bar"])
    assert "trap_bar" in resolved
    # And every preset item is still there
    assert FULL_COMMERCIAL_GYM_EXPANSION.issubset(resolved)


def test_full_commercial_gym_is_broader_than_full_gym_marker():
    """Commercial preset must NOT be narrower than the legacy hotel-gym marker."""
    assert FULL_GYM_EXPANSION.issubset(FULL_COMMERCIAL_GYM_EXPANSION), (
        "commercial gym should include everything hotel full_gym implies"
    )
    # And it must add commercial-specific machines the hotel marker did NOT have.
    added = FULL_COMMERCIAL_GYM_EXPANSION - FULL_GYM_EXPANSION
    assert "leg_press" in added
    assert "lat_pulldown" in added
    assert "chest_press_machine" in added


def test_travel_hotel_room_bodyweight_does_not_inherit_commercial_gym():
    """§14 — Hotel Room · Bodyweight must never expose commercial-gym items."""
    resolved = normalise_available(["bodyweight"])
    assert "leg_press" not in resolved
    assert "smith_machine" not in resolved
    assert "cable_stack" not in resolved
    assert "barbell" not in resolved


def test_travel_gym_marker_does_not_promote_to_commercial_gym():
    """§15 — a hotel gym (marker=full_gym_marker) is NOT the same as the
    permanent Full Commercial Gym preset."""
    hotel = normalise_available(["gym"])   # hotel-side "gym" alias → full_gym_marker
    home  = normalise_available(["commercial_gym_standard"])
    assert home != hotel
    assert home > hotel      # commercial gym is a strict superset
    # Specifically the commercial-only machines must not be in a hotel gym.
    assert "leg_press" not in hotel
    assert "lat_pulldown" not in hotel


def test_no_equipment_wins_over_marker_when_only_bodyweight():
    resolved = normalise_available(["bodyweight"])
    assert resolved == {"bodyweight"}
