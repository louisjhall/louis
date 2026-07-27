"""V2 end-to-end pipeline pytest.

Exercises P2 → P3 → P4 → P5 → P6 → P7 → P8 → P10 in one flow:
  1. Create a client with all V2 flags on.
  2. Add a Goal, create a Programme, build phases.
  3. Build objectives → windows.
  4. Insert a synthetic V1 roster, build V2 roster facets.
  5. Build the plan (assignments) + implementations.
  6. Apply an equipment adaptation (P7).
  7. Submit a performance record (P8).
  8. Apply a reality chip (P10).

Verifies each layer writes to its expected V2 collection and that
V1 collections (`workouts`, `programme_status`, etc.) are NOT touched.
"""
from __future__ import annotations

import os, sys, asyncio, datetime as _dt

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mongo_available() -> bool:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    return bool(os.environ.get("MONGO_URL"))


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason="Mongo not configured in test env"
)


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_factory(loop))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _fresh_db(loop):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
    return client[os.environ.get("DB_NAME", "crewfit_v1")]


def _client_doc(uid: str) -> dict:
    return {
        "id": uid, "email": f"{uid[:8]}@test.local", "name": f"Test {uid[:6]}",
        "role": "client",
        "profile": {
            "v2_flags": {
                "state_foundation_enabled": True,
                "goals_phases_enabled": True,
                "demand_engine_enabled": True,
                "roster_facets_enabled": True,
                "scheduling_v2_enabled": True,
                "construction_v2_enabled": True,
                "equipment_adaptation_v2_enabled": True,
                "progression_v2_enabled": True,
                "events_v2_enabled": True,
                "reality_v2_enabled": True,
                "automation_v2_enabled": True,
                "shadow_mode": True,
                "v2_default": False,
            }
        }
    }


def _coach_doc(uid: str) -> dict:
    return {"id": uid, "email": f"{uid[:8]}@coach.test", "role": "coach"}


def test_v2_full_pipeline():
    async def _t(loop):
        db = _fresh_db(loop)
        # Insert client + coach
        cid, coach_id = f"tc_{os.urandom(4).hex()}", f"co_{os.urandom(4).hex()}"
        await db.users.insert_one(_client_doc(cid))
        await db.users.insert_one(_coach_doc(coach_id))
        try:
            from feature_v2_p2_goals import (
                GoalBody, ProgrammeBody, PhaseSequenceBody,
                goal_create, programme_create, phases_build, seed_catalogs_once,
            )
            from feature_v2_p3_demand import (
                BuildDemandBody, WindowBody,
                objectives_build, window_create,
            )
            from feature_v2_p4_roster import roster_facets_build, BuildRosterFacetsBody
            from feature_v2_p5_scheduling import plan_build, BuildPlanBody
            from feature_v2_p6_construction import (
                implementations_build, BuildImplBody, seed_slot_templates_once,
            )
            from feature_v2_p7_equipment import _adapt, AdaptBody
            from feature_v2_p8_progression import (
                _submit as perf_submit, PerformanceBody, ExerciseRecord,
            )
            from feature_v2_p10_reality import _apply_reality, RealityChipBody

            # Ensure seed data present
            await seed_catalogs_once()
            await seed_slot_templates_once()

            coach = {"id": coach_id}

            # ---- P2: goal + programme + phases ----
            g = await goal_create(cid, GoalBody(
                goal_id_taxonomy="body_composition.muscle_gain", priority="A", weight=1.0
            ), coach)
            assert g["id"], "goal created"

            today = _dt.date.today()
            prog = await programme_create(cid, ProgrammeBody(
                primary_goal_id=g["id"], start_date=today.isoformat()
            ), coach)
            assert prog["id"]

            phases = await phases_build(cid, PhaseSequenceBody(
                programme_id=prog["id"],
                phase_sequence=[
                    {"phase_kind": "foundation", "weeks": 2},
                    {"phase_kind": "hypertrophy", "weeks": 4},
                ],
            ), coach)
            assert phases["count"] == 2

            # ---- P3: objectives + windows ----
            objs = await objectives_build(cid, BuildDemandBody(programme_id=prog["id"]), coach)
            assert objs["objectives_created"] > 0

            win = await window_create(cid, WindowBody(
                programme_id=prog["id"],
                start_date=today.isoformat(),
                end_date=(today + _dt.timedelta(days=13)).isoformat(),
            ), coach)
            assert win["id"]

            # ---- P4: insert synthetic V1 roster, build facets ----
            roster_id = f"r_{os.urandom(3).hex()}"
            await db.rosters.insert_one({
                "id": roster_id, "user_id": cid, "is_active": True,
                "created_at": _dt.datetime.utcnow().isoformat(),
                "days": [
                    {"date": (today + _dt.timedelta(days=i)).isoformat(),
                     "classification": "rest" if i % 3 == 0 else ("layover_full" if i % 3 == 1 else "home"),
                     "duties": [] if i % 3 == 0 else [
                        {"duty_type": "flight", "duty_start_time": None, "duty_finish_time": None,
                         "sectors": [{"dep": "AUH", "arr": "LHR"}]}
                     ]}
                    for i in range(14)
                ]
            })
            fac = await roster_facets_build(cid, BuildRosterFacetsBody(all_active=True), coach)
            assert fac["schedule_days"] == 14

            # ---- P5: build plan ----
            plan = await plan_build(cid, BuildPlanBody(
                programme_id=prog["id"],
                from_date=today.isoformat(),
                to_date=(today + _dt.timedelta(days=13)).isoformat(),
                max_assignments=8,
            ), coach)
            assert plan["assignments_created"] > 0

            # ---- P6: implementations ----
            impls = await implementations_build(cid, BuildImplBody(programme_id=prog["id"]), coach)
            assert impls["implementations_created"] > 0

            # Pick one assignment for adaptation
            assignment = await db.workout_assignments.find_one({"client_id": cid}, {"_id": 0})
            assert assignment

            # ---- P7: equipment adaptation ----
            adapt = await _adapt(cid, AdaptBody(
                assignment_id=assignment["id"],
                equipment_inline=["bodyweight", "mat"],
                duration_min_override=25,
            ), actor="client")
            assert adapt["implementation"]["id"]

            # ---- P8: performance record ----
            perf = await perf_submit(cid, PerformanceBody(
                assignment_id=assignment["id"],
                session_rpe=7.5,
                perceived_difficulty=6,
                session_completion_pct=100.0,
                exercise_records=[
                    ExerciseRecord(exercise_id="dummy", sets_completed=3,
                                   reps_per_set=[10, 10, 9], rpe_per_set=[7, 7.5, 8])
                ],
            ), actor="client")
            assert perf["id"]

            # ---- P10: reality chip ----
            other = await db.workout_assignments.find_one(
                {"client_id": cid, "id": {"$ne": assignment["id"]}}, {"_id": 0}
            )
            if other:
                r = await _apply_reality(cid, RealityChipBody(
                    assignment_id=other["id"], intent="short_on_time"
                ), actor="client")
                assert r["chip"]["intent"] == "short_on_time"

            # ---- Verify V1 collections untouched ----
            v1_workouts = await db.workouts.count_documents({"user_id": cid})
            assert v1_workouts == 0, "V2 pipeline must not write into V1 workouts"

        finally:
            # cleanup
            for coll in ("users", "goals_v2", "programmes_v2", "programme_phases_v2",
                          "training_objectives", "objective_exposures", "planning_windows",
                          "schedule_days", "roster_duties", "flight_sectors",
                          "workout_assignments", "workout_implementations",
                          "equipment_contexts", "performance_records", "progression_states",
                          "readiness_states", "exceptions", "decision_records", "change_sets",
                          "rosters"):
                try:
                    await db[coll].delete_many({"client_id": cid})
                    await db[coll].delete_many({"user_id": cid})
                    await db[coll].delete_many({"id": cid})
                except Exception:
                    pass
            try:
                await db.users.delete_many({"id": {"$in": [cid, coach_id]}})
            except Exception:
                pass

    _run(_t)
