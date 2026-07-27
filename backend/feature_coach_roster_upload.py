"""
feature_coach_roster_upload — Phase A · A2 of the Coach Dashboard rebuild.

Adds coach-side endpoints so Louis can upload a roster ON BEHALF OF a
client and immediately push it live. This is a coach convenience path;
the client's own upload flow (feature_roster_confirmation) is
unchanged and remains the source-of-truth for parsing + confirmation.

Endpoints:
    * POST /api/coach/clients/{cid}/roster/upload-parse
        Parse a roster on behalf of the client. Stores it as a
        `pending_confirmation` roster owned by the client. Returns a
        job_id the coach UI polls via GET /api/roster/jobs/{job_id}.
        The coach can then review + confirm via the coach-confirm
        endpoint below (or the client sees it in their pending list —
        both flows work).

    * POST /api/coach/clients/{cid}/roster/pending/{rid}/confirm
        Coach-side confirmation of a pending roster. Bypasses the
        "all low-confidence days must be reviewed" client-side gate
        (the coach IS the reviewer). Reuses the same activation +
        generation pipeline the client-facing endpoint uses.

Product notes:
    * "Uploaded_by = 'coach'" metadata is stamped so we can badge these
      in the roster history drawer.
    * Overlap semantics match the client flow: only rosters that
      overlap the new date range get superseded. Non-overlapping
      months (July + August split across two uploads) both remain
      active — this is what unblocks the "July disappeared" class of
      bug at the workflow layer.
"""
from __future__ import annotations

import asyncio as _asyncio
import os
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api,
    db,
    require_role,
    new_id,
    now_iso,
    logger,
    write_temp,
    call_gemini_file,
    parse_json_from_text,
    _detect_overlap,
    _generate_month,
    _generation_heartbeat,
    _set_job,
    _open_coach_task_for_stuck_generation,
    _notify_coaches_of_new_roster,
    _merge_variants,
    ROSTER_SYSTEM,
)

# We reuse the helpers from feature_roster_confirmation to avoid
# duplicating the label-enrichment + persistence logic.
from feature_roster_confirmation import (
    _apply_day_defaults,
    _persist_pending_roster,
    _needs_review,
)


class CoachRosterUploadBody(BaseModel):
    file_base64: str
    mime_type: str
    filename: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /coach/clients/{cid}/roster/upload-parse
# ---------------------------------------------------------------------------

@api.post("/coach/clients/{client_id}/roster/upload-parse")
async def coach_upload_parse(
    client_id: str,
    body: CoachRosterUploadBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Parse a roster on behalf of a client.

    Same worker as the client-side `/roster/upload-parse` — just
    scoped to the target client's user_id and stamped with
    `uploaded_by='coach'`.
    """
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")

    job_id = new_id()
    now = now_iso()
    await db.roster_jobs.insert_one({
        "id": job_id,
        "user_id": client_id,
        "coach_id": coach["id"],
        "uploaded_by": "coach",
        "status": "queued",
        "stage": "uploading",
        "message": "Uploading roster...",
        "progress": 1,
        "created_at": now,
        "updated_at": now,
        "filename": body.filename or "roster",
        "flow": "coach_parse_only",
        "pending_roster_id": None,
        "roster_id": None,
        "error": None,
        "overlap": None,
        "retry_count": 0,
    })

    async def _worker():
        path: Optional[str] = None
        try:
            await _set_job(job_id, status="processing", stage="uploading", progress=5, message="Uploading roster...")
            path = await write_temp(body.file_base64, body.mime_type)

            days: list = []
            raw = ""
            parser_source = "llm"
            if (body.mime_type or "").lower() == "application/pdf":
                try:
                    from parsers.etihad import detect_etihad, parse_etihad_pdf, to_crewfit_days as etihad_to_days
                    from parsers.emirates import detect_emirates, parse_emirates_pdf, to_crewfit_days as emirates_to_days
                    with open(path, "rb") as fh:
                        pdf_bytes = fh.read()
                    if detect_etihad(pdf_bytes):
                        await _set_job(job_id, stage="reading", progress=20, message="Reading Etihad roster...")
                        pr = parse_etihad_pdf(pdf_bytes, filename=body.filename)
                        days = etihad_to_days(pr)
                        parser_source = "etihad_parser_v1"
                        raw = f"etihad-parser: {len(days)} days, confidence={pr.parse_confidence}"
                    elif detect_emirates(pdf_bytes):
                        await _set_job(job_id, stage="reading", progress=20, message="Reading Emirates roster...")
                        pr = parse_emirates_pdf(pdf_bytes, filename=body.filename)
                        days = emirates_to_days(pr)
                        parser_source = "emirates_parser_v1"
                        raw = f"emirates-parser: {len(days)} days, confidence={pr.parse_confidence}"
                except Exception as e:
                    logger.warning("Coach upload — airline parser skipped: %s", e)
                    days = []

            if not days:
                await _set_job(job_id, stage="reading", progress=20, message="Reading roster...")
                try:
                    raw = await call_gemini_file(ROSTER_SYSTEM, "Extract the complete roster shown. Return only JSON.", path, body.mime_type)
                except Exception as e:
                    logger.warning("Coach upload — LLM roster call failed: %s", e)
                await _set_job(job_id, stage="extracting", progress=45, message="Extracting duties...")
                parsed: Any = {}
                try:
                    parsed = parse_json_from_text(raw) if raw else {}
                except Exception as e:
                    logger.warning("Coach upload — parse failed: %s", e)
                days = parsed.get("days", []) if isinstance(parsed, dict) else parsed

            if not days:
                await _set_job(
                    job_id, status="failed", stage="extracting", progress=45,
                    error="Roster couldn't be read clearly. Try a clearer file.",
                    message="Roster could not be read",
                )
                return

            await _set_job(job_id, stage="detecting", progress=65, message="Detecting layovers and turnarounds...")
            days = _apply_day_defaults(days)
            overlap = await _detect_overlap(client_id, days)
            pending = await _persist_pending_roster(
                client_id, days, body.filename or "roster", raw, job_id
            )
            try:
                await db.rosters.update_one(
                    {"id": pending["id"]},
                    {"$set": {
                        "parser_source": parser_source,
                        "overlap": overlap,
                        "uploaded_by": "coach",
                        "uploaded_by_coach_id": coach["id"],
                    }},
                )
            except Exception:
                pass
            await _set_job(
                job_id,
                pending_roster_id=pending["id"],
                overlap=overlap,
                status="awaiting_confirmation",
                stage="ready_to_confirm",
                progress=100,
                message="Roster ready to review",
                completed_at=now_iso(),
            )
        except Exception as e:
            logger.exception("coach roster parse job %s failed", job_id)
            await _set_job(job_id, status="failed", error=str(e)[:400], message="Roster processing failed")
        finally:
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass

    _asyncio.create_task(_worker())
    return {"job_id": job_id, "status": "queued", "poll": f"/roster/jobs/{job_id}"}


# ---------------------------------------------------------------------------
# POST /coach/clients/{cid}/roster/pending/{rid}/confirm
# ---------------------------------------------------------------------------

@api.post("/coach/clients/{client_id}/roster/pending/{rid}/confirm")
async def coach_pending_confirm(
    client_id: str,
    rid: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Coach-side confirmation of a pending roster.

    Same activation + generation pipeline as the client-facing
    confirm endpoint, but scoped to the target client's user_id and
    stamped with `confirmed_by='coach'`.

    Unlike the client flow, this does NOT enforce that every
    low-confidence day be reviewed first — the coach IS the reviewer.
    """
    pending = await db.rosters.find_one(
        {"id": rid, "user_id": client_id, "status": "pending_confirmation"},
        {"_id": 0},
    )
    if not pending:
        raise HTTPException(404, "Pending roster not found for this client")

    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")

    now = now_iso()
    days = pending.get("days") or []

    # Overlap-aware deactivation — supersede only the rosters that
    # actually overlap the new roster's date range. Non-overlapping
    # months (e.g. July + August split) remain active side-by-side.
    try:
        pending_dates = {d.get("date") for d in days if d.get("date")}
        if pending_dates:
            start = min(pending_dates); end = max(pending_dates)
            await db.rosters.update_many(
                {
                    "user_id": client_id, "is_active": True,
                    "id": {"$ne": rid},
                    "start_date": {"$lte": end}, "end_date": {"$gte": start},
                },
                {"$set": {"is_active": False}},
            )
            superseded = await db.rosters.find({
                "user_id": client_id, "id": {"$ne": rid},
                "start_date": {"$lte": end}, "end_date": {"$gte": start},
                "status": {"$in": ["confirmed", "expired"]},
            }, {"_id": 0, "id": 1}).to_list(20)
            if superseded:
                ids = [s["id"] for s in superseded]
                await db.rosters.update_many(
                    {"id": {"$in": ids}},
                    {"$set": {"status": "superseded", "superseded_by": rid, "superseded_at": now}},
                )
    except Exception:
        logger.exception("Coach confirm — overlap deactivation failed; falling back to legacy")
        await db.rosters.update_many(
            {"user_id": client_id, "is_active": True, "id": {"$ne": rid}},
            {"$set": {"is_active": False}},
        )

    await db.rosters.update_one(
        {"id": rid},
        {"$set": {
            "is_active": True,
            "status": "confirmed",
            "confirmed": True,
            "confirmed_at": now,
            "confirmed_by": "coach",
            "confirmed_by_coach_id": coach["id"],
            "updated_at": now,
        }},
    )
    roster = await db.rosters.find_one({"id": rid}, {"_id": 0})

    # Phase 7A hooks — client notification + coach approval task.
    try:
        from feature_programme_status import create_upload_confirmation_message, create_coach_approval_task
        await create_upload_confirmation_message(client_id)
        await create_coach_approval_task(client_id, rid)
    except Exception:
        logger.exception("Phase 7A post-confirm hooks failed (non-fatal)")

    # V2 bridge — for V2-flagged clients, immediately materialise
    # schedule_days / roster_duties / flight_sectors from the confirmed
    # V1 roster so the V2 coach workspace stops showing
    # "V1 roster · read-only" and P5 can build a draft.
    try:
        client_v2 = ((client.get("profile") or {}).get("v2_flags") or {})
        if client_v2.get("v2_default") or client_v2.get("state_foundation_enabled") or client_v2.get("roster_facets_enabled"):
            from feature_v2_p4_roster import _build_roster_facets
            bridge_result = await _build_roster_facets(
                client_id=client_id, roster_id=rid, all_active=False,
                actor_id=coach["id"],
            )
            logger.info(
                "coach-confirm V2 bridge: client=%s roster=%s → %s days, %s duties, %s sectors",
                client_id, rid, bridge_result.get("schedule_days"),
                bridge_result.get("duties"), bridge_result.get("sectors"),
            )
    except Exception:
        logger.exception("coach-confirm: V2 roster-facets bridge failed (non-fatal)")

    # Kick off workout generation (same worker shape as the client flow).
    job_id = new_id()
    await db.roster_jobs.insert_one({
        "id": job_id, "user_id": client_id, "coach_id": coach["id"],
        "uploaded_by": "coach",
        "status": "processing", "stage": "generating",
        "message": "Generating personalised plan...",
        "progress": 80, "created_at": now,
        "filename": pending.get("source_filename") or "roster",
        "flow": "coach_confirm_build",
        "roster_id": rid, "pending_roster_id": rid,
        "error": None, "overlap": None, "retry_count": 0,
    })

    async def _worker():
        heartbeat_task = _asyncio.create_task(_generation_heartbeat(job_id))
        programme_ctx = None
        try:
            from feature_programme_quality import programme_context_for_llm
            programme_ctx = await programme_context_for_llm(client, roster)
        except Exception:
            logger.exception("coach-confirm: programme_context failed")
        try:
            workouts = await _asyncio.wait_for(
                _generate_month(client, roster, programme_ctx=programme_ctx),
                timeout=180.0,
            )
        except Exception as e:
            logger.warning("coach-confirm: generation failed/timeout: %s — template fallback", e)
            workouts = []

        used_template = False
        try:
            from feature_workout_fallback import build_template_plan, is_empty_or_llm_failure
            from feature_hotel_system import load_hotel_lookup_for_roster
            from feature_progression import get_current_status
            if is_empty_or_llm_failure(workouts):
                hotel_lookup = await load_hotel_lookup_for_roster(db, roster)
                prog_status = await get_current_status(db, client_id)
                workouts = build_template_plan(client, roster, hotel_lookup=hotel_lookup, progression_status=prog_status)
                used_template = bool(workouts)
                if workouts:
                    try:
                        from feature_v2_resolver import apply_resolver_to_workouts
                        await apply_resolver_to_workouts(workouts, user=client, roster=roster)
                    except Exception:
                        logger.exception("coach-confirm: v2 resolver failed on fallback")
        except Exception:
            logger.exception("coach-confirm: template fallback failed")
        finally:
            heartbeat_task.cancel()

        existing = {
            w["date"]: w for w in await db.workouts.find(
                {"user_id": client_id, "roster_id": rid}, {"_id": 0}
            ).to_list(500)
        }
        for w in workouts:
            d = w.get("date")
            if not d:
                continue
            prev = existing.get(d)
            if prev and (prev.get("coach_locked") or prev.get("completed")):
                continue
            doc = {
                "id": prev["id"] if prev else new_id(),
                "user_id": client_id, "roster_id": rid, "date": d,
                "day_load": w.get("day_load", "green"),
                "title": w.get("title", "Session"),
                "location": w.get("location", "Home Workout"),
                "duration_min": w.get("duration_min", 40),
                "focus": w.get("focus", "full"),
                "warmup": w.get("warmup", []),
                "exercises": w.get("exercises", []),
                "alternatives": w.get("alternatives", {}),
                "rationale": w.get("rationale", ""),
                "key_session": bool(w.get("key_session", False)),
                "event_phase": w.get("event_phase"),
                "source": "template" if used_template else "coaching_system",
                "needs_coach_review": bool(used_template),
                "variants": _merge_variants(w, prev),
                "approved": prev.get("approved", False) if prev else False,
                "completed": False,
                "coach_notes": prev.get("coach_notes", "") if prev else "",
                "coach_locked": False,
                "created_at": prev.get("created_at", now_iso()) if prev else now_iso(),
                "updated_at": now_iso(),
            }
            try:
                await db.workouts.delete_many({"user_id": client_id, "date": d})
                await db.workouts.insert_one(doc)
            except Exception as e:
                logger.warning("coach-confirm workout upsert failed date=%s: %s", d, e)

        persisted_count = await db.workouts.count_documents(
            {"user_id": client_id, "roster_id": rid}
        )

        if persisted_count == 0:
            await _set_job(
                job_id, status="needs_review", stage="generating", progress=95,
                error="Roster confirmed but the training plan needs review.",
                message="Roster saved — plan needs review",
                workouts_generated=0,
            )
            try:
                await _open_coach_task_for_stuck_generation(client, roster, job_id, reason="coach-confirm produced 0 workouts")
            except Exception:
                pass
            return

        await _set_job(job_id, stage="coach", progress=98, message="Preparing coach review...")
        try:
            await _notify_coaches_of_new_roster(client, roster, job_id)
        except Exception:
            pass
        if used_template:
            try:
                await _open_coach_task_for_stuck_generation(client, roster, job_id, reason="coach-confirm used template fallback")
            except Exception:
                pass

        await _set_job(
            job_id,
            status="complete", stage="complete", progress=100,
            message="Plan ready", completed_at=now_iso(),
            workouts_generated=len(workouts), used_template=used_template,
        )

    _asyncio.create_task(_worker())
    return {
        "job_id": job_id,
        "status": "processing",
        "roster_id": rid,
        "poll": f"/roster/jobs/{job_id}",
    }


logger.info("feature_coach_roster_upload: registered coach-side roster upload endpoints")
