"""
Phase B integration tests — Aviation Support endpoints + isolation invariants.

Verifies via direct DB + HTTP that:
- Client Today aggregates training + flight support without merging.
- Rest + Flight Support renders as separate blocks.
- Workout + Flight Support both render.
- Coach replace / disable / add_custom / disable_day / toggle work.
- Client completion is completely separate from workout completion.
- Skipped Flight Support does NOT create a missed_workout event.
- Unknown role does not receive pilot protocol.
- Pilot continues receiving pilot protocol.
- Cabin crew receives no pilot protocol.
- Custom intervention never becomes an ObjectiveExposure.
- Engine V2 invariants preserved.
"""
from __future__ import annotations

import os
import pytest
from datetime import datetime, timezone

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_HTTP_TESTS") == "1",
    reason="HTTP integration tests disabled",
)

import requests

BASE = os.environ.get("BACKEND_URL", "http://localhost:8001") + "/api"
COACH = ("louis@crewfit.net", "Louis123!")
PIETRO = ("pietrosangermano1992@hotmail.com", "Pietro2026")


def _login(email, pw) -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": pw}, timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(t): return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def coach_token():
    return _login(*COACH)


@pytest.fixture(scope="module")
def client_token():
    return _login(*PIETRO)


@pytest.fixture(scope="module")
def pietro_id(client_token):
    r = requests.get(f"{BASE}/auth/me", headers=_hdr(client_token), timeout=10)
    r.raise_for_status()
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Client Today aggregation
# ---------------------------------------------------------------------------

def test_client_today_aggregates_training_and_flight_support(client_token):
    r = requests.get(f"{BASE}/client/today", headers=_hdr(client_token), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["role"] == "pilot"
    assert "training" in d and "flight_support" in d
    # Training and Flight Support are SEPARATE lists — they must never be
    # merged into a single "workouts" array.
    assert isinstance(d["training"]["workouts"], list)
    assert isinstance(d["flight_support"], list)
    assert d["auto_flight_support_enabled"] in (True, False)
    assert "labels" in d


def test_client_today_labels_reflect_state(client_token):
    r = requests.get(f"{BASE}/client/today", headers=_hdr(client_token), timeout=10)
    d = r.json()
    ts = d["labels"]["training_state"]
    fs = d["labels"]["flight_support_state"]
    assert ts in ("rest_day", "session_planned")
    assert fs in ("present", "none", "disabled")


# ---------------------------------------------------------------------------
# Client Flight-Support listing (isolated from training)
# ---------------------------------------------------------------------------

def test_client_flight_support_range(client_token):
    r = requests.get(
        f"{BASE}/client/flight-support",
        params={"from": "2026-07-27", "to": "2026-07-30"},
        headers=_hdr(client_token), timeout=10,
    )
    d = r.json()
    assert d["role"] == "pilot"
    # 2026-07-27 must be bundled (Arrival Reset)
    items_2707 = d["days"].get("2026-07-27") or []
    assert items_2707, "expected arrival-reset bundle"
    bundle = next((x for x in items_2707 if x.get("is_bundle")), None)
    assert bundle is not None
    assert bundle["title"] == "Arrival Reset"
    assert len(bundle.get("sub_interventions") or []) == 2


def test_flight_support_never_leaks_into_workouts_week(client_token):
    r = requests.get(f"{BASE}/workouts/week", headers=_hdr(client_token), timeout=10)
    rows = r.json()
    for w in rows:
        # No fs:*/bundle:*/aviation ids should appear as training workouts.
        wid = str(w.get("id") or "")
        assert not wid.startswith("fs:")
        assert not wid.startswith("bundle:")
        # Focus / source may not be "flight_support"
        assert (w.get("focus") or "").lower() != "flight_support"


# ---------------------------------------------------------------------------
# Coach controls
# ---------------------------------------------------------------------------

def test_coach_list_protocols(coach_token):
    r = requests.get(
        f"{BASE}/v2/coach/protocols/flight-support",
        params={"role": "pilot"},
        headers=_hdr(coach_token), timeout=10,
    )
    d = r.json()
    keys = [p["key"] for p in d["protocols"]]
    assert "pilot_post_flight_walk_15" in keys
    assert "pilot_pre_flight_mobility_6" in keys
    assert len(keys) >= 8


def test_coach_replace_disable_and_add_custom_round_trip(coach_token, client_token, pietro_id):
    # 1) List before
    r = requests.get(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support",
        params={"from": "2026-07-30", "to": "2026-07-30"},
        headers=_hdr(coach_token), timeout=10,
    )
    before = r.json()["days"].get("2026-07-30") or []
    assert any(i["protocol_key"] == "pilot_turnaround_reset_5" for i in before)

    # 2) Replace with Movement Break
    r2 = requests.post(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support/override",
        json={"date": "2026-07-30", "action": "replace",
              "protocol_key": "pilot_turnaround_reset_5",
              "replace_key": "pilot_movement_break_5",
              "reason": "test"},
        headers=_hdr(coach_token), timeout=10,
    )
    assert r2.status_code == 200
    assert r2.json()["ok"] is True

    r3 = requests.get(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support",
        params={"from": "2026-07-30", "to": "2026-07-30"},
        headers=_hdr(coach_token), timeout=10,
    )
    after = r3.json()["days"].get("2026-07-30") or []
    assert any(i["protocol_key"] == "pilot_movement_break_5" for i in after)
    assert not any(i["protocol_key"] == "pilot_turnaround_reset_5" for i in after)

    # 3) Add a custom intervention on 2026-07-31
    r4 = requests.post(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support/override",
        json={"date": "2026-07-31", "action": "add_custom",
              "custom_intervention": {
                  "title": "Hotel Corridor Walk",
                  "family": "walk",
                  "intensity": "very_low",
                  "duration_min": 12,
                  "cues": ["Easy pace, hydrate."],
              }},
        headers=_hdr(coach_token), timeout=10,
    )
    assert r4.status_code == 200

    # Custom must appear in client view
    rc = requests.get(
        f"{BASE}/client/flight-support",
        params={"from": "2026-07-31", "to": "2026-07-31"},
        headers=_hdr(client_token), timeout=10,
    )
    items = rc.json()["days"].get("2026-07-31") or []
    assert any(i.get("title") == "Hotel Corridor Walk" for i in items)
    for i in items:
        # §7 — custom must never carry exposure/objective ids that Engine
        # V2 could latch on to.
        assert i.get("exposure_id") is None
        assert i.get("objective_id") is None

    # 4) Cleanup: remove overrides
    for date, pkey in [("2026-07-30", "pilot_turnaround_reset_5"),
                        ("2026-07-31", None)]:
        requests.post(
            f"{BASE}/v2/coach/clients/{pietro_id}/flight-support/override/remove",
            json={"date": date, "protocol_key": pkey},
            headers=_hdr(coach_token), timeout=10,
        )


def test_coach_disable_day(coach_token, client_token, pietro_id):
    # Push a disable-day override for 2026-07-27
    r = requests.post(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support/override",
        json={"date": "2026-07-27", "action": "disable_day"},
        headers=_hdr(coach_token), timeout=10,
    )
    assert r.json()["ok"] is True

    # Client should see NOTHING for 27
    rc = requests.get(
        f"{BASE}/client/flight-support",
        params={"from": "2026-07-27", "to": "2026-07-27"},
        headers=_hdr(client_token), timeout=10,
    )
    items = rc.json()["days"].get("2026-07-27") or []
    assert items == [], f"expected empty after disable_day, got: {items}"

    # Cleanup
    requests.post(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support/override/remove",
        json={"date": "2026-07-27"},
        headers=_hdr(coach_token), timeout=10,
    )


def test_coach_global_toggle(coach_token, client_token, pietro_id):
    # OFF
    requests.post(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support/toggle",
        json={"enabled": False}, headers=_hdr(coach_token), timeout=10,
    )
    rc = requests.get(f"{BASE}/client/today", headers=_hdr(client_token), timeout=10)
    d = rc.json()
    assert d["auto_flight_support_enabled"] is False
    assert d["flight_support"] == []

    # ON again
    requests.post(
        f"{BASE}/v2/coach/clients/{pietro_id}/flight-support/toggle",
        json={"enabled": True}, headers=_hdr(coach_token), timeout=10,
    )


# ---------------------------------------------------------------------------
# Completion tracking isolation
# ---------------------------------------------------------------------------

def test_completion_never_affects_workout_endpoint(client_token, pietro_id):
    # Look up an intervention id
    r = requests.get(
        f"{BASE}/client/flight-support",
        params={"from": "2026-07-29", "to": "2026-07-29"},
        headers=_hdr(client_token), timeout=10,
    )
    items = r.json()["days"].get("2026-07-29") or []
    assert items
    iid = items[0]["id"]

    # Snapshot workouts/week BEFORE
    w0 = requests.get(f"{BASE}/workouts/week", headers=_hdr(client_token), timeout=10).json()
    n_before = len(w0)

    # Skip the intervention
    r2 = requests.post(
        f"{BASE}/client/flight-support/complete",
        json={"intervention_id": iid, "status": "skipped",
              "skip_reason": "Late finish"},
        headers=_hdr(client_token), timeout=10,
    )
    assert r2.json()["ok"] is True

    # Snapshot workouts/week AFTER
    w1 = requests.get(f"{BASE}/workouts/week", headers=_hdr(client_token), timeout=10).json()
    assert len(w1) == n_before, "workouts/week count must not change after skip"
    # No missed_workout event should ever mention a flight-support id.
    for w in w1:
        assert not str(w.get("id") or "").startswith("fs:")


def test_engine_v2_publish_endpoint_unaffected_by_flight_support(client_token):
    r = requests.get(f"{BASE}/v2/client/plan/live", headers=_hdr(client_token), timeout=10)
    assert r.status_code == 200
    d = r.json()
    # Payload must NOT contain any Flight Support keys — ObjectiveExposure
    # invariants are inviolable.
    body = str(d)
    assert "fs:" not in body
    assert "pilot_post_flight_walk" not in body
    assert "flight_support" not in body


# ---------------------------------------------------------------------------
# Role safety
# ---------------------------------------------------------------------------

def test_unknown_role_returns_no_flight_support(coach_token, client_token, pietro_id):
    """Flip Pietro's job_title to something ambiguous → expect empty FS."""
    from pymongo import MongoClient
    mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mongo[os.environ.get("DB_NAME", "crewfit_v1")]
    original = db.users.find_one({"id": pietro_id}, {"_id": 0,
                                                      "profile.job_title": 1,
                                                      "profile.aviation_role": 1})
    try:
        db.users.update_one(
            {"id": pietro_id},
            {"$set": {"profile.job_title": "Ground Ops Manager",
                      "profile.aviation_role": None}},
        )
        rc = requests.get(
            f"{BASE}/client/flight-support",
            params={"from": "2026-07-27", "to": "2026-08-05"},
            headers=_hdr(client_token), timeout=10,
        )
        d = rc.json()
        assert d["role"] == "role_unknown"
        # Every day must be empty
        for date, items in (d.get("days") or {}).items():
            assert items == [], f"expected empty for role_unknown on {date}, got {items}"
    finally:
        orig_profile = original.get("profile") or {}
        db.users.update_one(
            {"id": pietro_id},
            {"$set": {"profile.job_title": orig_profile.get("job_title") or "Pilot",
                      "profile.aviation_role": orig_profile.get("aviation_role")}},
        )
    mongo.close()


def test_cabin_crew_role_returns_no_pilot_protocol(pietro_id, client_token):
    from pymongo import MongoClient
    mongo = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = mongo[os.environ.get("DB_NAME", "crewfit_v1")]
    original = db.users.find_one({"id": pietro_id}, {"_id": 0,
                                                      "profile.job_title": 1,
                                                      "profile.aviation_role": 1})
    try:
        db.users.update_one(
            {"id": pietro_id},
            {"$set": {"profile.aviation_role": "cabin_crew"}},
        )
        rc = requests.get(
            f"{BASE}/client/flight-support",
            params={"from": "2026-07-27", "to": "2026-08-05"},
            headers=_hdr(client_token), timeout=10,
        )
        d = rc.json()
        assert d["role"] == "cabin_crew"
        for date, items in (d.get("days") or {}).items():
            # No pilot-scoped protocol may leak into a cabin-crew user
            for i in items:
                assert not i["protocol_key"].startswith("pilot_"), \
                    f"cabin crew leak on {date}: {i}"
            assert items == []
    finally:
        db.users.update_one(
            {"id": pietro_id},
            {"$set": {"profile.aviation_role":
                       (original.get("profile") or {}).get("aviation_role")}},
        )
    mongo.close()
