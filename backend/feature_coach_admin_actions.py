"""feature_coach_admin_actions
=============================

Two small self-service admin endpoints on the coach client workspace:

1. `PATCH /api/v2/coach/clients/{cid}/manual-draft-override`
   Toggle `profile.v2_flags.manual_draft_override` on any client.
   When True the client can run V2 kickoff / publish / regenerate even
   while global MANUAL_MODE is active. Audited via `db.decisions`.

2. `GET  /api/v2/coach/clients/{cid}/manual-draft-override`
   Read the current flag state + audit metadata.

3. `POST /api/coach/clients/{cid}/workouts/bulk-delete`
   Bulk-delete workouts on a client in a date window, optionally filtered
   by source or import_ref. Refuses to delete completed sessions.
   Every deleted row emits a permanent audit trail via `_log_change` and
   is written to `db.decisions` for traceability.

These are coach-only, audit-logged, idempotent-friendly actions.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, now_iso, logger


# ---------------------------------------------------------------------------
# 1. Manual-draft-override toggle
# ---------------------------------------------------------------------------

class ManualDraftOverrideBody(BaseModel):
    enabled: bool
    reason: Optional[str] = None


@api.get("/v2/coach/clients/{client_id}/manual-draft-override")
async def read_manual_draft_override(
    client_id: str, coach: dict = Depends(require_role("coach")),
) -> dict:
    u = await db.users.find_one(
        {"id": client_id},
        {"_id": 0, "id": 1, "email": 1, "profile.v2_flags": 1},
    )
    if not u:
        raise HTTPException(404, "Client not found")
    flags = ((u.get("profile") or {}).get("v2_flags") or {})
    return {
        "client_id": client_id,
        "enabled": bool(flags.get("manual_draft_override")),
        "updated_at": flags.get("manual_draft_override_at"),
        "updated_by": flags.get("manual_draft_override_by"),
        "reason": flags.get("manual_draft_override_reason"),
    }


@api.patch("/v2/coach/clients/{client_id}/manual-draft-override")
async def toggle_manual_draft_override(
    client_id: str, body: ManualDraftOverrideBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    u = await db.users.find_one(
        {"id": client_id},
        {"_id": 0, "id": 1, "email": 1},
    )
    if not u:
        raise HTTPException(404, "Client not found")

    now = now_iso()
    coach_email = coach.get("email") or "unknown"
    coach_id = coach.get("id")

    if body.enabled:
        set_fields = {
            # Enable both the override AND the engine_v2 flag itself — they
            # are pointless separately. The override just bypasses global
            # MANUAL_MODE, but the kickoff endpoint checks `engine_v2` first
            # and returns 409 "Engine V2 not enabled for this client" if
            # missing. Coaches enabling the override are always trying to
            # run Engine V2 on that client, so this is the right coupling.
            "profile.v2_flags.engine_v2": True,
            "profile.v2_flags.manual_draft_override": True,
            "profile.v2_flags.manual_draft_override_at": now,
            "profile.v2_flags.manual_draft_override_by": f"coach:{coach_email}",
            "profile.v2_flags.manual_draft_override_reason":
                (body.reason or "Coach enabled via workspace toggle."),
            "updated_at": now,
        }
        await db.users.update_one({"id": client_id}, {"$set": set_fields})
        outcome = "ENABLED"
    else:
        # $unset removes the override fields entirely so the flag reads
        # False naturally. We DO NOT unset engine_v2 — that's a separate
        # capability flag and other flows may depend on it. Coaches who
        # want to fully disable Engine V2 should use a different action.
        await db.users.update_one(
            {"id": client_id},
            {
                "$unset": {
                    "profile.v2_flags.manual_draft_override": "",
                    "profile.v2_flags.manual_draft_override_at": "",
                    "profile.v2_flags.manual_draft_override_by": "",
                    "profile.v2_flags.manual_draft_override_reason": "",
                },
                "$set": {"updated_at": now},
            },
        )
        outcome = "DISABLED"

    # Audit entry
    try:
        await db.decisions.insert_one({
            "id": f"dec_{client_id}_mdo_{int(_dt.datetime.utcnow().timestamp())}",
            "client_id": client_id,
            "coach_id": coach_id,
            "actor": "coach",
            "layer": "ORCHESTRATION",
            "scope_kind": "manual_draft_override_toggle",
            "scope_id": client_id,
            "outcome": outcome,
            "reason": body.reason
                or f"Coach toggled manual_draft_override → {outcome}",
            "created_at": now,
        })
    except Exception:
        logger.exception("manual_draft_override audit write failed")

    logger.info(
        f"manual_draft_override[{outcome}] client_id={client_id} "
        f"by=coach:{coach_email} reason={(body.reason or '')[:120]!r}"
    )
    return {
        "ok": True,
        "client_id": client_id,
        "enabled": body.enabled,
        "outcome": outcome,
    }


# ---------------------------------------------------------------------------
# 2. Bulk delete workouts
# ---------------------------------------------------------------------------

class BulkDeleteWorkoutsBody(BaseModel):
    start_date: str = Field(
        description="ISO YYYY-MM-DD, inclusive lower bound",
    )
    end_date: str = Field(
        description="ISO YYYY-MM-DD, inclusive upper bound",
    )
    sources: Optional[list[str]] = Field(
        default=None,
        description="Optional filter: only delete workouts whose "
                    "`source` is in this list (e.g. [\"coach_manual\"]).",
    )
    only_imported: bool = Field(
        default=False,
        description="If true, only delete workouts that have an `import_ref` "
                    "field (i.e. were written by the JSON importer). Uses "
                    "$exists so it correctly picks up every imported row.",
    )
    import_ref_prefix: Optional[str] = Field(
        default=None,
        description="Optional narrower filter: only delete workouts whose "
                    "`import_ref` starts with this string.",
    )
    reason: str = Field(..., min_length=3,
                        description="Required — audit trail explanation.")
    confirm: bool = Field(default=False,
                          description="Must be true to actually delete.")


_ISO_DATE = _dt.date.fromisoformat


@api.post("/coach/clients/{client_id}/workouts/bulk-delete")
async def bulk_delete_workouts(
    client_id: str, body: BulkDeleteWorkoutsBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not body.confirm:
        raise HTTPException(
            400,
            "confirmation required — set confirm=true to actually delete",
        )
    try:
        d0 = _ISO_DATE(body.start_date)
        d1 = _ISO_DATE(body.end_date)
    except ValueError:
        raise HTTPException(400, "start_date/end_date must be YYYY-MM-DD")
    if d1 < d0:
        raise HTTPException(400, "end_date must be >= start_date")

    u = await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1, "email": 1})
    if not u:
        raise HTTPException(404, "Client not found")

    q: dict = {
        "user_id": client_id,
        "date": {"$gte": body.start_date, "$lte": body.end_date},
    }
    if body.sources:
        q["source"] = {"$in": body.sources}
    if body.only_imported:
        # Iter 140d — use $exists so we correctly identify every row the
        # JSON importer touched. A prefix regex missed rows whose
        # import_ref started with a slash / non-word character.
        q["import_ref"] = {"$exists": True, "$ne": None}
    if body.import_ref_prefix is not None:
        # An empty prefix ("") matches any workout that HAS an import_ref
        # field — Mongo naturally excludes documents where the field is
        # missing.
        q["import_ref"] = {"$regex": f"^{body.import_ref_prefix}"}

    # Refuse to delete completed sessions — surface them to the caller.
    completed = await db.workouts.count_documents(
        {**q, "completed": True},
    )
    if completed:
        raise HTTPException(
            409,
            f"{completed} workout(s) in this range are marked completed. "
            "Delete completed sessions individually via the workout view.",
        )

    # Fetch what we're about to delete so we can write per-row audit rows.
    to_delete = await db.workouts.find(
        q, {"_id": 0, "id": 1, "date": 1, "title": 1, "workout_type": 1,
            "source": 1, "import_ref": 1, "manual_lock": 1}
    ).sort("date", 1).to_list(length=None)
    if not to_delete:
        return {"ok": True, "deleted_count": 0, "deleted": []}

    now = now_iso()
    coach_id = coach.get("id")
    coach_email = coach.get("email") or "unknown"

    # Best-effort: fire per-row audit via _log_change if available.
    try:
        from server import _log_change  # type: ignore
    except Exception:
        _log_change = None  # type: ignore

    for w in to_delete:
        if _log_change:
            try:
                await _log_change(
                    coach_id=coach_id, client_id=client_id,
                    category="workout", kind="workout_bulk_delete",
                    title=f"Bulk delete workout on {w.get('date')}",
                    description=body.reason,
                    actor="coach",
                    meta={
                        "workout_id": w.get("id"), "date": w.get("date"),
                        "title": w.get("title"),
                        "workout_type": w.get("workout_type"),
                        "source": w.get("source"),
                        "import_ref": w.get("import_ref"),
                        "manual_lock": w.get("manual_lock"),
                        "range": [body.start_date, body.end_date],
                        "filters": {
                            "sources": body.sources,
                            "import_ref_prefix": body.import_ref_prefix,
                        },
                    },
                )
            except Exception:
                logger.exception("bulk_delete: _log_change failed for wid=%s", w.get("id"))

    res = await db.workouts.delete_many(q)

    # One consolidated decision row for the whole batch.
    try:
        await db.decisions.insert_one({
            "id": f"dec_{client_id}_bulkdel_{int(_dt.datetime.utcnow().timestamp())}",
            "client_id": client_id,
            "coach_id": coach_id,
            "actor": "coach",
            "layer": "ORCHESTRATION",
            "scope_kind": "workout_bulk_delete",
            "scope_id": client_id,
            "outcome": f"deleted {res.deleted_count}",
            "reason": body.reason,
            "created_at": now,
            "meta": {
                "range": [body.start_date, body.end_date],
                "filters": {
                    "sources": body.sources,
                    "import_ref_prefix": body.import_ref_prefix,
                },
                "deleted_ids": [w.get("id") for w in to_delete],
            },
        })
    except Exception:
        logger.exception("bulk_delete: decision audit write failed")

    logger.info(
        f"workout_bulk_delete client_id={client_id} coach={coach_email} "
        f"range=[{body.start_date}..{body.end_date}] sources={body.sources} "
        f"import_ref_prefix={body.import_ref_prefix!r} deleted={res.deleted_count}"
    )

    return {
        "ok": True,
        "deleted_count": res.deleted_count,
        "deleted": [
            {"id": w.get("id"), "date": w.get("date"),
             "title": w.get("title"), "source": w.get("source"),
             "import_ref": w.get("import_ref")}
            for w in to_delete
        ],
    }


logger.info(
    "feature_coach_admin_actions: /api/v2/coach/clients/*/manual-draft-override "
    "+ /api/coach/clients/*/workouts/bulk-delete registered"
)


# ---------------------------------------------------------------------------
# 3. Hard-delete a single workout / assignment / implementation
# ---------------------------------------------------------------------------

class HardDeleteWorkoutBody(BaseModel):
    workout_id: Optional[str] = Field(
        default=None,
        description="ID from db.workouts (legacy + JSON-imported rows).",
    )
    assignment_id: Optional[str] = Field(
        default=None,
        description="ID from db.workout_assignments (V2 plan). If provided, "
                    "the linked draft & live implementations are also deleted.",
    )
    implementation_id: Optional[str] = Field(
        default=None,
        description="ID from db.workout_implementations. Deletes just this "
                    "implementation and clears the pointer on its assignment.",
    )
    force: bool = Field(
        default=False,
        description="Bypass completed / coach_locked / manual_lock guards. "
                    "REQUIRED when deleting a row with any of those flags set.",
    )
    reason: str = Field(
        ..., min_length=3,
        description="Audit trail — why this workout was hard-deleted.",
    )


@api.post("/coach/clients/{client_id}/workouts/hard-delete")
async def hard_delete_workout(
    client_id: str, body: HardDeleteWorkoutBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Hard-delete a single workout card from the coach calendar. Handles all
    three shapes the calendar might render:

      - `db.workouts` (legacy / JSON-imported / manual)
      - `db.workout_assignments` (V2 plan) — cascades to
        `db.workout_implementations` (draft + live) and bumps the active
        plan_drafts_v2.version so downstream state endpoints see a fresh
        signature.
      - `db.workout_implementations` (direct impl id) — deletes the impl and
        clears the pointer on its parent assignment.

    Guards (completed / coach_locked / manual_lock) protect the row by
    default. Set `force=true` to bypass them.

    Returns a summary of what was actually removed.
    """
    if not any([body.workout_id, body.assignment_id, body.implementation_id]):
        raise HTTPException(
            400,
            "Provide exactly one of workout_id, assignment_id, "
            "implementation_id",
        )

    now = now_iso()
    coach_id = coach.get("id")
    coach_email = coach.get("email") or "unknown"
    summary: dict = {
        "workouts_deleted": 0,
        "assignments_deleted": 0,
        "implementations_deleted": 0,
        "plan_version_bumped": False,
        "guards_bypassed": [],
    }

    def _check_guard(doc: dict, kind: str) -> None:
        blockers = []
        if doc.get("completed"):
            blockers.append("completed")
        if doc.get("coach_locked"):
            blockers.append("coach_locked")
        if doc.get("manual_lock"):
            blockers.append("manual_lock")
        if blockers and not body.force:
            raise HTTPException(
                409,
                f"{kind} is protected by {'+'.join(blockers)}. "
                "Set force=true to bypass.",
            )
        if blockers:
            summary["guards_bypassed"].extend([f"{kind}:{b}" for b in blockers])

    # ----- Branch A0: synthetic v2p:{source_id}:{exposure_id} id -----
    # These ids don't exist in db.workouts — they synth from either
    # plan_live_v2 (published) or plan_drafts_v2 (in-flight review).
    # Delete = pull the placement out of the placements array and
    # unset the corresponding session_specs entry. Preserve the doc
    # itself; bump `version` on drafts so downstream state endpoints
    # notice the change.
    if body.workout_id and str(body.workout_id).startswith("v2p:"):
        parts = str(body.workout_id).split(":", 2)
        if len(parts) < 3:
            raise HTTPException(400, "malformed v2p workout id")
        source_id, exposure_id = parts[1], parts[2]

        target_coll = None      # "plan_live_v2" or "plan_drafts_v2"
        target_doc = None
        # 1. Try live first
        target_doc = await db.plan_live_v2.find_one(
            {"id": source_id, "client_id": client_id}, {"_id": 0},
        )
        if target_doc:
            target_coll = "plan_live_v2"
        else:
            # 2. Fall back to in-review or already-published drafts (Iter 147:
            # 'published' added — some coach workflows keep the draft doc as
            # the authoritative source even after publication until it's
            # superseded).
            target_doc = await db.plan_drafts_v2.find_one(
                {"id": source_id, "client_id": client_id,
                 "status": {"$in": ["needs_review", "ready_for_review", "published"]}},
                {"_id": 0},
            )
            if target_doc:
                target_coll = "plan_drafts_v2"
        if not target_coll or not target_doc:
            raise HTTPException(404, "v2p source not found in plan_live_v2 or plan_drafts_v2")

        # Guard: is this specific placement completed / coach_locked?
        placement = next(
            (p for p in (target_doc.get("placements") or [])
             if p.get("exposure_id") == exposure_id),
            None,
        )
        if placement:
            _check_guard(placement, f"{target_coll} placement:{exposure_id[:8]}")
        else:
            raise HTTPException(404, f"exposure_id {exposure_id} not found in {target_coll} placements")

        update = {
            "$pull": {"placements": {"exposure_id": exposure_id}},
            "$unset": {f"session_specs.{exposure_id}": ""},
            "$set": {"updated_at": now, "last_edit_kind": "hard_delete",
                     "last_edit_by": coach_id},
        }
        coll = getattr(db, target_coll)
        r = await coll.update_one({"id": source_id}, update)
        # Count success as one "workout deletion" for the summary.
        summary["workouts_deleted"] = 1 if r.modified_count else 0

        # Bump version on drafts so the coach dashboard sees a fresh signature.
        if target_coll == "plan_drafts_v2":
            new_version = int(target_doc.get("version") or 0) + 1
            await db.plan_drafts_v2.update_one(
                {"id": source_id},
                {"$set": {"version": new_version, "updated_at": now}},
            )
            summary["plan_version_bumped"] = True
            summary["new_plan_version"] = new_version

    # ----- Branch A: workout_id (db.workouts) -----
    elif body.workout_id:
        w = await db.workouts.find_one(
            {"id": body.workout_id, "user_id": client_id},
            {"_id": 0},
        )
        if not w:
            raise HTTPException(404, "workout_id not found on this client")
        _check_guard(w, "workout")
        # Also delete any linked assignment/implementation if the workout
        # carries pointers (some legacy rows do).
        if w.get("assignment_id"):
            body.assignment_id = w["assignment_id"]  # fall through
        res = await db.workouts.delete_one({"id": body.workout_id})
        summary["workouts_deleted"] = res.deleted_count

    # ----- Branch B: assignment_id (V2 plan) -----
    if body.assignment_id:
        a = await db.workout_assignments.find_one(
            {"id": body.assignment_id, "client_id": client_id},
            {"_id": 0},
        )
        if a:
            _check_guard(a, "assignment")
            impl_ids: list[str] = []
            for k in ("draft_implementation_id", "live_implementation_id"):
                if a.get(k):
                    impl_ids.append(a[k])
            # Guard each impl individually so a completed live impl still
            # blocks the delete unless force=true.
            for iid in impl_ids:
                impl = await db.workout_implementations.find_one(
                    {"id": iid}, {"_id": 0},
                )
                if impl:
                    _check_guard(impl, f"implementation:{iid[:8]}")
            if impl_ids:
                r_impl = await db.workout_implementations.delete_many(
                    {"id": {"$in": impl_ids}},
                )
                summary["implementations_deleted"] += r_impl.deleted_count
            r_ass = await db.workout_assignments.delete_one(
                {"id": body.assignment_id},
            )
            summary["assignments_deleted"] += r_ass.deleted_count
            # Bump the active draft's version so state endpoints see a fresh
            # signature. Only bump the ACTIVE (non-published, non-superseded)
            # draft — historical drafts are immutable.
            draft = await db.plan_drafts_v2.find_one(
                {"client_id": client_id,
                 "status": {"$nin": ["published", "superseded"]}},
                {"_id": 0, "id": 1, "version": 1},
                sort=[("created_at", -1)],
            )
            if draft:
                new_version = int(draft.get("version") or 0) + 1
                await db.plan_drafts_v2.update_one(
                    {"id": draft["id"]},
                    {"$set": {
                        "version": new_version,
                        "updated_at": now,
                        "last_edit_kind": "hard_delete",
                        "last_edit_by": coach_id,
                    }},
                )
                summary["plan_version_bumped"] = True
                summary["new_plan_version"] = new_version

    # ----- Branch C: implementation_id (direct) -----
    elif body.implementation_id:
        impl = await db.workout_implementations.find_one(
            {"id": body.implementation_id}, {"_id": 0},
        )
        if not impl:
            raise HTTPException(404, "implementation_id not found")
        _check_guard(impl, "implementation")
        # Clear the pointer on the parent assignment(s).
        await db.workout_assignments.update_many(
            {"$or": [
                {"draft_implementation_id": body.implementation_id},
                {"live_implementation_id": body.implementation_id},
            ]},
            {"$set": {"updated_at": now},
             "$unset": {"draft_implementation_id": "",
                        "live_implementation_id": ""}},
        )
        r = await db.workout_implementations.delete_one(
            {"id": body.implementation_id},
        )
        summary["implementations_deleted"] = r.deleted_count

    # ----- Audit trail -----
    try:
        await db.decisions.insert_one({
            "id": f"dec_{client_id}_harddel_{int(_dt.datetime.utcnow().timestamp())}",
            "client_id": client_id,
            "coach_id": coach_id,
            "actor": "coach",
            "layer": "ORCHESTRATION",
            "scope_kind": "workout_hard_delete",
            "scope_id": (body.workout_id or body.assignment_id
                         or body.implementation_id),
            "outcome": "HARD_DELETED",
            "reason": body.reason,
            "created_at": now,
            "meta": {
                "workout_id": body.workout_id,
                "assignment_id": body.assignment_id,
                "implementation_id": body.implementation_id,
                "force": body.force,
                **summary,
            },
        })
    except Exception:
        logger.exception("hard_delete: decision audit write failed")

    logger.info(
        f"workout_hard_delete client_id={client_id} coach={coach_email} "
        f"workout_id={body.workout_id} assignment_id={body.assignment_id} "
        f"implementation_id={body.implementation_id} force={body.force} "
        f"summary={summary}"
    )

    if not (summary["workouts_deleted"]
            or summary["assignments_deleted"]
            or summary["implementations_deleted"]):
        raise HTTPException(404, "Nothing found to delete for the given IDs")

    return {"ok": True, **summary}


logger.info(
    "feature_coach_admin_actions: /api/coach/clients/*/workouts/hard-delete "
    "registered"
)
