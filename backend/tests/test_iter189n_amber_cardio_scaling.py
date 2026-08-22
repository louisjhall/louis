"""Iter189n · Traffic-light green→amber cardio scaling regression tests.

Guards the hardened `_derive_amber` contract:
  1. Cardio-by-NAME exercises get their per-exercise duration/distance
     scaled — not just the workout-level `duration_min`.
  2. Cardio-by-DURATION exercises (no logging_type, but duration_sec > 0)
     are also scaled.
  3. Explicit strength `logging_type` (weighted / bodyweight / mobility)
     is NOT flipped to cardio by a stray duration_sec (guards against
     e.g. Dumbbell Row with duration_sec=60 rest hint).
  4. Time embedded in the `reps` string (30 min, 45s, 5:00) is scaled.
  5. `logging_type` survives amber untouched.

Run: `python -m pytest backend/tests/test_iter189n_amber_cardio_scaling.py -q`
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from feature_traffic_light import (  # noqa: E402
    _derive_amber,
    _is_cardio_ex,
    _scale_time_in_reps,
)


# ---------------------------------------------------------------------------
# _is_cardio_ex — mirror of the frontend classifier.
# ---------------------------------------------------------------------------
def test_cardio_by_logging_type_cardio():
    assert _is_cardio_ex({"logging_type": "cardio"})


def test_cardio_by_logging_type_timer():
    assert _is_cardio_ex({"logging_type": "timer"})


def test_cardio_by_duration_sec():
    assert _is_cardio_ex({"name": "Steady State", "duration_sec": 300})


def test_cardio_by_duration_min():
    assert _is_cardio_ex({"name": "Recovery Bout", "duration_min": 20})


def test_cardio_by_name_easy_run():
    assert _is_cardio_ex({"name": "Easy Run"})


def test_cardio_by_name_zone_2_bike():
    assert _is_cardio_ex({"name": "Zone 2 Bike"})


def test_cardio_by_name_rowing_erg():
    assert _is_cardio_ex({"name": "Rowing Erg 5k"})


def test_cardio_by_name_treadmill_walk():
    assert _is_cardio_ex({"name": "Treadmill Walk"})


def test_cardio_by_reps_time_hint():
    assert _is_cardio_ex({"name": "Plank Hold", "reps": "30 sec hold"})


def test_strength_barbell_row_not_cardio():
    assert not _is_cardio_ex({"name": "Barbell Row", "reps": "8"})


def test_strength_walking_lunge_not_cardio():
    assert not _is_cardio_ex({"name": "Walking Lunge", "reps": "10 each side"})


def test_strength_hip_thrust_not_cardio():
    assert not _is_cardio_ex({"name": "Hip Thrust", "reps": "10"})


def test_weighted_logging_type_blocks_duration_flip():
    """A Dumbbell Row incorrectly stamped with a stray duration_sec=60
    (typically a rest hint) MUST NOT be flipped to cardio."""
    assert not _is_cardio_ex({
        "name": "Dumbbell Row",
        "logging_type": "weighted",
        "duration_sec": 60,
        "reps": "10",
    })


def test_weighted_logging_type_still_flips_when_name_is_clearly_cardio():
    """Guard: if the coach tags an Easy Run as bodyweight, we still
    trust the name over the mislabelled logging_type."""
    assert _is_cardio_ex({
        "name": "Easy Run",
        "logging_type": "bodyweight",
    })


# ---------------------------------------------------------------------------
# _scale_time_in_reps — time-in-reps string scaling.
# ---------------------------------------------------------------------------
def test_scale_time_minutes():
    assert _scale_time_in_reps("30 min", 0.65) == "20 min"


def test_scale_time_seconds():
    assert _scale_time_in_reps("45s", 0.65) == "29s"


def test_scale_time_seconds_full_word():
    assert _scale_time_in_reps("45 seconds", 0.65) == "29 seconds"


def test_scale_time_mmss():
    assert _scale_time_in_reps("5:00", 0.65) == "3:15"


def test_scale_time_pure_number_untouched():
    assert _scale_time_in_reps("8", 0.65) is None


def test_scale_time_rep_range_untouched():
    assert _scale_time_in_reps("8-10", 0.65) is None


def test_scale_time_empty_untouched():
    assert _scale_time_in_reps("", 0.65) is None
    assert _scale_time_in_reps(None, 0.65) is None


# ---------------------------------------------------------------------------
# _derive_amber — full end-to-end.
# ---------------------------------------------------------------------------
def test_amber_scales_cardio_by_name_reps_string():
    """The regression: green Long Run with reps='30 min' MUST have that
    30 min scaled down on amber — not just the workout-level duration."""
    green = {
        "title": "Long Run",
        "duration_min": 60,
        "exercises": [
            {"name": "Easy Run", "reps": "30 min", "sets": 1},
        ],
    }
    amber = _derive_amber(green)
    er = amber["exercises"][0]
    assert er["reps"] == "20 min", f"cardio reps not scaled: {er['reps']!r}"
    # Cardio sets stay untouched.
    assert er.get("sets") == 1
    # Workout-level duration also scaled.
    assert amber["duration_min"] == 39  # 60 * 0.65


def test_amber_scales_cardio_by_duration_sec():
    green = {
        "title": "Intervals",
        "duration_min": 45,
        "exercises": [
            {"name": "Assault Bike", "duration_sec": 300, "sets": 1},
        ],
    }
    amber = _derive_amber(green)
    assert amber["exercises"][0]["duration_sec"] == 195  # 300 * 0.65


def test_amber_scales_cardio_distance_km():
    green = {
        "title": "Row 5k",
        "duration_min": 30,
        "exercises": [
            {"name": "Rowing Erg", "distance_km": 5.0, "sets": 1},
        ],
    }
    amber = _derive_amber(green)
    assert amber["exercises"][0]["distance_km"] == 3.25  # 5 * 0.65


def test_amber_scales_strength_sets_not_cardio_fields():
    green = {
        "title": "Squat Focus",
        "duration_min": 45,
        "exercises": [
            {"name": "Back Squat", "reps": "8", "sets": 5, "rpe": 8},
        ],
    }
    amber = _derive_amber(green)
    ex = amber["exercises"][0]
    assert ex["sets"] == 3  # 5 * 0.65 → 3.25 → 3
    assert ex["rpe"] == 7  # rpe - 1
    # No duration_sec / distance keys should have appeared on a strength lift.
    assert "duration_sec" not in ex
    assert "distance_km" not in ex


def test_amber_preserves_logging_type():
    green = {
        "title": "Run",
        "duration_min": 30,
        "exercises": [
            {"name": "Easy Walk", "logging_type": "cardio", "reps": "20 min"},
        ],
    }
    amber = _derive_amber(green)
    assert amber["exercises"][0]["logging_type"] == "cardio"
    assert amber["exercises"][0]["reps"] == "13 min"


def test_amber_weighted_lift_with_duration_hint_stays_strength():
    """The Dumbbell Row case — stray duration_sec must not turn it into
    a cardio row that skips set-scaling."""
    green = {
        "title": "Pull Day",
        "duration_min": 45,
        "exercises": [
            {"name": "Dumbbell Row", "logging_type": "weighted",
             "duration_sec": 60, "reps": "10", "sets": 4},
        ],
    }
    amber = _derive_amber(green)
    ex = amber["exercises"][0]
    # Sets should be scaled (strength branch).
    assert ex["sets"] == 3  # 4 * 0.65 → 2.6 → floored at 2 minimum → 3 via round
    # Duration_sec should NOT be scaled (strength branch skipped that block).
    assert ex["duration_sec"] == 60


def test_amber_drops_last_accessory_when_five_plus_exercises():
    green = {
        "title": "Full",
        "duration_min": 60,
        "exercises": [
            {"name": f"Ex{i}", "reps": "10", "sets": 3} for i in range(6)
        ],
    }
    amber = _derive_amber(green)
    assert len(amber["exercises"]) == 5
