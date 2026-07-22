"""
Iter 92 (Phase 2 — Living Profile Wire-Back) tests.

Covers:
  * Task 2.1: signal extractor unit tests (direct import).
  * Task 2.2: /api/profile/live-state (client) + /api/coach/clients/{id}/live-state (coach).
  * Task 2.3: auto-deload flip in programme_context_for_llm.
  * Task 2.4: /api/messages with include_in_next_plan pins coach_directive.
  * Task 2.4b: /api/coach/clients/{id}/directives POST + DELETE.
  * Regression: strength_overload dampened when energy_trend == 'down'.

Uses live backend via `requests` (avoids TestClient event-loop conflict with motor).
"""
import os
import asyncio
import datetime as _dt
import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or os.environ.get("EXPO_BACKEND_URL") or "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL is required"
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PW = "Client123!"
COACH_EMAIL = "louis@crewfit.net"
COACH_PW = "Louis123!"


def _login(email, pw):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": pw}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["token"], d["user"]


@pytest.fixture(scope="module")
def client_ctx():
    tok, u = _login(CLIENT_EMAIL, CLIENT_PW)
    return {"token": tok, "user": u,
            "headers": {"Authorization": f"Bearer {tok}",
                        "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def coach_ctx():
    tok, u = _login(COACH_EMAIL, COACH_PW)
    return {"token": tok, "user": u,
            "headers": {"Authorization": f"Bearer {tok}",
                        "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def mdb():
    cli = MongoClient(MONGO_URL)
    return cli[DB_NAME]


_LOOP = asyncio.new_event_loop()


def _run(coro):
    return _LOOP.run_until_complete(coro)


# ===========================================================================
# TASK 2.1 — Signal extractor
# ===========================================================================

class TestTask21Extractor:
    def test_pain_and_focus_shift(self):
        from feature_live_state import extract_signals_from_checkin
        sig = extract_signals_from_checkin({
            "energy": 3, "sleep": 5, "soreness": 8, "stress": 8,
            "notes": "My left shoulder has been sore all week. Please add more strength work."
        })
        assert sig["energy_score"] == 3
        assert sig["motivation_flag"] == "low"
        assert any(p["region"] == "shoulder" for p in sig["pain_flags"])
        assert sig["focus_shift_request"]["target"] == "strength"

    def test_no_pain_high_motivation(self):
        from feature_live_state import extract_signals_from_checkin
        sig = extract_signals_from_checkin({
            "energy": 9, "sleep": 8, "soreness": 3, "stress": 3,
            "notes": "Feeling great, ready to push."
        })
        assert sig["motivation_flag"] == "high"
        assert not sig.get("pain_flags")

    def test_life_change_detected(self):
        from feature_live_state import extract_signals_from_checkin
        sig = extract_signals_from_checkin({
            "energy": 5, "sleep": 5, "soreness": 5, "stress": 5,
            "notes": "New roster this month, back on standby."
        })
        assert sig.get("life_change_flag") is True

    def test_pain_variants(self):
        from feature_live_state import extract_signals_from_checkin
        variants = {
            "Pain in my right knee when running.":         "knee",
            "Lower back tight after long haul.":           "lower_back",
            "Achilles is niggling.":                       "achilles",
            "My hip aches after squats.":                  "hip",
        }
        for note, expected in variants.items():
            sig = extract_signals_from_checkin({
                "energy": 6, "sleep": 6, "soreness": 5, "stress": 5, "notes": note,
            })
            regions = {p["region"] for p in (sig.get("pain_flags") or [])}
            assert expected in regions, f"failed on: {note}"


# ===========================================================================
# TASK 2.2 — read-model endpoints
# ===========================================================================

class TestTask22ReadModel:
    def test_client_live_state_endpoint(self, client_ctx):
        r = requests.get(f"{BASE_URL}/api/profile/live-state",
                         headers=client_ctx["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "live_state" in body
        ls = body["live_state"]
        for k in ("window_days", "auto_deload_trigger", "pain_flags",
                  "avoid_movement_patterns", "adherence_pct", "energy_trend"):
            assert k in ls, f"missing {k}"

    def test_coach_live_state_endpoint(self, coach_ctx, mdb):
        u = mdb.users.find_one({"email": CLIENT_EMAIL})
        assert u
        r = requests.get(f"{BASE_URL}/api/coach/clients/{u['id']}/live-state",
                         headers=coach_ctx["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["client_id"] == u["id"]
        assert "live_state" in body


# ===========================================================================
# TASK 2.3 — auto-deload override in programme_context_for_llm
# ===========================================================================

class TestTask23AutoDeload:
    def test_auto_deload_flips_phase(self, mdb):
        from feature_live_state import compute_live_state
        from feature_programme_quality import programme_context_for_llm

        async def _go():
            # Use motor's async db handle
            from server import db as adb
            u = await adb.users.find_one({"email": CLIENT_EMAIL}, {"_id": 0})
            assert u
            # Seed: 6 planned real workouts last 7d, only 1 completed with high RPE.
            today = _dt.date.today()
            # Wipe any existing workouts in the last 7 days to avoid unique-index collisions.
            dates_to_seed = [(today - _dt.timedelta(days=i)).isoformat() for i in range(6)]
            await adb.workouts.delete_many({"user_id": u["id"], "date": {"$in": dates_to_seed}})
            docs = []
            for i, d in enumerate(dates_to_seed):
                docs.append({
                    "id": f"wk_iter92_{i}", "user_id": u["id"], "date": d,
                    "title": "iter92-seed", "focus": "strength",
                    "completed": (i == 0), "rpe": 9 if i == 0 else None,
                    "exercises": [{"name": "Squat", "sets": 3, "reps": "5"}],
                    "created_at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
                })
            await adb.workouts.insert_many(docs)

            state = await compute_live_state(adb, u["id"])
            assert state["auto_deload_trigger"] is True, state

            # Force build_muscle goal so we get strength_overload
            await adb.users.update_one(
                {"id": u["id"]},
                {"$set": {"profile.main_goal_key": "build_muscle"}}
            )
            u2 = await adb.users.find_one({"id": u["id"]}, {"_id": 0})

            roster = {"id": "roster_iter92", "days": [
                {"date": (today + _dt.timedelta(days=i)).isoformat(),
                 "day_type": "rest_day", "load": "amber"} for i in range(7)
            ]}
            # Clean any prior programme row for this fake roster
            await adb.programmes.delete_many({"user_id": u["id"], "roster_id": "roster_iter92"})

            ctx = await programme_context_for_llm(u2, roster)
            assert ctx["phase"]["key"] == "deload", ctx["phase"]
            so = ctx.get("strength_overload") or {}
            assert so.get("sets_delta", 0) <= 0

            # Cleanup
            await adb.workouts.delete_many({"user_id": u["id"], "date": {"$in": dates_to_seed}})

        _run(_go())


# ===========================================================================
# TASK 2.4 — coach message → directive
# ===========================================================================

class TestTask24CoachDirectives:
    def test_message_include_in_next_plan_pins_directive(self, coach_ctx, mdb):
        u = mdb.users.find_one({"email": CLIENT_EMAIL})
        assert u
        # Clear existing directives
        mdb.users.update_one({"id": u["id"]},
                             {"$set": {"profile.live_state.coach_directives": []}})

        r = requests.post(f"{BASE_URL}/api/messages", headers=coach_ctx["headers"],
                          json={
                              "to_user_id": u["id"],
                              "text": "Iter92 directive: prioritise single-leg work next week.",
                              "include_in_next_plan": True,
                          }, timeout=30)
        assert r.status_code == 200, r.text
        msg = r.json()
        assert msg.get("include_in_next_plan") is True

        # Verify directive persisted
        u2 = mdb.users.find_one({"id": u["id"]})
        directives = ((u2.get("profile") or {}).get("live_state") or {}).get("coach_directives") or []
        assert directives, "coach_directives should be populated"
        assert any("single-leg" in (d.get("text") or "").lower() for d in directives)
        assert directives[0].get("source_message_id") == msg["id"]

    def test_add_and_delete_directive_endpoints(self, coach_ctx, mdb):
        u = mdb.users.find_one({"email": CLIENT_EMAIL})
        r = requests.post(f"{BASE_URL}/api/coach/clients/{u['id']}/directives",
                          headers=coach_ctx["headers"],
                          json={"text": "Iter92 add-endpoint directive", "ttl_days": 14},
                          timeout=30)
        assert r.status_code == 200, r.text
        did = r.json()["directive"]["id"]

        r2 = requests.get(f"{BASE_URL}/api/coach/clients/{u['id']}/live-state",
                          headers=coach_ctx["headers"], timeout=30)
        assert r2.status_code == 200
        directives = (r2.json().get("live_state") or {}).get("coach_directives") or []
        assert any(d.get("id") == did for d in directives)

        r3 = requests.delete(f"{BASE_URL}/api/coach/clients/{u['id']}/directives/{did}",
                             headers=coach_ctx["headers"], timeout=30)
        assert r3.status_code == 200


# ===========================================================================
# Regression: energy_trend='down' dampens strength_overload
# ===========================================================================

class TestEnergyTrendDampening:
    def test_energy_down_zeroes_sets_delta(self, mdb):
        from feature_programme_quality import programme_context_for_llm

        async def _go():
            from server import db as adb
            u = await adb.users.find_one({"email": CLIENT_EMAIL}, {"_id": 0})
            # Clean: workouts + iter92 check-ins
            await adb.checkins.delete_many({"user_id": u["id"], "notes": "iter92-energy"})
            await adb.workouts.delete_many({"user_id": u["id"], "title": "iter92-seed"})

            today = _dt.datetime.utcnow()
            # Seed 3 check-ins with descending energy (recent lowest ⇒ trend='down')
            for i, e in enumerate([3, 4, 6]):
                await adb.checkins.insert_one({
                    "id": f"ci_iter92_e_{i}", "user_id": u["id"],
                    "created_at": (today - _dt.timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S"),
                    "week_start": today.date().isoformat(),
                    "energy": e, "sleep": 6, "soreness": 5, "stress": 5,
                    "notes": "iter92-energy",
                    "signals": {"energy_score": e, "energy_delta": e - 5},
                })
            await adb.users.update_one({"id": u["id"]},
                                       {"$set": {"profile.main_goal_key": "build_muscle"}})
            u2 = await adb.users.find_one({"id": u["id"]}, {"_id": 0})

            await adb.programmes.delete_many({"user_id": u["id"], "roster_id": "roster_iter92_energy"})
            roster = {"id": "roster_iter92_energy", "days": [
                {"date": (today.date() + _dt.timedelta(days=i)).isoformat(),
                 "day_type": "rest_day", "load": "amber"} for i in range(7)
            ]}
            ctx = await programme_context_for_llm(u2, roster)
            live = ctx.get("live_state") or {}
            phase_key = (ctx.get("phase") or {}).get("key")
            # Only enforce dampening when we're NOT in deload phase (deload has its own negative delta).
            if (not live.get("auto_deload_trigger")
                    and live.get("energy_trend") == "down"
                    and phase_key != "deload"):
                so = ctx.get("strength_overload") or {}
                assert so.get("sets_delta") == 0, so
            # Cleanup
            await adb.checkins.delete_many({"user_id": u["id"], "notes": "iter92-energy"})

        _run(_go())
