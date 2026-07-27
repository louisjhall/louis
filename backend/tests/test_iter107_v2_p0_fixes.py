"""
Iteration 107 - V2 Generation Engine P0 Fixes verification.

Tests P0-1..P0-6 + P1-2 as described in review_request for CrewFit.
Coach: louis@crewfit.net / Louis123!
Client: Pietro Sangermano (user_id cbca8b09-1734-4442-9a55-1bb2f78f35c3)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "").rstrip("/") or os.environ.get("EXPO_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "EXPO_PUBLIC_BACKEND_URL (or EXPO_BACKEND_URL) must be set"

CLIENT_ID = "cbca8b09-1734-4442-9a55-1bb2f78f35c3"
COACH_EMAIL = "louis@crewfit.net"
COACH_PASSWORD = "Louis123!"


# ---------- Fixtures ----------


@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": COACH_EMAIL, "password": COACH_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    body = r.json()
    tok = body.get("token") or body.get("access_token") or body.get("jwt")
    assert tok, f"No token in login response: {body}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def roster_facets(auth_headers):
    """P0-3 step 1: build facets, return schedule-days list."""
    r = requests.post(
        f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/roster-facets/build",
        json={"all_active": True},
        headers=auth_headers,
        timeout=120,
    )
    assert r.status_code == 200, f"facets build failed: {r.status_code} {r.text}"

    r2 = requests.get(
        f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/schedule-days",
        headers=auth_headers,
        timeout=60,
    )
    assert r2.status_code == 200, f"schedule-days GET failed: {r2.status_code} {r2.text}"
    body = r2.json()
    days = body if isinstance(body, list) else (
        body.get("schedule_days") or body.get("days") or body.get("items") or []
    )
    assert isinstance(days, list) and len(days) > 0, f"No schedule days returned: {body}"
    return days


@pytest.fixture(scope="module")
def kickoff_response(auth_headers):
    """P0-4/5/6 step 7."""
    r = requests.post(
        f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/kickoff",
        json={"force": True},
        headers=auth_headers,
        timeout=300,
    )
    assert r.status_code == 200, f"kickoff failed: {r.status_code} {r.text}"
    return r.json()


# ---------- P0-3: categorical burden / opportunity ----------


class TestP03Categorical:
    def test_no_opportunity_100(self, roster_facets):
        # step 3
        bad = [
            d for d in roster_facets
            if (d.get("derived") or {}).get("training_opportunity") == 100
        ]
        assert not bad, f"Found {len(bad)} days with training_opportunity==100 (old-bug fingerprint)"

    def test_layover_arrival(self, roster_facets):
        # step 4
        arrivals = [d for d in roster_facets if d.get("day_type") == "layover_arrival"]
        assert arrivals, "No layover_arrival days in roster"
        for d in arrivals:
            der = d.get("derived") or {}
            burden = der.get("duty_burden_score")
            opp = der.get("training_opportunity")
            assert burden is not None and burden >= 70, (
                f"layover_arrival {d.get('date')} burden={burden} (want >=70) derived={der}"
            )
            assert opp is not None and opp <= 30, (
                f"layover_arrival {d.get('date')} opportunity={opp} (want <=30) derived={der}"
            )

    def test_home_day(self, roster_facets):
        # step 5
        home = [d for d in roster_facets if d.get("day_type") == "home_day"]
        assert home, "No home_day days in roster"
        for d in home:
            der = d.get("derived") or {}
            opp = der.get("training_opportunity")
            burden = der.get("duty_burden_score")
            assert opp is not None and opp >= 70, (
                f"home_day {d.get('date')} opportunity={opp} (want >=70) derived={der}"
            )
            assert burden is not None and burden <= 20, (
                f"home_day {d.get('date')} burden={burden} (want <=20) derived={der}"
            )

    def test_standby(self, roster_facets):
        # step 6
        sb = [d for d in roster_facets if d.get("day_type") == "standby"]
        if not sb:
            pytest.skip("No standby days present")
        for d in sb:
            der = d.get("derived") or {}
            burden = der.get("duty_burden_score")
            opp = der.get("training_opportunity")
            assert burden is not None and 40 <= burden <= 60, (
                f"standby {d.get('date')} burden={burden} (want 40-60) derived={der}"
            )
            assert opp is not None and 15 <= opp <= 55, (
                f"standby {d.get('date')} opportunity={opp} (want 15-55) derived={der}"
            )


# ---------- P0-4 + P0-5 + P0-6: kickoff pipeline ----------


class TestKickoff:
    def test_prep_window_event_anchored(self, kickoff_response):
        # step 8
        prep = kickoff_response.get("prep_window") or {}
        assert prep.get("end") == "2027-01-17", f"prep_window.end={prep.get('end')} expected 2027-01-17; prep={prep}"

    def test_phase_plan_present(self, kickoff_response):
        # step 9
        pp = kickoff_response.get("phase_plan") or []
        assert isinstance(pp, list) and pp, f"phase_plan missing/empty: {pp}"
        names = {p.get("phase_kind") or p.get("name") or p.get("phase") for p in pp}
        required = {"foundation", "aerobic_base", "build", "specific_prep", "taper", "race_week"}
        missing = required - names
        assert not missing, f"phase_plan missing phases: {missing}; got {names}"

    def test_phase_weeks_sum(self, kickoff_response):
        # step 10
        prep = kickoff_response.get("prep_window") or {}
        pp = kickoff_response.get("phase_plan") or []
        total = sum(int(p.get("weeks", 0)) for p in pp)
        assert total == prep.get("weeks"), (
            f"phase weeks sum {total} != prep_window.weeks {prep.get('weeks')}"
        )
        assert total == 25, f"expected total 25 weeks, got {total}"

    def test_dna_sync_equipment_context(self, kickoff_response):
        # step 11
        dna_sync = kickoff_response.get("dna_sync") or {}
        eq_ctx = dna_sync.get("equipment_context_id")
        assert isinstance(eq_ctx, str) and eq_ctx, f"dna_sync.equipment_context_id missing: {dna_sync}"

    def test_impl_and_assignments_created(self, kickoff_response):
        # step 12
        impl = kickoff_response.get("implementations_created")
        assg = kickoff_response.get("assignments_created")
        assert isinstance(impl, int) and impl >= 5, f"implementations_created={impl}"
        assert isinstance(assg, int) and assg >= 5, f"assignments_created={assg}"


# ---------- P0-1 + P0-2: assignment READY gating + blocks[] ----------


@pytest.fixture(scope="module")
def assignments(auth_headers, kickoff_response):
    r = requests.get(
        f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/assignments",
        headers=auth_headers,
        timeout=60,
    )
    assert r.status_code == 200, f"assignments GET failed: {r.status_code} {r.text}"
    body = r.json()
    items = body if isinstance(body, list) else body.get("assignments") or body.get("items") or []
    assert isinstance(items, list), f"unexpected assignments shape: {body}"
    return items


class TestReadyGating:
    def test_ready_have_content(self, auth_headers, assignments):
        # step 14
        ready = [a for a in assignments if (a.get("status") or "").lower() == "ready"]
        assert ready, "No READY assignments to verify"
        offenders = []
        for a in ready:
            aid = a.get("id") or a.get("assignment_id") or a.get("_id")
            r = requests.get(
                f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{aid}",
                headers=auth_headers,
                timeout=30,
            )
            if r.status_code != 200:
                offenders.append((aid, f"GET impl {r.status_code}"))
                continue
            impl = r.json()
            exercises = impl.get("exercises") or []
            blocks = impl.get("blocks") or []
            if not (len(exercises) > 0 or len(blocks) > 0):
                offenders.append((aid, f"empty; ex={len(exercises)} bl={len(blocks)}"))
        assert not offenders, f"READY assignments with empty content: {offenders}"

    def test_running_blocks(self, auth_headers, assignments):
        # step 15 — restrict to READY running assignments (cancelled ones have no impl)
        running_focus = {"long_run", "easy_run", "tempo_run", "interval_run", "intervals_run"}
        running_assg = [
            a for a in assignments
            if (a.get("status") or "").lower() == "ready"
            and (a.get("kind") or a.get("focus") or a.get("session_type") or "").lower() in running_focus
        ]
        if not running_assg:
            pytest.skip("No running assignments to verify")
        problems = []
        for a in running_assg:
            aid = a.get("id") or a.get("assignment_id") or a.get("_id")
            r = requests.get(
                f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/plan/implementations/{aid}",
                headers=auth_headers,
                timeout=30,
            )
            if r.status_code != 200:
                problems.append((aid, f"GET impl {r.status_code}"))
                continue
            impl = r.json()
            blocks = impl.get("blocks") or []
            if not blocks:
                problems.append((aid, "blocks empty"))
                continue
            for i, b in enumerate(blocks):
                if "type" not in b:
                    problems.append((aid, f"block[{i}] missing 'type': {b}"))
                btype = (b.get("type") or "").lower()
                if btype in ("warmup", "warm_up", "cooldown", "cool_down"):
                    if b.get("duration_min") is None:
                        problems.append((aid, f"block[{i}] {btype} missing duration_min"))
        assert not problems, f"Running block issues: {problems}"


# ---------- P1-2: decisions scope expansion ----------


class TestDecisionsScope:
    def test_scope_expansion(self, auth_headers, assignments):
        # steps 16-18
        assert assignments, "No assignments available"
        aid = assignments[0].get("id") or assignments[0].get("assignment_id") or assignments[0].get("_id")
        r = requests.get(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/decisions",
            params={"assignment_id": aid},
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"decisions GET failed: {r.status_code} {r.text}"
        body = r.json()
        scope_ids = body.get("scope_ids") or []
        assert isinstance(scope_ids, list) and len(set(scope_ids)) >= 2, (
            f"scope_ids should have >=2 unique ids, got {scope_ids}"
        )
        decisions = body.get("decisions") or []
        allowed = {"WHEN", "WHAT", "ORCHESTRATION"}
        matched = [d for d in decisions if (d.get("layer") or "").upper() in allowed]
        assert matched, f"No decisions with layer in {allowed}; got layers={[d.get('layer') for d in decisions]}"


# ---------- P0-6 side effect: equipment_contexts ----------


class TestEquipmentContexts:
    def test_equipment_context_persisted(self, auth_headers, kickoff_response):
        # step 19
        r = requests.get(
            f"{BASE_URL}/api/v2/coach/clients/{CLIENT_ID}/equipment-contexts",
            headers=auth_headers,
            timeout=30,
        )
        assert r.status_code == 200, f"equipment-contexts GET failed: {r.status_code} {r.text}"
        body = r.json()
        rows = body if isinstance(body, list) else (
            body.get("equipment_contexts") or body.get("contexts") or body.get("items") or []
        )
        assert isinstance(rows, list) and rows, f"no equipment_contexts rows: {body}"
        matches = [
            r for r in rows
            if r.get("source") == "profile_sync" and r.get("scope") == "permanent"
        ]
        assert matches, f"No profile_sync/permanent row found in {rows}"
        want = {"bodyweight", "dumbbells", "treadmill"}
        ok = False
        for m in matches:
            eq = m.get("equipment") or m.get("items") or m.get("equipment_list") or []
            if set(eq) >= want:
                ok = True
                break
        assert ok, f"No profile_sync/permanent row contains {want}; matches={matches}"
