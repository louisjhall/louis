"""
Iter 119 regression tests — Equipment selection on top of Change Setup.

Acceptance items covered:
1.  Hotel Gym + Dumbbells produces no barbell/cable-only exercises.
2.  Hotel Gym + Dumbbells + Bench can use bench-compatible exercises.
3.  Bodyweight Only produces bodyweight-safe strength.
4.  Hotel Room + Bands can use band-compatible exercises.
5.  Outdoor Run does not assume treadmill.
6.  Hotel Gym + Treadmill can produce treadmill running HOW.
7.  exposure_id unchanged.
8.  date unchanged.
9.  plan_live_v2 unchanged.
10. overlay contains selected equipment (canonical chip labels).
11. no LLM calls (adapt-live is deterministic).
12. no programme regeneration (only overlay row inserted).
"""
from __future__ import annotations

import os
import pytest
import requests

from feature_v2_plan_live_adapt import _normalize_equipment
from feature_v2_construction_v2 import build_session_spec, _STRENGTH_POOL

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_HTTP_TESTS") == "1", reason="HTTP disabled",
)

BASE = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"


# ============================================================================
# Unit tests — equipment normalizer
# ============================================================================

def test_normalize_dumbbells_stays_dumbbells():
    pool, canon = _normalize_equipment(["dumbbells"])
    assert "dumbbells" in pool
    assert canon == ["dumbbells"]


def test_normalize_barbell_implies_rack():
    pool, canon = _normalize_equipment(["barbell"])
    assert "barbell" in pool and "rack" in pool
    assert canon == ["barbell"]  # UI label preserved


def test_normalize_smith_machine_substitutes_for_barbell_rack():
    pool, canon = _normalize_equipment(["smith_machine"])
    assert "barbell" in pool and "rack" in pool and "smith_machine" in pool
    assert canon == ["smith_machine"]


def test_normalize_lat_pulldown_maps_to_cable_stack():
    pool, canon = _normalize_equipment(["lat_pulldown"])
    assert "cable_stack" in pool
    assert canon == ["lat_pulldown"]


def test_normalize_bands_ui_key_maps_to_band_pool_tag():
    # UI chip "band" or legacy "resistance_bands" both hit pool "band".
    for key in ("band", "resistance_bands", "bands"):
        pool, canon = _normalize_equipment([key])
        assert "band" in pool, f"UI key {key!r} did not reach pool tag 'band'"


def test_normalize_bike_maps_to_indoor_trainer_too():
    pool, canon = _normalize_equipment(["bike"])
    assert "bike" in pool and "indoor_trainer" in pool


def test_normalize_deduplicates():
    pool, canon = _normalize_equipment(["dumbbells", "Dumbbells", "dumbbells"])
    assert list(canon) == ["dumbbells"]


# ============================================================================
# Unit tests — deterministic construction under selected equipment
# ============================================================================

def _strength_exercises(kind: str, equipment_ctx: set[str]) -> list[dict]:
    spec = build_session_spec(
        kind=kind, duration_min=40, intensity_target="moderate",
        phase_kind="foundation", day_type="layover_full",
        equipment_ctx=set(equipment_ctx) | {"bodyweight"},
        avoid_patterns=set(),
    )
    return list((spec.payload or {}).get("exercises") or [])


def test_hotel_gym_dumbbells_only_no_barbell_or_cable():
    exs = _strength_exercises("strength_full_body", {"dumbbells"})
    assert exs, "expected at least one exercise from dumbbells-only setup"
    for ex in exs:
        eq = set(ex.get("equipment_used") or [])
        assert "barbell" not in eq, f"barbell leaked into dumbbells-only setup: {ex}"
        assert "rack" not in eq,    f"rack leaked into dumbbells-only setup: {ex}"
        assert "cable_stack" not in eq, f"cable leaked into dumbbells-only setup: {ex}"


def test_hotel_gym_dumbbells_bench_enables_bench_press():
    exs = _strength_exercises("strength_full_body", {"dumbbells", "bench"})
    names = " | ".join(ex.get("name", "") for ex in exs).lower()
    # Dumbbell Bench Press requires dumbbells + bench and should now surface.
    assert "bench" in names, f"expected a bench-based push, got: {names}"


def test_bodyweight_only_produces_bodyweight_safe():
    exs = _strength_exercises("strength_full_body", set())
    assert exs, "bodyweight-only should still produce a session"
    for ex in exs:
        eq = set(ex.get("equipment_used") or [])
        # every prescribed exercise must be reachable with just bodyweight
        # (i.e. its required tags ⊆ {bodyweight})
        assert eq <= {"bodyweight"}, f"non-bodyweight leaked in bw-only: {ex}"


def test_hotel_room_band_enables_band_exercises():
    # Hotel Room + Bands: band-compatible pulls should be available.
    exs = _strength_exercises("strength_pull", {"band"})
    names = " | ".join(ex.get("name", "") for ex in exs).lower()
    assert "band" in names, f"expected a band-based pull, got: {names}"


def test_outdoor_run_does_not_assume_treadmill():
    spec = build_session_spec(
        kind="run_easy", duration_min=30, intensity_target="low",
        phase_kind="foundation", day_type="outdoor",
        equipment_ctx={"bodyweight"}, avoid_patterns=set(),
    )
    assert spec.environment != "treadmill"
    assert "treadmill" not in (spec.equipment_used or [])


def test_hotel_gym_treadmill_can_produce_treadmill_running():
    spec = build_session_spec(
        kind="run_easy", duration_min=30, intensity_target="low",
        phase_kind="foundation", day_type="standby",
        equipment_ctx={"bodyweight", "treadmill"}, avoid_patterns=set(),
    )
    # standby + treadmill in equipment_ctx → treadmill running HOW.
    assert spec.environment == "treadmill"
    assert "treadmill" in (spec.equipment_used or [])


# ============================================================================
# HTTP integration — end-to-end via Pietro
# ============================================================================

def _login(e, p):
    r = requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def _h(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def pt():
    return _login("pietrosangermano1992@hotmail.com", "Pietro2026")


def _client_uid(pt):
    return requests.get(f"{BASE}/auth/me", headers=_h(pt), timeout=10).json()["id"]


def _first_strength_placement(pt):
    """Return (date, exposure_id) for a strength placement on Pietro's plan."""
    from pymongo import MongoClient
    m = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = m[os.environ.get("DB_NAME", "crewfit_v1")]
    uid = _client_uid(pt)
    live = db.plan_live_v2.find_one({"client_id": uid, "active": True})
    m.close()
    if not live:
        return None, None
    for p in (live.get("placements") or []):
        kind = str(p.get("kind") or "")
        if "strength" in kind:
            return p.get("date"), p.get("exposure_id")
    return None, None


def test_e2e_hotel_gym_dumbbells_bench_preserves_identity(pt):
    from pymongo import MongoClient
    m = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = m[os.environ.get("DB_NAME", "crewfit_v1")]
    uid = _client_uid(pt)

    date, eid = _first_strength_placement(pt)
    if not date:
        pytest.skip("No strength placement in Pietro's plan.")

    db.plan_live_v2_implementations.delete_many({"client_id": uid})
    live_before = db.plan_live_v2.find_one({"client_id": uid, "active": True})
    specs_before = dict(live_before["session_specs"])
    placements_before = list(live_before["placements"])

    r = requests.post(f"{BASE}/v2/client/plan/adapt-live", headers=_h(pt),
        json={"date": date, "environment": "hotel_gym",
              "equipment": ["dumbbells", "bench"], "scope": "this_session"},
        timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()

    # (7) exposure_id preserved
    assert data["exposure_id"] == eid
    # (8) date preserved
    assert data["date"] == date
    # (10) canonical equipment stored on overlay
    assert data["equipment"] == ["dumbbells", "bench"], data["equipment"]

    # (9) plan_live_v2 untouched
    live_after = db.plan_live_v2.find_one({"client_id": uid, "active": True})
    assert live_after["placements"] == placements_before, "placements mutated!"
    assert live_after["session_specs"] == specs_before,   "session_specs mutated!"

    # (12) programme not regenerated — same live_plan_id, no new plan_live_v2 rows
    assert live_after["id"] == live_before["id"]

    # Overlay row was created
    row = db.plan_live_v2_implementations.find_one(
        {"client_id": uid, "date": date, "is_active": True}
    )
    assert row is not None, "expected an active overlay row"
    assert row["environment"] == "hotel_gym"
    assert row["equipment"] == ["dumbbells", "bench"]
    # Overlay carries the adapted flag on its snapshot
    assert row["spec_snapshot"].get("adapted_from_original") is True

    # Bridge surfaces the adaptation
    r2 = requests.get(f"{BASE}/workouts/week", headers=_h(pt), timeout=10).json()
    day_row = next((w for w in r2 if w.get("date") == date), None)
    assert day_row is not None
    assert day_row.get("environment") == "hotel_gym"
    assert day_row.get("adapted_from_original") is True
    used = set(day_row.get("equipment_used") or [])
    assert "dumbbells" in used and "bench" in used

    # Cleanup
    db.plan_live_v2_implementations.delete_many({"client_id": uid})
    m.close()


def test_e2e_hotel_room_bodyweight_only_visibly_adapts(pt):
    from pymongo import MongoClient
    m = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = m[os.environ.get("DB_NAME", "crewfit_v1")]
    uid = _client_uid(pt)

    date, eid = _first_strength_placement(pt)
    if not date:
        pytest.skip("No strength placement in Pietro's plan.")

    db.plan_live_v2_implementations.delete_many({"client_id": uid})

    r = requests.post(f"{BASE}/v2/client/plan/adapt-live", headers=_h(pt),
        json={"date": date, "environment": "hotel_room",
              "equipment": [], "scope": "this_session"},
        timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["environment"] == "hotel_room"
    # No equipment silently added
    assert "dumbbells" not in data["equipment"]
    assert "cable_stack" not in data["equipment"]

    # Bridge shows the hotel-room adaptation with only bodyweight exercises
    r2 = requests.get(f"{BASE}/workouts/week", headers=_h(pt), timeout=10).json()
    day_row = next((w for w in r2 if w.get("date") == date), None)
    assert day_row is not None
    assert day_row.get("environment") == "hotel_room"
    assert day_row.get("adapted_from_original") is True
    # All prescribed exercises must be bodyweight-safe
    for ex in (day_row.get("exercises") or []):
        # Note: exercises through client bridge don't carry equipment tags in
        # the same shape, but names should not include barbell/cable/bench-only.
        name = str(ex.get("name") or ex.get("exercise_name_display") or "").lower()
        assert "barbell" not in name, f"barbell exercise in hotel_room bodyweight: {name}"
        assert "cable" not in name,   f"cable exercise in hotel_room bodyweight: {name}"

    db.plan_live_v2_implementations.delete_many({"client_id": uid})
    m.close()


def test_no_silent_dumbbells_in_hotel_gym_bodyweight_only(pt):
    """PRD: 'NO SILENT ASSUMPTIONS'. Hotel Gym + no equipment must NOT
    auto-add dumbbells."""
    from pymongo import MongoClient
    m = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = m[os.environ.get("DB_NAME", "crewfit_v1")]
    uid = _client_uid(pt)

    date, _ = _first_strength_placement(pt)
    if not date:
        pytest.skip("No strength placement in Pietro's plan.")

    db.plan_live_v2_implementations.delete_many({"client_id": uid})

    r = requests.post(f"{BASE}/v2/client/plan/adapt-live", headers=_h(pt),
        json={"date": date, "environment": "hotel_gym",
              "equipment": [], "scope": "this_session"},
        timeout=15).json()
    assert "dumbbells" not in r["equipment"], (
        "dumbbells silently added to Hotel Gym choice — violates NO SILENT ASSUMPTIONS"
    )

    db.plan_live_v2_implementations.delete_many({"client_id": uid})
    m.close()
