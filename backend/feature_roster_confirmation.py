"""
feature_roster_confirmation — Phase 2 of the CrewFit Programme Generation Upgrade.

Introduces a deliberate PARSE → CONFIRM → BUILD flow:

* `POST /api/roster/upload-parse` — parses a roster via Gemini and stores it as
  a PENDING roster (is_active=false, status='pending_confirmation'). Does NOT
  generate workouts and does NOT deactivate the current active roster.
* `GET  /api/roster/pending`         — returns the newest pending roster for the client.
* `GET  /api/roster/pending/{id}`    — one pending roster.
* `PATCH /api/roster/pending/{id}`   — accepts { days: [...] } to update the roster
  before confirmation (adds `_confirmed_by_user=true` on any day whose day_type
  changed away from "Unknown/Needs Confirmation").
* `POST /api/roster/pending/{id}/confirm` — validates that low-confidence days
  have been reviewed, activates the roster, and kicks off the same background
  generation worker (with template fallback) used by upload-and-generate.
* `DELETE /api/roster/pending/{id}`  — discard the draft.

Confirmation rule: any day whose parse `confidence < LOW_CONFIDENCE_THRESHOLD`
MUST have `_confirmed_by_user=true` (set by the client explicitly, or implicitly
by editing the day_type) before the "Confirm & build" endpoint accepts the
request. This is the amber-required-review UX from the master build prompt.
"""

from __future__ import annotations

import asyncio as _asyncio
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api,
    db,
    current_user,
    new_id,
    now_iso,
    logger,
    write_temp,
    call_gemini_file,
    parse_json_from_text,
    score_load,
    _detect_overlap,
    _generate_month,
    _generation_heartbeat,
    _set_job,
    _open_coach_task_for_stuck_generation,
    _notify_coaches_of_new_roster,
    _emit_reassessment_prompt,
    _merge_variants,
    ROSTER_SYSTEM,
    RosterConfirmBody,  # {days: list[dict]}
    RosterUploadGenerateBody,  # {file_base64, mime_type, filename}
)


LOW_CONFIDENCE_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _needs_review(day: dict) -> bool:
    """True when a parsed day is low-confidence AND has not been reviewed by
    the client. Confirming a day (either by explicit toggle or by editing its
    day_type away from "Unknown/Needs Confirmation") sets
    `_confirmed_by_user=true`, which flips this to False."""
    if day.get("_confirmed_by_user"):
        return False
    try:
        conf = float(day.get("confidence") or 0.5)
    except Exception:
        conf = 0.5
    if conf < LOW_CONFIDENCE_THRESHOLD:
        return True
    if (day.get("day_type") or "").lower().startswith("unknown"):
        return True
    return False


def _apply_day_defaults(days: list[dict]) -> list[dict]:
    """Normalise a raw days list post-parse or post-edit."""
    days = list(days or [])
    days.sort(key=lambda d: d.get("date") or "")
    for d in days:
        d.setdefault("flights", [])
        d.setdefault("day_type", "Unknown/Needs Confirmation")
        d.setdefault("confidence", 0.5)
        d["load"] = score_load(d)
        dtype_lower = (d.get("day_type") or "").lower()
        d["home_or_away"] = d.get("home_or_away") or (
            "away" if "layover" in dtype_lower
            else "home" if "home" in dtype_lower
            else "unknown"
        )
    return days


async def _persist_pending_roster(user_id: str, days: list[dict], source_filename: str, raw: str, job_id: str) -> dict:
    days = _apply_day_defaults(days)
    first = days[0]["date"] if days else None
    last = days[-1]["date"] if days else None
    doc = {
        "id": new_id(),
        "user_id": user_id,
        "created_at": now_iso(),
        "week_start": first,
        "start_date": first,
        "end_date": last,
        "days": days,
        "confirmed": False,
        "confirmed_at": None,
        "is_active": False,                    # NOT active until confirmed
        "status": "pending_confirmation",
        "raw_response": raw[:6000] if raw else "",
        "source_filename": source_filename,
        "upload_job_id": job_id,
        "day_count": len(days),
        "confidence_avg": round(sum(float(d.get("confidence") or 0.5) for d in days) / max(1, len(days)), 2),
        "review_flags": {
            "low_confidence_count": sum(1 for d in days if _needs_review(d)),
        },
    }
    await db.rosters.insert_one(doc)
    return doc


# ---------------------------------------------------------------------------
# Upload → Parse (no generation)
# ---------------------------------------------------------------------------

@api.post("/roster/upload-parse")
async def roster_upload_parse(body: RosterUploadGenerateBody, user: dict = Depends(current_user)):
    """Parse a roster file and store it as a PENDING roster. No workouts are
    generated. The client must POST /api/roster/pending/{id}/confirm to
    trigger the plan build."""
    job_id = new_id()
    await db.roster_jobs.insert_one({
        "id": job_id, "user_id": user["id"],
        "status": "queued", "stage": "uploading",
        "message": "Uploading your roster...",
        "progress": 1, "created_at": now_iso(),
        "filename": body.filename or "roster",
        "flow": "parse_only",
        "pending_roster_id": None, "roster_id": None,
        "error": None, "overlap": None, "retry_count": 0,
    })

    async def _worker():
        path: Optional[str] = None
        try:
            await _set_job(job_id, status="processing", stage="uploading", progress=5, message="Uploading your roster...")
            path = await write_temp(body.file_base64, body.mime_type)
            await _set_job(job_id, stage="reading", progress=20, message="Reading your duty pattern...")
            raw = ""
            try:
                raw = await call_gemini_file(ROSTER_SYSTEM, "Extract the complete roster shown. Return only JSON.", path, body.mime_type)
            except Exception as e:
                logger.warning("Gemini roster call failed: %s", e)
            await _set_job(job_id, stage="extracting", progress=45, message="Extracting duties...")
            parsed: Any = {}
            try:
                parsed = parse_json_from_text(raw) if raw else {}
            except Exception as e:
                logger.warning("roster parse failed: %s", e)
            days = parsed.get("days", []) if isinstance(parsed, dict) else parsed
            if not days:
                await _set_job(
                    job_id, status="failed", stage="extracting", progress=45,
                    error="We couldn't read this roster clearly. Please upload a clearer file or add days manually on the next screen.",
                    message="Roster could not be read",
                )
                return
            await _set_job(job_id, stage="detecting", progress=65, message="Detecting layovers and turnarounds...")
            days = _apply_day_defaults(days)
            overlap = await _detect_overlap(user["id"], days)
            pending = await _persist_pending_roster(user["id"], days, body.filename or "roster", raw, job_id)
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
            logger.exception("roster parse job %s failed", job_id)
            await _set_job(job_id, status="failed", error=str(e)[:400], message="Roster processing failed")
        finally:
            if path:
                try:
                    import os
                    os.unlink(path)
                except Exception:
                    pass

    _asyncio.create_task(_worker())
    return {"job_id": job_id, "status": "queued", "poll": f"/roster/jobs/{job_id}"}


# ---------------------------------------------------------------------------
# Pending roster CRUD
# ---------------------------------------------------------------------------

@api.get("/roster/pending")
async def roster_pending_latest(user: dict = Depends(current_user)):
    """Return the most recent pending roster for the user (if any)."""
    r = await db.rosters.find_one(
        {"user_id": user["id"], "status": "pending_confirmation"},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not r:
        return {}
    # Attach the per-day needs_review flag so the client can highlight amber.
    for d in r.get("days") or []:
        d["_needs_review"] = _needs_review(d)
    return r


@api.get("/roster/pending/{rid}")
async def roster_pending_get(rid: str, user: dict = Depends(current_user)):
    r = await db.rosters.find_one(
        {"id": rid, "user_id": user["id"], "status": "pending_confirmation"},
        {"_id": 0},
    )
    if not r:
        raise HTTPException(404, "Pending roster not found")
    for d in r.get("days") or []:
        d["_needs_review"] = _needs_review(d)
    return r


@api.patch("/roster/pending/{rid}")
async def roster_pending_patch(rid: str, body: RosterConfirmBody, user: dict = Depends(current_user)):
    """Save edits to a pending roster's days. Any day whose day_type has been
    changed away from 'Unknown/Needs Confirmation' auto-flags as reviewed.
    The client may also send `_confirmed_by_user=true` explicitly."""
    r = await db.rosters.find_one({"id": rid, "user_id": user["id"], "status": "pending_confirmation"}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Pending roster not found")

    incoming = _apply_day_defaults(body.days)
    prior_by_date = {d.get("date"): d for d in (r.get("days") or [])}
    for d in incoming:
        prior = prior_by_date.get(d.get("date")) or {}
        prior_type = (prior.get("day_type") or "").lower()
        new_type = (d.get("day_type") or "").lower()
        # Implicit confirmation: any edit that moves a day AWAY from the
        # 'Unknown/Needs Confirmation' default counts as reviewed.
        if d.get("_confirmed_by_user") is not True:
            if new_type and not new_type.startswith("unknown") and new_type != prior_type:
                d["_confirmed_by_user"] = True
            elif prior.get("_confirmed_by_user"):
                d["_confirmed_by_user"] = True

    review_flags = {"low_confidence_count": sum(1 for d in incoming if _needs_review(d))}
    updates = {
        "days": incoming,
        "start_date": incoming[0]["date"] if incoming else r.get("start_date"),
        "end_date": incoming[-1]["date"] if incoming else r.get("end_date"),
        "day_count": len(incoming),
        "confidence_avg": round(sum(float(d.get("confidence") or 0.5) for d in incoming) / max(1, len(incoming)), 2),
        "review_flags": review_flags,
        "updated_at": now_iso(),
    }
    await db.rosters.update_one({"id": rid}, {"$set": updates})
    r2 = await db.rosters.find_one({"id": rid}, {"_id": 0})
    for d in (r2 or {}).get("days") or []:
        d["_needs_review"] = _needs_review(d)
    return r2


class ConfirmDayBody(BaseModel):
    date: str


@api.post("/roster/pending/{rid}/confirm-day")
async def roster_pending_confirm_day(rid: str, body: ConfirmDayBody, user: dict = Depends(current_user)):
    """Mark a single day as reviewed (used for the amber 'Confirm' button on
    low-confidence days that the client wants to accept as-is)."""
    r = await db.rosters.find_one({"id": rid, "user_id": user["id"], "status": "pending_confirmation"}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Pending roster not found")
    days = list(r.get("days") or [])
    touched = False
    for d in days:
        if d.get("date") == body.date:
            d["_confirmed_by_user"] = True
            touched = True
            break
    if not touched:
        raise HTTPException(404, "Day not found in pending roster")
    review_flags = {"low_confidence_count": sum(1 for d in days if _needs_review(d))}
    await db.rosters.update_one({"id": rid}, {"$set": {"days": days, "review_flags": review_flags, "updated_at": now_iso()}})
    for d in days:
        d["_needs_review"] = _needs_review(d)
    return {"days": days, "review_flags": review_flags}


@api.delete("/roster/pending/{rid}")
async def roster_pending_delete(rid: str, user: dict = Depends(current_user)):
    res = await db.rosters.delete_one({"id": rid, "user_id": user["id"], "status": "pending_confirmation"})
    return {"deleted": res.deleted_count > 0}


# ---------------------------------------------------------------------------
# Confirm & build plan
# ---------------------------------------------------------------------------

@api.post("/roster/pending/{rid}/confirm")
async def roster_pending_confirm(rid: str, user: dict = Depends(current_user)):
    """Activate the pending roster and kick off workout generation.

    Enforces: no low-confidence day may remain unreviewed. Returns a job_id
    the client polls via GET /roster/jobs/{job_id}.
    """
    pending = await db.rosters.find_one({"id": rid, "user_id": user["id"], "status": "pending_confirmation"}, {"_id": 0})
    if not pending:
        raise HTTPException(404, "Pending roster not found")

    days = pending.get("days") or []
    unreviewed = [d for d in days if _needs_review(d)]
    if unreviewed:
        raise HTTPException(
            400,
            f"{len(unreviewed)} day(s) still need review before we can build your plan. "
            "Tap the amber days to confirm or edit their duty type.",
        )

    # Activate: mark all other rosters inactive, promote this one.
    await db.rosters.update_many({"user_id": user["id"], "is_active": True}, {"$set": {"is_active": False}})
    now = now_iso()
    await db.rosters.update_one(
        {"id": rid},
        {"$set": {
            "is_active": True,
            "status": "confirmed",
            "confirmed": True,
            "confirmed_at": now,
            "updated_at": now,
        }},
    )
    roster = await db.rosters.find_one({"id": rid}, {"_id": 0})

    # Kick off workout generation using a fresh job doc so the same
    # progress-polling UI works unchanged.
    job_id = new_id()
    await db.roster_jobs.insert_one({
        "id": job_id, "user_id": user["id"],
        "status": "processing", "stage": "generating",
        "message": "Generating your personalised plan...",
        "progress": 80, "created_at": now,
        "filename": pending.get("source_filename") or "roster",
        "flow": "confirm_build",
        "roster_id": rid, "pending_roster_id": rid,
        "error": None, "overlap": None, "retry_count": 0,
    })

    async def _worker():
        heartbeat_task = _asyncio.create_task(_generation_heartbeat(job_id))
        # Programme quality context — reused across generation, validation, persistence.
        programme_ctx = None
        try:
            from feature_programme_quality import programme_context_for_llm
            programme_ctx = await programme_context_for_llm(user, roster)
        except Exception:
            logger.exception("confirm-build: programme_context_for_llm failed")
        try:
            workouts = await _asyncio.wait_for(_generate_month(user, roster, programme_ctx=programme_ctx), timeout=180.0)
        except _asyncio.TimeoutError:
            logger.warning("confirm-build: plan generation TIMEOUT job=%s — template fallback", job_id)
            workouts = []
        except Exception as e:
            logger.exception("confirm-build: plan generation raised job=%s: %s — template fallback", job_id, e)
            workouts = []

        used_template = False
        try:
            from feature_workout_fallback import build_template_plan, is_empty_or_llm_failure
            from feature_hotel_system import load_hotel_lookup_for_roster
            if is_empty_or_llm_failure(workouts):
                hotel_lookup = await load_hotel_lookup_for_roster(db, roster)
                workouts = build_template_plan(user, roster, hotel_lookup=hotel_lookup)
                used_template = bool(workouts)
                if workouts:
                    try:
                        from feature_v2_resolver import apply_resolver_to_workouts
                        await apply_resolver_to_workouts(workouts, user=user, roster=roster)
                    except Exception:
                        logger.exception("confirm-build: v2_resolver on fallback failed")
                if used_template:
                    logger.warning("confirm-build job %s used TEMPLATE fallback", job_id)
        except Exception:
            logger.exception("confirm-build: template fallback failed")
        finally:
            heartbeat_task.cancel()

        # Persist workouts (same upsert pattern as roster_upload_and_generate main worker).
        existing = {w["date"]: w for w in await db.workouts.find({"user_id": user["id"], "roster_id": rid}, {"_id": 0}).to_list(500)}
        for w in workouts:
            d = w.get("date")
            if not d:
                continue
            prev = existing.get(d)
            if prev and (prev.get("coach_locked") or prev.get("completed")):
                continue
            doc = {
                "id": prev["id"] if prev else new_id(),
                "user_id": user["id"], "roster_id": rid, "date": d,
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
                await db.workouts.delete_many({"user_id": user["id"], "date": d})
                await db.workouts.insert_one(doc)
            except Exception as e:
                logger.warning("confirm-build workout upsert failed date=%s: %s", d, e)
                continue

        persisted_count = await db.workouts.count_documents({"user_id": user["id"], "roster_id": rid})

        # Programme quality gate: validate + persist.
        try:
            if programme_ctx is not None:
                from feature_programme_quality import validate_programme, persist_programme_record
                persisted_workouts = await db.workouts.find({"user_id": user["id"], "roster_id": rid}, {"_id": 0}).sort("date", 1).to_list(500)
                validation = validate_programme(user, roster, persisted_workouts, programme_ctx)
                await persist_programme_record(user, roster, persisted_workouts, programme_ctx, validation)
                if not validation.get("ok"):
                    await db.workouts.update_many(
                        {"user_id": user["id"], "roster_id": rid, "completed": {"$ne": True}, "coach_locked": {"$ne": True}},
                        {"$set": {"needs_coach_review": True, "updated_at": now_iso()}},
                    )
        except Exception:
            logger.exception("confirm-build: programme quality gate failed — non-fatal")

        if persisted_count == 0:
            await _set_job(
                job_id, status="needs_review", stage="generating", progress=95,
                error="Your roster is confirmed but the training plan needs review. Louis has been notified.",
                message="Roster saved — plan needs review",
                workouts_generated=0,
            )
            try:
                await _open_coach_task_for_stuck_generation(user, roster, job_id, reason="confirm-build produced 0 workouts")
            except Exception:
                pass
            return

        await _set_job(job_id, stage="coach", progress=98, message="Preparing coach review...")
        try:
            await _notify_coaches_of_new_roster(user, roster, job_id)
        except Exception:
            pass
        if used_template:
            try:
                await _open_coach_task_for_stuck_generation(user, roster, job_id, reason="confirm-build used template fallback")
            except Exception:
                pass
        try:
            await _emit_reassessment_prompt(
                user["id"], "roster_confirmed",
                "Roster confirmed — take 90s to update your availability so CrewFit adapts perfectly.",
                {"roster_id": rid, "days": len(roster.get("days") or [])},
            )
        except Exception:
            pass
        complete_message = (
            "Starter plan ready — Louis will refine your sessions soon."
            if used_template else "Your new plan is ready"
        )
        await _set_job(
            job_id,
            status="complete", stage="complete", progress=100,
            message=complete_message, completed_at=now_iso(),
            workouts_generated=len(workouts), used_template=used_template,
        )

    _asyncio.create_task(_worker())
    return {"job_id": job_id, "status": "processing", "roster_id": rid}
