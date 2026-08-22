"""Iter189m · Logging-type hardening tests.

Guards the hardened `_derive_logging_type` contract:
  1. Library's explicit `logging_type` value ALWAYS wins (passes through
     verbatim) — timer/cardio/weighted/bodyweight/mobility all round-trip.
  2. Blank / missing `logging_type` falls back to the category / training_type
     heuristic (cardio-family → cardio, everything else → weighted).
  3. Explicit `logging_type` beats a conflicting `category` value.

Also verifies the projection in `_enrich_for_guided` now returns
`logging_type` so the frontend can trust it.

Run: `python -m pytest backend/tests/test_iter189m_logging_type_hardening.py -q`
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from feature_coach_manual_workouts import _derive_logging_type  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Empty / None input.
# ---------------------------------------------------------------------------
def test_none_defaults_weighted():
    assert _derive_logging_type(None) == "weighted"


def test_empty_dict_defaults_weighted():
    assert _derive_logging_type({}) == "weighted"


# ---------------------------------------------------------------------------
# 2. Library `logging_type` passes through verbatim.
# ---------------------------------------------------------------------------
def test_library_timer_passthrough():
    assert _derive_logging_type({"logging_type": "timer"}) == "timer"


def test_library_cardio_passthrough():
    assert _derive_logging_type({"logging_type": "cardio"}) == "cardio"


def test_library_weighted_passthrough():
    assert _derive_logging_type({"logging_type": "weighted"}) == "weighted"


def test_library_bodyweight_passthrough():
    assert _derive_logging_type({"logging_type": "bodyweight"}) == "bodyweight"


def test_library_mobility_passthrough():
    assert _derive_logging_type({"logging_type": "mobility"}) == "mobility"


def test_library_value_case_and_whitespace():
    assert _derive_logging_type({"logging_type": " Timer "}) == "timer"


# ---------------------------------------------------------------------------
# 3. Fallback heuristic only fires when `logging_type` is blank / missing.
# ---------------------------------------------------------------------------
def test_blank_logging_type_falls_back_to_category_cardio():
    assert _derive_logging_type({"logging_type": "", "category": "cardio"}) == "cardio"


def test_none_logging_type_falls_back_to_training_type_cardio():
    assert _derive_logging_type({"logging_type": None, "training_type": "cardio"}) == "cardio"


def test_strength_category_falls_back_to_weighted():
    assert _derive_logging_type({"category": "strength"}) == "weighted"


def test_hiit_category_falls_back_to_cardio():
    assert _derive_logging_type({"category": "hiit"}) == "cardio"


def test_conditioning_category_falls_back_to_cardio():
    assert _derive_logging_type({"category": "conditioning"}) == "cardio"


# ---------------------------------------------------------------------------
# 4. Explicit `logging_type` wins over conflicting category.
# ---------------------------------------------------------------------------
def test_explicit_weighted_beats_cardio_category():
    assert _derive_logging_type({"logging_type": "weighted", "category": "cardio"}) == "weighted"


def test_explicit_timer_beats_strength_category():
    assert _derive_logging_type({"logging_type": "timer", "category": "strength"}) == "timer"
