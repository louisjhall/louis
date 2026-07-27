"""
feature_v2_p7_equipment — V2 Phase 7: EquipmentContext + SafeAdaptationBoundary.

Lets the client (or coach) declare available equipment (permanent / date-range /
today / this-session) and adapt a workout implementation to that context.
Falls back to bodyweight fallback slots defined in P6.

If the requested change stays inside the SafeAdaptationBoundary → no ChangeSet
required (coach doesn't see). If it exceeds SAB → creates a ChangeSet in P1
state for coach review.

Ships behind `v2_flags.equipment_adaptation_v2_enabled`.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, current_user, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg, emit_metric
)

FLAG = "equipment_adaptation_v2_enabled"

DEFAULT_SAB = {
    "allow_equipment_swap": True,
    "allow_duration_reduce_pct": 30,
    "allow_convert_to_recovery": False,
    "allow_convert_to_mobility": True,
    "allow_skip": False,
    "allow_move_within_planning_window": False,
    "allow_move_across_windows": False,
    "allow_substitute_exercise_from_approved_pool": True,
    "key_session_hardened": True,
    "overrides": {},
}


# ---------------------------------------------------------------------------
# EquipmentContext CRUD
# ---------------------------------------------------------------------------

class EquipmentContextBody(BaseModel):
    equipment: list[str]
    detail: Optional[dict] = None
    scope: str = "this_session"     # permanent | date_range | today | this_session
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    source: str = "client_selected"


@api.post("/v2/client/equipment-contexts")
async def eq_context_create_client(
    body: EquipmentContextBody, user: dict = Depends(current_user)
) -> dict:
    if user.get("role") != "client":
        raise HTTPException(403, "Client-only endpoint")
    if not (user.get("profile", {}).get("v2_flags", {}).get(FLAG)
            or user.get("profile", {}).get("v2_flags", {}).get("v2_default")):
        raise HTTPException(409, "V2 equipment adaptation not enabled for you")
    return await _create_eq_context(user["id"], body, source_override=body.source or "client_selected")


@api.post("/v2/coach/clients/{client_id}/equipment-contexts")
async def eq_context_create_coach(
    client_id: str, body: EquipmentContextBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    return await _create_eq_context(client_id, body, source_override="coach_selected")


async def _create_eq_context(client_id: str, body: EquipmentContextBody, source_override: str) -> dict:
    cid = new_id()
    doc = {
        "id": cid,
        "client_id": client_id,
        "source": source_override,
        "scope": body.scope,
        "equipment": list(dict.fromkeys(body.equipment or [])),
        "detail": body.detail or {},
        "valid_from": body.valid_from or now_iso(),
        "valid_until": body.valid_until,
        "created_at": now_iso(),
        "created_by": client_id,
    }
    await db.equipment_contexts.insert_one(dict(doc))
    await write_decision(
        actor="client" if source_override == "client_selected" else "coach",
        layer="ADAPT", scope_kind="equipment_context", scope_id=cid,
        client_id=client_id, outcome="APPLIED",
        reason=f"Equipment context set ({body.scope}): {doc['equipment']}",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/equipment-contexts")
async def eq_context_list(
    client_id: str, coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    rows = await db.equipment_contexts.find({"client_id": client_id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"equipment_contexts": rows}


# ---------------------------------------------------------------------------
# Adapt endpoint — apply new equipment context to an assignment's implementation
# ---------------------------------------------------------------------------

class AdaptBody(BaseModel):
    assignment_id: str
    equipment_context_id: Optional[str] = None
    equipment_inline: Optional[list[str]] = None
    duration_min_override: Optional[int] = None
    convert_to_mobility: bool = False


@api.post("/v2/client/plan/adapt")
async def adapt_client(
    body: AdaptBody, user: dict = Depends(current_user)
) -> dict:
    if user.get("role") != "client":
        raise HTTPException(403, "Client-only endpoint")
    return await _adapt(user["id"], body, actor="client")


@api.post("/v2/coach/clients/{client_id}/plan/adapt")
async def adapt_coach(
    client_id: str, body: AdaptBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    return await _adapt(client_id, body, actor="coach")


async def _adapt(client_id: str, body: AdaptBody, actor: str) -> dict:
    a = await db.workout_assignments.find_one({"id": body.assignment_id, "client_id": client_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Assignment not found")

    equip_list = list(body.equipment_inline or [])
    if body.equipment_context_id:
        ec = await db.equipment_contexts.find_one({"id": body.equipment_context_id, "client_id": client_id}, {"_id": 0})
        if not ec:
            raise HTTPException(404, "Equipment context not found")
        equip_list = list(ec.get("equipment") or [])
    if not equip_list:
        equip_list = ["bodyweight", "mat", "band"]

    sab = a.get("safe_adaptation_boundary") or DEFAULT_SAB
    exceeds_sab = False
    exceeds_reasons: list[str] = []

    # Duration change checks
    if body.duration_min_override:
        planned = int(a.get("planned_duration_min") or 45)
        reduce_pct = max(0, (planned - int(body.duration_min_override)) / planned * 100)
        allowed = int(sab.get("allow_duration_reduce_pct") or 20)
        if reduce_pct > allowed and (a.get("importance") == "key" and sab.get("key_session_hardened")):
            exceeds_sab = True
            exceeds_reasons.append(f"duration reduce {reduce_pct:.0f}% > SAB {allowed}% on KEY session")

    if body.convert_to_mobility and not sab.get("allow_convert_to_mobility", True):
        exceeds_sab = True
        exceeds_reasons.append("convert_to_mobility not allowed by SAB")

    # Rebuild via P6 with new equipment set
    from feature_v2_p6_construction import (
        _load_context, _select_exercise_for_slot,   # type: ignore
    )
    # Manually update the equipment set instead of loading defaults
    _, avoid_regions = await _load_context(client_id)
    equip_set = set(equip_list)

    obj = await db.training_objectives.find_one({"id": a.get("objective_id")}, {"_id": 0})
    phase = await db.programme_phases_v2.find_one({"id": (obj or {}).get("phase_id")}, {"_id": 0}) if obj else None
    tmpl = None
    if obj and phase:
        tmpl = await db.workout_slot_templates.find_one(
            {"objective_kind": obj["kind"], "phase_kind": phase["phase_kind"], "intent": "primary"}, {"_id": 0}
        )
        if not tmpl:
            tmpl = await db.workout_slot_templates.find_one({"objective_kind": obj["kind"], "intent": "primary"}, {"_id": 0})
    if not tmpl:
        # Broaden search: any objective_kind whose "family" matches (strength-like → full_body_strength)
        obj_kind = (obj or {}).get("kind", "")
        family_map = {
            "push_strength": "full_body_strength", "pull_strength": "full_body_strength",
            "lower_strength": "full_body_strength", "strength_support": "full_body_strength",
            "upper_strength": "full_body_strength",
            "strength_endurance": "full_body_strength",
        }
        fallback_kind = family_map.get(obj_kind, "full_body_strength")
        tmpl = await db.workout_slot_templates.find_one(
            {"objective_kind": fallback_kind, "intent": "primary"}, {"_id": 0}
        )
    if not tmpl:
        raise HTTPException(400, "No slot template found for this assignment's objective")

    gym_ish = equip_set & {"barbell", "dumbbells", "cable_stack", "machine_chest_press",
                            "machine_row", "machine_leg_press", "pull_up_bar"}
    if body.convert_to_mobility:
        tmpl = await db.workout_slot_templates.find_one({"objective_kind": "mobility", "intent": "primary"}, {"_id": 0}) or tmpl
        slots = tmpl.get("slots")
    else:
        slots = tmpl.get("slots") if gym_ish else (tmpl.get("bodyweight_fallback_slots") or tmpl.get("slots"))

    exercises_out: list[dict] = []
    for slot in slots or []:
        ex = await _select_exercise_for_slot(slot, equip_set, avoid_regions)
        if not ex and slot.get("required"):
            fb = next((s for s in (tmpl.get("bodyweight_fallback_slots") or []) if s.get("role") == slot.get("role")), None)
            if fb:
                ex = await _select_exercise_for_slot(fb, equip_set, avoid_regions)
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
            "coaching_cue": "",
        })

    wid = new_id()
    duration_min = body.duration_min_override or tmpl.get("target_duration_min") or a.get("planned_duration_min") or 30
    impl_doc = {
        "id": wid,
        "assignment_id": a["id"],
        "client_id": client_id,
        "date": a["date"],
        "variant_of_id": a.get("draft_implementation_id") or a.get("live_implementation_id"),
        "variant_type": "amber" if not body.convert_to_mobility else "red",
        "equipment_context": {"equipment": list(equip_set)},
        "duration_min": duration_min,
        "title": ("Mobility · adapted" if body.convert_to_mobility
                   else f"{(obj or {}).get('kind', 'Session').title()} · adapted"),
        "location_label": "",
        "focus": (obj or {}).get("kind", "adapted"),
        "warmup": [{"name": "Movement prep", "duration_sec": 240}],
        "exercises": exercises_out,
        "cooldown": [{"name": "Cooldown", "duration_sec": 180}],
        "rationale": "Adapted to what you have today — same intent, different tools.",
        "key_session": (a.get("importance") == "key" and not body.convert_to_mobility),
        "source": "template_v2",
        "needs_coach_review": exceeds_sab,
        "built_at": now_iso(),
        "cache_key": f"{(obj or {}).get('kind')}::adapt::{','.join(sorted(equip_set))}",
    }
    await db.workout_implementations.insert_one(dict(impl_doc))

    # Update assignment pointer
    upd = {"draft_implementation_id": wid, "updated_at": now_iso()}
    if not exceeds_sab and actor == "client":
        upd["live_implementation_id"] = wid   # client-side adapt within SAB is auto-live
    await db.workout_assignments.update_one({"id": a["id"]}, {"$set": upd})

    # Emit change set if SAB exceeded
    change_set_id = None
    if exceeds_sab:
        change_set_id = new_id()
        await db.change_sets.insert_one({
            "id": change_set_id,
            "draft_id": a.get("draft_id"),
            "client_id": client_id,
            "kind": "equipment_context_changed",
            "scope_assignment_ids": [a["id"]],
            "before_snapshot": {"equipment": []},
            "after_snapshot": {"equipment": list(equip_set),
                                "duration_min": duration_min,
                                "convert_to_mobility": body.convert_to_mobility},
            "triggered_by": actor, "triggered_event_id": None, "proposed_by": actor,
            "status": "proposed",
            "human_readable_summary": " · ".join(["Adaptation exceeds SAB"] + exceeds_reasons),
            "created_at": now_iso(),
        })
        await emit_metric("workout_adaptation_escalated", client_id=client_id, numeric_value=1)
    else:
        await emit_metric("workout_adaptation_within_sab", client_id=client_id, numeric_value=1)

    await write_decision(
        actor=actor, layer="ADAPT", scope_kind="workout_implementation",
        scope_id=wid, client_id=client_id,
        outcome="APPLIED" if not exceeds_sab else "PROPOSED",
        reason=f"Adapted assignment {a['id']} to {sorted(equip_set)}"
               + (f" · SAB exceeded: {exceeds_reasons}" if exceeds_sab else " · within SAB"),
    )

    impl_doc.pop("_id", None)
    return {"implementation": impl_doc, "exceeds_sab": exceeds_sab,
            "change_set_id": change_set_id, "reasons": exceeds_reasons}


# ---------------------------------------------------------------------------
# SAB read/write
# ---------------------------------------------------------------------------

class SABBody(BaseModel):
    assignment_id: Optional[str] = None
    programme_id: Optional[str] = None
    client_default: bool = False
    sab: dict


@api.patch("/v2/coach/clients/{client_id}/sab")
async def sab_set(
    client_id: str, body: SABBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    if body.client_default:
        await db.users.update_one(
            {"id": client_id},
            {"$set": {"profile.safe_adaptation_boundary_default": body.sab}}
        )
    elif body.assignment_id:
        await db.workout_assignments.update_one(
            {"id": body.assignment_id, "client_id": client_id},
            {"$set": {"safe_adaptation_boundary": body.sab, "updated_at": now_iso()}}
        )
    elif body.programme_id:
        await db.workout_assignments.update_many(
            {"programme_id": body.programme_id, "client_id": client_id},
            {"$set": {"safe_adaptation_boundary": body.sab, "updated_at": now_iso()}}
        )
    else:
        raise HTTPException(400, "Provide one of: client_default | assignment_id | programme_id")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("equipment_contexts", [
        ([("client_id", 1), ("scope", 1)], False, "eq_ctx_client_scope"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p7_equipment: /api/v2 equipment-contexts + adapt endpoints registered")
