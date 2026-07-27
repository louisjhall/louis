"""
feature_v2_p2_goals — V2 Phase 2: Goals + Timelines + Phases.

Introduces the new first-class Goal + Programme + ProgrammePhase entities,
plus admin-facing catalogs (GoalDefinition / PhaseDefinition) that back
the timeline classifier and phase machine.

All endpoints under /api/v2/*. Gated by `v2_flags.goals_phases_enabled`.
Zero impact on V1 (`users.profile.main_goal_key`, etc. remain untouched).
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional, Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, validator

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag,
    write_decision,
    ensure_indexes,
    bg,
)

FLAG = "goals_phases_enabled"

# ---------------------------------------------------------------------------
# Catalogs — GoalDefinition + PhaseDefinition
# ---------------------------------------------------------------------------
# Seed set is small but covers the core taxonomy from the RULE_ENGINE spec.
# Coach can extend without redeploying by writing catalog rows directly.

_GOAL_DEFINITIONS_SEED = [
    {
        "goal_id_taxonomy": "body_composition.fat_loss",
        "label": "Fat loss",
        "discipline_bias": {"strength": 0.4, "run": 0.3, "mobility": 0.2, "recovery": 0.1},
        "priority_adaptations": ["strength", "aerobic_base", "mobility"],
        "frequency_range": {"min": 3, "max": 5},
        "volume_curve": "linear",
        "intensity_curve": "linear",
        "key_stimuli": ["full_body_strength", "z2_run", "z2_bike", "mobility"],
        "progression_model": "linear_load",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 1, "weekly_deload_frequency": None},
        "compatible_phase_sequence": ["foundation", "build", "maintenance"],
        "ideal_prep_weeks": None,
        "standard_prep_weeks": None,
        "compressed_prep_weeks": None,
        "event_types_that_qualify": [],
    },
    {
        "goal_id_taxonomy": "body_composition.muscle_gain",
        "label": "Muscle gain",
        "discipline_bias": {"strength": 0.75, "mobility": 0.15, "recovery": 0.10},
        "priority_adaptations": ["hypertrophy", "strength"],
        "frequency_range": {"min": 3, "max": 5},
        "volume_curve": "undulating",
        "intensity_curve": "undulating",
        "key_stimuli": ["push_strength", "pull_strength", "lower_strength", "upper_hypertrophy", "lower_hypertrophy"],
        "progression_model": "double_progression",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 0, "weekly_deload_frequency": 4},
        "compatible_phase_sequence": ["foundation", "hypertrophy", "strength", "peak", "recovery"],
        "ideal_prep_weeks": None,
        "standard_prep_weeks": None,
        "compressed_prep_weeks": None,
        "event_types_that_qualify": [],
    },
    {
        "goal_id_taxonomy": "strength.general",
        "label": "General strength",
        "discipline_bias": {"strength": 0.85, "mobility": 0.15},
        "priority_adaptations": ["strength", "hypertrophy"],
        "frequency_range": {"min": 3, "max": 4},
        "volume_curve": "block",
        "intensity_curve": "block",
        "key_stimuli": ["push_strength", "pull_strength", "lower_strength"],
        "progression_model": "linear_load",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 0, "weekly_deload_frequency": 4},
        "compatible_phase_sequence": ["foundation", "hypertrophy", "strength", "peak", "recovery"],
        "ideal_prep_weeks": None, "standard_prep_weeks": None, "compressed_prep_weeks": None,
        "event_types_that_qualify": [],
    },
    {
        "goal_id_taxonomy": "running.5k",
        "label": "Run a 5K",
        "discipline_bias": {"run": 0.8, "strength": 0.1, "mobility": 0.1},
        "priority_adaptations": ["aerobic_base", "threshold", "VO2", "race_specific"],
        "frequency_range": {"min": 3, "max": 5},
        "volume_curve": "race_anchored",
        "intensity_curve": "race_anchored",
        "key_stimuli": ["easy_run", "tempo_run", "intervals_run", "long_run"],
        "progression_model": "race_km_curve",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 1, "weekly_deload_frequency": 4},
        "compatible_phase_sequence": ["aerobic_base", "build", "specific_prep", "peak", "taper", "race_week", "recovery"],
        "ideal_prep_weeks": 10, "standard_prep_weeks": 8, "compressed_prep_weeks": 5,
        "event_types_that_qualify": ["run_5k", "5k"],
    },
    {
        "goal_id_taxonomy": "running.10k",
        "label": "Run a 10K",
        "discipline_bias": {"run": 0.8, "strength": 0.1, "mobility": 0.1},
        "priority_adaptations": ["aerobic_base", "threshold", "VO2", "race_specific"],
        "frequency_range": {"min": 3, "max": 5},
        "volume_curve": "race_anchored", "intensity_curve": "race_anchored",
        "key_stimuli": ["long_run", "tempo_run", "intervals_run", "easy_run"],
        "progression_model": "race_km_curve",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 1, "weekly_deload_frequency": 4},
        "compatible_phase_sequence": ["aerobic_base", "build", "specific_prep", "peak", "taper", "race_week", "recovery"],
        "ideal_prep_weeks": 12, "standard_prep_weeks": 10, "compressed_prep_weeks": 6,
        "event_types_that_qualify": ["run_10k", "10k"],
    },
    {
        "goal_id_taxonomy": "running.half_marathon",
        "label": "Half marathon",
        "discipline_bias": {"run": 0.75, "strength": 0.15, "mobility": 0.10},
        "priority_adaptations": ["aerobic_base", "threshold", "VO2", "race_specific"],
        "frequency_range": {"min": 4, "max": 6},
        "volume_curve": "race_anchored", "intensity_curve": "race_anchored",
        "key_stimuli": ["long_run", "tempo_run", "intervals_run", "easy_run", "strength_support"],
        "progression_model": "race_km_curve",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 1, "weekly_deload_frequency": 4},
        "compatible_phase_sequence": ["aerobic_base", "build", "specific_prep", "peak", "taper", "race_week", "recovery"],
        "ideal_prep_weeks": 14, "standard_prep_weeks": 12, "compressed_prep_weeks": 8,
        "event_types_that_qualify": ["half_marathon", "hm"],
    },
    {
        "goal_id_taxonomy": "running.marathon",
        "label": "Marathon",
        "discipline_bias": {"run": 0.75, "strength": 0.15, "mobility": 0.10},
        "priority_adaptations": ["aerobic_base", "threshold", "VO2", "race_specific"],
        "frequency_range": {"min": 4, "max": 6},
        "volume_curve": "race_anchored", "intensity_curve": "race_anchored",
        "key_stimuli": ["long_run", "tempo_run", "intervals_run", "easy_run", "strength_support"],
        "progression_model": "race_km_curve",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 1, "weekly_deload_frequency": 4},
        "compatible_phase_sequence": ["aerobic_base", "build", "specific_prep", "peak", "taper", "race_week", "recovery"],
        "ideal_prep_weeks": 16, "standard_prep_weeks": 12, "compressed_prep_weeks": 8,
        "event_types_that_qualify": ["marathon"],
    },
    {
        "goal_id_taxonomy": "triathlon.70_3",
        "label": "Ironman 70.3",
        "discipline_bias": {"run": 0.35, "bike": 0.40, "swim": 0.15, "strength": 0.10},
        "priority_adaptations": ["aerobic_base", "threshold", "brick_capacity", "race_specific"],
        "frequency_range": {"min": 5, "max": 7},
        "volume_curve": "race_anchored", "intensity_curve": "race_anchored",
        "key_stimuli": ["long_run", "long_bike", "brick", "swim_aerobic", "tempo_run", "bike_intervals"],
        "progression_model": "race_km_curve",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 1, "weekly_deload_frequency": 4},
        "compatible_phase_sequence": ["aerobic_base", "build", "specific_prep", "peak", "taper", "race_week", "recovery"],
        "ideal_prep_weeks": 20, "standard_prep_weeks": 16, "compressed_prep_weeks": 12,
        "event_types_that_qualify": ["ironman_70_3", "70.3"],
    },
    {
        "goal_id_taxonomy": "general.longevity",
        "label": "Longevity / general health",
        "discipline_bias": {"strength": 0.4, "run": 0.25, "mobility": 0.25, "recovery": 0.10},
        "priority_adaptations": ["strength", "aerobic_base", "mobility"],
        "frequency_range": {"min": 3, "max": 5},
        "volume_curve": "maintenance", "intensity_curve": "maintenance",
        "key_stimuli": ["full_body_strength", "z2_run", "mobility"],
        "progression_model": "linear_load",
        "recovery_requirements": {"min_hours_between_key": 48, "min_easy_days_after_key": 0, "weekly_deload_frequency": None},
        "compatible_phase_sequence": ["foundation", "maintenance"],
        "ideal_prep_weeks": None, "standard_prep_weeks": None, "compressed_prep_weeks": None,
        "event_types_that_qualify": [],
    },
]

_PHASE_DEFINITIONS_SEED = [
    # Non-endurance
    {"phase_kind": "foundation",   "duration_weeks_range": {"min": 3, "max": 4},
     "training_priorities": ["full_body_strength", "mobility", "z2_run"],
     "volume_bias": "moderate", "intensity_bias": "low", "fatigue_tolerance": "high",
     "entry_criteria": [], "exit_criteria": [
         {"kind": "timeline", "parameters": {"min_weeks": 3}, "required": True},
         {"kind": "adherence", "parameters": {"min_pct": 0.65}, "required": False},
     ],
     "exercise_selection_bias": {"prefer_compound": True, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "hypertrophy",  "duration_weeks_range": {"min": 4, "max": 6},
     "training_priorities": ["upper_hypertrophy", "lower_hypertrophy"],
     "volume_bias": "high", "intensity_bias": "moderate", "fatigue_tolerance": "moderate",
     "entry_criteria": [], "exit_criteria": [
         {"kind": "timeline", "parameters": {"min_weeks": 4}, "required": True},
         {"kind": "performance", "parameters": {"load_delta_pct_min": 0.05}, "required": False},
     ],
     "exercise_selection_bias": {"prefer_compound": True, "prefer_unilateral": True, "prefer_ballistic": False}},
    {"phase_kind": "strength",     "duration_weeks_range": {"min": 3, "max": 4},
     "training_priorities": ["push_strength", "pull_strength", "lower_strength"],
     "volume_bias": "moderate", "intensity_bias": "high", "fatigue_tolerance": "moderate",
     "entry_criteria": [], "exit_criteria": [
         {"kind": "timeline", "parameters": {"min_weeks": 3}, "required": True},
         {"kind": "performance", "parameters": {"rpe_stable_or_down": True}, "required": False},
     ],
     "exercise_selection_bias": {"prefer_compound": True, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "peak",         "duration_weeks_range": {"min": 2, "max": 3},
     "training_priorities": ["push_strength", "pull_strength"],
     "volume_bias": "low", "intensity_bias": "high", "fatigue_tolerance": "low",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"min_weeks": 2}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": True, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "recovery",     "duration_weeks_range": {"min": 1, "max": 2},
     "training_priorities": ["mobility", "z2_run"],
     "volume_bias": "low", "intensity_bias": "low", "fatigue_tolerance": "high",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"min_weeks": 1}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": False, "prefer_unilateral": False, "prefer_ballistic": False}},
    # Endurance
    {"phase_kind": "aerobic_base", "duration_weeks_range": {"min": 4, "max": 8},
     "training_priorities": ["easy_run", "long_run", "z2_bike"],
     "volume_bias": "high", "intensity_bias": "low", "fatigue_tolerance": "high",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"min_weeks": 4}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": False, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "build",        "duration_weeks_range": {"min": 4, "max": 6},
     "training_priorities": ["tempo_run", "intervals_run", "long_run"],
     "volume_bias": "high", "intensity_bias": "moderate", "fatigue_tolerance": "moderate",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"min_weeks": 4}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": False, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "specific_prep","duration_weeks_range": {"min": 3, "max": 4},
     "training_priorities": ["long_run", "tempo_run"],
     "volume_bias": "moderate", "intensity_bias": "race_specific", "fatigue_tolerance": "moderate",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"min_weeks": 3}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": False, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "taper",        "duration_weeks_range": {"min": 2, "max": 3},
     "training_priorities": ["easy_run", "tempo_run"],
     "volume_bias": "tapering", "intensity_bias": "race_specific", "fatigue_tolerance": "low",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"race_days_within": 7}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": False, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "race_week",    "duration_weeks_range": {"min": 1, "max": 1},
     "training_priorities": ["easy_run"],
     "volume_bias": "tapering", "intensity_bias": "race_specific", "fatigue_tolerance": "low",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"race_arrived": True}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": False, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "return_to_training", "duration_weeks_range": {"min": 4, "max": 6},
     "training_priorities": ["mobility", "z2_run", "full_body_strength"],
     "volume_bias": "low", "intensity_bias": "low", "fatigue_tolerance": "high",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"min_weeks": 4}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": True, "prefer_unilateral": False, "prefer_ballistic": False}},
    {"phase_kind": "maintenance",  "duration_weeks_range": {"min": 4, "max": 12},
     "training_priorities": ["full_body_strength", "z2_run", "mobility"],
     "volume_bias": "moderate", "intensity_bias": "moderate", "fatigue_tolerance": "moderate",
     "entry_criteria": [], "exit_criteria": [{"kind": "timeline", "parameters": {"min_weeks": 4}, "required": True}],
     "exercise_selection_bias": {"prefer_compound": True, "prefer_unilateral": False, "prefer_ballistic": False}},
]


async def seed_catalogs_once() -> None:
    """Upsert seed GoalDefinition + PhaseDefinition records if missing."""
    for gd in _GOAL_DEFINITIONS_SEED:
        await db.goal_definitions.update_one(
            {"goal_id_taxonomy": gd["goal_id_taxonomy"]},
            {"$setOnInsert": {**gd, "id": new_id(), "created_at": now_iso(),
                              "updated_at": now_iso()}},
            upsert=True,
        )
    for pd in _PHASE_DEFINITIONS_SEED:
        await db.phase_definitions.update_one(
            {"phase_kind": pd["phase_kind"]},
            {"$setOnInsert": {**pd, "id": new_id(), "created_at": now_iso(),
                              "updated_at": now_iso()}},
            upsert=True,
        )


# ---------------------------------------------------------------------------
# Goal — CRUD (per client)
# ---------------------------------------------------------------------------

class GoalBody(BaseModel):
    goal_id_taxonomy: str
    priority: Literal["A", "B", "C"] = "A"
    weight: float = Field(1.0, ge=0, le=1)
    target_date: Optional[str] = None
    target_metric: Optional[dict] = None
    current_baseline: Optional[dict] = None
    notes: str = ""


def _classify_timeline(gd: dict, target_date: Optional[str]) -> str:
    if not target_date or gd.get("ideal_prep_weeks") is None:
        return "developmental"
    try:
        td = _dt.date.fromisoformat(target_date)
        today = _dt.date.today()
        weeks = (td - today).days / 7.0
    except Exception:
        return "developmental"
    if weeks >= (gd.get("ideal_prep_weeks") or 999):    return "developmental"
    if weeks >= (gd.get("standard_prep_weeks") or 999): return "standard"
    if weeks >= (gd.get("compressed_prep_weeks") or 999): return "compressed"
    return "high_risk"


async def _normalise_weights(client_id: str) -> None:
    """Re-normalise weights of active goals so they sum to ~1.0."""
    rows = await db.goals_v2.find(
        {"client_id": client_id, "status": "active"}, {"_id": 0, "id": 1, "weight": 1}
    ).to_list(50)
    total = sum(float(r.get("weight") or 0) for r in rows) or 1.0
    if abs(total - 1.0) < 1e-3:
        return
    for r in rows:
        w = float(r.get("weight") or 0) / total
        await db.goals_v2.update_one({"id": r["id"]}, {"$set": {"weight": round(w, 4)}})


@api.post("/v2/coach/clients/{client_id}/goals")
async def goal_create(
    client_id: str,
    body: GoalBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    gd = await db.goal_definitions.find_one({"goal_id_taxonomy": body.goal_id_taxonomy}, {"_id": 0})
    if not gd:
        raise HTTPException(400, f"Unknown goal_id_taxonomy: {body.goal_id_taxonomy}")

    # Only one priority=A permitted unless coach explicitly demotes existing
    if body.priority == "A":
        clash = await db.goals_v2.find_one(
            {"client_id": client_id, "status": "active", "priority": "A"}, {"_id": 0, "id": 1}
        )
        if clash:
            raise HTTPException(409, f"Another priority-A goal already exists ({clash['id']}). Demote it first.")

    gid = new_id()
    doc = {
        "id": gid,
        "client_id": client_id,
        "goal_id_taxonomy": body.goal_id_taxonomy,
        "priority": body.priority,
        "weight": float(body.weight or 1.0),
        "target_date": body.target_date,
        "target_metric": body.target_metric,
        "current_baseline": body.current_baseline,
        "notes": body.notes,
        "status": "active",
        "timeline_class": _classify_timeline(gd, body.target_date),
        "created_by": coach["id"],
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    await db.goals_v2.insert_one(dict(doc))
    await _normalise_weights(client_id)
    await write_decision(
        actor="coach", layer="WHAT", scope_kind="goal", scope_id=gid,
        client_id=client_id, outcome="APPLIED",
        reason=f"Goal added: {body.goal_id_taxonomy} (priority={body.priority}, timeline={doc['timeline_class']})",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/goals")
async def goal_list(
    client_id: str, status: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if status:
        q["status"] = status
    rows = await db.goals_v2.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"goals": rows}


class GoalPatchBody(BaseModel):
    priority: Optional[Literal["A", "B", "C"]] = None
    weight: Optional[float] = None
    target_date: Optional[str] = None
    target_metric: Optional[dict] = None
    current_baseline: Optional[dict] = None
    notes: Optional[str] = None
    status: Optional[Literal["active", "paused", "completed", "abandoned"]] = None


@api.patch("/v2/coach/clients/{client_id}/goals/{goal_id}")
async def goal_patch(
    client_id: str, goal_id: str, body: GoalPatchBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    current = await db.goals_v2.find_one({"id": goal_id, "client_id": client_id}, {"_id": 0})
    if not current:
        raise HTTPException(404, "Goal not found")

    updates: dict = {"updated_at": now_iso()}
    for k in ("priority", "weight", "target_metric", "current_baseline", "notes", "status"):
        v = getattr(body, k)
        if v is not None:
            updates[k] = v
    if body.target_date is not None:
        updates["target_date"] = body.target_date
        gd = await db.goal_definitions.find_one({"goal_id_taxonomy": current["goal_id_taxonomy"]}, {"_id": 0})
        if gd:
            updates["timeline_class"] = _classify_timeline(gd, body.target_date)
    updates["version"] = int(current.get("version", 1)) + 1

    await db.goals_v2.update_one({"id": goal_id}, {"$set": updates})
    if body.weight is not None or body.status is not None:
        await _normalise_weights(client_id)

    await write_decision(
        actor="coach", layer="WHAT", scope_kind="goal", scope_id=goal_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Goal patched: {sorted(k for k in updates if k not in ('updated_at','version'))}",
    )
    return await db.goals_v2.find_one({"id": goal_id}, {"_id": 0})


# ---------------------------------------------------------------------------
# Programme + ProgrammePhase
# ---------------------------------------------------------------------------

class ProgrammeBody(BaseModel):
    primary_goal_id: str
    secondary_goal_ids: list[str] = []
    event_ids: list[str] = []
    start_date: str
    end_date: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/programmes")
async def programme_create(
    client_id: str, body: ProgrammeBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    primary = await db.goals_v2.find_one({"id": body.primary_goal_id, "client_id": client_id}, {"_id": 0})
    if not primary:
        raise HTTPException(400, "Primary goal not found for this client")

    # Mark any active programme as superseded
    await db.programmes_v2.update_many(
        {"client_id": client_id, "status": "active"},
        {"$set": {"status": "superseded", "updated_at": now_iso()}},
    )

    pid = new_id()
    now = now_iso()
    doc = {
        "id": pid,
        "client_id": client_id,
        "primary_goal_id": body.primary_goal_id,
        "secondary_goal_ids": body.secondary_goal_ids,
        "event_ids": body.event_ids,
        "timeline_class": primary.get("timeline_class", "developmental"),
        "start_date": body.start_date,
        "end_date": body.end_date,
        "status": "draft",
        "phase_sequence": [],
        "live_plan_version": 0,
        "draft_plan_version": 1,
        "created_by": coach["id"],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    await db.programmes_v2.insert_one(dict(doc))
    await write_decision(
        actor="coach", layer="WHAT", scope_kind="programme", scope_id=pid,
        client_id=client_id, outcome="APPLIED",
        reason=f"Programme created (primary_goal={primary.get('goal_id_taxonomy')}, timeline={doc['timeline_class']})",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/programmes")
async def programme_list(
    client_id: str, coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    rows = await db.programmes_v2.find({"client_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"programmes": rows}


class PhaseSequenceBody(BaseModel):
    programme_id: str
    phase_sequence: list[dict]  # [{phase_kind, weeks, start_date?}, ...]


def _phase_definition_map(seed: list[dict]) -> dict:
    return {p["phase_kind"]: p for p in seed}


@api.post("/v2/coach/clients/{client_id}/programme-phases/build")
async def phases_build(
    client_id: str, body: PhaseSequenceBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Build a ProgrammePhase timeline from a phase sequence.

    Each entry must reference a known phase_kind (from phase_definitions).
    Dates chain forward from `start_date` of the first entry (or programme start).
    """
    await require_client_and_flag(client_id, FLAG)
    prog = await db.programmes_v2.find_one({"id": body.programme_id, "client_id": client_id}, {"_id": 0})
    if not prog:
        raise HTTPException(404, "Programme not found")
    if not body.phase_sequence:
        raise HTTPException(400, "phase_sequence must not be empty")

    # Wipe existing phases for a clean rebuild
    await db.programme_phases_v2.delete_many({"programme_id": body.programme_id})

    cursor_date = _dt.date.fromisoformat(prog["start_date"])
    phase_ids: list[str] = []
    for ordinal, entry in enumerate(body.phase_sequence, start=1):
        pk = entry.get("phase_kind")
        weeks = int(entry.get("weeks") or 4)
        start_date = _dt.date.fromisoformat(entry["start_date"]) if entry.get("start_date") else cursor_date
        end_date = start_date + _dt.timedelta(weeks=weeks) - _dt.timedelta(days=1)
        pd_def = await db.phase_definitions.find_one({"phase_kind": pk}, {"_id": 0})
        if not pd_def:
            raise HTTPException(400, f"Unknown phase_kind: {pk}")
        phid = new_id()
        await db.programme_phases_v2.insert_one({
            "id": phid,
            "programme_id": body.programme_id,
            "client_id": client_id,
            "phase_kind": pk,
            "ordinal": ordinal,
            "planned_start_date": start_date.isoformat(),
            "planned_end_date": end_date.isoformat(),
            "actual_start_date": None,
            "actual_end_date": None,
            "entry_criteria": pd_def.get("entry_criteria", []),
            "exit_criteria": pd_def.get("exit_criteria", []),
            "status": "upcoming" if ordinal > 1 else "active",
            "purpose_summary": f"{pk.replace('_', ' ').title()} block",
            "training_priorities": pd_def.get("training_priorities", []),
            "volume_bias": pd_def.get("volume_bias"),
            "intensity_bias": pd_def.get("intensity_bias"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        phase_ids.append(phid)
        cursor_date = end_date + _dt.timedelta(days=1)

    await db.programmes_v2.update_one(
        {"id": body.programme_id},
        {"$set": {"phase_sequence": phase_ids, "updated_at": now_iso()}}
    )
    await write_decision(
        actor="coach", layer="WHAT", scope_kind="programme", scope_id=body.programme_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Phases built: {[p.get('phase_kind') for p in body.phase_sequence]}",
    )
    return {"programme_id": body.programme_id, "phase_ids": phase_ids, "count": len(phase_ids)}


@api.get("/v2/coach/clients/{client_id}/programme-phases")
async def phases_list(
    client_id: str, programme_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    rows = await db.programme_phases_v2.find(
        {"programme_id": programme_id, "client_id": client_id}, {"_id": 0}
    ).sort("ordinal", 1).to_list(50)
    return {"phases": rows}


# ---------------------------------------------------------------------------
# Catalogs — read-only for now
# ---------------------------------------------------------------------------

@api.get("/v2/catalog/goal-definitions")
async def catalog_goal_definitions(coach: dict = Depends(require_role("coach"))) -> dict:
    rows = await db.goal_definitions.find({}, {"_id": 0}).sort("goal_id_taxonomy", 1).to_list(200)
    return {"goal_definitions": rows}


@api.get("/v2/catalog/phase-definitions")
async def catalog_phase_definitions(coach: dict = Depends(require_role("coach"))) -> dict:
    rows = await db.phase_definitions.find({}, {"_id": 0}).sort("phase_kind", 1).to_list(200)
    return {"phase_definitions": rows}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("goals_v2", [
        ([("client_id", 1), ("status", 1)], False, "goals_v2_client_status"),
        ([("client_id", 1), ("priority", 1)], False, "goals_v2_client_priority"),
    ])
    await ensure_indexes("programmes_v2", [
        ([("client_id", 1), ("status", 1)], False, "programmes_v2_client_status"),
    ])
    await ensure_indexes("programme_phases_v2", [
        ([("programme_id", 1), ("ordinal", 1)], True, "programme_phases_v2_prog_ordinal"),
    ])
    await ensure_indexes("goal_definitions", [
        ([("goal_id_taxonomy", 1)], True, "goal_definitions_taxonomy"),
    ])
    await ensure_indexes("phase_definitions", [
        ([("phase_kind", 1)], True, "phase_definitions_kind"),
    ])
    await seed_catalogs_once()


bg(_bootstrap())


logger.info("feature_v2_p2_goals: /api/v2 goals + programmes + phases endpoints registered")
