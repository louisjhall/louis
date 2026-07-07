"""CrewFit V1.5 §24 Dynamic Schedule Engine + §25 Workout Player tests.

Covers:
 - POST /schedule/daily-happened (all 11 tags, invalid tag, idempotency, event log rules)
 - GET  /schedule/daily-happened (DESC by date, scoped)
 - POST /schedule/standby (active on/off, mode toggle, event log)
 - POST /schedule/sickness (active on/off, profile.sickness dict, change_type=moderate)
 - POST /schedule/holiday  (active on/off, profile.holiday dict)
 - GET  /schedule/events   (DESC by created_at, scoped)
 - POST /schedule/smart-replan (active roster path, no-roster 400)
 - PATCH /auth/player-pref (valid + invalid + optional fields)
 - PATCH /workouts/{id}/player (valid, invalid, 403 cross-client)
"""
import uuid
import pytest


LOCAL = "http://localhost:8001"   # smart-replan invokes Claude via workouts_regenerate (slow)


TRIGGER_TAGS = [
    "flight_delayed", "called_from_standby", "slept_badly", "less_time",
    "hotel_changed", "ill", "workout_missed", "family_plans", "other",
]
MODERATE_TAGS = {"ill", "called_from_standby"}
NON_TRIGGER_TAGS = ["yes_as_planned", "workout_completed"]
ALL_TAGS = TRIGGER_TAGS + NON_TRIGGER_TAGS


# ------------- Daily Happened ---------------------------------------
class TestDailyHappened:
    def test_invalid_tag_400(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/schedule/daily-happened",
                     headers=client_auth["headers"],
                     json={"tag": "nonsense_xyz"}, timeout=15)
        assert r.status_code == 400, r.text

    @pytest.mark.parametrize("tag", ALL_TAGS)
    def test_valid_tag_upsert(self, api, base_url, client_auth, tag):
        # unique date per tag so we don't overwrite prior ones
        d = f"2029-01-{ALL_TAGS.index(tag)+1:02d}"
        r = api.post(f"{base_url}/api/schedule/daily-happened",
                     headers=client_auth["headers"],
                     json={"tag": tag, "date": d, "note": f"TEST {tag}"}, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tag"] == tag
        assert body["date"] == d
        assert body["note"] == f"TEST {tag}"
        assert "id" in body and "user_id" in body

    def test_idempotent_same_user_same_date(self, api, base_url, client_auth):
        d = "2029-02-15"
        r1 = api.post(f"{base_url}/api/schedule/daily-happened",
                      headers=client_auth["headers"],
                      json={"tag": "less_time", "date": d, "note": "first"}, timeout=15)
        assert r1.status_code == 200
        r2 = api.post(f"{base_url}/api/schedule/daily-happened",
                      headers=client_auth["headers"],
                      json={"tag": "slept_badly", "date": d, "note": "second"}, timeout=15)
        assert r2.status_code == 200
        # GET and count how many rows for that date exist for this user
        g = api.get(f"{base_url}/api/schedule/daily-happened",
                    headers=client_auth["headers"], timeout=15)
        assert g.status_code == 200
        rows = [x for x in g.json() if x.get("date") == d]
        assert len(rows) == 1, f"expected upsert, got {len(rows)} rows"
        assert rows[0]["tag"] == "slept_badly"
        assert rows[0]["note"] == "second"

    def test_list_desc_by_date_scoped(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/schedule/daily-happened",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 2
        # all rows belong to this user
        assert all(x["user_id"] == client_auth["user"]["id"] for x in rows)
        dates = [x["date"] for x in rows]
        assert dates == sorted(dates, reverse=True), f"not DESC: {dates[:5]}"

    def test_non_trigger_tags_dont_log_event(self, api, base_url, client_auth):
        # snapshot events BEFORE
        pre = api.get(f"{base_url}/api/schedule/events",
                      headers=client_auth["headers"], timeout=15).json()
        pre_kinds = {e["id"] for e in pre}

        for tag in NON_TRIGGER_TAGS:
            r = api.post(f"{base_url}/api/schedule/daily-happened",
                         headers=client_auth["headers"],
                         json={"tag": tag, "date": "2029-03-01", "note": "no-event"},
                         timeout=15)
            assert r.status_code == 200

        post = api.get(f"{base_url}/api/schedule/events",
                       headers=client_auth["headers"], timeout=15).json()
        new_events = [e for e in post if e["id"] not in pre_kinds]
        # No new events should be logged specifically for daily_yes_as_planned / daily_workout_completed
        offending = [e for e in new_events if e["kind"] in ("daily_yes_as_planned", "daily_workout_completed")]
        assert offending == [], f"non-trigger tags logged events: {offending}"

    def test_trigger_tag_logs_event_with_change_type(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/schedule/daily-happened",
                     headers=client_auth["headers"],
                     json={"tag": "ill", "date": "2029-03-02", "note": "sick day"},
                     timeout=15)
        assert r.status_code == 200
        ev = api.get(f"{base_url}/api/schedule/events",
                     headers=client_auth["headers"], timeout=15).json()
        matches = [e for e in ev if e["kind"] == "daily_ill" and e["details"].get("date") == "2029-03-02"]
        assert len(matches) >= 1, "expected daily_ill event to be logged"
        assert matches[0]["change_type"] == "moderate"

    def test_trigger_tag_minor_change_type(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/schedule/daily-happened",
                     headers=client_auth["headers"],
                     json={"tag": "less_time", "date": "2029-03-03"},
                     timeout=15)
        assert r.status_code == 200
        ev = api.get(f"{base_url}/api/schedule/events",
                     headers=client_auth["headers"], timeout=15).json()
        matches = [e for e in ev if e["kind"] == "daily_less_time" and e["details"].get("date") == "2029-03-03"]
        assert len(matches) >= 1
        assert matches[0]["change_type"] == "minor"


# ------------- Standby ---------------------------------------------
class TestStandby:
    def test_standby_on_off_persists_and_logs(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/schedule/standby",
                     headers=client_auth["headers"],
                     json={"active": True, "date": "2029-04-01"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["schedule_mode"] == "standby"
        me = api.get(f"{base_url}/api/auth/me",
                     headers=client_auth["headers"], timeout=15).json()
        assert me["profile"].get("schedule_mode") == "standby"
        assert me["profile"].get("standby_active") is True

        ev = api.get(f"{base_url}/api/schedule/events",
                     headers=client_auth["headers"], timeout=15).json()
        assert any(e["kind"] == "standby_on" for e in ev)

        # OFF
        r2 = api.post(f"{base_url}/api/schedule/standby",
                      headers=client_auth["headers"],
                      json={"active": False}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["schedule_mode"] == "normal"
        me2 = api.get(f"{base_url}/api/auth/me",
                      headers=client_auth["headers"], timeout=15).json()
        assert me2["profile"].get("schedule_mode") == "normal"
        ev2 = api.get(f"{base_url}/api/schedule/events",
                      headers=client_auth["headers"], timeout=15).json()
        assert any(e["kind"] == "standby_off" for e in ev2)


# ------------- Sickness ---------------------------------------------
class TestSickness:
    def test_sickness_on_off_persists_dict_and_logs_moderate(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/schedule/sickness",
                     headers=client_auth["headers"],
                     json={"active": True, "illness": "flu", "severity": 6,
                           "doctor_advised_rest": True}, timeout=15)
        assert r.status_code == 200
        assert r.json()["schedule_mode"] == "sickness"

        me = api.get(f"{base_url}/api/auth/me",
                     headers=client_auth["headers"], timeout=15).json()
        prof = me["profile"]
        assert prof.get("schedule_mode") == "sickness"
        assert prof.get("sickness_active") is True
        sick = prof.get("sickness") or {}
        assert sick.get("illness") == "flu"
        assert sick.get("severity") == 6
        assert sick.get("doctor_advised_rest") is True
        assert sick.get("started_at")  # some ISO timestamp

        ev = api.get(f"{base_url}/api/schedule/events",
                     headers=client_auth["headers"], timeout=15).json()
        on = [e for e in ev if e["kind"] == "sickness_on"]
        assert on and on[0]["change_type"] == "moderate"

        # OFF
        r2 = api.post(f"{base_url}/api/schedule/sickness",
                      headers=client_auth["headers"],
                      json={"active": False}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["schedule_mode"] == "normal"
        me2 = api.get(f"{base_url}/api/auth/me",
                      headers=client_auth["headers"], timeout=15).json()
        assert me2["profile"].get("schedule_mode") == "normal"


# ------------- Holiday ---------------------------------------------
class TestHoliday:
    def test_holiday_on_off_persists_dict(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/schedule/holiday",
                     headers=client_auth["headers"],
                     json={"active": True, "start_date": "2029-05-01",
                           "end_date": "2029-05-10", "holiday_type": "beach",
                           "goal": "maintain", "equipment": ["bands", "bodyweight"]},
                     timeout=15)
        assert r.status_code == 200
        assert r.json()["schedule_mode"] == "holiday"

        me = api.get(f"{base_url}/api/auth/me",
                     headers=client_auth["headers"], timeout=15).json()
        prof = me["profile"]
        assert prof.get("schedule_mode") == "holiday"
        hol = prof.get("holiday") or {}
        assert hol.get("start_date") == "2029-05-01"
        assert hol.get("end_date") == "2029-05-10"
        assert hol.get("holiday_type") == "beach"
        assert hol.get("goal") == "maintain"
        assert "bands" in (hol.get("equipment") or [])

        ev = api.get(f"{base_url}/api/schedule/events",
                     headers=client_auth["headers"], timeout=15).json()
        assert any(e["kind"] == "holiday_on" and e["change_type"] == "moderate" for e in ev)

        # OFF → mode reverts to normal
        r2 = api.post(f"{base_url}/api/schedule/holiday",
                      headers=client_auth["headers"],
                      json={"active": False}, timeout=15)
        assert r2.status_code == 200
        assert r2.json()["schedule_mode"] == "normal"


# ------------- Schedule Events list --------------------------------
class TestScheduleEventsList:
    def test_list_desc_and_scoped(self, api, base_url, client_auth, coach_auth):
        r = api.get(f"{base_url}/api/schedule/events",
                    headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 2
        client_uid = client_auth["user"]["id"]
        assert all(e["user_id"] == client_uid for e in rows)
        ts = [e["created_at"] for e in rows]
        assert ts == sorted(ts, reverse=True), "events not DESC by created_at"

        # coach's own events must not include client's events
        r2 = api.get(f"{base_url}/api/schedule/events",
                     headers=coach_auth["headers"], timeout=15)
        assert r2.status_code == 200
        coach_rows = r2.json()
        assert all(e["user_id"] != client_uid for e in coach_rows)


# ------------- Smart Replan ---------------------------------------
class TestSmartReplan:
    def test_no_active_roster_400(self, api, coach_auth):
        # Coach has no active roster
        r = api.post(f"{LOCAL}/api/schedule/smart-replan",
                     headers=coach_auth["headers"],
                     json={"reason": "test", "dates": ["2029-01-01"], "scope": "affected"},
                     timeout=15)
        assert r.status_code == 400, r.text

    def test_active_roster_replans_specific_dates(self, api, client_auth):
        # first find a roster date
        r0 = api.get(f"{LOCAL}/api/roster/current",
                     headers=client_auth["headers"], timeout=30)
        assert r0.status_code == 200
        days = r0.json().get("days") or []
        assert days, "client has no roster days"
        target = [days[0]["date"]]

        r = api.post(f"{LOCAL}/api/schedule/smart-replan",
                     headers=client_auth["headers"],
                     json={"reason": "iter7 test", "dates": target, "scope": "affected"},
                     timeout=180)  # Claude can be slow
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["reason"] == "iter7 test"
        assert body["scope"] == "affected"
        assert body["dates"] == target
        assert isinstance(body.get("workouts"), list)
        # log check
        ev = api.get(f"{LOCAL}/api/schedule/events",
                     headers=client_auth["headers"], timeout=15).json()
        matches = [e for e in ev if e["kind"] == "smart_replan"
                   and e["details"].get("reason") == "iter7 test"]
        assert matches, "smart_replan event was not logged"
        assert matches[0]["change_type"] == "moderate"


# ------------- Player pref ---------------------------------------
class TestPlayerPref:
    @pytest.mark.parametrize("player", ["free", "guided_strength", "guided_timer", "auto"])
    def test_valid_player_persists(self, api, base_url, client_auth, player):
        r = api.patch(f"{base_url}/api/auth/player-pref",
                      headers=client_auth["headers"],
                      json={"default_player": player,
                            "auto_flow": True, "rest_timer_mode": "auto"},
                      timeout=15)
        assert r.status_code == 200, r.text
        user = r.json()
        assert user["profile"]["default_player"] == player
        assert user["profile"]["auto_flow"] is True
        assert user["profile"]["rest_timer_mode"] == "auto"

    def test_invalid_player_400(self, api, base_url, client_auth):
        r = api.patch(f"{base_url}/api/auth/player-pref",
                      headers=client_auth["headers"],
                      json={"default_player": "invalid_player"}, timeout=15)
        assert r.status_code == 400

    def test_player_pref_works_for_coach(self, api, base_url, coach_auth):
        r = api.patch(f"{base_url}/api/auth/player-pref",
                      headers=coach_auth["headers"],
                      json={"default_player": "free"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["profile"]["default_player"] == "free"


# ------------- Workout Player Override ---------------------------
class TestWorkoutPlayer:
    @pytest.fixture(scope="class")
    def wid(self, api, base_url, client_auth):
        rows = api.get(f"{base_url}/api/workouts/week",
                       headers=client_auth["headers"], timeout=30).json()
        assert isinstance(rows, list) and rows, "no workouts for client"
        return rows[0]["id"]

    def test_valid_player_updates_workout(self, api, base_url, client_auth, wid):
        r = api.patch(f"{base_url}/api/workouts/{wid}/player",
                      headers=client_auth["headers"],
                      json={"player": "guided_timer"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["player"] == "guided_timer"

    def test_invalid_player_value_400(self, api, base_url, client_auth, wid):
        r = api.patch(f"{base_url}/api/workouts/{wid}/player",
                      headers=client_auth["headers"],
                      json={"player": "nope"}, timeout=15)
        assert r.status_code == 400

    def test_client_cannot_patch_someone_elses_workout(self, api, base_url, coach_auth, client_auth, wid):
        # Coach can patch (owns nothing → not blocked); but create a fake "another client":
        # register a new user and try to patch the client's workout with that user's token
        email = f"otherclient_{uuid.uuid4().hex[:6]}@crewfit.com"
        reg = api.post(f"{base_url}/api/auth/signup",
                       json={"email": email, "password": "Passw0rd!", "role": "client",
                             "name": "Other Client"}, timeout=15)
        assert reg.status_code == 200, reg.text
        other_token = reg.json()["token"]
        r = api.patch(f"{base_url}/api/workouts/{wid}/player",
                      headers={"Authorization": f"Bearer {other_token}"},
                      json={"player": "free"}, timeout=15)
        assert r.status_code == 403, r.text
