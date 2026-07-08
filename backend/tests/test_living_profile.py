"""Backend tests for Living Profile (Phase C) — Coaching DNA injection + re-assessment prompt engine.

Covers the 13 cases requested in the review:
  1. Client login
  2. GET /reassessment/prompts base structure
  3. Cleanup (dismiss existing)
  4. /workouts/week emits missed_workouts / event_completed
  5. Cool-down prevents duplicate missed_workouts
  6. Dismiss by prompt_id
  7. Dismiss by kind
  8. Empty dismiss body → 400
  9. PATCH /coaching-dna primary_goal → life_change prompt
 10. Second PATCH → cool-down keeps count at 1
 11. day-override with injured tag → injury_flagged prompt
 12. /reality/submit still works with DNA context injection
 13. Auth gating on both prompt endpoints
"""
import asyncio
import os
import sys
from datetime import date, timedelta

import pytest
import requests

# Make backend module importable so we can bootstrap DNA docs directly on Mongo
sys.path.insert(0, "/app/backend")

# The review request specifies live backend @ http://localhost:8001
BASE_URL = "http://localhost:8001"


def _mongo_db():
    """Return a sync pymongo db handle using the same env the server uses."""
    from pymongo import MongoClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv("/app/backend/.env")
    client = MongoClient(os.environ["MONGO_URL"])
    return client, client[os.environ["DB_NAME"]]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.iscoroutine(coro) else asyncio.new_event_loop().run_until_complete(coro)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def client_auth(api):
    r = api.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "client@crewfit.com", "password": "Client123!"},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    return {"token": data["token"], "user": data["user"],
            "headers": {"Authorization": f"Bearer {data['token']}"}}


@pytest.fixture(scope="module")
def original_dna(api, client_auth):
    """Capture original DNA so we can restore any fields we mutate.
    If the seed client has NO DNA yet (fresh env), bootstrap a minimal record
    so the PATCH endpoint doesn't 404. Remove the bootstrapped record in teardown.
    """
    r = api.get(f"{BASE_URL}/api/coaching-dna", headers=client_auth["headers"], timeout=15)
    assert r.status_code == 200
    dna = r.json().get("dna")
    bootstrapped_id = None

    if not dna:
        # Insert a minimal DNA doc directly so PATCH has something to update.
        import uuid
        from datetime import datetime, timezone
        client, dbh = _mongo_db()
        try:
            new_doc = {
                "id": str(uuid.uuid4()),
                "user_id": client_auth["user"]["id"],
                "assessment_id": None,
                "version": 1,
                "primary_goal": "TEST bootstrap goal",
                "recovery_risk": "medium",
                "motivation_style": "routine",
                "coaching_style": "supportive",
                "training_availability": "4x/week 45min",
                "biggest_weakness": "consistency",
                "biggest_opportunity": "aerobic base",
                "ai_confidence_score": 50,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "_test_bootstrap": True,
            }
            dbh.coaching_dna.insert_one(new_doc)
            bootstrapped_id = new_doc["id"]
        finally:
            client.close()
        # Refetch via API to confirm
        r2 = api.get(f"{BASE_URL}/api/coaching-dna", headers=client_auth["headers"], timeout=15)
        dna = r2.json().get("dna")
        assert dna, "bootstrap failed — DNA still not visible"

    yield dna

    # Teardown: if we bootstrapped, remove only that doc so we leave no permanent trace
    if bootstrapped_id:
        client, dbh = _mongo_db()
        try:
            dbh.coaching_dna.delete_one({"id": bootstrapped_id})
        finally:
            client.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _get_prompts(api, auth):
    r = api.get(f"{BASE_URL}/api/reassessment/prompts", headers=auth["headers"], timeout=15)
    assert r.status_code == 200, f"GET prompts failed: {r.status_code} {r.text}"
    body = r.json()
    assert "prompts" in body and isinstance(body["prompts"], list), body
    return body["prompts"]


def _dismiss_all_kinds(api, auth):
    prompts = _get_prompts(api, auth)
    kinds = sorted({p["kind"] for p in prompts})
    for k in kinds:
        r = api.post(
            f"{BASE_URL}/api/reassessment/dismiss",
            headers=auth["headers"], json={"kind": k}, timeout=15,
        )
        assert r.status_code == 200, f"dismiss {k} failed: {r.status_code} {r.text}"
    # verify empty
    assert _get_prompts(api, auth) == [], "prompts should be empty after cleanup"


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
class TestLivingProfile:

    # 1 + 2
    def test_01_login_and_base_prompts(self, api, client_auth):
        assert client_auth["user"]["email"] == "client@crewfit.com"
        prompts = _get_prompts(api, client_auth)
        # Structure only — count may be non-zero from earlier flows
        for p in prompts:
            assert "id" in p and "kind" in p and "reason" in p and "created_at" in p
            assert p.get("dismissed") is False

    # 3
    def test_02_cleanup_existing(self, api, client_auth):
        _dismiss_all_kinds(api, client_auth)

    # 4
    def test_03_workouts_week_emits_prompt(self, api, client_auth):
        r = api.get(f"{BASE_URL}/api/workouts/week", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        prompts = _get_prompts(api, client_auth)
        kinds = {p["kind"] for p in prompts}
        assert kinds & {"missed_workouts", "event_completed"}, \
            f"expected at least one of missed_workouts/event_completed, got {kinds}"

    # 5
    def test_04_missed_workouts_cooldown(self, api, client_auth):
        before = _get_prompts(api, client_auth)
        missed_before = [p for p in before if p["kind"] == "missed_workouts"]
        # call week again
        r = api.get(f"{BASE_URL}/api/workouts/week", headers=client_auth["headers"], timeout=30)
        assert r.status_code == 200
        after = _get_prompts(api, client_auth)
        missed_after = [p for p in after if p["kind"] == "missed_workouts"]
        # Cool-down should hold count constant (at most 1, exactly the pre-existing count)
        assert len(missed_after) == len(missed_before), \
            f"cool-down failed: missed_before={len(missed_before)} missed_after={len(missed_after)}"
        if missed_after:
            assert len(missed_after) == 1, f"expected exactly 1 missed_workouts prompt, got {len(missed_after)}"

    # 6
    def test_05_dismiss_by_prompt_id(self, api, client_auth):
        prompts = _get_prompts(api, client_auth)
        assert prompts, "need at least one prompt to dismiss by id"
        pid = prompts[0]["id"]
        r = api.post(
            f"{BASE_URL}/api/reassessment/dismiss",
            headers=client_auth["headers"], json={"prompt_id": pid}, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("dismissed") == 1
        remaining_ids = [p["id"] for p in _get_prompts(api, client_auth)]
        assert pid not in remaining_ids

    # 7
    def test_06_dismiss_by_kind(self, api, client_auth):
        r = api.post(
            f"{BASE_URL}/api/reassessment/dismiss",
            headers=client_auth["headers"], json={"kind": "event_completed"}, timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("dismissed") >= 0
        kinds = {p["kind"] for p in _get_prompts(api, client_auth)}
        assert "event_completed" not in kinds

    # 8
    def test_07_dismiss_empty_body_400(self, api, client_auth):
        r = api.post(
            f"{BASE_URL}/api/reassessment/dismiss",
            headers=client_auth["headers"], json={}, timeout=15,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"

    # 9
    def test_08_dna_patch_emits_life_change(self, api, client_auth, original_dna):
        # ensure no life_change prompt already exists in cool-down window
        api.post(f"{BASE_URL}/api/reassessment/dismiss",
                 headers=client_auth["headers"], json={"kind": "life_change"}, timeout=15)
        # store original goal for restoration
        original_goal = original_dna.get("primary_goal")
        r = api.patch(
            f"{BASE_URL}/api/coaching-dna",
            headers=client_auth["headers"],
            json={"updates": {"primary_goal": "TEST TEMP GOAL"}, "reason": "living-profile test"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        prompts = _get_prompts(api, client_auth)
        life = [p for p in prompts if p["kind"] == "life_change"]
        assert life, f"expected life_change prompt, got kinds={[p['kind'] for p in prompts]}"
        assert "primary_goal" in (life[0].get("meta") or {}).get("fields", []), life[0]
        # stash restore target for a later teardown-ish test
        pytest.living_profile_original_goal = original_goal

    # 10
    def test_09_dna_patch_life_change_cooldown(self, api, client_auth):
        before = [p for p in _get_prompts(api, client_auth) if p["kind"] == "life_change"]
        r = api.patch(
            f"{BASE_URL}/api/coaching-dna",
            headers=client_auth["headers"],
            json={"updates": {"primary_goal": "TEST TEMP GOAL 2"}, "reason": "cool-down probe"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        after = [p for p in _get_prompts(api, client_auth) if p["kind"] == "life_change"]
        assert len(after) == len(before) == 1, \
            f"cool-down failed: before={len(before)} after={len(after)}"

    # 11
    def test_10_day_override_injury_flag(self, api, client_auth):
        # make sure no lingering injury_flagged prompt from a prior run
        api.post(f"{BASE_URL}/api/reassessment/dismiss",
                 headers=client_auth["headers"], json={"kind": "injury_flagged"}, timeout=15)
        future = (date.today() + timedelta(days=3)).isoformat()
        r = api.post(
            f"{BASE_URL}/api/calendar/day-override",
            headers=client_auth["headers"],
            json={"date": future, "tags": ["injured"]},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        try:
            prompts = _get_prompts(api, client_auth)
            kinds = [p["kind"] for p in prompts]
            assert "injury_flagged" in kinds, f"expected injury_flagged, got {kinds}"
            inj = [p for p in prompts if p["kind"] == "injury_flagged"][0]
            assert (inj.get("meta") or {}).get("date") == future
        finally:
            # cleanup override + prompt
            api.delete(f"{BASE_URL}/api/calendar/day-override",
                       headers=client_auth["headers"], params={"date": future}, timeout=15)
            api.post(f"{BASE_URL}/api/reassessment/dismiss",
                     headers=client_auth["headers"], json={"kind": "injury_flagged"}, timeout=15)

    # 12
    def test_11_reality_submit_with_dna_context(self, api, client_auth):
        today = date.today().isoformat()
        r = api.post(
            f"{BASE_URL}/api/reality/submit",
            headers=client_auth["headers"],
            json={"date": today, "reality_kind": "more_time", "notes": "living-profile smoke test",
                  "time_available_min": 45},
            timeout=60,
        )
        assert r.status_code == 200, f"reality/submit failed: {r.status_code} {r.text}"
        body = r.json()
        # Structure: options list with 3 items
        options = body.get("options") or body.get("event", {}).get("options") or []
        assert len(options) == 3, f"expected 3 options, got {len(options)}"
        # Soft check: no crash. Optional log if Claude referenced DNA elements.
        summary = (body.get("context_summary") or body.get("event", {}).get("context_summary") or "")
        _ = summary  # soft-check only; do not assert

    # 13
    def test_12_auth_gating(self, api):
        r1 = api.get(f"{BASE_URL}/api/reassessment/prompts", timeout=15)
        assert r1.status_code in (401, 403), f"GET should require auth, got {r1.status_code}"
        r2 = api.post(f"{BASE_URL}/api/reassessment/dismiss", json={"kind": "life_change"}, timeout=15)
        assert r2.status_code in (401, 403), f"POST should require auth, got {r2.status_code}"

    # 14 — teardown / restoration
    def test_99_cleanup_restore(self, api, client_auth, original_dna):
        # Restore original primary_goal to whatever it was before mutation
        target = getattr(pytest, "living_profile_original_goal", None)
        if original_dna and target is not None:
            api.patch(
                f"{BASE_URL}/api/coaching-dna",
                headers=client_auth["headers"],
                json={"updates": {"primary_goal": target}, "reason": "restore after living-profile test"},
                timeout=20,
            )
        # Dismiss every prompt we may have touched
        for kind in ("life_change", "injury_flagged", "missed_workouts",
                     "event_completed", "annual_leave", "roster_uploaded"):
            api.post(
                f"{BASE_URL}/api/reassessment/dismiss",
                headers=client_auth["headers"], json={"kind": kind}, timeout=15,
            )
        assert _get_prompts(api, client_auth) == [], "prompts should be empty after cleanup"
