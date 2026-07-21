"""
Phase 2 — Integration tests for apply_resolver_to_workouts equipment gating.

These are STATEFUL against the small approved-pool library. We rely on the
"Goblet Squat" library entry (equipment_type: ['dumbbell', 'kettlebell'])
being present. The tests verify that:
  1. The resolver stats dict includes the new `equipment_failures` and
     `workouts_needs_review` counters.
  2. On a layover with an unknown hotel, matched exercises requiring equipment
     that isn't in "bodyweight-only" get flagged and the workout gets a
     hotel-context change_reason.
  3. On a home day with matching client equipment, no gate failures occur.
  4. On a home day where the client has no equipment, matched exercises
     requiring kit get flagged with a home-context change_reason.
"""
import sys
sys.path.insert(0, "/app/backend")

import asyncio

from feature_v2_resolver import apply_resolver_to_workouts


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_apply_resolver_stats_include_phase2_keys():
    """Stats dict must always include equipment_failures + workouts_needs_review."""
    user = {"id": "TEST_p2_stats", "profile": {"equipment": ["Dumbbells"]}}
    workouts = [{"id": "TEST_wk_stats", "date": "2026-08-01", "exercises": []}]
    stats = _run(apply_resolver_to_workouts(workouts, user=user, roster=None))
    assert "equipment_failures" in stats
    assert "workouts_needs_review" in stats
    assert isinstance(stats["equipment_failures"], int)
    assert isinstance(stats["workouts_needs_review"], int)


def test_apply_resolver_layover_unknown_hotel_flags_matched_ex():
    """Layover + unknown hotel → matched Goblet Squat (needs DB/KB) should fail
    the equipment gate because the fallback is bodyweight-only."""
    user = {
        "id": "TEST_p2_layover_unknown",
        "profile": {"equipment": ["Dumbbells", "Kettlebell"]},  # home has kit
    }
    roster = {
        "id": "TEST_p2_roster_unknown",
        "days": [
            {"date": "2026-07-20", "day_type": "layover"},  # no hotel_id → unknown
            {"date": "2026-07-21", "day_type": "home"},
        ],
    }
    workouts = [{
        "id": "TEST_p2_wk_layover_unknown",
        "date": "2026-07-20",
        "exercises": [
            {"name": "Goblet Squat"},  # in library → will match & then fail gate
        ],
    }]
    stats = _run(apply_resolver_to_workouts(workouts, user=user, roster=roster))
    assert stats["equipment_failures"] >= 1, f"Expected >=1 gate failure, got: {stats}"
    assert stats["workouts_needs_review"] >= 1
    w = workouts[0]
    assert w.get("needs_coach_review") is True
    assert w.get("change_reason")
    assert "Hotel gym is limited" in w["change_reason"]


def test_apply_resolver_home_day_with_kit_passes_gate():
    """Home day + client has required kit → gate passes, no coach review."""
    user = {
        "id": "TEST_p2_home_kit",
        "profile": {"equipment": ["Dumbbells", "Kettlebell"]},
    }
    workouts = [{
        "id": "TEST_p2_wk_home_ok",
        "date": "2026-07-25",
        "exercises": [{"name": "Goblet Squat"}],
    }]
    stats = _run(apply_resolver_to_workouts(workouts, user=user, roster=None))
    assert stats["equipment_failures"] == 0
    assert stats["workouts_needs_review"] == 0
    assert workouts[0].get("needs_coach_review") is not True


def test_apply_resolver_home_day_missing_kit_flags_review():
    """Home day + client has no kit → matched barbell/DB moves fail."""
    user = {
        "id": "TEST_p2_home_bw",
        "profile": {"equipment": ["no equipment"]},
    }
    workouts = [{
        "id": "TEST_p2_wk_home_bw",
        "date": "2026-08-01",
        "exercises": [{"name": "Goblet Squat"}],
    }]
    stats = _run(apply_resolver_to_workouts(workouts, user=user, roster=None))
    assert stats["equipment_failures"] >= 1
    assert workouts[0].get("needs_coach_review") is True
    # Non-hotel context prefix
    assert "Your setup is missing kit" in workouts[0]["change_reason"]
