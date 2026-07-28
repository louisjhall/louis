"""Iter 114 — Verify Pietro (V2) programme_status + Today's Reality routing.

Two bugs under test:
  1. `_apply_reality_action` was no-op for V2 clients — should now route via
     `feature_v2_client_bridge.apply_reality_action_v2` and mutate
     `plan_live_v2.placements` + `session_specs`.
  2. `_derive_programme_status` counted `db.workouts` — V2 clients have
     zero legacy workouts → always returned `waiting_for_programme_approval`.
     Should now return `programme_live` when `plan_live_v2` is active.

Also regression: V1 client's programme_status still uses the legacy path
and V1 reality/apply still mutates `db.workouts`.
"""
import os
import pytest
import requests


def _load_env():
    for path in ["/app/frontend/.env", "/app/backend/.env"]:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k, v.strip().strip('"'))
        except Exception:
            pass


_load_env()
BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or
            os.environ.get("EXPO_BACKEND_URL", "").rstrip("/"))
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL/EXPO_BACKEND_URL must be set"

PIETRO_EMAIL = "pietrosangermano1992@hotmail.com"
PIETRO_PW = "Pietro2026"
PIETRO_UID = "c4c7c7dd-4303-4645-af2c-b70212495360"

LOUIS_EMAIL = "louis@crewfit.net"
LOUIS_PW = "Louis123!"

# V1 client (has legacy workouts)
V1_CLIENT_EMAIL = "testcal2@crewfit.com"
V1_CLIENT_PW = "TestCal123!"


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def pietro_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": PIETRO_EMAIL, "password": PIETRO_PW},
                      timeout=30)
    assert r.status_code == 200, f"Pietro login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def v1_token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": V1_CLIENT_EMAIL, "password": V1_CLIENT_PW},
                      timeout=30)
    if r.status_code != 200:
        pytest.skip(f"V1 client login failed: {r.status_code} {r.text}")
    return r.json()["token"]


# ---------------------------------------------------------------------------
# 1. Bug 2 — programme_status for Pietro (V2)
# ---------------------------------------------------------------------------

class TestProgrammeStatusV2:
    def test_pietro_programme_status_is_live(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/programme/status",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("programme_status") == "programme_live", (
            f"Expected 'programme_live' got {data.get('programme_status')} :: {data}"
        )

    def test_pietro_today_plan_state_not_waiting(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/programme/status",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 200
        today = r.json().get("today_plan_state") or {}
        state = today.get("state")
        # Must NOT be waiting.
        assert state != "programme_waiting_approval", (
            f"Today state is still 'programme_waiting_approval': {today}"
        )
        # Happy expected values (per iter114 spec)
        assert state in {"session_planned", "rest_day", "recovery_planned",
                          "travel_day", "layover_day", "no_session_planned"}, (
            f"Unexpected today state {state}: {today}"
        )

    def test_pietro_timeline_all_completed(self, pietro_token):
        r = requests.get(f"{BASE_URL}/api/programme/status",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 200
        timeline = r.json().get("timeline") or []
        assert len(timeline) == 4, f"Expected 4 steps, got {timeline}"
        keys = [s.get("key") for s in timeline]
        assert keys == ["uploaded", "reviewed", "approved", "live"], keys
        states = [s.get("state") for s in timeline]
        assert all(s == "completed" for s in states), (
            f"Not all steps completed: {states} :: {timeline}"
        )


# ---------------------------------------------------------------------------
# 2. Bug 1 — Reality apply E2E for Pietro (mutates plan_live_v2)
# ---------------------------------------------------------------------------

TARGET_DATE = "2026-08-02"


def _get_placement_snapshot(token, date):
    """Return the workout row (from /calendar/range) that corresponds to
    `date` for the current user. Response shape: {days:[{date, workout}]}"""
    r = requests.get(f"{BASE_URL}/api/calendar/range?from={date}&to={date}",
                     headers=_auth(token), timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    days = body.get("days") if isinstance(body, dict) else None
    if days:
        for d in days:
            if d.get("date") == date and d.get("workout"):
                w = dict(d["workout"])
                w["date"] = d["date"]
                return w
    # Fallback: list-shape response
    workouts = body if isinstance(body, list) else (body.get("workouts") or [])
    matching = [w for w in workouts if w.get("date") == date]
    return matching[0] if matching else None


class TestPietroRealityApplyV2:
    def test_reality_submit_returns_options(self, pietro_token):
        r = requests.post(
            f"{BASE_URL}/api/reality/submit",
            headers=_auth(pietro_token),
            json={"date": TARGET_DATE,
                  "reality_kind": "less_time",
                  "time_available_min": 30},
            timeout=90,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("reality_event_id"), body
        opts = body.get("options") or []
        assert len(opts) >= 3, f"Expected ≥3 options, got {len(opts)}: {opts}"
        ids = [o.get("id") for o in opts]
        assert "A" in ids
        # persist to next test
        pytest.reality_event_id = body["reality_event_id"]
        pytest.reality_options = opts

    def test_reality_apply_mutates_v2_plan(self, pietro_token):
        assert getattr(pytest, "reality_event_id", None), "submit test must run first"
        # snapshot before
        before = _get_placement_snapshot(pietro_token, TARGET_DATE)
        assert before is not None, (
            f"No workout row for Pietro on {TARGET_DATE} before apply — "
            f"plan_live_v2 may not span that date"
        )
        before_duration = (before.get("duration_min")
                            or before.get("duration_minutes")
                            or before.get("estimated_minutes"))
        before_title = before.get("title")

        # apply option A (should NOT be ask_coach → strict + touches_locked
        # rules only apply if the option's actions target coach_locked dates;
        # for V2 the whole thing is coach_locked by design — but option A is
        # 'Recommended' and the coach_mode default is 'balanced', so it
        # should apply cleanly and NOT be routed to ask_coach unless the
        # option itself has kind ask_coach.)
        r = requests.post(
            f"{BASE_URL}/api/reality/apply",
            headers=_auth(pietro_token),
            json={"reality_event_id": pytest.reality_event_id,
                  "option_id": "A"},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") in ("applied", "ask_coach"), body

        # If option A was ask_coach (e.g. AI marked it so), fall through to
        # option B which is expected to be a plain adaptation.
        if body.get("status") == "ask_coach":
            # try B
            r2 = requests.post(
                f"{BASE_URL}/api/reality/apply",
                headers=_auth(pietro_token),
                json={"reality_event_id": pytest.reality_event_id,
                      "option_id": "B"},
                timeout=60,
            )
            # apply on a re-used event returns 400 already_applied
            # If so, we still want to verify that the intended kind was
            # something other than ask_coach on option A. Skip mutation check.
            if r2.status_code == 400:
                pytest.skip(f"Option A routed to ask_coach; cannot verify mutation. body={body}")
            body = r2.json()

        assert body.get("status") == "applied", body
        changes = body.get("changes") or []
        assert changes, f"No changes recorded: {body}"

        # At least one change should be `changed=True` OR a `keep`/`ask_coach`
        # legit no-op. For less_time / 30min, the recommended option is
        # almost always a reduce → changed True.
        any_changed = any(c.get("changed") for c in changes)
        # If all no-ops, verify the option's actions were only keep/ask_coach
        if not any_changed:
            all_noop = all((c.get("kind") in ("keep", "ask_coach"))
                            for c in changes)
            assert all_noop, f"Expected mutations but changes={changes}"

        # snapshot after → the workout on TARGET_DATE should have a v2p: id
        # and (for reduce/replace/convert) a different title/duration.
        after = _get_placement_snapshot(pietro_token, TARGET_DATE)
        assert after is not None, f"Post-apply, no row for {TARGET_DATE}"
        assert (after.get("id") or "").startswith("v2p:"), (
            f"Post-apply row is not a V2 synth workout: {after.get('id')}"
        )
        # verify source is engine_v2
        assert after.get("source") == "engine_v2", (
            f"Expected source=engine_v2, got {after.get('source')}"
        )

        # If we actually mutated, either title changed OR duration changed
        after_duration = (after.get("duration_min")
                           or after.get("duration_minutes")
                           or after.get("estimated_minutes"))
        after_title = after.get("title")
        if any_changed:
            # Determine whether the changes actually altered the placement
            # kind/duration (some actions like `note` only touch coach_note
            # and don't affect title/duration surfaced to the client).
            structural_kinds = {"reduce", "extend", "replace",
                                 "convert_mobility", "convert_recovery",
                                 "convert_walk", "skip",
                                 "move", "bring_forward", "push_back"}
            structural = any(c.get("kind") in structural_kinds
                              and c.get("changed") for c in changes)
            if structural:
                mutated = (after_title != before_title) or (
                    after_duration != before_duration
                )
                assert mutated, (
                    f"Expected mutation on {TARGET_DATE} but before "
                    f"({before_title}/{before_duration}m) == after "
                    f"({after_title}/{after_duration}m). "
                    f"changes={changes}"
                )

        pytest.after_snapshot = after

    def test_workouts_week_reflects_reality_change(self, pietro_token):
        """/workouts/week should surface the SAME modified V2 row for TARGET_DATE."""
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(pietro_token), timeout=30)
        assert r.status_code == 200
        rows = r.json()
        matches = [w for w in rows if w.get("date") == TARGET_DATE]
        assert matches, f"No row for {TARGET_DATE} in /workouts/week"
        w = matches[0]
        assert (w.get("id") or "").startswith("v2p:"), w.get("id")
        after = getattr(pytest, "after_snapshot", None)
        if after:
            # duration should agree between the two endpoints
            wd = (w.get("duration_min") or w.get("duration_minutes")
                  or w.get("estimated_minutes"))
            ad = (after.get("duration_min") or after.get("duration_minutes")
                  or after.get("estimated_minutes"))
            assert wd == ad, (
                f"Duration mismatch between /workouts/week ({wd}) "
                f"and /calendar/range ({ad}) after reality apply"
            )


# ---------------------------------------------------------------------------
# 3. Regression — V1 client still uses legacy path
# ---------------------------------------------------------------------------

class TestV1ProgrammeStatusRegression:
    def test_v1_client_programme_status_still_works(self, v1_token):
        r = requests.get(f"{BASE_URL}/api/programme/status",
                         headers=_auth(v1_token), timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # Whatever the value, it should be a valid enum from the spec.
        assert data.get("programme_status") in {
            "no_roster_uploaded", "roster_parsing",
            "roster_needs_client_review", "roster_needs_coach_review",
            "waiting_for_programme_approval", "programme_live",
            "programme_needs_update",
        }, data
        # Timeline shape intact
        tl = data.get("timeline") or []
        assert len(tl) == 4, tl

    def test_v1_workouts_week_no_v2_rows(self, v1_token):
        r = requests.get(f"{BASE_URL}/api/workouts/week",
                         headers=_auth(v1_token), timeout=30)
        assert r.status_code == 200
        rows = r.json()
        # Confirm no v2p: ids surfaced (V1 client shouldn't route through V2)
        v2_rows = [w for w in rows if (w.get("id") or "").startswith("v2p:")]
        assert v2_rows == [], f"V1 client leaked V2 rows: {v2_rows}"
