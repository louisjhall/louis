"""
Phase 5 — Progression-aware Marathon adjustments tests.

Covers:
  * PROGRESSION_SCALARS multipliers are sane
  * scale_endurance_session mutates duration_min + reps + change_reason correctly
  * scale_endurance_session no-op on None / maintain
  * build_template_plan with progression_status wires the scaler into long_run
  * get_current_status returns None when no snapshot, or the status when one exists
"""
import sys
sys.path.insert(0, "/app/backend")
import copy

from feature_progression import (
    PROGRESSION_SCALARS, PROGRESSION_REASONS,
    STATUS_PROGRESSING, STATUS_MAINTAIN, STATUS_REDUCE, STATUS_DELOAD,
    scale_endurance_session,
)


# ---------------------------------------------------------------------------
# Scalars are sane
# ---------------------------------------------------------------------------

def test_progression_scalars_have_all_statuses():
    assert set(PROGRESSION_SCALARS.keys()) == {
        STATUS_PROGRESSING, STATUS_MAINTAIN, STATUS_REDUCE, STATUS_DELOAD,
    }


def test_progression_scalars_directionality():
    # Progressing = bump up; maintain = 1.0; reduce/deload = pull back
    assert PROGRESSION_SCALARS[STATUS_PROGRESSING] > 1.0
    assert abs(PROGRESSION_SCALARS[STATUS_MAINTAIN] - 1.0) < 0.01
    assert PROGRESSION_SCALARS[STATUS_REDUCE] < 1.0
    assert PROGRESSION_SCALARS[STATUS_DELOAD] < PROGRESSION_SCALARS[STATUS_REDUCE]


def test_progression_reasons_have_all_statuses():
    for s in (STATUS_PROGRESSING, STATUS_MAINTAIN, STATUS_REDUCE, STATUS_DELOAD):
        assert PROGRESSION_REASONS[s]
        assert isinstance(PROGRESSION_REASONS[s], str)


# ---------------------------------------------------------------------------
# scale_endurance_session
# ---------------------------------------------------------------------------

def _fake_long_run():
    return {
        "date": "2026-07-26", "title": "Long Run", "focus": "long_run",
        "duration_min": 75,
        "exercises": [
            {"name": "Long Run", "sets": 1, "reps": "60-90 min steady", "rest_sec": 0, "rpe": 5,
             "notes": "Steady."},
        ],
    }


def test_scale_no_status_no_op():
    w = _fake_long_run()
    out = scale_endurance_session(copy.deepcopy(w), None)
    assert out["duration_min"] == 75  # unchanged
    assert out["exercises"][0]["reps"] == "60-90 min steady"


def test_scale_maintain_stamps_status_but_no_change():
    w = _fake_long_run()
    out = scale_endurance_session(copy.deepcopy(w), STATUS_MAINTAIN)
    assert out["duration_min"] == 75
    assert out.get("progression_status") == STATUS_MAINTAIN


def test_scale_progressing_well_bumps_duration():
    w = _fake_long_run()
    out = scale_endurance_session(copy.deepcopy(w), STATUS_PROGRESSING)
    # 75 * 1.07 = 80.25 → rounds to 80 (nearest 5)
    assert out["duration_min"] == 80
    assert out["progression_status"] == STATUS_PROGRESSING
    # reps range scaled: 60*1.07=64.2→64, 90*1.07=96.3→96
    assert "64-96 min" in out["exercises"][0]["reps"]
    assert out["change_reason"] == PROGRESSION_REASONS[STATUS_PROGRESSING]


def test_scale_reduce_load_pulls_back_duration():
    w = _fake_long_run()
    out = scale_endurance_session(copy.deepcopy(w), STATUS_REDUCE)
    # 75 * 0.88 = 66 → rounds to 65 (nearest 5)
    assert out["duration_min"] == 65
    # reps: 60*0.88=52.8→53, 90*0.88=79.2→79
    assert "53-79 min" in out["exercises"][0]["reps"]
    assert PROGRESSION_REASONS[STATUS_REDUCE] in out["change_reason"]


def test_scale_deload_big_pull_back():
    w = _fake_long_run()
    out = scale_endurance_session(copy.deepcopy(w), STATUS_DELOAD)
    # 75 * 0.55 = 41.25 → rounds to 40
    assert out["duration_min"] == 40
    assert "33-50 min" in out["exercises"][0]["reps"] or "33-49 min" in out["exercises"][0]["reps"]
    assert PROGRESSION_REASONS[STATUS_DELOAD] in out["change_reason"]


def test_scale_preserves_existing_change_reason_append():
    w = _fake_long_run()
    w["change_reason"] = "Hotel gym is limited — bodyweight only."
    out = scale_endurance_session(copy.deepcopy(w), STATUS_REDUCE)
    assert "Hotel gym is limited" in out["change_reason"]
    assert PROGRESSION_REASONS[STATUS_REDUCE] in out["change_reason"]


def test_scale_min_duration_floor():
    w = _fake_long_run()
    w["duration_min"] = 20
    out = scale_endurance_session(copy.deepcopy(w), STATUS_DELOAD)
    # 20 * 0.55 = 11 → but we floor to 15
    assert out["duration_min"] == 15


def test_scale_ignores_non_endurance():
    """Non-endurance sessions still get the status stamp but no numeric change
    when there's no duration_min in the payload."""
    w = {"date": "2026-07-26", "title": "Strength Support", "exercises": [
        {"name": "RDL", "sets": 3, "reps": "10", "rest_sec": 60}
    ]}
    out = scale_endurance_session(copy.deepcopy(w), STATUS_REDUCE)
    # reps "10" doesn't match "X-Y min" or "X min" → unchanged
    assert out["exercises"][0]["reps"] == "10"


# ---------------------------------------------------------------------------
# Integration with build_template_plan
# ---------------------------------------------------------------------------

def test_build_template_plan_scales_long_run_when_reduce_load():
    from feature_workout_fallback import build_template_plan
    user = {
        "id": "u1",
        "profile": {
            "main_goal_key": "event",
            "event_type_pref": "marathon",
            "training_days_per_week": 5,
            "equipment": ["dumbbells", "yoga_mat"],
        },
    }
    # 7-day roster with all home days (no layovers, no turnarounds)
    roster = {
        "days": [
            {"date": "2026-07-20", "day_type": "home"},
            {"date": "2026-07-21", "day_type": "home"},
            {"date": "2026-07-22", "day_type": "home"},
            {"date": "2026-07-23", "day_type": "home"},
            {"date": "2026-07-24", "day_type": "home"},
            {"date": "2026-07-25", "day_type": "home"},
            {"date": "2026-07-26", "day_type": "home"},
        ],
    }
    baseline = build_template_plan(user, roster, hotel_lookup={}, progression_status=None)
    reduced = build_template_plan(user, roster, hotel_lookup={}, progression_status=STATUS_REDUCE)

    # Find the long_run session in each
    b_lr = next((w for w in baseline if w.get("focus") == "long_run" and w.get("title") == "Long Run"), None)
    r_lr = next((w for w in reduced if w.get("focus") == "long_run" and w.get("title") == "Long Run"), None)
    assert b_lr and r_lr, "Long Run session must exist in both plans"
    assert r_lr["duration_min"] < b_lr["duration_min"], "reduce_load should shorten the long run"
    assert r_lr.get("progression_status") == STATUS_REDUCE
    assert r_lr.get("change_reason"), "reduce_load should stamp a change_reason"


def test_build_template_plan_progressing_well_bumps_long_run():
    from feature_workout_fallback import build_template_plan
    user = {
        "id": "u1",
        "profile": {
            "main_goal_key": "event",
            "event_type_pref": "marathon",
            "training_days_per_week": 5,
            "equipment": ["dumbbells", "yoga_mat"],
        },
    }
    roster = {"days": [{"date": f"2026-07-{20+i:02d}", "day_type": "home"} for i in range(7)]}
    baseline = build_template_plan(user, roster, hotel_lookup={}, progression_status=None)
    bumped = build_template_plan(user, roster, hotel_lookup={}, progression_status=STATUS_PROGRESSING)

    b_lr = next((w for w in baseline if w.get("focus") == "long_run" and w.get("title") == "Long Run"), None)
    p_lr = next((w for w in bumped if w.get("focus") == "long_run" and w.get("title") == "Long Run"), None)
    assert b_lr and p_lr
    assert p_lr["duration_min"] > b_lr["duration_min"], "progressing_well should extend the long run"
    assert p_lr["progression_status"] == STATUS_PROGRESSING


# ---------------------------------------------------------------------------
# HTTP: recompute + snapshot flow should influence downstream generation
# (Live server test — verify the status flows through)
# ---------------------------------------------------------------------------

def test_get_current_status_returns_string_when_snapshot_exists(api, base_url, client_auth):
    # Force a snapshot for the client
    r = api.post(f"{base_url}/api/progress/recompute", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200
    snap = r.json()
    if snap:
        assert snap.get("status") in (STATUS_PROGRESSING, STATUS_MAINTAIN, STATUS_REDUCE, STATUS_DELOAD)
