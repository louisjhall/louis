"""
Phase 2 — Strict Equipment Matching tests.

Covers:
  * required_equipment inference from name + library equipment_type
  * validate_exercise_equipment pass/fail with reason strings
  * normalise_available (list + dict forms, aliases)
  * enforce_equipment_gate mutates workout + sets needs_coach_review
"""
import sys
sys.path.insert(0, "/app/backend")

from feature_equipment_matcher import (
    required_equipment,
    validate_exercise_equipment,
    normalise_available,
    enforce_equipment_gate,
    FULL_GYM_EXPANSION,
)


# ---------------------------------------------------------------------------
# required_equipment inference
# ---------------------------------------------------------------------------

def test_required_barbell_bench_press():
    req = required_equipment({"name": "Barbell Bench Press"})
    # First matching regex wins — "barbell.*bench press" → ("barbell",)
    assert "barbell" in req


def test_required_bench_press_any_bench():
    req = required_equipment({"name": "Dumbbell Bench Press"})
    assert "bench" in req


def test_required_cable_row():
    assert required_equipment({"name": "Cable Row"}) == ("cable_stack",)


def test_required_pull_up():
    assert required_equipment({"name": "Pull-up"}) == ("pull_up_bar",)
    assert required_equipment({"name": "Chin up"}) == ("pull_up_bar",)


def test_required_dumbbell_curl():
    assert required_equipment({"name": "Dumbbell Curl"}) == ("dumbbells",)


def test_required_from_library_equipment_type():
    ex = {"name": "Custom Move", "equipment_type": ["cable_stack"]}
    assert required_equipment(ex) == ("cable_stack",)


def test_required_bodyweight_default():
    # Push-up has no regex hit → empty tuple = bodyweight ok
    assert required_equipment({"name": "Push-up"}) == ()


def test_required_kettlebell_swing():
    assert required_equipment({"name": "Kettlebell Swing"}) == ("kettlebell",)


def test_required_squat_barbell_or_smith():
    req = required_equipment({"name": "Back Squat"})
    assert "barbell" in req and "smith_machine" in req


def test_required_rdl_multi_option():
    req = required_equipment({"name": "Romanian Deadlift"})
    assert "barbell" in req and "dumbbells" in req and "kettlebell" in req


# ---------------------------------------------------------------------------
# validate_exercise_equipment
# ---------------------------------------------------------------------------

def test_validate_pass_bodyweight():
    r = validate_exercise_equipment({"name": "Push-up"}, {"bodyweight"})
    assert r["passes"] is True
    assert r["missing"] == ()
    assert r["reason"] is None


def test_validate_fail_bench_press_no_bench():
    r = validate_exercise_equipment({"name": "Dumbbell Bench Press"}, {"bodyweight", "dumbbells"})
    assert r["passes"] is False
    assert "bench" in r["missing"]
    assert r["reason"] and "bench" in r["reason"].lower()


def test_validate_pass_bench_press_with_bench():
    r = validate_exercise_equipment(
        {"name": "Dumbbell Bench Press"},
        {"bodyweight", "dumbbells", "bench"},
    )
    assert r["passes"] is True


def test_validate_pass_when_any_of_matches():
    # RDL requires barbell OR dumbbells OR kettlebell — client only has kettlebell
    r = validate_exercise_equipment(
        {"name": "Romanian Deadlift"},
        {"bodyweight", "kettlebell"},
    )
    assert r["passes"] is True


def test_validate_fail_cable_no_cable():
    r = validate_exercise_equipment({"name": "Cable Row"}, {"bodyweight", "dumbbells", "bench"})
    assert r["passes"] is False
    assert "cable" in r["reason"].lower()


# ---------------------------------------------------------------------------
# normalise_available
# ---------------------------------------------------------------------------

def test_normalise_available_list_with_aliases():
    got = normalise_available(["DB", "Barbell", "no equipment", "Pull Up Bar"])
    assert "dumbbells" in got
    assert "barbell" in got
    assert "bodyweight" in got
    assert "pull_up_bar" in got


def test_normalise_available_dict_from_hotel():
    got = normalise_available({"dumbbells": True, "treadmill": True, "bench": False})
    assert "dumbbells" in got
    assert "treadmill" in got
    assert "bench" not in got  # False means not available
    assert "bodyweight" in got  # always present


def test_normalise_available_full_gym_marker_expands():
    got = normalise_available(["Hotel Gym"])
    # Should expand to include FULL_GYM_EXPANSION
    assert "barbell" in got
    assert "bench" in got
    assert "cable_stack" in got


def test_normalise_available_none_input():
    got = normalise_available(None)
    assert got == {"bodyweight"}


def test_normalise_available_empty_dict():
    got = normalise_available({})
    assert got == {"bodyweight"}


# ---------------------------------------------------------------------------
# enforce_equipment_gate — mutates workout
# ---------------------------------------------------------------------------

def test_enforce_gate_all_pass_bodyweight_workout():
    w = {
        "id": "w1", "date": "2026-07-21", "title": "Home Bodyweight",
        "exercises": [
            {"name": "Push-up"},
            {"name": "Bird-dog"},
            {"name": "Reverse Lunge"},
        ],
    }
    r = enforce_equipment_gate(w, available={"bodyweight"})
    assert r["fails"] == 0
    assert r["passes"] == 3
    assert r["needs_review"] is False
    assert w.get("needs_coach_review") is not True


def test_enforce_gate_mixed_workout_flags_review():
    w = {
        "id": "w2", "date": "2026-07-22", "title": "Upper Body",
        "exercises": [
            {"name": "Push-up"},                        # pass
            {"name": "Barbell Bench Press"},            # fail — no barbell/bench
            {"name": "Cable Row"},                      # fail — no cable
        ],
    }
    r = enforce_equipment_gate(w, available={"bodyweight", "dumbbells"})
    assert r["fails"] == 2
    assert r["passes"] == 1
    assert r["needs_review"] is True
    assert w.get("needs_coach_review") is True
    assert "Louis will review" in w["change_reason"]
    # Failing exercises get equipment_check="fail" + reason
    fails = [e for e in w["exercises"] if e.get("equipment_check") == "fail"]
    assert len(fails) == 2
    assert all(f.get("equipment_reason") for f in fails)
    assert all(isinstance(f.get("equipment_required"), list) for f in fails)


def test_enforce_gate_hotel_context_reason_uses_hotel_name():
    w = {
        "id": "w3", "date": "2026-07-23", "title": "Hotel Session",
        "exercises": [
            {"name": "Cable Row"},  # will fail — bodyweight-only hotel
        ],
    }
    r = enforce_equipment_gate(w, available={"bodyweight"}, hotel_context=True, hotel_name="Marina Bay Sands")
    assert r["needs_review"] is True
    assert "Marina Bay Sands" in w["change_reason"]
    assert "Hotel gym is limited" in w["change_reason"]


def test_enforce_gate_full_gym_layover_all_pass():
    w = {
        "id": "w4", "date": "2026-07-24", "title": "Layover Full Gym",
        "exercises": [
            {"name": "Dumbbell Bench Press"},
            {"name": "Cable Row"},
            {"name": "Barbell Back Squat"},
        ],
    }
    hotel_eq = normalise_available({"dumbbells": True, "bench": True, "cable_stack": True, "barbell": True})
    r = enforce_equipment_gate(w, available=hotel_eq, hotel_context=True, hotel_name="Le Meridien")
    assert r["fails"] == 0
    assert r["passes"] == 3
    assert w.get("needs_coach_review") is not True


def test_full_gym_expansion_covers_common_lifts():
    # Sanity: any exercise that needs one of the FULL_GYM items should pass
    # when client says "hotel gym" (full_gym_marker expansion).
    for ex_name in ["Dumbbell Bench Press", "Cable Row", "Back Squat", "Pull-up"]:
        r = validate_exercise_equipment({"name": ex_name}, FULL_GYM_EXPANSION | {"bodyweight"})
        assert r["passes"] is True, f"Full gym should cover {ex_name}"
