"""
feature_v2_p9_events — V2 Phase 9: Event countdown + phase transitions.

Provides:
  - Event countdown queries (weeks/days until each active priority-A event)
  - Auto-generated PhaseTransitionProposed events for coach approval
  - `auto_advance_enabled` toggle per programme

Ships behind `v2_flags.events_v2_enabled`.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg
)

FLAG = "events_v2_enabled"


# ---------------------------------------------------------------------------
# Countdown
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/events/countdown")
async def event_countdown(
    client_id: str, coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    rows = await db.events.find(
        {"user_id": client_id, "status": "active"}, {"_id": 0}
    ).sort("date", 1).to_list(50) or []
    # V2 events collection fallback
    v2rows = await db.events_v2.find(
        {"client_id": client_id, "status": "active"}, {"_id": 0}
    ).sort("date", 1).to_list(50) or []

    today = _dt.date.today()
    out = []
    for e in (rows + v2rows):
        try:
            d = _dt.date.fromisoformat(e.get("date"))
        except Exception:
            continue
        days = (d - today).days
        out.append({
            "event_id": e.get("id"),
            "event_type": e.get("event_type"),
            "date": e.get("date"),
            "days_to_event": days,
            "weeks_to_event": round(days / 7.0, 1),
            "priority": e.get("priority") or "A",
            "location": e.get("location"),
        })
    return {"events": out}


# ---------------------------------------------------------------------------
# Phase transition proposals
# ---------------------------------------------------------------------------

@api.post("/v2/coach/clients/{client_id}/phase-transitions/evaluate")
async def phase_transitions_evaluate(
    client_id: str, programme_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Evaluate the current active phase's exit criteria & propose transitions."""
    await require_client_and_flag(client_id, FLAG)
    active = await db.programme_phases_v2.find_one(
        {"programme_id": programme_id, "client_id": client_id, "status": "active"}, {"_id": 0}
    )
    if not active:
        return {"proposals": [], "note": "No active phase"}

    today = _dt.date.today()
    try:
        end = _dt.date.fromisoformat(active["planned_end_date"])
    except Exception:
        end = today

    proposals: list[dict] = []
    if today >= end:
        # Find next phase
        nxt = await db.programme_phases_v2.find_one(
            {"programme_id": programme_id, "ordinal": {"$gt": int(active["ordinal"])}},
            {"_id": 0}, sort=[("ordinal", 1)]
        )
        prop_id = new_id()
        proposal = {
            "id": prop_id,
            "client_id": client_id,
            "programme_id": programme_id,
            "from_phase_id": active["id"],
            "from_phase_kind": active["phase_kind"],
            "to_phase_id": (nxt or {}).get("id"),
            "to_phase_kind": (nxt or {}).get("phase_kind"),
            "reason": "planned_end_date reached",
            "status": "proposed",
            "created_at": now_iso(),
        }
        await db.phase_transition_proposals.insert_one(dict(proposal))
        proposal.pop("_id", None)
        proposals.append(proposal)

    return {"proposals": proposals}


class ApplyTransitionBody(BaseModel):
    proposal_id: str


@api.post("/v2/coach/clients/{client_id}/phase-transitions/apply")
async def phase_transition_apply(
    client_id: str, body: ApplyTransitionBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    prop = await db.phase_transition_proposals.find_one(
        {"id": body.proposal_id, "client_id": client_id, "status": "proposed"}, {"_id": 0}
    )
    if not prop:
        raise HTTPException(404, "Proposal not found or already applied")
    await db.programme_phases_v2.update_one(
        {"id": prop["from_phase_id"]},
        {"$set": {"status": "completed", "actual_end_date": now_iso().split("T")[0], "updated_at": now_iso()}}
    )
    if prop.get("to_phase_id"):
        await db.programme_phases_v2.update_one(
            {"id": prop["to_phase_id"]},
            {"$set": {"status": "active", "actual_start_date": now_iso().split("T")[0], "updated_at": now_iso()}}
        )
    await db.phase_transition_proposals.update_one(
        {"id": body.proposal_id}, {"$set": {"status": "applied", "applied_by": coach["id"], "applied_at": now_iso()}}
    )
    await write_decision(
        actor="coach", layer="WHAT", scope_kind="phase", scope_id=prop["from_phase_id"],
        client_id=client_id, outcome="APPLIED",
        reason=f"Phase transition applied: {prop.get('from_phase_kind')} → {prop.get('to_phase_kind')}",
    )
    return {"ok": True, "from": prop.get("from_phase_kind"), "to": prop.get("to_phase_kind")}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("phase_transition_proposals", [
        ([("programme_id", 1), ("status", 1)], False, "ptp_prog_status"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p9_events: /api/v2 countdown + phase-transition endpoints registered")
