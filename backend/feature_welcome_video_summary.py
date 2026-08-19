"""
Iter186 · Welcome-video summary + coach-side sent-lookup.

Two responsibilities in one small module because they share the
`db.weekly_videos` collection and the `video_kind == "welcome"` filter.

  1. ``generate_welcome_summary(script) -> list[str]``
     Calls Claude Sonnet 4.5 (via emergentintegrations) to distil the
     coach's full teleprompter script into **3-5 short bullet points**
     that the client will see under "WHAT LOUIS WANTED TO SAY" instead
     of the raw transcript. Kept out of the request/response path — the
     caller fires it as a background task from ``_spawn_bg`` so upload
     latency isn't affected.

  2. ``GET /api/coach/videos/welcome/{client_id}``
     Returns the most-recent welcome video (with ``sent_at`` + status)
     that this coach has sent to a particular client. Used by the
     workspace header to swap the "WELCOME VIDEO" button pill into a
     "SENT · dd Mon" delivered pill when a welcome video already exists.

Neither endpoint changes existing data — summaries are written back to
``weekly_videos.script_summary`` via a targeted ``update_one``. All
writes are idempotent.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.getenv("EMERGENT_LLM_KEY") or os.getenv("EMERGENT_LLM_UNIVERSAL_KEY") or ""

_SUMMARY_SYSTEM_PROMPT_WELCOME = """You are helping a fitness coach's mobile app render a friendly
summary of the coach's welcome video for a new client. You will receive the
full script the coach recorded (spoken monologue, first-person voice).

Return ONLY a JSON object with a single key "bullets" whose value is an
array of 3–5 SHORT strings. Each bullet MUST:
- Be a first-person paraphrase from the coach's perspective ("I'll…",
  "we're going to…", "you can expect…") — NOT a third-person description.
- Be 60 characters max.
- Capture one distinct idea (a promise, a next step, an emphasis, a
  reassurance). No fluff, no repeated ideas.
- Feel warm and human. No jargon, no "AI-generated" phrasing.

Return NOTHING outside the JSON. No preamble, no code fences.
Example output shape:
{"bullets": ["I've got your back on flying weeks", "We'll train around your roster",
             "You can message me anytime", "Your first plan drops after your check-in"]}
"""

_SUMMARY_SYSTEM_PROMPT_WEEKLY = """You are helping a fitness coach's mobile app render a summary of
the coach's WEEKLY REVIEW video for an existing client. You will receive
the full script the coach recorded (spoken monologue, first-person voice,
reflecting on the past week and priming the next).

Return ONLY a JSON object with a single key "bullets" whose value is an
array of 3–5 SHORT strings. Each bullet MUST:
- Be a first-person paraphrase from the coach's perspective ("great job
  on…", "this week we're focusing on…", "let's push harder on…") — NOT a
  third-person description.
- Be 60 characters max.
- Capture one distinct point (a callout, a next step, an intensity note,
  a form cue, a check-in question). No fluff, no repeated ideas.
- Feel warm, direct, human. No jargon, no "AI-generated" phrasing.

Return NOTHING outside the JSON. No preamble, no code fences.
Example output shape:
{"bullets": ["Strong deadlift session — new PR ready", "Cardio bumps to 4x this week",
             "Watch your knee on split squats", "How's sleep holding up?"]}
"""


# Backward-compat alias (some external code may reference this name).
_SUMMARY_SYSTEM_PROMPT = _SUMMARY_SYSTEM_PROMPT_WELCOME


def _fallback_bullets(script: str) -> list[str]:
    """Last-resort splitter when the LLM is unreachable — turns the
    script into 3 rough bullets by sentence boundaries. Deterministic
    and safe; the client sees SOMETHING useful rather than the raw
    script."""
    if not script or not script.strip():
        return []
    # Split on sentence terminators; keep the first 3 non-trivial ones.
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script.strip()) if s.strip()]
    picks = parts[:3]
    # Clip each to 80 chars (looser than the LLM 60, since we don't get
    # to rewrite — just gives coach some breathing room).
    return [p[:80] + ("…" if len(p) > 80 else "") for p in picks]


async def generate_welcome_summary(script: str, video_kind: str = "welcome") -> list[str]:
    """Best-effort LLM summary for a coach video. Falls back to sentence
    splitting on any error so the client never sees an empty state.

    Iter186+ · `video_kind` picks the right system prompt:
      - "welcome" → warm-intro voice (I'll, we're going to, you can expect)
      - anything else → weekly-review voice (great job on, this week, watch)
    """
    script = (script or "").strip()
    if not script:
        return []
    if not EMERGENT_LLM_KEY:
        logger.warning("EMERGENT_LLM_KEY missing — falling back to sentence split.")
        return _fallback_bullets(script)

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception:
        logger.exception("emergentintegrations import failed — using fallback.")
        return _fallback_bullets(script)

    system_prompt = (
        _SUMMARY_SYSTEM_PROMPT_WELCOME
        if (video_kind or "").lower() == "welcome"
        else _SUMMARY_SYSTEM_PROMPT_WEEKLY
    )

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"video-summary-{abs(hash(script)) % 10_000_000}",
            system_message=system_prompt,
        )
        chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
        raw = await chat.send_message(UserMessage(text=script))
        if not isinstance(raw, str):
            raw = str(raw)
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return _fallback_bullets(script)
        parsed = json.loads(m.group(0))
        bullets = parsed.get("bullets") or []
        out = [str(b).strip() for b in bullets if str(b).strip()]
        if len(out) < 3:
            return _fallback_bullets(script)
        return out[:5]
    except Exception:
        logger.exception("video-summary LLM call failed — fallback.")
        return _fallback_bullets(script)


async def stamp_welcome_summary(db, video_id: str, script: str) -> None:
    """Background helper — computes the summary and writes it back to
    ``weekly_videos.script_summary``. Idempotent: skips if already set.
    Safe to call from ``_spawn_bg`` — never raises to the caller.

    Iter186+ · Extended to ALL videos (welcome + weekly). The video_kind
    field on the doc drives the LLM voice; if unset we default to
    "weekly" since that's the majority path.
    """
    try:
        doc = await db.weekly_videos.find_one(
            {"id": video_id},
            {"_id": 0, "script_summary": 1, "video_kind": 1, "script": 1},
        )
        if not doc:
            return
        if doc.get("script_summary"):
            return
        kind = (doc.get("video_kind") or "weekly").lower()
        bullets = await generate_welcome_summary(script or doc.get("script") or "", video_kind=kind)
        if not bullets:
            return
        await db.weekly_videos.update_one(
            {"id": video_id},
            {"$set": {"script_summary": bullets}},
        )
    except Exception:
        logger.exception("stamp_welcome_summary failed for %s", video_id)


async def backfill_all_video_summaries(db, batch_size: int = 25) -> dict:
    """Iter186+ · One-shot backfill for existing videos that have a
    ``script`` but no ``script_summary``. Runs sequentially with a
    short delay to respect the Universal Key rate ceiling.

    Returns ``{"scanned": N, "stamped": M, "skipped": K}`` — safe to
    call repeatedly, idempotent per row.
    """
    import asyncio
    scanned = stamped = skipped = 0
    try:
        cur = db.weekly_videos.find(
            {
                "script": {"$exists": True, "$nin": [None, ""]},
                "$or": [
                    {"script_summary": {"$exists": False}},
                    {"script_summary": None},
                    {"script_summary": []},
                ],
            },
            {"_id": 0, "id": 1, "video_kind": 1, "script": 1},
        )
        async for row in cur:
            scanned += 1
            if scanned > 500:   # hard cap so a runaway can't blow the LLM budget
                break
            script = (row.get("script") or "").strip()
            if not script or len(script) < 30:
                skipped += 1
                continue
            kind = (row.get("video_kind") or "weekly").lower()
            bullets = await generate_welcome_summary(script, video_kind=kind)
            if not bullets:
                skipped += 1
                continue
            await db.weekly_videos.update_one(
                {"id": row["id"]}, {"$set": {"script_summary": bullets}},
            )
            stamped += 1
            await asyncio.sleep(0.4)  # gentle pacing
    except Exception:
        logger.exception("backfill_all_video_summaries crashed at scanned=%d", scanned)
    return {"scanned": scanned, "stamped": stamped, "skipped": skipped}


# ---------------------------------------------------------------------------
# API — factory pattern.
# ---------------------------------------------------------------------------
def make_router(db, require_role) -> APIRouter:
    r = APIRouter()

    @r.get("/coach/videos/welcome/{client_id}")
    async def coach_welcome_video_for_client(
        client_id: str,
        coach: dict = Depends(require_role("coach")),
    ):
        """Return the most-recent welcome video for a given client.

        Ordering: prefer status=='sent' rows, then most recent
        ``sent_at`` / ``created_at`` — so an old sent video wins over a
        newer draft (the coach ADMIN cares about "was one delivered?").
        """
        # Prefer a SENT one first.
        sent = await db.weekly_videos.find_one(
            {"user_id": client_id, "video_kind": "welcome", "status": "sent"},
            {"_id": 0},
            sort=[("sent_at", -1), ("created_at", -1)],
        )
        if sent:
            return {"video": sent, "status": "sent"}
        # Otherwise a recent draft/recorded row.
        draft = await db.weekly_videos.find_one(
            {"user_id": client_id, "video_kind": "welcome"},
            {"_id": 0},
            sort=[("created_at", -1)],
        )
        if draft:
            return {"video": draft, "status": draft.get("status") or "draft"}
        return {"video": None, "status": "none"}

    @r.post("/coach/videos/{video_id}/regenerate-summary")
    async def coach_regenerate_summary(
        video_id: str,
        coach: dict = Depends(require_role("coach")),
    ):
        """Coach-triggered summary regenerate (e.g. if the auto-summary
        misses something). Clears the existing summary + reruns."""
        v = await db.weekly_videos.find_one({"id": video_id}, {"_id": 0})
        if not v:
            raise HTTPException(404, "video not found")
        if (v.get("video_kind") or "").lower() != "welcome":
            raise HTTPException(400, "only welcome videos have summaries")
        # Blank first so `stamp_welcome_summary` idempotency skip won't
        # short-circuit us.
        await db.weekly_videos.update_one(
            {"id": video_id}, {"$unset": {"script_summary": ""}},
        )
        bullets = await generate_welcome_summary(v.get("script") or "")
        await db.weekly_videos.update_one(
            {"id": video_id}, {"$set": {"script_summary": bullets}},
        )
        return {"ok": True, "bullets": bullets}

    @r.post("/coach/videos/backfill-summaries")
    async def coach_backfill_video_summaries(
        coach: dict = Depends(require_role("coach")),
    ):
        """Iter186+ · One-shot backfill for existing videos that have a
        ``script`` but no ``script_summary``. Runs sequentially with a
        short delay to respect the Universal Key rate ceiling. Coach-only.
        Safe to re-run — idempotent per row.
        """
        return await backfill_all_video_summaries(db)

    @r.post("/coach/videos/{video_id}/convert-to-welcome")
    async def coach_convert_to_welcome(
        video_id: str,
        coach: dict = Depends(require_role("coach")),
    ):
        """Iter186 · Repair endpoint — flips a video that was saved as
        a weekly-review into a welcome video. Triggers summary
        generation immediately so bullets appear on the next fetch.

        Common failure mode this heals: coach forgot to tick the
        "MARK AS WELCOME VIDEO" toggle before hitting SEND, so the
        video landed on the client's weekly-review card instead of
        the welcome banner + no bullets + no "Message Your Coach"
        button. This endpoint retro-fits the correct state without
        the coach having to re-record.
        """
        v = await db.weekly_videos.find_one({"id": video_id}, {"_id": 0})
        if not v:
            raise HTTPException(404, "video not found")
        await db.weekly_videos.update_one(
            {"id": video_id},
            {"$set": {"video_kind": "welcome"},
             "$unset": {"check_in_id": ""}},
        )
        # Kick off summary generation inline so the bullets are ready
        # by the time the client re-opens the video.
        try:
            bullets = await generate_welcome_summary(v.get("script") or "")
            if bullets:
                await db.weekly_videos.update_one(
                    {"id": video_id}, {"$set": {"script_summary": bullets}},
                )
        except Exception:
            logger.exception("convert-to-welcome summary failed for %s", video_id)
        fresh = await db.weekly_videos.find_one({"id": video_id}, {"_id": 0})
        return {"ok": True, "video": fresh}

    return r
