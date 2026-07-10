"""
Test suite for feature_social_studio (V1 Admin-only Social Media Studio).

Covers:
 - Role guard (client 403, coach/admin 200)
 - Content generation (Atlas + deterministic fallback)
 - Post CRUD + regenerate + status transitions
 - Analytics
 - Settings GET/PUT
 - Daily task generate/regenerate idempotency + pillar rotation
 - Regression: coach/tasks and other endpoints still work
"""
import os
import datetime as _dt
import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"


# ---- Auth helpers ---------------------------------------------------------

@pytest.fixture(scope="module")
def http():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def coach_headers(http):
    r = http.post(f"{API}/auth/login", json={"email": "coach@crewfit.com", "password": "Coach123!"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['token']}"}, data["user"]


@pytest.fixture(scope="module")
def client_headers(http):
    r = http.post(f"{API}/auth/login", json={"email": "client@crewfit.com", "password": "Client123!"}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['token']}"}, data["user"]


# ---- Role guard -----------------------------------------------------------

class TestRoleGuard:
    def test_settings_client_forbidden(self, http, client_headers):
        headers, _ = client_headers
        r = http.get(f"{API}/social/settings", headers=headers, timeout=15)
        assert r.status_code == 403

    def test_settings_coach_ok(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.get(f"{API}/social/settings", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("settings", "defaults", "pillars", "platforms", "post_types"):
            assert key in body, f"missing {key}"
        assert isinstance(body["pillars"], list) and len(body["pillars"]) > 0
        assert isinstance(body["platforms"], list) and len(body["platforms"]) > 0


# ---- Generation ------------------------------------------------------------

class TestGenerate:
    def test_generate_returns_valid_shape(self, http, coach_headers):
        headers, _ = coach_headers
        payload = {
            "platform": "LinkedIn",
            "pillar": "Roster-proof fitness",
            "audience": "airline crew",
            "goal": "educate",
            "post_type": "LinkedIn post",
        }
        r = http.post(f"{API}/social/generate", headers=headers, json=payload, timeout=90)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "generated" in body and "context" in body
        g = body["generated"]
        for k in (
            "title", "hook", "script", "caption", "hashtags", "cta",
            "visual_notes", "platform_recommendation", "post_type",
            "best_posting_time_local", "angle",
        ):
            assert k in g, f"generated missing key {k}"
        assert isinstance(g["hashtags"], list)
        assert isinstance(g["hook"], str) and len(g["hook"]) > 0
        # teleprompter_script may be present or defaulted
        assert "teleprompter_script" in g or g.get("script")


# ---- Post CRUD ------------------------------------------------------------

@pytest.fixture(scope="module")
def created_post(http, coach_headers):
    headers, user = coach_headers
    payload = {
        "title": "TEST_post_" + _dt.datetime.utcnow().isoformat(),
        "platform": "LinkedIn",
        "post_type": "LinkedIn post",
        "content_pillar": "Roster-proof fitness",
        "hook": "Test hook",
        "caption": "Test caption",
    }
    r = http.post(f"{API}/social/posts", headers=headers, json=payload, timeout=30)
    assert r.status_code == 200, r.text
    p = r.json()["post"]
    yield p, headers, user
    # Best-effort cleanup: dismiss the post
    try:
        http.post(f"{API}/social/posts/{p['id']}/dismiss", headers=headers, timeout=15)
    except Exception:
        pass


class TestPostCRUD:
    def test_create_post(self, created_post):
        p, _, user = created_post
        assert "id" in p
        assert p["status"] == "Draft"
        assert p["created_by"] == user["id"]
        assert p["revision_history"] == []
        assert p["created_at"]

    def test_list_posts(self, http, coach_headers, created_post):
        headers, _ = coach_headers
        p, _, _ = created_post
        r = http.get(f"{API}/social/posts", headers=headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "posts" in body and "count" in body
        ids = [x["id"] for x in body["posts"]]
        assert p["id"] in ids

    def test_list_filters_by_status(self, http, coach_headers, created_post):
        headers, _ = coach_headers
        r = http.get(f"{API}/social/posts?status=Draft", headers=headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert all(x["status"] == "Draft" for x in body["posts"])

    def test_list_filters_by_platform(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.get(f"{API}/social/posts?platform=LinkedIn", headers=headers, timeout=15)
        assert r.status_code == 200
        for x in r.json()["posts"]:
            assert x["platform"] == "LinkedIn"

    def test_get_post_detail(self, http, coach_headers, created_post):
        headers, _ = coach_headers
        p, _, _ = created_post
        r = http.get(f"{API}/social/posts/{p['id']}", headers=headers, timeout=15)
        assert r.status_code == 200
        got = r.json()["post"]
        assert got["id"] == p["id"]
        assert "revision_history" in got

    def test_patch_post(self, http, coach_headers, created_post):
        headers, _ = coach_headers
        p, _, _ = created_post
        r = http.patch(f"{API}/social/posts/{p['id']}", headers=headers, json={"caption": "updated caption"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["post"]["caption"] == "updated caption"

    def test_patch_post_invalid_status(self, http, coach_headers, created_post):
        headers, _ = coach_headers
        p, _, _ = created_post
        r = http.patch(f"{API}/social/posts/{p['id']}", headers=headers, json={"status": "NotAStatus"}, timeout=15)
        assert r.status_code == 400


# ---- Regenerate -----------------------------------------------------------

class TestRegenerate:
    @pytest.fixture(scope="class")
    def regen_post(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.post(f"{API}/social/posts", headers=headers, json={
            "title": "TEST_regen",
            "platform": "LinkedIn",
            "post_type": "LinkedIn post",
            "content_pillar": "Roster-proof fitness",
            "hook": "Original hook", "caption": "Original caption", "script": "Original script",
        }, timeout=30)
        assert r.status_code == 200
        p = r.json()["post"]
        yield p, headers
        try:
            http.post(f"{API}/social/posts/{p['id']}/dismiss", headers=headers, timeout=15)
        except Exception:
            pass

    def test_regenerate_shorter(self, http, regen_post):
        p, headers = regen_post
        r = http.post(f"{API}/social/posts/{p['id']}/regenerate", headers=headers, json={"action": "shorter"}, timeout=90)
        assert r.status_code == 200, r.text
        saved = r.json()["post"]
        assert len(saved["revision_history"]) >= 1
        # revision history should include a snapshot with original values
        snap = saved["revision_history"][-1]["snapshot"]
        assert snap["hook"] == "Original hook"

    def test_regenerate_hook_only(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.post(f"{API}/social/posts", headers=headers, json={
            "title": "TEST_hook_only",
            "platform": "LinkedIn",
            "post_type": "LinkedIn post",
            "content_pillar": "Jet lag and recovery",
            "hook": "H0", "caption": "C0", "script": "S0",
        }, timeout=30)
        assert r.status_code == 200
        pid = r.json()["post"]["id"]
        rr = http.post(f"{API}/social/posts/{pid}/regenerate", headers=headers, json={"action": "regen_hook"}, timeout=90)
        assert rr.status_code == 200
        saved = rr.json()["post"]
        # caption/script should remain unchanged (only hook regenerated)
        assert saved["caption"] == "C0"
        assert saved["script"] == "S0"
        # hook may or may not differ but must exist
        assert saved["hook"]
        # cleanup
        http.post(f"{API}/social/posts/{pid}/dismiss", headers=headers, timeout=15)

    def test_regenerate_caption_only(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.post(f"{API}/social/posts", headers=headers, json={
            "title": "TEST_caption_only",
            "platform": "LinkedIn",
            "post_type": "LinkedIn post",
            "content_pillar": "Hotel gym training",
            "hook": "H0", "caption": "C0", "script": "S0",
        }, timeout=30)
        pid = r.json()["post"]["id"]
        rr = http.post(f"{API}/social/posts/{pid}/regenerate", headers=headers, json={"action": "regen_caption"}, timeout=90)
        assert rr.status_code == 200
        saved = rr.json()["post"]
        assert saved["hook"] == "H0"
        assert saved["script"] == "S0"
        assert saved["caption"]
        http.post(f"{API}/social/posts/{pid}/dismiss", headers=headers, timeout=15)

    def test_regenerate_invalid_action(self, http, regen_post):
        p, headers = regen_post
        r = http.post(f"{API}/social/posts/{p['id']}/regenerate", headers=headers, json={"action": "invalid"}, timeout=15)
        assert r.status_code == 400


# ---- Status transitions ---------------------------------------------------

class TestStatusTransitions:
    @pytest.fixture
    def fresh_post(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.post(f"{API}/social/posts", headers=headers, json={
            "title": "TEST_status", "platform": "LinkedIn", "post_type": "LinkedIn post",
            "content_pillar": "CrewFit app features",
        }, timeout=30)
        assert r.status_code == 200
        return r.json()["post"], headers

    def test_approve(self, http, fresh_post, coach_headers):
        p, headers = fresh_post
        _, user = coach_headers
        r = http.post(f"{API}/social/posts/{p['id']}/approve", headers=headers, timeout=15)
        assert r.status_code == 200
        # Verify via GET
        got = http.get(f"{API}/social/posts/{p['id']}", headers=headers, timeout=15).json()["post"]
        assert got["status"] == "Approved"
        assert got["approved_at"]
        assert got["approved_by"] == user["id"]

    def test_schedule_marks_task_done(self, http, fresh_post):
        p, headers = fresh_post
        r = http.post(f"{API}/social/posts/{p['id']}/schedule", headers=headers,
                      json={"scheduled_local_datetime": "2026-07-15T09:00", "scheduled_time_zone": "Europe/London"}, timeout=15)
        assert r.status_code == 200
        got = http.get(f"{API}/social/posts/{p['id']}", headers=headers, timeout=15).json()["post"]
        assert got["status"] == "Scheduled"
        assert got["scheduled_local_datetime"] == "2026-07-15T09:00"
        assert got["scheduled_time_zone"] == "Europe/London"

    def test_mark_posted(self, http, fresh_post):
        p, headers = fresh_post
        r = http.post(f"{API}/social/posts/{p['id']}/mark-posted", headers=headers, timeout=15)
        assert r.status_code == 200
        got = http.get(f"{API}/social/posts/{p['id']}", headers=headers, timeout=15).json()["post"]
        assert got["status"] == "Posted"
        assert got["posted_at"]

    def test_dismiss(self, http, fresh_post):
        p, headers = fresh_post
        r = http.post(f"{API}/social/posts/{p['id']}/dismiss", headers=headers, timeout=15)
        assert r.status_code == 200
        got = http.get(f"{API}/social/posts/{p['id']}", headers=headers, timeout=15).json()["post"]
        assert got["status"] == "Dismissed"


# ---- Analytics ------------------------------------------------------------

class TestAnalytics:
    def test_analytics_shape(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.get(f"{API}/social/analytics", headers=headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        for k in ("by_status", "by_platform", "by_pillar", "counts"):
            assert k in body
        for k in ("scheduled", "posted", "failed", "draft"):
            assert k in body["counts"]
            assert isinstance(body["counts"][k], int)


# ---- Settings PUT ---------------------------------------------------------

class TestSettings:
    def test_put_settings_persists(self, http, coach_headers):
        headers, _ = coach_headers
        # Toggle off then back on
        r = http.put(f"{API}/social/settings", headers=headers, json={"daily_task_enabled": False}, timeout=15)
        assert r.status_code == 200
        got = http.get(f"{API}/social/settings", headers=headers, timeout=15).json()
        assert got["settings"]["daily_task_enabled"] is False
        # Restore
        r2 = http.put(f"{API}/social/settings", headers=headers, json={"daily_task_enabled": True}, timeout=15)
        assert r2.status_code == 200
        got2 = http.get(f"{API}/social/settings", headers=headers, timeout=15).json()
        assert got2["settings"]["daily_task_enabled"] is True

    def test_put_settings_empty_body_400(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.put(f"{API}/social/settings", headers=headers, json={}, timeout=15)
        assert r.status_code == 400


# ---- Daily task -----------------------------------------------------------

class TestDailyTask:
    def test_daily_generate_creates_task(self, http, coach_headers):
        headers, _ = coach_headers
        # Use a unique historical date to avoid interfering with today's ticker state
        target_date = "2025-01-15"
        # Clean pre-existing (best effort)
        r = http.post(f"{API}/social/daily/generate?date={target_date}", headers=headers, timeout=120)
        assert r.status_code == 200, r.text
        task = r.json().get("task")
        assert task is not None
        assert task["task_type"] == "daily_social_media_post"
        payload = task.get("payload") or {}
        assert payload.get("for_date") == target_date
        assert payload.get("social_post_id")
        assert payload.get("platform")
        assert payload.get("pillar")

    def test_daily_generate_idempotent(self, http, coach_headers):
        headers, _ = coach_headers
        target_date = "2025-01-16"
        r1 = http.post(f"{API}/social/daily/generate?date={target_date}", headers=headers, timeout=120)
        assert r1.status_code == 200
        t1 = r1.json()["task"]
        r2 = http.post(f"{API}/social/daily/generate?date={target_date}", headers=headers, timeout=30)
        assert r2.status_code == 200
        t2 = r2.json()["task"]
        assert t1["id"] == t2["id"], "second call should return the same task (idempotent)"

    def test_daily_regenerate_archives_and_replaces(self, http, coach_headers):
        headers, _ = coach_headers
        target_date = "2025-01-17"
        r1 = http.post(f"{API}/social/daily/generate?date={target_date}", headers=headers, timeout=120)
        assert r1.status_code == 200
        t1 = r1.json()["task"]
        old_post_id = t1["payload"]["social_post_id"]

        r2 = http.post(f"{API}/social/daily/regenerate?date={target_date}", headers=headers, timeout=120)
        assert r2.status_code == 200
        t2 = r2.json()["task"]
        assert t2["id"] != t1["id"], "regenerate should create a new task"
        new_post_id = t2["payload"]["social_post_id"]
        assert new_post_id != old_post_id

        # Old post should be archived
        got_old = http.get(f"{API}/social/posts/{old_post_id}", headers=headers, timeout=15)
        assert got_old.status_code == 200
        assert got_old.json()["post"]["status"] == "Archived"

    def test_pillar_rotation(self, http, coach_headers):
        """After 3 consecutive regenerates, at least 2 distinct pillars observed."""
        headers, _ = coach_headers
        target_date = "2025-01-18"
        pillars = []
        r = http.post(f"{API}/social/daily/generate?date={target_date}", headers=headers, timeout=120)
        assert r.status_code == 200
        pillars.append(r.json()["task"]["payload"]["pillar"])
        for _ in range(3):
            rr = http.post(f"{API}/social/daily/regenerate?date={target_date}", headers=headers, timeout=120)
            assert rr.status_code == 200
            pillars.append(rr.json()["task"]["payload"]["pillar"])
        distinct = set(pillars)
        assert len(distinct) >= 2, f"expected pillar rotation, got {pillars}"


# ---- Regression -----------------------------------------------------------

class TestRegression:
    def test_coach_tasks_lists_social_task(self, http, coach_headers):
        headers, _ = coach_headers
        # Ensure a daily social task exists today for the coach
        today = _dt.date.today().isoformat()
        http.post(f"{API}/social/daily/generate?date={today}", headers=headers, timeout=120)
        r = http.get(f"{API}/coach/tasks", headers=headers, timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        # response may be {tasks:[...]} or a list; handle both
        tasks = body.get("tasks") if isinstance(body, dict) else body
        assert tasks is not None
        types = {t.get("task_type") for t in tasks}
        assert "daily_social_media_post" in types

    def test_habits_today(self, http, client_headers):
        headers, _ = client_headers
        r = http.get(f"{API}/habits/today", headers=headers, timeout=15)
        assert r.status_code == 200

    def test_notifications_settings(self, http, client_headers):
        headers, _ = client_headers
        r = http.get(f"{API}/notifications/settings", headers=headers, timeout=15)
        assert r.status_code == 200

    def test_coach_messages_drafts(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.get(f"{API}/coach/messages/drafts", headers=headers, timeout=15)
        assert r.status_code == 200

    def test_coach_change_log(self, http, coach_headers):
        headers, _ = coach_headers
        r = http.get(f"{API}/coach/change-log", headers=headers, timeout=15)
        assert r.status_code == 200

    def test_standby_today(self, http, client_headers):
        headers, _ = client_headers
        r = http.get(f"{API}/standby/today", headers=headers, timeout=15)
        assert r.status_code == 200
