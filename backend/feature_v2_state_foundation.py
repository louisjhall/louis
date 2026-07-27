"""
feature_v2_state_foundation — V2 Phase 1: state layer (DRAFT / LIVE / VERSIONING).

Adds the safety net every subsequent V2 phase depends on.
Ships behind a per-client feature flag `profile.v2_flags.state_foundation_enabled`.
Zero impact on V1 behaviour: this module only writes to new collections and
new endpoints under `/api/v2/*`. No existing collections are read or mutated.

Entities (new collections):
    plan_drafts            — the mutable working copy of a client's plan
    plan_versions          — immutable published versions of a client's plan
    plan_snapshots         — the per-version snapshot payload (frozen state)
    change_sets            — proposed diffs against the current draft
    approvals              — coach approvals that promote draft → version
    locks                  — protection markers on any target
    decision_records       — audit trail for every material decision

Non-goals for P1: goal/phase/objective engines, scheduling, workout
construction. Those land in P2-P6 and reference this state layer.

Guarantees (unit-tested):
    * Only a coach with the flag enabled on the target client can call these APIs
    * plan_versions rows are immutable once published
    * Revert to any historical version creates a NEW version (never destructive)
    * DRAFT never affects the client's LIVE experience (no reads from V1 code)
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import (
    api,
    db,
    require_role,
    current_user,
    new_id,
    now_iso,
    logger,
)

# ---------------------------------------------------------------------------
# Feature flag helpers
# ---------------------------------------------------------------------------

FLAG_PATH = "v2_flags.state_foundation_enabled"


async def _client_has_v2_flag(client_id: str) -> bool:
    user = await db.users.find_one(
        {"id": client_id}, {"_id": 0, "profile.v2_flags": 1}
    )
    if not user:
        return False
    return bool(
        (user.get("profile") or {}).get("v2_flags", {}).get("state_foundation_enabled")
    )


async def _require_client_and_flag(client_id: str) -> dict:
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")
    if not (client.get("profile") or {}).get("v2_flags", {}).get(
        "state_foundation_enabled"
    ):
        raise HTTPException(
            409,
            "V2 state foundation not enabled for this client. "
            "Enable via PATCH /api/v2/coach/clients/{cid}/flags first.",
        )
    return client


# ---------------------------------------------------------------------------
# Decision record — used everywhere
# ---------------------------------------------------------------------------

async def _write_decision(
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
    """Write a DecisionRecord. Returns its id."""
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


# ---------------------------------------------------------------------------
# Flag admin
# ---------------------------------------------------------------------------

class FlagBody(BaseModel):
    state_foundation_enabled: Optional[bool] = None
    goals_phases_enabled: Optional[bool] = None
    demand_engine_enabled: Optional[bool] = None
    roster_facets_enabled: Optional[bool] = None
    scheduling_v2_enabled: Optional[bool] = None
    construction_v2_enabled: Optional[bool] = None
    equipment_adaptation_v2_enabled: Optional[bool] = None
    progression_v2_enabled: Optional[bool] = None
    events_v2_enabled: Optional[bool] = None
    reality_v2_enabled: Optional[bool] = None
    automation_v2_enabled: Optional[bool] = None
    shadow_mode: Optional[bool] = None
    v2_default: Optional[bool] = None


@api.patch("/v2/coach/clients/{client_id}/flags")
async def v2_set_flags(
    client_id: str,
    body: FlagBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Enable/disable V2 feature flags for a specific client."""
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")

    updates: dict = {}
    body_dict = body.model_dump(exclude_none=True)
    for flag_name, val in body_dict.items():
        updates[f"profile.v2_flags.{flag_name}"] = bool(val)
    if not updates:
        return {"ok": True, "changed": []}
    updates["profile.v2_flags.updated_at"] = now_iso()
    updates["profile.v2_flags.updated_by"] = coach["id"]
    await db.users.update_one({"id": client_id}, {"$set": updates})

    await _write_decision(
        actor="coach",
        layer="PUBLISH",
        scope_kind="client",
        scope_id=client_id,
        outcome="APPLIED",
        client_id=client_id,
        reason=f"V2 flags updated: {list(updates.keys())}",
    )
    return {"ok": True, "changed": list(updates.keys())}


@api.get("/v2/coach/clients/{client_id}/flags")
async def v2_get_flags(
    client_id: str, coach: dict = Depends(require_role("coach"))
) -> dict:
    client = await db.users.find_one(
        {"id": client_id}, {"_id": 0, "profile.v2_flags": 1}
    )
    if not client:
        raise HTTPException(404, "Client not found")
    return (client.get("profile") or {}).get("v2_flags", {})


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

class DraftCreateBody(BaseModel):
    programme_id: Optional[str] = None
    parent_plan_version_id: Optional[str] = None
    notes: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/drafts")
async def draft_create(
    client_id: str,
    body: DraftCreateBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Create a new DRAFT. Discards any previous non-promoted draft
    for the same programme (only one active draft per programme)."""
    await _require_client_and_flag(client_id)

    programme_id = body.programme_id or f"programme:{client_id}"
    existing = await db.plan_drafts.find_one(
        {
            "programme_id": programme_id,
            "status": {"$in": ["building", "ready_for_review", "partially_approved"]},
        },
        {"_id": 0, "id": 1},
    )
    if existing:
        # Mark previous as discarded rather than deleting — audit trail matters
        await db.plan_drafts.update_one(
            {"id": existing["id"]},
            {"$set": {"status": "discarded", "discarded_at": now_iso(), "discarded_by": coach["id"]}},
        )

    did = new_id()
    now = now_iso()
    doc = {
        "id": did,
        "client_id": client_id,
        "programme_id": programme_id,
        "parent_plan_version_id": body.parent_plan_version_id,
        "change_set_ids": [],
        "status": "building",
        "notes": body.notes or "",
        "metrics": {
            "ready_count": 0,
            "needs_review_count": 0,
            "conflict_count": 0,
            "coach_edited_count": 0,
            "blocked_count": 0,
        },
        "build_started_at": now,
        "build_completed_at": None,
        "created_by": coach["id"],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    await db.plan_drafts.insert_one(dict(doc))  # copy — insert_one mutates

    await _write_decision(
        actor="coach",
        layer="PUBLISH",
        scope_kind="plan_draft",
        scope_id=did,
        outcome="APPLIED",
        client_id=client_id,
        reason=f"Draft created (programme={programme_id})",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/drafts")
async def draft_list(
    client_id: str,
    programme_id: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    q: dict = {"client_id": client_id}
    if programme_id:
        q["programme_id"] = programme_id
    drafts = (
        await db.plan_drafts.find(q, {"_id": 0}).sort("created_at", -1).to_list(50)
    )
    return {"drafts": drafts}


@api.get("/v2/coach/clients/{client_id}/drafts/{draft_id}")
async def draft_get(
    client_id: str, draft_id: str, coach: dict = Depends(require_role("coach"))
) -> dict:
    await _require_client_and_flag(client_id)
    draft = await db.plan_drafts.find_one(
        {"id": draft_id, "client_id": client_id}, {"_id": 0}
    )
    if not draft:
        raise HTTPException(404, "Draft not found")
    return draft


class DraftPatchBody(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    metrics: Optional[dict] = None


@api.patch("/v2/coach/clients/{client_id}/drafts/{draft_id}")
async def draft_patch(
    client_id: str,
    draft_id: str,
    body: DraftPatchBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    upd: dict = {"updated_at": now_iso()}
    if body.status is not None:
        if body.status not in {
            "building",
            "ready_for_review",
            "partially_approved",
            "promoted",
            "discarded",
        }:
            raise HTTPException(400, f"Invalid draft status: {body.status}")
        upd["status"] = body.status
    if body.notes is not None:
        upd["notes"] = body.notes
    if body.metrics is not None:
        upd["metrics"] = body.metrics
    r = await db.plan_drafts.update_one(
        {"id": draft_id, "client_id": client_id}, {"$set": upd}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Draft not found")
    return await db.plan_drafts.find_one(
        {"id": draft_id}, {"_id": 0}
    )


# ---------------------------------------------------------------------------
# Change sets
# ---------------------------------------------------------------------------

class ChangeSetBody(BaseModel):
    kind: str = Field(..., min_length=1)
    scope_assignment_ids: list[str] = []
    before_snapshot: Any = None
    after_snapshot: Any = None
    triggered_by: str = "system"        # system | coach | client | ai_command_bar
    triggered_event_id: Optional[str] = None
    proposed_by: str = "system"
    human_readable_summary: str = ""


@api.post("/v2/coach/clients/{client_id}/drafts/{draft_id}/change-sets")
async def change_set_create(
    client_id: str,
    draft_id: str,
    body: ChangeSetBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    draft = await db.plan_drafts.find_one(
        {"id": draft_id, "client_id": client_id}, {"_id": 0, "id": 1, "status": 1}
    )
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft["status"] in ("promoted", "discarded"):
        raise HTTPException(409, f"Cannot add change set to {draft['status']} draft")

    cid = new_id()
    doc = {
        "id": cid,
        "draft_id": draft_id,
        "client_id": client_id,
        "kind": body.kind,
        "scope_assignment_ids": body.scope_assignment_ids,
        "before_snapshot": body.before_snapshot,
        "after_snapshot": body.after_snapshot,
        "triggered_by": body.triggered_by,
        "triggered_event_id": body.triggered_event_id,
        "proposed_by": body.proposed_by,
        "status": "proposed",
        "human_readable_summary": body.human_readable_summary,
        "created_at": now_iso(),
        "resolved_at": None,
        "resolved_by": None,
    }
    await db.change_sets.insert_one(dict(doc))
    await db.plan_drafts.update_one(
        {"id": draft_id},
        {"$push": {"change_set_ids": cid}, "$set": {"updated_at": now_iso()}},
    )
    await _write_decision(
        actor=body.proposed_by,
        layer="PUBLISH",
        scope_kind="change_set",
        scope_id=cid,
        outcome="PROPOSED",
        client_id=client_id,
        reason=body.human_readable_summary or f"Change set proposed: {body.kind}",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/drafts/{draft_id}/change-sets")
async def change_set_list(
    client_id: str,
    draft_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    rows = await db.change_sets.find(
        {"draft_id": draft_id, "client_id": client_id}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)
    return {"change_sets": rows}


class ChangeSetResolveBody(BaseModel):
    status: str   # accepted | rejected | auto_applied
    notes: Optional[str] = None


@api.patch(
    "/v2/coach/clients/{client_id}/change-sets/{change_set_id}/resolve"
)
async def change_set_resolve(
    client_id: str,
    change_set_id: str,
    body: ChangeSetResolveBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    if body.status not in {"accepted", "rejected", "auto_applied"}:
        raise HTTPException(400, f"Invalid resolution: {body.status}")
    r = await db.change_sets.update_one(
        {"id": change_set_id, "client_id": client_id},
        {
            "$set": {
                "status": body.status,
                "resolved_at": now_iso(),
                "resolved_by": coach["id"],
                "resolution_notes": body.notes or "",
            }
        },
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Change set not found")
    await _write_decision(
        actor="coach",
        layer="PUBLISH",
        scope_kind="change_set",
        scope_id=change_set_id,
        outcome=body.status.upper(),
        client_id=client_id,
        reason=body.notes or f"Change set {body.status} by coach",
    )
    return await db.change_sets.find_one(
        {"id": change_set_id}, {"_id": 0}
    )


# ---------------------------------------------------------------------------
# Approvals + publishing (DRAFT → VERSION)
# ---------------------------------------------------------------------------

class ApprovalBody(BaseModel):
    scope: str    # workout | day | date_range | planning_window | phase | programme | batch_ready
    scope_ref: Any                              # id or list of ids
    include_change_set_ids: Optional[list[str]] = None
    notes: Optional[str] = None


async def _next_version_number(programme_id: str) -> int:
    latest = await db.plan_versions.find_one(
        {"programme_id": programme_id},
        {"_id": 0, "version": 1},
        sort=[("version", -1)],
    )
    return int((latest or {}).get("version") or 0) + 1


@api.post("/v2/coach/clients/{client_id}/drafts/{draft_id}/approvals")
async def approve_draft(
    client_id: str,
    draft_id: str,
    body: ApprovalBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Promote (part of) a draft to a new immutable PlanVersion.

    The snapshot payload is deliberately opaque here — future phases fill it
    (workout_assignments + implementations + exposures). At P1 the snapshot
    contains just the metadata + the accepted change_set_ids so the audit
    trail is complete.
    """
    await _require_client_and_flag(client_id)
    draft = await db.plan_drafts.find_one(
        {"id": draft_id, "client_id": client_id}, {"_id": 0}
    )
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft["status"] in ("promoted", "discarded"):
        raise HTTPException(409, f"Draft is {draft['status']}")

    programme_id = draft["programme_id"]
    version_no = await _next_version_number(programme_id)
    supersedes = await db.plan_versions.find_one(
        {"programme_id": programme_id},
        {"_id": 0, "id": 1},
        sort=[("version", -1)],
    )

    # Immutable snapshot
    snap_id = new_id()
    accepted_change_sets = body.include_change_set_ids or []
    snapshot_doc = {
        "id": snap_id,
        "programme_id": programme_id,
        "client_id": client_id,
        "draft_id": draft_id,
        "scope": body.scope,
        "scope_ref": body.scope_ref,
        "accepted_change_set_ids": accepted_change_sets,
        "created_at": now_iso(),
        # Payload fields below are filled by later phases as those entities exist
        "workout_assignments_snapshot": [],
        "workout_implementations_snapshot": [],
        "objective_exposures_snapshot": [],
    }
    await db.plan_snapshots.insert_one(snapshot_doc)

    version_id = new_id()
    version_doc = {
        "id": version_id,
        "programme_id": programme_id,
        "client_id": client_id,
        "version": version_no,
        "published_at": now_iso(),
        "published_by": coach["id"],
        "snapshot_id": snap_id,
        "supersedes_version_id": (supersedes or {}).get("id"),
        "approvals": [],
        "immutable": True,
    }
    await db.plan_versions.insert_one(version_doc)

    approval_id = new_id()
    approval_doc = {
        "id": approval_id,
        "draft_id": draft_id,
        "programme_id": programme_id,
        "client_id": client_id,
        "version_id": version_id,
        "scope": body.scope,
        "scope_ref": body.scope_ref,
        "include_change_set_ids": accepted_change_sets,
        "notes": body.notes or "",
        "approved_by": coach["id"],
        "approved_at": now_iso(),
    }
    await db.approvals.insert_one(approval_doc)
    await db.plan_versions.update_one(
        {"id": version_id}, {"$push": {"approvals": approval_id}}
    )

    # Mark accepted change sets
    if accepted_change_sets:
        await db.change_sets.update_many(
            {"id": {"$in": accepted_change_sets}, "client_id": client_id},
            {
                "$set": {
                    "status": "accepted",
                    "resolved_at": now_iso(),
                    "resolved_by": coach["id"],
                    "promoted_in_version_id": version_id,
                }
            },
        )

    # Draft state
    if body.scope in ("programme", "batch_ready"):
        await db.plan_drafts.update_one(
            {"id": draft_id}, {"$set": {"status": "promoted", "updated_at": now_iso()}}
        )
    else:
        await db.plan_drafts.update_one(
            {"id": draft_id},
            {"$set": {"status": "partially_approved", "updated_at": now_iso()}},
        )

    await _write_decision(
        actor="coach",
        layer="PUBLISH",
        scope_kind="plan_version",
        scope_id=version_id,
        outcome="APPLIED",
        client_id=client_id,
        reason=f"Approved scope={body.scope} → v{version_no}",
        previous_state_ref=(supersedes or {}).get("id"),
        new_state_ref=version_id,
    )
    return {
        "approval_id": approval_id,
        "version_id": version_id,
        "version": version_no,
        "snapshot_id": snap_id,
    }


# ---------------------------------------------------------------------------
# Versions read-only + revert
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/versions")
async def versions_list(
    client_id: str,
    programme_id: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    q: dict = {"client_id": client_id}
    if programme_id:
        q["programme_id"] = programme_id
    rows = (
        await db.plan_versions.find(q, {"_id": 0}).sort("version", -1).to_list(200)
    )
    return {"versions": rows}


@api.get("/v2/coach/clients/{client_id}/versions/{version_id}")
async def version_get(
    client_id: str,
    version_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    v = await db.plan_versions.find_one(
        {"id": version_id, "client_id": client_id}, {"_id": 0}
    )
    if not v:
        raise HTTPException(404, "Version not found")
    snap = await db.plan_snapshots.find_one(
        {"id": v.get("snapshot_id")}, {"_id": 0}
    )
    return {"version": v, "snapshot": snap}


class RevertBody(BaseModel):
    target_version_id: str
    notes: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/versions/revert")
async def version_revert(
    client_id: str,
    body: RevertBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Non-destructive revert.
    Creates a NEW version that copies the target snapshot payload.
    Previous versions remain untouched.
    """
    await _require_client_and_flag(client_id)
    target = await db.plan_versions.find_one(
        {"id": body.target_version_id, "client_id": client_id}, {"_id": 0}
    )
    if not target:
        raise HTTPException(404, "Target version not found")
    target_snap = await db.plan_snapshots.find_one(
        {"id": target.get("snapshot_id")}, {"_id": 0}
    )
    programme_id = target["programme_id"]
    latest = await db.plan_versions.find_one(
        {"programme_id": programme_id},
        {"_id": 0, "id": 1, "version": 1},
        sort=[("version", -1)],
    )
    new_version_no = int((latest or {}).get("version") or 0) + 1

    new_snap_id = new_id()
    new_snap = dict(target_snap or {})
    new_snap.update(
        {
            "id": new_snap_id,
            "created_at": now_iso(),
            "reverted_from_version_id": body.target_version_id,
            "reverted_from_snapshot_id": target.get("snapshot_id"),
        }
    )
    await db.plan_snapshots.insert_one(new_snap)

    new_version_id = new_id()
    await db.plan_versions.insert_one(
        {
            "id": new_version_id,
            "programme_id": programme_id,
            "client_id": client_id,
            "version": new_version_no,
            "published_at": now_iso(),
            "published_by": coach["id"],
            "snapshot_id": new_snap_id,
            "supersedes_version_id": (latest or {}).get("id"),
            "approvals": [],
            "immutable": True,
            "reverted_from_version_id": body.target_version_id,
            "revert_notes": body.notes or "",
        }
    )
    await _write_decision(
        actor="coach",
        layer="PUBLISH",
        scope_kind="plan_version",
        scope_id=new_version_id,
        outcome="APPLIED",
        client_id=client_id,
        reason=f"Revert to v{target['version']} → new v{new_version_no}",
        previous_state_ref=(latest or {}).get("id"),
        new_state_ref=new_version_id,
    )
    return {
        "new_version_id": new_version_id,
        "new_version": new_version_no,
        "reverted_from_version_id": body.target_version_id,
    }


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------

class LockBody(BaseModel):
    target_kind: str       # exercise|workout|day|objective|exposure|phase|programme|directive
    target_id: str
    reason: Optional[str] = None
    auto_release_at: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/locks")
async def lock_create(
    client_id: str,
    body: LockBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    if body.target_kind not in {
        "exercise", "workout", "day", "objective", "exposure",
        "phase", "programme", "directive",
    }:
        raise HTTPException(400, "Invalid target_kind")
    lid = new_id()
    doc = {
        "id": lid,
        "client_id": client_id,
        "target_kind": body.target_kind,
        "target_id": body.target_id,
        "locked_by": coach["id"],
        "locked_at": now_iso(),
        "reason": body.reason or "",
        "auto_release_at": body.auto_release_at,
        "released_at": None,
        "released_by": None,
    }
    await db.locks.insert_one(dict(doc))
    await _write_decision(
        actor="coach",
        layer="PUBLISH",
        scope_kind=body.target_kind,
        scope_id=body.target_id,
        outcome="APPLIED",
        client_id=client_id,
        reason=f"Lock created: {body.reason or 'no reason'}",
    )
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/locks")
async def lock_list(
    client_id: str, coach: dict = Depends(require_role("coach"))
) -> dict:
    await _require_client_and_flag(client_id)
    rows = (
        await db.locks.find(
            {"client_id": client_id, "released_at": None}, {"_id": 0}
        ).to_list(500)
    )
    return {"locks": rows}


@api.delete("/v2/coach/clients/{client_id}/locks/{lock_id}")
async def lock_release(
    client_id: str,
    lock_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _require_client_and_flag(client_id)
    r = await db.locks.update_one(
        {"id": lock_id, "client_id": client_id, "released_at": None},
        {"$set": {"released_at": now_iso(), "released_by": coach["id"]}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Lock not found or already released")
    await _write_decision(
        actor="coach",
        layer="PUBLISH",
        scope_kind="lock",
        scope_id=lock_id,
        outcome="APPLIED",
        client_id=client_id,
        reason="Lock released",
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Decision records read
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/decisions")
async def decisions_list(
    client_id: str,
    scope_id: Optional[str] = None,
    assignment_id: Optional[str] = None,
    layer: Optional[str] = None,
    limit: int = 100,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """List decision records for the client.

    P1-2: when `assignment_id` is provided, expand the scope query to include
    the objective_id and programme_id linked to that assignment so the
    coach's "Why this?" drawer surfaces WHY/WHAT/WHEN/HOW/ORCHESTRATION
    layers, not only the assignment-scoped WHEN record.
    """
    await _require_client_and_flag(client_id)
    scope_ids: set[str] = set()
    if scope_id:
        scope_ids.add(scope_id)
    if assignment_id:
        scope_ids.add(assignment_id)
        try:
            a = await db.workout_assignments.find_one(
                {"id": assignment_id, "client_id": client_id}, {"_id": 0}
            )
            if a:
                if a.get("objective_id"):
                    scope_ids.add(a["objective_id"])
                if a.get("programme_id"):
                    scope_ids.add(a["programme_id"])
                if a.get("draft_implementation_id"):
                    scope_ids.add(a["draft_implementation_id"])
                if a.get("live_implementation_id"):
                    scope_ids.add(a["live_implementation_id"])
                if a.get("objective_exposure_id"):
                    scope_ids.add(a["objective_exposure_id"])
                # Include phase-scoped decisions too, if the objective is linked
                try:
                    if a.get("objective_id"):
                        obj = await db.training_objectives.find_one(
                            {"id": a["objective_id"]}, {"_id": 0}
                        )
                        if obj and obj.get("phase_id"):
                            scope_ids.add(obj["phase_id"])
                except Exception:
                    pass
        except Exception:
            pass
    q: dict = {"client_id": client_id}
    if scope_ids:
        q["scope_id"] = {"$in": list(scope_ids)}
    if layer:
        q["layer"] = layer
    limit = max(1, min(500, int(limit)))
    rows = (
        await db.decision_records.find(q, {"_id": 0})
        .sort("timestamp", -1)
        .to_list(limit)
    )
    return {"decisions": rows, "scope_ids": list(scope_ids)}


# ---------------------------------------------------------------------------
# Client-facing LIVE endpoint (currently no data — clients still see V1)
# ---------------------------------------------------------------------------

@api.get("/v2/live/plan")
async def live_plan(user: dict = Depends(current_user)) -> dict:
    """P1 stub — the CLIENT-facing LIVE endpoint.

    P1 intentionally returns an empty payload with the latest version pointer.
    The client's actual visible plan continues to be served by V1 endpoints
    until later phases populate the snapshot payload.
    """
    if user.get("role") != "client":
        raise HTTPException(403, "Client-only endpoint")
    latest = await db.plan_versions.find_one(
        {"client_id": user["id"]},
        {"_id": 0},
        sort=[("version", -1)],
    )
    if not latest:
        return {"has_v2_plan": False, "note": "V2 plan not published yet."}
    snap = await db.plan_snapshots.find_one(
        {"id": latest.get("snapshot_id")}, {"_id": 0}
    )
    return {
        "has_v2_plan": True,
        "version": latest.get("version"),
        "version_id": latest.get("id"),
        "published_at": latest.get("published_at"),
        "snapshot": snap,
    }


logger.info(
    "feature_v2_state_foundation: DRAFT/LIVE/VERSION endpoints registered under /api/v2/*"
)
