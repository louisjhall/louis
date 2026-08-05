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
import os
from typing import Any, Optional

from fastapi import HTTPException

from server import db, new_id, now_iso, logger


# ---------------------------------------------------------------------------
# MANUAL_MODE — strategic pivot pause switch (Phase M-1 / 1A).
#
# When MANUAL_MODE=true, all automatic programme-generation endpoints must
# return 403. Roster upload/parse/confirm still work, but their downstream
# workout-generation blocks are skipped. Flight Support is NOT affected.
#
# Reversible: unset the env var (or set to false) to restore auto-generation.
# ---------------------------------------------------------------------------
def is_manual_mode() -> bool:
    return os.getenv("MANUAL_MODE", "false").strip().lower() in ("1", "true", "yes", "on")


def require_auto_gen_allowed(override: bool = False) -> None:
    """Raise 403 if MANUAL_MODE is active. Call at the top of every
    endpoint that writes to db.workouts / db.plan_drafts_v2 / db.plan_live_v2
    as part of automatic programme generation.

    `override=True` bypasses the gate — used for per-client manual draft
    builds (e.g. restored clients where the coach explicitly wants a V2
    draft shell that will be overwritten by a manual JSON import).
    Callers must compute the override themselves via
    `check_manual_override_for_client(client_id)` and pass the boolean in.
    """
    if override:
        return
    if is_manual_mode():
        raise HTTPException(
            status_code=403,
            detail="Manual mode active — automatic programme generation is paused.",
        )


async def check_manual_override_for_client(client_id: str) -> bool:
    """Return True if this client has `profile.v2_flags.manual_draft_override`
    set, permitting a one-off V2 kickoff / publish while MANUAL_MODE is
    still globally active. Safe to call under any mode — returns False if
    the user or flag is missing.
    """
    if not client_id:
        return False
    try:
        u = await db.users.find_one(
            {"id": client_id},
            {"_id": 0, "profile": 1},
        )
    except Exception:
        return False
    if not u:
        return False
    flags = ((u.get("profile") or {}).get("v2_flags") or {})
    return bool(flags.get("manual_draft_override"))


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
# P0-6: DNA → V2 collection sync (restrictions + equipment_contexts)
# ---------------------------------------------------------------------------

# Free-text injury keyword → structured restriction row.
# Keeps the map narrow — anything that doesn't match becomes a generic
# "general" restriction so nothing is silently dropped.
_INJURY_KEYWORDS: dict[str, dict] = {
    "knee":      {"region": "knee",      "avoid_patterns": ["deep_squat", "lunge", "gait_run_tempo"]},
    "acl":       {"region": "knee",      "avoid_patterns": ["deep_squat", "lateral_bound", "gait_run_tempo"]},
    "meniscus":  {"region": "knee",      "avoid_patterns": ["deep_squat", "lunge"]},
    "hip":       {"region": "hip",       "avoid_patterns": ["deep_squat", "hip_flex_heavy"]},
    "back":      {"region": "lower_back","avoid_patterns": ["heavy_hinge", "overhead_press_heavy"]},
    "lumbar":    {"region": "lower_back","avoid_patterns": ["heavy_hinge", "overhead_press_heavy"]},
    "spine":     {"region": "lower_back","avoid_patterns": ["heavy_hinge"]},
    "shoulder":  {"region": "shoulder",  "avoid_patterns": ["overhead_press_heavy", "vertical_push"]},
    "rotator":   {"region": "shoulder",  "avoid_patterns": ["overhead_press_heavy", "vertical_pull"]},
    "elbow":     {"region": "elbow",     "avoid_patterns": ["heavy_horizontal_push"]},
    "wrist":     {"region": "wrist",     "avoid_patterns": ["heavy_horizontal_push", "front_rack_hold"]},
    "ankle":     {"region": "ankle",     "avoid_patterns": ["gait_run_tempo", "lateral_bound"]},
    "foot":      {"region": "foot",      "avoid_patterns": ["gait_run_tempo", "gait_run_long"]},
    "plantar":   {"region": "foot",      "avoid_patterns": ["gait_run_tempo", "gait_run_long"]},
    "achilles":  {"region": "ankle",     "avoid_patterns": ["gait_run_tempo", "lateral_bound"]},
    "neck":      {"region": "neck",      "avoid_patterns": ["overhead_press_heavy"]},
    "concussion":{"region": "head",      "avoid_patterns": ["overhead_press_heavy", "gait_run_tempo"]},
    "pregnancy": {"region": "trunk",     "avoid_patterns": ["heavy_hinge", "supine_load"]},
    "hernia":    {"region": "trunk",     "avoid_patterns": ["heavy_hinge", "valsalva_heavy"]},
}


def _parse_injury_freetext(text: str) -> list[dict]:
    """Turn a free-text injury string into 0..N structured restriction rows.
    Empty / 'none' / 'no injuries' string → empty list.
    """
    t = (text or "").strip().lower()
    if not t or t in ("none", "no", "no injuries", "no restrictions", "n/a", "na", "-"):
        return []
    matched: list[dict] = []
    for kw, meta in _INJURY_KEYWORDS.items():
        if kw in t:
            matched.append({
                "region": meta["region"],
                "severity": "moderate",
                "avoid_patterns": meta["avoid_patterns"],
                "raw_text": text,
                "source": "profile.injuries",
            })
    if not matched:
        # Fallback — we couldn't map it, but the client told us SOMETHING
        matched.append({
            "region": "general",
            "severity": "moderate",
            "avoid_patterns": [],
            "raw_text": text,
            "source": "profile.injuries",
        })
    return matched


async def sync_restrictions_from_profile(client_id: str) -> int:
    """Upsert `restrictions` collection rows from user profile.

    Sources (any of):
      - profile.injuries (free text)
      - profile.persistent_restrictions (list of {region, avoid_patterns, severity})

    Returns number of restriction rows now stored for the client.
    """
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        return 0
    prof = user.get("profile") or {}
    rows: list[dict] = []

    # Structured list first
    for r in prof.get("persistent_restrictions") or []:
        if not isinstance(r, dict):
            continue
        rows.append({
            "region": (r.get("region") or "general").lower(),
            "severity": r.get("severity") or "moderate",
            "avoid_patterns": list(r.get("avoid_patterns") or []),
            "raw_text": r.get("raw_text") or r.get("description") or "",
            "source": "profile.persistent_restrictions",
        })

    # Free-text injuries
    inj = prof.get("injuries") or prof.get("injury") or ""
    if isinstance(inj, str):
        rows.extend(_parse_injury_freetext(inj))
    elif isinstance(inj, list):
        for item in inj:
            if isinstance(item, str):
                rows.extend(_parse_injury_freetext(item))
            elif isinstance(item, dict):
                rows.append({
                    "region": (item.get("region") or "general").lower(),
                    "severity": item.get("severity") or "moderate",
                    "avoid_patterns": list(item.get("avoid_patterns") or []),
                    "raw_text": item.get("raw_text") or item.get("description") or "",
                    "source": "profile.injuries",
                })

    # Wipe & re-insert (idempotent), keeping any coach-added rows
    await db.restrictions.delete_many(
        {"client_id": client_id, "source": {"$in": ["profile.injuries", "profile.persistent_restrictions"]}}
    )
    for r in rows:
        await db.restrictions.insert_one({
            "id": new_id(),
            "client_id": client_id,
            "region": r["region"],
            "severity": r["severity"],
            "avoid_patterns": r["avoid_patterns"],
            "raw_text": r["raw_text"],
            "source": r["source"],
            "status": "active",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
    return len(rows)


async def sync_equipment_context_from_profile(client_id: str) -> Optional[str]:
    """Upsert a `permanent`-scope equipment_context from the user profile.

    Reads from (in priority order):
      profile.equipment  →  list[str] or list[dict]
      profile.home_equipment → list[str]
      profile.equipment_permanent → list[dict] (already structured, coach-set)

    Returns the equipment_context.id (or None if nothing to sync).
    """
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        return None
    prof = user.get("profile") or {}
    equip: set[str] = set()
    for src_key in ("equipment", "home_equipment", "equipment_permanent"):
        v = prof.get(src_key)
        if not v:
            continue
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    equip.add(item.strip().lower())
                elif isinstance(item, dict):
                    for e in (item.get("equipment") or []):
                        equip.add(str(e).strip().lower())
        elif isinstance(v, str):
            equip.add(v.strip().lower())
    # Always keep bodyweight as a floor so P6 never fails
    equip.add("bodyweight")
    equip.discard("")

    # Upsert a permanent-scope context for this client
    existing = await db.equipment_contexts.find_one(
        {"client_id": client_id, "scope": "permanent", "source": "profile_sync"}, {"_id": 0}
    )
    if existing:
        await db.equipment_contexts.update_one(
            {"id": existing["id"]},
            {"$set": {
                "equipment": sorted(equip),
                "detail": {"home_base": prof.get("home_base"), "airline": prof.get("airline")},
                "updated_at": now_iso(),
            }}
        )
        return existing["id"]
    cid = new_id()
    await db.equipment_contexts.insert_one({
        "id": cid,
        "client_id": client_id,
        "source": "profile_sync",
        "scope": "permanent",
        "equipment": sorted(equip),
        "detail": {"home_base": prof.get("home_base"), "airline": prof.get("airline")},
        "valid_from": now_iso(),
        "valid_until": None,
        "created_at": now_iso(),
        "created_by": "system",
    })
    return cid


async def sync_dna_to_v2_collections(client_id: str) -> dict:
    """One-shot: mirror DNA fields into restrictions + equipment_contexts.
    Safe to call any time (idempotent). Returns counts."""
    n_restrictions = await sync_restrictions_from_profile(client_id)
    ec_id = await sync_equipment_context_from_profile(client_id)
    return {
        "restrictions_written": n_restrictions,
        "equipment_context_id": ec_id,
    }


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
