"""
feature_v2_p8_progression — V2 Phase 8: Progression states + Performance records.

Tracks per-objective progression state, feeds forward per-exercise load memory,
and computes next-prescription deltas per progression_model.

Ships behind `v2_flags.progression_v2_enabled`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, current_user, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg, emit_metric
)

FLAG = "progression_v2_enabled"


# ---------------------------------------------------------------------------
# Deterministic progression rules
# ---------------------------------------------------------------------------

def _next_deltas_linear_load(state: dict, latest_rpe_avg: float) -> dict:
    """If last session RPE avg ≤ 7, +2.5% load; if ≥ 9, -5% load; else hold."""
    if latest_rpe_avg <= 7.0:
        return {"load_delta_pct": 0.025}
    if latest_rpe_avg >= 9.0:
        return {"load_delta_pct": -0.05}
    return {"load_delta_pct": 0.0}


def _next_deltas_double_progression(state: dict, reps_last_max: int) -> dict:
    """If reps_last hit top of range → +2.5% load next; else +1 rep."""
    if reps_last_max >= 12:
        return {"load_delta_pct": 0.025, "reps_delta": -3}   # reset reps window
    return {"reps_delta": +1}


def _next_deltas_polarised(state: dict, adherence_pct: float) -> dict:
    """If adherence ≥ 80% for 2 weeks, +5% km on long_run; else hold."""
    if adherence_pct >= 0.8:
        return {"km_delta": 0.05}
    return {"km_delta": 0.0}


def _next_deltas_race_km_curve(state: dict, weeks_to_race: Optional[int]) -> dict:
    """Simple race-anchored curve — grow ~10% per week until 3 weeks out; taper."""
    if weeks_to_race is None:
        return {"km_delta": 0.05}
    if weeks_to_race <= 1:
        return {"km_delta": -0.5}
    if weeks_to_race <= 3:
        return {"km_delta": -0.2}
    return {"km_delta": 0.10}


# ---------------------------------------------------------------------------
# Submit performance
# ---------------------------------------------------------------------------

class ExerciseRecord(BaseModel):
    exercise_id: str
    sets_completed: int
    reps_per_set: list[int] = []
    load_per_set_kg: list[float] = []
    rpe_per_set: list[float] = []
    duration_sec: Optional[int] = None
    distance_m: Optional[int] = None
    pace_sec_per_km: Optional[int] = None
    notes: Optional[str] = None


class PerformanceBody(BaseModel):
    assignment_id: str
    session_rpe: Optional[float] = None
    perceived_difficulty: Optional[int] = None
    session_notes: str = ""
    session_completion_pct: Optional[float] = None
    substitutions_used: list[dict] = []
    exercise_records: list[ExerciseRecord] = []


@api.post("/v2/client/plan/performance")
async def performance_submit_client(
    body: PerformanceBody, user: dict = Depends(current_user)
) -> dict:
    if user.get("role") != "client":
        raise HTTPException(403, "Client-only endpoint")
    return await _submit(user["id"], body, actor="client")


@api.post("/v2/coach/clients/{client_id}/plan/performance")
async def performance_submit_coach(
    client_id: str, body: PerformanceBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    return await _submit(client_id, body, actor="coach")


async def _submit(client_id: str, body: PerformanceBody, actor: str) -> dict:
    a = await db.workout_assignments.find_one(
        {"id": body.assignment_id, "client_id": client_id}, {"_id": 0}
    )
    if not a:
        raise HTTPException(404, "Assignment not found")
    exposure = await db.objective_exposures.find_one(
        {"assignment_id": a["id"]}, {"_id": 0}
    )
    if not exposure:
        raise HTTPException(404, "Exposure not found for this assignment")
    impl_id = a.get("live_implementation_id") or a.get("draft_implementation_id")

    prid = new_id()
    doc = {
        "id": prid,
        "client_id": client_id,
        "assignment_id": a["id"],
        "implementation_id": impl_id,
        "exposure_id": exposure["id"],
        "objective_id": a.get("objective_id"),
        "date": a["date"],
        "exercise_records": [er.model_dump() for er in (body.exercise_records or [])],
        "session_rpe": body.session_rpe,
        "perceived_difficulty": body.perceived_difficulty,
        "substitutions_used": body.substitutions_used,
        "session_completion_pct": body.session_completion_pct or 100.0,
        "session_notes": body.session_notes,
        "submitted_at": now_iso(),
    }
    await db.performance_records.insert_one(dict(doc))

    # Advance exposure
    completion_pct = float(body.session_completion_pct or 100.0)
    if completion_pct >= 50:
        new_expo_status = "completed"
    elif completion_pct > 0:
        new_expo_status = "in_progress"
    else:
        new_expo_status = "missed"
    await db.objective_exposures.update_one(
        {"id": exposure["id"]},
        {"$set": {"status": new_expo_status, "performance_record_id": prid, "updated_at": now_iso()}}
    )
    await db.workout_assignments.update_one(
        {"id": a["id"]},
        {"$set": {"status": "completed" if new_expo_status == "completed" else "in_progress",
                  "updated_at": now_iso()}}
    )

    # Update progression state for the objective
    await _update_progression_state(client_id, a.get("objective_id"), body)

    await write_decision(
        actor=actor, layer="CLIENT_COMPLETION", scope_kind="performance_record",
        scope_id=prid, client_id=client_id,
        outcome="APPLIED",
        reason=f"Performance recorded: completion {completion_pct:.0f}% · sRPE {body.session_rpe}",
    )
    await emit_metric("session_completed", client_id=client_id, numeric_value=completion_pct,
                      labels={"objective_id": a.get("objective_id") or ""})
    doc.pop("_id", None)
    return doc


async def _update_progression_state(
    client_id: str, objective_id: Optional[str], perf: PerformanceBody
) -> None:
    if not objective_id:
        return
    obj = await db.training_objectives.find_one({"id": objective_id}, {"_id": 0})
    if not obj:
        return
    model = obj.get("progression_model") or "linear_load"

    # Aggregate stats from perf
    all_rpes = [r for er in perf.exercise_records for r in (er.rpe_per_set or [])]
    rpe_avg = sum(all_rpes) / len(all_rpes) if all_rpes else (perf.session_rpe or 7.0)
    reps_max = max([max(er.reps_per_set or [0]) for er in perf.exercise_records] or [0])

    state = await db.progression_states.find_one({"client_id": client_id, "objective_id": objective_id}, {"_id": 0})
    history_entry = {
        "date": now_iso(),
        "metric_snapshot": {"rpe_avg": rpe_avg, "reps_max": reps_max,
                            "session_completion_pct": perf.session_completion_pct or 100.0},
        "outcome": "completed",
    }

    if model == "linear_load":
        deltas = _next_deltas_linear_load(state or {}, rpe_avg)
    elif model == "double_progression":
        deltas = _next_deltas_double_progression(state or {}, reps_max)
    elif model == "polarised":
        deltas = _next_deltas_polarised(state or {}, (perf.session_completion_pct or 100.0) / 100.0)
    elif model == "race_km_curve":
        deltas = _next_deltas_race_km_curve(state or {}, None)
    else:
        deltas = {}

    label = "progressing_well"
    if rpe_avg >= 9:      label = "reduce_load"
    elif rpe_avg <= 6.5:  label = "maintain"

    if state:
        await db.progression_states.update_one(
            {"id": state["id"]},
            {"$set": {"next_prescription_deltas": deltas, "status_label": label,
                       "current_metric_snapshot": history_entry["metric_snapshot"],
                       "updated_at": now_iso()},
             "$push": {"history": history_entry}}
        )
    else:
        await db.progression_states.insert_one({
            "id": new_id(),
            "client_id": client_id,
            "objective_id": objective_id,
            "discipline": obj.get("discipline"),
            "current_metric_snapshot": history_entry["metric_snapshot"],
            "history": [history_entry],
            "next_prescription_deltas": deltas,
            "status_label": label,
            "reason": f"model={model}",
            "updated_at": now_iso(),
        })


@api.get("/v2/coach/clients/{client_id}/progression-states")
async def progression_list(
    client_id: str, objective_id: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if objective_id: q["objective_id"] = objective_id
    rows = await db.progression_states.find(q, {"_id": 0}).to_list(200)
    return {"progression_states": rows}


@api.get("/v2/coach/clients/{client_id}/performance-records")
async def performance_list(
    client_id: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if from_date or to_date:
        q["date"] = {}
        if from_date: q["date"]["$gte"] = from_date
        if to_date:   q["date"]["$lte"] = to_date
    rows = await db.performance_records.find(q, {"_id": 0}).sort("date", -1).to_list(200)
    return {"performance_records": rows}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("progression_states", [
        ([("client_id", 1), ("objective_id", 1)], True, "prog_client_obj_unique"),
    ])
    await ensure_indexes("performance_records", [
        ([("client_id", 1), ("date", -1)], False, "perf_client_date"),
        ([("exposure_id", 1)], False, "perf_expo"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p8_progression: /api/v2 performance + progression endpoints registered")
