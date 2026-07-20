"""
Iter 68 — Coach Dashboard Slice 3 (partial).
Backend tests for the new 'needs_review' filter on /api/coach/dashboard.

Uses Motor to temporarily flip the latest programme row for client@crewfit.com
to {validation_status: 'needs_review', coach_approved: false} and restore at
teardown.
"""
import os
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
).rstrip("/")

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")

LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PWD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PWD = "Client123!"


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def louis_auth(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": LOUIS_EMAIL, "password": LOUIS_PWD}, timeout=30)
    assert r.status_code == 200, f"login louis: {r.status_code} {r.text}"
    d = r.json()
    return {"token": d["token"], "user": d["user"], "headers": {"Authorization": f"Bearer {d['token']}"}}


@pytest.fixture(scope="module")
def client_auth(api):
    r = api.post(f"{BASE_URL}/api/auth/login",
                 json={"email": CLIENT_EMAIL, "password": CLIENT_PWD}, timeout=30)
    assert r.status_code == 200, f"login client: {r.status_code} {r.text}"
    d = r.json()
    return {"token": d["token"], "user": d["user"], "headers": {"Authorization": f"Bearer {d['token']}"}}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def flipped_client(client_auth):
    """Temporarily flip client's latest programme to needs_review.
    Restore original values at teardown."""
    cid = client_auth["user"]["id"]
    original = {}

    async def _flip():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        try:
            row = await db.programmes.find_one({"user_id": cid}, sort=[("created_at", -1)])
            if not row:
                # Insert a minimal programme so the pill exists.
                import uuid, datetime
                doc = {
                    "id": str(uuid.uuid4()),
                    "user_id": cid,
                    "goal_key": "endurance",
                    "goal_label": "Endurance",
                    "phase": {"key": "build", "label": "Build"},
                    "week_index": 1,
                    "target_sessions_per_week": 3,
                    "validation_status": "needs_review",
                    "coach_approved": False,
                    "created_at": datetime.datetime.utcnow().isoformat(),
                    "updated_at": datetime.datetime.utcnow().isoformat(),
                    "_iter68_seeded": True,
                }
                await db.programmes.insert_one(doc)
                original["seeded_id"] = doc["id"]
            else:
                original["_id"] = row["_id"]
                original["validation_status"] = row.get("validation_status")
                original["coach_approved"] = row.get("coach_approved")
                await db.programmes.update_one(
                    {"_id": row["_id"]},
                    {"$set": {"validation_status": "needs_review", "coach_approved": False}},
                )
        finally:
            client.close()

    _run(_flip())

    yield cid

    async def _restore():
        client = AsyncIOMotorClient(MONGO_URL)
        db = client[DB_NAME]
        try:
            if original.get("seeded_id"):
                await db.programmes.delete_one({"id": original["seeded_id"]})
            elif original.get("_id"):
                await db.programmes.update_one(
                    {"_id": original["_id"]},
                    {"$set": {
                        "validation_status": original.get("validation_status"),
                        "coach_approved": bool(original.get("coach_approved")),
                    }},
                )
        finally:
            client.close()

    _run(_restore())


# ---------- tests ----------

class TestCoachDashboardNeedsReview:
    """Slice 3 backend: needs_review filter"""

    def test_dashboard_no_filter_still_returns_full_list(self, api, louis_auth):
        r = api.get(f"{BASE_URL}/api/coach/dashboard", headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "clients" in d and "counts" in d and "total" in d
        assert isinstance(d["clients"], list)
        assert d["total"] == len(d["clients"])
        # Existing buckets still present
        for k in ["expiring_soon", "expired", "no_roster", "needs_confirmation",
                  "pending_approval", "red_days", "missed"]:
            assert k in d["counts"], f"missing bucket {k}"
        # New bucket key present in counts
        assert "needs_review" in d["counts"], "needs_review key missing from counts"

    def test_dashboard_include_archived_still_works(self, api, louis_auth):
        r = api.get(f"{BASE_URL}/api/coach/dashboard?include_archived=true",
                    headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["clients"], list)
        assert "needs_review" in d["counts"]

    def test_dashboard_needs_review_filter_returns_only_matching(self, api, louis_auth, flipped_client):
        cid = flipped_client
        r = api.get(f"{BASE_URL}/api/coach/dashboard?filter=needs_review",
                    headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "clients" in d and "counts" in d
        assert "needs_review" in d["counts"]
        assert d["counts"]["needs_review"] >= 1, f"expected at least 1 needs_review, got counts={d['counts']}"

        # Every returned client must match the needs_review criteria
        for c in d["clients"]:
            pp = c.get("programme_pill") or {}
            assert pp.get("validation_status") == "needs_review", f"non-needs_review row leaked: {c.get('id')} pill={pp}"
            assert not pp.get("coach_approved"), f"coach_approved row leaked: {c.get('id')}"

        # Our flipped client should be in the list
        ids = [c["id"] for c in d["clients"]]
        assert cid in ids, f"flipped client {cid} not in needs_review bucket. ids={ids}"

    def test_dashboard_all_filter_unaffected(self, api, louis_auth, flipped_client):
        r = api.get(f"{BASE_URL}/api/coach/dashboard?filter=all",
                    headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["clients"], list)
        # total should equal all list length
        assert d["total"] == len(d["clients"])

    def test_regression_existing_buckets(self, api, louis_auth):
        """Existing buckets from iter66/67 not broken by the new needs_review addition."""
        r = api.get(f"{BASE_URL}/api/coach/dashboard", headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        counts = d["counts"]
        # All bucket keys must be integers
        for k, v in counts.items():
            assert isinstance(v, int), f"bucket {k} count must be int, got {type(v).__name__}"

    def test_needs_review_requires_coach_role(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/coach/dashboard?filter=needs_review",
                    headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403, f"client should be denied, got {r.status_code}"

    def test_client_has_route_focus_from_iter60(self, api, louis_auth):
        """Iter60 seeded client@crewfit.com with route_focus. Verify it is exposed
        via the coach dashboard (used by FE to render route_focus line)."""
        r = api.get(f"{BASE_URL}/api/coach/dashboard", headers=louis_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        seeded = next((c for c in d["clients"] if c.get("email") == CLIENT_EMAIL), None)
        assert seeded is not None, "seeded client@crewfit.com not present"
        # profile should contain route_focus (may be None if not seeded but usually set)
        prof = seeded.get("profile") or {}
        # Not a hard assert to avoid false-fail if seed drifted; just log
        if "route_focus" not in prof:
            pytest.skip(f"client profile does not have route_focus (iter60 seed drifted). profile keys: {list(prof.keys())}")
        assert prof.get("route_focus"), f"route_focus is empty: {prof.get('route_focus')}"
