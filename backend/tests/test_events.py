"""CrewFit V1.5 Event Training Mode tests.

Covers all new /api/events* endpoints + phase computation + coach client_detail
event field + PATCH /api/workouts/{id} key_session/event_phase.
"""
import uuid
from datetime import date, timedelta

import pytest


def _future_iso(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


PHASE_CASES = [
    (200, "base"),        # >14 weeks
    (70, "build"),        # 10 weeks -> build (8..14)
    (40, "peak"),         # ~5 weeks -> peak (>21d, weeks<=8)
    (15, "taper"),        # 15d
    (5, "race_week"),     # <=7d
    (-5, "recovery"),     # past by <=14
    (-30, "post"),        # past by >14
]


class TestEventCRUD:
    def _mk_body(self, days_from_today: int, name_suffix: str = ""):
        return {
            "event_type": "marathon",
            "event_name": f"TEST Event {name_suffix or uuid.uuid4().hex[:6]}",
            "event_date": _future_iso(days_from_today),
            "target_time": "3:45:00",
            "current_ability": "runs 15km",
            "weekly_availability_min": 300,
            "longest_recent": "18km",
            "injury_history": "left knee",
            "preferred_days": ["Tue", "Thu", "Sat", "Sun"],
            "access_gym": True,
            "access_pool": False,
            "access_bike": True,
            "access_treadmill": True,
            "include_strength": True,
            "include_mobility": True,
            "notes": "TEST",
        }

    def test_client_create_event(self, api, base_url, client_auth):
        body = self._mk_body(60, "create")
        r = api.post(f"{base_url}/api/events", headers=client_auth["headers"], json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("id") and d["event_name"] == body["event_name"]
        assert d["is_active"] is True
        assert d["user_id"] == client_auth["user"]["id"]
        assert "_id" not in d

    def test_create_deactivates_previous_and_history_kept(self, api, base_url, client_auth):
        # create #1
        r1 = api.post(f"{base_url}/api/events", headers=client_auth["headers"],
                      json=self._mk_body(50, "old"), timeout=30)
        assert r1.status_code == 200
        eid_old = r1.json()["id"]
        # create #2
        r2 = api.post(f"{base_url}/api/events", headers=client_auth["headers"],
                      json=self._mk_body(80, "new"), timeout=30)
        assert r2.status_code == 200
        eid_new = r2.json()["id"]

        # history contains both
        rh = api.get(f"{base_url}/api/events/history", headers=client_auth["headers"], timeout=15)
        assert rh.status_code == 200
        rows = rh.json()
        ids = {x["id"] for x in rows}
        assert eid_old in ids and eid_new in ids
        # only new is_active
        actives = [x for x in rows if x.get("is_active")]
        assert len(actives) == 1 and actives[0]["id"] == eid_new
        # phase_info attached on every history row
        for x in rows:
            assert "phase_info" in x
            assert set(x["phase_info"].keys()) >= {"weeks_to_race", "days_to_race", "phase"}

    def test_current_returns_active_with_phase_info(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/events/current", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d and d.get("is_active") is True
        pi = d.get("phase_info")
        assert pi and "weeks_to_race" in pi and "days_to_race" in pi and "phase" in pi

    def test_patch_own_event(self, api, base_url, client_auth):
        # Grab current event id
        cur = api.get(f"{base_url}/api/events/current", headers=client_auth["headers"], timeout=15).json()
        eid = cur["id"]
        upd = {
            "event_type": cur["event_type"],
            "event_name": "TEST Event RENAMED",
            "event_date": _future_iso(90),
            "target_time": "3:30:00",
            "preferred_days": ["Wed", "Sat"],
            "access_gym": True,
            "include_strength": False,
        }
        r = api.patch(f"{base_url}/api/events/{eid}", headers=client_auth["headers"], json=upd, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["event_name"] == "TEST Event RENAMED"
        assert d["target_time"] == "3:30:00"
        assert d["include_strength"] is False

    def test_client_cannot_patch_other_users_event(self, api, base_url, client_auth, coach_auth):
        # Coach creates an event on behalf of themselves (owner=coach) to test 403.
        r_c = api.post(f"{base_url}/api/events", headers=coach_auth["headers"],
                       json=self._mk_body(45, "coachown"), timeout=30)
        assert r_c.status_code == 200
        other_eid = r_c.json()["id"]
        # client tries to patch it
        r = api.patch(f"{base_url}/api/events/{other_eid}", headers=client_auth["headers"],
                      json=self._mk_body(30, "hack"), timeout=15)
        assert r.status_code == 403

    def test_delete_soft_deactivates(self, api, base_url, client_auth):
        # create fresh
        r = api.post(f"{base_url}/api/events", headers=client_auth["headers"],
                     json=self._mk_body(60, "todelete"), timeout=30)
        assert r.status_code == 200
        eid = r.json()["id"]
        rd = api.delete(f"{base_url}/api/events/{eid}", headers=client_auth["headers"], timeout=15)
        assert rd.status_code == 200
        assert rd.json().get("ok") is True
        # still in history
        rh = api.get(f"{base_url}/api/events/history", headers=client_auth["headers"], timeout=15).json()
        row = next((x for x in rh if x["id"] == eid), None)
        assert row is not None
        assert row["is_active"] is False

    def test_client_cannot_delete_other_users_event(self, api, base_url, client_auth, coach_auth):
        r_c = api.post(f"{base_url}/api/events", headers=coach_auth["headers"],
                       json=self._mk_body(40, "coachdel"), timeout=30)
        assert r_c.status_code == 200
        other_eid = r_c.json()["id"]
        r = api.delete(f"{base_url}/api/events/{other_eid}", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403


class TestEventCoachOnBehalf:
    def test_coach_creates_event_for_client(self, api, base_url, coach_auth, client_auth):
        client_id = client_auth["user"]["id"]
        body = {
            "user_id": client_id,
            "event_type": "10K",
            "event_name": "TEST Coach-set 10K",
            "event_date": _future_iso(60),
            "target_time": "45:00",
            "preferred_days": ["Mon", "Thu"],
            "access_gym": True, "include_strength": True, "include_mobility": True,
        }
        r = api.post(f"{base_url}/api/events", headers=coach_auth["headers"], json=body, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user_id"] == client_id
        assert d["event_name"] == "TEST Coach-set 10K"
        assert d["is_active"] is True

    def test_coach_get_client_event(self, api, base_url, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/coach/clients/{cid}/event",
                    headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        # last coach-set event for client should be active
        assert d and d.get("is_active") is True
        assert d["user_id"] == cid
        pi = d.get("phase_info")
        assert pi and "phase" in pi and "weeks_to_race" in pi

    def test_coach_client_endpoint_requires_coach(self, api, base_url, client_auth):
        cid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/coach/clients/{cid}/event",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_coach_client_detail_includes_event(self, api, base_url, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/coach/clients/{cid}", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "event" in d
        ev = d["event"]
        assert ev is not None
        assert ev.get("is_active") is True
        assert "phase_info" in ev


class TestEventPhaseComputation:
    """Verify phase branches: base, build, peak, taper, race_week, recovery, post."""

    @pytest.mark.parametrize("days,expected_phase", PHASE_CASES)
    def test_phase_branch(self, api, base_url, client_auth, days, expected_phase):
        body = {
            "event_type": "marathon",
            "event_name": f"TEST Phase {expected_phase} {uuid.uuid4().hex[:5]}",
            "event_date": _future_iso(days),
            "preferred_days": [],
            "include_strength": True, "include_mobility": True,
        }
        r = api.post(f"{base_url}/api/events", headers=client_auth["headers"], json=body, timeout=30)
        assert r.status_code == 200, r.text
        cur = api.get(f"{base_url}/api/events/current", headers=client_auth["headers"], timeout=15).json()
        pi = cur["phase_info"]
        assert pi["phase"] == expected_phase, f"expected {expected_phase} at {days}d, got {pi}"
        # days_to_race should equal our offset (today baseline)
        assert pi["days_to_race"] == days


class TestWorkoutPatchEventFields:
    def test_patch_key_session_and_event_phase(self, api, base_url, coach_auth, client_auth):
        # Find any existing workout for this client (from prior tests / seed).
        wr = api.get(f"{base_url}/api/workouts/week", headers=client_auth["headers"], timeout=15)
        assert wr.status_code == 200
        rows = wr.json()
        if not rows:
            pytest.skip("no workouts to patch")
        wid = rows[0]["id"]
        r = api.patch(f"{base_url}/api/workouts/{wid}", headers=coach_auth["headers"],
                      json={"key_session": True, "event_phase": "peak"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("key_session") is True
        assert d.get("event_phase") == "peak"


class TestEventsNotFound:
    def test_patch_missing_returns_404(self, api, base_url, client_auth):
        r = api.patch(f"{base_url}/api/events/does-not-exist-{uuid.uuid4().hex}",
                      headers=client_auth["headers"],
                      json={"event_type": "5K", "event_name": "x", "event_date": _future_iso(10)},
                      timeout=15)
        assert r.status_code == 404

    def test_delete_missing_returns_404(self, api, base_url, client_auth):
        r = api.delete(f"{base_url}/api/events/does-not-exist-{uuid.uuid4().hex}",
                       headers=client_auth["headers"], timeout=15)
        assert r.status_code == 404
