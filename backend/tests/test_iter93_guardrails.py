"""
Iter 93 · Phase 3 — Strict post-LLM guardrails tests.

Covers feature_workout_guardrails.py behavior:
  * H_AVOID: banned overhead press → substituted with Landmine Press
  * H_AVOID: banned deep squat → substituted with Box Squat
  * H_OVERLOAD: sets clamped into strength_overload band, reps rewritten
  * H_DURATION: clamped into phase band
  * H_SHAPE: weekly_shape_ideal not met → flagged for coach
  * Endurance workout with matching long_run in batch → shape OK
  * Guardrail preserves recovery / mobility workouts untouched
  * Report totals count healed vs flagged correctly
"""
from feature_workout_guardrails import validate_workout, validate_batch


CTX_BUILD = {
    "live_state": {"avoid_movement_patterns": ["overhead_press", "deep_squat"]},
    "goal_key": "build_muscle",
    "phase": {"key": "build"},
    "strength_overload": {"sets_delta": 1, "reps_target": "8-10", "load_delta_pct": 2.5, "rpe": "7-8"},
}


class TestHAvoid:
    def test_overhead_press_substituted(self):
        w = {"id": "w1", "date": "2026-07-25", "focus": "push", "duration_min": 45,
             "exercises": [{"name": "Barbell Overhead Press", "sets": 4, "reps": 8, "rpe": 8}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["exercises"][0]["name"] == "Landmine Press"
        assert any(x["kind"] == "H_AVOID" for x in v)

    def test_deep_squat_substituted(self):
        w = {"id": "w2", "date": "2026-07-25", "focus": "lower", "duration_min": 45,
             "exercises": [{"name": "ATG Squat", "sets": 3, "reps": 5}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["exercises"][0]["name"] == "Box Squat (parallel)"

    def test_no_avoid_no_change(self):
        ctx = {**CTX_BUILD, "live_state": {"avoid_movement_patterns": []}}
        w = {"id": "w3", "date": "2026-07-25", "focus": "push", "duration_min": 45,
             "exercises": [{"name": "Barbell Overhead Press", "sets": 4, "reps": 8}]}
        h, v = validate_workout(w, ctx)
        assert h["exercises"][0]["name"] == "Barbell Overhead Press"
        # But sets/reps may still be clamped — that's fine


class TestHOverload:
    def test_sets_clamped_high(self):
        w = {"id": "w4", "date": "2026-07-25", "focus": "lower", "duration_min": 45,
             "exercises": [{"name": "Bench Press", "sets": 8, "reps": 8}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["exercises"][0]["sets"] == 5
        assert any(x["kind"] == "H_OVERLOAD" for x in v)

    def test_sets_clamped_low(self):
        w = {"id": "w5", "date": "2026-07-25", "focus": "push", "duration_min": 45,
             "exercises": [{"name": "Bench Press", "sets": 1, "reps": 8}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["exercises"][0]["sets"] == 2

    def test_reps_way_off(self):
        w = {"id": "w6", "date": "2026-07-25", "focus": "push", "duration_min": 45,
             "exercises": [{"name": "Bench Press", "sets": 3, "reps": 25}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["exercises"][0]["reps"] == "8-10"

    def test_endurance_goal_no_overload_clamp(self):
        ctx = {**CTX_BUILD, "goal_key": "event", "strength_overload": None}
        w = {"id": "w7", "date": "2026-07-25", "focus": "long_run", "duration_min": 90,
             "exercises": [{"name": "Long Run Z2", "sets": 1, "reps": "20km"}]}
        h, v = validate_workout(w, ctx)
        # No sets clamping for endurance.
        assert h["exercises"][0]["sets"] == 1


class TestHDuration:
    def test_too_long_clamped(self):
        w = {"id": "w8", "date": "2026-07-25", "focus": "push", "duration_min": 120,
             "exercises": [{"name": "Bench Press", "sets": 3, "reps": 8}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["duration_min"] == 75
        assert any(x["kind"] == "H_DURATION" for x in v)

    def test_too_short_clamped(self):
        w = {"id": "w9", "date": "2026-07-25", "focus": "push", "duration_min": 5,
             "exercises": [{"name": "Bench Press", "sets": 3, "reps": 8}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["duration_min"] == 20

    def test_recovery_short_ok(self):
        w = {"id": "w10", "date": "2026-07-25", "focus": "recovery", "duration_min": 10,
             "exercises": [{"name": "Walk", "sets": 1}]}
        h, v = validate_workout(w, CTX_BUILD)
        assert h["duration_min"] == 10
        assert not any(x["kind"] == "H_DURATION" for x in v)


class TestHShape:
    def test_missing_long_run_flagged(self):
        ctx = {**CTX_BUILD, "goal_key": "event",
               "weekly_shape_ideal": ["long_run", "easy_run", "strength"]}
        batch = [
            {"id": "a", "date": "2026-07-25", "focus": "strength",
             "exercises": [{"name": "Bench", "sets": 3, "reps": 8}]},
            {"id": "b", "date": "2026-07-26", "focus": "strength",
             "exercises": [{"name": "Squat", "sets": 3, "reps": 8}]},
        ]
        result = validate_batch(batch, ctx)
        assert any(x["kind"] == "H_SHAPE" for x in result["report"]["violations"])
        assert result["report"]["flagged"] >= 1

    def test_shape_matched_no_flag(self):
        ctx = {**CTX_BUILD, "goal_key": "event",
               "weekly_shape_ideal": ["long_run", "easy_run"]}
        batch = [
            {"id": "a", "date": "2026-07-25", "focus": "long_run",
             "exercises": [{"name": "Long Run Z2", "sets": 1}]},
            {"id": "b", "date": "2026-07-26", "focus": "easy_run",
             "exercises": [{"name": "Easy Run Z2", "sets": 1}]},
        ]
        result = validate_batch(batch, ctx)
        assert not any(x["kind"] == "H_SHAPE" for x in result["report"]["violations"])


class TestBatchReport:
    def test_report_totals(self):
        batch = [
            # workout 1: banned exercise → healed
            {"id": "a", "date": "2026-07-25", "focus": "push", "duration_min": 45,
             "exercises": [{"name": "Barbell Overhead Press", "sets": 4, "reps": 8}]},
            # workout 2: ok
            {"id": "b", "date": "2026-07-26", "focus": "pull", "duration_min": 45,
             "exercises": [{"name": "Chest-Supported Row", "sets": 3, "reps": 10}]},
            # workout 3: missing shape (batch flagged)
            {"id": "c", "date": "2026-07-27", "focus": "push", "duration_min": 45,
             "exercises": [{"name": "Bench Press", "sets": 3, "reps": 8}]},
        ]
        ctx = {**CTX_BUILD, "weekly_shape_ideal": ["push", "pull", "long_run"]}
        result = validate_batch(batch, ctx)
        rep = result["report"]
        assert rep["total"] == 3
        assert rep["healed"] >= 1  # overhead press was substituted
        assert rep["flagged"] >= 1  # long_run missing


class TestEmptyBatch:
    def test_empty(self):
        result = validate_batch([], {})
        assert result["workouts"] == []
        assert result["report"]["total"] == 0

    def test_none_workout_survives(self):
        result = validate_batch([None, {"id": "x", "date": "2026-07-25", "focus": "push", "exercises": []}], CTX_BUILD)
        # None gets passed through; the empty-exercises workout gets flagged.
        assert result["report"]["total"] == 2
