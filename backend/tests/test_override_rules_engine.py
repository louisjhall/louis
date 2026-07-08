"""Comprehensive tests for the Client Calendar Override Rules Engine.

Covers:
  * All ~10 rule matrix rows (rest / off / mobility / reduce / location_only /
    availability_min edges / feeling_good noop / no-triggers noop)
  * Precedence: coach_locked, completed, missing workout
  * Coach visibility: /api/coach/calendar cells + /api/coach/clients/{id}
    should surface override_tags / override_notes / override_applied /
    overrides[] / change_log[] and be role-gated (403 for client).

The tests hit the live backend on http://localhost:8001 and use MongoDB
directly for state snapshot/restore so each rule is exercised against a
fresh, distinct workout row.
"""

import os
import copy
from datetime import date, timedelta

import pytest
import requests
from pymongo import MongoClient


BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"
COACH_EMAIL = "coach@crewfit.com"
COACH_PW = "Coach123!"

_MONGO = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
_DB = _MONGO[os.environ.get("DB_NAME", "crewfit_v1")]


# ---------------------------------------------------------------------------
# Session-level auth + shared workout allocator
# ---------------------------------------------------------------------------

def _login(email: str, pw: str) -> tuple[str, dict]:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    return j["token"], j["user"]


@pytest.fixture(scope="module")
def client_ctx():
    tok, user = _login(CLIENT_EMAIL, CLIENT_PW)
    return {"token": tok, "user": user, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def coach_ctx():
    tok, user = _login(COACH_EMAIL, COACH_PW)
    return {"token": tok, "user": user, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def future_workouts(client_ctx):
    """Return a list of workout docs whose date is today-or-future, sorted asc."""
    r = requests.get(f"{API}/workouts/week", headers=client_ctx["headers"], timeout=20)
    assert r.status_code == 200, r.text
    today = date.today().isoformat()
    return sorted(
        [w for w in r.json() if w.get("date", "") >= today and not w.get("coach_locked") and not w.get("completed")],
        key=lambda w: w["date"],
    )


@pytest.fixture(scope="module")
def date_pool(future_workouts):
    """Distinct future dates for each test to avoid cross-contamination."""
    return [w["date"] for w in future_workouts]


class DateAllocator:
    """Cyclic allocator — since each test snapshots/restores the workout,
    dates can be safely reused across tests."""

    def __init__(self, dates: list[str]):
        self._dates = list(dates)
        self._idx = 0

    def next(self) -> str:
        if not self._dates:
            pytest.skip("No future workout dates available")
        d = self._dates[self._idx % len(self._dates)]
        self._idx += 1
        return d


@pytest.fixture(scope="module")
def allocator(date_pool):
    return DateAllocator(date_pool)


# ---------------------------------------------------------------------------
# Helpers: snapshot / restore workout doc, cleanup override
# ---------------------------------------------------------------------------

def _snapshot_workout(user_id: str, date_iso: str) -> dict | None:
    return _DB.workouts.find_one({"user_id": user_id, "date": date_iso})


def _restore_workout(snap: dict) -> None:
    if not snap:
        return
    snap = {k: v for k, v in snap.items() if k != "_id"}
    _DB.workouts.update_one(
        {"user_id": snap["user_id"], "date": snap["date"], "id": snap["id"]},
        {"$set": snap},
    )
    # Clear any override_* fields that weren't in the snapshot
    unset = {}
    for k in ("override_applied", "override_generated", "override_reason"):
        if k not in snap:
            unset[k] = ""
    if unset:
        _DB.workouts.update_one({"id": snap["id"]}, {"$unset": unset})


def _clear_override(client_headers: dict, date_iso: str) -> None:
    requests.delete(f"{API}/calendar/day-override?date={date_iso}", headers=client_headers, timeout=10)


@pytest.fixture
def target(request, allocator, client_ctx):
    """Allocate a fresh date + snapshot the workout, restore on teardown."""
    d = allocator.next()
    snap = _snapshot_workout(client_ctx["user"]["id"], d)
    assert snap, f"No workout found on {d} to test against"
    _clear_override(client_ctx["headers"], d)

    yield {"date": d, "snapshot": copy.deepcopy(snap), "wid": snap["id"]}

    _clear_override(client_ctx["headers"], d)
    _restore_workout(snap)


def _post_override(client_ctx, date_iso, **payload) -> dict:
    body = {"date": date_iso, **payload}
    r = requests.post(f"{API}/calendar/day-override", json=body, headers=client_ctx["headers"], timeout=15)
    assert r.status_code == 200, f"day-override POST failed: {r.status_code} {r.text}"
    return r.json()


def _get_workout(client_ctx, wid) -> dict:
    r = requests.get(f"{API}/workouts/{wid}", headers=client_ctx["headers"], timeout=10)
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Rules Matrix
# ---------------------------------------------------------------------------

class TestRulesMatrix:
    """Each test verifies one row of the rules matrix from the review request."""

    # --- REST ---
    @pytest.mark.parametrize("payload,label", [
        ({"tags": ["sick"]}, "tags=sick"),
        ({"day_type": "sick"}, "day_type=sick"),
        ({"tags": ["injured"]}, "tags=injured"),
        ({"day_type": "injury"}, "day_type=injury"),
        ({"training_preference": "rest"}, "pref=rest"),
    ])
    def test_rest_variants(self, client_ctx, target, payload, label):
        resp = _post_override(client_ctx, target["date"], **payload)
        adj = resp["adjustment"]
        assert adj["action"] == "rest", f"{label}: action={adj['action']} reason={adj.get('reason')}"
        assert adj["changed"] is True
        assert adj["new_title"] == "Rest & Recovery"
        assert adj["new_duration"] == 0
        assert adj["new_day_load"] == "green"
        # Verify the workout doc was mutated in-place (id preserved)
        w = _get_workout(client_ctx, target["wid"])
        assert w["id"] == target["wid"]
        assert w["title"] == "Rest & Recovery"
        assert w["exercises"] == []
        assert w["duration_min"] == 0
        assert w["day_load"] == "green"
        assert w.get("focus") == "rest"
        assert w.get("override_applied") is True
        assert w.get("override_generated") is True
        assert w.get("override_reason")

    # --- OFF ---
    @pytest.mark.parametrize("payload,label", [
        ({"tags": ["annual_leave"]}, "tags=annual_leave"),
        ({"day_type": "annual_leave"}, "day_type=annual_leave"),
        ({"tags": ["holiday"]}, "tags=holiday"),
        ({"day_type": "holiday"}, "day_type=holiday"),
        ({"day_type": "family"}, "day_type=family"),
    ])
    def test_off_variants(self, client_ctx, target, payload, label):
        resp = _post_override(client_ctx, target["date"], **payload)
        adj = resp["adjustment"]
        assert adj["action"] == "off", f"{label}: action={adj['action']}"
        assert adj["changed"] is True
        assert adj["new_title"] == "Off Day"
        assert adj["new_duration"] == 0
        assert adj["new_day_load"] == "grey"
        w = _get_workout(client_ctx, target["wid"])
        assert w["title"] == "Off Day"
        assert w["duration_min"] == 0
        assert w["day_load"] == "grey"
        assert w.get("focus") == "off"
        assert w["exercises"] == []
        assert w.get("override_generated") is True

    # --- MOBILITY ---
    @pytest.mark.parametrize("payload,label", [
        ({"tags": ["poor_sleep"]}, "tags=poor_sleep"),
        ({"tags": ["need_rest"]}, "tags=need_rest"),
        ({"tags": ["high_stress"]}, "tags=high_stress"),
        ({"tags": ["family_commitment"]}, "tags=family_commitment"),
        ({"tags": ["childcare"]}, "tags=childcare"),
        ({"training_preference": "mobility"}, "pref=mobility"),
    ])
    def test_mobility_variants(self, client_ctx, target, payload, label):
        resp = _post_override(client_ctx, target["date"], **payload)
        adj = resp["adjustment"]
        assert adj["action"] == "mobility", f"{label}: action={adj['action']}"
        assert adj["changed"] is True
        assert adj["new_title"] == "Light Mobility & Stretch"
        assert adj["new_duration"] == 15
        assert adj["new_day_load"] == "green"
        w = _get_workout(client_ctx, target["wid"])
        assert w["title"] == "Light Mobility & Stretch"
        assert w["duration_min"] == 15
        assert w["day_load"] == "green"
        assert w.get("focus") == "mobility"
        assert len(w["exercises"]) == 5, f"expected exactly 5 mobility exercises, got {len(w['exercises'])}"
        assert w.get("override_generated") is True

    # --- REDUCE ---
    @pytest.mark.parametrize("payload,label", [
        ({"training_preference": "reduce"}, "pref=reduce"),
        ({"tags": ["limited_time"]}, "tags=limited_time"),
        ({"availability_min": 15}, "avail_min=15"),
        ({"availability_min": 1}, "avail_min=1"),
        ({"availability_min": 20}, "avail_min=20"),
    ])
    def test_reduce_variants(self, client_ctx, target, payload, label):
        snap = target["snapshot"]
        orig_exercises = snap.get("exercises") or []
        orig_duration = int(snap.get("duration_min") or 0)
        orig_load = snap.get("day_load")

        resp = _post_override(client_ctx, target["date"], **payload)
        adj = resp["adjustment"]
        assert adj["action"] == "reduce", f"{label}: action={adj['action']}"
        assert adj["changed"] is True

        w = _get_workout(client_ctx, target["wid"])
        # Sets decrement by 1 (min 1)
        new_ex = w.get("exercises") or []
        assert len(new_ex) == len(orig_exercises), "reduce should preserve exercise count"
        for orig_e, new_e in zip(orig_exercises, new_ex):
            try:
                os_sets = int(orig_e.get("sets") or 0)
                ns_sets = int(new_e.get("sets") or 0)
            except Exception:
                continue
            if os_sets > 1:
                assert ns_sets == max(1, os_sets - 1), f"sets not decremented: {os_sets} -> {ns_sets}"
        # duration ~65% of original (min 15)
        if orig_duration:
            expected = max(15, int(orig_duration * 0.65))
            assert w["duration_min"] == expected, f"{label}: dur {w['duration_min']} != expected {expected} (orig={orig_duration})"
        # day_load decreases one step
        expected_load = {"red": "amber", "amber": "green"}.get(orig_load, orig_load)
        assert w["day_load"] == expected_load, f"{label}: day_load {orig_load} -> {w['day_load']} expected {expected_load}"
        assert w.get("override_generated") is True

    # --- availability_min == 0 → REST ---
    def test_availability_zero_is_rest(self, client_ctx, target):
        resp = _post_override(client_ctx, target["date"], availability_min=0)
        adj = resp["adjustment"]
        # availability_min == 0 is currently classified before the reduce branch —
        # but the code checks `if avail is not None` after reduce; look at server.py:
        # Actually order is: rest → off → mobility → LIGHT → reduce/limited_time → avail branch.
        # availability_min=0 does NOT hit "reduce" (since limited_time tag not set + pref not reduce),
        # so it should fall into avail branch and return rest.
        assert adj["action"] == "rest", f"avail=0 action={adj['action']}"
        assert adj["changed"] is True
        w = _get_workout(client_ctx, target["wid"])
        assert w["title"] == "Rest & Recovery"
        assert w["duration_min"] == 0

    # --- LOCATION-ONLY ---
    @pytest.mark.parametrize("payload,expected_loc", [
        ({"tags": ["hotel_gym"]}, "Hotel Gym"),
        ({"tags": ["no_gym"]}, "Hotel Room (Bodyweight)"),
        ({"tags": ["outdoor_run_possible"]}, "Outdoor Run"),
    ])
    def test_location_only_variants(self, client_ctx, target, payload, expected_loc):
        snap = target["snapshot"]
        orig_ex = snap.get("exercises") or []

        resp = _post_override(client_ctx, target["date"], **payload)
        adj = resp["adjustment"]
        assert adj["action"] == "location_only", f"action={adj['action']}"
        assert adj["changed"] is True
        w = _get_workout(client_ctx, target["wid"])
        assert w["location"] == expected_loc
        # exercises should be unchanged (same count and same first exercise name)
        new_ex = w.get("exercises") or []
        assert len(new_ex) == len(orig_ex), "location_only should not change exercise count"
        if orig_ex and new_ex:
            assert new_ex[0].get("name") == orig_ex[0].get("name")

    # --- NOOP: feeling_good only ---
    def test_feeling_good_only_is_noop(self, client_ctx, target):
        snap = target["snapshot"]
        resp = _post_override(client_ctx, target["date"], tags=["feeling_good"])
        adj = resp["adjustment"]
        assert adj["action"] == "noop", f"action={adj['action']}"
        assert adj["changed"] is False
        w = _get_workout(client_ctx, target["wid"])
        # Content unchanged
        assert w["title"] == snap["title"]
        assert w["duration_min"] == snap["duration_min"]
        assert w["day_load"] == snap["day_load"]
        assert len(w.get("exercises") or []) == len(snap.get("exercises") or [])

    # --- NOOP: no triggers ---
    def test_no_triggers_is_noop(self, client_ctx, target):
        snap = target["snapshot"]
        # Provide only notes, no tag/pref/day_type/avail triggers
        resp = _post_override(client_ctx, target["date"], notes="Just a note today")
        adj = resp["adjustment"]
        assert adj["action"] == "noop", f"action={adj['action']}"
        assert adj["changed"] is False
        w = _get_workout(client_ctx, target["wid"])
        assert w["title"] == snap["title"]


# ---------------------------------------------------------------------------
# Precedence tests
# ---------------------------------------------------------------------------

class TestPrecedence:
    def test_coach_locked_short_circuits(self, client_ctx, coach_ctx, target):
        # Lock via coach PATCH
        r = requests.patch(
            f"{API}/workouts/{target['wid']}",
            json={"coach_locked": True},
            headers=coach_ctx["headers"], timeout=10,
        )
        assert r.status_code in (200, 201), r.text
        try:
            resp = _post_override(client_ctx, target["date"], tags=["sick"])
            adj = resp["adjustment"]
            assert adj["changed"] is False, "coach_locked must not mutate workout"
            assert adj["coach_locked"] is True
            assert resp["coach_locked"] is True
            # Workout content NOT changed
            w = _get_workout(client_ctx, target["wid"])
            assert w["title"] == target["snapshot"]["title"], "workout title mutated despite coach_lock"
            assert w.get("coach_locked") is True
        finally:
            requests.patch(
                f"{API}/workouts/{target['wid']}",
                json={"coach_locked": False},
                headers=coach_ctx["headers"], timeout=10,
            )

    def test_completed_workout_short_circuits(self, client_ctx, target):
        # Flip completed=true directly in Mongo (no wire endpoint to un-complete)
        _DB.workouts.update_one({"id": target["wid"]}, {"$set": {"completed": True}})
        try:
            resp = _post_override(client_ctx, target["date"], tags=["sick"])
            adj = resp["adjustment"]
            assert adj["changed"] is False, "completed workout must not mutate"
            w = _get_workout(client_ctx, target["wid"])
            assert w["title"] == target["snapshot"]["title"]
        finally:
            _DB.workouts.update_one({"id": target["wid"]}, {"$set": {"completed": False}})

    def test_no_workout_on_date_no_crash(self, client_ctx):
        # Pick a date far in the future for which no workout exists
        d = (date.today() + timedelta(days=800)).isoformat()
        _clear_override(client_ctx["headers"], d)
        try:
            r = requests.post(f"{API}/calendar/day-override",
                              json={"date": d, "tags": ["sick"]},
                              headers=client_ctx["headers"], timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            adj = body["adjustment"]
            assert adj["changed"] is False
            assert adj["workout_id"] is None
        finally:
            _clear_override(client_ctx["headers"], d)


# ---------------------------------------------------------------------------
# Coach visibility
# ---------------------------------------------------------------------------

class TestCoachVisibility:
    def test_coach_calendar_reflects_override(self, client_ctx, coach_ctx, target):
        d = target["date"]
        notes = "Feeling wiped after redeye"
        _post_override(client_ctx, d, tags=["poor_sleep", "hotel_gym"], notes=notes)

        # Window: from today up to and including target date
        days = (date.fromisoformat(d) - date.today()).days + 1
        days = max(days, 1)
        r = requests.get(f"{API}/coach/calendar?days={days + 1}", headers=coach_ctx["headers"], timeout=20)
        assert r.status_code == 200, r.text
        payload = r.json()
        client_id = client_ctx["user"]["id"]
        row = next((c for c in payload["clients"] if c["client_id"] == client_id), None)
        assert row, "client row missing in coach/calendar"
        cell = next((cc for cc in row["days"] if cc["date"] == d), None)
        assert cell, f"cell for {d} missing"
        assert "poor_sleep" in (cell.get("override_tags") or [])
        assert "hotel_gym" in (cell.get("override_tags") or [])
        assert cell.get("override_notes") == notes
        # mobility action → workout was mutated → override_applied True
        assert cell.get("override_applied") is True

    def test_coach_client_detail_includes_overrides_and_change_log(self, client_ctx, coach_ctx, target):
        d = target["date"]
        _post_override(client_ctx, d, tags=["injured"], notes="tweaked knee")
        client_id = client_ctx["user"]["id"]
        r = requests.get(f"{API}/coach/clients/{client_id}", headers=coach_ctx["headers"], timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body.get("overrides"), list), "overrides array missing"
        assert isinstance(body.get("change_log"), list), "change_log array missing"
        # Our override should appear
        assert any(
            o.get("date") == d and "injured" in (o.get("tags") or [])
            for o in body["overrides"]
        ), "posted override not found in overrides[]"
        # change_log should record it
        assert any(
            (cl.get("date") == d) and (cl.get("new") or {}).get("date") == d
            for cl in body["change_log"]
        ), "change_log entry missing"

    def test_client_cannot_hit_coach_calendar(self, client_ctx):
        r = requests.get(f"{API}/coach/calendar", headers=client_ctx["headers"], timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_client_cannot_hit_coach_client_detail(self, client_ctx):
        cid = client_ctx["user"]["id"]
        r = requests.get(f"{API}/coach/clients/{cid}", headers=client_ctx["headers"], timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"


# ---------------------------------------------------------------------------
# Sanity: response envelope shape
# ---------------------------------------------------------------------------

class TestResponseEnvelope:
    def test_response_envelope_shape(self, client_ctx, target):
        resp = _post_override(client_ctx, target["date"], tags=["poor_sleep"])
        assert "override" in resp
        assert "coach_locked" in resp
        assert "adjustment" in resp
        adj = resp["adjustment"]
        for k in ("action", "reason", "changed", "workout_id", "coach_locked"):
            assert k in adj, f"adjustment missing key {k}"
        # For a mutation, extra keys populated
        assert adj["workout_id"] == target["wid"]
        assert isinstance(adj["reason"], str) and adj["reason"]
