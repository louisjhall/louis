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

from server import api, db, current_user, require_role, logger
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


async def _apply_change_setup_manual(*, user: dict, body: ChangeSetupBody, actor: str) -> dict:
    """Manual-Mode hotel-adapt path.

    Applies to clients whose workouts live in `db.workouts` (source=coach_manual)
    rather than in `plan_live_v2.session_specs`. Rather than regenerating
    the session from a construction pool (which doesn't fit Manual Mode's
    "coach picks every exercise" principle), we take the coach's actual
    workout and *filter it down* to what fits the client's declared
    equipment. Exercises that don't fit are moved into a `hotel_dropped`
    array so nothing is lost, and the original prescription is snapshotted
    into `hotel_original_snapshot` for a clean revert.

    Reuses the shared hotel-conversion repair helpers to gate the equipment
    allow-list, run the library-first resolver (so any surviving exercise
    still has an `exercise_id`), and validate the final workout.
    """
    from feature_hotel_conversion_repair import (
        resolve_hotel_spec_with_library, validate_hotel_spec,
        _canonical_allow_list,
    )

    user_id = user["id"]
    env = _ENVIRONMENT_ALIASES.get(body.environment.lower())
    if not env:
        raise HTTPException(400, f"Unknown environment: {body.environment}")

    # Locate the manual workout for this date. If the coach hasn't scheduled
    # one, there's nothing to adapt — be explicit so the client isn't left
    # wondering what went wrong.
    workout = await db.workouts.find_one(
        {"user_id": user_id, "date": body.date, "source": "coach_manual",
         "deactivated": {"$ne": True}},
        {"_id": 0},
    )
    if not workout:
        raise HTTPException(
            404,
            f"No coach-set workout on {body.date}. Ask your coach to add "
            "a session for this day, then adapt it for your hotel.",
        )

    _pool_tags, canonical_equipment = _normalize_equipment(body.equipment or [])
    if env == "bodyweight_only":
        canonical_equipment = []
    profile = user.get("profile") or {}
    allow_list = _canonical_allow_list(
        canonical_equipment,
        bodyweight_disabled=bool(profile.get("bodyweight_disabled")),
    )

    # Snapshot the ORIGINAL prescription once — a revert restores from this.
    original_snapshot = {
        "exercises":  list(workout.get("exercises")  or []),
        "warmup":     list(workout.get("warmup")     or []),
        "cooldown":   list(workout.get("cooldown")   or []),
        "title":      workout.get("title"),
        "duration_min": workout.get("duration_min"),
        "snapshotted_at": _now(),
    }
    # Idempotent — never overwrite an existing snapshot. If a revert is
    # needed later we always want the FIRST (pre-adapt) prescription.
    if not workout.get("hotel_original_snapshot"):
        await db.workouts.update_one(
            {"id": workout["id"]},
            {"$set": {"hotel_original_snapshot": original_snapshot}},
        )

    # Build a synthetic spec so we can reuse the same library-first pass
    # the V2 hotel path uses. Merge warmup + main so the resolver treats
    # the whole session consistently, then split them back afterwards.
    synthetic_spec = {
        "kind": workout.get("focus") or workout.get("workout_type") or "session",
        "duration_min": workout.get("duration_min") or 30,
        "environment": env,
        "payload": {
            "exercises": [
                {**e, "_bucket": "main"} for e in (workout.get("exercises") or [])
            ] + [
                {**e, "_bucket": "warmup"} for e in (workout.get("warmup") or [])
            ] + [
                {**e, "_bucket": "cooldown"} for e in (workout.get("cooldown") or [])
            ],
        },
    }

    try:
        resolved_spec, conv_summary = await resolve_hotel_spec_with_library(
            synthetic_spec, allow_list=allow_list, client=user,
            workout_date=body.date, workout_id=workout["id"],
        )
    except Exception:
        logger.exception("manual hotel_adapt: resolver failed for wid=%s", workout["id"])
        raise HTTPException(500, "Could not adapt the workout for that hotel setup.")

    vres = validate_hotel_spec(resolved_spec, allow_list=allow_list)
    kept = resolved_spec.get("payload", {}).get("exercises") or []
    kept_main     = [{k: v for k, v in e.items() if k != "_bucket"}
                     for e in kept if e.get("_bucket") == "main"]
    kept_warmup   = [{k: v for k, v in e.items() if k != "_bucket"}
                     for e in kept if e.get("_bucket") == "warmup"]
    kept_cooldown = [{k: v for k, v in e.items() if k != "_bucket"}
                     for e in kept if e.get("_bucket") == "cooldown"]

    # If NOTHING survived (bodyweight-only with a heavy strength session),
    # drop a friendly, safe bodyweight session so the client isn't stranded
    # with a blank workout.
    if not kept_main:
        kept_main = [
            {"name": "Bodyweight Squat",   "sets": 3, "reps": "15",
             "rest_sec": 45, "notes": "Slow tempo, full range.",
             "hotel_adapted_fallback": True},
            {"name": "Push-Up (or incline)", "sets": 3, "reps": "10-15",
             "rest_sec": 45, "notes": "Use hotel bed or desk to scale.",
             "hotel_adapted_fallback": True},
            {"name": "Plank",              "sets": 3, "reps": "30s",
             "rest_sec": 30, "notes": "Braced, glutes on.",
             "hotel_adapted_fallback": True},
        ]

    # Persist the adapted workout in place. Coach can still audit + revert.
    now = _now()
    await db.workouts.update_one(
        {"id": workout["id"]},
        {"$set": {
            "exercises": kept_main,
            "warmup": kept_warmup,
            "cooldown": kept_cooldown,
            "hotel_adapted": True,
            "hotel_adapted_at": now,
            "hotel_adapted_by": actor,
            "hotel_adapted_environment": env,
            "hotel_adapted_equipment": canonical_equipment,
            "hotel_adapted_summary": conv_summary,
            "hotel_adapted_validation": vres,
            "updated_at": now,
        }},
    )

    return {
        "ok": True,
        "mode": "manual",
        "workout_id": workout["id"],
        "date": body.date,
        "environment": env,
        "equipment": canonical_equipment,
        "kept_main": len(kept_main),
        "kept_warmup": len(kept_warmup),
        "kept_cooldown": len(kept_cooldown),
        "summary": conv_summary,
        "validation": vres,
        "message": (
            "Workout adapted for your hotel setup. "
            f"Kept {len(kept_main)} main exercise(s)."
            + (" Coach will review any newly added exercises."
               if conv_summary.get("drafts_created") else "")
        ),
    }


async def _apply_change_setup(*, user: dict, body: ChangeSetupBody, actor: str) -> dict:
    user_id = user["id"]
    live = await _load_active_live(user_id)
    if not live:
        # Manual-Mode fallback — no V2 Live plan exists. Route the request
        # to the manual workout path so the client can still adapt their
        # coach-built session for a hotel gym.
        return await _apply_change_setup_manual(user=user, body=body, actor=actor)
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

    # Hotel-Conversion Repair — pull the client's injury / no-go list so the
    # deterministic constructor can avoid contraindicated patterns instead
    # of receiving an empty avoid-set. Reuses existing profile fields.
    from feature_hotel_conversion_repair import (
        resolve_hotel_spec_with_library, validate_hotel_spec,
        _canonical_allow_list,
    )
    profile = user.get("profile") or {}
    injuries_str = str(profile.get("injuries") or "").lower()
    no_go = profile.get("no_go_movements") or []
    if isinstance(no_go, str):
        no_go = [t.strip() for t in no_go.split(",") if t.strip()]
    avoid_patterns: set[str] = set()
    for kw in ("knee", "back", "shoulder", "elbow", "hip", "ankle", "wrist"):
        if kw in injuries_str:
            avoid_patterns.add(kw)
    for m in no_go or []:
        avoid_patterns.add(str(m).lower())

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
            equipment_ctx=equipment_ctx, avoid_patterns=avoid_patterns,
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

    # Hotel-Conversion Repair — library-first pass + hard equipment gate.
    # 1) Every exercise in the spec is looked up in exercises_v2 first.
    # 2) Missing exercises get a draft library record (dedup'd) and the
    #    coach media queue is bumped with urgency based on workout date.
    # 3) Deterministic validation refuses to save an invalid conversion.
    allow_list = _canonical_allow_list(
        canonical_equipment,
        bodyweight_disabled=bool(profile.get("bodyweight_disabled")),
    )
    # Non-strength sessions (running / cycling / swim) don't carry an
    # `exercises` list — skip the pass so we don't spuriously reject them.
    _payload = new_spec.get("payload") or {}
    if _payload.get("exercises"):
        try:
            new_spec, conv_summary = await resolve_hotel_spec_with_library(
                new_spec, allow_list=allow_list, client=user,
                workout_date=body.date, workout_id=None,
            )
        except Exception:
            logger.exception("hotel_repair: library resolution failed — proceeding with best-effort spec")
            conv_summary = {"warnings": ["library resolution errored — see server logs"]}
        # Deterministic validation gate.
        vres = validate_hotel_spec(new_spec, allow_list=allow_list)
        if not vres.get("ok"):
            raise HTTPException(
                400,
                "Converted workout failed equipment/library validation: "
                + " · ".join(vres.get("errors") or []),
            )

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


# ---------------------------------------------------------------------------
# Iter 130b — Revert Change Setup.
# ---------------------------------------------------------------------------
# Deactivate the active `plan_live_v2_implementations` row for a placement
# so the client / coach sees the original programme setup again. The
# original row is preserved (`is_active=false, superseded_by='revert'`) so
# the audit trail is intact. No spec mutation, no regeneration — just flips
# a boolean.

class RevertChangeSetupBody(BaseModel):
    date: str = Field(..., description="ISO date whose Change Setup override should be reverted.")


async def _apply_revert_change_setup(*, user: dict, body: RevertChangeSetupBody, actor: str) -> dict:
    user_id = user["id"]
    # Count what's active before we flip anything, so we can tell the caller
    # whether the revert did anything (idempotent, no throw).
    active_before = await db.plan_live_v2_implementations.count_documents(
        {"client_id": user_id, "date": body.date, "is_active": True},
    )
    if active_before == 0:
        # Manual-Mode fallback — no V2 impl to revert. Try to restore the
        # manual workout from its `hotel_original_snapshot` if one exists.
        manual_workout = await db.workouts.find_one(
            {"user_id": user_id, "date": body.date, "source": "coach_manual",
             "hotel_original_snapshot": {"$exists": True}},
            {"_id": 0},
        )
        if manual_workout:
            snap = manual_workout.get("hotel_original_snapshot") or {}
            now = _now()
            await db.workouts.update_one(
                {"id": manual_workout["id"]},
                {"$set": {
                    "exercises": snap.get("exercises") or [],
                    "warmup":    snap.get("warmup")    or [],
                    "cooldown":  snap.get("cooldown")  or [],
                    "hotel_adapted": False,
                    "hotel_reverted_at": now,
                    "hotel_reverted_by": actor,
                    "updated_at": now,
                }},
            )
            return {
                "ok": True, "mode": "manual", "date": body.date,
                "reverted_count": 1, "actor": actor,
                "message": f"Restored original workout for {body.date}.",
            }
        return {
            "ok": True,
            "date": body.date,
            "reverted_count": 0,
            "message": "No active Change Setup override on this date — already at original setup.",
        }
    res = await db.plan_live_v2_implementations.update_many(
        {"client_id": user_id, "date": body.date, "is_active": True},
        {"$set": {
            "is_active": False,
            "superseded_at": _now(),
            "superseded_by": f"revert_{actor}",
        }},
    )
    return {
        "ok": True,
        "date": body.date,
        "reverted_count": int(res.modified_count),
        "actor": actor,
        "message": f"Reverted to original setup for {body.date}.",
    }


@api.post("/v2/client/plan/adapt-live/revert")
async def client_revert_adapt_live(
    body: RevertChangeSetupBody,
    user: dict = Depends(current_user),
) -> dict:
    return await _apply_revert_change_setup(user=user, body=body, actor="client")


@api.post("/v2/coach/clients/{client_id}/plan/adapt-live/revert")
async def coach_revert_adapt_live(
    client_id: str, body: RevertChangeSetupBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found.")
    return await _apply_revert_change_setup(user=client, body=body, actor="coach")
