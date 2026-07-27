"""
feature_v2_p6_construction — V2 Phase 6: Workout construction (HOW layer).

Materialises WorkoutImplementations from WorkoutAssignments by:
  1. Looking up a matching workout_slot_template for the objective_kind + phase_kind.
  2. Ranking approved exercises_v2 records that match each slot's role_pattern_pool
     and the equipment_context.
  3. Applying deterministic post-filters (contraindication vs restrictions & readiness pain_flags).
  4. Emitting a WorkoutImplementation with sets/reps/rest resolved from the slot spec.
  5. Optionally polishing rationale via LLM (best-effort; falls back to template).

Ships behind `v2_flags.construction_v2_enabled`. Requires P3+P5 upstream.
"""
from __future__ import annotations

import datetime as _dt
import random
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg, emit_metric
)

FLAG = "construction_v2_enabled"


# ---------------------------------------------------------------------------
# Slot templates (seeded)
# ---------------------------------------------------------------------------

_SLOT_TEMPLATES_SEED = [
    # ---- Strength ----
    {
        "objective_kind": "upper_hypertrophy", "phase_kind": "hypertrophy",
        "intent": "primary", "target_duration_min": 45,
        "slots": [
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"],
             "equipment_preference": ["barbell", "dumbbells", "machine_chest_press"],
             "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7-8", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"],
             "equipment_preference": ["dumbbells", "cable_stack", "machine_row"],
             "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7-8", "key": True, "required": True},
            {"role": "secondary_vertical_push", "role_pattern_pool": ["vertical_push"],
             "equipment_preference": ["dumbbells", "barbell"], "sets": 3, "reps": "10-12",
             "rest_sec": 60, "rpe_target": "7", "key": False, "required": False},
            {"role": "secondary_vertical_pull", "role_pattern_pool": ["vertical_pull"],
             "equipment_preference": ["pull_up_bar", "machine_lat_pulldown", "band"],
             "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": False, "required": False},
            {"role": "trunk", "role_pattern_pool": ["anti_extension", "anti_rotate"],
             "equipment_preference": ["bodyweight", "cable_stack"], "sets": 2, "reps": "30-45s",
             "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
        "short_variants": [
            {"target_duration_min": 30, "keep_slots": ["primary_horizontal_push", "primary_horizontal_pull", "trunk"], "compress_rules": {}},
            {"target_duration_min": 20, "keep_slots": ["primary_horizontal_push", "primary_horizontal_pull"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"],
             "equipment_preference": ["bodyweight"], "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"],
             "equipment_preference": ["bodyweight", "band"], "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "trunk", "role_pattern_pool": ["anti_extension"], "equipment_preference": ["bodyweight"],
             "sets": 2, "reps": "30-45s", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
    },
    {
        "objective_kind": "lower_hypertrophy", "phase_kind": "hypertrophy",
        "intent": "primary", "target_duration_min": 45,
        "slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"],
             "equipment_preference": ["barbell", "dumbbells", "machine_leg_press"],
             "sets": 4, "reps": "6-8", "rest_sec": 120, "rpe_target": "8", "key": True, "required": True},
            {"role": "primary_hinge", "role_pattern_pool": ["hinge"],
             "equipment_preference": ["barbell", "dumbbells", "kettlebell"],
             "sets": 3, "reps": "8-10", "rest_sec": 120, "rpe_target": "7-8", "key": True, "required": True},
            {"role": "unilateral_leg", "role_pattern_pool": ["lunge"],
             "equipment_preference": ["dumbbells", "kettlebell", "bodyweight"],
             "sets": 3, "reps": "10 each side", "rest_sec": 60, "rpe_target": "7", "key": False, "required": False},
            {"role": "trunk", "role_pattern_pool": ["anti_rotate"], "equipment_preference": ["cable_stack", "band", "bodyweight"],
             "sets": 2, "reps": "30-45s", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
        "short_variants": [
            {"target_duration_min": 30, "keep_slots": ["primary_squat", "primary_hinge", "trunk"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["bodyweight"],
             "sets": 3, "reps": "12-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_hinge", "role_pattern_pool": ["hinge"], "equipment_preference": ["bodyweight"],
             "sets": 3, "reps": "10-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "unilateral_leg", "role_pattern_pool": ["lunge"], "equipment_preference": ["bodyweight"],
             "sets": 3, "reps": "10 each side", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
    },
    {
        "objective_kind": "full_body_strength", "phase_kind": "foundation",
        "intent": "primary", "target_duration_min": 40,
        "slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["barbell", "dumbbells", "bodyweight"],
             "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"],
             "equipment_preference": ["dumbbells", "barbell", "bodyweight"], "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"],
             "equipment_preference": ["dumbbells", "cable_stack", "band"], "sets": 3, "reps": "8-10", "rest_sec": 90, "rpe_target": "7", "key": True, "required": True},
            {"role": "trunk", "role_pattern_pool": ["anti_extension", "anti_rotate"],
             "equipment_preference": ["bodyweight"], "sets": 2, "reps": "30-45s", "rest_sec": 45, "rpe_target": "6", "key": False, "required": False},
        ],
        "short_variants": [
            {"target_duration_min": 25, "keep_slots": ["primary_squat", "primary_horizontal_push", "primary_horizontal_pull"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "primary_squat", "role_pattern_pool": ["squat"], "equipment_preference": ["bodyweight"], "sets": 3, "reps": "12-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_push", "role_pattern_pool": ["horizontal_push"], "equipment_preference": ["bodyweight"], "sets": 3, "reps": "8-15", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
            {"role": "primary_horizontal_pull", "role_pattern_pool": ["horizontal_pull"], "equipment_preference": ["bodyweight", "band"], "sets": 3, "reps": "8-12", "rest_sec": 60, "rpe_target": "7", "key": True, "required": True},
        ],
    },
    # ---- Endurance ----
    {
        "objective_kind": "easy_run", "phase_kind": "aerobic_base",
        "intent": "primary", "target_duration_min": 40,
        "slots": [
            {"role": "cardio_z2", "role_pattern_pool": ["gait_run_easy"],
             "equipment_preference": ["outdoor_run_safe", "treadmill"],
             "sets": 1, "reps": "z2", "rest_sec": 0, "rpe_target": "4-5", "key": True, "required": True,
             "hr_zone": "z2"},
        ],
        "short_variants": [
            {"target_duration_min": 20, "keep_slots": ["cardio_z2"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "cardio_z2_indoor", "role_pattern_pool": ["gait_run_easy"], "equipment_preference": ["bodyweight"],
             "sets": 1, "reps": "z2 (marching / step)", "rest_sec": 0, "rpe_target": "4-5", "key": True, "required": True},
        ],
    },
    {
        "objective_kind": "long_run", "phase_kind": "build",
        "intent": "primary", "target_duration_min": 90,
        "slots": [
            {"role": "cardio_long", "role_pattern_pool": ["gait_run_long"],
             "equipment_preference": ["outdoor_run_safe"], "sets": 1, "reps": "60-90 min z2",
             "rest_sec": 0, "rpe_target": "5-6", "key": True, "required": True, "hr_zone": "z2"},
        ],
        "short_variants": [
            {"target_duration_min": 60, "keep_slots": ["cardio_long"], "compress_rules": {}},
            {"target_duration_min": 45, "keep_slots": ["cardio_long"], "compress_rules": {}},
        ],
        "bodyweight_fallback_slots": [
            {"role": "cardio_long_indoor", "role_pattern_pool": ["gait_run_long"], "equipment_preference": ["treadmill"],
             "sets": 1, "reps": "45-60 min z2", "rest_sec": 0, "rpe_target": "5", "key": True, "required": True},
        ],
    },
    {
        "objective_kind": "tempo_run", "phase_kind": "build",
        "intent": "primary", "target_duration_min": 45,
        "slots": [
            {"role": "cardio_tempo", "role_pattern_pool": ["gait_run_tempo"],
             "equipment_preference": ["outdoor_run_safe", "treadmill"], "sets": 1, "reps": "20-30min tempo",
             "rest_sec": 0, "rpe_target": "7", "key": True, "required": True, "hr_zone": "z4"},
        ],
        "short_variants": [{"target_duration_min": 30, "keep_slots": ["cardio_tempo"], "compress_rules": {}}],
        "bodyweight_fallback_slots": [
            {"role": "cardio_tempo_indoor", "role_pattern_pool": ["gait_run_tempo"], "equipment_preference": ["treadmill"],
             "sets": 1, "reps": "20 min tempo", "rest_sec": 0, "rpe_target": "7", "key": True, "required": True},
        ],
    },
    {
        "objective_kind": "mobility", "phase_kind": "foundation",
        "intent": "primary", "target_duration_min": 20,
        "slots": [
            {"role": "flow", "role_pattern_pool": ["mobility_flow"],
             "equipment_preference": ["mat", "bodyweight"], "sets": 1, "reps": "15-20 min flow",
             "rest_sec": 0, "rpe_target": "3-4", "key": False, "required": True},
        ],
        "short_variants": [{"target_duration_min": 10, "keep_slots": ["flow"], "compress_rules": {}}],
        "bodyweight_fallback_slots": [
            {"role": "flow", "role_pattern_pool": ["mobility_flow"], "equipment_preference": ["bodyweight"],
             "sets": 1, "reps": "10-15 min flow", "rest_sec": 0, "rpe_target": "3-4", "key": False, "required": True},
        ],
    },
]


async def seed_slot_templates_once() -> None:
    for t in _SLOT_TEMPLATES_SEED:
        await db.workout_slot_templates.update_one(
            {"objective_kind": t["objective_kind"], "phase_kind": t["phase_kind"], "intent": t["intent"]},
            {"$setOnInsert": {**t, "id": new_id(), "created_at": now_iso(), "updated_at": now_iso()}},
            upsert=True,
        )


# ---------------------------------------------------------------------------
# Exercise selection
# ---------------------------------------------------------------------------

async def _select_exercise_for_slot(
    slot: dict, equipment_avail: set[str], avoid_regions: set[str]
) -> Optional[dict]:
    """Find best approved exercise from exercises_v2 for a slot."""
    pool = list(slot.get("role_pattern_pool") or [])
    pref = list(slot.get("equipment_preference") or [])
    if not pool:
        return None

    # Query candidates
    q: dict = {
        "$and": [
            {"$or": [{"movement_pattern": {"$in": pool}}, {"movement_family": {"$in": pool}}]},
            {"$or": [{"approval": "approved"}, {"approval_status": {"$in": ["approved", "live"]}}]},
        ]
    }
    if equipment_avail:
        q["$and"].append({"equipment_type": {"$in": list(equipment_avail)}})

    candidates = await db.exercises_v2.find(q, {"_id": 0}).limit(50).to_list(50)
    if not candidates:
        # fall back to exercises legacy
        candidates = await db.exercises.find(
            {"$or": [{"movement_pattern": {"$in": pool}}, {"movement_family": {"$in": pool}}]},
            {"_id": 0}
        ).limit(50).to_list(50) or []

    # Post-filter: avoid contraindicated regions
    def _ok(ex: dict) -> bool:
        contra = set(ex.get("contraindications") or [])
        return not (avoid_regions & contra)

    candidates = [c for c in candidates if _ok(c)]
    if not candidates:
        return None

    # Rank: exact equipment match first, then compound, then random
    def _score(ex: dict) -> tuple[int, int, int]:
        eq = set(ex.get("equipment_type") or [])
        pref_score = 100 - min(99, next((i for i, p in enumerate(pref) if p in eq), 99))
        compound_score = 1 if ex.get("compound") else 0
        return (pref_score, compound_score, random.randint(0, 1000))

    candidates.sort(key=_score, reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Build implementation
# ---------------------------------------------------------------------------

class BuildImplBody(BaseModel):
    assignment_ids: Optional[list[str]] = None
    draft_id: Optional[str] = None
    programme_id: Optional[str] = None
    include_variants: bool = False   # produce amber/red short variants too


async def _load_context(client_id: str) -> tuple[set[str], set[str]]:
    """Return (equipment_types_avail, movement_regions_to_avoid)."""
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    prof = (user or {}).get("profile") or {}
    equip_perm = set()
    for ec in prof.get("equipment_permanent") or []:
        if isinstance(ec, dict):
            equip_perm.update(ec.get("equipment") or [])
        elif isinstance(ec, str):
            equip_perm.add(ec)
    # If nothing declared, allow bodyweight + typical hotel-room equipment
    if not equip_perm:
        equip_perm = {"bodyweight", "mat", "band"}

    avoid = set()
    for r in prof.get("persistent_restrictions") or []:
        avoid.add((r.get("region") or "").lower())
    # Latest readiness pain flags
    rs = await db.readiness_states.find_one({"client_id": client_id}, {"_id": 0}, sort=[("as_of_date", -1)])
    for p in ((rs or {}).get("signals", {}).get("pain_flags") or []):
        avoid.add((p.get("region") or "").lower())
    # Active coach directives — avoid_movement patterns
    try:
        import datetime as _dtm
        from feature_v2_directive_engine import active_directives_for
        dirs = await active_directives_for(client_id, _dtm.date.today())
    except Exception:
        dirs = []
    for d in dirs:
        if d.get("kind") == "avoid_movement":
            patt = ((d.get("parameters") or {}).get("pattern") or "").lower()
            if patt: avoid.add(patt)
            txt = (d.get("free_text") or "").lower()
            if "run" in txt: avoid.add("gait_run_tempo"); avoid.add("gait_run_easy")
            if "knee" in txt: avoid.add("knee")
    return equip_perm, {r for r in avoid if r}


@api.post("/v2/coach/clients/{client_id}/plan/build-implementations")
async def implementations_build(
    client_id: str, body: BuildImplBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id, "status": {"$in": ["proposed", "ready"]}}
    if body.assignment_ids:
        q["id"] = {"$in": body.assignment_ids}
    elif body.programme_id:
        q["programme_id"] = body.programme_id
    elif body.draft_id:
        q["draft_id"] = body.draft_id
    assignments = await db.workout_assignments.find(q, {"_id": 0}).to_list(500)
    if not assignments:
        return {"implementations_created": 0, "note": "no assignments matched"}

    equip_avail, avoid_regions = await _load_context(client_id)
    built = 0
    for a in assignments:
        obj = await db.training_objectives.find_one({"id": a.get("objective_id")}, {"_id": 0})
        if not obj:
            continue
        phase = await db.programme_phases_v2.find_one({"id": obj.get("phase_id")}, {"_id": 0})
        if not phase:
            continue

        # Find matching slot template
        tmpl = await db.workout_slot_templates.find_one(
            {"objective_kind": obj["kind"], "phase_kind": phase["phase_kind"], "intent": "primary"},
            {"_id": 0}
        )
        if not tmpl:
            # Try any phase_kind for that objective_kind
            tmpl = await db.workout_slot_templates.find_one(
                {"objective_kind": obj["kind"], "intent": "primary"}, {"_id": 0}
            )
        if not tmpl:
            # Family fallback for strength variants
            family_map = {
                "push_strength": "full_body_strength", "pull_strength": "full_body_strength",
                "lower_strength": "full_body_strength", "upper_strength": "full_body_strength",
                "strength_support": "full_body_strength",
                "strength_endurance": "full_body_strength",
            }
            fallback_kind = family_map.get(obj["kind"])
            if fallback_kind:
                tmpl = await db.workout_slot_templates.find_one(
                    {"objective_kind": fallback_kind, "intent": "primary"}, {"_id": 0}
                )
        if not tmpl:
            continue

        # Choose slot set (bodyweight fallback if no gym-like equipment)
        gym_ish = equip_avail & {"barbell", "dumbbells", "cable_stack", "machine_chest_press",
                                 "machine_row", "machine_leg_press", "pull_up_bar"}
        slots = tmpl.get("slots") if gym_ish else (tmpl.get("bodyweight_fallback_slots") or tmpl.get("slots"))

        exercises_out: list[dict] = []
        for slot in slots or []:
            ex = await _select_exercise_for_slot(slot, equip_avail, avoid_regions)
            if not ex and slot.get("required"):
                # try bodyweight fallback slot
                fb = next((s for s in (tmpl.get("bodyweight_fallback_slots") or []) if s.get("role") == slot.get("role")), None)
                if fb:
                    ex = await _select_exercise_for_slot(fb, equip_avail, avoid_regions)
            if not ex:
                continue
            exercises_out.append({
                "slot_role": slot.get("role"),
                "exercise_id": ex.get("id"),
                "exercise_name_display": ex.get("exercise_name") or ex.get("name") or "Exercise",
                "sets": slot.get("sets"),
                "reps": slot.get("reps"),
                "rest_sec": slot.get("rest_sec"),
                "rpe": slot.get("rpe_target"),
                "hr_zone": slot.get("hr_zone"),
                "coaching_cue": "",   # LLM polish (P6 later); safe empty string for now
            })

        wid = new_id()
        impl_doc = {
            "id": wid,
            "assignment_id": a["id"],
            "client_id": client_id,
            "date": a["date"],
            "variant_of_id": None, "variant_type": "green",
            "equipment_context": {"equipment": list(equip_avail)},
            "duration_min": a.get("planned_duration_min") or tmpl.get("target_duration_min"),
            "title": f"{obj['kind'].replace('_', ' ').title()}",
            "location_label": "",
            "focus": obj["kind"],
            "warmup": [{"name": "Movement prep", "duration_sec": 300}],
            "exercises": exercises_out,
            "cooldown": [{"name": "Cooldown & mobility", "duration_sec": 180}],
            "rationale": f"{phase['phase_kind'].title()} phase · {obj['importance']} session · from the plan Louis built for you.",
            "key_session": (obj.get("importance") == "key"),
            "source": "template_v2",
            "needs_coach_review": False,
            "built_at": now_iso(),
            "cache_key": f"{obj['kind']}::{phase['phase_kind']}::{','.join(sorted(equip_avail))}",
        }
        await db.workout_implementations.insert_one(dict(impl_doc))
        await db.workout_assignments.update_one(
            {"id": a["id"]},
            {"$set": {"draft_implementation_id": wid, "status": "ready", "updated_at": now_iso()}}
        )
        await db.objective_exposures.update_one(
            {"assignment_id": a["id"]},
            {"$set": {"implementation_id": wid, "updated_at": now_iso()}}
        )
        await write_decision(
            actor="system", layer="HOW", scope_kind="workout_implementation",
            scope_id=wid, client_id=client_id, outcome="READY",
            reason=f"Built {obj['kind']} implementation ({len(exercises_out)} exercises) from slot template",
        )
        await emit_metric("workout_built", client_id=client_id, numeric_value=1,
                          labels={"objective_kind": obj["kind"], "phase_kind": phase["phase_kind"]})
        built += 1

    return {"implementations_created": built}


@api.get("/v2/coach/clients/{client_id}/plan/implementations/{assignment_id}")
async def implementation_get(
    client_id: str, assignment_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    row = await db.workout_implementations.find_one(
        {"assignment_id": assignment_id, "client_id": client_id}, {"_id": 0}
    )
    if not row:
        raise HTTPException(404, "No implementation for this assignment")
    return row


@api.get("/v2/catalog/slot-templates")
async def catalog_slot_templates(coach: dict = Depends(require_role("coach"))) -> dict:
    rows = await db.workout_slot_templates.find({}, {"_id": 0}).sort("objective_kind", 1).to_list(200)
    return {"slot_templates": rows}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("workout_implementations", [
        ([("assignment_id", 1)], False, "impl_assign"),
        ([("client_id", 1), ("date", 1)], False, "impl_client_date"),
    ])
    await ensure_indexes("workout_slot_templates", [
        ([("objective_kind", 1), ("phase_kind", 1), ("intent", 1)], False, "slot_tmpl_key"),
    ])
    await seed_slot_templates_once()


bg(_bootstrap())


logger.info("feature_v2_p6_construction: /api/v2 implementations + slot templates registered")
