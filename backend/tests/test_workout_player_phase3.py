"""Phase 3 Workout Player backend tests — cardio interval logging + smart progression + warm-up flags.

Endpoints under test:
- POST /api/workouts/{wid}/sets  (WorkoutSetBody with cardio + warmup fields)
- GET  /api/workouts/{wid}/sets
- GET  /api/exercises/previous?name=... (with progression_hint)
"""
import time
import uuid
import pytest


# ---------------- Fixtures ----------------

@pytest.fixture(scope="module")
def wid(api, base_url, client_auth):
    """Grab a valid workout_id for the client from /workouts/week."""
    r = api.get(f"{base_url}/api/workouts/week", headers=client_auth["headers"], timeout=30)
    assert r.status_code == 200, f"/workouts/week failed: {r.status_code} {r.text[:300]}"
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0, "client has no seeded workouts to use"
    # Pick the first workout row that has a stable id
    for w in rows:
        if w.get("id"):
            return w["id"]
    pytest.skip("No workout with id present for client")


def _post_set(api, base_url, headers, wid, **overrides):
    """Post a workout set with sensible defaults, overridable per-call."""
    payload = {
        "workout_id": wid,
        "exercise_index": 0,
        "exercise_name": overrides.pop("exercise_name", "TEST_Exercise"),
        "set_number": overrides.pop("set_number", 1),
    }
    payload.update(overrides)
    r = api.post(f"{base_url}/api/workouts/{wid}/sets", json=payload, headers=headers, timeout=30)
    return r


# ---------------- Cardio interval logging (Phase 3) ----------------

class TestCardioSetLogging:
    def test_pace_auto_derived_from_duration_and_distance(self, api, base_url, client_auth, wid):
        # 1800s over 5000m → 1800 / (5000/1000) = 360.0 s/km
        r = _post_set(
            api, base_url, client_auth["headers"], wid,
            exercise_name=f"TEST_Cardio_Auto_{uuid.uuid4().hex[:6]}",
            logging_type="cardio",
            duration_sec=1800,
            distance_m=5000,
        )
        assert r.status_code == 200, r.text
        s = r.json()["set"]
        assert s["logging_type"] == "cardio"
        assert s["duration_sec"] == 1800
        assert s["distance_m"] == 5000
        assert s["pace_sec_per_km"] == 360.0, f"expected auto-derived pace 360.0, got {s['pace_sec_per_km']}"

    def test_explicit_pace_preserved(self, api, base_url, client_auth, wid):
        # Server must NOT override caller-supplied pace even if it disagrees with duration/distance.
        r = _post_set(
            api, base_url, client_auth["headers"], wid,
            exercise_name=f"TEST_Cardio_Explicit_{uuid.uuid4().hex[:6]}",
            logging_type="cardio",
            duration_sec=1200,
            distance_m=4000,
            pace_sec_per_km=275.5,
        )
        assert r.status_code == 200, r.text
        s = r.json()["set"]
        assert s["pace_sec_per_km"] == 275.5, f"expected preserved 275.5, got {s['pace_sec_per_km']}"

    def test_duration_only_pace_is_null(self, api, base_url, client_auth, wid):
        # Plank / timed hold: duration but no distance → pace stays null.
        r = _post_set(
            api, base_url, client_auth["headers"], wid,
            exercise_name=f"TEST_Timer_{uuid.uuid4().hex[:6]}",
            logging_type="timer",
            duration_sec=60,
        )
        assert r.status_code == 200, r.text
        s = r.json()["set"]
        assert s["duration_sec"] == 60
        assert s["distance_m"] is None
        assert s["pace_sec_per_km"] is None

    def test_warmup_and_timer_persisted(self, api, base_url, client_auth, wid):
        r = _post_set(
            api, base_url, client_auth["headers"], wid,
            exercise_name=f"TEST_WarmupTimer_{uuid.uuid4().hex[:6]}",
            logging_type="timer",
            duration_sec=45,
            warmup=True,
        )
        assert r.status_code == 200, r.text
        s = r.json()["set"]
        assert s["warmup"] is True
        assert s["logging_type"] == "timer"
        assert s["duration_sec"] == 45

    def test_heart_rate_and_calories_persisted(self, api, base_url, client_auth, wid):
        r = _post_set(
            api, base_url, client_auth["headers"], wid,
            exercise_name=f"TEST_Cardio_HR_{uuid.uuid4().hex[:6]}",
            logging_type="cardio",
            duration_sec=600,
            distance_m=2000,
            heart_rate_avg=142,
            heart_rate_max=168,
            calories=95,
        )
        assert r.status_code == 200, r.text
        s = r.json()["set"]
        assert s["heart_rate_avg"] == 142
        assert s["heart_rate_max"] == 168
        assert s["calories"] == 95

    def test_list_sets_returns_cardio_fields(self, api, base_url, client_auth, wid):
        ex_name = f"TEST_Cardio_List_{uuid.uuid4().hex[:6]}"
        r_post = _post_set(
            api, base_url, client_auth["headers"], wid,
            exercise_name=ex_name,
            logging_type="cardio",
            duration_sec=900,
            distance_m=3000,
            heart_rate_avg=140,
        )
        assert r_post.status_code == 200

        r_list = api.get(
            f"{base_url}/api/workouts/{wid}/sets",
            headers=client_auth["headers"], timeout=30,
        )
        assert r_list.status_code == 200, r_list.text
        rows = r_list.json()["sets"]
        matches = [r for r in rows if r.get("exercise_name") == ex_name]
        assert matches, f"posted set for {ex_name} not returned by list"
        row = matches[-1]
        # All cardio fields must round-trip
        for f in ("logging_type", "duration_sec", "distance_m", "pace_sec_per_km",
                  "heart_rate_avg", "heart_rate_max", "calories", "warmup"):
            assert f in row, f"missing field {f} on listed set: {row}"
        assert row["logging_type"] == "cardio"
        assert row["duration_sec"] == 900
        assert row["distance_m"] == 3000
        assert row["pace_sec_per_km"] == 300.0  # 900 / 3 = 300
        assert row["heart_rate_avg"] == 140


# ---------------- Smart progression algorithm ----------------

def _log_two_sets(api, base_url, headers, wid, ex_name, weight, reps, rpe, target_reps="8"):
    for i in (1, 2):
        r = _post_set(
            api, base_url, headers, wid,
            exercise_name=ex_name,
            set_number=i,
            target_reps=target_reps,
            actual_reps=reps,
            target_weight=weight,
            actual_weight=weight,
            rpe=rpe,
            logging_type="weighted",
        )
        assert r.status_code == 200, r.text
        # tiny gap so created_at ordering is deterministic
        time.sleep(0.02)


class TestProgressionHint:
    def test_progression_increase_when_target_hit_and_rpe_low(self, api, base_url, client_auth, wid):
        ex = f"TEST_Prog_Increase_{uuid.uuid4().hex[:6]}"
        _log_two_sets(api, base_url, client_auth["headers"], wid, ex, weight=80, reps=8, rpe=7.0)

        r = api.get(
            f"{base_url}/api/exercises/previous",
            params={"name": ex},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("suggested_load") == 82.5, f"expected 82.5, got {data.get('suggested_load')}"
        hint = data.get("progression_hint")
        assert hint is not None, "progression_hint missing"
        assert hint["action"] == "increase"
        assert hint["delta_kg"] == 2.5
        assert "Hit target reps" in hint["reason"]
        assert "RPE 7" in hint["reason"]

    def test_progression_hold_when_rpe_high(self, api, base_url, client_auth, wid):
        ex = f"TEST_Prog_Hold_{uuid.uuid4().hex[:6]}"
        _log_two_sets(api, base_url, client_auth["headers"], wid, ex, weight=80, reps=8, rpe=9.0)

        r = api.get(
            f"{base_url}/api/exercises/previous",
            params={"name": ex},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("suggested_load") == 80.0, f"expected 80.0, got {data.get('suggested_load')}"
        hint = data.get("progression_hint")
        assert hint is not None
        assert hint["action"] == "hold"
        assert hint["delta_kg"] == 0.0

    def test_progression_uncertain_when_rpe_missing(self, api, base_url, client_auth, wid):
        ex = f"TEST_Prog_NoRPE_{uuid.uuid4().hex[:6]}"
        # rpe=None → the top_set rpe branch falls through → hold with "log RPE" reason
        _log_two_sets(api, base_url, client_auth["headers"], wid, ex, weight=80, reps=8, rpe=None)

        r = api.get(
            f"{base_url}/api/exercises/previous",
            params={"name": ex},
            headers=client_auth["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("suggested_load") == 80.0
        hint = data.get("progression_hint")
        assert hint is not None
        assert hint["action"] == "hold"
        assert "log RPE" in hint["reason"], f"expected 'log RPE' hint, got: {hint['reason']}"


# ---------------- Regression: existing weighted-set logging still works ----------------

class TestWeightedSetRegression:
    def test_weighted_set_basic_persistence(self, api, base_url, client_auth, wid):
        ex = f"TEST_Weighted_Regr_{uuid.uuid4().hex[:6]}"
        r = _post_set(
            api, base_url, client_auth["headers"], wid,
            exercise_name=ex,
            set_number=1,
            target_reps="5",
            actual_reps=5,
            target_weight=100.0,
            actual_weight=100.0,
            rpe=7.5,
            notes="TEST_regression",
            logging_type="weighted",
        )
        assert r.status_code == 200, r.text
        s = r.json()["set"]
        assert s["exercise_name"] == ex
        assert s["actual_weight"] == 100.0
        assert s["actual_reps"] == 5
        assert s["rpe"] == 7.5
        assert s["notes"] == "TEST_regression"
        # New cardio fields exist but null for a weighted set (except logging_type which we sent)
        assert s["logging_type"] == "weighted"
        assert s["duration_sec"] is None
        assert s["distance_m"] is None
        assert s["pace_sec_per_km"] is None
        assert s["warmup"] is False
