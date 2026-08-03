"""
feature_v2_p12_automation — V2 Phase 12: Job runner + shadow mode + metrics.

Provides a durable-ish job runner (Mongo-backed, idempotent by
`idempotency_key`) and a shadow-mode endpoint that runs the V2 pipeline
without affecting the client's LIVE V1 view.

Ships behind `v2_flags.automation_v2_enabled` and (for shadow) `shadow_mode`.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg, emit_metric, flag_on
)

FLAG = "automation_v2_enabled"


# ---------------------------------------------------------------------------
# Job queue
# ---------------------------------------------------------------------------

class JobBody(BaseModel):
    kind: str
    input: dict = {}
    idempotency_key: Optional[str] = None
    max_attempts: int = 3


@api.post("/v2/coach/clients/{client_id}/jobs")
async def job_enqueue(
    client_id: str, body: JobBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    idem = body.idempotency_key or f"{body.kind}::{client_id}::{now_iso()}"
    # Idempotency: return existing if present
    existing = await db.jobs.find_one({"idempotency_key": idem}, {"_id": 0})
    if existing:
        return {"job": existing, "deduped": True}
    jid = new_id()
    doc = {
        "id": jid,
        "kind": body.kind,
        "target_scope": {"client_id": client_id},
        "status": "queued",
        "attempts": 0,
        "max_attempts": body.max_attempts,
        "idempotency_key": idem,
        "input": body.input,
        "output": None,
        "error": None,
        "progress": {"stage": "queued", "pct": 0},
        "scheduled_at": now_iso(),
        "started_at": None,
        "completed_at": None,
        "worker_id": None,
        "dependencies": [],
    }
    await db.jobs.insert_one(dict(doc))
    doc.pop("_id", None)
    return {"job": doc, "deduped": False}


@api.get("/v2/coach/clients/{client_id}/jobs")
async def job_list(
    client_id: str, status: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await require_client_and_flag(client_id, FLAG)
    q: dict = {"target_scope.client_id": client_id}
    if status: q["status"] = status
    rows = await db.jobs.find(q, {"_id": 0}).sort("scheduled_at", -1).to_list(50)
    return {"jobs": rows}


# Job handlers — each takes the job doc, returns the output dict.
_JOB_HANDLERS: dict[str, callable] = {}


def _register_handler(kind: str):
    def _wrap(fn):
        _JOB_HANDLERS[kind] = fn
        return fn
    return _wrap


@_register_handler("draft_build")
async def _handle_draft_build(job: dict) -> dict:
    """Execute the full V2 build pipeline for a client, end-to-end:
      P4 roster-facets → P3 objectives-build → P3 window-create → P5 plan-build → P6 build-implementations.
    """
    client_id = (job.get("target_scope") or {}).get("client_id")
    inp = job.get("input") or {}
    programme_id = inp.get("programme_id")

    from feature_v2_p4_roster import roster_facets_build, BuildRosterFacetsBody
    from feature_v2_p3_demand import objectives_build, BuildDemandBody, window_create, WindowBody
    from feature_v2_p5_scheduling import plan_build, BuildPlanBody
    from feature_v2_p6_construction import implementations_build, BuildImplBody

    class _Coach: id = "system"
    coach = {"id": "system"}   # bypass require_role via direct call

    output = {}
    try:
        r = await roster_facets_build(client_id, BuildRosterFacetsBody(all_active=True), coach)
        output["roster_facets"] = r
    except Exception as e:
        output["roster_facets_error"] = str(e)

    try:
        o = await objectives_build(client_id, BuildDemandBody(programme_id=programme_id), coach)
        output["objectives"] = o
    except Exception as e:
        output["objectives_error"] = str(e)

    try:
        import datetime as _dt
        sd = _dt.date.today().isoformat()
        ed = (_dt.date.today() + _dt.timedelta(days=27)).isoformat()
        w = await window_create(client_id, WindowBody(programme_id=programme_id, start_date=sd, end_date=ed), coach)
        output["window"] = w
    except Exception as e:
        output["window_error"] = str(e)

    try:
        p = await plan_build(client_id, BuildPlanBody(programme_id=programme_id), coach)
        output["plan"] = p
    except Exception as e:
        output["plan_error"] = str(e)

    try:
        i = await implementations_build(client_id, BuildImplBody(programme_id=programme_id), coach)
        output["implementations"] = i
    except Exception as e:
        output["implementations_error"] = str(e)

    return output


async def _run_one_job(job: dict) -> None:
    kind = job["kind"]
    handler = _JOB_HANDLERS.get(kind)
    started = now_iso()
    await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": "in_progress", "started_at": started,
                                                            "attempts": (job.get("attempts") or 0) + 1}})
    try:
        if not handler:
            raise RuntimeError(f"No handler for job kind: {kind}")
        out = await handler(job)
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": "succeeded", "output": out,
                                                                "completed_at": now_iso(),
                                                                "progress": {"stage": "done", "pct": 100}}})
        await emit_metric("job_succeeded", labels={"kind": kind})
    except Exception as e:
        attempts = (job.get("attempts") or 0) + 1
        status = "failed" if attempts >= (job.get("max_attempts") or 3) else "queued"
        if attempts >= (job.get("max_attempts") or 3):
            status = "dead_letter"
        await db.jobs.update_one({"id": job["id"]}, {"$set": {"status": status, "error": str(e),
                                                                "completed_at": now_iso(),
                                                                "progress": {"stage": "error", "pct": 0}}})
        await emit_metric("job_failed", labels={"kind": kind, "error_type": type(e).__name__})
        logger.warning(f"V2 job {job['id']} ({kind}) failed: {e}")


@api.post("/v2/coach/clients/{client_id}/jobs/{job_id}/run")
async def job_run(
    client_id: str, job_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    from feature_v2_common import require_auto_gen_allowed
    require_auto_gen_allowed()
    await require_client_and_flag(client_id, FLAG)
    job = await db.jobs.find_one({"id": job_id, "target_scope.client_id": client_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] not in ("queued", "failed"):
        raise HTTPException(409, f"Job status is {job['status']}")
    await _run_one_job(job)
    return await db.jobs.find_one({"id": job_id}, {"_id": 0})


# ---------------------------------------------------------------------------
# Shadow mode — dry-run the V2 pipeline without affecting client's LIVE view
# ---------------------------------------------------------------------------

@api.post("/v2/coach/clients/{client_id}/shadow/build")
async def shadow_build(
    client_id: str, programme_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Run the V2 build pipeline into `plan_shadows` for coach-only inspection.

    Nothing here touches V1 collections or the client's LIVE view.
    Requires `shadow_mode` flag OR `automation_v2_enabled`.
    """
    on = await flag_on(client_id, "shadow_mode") or await flag_on(client_id, FLAG)
    if not on:
        raise HTTPException(409, "Shadow mode not enabled for this client")

    fake_job = {"id": "shadow", "kind": "draft_build",
                "target_scope": {"client_id": client_id},
                "input": {"programme_id": programme_id}}
    out = await _handle_draft_build(fake_job)
    shadow_id = new_id()
    await db.plan_shadows.insert_one({
        "id": shadow_id,
        "client_id": client_id,
        "programme_id": programme_id,
        "created_at": now_iso(),
        "output_summary": out,
    })
    await write_decision(
        actor="coach", layer="PUBLISH", scope_kind="plan_shadow", scope_id=shadow_id,
        client_id=client_id, outcome="APPLIED",
        reason="V2 shadow build executed (not visible to client)",
    )
    return {"shadow_id": shadow_id, "summary": out}


# ---------------------------------------------------------------------------
# Metrics read
# ---------------------------------------------------------------------------

@api.get("/v2/admin/metrics")
async def metrics_list(
    event_name: Optional[str] = None,
    client_id: Optional[str] = None,
    limit: int = 200,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    q: dict = {}
    if event_name: q["event_name"] = event_name
    if client_id:  q["client_id"] = client_id
    limit = max(1, min(1000, int(limit)))
    rows = await db.metrics_events.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return {"metrics": rows}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("jobs", [
        ([("kind", 1), ("status", 1), ("scheduled_at", 1)], False, "jobs_kind_status_time"),
        ([("idempotency_key", 1)], True, "jobs_idem_unique"),
        ([("target_scope.client_id", 1)], False, "jobs_target_client"),
    ])
    await ensure_indexes("metrics_events", [
        ([("event_name", 1), ("timestamp", -1)], False, "metrics_event_time"),
        ([("client_id", 1)], False, "metrics_client"),
    ])
    await ensure_indexes("plan_shadows", [
        ([("client_id", 1), ("created_at", -1)], False, "shadow_client_time"),
    ])
    await ensure_indexes("decision_records", [
        ([("scope_id", 1), ("timestamp", -1)], False, "dr_scope_time"),
        ([("actor", 1), ("layer", 1)], False, "dr_actor_layer"),
        ([("layer", 1), ("outcome", 1), ("timestamp", -1)], False, "dr_layer_outcome"),
    ])

bg(_bootstrap())


logger.info("feature_v2_p12_automation: /api/v2 jobs + shadow + metrics endpoints registered")
