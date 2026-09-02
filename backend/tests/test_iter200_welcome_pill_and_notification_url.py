"""Iter200 regression: welcome-pill endpoint + notify_weekly_video_ready action_url.

Covers:
    * GET /api/videos/welcome-for-me priority order
        - Case A: no welcome + no weekly → {video: null}
        - Case B: welcome sent, no weekly → welcome
        - Case C: welcome + weekly → weekly wins (welcome hidden)
        - Case D: only weekly, viewed long ago → still returned
        - Case E: two weeklies → returns most recent sent_at
    * notify_weekly_video_ready() writes action_url
        - "/video/{id}" when video_id passed
        - "/(client)/home" when video_id is None
"""
# ruff: noqa: E402
import os
import sys
import uuid
import asyncio
import datetime as _dt
import pytest
import requests

sys.path.insert(0, "/app/backend")

# Pre-load server module in a controlled order to avoid the circular
# import between feature_notifications ↔ feature_standby that occurs if
# we do `from feature_notifications import ...` first. server.py imports
# feature_notifications at the *end*, after feature_standby has landed.
_SERVER_IMPORTED = False


def _import_server_once():
    global _SERVER_IMPORTED
    if _SERVER_IMPORTED:
        return
    import server  # noqa: F401
    _SERVER_IMPORTED = True


def _load_env():
    for path in ("/app/backend/.env", "/app/frontend/.env"):
        if not os.path.exists(path):
            continue
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"')
            os.environ.setdefault(k, v)


_load_env()

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"
API = f"{BASE_URL}/api"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "crewfit_v1")


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _iso_delta(hours: float) -> str:
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=hours)).isoformat()


def run_async(coro_factory):
    """Run an async function on a SHARED module-scoped event loop.

    Uses one persistent loop so that motor clients bound to server.py's
    module-level ``db`` remain valid across tests (server.db is created
    lazily on first use and bound to whatever loop is running then).
    ``coro_factory`` is a callable that receives ``db`` and returns a
    coroutine to await.
    """
    async def _wrap():
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            db = client[DB_NAME]
            return await coro_factory(db)
        finally:
            client.close()
    loop = _get_shared_loop()
    return loop.run_until_complete(_wrap())


_SHARED_LOOP = None


def _get_shared_loop():
    global _SHARED_LOOP
    if _SHARED_LOOP is None or _SHARED_LOOP.is_closed():
        _SHARED_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_SHARED_LOOP)
    return _SHARED_LOOP


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def s():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def client_auth(s):
    r = s.post(f"{API}/auth/login", json={"email": "client@crewfit.com", "password": "Client123!"}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    d = r.json()
    return {"token": d["token"], "user": d["user"], "headers": {"Authorization": f"Bearer {d['token']}"}}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_video(user_id: str, *, video_kind: str, status: str,
                sent_at: str | None, watched_at: str | None, tag: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "coach_id": "test_coach",
        "check_in_id": None,
        "video_kind": video_kind,
        "script": f"TEST_iter200_{tag} script",
        "file_url": "https://example.com/test.mp4",
        "storage_key": None,
        "file_ext": "mp4",
        "file_mime": "video/mp4",
        "thumbnail_url": None,
        "duration_seconds": 30,
        "status": status,
        "created_at": _now_iso(),
        "sent_at": sent_at,
        "watched_at": watched_at,
    }


def _get_welcome_for_me(s, headers) -> dict:
    r = s.get(f"{API}/videos/welcome-for-me", headers=headers, timeout=15)
    assert r.status_code == 200, f"{r.status_code} {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# saved-state fixture: back up existing rows for this user, restore after
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def preserve_client_video_state(client_auth):
    """Back up client's weekly_videos rows before the tests and restore after.

    The tests need to control exactly what the client's video state is, so
    we snapshot & clear at start, then restore at teardown.
    """
    user_id = client_auth["user"]["id"]

    def _snapshot(db):
        async def _do(db):
            rows = await db.weekly_videos.find({"user_id": user_id}).to_list(1000)
            for r in rows:
                r.pop("_id", None)
            await db.weekly_videos.delete_many({"user_id": user_id})
            return rows
        return _do(db)

    rows = run_async(_snapshot)
    yield rows

    def _restore(db):
        async def _do(db):
            # Clean any leftover test rows first
            await db.weekly_videos.delete_many({"user_id": user_id})
            if rows:
                await db.weekly_videos.insert_many(rows)
        return _do(db)

    run_async(_restore)


# ---------------------------------------------------------------------------
# 1) /api/videos/welcome-for-me priority tests
# ---------------------------------------------------------------------------

class TestWelcomeForMe:
    """Endpoint priority: weekly > welcome (grace) > null."""

    def test_case_A_none(self, s, client_auth):
        """Case A: no welcome + no weekly → {video: null}."""
        user_id = client_auth["user"]["id"]
        run_async(lambda db: db.weekly_videos.delete_many({"user_id": user_id}))
        body = _get_welcome_for_me(s, client_auth["headers"])
        assert body == {"video": None}, body

    def test_case_B_welcome_only(self, s, client_auth):
        """Case B: welcome sent, no weekly → welcome video returned."""
        user_id = client_auth["user"]["id"]
        welcome = _make_video(user_id, video_kind="welcome", status="sent",
                              sent_at=_iso_delta(-1), watched_at=None, tag="caseB")

        async def _setup(db):
            await db.weekly_videos.delete_many({"user_id": user_id})
            await db.weekly_videos.insert_one(welcome)
        run_async(_setup)
        try:
            body = _get_welcome_for_me(s, client_auth["headers"])
            assert body.get("video") is not None, body
            assert body["video"]["id"] == welcome["id"], body["video"]
            assert body["video"]["video_kind"] == "welcome"
        finally:
            run_async(lambda db: db.weekly_videos.delete_many({"user_id": user_id}))

    def test_case_C_welcome_and_weekly(self, s, client_auth):
        """Case C: welcome + weekly → returns WEEKLY, not welcome."""
        user_id = client_auth["user"]["id"]
        welcome = _make_video(user_id, video_kind="welcome", status="sent",
                              sent_at=_iso_delta(-2), watched_at=None, tag="caseC")
        weekly = _make_video(user_id, video_kind="weekly", status="sent",
                             sent_at=_iso_delta(-1), watched_at=None, tag="caseC")

        async def _setup(db):
            await db.weekly_videos.delete_many({"user_id": user_id})
            await db.weekly_videos.insert_many([welcome, weekly])
        run_async(_setup)
        try:
            body = _get_welcome_for_me(s, client_auth["headers"])
            assert body.get("video") is not None, body
            assert body["video"]["id"] == weekly["id"], (
                f"expected weekly {weekly['id']} but got {body['video']}"
            )
            assert body["video"]["video_kind"] == "weekly"
        finally:
            run_async(lambda db: db.weekly_videos.delete_many({"user_id": user_id}))

    def test_case_D_weekly_viewed_long_ago(self, s, client_auth):
        """Case D: only weekly, viewed a week ago → still returned (no grace)."""
        user_id = client_auth["user"]["id"]
        weekly = _make_video(user_id, video_kind="weekly", status="viewed",
                             sent_at=_iso_delta(-7 * 24), watched_at=_iso_delta(-6 * 24),
                             tag="caseD")

        async def _setup(db):
            await db.weekly_videos.delete_many({"user_id": user_id})
            await db.weekly_videos.insert_one(weekly)
        run_async(_setup)
        try:
            body = _get_welcome_for_me(s, client_auth["headers"])
            assert body.get("video") is not None, body
            assert body["video"]["id"] == weekly["id"]
            assert body["video"]["video_kind"] == "weekly"
            assert body["video"]["status"] == "viewed"
        finally:
            run_async(lambda db: db.weekly_videos.delete_many({"user_id": user_id}))

    def test_case_E_two_weeklies_returns_latest(self, s, client_auth):
        """Case E: two weeklies → returns the one with the more recent sent_at."""
        user_id = client_auth["user"]["id"]
        older = _make_video(user_id, video_kind="weekly", status="sent",
                            sent_at=_iso_delta(-72), watched_at=None, tag="caseE_old")
        newer = _make_video(user_id, video_kind="weekly", status="sent",
                            sent_at=_iso_delta(-1), watched_at=None, tag="caseE_new")

        async def _setup(db):
            await db.weekly_videos.delete_many({"user_id": user_id})
            await db.weekly_videos.insert_many([older, newer])
        run_async(_setup)
        try:
            body = _get_welcome_for_me(s, client_auth["headers"])
            assert body.get("video") is not None
            assert body["video"]["id"] == newer["id"], (
                f"expected newer {newer['id']} but got {body['video']['id']}"
            )
        finally:
            run_async(lambda db: db.weekly_videos.delete_many({"user_id": user_id}))


# ---------------------------------------------------------------------------
# 2) notify_weekly_video_ready action_url tests
# ---------------------------------------------------------------------------

class TestNotifyWeeklyVideoReadyActionURL:
    """Direct call into feature_notifications.notify_weekly_video_ready.

    Verifies the row inserted into db.notifications has the new
    ``action_url`` format (Iter200 change).
    """

    def test_action_url_with_video_id(self, client_auth):
        user_id = client_auth["user"]["id"]
        video_id = f"TEST_iter200_{uuid.uuid4().hex[:8]}"
        dedupe = f"weekly_video::{video_id}"

        async def _run(db):
            await db.notifications.delete_many({"user_id": user_id, "dedupe_key": dedupe})
            _import_server_once()
            from feature_notifications import notify_weekly_video_ready
            await notify_weekly_video_ready(user_id, video_id=video_id, video_kind="welcome")
            row = await db.notifications.find_one(
                {"user_id": user_id, "dedupe_key": dedupe}, {"_id": 0}
            )
            await db.notifications.delete_many({"user_id": user_id, "dedupe_key": dedupe})
            return row

        row = run_async(_run)
        assert row is not None, "notification row was not inserted"
        assert row.get("action_url") == f"/video/{video_id}", row
        assert row.get("notif_type") == "weekly_video_ready"
        assert row.get("related_id") == video_id

    def test_action_url_without_video_id(self, client_auth):
        user_id = client_auth["user"]["id"]
        dedupe = "weekly_video::"

        async def _run(db):
            await db.notifications.delete_many({"user_id": user_id, "dedupe_key": dedupe})
            _import_server_once()
            from feature_notifications import notify_weekly_video_ready
            await notify_weekly_video_ready(user_id, video_id=None, video_kind="weekly")
            row = await db.notifications.find_one(
                {"user_id": user_id, "dedupe_key": dedupe}, {"_id": 0}
            )
            await db.notifications.delete_many({"user_id": user_id, "dedupe_key": dedupe})
            return row

        row = run_async(_run)
        assert row is not None, "notification row was not inserted"
        assert row.get("action_url") == "/(client)/home", row
        assert row.get("notif_type") == "weekly_video_ready"
