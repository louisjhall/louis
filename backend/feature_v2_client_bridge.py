"""
feature_v2_client_bridge — Legacy /workouts/* → Engine V2 bridge (client-side)
==============================================================================

Engine V2 stores each client's Live plan in `plan_live_v2` (placements +
session_specs), NOT in the legacy `workouts` collection. The client-side
Expo app still reads from `/workouts/week`, `/workouts/{id}`, and
`/calendar/timeline` — so V2 clients see an empty dashboard even after
publishing.

This module produces synthetic *workout-shaped* dicts from the active
plan_live_v2 for a given date window, so the legacy endpoints can splice
them into their responses without disturbing V1 behaviour.

Synthetic IDs are `v2p:{live_id}:{exposure_id}` — matching the coach
workspace convention. They resolve back to placement+session_spec via
`build_synth_workout_for_wid`.
"""
from __future__ import annotations

from typing import Any, Optional


V2_WORKOUT_ID_PREFIX = "v2p:"


def _humanise(s: Optional[str]) -> str:
    if not s:
        return ""
    return s.replace("_", " ").replace("-", " ").title()


def _spec_to_blocks(spec: dict) -> list[dict]:
    """Convert a SessionSpec payload into the legacy `blocks[]` shape the
    client workout screens already know how to render (P0-1/P1-3)."""
    spec_kind = spec.get("spec_kind") or ""
    payload = spec.get("payload") or {}
    blocks: list[dict] = []

    def _push(t: str, blk: Optional[dict]):
        if not blk:
            return
        dur = blk.get("duration_min") or 0
        if not dur:
            return
        item = {
            "type": t,
            "duration_min": dur,
        }
        for k in ("hr_zone", "pace_target", "power_target", "cadence",
                  "effort_rpe", "cue", "fuel_cue"):
            v = blk.get(k)
            if v is not None:
                item[k] = v
        if blk.get("reps") is not None:
            item["sets"] = blk.get("reps")
        for k in ("work_sec", "rest_sec"):
            v = blk.get(k)
            if v is not None:
                item[k] = v
        blocks.append(item)

    if spec_kind in ("running", "cycling", "swimming", "brick"):
        _push("warmup", payload.get("warmup"))
        main = payload.get("main") or {}
        _push(main.get("type") or "main", main)
        _push("cooldown", payload.get("cooldown"))
        for seg in (payload.get("segments") or []):
            _push(seg.get("type") or seg.get("modality") or "segment", seg)
    elif spec_kind in ("mobility", "recovery", "activation", "travel_recovery"):
        for b in (payload.get("flow_blocks") or payload.get("blocks") or []):
            _push(b.get("name") or b.get("type") or "block", {
                "duration_min": b.get("duration_min")
                                or (int(round((b.get("duration_sec") or 0) / 60))
                                    if b.get("duration_sec") else 0),
                "cue": b.get("cue"),
            })

    return blocks


def _spec_to_exercises(spec: dict) -> list[dict]:
    """Convert a strength SessionSpec payload into the legacy exercise list
    shape used by /workouts/[id]/index.tsx."""
    if spec.get("spec_kind") != "strength":
        return []
    out: list[dict] = []
    for ex in (spec.get("payload") or {}).get("exercises") or []:
        out.append({
            "name": ex.get("name") or ex.get("exercise") or "Exercise",
            "exercise_name_display": ex.get("name") or ex.get("exercise") or "Exercise",
            "sets": ex.get("sets"),
            "reps": ex.get("reps"),
            "rpe": ex.get("rpe") or ex.get("load_target"),
            "load_target": ex.get("load_target"),
            "rest_sec": ex.get("rest_sec"),
            "notes": ex.get("cue") or ex.get("notes"),
        })
    return out


def synth_workout_from_placement(
    *, live_id: str, placement: dict, spec: dict, user_id: str,
) -> dict:
    """Build a legacy-shaped workout dict from one (placement, session_spec).
    Returns None for rest placements — the client renders them as "Rest"
    without a workout row."""
    kind = placement.get("kind") or spec.get("kind") or "session"
    if kind == "rest":
        return None
    eid = placement.get("exposure_id") or ""
    duration = int(spec.get("duration_min")
                    or placement.get("target_duration_min") or 0)
    focus = spec.get("spec_kind") or kind
    exercises = _spec_to_exercises(spec)
    blocks = _spec_to_blocks(spec)
    equipment_used = list(spec.get("equipment_used") or [])
    env = spec.get("environment")
    if env and env not in ("any", "none", "?"):
        location = env
    else:
        location = None
    return {
        "id": f"{V2_WORKOUT_ID_PREFIX}{live_id}:{eid}",
        "user_id": user_id,
        "date": placement.get("date"),
        "title": _humanise(kind) or "Session",
        "focus": focus,
        "duration_min": duration,
        "day_load": 3 if bool(placement.get("key")) else 2,
        "key_session": bool(placement.get("key")),
        "location": location,
        "needs_coach_review": bool(spec.get("coach_review_required")),
        "approved": True,      # V2 Live is by definition coach-approved
        "coach_locked": True,  # V2 clients cannot edit Live
        "completed": False,
        "coach_notes": "",
        "rationale": spec.get("rationale") or "",
        "warmup": (spec.get("payload") or {}).get("warmup") or None,
        "exercises": exercises,
        "blocks": blocks,
        "alternatives": [],
        "variants": [],
        "event_phase": None,
        "source": "engine_v2",
        # Metadata the client screens can use for badges / rationale panels
        "v2_placement": True,
        "v2_source": "live",
        "v2_source_id": live_id,
        "v2_exposure_id": eid,
        "v2_intensity_target": (placement.get("intensity_target")
                                 or spec.get("intensity_target")),
        "v2_exposure_number": placement.get("exposure_number"),
        "v2_priority": placement.get("priority"),
        "equipment_used": equipment_used,
        "environment": env,
    }


async def synth_workouts_for_user(
    db, user_id: str, *,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
) -> list[dict]:
    """Return legacy-shaped workout rows for a client's active plan_live_v2.
    Silently returns [] when no active V2 plan or client is not V2-flagged."""
    user = await db.users.find_one(
        {"id": user_id}, {"_id": 0, "profile.v2_flags": 1},
    )
    if not user:
        return []
    flags = (user.get("profile") or {}).get("v2_flags") or {}
    if not (flags.get("engine_v2") or flags.get("v2_default")):
        return []
    live = await db.plan_live_v2.find_one(
        {"client_id": user_id, "active": True}, {"_id": 0},
    )
    if not live:
        return []
    live_id = live.get("id")
    placements = live.get("placements") or []
    specs = live.get("session_specs") or {}
    out: list[dict] = []
    for p in placements:
        d = p.get("date")
        if not d:
            continue
        if start_iso and d < start_iso:
            continue
        if end_iso and d > end_iso:
            continue
        eid = p.get("exposure_id") or ""
        spec = specs.get(eid) or {}
        row = synth_workout_from_placement(
            live_id=live_id, placement=p, spec=spec, user_id=user_id,
        )
        if row is not None:
            out.append(row)
    return out


async def synth_workout_by_wid(db, wid: str, user_id: str) -> Optional[dict]:
    """Resolve a `v2p:{live_id}:{exposure_id}` id back to a legacy-shaped
    workout row, or None if the source doc no longer matches."""
    if not (wid or "").startswith(V2_WORKOUT_ID_PREFIX):
        return None
    parts = wid.split(":", 2)
    if len(parts) < 3:
        return None
    live_id = parts[1]
    exposure_id = parts[2]
    live = await db.plan_live_v2.find_one(
        {"id": live_id, "client_id": user_id, "active": True}, {"_id": 0},
    )
    if not live:
        return None
    for p in (live.get("placements") or []):
        if p.get("exposure_id") == exposure_id:
            spec = (live.get("session_specs") or {}).get(exposure_id) or {}
            return synth_workout_from_placement(
                live_id=live_id, placement=p, spec=spec, user_id=user_id,
            )
    return None


__all__ = [
    "V2_WORKOUT_ID_PREFIX",
    "synth_workouts_for_user",
    "synth_workout_by_wid",
    "synth_workout_from_placement",
]
