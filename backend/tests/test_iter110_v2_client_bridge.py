"""Iter 110 — V2 client-side bridge tests

Verifies that the legacy client-side endpoints (/workouts/week,
/workouts/{id}, /calendar/timeline) surface Pietro's active plan_live_v2
placements via feature_v2_client_bridge, without breaking V1 clients.
"""
import os
import pytest
import requests


def _load_frontend_env():
    for path in ["/app/frontend/.env", "/app/backend/.env"]:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k, v.strip().strip('"'))
        except Exception:
            pass


_load_frontend_env()
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or
            os.environ.get("EXPO_BACKEND_URL", "").rstrip("/"))
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL/EXPO_BACKEND_URL must be set"

PIETRO_EMAIL = "pietrosangermano1992@hotmail.com"
PIETRO_PW = "Pietro2026"
PIETRO_UID = "c4c7c7dd-4303-4645-af2c-b70212495360"
PIETRO_LIVE_ID = "edc0be3a-9424-4bba-85eb-076b3818c945"

LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PW = "Louis123!"


@pytest.fixture(scope="module")
def pietro_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": PIETRO_EMAIL, "password": PIETRO_PW},
                      timeout=30)
    assert r.status_code == 200, f"Pietro login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def louis_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": LOUIS_EMAIL, "password": LOUIS_PW},
                      timeout=30)
    assert r.status_code == 200, f"Louis login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


# ---------- 1. /workouts/week for Pietro ------------------------------

class TestPietroWorkoutsWeek:
    def test_workouts_week_contains_v2_rows(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 200, r.text
        rows = r.json()
        # gather engine_v2 rows
        v2_rows = [w for w in rows if w.get("source") == "engine_v2"
                   and (w.get("id") or "").startswith("v2p:")]
        assert len(v2_rows) >= 3, f"Expected >=3 v2 rows, got {len(v2_rows)}: {[w.get('title') for w in v2_rows]}"

        # Filter to expected dates for assertions
        by_date_title = {}
        for w in v2_rows:
            by_date_title.setdefault(w["date"], []).append(w)

        assert "2026-07-28" in by_date_title, f"Missing 2026-07-28 rows: {by_date_title}"
        assert "2026-07-31" in by_date_title, f"Missing 2026-07-31 rows: {by_date_title}"

        titles_28 = {w["title"] for w in by_date_title["2026-07-28"]}
        titles_31 = {w["title"] for w in by_date_title["2026-07-31"]}
        assert any("Run Easy" in t for t in titles_28), f"Run Easy missing on 2026-07-28: {titles_28}"
        assert any("Mobility" in t for t in titles_28), f"Mobility missing on 2026-07-28: {titles_28}"
        assert any("Run Long" in t for t in titles_31), f"Run Long missing on 2026-07-31: {titles_31}"

    def test_v2_rows_have_expected_shape(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 200
        rows = r.json()
        v2_rows = [w for w in rows if w.get("source") == "engine_v2"]
        assert v2_rows

        for w in v2_rows:
            assert w.get("id", "").startswith("v2p:"), w
            assert w.get("approved") is True, w
            assert w.get("coach_locked") is True, w
            # warmup should be present as a compat field (dict or None)
            assert "warmup" in w, w

    def test_run_easy_shape(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(pietro_token), timeout=30)
        rows = r.json()
        run_easy = next((w for w in rows if w.get("source") == "engine_v2"
                        and "Run Easy" in (w.get("title") or "")
                        and w.get("date") == "2026-07-28"), None)
        assert run_easy, "Run Easy on 2026-07-28 not found"
        assert run_easy["duration_min"] == 35, run_easy
        assert run_easy["location"] == "treadmill", run_easy
        assert run_easy["blocks"], "blocks[] empty for Run Easy"
        # blocks should have warmup + main + cooldown
        types = [b.get("type") for b in run_easy["blocks"]]
        assert "warmup" in types, types
        assert "cooldown" in types, types

    def test_mobility_shape(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(pietro_token), timeout=30)
        rows = r.json()
        mob = next((w for w in rows if w.get("source") == "engine_v2"
                    and "Mobility" in (w.get("title") or "")
                    and w.get("date") == "2026-07-28"), None)
        assert mob, "Mobility on 2026-07-28 not found"
        assert mob["duration_min"] == 20, mob

    def test_run_long_shape(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(pietro_token), timeout=30)
        rows = r.json()
        rl = next((w for w in rows if w.get("source") == "engine_v2"
                   and "Run Long" in (w.get("title") or "")
                   and w.get("date") == "2026-07-31"), None)
        assert rl, "Run Long on 2026-07-31 not found"
        assert rl["duration_min"] == 60, rl
        assert rl["key_session"] is True, rl
        assert rl["location"] == "outdoor", rl
        assert rl["blocks"], "blocks[] empty for Run Long"


# ---------- 2. /workouts/{wid} for Run Long v2p ------------------------

class TestPietroWorkoutGet:
    def test_run_long_detail(self, pietro_token):
        # First get the week to fetch the id
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(pietro_token), timeout=30)
        rows = r.json()
        rl = next((w for w in rows if w.get("source") == "engine_v2"
                   and "Run Long" in (w.get("title") or "")), None)
        assert rl, "Run Long v2 row not found"
        wid = rl["id"]

        det = requests.get(f"{BASE_URL}/api/workouts/{wid}",
                           headers=_auth(pietro_token), timeout=30)
        assert det.status_code == 200, det.text
        w = det.json()
        assert w["id"] == wid
        assert w["source"] == "engine_v2"
        assert w["approved"] is True
        assert w["coach_locked"] is True
        assert w.get("rationale"), "rationale must be non-empty"
        assert "Run Long" in w["rationale"] or "foundation" in w["rationale"].lower(), \
            f"Rationale did not mention 'Run Long — foundation phase': {w['rationale']!r}"

        # Blocks[] should contain warmup + long_steady + cooldown
        blocks = w.get("blocks") or []
        assert blocks, "blocks[] empty"
        types = [b.get("type") for b in blocks]
        # Warmup / cooldown present
        assert "warmup" in types, types
        assert "cooldown" in types, types
        # Long steady main block with MP+90s and fuel_cue
        long_block = next((b for b in blocks if b.get("type") == "long_steady"), None)
        assert long_block, f"long_steady block missing; got types={types}"
        assert long_block.get("pace_target") == "MP+90s", long_block
        assert long_block.get("fuel_cue"), f"fuel_cue missing on long_steady: {long_block}"

    def test_negative_v2p_returns_404(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/workouts/v2p:non-existent:bogus",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


# ---------- 3. /calendar/timeline for Pietro ---------------------------

class TestPietroCalendarTimeline:
    def test_timeline_includes_v2_days(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/calendar/timeline"
                         "?months_back=0&months_ahead=1",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 200, r.text
        payload = r.json()
        months = payload.get("months") or []
        july = next((m for m in months if m.get("iso") == "2026-07"
                     or (m.get("year") == 2026 and m.get("month") == 7)), None)
        # be tolerant of the shape — inspect first
        if not july:
            # dump structure
            keys = [(m.get("month"), m.get("year")) for m in months]
            pytest.fail(f"July 2026 month not found; months={keys}")

        days = july.get("days") or []
        d28 = next((d for d in days if d.get("date") == "2026-07-28"), None)
        d31 = next((d for d in days if d.get("date") == "2026-07-31"), None)
        assert d28, f"2026-07-28 missing in July days"
        assert d31, f"2026-07-31 missing in July days"

        assert d28.get("workout_id", "").startswith("v2p:"), d28
        assert d28.get("workout_title"), d28
        assert d31.get("workout_id", "").startswith("v2p:"), d31
        assert d31.get("workout_title"), d31
        assert "Run Long" in (d31.get("workout_title") or ""), d31
        assert d31.get("key_session") is True, d31


# ---------- 4. V1 client regression ------------------------------------

class TestV1ClientRegression:
    def test_v1_client_week_no_v2p(self, louis_token):
        # Fetch Louis's roster to pick a V1 client (no v2_flags.engine_v2)
        r = requests.get(f"{BASE_URL}/api/v2/coach/clients",
                         headers=_auth(louis_token), timeout=30)
        if r.status_code != 200:
            pytest.skip(f"coach clients roster unavailable: {r.status_code}")
        clients = r.json()
        # clients might be dict-with-list or a list
        if isinstance(clients, dict):
            clients = clients.get("clients") or clients.get("items") or []
        # Pick a client where kind != v2 (v1)
        v1_client = None
        for c in clients:
            uid = c.get("user_id") or c.get("id") or c.get("client_id")
            if not uid or uid == PIETRO_UID:
                continue
            if (c.get("kind") or "").lower() == "v1":
                v1_client = c
                break
        if not v1_client:
            # fallback: any client that isn't Pietro
            for c in clients:
                uid = c.get("user_id") or c.get("id") or c.get("client_id")
                if uid and uid != PIETRO_UID:
                    v1_client = c
                    break
        if not v1_client:
            pytest.skip("No V1 client available in Louis's roster")

        # We can't easily impersonate a V1 client without their password,
        # so use the coach-scope endpoint to look at their workouts:
        uid = v1_client.get("user_id") or v1_client.get("id") or v1_client.get("client_id")
        # /api/workouts/week requires the target user's token. Instead,
        # verify via a coach-scoped endpoint that any v1 client doesn't
        # get v2 splicing. The bridge itself gates on user.profile.v2_flags.
        # Check the client's profile.v2_flags via coach lookup:
        prof_r = requests.get(f"{BASE_URL}/api/v2/coach/client/{uid}/workspace",
                              headers=_auth(louis_token), timeout=30)
        if prof_r.status_code == 200:
            body = prof_r.json()
            kind = (body.get("client") or {}).get("kind")
            assert kind != "v2", f"Selected supposed-V1 client is actually V2: {body.get('client')}"
        else:
            pytest.skip(f"workspace endpoint for {uid} returned {prof_r.status_code}")

    def test_bridge_returns_empty_for_v1(self):
        """Direct unit-ish test: the bridge helper returns [] when the user
        has no v2_flags.engine_v2 set."""
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
        from feature_v2_client_bridge import synth_workouts_for_user  # noqa: E402

        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        assert mongo_url and db_name

        async def _run():
            cli = AsyncIOMotorClient(mongo_url)
            dbh = cli[db_name]
            # Find a user without v2_flags.engine_v2
            u = await dbh.users.find_one({
                "role": "client",
                "$or": [
                    {"profile.v2_flags.engine_v2": {"$exists": False}},
                    {"profile.v2_flags.engine_v2": False},
                ],
                "id": {"$ne": PIETRO_UID},
            }, {"_id": 0, "id": 1, "email": 1})
            cli.close()
            return u

        u = asyncio.get_event_loop().run_until_complete(_run())
        if not u:
            pytest.skip("No V1 client found in DB")

        async def _run2(uid):
            cli = AsyncIOMotorClient(mongo_url)
            dbh = cli[db_name]
            out = await synth_workouts_for_user(dbh, uid)
            cli.close()
            return out

        rows = asyncio.get_event_loop().run_until_complete(_run2(u["id"]))
        assert rows == [], f"Expected empty v2 rows for V1 client {u.get('email')}, got {rows}"
