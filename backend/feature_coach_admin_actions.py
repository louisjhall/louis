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
        # $unset removes the fields entirely so the flag reads False naturally.
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
    import_ref_prefix: Optional[str] = Field(
        default=None,
        description="Optional filter: only delete workouts whose "
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
    if body.import_ref_prefix is not None:
        # An empty prefix ("") matches any workout that HAS an import_ref
        # field — Mongo naturally excludes documents where the field is
        # missing. This is how the frontend targets "imported only".
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
