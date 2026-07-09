"""
Coach Message Drafts, Coach Controls, and Change Log — backend tests.
Covers:
- Client → Coach message triggers background Atlas draft + message_draft_ready coach_task
- /coach/messages/drafts GET (list + detail with thread)
- /coach/messages/generate manual generation
- /coach/messages/{id}/regenerate (tone update, history)
- /coach/messages/{id} PATCH (coach_edited_text)
- /coach/messages/{id}/approve (persists message + status transitions + change_log)
- /coach/messages/{id}/dismiss
- Double-approve returns 400
- Coach controls GET/PUT + change_log diff
- Change log filters
- Role guards
- /messages between clients does NOT generate draft
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

COACH = {"email": "coach@crewfit.com", "password": "Coach123!"}
CLIENT = {"email": "client@crewfit.com", "password": "Client123!"}


# ---------- fixtures ---------------------------------------------------------
@pytest.fixture(scope="module")
def coach_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json=COACH, timeout=15)
    assert r.status_code == 200, f"coach login failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    s.user = r.json()["user"]
    return s


@pytest.fixture(scope="module")
def client_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json=CLIENT, timeout=15)
    assert r.status_code == 200, f"client login failed: {r.status_code} {r.text}"
    tok = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})
    s.user = r.json()["user"]
    return s


@pytest.fixture(scope="module")
def anon_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- helpers ---------------------------------------------------------
def _send_client_message(client_session, coach_session, text):
    coach_id = coach_session.user["id"]
    r = client_session.post(f"{API}/messages", json={"to_user_id": coach_id, "text": text}, timeout=15)
    assert r.status_code == 200, f"send message failed: {r.status_code} {r.text}"
    return r.json()


def _wait_for_draft(coach_session, source_message_id, timeout=15):
    """Poll drafts list until one appears referencing source_message_id."""
    start = time.time()
    last = None
    while time.time() - start < timeout:
        r = coach_session.get(f"{API}/coach/messages/drafts?status=waiting_approval", timeout=10)
        assert r.status_code == 200
        last = r.json()
        for d in last.get("drafts", []):
            if d.get("source_message_id") == source_message_id:
                return d
        time.sleep(1)
    pytest.fail(f"draft for source_message {source_message_id} not created within {timeout}s. last={last}")


# =====================================================================
# 1. Client → Coach message triggers background draft + coach_task
# =====================================================================
class TestBackgroundDraftFromClientMessage:
    _msg_id = None
    _draft = None

    def test_client_send_message_returns_normally(self, client_session, coach_session):
        msg = _send_client_message(client_session, coach_session, "TEST_DRAFT: Hi coach, my knee feels a bit sore after Tuesday's run — should I still lift heavy tomorrow?")
        assert msg.get("id")
        assert msg.get("from_user_id") == client_session.user["id"]
        assert msg.get("to_user_id") == coach_session.user["id"]
        assert msg.get("text").startswith("TEST_DRAFT:")
        TestBackgroundDraftFromClientMessage._msg_id = msg["id"]

    def test_background_draft_created(self, coach_session):
        assert TestBackgroundDraftFromClientMessage._msg_id, "message not created — cannot verify draft"
        draft = _wait_for_draft(coach_session, TestBackgroundDraftFromClientMessage._msg_id, timeout=20)
        assert draft["status"] == "waiting_approval"
        assert draft["client_id"] and draft["coach_id"]
        assert draft["thread_id"].startswith(draft["client_id"] + "::")
        assert draft.get("atlas_draft"), "atlas_draft empty (fallback should still set text)"
        assert draft["risk_level"] in {"low", "medium", "high"}
        # tone_used should be set
        assert draft.get("tone_used")
        TestBackgroundDraftFromClientMessage._draft = draft

    def test_coach_task_message_draft_ready_exists(self, coach_session):
        draft = TestBackgroundDraftFromClientMessage._draft
        assert draft, "no draft to look up"
        r = coach_session.get(f"{API}/coach/tasks", timeout=10)
        assert r.status_code == 200, r.text
        payload = r.json()
        tasks = payload if isinstance(payload, list) else payload.get("tasks") or payload.get("items") or []
        matched = [t for t in tasks if t.get("message_draft_id") == draft["id"]]
        assert matched, f"no coach_task found for draft {draft['id']}. tasks={tasks[:3]}"
        t = matched[0]
        assert t.get("task_type") == "message_draft_ready"
        assert t.get("category") == "messages"
        assert t.get("risk_level") in {"low", "medium", "high"}
        assert t.get("priority") in {"urgent", "high", "normal"}

    def test_draft_detail_with_thread(self, coach_session):
        draft = TestBackgroundDraftFromClientMessage._draft
        r = coach_session.get(f"{API}/coach/messages/drafts/{draft['id']}", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["draft"]["id"] == draft["id"]
        assert isinstance(body["thread"], list)
        assert len(body["thread"]) >= 1
        # Thread ordered ascending: source msg text should be present
        texts = [m.get("text") for m in body["thread"]]
        assert any("TEST_DRAFT:" in (t or "") for t in texts)


# =====================================================================
# 2. Manual /coach/messages/generate
# =====================================================================
class TestManualGenerate:
    _draft = None

    def test_manual_generate_creates_draft(self, coach_session, client_session):
        r = coach_session.post(
            f"{API}/coach/messages/generate",
            json={"client_id": client_session.user["id"], "tone_hint": "warmer"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload.get("draft") and payload["draft"].get("id")
        d = payload["draft"]
        assert d["status"] == "waiting_approval"
        assert d.get("atlas_draft")
        assert d.get("risk_level") in {"low", "medium", "high"}
        TestManualGenerate._draft = d


# =====================================================================
# 3. Regenerate with tone (updates draft + history)
# =====================================================================
class TestRegenerate:
    def test_regenerate_shorter(self, coach_session):
        d = TestManualGenerate._draft
        assert d, "no draft from previous test"
        prev_text = d.get("atlas_draft")
        r = coach_session.post(
            f"{API}/coach/messages/{d['id']}/regenerate",
            json={"tone": "shorter"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        d2 = r.json()["draft"]
        assert d2["id"] == d["id"]
        assert d2["status"] == "waiting_approval"
        # tone_used could be "shorter" or model-normalized — must be set
        assert d2.get("tone_used")
        # regeneration_history should include the previous atlas_draft
        history = d2.get("regeneration_history") or []
        assert len(history) >= 1
        assert history[-1].get("atlas_draft") == prev_text
        assert len(history) <= 5
        # update cached draft
        TestManualGenerate._draft = d2


# =====================================================================
# 4. PATCH coach_edited_text
# =====================================================================
class TestEdit:
    def test_patch_edit_text(self, coach_session):
        d = TestManualGenerate._draft
        edited = "TEST_EDIT: Coach's edited reply."
        r = coach_session.patch(
            f"{API}/coach/messages/{d['id']}",
            json={"coach_edited_text": edited},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        d2 = r.json()["draft"]
        assert d2["coach_edited_text"] == edited
        assert d2["status"] == "waiting_approval"
        TestManualGenerate._draft = d2


# =====================================================================
# 5. Approve — creates real message, updates draft, closes task, logs change
# =====================================================================
class TestApprove:
    def test_approve_sends_message(self, coach_session, client_session):
        d = TestManualGenerate._draft
        assert d and d["status"] == "waiting_approval"
        r = coach_session.post(f"{API}/coach/messages/{d['id']}/approve", json={}, timeout=15)
        # approve accepts either no body or {coach_edited_text}. Empty body with content-type json
        # may fail model validation because coach_edited_text is required. Try again with explicit text.
        if r.status_code == 422:
            r = coach_session.post(
                f"{API}/coach/messages/{d['id']}/approve",
                json={"coach_edited_text": d.get("coach_edited_text") or d.get("atlas_draft") or "Approved"},
                timeout=15,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        msg = body.get("message")
        assert msg and msg.get("id")
        assert msg["from_user_id"] == coach_session.user["id"]
        assert msg["to_user_id"] == client_session.user["id"]
        assert msg.get("source_draft_id") == d["id"]

        # Verify draft status transitioned
        r2 = coach_session.get(f"{API}/coach/messages/drafts/{d['id']}", timeout=10)
        assert r2.status_code == 200
        d2 = r2.json()["draft"]
        assert d2["status"] == "sent"
        assert d2.get("sent_at")
        assert d2.get("sent_message_id") == msg["id"]

        # Verify coach_task transitioned to done
        r3 = coach_session.get(f"{API}/coach/tasks", timeout=10)
        tasks = r3.json() if isinstance(r3.json(), list) else r3.json().get("tasks") or r3.json().get("items") or []
        matched = [t for t in tasks if t.get("message_draft_id") == d["id"]]
        # tasks may filter out done — that's fine. If present, must not be todo/in_progress.
        for t in matched:
            assert t.get("status") not in ("todo", "in_progress"), f"task not closed: {t}"

        # Verify change log entry
        r4 = coach_session.get(f"{API}/coach/change-log?category=message", timeout=10)
        assert r4.status_code == 200
        entries = r4.json().get("entries", [])
        assert any(e.get("meta", {}).get("draft_id") == d["id"] for e in entries), \
            "no change_log entry for approved draft"

    def test_double_approve_400(self, coach_session):
        d = TestManualGenerate._draft
        r = coach_session.post(
            f"{API}/coach/messages/{d['id']}/approve",
            json={"coach_edited_text": "again"},
            timeout=10,
        )
        assert r.status_code == 400, f"expected 400 on second approve, got {r.status_code} {r.text}"


# =====================================================================
# 6. Dismiss flow (separate draft)
# =====================================================================
class TestDismiss:
    def test_dismiss_flow(self, coach_session, client_session):
        # Generate a fresh draft to dismiss
        r = coach_session.post(
            f"{API}/coach/messages/generate",
            json={"client_id": client_session.user["id"]},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        d = r.json()["draft"]
        assert d["status"] == "waiting_approval"

        r2 = coach_session.post(f"{API}/coach/messages/{d['id']}/dismiss", timeout=10)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("ok") is True

        # Verify status
        r3 = coach_session.get(f"{API}/coach/messages/drafts/{d['id']}", timeout=10)
        assert r3.status_code == 200
        assert r3.json()["draft"]["status"] == "dismissed"

        # Verify change log entry with category=message
        r4 = coach_session.get(f"{API}/coach/change-log?category=message", timeout=10)
        entries = r4.json().get("entries", [])
        assert any(e.get("meta", {}).get("draft_id") == d["id"] for e in entries), \
            "no change_log for dismissed draft"


# =====================================================================
# 7. Coach Controls (GET/PUT merge + change log)
# =====================================================================
class TestCoachControls:
    def test_get_controls_defaults(self, coach_session, client_session):
        r = coach_session.get(f"{API}/coach/clients/{client_session.user['id']}/controls", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "controls" in body and "defaults" in body
        d = body["defaults"]
        assert d == {
            "programme_flexibility": "flexible",
            "progression_speed": "standard",
            "injury_caution": "medium",
            "video_frequency": "weekly",
            "auto_approval_risk_threshold": "none",
        }
        c = body["controls"]
        for k in d:
            assert k in c

    def test_put_partial_merge(self, coach_session, client_session):
        cid = client_session.user["id"]
        # Set two fields
        r0 = coach_session.put(f"{API}/coach/clients/{cid}/controls",
                               json={"progression_speed": "cautious", "injury_caution": "high"}, timeout=10)
        assert r0.status_code == 200, r0.text
        # Now partial: only progression_speed
        r1 = coach_session.put(f"{API}/coach/clients/{cid}/controls",
                               json={"progression_speed": "aggressive"}, timeout=10)
        assert r1.status_code == 200, r1.text
        merged = r1.json()["controls"]
        assert merged["progression_speed"] == "aggressive"
        # injury_caution must persist from prior put (not wiped)
        assert merged["injury_caution"] == "high", f"partial PUT wiped other fields! merged={merged}"
        # Defaults untouched
        assert merged["auto_approval_risk_threshold"] == "none"

    def test_controls_change_log_entry(self, coach_session, client_session):
        r = coach_session.get(f"{API}/coach/change-log?category=controls&client_id={client_session.user['id']}",
                              timeout=10)
        assert r.status_code == 200
        entries = r.json().get("entries", [])
        # Expect at least one entry mentioning progression_speed diff
        found = False
        for e in entries:
            diff = (e.get("meta") or {}).get("diff") or {}
            if "progression_speed" in diff:
                found = True
                break
        assert found, f"no change_log entry with progression_speed diff. entries={entries[:3]}"


# =====================================================================
# 8. Change log endpoints (sorting + filters)
# =====================================================================
class TestChangeLog:
    def test_change_log_sorted_newest_first(self, coach_session):
        r = coach_session.get(f"{API}/coach/change-log", timeout=10)
        assert r.status_code == 200
        entries = r.json().get("entries", [])
        assert len(entries) >= 2
        # created_at must be non-increasing
        prev = None
        for e in entries:
            if prev is not None:
                assert e["created_at"] <= prev, "change log not sorted newest-first"
            prev = e["created_at"]

    def test_change_log_filter_category_message(self, coach_session):
        r = coach_session.get(f"{API}/coach/change-log?category=message", timeout=10)
        assert r.status_code == 200
        for e in r.json().get("entries", []):
            assert e.get("category") == "message"

    def test_client_scoped_change_log(self, coach_session, client_session):
        r = coach_session.get(f"{API}/coach/clients/{client_session.user['id']}/change-log", timeout=10)
        assert r.status_code == 200
        for e in r.json().get("entries", []):
            assert e.get("client_id") == client_session.user["id"]


# =====================================================================
# 9. Role guards
# =====================================================================
class TestRoleGuards:
    def _forbidden(self, resp):
        # Accept 401 or 403 as valid guards. 200 is fail.
        assert resp.status_code in (401, 403), f"expected 401/403 got {resp.status_code}: {resp.text[:200]}"

    def test_client_cannot_list_drafts(self, client_session):
        self._forbidden(client_session.get(f"{API}/coach/messages/drafts", timeout=10))

    def test_anon_cannot_list_drafts(self, anon_session):
        self._forbidden(anon_session.get(f"{API}/coach/messages/drafts", timeout=10))

    def test_client_cannot_read_controls(self, client_session):
        self._forbidden(client_session.get(f"{API}/coach/clients/{client_session.user['id']}/controls", timeout=10))

    def test_client_cannot_write_controls(self, client_session):
        self._forbidden(client_session.put(f"{API}/coach/clients/{client_session.user['id']}/controls",
                                           json={"progression_speed": "standard"}, timeout=10))

    def test_client_cannot_read_change_log(self, client_session):
        self._forbidden(client_session.get(f"{API}/coach/change-log", timeout=10))

    def test_client_cannot_generate_draft(self, client_session):
        self._forbidden(client_session.post(f"{API}/coach/messages/generate",
                                            json={"client_id": client_session.user["id"]}, timeout=10))


# =====================================================================
# 10. /messages between two clients — no draft generated
# =====================================================================
class TestNoDraftForClientToClient:
    def test_client_to_client_no_draft(self, client_session, coach_session):
        # Find another client. If none exists, create one via signup as a fallback.
        r = coach_session.get(f"{API}/coach/clients", timeout=10)
        other_id = None
        if r.status_code == 200:
            clients = r.json() if isinstance(r.json(), list) else (r.json().get("clients") or r.json().get("items") or [])
            for c in clients:
                if c.get("id") and c["id"] != client_session.user["id"]:
                    other_id = c["id"]
                    break
        if not other_id:
            # Create a second client via signup
            email = f"TEST_secondclient_{int(time.time())}@example.com"
            reg = requests.post(f"{API}/auth/signup",
                                json={"email": email, "password": "Pw123456!", "name": "TEST Second", "role": "client"},
                                timeout=10)
            if reg.status_code == 200:
                other_id = reg.json().get("user", {}).get("id")
        if not other_id:
            pytest.skip("no second client available")

        # Count drafts before
        r0 = coach_session.get(f"{API}/coach/messages/drafts?status=waiting_approval&limit=200", timeout=10)
        before = r0.json().get("count", 0)

        # Send client→client
        r1 = client_session.post(f"{API}/messages",
                                 json={"to_user_id": other_id, "text": "TEST_C2C: hi other client"}, timeout=10)
        assert r1.status_code == 200, r1.text

        # Wait a bit then verify no new waiting_approval draft was created
        time.sleep(6)
        r2 = coach_session.get(f"{API}/coach/messages/drafts?status=waiting_approval&limit=200", timeout=10)
        after = r2.json().get("count", 0)
        assert after <= before, f"unexpected new draft created for client→client message. before={before}, after={after}"
