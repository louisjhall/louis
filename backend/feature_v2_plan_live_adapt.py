"""
feature_v2_plan_live_adapt — HOW-only adaptation of a published V2 Live plan
============================================================================

Iter 118 · Change Setup for hotel / travel workouts.

Design contract (agreed with product):
- NEVER mutate `plan_live_v2.session_specs[eid]` in place.
- The published programme structure remains auditable; a client changing
  environment/equipment is producing a *variant* on top of that structure.
- Uses a dedicated collection `plan_live_v2_implementations` that stores:
    { client_id, live_plan_id, exposure_id, date, environment, equipment[],
      scope, valid_from, valid_until, spec_snapshot,
      original_spec_snapshot, actor, created_at, is_active }
  Only ONE row is `is_active: true` per (client_id, exposure_id, date).
- `feature_v2_client_bridge.synth_workouts_for_user` reads the active
  implementation for the placement and prefers it over the original
  `session_specs[eid]` — see companion patch there.
- Preserves: exposure_id, kind, priority, date, ObjectiveExposure identity,
  placement, programme quota. NO regeneration, NO LLM.
- Reuses `feature_v2_construction_v2.build_session_spec` for deterministic
  regeneration of `spec.payload` under the new equipment context.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Depends, Body
from pydantic import BaseModel, Field

from server import api, db, current_user, require_role
from feature_v2_construction_v2 import build_session_spec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChangeSetupBody(BaseModel):
    date: str = Field(..., description="ISO date of the placement being adapted.")
    environment: str = Field(
        ...,
        description=("hotel_room | hotel_gym | outdoor | treadmill | gym | "
                     "home | bodyweight_only | flexible"),
    )
    equipment: list[str] = Field(default_factory=list)
    scope: str = Field("this_session",
                        description="this_session | today | this_layover")


_ENVIRONMENT_ALIASES = {
    "hotel_room": "hotel_room",
    "hotel_gym":  "hotel_gym",
    "outdoor":    "outdoor",
    "treadmill":  "treadmill",
    "gym":        "gym",
    "home":       "home",
    "bodyweight": "bodyweight_only",
    "bodyweight_only": "bodyweight_only",
    "flexible":   "flexible",
    "other":      "hotel_room",  # coach-only fallback
}


# Iter 119 — Equipment chip normalization.
# The Change Setup UI exposes user-friendly chips (e.g. "Cable Machine",
# "Smith Machine", "Lat Pulldown", "Bike") that must map onto the tags the
# deterministic construction pool understands. Everything is explicit —
# there is no silent "add dumbbells for hotel_gym" assumption anywhere.
# A chip may expand into multiple pool tags (e.g. Barbell implies rack in a
# hotel-gym context; Smith Machine substitutes for rack+barbell lifts).
_EQUIPMENT_ALIASES: dict[str, list[str]] = {
    # canonical pass-throughs
    "dumbbells":         ["dumbbells"],
    "bench":             ["bench"],
    "kettlebell":        ["kettlebell"],
    "band":              ["band"],
    "resistance_bands":  ["band"],           # UI legacy → pool tag
    "bands":             ["band"],           # tolerate plural
    "mat":               ["mat"],
    "yoga_mat":          ["mat"],
    "treadmill":         ["treadmill"],
    "pool":              ["pool"],
    "rings":             ["rings"],
    "pull_up_bar":       ["pull_up_bar"],
    "box":               ["box"],
    "rack":              ["rack"],
    "bar":               ["bar"],
    # gym machines / compound implements
    "barbell":           ["barbell", "rack"],       # gym barbell implies rack
    "smith_machine":     ["smith_machine", "barbell", "rack"],  # substitutes for barbell+rack lifts
    "cable_stack":       ["cable_stack"],
    "cable_machine":     ["cable_stack"],
    "cable":             ["cable_stack"],
    "lat_pulldown":      ["cable_stack"],           # same modality as cable_stack pulldown
    "leg_press":         ["leg_press"],             # tag stored for audit; no pool substitution
    "bike":              ["bike", "indoor_trainer"],
    "indoor_trainer":    ["bike", "indoor_trainer"],
}


def _normalize_equipment(items: list[str]) -> tuple[set[str], list[str]]:
    """Turn UI chip keys into pool tags. Returns (pool_tags, canonical_list).
    `pool_tags` is fed to the deterministic constructor (issubset filter).
    `canonical_list` is stored in the overlay for audit + display, keeping
    original chip identity (so the client can see "Smith Machine · Cable"
    rather than the expanded pool tags)."""
    pool: set[str] = set()
    canon: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        key = str(raw or "").strip().lower().replace(" ", "_")
        if not key or key in seen:
            continue
        seen.add(key)
        tags = _EQUIPMENT_ALIASES.get(key)
        if tags is None:
            # Unknown chip — trust the client, pass through as-is.
            pool.add(key)
            canon.append(key)
        else:
            pool.update(tags)
            canon.append(key)
    return pool, canon


async def _load_active_live(user_id: str) -> Optional[dict]:
    return await db.plan_live_v2.find_one(
        {"client_id": user_id, "active": True}, {"_id": 0},
    )


async def _load_placement(live: dict, date: str) -> Optional[dict]:
    for p in (live.get("placements") or []):
        if p.get("date") == date:
            return p
    return None


async def _resolve_layover_range(user_id: str, date: str) -> tuple[str, str]:
    """Given a layover date, return (from, to) covering the whole layover
    block (contiguous layover_* days) so `this_layover` scope expires
    correctly. Falls back to (date, date) when the day isn't a layover."""
    roster = await db.rosters.find_one(
        {"user_id": user_id, "is_active": True, "confirmed": True},
        {"_id": 0, "days": 1},
    )
    if not roster:
        return date, date
    days = sorted(roster.get("days") or [], key=lambda d: d.get("date") or "")
    target_idx = next((i for i, d in enumerate(days) if d.get("date") == date), -1)
    if target_idx < 0:
        return date, date
    dt = str(days[target_idx].get("day_type") or "").lower()
    if "layover" not in dt:
        return date, date
    # Walk backwards + forwards while day_type is layover*
    lo, hi = target_idx, target_idx
    while lo > 0 and "layover" in str(days[lo - 1].get("day_type") or "").lower():
        lo -= 1
    while hi + 1 < len(days) and "layover" in str(days[hi + 1].get("day_type") or "").lower():
        hi += 1
    return days[lo]["date"], days[hi]["date"]


async def _apply_change_setup(*, user: dict, body: ChangeSetupBody, actor: str) -> dict:
    user_id = user["id"]
    live = await _load_active_live(user_id)
    if not live:
        raise HTTPException(404, "No active V2 Live plan for this client.")
    placement = await _load_placement(live, body.date)
    if not placement:
        raise HTTPException(404, f"No placement on {body.date}.")
    eid = placement.get("exposure_id") or ""
    original_spec = dict((live.get("session_specs") or {}).get(eid) or {})

    env = _ENVIRONMENT_ALIASES.get(body.environment.lower())
    if not env:
        raise HTTPException(400, f"Unknown environment: {body.environment}")

    # Build a temporary equipment_ctx that the constructor understands.
    # `bodyweight` is always available. Iter 119 — Chip labels are normalized
    # into pool tags (e.g. Barbell → barbell+rack, Smith Machine → barbell+rack).
    # NO SILENT ASSUMPTIONS: if the client selects Hotel Gym with zero
    # equipment, they get a bodyweight-safe strength session — not a stealth
    # dumbbells session.
    pool_tags, canonical_equipment = _normalize_equipment(body.equipment or [])
    equipment_ctx = set(pool_tags)
    equipment_ctx.add("bodyweight")
    if env == "treadmill":
        equipment_ctx.add("treadmill")
    # `bodyweight_only` env explicitly means: strip everything except bodyweight
    if env == "bodyweight_only":
        equipment_ctx = {"bodyweight"}
        canonical_equipment = []

    # Reuse Engine V2's construction to deterministically rebuild the spec
    # payload under the new environment/equipment — WHAT/WHEN untouched.
    kind = placement.get("kind") or original_spec.get("kind") or "session"
    duration = int(original_spec.get("duration_min")
                    or placement.get("target_duration_min") or 30)
    phase_kind = original_spec.get("phase_kind") or "foundation"
    intensity = original_spec.get("intensity_target") or "low"
    day_type_for_env = env if env in ("hotel_room", "hotel_gym", "outdoor",
                                         "treadmill", "gym", "home",
                                         "bodyweight_only")\
        else str(placement.get("day_type") or "layover")

    try:
        new_spec_obj = build_session_spec(
            kind=kind, duration_min=duration, phase_kind=phase_kind,
            intensity_target=intensity, day_type=day_type_for_env,
            equipment_ctx=equipment_ctx, avoid_patterns=set(),
        )
        # SessionSpec dataclass → dict
        new_spec = {
            "spec_kind": new_spec_obj.spec_kind,
            "kind": new_spec_obj.kind,
            "duration_min": new_spec_obj.duration_min,
            "intensity_target": new_spec_obj.intensity_target,
            "environment": env,
            "equipment_used": canonical_equipment or (
                sorted(list(new_spec_obj.equipment_used)) or ["bodyweight"]
            ),
            "payload": new_spec_obj.payload,
            "rationale": (original_spec.get("rationale") or "")
                         + f"  |  Change Setup → {env} ({actor}).",
            "adapted_from_original": True,
            "original_environment": original_spec.get("environment"),
        }
    except Exception:
        # Never fail the client: fall back to a minimal spec that keeps the
        # same duration but reflects the new environment/equipment.
        new_spec = dict(original_spec)
        new_spec["environment"] = env
        new_spec["equipment_used"] = canonical_equipment or ["bodyweight"]
        new_spec["rationale"] = (original_spec.get("rationale") or "") \
                                 + f"  |  Change Setup → {env} ({actor}) [fallback]."
        new_spec["adapted_from_original"] = True
        new_spec["original_environment"] = original_spec.get("environment")

    # Resolve scope → valid_until
    valid_from = _now()
    valid_until: Optional[str] = None
    scope = body.scope.lower()
    if scope == "this_session":
        valid_until = None  # tied to placement date; consumer checks date
    elif scope == "today":
        valid_until = None
    elif scope == "this_layover":
        # find layover range
        lo, hi = await _resolve_layover_range(user_id, body.date)
        valid_until = hi
    else:
        raise HTTPException(400, "scope must be this_session | today | this_layover")

    # Deactivate any prior active implementation for the same (exposure_id, date)
    await db.plan_live_v2_implementations.update_many(
        {"client_id": user_id, "exposure_id": eid,
         "is_active": True,
         # scope-narrowed: for this_layover we only supersede overlapping ones
         **({"date_range_end": {"$gte": body.date}} if scope == "this_layover" else {"date": body.date}),
        },
        {"$set": {"is_active": False,
                  "superseded_at": _now(),
                  "superseded_by": "change_setup"}},
    )

    row = {
        "id": str(uuid.uuid4()),
        "client_id": user_id,
        "live_plan_id": live["id"],
        "exposure_id": eid,
        "date": body.date,
        "date_range_start": body.date,
        "date_range_end": valid_until or body.date,
        "scope": scope,
        "environment": env,
        "equipment": canonical_equipment,
        "spec_snapshot": new_spec,
        "original_spec_snapshot": original_spec,
        "actor": actor,
        "actor_id": user["id"],
        "created_at": _now(),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "is_active": True,
    }
    await db.plan_live_v2_implementations.insert_one(row)

    return {
        "ok": True,
        "exposure_id": eid,
        "date": body.date,
        "environment": env,
        "equipment": canonical_equipment,
        "scope": scope,
        "valid_until": valid_until,
        "implementation_id": row["id"],
        "spec": {
            "duration_min": new_spec.get("duration_min"),
            "environment": new_spec.get("environment"),
            "equipment_used": new_spec.get("equipment_used"),
            "rationale": new_spec.get("rationale"),
        },
    }


@api.post("/v2/client/plan/adapt-live")
async def client_adapt_live(
    body: ChangeSetupBody,
    user: dict = Depends(current_user),
) -> dict:
    return await _apply_change_setup(user=user, body=body, actor="client")


@api.post("/v2/coach/clients/{client_id}/plan/adapt-live")
async def coach_adapt_live(
    client_id: str, body: ChangeSetupBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found.")
    return await _apply_change_setup(user=client, body=body, actor="coach")


@api.get("/v2/client/plan/live/implementations/{date}")
async def client_live_implementation_for_date(
    date: str, user: dict = Depends(current_user),
) -> dict:
    """Inspect the active implementation override for a placement date."""
    row = await db.plan_live_v2_implementations.find_one(
        {"client_id": user["id"], "date": date, "is_active": True}, {"_id": 0},
    )
    return {"date": date, "implementation": row}
