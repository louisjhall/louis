"""
Regression tests for the Aviation Support Layer (Phase A / Iter 116).

These tests guarantee that operational interventions never leak into
Engine V2 quotas, adherence, or scheduling. If any test here regresses,
we've broken the WHAT → WHEN → HOW → VALIDATE contract of Engine V2.
"""
from __future__ import annotations

import pytest

from feature_aviation_support import (
    PROTOCOLS,
    select_interventions_for_day,
    summarise_training_by_date_from_workouts,
)


# ---------------------------------------------------------------------------
# 1. Protocol library is well-formed
# ---------------------------------------------------------------------------

def test_protocol_library_shape():
    assert len(PROTOCOLS) >= 8
    for k, p in PROTOCOLS.items():
        assert p.key == k, f"key mismatch for {k}"
        assert p.role in ("pilot", "cabin_crew")
        assert p.intensity in ("very_low", "low")
        assert p.duration_min >= 3
        assert p.duration_min <= 30
        lo, hi = p.duration_range
        assert lo <= p.duration_min <= hi
        assert p.family in ("walk", "mobility", "activation",
                             "recovery", "reset", "movement_break")


# ---------------------------------------------------------------------------
# 2. Non-pilot & non-duty short-circuits
# ---------------------------------------------------------------------------

def test_non_pilot_returns_empty():
    # Cabin crew comes in Phase C — for now the selector must be silent.
    got = select_interventions_for_day(
        role="cabin_crew",
        roster_day={"day_type": "flight", "flights": [{"flight_number": "1"}]},
        date="2026-08-10", has_training_today=False,
    )
    assert got == []


def test_no_roster_returns_empty():
    got = select_interventions_for_day(
        role="pilot", roster_day=None, date="2026-08-10",
        has_training_today=False,
    )
    assert got == []


def test_home_day_returns_empty():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "home_day", "flights": []},
        date="2026-08-10", has_training_today=False,
    )
    assert got == []


def test_rest_returns_empty():
    for label in ("rest", "off", "annual_leave", "day_off"):
        assert select_interventions_for_day(
            role="pilot", roster_day={"day_type": label, "flights": []},
            date="2026-08-10", has_training_today=False,
        ) == []


# ---------------------------------------------------------------------------
# 3. Duty-context routing
# ---------------------------------------------------------------------------

def test_layover_arrival_two_cards_walk_plus_mobility():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={
            "day_type": "layover_arrival", "layover_city": "NBO",
            "flights": [{"flight_number": "770", "dep_time": "07:00",
                          "arr_time": "13:15"}],
        },
        date="2026-08-10", has_training_today=False,
    )
    assert len(got) == 2
    families = sorted(i.family for i in got)
    assert families == ["mobility", "walk"]
    # Both share the bundle key
    assert got[0].bundle_key == got[1].bundle_key
    assert got[0].bundle_key.startswith("bundle:arrival:")


def test_layover_arrival_late_finish_drops_walk():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={
            "day_type": "layover_arrival", "layover_city": "SIN",
            "flights": [{"flight_number": "384", "dep_time": "19:00",
                          "arr_time": "23:40"}],
        },
        date="2026-08-10", has_training_today=False,
    )
    families = [i.family for i in got]
    assert "walk" not in families  # too late to walk
    assert "mobility" in families


def test_turnaround_is_single_reset():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "turnaround",
                     "flights": [{"flight_number": "332"},
                                 {"flight_number": "333"}]},
        date="2026-08-10", has_training_today=False,
    )
    assert len(got) == 1
    assert got[0].family == "reset"
    assert got[0].duration_min <= 8


def test_standby_no_training_gets_movement_break():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "standby", "flights": []},
        date="2026-08-10", has_training_today=False,
    )
    assert len(got) == 1
    assert got[0].family == "movement_break"


def test_standby_with_training_returns_empty():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "standby", "flights": []},
        date="2026-08-10", has_training_today=True,
    )
    assert got == []


def test_layover_full_with_training_skipped_over_prescribe():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "layover_full", "layover_city": "NBO"},
        date="2026-08-10", has_training_today=True,
    )
    assert got == []


def test_layover_full_without_training_gets_walk():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "layover_full", "layover_city": "NBO"},
        date="2026-08-10", has_training_today=False,
    )
    assert len(got) == 1
    assert got[0].family == "walk"


def test_flight_duty_long_haul_gets_walk_plus_mobility():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "flight", "duty_hours": 10,
                     "flights": [{"dep_time": "08:00", "arr_time": "18:00"}]},
        date="2026-08-10", has_training_today=False,
    )
    kinds = sorted(i.family for i in got)
    assert "mobility" in kinds and "walk" in kinds


def test_flight_duty_late_finish_uses_reset_not_walk():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "flight", "duty_hours": 8,
                     "flights": [{"dep_time": "18:00", "arr_time": "23:30"}]},
        date="2026-08-10", has_training_today=False,
    )
    families = [i.family for i in got]
    assert "walk" not in families


def test_flight_duty_heavy_training_gets_only_light_movement():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "flight", "duty_hours": 10,
                     "flights": [{"dep_time": "08:00", "arr_time": "18:00"}]},
        date="2026-08-10", has_training_today=True,
        training_intensity="hard",
    )
    families = [i.family for i in got]
    # Post-flight walk downgraded to movement_break when heavy training
    assert "movement_break" in families
    assert "walk" not in families


# ---------------------------------------------------------------------------
# 4. Isolation from Engine V2 quotas
# ---------------------------------------------------------------------------

def test_walk_is_marked_as_flight_support_not_training():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={"day_type": "layover_arrival",
                     "flights": [{"dep_time": "10:00", "arr_time": "12:00"}]},
        date="2026-08-10", has_training_today=False,
    )
    for i in got:
        assert i.is_flight_support is True
        # A flight-support walk MUST NOT be a run_easy / run_long / any kind
        # that Engine V2 counts as a required_exposure.
        assert i.protocol_key not in (
            "run_easy", "run_long", "run_tempo", "run_intervals",
            "strength_full_body", "programme_mobility", "run_race_pace",
        )


def test_summarise_ignores_flight_support_interventions():
    # Feeding a mixed list should only yield training-context. Flight-
    # support interventions are never stored in the workouts collection so
    # they are simply absent from the input — this test verifies the input
    # contract used by /calendar/range.
    training_row = {"date": "2026-08-10", "title": "Run Long",
                    "focus": "run_long", "day_load": 3, "key_session": True}
    other = {"date": "2026-08-11", "title": "Run Easy",
             "focus": "run_easy", "day_load": 2, "key_session": False}
    got = summarise_training_by_date_from_workouts([training_row, other])
    assert set(got.keys()) == {"2026-08-10", "2026-08-11"}
    assert got["2026-08-10"]["intensity"] == "hard"
    assert got["2026-08-11"]["intensity"] == "moderate"


def test_flight_support_id_is_unique_and_dedup_safe():
    got = select_interventions_for_day(
        role="pilot",
        roster_day={
            "day_type": "layover_arrival",
            "flights": [{"dep_time": "08:00", "arr_time": "10:00"}],
        },
        date="2026-08-10", has_training_today=False,
    )
    ids = [i.id for i in got]
    assert len(ids) == len(set(ids)), "duplicate intervention ids"
    for i in got:
        # ID must be stable + date-scoped so a re-render doesn't produce
        # new ids for the same day.
        assert i.id.startswith(f"fs:{i.date}:")


def test_max_three_interventions_per_day():
    """Spec §17 — never over-prescribe. Max 3 per day."""
    scenarios = [
        {"day_type": "layover_arrival", "flights": [{"dep_time": "08:00",
                                                     "arr_time": "10:00"}]},
        {"day_type": "flight", "duty_hours": 12,
         "flights": [{"dep_time": "08:00", "arr_time": "20:00"}]},
        {"day_type": "layover_departure", "duty_hours": 10,
         "flights": [{"dep_time": "20:00", "arr_time": "22:00"}]},
    ]
    for r in scenarios:
        got = select_interventions_for_day(
            role="pilot", roster_day=r, date="2026-08-10",
            has_training_today=False,
        )
        assert len(got) <= 3, f"too many interventions for {r}"
