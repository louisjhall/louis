"""
CrewFit — Notifications V1 backend regression suite.

Covers:
  * GET/PUT /api/notifications/settings
  * POST /api/notifications/permission
  * GET /api/notifications  +  /api/notifications/unread-count
  * POST /api/notifications/{id}/read + /api/notifications/read-all
  * Hook wiring: /api/coach/messages/generate  → coach draft_ready
  *              /api/coach/messages/{id}/approve → client coach_message
  * Duplicate prevention (dedupe_key uniqueness per draft)
  * Role guards (anonymous → 401)
  * Regression on habits + coach endpoints
"""
import os
import time
import uuid
import pytest
import requests

def _load_frontend_env():
    p = "/app/frontend/.env"
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line.startswith("EXPO_PUBLIC_BACKEND_URL=") and "EXPO_PUBLIC_BACKEND_URL" not in os.environ:
                os.environ["EXPO_PUBLIC_BACKEND_URL"] = line.split("=", 1)[1]


_load_frontend_env()
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL not set"
API = f"{BASE_URL}/api"


# ---------- shared fixtures ----------

@pytest.fixture(scope="module")
def s():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


def _login(s, email, password):
    r = s.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="module")
def client_auth(s):
    d = _login(s, "client@crewfit.com", "Client123!")
    return {"token": d["token"], "user": d["user"],
            "headers": {"Authorization": f"Bearer {d['token']}"}}


@pytest.fixture(scope="module")
def coach_auth(s):
    d = _login(s, "coach@crewfit.com", "Coach123!")
    return {"token": d["token"], "user": d["user"],
            "headers": {"Authorization": f"Bearer {d['token']}"}}


@pytest.fixture(scope="module")
def fresh_user(s):
    """Create a fresh client user for the 'defaults' test."""
    email = f"TEST_notif_{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/auth/signup",
               json={"email": email, "name": "Notif Test", "password": "Passw0rd!", "role": "client"},
               timeout=30)
    assert r.status_code == 200, f"signup: {r.status_code} {r.text}"
    d = r.json()
    return {"token": d["token"], "user": d["user"], "email": email,
            "headers": {"Authorization": f"Bearer {d['token']}"}}


# ---------- 1) Settings + defaults ----------

class TestSettingsDefaults:
    def test_fresh_user_defaults(self, s, fresh_user):
        r = s.get(f"{API}/notifications/settings", headers=fresh_user["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "settings" in body and "defaults" in body
        st = body["settings"]
        # Permission status must be 'not_requested' for a fresh user
        assert st.get("permission_status") == "not_requested", st
        # All 7 categories default true
        for k in ("check_ins", "habits", "workouts", "coach_messages",
                  "weekly_videos", "roster", "programme_updates"):
            assert st.get(k) is True, f"{k}={st.get(k)}"
        assert st.get("quiet_hours_start") == "21:00"
        assert st.get("quiet_hours_end") == "07:00"
        assert st.get("preferred_reminder_time") == "07:30"
        assert st.get("travel_use_current_tz") is True

    def test_put_partial_merge(self, s, fresh_user):
        # Set a first change: only workouts=false and preferred time=08:15
        r = s.put(f"{API}/notifications/settings",
                  headers=fresh_user["headers"],
                  json={"workouts": False, "preferred_reminder_time": "08:15"},
                  timeout=15)
        assert r.status_code == 200, r.text
        st = r.json()["settings"]
        assert st["workouts"] is False
        assert st["preferred_reminder_time"] == "08:15"
        # Others should retain their defaults
        assert st["habits"] is True
        assert st["check_ins"] is True
        assert st["quiet_hours_start"] == "21:00"

        # Second change: only quiet_hours_start. workouts=False must still be there.
        r2 = s.put(f"{API}/notifications/settings",
                   headers=fresh_user["headers"],
                   json={"quiet_hours_start": "22:30"},
                   timeout=15)
        assert r2.status_code == 200
        st2 = r2.json()["settings"]
        assert st2["quiet_hours_start"] == "22:30"
        assert st2["workouts"] is False                    # <-- merge, not wipe
        assert st2["preferred_reminder_time"] == "08:15"

    def test_put_empty_body_400(self, s, fresh_user):
        r = s.put(f"{API}/notifications/settings",
                  headers=fresh_user["headers"], json={}, timeout=15)
        assert r.status_code == 400, r.text


# ---------- 2) Permission ----------

class TestPermission:
    def test_granted(self, s, fresh_user):
        r = s.post(f"{API}/notifications/permission",
                   headers=fresh_user["headers"],
                   json={"status": "granted", "platform": "ios"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "granted"
        # Verify GET reflects it
        st = s.get(f"{API}/notifications/settings",
                   headers=fresh_user["headers"], timeout=15).json()["settings"]
        assert st["permission_status"] == "granted"

    def test_denied(self, s, fresh_user):
        r = s.post(f"{API}/notifications/permission",
                   headers=fresh_user["headers"],
                   json={"status": "denied"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["status"] == "denied"

    def test_not_requested(self, s, fresh_user):
        r = s.post(f"{API}/notifications/permission",
                   headers=fresh_user["headers"],
                   json={"status": "not_requested"}, timeout=15)
        assert r.status_code == 200

    def test_invalid_status_400(self, s, fresh_user):
        r = s.post(f"{API}/notifications/permission",
                   headers=fresh_user["headers"],
                   json={"status": "maybe"}, timeout=15)
        assert r.status_code == 400, r.text


# ---------- 3) List / unread / read / read-all ----------

class TestListAndRead:
    def test_list_and_unread_shape(self, s, fresh_user):
        r = s.get(f"{API}/notifications", headers=fresh_user["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body.get("notifications"), list)
        assert isinstance(body.get("unread"), int)
        # Fresh user should have zero notifications
        assert body["notifications"] == []
        assert body["unread"] == 0

        u = s.get(f"{API}/notifications/unread-count",
                  headers=fresh_user["headers"], timeout=15)
        assert u.status_code == 200
        assert u.json() == {"unread": 0}

    def test_read_nonexistent_returns_404(self, s, client_auth):
        r = s.post(f"{API}/notifications/does-not-exist-xyz/read",
                   headers=client_auth["headers"], timeout=15)
        assert r.status_code == 404, r.text

    def test_read_all_empty_returns_marked_int(self, s, fresh_user):
        r = s.post(f"{API}/notifications/read-all",
                   headers=fresh_user["headers"], timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json().get("marked"), int)


# ---------- 4) Role guards ----------

class TestRoleGuards:
    def test_anonymous_list_401(self, s):
        r = s.get(f"{API}/notifications", timeout=15)
        assert r.status_code == 401

    def test_anonymous_settings_401(self, s):
        r = s.get(f"{API}/notifications/settings", timeout=15)
        assert r.status_code == 401

    def test_anonymous_permission_401(self, s):
        r = s.post(f"{API}/notifications/permission",
                   json={"status": "granted"}, timeout=15)
        assert r.status_code == 401


# ---------- 5) Hook wiring: coach generate + approve ----------

def _wait_for_notif(s, headers, predicate, tries=10, delay=0.6):
    """Poll GET /notifications until predicate matches or timeout (~6s)."""
    last = []
    for _ in range(tries):
        r = s.get(f"{API}/notifications", headers=headers, timeout=15)
        if r.status_code == 200:
            rows = r.json().get("notifications", [])
            last = rows
            for row in rows:
                if predicate(row):
                    return row
        time.sleep(delay)
    return None, last


class TestHookWiring:
    """Client sends a message → coach gets coach_draft_ready → coach approves
       → client gets coach_message notification."""

    @pytest.fixture(scope="class")
    def client_and_coach(self, s):
        c = _login(s, "client@crewfit.com", "Client123!")
        k = _login(s, "coach@crewfit.com", "Coach123!")
        return {
            "client": {"token": c["token"], "user": c["user"],
                       "headers": {"Authorization": f"Bearer {c['token']}"}},
            "coach": {"token": k["token"], "user": k["user"],
                      "headers": {"Authorization": f"Bearer {k['token']}"}},
        }

    def test_generate_creates_coach_draft_ready(self, s, client_and_coach):
        coach = client_and_coach["coach"]
        client_id = client_and_coach["client"]["user"]["id"]
        # Trigger draft generation
        r = s.post(f"{API}/coach/messages/generate",
                   headers=coach["headers"],
                   json={"client_id": client_id,
                         "custom_instruction": "TEST_notif hook wiring"},
                   timeout=60)
        assert r.status_code == 200, r.text
        draft = r.json().get("draft")
        assert draft and draft.get("id")
        self.__class__.draft_id_1 = draft["id"]

        # Poll coach notifications for coach_draft_ready with the correct action_url
        found = None
        for _ in range(12):
            n = s.get(f"{API}/notifications", headers=coach["headers"], timeout=15).json()
            for row in n.get("notifications", []):
                if (row.get("notif_type") == "coach_draft_ready"
                        and row.get("related_id") == draft["id"]):
                    found = row; break
            if found:
                break
            time.sleep(0.5)
        assert found is not None, "coach_draft_ready notification not enqueued"
        assert found.get("category") == "coach_messages"
        assert found.get("action_url") == f"/coach/draft/{draft['id']}"
        assert found.get("dedupe_key") == f"draft::{draft['id']}"

    def test_second_generate_creates_second_notification_unique_dedupe(self, s, client_and_coach):
        coach = client_and_coach["coach"]
        client_id = client_and_coach["client"]["user"]["id"]
        r = s.post(f"{API}/coach/messages/generate",
                   headers=coach["headers"],
                   json={"client_id": client_id,
                         "custom_instruction": "TEST_notif hook wiring #2"},
                   timeout=60)
        assert r.status_code == 200, r.text
        draft2 = r.json()["draft"]
        assert draft2["id"] != self.__class__.draft_id_1
        self.__class__.draft_id_2 = draft2["id"]

        # Wait for the second coach_draft_ready row (different dedupe_key ⇒ new row)
        found = None
        for _ in range(12):
            n = s.get(f"{API}/notifications", headers=coach["headers"], timeout=15).json()
            for row in n.get("notifications", []):
                if row.get("dedupe_key") == f"draft::{draft2['id']}":
                    found = row; break
            if found:
                break
            time.sleep(0.5)
        assert found is not None, "second coach_draft_ready did not create its own notification"
        assert found.get("related_id") == draft2["id"]

        # Sanity: both dedupe_key rows still exist and are distinct
        all_ = s.get(f"{API}/notifications", headers=coach["headers"], timeout=15).json()["notifications"]
        keys = [r for r in all_ if r.get("notif_type") == "coach_draft_ready"
                and r.get("dedupe_key") in (f"draft::{self.__class__.draft_id_1}",
                                            f"draft::{self.__class__.draft_id_2}")]
        # At least one row per key
        d1 = [r for r in keys if r.get("dedupe_key") == f"draft::{self.__class__.draft_id_1}"]
        d2 = [r for r in keys if r.get("dedupe_key") == f"draft::{self.__class__.draft_id_2}"]
        assert len(d1) == 1 and len(d2) == 1, f"expected exactly 1 row per dedupe key; got d1={len(d1)} d2={len(d2)}"

    def test_approve_creates_client_coach_message_notification(self, s, client_and_coach):
        coach = client_and_coach["coach"]
        client = client_and_coach["client"]
        draft_id = self.__class__.draft_id_2
        # Approve the second draft (leave first pending)
        r = s.post(f"{API}/coach/messages/{draft_id}/approve",
                   headers=coach["headers"],
                   json={"coach_edited_text": "TEST_notif approved reply — please ignore."},
                   timeout=30)
        assert r.status_code == 200, r.text

        # Poll client's notifications for coach_message
        found = None
        for _ in range(12):
            n = s.get(f"{API}/notifications", headers=client["headers"], timeout=15).json()
            for row in n.get("notifications", []):
                if row.get("notif_type") == "coach_message":
                    found = row; break
            if found:
                break
            time.sleep(0.5)
        assert found is not None, "client did not get coach_message notification"
        assert found.get("category") == "coach_messages"
        assert found.get("action_url") == "/(client)/messages"
        title = found.get("title") or ""
        # Coach name should appear in the title
        coach_name = client_and_coach["coach"]["user"].get("name") or ""
        assert coach_name and coach_name in title, f"title={title!r} coach_name={coach_name!r}"

    def test_double_approve_400(self, s, client_and_coach):
        coach = client_and_coach["coach"]
        draft_id = self.__class__.draft_id_2
        r = s.post(f"{API}/coach/messages/{draft_id}/approve",
                   headers=coach["headers"],
                   json={"coach_edited_text": "second attempt"}, timeout=30)
        assert r.status_code == 400, r.text

    def test_second_approve_creates_second_coach_message_unique_dedupe(self, s, client_and_coach):
        """Approve draft_id_1 (still pending from test #1) → client should now have
        TWO coach_message rows (one per approved draft) with different dedupe_keys
        because each sent message has a unique id."""
        coach = client_and_coach["coach"]
        client = client_and_coach["client"]
        draft_id_a = self.__class__.draft_id_1  # still 'waiting_approval'

        # Approve draft A
        r = s.post(f"{API}/coach/messages/{draft_id_a}/approve",
                   headers=coach["headers"],
                   json={"coach_edited_text": "TEST_notif approved reply A."},
                   timeout=30)
        assert r.status_code == 200, r.text
        sent_msg_a = r.json().get("message", {})
        assert sent_msg_a.get("id"), "approve didn't return a message id"
        msg_id_a = sent_msg_a["id"]

        # Poll client notifications until we see two distinct coach_message rows
        dedupe_a = f"coach_msg::{msg_id_a}"
        rows = []
        for _ in range(15):
            n = s.get(f"{API}/notifications", headers=client["headers"], timeout=15).json()
            rows = [r for r in n.get("notifications", []) if r.get("notif_type") == "coach_message"]
            if any(row.get("dedupe_key") == dedupe_a for row in rows):
                break
            time.sleep(0.5)

        # Must contain dedupe_key for msg_a
        keys = [row.get("dedupe_key") for row in rows]
        assert dedupe_a in keys, (
            f"dedupe_key for approved draft A ({dedupe_a}) missing; found keys={keys}"
        )
        # And at least one OTHER coach_message row (from the earlier approve of draft_2)
        other_rows = [row for row in rows if row.get("dedupe_key") != dedupe_a]
        assert len(other_rows) >= 1, (
            f"expected a second coach_message row from earlier approve; got rows={rows}"
        )
        # All dedupe_keys must be unique per message
        assert len(set(keys)) == len(keys), f"duplicate dedupe_keys found: {keys}"
        # Verify related_id points to the sent message id
        row_a = next(r for r in rows if r.get("dedupe_key") == dedupe_a)
        assert row_a.get("related_id") == msg_id_a


# ---------- 6) List sorting + unread_only ----------

class TestListFilters:
    def test_sorted_desc_and_unread_only(self, s, client_auth):
        r = s.get(f"{API}/notifications", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()["notifications"]
        if len(rows) >= 2:
            # Newest first
            ts = [row["created_at"] for row in rows]
            assert ts == sorted(ts, reverse=True), "notifications must be sorted newest first"

        # unread_only=true
        r2 = s.get(f"{API}/notifications?unread_only=true",
                   headers=client_auth["headers"], timeout=15)
        assert r2.status_code == 200
        for row in r2.json()["notifications"]:
            assert row.get("read_at") in (None, ""), row

    def test_mark_single_read_and_read_all(self, s, client_auth):
        # Get any unread; if none, skip
        r = s.get(f"{API}/notifications?unread_only=true",
                  headers=client_auth["headers"], timeout=15)
        rows = r.json().get("notifications", [])
        if not rows:
            pytest.skip("no unread notifications for client")
        nid = rows[0]["id"]
        r1 = s.post(f"{API}/notifications/{nid}/read",
                    headers=client_auth["headers"], timeout=15)
        assert r1.status_code == 200
        # Idempotent
        r2 = s.post(f"{API}/notifications/{nid}/read",
                    headers=client_auth["headers"], timeout=15)
        assert r2.status_code == 200

        # read-all
        r3 = s.post(f"{API}/notifications/read-all",
                    headers=client_auth["headers"], timeout=15)
        assert r3.status_code == 200
        marked = r3.json().get("marked")
        assert isinstance(marked, int)

        # Verify unread count is 0
        u = s.get(f"{API}/notifications/unread-count",
                  headers=client_auth["headers"], timeout=15).json()
        assert u["unread"] == 0


# ---------- 7) Regression on previously-passing endpoints ----------

class TestRegression:
    def test_habits_today(self, s, client_auth):
        r = s.get(f"{API}/habits/today", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "habits" in body and "date_local" in body

    def test_habit_log(self, s, client_auth):
        today = s.get(f"{API}/habits/today", headers=client_auth["headers"], timeout=15).json()
        habits = today.get("habits", [])
        if not habits:
            pytest.skip("no habits available for regression log test")
        hid = habits[0]["id"]
        r = s.post(f"{API}/habits/{hid}/log",
                   headers=client_auth["headers"],
                   json={"status": "done"}, timeout=15)
        assert r.status_code == 200, r.text

    def test_coach_message_drafts(self, s, coach_auth):
        r = s.get(f"{API}/coach/messages/drafts", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json().get("drafts"), list)

    def test_coach_client_controls(self, s, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = s.get(f"{API}/coach/clients/{cid}/controls",
                  headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200

    def test_coach_change_log(self, s, coach_auth):
        r = s.get(f"{API}/coach/change-log", headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200

    def test_coach_client_habits(self, s, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = s.get(f"{API}/coach/clients/{cid}/habits",
                  headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "active" in body and "paused" in body

    def test_habit_review_approve_404_for_bogus_id(self, s, coach_auth):
        # We don't want to mutate real reviews here; verify endpoint at least returns 4xx (not 5xx)
        r = s.post(f"{API}/coach/habits/reviews/does-not-exist/approve",
                   headers=coach_auth["headers"], json={}, timeout=15)
        assert 400 <= r.status_code < 500, r.text
