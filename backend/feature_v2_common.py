"""
feature_v2_common — shared helpers for all V2 phase modules.

Purpose:
- Centralise the feature-flag gate used by every V2 endpoint.
- Provide a single DecisionRecord writer so audit trail is consistent.
- Ensure no V2 phase module ever bypasses the flag or forgets to log.

All V2 phases (P2..P12) route through `require_v2_flag(client_id, flag_name)`.
Nothing in this file writes into V1 collections.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import HTTPException

from server import db, new_id, now_iso, logger


V2_FLAGS = {
    "state_foundation_enabled",       # P1 — already shipped
    "goals_phases_enabled",           # P2
    "demand_engine_enabled",          # P3
    "roster_facets_enabled",          # P4
    "scheduling_v2_enabled",          # P5
    "construction_v2_enabled",        # P6
    "equipment_adaptation_v2_enabled",# P7
    "progression_v2_enabled",         # P8
    "events_v2_enabled",              # P9
    "reality_v2_enabled",             # P10
    "automation_v2_enabled",          # P12
    "shadow_mode",                    # P12
    "v2_default",                     # master
}


async def require_client_and_flag(client_id: str, flag: str) -> dict:
    """Load a client and enforce the given V2 flag is enabled.
    Raises 404 if not found, 409 if the flag is off.
    Returns the user document.
    """
    if flag not in V2_FLAGS:
        raise HTTPException(500, f"Unknown V2 flag: {flag}")
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")
    v2 = ((client.get("profile") or {}).get("v2_flags") or {})
    if not (v2.get(flag) or v2.get("v2_default")):
        raise HTTPException(
            409,
            f"V2 flag '{flag}' not enabled for this client. "
            f"Enable via PATCH /api/v2/coach/clients/{{cid}}/flags first.",
        )
    return client


async def flag_on(client_id: str, flag: str) -> bool:
    if flag not in V2_FLAGS:
        return False
    user = await db.users.find_one(
        {"id": client_id}, {"_id": 0, "profile.v2_flags": 1}
    )
    if not user:
        return False
    v2 = ((user.get("profile") or {}).get("v2_flags") or {})
    return bool(v2.get(flag) or v2.get("v2_default"))


async def write_decision(
    *,
    actor: str,
    layer: str,
    scope_kind: str,
    scope_id: str,
    outcome: str,
    reason: str,
    client_id: Optional[str] = None,
    event_id: Optional[str] = None,
    rule_or_prompt: Optional[dict] = None,
    confidence: Optional[float] = None,
    previous_state_ref: Optional[str] = None,
    new_state_ref: Optional[str] = None,
    input_summary: Optional[str] = None,
    llm_call_ref: Optional[dict] = None,
) -> str:
    rid = new_id()
    await db.decision_records.insert_one(
        {
            "id": rid,
            "client_id": client_id,
            "timestamp": now_iso(),
            "actor": actor,
            "event_id": event_id,
            "layer": layer,
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "input_summary": input_summary,
            "rule_or_prompt": rule_or_prompt,
            "confidence": confidence,
            "previous_state_ref": previous_state_ref,
            "new_state_ref": new_state_ref,
            "outcome": outcome,
            "human_readable_reason": reason,
            "llm_call_ref": llm_call_ref,
        }
    )
    return rid


async def emit_metric(event_name: str, *, client_id: Optional[str] = None,
                      coach_id: Optional[str] = None,
                      numeric_value: Optional[float] = None,
                      labels: Optional[dict] = None) -> None:
    try:
        await db.metrics_events.insert_one({
            "id": new_id(),
            "event_name": event_name,
            "client_id": client_id,
            "coach_id": coach_id,
            "numeric_value": numeric_value,
            "labels": labels or {},
            "timestamp": now_iso(),
        })
    except Exception as e:  # metric failures never break flow
        logger.warning(f"emit_metric({event_name}) failed: {e}")


# ---------------------------------------------------------------------------
# Idempotent index bootstrapping — called by each module on import
# ---------------------------------------------------------------------------

_INDEXES_CREATED: set[str] = set()


async def ensure_indexes(collection_name: str, index_specs: list[tuple]) -> None:
    """Idempotently create indexes for a V2 collection.

    index_specs entries: (keys, unique_bool, name)
      keys is a list of (field, direction) tuples.
    """
    key = f"{collection_name}::" + ";".join(spec[2] for spec in index_specs)
    if key in _INDEXES_CREATED:
        return
    try:
        coll = getattr(db, collection_name)
        for keys, unique, name in index_specs:
            await coll.create_index(keys, unique=unique, name=name)
        _INDEXES_CREATED.add(key)
    except Exception as e:  # pragma: no cover
        logger.warning(f"ensure_indexes({collection_name}) failed: {e}")


def bg(coro) -> None:
    """Fire-and-forget helper for background index creation on module import."""
    import asyncio as _a
    try:
        loop = _a.get_event_loop()
        if loop and loop.is_running():
            _a.create_task(coro)
        else:  # test / no loop
            loop = _a.new_event_loop()
            loop.run_until_complete(coro)
            loop.close()
    except Exception as e:  # pragma: no cover
        logger.warning(f"bg() failed: {e}")


logger.info("feature_v2_common: helpers loaded")
