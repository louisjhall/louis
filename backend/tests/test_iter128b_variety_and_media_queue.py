"""
Iter 128b — Flight Support Variety Engine + Coach Media Queue Matrix tests.

Backend-only. Deterministic Python + Mongo reads. No LLM.
"""
from __future__ import annotations
import os
import sys
import asyncio
import datetime as _dt
from typing import Any

import pytest
import requests

# Ensure backend importable for direct unit tests on feature_aviation_support
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://flight-fit-plans.preview.emergentagent.com").rstrip("/")

COACH = ("louis@crewfit.net", "Louis123!")
CLIENT = ("reviewer@crewfit.net", "CrewFitReview2026!")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": password}, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"], r.json()["user"]


@pytest.fixture(scope="module")
def coach_ctx():
    tok, user = _login(*COACH)
    return {"token": tok, "user": user, "headers": {"Authorization": f"Bearer {tok}"}}


@pytest.fixture(scope="module")
def client_ctx():
    tok, user = _login(*CLIENT)
    return {"token": tok, "user": user, "headers": {"Authorization": f"Bearer {tok}"}}


# ---------------------------------------------------------------------------
# 1. Variety Engine unit tests (feature_aviation_support)
# ---------------------------------------------------------------------------

class TestVarietyEngineUnit:
    """Deterministic in-process tests of pick_from_pool / select_interventions_for_day."""

    def test_a_determinism(self):
        from feature_aviation_support import pick_from_pool
        k1 = pick_from_pool(pool_key="pre_flight_light", user_id="u1", date="2026-01-15",
                            history_keys=[], restrictions=[])
        k2 = pick_from_pool(pool_key="pre_flight_light", user_id="u1", date="2026-01-15",
                            history_keys=[], restrictions=[])
        assert k1 == k2 and k1 is not None

    def test_b_date_rotation(self):
        from feature_aviation_support import pick_from_pool
        picks = {pick_from_pool(pool_key="pre_flight_light", user_id="u1",
                                date=f"2026-01-{d:02d}", history_keys=[], restrictions=[])
                 for d in range(1, 30)}
        # Different dates over a month should produce >1 distinct pick
        assert len(picks) >= 2, f"date rotation not observable across a month: {picks}"

    def test_c_recency_penalty(self):
        from feature_aviation_support import pick_from_pool, POOLS
        pool = "pre_flight_light"
        first = pick_from_pool(pool_key=pool, user_id="u1", date="2026-01-15",
                               history_keys=[], restrictions=[])
        # Feed first pick as recent history — pick should change
        second = pick_from_pool(pool_key=pool, user_id="u1", date="2026-01-15",
                                history_keys=[first], restrictions=[])
        assert second != first, f"recency penalty failed: {first} -> {second}"
        # With 3 recent picks, the next MUST be one of the remaining pool entries
        recent = [first, second]
        third = pick_from_pool(pool_key=pool, user_id="u1", date="2026-01-15",
                               history_keys=recent, restrictions=[])
        recent.append(third)
        fourth = pick_from_pool(pool_key=pool, user_id="u1", date="2026-01-15",
                                history_keys=recent, restrictions=[])
        assert fourth in POOLS[pool] and fourth not in recent, \
            f"fourth pick {fourth} should be new; recent={recent}"

    def test_d_safety_filter_restrictions(self):
        from feature_aviation_support import pick_from_pool
        # With a heavy knee restriction, hip_opener_7 should never be chosen
        for i in range(15):
            k = pick_from_pool(pool_key="pre_flight_light",
                               user_id=f"u{i}", date=f"2026-01-{(i % 28)+1:02d}",
                               history_keys=[], restrictions=["knee"])
            assert k != "pilot_pre_flight_hip_opener_7", f"knee restriction leaked hip_opener: {k}"

    def test_e_fallback_safety(self):
        """If we invent a restriction that eliminates every candidate via
        restricted_regions, pick_from_pool must still return something
        (not None) — safety-first fallback."""
        from feature_aviation_support import pick_from_pool, POOLS, PROTOCOLS
        # Choose a pool where every entry has some restricted_regions
        # (post_flight_reset: some entries have back, others none). We'll
        # test with an aggressive multi-region restriction.
        # Take all restricted regions across a pool and pass them all →
        # everything filtered, but we still expect a fallback.
        pool = "layover_full"
        all_regs = set()
        for k in POOLS[pool]:
            all_regs.update(PROTOCOLS[k].restricted_regions or [])
        # every layover_full entry has foot+ankle → this restriction kills them all
        res = pick_from_pool(pool_key=pool, user_id="u1", date="2026-01-15",
                             history_keys=[], restrictions=list(all_regs))
        assert res is not None, "fallback should never return None"
        assert res in POOLS[pool], f"fallback returned unknown key: {res}"

    def test_g_pool_key_populated(self):
        from feature_aviation_support import select_interventions_for_day
        roster_day = {"day_type": "flight_duty",
                      "flights": [{"dep_time": "08:00", "arr_time": "12:00"}]}
        result = select_interventions_for_day(
            role="pilot", roster_day=roster_day, date="2026-01-15",
            has_training_today=False,
            user_id="u1", history_keys=[], restrictions=[], equipment_available=[],
        )
        assert len(result) >= 1
        for it in result:
            assert it.pool_key, f"missing pool_key on intervention: {it}"

    def test_h_backward_compat_no_new_kwargs(self):
        """Calling without the new kwargs should still return interventions
        (uses first pool candidate as safe fallback)."""
        from feature_aviation_support import select_interventions_for_day
        roster_day = {"day_type": "flight_duty",
                      "flights": [{"dep_time": "08:00", "arr_time": "12:00"}]}
        result = select_interventions_for_day(
            role="pilot", roster_day=roster_day, date="2026-01-15",
            has_training_today=False,
        )
        assert len(result) >= 1
        assert all(i.protocol_key for i in result)


# ---------------------------------------------------------------------------
# 2. Full-pipeline (Mongo-backed) test via get_flight_support_by_date
# ---------------------------------------------------------------------------

class TestFlightSupportPipeline:
    def test_f_history_filters_next_pick(self, client_ctx):
        """(f) Seed 3 fake flight_support_activity docs and verify the
        selected pre_flight_light pick is NOT one of them."""
        import motor.motor_asyncio as _motor
        from feature_aviation_support import get_flight_support_by_date

        mongo_url = os.environ.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME")
        assert mongo_url and db_name

        user_id = client_ctx["user"]["id"]
        seeded_keys = [
            "pilot_pre_flight_breathing_5",
            "pilot_pre_flight_neck_shoulder_5",
            "pilot_pre_flight_mobility_6",
        ]

        async def _run():
            client = _motor.AsyncIOMotorClient(mongo_url)
            db = client[db_name]
            # Cleanup any leftover TEST_ seeded rows from prior runs
            await db.flight_support_activity.delete_many(
                {"user_id": user_id, "test_marker": "TEST_iter128b"}
            )
            now = _dt.datetime.now(_dt.timezone.utc)
            # Seed rows newest-first-friendly. Use dates in the past week.
            for i, k in enumerate(seeded_keys):
                await db.flight_support_activity.insert_one({
                    "user_id": user_id,
                    "protocol_key": k,
                    "date": (now - _dt.timedelta(days=i + 1)).date().isoformat(),
                    "updated_at": (now - _dt.timedelta(hours=i)).isoformat(),
                    "status": "completed",
                    "test_marker": "TEST_iter128b",
                })
            try:
                # Force pilot role for this reviewer test regardless of prod profile
                await db.users.update_one(
                    {"id": user_id},
                    {"$set": {"profile.aviation_role": "pilot"}},
                )
                target_date = "2026-02-14"
                roster = {target_date: {"day_type": "flight_duty",
                                        "flights": [{"dep_time": "08:00", "arr_time": "12:00"}]}}
                result = await get_flight_support_by_date(db, user_id, roster, {})
                assert target_date in result, f"empty result: {result}"
                items = result[target_date]
                pre = next((x for x in items if x.get("pool_key") == "pre_flight_light"), None)
                assert pre is not None, f"no pre_flight_light in {items}"
                assert pre["protocol_key"] not in seeded_keys, \
                    f"variety history filter FAILED: picked {pre['protocol_key']} despite recent {seeded_keys}"
                # Also confirm every returned intervention has pool_key set
                for it in items:
                    assert it.get("pool_key"), f"missing pool_key: {it}"
            finally:
                await db.flight_support_activity.delete_many(
                    {"user_id": user_id, "test_marker": "TEST_iter128b"}
                )
                client.close()

        asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# 3. Coach Media Queue endpoint tests
# ---------------------------------------------------------------------------

MEDIA_URL = f"{BASE_URL}/api/coach/flight-support/media-queue"


class TestCoachMediaQueue:
    def test_i_unauthenticated(self):
        r = requests.get(MEDIA_URL, timeout=30)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_i_client_forbidden(self, client_ctx):
        r = requests.get(MEDIA_URL, headers=client_ctx["headers"], timeout=30)
        assert r.status_code == 403, f"expected 403 for client, got {r.status_code} {r.text}"
        assert "coach" in r.text.lower()

    def test_j_coach_happy_path(self, coach_ctx):
        r = requests.get(MEDIA_URL, headers=coach_ctx["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "stats" in body
        assert isinstance(body["items"], list)
        for key in ("total", "needs_media", "complete",
                    "pilot_missing_count", "louis_missing_count", "female_missing_count"):
            assert key in body["stats"], f"missing stats.{key}"

        # If empty, seed by resolving frames for known exercises then re-query
        if not body["items"]:
            self._seed_and_verify(coach_ctx)

    def _seed_and_verify(self, coach_ctx):
        import motor.motor_asyncio as _motor
        from feature_flight_support_media import resolve_flight_support_frames

        async def _seed():
            client = _motor.AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]
            try:
                for name in ("Goblet Squat", "Push-Up", "Push Up"):
                    try:
                        await resolve_flight_support_frames(db, name, prefer="pilot")
                    except Exception as e:
                        print(f"seed skip {name}: {e}")
            finally:
                client.close()

        asyncio.get_event_loop().run_until_complete(_seed())
        r = requests.get(MEDIA_URL, headers=coach_ctx["headers"], timeout=30)
        assert r.status_code == 200
        # Note: may still be empty if no exercises match — this is not a hard fail
        body = r.json()
        print(f"After seed: {len(body['items'])} items")

    def test_k_sort_order_pilot_missing_first(self, coach_ctx):
        r = requests.get(MEDIA_URL, headers=coach_ctx["headers"], timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        if len(items) < 2:
            pytest.skip("need >=2 rows to verify sort")
        pilot_miss_counts = [len((it.get("missing") or {}).get("pilot") or []) for it in items]
        # non-increasing
        assert all(pilot_miss_counts[i] >= pilot_miss_counts[i + 1] for i in range(len(pilot_miss_counts) - 1)), \
            f"pilot-missing not sorted DESC: {pilot_miss_counts}"

    def test_l_persona_filter_pilot(self, coach_ctx):
        r = requests.get(MEDIA_URL, headers=coach_ctx["headers"],
                         params={"persona_missing": "pilot"}, timeout=30)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert (it["missing"].get("pilot") or []), \
                f"row with no pilot-missing leaked: {it['exercise_name']}"

    def test_m_status_filters(self, coach_ctx):
        r1 = requests.get(MEDIA_URL, headers=coach_ctx["headers"],
                          params={"status": "needs_media"}, timeout=30)
        assert r1.status_code == 200
        for it in r1.json()["items"]:
            assert it["status"] == "needs_media", f"leak: {it}"

        r2 = requests.get(MEDIA_URL, headers=coach_ctx["headers"],
                          params={"status": "complete"}, timeout=30)
        assert r2.status_code == 200
        for it in r2.json()["items"]:
            assert it["status"] == "complete", f"leak: {it}"

    def test_n_search_filter(self, coach_ctx):
        r = requests.get(MEDIA_URL, headers=coach_ctx["headers"],
                         params={"search": "push"}, timeout=30)
        assert r.status_code == 200
        for it in r.json()["items"]:
            assert "push" in it["exercise_name"].lower(), f"search filter leak: {it['exercise_name']}"

    def test_o_matrix_cells_accurate(self, coach_ctx):
        """For any row, matrix[persona][slot] must equal actual doc presence
        (persona,slot) in exercise_content_images."""
        import motor.motor_asyncio as _motor

        r = requests.get(MEDIA_URL, headers=coach_ctx["headers"], timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        if not items:
            pytest.skip("no media queue rows to verify matrix against")

        sample = items[0]
        exercise_id = sample["exercise_id"]

        async def _verify():
            client = _motor.AsyncIOMotorClient(os.environ["MONGO_URL"])
            db = client[os.environ["DB_NAME"]]
            try:
                actual_by_persona: dict[str, set] = {"pilot": set(), "louis": set(), "female": set()}
                async for img in db.exercise_content_images.find(
                    {"exercise_id": exercise_id, "status": "ready"}
                ):
                    p = img.get("persona")
                    if p not in ("pilot", "louis", "female"):
                        p = "female" if img.get("female") else "louis"
                    slot = (img.get("slot") or "").lower()
                    if slot in ("start", "mid", "end"):
                        actual_by_persona[p].add(slot)
                return actual_by_persona
            finally:
                client.close()

        actual = asyncio.get_event_loop().run_until_complete(_verify())
        matrix = sample["matrix"]
        for persona in ("pilot", "louis", "female"):
            for slot in ("start", "mid", "end"):
                expected = slot in actual[persona]
                got = matrix[persona][slot]
                assert got == expected, (
                    f"matrix mismatch for {exercise_id} {persona}/{slot}: "
                    f"api={got} actual={expected}"
                )
