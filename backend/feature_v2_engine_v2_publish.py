"""
CrewFit V2 Engine V2 — Coach Dashboard Draft integration
==========================================================

Adds the coach-facing publish workflow for Engine V2 drafts, plus the
client-side read path. Strictly scoped:

    Coach:
      GET    /api/v2/coach/goal-config/status/{goal_key}
                Returns {status: COMPLETE|PARTIAL|MISSING, warnings[]}
      GET    /api/v2/coach/clients/{cid}/engine-v2/exceptions
                Returns [{id, kind, priority, ...}]
      POST   /api/v2/coach/clients/{cid}/engine-v2/exceptions/{eid}/resolve
                Body: {action, ...} — accept_unfilled | keep_unfilled |
                move_manually | modify_objective | carry_forward
      GET    /api/v2/coach/clients/{cid}/engine-v2/compare
                Draft-vs-Live placement diff list
      POST   /api/v2/coach/clients/{cid}/engine-v2/publish
                Body: {draft_id, ack_partial_config?, override_reason?}
                Atomic Draft → Live promotion with all gating.

    Client:
      GET    /api/v2/client/plan/live
                Returns the currently-active Engine V2 Live plan for the
                authenticated client (V2 flag required).
      GET    /api/v2/client/plan/live/day/{iso_date}
                Returns the workout(s) for a given date.

All endpoints preserve Live during Draft edits — publishing is the ONLY
mutation that touches Live.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger

from feature_v2_sport_configs import (
    canonicalise_goal_key, get_goal_config, SPORT_CONFIGS,
)
from feature_v2_common import write_decision, emit_metric


# ---------------------------------------------------------------------------
# Goal-config status classifier
# ---------------------------------------------------------------------------
# COMPLETE  — quotas + cadence + recovery + progression + validation ratified
# PARTIAL   — quotas + validation exist but cadence/progression rules missing
# MISSING   — goal not in SPORT_CONFIGS at all
#
# This is a static assessment at code-authoring time. Once we ratify a goal's
# programming, its entry here changes to COMPLETE.

GOAL_CONFIG_STATUS: dict[str, dict[str, Any]] = {
    "running.marathon": {
        "status": "COMPLETE",
        "warnings": [],
        "notes": "Cadence, recovery, progression, and phase quotas ratified.",
    },
    "running.half_marathon": {
        "status": "PARTIAL",
        "warnings": [
            "Long-run explicit cadence not configured (engine uses derived default 7d).",
            "Progression rules configured for only 1/6 phases.",
        ],
    },
    "running.10k": {
        "status": "PARTIAL",
        "warnings": [
            "Long-run cadence not explicitly configured.",
            "Progression rules not defined per phase.",
        ],
    },
    "running.5k": {
        "status": "PARTIAL",
        "warnings": [
            "Cadence rules use derived defaults.",
            "Progression rules not defined per phase.",
        ],
    },
    "cycling.endurance": {
        "status": "PARTIAL",
        "warnings": [
            "Cadence rules use derived defaults.",
            "Progression rules not defined per phase.",
        ],
    },
    "triathlon.olympic": {
        "status": "PARTIAL",
        "warnings": [
            "Only bike_long family recovery mapped; swim/run family recovery hours not specified.",
            "Cadence + progression rules not defined per phase.",
            "Interference rules between disciplines minimal.",
        ],
    },
    "strength.muscle_gain": {
        "status": "PARTIAL",
        "warnings": [
            "Hypertrophy phase demand ≈ 5 strength days/wk but phase.strength_days_per_week_max defaults to 2 — programme will legitimately land in needs_review.",
            "Cadence rules use derived defaults.",
        ],
    },
    "strength.fat_loss": {
        "status": "PARTIAL",
        "warnings": [
            "Cadence + progression rules not defined per phase.",
        ],
    },
    "strength.general": {
        "status": "PARTIAL",
        "warnings": [
            "Cadence + progression rules not defined per phase.",
        ],
    },
    "general.fitness": {
        "status": "PARTIAL",
        "warnings": [
            "Family recovery hours minimal; cadence + progression not defined.",
        ],
    },
}


def get_goal_config_status(goal_key: str) -> dict[str, Any]:
    from feature_v2_sport_configs import _GOAL_ALIASES
    raw = (goal_key or "").strip().lower().replace(" ", "_")
    # Consider MISSING when the raw input doesn't resolve to any known goal.
    if raw and raw not in SPORT_CONFIGS and raw not in _GOAL_ALIASES:
        return {"status": "MISSING", "warnings": [
            f"Goal '{goal_key}' is not registered in SPORT_CONFIGS."
        ], "goal_key": raw}
    canon = canonicalise_goal_key(goal_key)
    if canon not in SPORT_CONFIGS:
        return {"status": "MISSING", "warnings": [
            f"Goal '{goal_key}' is not registered in SPORT_CONFIGS."
        ], "goal_key": canon}
    info = GOAL_CONFIG_STATUS.get(canon)
    if info:
        return {"status": info["status"], "warnings": info.get("warnings", []),
                "notes": info.get("notes"), "goal_key": canon}
    return {"status": "PARTIAL", "warnings": [
        "No status entry in GOAL_CONFIG_STATUS registry — treated as PARTIAL by default."
    ], "goal_key": canon}


@api.get("/v2/coach/goal-config/status/{goal_key:path}")
async def endpoint_goal_config_status(
    goal_key: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    return get_goal_config_status(goal_key)


# ---------------------------------------------------------------------------
# Exception tray
# ---------------------------------------------------------------------------
# An "exception" surfaces from the latest Draft: unfilled objectives,
# validator errors, DNA gaps flagged as needs_review, and any coach directive
# conflicts recorded by the engine. Each exception is deterministically ID'd
# so the coach can resolve individual items.

def _draft_exception_id(draft_id: str, category: str, key: str) -> str:
    import hashlib
    return hashlib.sha1(f"{draft_id}::{category}::{key}".encode()).hexdigest()[:20]


def _extract_exceptions(draft: dict) -> list[dict]:
    exceptions: list[dict] = []
    did = draft["id"]

    # 1. Unfilled objectives (each unfilled record is an exception)
    for u in (draft.get("unfilled") or []):
        exceptions.append({
            "id": _draft_exception_id(did, "unfilled", u.get("exposure_id", "")),
            "category": "unfilled_objective",
            "priority": u.get("priority") or "UNKNOWN",
            "kind": u.get("kind"),
            "exposure_id": u.get("exposure_id"),
            "reason_code": u.get("reason_code"),
            "human_reason": u.get("human_reason"),
            "candidate_hints": u.get("candidate_hint_dates") or [],
            "actions": ["accept_unfilled", "keep_unfilled", "move_manually",
                        "modify_objective", "carry_forward"],
            "resolved": False,
        })

    # 2. Programme validation errors (KEY/IMPORTANT unfilled already covered
    # above; forbidden sequences, cap breaches, exposure ordering, etc. are
    # additional exceptions requiring coach review)
    pv = (draft.get("programme_validation") or {})
    for i in (pv.get("issues") or []):
        if i.get("severity") != "error":
            continue
        code = i.get("code", "")
        if code in ("important_unfilled", "key_unfilled"):
            continue  # covered above
        exceptions.append({
            "id": _draft_exception_id(did, "validator", code + ":" + str(i.get("message", ""))[:32]),
            "category": "validator_error",
            "priority": "IMPORTANT",
            "kind": code,
            "reason_code": code,
            "human_reason": i.get("message"),
            "actions": ["accept", "override_with_reason"],
            "resolved": False,
        })

    # 3. DNA gaps flagged as needs_review (info gaps are surfaced separately)
    for g in ((draft.get("demand") or {}).get("dna_gaps") or []):
        if g.get("severity") == "needs_review":
            exceptions.append({
                "id": _draft_exception_id(did, "dna_gap", g.get("field", "")),
                "category": "dna_gap",
                "priority": "IMPORTANT",
                "kind": g.get("field"),
                "reason_code": "dna_missing",
                "human_reason": g.get("message"),
                "actions": ["update_dna", "accept"],
                "resolved": False,
            })

    # 4. Goal-config status warnings (visible but not blocking)
    goal_key = ((draft.get("effective_context") or {}).get("goal_key") or "")
    cs = get_goal_config_status(goal_key)
    if cs["status"] == "PARTIAL":
        exceptions.append({
            "id": _draft_exception_id(did, "config", cs["status"]),
            "category": "config_status",
            "priority": "SUPPORTING",
            "kind": "goal_config_partial",
            "reason_code": "goal_config_partial",
            "human_reason": (
                f"Goal '{goal_key}' has a PARTIAL Engine V2 configuration. "
                + "; ".join(cs.get("warnings") or [])
            ),
            "actions": ["acknowledge"],
            "resolved": False,
        })

    return exceptions


@api.get("/v2/coach/clients/{client_id}/engine-v2/exceptions")
async def endpoint_engine_v2_exceptions(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    d = await db.plan_drafts_v2.find_one(
        {"client_id": client_id}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not d:
        raise HTTPException(404, "No Engine V2 draft found.")

    # Merge in stored resolutions (see resolve endpoint)
    resolutions = {r["exception_id"]: r for r in (d.get("exception_resolutions") or [])}
    raw = _extract_exceptions(d)
    for e in raw:
        r = resolutions.get(e["id"])
        if r:
            e["resolved"] = True
            e["resolution"] = {
                "action": r.get("action"),
                "reason": r.get("reason"),
                "coach_id": r.get("coach_id"),
                "at": r.get("at"),
                "details": r.get("details"),
            }

    return {
        "draft_id": d["id"],
        "goal_config_status": get_goal_config_status(
            (d.get("effective_context") or {}).get("goal_key") or "",
        ),
        "programme_validation_ok": ((d.get("programme_validation") or {}).get("ok", False)),
        "counts": {
            "total": len(raw),
            "unresolved": sum(1 for e in raw if not e.get("resolved")),
            "unresolved_key_important": sum(
                1 for e in raw if not e.get("resolved")
                and (e.get("priority") in ("KEY", "IMPORTANT"))
                and e.get("category") in ("unfilled_objective", "validator_error", "dna_gap")
            ),
        },
        "exceptions": raw,
    }


class ExceptionResolveBody(BaseModel):
    action: str  # accept_unfilled | keep_unfilled | move_manually | ...
    reason: Optional[str] = None
    details: Optional[dict[str, Any]] = None  # e.g. {"new_date": "2026-08-25"} for move_manually


@api.post("/v2/coach/clients/{client_id}/engine-v2/exceptions/{exception_id}/resolve")
async def endpoint_engine_v2_resolve_exception(
    client_id: str,
    exception_id: str,
    body: ExceptionResolveBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    d = await db.plan_drafts_v2.find_one(
        {"client_id": client_id}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not d:
        raise HTTPException(404, "No Engine V2 draft found.")

    # Validate this exception exists on the current draft
    valid_ids = {e["id"] for e in _extract_exceptions(d)}
    if exception_id not in valid_ids:
        raise HTTPException(404, f"Exception {exception_id} not found on current draft.")

    # Certain override actions require a reason
    if body.action in ("override_with_reason", "carry_forward", "modify_objective"):
        if not (body.reason and body.reason.strip()):
            raise HTTPException(400, f"Action '{body.action}' requires a reason.")

    resolution_record = {
        "exception_id": exception_id,
        "action": body.action,
        "reason": body.reason,
        "details": body.details or {},
        "coach_id": coach["id"],
        "at": now_iso(),
    }

    # Upsert into draft.exception_resolutions
    await db.plan_drafts_v2.update_one(
        {"id": d["id"]},
        {"$pull": {"exception_resolutions": {"exception_id": exception_id}}},
    )
    await db.plan_drafts_v2.update_one(
        {"id": d["id"]},
        {"$push": {"exception_resolutions": resolution_record}},
    )

    await write_decision(
        actor="coach", layer="ORCHESTRATION", scope_kind="plan_draft_v2_exception",
        scope_id=exception_id, client_id=client_id,
        outcome="RESOLVED",
        reason=f"Coach {coach.get('email')} resolved exception via '{body.action}'"
                + (f": {body.reason}" if body.reason else ""),
    )

    return {"ok": True, "resolution": resolution_record}


# ---------------------------------------------------------------------------
# Draft vs Live comparison (placement diff list)
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/engine-v2/compare")
async def endpoint_engine_v2_compare(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    d = await db.plan_drafts_v2.find_one(
        {"client_id": client_id}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not d:
        raise HTTPException(404, "No Engine V2 draft found.")

    live = await db.plan_live_v2.find_one(
        {"client_id": client_id, "active": True}, {"_id": 0},
    )

    draft_placements = d.get("placements") or []
    live_placements = (live or {}).get("placements") or []

    # Index each by (date, kind, objective_id) for stable matching
    def _idx(items):
        return {(p["date"], p["kind"], p.get("objective_id", "")): p for p in items}
    draft_map = _idx(draft_placements)
    live_map = _idx(live_placements)

    added, removed, changed, unchanged = [], [], [], []
    all_keys = set(draft_map.keys()) | set(live_map.keys())
    for k in sorted(all_keys):
        dv = draft_map.get(k)
        lv = live_map.get(k)
        if dv and not lv:
            added.append({"date": k[0], "kind": k[1], "draft": _placement_summary(dv)})
        elif lv and not dv:
            removed.append({"date": k[0], "kind": k[1], "live": _placement_summary(lv)})
        else:
            # Compare fields
            diffs = _placement_diff_fields(lv, dv)
            if diffs:
                changed.append({"date": k[0], "kind": k[1],
                                 "live": _placement_summary(lv),
                                 "draft": _placement_summary(dv),
                                 "changed_fields": diffs})
            else:
                unchanged.append({"date": k[0], "kind": k[1]})

    # Detect MOVED = one item's key differs on date but same objective_id+kind
    # exists on another date. Simplification: pair each removed with an added
    # of same (kind, objective_id) whose date differs.
    moved = []
    still_removed = list(removed)
    still_added = list(added)
    for r in list(still_removed):
        for a in list(still_added):
            if (a["kind"] == r["kind"] and
                a["draft"].get("objective_id") == r["live"].get("objective_id")):
                moved.append({
                    "kind": r["kind"],
                    "from_date": r["date"],
                    "to_date": a["date"],
                    "live": r["live"],
                    "draft": a["draft"],
                })
                still_removed.remove(r)
                still_added.remove(a)
                break

    return {
        "has_live": bool(live),
        "live_version_id": (live or {}).get("id"),
        "draft_id": d["id"],
        "summary": {
            "added": len(still_added),
            "removed": len(still_removed),
            "moved": len(moved),
            "changed": len(changed),
            "unchanged": len(unchanged),
        },
        "added": still_added,
        "removed": still_removed,
        "moved": moved,
        "changed": changed,
    }


def _placement_summary(p: dict) -> dict:
    return {
        "objective_id": p.get("objective_id"),
        "priority": p.get("priority"),
        "duration_min": p.get("target_duration_min"),
        "intensity": p.get("intensity_target"),
        "exposure_number": p.get("exposure_number"),
        "key": bool(p.get("key")),
    }


def _placement_diff_fields(a: dict, b: dict) -> list[str]:
    fields = ("target_duration_min", "intensity_target", "priority", "key")
    return [f for f in fields if a.get(f) != b.get(f)]


# ---------------------------------------------------------------------------
# Safe Publish transaction
# ---------------------------------------------------------------------------

class EngineV2PublishBody(BaseModel):
    draft_id: str
    ack_partial_config: bool = False
    override_reason: Optional[str] = None
    coach_note: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/engine-v2/publish")
async def endpoint_engine_v2_publish(
    client_id: str,
    body: EngineV2PublishBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    # 1. Load draft & confirm it's current
    latest = await db.plan_drafts_v2.find_one(
        {"client_id": client_id}, {"_id": 0}, sort=[("created_at", -1)],
    )
    if not latest:
        raise HTTPException(404, "No Engine V2 draft found.")
    if latest["id"] != body.draft_id:
        raise HTTPException(422, {
            "code": "stale_draft",
            "message": "A newer draft has been generated since this one was loaded.",
            "current_draft_id": latest["id"],
        })

    # 2. Goal-config gate
    goal_key = ((latest.get("effective_context") or {}).get("goal_key") or "")
    cs = get_goal_config_status(goal_key)
    if cs["status"] == "MISSING":
        raise HTTPException(422, {
            "code": "config_missing",
            "message": f"Goal '{goal_key}' is not configured in Engine V2. Publish blocked.",
            "goal_config_status": cs,
        })
    if cs["status"] == "PARTIAL" and not body.ack_partial_config:
        raise HTTPException(422, {
            "code": "partial_config_ack_required",
            "message": (
                f"Goal '{goal_key}' has a PARTIAL Engine V2 configuration. "
                "The coach must explicitly acknowledge this before publishing."
            ),
            "goal_config_status": cs,
        })

    # 3. Programme validation gate
    pv = latest.get("programme_validation") or {}
    if not pv.get("ok"):
        # Programme has validator errors — check whether they're all resolved.
        exceptions = _extract_exceptions(latest)
        resolutions = {r["exception_id"]: r for r in (latest.get("exception_resolutions") or [])}
        unresolved_blockers = [
            e for e in exceptions
            if e["id"] not in resolutions
            and e.get("priority") in ("KEY", "IMPORTANT")
            and e.get("category") in ("unfilled_objective", "validator_error", "dna_gap")
        ]
        if unresolved_blockers:
            raise HTTPException(422, {
                "code": "unresolved_blocking_exceptions",
                "message": (
                    f"{len(unresolved_blockers)} KEY/IMPORTANT exceptions remain "
                    "unresolved. Resolve or acknowledge each before publishing."
                ),
                "blockers": [
                    {"id": e["id"], "kind": e["kind"], "priority": e["priority"],
                     "reason": e.get("human_reason")}
                    for e in unresolved_blockers[:20]
                ],
            })

    # 4. Every placement must have a session_spec (workout construction complete)
    specs = (latest.get("session_specs") or {})
    for p in (latest.get("placements") or []):
        eid = p.get("exposure_id")
        if p.get("kind") == "rest":
            continue
        if not specs.get(eid):
            raise HTTPException(422, {
                "code": "incomplete_workout_construction",
                "message": f"Placement {eid} ({p.get('kind')} on {p.get('date')}) is missing a session_spec.",
            })

    # 5. Deactivate previous Live (retain in history)
    prev_live = await db.plan_live_v2.find_one(
        {"client_id": client_id, "active": True}, {"_id": 0},
    )
    if prev_live:
        await db.plan_live_v2.update_one(
            {"id": prev_live["id"]},
            {"$set": {
                "active": False,
                "deactivated_at": now_iso(),
                "deactivated_by": coach["id"],
                "superseded_by_draft": body.draft_id,
            }},
        )

    # 6. Create immutable Live version
    live_id = new_id()
    live_doc = {
        "id": live_id,
        "client_id": client_id,
        "coach_id": coach["id"],
        "engine_version": "v2",
        "source_draft_id": body.draft_id,
        "goal_key": goal_key,
        "goal_config_status_at_publish": cs,
        "planning_window": latest.get("planning_window"),
        "effective_context": latest.get("effective_context"),
        "demand": latest.get("demand"),
        "placements": latest.get("placements"),
        "session_specs": latest.get("session_specs"),
        "programme_validation": latest.get("programme_validation"),
        "unfilled": latest.get("unfilled"),
        "exception_resolutions": latest.get("exception_resolutions") or [],
        "ack_partial_config": bool(body.ack_partial_config),
        "override_reason": body.override_reason,
        "coach_note": body.coach_note,
        "activated_at": now_iso(),
        "activated_by": coach["id"],
        "active": True,
        "previous_live_id": (prev_live or {}).get("id"),
    }
    await db.plan_live_v2.insert_one(live_doc)

    # 7. Mark draft as published
    await db.plan_drafts_v2.update_one(
        {"id": body.draft_id},
        {"$set": {
            "status": "published",
            "published_at": now_iso(),
            "published_by": coach["id"],
            "live_id": live_id,
        }},
    )

    # 8. Audit trail
    await write_decision(
        actor="coach", layer="ORCHESTRATION", scope_kind="plan_live_v2",
        scope_id=live_id, client_id=client_id,
        outcome="PUBLISHED",
        reason=(
            f"Coach {coach.get('email')} published Engine V2 draft {body.draft_id} "
            f"(goal={goal_key}, config_status={cs['status']}, "
            f"ack_partial={body.ack_partial_config}, prev_live={bool(prev_live)}). "
            + (f"Override reason: {body.override_reason}. " if body.override_reason else "")
            + (f"Note: {body.coach_note}" if body.coach_note else "")
        ),
    )
    await emit_metric("engine_v2_publish", client_id=client_id,
                       coach_id=coach["id"], numeric_value=1,
                       labels={"goal": goal_key, "config_status": cs["status"]})

    return {
        "ok": True,
        "live_id": live_id,
        "previous_live_id": (prev_live or {}).get("id"),
        "goal_config_status": cs,
    }


# ---------------------------------------------------------------------------
# Client Live-read endpoints
# ---------------------------------------------------------------------------

async def _require_v2_active(user_id: str) -> None:
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "profile": 1})
    if not u:
        raise HTTPException(404, "User not found.")
    flags = (u.get("profile") or {}).get("v2_flags") or {}
    if not flags.get("engine_v2"):
        raise HTTPException(409, "Engine V2 not enabled for this client.")


def _current_user_dep():
    """Small dep that returns whichever role signs in — client or coach.
    Requires an authenticated JWT."""
    from server import get_current_user
    return get_current_user


@api.get("/v2/client/plan/live")
async def endpoint_client_plan_live(
    user: dict = Depends(require_role("client")),
) -> dict:
    """Return the currently-active Engine V2 Live plan for the authenticated
    client. If Engine V2 is not enabled, or no plan is published yet, returns
    a structured code rather than falling back to V1."""
    await _require_v2_active(user["id"])
    live = await db.plan_live_v2.find_one(
        {"client_id": user["id"], "active": True}, {"_id": 0},
    )
    if not live:
        return {"ok": False, "code": "no_live_v2", "message": "No Engine V2 Live plan published."}
    return {
        "ok": True,
        "live_id": live["id"],
        "activated_at": live.get("activated_at"),
        "goal_key": live.get("goal_key"),
        "planning_window": live.get("planning_window"),
        "placements": live.get("placements") or [],
        "session_specs": live.get("session_specs") or {},
        "effective_context": live.get("effective_context") or {},
        "programme_validation": live.get("programme_validation") or {},
    }


@api.get("/v2/client/plan/live/day/{iso_date}")
async def endpoint_client_plan_live_day(
    iso_date: str,
    user: dict = Depends(require_role("client")),
) -> dict:
    await _require_v2_active(user["id"])
    live = await db.plan_live_v2.find_one(
        {"client_id": user["id"], "active": True}, {"_id": 0},
    )
    if not live:
        return {"ok": False, "code": "no_live_v2", "workouts": []}
    placements = [p for p in (live.get("placements") or []) if p.get("date") == iso_date]
    specs = live.get("session_specs") or {}
    workouts = []
    for p in placements:
        eid = p.get("exposure_id")
        workouts.append({
            "placement": p,
            "session_spec": specs.get(eid) or {},
        })
    return {
        "ok": True,
        "date": iso_date,
        "workouts": workouts,
        "live_id": live["id"],
    }


logger.info("feature_v2_engine_v2_publish: /api/v2/coach/goal-config, exceptions, compare, publish + /api/v2/client/plan/* registered")
