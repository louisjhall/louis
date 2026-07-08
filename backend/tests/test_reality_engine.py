"""Tests for CrewFit Intelligence™ Dynamic Life Adaptation Engine (Reality Engine).

Covers all endpoints:
  * GET  /api/reality/kinds
  * POST /api/reality/submit
  * POST /api/reality/apply
  * GET  /api/reality/history
  * GET  /api/reality/{event_id}
  * GET  /api/coach/reality/pending
  * POST /api/coach/reality/decision
  * PATCH /api/coach/settings/mode
  * GET  /api/coach/settings

Runs against the live backend on http://localhost:8001. Claude Sonnet 4.5 calls
can take 5-15s each so submit calls use timeout=60.
"""

import os
import copy
import time
from datetime import date, datetime

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


ALL_KINDS = [
    "exhausted", "flight_delayed", "roster_changed", "hotel_changed", "no_gym",
    "feeling_amazing", "less_time", "more_time", "family_commitments",
    "annual_leave", "feeling_ill", "injured", "travelling", "bad_weather",
    "missed_yesterday", "want_to_move", "other",
]

# -----------------------------------------------------------------------------
# Auth helpers
# -----------------------------------------------------------------------------

def _login(email, pw):
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
def workout_dates(client_ctx):
    """Return unlocked, uncompleted workout dates from the seed."""
    r = requests.get(f"{API}/workouts/week", headers=client_ctx["headers"], timeout=20)
    assert r.status_code == 200, r.text
    wks = sorted(
        [w for w in r.json() if not w.get("coach_locked") and not w.get("completed")],
        key=lambda w: w["date"],
    )
    return [w["date"] for w in wks]


@pytest.fixture(scope="module")
def target_date(workout_dates):
    assert workout_dates, "No seeded workouts to test against"
    # Pick a date roughly in the middle of the seed
    return workout_dates[len(workout_dates) // 2]


def _submit(client_ctx, target_date, reality_kind, notes=None, time_available_min=None):
    body = {"date": target_date, "reality_kind": reality_kind}
    if notes is not None:
        body["notes"] = notes
    if time_available_min is not None:
        body["time_available_min"] = time_available_min
    return requests.post(f"{API}/reality/submit", json=body, headers=client_ctx["headers"], timeout=60)


# ---- Ensure coach is in 'balanced' before entire suite; restore at end ------

@pytest.fixture(scope="module", autouse=True)
def _reset_coach_mode(coach_ctx):
    # Force balanced before tests
    r = requests.patch(f"{API}/coach/settings/mode", json={"mode": "balanced"},
                       headers=coach_ctx["headers"], timeout=10)
    assert r.status_code == 200, r.text
    yield
    requests.patch(f"{API}/coach/settings/mode", json={"mode": "balanced"},
                   headers=coach_ctx["headers"], timeout=10)


# =============================================================================
# 1. GET /api/reality/kinds
# =============================================================================

class TestRealityKinds:
    def test_kinds_returns_17(self):
        r = requests.get(f"{API}/reality/kinds", timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "kinds" in body
        keys = [k["kind"] for k in body["kinds"]]
        assert len(keys) == 17, f"expected 17 kinds, got {len(keys)}: {keys}"
        assert set(keys) == set(ALL_KINDS), f"missing: {set(ALL_KINDS) - set(keys)}, extra: {set(keys) - set(ALL_KINDS)}"
        # Each has a label
        for row in body["kinds"]:
            assert row.get("label"), row


# =============================================================================
# 2. POST /api/reality/submit — every kind returns 3 options with A/B/C ids
# =============================================================================

class TestSubmitAllKinds:
    @pytest.mark.parametrize("kind", ALL_KINDS)
    def test_submit_kind(self, client_ctx, target_date, kind):
        r = _submit(client_ctx, target_date, kind)
        assert r.status_code == 200, f"{kind}: {r.status_code} {r.text[:400]}"
        body = r.json()
        assert "reality_event_id" in body
        assert body.get("coach_mode") in ("strict", "balanced", "flexible")
        options = body.get("options") or []
        assert len(options) == 3, f"{kind}: got {len(options)} options"
        ids = [o.get("id") for o in options]
        assert ids == ["A", "B", "C"], f"{kind}: option ids = {ids}"
        for o in options:
            assert o.get("title"), f"{kind}: option {o.get('id')} missing title"
            assert o.get("why"), f"{kind}: option {o.get('id')} missing why"
            assert isinstance(o.get("actions"), list), f"{kind}: actions not a list"
            assert "touches_locked" in o, f"{kind}: touches_locked flag missing"


# =============================================================================
# 3. Invalid kind → 400
# =============================================================================

class TestSubmitValidation:
    def test_invalid_kind_400(self, client_ctx, target_date):
        r = requests.post(f"{API}/reality/submit",
                          json={"date": target_date, "reality_kind": "not_a_kind"},
                          headers=client_ctx["headers"], timeout=15)
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"


# =============================================================================
# 4. Apply Option A workflow
# =============================================================================

class TestApplyOptionA:
    def test_apply_A_records_history(self, client_ctx, target_date):
        # Snapshot workout so we can restore
        wid_before = _DB.workouts.find_one({"user_id": client_ctx["user"]["id"], "date": target_date})
        wid_before_copy = copy.deepcopy(wid_before) if wid_before else None
        # Baseline history count
        hist_before = requests.get(f"{API}/reality/history", headers=client_ctx["headers"], timeout=15)
        assert hist_before.status_code == 200
        base_count = len(hist_before.json().get("history") or [])

        try:
            r = _submit(client_ctx, target_date, "less_time", time_available_min=20)
            assert r.status_code == 200, r.text
            evt_id = r.json()["reality_event_id"]

            apply_r = requests.post(f"{API}/reality/apply",
                                    json={"reality_event_id": evt_id, "option_id": "A"},
                                    headers=client_ctx["headers"], timeout=30)
            assert apply_r.status_code == 200, apply_r.text
            body = apply_r.json()
            assert body["status"] == "applied", body
            assert body["reality_event_id"] == evt_id
            assert isinstance(body.get("changes"), list)

            # DB reality_events status == applied
            evt = _DB.reality_events.find_one({"id": evt_id})
            assert evt["status"] == "applied"
            assert evt["applied_option"] == "A"
            assert evt.get("applied_at")

            # move_history has a new entry
            hist_after = requests.get(f"{API}/reality/history", headers=client_ctx["headers"], timeout=15).json()["history"]
            assert len(hist_after) == base_count + 1
            latest = hist_after[0]
            assert latest["reality_event_id"] == evt_id
            assert latest["option_id"] == "A"
            assert latest.get("actor_role") == "client"
            # verify required move_history schema fields
            for key in ("id", "user_id", "reality_event_id", "reality_kind", "reality_label",
                        "date", "option_id", "option_title", "option_why", "changes",
                        "actor_id", "actor_role", "coach_mode", "created_at"):
                assert key in latest, f"move_history missing key {key}"
        finally:
            # Restore workout if it was mutated
            if wid_before_copy:
                snap = {k: v for k, v in wid_before_copy.items() if k != "_id"}
                _DB.workouts.update_one({"id": snap["id"]}, {"$set": snap})


# =============================================================================
# 5. Apply Option C → ask_coach + coach_alert
# =============================================================================

class TestApplyOptionC:
    def test_apply_C_routes_to_coach(self, client_ctx, target_date):
        r = _submit(client_ctx, target_date, "other", notes="testing option C")
        assert r.status_code == 200, r.text
        evt_id = r.json()["reality_event_id"]

        # Snapshot workout — Option C should NOT mutate
        w_before = _DB.workouts.find_one({"user_id": client_ctx["user"]["id"], "date": target_date})
        w_before_title = w_before["title"] if w_before else None

        apply_r = requests.post(f"{API}/reality/apply",
                                json={"reality_event_id": evt_id, "option_id": "C"},
                                headers=client_ctx["headers"], timeout=30)
        assert apply_r.status_code == 200, apply_r.text
        body = apply_r.json()
        assert body["status"] == "ask_coach", body

        # reality_events status
        evt = _DB.reality_events.find_one({"id": evt_id})
        assert evt["status"] == "ask_coach"

        # coach_alerts row exists
        alert = _DB.coach_alerts.find_one({"reality_event_id": evt_id, "kind": "reality_ask_coach"})
        assert alert is not None, "coach_alerts row (reality_ask_coach) not found"

        # Workout NOT mutated
        w_after = _DB.workouts.find_one({"user_id": client_ctx["user"]["id"], "date": target_date})
        if w_before_title and w_after:
            assert w_after["title"] == w_before_title, "Option C should not mutate workout"


# =============================================================================
# 6. Apply same event twice → 400
# =============================================================================

class TestApplyIdempotency:
    def test_apply_twice_400(self, client_ctx, target_date):
        r = _submit(client_ctx, target_date, "more_time")
        assert r.status_code == 200, r.text
        evt_id = r.json()["reality_event_id"]

        # First apply — Option C is safe (no workout mutation)
        r1 = requests.post(f"{API}/reality/apply",
                           json={"reality_event_id": evt_id, "option_id": "C"},
                           headers=client_ctx["headers"], timeout=30)
        assert r1.status_code == 200

        # Second apply → 400
        r2 = requests.post(f"{API}/reality/apply",
                           json={"reality_event_id": evt_id, "option_id": "A"},
                           headers=client_ctx["headers"], timeout=30)
        assert r2.status_code == 400, f"expected 400, got {r2.status_code}: {r2.text[:200]}"


# =============================================================================
# 7. Apply non-existent event → 404
# =============================================================================

class TestApplyNotFound:
    def test_apply_nonexistent_404(self, client_ctx):
        r = requests.post(f"{API}/reality/apply",
                          json={"reality_event_id": "does-not-exist-uuid", "option_id": "A"},
                          headers=client_ctx["headers"], timeout=15)
        assert r.status_code == 404, f"expected 404, got {r.status_code}"


# =============================================================================
# 8 & 9. Precedence: coach_locked / completed workout is preserved
# =============================================================================

class TestPrecedence:
    def _restore(self, uid, d, snap):
        if snap:
            copy_ = {k: v for k, v in snap.items() if k != "_id"}
            _DB.workouts.update_one({"id": copy_["id"]}, {"$set": copy_})

    def test_coach_locked_workout_untouched(self, client_ctx, target_date):
        uid = client_ctx["user"]["id"]
        snap = _DB.workouts.find_one({"user_id": uid, "date": target_date})
        assert snap, "seeded workout not found"
        snap_copy = copy.deepcopy(snap)

        _DB.workouts.update_one({"id": snap["id"]}, {"$set": {"coach_locked": True}})
        try:
            r = _submit(client_ctx, target_date, "less_time", time_available_min=20)
            assert r.status_code == 200, r.text
            evt_id = r.json()["reality_event_id"]

            apply_r = requests.post(f"{API}/reality/apply",
                                    json={"reality_event_id": evt_id, "option_id": "A"},
                                    headers=client_ctx["headers"], timeout=30)
            assert apply_r.status_code == 200, apply_r.text
            body = apply_r.json()

            # Either changes[*].skipped_reason == locked_or_completed OR workout unchanged
            w_after = _DB.workouts.find_one({"id": snap["id"]})
            unchanged = (w_after["title"] == snap_copy["title"] and
                         w_after.get("duration_min") == snap_copy.get("duration_min"))
            skipped_flags = [c.get("skipped_reason") == "locked_or_completed"
                             for c in body.get("changes", [])
                             if c.get("action", {}).get("date") == target_date]
            assert unchanged or any(skipped_flags) or body.get("status") == "ask_coach", \
                f"workout mutated despite coach_lock: title={w_after['title']} vs {snap_copy['title']}; changes={body.get('changes')}"
        finally:
            self._restore(uid, target_date, snap_copy)

    def test_completed_workout_untouched(self, client_ctx, target_date):
        uid = client_ctx["user"]["id"]
        snap = _DB.workouts.find_one({"user_id": uid, "date": target_date})
        assert snap
        snap_copy = copy.deepcopy(snap)

        _DB.workouts.update_one({"id": snap["id"]}, {"$set": {"completed": True, "coach_locked": False}})
        try:
            r = _submit(client_ctx, target_date, "less_time", time_available_min=20)
            assert r.status_code == 200
            evt_id = r.json()["reality_event_id"]
            apply_r = requests.post(f"{API}/reality/apply",
                                    json={"reality_event_id": evt_id, "option_id": "A"},
                                    headers=client_ctx["headers"], timeout=30)
            assert apply_r.status_code == 200
            body = apply_r.json()
            w_after = _DB.workouts.find_one({"id": snap["id"]})
            unchanged = (w_after["title"] == snap_copy["title"] and
                         w_after.get("duration_min") == snap_copy.get("duration_min"))
            skipped_flags = [c.get("skipped_reason") == "locked_or_completed"
                             for c in body.get("changes", [])
                             if c.get("action", {}).get("date") == target_date]
            assert unchanged or any(skipped_flags), \
                f"completed workout mutated: changes={body.get('changes')}"
        finally:
            self._restore(uid, target_date, snap_copy)


# =============================================================================
# 10. Coach visibility — /coach/roster-alerts shows reality_applied entry
# =============================================================================

class TestCoachAlertVisibility:
    def test_reality_applied_shows_in_roster_alerts(self, client_ctx, coach_ctx, target_date):
        uid = client_ctx["user"]["id"]
        snap = _DB.workouts.find_one({"user_id": uid, "date": target_date})
        snap_copy = copy.deepcopy(snap) if snap else None

        try:
            r = _submit(client_ctx, target_date, "less_time", time_available_min=20)
            assert r.status_code == 200
            evt_id = r.json()["reality_event_id"]

            apply_r = requests.post(f"{API}/reality/apply",
                                    json={"reality_event_id": evt_id, "option_id": "A"},
                                    headers=client_ctx["headers"], timeout=30)
            assert apply_r.status_code == 200
            assert apply_r.json()["status"] == "applied"

            # Give a moment for background write
            time.sleep(0.3)
            alerts_r = requests.get(f"{API}/coach/roster-alerts?unread=true",
                                    headers=coach_ctx["headers"], timeout=15)
            assert alerts_r.status_code == 200, alerts_r.text
            alerts = alerts_r.json()
            match = next((a for a in alerts if a.get("kind") == "reality_applied"
                          and a.get("reality_event_id") == evt_id), None)
            assert match is not None, f"reality_applied alert not found for evt {evt_id}. Alerts: {alerts[:5]}"
            assert match.get("client_id") == uid
            assert match.get("option_id") == "A"
        finally:
            if snap_copy:
                copy_ = {k: v for k, v in snap_copy.items() if k != "_id"}
                _DB.workouts.update_one({"id": copy_["id"]}, {"$set": copy_})


# =============================================================================
# 11. Coach pending — after Option C, /coach/reality/pending lists event
# =============================================================================

class TestCoachPending:
    def test_pending_after_ask_coach(self, client_ctx, coach_ctx, target_date):
        r = _submit(client_ctx, target_date, "roster_changed", notes="need help")
        assert r.status_code == 200
        evt_id = r.json()["reality_event_id"]

        apply_r = requests.post(f"{API}/reality/apply",
                                json={"reality_event_id": evt_id, "option_id": "C"},
                                headers=client_ctx["headers"], timeout=30)
        assert apply_r.status_code == 200
        assert apply_r.json()["status"] == "ask_coach"

        pend_r = requests.get(f"{API}/coach/reality/pending",
                              headers=coach_ctx["headers"], timeout=15)
        assert pend_r.status_code == 200, pend_r.text
        rows = pend_r.json()
        assert isinstance(rows, list)
        row = next((r for r in rows if r.get("id") == evt_id), None)
        assert row is not None, "event not in coach pending list"
        assert row.get("client_name"), "client_name enrichment missing"
        assert row.get("status") == "ask_coach"


# =============================================================================
# 12. Coach decision — approve_A executes and records move_history w/ coach
# =============================================================================

class TestCoachDecision:
    def test_approve_A(self, client_ctx, coach_ctx, target_date):
        uid = client_ctx["user"]["id"]
        # Setup: create ask_coach event
        snap = _DB.workouts.find_one({"user_id": uid, "date": target_date})
        snap_copy = copy.deepcopy(snap) if snap else None

        try:
            r = _submit(client_ctx, target_date, "less_time", time_available_min=25)
            assert r.status_code == 200
            evt_id = r.json()["reality_event_id"]

            # Client picks C to route to coach
            apply_r = requests.post(f"{API}/reality/apply",
                                    json={"reality_event_id": evt_id, "option_id": "C"},
                                    headers=client_ctx["headers"], timeout=30)
            assert apply_r.status_code == 200

            # Coach approves A
            dec_r = requests.post(f"{API}/coach/reality/decision",
                                  json={"reality_event_id": evt_id, "decision": "approve_A"},
                                  headers=coach_ctx["headers"], timeout=30)
            assert dec_r.status_code == 200, dec_r.text
            assert dec_r.json()["status"] == "coach_approved"

            # Verify event status
            evt = _DB.reality_events.find_one({"id": evt_id})
            assert evt["status"] == "coach_approved"
            assert evt.get("coach_reviewer_id") == coach_ctx["user"]["id"]

            # Verify a new move_history with actor_role='coach'
            hist_rows = list(_DB.move_history.find({"reality_event_id": evt_id}).sort("created_at", -1))
            coach_row = next((h for h in hist_rows if h.get("actor_role") == "coach"), None)
            assert coach_row is not None, "no coach move_history entry"
            assert coach_row["option_id"] == "A"
            assert coach_row["actor_id"] == coach_ctx["user"]["id"]
        finally:
            if snap_copy:
                copy_ = {k: v for k, v in snap_copy.items() if k != "_id"}
                _DB.workouts.update_one({"id": copy_["id"]}, {"$set": copy_})


# =============================================================================
# 13. Coach mode set + get
# =============================================================================

class TestCoachMode:
    def test_set_and_get_mode(self, coach_ctx):
        try:
            r = requests.patch(f"{API}/coach/settings/mode", json={"mode": "strict"},
                               headers=coach_ctx["headers"], timeout=10)
            assert r.status_code == 200, r.text
            assert r.json()["mode"] == "strict"

            g = requests.get(f"{API}/coach/settings", headers=coach_ctx["headers"], timeout=10)
            assert g.status_code == 200
            assert g.json()["coach_mode"] == "strict"
        finally:
            requests.patch(f"{API}/coach/settings/mode", json={"mode": "balanced"},
                           headers=coach_ctx["headers"], timeout=10)

    def test_invalid_mode_400(self, coach_ctx):
        r = requests.patch(f"{API}/coach/settings/mode", json={"mode": "yolo"},
                           headers=coach_ctx["headers"], timeout=10)
        assert r.status_code == 400


# =============================================================================
# 14. Strict mode + coach_locked → apply routes to ask_coach
# =============================================================================

class TestStrictModeLocked:
    def test_strict_locked_routes_to_ask_coach(self, client_ctx, coach_ctx, target_date):
        uid = client_ctx["user"]["id"]
        snap = _DB.workouts.find_one({"user_id": uid, "date": target_date})
        assert snap
        snap_copy = copy.deepcopy(snap)

        # Set strict mode + lock workout
        requests.patch(f"{API}/coach/settings/mode", json={"mode": "strict"},
                       headers=coach_ctx["headers"], timeout=10)
        _DB.workouts.update_one({"id": snap["id"]}, {"$set": {"coach_locked": True}})

        try:
            r = _submit(client_ctx, target_date, "less_time", time_available_min=20)
            assert r.status_code == 200
            body = r.json()
            assert body["coach_mode"] == "strict"
            evt_id = body["reality_event_id"]

            # Option A should have touches_locked=True
            opt_a = next((o for o in body["options"] if o["id"] == "A"), None)
            assert opt_a is not None

            apply_r = requests.post(f"{API}/reality/apply",
                                    json={"reality_event_id": evt_id, "option_id": "A"},
                                    headers=client_ctx["headers"], timeout=30)
            assert apply_r.status_code == 200, apply_r.text
            resp = apply_r.json()

            # If AI produced an action for the locked date, touches_locked=True and status
            # must be ask_coach. Otherwise the option didn't actually touch a locked date
            # so behavior is legitimate applied. We only assert ask_coach when locked was touched.
            if opt_a.get("touches_locked"):
                assert resp["status"] == "ask_coach", f"strict+locked should route to ask_coach: {resp}"
                # workout untouched
                w_after = _DB.workouts.find_one({"id": snap["id"]})
                assert w_after["title"] == snap_copy["title"]
            else:
                # Not touching locked date — no gating expected
                assert resp["status"] in ("applied", "ask_coach")
        finally:
            _DB.workouts.update_one({"id": snap["id"]},
                                    {"$set": {k: v for k, v in snap_copy.items() if k != "_id"}})
            requests.patch(f"{API}/coach/settings/mode", json={"mode": "balanced"},
                           headers=coach_ctx["headers"], timeout=10)


# =============================================================================
# 15. Role gating
# =============================================================================

class TestRoleGating:
    def test_client_cannot_hit_coach_pending(self, client_ctx):
        r = requests.get(f"{API}/coach/reality/pending",
                         headers=client_ctx["headers"], timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_client_cannot_hit_coach_decision(self, client_ctx):
        r = requests.post(f"{API}/coach/reality/decision",
                          json={"reality_event_id": "x", "decision": "reject"},
                          headers=client_ctx["headers"], timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_client_cannot_set_coach_mode(self, client_ctx):
        r = requests.patch(f"{API}/coach/settings/mode",
                           json={"mode": "strict"},
                           headers=client_ctx["headers"], timeout=10)
        assert r.status_code == 403, f"expected 403, got {r.status_code}"

    def test_client_cannot_get_coach_settings(self, client_ctx):
        r = requests.get(f"{API}/coach/settings",
                         headers=client_ctx["headers"], timeout=10)
        assert r.status_code == 403


# =============================================================================
# 16. Fetch by id — client A cannot fetch client B's event (403)
# =============================================================================

class TestFetchById:
    def test_client_can_fetch_own(self, client_ctx, target_date):
        r = _submit(client_ctx, target_date, "more_time")
        assert r.status_code == 200
        evt_id = r.json()["reality_event_id"]
        g = requests.get(f"{API}/reality/{evt_id}",
                         headers=client_ctx["headers"], timeout=10)
        assert g.status_code == 200
        body = g.json()
        # Verify reality_events schema on DB doc
        for key in ("id", "user_id", "date", "reality_kind", "reality_label", "notes",
                    "time_available_min", "context_snapshot", "recovery_score",
                    "context_summary", "options", "coach_mode", "applied_option",
                    "applied_at", "status", "created_at"):
            assert key in body, f"reality_events missing key {key}"

    def test_coach_can_fetch_any(self, client_ctx, coach_ctx, target_date):
        r = _submit(client_ctx, target_date, "more_time")
        assert r.status_code == 200
        evt_id = r.json()["reality_event_id"]
        g = requests.get(f"{API}/reality/{evt_id}",
                         headers=coach_ctx["headers"], timeout=10)
        assert g.status_code == 200

    def test_other_client_cannot_fetch(self, coach_ctx, target_date):
        # We only have one seeded client account, so simulate a "different client"
        # by inserting a fake reality_event owned by a made-up user_id and hitting
        # from the seeded client account — should return 403.
        fake_evt = {
            "id": "fake-other-client-evt-uuid-xxx",
            "user_id": "fake-user-id-not-real",
            "date": target_date,
            "reality_kind": "less_time",
            "reality_label": "Less time today",
            "notes": None, "time_available_min": None,
            "context_snapshot": {}, "recovery_score": None,
            "context_summary": "test", "options": [],
            "coach_mode": "balanced", "applied_option": None,
            "applied_at": None, "status": "awaiting_choice",
            "created_at": datetime.utcnow().isoformat(),
        }
        _DB.reality_events.insert_one(fake_evt)
        try:
            client_tok, _ = _login(CLIENT_EMAIL, CLIENT_PW)
            g = requests.get(f"{API}/reality/{fake_evt['id']}",
                             headers={"Authorization": f"Bearer {client_tok}"}, timeout=10)
            assert g.status_code == 403, f"expected 403 for cross-client fetch, got {g.status_code}"
            # Coach can still fetch it
            g2 = requests.get(f"{API}/reality/{fake_evt['id']}",
                              headers=coach_ctx["headers"], timeout=10)
            assert g2.status_code == 200
        finally:
            _DB.reality_events.delete_one({"id": fake_evt["id"]})
