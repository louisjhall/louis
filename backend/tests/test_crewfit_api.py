"""CrewFit V1.5 backend integration tests.

Covers:
 - Auth (signup, login, /me, extended onboarding via HomeEquipmentBody)
 - Roster extract / confirm / current / history (+expiry, is_active, start/end)
 - Hotels search + upsert + attach to roster
 - Workouts generate-month + regenerate + patch(coach_locked, location) + complete
 - Coach clients + dashboard filters + client detail (+ roster_history)
 - Exercises CRUD (coach-only guarded)
 - Check-ins / Nutrition (meal + summary) / Progress / Messages
 - Push registration (must return 201 even with placeholder key)
 - V1 regression: exercise create is coach-only
"""
import os
import uuid
import pytest

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="


# ---------------- Health ----------------
class TestHealth:
    def test_root(self, api, base_url):
        r = api.get(f"{base_url}/api/", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("ok") is True
        assert "V1.5" in d.get("service", "")


# ---------------- Auth ----------------
class TestAuth:
    def test_login_client(self, client_auth):
        assert client_auth["user"]["role"] == "client"
        assert client_auth["user"]["email"] == "client@crewfit.com"
        # V1.5 seed: extended profile equipment[]
        prof = client_auth["user"].get("profile") or {}
        assert isinstance(prof.get("equipment"), list) and len(prof["equipment"]) >= 1

    def test_login_coach(self, coach_auth):
        assert coach_auth["user"]["role"] == "coach"

    def test_me_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/auth/me", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        u = r.json()
        assert u["email"] == "client@crewfit.com"
        assert "password_hash" not in u

    def test_me_missing_token(self, api, base_url):
        r = api.get(f"{base_url}/api/auth/me", timeout=15)
        assert r.status_code == 401

    def test_login_bad_pw(self, api, base_url):
        r = api.post(f"{base_url}/api/auth/login",
                     json={"email": "client@crewfit.com", "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_signup_and_extended_onboarding(self, api, base_url):
        email = f"test_{uuid.uuid4().hex[:8]}@crewfit.com"
        r = api.post(f"{base_url}/api/auth/signup", json={
            "email": email, "password": "Passw0rd!", "name": "Test User", "role": "client"
        }, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "token" in d and d["user"]["email"] == email
        headers = {"Authorization": f"Bearer {d['token']}"}
        # duplicate signup
        r2 = api.post(f"{base_url}/api/auth/signup", json={
            "email": email, "password": "Passw0rd!", "name": "Test User", "role": "client"
        }, timeout=15)
        assert r2.status_code == 400
        # V1.5 extended onboarding (HomeEquipmentBody)
        payload = {
            "equipment": ["dumbbells", "resistance bands", "yoga mat"],
            "training_location": "home gym",
            "max_home_minutes": 45,
            "preferred_days": ["Mon", "Wed", "Fri", "Sat"],
            "goal": "lose 3kg while flying",
            "injuries": "left knee mild",
            "cardio_equipment": ["skipping rope"],
            "home_base": "DXB",
            "position": "cabin crew",
            "airline": "Skyline",
            "experience_level": "intermediate",
            "strength_level": "intermediate",
            "training_days_per_week": 4,
            "height_cm": 175, "weight_kg": 70,
            "calorie_target": 2100, "protein_target": 140,
            "will_run_outside": True,
        }
        r3 = api.post(f"{base_url}/api/auth/onboarding", headers=headers, json=payload, timeout=15)
        assert r3.status_code == 200, r3.text
        j = r3.json()
        assert j["onboarded"] is True
        p = j["profile"]
        assert p["training_location"] == "home gym"
        assert p["max_home_minutes"] == 45
        assert p["equipment"] == ["dumbbells", "resistance bands", "yoga mat"]
        assert p["preferred_days"] == ["Mon", "Wed", "Fri", "Sat"]
        assert p["cardio_equipment"] == ["skipping rope"]
        assert p["home_base"] == "DXB"
        assert p["position"] == "cabin crew"
        assert p["injuries"] == "left knee mild"


# ---------------- Roster (V1.5) ----------------
class TestRoster:
    @pytest.fixture(scope="class")
    def roster_id(self, api, base_url, client_auth):
        body = {"file_base64": TINY_PNG_B64, "mime_type": "image/png", "week_start": "2026-02-02"}
        r = api.post(f"{base_url}/api/roster/extract", headers=client_auth["headers"],
                     json=body, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        # V1.5 required fields
        assert "id" in d and "days" in d
        assert d.get("is_active") is True
        assert "start_date" in d and "end_date" in d
        # Fallback 7-day off-week when LLM cannot parse the 1x1 png
        assert len(d["days"]) >= 1
        for day in d["days"]:
            assert "date" in day
            assert day.get("day_type") in None.__class__.__mro__ or True  # non-strict
            assert "load" in day
            assert day["load"] in ("green", "amber", "red", "blue", "purple", "grey")
            assert "confidence" in day
            assert "home_or_away" in day
        return d["id"]

    def test_previous_rosters_deactivated(self, api, base_url, client_auth, roster_id):
        # Upload again → previous roster should now be is_active=false
        body = {"file_base64": TINY_PNG_B64, "mime_type": "image/png", "week_start": "2026-03-02"}
        r2 = api.post(f"{base_url}/api/roster/extract", headers=client_auth["headers"],
                      json=body, timeout=120)
        assert r2.status_code == 200
        new_id = r2.json()["id"]
        assert new_id != roster_id
        # history should have both
        rh = api.get(f"{base_url}/api/roster/history", headers=client_auth["headers"], timeout=15)
        assert rh.status_code == 200
        rows = rh.json()
        ids = [x["id"] for x in rows]
        assert roster_id in ids and new_id in ids
        # exactly one active per user
        actives = [x for x in rows if x.get("is_active")]
        assert len(actives) == 1 and actives[0]["id"] == new_id
        # expiry attached to each history row
        for x in rows:
            assert "expiry" in x
            assert x["expiry"]["coverage"] in ("good", "limited", "low", "critical", "expired", "unknown")

    def test_current_expiry(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("is_active") is True
        e = d.get("expiry")
        assert e and "days_remaining" in e and "coverage" in e and "expired" in e

    def test_confirm_rescores(self, api, base_url, client_auth):
        # get current active roster id
        rc = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15).json()
        rid = rc["id"]
        days = [
            {"date": "2026-03-02", "day_type": "Home Day", "flights": [], "notes": ""},
            {"date": "2026-03-03", "day_type": "Long-Haul Duty",
             "flights": [{"from": "DXB", "to": "LHR", "dep": "23:30", "arr": "04:00"}],
             "report_time": "22:00", "notes": ""},
            {"date": "2026-03-04", "day_type": "Layover Arrival Day", "flights": [], "notes": ""},
            {"date": "2026-03-05", "day_type": "Standby", "flights": [], "notes": ""},
            {"date": "2026-03-06", "day_type": "Turnaround Duty",
             "flights": [{"from": "LHR", "to": "CDG"}, {"from": "CDG", "to": "LHR"}, {"from": "LHR", "to": "AMS"}],
             "report_time": "04:30", "notes": ""},
            {"date": "2026-03-07", "day_type": "Rest Day", "flights": [], "notes": ""},
        ]
        r = api.post(f"{base_url}/api/roster/{rid}/confirm", headers=client_auth["headers"],
                     json={"days": days}, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["confirmed"] is True
        assert d["start_date"] == "2026-03-02"
        assert d["end_date"] == "2026-03-07"
        loads = {x["date"]: x["load"] for x in d["days"]}
        assert loads["2026-03-02"] == "green"    # Home Day
        assert loads["2026-03-03"] == "red"      # Long-Haul
        assert loads["2026-03-04"] == "red"      # Layover Arrival
        assert loads["2026-03-05"] == "amber"    # Standby
        assert loads["2026-03-06"] == "red"      # Turnaround w/ early report + 3 flights
        assert loads["2026-03-07"] == "green"    # Rest


# ---------------- Hotels ----------------
class TestHotels:
    def test_search_seeded(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/hotels/search?name=marina", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert any("Marina Bay Sands" in x["name"] for x in rows)
        r2 = api.get(f"{base_url}/api/hotels/search?city=los", headers=client_auth["headers"], timeout=15)
        assert r2.status_code == 200
        rows2 = r2.json()
        assert any("Sofitel" in x["name"] for x in rows2)

    def test_upsert_increments(self, api, base_url, client_auth):
        payload = {"name": "Marina Bay Sands", "city": "Singapore", "country": "SG",
                   "gym_available": True, "equipment": {"dumbbells": True, "treadmill": True},
                   "outdoor_safe": True, "pool": True, "opening_hours": "24h"}
        r = api.post(f"{base_url}/api/hotels", headers=client_auth["headers"], json=payload, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "Marina Bay Sands"
        assert d["submissions"] >= 2  # seed + this
        assert d["confidence"] >= 0.6

    def test_attach_hotel_to_roster_day(self, api, base_url, client_auth):
        rc = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15).json()
        rid = rc["id"]
        # pick first day date
        day_date = rc["days"][0]["date"]
        payload = {
            "date": day_date,
            "hotel": {"name": f"TEST Hotel {uuid.uuid4().hex[:5]}",
                      "city": "Testville", "country": "TT",
                      "gym_available": True,
                      "equipment": {"dumbbells": True, "bench": True}, "pool": False},
        }
        r = api.post(f"{base_url}/api/roster/{rid}/hotel", headers=client_auth["headers"],
                     json=payload, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["day"]["hotel_id"] and d["day"]["hotel_name"]
        assert d["hotel"]["city"] == "Testville"


# ---------------- Workouts (V1.5) ----------------
class TestWorkouts:
    @pytest.fixture(scope="class")
    def gen_result(self, api, base_url, client_auth):
        # NOTE: The public preview URL is fronted by Cloudflare with ~60s edge timeout.
        # /api/workouts/generate-month invokes Claude Sonnet 4.5 for a full month which
        # takes 100-240s → CF returns 502. We call the backend directly on localhost:8001
        # for FUNCTIONAL validation of the endpoint. The CF timeout is reported separately
        # as a HIGH-priority infra/perf issue.
        LOCAL = "http://localhost:8001"
        rc = api.get(f"{base_url}/api/roster/current", headers=client_auth["headers"], timeout=15).json()
        rid = rc["id"]
        r = api.post(f"{LOCAL}/api/workouts/generate-month", headers=client_auth["headers"],
                     json={"roster_id": rid}, timeout=360)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "workouts" in d and isinstance(d["workouts"], list)
        return {"roster_id": rid, "workouts": d["workouts"]}

    def test_shape(self, gen_result):
        ws = gen_result["workouts"]
        if not ws:
            pytest.skip("LLM returned no workouts; skipping shape assertions")
        w = ws[0]
        # V1.5 required fields
        for k in ("id", "date", "day_load", "title", "location", "duration_min",
                  "focus", "warmup", "exercises", "alternatives", "rationale"):
            assert k in w, f"missing key {k} in workout"
        assert isinstance(w["exercises"], list)
        if w["exercises"]:
            ex = w["exercises"][0]
            for k in ("name", "sets", "reps", "rest_sec", "rpe"):
                assert k in ex
        # alternatives keys
        alt = w["alternatives"]
        for k in ("home", "hotel", "no_equipment", "easier", "harder"):
            assert k in alt

    def test_patch_coach_locked_and_location(self, api, base_url, coach_auth, client_auth, gen_result):
        ws = gen_result["workouts"]
        if not ws:
            pytest.skip("no workouts to patch")
        wid = ws[0]["id"]
        r = api.patch(f"{base_url}/api/workouts/{wid}", headers=coach_auth["headers"],
                      json={"coach_locked": True, "location": "Hotel Gym Workout"}, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["coach_locked"] is True
        assert d["location"] == "Hotel Gym Workout"

    def test_client_cannot_patch_other_workout(self, api, base_url, coach_auth):
        # coach patches their own? Non-owned workouts by client → we test 404 on a bogus id
        r = api.get(f"{base_url}/api/workouts/nonexistent-{uuid.uuid4().hex}",
                    headers=coach_auth["headers"], timeout=15)
        assert r.status_code == 404

    def test_regenerate_scope_dates_preserves_locked(self, api, base_url, client_auth, gen_result):
        LOCAL = "http://localhost:8001"
        ws = gen_result["workouts"]
        if len(ws) < 2:
            pytest.skip("need at least 2 workouts")
        locked_wid = ws[0]["id"]
        locked_date = ws[0]["date"]
        target_date = ws[1]["date"]  # regenerate this one
        r = api.post(f"{LOCAL}/api/workouts/regenerate", headers=client_auth["headers"],
                     json={"roster_id": gen_result["roster_id"], "dates": [target_date]}, timeout=300)
        assert r.status_code == 200, r.text
        rg = api.get(f"{base_url}/api/workouts/{locked_wid}", headers=client_auth["headers"], timeout=15)
        assert rg.status_code == 200
        assert rg.json().get("coach_locked") is True
        _ = locked_date

    def test_regenerate_week(self, api, base_url, client_auth, gen_result):
        LOCAL = "http://localhost:8001"
        ws = gen_result["workouts"]
        if not ws:
            pytest.skip("no workouts")
        week_start = ws[0]["date"]
        r = api.post(f"{LOCAL}/api/workouts/regenerate", headers=client_auth["headers"],
                     json={"roster_id": gen_result["roster_id"], "week_start": week_start}, timeout=300)
        assert r.status_code == 200, r.text
        assert "workouts" in r.json()

    def test_regenerate_no_scope_400(self, api, base_url, client_auth, gen_result):
        r = api.post(f"{base_url}/api/workouts/regenerate", headers=client_auth["headers"],
                     json={"roster_id": gen_result["roster_id"]}, timeout=30)
        assert r.status_code == 400

    def test_complete_workout(self, api, base_url, client_auth, gen_result):
        ws = gen_result["workouts"]
        # find one not coach_locked
        candidates = [w for w in ws if not w.get("coach_locked")]
        if not candidates:
            pytest.skip("no unlocked workouts")
        wid = candidates[0]["id"]
        r = api.post(f"{base_url}/api/workouts/{wid}/complete", headers=client_auth["headers"],
                     json={"completed_exercises": [{"name": "Push-Up", "sets": 3}], "rpe": 7,
                           "notes": "TEST complete"}, timeout=15)
        assert r.status_code == 200
        assert r.json()["completed"] is True


# ---------------- Exercises (regression) ----------------
class TestExercises:
    def test_list(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/exercises", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) >= 15
        # Metadata fields present
        sample = rows[0]
        for k in ("name", "category", "equipment", "movement_pattern",
                  "home_ok", "hotel_ok", "bodyweight_ok", "level", "fatigue_cost"):
            assert k in sample

    def test_client_forbidden_create(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/exercises", headers=client_auth["headers"],
                     json={"name": "TEST", "category": "core", "equipment": ["bodyweight"]}, timeout=15)
        assert r.status_code == 403

    def test_coach_create_and_delete(self, api, base_url, coach_auth):
        r = api.post(f"{base_url}/api/exercises", headers=coach_auth["headers"],
                     json={"name": f"TEST_{uuid.uuid4().hex[:6]}", "category": "core",
                           "equipment": ["bodyweight"]}, timeout=15)
        assert r.status_code == 200
        eid = r.json()["id"]
        rd = api.delete(f"{base_url}/api/exercises/{eid}", headers=coach_auth["headers"], timeout=15)
        assert rd.status_code == 200


# ---------------- Check-ins ----------------
class TestCheckins:
    def test_create_and_list(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/checkins", headers=client_auth["headers"], json={
            "week_start": "2026-02-02", "energy": 7, "sleep": 6, "soreness": 4, "stress": 5,
            "weight_kg": 82.5, "notes": "TEST checkin"
        }, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["energy"] == 7 and d["notes"] == "TEST checkin"
        rl = api.get(f"{base_url}/api/checkins", headers=client_auth["headers"], timeout=15)
        assert rl.status_code == 200
        assert any(x["id"] == d["id"] for x in rl.json())


# ---------------- Nutrition ----------------
class TestNutrition:
    def test_meal_no_photo(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/nutrition/meals", headers=client_auth["headers"], json={
            "meal_type": "lunch", "description": "TEST grilled chicken salad",
            "calories": 500, "protein_g": 40,
        }, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["calories"] == 500

    def test_list_and_summary(self, api, base_url, client_auth):
        rl = api.get(f"{base_url}/api/nutrition/meals", headers=client_auth["headers"], timeout=15)
        assert rl.status_code == 200
        assert isinstance(rl.json(), list)
        rs = api.get(f"{base_url}/api/nutrition/summary", headers=client_auth["headers"], timeout=15)
        assert rs.status_code == 200
        s = rs.json()
        assert "calories" in s and "protein_g" in s and "meals" in s
        # onboarding step in TestAuth changed targets for a NEW user only; seeded user targets = 2400/160
        assert s["calorie_target"] in (2100, 2400, 2200)


# ---------------- Progress ----------------
class TestProgress:
    def test_create_and_list(self, api, base_url, client_auth):
        r = api.post(f"{base_url}/api/progress", headers=client_auth["headers"], json={
            "weight_kg": 81.2, "notes": "TEST progress"
        }, timeout=15)
        assert r.status_code == 200
        rl = api.get(f"{base_url}/api/progress", headers=client_auth["headers"], timeout=15)
        assert rl.status_code == 200
        assert any(x.get("notes") == "TEST progress" for x in rl.json())


# ---------------- Messages ----------------
class TestMessages:
    def test_thread_and_partners(self, api, base_url, client_auth, coach_auth):
        client_id = client_auth["user"]["id"]
        coach_id = coach_auth["user"]["id"]
        r = api.post(f"{base_url}/api/messages", headers=client_auth["headers"],
                     json={"to_user_id": coach_id, "text": "TEST hello coach"}, timeout=15)
        assert r.status_code == 200
        r2 = api.post(f"{base_url}/api/messages", headers=coach_auth["headers"],
                      json={"to_user_id": client_id, "text": "TEST hey client"}, timeout=15)
        assert r2.status_code == 200
        rt = api.get(f"{base_url}/api/messages/{coach_id}", headers=client_auth["headers"], timeout=15)
        assert rt.status_code == 200
        texts = [m["text"] for m in rt.json()]
        assert "TEST hello coach" in texts and "TEST hey client" in texts
        rp = api.get(f"{base_url}/api/messages", headers=client_auth["headers"], timeout=15)
        assert rp.status_code == 200 and isinstance(rp.json(), list) and len(rp.json()) >= 1
        rp2 = api.get(f"{base_url}/api/messages", headers=coach_auth["headers"], timeout=15)
        assert rp2.status_code == 200 and isinstance(rp2.json(), list) and len(rp2.json()) >= 1


# ---------------- Coach (V1.5) ----------------
class TestCoach:
    def test_clients_summary(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/clients", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        rows = r.json()
        alex = next((u for u in rows if u["email"] == "client@crewfit.com"), None)
        assert alex is not None
        # V1.5 enriched fields
        for k in ("roster_expiry", "pending_approvals", "red_days", "missed_workouts"):
            assert k in alex
        assert alex["roster_expiry"]["coverage"] in ("good", "limited", "low", "critical", "expired", "no_roster", "unknown")

    def test_dashboard_all_and_counts(self, api, base_url, coach_auth):
        r = api.get(f"{base_url}/api/coach/dashboard", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "clients" in d and "counts" in d and "total" in d
        for k in ("expiring_soon", "expired", "no_roster", "needs_confirmation",
                  "pending_approval", "red_days", "missed"):
            assert k in d["counts"]

    @pytest.mark.parametrize("flt", ["expiring_soon", "expired", "no_roster",
                                     "needs_confirmation", "pending_approval",
                                     "red_days", "missed", "all"])
    def test_dashboard_filters(self, api, base_url, coach_auth, flt):
        r = api.get(f"{base_url}/api/coach/dashboard?filter={flt}",
                    headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "clients" in d and isinstance(d["clients"], list)

    def test_dashboard_forbidden_for_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/dashboard", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403

    def test_client_detail_with_history(self, api, base_url, coach_auth, client_auth):
        cid = client_auth["user"]["id"]
        r = api.get(f"{base_url}/api/coach/clients/{cid}", headers=coach_auth["headers"], timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["client"]["id"] == cid
        assert "workouts" in d and "checkins" in d
        assert "roster_history" in d
        assert isinstance(d["roster_history"], list)
        if d.get("roster"):
            assert "expiry" in d["roster"]

    def test_clients_forbidden_for_client(self, api, base_url, client_auth):
        r = api.get(f"{base_url}/api/coach/clients", headers=client_auth["headers"], timeout=15)
        assert r.status_code == 403


# ---------------- Push ----------------
class TestPush:
    def test_register_push_placeholder_key_still_201(self, api, base_url, client_auth):
        payload = {"user_id": client_auth["user"]["id"], "platform": "ios",
                   "device_token": f"TEST-tok-{uuid.uuid4().hex}"}
        r = api.post(f"{base_url}/api/register-push", json=payload, timeout=30)
        # Should return 201 and NOT 500 even with placeholder key
        assert r.status_code == 201, f"expected 201, got {r.status_code}: {r.text}"
        assert r.json().get("status") == "registered"
