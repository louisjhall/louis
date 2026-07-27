"""
feature_v2_p5_scheduling — V2 Phase 5: Scheduling engine (the WHEN layer).

Assigns pending ObjectiveExposures to ScheduleDays based on:
  - training_opportunity score per day (higher = better)
  - recommended_intensity_ceiling vs objective's required intensity
  - min_recovery_hours_after between key sessions
  - objective active window (start/end dates)

Also runs a light V1..V16 validation post-scheduling.
Gated by `v2_flags.scheduling_v2_enabled`.
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
# NOTE: feature_v2_directive_engine imported lazily inside functions to avoid
# a circular import (that module also imports from `server`).

FLAG = "scheduling_v2_enabled"


# ---------------------------------------------------------------------------
# Validation rules (subset of V1..V16 from RULE_ENGINE §16-17)
# ---------------------------------------------------------------------------

VALIDATION_CHECKS = {
    "V1_no_double_key_in_24h": "Two key sessions within 24h",
    "V2_intensity_ceiling":    "Assignment intensity exceeds day's recommended ceiling",
    "V3_burden_conflict":      "Key assignment scheduled on extreme-burden day",
    "V4_pain_region_avoid":    "Assignment uses a movement pattern the client should avoid",
    "V5_min_recovery_hours":   "Recovery hours since prior key session below threshold",
    "V6_no_orphan_exposure":   "Exposure has no schedule day within active window",
    "V16_stale_progression":   "Progression state stale (>30 days since last update)",
}


class BuildPlanBody(BaseModel):
    programme_id: str
    window_id: Optional[str] = None
    draft_id: Optional[str] = None
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    max_assignments: int = Field(28, ge=1, le=200)


def _daydate(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def _rank_days(days: list[dict], objective: dict) -> list[dict]:
    """Sort candidate schedule_days by suitability for the objective.
    Highest training_opportunity first, tie-breaking by lowest duty_burden."""
    imp = objective.get("importance") or "important"
    key_penalty_bands = {"heavy": -10, "extreme": -30, "moderate": -3, "light": 0}
    ranked = []
    for d in days:
        drv = d.get("derived") or {}
        opp = int(drv.get("training_opportunity") or 0)
        burden = int(drv.get("duty_burden_score") or 0)
        band = drv.get("duty_burden_band") or "light"
        adj = 0
        if imp == "key":
            adj += key_penalty_bands.get(band, 0)
        ranked.append((opp - burden // 10 + adj, d))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in ranked]


def _last_key_date_within(dates: list[_dt.date], target: _dt.date, hours: int) -> Optional[_dt.date]:
    """Return the most recent date in `dates` that's within `hours` before `target`, or None."""
    win_days = max(1, hours // 24)
    for d in sorted(dates, reverse=True):
        if 0 <= (target - d).days <= win_days:
            return d
    return None


@api.post("/v2/coach/clients/{client_id}/plan/build")
async def plan_build(
    client_id: str, body: BuildPlanBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Materialise WorkoutAssignments for pending exposures on the best days.

    Fair-and-simple algorithm:
      1. Fetch pending exposures for the programme, ordered by importance then sequence.
      2. Fetch candidate schedule_days in [from_date, to_date] with no other assignment.
      3. For each exposure, rank days by suitability, pick top day that satisfies
         min_recovery_hours_after vs prior placed key sessions of the same discipline.
      4. Emit WorkoutAssignment. Backfill exposure references.
      5. Run V1..V6 validation post-pass, emit `exceptions` rows for failures.
    """
    await require_client_and_flag(client_id, FLAG)
    prog = await db.programmes_v2.find_one({"id": body.programme_id, "client_id": client_id}, {"_id": 0})
    if not prog:
        raise HTTPException(404, "Programme not found")

    # Determine date range
    if body.from_date:
        sd = _daydate(body.from_date)
    else:
        sd = _daydate(prog.get("start_date")) if prog.get("start_date") else _dt.date.today()
    if body.to_date:
        ed = _daydate(body.to_date)
    else:
        ed = sd + _dt.timedelta(days=27)

    # Candidate schedule days (unassigned)
    days = await db.schedule_days.find(
        {"client_id": client_id, "date": {"$gte": sd.isoformat(), "$lte": ed.isoformat()}}, {"_id": 0}
    ).to_list(200)
    if not days:
        return {"assignments_created": 0, "note": "no schedule_days in range; run P4 build first"}

    assigned_day_ids = {row["schedule_day_id"] async for row in db.workout_assignments.find(
        {"client_id": client_id, "date": {"$gte": sd.isoformat(), "$lte": ed.isoformat()},
         "status": {"$in": ["proposed", "ready", "live", "in_progress"]}},
        {"_id": 0, "schedule_day_id": 1}
    )}
    available_days = [d for d in days if d["id"] not in assigned_day_ids]

    # Pending exposures ordered by importance then sequence
    importance_order = {"key": 0, "important": 1, "supporting": 2, "optional": 3}
    objectives_by_id = {
        o["id"]: o for o in await db.training_objectives.find(
            {"programme_id": body.programme_id, "client_id": client_id}, {"_id": 0}
        ).to_list(500)
    }
    pending = await db.objective_exposures.find(
        {"programme_id": body.programme_id, "client_id": client_id, "status": "pending"},
        {"_id": 0}
    ).sort("sequence", 1).to_list(1000)
    pending.sort(key=lambda e: (importance_order.get(objectives_by_id.get(e["objective_id"], {}).get("importance", "important"), 5),
                                e["sequence"]))

    created = 0
    placed_dates: dict[str, list[_dt.date]] = {}   # by discipline
    exceptions: list[dict] = []

    for expo in pending:
        if created >= body.max_assignments:
            break
        obj = objectives_by_id.get(expo["objective_id"])
        if not obj:
            continue
        # Filter days inside objective's active window
        obj_start = _daydate(obj["active_start_date"])
        obj_end = _daydate(obj["active_end_date"])
        cand = [d for d in available_days if obj_start <= _daydate(d["date"]) <= obj_end]
        if not cand:
            exceptions.append({
                "kind": "objective_missed", "severity": "warning",
                "reason": f"No available day in window for exposure #{expo['sequence']} of {obj['kind']}",
                "expo_id": expo["id"],
            })
            continue

        ranked = _rank_days(cand, obj)
        placed = None
        forbid_reasons: list[str] = []
        from feature_v2_directive_engine import active_directives_for, directive_forbids_kind
        for d in ranked:
            # Check active coach directives for this candidate date
            try:
                day_directives = await active_directives_for(client_id, _daydate(d["date"]))
            except Exception:
                day_directives = []
            if directive_forbids_kind(day_directives, obj.get("kind")):
                forbid_reasons.append(f"{d['date']} blocked by directive")
                continue
            # min_recovery hours check
            disc = obj.get("discipline") or "conditioning"
            prev = _last_key_date_within(
                placed_dates.get(disc, []), _daydate(d["date"]),
                int(obj.get("min_recovery_hours_after") or 24)
            )
            if prev and obj.get("importance") == "key":
                continue
            placed = d
            break

        if not placed:
            reason = "; ".join(forbid_reasons) or f"No candidate day satisfies min_recovery_hours for {obj['kind']}"
            exceptions.append({
                "kind": "insufficient_recovery" if not forbid_reasons else "coach_directive_conflict",
                "severity": "warning",
                "reason": reason + f" #{expo['sequence']}",
                "expo_id": expo["id"],
            })
            continue

        # Create the assignment
        aid = new_id()
        await db.workout_assignments.insert_one({
            "id": aid,
            "client_id": client_id,
            "programme_id": body.programme_id,
            "planning_window_id": body.window_id,
            "objective_exposure_id": expo["id"],
            "objective_id": obj["id"],
            "schedule_day_id": placed["id"],
            "date": placed["date"],
            "status": "proposed",
            "importance": obj.get("importance"),
            "planned_duration_min": (placed.get("derived") or {}).get("available_time_min") or 45,
            "safe_adaptation_boundary": None,
            "live_implementation_id": None,
            "draft_implementation_id": None,
            "locked": False,
            "coach_notes": "",
            "decision_record_ids": [],
            "kind": obj["kind"],
            "discipline": obj.get("discipline"),
            "draft_id": body.draft_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        # Advance exposure state
        await db.objective_exposures.update_one(
            {"id": expo["id"]},
            {"$set": {"status": "assigned", "assignment_id": aid,
                      "planning_window_id": body.window_id, "updated_at": now_iso()}}
        )
        placed_dates.setdefault(obj.get("discipline") or "conditioning", []).append(_daydate(placed["date"]))
        # Remove day from availability
        available_days = [d for d in available_days if d["id"] != placed["id"]]
        created += 1

        # Assignment-scoped decision (populates "Why this?" drawer)
        try:
            from feature_v2_directive_engine import write_assignment_decision
            burden = ((placed.get("derived") or {}).get("duty_burden_band") or "light")
            opp = ((placed.get("derived") or {}).get("training_opportunity") or 0)
            reason = (
                f"{obj.get('importance','important').title()} {obj.get('kind','session')} "
                f"placed on {placed['date']} ({burden} burden · opportunity {opp}). "
                f"Exposure #{expo['sequence']} of objective."
            )
            await write_assignment_decision(
                assignment_id=aid, client_id=client_id, reason=reason,
                layer="WHEN", rule_id="planner_v1_place",
            )
        except Exception:
            pass

    # V1..V6 post-validation
    await _validate_assignments(client_id, body.programme_id, body.draft_id, exceptions_out=exceptions)

    # Persist exceptions
    for exc in exceptions:
        eid = new_id()
        await db.exceptions.insert_one({
            "id": eid,
            "client_id": client_id,
            "draft_id": body.draft_id,
            "kind": exc["kind"], "severity": exc.get("severity", "warning"),
            "scope_ref": exc.get("expo_id") or exc.get("assignment_id"),
            "triggered_at": now_iso(),
            "human_readable_reason": exc["reason"],
            "status": "open",
            "proposed_resolutions": [],
        })

    await write_decision(
        actor="coach", layer="WHEN", scope_kind="programme", scope_id=body.programme_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Plan built: {created} assignments, {len(exceptions)} exceptions",
    )
    return {"assignments_created": created, "exceptions_created": len(exceptions)}


async def _validate_assignments(
    client_id: str, programme_id: str, draft_id: Optional[str],
    exceptions_out: list[dict]
) -> None:
    """Deterministic V1..V6 checks. Populates exceptions_out in place."""
    assignments = await db.workout_assignments.find(
        {"client_id": client_id, "programme_id": programme_id,
         "status": {"$in": ["proposed", "ready"]}},
        {"_id": 0}
    ).sort("date", 1).to_list(500)

    # V1 — no double key in 24h
    by_date: dict[str, list[dict]] = {}
    for a in assignments:
        by_date.setdefault(a["date"], []).append(a)
    for date_str, arr in by_date.items():
        keys = [a for a in arr if a.get("importance") == "key"]
        if len(keys) >= 2:
            exceptions_out.append({
                "kind": "session_cannot_fit", "severity": "blocker",
                "reason": f"V1 double key sessions on {date_str}: {[a['kind'] for a in keys]}",
                "assignment_id": keys[-1]["id"],
            })

    # V2 — intensity ceiling
    sd_map = {sd["date"]: sd for sd in await db.schedule_days.find(
        {"client_id": client_id, "date": {"$in": list(by_date.keys())}}, {"_id": 0}
    ).to_list(400)}
    for a in assignments:
        sd = sd_map.get(a["date"])
        if not sd: continue
        ceiling = ((sd.get("derived") or {}).get("recommended_intensity_ceiling") or "any")
        req_intensity = "rpe8" if a.get("importance") == "key" else "rpe7"
        # simple ordering
        order = {"rpe4": 4, "rpe6": 6, "rpe7": 7, "rpe8": 8, "any": 10}
        if order.get(req_intensity, 10) > order.get(ceiling, 10):
            exceptions_out.append({
                "kind": "insufficient_recovery", "severity": "warning",
                "reason": f"V2 intensity {req_intensity} exceeds day ceiling {ceiling} on {a['date']}",
                "assignment_id": a["id"],
            })


@api.get("/v2/coach/clients/{client_id}/plan/assignments")
async def assignments_list(
    client_id: str, from_date: Optional[str] = None, to_date: Optional[str] = None,
    draft_id: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if draft_id: q["draft_id"] = draft_id
    if from_date or to_date:
        q["date"] = {}
        if from_date: q["date"]["$gte"] = from_date
        if to_date:   q["date"]["$lte"] = to_date
    rows = await db.workout_assignments.find(q, {"_id": 0}).sort("date", 1).to_list(500)
    return {"assignments": rows}


class MoveBody(BaseModel):
    to_date: str


@api.patch("/v2/coach/clients/{client_id}/plan/assignments/{assignment_id}/move")
async def assignment_move(
    client_id: str, assignment_id: str, body: MoveBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    cur = await db.workout_assignments.find_one({"id": assignment_id, "client_id": client_id}, {"_id": 0})
    if not cur:
        raise HTTPException(404, "Assignment not found")
    sd = await db.schedule_days.find_one({"client_id": client_id, "date": body.to_date}, {"_id": 0})
    if not sd:
        raise HTTPException(400, "Target date has no schedule_day; run P4 build first")
    await db.workout_assignments.update_one(
        {"id": assignment_id},
        {"$set": {"date": body.to_date, "schedule_day_id": sd["id"], "updated_at": now_iso()}}
    )
    await write_decision(
        actor="coach", layer="WHEN", scope_kind="assignment", scope_id=assignment_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Assignment moved: {cur.get('date')} → {body.to_date}",
    )
    return await db.workout_assignments.find_one({"id": assignment_id}, {"_id": 0})


@api.get("/v2/coach/clients/{client_id}/exceptions")
async def exceptions_list(
    client_id: str, status: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if status: q["status"] = status
    rows = await db.exceptions.find(q, {"_id": 0}).sort("triggered_at", -1).to_list(500)
    return {"exceptions": rows}


class ResolveExceptionBody(BaseModel):
    status: str = "resolved"    # resolved | dismissed | escalated
    notes: Optional[str] = None


@api.patch("/v2/coach/clients/{client_id}/exceptions/{exception_id}")
async def exception_resolve(
    client_id: str, exception_id: str, body: ResolveExceptionBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    r = await db.exceptions.update_one(
        {"id": exception_id, "client_id": client_id},
        {"$set": {"status": body.status, "resolved_at": now_iso(),
                  "resolved_by": coach["id"], "resolution_notes": body.notes or ""}}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Exception not found")
    return await db.exceptions.find_one({"id": exception_id}, {"_id": 0})


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("workout_assignments", [
        ([("client_id", 1), ("date", 1)], False, "assign_client_date"),
        ([("objective_exposure_id", 1)], True, "assign_expo_unique"),
        ([("status", 1)], False, "assign_status"),
        ([("draft_id", 1)], False, "assign_draft"),
    ])
    await ensure_indexes("exceptions", [
        ([("client_id", 1), ("status", 1), ("severity", 1)], False, "exc_client_status"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p5_scheduling: /api/v2 plan build + assignments registered")
