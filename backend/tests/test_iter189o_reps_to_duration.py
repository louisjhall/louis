"""Iter189o · Auto-fill duration_sec from reps on warm-up / cool-down /
mobility rows so guided flow renders a timer instead of a bare reps
checkbox.

Guards the contract that `_approx_duration_from_reps`:
  1. Estimates a duration from a bare rep count on warmup/cooldown rows.
  2. Doubles per-side reps.
  3. Uses breath-work cadence for "N breaths".
  4. Never overwrites an explicit time-string reps ("30 sec", "5 min", "5:00", "hold").
  5. Never touches main-section strength rows.
  6. Applies to main rows only when logging_type/category is 'mobility'.
  7. Skips cardio rows entirely.
  8. Clamps to [15s, 300s].

Run: `python -m pytest backend/tests/test_iter189o_reps_to_duration.py -q`
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from feature_coach_manual_workouts import _approx_duration_from_reps  # noqa: E402


# 1. Basic warm-up estimation (3 sec/rep)
def test_warmup_bare_reps():
    assert _approx_duration_from_reps("8", "warmup") == 24


def test_warmup_per_side_doubles():
    assert _approx_duration_from_reps("10/side", "warmup") == 60


def test_warmup_each_side_doubles():
    assert _approx_duration_from_reps("10 each side", "warmup") == 60


def test_warmup_per_side_variant():
    assert _approx_duration_from_reps("6 per side", "warmup") == 36


def test_warmup_range_uses_midpoint():
    assert _approx_duration_from_reps("8-10", "warmup") == 27  # midpoint 9 × 3


# 2. Cool-down estimation (5 sec/rep)
def test_cooldown_bare_reps():
    assert _approx_duration_from_reps("8", "cooldown") == 40


def test_cooldown_per_side_doubles():
    assert _approx_duration_from_reps("4/side", "cooldown") == 40


# 3. Breath work uses breath cadence (6 sec/breath)
def test_breath_work_cadence():
    assert _approx_duration_from_reps("5 breaths", "cooldown") == 30


def test_breath_work_inhale():
    assert _approx_duration_from_reps("3 inhales", "cooldown") == 18


# 4. Never overwrite explicit time strings
def test_skip_sec_hint():
    assert _approx_duration_from_reps("60 sec", "warmup") is None


def test_skip_min_hint():
    assert _approx_duration_from_reps("5 min", "warmup") is None


def test_skip_hold_hint():
    assert _approx_duration_from_reps("30 sec hold", "cooldown") is None


def test_skip_mmss_hint():
    assert _approx_duration_from_reps("5:00", "warmup") is None


def test_skip_steady_hint():
    assert _approx_duration_from_reps("30 min steady", "warmup") is None


# 5. Never touch main-section strength rows
def test_main_strength_bare_reps_untouched():
    assert _approx_duration_from_reps("8", "main") is None


def test_main_weighted_untouched():
    assert _approx_duration_from_reps("8", "main", logging_type="weighted") is None


# 6. Main section OK when logging_type or category is mobility
def test_main_mobility_lt_estimated():
    assert _approx_duration_from_reps("8", "main", logging_type="mobility") == 40


def test_main_mobility_cat_estimated():
    assert _approx_duration_from_reps("8", "main", category="mobility") == 40


# 7. Cardio rows skipped entirely
def test_cardio_lt_skipped():
    assert _approx_duration_from_reps("30 min", "main", logging_type="cardio") is None


def test_timer_lt_skipped():
    assert _approx_duration_from_reps("8", "warmup", logging_type="timer") is None


# 8. Clamping
def test_clamp_min_15s():
    assert _approx_duration_from_reps("1", "warmup") == 15


def test_clamp_max_300s():
    assert _approx_duration_from_reps("200", "warmup") == 300


# 9. Falsy inputs
def test_none_reps():
    assert _approx_duration_from_reps(None, "warmup") is None


def test_empty_reps():
    assert _approx_duration_from_reps("", "warmup") is None
    assert _approx_duration_from_reps("   ", "warmup") is None


def test_unparseable_reps():
    assert _approx_duration_from_reps("as many as possible", "warmup") is None


# 10. Section not warmup/cooldown → skip (unless mobility)
def test_arbitrary_section_skipped():
    assert _approx_duration_from_reps("8", "middle") is None
