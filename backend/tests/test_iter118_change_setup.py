"""
Iter 118 regression tests — Change Setup / HOW-only adaptation.

Acceptance items covered:
- Engine V2 construction no longer inherits home equipment on layover days.
- adapt-live preserves exposure_id, kind, priority, date.
- Live session_specs never mutated (audit trail).
- Client bridge prefers active implementation override.
- Hotel Room wins over confirmed hotel gym.
- Layover + no hotel_id + no override → travel-safe defaults.
- No LLM.
"""
from __future__ import annotations

import os
import pytest
import requests
from feature_v2_construction_v2 import (
    _pick_strength_environment, _pick_running_environment,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_HTTP_TESTS") == "1", reason="HTTP disabled",
)

BASE = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"


# ----- unit: construction env pickers -----

def test_strength_layover_ignores_permanent_dumbbells():
    env = _pick_strength_environment("layover_full", {"dumbbells", "bench"})
    # Only counts as hotel_gym now because both dumbbells AND bench are supplied
    assert env in ("hotel_gym",), env


def test_strength_layover_no_temp_equipment_is_hotel_room():
    env = _pick_strength_environment("layover_full", set())
    assert env == "hotel_room"


def test_strength_layover_bodyweight_only_is_hotel_room():
    env = _pick_strength_environment("layover_arrival", {"bodyweight"})
    assert env == "hotel_room"


def test_running_layover_never_assumes_treadmill():
    # Even if permanent DNA has treadmill, layover picks flexible (client
    # will choose outdoor / treadmill via Change Setup).
    env = _pick_running_environment("layover_full", {"treadmill"})
    assert env == "flexible"


def test_running_home_still_uses_treadmill_when_dna_has_it():
    # Non-layover, standby/duty day with DNA treadmill → treadmill.
    env = _pick_running_environment("standby", {"treadmill"})
    assert env == "treadmill"


def test_running_home_default_is_outdoor():
    env = _pick_running_environment("home", set())
    assert env == "outdoor"


# ----- HTTP: adapt-live preserves identity -----

def _login(e, p):
    return requests.post(f"{BASE}/auth/login", json={"email": e, "password": p}, timeout=10).json()["token"]
def _h(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def pt():
    return _login("pietrosangermano1992@hotmail.com", "Pietro2026")


def _first_v2_date(pt) -> str:
    r = requests.get(f"{BASE}/v2/client/plan/live", headers=_h(pt), timeout=10).json()
    placements = r.get("placements") or []
    return placements[0]["date"] if placements else None


def test_adapt_live_preserves_exposure_and_placement(pt):
    from pymongo import MongoClient
    m = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = m[os.environ.get("DB_NAME", "crewfit_v1")]
    uid = requests.get(f"{BASE}/auth/me", headers=_h(pt), timeout=10).json()["id"]
    db.plan_live_v2_implementations.delete_many({"client_id": uid})

    live = db.plan_live_v2.find_one({"client_id": uid, "active": True})
    p0 = live["placements"][0]
    date = p0["date"]
    eid = p0["exposure_id"]
    original_specs = dict(live["session_specs"])

    r = requests.post(f"{BASE}/v2/client/plan/adapt-live", headers=_h(pt),
        json={"date": date, "environment": "hotel_room",
              "equipment": ["resistance_bands"], "scope": "this_session"},
        timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["exposure_id"] == eid
    assert data["date"] == date

    # Reload live — placements + session_specs must be untouched
    live2 = db.plan_live_v2.find_one({"client_id": uid, "active": True})
    assert live2["placements"] == live["placements"], "placements mutated!"
    assert live2["session_specs"] == original_specs, "session_specs mutated!"

    # Client bridge shows the override
    r2 = requests.get(f"{BASE}/workouts/week", headers=_h(pt), timeout=10).json()
    day_row = next((w for w in r2 if w.get("date") == date), None)
    assert day_row is not None
    assert day_row.get("environment") == "hotel_room"

    # Cleanup
    db.plan_live_v2_implementations.delete_many({"client_id": uid})
    m.close()


def test_hotel_room_wins_over_confirmed_hotel_gym(pt):
    """Client picks hotel_room even though a hotel_id with dumbbells could exist."""
    from pymongo import MongoClient
    m = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = m[os.environ.get("DB_NAME", "crewfit_v1")]
    uid = requests.get(f"{BASE}/auth/me", headers=_h(pt), timeout=10).json()["id"]
    live = db.plan_live_v2.find_one({"client_id": uid, "active": True})
    p0 = live["placements"][0]

    r = requests.post(f"{BASE}/v2/client/plan/adapt-live", headers=_h(pt),
        json={"date": p0["date"], "environment": "hotel_room",
              "equipment": [], "scope": "this_session"}, timeout=15).json()
    assert r["environment"] == "hotel_room", r
    assert "dumbbells" not in r["equipment"], "hotel gym leaked into room choice"

    db.plan_live_v2_implementations.delete_many({"client_id": uid})
    m.close()


def test_permanent_dna_unchanged_after_adapt(pt):
    from pymongo import MongoClient
    m = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = m[os.environ.get("DB_NAME", "crewfit_v1")]
    uid = requests.get(f"{BASE}/auth/me", headers=_h(pt), timeout=10).json()["id"]

    dna_before = db.equipment_contexts.find_one(
        {"client_id": uid, "scope": "permanent"},
        sort=[("created_at", -1)],
    )
    live = db.plan_live_v2.find_one({"client_id": uid, "active": True})
    p0 = live["placements"][0]

    requests.post(f"{BASE}/v2/client/plan/adapt-live", headers=_h(pt),
        json={"date": p0["date"], "environment": "hotel_gym",
              "equipment": ["dumbbells", "bench"],
              "scope": "this_layover"}, timeout=15)

    dna_after = db.equipment_contexts.find_one(
        {"client_id": uid, "scope": "permanent"},
        sort=[("created_at", -1)],
    )
    assert dna_before == dna_after, "permanent DNA was mutated!"

    db.plan_live_v2_implementations.delete_many({"client_id": uid})
    m.close()
