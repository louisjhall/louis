"""
feature_v2_p10_reality — V2 Phase 10: Readiness + Today's Reality resolver.

Structured chip resolver for today's reality (energy / soreness / pain /
missed / time-pressed / low-motivation / life-change). Only "Other" escalates
to LLM.

Ships behind `v2_flags.reality_v2_enabled`.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, current_user, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg, emit_metric
)

FLAG = "reality_v2_enabled"


# ---------------------------------------------------------------------------
# Readiness store
# ---------------------------------------------------------------------------

class ReadinessBody(BaseModel):
    window: int = Field(7, ge=1, le=28)
    signals: dict


@api.post("/v2/client/readiness")
async def readiness_submit_client(
    body: ReadinessBody, user: dict = Depends(current_user)
) -> dict:
    if user.get("role") != "client":
        raise HTTPException(403, "Client-only endpoint")
    return await _write_readiness(user["id"], body)


@api.post("/v2/coach/clients/{client_id}/readiness")
async def readiness_submit_coach(
    client_id: str, body: ReadinessBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    return await _write_readiness(client_id, body)


async def _write_readiness(client_id: str, body: ReadinessBody) -> dict:
    band = _classify_readiness(body.signals or {})
    avoid_patterns = _movement_avoidance_from_pain(body.signals or {})
    rid = new_id()
    doc = {
        "id": rid,
        "client_id": client_id,
        "as_of_date": now_iso().split("T")[0],
        "window": body.window,
        "signals": body.signals or {},
        "band": band,
        "avoid_movement_patterns": avoid_patterns,
        "computed_at": now_iso(),
    }
    await db.readiness_states.insert_one(dict(doc))
    await write_decision(
        actor="client", layer="ADAPT", scope_kind="readiness_state", scope_id=rid,
        client_id=client_id, outcome="APPLIED",
        reason=f"Readiness recorded → band={band}, avoid={avoid_patterns}",
    )
    doc.pop("_id", None)
    return doc


def _classify_readiness(signals: dict) -> str:
    """Map raw signals to a band per the RULE_ENGINE spec (§10)."""
    sleep = float(signals.get("sleep_score_avg") or 6.0)
    energy = float(signals.get("energy_score_avg") or 6.0)
    soreness = float(signals.get("soreness_score_avg") or 3.0)
    pain = signals.get("pain_flags") or []
    missed = int(signals.get("missed_sessions_count") or 0)

    if pain or missed >= 3:                            return "coach_review"
    if sleep < 4.5 or energy < 4.5 or soreness > 7:    return "recover_priority"
    if sleep < 5.5 or energy < 5.5 or soreness > 5.5:  return "slight_reduce"
    return "normal"


def _movement_avoidance_from_pain(signals: dict) -> list[str]:
    pain_flags = signals.get("pain_flags") or []
    avoid = set()
    for p in pain_flags:
        region = (p.get("region") or "").lower()
        if "knee" in region:      avoid.update(["deep_squat", "lunge", "gait_run_tempo"])
        if "shoulder" in region:  avoid.update(["overhead_press", "vertical_pull"])
        if "back" in region:      avoid.update(["hinge", "deep_squat"])
        if "ankle" in region:     avoid.update(["gait_run_tempo", "lunge"])
    return sorted(avoid)


# ---------------------------------------------------------------------------
# Reality chip resolver
# ---------------------------------------------------------------------------

class RealityChipBody(BaseModel):
    assignment_id: str
    intent: str    # "im_tired" | "sore_knee" | "short_on_time" | "hotel_room" | "no_energy" | "low_motivation" | "life_change" | "other"
    detail: Optional[str] = None    # free text for "other"
    minutes_available: Optional[int] = None


CHIP_MAP = {
    "im_tired":          {"reduce_pct": 30, "convert_to_mobility": False, "cue": "shorter session, same shape"},
    "sore_knee":         {"reduce_pct": 20, "convert_to_mobility": False, "cue": "we'll skip loaded squats today"},
    "short_on_time":     {"reduce_pct": 40, "convert_to_mobility": False, "cue": "priorities only"},
    "hotel_room":        {"reduce_pct": 30, "convert_to_mobility": False, "cue": "bodyweight only"},
    "no_energy":         {"reduce_pct": 40, "convert_to_mobility": False, "cue": "recovery-focused"},
    "low_motivation":    {"reduce_pct": 25, "convert_to_mobility": False, "cue": "do the first 10 min, then decide"},
    "life_change":       {"reduce_pct": 20, "convert_to_mobility": True,  "cue": "mobility & reset today"},
}


@api.post("/v2/client/reality/apply")
async def reality_apply_client(
    body: RealityChipBody, user: dict = Depends(current_user)
) -> dict:
    if user.get("role") != "client":
        raise HTTPException(403, "Client-only endpoint")
    return await _apply_reality(user["id"], body, actor="client")


@api.post("/v2/coach/clients/{client_id}/reality/apply")
async def reality_apply_coach(
    client_id: str, body: RealityChipBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    return await _apply_reality(client_id, body, actor="coach")


async def _apply_reality(client_id: str, body: RealityChipBody, actor: str) -> dict:
    a = await db.workout_assignments.find_one({"id": body.assignment_id, "client_id": client_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Assignment not found")

    profile = CHIP_MAP.get(body.intent) or {"reduce_pct": 25, "convert_to_mobility": False, "cue": "adapted"}
    planned = int(a.get("planned_duration_min") or 45)
    target = body.minutes_available or int(planned * (1 - profile["reduce_pct"] / 100))

    # Route through P7 adapt endpoint helper
    from feature_v2_p7_equipment import _adapt, AdaptBody
    adapt_body = AdaptBody(
        assignment_id=body.assignment_id,
        equipment_inline=None,     # keep current
        duration_min_override=target,
        convert_to_mobility=profile["convert_to_mobility"],
    )
    # If we don't have any equipment context yet, use bodyweight
    adapt_body.equipment_inline = ["bodyweight", "mat", "band"]
    result = await _adapt(client_id, adapt_body, actor=actor)
    result["chip"] = {"intent": body.intent, "cue": profile["cue"], "target_min": target}

    await emit_metric("reality_chip_applied", client_id=client_id, numeric_value=1,
                      labels={"intent": body.intent})
    await write_decision(
        actor=actor, layer="ADAPT", scope_kind="assignment", scope_id=body.assignment_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Reality chip '{body.intent}' applied: reduce to {target}m ({profile['cue']})",
    )
    return result


# ---------------------------------------------------------------------------
# Coach directives (structured)
# ---------------------------------------------------------------------------

class CoachDirectiveBody(BaseModel):
    kind: str   # avoid_movement|require_movement|limit_frequency|limit_volume|limit_intensity|note_only|...
    scope: dict = {}
    parameters: dict = {}
    free_text: str = ""


@api.post("/v2/coach/clients/{client_id}/directives")
async def directive_create(
    client_id: str, body: CoachDirectiveBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    did = new_id()
    doc = {
        "id": did,
        "client_id": client_id,
        "coach_id": coach["id"],
        "kind": body.kind,
        "scope": body.scope,
        "parameters": body.parameters,
        "free_text": body.free_text,
        "status": "active",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.coach_directives.insert_one(dict(doc))
    await write_decision(
        actor="coach", layer="ADAPT", scope_kind="coach_directive", scope_id=did,
        client_id=client_id, outcome="APPLIED",
        reason=f"Coach directive: {body.kind} · {body.free_text[:80]}",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/directives")
async def directive_list(
    client_id: str, status: Optional[str] = "active",
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"client_id": client_id}
    if status: q["status"] = status
    rows = await db.coach_directives.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"directives": rows}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("readiness_states", [
        ([("client_id", 1), ("as_of_date", -1)], False, "readiness_client_date"),
    ])
    await ensure_indexes("coach_directives", [
        ([("client_id", 1), ("status", 1)], False, "cd_client_status"),
        ([("kind", 1)], False, "cd_kind"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p10_reality: /api/v2 readiness + reality-chip + directives registered")
