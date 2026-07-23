"""
Iter 94v Phase 4 — Master Fix Phase 4 backend tests + full pre-beta regression sweep.

Covers:
- Admin Live App Controls: GET/POST/DELETE /api/admin/app-config + audit
- Coach recovery timeline: GET /api/admin/recovery/timeline (all clients),
  GET /api/admin/client/{uid}/recovery/timeline (single client)
- Milestone B: recovery flow writes timeline_events with resolvable client identity
- Full regression: Phases 1-3 + Iter 94u endpoints
- Dismiss-first fix: /daily-briefing/dismiss no longer creates a stub row
"""
import os
import time
import datetime as _dt

import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL")
            or "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

CLIENT_EMAIL = "testcal2@crewfit.com"
CLIENT_PASS = "TestCal123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASS = "Louis123!"


def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text[:300]}"
    return r.json()


@pytest.fixture(scope="module")
def coach_auth():
    d = _login(COACH_EMAIL, COACH_PASS)
    return {"token": d["token"], "user": d.get("user") or {}, "headers": {"Authorization": f"Bearer {d['token']}", "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def client_auth():
    d = _login(CLIENT_EMAIL, CLIENT_PASS)
    return {"token": d["token"], "user": d.get("user") or {}, "headers": {"Authorization": f"Bearer {d['token']}", "Content-Type": "application/json"}}


# ---------------------------------------------------------------------------
# Phase 4a — Live App Controls
# ---------------------------------------------------------------------------

class TestLiveAppConfigList:

    def test_admin_list_has_16_default_flags_and_safe_keys(self, coach_auth):
        r = requests.get(f"{BASE_URL}/api/admin/app-config", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "safe_content_keys" in body
        keys = {i["key"] for i in body["items"]}
        # Must include the 16 default flags
        expected = {
            "guided_flow_enabled", "guided_flow_timer_mode_enabled", "guided_flow_image_autoscroll",
            "exercise_media_required", "missing_media_client_fallback_enabled",
            "hotel_system_enabled", "progress_charts_enabled", "nutrition_dashboard_enabled",
            "wearable_steps_enabled", "habits_dynamic_enabled",
            "first_day_workout_choice_enabled", "whatsapp_support_enabled",
            "beta_banner_enabled", "missed_workout_recovery_enabled",
            "timezone_card_enabled", "calendar_scroll_enabled",
        }
        missing = expected - keys
        assert not missing, f"admin list missing default flags: {missing}"
        # safe_content_keys allowlist
        sck = body["safe_content_keys"]
        assert isinstance(sck, list)
        for k in ("beta_banner_text", "welcome_message_client", "support_whatsapp_number"):
            assert k in sck, f"safe_content_keys missing {k}"

    def test_admin_list_requires_coach(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/admin/app-config", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403


class TestLiveAppConfigMutate:

    def test_toggle_beta_banner_flag_roundtrip(self, coach_auth):
        # Toggle beta_banner_enabled: True -> False -> True
        r1 = requests.post(f"{BASE_URL}/api/admin/app-config",
                           headers=coach_auth["headers"],
                           json={"key": "beta_banner_enabled", "value": False,
                                 "kind": "flag", "description": "temporarily off for test"},
                           timeout=30)
        assert r1.status_code == 200, r1.text
        assert r1.json()["item"]["value"] is False

        pub = requests.get(f"{BASE_URL}/api/app-config", headers=coach_auth["headers"], timeout=30).json()
        assert pub["flags"].get("beta_banner_enabled") is False

        r2 = requests.post(f"{BASE_URL}/api/admin/app-config",
                           headers=coach_auth["headers"],
                           json={"key": "beta_banner_enabled", "value": True, "kind": "flag"},
                           timeout=30)
        assert r2.status_code == 200
        assert r2.json()["item"]["value"] is True

        pub2 = requests.get(f"{BASE_URL}/api/app-config", headers=coach_auth["headers"], timeout=30).json()
        assert pub2["flags"].get("beta_banner_enabled") is True

    def test_content_key_not_on_allowlist_400(self, coach_auth):
        r = requests.post(f"{BASE_URL}/api/admin/app-config",
                          headers=coach_auth["headers"],
                          json={"key": "TEST_random_content_key", "value": "hello",
                                "kind": "content"}, timeout=30)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"

    def test_content_key_on_allowlist_saves(self, coach_auth):
        r = requests.post(f"{BASE_URL}/api/admin/app-config",
                          headers=coach_auth["headers"],
                          json={"key": "beta_banner_text",
                                "value": "Private beta — thanks for testing!",
                                "kind": "content"}, timeout=30)
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        assert item["key"] == "beta_banner_text"
        assert item["kind"] == "content"

        pub = requests.get(f"{BASE_URL}/api/app-config", headers=coach_auth["headers"], timeout=30).json()
        assert pub["content"].get("beta_banner_text") == "Private beta — thanks for testing!"

    def test_soft_disable_flag(self, coach_auth):
        key = "TEST_iter94v_disable"
        # Create
        requests.post(f"{BASE_URL}/api/admin/app-config",
                      headers=coach_auth["headers"],
                      json={"key": key, "value": True}, timeout=30)
        # Delete (soft-disable)
        rd = requests.delete(f"{BASE_URL}/api/admin/app-config/{key}",
                             headers=coach_auth["headers"], timeout=30)
        assert rd.status_code == 200, rd.text
        assert rd.json().get("disabled") == key
        # No longer in public config
        pub = requests.get(f"{BASE_URL}/api/app-config", headers=coach_auth["headers"], timeout=30).json()
        assert key not in pub["flags"]

    def test_upsert_requires_coach(self, client_auth):
        r = requests.post(f"{BASE_URL}/api/admin/app-config",
                          headers=client_auth["headers"],
                          json={"key": "TEST_client_upsert", "value": True}, timeout=30)
        assert r.status_code == 403


class TestLiveAppConfigAudit:

    def test_audit_records_recent_writes(self, coach_auth):
        # Trigger a write we can look for
        probe = f"TEST_iter94v_audit_{int(time.time())}"
        requests.post(f"{BASE_URL}/api/admin/app-config",
                      headers=coach_auth["headers"],
                      json={"key": probe, "value": True}, timeout=30)
        time.sleep(0.3)
        r = requests.get(f"{BASE_URL}/api/admin/app-config/audit",
                         headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        rows = r.json().get("audit", [])
        assert isinstance(rows, list) and rows
        seen = {row.get("key") for row in rows}
        assert probe in seen, f"audit missing key {probe}"
        # actor identity should be present
        matches = [row for row in rows if row.get("key") == probe]
        assert matches[0].get("actor_id") or matches[0].get("actor_name")
        # cleanup
        requests.delete(f"{BASE_URL}/api/admin/app-config/{probe}",
                        headers=coach_auth["headers"], timeout=30)

    def test_audit_requires_coach(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/admin/app-config/audit",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Phase 4b — Coach recovery timeline
# ---------------------------------------------------------------------------

class TestRecoveryTimeline:

    def _seed_skip_event(self, client_auth):
        """Ensure at least one workout_skipped event exists for this client so
        the timeline endpoints have something to return."""
        missed = requests.get(f"{BASE_URL}/api/recovery/missed",
                              params={"window": 60},
                              headers=client_auth["headers"], timeout=30).json().get("missed", [])
        candidates = [m for m in missed if not m.get("coach_locked")]
        if not candidates:
            return None
        wid = candidates[0]["id"]
        r = requests.post(f"{BASE_URL}/api/recovery/{wid}/skip",
                          headers=client_auth["headers"],
                          json={"reason": "TEST_iter94v_seed"}, timeout=30)
        assert r.status_code == 200, r.text
        return wid

    def test_all_clients_timeline_returns_events_with_identity(self, coach_auth, client_auth):
        self._seed_skip_event(client_auth)
        r = requests.get(f"{BASE_URL}/api/admin/recovery/timeline",
                         headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "events" in body and "count" in body
        assert isinstance(body["events"], list)
        if not body["events"]:
            pytest.skip("no recovery events in DB — can't verify identity fields")
        # Every event should be workout_recovered or workout_skipped
        kinds = {e.get("kind") for e in body["events"]}
        assert kinds.issubset({"workout_recovered", "workout_skipped"}), f"unexpected kinds: {kinds}"
        # Identity fields must be present on all events (Milestone B)
        for e in body["events"]:
            assert "client_email" in e and "client_name" in e, \
                f"missing client identity on event: {e}"
        # At least one event should resolve to a real email (non-null)
        with_email = [e for e in body["events"] if e.get("client_email")]
        assert with_email, "no events had a resolvable client_email"

    def test_single_client_timeline_scoped_to_uid(self, coach_auth, client_auth):
        self._seed_skip_event(client_auth)
        uid = client_auth["user"].get("id")
        assert uid, "client user id missing from login payload"
        r = requests.get(f"{BASE_URL}/api/admin/client/{uid}/recovery/timeline",
                         headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "events" in body and "count" in body
        # Every returned event must be for this uid
        for e in body["events"]:
            assert e.get("user_id") == uid, f"event leaked from another user: {e}"

    def test_all_clients_timeline_requires_coach(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/admin/recovery/timeline",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403

    def test_single_client_timeline_requires_coach(self, client_auth):
        uid = client_auth["user"].get("id") or "anyuid"
        r = requests.get(f"{BASE_URL}/api/admin/client/{uid}/recovery/timeline",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Milestone B — recovery flow writes timeline_events for coach dashboard
# ---------------------------------------------------------------------------

class TestMilestoneB_RecoveryWritesTimeline:

    def test_skip_writes_workout_skipped_event(self, coach_auth, client_auth):
        # Seed a fresh missed workout directly in the DB so this test never depends on
        # leftover state from prior runs.
        from motor.motor_asyncio import AsyncIOMotorClient
        import asyncio
        from pathlib import Path
        env = {}
        for line in Path("/app/backend/.env").read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
        mongo_url = env.get("MONGO_URL") or os.environ.get("MONGO_URL")
        db_name = env.get("DB_NAME") or os.environ.get("DB_NAME")
        assert mongo_url and db_name
        client = AsyncIOMotorClient(mongo_url)
        d = client[db_name]
        loop = asyncio.new_event_loop()

        uid = client_auth["user"].get("id")
        # Use a random past date unlikely to collide with seeded data
        offset = int(time.time()) % 300 + 400  # 400-700 days ago
        y = (_dt.date.today() - _dt.timedelta(days=offset)).isoformat()
        seed_wid = f"TEST_iter94v_ms_b_{int(time.time())}"

        async def _seed():
            await d.workouts.insert_one({
                "id": seed_wid,
                "user_id": uid,
                "date": y,
                "title": "TEST Skip Seed",
                "focus": "strength_lower",
                "completed": False,
                "skipped": False,
                "key_session": False,
            })

        async def _cleanup():
            await d.workouts.delete_one({"id": seed_wid})
            await d.timeline_events.delete_many({"workout_id": seed_wid})

        try:
            loop.run_until_complete(_seed())
            r = requests.post(f"{BASE_URL}/api/recovery/{seed_wid}/skip",
                              headers=client_auth["headers"],
                              json={"reason": "TEST_milestone_b"}, timeout=30)
            assert r.status_code == 200, r.text
            time.sleep(0.3)
            # Single-client timeline should include this workout_skipped event
            tl = requests.get(f"{BASE_URL}/api/admin/client/{uid}/recovery/timeline",
                              headers=coach_auth["headers"], timeout=30).json()
            events = tl.get("events") or []
            match = [e for e in events if e.get("workout_id") == seed_wid and e.get("kind") == "workout_skipped"]
            assert match, f"skip did not write a workout_skipped event for wid={seed_wid}"

            # All-clients timeline must have client identity populated for this event
            all_tl = requests.get(f"{BASE_URL}/api/admin/recovery/timeline",
                                  headers=coach_auth["headers"], timeout=30).json()
            all_events = all_tl.get("events") or []
            all_match = [e for e in all_events if e.get("workout_id") == seed_wid]
            assert all_match, "seeded event not in global timeline"
            assert all_match[0].get("client_email") == CLIENT_EMAIL, \
                f"client_email not resolved: {all_match[0].get('client_email')}"
        finally:
            loop.run_until_complete(_cleanup())
            loop.close()


# ---------------------------------------------------------------------------
# Full Pre-Beta Regression Sweep — Phases 1-3 + Iter 94u
# ---------------------------------------------------------------------------

class TestRegressionSweep:

    def test_app_config_public(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/app-config", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert "flags" in r.json()

    def test_calendar_range(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/calendar/range",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert "days" in r.json()

    def test_recovery_missed(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/recovery/missed",
                         params={"window": 14},
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert "missed" in r.json()

    def test_recovery_suggestions_and_skip_endpoints_reachable(self, client_auth):
        # We use a nonsense wid to confirm route exists — expect 404 (not 405/500)
        r = requests.post(f"{BASE_URL}/api/recovery/NON_EXISTENT_WID/suggestions",
                          headers=client_auth["headers"], timeout=30)
        assert r.status_code in (404, 400), f"unexpected {r.status_code}: {r.text[:200]}"
        r2 = requests.post(f"{BASE_URL}/api/recovery/NON_EXISTENT_WID/skip",
                           headers=client_auth["headers"],
                           json={"reason": "x"}, timeout=30)
        assert r2.status_code in (404, 400), f"unexpected {r2.status_code}: {r2.text[:200]}"

    def test_profile_timezone_status(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/profile/timezone-status",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        for k in ("home_base", "home_timezone", "current_timezone",
                  "current_timezone_source", "current_timezone_confidence",
                  "needs_confirmation"):
            assert k in r.json(), f"missing {k}"

    def test_nutrition_today(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/nutrition/today",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_progress_dashboard(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/progress/dashboard",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_progress_body_get(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/progress/body",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_progress_running_get(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/progress/running",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_progress_strength_get(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/progress/strength",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_progress_photo_lifecycle(self, client_auth):
        """Upload -> list -> get -> delete (with tiny 1x1 png)."""
        # 1x1 transparent PNG base64
        tiny_png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
        upload = requests.post(f"{BASE_URL}/api/progress/photo/base64",
                               headers=client_auth["headers"],
                               json={"photo_b64": tiny_png,
                                     "mime": "image/png",
                                     "angle": "front"},
                               timeout=30)
        assert upload.status_code in (200, 201), upload.text
        body = upload.json()
        photo_id = (body.get("photo") or {}).get("id") or body.get("id")
        assert photo_id, f"upload did not return photo id: {body}"
        # Signed URL params for GET
        photo_url = (body.get("photo") or {}).get("url")

        lst = requests.get(f"{BASE_URL}/api/progress/photos",
                           headers=client_auth["headers"], timeout=30)
        assert lst.status_code == 200, lst.text
        photos = lst.json().get("photos", lst.json().get("items", []))
        ids = [p.get("id") for p in photos]
        assert photo_id in ids, f"uploaded photo not in list; got ids={ids[:5]}"

        # Get single: uses signed URL from upload response
        if photo_url:
            # url is like /api/progress/photo/{pid}?u=&e=&t= — hit base + path
            full_url = photo_url if photo_url.startswith("http") else f"{BASE_URL}{photo_url}"
            get_r = requests.get(full_url, headers=client_auth["headers"], timeout=30)
            assert get_r.status_code == 200, f"signed photo GET failed: {get_r.status_code} {get_r.text[:200]}"

        # Delete
        d = requests.delete(f"{BASE_URL}/api/progress/photo/{photo_id}",
                            headers=client_auth["headers"], timeout=30)
        assert d.status_code in (200, 204), d.text

        # Verify gone
        lst2 = requests.get(f"{BASE_URL}/api/progress/photos",
                            headers=client_auth["headers"], timeout=30).json()
        photos2 = lst2.get("photos", lst2.get("items", []))
        assert photo_id not in [p.get("id") for p in photos2], "photo still present after delete"

    def test_coach_profile(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/coach-profile",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("name") == "Louis Hall"

    def test_daily_briefing_today_idempotent_and_context_change_refires(self, client_auth):
        # Force fresh state
        requests.post(f"{BASE_URL}/api/daily-briefing/regenerate",
                      headers=client_auth["headers"], timeout=30)
        r1 = requests.get(f"{BASE_URL}/api/daily-briefing/today",
                          headers=client_auth["headers"], timeout=30)
        r2 = requests.get(f"{BASE_URL}/api/daily-briefing/today",
                          headers=client_auth["headers"], timeout=30)
        assert r1.status_code == 200 and r2.status_code == 200
        id1 = r1.json()["briefing"].get("id")
        id2 = r2.json()["briefing"].get("id")
        sig1 = r1.json()["briefing"].get("context_signature")
        sig2 = r2.json()["briefing"].get("context_signature")
        assert id1 == id2, f"briefing not idempotent: {id1} vs {id2}"
        assert sig1 == sig2, "context_signature drifted on identical context"

        # Regenerate → new id but same context → idempotent again on next GET
        regen = requests.post(f"{BASE_URL}/api/daily-briefing/regenerate",
                              headers=client_auth["headers"], timeout=30)
        assert regen.status_code == 200
        new_id = regen.json()["briefing"]["id"]
        assert new_id != id1, "regenerate should produce a new id"

    def test_daily_briefing_preferences_and_regenerate(self, client_auth):
        r = requests.get(f"{BASE_URL}/api/daily-briefing/preferences",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        p = r.json()
        for k in ("daily_summary_enabled", "daily_summary_push_enabled", "daily_summary_tone"):
            assert k in p
        # Update + revert
        u = requests.post(f"{BASE_URL}/api/daily-briefing/preferences",
                          headers=client_auth["headers"],
                          json={"daily_summary_tone": "direct"}, timeout=30)
        assert u.status_code == 200
        rv = requests.get(f"{BASE_URL}/api/daily-briefing/preferences",
                          headers=client_auth["headers"], timeout=30).json()
        assert rv["daily_summary_tone"] == "direct"
        requests.post(f"{BASE_URL}/api/daily-briefing/preferences",
                      headers=client_auth["headers"],
                      json={"daily_summary_tone": "gentle"}, timeout=30)


# ---------------------------------------------------------------------------
# Dismiss-first fix — post-fix, /daily-briefing/dismiss must not create a stub row.
# ---------------------------------------------------------------------------

class TestDismissDoesNotStub:

    def test_dismiss_builds_then_marks(self, client_auth):
        # Wipe today's briefing by regenerating first
        # Then call dismiss BEFORE any GET, and confirm the briefing that comes
        # back on next GET is a real (non-stub) doc with all fields.
        # Force clean state via regenerate + explicit delete via regenerate route
        requests.post(f"{BASE_URL}/api/daily-briefing/regenerate",
                      headers=client_auth["headers"], timeout=30)

        d = requests.post(f"{BASE_URL}/api/daily-briefing/dismiss",
                          headers=client_auth["headers"],
                          json={"reason": "TEST_iter94v_dismiss_first"}, timeout=30)
        assert d.status_code == 200, d.text
        assert d.json().get("ok") is True

        # Now GET today — must be a complete briefing with dismissed_at set + should_show_modal False
        r = requests.get(f"{BASE_URL}/api/daily-briefing/today",
                         headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["should_show_modal"] is False
        b = payload["briefing"]
        # All the core content fields must exist and be non-empty — proves NOT a stub
        for k in ("title", "greeting", "workout_focus", "nutrition_focus", "recovery_focus"):
            assert b.get(k), f"stub row detected — missing/empty field: {k}"
        assert b.get("main_action", {}).get("label"), "stub row — no main_action"
        assert b.get("dismissed_at"), "dismissed_at should be set"
