"""
Iter 68 - Slice 3.5 Coach Deep-Edit backend tests.

Covers all 6 endpoints in /app/backend/feature_coach_deep_edit.py:
  * POST /api/coach/workouts/{wid}/approve
  * POST /api/coach/workouts/{wid}/lock
  * POST /api/coach/workouts/{wid}/move
  * POST /api/coach/workouts/{wid}/regenerate
  * PATCH /api/coach/clients/{client_id}/roster/{rid}/day
  * POST  /api/coach/clients/{client_id}/roster/{rid}/hotel

Plus:
  * Auth gates (401 no token / 403 client token)
  * Edge cases (regen on locked; move a completed; invalid day_type; invalid load)
  * Audit-log verification (action strings in db.audit_logs)
  * Regression smoke on GET /api/coach/clients, /api/coach/clients/{id}, /api/coach/dashboard
"""
import os
import asyncio
import uuid
import pytest
import requests
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
).rstrip("/")
API = f"{BASE_URL}/api"

MONGO_URL = (os.environ.get("MONGO_URL") or "mongodb://localhost:27017").strip('"').strip("'")
DB_NAME = (os.environ.get("DB_NAME") or "crewfit_v1").strip('"').strip("'")

LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PWD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PWD = "Client123!"


# ------------------------- helpers -------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed for {email}: {r.status_code} {r.text}"
    d = r.json()
    return d["token"], d["user"]


# ------------------------- fixtures ------------------------

@pytest.fixture(scope="module")
def louis_auth():
    t, u = _login(LOUIS_EMAIL, LOUIS_PWD)
    return {"token": t, "user": u, "headers": {"Authorization": f"Bearer {t}"}}


@pytest.fixture(scope="module")
def client_auth():
    t, u = _login(CLIENT_EMAIL, CLIENT_PWD)
    return {"token": t, "user": u, "headers": {"Authorization": f"Bearer {t}"}}


@pytest.fixture(scope="module")
def client_id(client_auth):
    return client_auth["user"]["id"]


@pytest.fixture(scope="module")
def client_bundle(louis_auth, client_id):
    """Fetch coach view of client with workouts + roster."""
    r = requests.get(f"{API}/coach/clients/{client_id}", headers=louis_auth["headers"], timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def workout(client_bundle):
    """Pick a non-completed, non-locked workout that has a roster_id."""
    ws = client_bundle.get("workouts") or []
    for w in ws:
        if (not w.get("completed")
                and not w.get("coach_locked")
                and w.get("roster_id")
                and w.get("date")):
            return w
    pytest.skip("no editable workout found for client")


@pytest.fixture(scope="module")
def active_roster(client_bundle, client_id):
    r = client_bundle.get("roster")
    if r and r.get("id") and (r.get("days") or []):
        return r

    # Fall back: query mongo directly for any roster that has days
    async def _q():
        c = AsyncIOMotorClient(MONGO_URL)
        try:
            db = c[DB_NAME]
            row = await db.rosters.find_one(
                {"user_id": client_id, "days.0": {"$exists": True}},
                {"_id": 0}, sort=[("created_at", -1)])
            return row
        finally:
            c.close()
    row = _run(_q())
    if not row:
        pytest.skip("client has no roster with days")
    return row


# ------------------------- Auth gate tests -------------------------

class TestAuthGates:
    """All 6 endpoints require coach/admin.  401 no token, 403 client token."""

    endpoints = [
        ("POST", "/coach/workouts/dummy-id/approve", {}),
        ("POST", "/coach/workouts/dummy-id/lock", {"locked": True}),
        ("POST", "/coach/workouts/dummy-id/move", {"to_date": "2030-01-01"}),
        ("POST", "/coach/workouts/dummy-id/regenerate", {}),
        ("PATCH", "/coach/clients/dummy-cid/roster/dummy-rid/day", {"date": "2030-01-01"}),
        ("POST", "/coach/clients/dummy-cid/roster/dummy-rid/hotel",
         {"date": "2030-01-01", "hotel": {"name": "n", "city": "c"}}),
    ]

    def test_no_token_returns_401(self):
        for method, path, body in self.endpoints:
            r = requests.request(method, f"{API}{path}", json=body, timeout=15)
            assert r.status_code == 401, f"{method} {path} expected 401 got {r.status_code}: {r.text}"

    def test_client_token_returns_403(self, client_auth):
        for method, path, body in self.endpoints:
            r = requests.request(method, f"{API}{path}", json=body,
                                 headers=client_auth["headers"], timeout=15)
            assert r.status_code == 403, f"{method} {path} expected 403 got {r.status_code}: {r.text}"


# ------------------------- Happy path & audit ---------------------

class TestApprove:
    def test_approve_workout_sets_flags(self, louis_auth, workout):
        wid = workout["id"]
        r = requests.post(f"{API}/coach/workouts/{wid}/approve",
                          json={"note": "TEST_iter68_approve"},
                          headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        w = d["workout"]
        assert w["approved"] is True
        assert w.get("needs_coach_review") is False
        assert w.get("coach_approved_by") == louis_auth["user"]["id"]
        assert w.get("coach_approved_at")
        # first approve, was_already_approved should be False
        assert d.get("was_already_approved") is False

    def test_approve_idempotent(self, louis_auth, workout):
        wid = workout["id"]
        r = requests.post(f"{API}/coach/workouts/{wid}/approve", json={},
                          headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["was_already_approved"] is True

    def test_approve_audit_row_present(self, workout):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                row = await db.audit_logs.find_one(
                    {"action": "workout.approve", "after.workout_id": workout["id"]},
                    sort=[("created_at", -1)],
                )
                assert row is not None, "workout.approve audit row missing"
            finally:
                c.close()
        _run(_check())


class TestLock:
    def test_lock_workout(self, louis_auth, workout):
        wid = workout["id"]
        r = requests.post(f"{API}/coach/workouts/{wid}/lock",
                          json={"locked": True, "note": "TEST_iter68_lock"},
                          headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] and d["changed"] is True
        assert d["workout"]["coach_locked"] is True
        assert d["workout"].get("coach_locked_by") == louis_auth["user"]["id"]

    def test_lock_idempotent_returns_changed_false(self, louis_auth, workout):
        r = requests.post(f"{API}/coach/workouts/{workout['id']}/lock",
                          json={"locked": True},
                          headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        assert r.json().get("changed") is False

    def test_regen_refused_on_locked(self, louis_auth, workout):
        """Edge: regenerating a coach_locked workout -> 400."""
        r = requests.post(f"{API}/coach/workouts/{workout['id']}/regenerate", json={},
                          headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"

    def test_unlock_workout(self, louis_auth, workout):
        r = requests.post(f"{API}/coach/workouts/{workout['id']}/lock",
                          json={"locked": False},
                          headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["changed"] is True
        assert d["workout"]["coach_locked"] is False

    def test_lock_and_unlock_audit_rows(self, workout):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                lock_row = await db.audit_logs.find_one(
                    {"action": "workout.lock", "extra.workout_id": workout["id"]},
                    sort=[("created_at", -1)])
                unlock_row = await db.audit_logs.find_one(
                    {"action": "workout.unlock", "extra.workout_id": workout["id"]},
                    sort=[("created_at", -1)])
                assert lock_row is not None, "workout.lock audit missing"
                assert unlock_row is not None, "workout.unlock audit missing"
            finally:
                c.close()
        _run(_check())


class TestMove:
    def test_move_workout_to_new_date(self, louis_auth, workout):
        wid = workout["id"]
        from_date = workout["date"]
        # Choose a target date +180 days ahead which is very likely unused
        base = datetime.strptime(from_date, "%Y-%m-%d")
        to_date = (base + timedelta(days=180)).strftime("%Y-%m-%d")

        # If destination is occupied, keep skipping forward
        async def _find_empty():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                d = to_date
                for i in range(60):
                    cand = (base + timedelta(days=180 + i)).strftime("%Y-%m-%d")
                    hit = await db.workouts.find_one(
                        {"user_id": workout["user_id"], "date": cand})
                    if not hit:
                        return cand
                return d
            finally:
                c.close()
        target = _run(_find_empty())

        r = requests.post(f"{API}/coach/workouts/{wid}/move",
                          json={"to_date": target, "note": "TEST_iter68_move"},
                          headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] and d["changed"] is True
        assert d["workout"]["date"] == target
        assert d.get("swapped") is False

        # Move it back to original date so downstream tests still work
        rb = requests.post(f"{API}/coach/workouts/{wid}/move",
                           json={"to_date": from_date},
                           headers=louis_auth["headers"], timeout=30)
        assert rb.status_code == 200, rb.text

    def test_move_completed_workout_400(self, louis_auth, client_id):
        """Edge: moving a completed workout -> 400.  Seeds a temp completed workout."""
        async def _seed():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                # find an existing workout to clone as completed
                base = await db.workouts.find_one({"user_id": client_id}, {"_id": 0})
                if not base:
                    return None
                doc = dict(base)
                doc["id"] = str(uuid.uuid4())
                doc["date"] = "2019-01-05"
                doc["completed"] = True
                doc["coach_locked"] = False
                doc["_iter68_seed"] = True
                await db.workouts.insert_one(doc)
                return doc["id"]
            finally:
                c.close()
        seeded_id = _run(_seed())
        if not seeded_id:
            pytest.skip("no workout to seed completed variant")
        try:
            r = requests.post(f"{API}/coach/workouts/{seeded_id}/move",
                              json={"to_date": "2019-02-05"},
                              headers=louis_auth["headers"], timeout=30)
            assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"
        finally:
            async def _cleanup():
                c = AsyncIOMotorClient(MONGO_URL)
                try:
                    await c[DB_NAME].workouts.delete_one({"id": seeded_id})
                finally:
                    c.close()
            _run(_cleanup())

    def test_move_audit_row(self, workout):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                row = await db.audit_logs.find_one(
                    {"action": "workout.move", "extra.workout_id": workout["id"]},
                    sort=[("created_at", -1)])
                assert row is not None, "workout.move audit missing"
            finally:
                c.close()
        _run(_check())


class TestRegenerateSingle:
    def test_regenerate_workout(self, louis_auth, workout):
        """After unlock (from TestLock.test_unlock_workout), regen should succeed."""
        wid = workout["id"]
        r = requests.post(f"{API}/coach/workouts/{wid}/regenerate",
                          json={"note": "TEST_iter68_regen"},
                          headers=louis_auth["headers"], timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        w = d["workout"]
        assert w["date"] == workout["date"]
        assert w["user_id"] == workout["user_id"]
        # source marker
        assert w.get("source") == "coach_regen_single"
        # approved reset per spec
        assert w.get("approved") is False
        assert w.get("coach_locked") is False

    def test_regenerate_audit_row(self, workout):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                row = await db.audit_logs.find_one(
                    {"action": "workout.regenerate_single",
                     "before.workout_id": workout["id"]},
                    sort=[("created_at", -1)])
                assert row is not None, "workout.regenerate_single audit missing"
            finally:
                c.close()
        _run(_check())


class TestRosterDayEdit:
    def test_edit_day_type_and_load(self, louis_auth, client_id, active_roster):
        rid = active_roster["id"]
        days = active_roster.get("days") or []
        assert days, "roster has no days"
        # pick a middle day to edit
        day = days[len(days) // 2]
        date = day["date"]
        prev_type = day.get("day_type")
        prev_load = day.get("load")
        new_type = "Layover Full Day" if prev_type != "Layover Full Day" else "Home Day"
        new_load = "amber" if prev_load != "amber" else "green"

        r = requests.patch(f"{API}/coach/clients/{client_id}/roster/{rid}/day",
                           json={"date": date, "day_type": new_type, "load": new_load,
                                 "notes": "TEST_iter68_day_edit"},
                           headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["day"]["day_type"] == new_type
        assert d["day"]["load"] == new_load
        assert d["day"].get("last_edited_by") == "coach"

    def test_invalid_day_type_400(self, louis_auth, client_id, active_roster):
        rid = active_roster["id"]
        date = (active_roster.get("days") or [{}])[0].get("date")
        r = requests.patch(f"{API}/coach/clients/{client_id}/roster/{rid}/day",
                           json={"date": date, "day_type": "NotARealType"},
                           headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"

    def test_invalid_load_400(self, louis_auth, client_id, active_roster):
        rid = active_roster["id"]
        date = (active_roster.get("days") or [{}])[0].get("date")
        r = requests.patch(f"{API}/coach/clients/{client_id}/roster/{rid}/day",
                           json={"date": date, "load": "rainbow"},
                           headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 400, f"expected 400 got {r.status_code} {r.text}"

    def test_day_edit_audit_row(self, client_id):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                row = await db.audit_logs.find_one(
                    {"action": "roster.day_edit", "target_user_id": client_id},
                    sort=[("created_at", -1)])
                assert row is not None, "roster.day_edit audit missing"
            finally:
                c.close()
        _run(_check())


class TestHotelAttach:
    def test_attach_hotel(self, louis_auth, client_id, active_roster):
        rid = active_roster["id"]
        days = active_roster.get("days") or []
        assert days, "roster has no days"
        date = days[0]["date"]
        payload = {
            "date": date,
            "hotel": {
                "name": f"TEST Hotel Iter68 {uuid.uuid4().hex[:6]}",
                "city": "Dubai",
                "country": "AE",
                "gym_available": True,
                "equipment": {"dumbbells": True, "treadmill": True},
                "notes": "TEST_iter68_hotel",
            },
        }
        r = requests.post(f"{API}/coach/clients/{client_id}/roster/{rid}/hotel",
                          json=payload, headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["hotel"]["name"] == payload["hotel"]["name"]
        assert d["day"].get("hotel_id") == d["hotel"]["id"]
        assert d["day"].get("hotel_name") == d["hotel"]["name"]

    def test_hotel_audit_row(self, client_id):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            try:
                db = c[DB_NAME]
                row = await db.audit_logs.find_one(
                    {"action": "roster.hotel_attach", "target_user_id": client_id},
                    sort=[("created_at", -1)])
                assert row is not None, "roster.hotel_attach audit missing"
            finally:
                c.close()
        _run(_check())


# ------------------------- Regression smoke ---------------------

class TestRegressionSmoke:
    def test_coach_clients_list(self, louis_auth):
        r = requests.get(f"{API}/coach/clients", headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        # server may return a list directly or {clients:[...]}
        rows = d if isinstance(d, list) else d.get("clients") or []
        assert isinstance(rows, list)

    def test_coach_client_detail(self, louis_auth, client_id):
        r = requests.get(f"{API}/coach/clients/{client_id}",
                         headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert (d.get("client") or {}).get("id") or d.get("id")
        assert "workouts" in d

    def test_coach_dashboard(self, louis_auth):
        r = requests.get(f"{API}/coach/dashboard",
                         headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "clients" in d and "counts" in d
