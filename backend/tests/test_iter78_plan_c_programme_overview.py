"""Iter78 Plan C (C1 + C2 + C3) — coach programme overview & timeline tests.

Coverage:
  T1  GET /api/coach/clients/{cid}/programme-overview — response shape, counters,
      source label logic, next_key_session picker, coach role guard.
  T2  GET /api/coach/clients/{cid}/programme-timeline — event merging across
      users, coaching_dna, rosters, roster_audit_log, programmes, workouts,
      change_log, checkins; DESC sort; 404 for unknown client.

All tests seed to a dedicated ephemeral TEST_ user and tear it down cleanly.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EXPO_BACKEND_URL")
    or "https://flight-fit-plans.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

COACH_EMAIL = "louis@crewfit.net"
COACH_PWD = "Louis123!"
CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PWD = "Client123!"


# Single event loop across whole session — motor client is bound to first loop.
# Reuse any pre-existing loop from another test module (e.g. iter77) so that we
# don't pin motor to a second loop that later becomes stale during collection.
try:
    _LOOP = asyncio.get_event_loop()
    if _LOOP.is_closed():
        raise RuntimeError("closed")
except RuntimeError:
    _LOOP = asyncio.new_event_loop()
    asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def coach_token() -> str:
    r = requests.post(f"{API}/auth/login", json={"email": COACH_EMAIL, "password": COACH_PWD}, timeout=20)
    assert r.status_code == 200, f"coach login failed: {r.text}"
    d = r.json()
    return d.get("access_token") or d.get("token")


@pytest.fixture(scope="module")
def client_login():
    """Try normal login first; if the shared test client is disabled, mint a
    fresh test client user + token directly (using make_token from server)."""
    r = requests.post(f"{API}/auth/login", json={"email": CLIENT_EMAIL, "password": CLIENT_PWD}, timeout=20)
    cleanup_uid = None
    if r.status_code == 200:
        d = r.json()
        tok = d.get("access_token") or d.get("token")
        me = requests.get(f"{API}/auth/me", headers=_auth(tok), timeout=20).json()
        yield {"token": tok, "id": me["id"]}
        return

    async def _mint():
        from server import db, make_token  # type: ignore
        uid = f"{TEST_TAG}_cli_{uuid.uuid4().hex[:6]}"
        await db.users.insert_one({
            "id": uid, "email": f"{uid}@crewfit-test.com",
            "name": "TestClient", "role": "client",
            "status": "active", "created_at": _iso_ts(0),
        })
        return uid, make_token(uid, "client")

    uid, tok = _run(_mint())
    cleanup_uid = uid
    try:
        yield {"token": tok, "id": uid}
    finally:
        _run(_cleanup(cleanup_uid))


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

TEST_TAG = f"TEST_iter78_{uuid.uuid4().hex[:6]}"


def _iso_date(days_delta: int = 0) -> str:
    return (_dt.date.today() + _dt.timedelta(days=days_delta)).isoformat()


def _iso_ts(days_delta: int = 0) -> str:
    return (_dt.datetime.utcnow() + _dt.timedelta(days=days_delta)).isoformat() + "Z"


async def _seed_full_client():
    """Seed a client + roster + programme + mix of workouts + audit + dna +
    change_log + checkins.  Returns the client_id."""
    from server import db  # type: ignore

    cid = f"{TEST_TAG}_u_{uuid.uuid4().hex[:6]}"
    email = f"{cid}@crewfit-test.com"

    created_at = _iso_ts(-40)
    onboarded_at = _iso_ts(-38)

    await db.users.insert_one({
        "id": cid,
        "email": email,
        "name": "Iter78 Test",
        "role": "client",
        "created_at": created_at,
        "onboarded_at": onboarded_at,
        "profile": {"main_goal_key": "event", "event_type_pref": "marathon", "training_days_per_week": 4},
    })

    # coaching_dna versions
    await db.coaching_dna.insert_one({
        "id": f"{TEST_TAG}_dna_1", "user_id": cid, "version": 1,
        "created_at": _iso_ts(-37), "generated_by": "system",
        "primary_goal": "marathon", "motivation_style": "gritty",
    })

    # rosters
    r1_id = f"{TEST_TAG}_ros_1"
    await db.rosters.insert_one({
        "id": r1_id, "user_id": cid, "version": 1,
        "created_at": _iso_ts(-30),
        "confirmed_at": _iso_ts(-29),
        "week_start": _iso_date(-30), "week_end": _iso_date(-24),
        "is_active": True, "status": "confirmed",
    })

    # roster_audit_log — a deletion event
    await db.roster_audit_log.insert_one({
        "id": f"{TEST_TAG}_audit_1", "user_id": cid, "roster_id": r1_id,
        "actor": "client", "event": "deleted", "at": _iso_ts(-20),
        "meta": {"reason": "restart"},
    })

    # programmes with validation errors
    prog_id = f"{TEST_TAG}_prog_1"
    await db.programmes.insert_one({
        "id": prog_id, "user_id": cid, "version_number": 1,
        "goal_key": "event_marathon", "goal_label": "Marathon",
        "phase": {"key": "base", "label": "Base"},
        "target_sessions_per_week": 4,
        "validation_status": "incomplete_content",
        "validation_errors": ["missing_key_session_details"],
        "coach_edited": False,
        "created_at": _iso_ts(-25),
        "deactivated": False,
    })

    # Workouts — a mix
    monday = _dt.date.today() - _dt.timedelta(days=_dt.date.today().weekday())
    today = _dt.date.today()
    #   completed (real training) — this week Monday
    await db.workouts.insert_one({
        "id": f"{TEST_TAG}_w_done", "user_id": cid,
        "date": monday.isoformat(), "focus": "endurance",
        "title": "Easy Run", "completed": True,
        "completed_at": _iso_ts(-2), "duration_min": 45,
    })
    #   missed (real training, this-week past day, not completed).
    #   Must be strictly < today and >= monday and NOT equal to monday (already used).
    missed_date = today - _dt.timedelta(days=1)
    include_missed = (missed_date >= monday) and (missed_date != monday)
    if include_missed:
        await db.workouts.insert_one({
            "id": f"{TEST_TAG}_w_missed", "user_id": cid,
            "date": missed_date.isoformat(), "focus": "strength",
            "title": "Missed Strength", "completed": False,
        })
    #   upcoming — needs_coach_review + template + key_session (today+2)
    await db.workouts.insert_one({
        "id": f"{TEST_TAG}_w_review_key", "user_id": cid,
        "date": _iso_date(2), "focus": "long_run",
        "title": "Long Run", "completed": False,
        "needs_coach_review": True, "key_session": True,
        "source": "template",
    })
    #   upcoming — coach_locked (today+3)
    await db.workouts.insert_one({
        "id": f"{TEST_TAG}_w_locked", "user_id": cid,
        "date": _iso_date(3), "focus": "strength",
        "title": "Locked Strength", "completed": False,
        "coach_locked": True, "source": "template",
    })
    #   upcoming — incomplete_content (today+4)
    await db.workouts.insert_one({
        "id": f"{TEST_TAG}_w_incomp", "user_id": cid,
        "date": _iso_date(4), "focus": "intervals",
        "title": "Intervals", "completed": False,
        "validation_status": "incomplete_content", "source": "template",
    })
    #   upcoming — plain template (today+5)
    await db.workouts.insert_one({
        "id": f"{TEST_TAG}_w_plain", "user_id": cid,
        "date": _iso_date(5), "focus": "endurance",
        "title": "Easy Run 2", "completed": False, "source": "template",
    })
    #   upcoming — recovery (should NOT count as key session / real training) (today+8)
    await db.workouts.insert_one({
        "id": f"{TEST_TAG}_w_recov", "user_id": cid,
        "date": _iso_date(8), "focus": "recovery",
        "title": "Recovery Walk", "completed": False, "key_session": True,
    })

    # change_log — a coach edit
    await db.change_log.insert_one({
        "id": f"{TEST_TAG}_cl_1", "client_id": cid,
        "category": "workout", "kind": "edit",
        "actor": "coach:louis", "at": _iso_ts(-1),
        "title": "Coach adjusted long run", "description": "Reduced volume",
    })

    # checkins
    await db.checkins.insert_one({
        "id": f"{TEST_TAG}_ci_1", "user_id": cid,
        "created_at": _iso_ts(-7), "summary": "feeling fresh",
    })

    return cid


async def _cleanup(cid: str):
    from server import db  # type: ignore

    await db.users.delete_many({"id": cid})
    await db.coaching_dna.delete_many({"user_id": cid})
    await db.rosters.delete_many({"user_id": cid})
    await db.roster_audit_log.delete_many({"user_id": cid})
    await db.programmes.delete_many({"user_id": cid})
    await db.workouts.delete_many({"user_id": cid})
    await db.change_log.delete_many({"client_id": cid})
    await db.checkins.delete_many({"user_id": cid})
    await db.coach_tasks.delete_many({"client_id": cid})


@pytest.fixture(scope="module")
def seeded_client():
    cid = _run(_seed_full_client())
    yield cid
    _run(_cleanup(cid))


# =====================================================================
# T1 — programme-overview endpoint
# =====================================================================

class TestT1ProgrammeOverview:
    def test_overview_shape_and_counters(self, coach_token, seeded_client):
        r = requests.get(
            f"{API}/coach/clients/{seeded_client}/programme-overview",
            headers=_auth(coach_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()

        # Top-level shape
        for key in ("client", "programme", "roster", "week_counts", "upcoming",
                     "next_key_session", "source", "needs_coach_review",
                     "open_coach_tasks_for_client", "at"):
            assert key in d, f"missing key {key} in overview"

        assert d["client"]["id"] == seeded_client
        # week_counts
        wc = d["week_counts"]
        assert wc["completed"] == 1, f"expected 1 completed (Easy Run), got {wc}"
        assert wc["target"] == 4
        assert wc["planned"] >= 2

        # upcoming — includes the review_key + locked + incomp + plain + recov (=5)
        up = d["upcoming"]
        assert up["total_14d"] >= 5, f"expected >=5 upcoming, got {up}"
        assert up["needs_coach_review"] >= 1
        assert up["coach_locked"] >= 1
        assert up["incomplete_content"] >= 1
        assert up["template_count"] >= 4  # review_key, locked, incomp, plain

        # next_key_session — must be the LONG RUN (review_key), NOT recovery
        assert d["next_key_session"] is not None
        assert d["next_key_session"]["id"] == f"{TEST_TAG}_w_review_key"
        assert d["next_key_session"]["focus"] == "long_run"

        # source_label — >50% templates + programme exists → template_fallback
        assert d["source"] == "template_fallback", f"unexpected source: {d['source']}"

        # needs_coach_review — validation_status='incomplete_content' triggers True
        assert d["needs_coach_review"] is True

        # roster is present
        assert d["roster"] is not None
        assert d["roster"]["is_active"] is True

    def test_overview_client_role_denied(self, client_login, seeded_client):
        r = requests.get(
            f"{API}/coach/clients/{seeded_client}/programme-overview",
            headers=_auth(client_login["token"]), timeout=20,
        )
        assert r.status_code == 403, f"expected 403 for client role, got {r.status_code}: {r.text}"

    def test_overview_unknown_client_404(self, coach_token):
        r = requests.get(
            f"{API}/coach/clients/NOTEXIST_{uuid.uuid4().hex[:6]}/programme-overview",
            headers=_auth(coach_token), timeout=20,
        )
        assert r.status_code == 404

    def test_source_awaiting_generation_when_no_programme(self, coach_token):
        """Seed a user with NO programme → source should be awaiting_generation."""
        async def setup():
            from server import db  # type: ignore
            uid = f"{TEST_TAG}_nogen_{uuid.uuid4().hex[:6]}"
            await db.users.insert_one({
                "id": uid, "email": f"{uid}@crewfit-test.com",
                "name": "NoProg", "role": "client",
                "created_at": _iso_ts(-1),
            })
            return uid
        uid = _run(setup())
        try:
            r = requests.get(
                f"{API}/coach/clients/{uid}/programme-overview",
                headers=_auth(coach_token), timeout=20,
            )
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["source"] == "awaiting_generation"
            assert d["programme"] == {}
        finally:
            _run(_cleanup(uid))

    def test_source_coach_edited_wins(self, coach_token):
        """coach_edited=True on programme should override template_fallback."""
        async def setup():
            from server import db  # type: ignore
            uid = f"{TEST_TAG}_ce_{uuid.uuid4().hex[:6]}"
            await db.users.insert_one({
                "id": uid, "email": f"{uid}@crewfit-test.com",
                "name": "CoachEdited", "role": "client",
                "created_at": _iso_ts(-1),
            })
            await db.programmes.insert_one({
                "id": f"{TEST_TAG}_ce_prog", "user_id": uid, "version_number": 1,
                "goal_label": "Marathon",
                "coach_edited": True, "created_at": _iso_ts(-2),
                "validation_status": "ok",
                "target_sessions_per_week": 4,
            })
            # upcoming — one template (would normally push template_fallback), but coach_edited wins
            await db.workouts.insert_one({
                "id": f"{TEST_TAG}_ce_w", "user_id": uid, "date": _iso_date(2),
                "focus": "endurance", "title": "T", "source": "template",
            })
            return uid
        uid = _run(setup())
        try:
            r = requests.get(
                f"{API}/coach/clients/{uid}/programme-overview",
                headers=_auth(coach_token), timeout=20,
            )
            assert r.status_code == 200, r.text
            assert r.json()["source"] == "coach_edited"
        finally:
            _run(_cleanup(uid))

    def test_source_full_planning_when_low_templates(self, coach_token):
        """Programme exists, no coach_edited, mostly non-template workouts → full_planning."""
        async def setup():
            from server import db  # type: ignore
            uid = f"{TEST_TAG}_fp_{uuid.uuid4().hex[:6]}"
            await db.users.insert_one({
                "id": uid, "email": f"{uid}@crewfit-test.com",
                "name": "FullPlanning", "role": "client",
                "created_at": _iso_ts(-1),
            })
            await db.programmes.insert_one({
                "id": f"{TEST_TAG}_fp_prog", "user_id": uid, "version_number": 1,
                "goal_label": "Marathon",
                "coach_edited": False, "created_at": _iso_ts(-2),
                "validation_status": "ok",
                "target_sessions_per_week": 4,
            })
            # 3 llm-source + 1 template → 25% template < 50%
            for i, src in enumerate(["llm", "llm", "llm", "template"]):
                await db.workouts.insert_one({
                    "id": f"{TEST_TAG}_fp_w{i}", "user_id": uid,
                    "date": _iso_date(i + 1), "focus": "endurance",
                    "title": f"W{i}", "source": src,
                })
            return uid
        uid = _run(setup())
        try:
            r = requests.get(
                f"{API}/coach/clients/{uid}/programme-overview",
                headers=_auth(coach_token), timeout=20,
            )
            assert r.status_code == 200, r.text
            assert r.json()["source"] == "full_planning"
        finally:
            _run(_cleanup(uid))


# =====================================================================
# T2 — programme-timeline endpoint
# =====================================================================

class TestT2ProgrammeTimeline:
    def test_timeline_shape_and_events(self, coach_token, seeded_client):
        r = requests.get(
            f"{API}/coach/clients/{seeded_client}/programme-timeline?limit=200",
            headers=_auth(coach_token), timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "timeline" in d and "count" in d
        assert d["count"] == len(d["timeline"])
        assert d["count"] >= 8, f"expected many events, got {d['count']}"

        # Collect kinds
        kinds = {e["kind"] for e in d["timeline"]}
        expected = {
            "onboarding.started",
            "assessment.completed",
            "dna.version",
            "roster.uploaded",
            "roster.confirmed",
            "roster.deleted",
            "programme.generated",
            "programme.validation_flag",
            "workout.completed",
            "checkin.completed",
        }
        missing = expected - kinds
        assert not missing, f"missing expected kinds: {missing}. Got: {kinds}"

        # DESC sort — first `at` >= last `at`
        ats = [e["at"] for e in d["timeline"] if e.get("at")]
        assert ats == sorted(ats, reverse=True), "timeline not sorted DESC by at"

        # Every event has minimally required keys
        for e in d["timeline"]:
            assert "at" in e and e["at"]
            assert "kind" in e and e["kind"]
            assert "title" in e
            assert "detail" in e or e.get("meta") is not None
            assert "actor" in e

    def test_timeline_limit_respected(self, coach_token, seeded_client):
        r = requests.get(
            f"{API}/coach/clients/{seeded_client}/programme-timeline?limit=3",
            headers=_auth(coach_token), timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["count"] <= 3

    def test_timeline_unknown_client_404(self, coach_token):
        r = requests.get(
            f"{API}/coach/clients/NOTEXIST_{uuid.uuid4().hex[:6]}/programme-timeline",
            headers=_auth(coach_token), timeout=20,
        )
        assert r.status_code == 404

    def test_timeline_client_role_denied(self, client_login, seeded_client):
        r = requests.get(
            f"{API}/coach/clients/{seeded_client}/programme-timeline",
            headers=_auth(client_login["token"]), timeout=20,
        )
        assert r.status_code == 403


# =====================================================================
# T3 — Regression smoke: Plan A/B/D endpoints still healthy
# =====================================================================

class TestT3RegressionSmoke:
    def test_coach_dashboard_healthy(self, coach_token):
        r = requests.get(f"{API}/coach/dashboard", headers=_auth(coach_token), timeout=30)
        assert r.status_code == 200

    def test_client_home_endpoints(self, client_login):
        r = requests.get(f"{API}/programme/current", headers=_auth(client_login["token"]), timeout=30)
        assert r.status_code in (200, 404)  # 404 if no programme yet is OK

    def test_coach_roster_alerts(self, coach_token):
        r = requests.get(f"{API}/coach/roster-alerts", headers=_auth(coach_token), timeout=20)
        assert r.status_code == 200
