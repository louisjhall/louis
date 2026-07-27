"""
feature_v2_p3_demand — V2 Phase 3: Training-demand engine (the WHAT layer).

Creates first-class TrainingObjective + ObjectiveExposure + PlanningWindow
entities and the demand engine that translates (Goal + Phase + timeline)
into a target exposure count.

Ships under /api/v2/*, gated by `v2_flags.demand_engine_enabled`.
Requires P2 (goals/phases) to be enabled on the client.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg
)

FLAG = "demand_engine_enabled"


# ---------------------------------------------------------------------------
# Demand engine core
# ---------------------------------------------------------------------------

def _weekly_target_from_goal(goal_def: dict, priority_weight: float) -> dict[str, int]:
    """Return {objective_kind: sessions_per_week} for a goal & priority weight.
    Draws on `key_stimuli` order (most important first) and `frequency_range`.
    """
    stims = list(goal_def.get("key_stimuli") or [])
    if not stims:
        return {}
    fr = goal_def.get("frequency_range") or {"min": 3, "max": 4}
    total = int(round(fr.get("min", 3) + priority_weight * (fr.get("max", fr.get("min", 3)) - fr.get("min", 3))))
    total = max(2, min(total, 7))
    # Distribute: primary stimulus gets weighted more.
    weights = [max(1.0, 3.0 - 0.4 * i) for i in range(len(stims))]
    ws = sum(weights)
    quotas = {}
    remaining = total
    for i, kind in enumerate(stims[:5]):
        share = int(round(total * (weights[i] / ws)))
        quotas[kind] = max(1, share)
        remaining -= quotas[kind]
    # Absorb rounding slack into primary stimulus
    if stims:
        quotas[stims[0]] = max(1, quotas.get(stims[0], 1) + remaining)
    return quotas


def _importance_for(kind: str, primary_kind: str) -> str:
    if kind == primary_kind:
        return "key"
    return "important"


class BuildDemandBody(BaseModel):
    programme_id: str
    weeks: int = Field(4, ge=1, le=16)


@api.post("/v2/coach/clients/{client_id}/objectives/build")
async def objectives_build(
    client_id: str, body: BuildDemandBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Materialise TrainingObjectives across every active phase of the programme,
    based on the primary goal's key_stimuli & frequency_range."""
    await require_client_and_flag(client_id, FLAG)
    prog = await db.programmes_v2.find_one(
        {"id": body.programme_id, "client_id": client_id}, {"_id": 0}
    )
    if not prog:
        raise HTTPException(404, "Programme not found")
    primary = await db.goals_v2.find_one(
        {"id": prog["primary_goal_id"], "client_id": client_id}, {"_id": 0}
    )
    if not primary:
        raise HTTPException(400, "Primary goal missing")
    goal_def = await db.goal_definitions.find_one(
        {"goal_id_taxonomy": primary["goal_id_taxonomy"]}, {"_id": 0}
    )
    if not goal_def:
        raise HTTPException(400, "GoalDefinition not found")
    phases = await db.programme_phases_v2.find(
        {"programme_id": body.programme_id, "client_id": client_id}, {"_id": 0}
    ).sort("ordinal", 1).to_list(50)
    if not phases:
        raise HTTPException(400, "Programme has no phases (P2 phases_build first)")

    # Wipe prior planned objectives + exposures for a clean rebuild
    old_obj_ids = [o["id"] async for o in db.training_objectives.find(
        {"programme_id": body.programme_id}, {"_id": 0, "id": 1})]
    if old_obj_ids:
        await db.training_objectives.delete_many({"id": {"$in": old_obj_ids}})
        await db.objective_exposures.delete_many({"objective_id": {"$in": old_obj_ids}})

    quotas = _weekly_target_from_goal(goal_def, float(primary.get("weight") or 1.0))
    primary_kind = (goal_def.get("key_stimuli") or [None])[0]
    created_objectives: list[dict] = []

    for phase in phases:
        # Filter quotas to phase's training_priorities where any overlap exists;
        # otherwise fall back to entire quota set.
        phase_priorities = set(phase.get("training_priorities") or [])
        allowed = {k: v for k, v in quotas.items() if not phase_priorities or k in phase_priorities}
        if not allowed:
            allowed = dict(quotas)

        # Compute phase span in weeks
        try:
            s = _dt.date.fromisoformat(phase["planned_start_date"])
            e = _dt.date.fromisoformat(phase["planned_end_date"])
            weeks_in_phase = max(1, ((e - s).days + 1) // 7)
        except Exception:
            weeks_in_phase = 4

        for kind, per_week in allowed.items():
            oid = new_id()
            target_total = per_week * weeks_in_phase
            doc = {
                "id": oid,
                "programme_id": body.programme_id,
                "client_id": client_id,
                "phase_id": phase["id"],
                "kind": kind,
                "discipline": _discipline_from_kind(kind),
                "target_exposures_in_phase": target_total,
                "target_exposures_per_window": per_week,
                "importance": _importance_for(kind, primary_kind),
                "slot_template_id": None,     # linked by P6 when template exists
                "progression_model": goal_def.get("progression_model") or "linear_load",
                "min_recovery_hours_after": 24 if kind in {"long_run", "tempo_run", "intervals_run"} else 24,
                "paired_with_other_objectives": [],
                "active_start_date": phase["planned_start_date"],
                "active_end_date": phase["planned_end_date"],
                "status": "planned",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
            await db.training_objectives.insert_one(dict(doc))
            # Pre-create N pending exposures per objective (sequence numbers monotonic)
            for seq in range(1, target_total + 1):
                await db.objective_exposures.insert_one({
                    "id": new_id(),
                    "objective_id": oid,
                    "programme_id": body.programme_id,
                    "client_id": client_id,
                    "sequence": seq,
                    "status": "pending",
                    "planning_window_id": None,
                    "assignment_id": None,
                    "implementation_id": None,
                    "performance_record_id": None,
                    "progression_state_snapshot": {},
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })
            doc.pop("_id", None)
            created_objectives.append(doc)

    await write_decision(
        actor="coach", layer="WHAT", scope_kind="programme", scope_id=body.programme_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Objectives built: {len(created_objectives)} across {len(phases)} phases; total quotas {quotas}",
    )
    return {"programme_id": body.programme_id, "objectives_created": len(created_objectives),
            "weekly_quota": quotas}


def _discipline_from_kind(kind: str) -> str:
    if kind.startswith(("push_", "pull_", "upper_", "lower_", "full_body_")): return "strength"
    if kind.startswith(("long_run", "tempo_run", "intervals_run", "easy_run", "z2_run", "swim", "z2_bike", "bike_", "long_bike", "brick", "run_")):
        if kind.startswith(("swim",)): return "swim"
        if kind.startswith(("bike_", "long_bike", "z2_bike", "easy_bike")): return "bike"
        if kind.startswith("brick"): return "brick"
        return "run"
    if kind == "mobility":       return "mobility"
    if kind == "recovery":       return "recovery"
    if kind == "strength_support": return "strength"
    return "conditioning"


# ---------------------------------------------------------------------------
# Planning windows (rolling 7-day / iso-week)
# ---------------------------------------------------------------------------

class WindowBody(BaseModel):
    programme_id: str
    kind: str = "iso_week"       # iso_week | rolling_7d
    start_date: str              # ISO
    end_date: Optional[str] = None
    anchor: str = "iso_monday"


@api.post("/v2/coach/clients/{client_id}/planning-windows")
async def window_create(
    client_id: str, body: WindowBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    try:
        sd = _dt.date.fromisoformat(body.start_date)
    except Exception:
        raise HTTPException(400, "Invalid start_date")
    ed = _dt.date.fromisoformat(body.end_date) if body.end_date else (sd + _dt.timedelta(days=6))
    if ed < sd:
        raise HTTPException(400, "end_date < start_date")

    # Compute target exposures from objectives active in window
    active_objectives = await db.training_objectives.find(
        {"programme_id": body.programme_id, "client_id": client_id,
         "active_start_date": {"$lte": ed.isoformat()},
         "active_end_date": {"$gte": sd.isoformat()}},
        {"_id": 0}
    ).to_list(200)

    target_exposures: list[dict] = []
    for obj in active_objectives:
        target_exposures.append({
            "objective_id": obj["id"],
            "kind": obj["kind"],
            "required": obj.get("target_exposures_per_window") or 1,
            "importance": obj.get("importance"),
        })

    wid = new_id()
    doc = {
        "id": wid,
        "programme_id": body.programme_id,
        "client_id": client_id,
        "kind": body.kind,
        "start_date": sd.isoformat(),
        "end_date": ed.isoformat(),
        "anchor": body.anchor,
        "target_exposures": target_exposures,
        "actual_exposures": [],
        "status": "active" if sd <= _dt.date.today() <= ed else ("upcoming" if sd > _dt.date.today() else "closed"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.planning_windows.insert_one(dict(doc))
    await write_decision(
        actor="coach", layer="WHAT", scope_kind="planning_window", scope_id=wid,
        client_id=client_id, outcome="APPLIED",
        reason=f"Planning window created {sd}..{ed} ({len(target_exposures)} target exposures)",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/planning-windows")
async def window_list(
    client_id: str, programme_id: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if programme_id:
        q["programme_id"] = programme_id
    rows = await db.planning_windows.find(q, {"_id": 0}).sort("start_date", -1).to_list(50)
    return {"planning_windows": rows}


@api.get("/v2/coach/clients/{client_id}/objectives")
async def objectives_list(
    client_id: str, programme_id: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if programme_id:
        q["programme_id"] = programme_id
    rows = await db.training_objectives.find(q, {"_id": 0}).sort("active_start_date", 1).to_list(500)
    return {"objectives": rows}


@api.get("/v2/coach/clients/{client_id}/objectives/{objective_id}/exposures")
async def exposures_list(
    client_id: str, objective_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    rows = await db.objective_exposures.find(
        {"objective_id": objective_id, "client_id": client_id}, {"_id": 0}
    ).sort("sequence", 1).to_list(1000)
    return {"exposures": rows}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("training_objectives", [
        ([("programme_id", 1), ("phase_id", 1)], False, "obj_prog_phase"),
        ([("kind", 1)], False, "obj_kind"),
        ([("client_id", 1), ("status", 1)], False, "obj_client_status"),
    ])
    await ensure_indexes("objective_exposures", [
        ([("objective_id", 1), ("sequence", 1)], True, "expo_obj_seq_unique"),
        ([("client_id", 1), ("status", 1)], False, "expo_client_status"),
        ([("assignment_id", 1)], False, "expo_assignment"),
    ])
    await ensure_indexes("planning_windows", [
        ([("programme_id", 1), ("start_date", 1)], False, "pw_prog_start"),
        ([("status", 1)], False, "pw_status"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p3_demand: /api/v2 objectives + exposures + planning windows registered")
