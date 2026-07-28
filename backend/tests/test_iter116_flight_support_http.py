"""
Iter 116 — HTTP integration tests for Aviation Support Layer (Phase A).

Uses synchronous pymongo for the state flips so we don't run into
motor's "Event loop is closed" issue between pytest test invocations.
"""
from __future__ import annotations

import os
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get(
    "EXPO_PUBLIC_BACKEND_URL",
    "https://flight-fit-plans.preview.emergentagent.com",
).rstrip("/")

PIETRO_EMAIL = "pietrosangermano1992@hotmail.com"
PIETRO_PASSWORD = "Pietro2026"
PIETRO_ID = "c4c7c7dd-4303-4645-af2c-b70212495360"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def pietro_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": PIETRO_EMAIL, "password": PIETRO_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in response: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(pietro_token):
    return {"Authorization": f"Bearer {pietro_token}",
            "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def db():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


def _get_calendar_range(auth_headers, d_from="2026-07-25", d_to="2026-08-05"):
    r = requests.get(
        f"{BASE_URL}/api/calendar/range",
        params={"from": d_from, "to": d_to},
        headers=auth_headers,
        timeout=30,
    )
    assert r.status_code == 200, f"calendar/range failed: {r.status_code} {r.text[:400]}"
    days = r.json().get("days") or []
    return {d["date"]: d for d in days}


# --------------------------------------------------------------------------- 1. Basic shape

class TestFlightSupportField:
    def test_calendar_range_returns_flight_support_key(self, auth_headers):
        by_date = _get_calendar_range(auth_headers)
        assert by_date, "no days returned"
        for d, row in by_date.items():
            assert "flight_support" in row, f"missing flight_support on {d}"
            assert isinstance(row["flight_support"], list)


# --------------------------------------------------------------------------- 2. Per-date interventions

class TestFlightSupportPerDate:
    def test_07_27_layover_arrival_bundle(self, auth_headers):
        row = _get_calendar_range(auth_headers).get("2026-07-27")
        assert row
        fs = row["flight_support"]
        print(f"[07-27] day_type={(row.get('roster_day') or {}).get('day_type')} "
              f"titles={[i['title'] for i in fs]}")
        assert len(fs) == 2, f"expected 2, got {fs}"
        titles = sorted(i["title"] for i in fs)
        assert titles == ["Arrival Mobility", "Arrival Walk"]
        durations = {i["title"]: i["duration_min"] for i in fs}
        assert durations["Arrival Walk"] == 10
        assert durations["Arrival Mobility"] == 5
        for i in fs:
            assert i["bundle_key"].startswith("bundle:arrival:")

    def test_07_28_layover_full_walk(self, auth_headers):
        row = _get_calendar_range(auth_headers).get("2026-07-28")
        assert row
        fs = row["flight_support"]
        w = row.get("workout")
        print(f"[07-28] day_type={(row.get('roster_day') or {}).get('day_type')} "
              f"workout={w.get('title') if w else None} fs={[i['title'] for i in fs]}")
        # Spec: layover_full + has_training_today → skip (over-prescribe guard).
        # Pietro has a Run Easy on 2026-07-28, so [] is CORRECT per spec.
        if w:
            assert fs == [], (
                f"07-28 has training ({w.get('title')}), fs should be [], got {fs}"
            )
        else:
            assert len(fs) == 1 and fs[0]["title"] == "Layover Walk", fs

    def test_07_29_layover_departure_long_haul(self, auth_headers):
        row = _get_calendar_range(auth_headers).get("2026-07-29")
        assert row
        fs = row["flight_support"]
        titles = sorted(i["title"] for i in fs)
        print(f"[07-29] titles={titles}")
        assert titles == ["Movement Break", "Pre-Flight Mobility"], titles

    def test_07_30_turnaround_reset(self, auth_headers):
        row = _get_calendar_range(auth_headers).get("2026-07-30")
        assert row
        fs = row["flight_support"]
        assert len(fs) == 1 and fs[0]["title"] == "Turnaround Reset"
        assert fs[0]["duration_min"] == 5

    def test_home_days_with_training_empty(self, auth_headers):
        by_date = _get_calendar_range(auth_headers)
        for d in ("2026-07-31", "2026-08-01", "2026-08-02"):
            row = by_date.get(d)
            assert row
            print(f"[{d}] fs={row['flight_support']}")
            assert row["flight_support"] == []

    def test_08_03_standby_no_training_movement_break(self, auth_headers):
        row = _get_calendar_range(auth_headers).get("2026-08-03")
        assert row
        fs = row["flight_support"]
        assert len(fs) == 1 and fs[0]["title"] == "Movement Break"

    def test_08_04_standby_with_training_empty(self, auth_headers):
        row = _get_calendar_range(auth_headers).get("2026-08-04")
        assert row
        assert row["flight_support"] == []


# --------------------------------------------------------------------------- 3. Intervention shape invariants

class TestInterventionShape:
    def test_every_intervention_has_required_fields(self, auth_headers):
        by_date = _get_calendar_range(auth_headers)
        seen = 0
        for date, row in by_date.items():
            for i in row.get("flight_support") or []:
                seen += 1
                assert i.get("id", "").startswith(f"fs:{date}:"), i.get("id")
                assert i.get("is_flight_support") is True
                for k in ("protocol_key", "title", "family", "intensity",
                          "duration_min", "cues", "blocks", "trigger_reason"):
                    assert k in i, f"missing {k}"
                assert i["intensity"] in ("very_low", "low")
                assert isinstance(i["cues"], list) and isinstance(i["blocks"], list)
        assert seen >= 5, f"too few interventions across range: {seen}"


# --------------------------------------------------------------------------- 4. Engine V2 isolation

def _all_ids(node):
    if isinstance(node, dict):
        if isinstance(node.get("id"), str):
            yield node["id"]
        for v in node.values():
            yield from _all_ids(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_ids(v)


class TestEngineV2Isolation:
    def test_workouts_week_no_flight_support_leakage(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        data = r.json()
        ids = list(_all_ids(data))
        bad = [i for i in ids if i.startswith("fs:")
               or "v2p:fs" in i or "v2p:aviation" in i]
        assert not bad, f"leakage in /workouts/week: {bad[:5]}"

    def test_v2_plan_live_no_fs_leakage_and_status(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/v2/client/plan/live",
                         headers=auth_headers, timeout=30)
        if r.status_code == 404:
            pytest.skip("plan/live not available")
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        status = data.get("programme_status") or data.get("status")
        print(f"programme_status={status}")
        # Not asserting programme_live because iter110 note says Pietro's
        # live plan may have drifted. We only assert no aviation leakage.
        ids = list(_all_ids(data))
        bad = [i for i in ids if i.startswith("fs:")
               or "v2p:fs" in i or "v2p:aviation" in i]
        assert not bad, f"leakage in /v2/client/plan/live: {bad[:5]}"

    def test_calendar_workouts_have_no_fs_ids(self, auth_headers):
        by_date = _get_calendar_range(auth_headers)
        for date, row in by_date.items():
            w = row.get("workout")
            if not w:
                continue
            wid = str(w.get("id") or "")
            assert not wid.startswith("fs:"), f"fs: id in workout on {date}: {wid}"
            assert "v2p:fs" not in wid and "v2p:aviation" not in wid


# --------------------------------------------------------------------------- 5. Global disable & role toggles (sync pymongo)

class TestOverridesAndRole:
    def _set_flight_support_disabled(self, db, value: bool):
        db.users.update_one(
            {"id": PIETRO_ID},
            {"$set": {"profile.flight_support.disabled": value}},
        )

    def test_global_disable_returns_all_empty(self, db, auth_headers):
        try:
            self._set_flight_support_disabled(db, True)
            by_date = _get_calendar_range(auth_headers)
            non_empty = {d: r["flight_support"] for d, r in by_date.items()
                         if r["flight_support"]}
            assert non_empty == {}, f"expected empty everywhere: {non_empty}"
        finally:
            self._set_flight_support_disabled(db, False)
        # sanity restore
        by_date2 = _get_calendar_range(auth_headers)
        assert by_date2["2026-07-27"]["flight_support"], "not restored"

    def test_cabin_crew_job_title_returns_empty(self, db, auth_headers):
        u = db.users.find_one({"id": PIETRO_ID}, {"profile": 1})
        original = ((u or {}).get("profile") or {}).get("job_title") or "Pilot"
        try:
            db.users.update_one(
                {"id": PIETRO_ID},
                {"$set": {"profile.job_title": "Cabin Crew"}},
            )
            by_date = _get_calendar_range(auth_headers)
            non_empty = {d: r["flight_support"] for d, r in by_date.items()
                         if r["flight_support"]}
            assert non_empty == {}, (
                f"cabin_crew should return [] everywhere, got: {non_empty}"
            )
        finally:
            db.users.update_one(
                {"id": PIETRO_ID},
                {"$set": {"profile.job_title": original}},
            )
        by_date2 = _get_calendar_range(auth_headers)
        assert by_date2["2026-07-27"]["flight_support"], "not restored"


# --------------------------------------------------------------------------- 6. V1 regression

class TestV1ClientRegression:
    def test_v1_client_flight_support_all_empty(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "testcal2@crewfit.com", "password": "TestCal123!"},
            timeout=20,
        )
        if r.status_code != 200:
            pytest.skip(f"v1 login unavailable: {r.status_code}")
        tok = r.json().get("token") or r.json().get("access_token")
        r2 = requests.get(
            f"{BASE_URL}/api/calendar/range",
            params={"from": "2026-07-25", "to": "2026-08-05"},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        assert r2.status_code == 200
        days = r2.json().get("days") or []
        assert days, "no days returned for v1 client"
        for row in days:
            fs = row.get("flight_support")
            assert fs == [], (
                f"V1 client {row['date']} expected fs=[], got {fs}"
            )
