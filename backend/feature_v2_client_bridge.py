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
    client workout screens already know how to render (P0-1/P1-3).

    Iter 113 — for running/cycling warmups, ensures a `drills` list is
    attached (either straight from the payload, or backfilled from the
    default packs so already-published plans benefit without a republish).
    """
    spec_kind = spec.get("spec_kind") or ""
    kind = spec.get("kind") or ""
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
                  "effort_rpe", "cue", "fuel_cue", "drills"):
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
        # Iter 113 — backfill warmup drills if the builder didn't attach any.
        wu = payload.get("warmup")
        if isinstance(wu, dict) and not wu.get("drills"):
            _backfill_warmup_drills(wu, spec_kind, kind)
        _push("warmup", wu)
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


# Iter 113 — drill packs mirroring feature_v2_construction_v2 so historical
# plans (built before the construction-side attachment landed) still surface
# specific warmup drills to the client without needing a republish.
_RUN_DRILLS_STANDARD_BF: list[dict] = [
    {"name": "Ankle circles",         "duration_sec": 20, "cue": "Each foot"},
    {"name": "Leg swings (front/back)","duration_sec": 30, "cue": "Each leg"},
    {"name": "Leg swings (side)",     "duration_sec": 30, "cue": "Each leg"},
    {"name": "Walking lunges",        "duration_sec": 45, "cue": "Loose hips"},
    {"name": "High knees",            "duration_sec": 20, "cue": "Cadence prep"},
    {"name": "Butt kicks",            "duration_sec": 20, "cue": "Heel to glute"},
]
_RUN_DRILLS_INTERVAL_BF: list[dict] = _RUN_DRILLS_STANDARD_BF + [
    {"name": "A-skips",  "duration_sec": 30, "cue": "Snappy, tall posture"},
    {"name": "Strides",  "duration_sec": 20, "reps": 4, "rest_sec": 60,
     "cue": "4 × 20s at fast-but-relaxed"},
]
_CYCLE_DRILLS_STANDARD_BF: list[dict] = [
    {"name": "Easy spin",         "duration_sec": 120, "cue": "Loose legs"},
    {"name": "Cadence pyramid",   "duration_sec": 60,
     "cue": "20s @ 90rpm → 100rpm → 110rpm"},
    {"name": "Standing pedal",    "duration_sec": 30, "cue": "Out of saddle"},
]
_CYCLE_DRILLS_INTERVAL_BF: list[dict] = _CYCLE_DRILLS_STANDARD_BF + [
    {"name": "Openers", "duration_sec": 30, "reps": 3, "rest_sec": 30,
     "cue": "3 × 30s hard efforts"},
]


def _backfill_warmup_drills(wu: dict, spec_kind: str, kind: str) -> None:
    interval_ish = kind in (
        "run_intervals", "run_vo2", "run_tempo", "run_threshold",
        "run_marathon_pace", "run_race_pace", "run_strides",
        "cycle_intervals", "cycle_vo2", "cycle_threshold",
    )
    if spec_kind == "running":
        wu["drills"] = _RUN_DRILLS_INTERVAL_BF if interval_ish else _RUN_DRILLS_STANDARD_BF
    elif spec_kind == "cycling":
        wu["drills"] = _CYCLE_DRILLS_INTERVAL_BF if interval_ish else _CYCLE_DRILLS_STANDARD_BF
    # swimming / brick — leave alone (poolside drills need dedicated packs)


def _spec_to_exercises(spec: dict, swaps: Optional[list[dict]] = None) -> list[dict]:
    """Convert a strength SessionSpec payload into the legacy exercise list
    shape used by /workouts/[id]/index.tsx.

    Iter 130c — optionally overlay client-side exercise swaps
    (``plan_live_v2_exercise_swaps``) so the client sees their replacement
    exercise on every read. Only the NAME is overridden — sets/reps/rest
    stay exactly as the coach programmed them.
    """
    if spec.get("spec_kind") != "strength":
        return []
    swap_by_idx: dict[int, dict] = {}
    for s in swaps or []:
        if s.get("is_active") and isinstance(s.get("exercise_index"), int):
            swap_by_idx[int(s["exercise_index"])] = s
    out: list[dict] = []
    for i, ex in enumerate(((spec.get("payload") or {}).get("exercises") or [])):
        base_name = ex.get("name") or ex.get("exercise") or "Exercise"
        swap = swap_by_idx.get(i)
        display_name = (swap or {}).get("replacement_name") or base_name
        row = {
            "name": display_name,
            "exercise_name_display": display_name,
            "sets": ex.get("sets"),
            "reps": ex.get("reps"),
            "rpe": ex.get("rpe") or ex.get("load_target"),
            "load_target": ex.get("load_target"),
            "rest_sec": ex.get("rest_sec"),
            "notes": ex.get("cue") or ex.get("notes"),
        }
        if swap:
            row["swapped_from"] = swap.get("original_name") or base_name
            row["swapped_at"] = swap.get("created_at") or swap.get("replaced_at")
            row["swapped_by"] = swap.get("replaced_by")
        # Preserve alternates list so the client swap UI still has options
        if ex.get("subs_allowed"):
            row["subs_allowed"] = list(ex.get("subs_allowed") or [])
        out.append(row)
    return out


def synth_workout_from_placement(
    *, live_id: str, placement: dict, spec: dict, user_id: str,
    exercise_swaps: Optional[list[dict]] = None,
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
    exercises = _spec_to_exercises(spec, swaps=exercise_swaps)
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
        "duration_minutes": duration,       # /calendar/range alias
        "estimated_minutes": duration,      # /calendar/range alias
        "day_load": 3 if bool(placement.get("key")) else 2,
        "key_session": bool(placement.get("key")),
        "location": location,
        "needs_coach_review": bool(spec.get("coach_review_required")),
        "approved": True,      # V2 Live is by definition coach-approved
        "coach_locked": True,  # V2 clients cannot edit Live
        "completed": False,
        "coach_notes": "",
        "rationale": spec.get("rationale") or "",
        # NB: warmup is intentionally null — blocks[] already carries the
        # warm-up segment. Client workout detail treats a non-empty `warmup`
        # array as a gym-style warm-up list (name / duration_sec) which is the
        # wrong shape for cardio/mobility. Leaving it null avoids a broken
        # render; the BLOCKS section renders the full session.
        "warmup": None,
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
        # Iter 119 — surface adaptation flag so the client workout screen
        # can render the "Adapted from original" badge.
        "adapted_from_original": bool(spec.get("adapted_from_original")),
        "original_environment": spec.get("original_environment"),
    }


async def synth_workouts_for_user(
    db, user_id: str, *,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    override_dates: Optional[set] = None,
) -> list[dict]:
    """Return legacy-shaped workout rows for a client's active plan_live_v2.
    Silently returns [] when no active V2 plan or client is not V2-flagged.

    Phase 1 manual override: any date in `override_dates` (active
    replace_day or suppress_day) is dropped from the V2 splice so the
    client sees the coach's decision, not the automated placement.
    """
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
    _override_dates = override_dates or set()
    out: list[dict] = []
    for p in placements:
        d = p.get("date")
        if not d:
            continue
        if start_iso and d < start_iso:
            continue
        if end_iso and d > end_iso:
            continue
        if d in _override_dates:
            # Coach has an active date-level override for this date.
            # Drop the V2 session so the client sees the manual outcome
            # (a manual db.workouts row for replace_day, or rest for
            # suppress_day).
            continue
        eid = p.get("exposure_id") or ""
        spec = specs.get(eid) or {}
        # Iter 118 — Change Setup override. If an active
        # plan_live_v2_implementations row covers this (exposure, date),
        # prefer its spec_snapshot over the original session_specs entry.
        override = await db.plan_live_v2_implementations.find_one(
            {"client_id": user_id, "exposure_id": eid,
             "is_active": True,
             "$or": [
                 {"date": d},
                 {"$and": [
                     {"date_range_start": {"$lte": d}},
                     {"date_range_end":   {"$gte": d}},
                 ]},
             ]},
            {"_id": 0, "spec_snapshot": 1},
            sort=[("created_at", -1)],
        )
        if override and override.get("spec_snapshot"):
            spec = override["spec_snapshot"]
        # Iter 130c — pull per-exercise swaps for this placement so the
        # bridge can substitute the display name on the fly.
        swaps = await db.plan_live_v2_exercise_swaps.find(
            {"client_id": user_id, "exposure_id": eid,
             "date": d, "is_active": True},
            {"_id": 0},
        ).to_list(50)
        row = synth_workout_from_placement(
            live_id=live_id, placement=p, spec=spec, user_id=user_id,
            exercise_swaps=swaps,
        )
        if row is not None:
            out.append(row)
    return out


async def synth_workout_by_wid(db, wid: str, user_id: str) -> Optional[dict]:
    """Resolve a `v2p:{source_id}:{exposure_id}` id back to a legacy-shaped
    workout row, or None if the source doc no longer matches.

    Iter 146 — sources checked in order:
      1. plan_live_v2 (published, active)
      2. plan_drafts_v2 where status ∈ {needs_review, ready_for_review}
    This lets the client-side workout viewer render draft placements the
    coach hasn't yet published, matching the coach dashboard's own visibility.
    """
    if not (wid or "").startswith(V2_WORKOUT_ID_PREFIX):
        return None
    parts = wid.split(":", 2)
    if len(parts) < 3:
        return None
    source_id = parts[1]
    exposure_id = parts[2]

    # 1. Live plan first
    src = await db.plan_live_v2.find_one(
        {"id": source_id, "client_id": user_id, "active": True}, {"_id": 0},
    )
    src_is_draft = False
    if not src:
        # 2. In-review OR already-published draft fallback (Iter 146/147)
        src = await db.plan_drafts_v2.find_one(
            {"id": source_id, "client_id": user_id,
             "status": {"$in": ["needs_review", "ready_for_review", "published"]}},
            {"_id": 0},
        )
        src_is_draft = bool(src)
    if not src:
        return None
    for p in (src.get("placements") or []):
        if p.get("exposure_id") == exposure_id:
            spec = (src.get("session_specs") or {}).get(exposure_id) or {}
            # Overrides only exist for live plans — skip lookup for drafts.
            if not src_is_draft:
                override = await db.plan_live_v2_implementations.find_one(
                    {"client_id": user_id, "exposure_id": exposure_id,
                     "is_active": True,
                     "$or": [
                         {"date": p.get("date")},
                         {"$and": [
                             {"date_range_start": {"$lte": p.get("date")}},
                             {"date_range_end":   {"$gte": p.get("date")}},
                         ]},
                     ]},
                    {"_id": 0, "spec_snapshot": 1},
                    sort=[("created_at", -1)],
                )
                if override and override.get("spec_snapshot"):
                    spec = override["spec_snapshot"]
                # Per-exercise swaps also live only against live plans.
                swaps = await db.plan_live_v2_exercise_swaps.find(
                    {"client_id": user_id, "exposure_id": exposure_id,
                     "date": p.get("date"), "is_active": True},
                    {"_id": 0},
                ).to_list(50)
            else:
                swaps = []
            return synth_workout_from_placement(
                live_id=source_id, placement=p, spec=spec, user_id=user_id,
                exercise_swaps=swaps,
            )
    return None


__all__ = [
    "V2_WORKOUT_ID_PREFIX",
    "synth_workouts_for_user",
    "synth_workout_by_wid",
    "synth_workout_from_placement",
    "user_is_v2",
    "apply_reality_action_v2",
]


# ---------------------------------------------------------------------------
# Reality actions on Engine V2 plans (Iter 114)
# ---------------------------------------------------------------------------
# The legacy `_apply_reality_action` in server.py mutates rows in the
# `workouts` collection, which V2 clients don't have. This helper mirrors
# the most common reality kinds against `plan_live_v2` (placements +
# session_specs) so V2 clients can actually change their day from the
# Today's Reality modal.

async def user_is_v2(db, user: dict) -> bool:
    flags = (user.get("profile") or {}).get("v2_flags") or {}
    if flags.get("engine_v2") or flags.get("v2_default"):
        return True
    # Fallback: hydrate from DB if the passed-in user dict predates the
    # flag being set on the profile.
    doc = await db.users.find_one({"id": user.get("id")}, {"_id": 0, "profile.v2_flags": 1})
    ff = ((doc or {}).get("profile") or {}).get("v2_flags") or {}
    return bool(ff.get("engine_v2") or ff.get("v2_default"))


def _humanise_change(k: str, kind: str) -> str:
    return f"{k}={kind}"


async def _v2_find_placement(db, user_id: str, date: str) -> Optional[tuple]:
    """Return (live_doc, placement_index, placement, spec) for the placement
    on `date`, or None if not found."""
    live = await db.plan_live_v2.find_one(
        {"client_id": user_id, "active": True}, {"_id": 0},
    )
    if not live:
        return None
    placements = live.get("placements") or []
    for i, p in enumerate(placements):
        if p.get("date") == date:
            eid = p.get("exposure_id") or ""
            spec = (live.get("session_specs") or {}).get(eid) or {}
            return live, i, p, spec
    return None


def _build_v2_mobility_spec(reason: str) -> dict:
    """Return a mobility session spec compatible with the client bridge
    renderer (spec_kind='mobility' + payload.flow_blocks)."""
    return {
        "spec_kind": "mobility",
        "kind": "mobility",
        "duration_min": 20,
        "intensity_target": "low",
        "environment": "any",
        "equipment_used": ["mat"],
        "payload": {
            "flow_blocks": [
                {"name": "Diaphragmatic breathing", "duration_min": 3,
                 "cue": "Slow nasal breaths, ribs wide"},
                {"name": "Cat-cow",                 "duration_min": 3,
                 "cue": "Sync breath with spine flow"},
                {"name": "Hip 90/90",               "duration_min": 4,
                 "cue": "Rotate side to side, tall spine"},
                {"name": "T-spine openers",         "duration_min": 4,
                 "cue": "Reach through and over, exhale open"},
                {"name": "Couch stretch",           "duration_min": 4,
                 "cue": "Each side, glutes engaged"},
                {"name": "Guided decompress",       "duration_min": 2,
                 "cue": "Legs up wall, box breathing"},
            ],
        },
        "rationale": reason,
    }


def _build_v2_recovery_spec(reason: str, duration_min: int = 20) -> dict:
    return {
        "spec_kind": "recovery",
        "kind": "recovery",
        "duration_min": duration_min,
        "intensity_target": "low",
        "environment": "any",
        "equipment_used": [],
        "payload": {
            "flow_blocks": [
                {"name": "Easy walk or spin", "duration_min": duration_min,
                 "cue": "Nose-only breathing, zone 1"},
            ],
        },
        "rationale": reason,
    }


def _build_v2_walk_spec(reason: str, target_min: int = 30) -> dict:
    return {
        "spec_kind": "recovery",
        "kind": "walk",
        "duration_min": target_min,
        "intensity_target": "low",
        "environment": "outdoor",
        "equipment_used": ["walking_shoes"],
        "payload": {
            "flow_blocks": [
                {"name": "Steady walk", "duration_min": target_min,
                 "cue": "Easy pace, relaxed shoulders"},
            ],
        },
        "rationale": reason,
    }


def _scale_running_payload(payload: dict, factor: float) -> dict:
    """Proportionally shrink/expand the main block of a running/cycling
    session. Warmup and cooldown stay untouched (safety floor)."""
    if not isinstance(payload, dict):
        return payload
    p = dict(payload)
    main = p.get("main")
    if isinstance(main, dict) and main.get("duration_min"):
        new_main = dict(main)
        new_main["duration_min"] = max(5, int(round(main["duration_min"] * factor)))
        p["main"] = new_main
    return p


async def apply_reality_action_v2(db, user_id: str, action: dict) -> dict:
    """Execute a single Reality action against the client's active
    plan_live_v2 doc. Mirrors `_apply_reality_action` in server.py, returning
    the same {kind, action, changed, before, after} change record."""
    from datetime import datetime, timezone

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    kind = action.get("kind")
    change: dict = {"kind": kind, "action": action, "changed": False,
                    "before": None, "after": None}

    if kind in ("keep", "ask_coach"):
        # No mutation — coach alert (if any) is handled at the reality event
        # level in the calling reality_apply endpoint.
        return change

    date = action.get("date")

    if kind == "note":
        if not date:
            return change
        found = await _v2_find_placement(db, user_id, date)
        if not found:
            return change
        live, idx, p, _spec = found
        note_text = action.get("text") or ""
        current = p.get("coach_note") or ""
        new_note = (current + ("\n" if current else "") + note_text).strip()
        await db.plan_live_v2.update_one(
            {"id": live["id"]},
            {"$set": {f"placements.{idx}.coach_note": new_note,
                      "updated_at": _now()}},
        )
        change.update({"changed": True,
                       "before": {"coach_note": current},
                       "after":  {"coach_note": new_note}})
        return change

    # All remaining kinds need a placement.
    if kind in ("reduce", "extend", "replace", "convert_mobility",
                "convert_recovery", "convert_walk", "skip"):
        if not date:
            return change
        found = await _v2_find_placement(db, user_id, date)
        if not found:
            return change
        live, idx, p, spec = found
        eid = p.get("exposure_id") or ""
        before = {
            "kind": p.get("kind"),
            "duration_min": spec.get("duration_min")
                            or p.get("target_duration_min"),
            "spec_kind": spec.get("spec_kind"),
        }
        new_placement = dict(p)
        new_spec = dict(spec)

        if kind == "reduce":
            orig = int(spec.get("duration_min")
                        or p.get("target_duration_min") or 40)
            target = int(action.get("target_min")
                          or max(15, int(orig * 0.6)))
            factor = target / max(1, orig)
            new_spec["duration_min"] = target
            new_placement["target_duration_min"] = target
            if new_spec.get("payload"):
                new_spec["payload"] = _scale_running_payload(
                    new_spec["payload"], factor,
                )
            # Downgrade KEY priority to IMPORTANT once shrunk
            if str(new_placement.get("priority") or "").upper() == "KEY":
                new_placement["priority"] = "IMPORTANT"
            new_spec["rationale"] = (
                (spec.get("rationale") or "") + f"  |  Reduced to {target}m via Today's Reality."
            ).strip()
        elif kind == "extend":
            add = int(action.get("add_min") or 15)
            orig = int(spec.get("duration_min")
                        or p.get("target_duration_min") or 40)
            new_duration = orig + add
            new_spec["duration_min"] = new_duration
            new_placement["target_duration_min"] = new_duration
            if new_spec.get("payload"):
                new_spec["payload"] = _scale_running_payload(
                    new_spec["payload"], new_duration / max(1, orig),
                )
            new_spec["rationale"] = (
                (spec.get("rationale") or "") + f"  |  +{add}m bonus via Today's Reality."
            ).strip()
        elif kind == "replace":
            new_title = action.get("new_title")
            if new_title:
                new_placement["kind"] = str(new_title).lower().replace(" ", "_")
                new_spec["kind"] = new_placement["kind"]
            if action.get("target_min"):
                nd = int(action["target_min"])
                new_spec["duration_min"] = nd
                new_placement["target_duration_min"] = nd
            new_spec["rationale"] = (
                (spec.get("rationale") or "") + f"  |  Replaced: {new_title or 'session'}."
            ).strip()
        elif kind == "convert_mobility":
            reason = action.get("reason") or "Client reality: switched to mobility."
            mob = _build_v2_mobility_spec(reason)
            new_placement["kind"] = "mobility"
            new_placement["target_duration_min"] = mob["duration_min"]
            new_placement["priority"] = "SUPPORT"
            new_spec = mob
        elif kind == "convert_recovery":
            reason = action.get("reason") or "Client reality: converted to recovery."
            rec = _build_v2_recovery_spec(reason)
            new_placement["kind"] = "recovery"
            new_placement["target_duration_min"] = rec["duration_min"]
            new_placement["priority"] = "SUPPORT"
            new_spec = rec
        elif kind == "convert_walk":
            target = int(action.get("target_min") or 30)
            reason = action.get("reason") or f"Client reality: converted to {target}m walk."
            wsp = _build_v2_walk_spec(reason, target)
            new_placement["kind"] = "walk"
            new_placement["target_duration_min"] = target
            new_placement["priority"] = "SUPPORT"
            new_spec = wsp
        elif kind == "skip":
            new_placement["kind"] = "rest"
            new_placement["target_duration_min"] = 0
            new_placement["priority"] = "SUPPORT"
            new_placement["skipped"] = True
            new_placement["skip_reason"] = action.get("reason") or "Client reality: skip today."
            # Clear the spec — rest days render as "Rest" without a card.
            new_spec = {
                "spec_kind": "rest",
                "kind": "rest",
                "duration_min": 0,
                "environment": "any",
                "equipment_used": [],
                "payload": {},
                "rationale": new_placement["skip_reason"],
            }

        # Write both placement + spec back atomically
        await db.plan_live_v2.update_one(
            {"id": live["id"]},
            {"$set": {
                f"placements.{idx}": new_placement,
                f"session_specs.{eid}": new_spec,
                "updated_at": _now(),
            }},
        )
        after = {
            "kind": new_placement.get("kind"),
            "duration_min": new_spec.get("duration_min")
                            or new_placement.get("target_duration_min"),
            "spec_kind": new_spec.get("spec_kind"),
        }
        change.update({"changed": True, "before": before, "after": after})
        return change

    if kind in ("move", "bring_forward", "push_back"):
        # V2 date-swap: exchange placement dates between two placements.
        f, t = action.get("from_date"), action.get("to_date")
        if not f or not t:
            return change
        live = await db.plan_live_v2.find_one(
            {"client_id": user_id, "active": True}, {"_id": 0},
        )
        if not live:
            return change
        placements = list(live.get("placements") or [])
        idx_from = idx_to = -1
        for i, p in enumerate(placements):
            if p.get("date") == f:
                idx_from = i
            if p.get("date") == t:
                idx_to = i
        if idx_from < 0:
            return change
        pf = dict(placements[idx_from])
        pt = dict(placements[idx_to]) if idx_to >= 0 else None
        pf["date"] = t
        if pt:
            pt["date"] = f
            placements[idx_from], placements[idx_to] = pt, pf
        else:
            placements[idx_from] = pf
        await db.plan_live_v2.update_one(
            {"id": live["id"]},
            {"$set": {"placements": placements, "updated_at": _now()}},
        )
        change.update({"changed": True,
                       "before": {"from": f, "to": t},
                       "after":  {"from": f, "to": t}})
        return change

    return change
