"""
feature_auto_media_gen — Auto-generate exercise media on creation.

Coach requested: whenever a new exercise is added (from manual workouts,
Atlas alternatives, hotel conversions, traffic-light variants, or a
direct coach create) the app should automatically queue the standard
Nano-Banana image generations (primary + start + end) AND the Claude
coaching-points draft, so the coach never has to click Generate on every
new exercise. The coach STILL has to Approve — images land as
`approved_image_status = "Needs Review"` exactly like the manual path.

Fully reuses:
  * feature_exercise_content._build_ex_prompt / _run_image_job
    (Nano Banana image pipeline).
  * feature_exercise_content.ex_generate_content style prompt
    (Claude coaching-points draft).
  * db.exercise_content_images / db.exercises_v2 fields.

Design:
  * Idempotent — if a slot already has an image, skip it. If
    coaching_points already exist, skip.
  * Non-blocking — every generation runs as an asyncio task.
  * Feature-flag: `AUTO_MEDIA_GEN` env var (default: on).
  * The coach still needs to approve — nothing is auto-published.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Optional

from server import db, logger, new_id, now_iso, EMERGENT_LLM_KEY


AUTO_MEDIA_GEN_ENABLED = str(os.environ.get("AUTO_MEDIA_GEN", "true")).lower() in ("1", "true", "yes", "on")

# Default slots to auto-generate. Coach can extend per-exercise via the
# existing `required_slots` field, but the three standard frames cover
# every workout-preview reader (primary hero + guided-flow start/end).
_AUTO_SLOTS = ("primary", "start", "end")

# System user marker for tasks kicked off automatically.
_AUTO_USER_ID = "system_auto_media_gen"


# ---------------------------------------------------------------------------
# CRITICAL — Fire-and-forget task tracking.
# ---------------------------------------------------------------------------
# Python's `asyncio.create_task` only keeps a WEAK reference to the returned
# Task object. Per the official asyncio docs: "Save a reference to the
# result of this function, to avoid a task disappearing mid-execution.
# The event loop only keeps weak references to tasks."
#
# In production, under load / worker recycling / GC pressure, this means
# fire-and-forget background tasks (LLM calls, image gen) can be silently
# garbage-collected mid-run, leaving DB writes never happening. That's
# exactly what happened during the 222-exercise Needs-Review backfill on
# https://flight-fit-plans.emergent.host — the endpoint returned "queued
# 222" but many tasks were GC'd before their Claude calls completed.
#
# Fix: keep every fire-and-forget task in this module-level set, and add
# a done-callback that removes them once they finish (so the set doesn't
# grow forever). This is the exact idiom recommended by the CPython docs.
_BG_TASKS: set[asyncio.Task] = set()


def _spawn_bg(coro) -> asyncio.Task:
    """Fire-and-forget wrapper that STRONGLY references the task so it
    can't be GC'd mid-execution. Always use this instead of a bare
    `asyncio.create_task(...)` inside this module."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


# ---------------------------------------------------------------------------
# Per-kind toggles — coach flips at runtime without a redeploy.
# ---------------------------------------------------------------------------

# All kinds we know about. Each maps to a friendly label the coach sees.
# Images are split per-slot so the coach can enable Primary only (default)
# and add Start/End when they specifically need the two-frame flow.
_KIND_LABELS: dict[str, str] = {
    "image_primary":   "Images · Primary frame",
    "image_start":     "Images · Start frame",
    "image_end":       "Images · End frame",
    "coaching_points": "Coaching points (Louis-voice)",
    "common_mistakes": "Common mistakes",
    "alternatives":    "Alternative exercises (+ library drafts)",
    "instructions":    "Client-facing instructions",
}

# Defaults — MINIMAL by default to conserve credits. Only the primary
# image and coaching points fire on new exercises; the coach can flip
# additional kinds on from the Generation Control panel when they need
# fuller coverage. Changing these defaults DOES NOT overwrite existing
# coach preferences stored in db.settings — they only apply to fresh
# environments that never opened the panel.
_KIND_DEFAULTS: dict[str, bool] = {
    "image_primary":   True,
    "image_start":     False,
    "image_end":       False,
    "coaching_points": True,
    "common_mistakes": True,
    "alternatives":    True,
    "instructions":    True,
}

# Env-var overrides (checked last as a hard kill-switch — flipping any of
# these to "false" beats the DB toggle so cost blow-outs can be stopped
# via an env change even if the DB is unreachable).
def _env_off(name: str) -> bool:
    return str(os.environ.get(name, "true")).lower() not in ("1", "true", "yes", "on")

_KIND_ENV_OFF = {
    # Legacy `AUTO_MEDIA_GEN_IMAGES` still kills all three image slots
    # so an existing env var keeps working.
    "image_primary":   _env_off("AUTO_MEDIA_GEN_IMAGE_PRIMARY") or _env_off("AUTO_MEDIA_GEN_IMAGES"),
    "image_start":     _env_off("AUTO_MEDIA_GEN_IMAGE_START")   or _env_off("AUTO_MEDIA_GEN_IMAGES"),
    "image_end":       _env_off("AUTO_MEDIA_GEN_IMAGE_END")     or _env_off("AUTO_MEDIA_GEN_IMAGES"),
    "coaching_points": _env_off("AUTO_MEDIA_GEN_COACHING"),
    "common_mistakes": _env_off("AUTO_MEDIA_GEN_MISTAKES"),
    "alternatives":    _env_off("AUTO_MEDIA_GEN_ALTERNATIVES"),
    "instructions":    _env_off("AUTO_MEDIA_GEN_INSTRUCTIONS"),
}

_SETTINGS_DOC_ID = "auto_media_gen"


async def _load_kind_toggles() -> dict:
    """Return {kind: bool} — merge of DB settings (source of truth) and
    env-var kill switches (env-false ALWAYS wins). Falls back to the
    _KIND_DEFAULTS above when the DB doc is missing.

    Migration note: if the DB doc still carries the legacy `images`
    key from an older release we honour it — its value seeds the three
    new per-slot toggles unless the coach has already saved per-slot
    values."""
    try:
        doc = await db.settings.find_one({"_id": _SETTINGS_DOC_ID}) or {}
    except Exception as e:
        logger.warning(f"auto_media_gen: settings load failed ({e}), using defaults")
        doc = {}

    legacy_images = doc.get("images")
    toggles: dict[str, bool] = {}
    for k, default in _KIND_DEFAULTS.items():
        if k in doc and isinstance(doc[k], bool):
            val = doc[k]
        elif isinstance(legacy_images, bool) and k in ("image_primary", "image_start", "image_end"):
            # Seed all three from the legacy single toggle. Coach can
            # refine individually once they open the panel.
            val = legacy_images if k == "image_primary" else False
        else:
            val = default
        # Env kill-switch wins
        if _KIND_ENV_OFF.get(k):
            val = False
        toggles[k] = val
    return toggles


async def _kind_enabled(kind: str) -> bool:
    return (await _load_kind_toggles()).get(kind, True)


# ---------------------------------------------------------------------------
# Budget safeguard — global pause when the LLM key runs out of credit.
# ---------------------------------------------------------------------------
#
# When ANY auto-generation task detects a "Budget has been exceeded" error
# (or one of its close cousins) we set a single `budget_paused_*` marker
# in db.settings. Every subsequent auto-gen call short-circuits on that
# marker so we don't burn through further failed API calls at ~1 credit each.
#
# The pause is coach-visible in the Generation Control panel and coach-
# clearable via POST /coach/auto-media-gen/budget/resume once credits are
# topped up. This is a global, cross-exercise flag — one blown budget stops
# ALL kinds until the coach explicitly resumes.

_BUDGET_MARKERS: tuple[str, ...] = (
    "budget has been exceeded",
    "budget exceeded",
    "insufficient credits",
    "quota exceeded",
    "credit limit",
    "402 payment required",
)


def _is_budget_error(err: object) -> bool:
    """Cheap substring check on the error string. We accept `Exception`,
    `HTTPException`, or any object whose `str()` includes a budget marker."""
    if err is None:
        return False
    text = ""
    try:
        # HTTPException stores structured detail — inspect both.
        detail = getattr(err, "detail", None)
        if detail is not None:
            text += " " + str(detail)
    except Exception:
        pass
    try:
        text += " " + str(err)
    except Exception:
        pass
    text = text.lower()
    return any(m in text for m in _BUDGET_MARKERS)


async def is_budget_paused() -> bool:
    """True if a budget-exceeded error has been recorded and NOT yet
    resumed by the coach. Cheap read; called at the top of every auto-gen
    task."""
    try:
        doc = await db.settings.find_one(
            {"_id": _SETTINGS_DOC_ID},
            {"_id": 0, "budget_paused_at": 1, "budget_resumed_at": 1},
        ) or {}
    except Exception:
        return False
    paused_at = doc.get("budget_paused_at")
    resumed_at = doc.get("budget_resumed_at")
    if not paused_at:
        return False
    # Resume must be strictly newer than the pause to clear it.
    if resumed_at and str(resumed_at) > str(paused_at):
        return False
    return True


async def _mark_budget_paused(reason: str, *, ex_id: Optional[str] = None,
                              kind: Optional[str] = None) -> None:
    """Record the pause once — noisy log level so it lands in supervisor
    output. Coach dashboards poll `is_budget_paused()` to render the banner.
    Also stamps the offending exercise so its media row can render a
    "GENERATION PAUSED" chip instead of a blank slot."""
    now = now_iso()
    reason = (reason or "")[:400]
    try:
        already = await is_budget_paused()
        await db.settings.update_one(
            {"_id": _SETTINGS_DOC_ID},
            {"$set": {
                "budget_paused_at": now,
                "budget_paused_reason": reason,
                "budget_paused_by_kind": kind,
                "budget_paused_by_exercise_id": ex_id,
                "updated_at": now,
            }},
            upsert=True,
        )
        if not already:
            logger.warning(
                "auto_media_gen: BUDGET PAUSED — ex=%s kind=%s reason=%s",
                ex_id, kind, reason,
            )
        # Also mark the offending exercise so per-row UI shows the pause.
        if ex_id:
            try:
                await db.exercises_v2.update_one(
                    {"id": ex_id},
                    {"$set": {
                        "auto_media_gen_paused": True,
                        "auto_media_gen_paused_reason": reason,
                        "auto_media_gen_paused_at": now,
                    }},
                )
            except Exception:
                logger.exception("auto_media_gen: failed to stamp exercise pause")
    except Exception:
        logger.exception("auto_media_gen: failed to record budget pause")


async def _clear_budget_pause(by: str) -> dict:
    """Coach explicitly resumes generation after topping up credits."""
    now = now_iso()
    await db.settings.update_one(
        {"_id": _SETTINGS_DOC_ID},
        {"$set": {"budget_resumed_at": now, "budget_resumed_by": by,
                  "updated_at": now}},
        upsert=True,
    )
    # Clear per-exercise pause flags so stale banners disappear next reload.
    try:
        await db.exercises_v2.update_many(
            {"auto_media_gen_paused": True},
            {"$set": {"auto_media_gen_paused": False,
                      "auto_media_gen_resumed_at": now}},
        )
    except Exception:
        logger.exception("auto_media_gen: failed to clear per-exercise pauses")
    logger.warning("auto_media_gen: BUDGET pause CLEARED by %s", by)
    return {"resumed_at": now, "resumed_by": by}



async def _safe_run_image_job(image_id: str, prompt: str, *,
                              ex_id: Optional[str] = None,
                              slot: Optional[str] = None) -> None:
    """Wrap the exercise-content image job with budget-aware error handling.

    If the underlying image generator raises a budget-exceeded error we
    stamp the global pause flag so nothing else fires, and mark the
    image row as ``status=paused_budget`` so the UI can render the badge
    (rather than a blank slot).
    """
    try:
        from feature_exercise_content import _run_image_job
    except Exception:
        logger.exception("auto_media_gen: _run_image_job unavailable")
        return

    # Second-line defence: skip if the budget is already paused before we
    # even queue an API call. Cheap DB read but avoids a wasted attempt.
    if await is_budget_paused():
        try:
            await db.exercise_content_images.update_one(
                {"id": image_id},
                {"$set": {"status": "paused_budget",
                          "error": "budget_paused",
                          "updated_at": now_iso()}},
            )
        except Exception:
            pass
        return

    try:
        await _run_image_job(image_id, prompt, use_louis_ref=True)
    except Exception as e:
        # _run_image_job already writes status=failed on its own; we only
        # need to trip the budget pause when the error smells budget-y.
        if _is_budget_error(e):
            await _mark_budget_paused(str(e), ex_id=ex_id, kind=f"image_{slot}")
        # Otherwise leave the row's failure state as-is.

    # _run_image_job doesn't raise on inner failures — it writes
    # status=failed with `error`. Inspect it here to trip the pause.
    try:
        row = await db.exercise_content_images.find_one(
            {"id": image_id}, {"_id": 0, "status": 1, "error": 1},
        )
        if row and row.get("status") == "failed" and _is_budget_error(row.get("error")):
            await _mark_budget_paused(
                str(row.get("error"))[:400], ex_id=ex_id, kind=f"image_{slot}",
            )
            # Retag the row as paused_budget so the UI can differentiate
            # "we hit a budget wall" from "the image generator crashed".
            try:
                await db.exercise_content_images.update_one(
                    {"id": image_id},
                    {"$set": {"status": "paused_budget",
                              "updated_at": now_iso()}},
                )
            except Exception:
                pass
    except Exception:
        logger.exception("auto_media_gen: post-image budget check failed")


async def _next_persona_for_new_exercise(force: Optional[str] = None) -> str:
    """Iter181 · Male↔female alternation counter for auto-media generation.

    Ensures the exercise library shows diverse demonstrators without the
    coach having to think about it. The counter lives in `db.settings`
    under the key ``auto_media_gen_persona_counter`` so alternation is
    global across every creation path (coach form, JSON imports, v2
    resolver, backfill).

    ``force`` — when a coach explicitly picks a persona for a specific
    creation (e.g. from the admin form) that value wins and the counter
    is left untouched, keeping the alternation deterministic.
    """
    if force in ("male", "female", "pilot"):
        return force
    doc = await db.settings.find_one({"key": "auto_media_gen_persona_counter"}) or {}
    n = int(doc.get("value") or 0)
    persona = "female" if (n % 2) == 1 else "male"
    try:
        await db.settings.update_one(
            {"key": "auto_media_gen_persona_counter"},
            {"$set": {"value": n + 1, "updated_at": now_iso()}},
            upsert=True,
        )
    except Exception:
        logger.warning("auto_media_gen: persona counter increment failed", exc_info=True)
    return persona


async def auto_enqueue_media_for_exercise(
    ex_id: str, *, triggered_by: Optional[str] = None,
    suppress_kinds: tuple[str, ...] = (),
    persona: Optional[str] = None,
) -> dict:
    """Kick off auto-generation for one exercise. Returns a summary dict.

    Fires and forgets — the actual LLM calls run in background tasks.
    Safe to call repeatedly; slots already populated are skipped.

    `triggered_by` is a user id (coach) for the audit log, when the
    creation is directly attributable. If None we use the system marker.

    `suppress_kinds` is a tuple of kind names that are FORBIDDEN for this
    invocation regardless of the default/DB/env toggles. Used by the
    alternatives auto-generator to guarantee a depth-1 fan-out — when we
    recurse into a newly-created alternative draft we pass
    ``suppress_kinds=("alternatives",)`` so the second-level draft
    generates primary image + coaching_points + common_mistakes but
    NEVER another alternatives round. Mathematically prevents recursion.
    """
    if not AUTO_MEDIA_GEN_ENABLED:
        return {"skipped": True, "reason": "AUTO_MEDIA_GEN disabled"}

    # Iter181c · MANUAL_MODE kill-switch. When ON, all AUTOMATIC exercise
    # media triggers (Atlas alternatives fanout, hotel conversion, alt
    # stubs from subs_allowed, new-exercise-on-create) short-circuit.
    # Coach-tapped bulk sweep + per-exercise regen still go through
    # dedicated endpoints that respect their own env guards.
    try:
        from feature_exercise_dedup import manual_mode_active
        if manual_mode_active():
            return {"skipped": True, "reason": "MANUAL_MODE"}
    except Exception:
        # Import failure is non-fatal — auto-gen simply keeps its old
        # behaviour if the dedup module is unavailable for some reason.
        pass

    # Global budget pause — one blown budget stops all kinds until the
    # coach clears it from the Generation Control panel.
    if await is_budget_paused():
        return {"skipped": True, "reason": "budget_paused"}

    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex:
        return {"skipped": True, "reason": "exercise not found"}

    # Iter 161 · Alias short-circuit — if this exercise is an alias of a
    # canonical winner, NEVER trigger media generation. The workout will
    # resolve to the winner's approved media instead. Prevents duplicate
    # naming (e.g. "Calf Raises" vs "Calf Raise") from paying for a fresh
    # image / coaching-points round.
    if ex.get("canonical_id") and ex["canonical_id"] != ex.get("id"):
        return {"skipped": True, "reason": "alias_of_canonical",
                "canonical_id": ex.get("canonical_id")}

    # Do NOT run against fully-approved exercises — respect coach's finished work.
    if ex.get("approval_status") == "approved" and ex.get("approved_image_status") == "Approved":
        return {"skipped": True, "reason": "already approved"}

    creator = triggered_by or _AUTO_USER_ID
    queued_images: list[str] = []
    queued_content: list[str] = []
    skipped_by_toggle: list[str] = []

    toggles = await _load_kind_toggles()

    # Recursion guard: any kind listed in ``suppress_kinds`` is force-disabled
    # for THIS invocation only. Never mutates DB toggles.
    if suppress_kinds:
        for _k in suppress_kinds:
            if _k in toggles:
                toggles[_k] = False
                skipped_by_toggle.append(f"{_k}:suppressed")
        logger.info(
            "auto_media_gen: suppress_kinds=%s applied for ex=%s",
            suppress_kinds, ex_id,
        )

    # ---- Images (only for slots that are still empty AND enabled) ----
    per_slot_toggle = {
        "primary": toggles.get("image_primary", True),
        "start":   toggles.get("image_start",   False),
        "end":     toggles.get("image_end",     False),
    }
    if not any(per_slot_toggle.values()):
        for slot in _AUTO_SLOTS:
            skipped_by_toggle.append(f"image_{slot}")
    else:
        try:
            from feature_exercise_content import (
                _build_ex_prompt, _run_image_job, _resolve_persona,
                _slot_map_field_for_persona,
            )
            # Iter181 · Alternate male/female by default so the library
            # shows diversity. Callers can force a persona for a specific
            # exercise via the `persona` kwarg (e.g. coach admin form).
            resolved_persona = await _next_persona_for_new_exercise(force=persona)
            slot_map_field = _slot_map_field_for_persona(resolved_persona)

            legacy_key_by_slot = {
                "primary": "primary_image_id",
                "start":   "demo_start_image_id",
                "end":     "demo_end_image_id",
            }
            set_updates: dict = {}
            for slot in _AUTO_SLOTS:
                if not per_slot_toggle.get(slot):
                    skipped_by_toggle.append(f"image_{slot}")
                    continue
                legacy_key = legacy_key_by_slot[slot]
                # Skip if already populated (via legacy or persona map).
                if ex.get(legacy_key):
                    continue
                slot_map = ex.get(slot_map_field) or {}
                if slot_map.get(slot):
                    continue

                image_id = new_id()
                prompt = _build_ex_prompt(ex, slot, None, persona=resolved_persona)
                await db.exercise_content_images.insert_one({
                    "id": image_id, "exercise_id": ex_id, "slot": slot,
                    "requested_slot": slot,
                    "gender": resolved_persona if resolved_persona in ("male", "female") else "male",
                    "persona": resolved_persona,
                    "prompt": prompt, "status": "generating",
                    "storage_path": None, "size_bytes": None, "mime": None,
                    "created_by": creator, "auto": True,
                    "created_at": now_iso(), "updated_at": now_iso(),
                })
                set_updates[f"{slot_map_field}.{slot}"] = image_id
                set_updates[legacy_key] = image_id
                queued_images.append(slot)
                _spawn_bg(
                    _safe_run_image_job(image_id, prompt, ex_id=ex_id, slot=slot)
                )

            if set_updates:
                set_updates["approved_image_status"] = "Needs Review"
                set_updates["content_status.images"] = True
                # Iter181 · Persist which demonstrator persona this
                # exercise was rendered with so the coach UI can show a
                # small M/F chip and offer a one-tap "regenerate as
                # opposite gender" action.
                set_updates["auto_persona"] = resolved_persona
                set_updates["updated_at"] = now_iso()
                await db.exercises_v2.update_one({"id": ex_id}, {"$set": set_updates})
        except Exception as e:
            logger.warning(f"auto_media_gen: image queue failed for {ex_id}: {e}")

    # ---- Written content — coaching points, common mistakes, alternatives,
    # client-facing instructions. Each fires only if its field is empty on the
    # exercise, and each runs as its own asyncio task so exercise creation
    # returns immediately. Coach still has final say — nothing is published
    # and the coach can regenerate any of them from the library UI.
    _CONTENT_KINDS: tuple[str, ...] = (
        "coaching_points",
        "common_mistakes",
        "alternatives",
        "instructions",
    )
    try:
        for kind in _CONTENT_KINDS:
            if not toggles.get(kind, True):
                skipped_by_toggle.append(kind)
                continue
            field = _kind_to_field(kind)
            existing = ex.get(field)
            # Skip if the coach has already authored content for this field.
            already_populated = (
                (isinstance(existing, list) and len(existing) > 0)
                or (isinstance(existing, str) and existing.strip() != "")
            )
            if already_populated:
                continue
            _spawn_bg(_auto_generate_content(ex_id, kind, creator))
            # ^^ INTENTIONAL: this path is used by single-exercise
            # creation triggers (Atlas alternatives, hotel conversions,
            # manual add). We rely on the caller keeping the endpoint
            # response short; for bulk sweeps, the backfill endpoint
            # switches to inline `await` (see /backfill-needs-review)
            # so GC / worker-recycle cannot drop mid-execution tasks.
            #
            # Even on this path we STRONGLY reference the task via the
            # module-level _BG_TASKS set so Python's weak-ref GC can't
            # drop it.
            queued_content.append(kind)
    except Exception as e:
        logger.warning(f"auto_media_gen: content queue failed for {ex_id}: {e}")

    if queued_images or queued_content:
        try:
            from feature_exercise_content import _log
            await _log(
                ex_id, creator, "auto_media_gen_enqueued",
                f"images={','.join(queued_images) or '-'} content={','.join(queued_content) or '-'}"
                + (f" skipped_by_toggle={','.join(skipped_by_toggle)}" if skipped_by_toggle else ""),
            )
        except Exception:
            pass

    return {
        "skipped": False,
        "queued_images": queued_images,
        "queued_content": queued_content,
        "skipped_by_toggle": skipped_by_toggle,
    }


# ---------------------------------------------------------------------------
# Written content — unified generator (coaching points / mistakes / alt / instr)
# ---------------------------------------------------------------------------

def _kind_to_field(kind: str) -> str:
    """Map the content kind to the exercises_v2 field name it writes to.
    Mirrors the manual /exercise-content/{id}/generate-content field map so
    both paths converge on the same schema."""
    return {
        "coaching_points":  "coaching_points",
        "common_mistakes":  "common_mistakes",
        "alternatives":     "alternatives",
        "instructions":     "client_facing_instructions",
    }[kind]


# Same prompts as the manual endpoint. Keeping them in one place avoids
# drift between auto and manual generation.
_KIND_TASK_PROMPTS: dict[str, str] = {
    "coaching_points": (
        "Return 4–6 short concise coaching points (imperative, one line each). "
        "Focus on technique cues an aviation-crew client can execute in a "
        "hotel gym."
    ),
    "common_mistakes": (
        "Return 3–5 common mistakes clients make with this exercise. "
        "Each item is one short sentence."
    ),
    "alternatives": (
        "Return AT MOST 3 alternative exercises that train the same movement "
        "pattern, ordered by similarity. Only the exercise names, no "
        "explanation. Return no more than 3 items even if more are possible."
    ),
    "instructions": (
        "Return 3–5 sentences of client-facing plain-English instructions "
        "for how to perform the exercise, written warmly (as if Louis is "
        "coaching the client through it)."
    ),
}


async def _auto_generate_content(ex_id: str, kind: str, creator: str) -> None:
    """Background — draft one content field via Claude. Idempotent.
    Never raises; failure just logs so the coach can regenerate manually.

    On `alternatives`, mirrors the manual endpoint by promoting each
    alternative name into a real library draft via `resolve_or_draft_exercise`
    so the media queue and swap-menu can reference them. Idempotent — the
    resolver itself dedups.
    """
    if kind not in _KIND_TASK_PROMPTS:
        return
    # Belt-and-braces: honour the toggle at task start too, in case the
    # coach flipped it OFF between enqueue and execution.
    if not await _kind_enabled(kind):
        return
    # Global budget pause — abort ALL further generation once we've hit
    # a budget-exceeded error, so we don't burn credits on error responses.
    if await is_budget_paused():
        return
    try:
        ex = await db.exercises_v2.find_one({"id": ex_id})
        if not ex:
            return
        field = _kind_to_field(kind)
        # Coach may have written content while our task sat in the queue.
        current = ex.get(field)
        if (isinstance(current, list) and current) or (
            isinstance(current, str) and current.strip()
        ):
            return

        name = ex.get("exercise_name") or "exercise"
        equipment = ", ".join(ex.get("equipment_type") or []) or "bodyweight"
        body_area = ex.get("body_area") or ""
        difficulty = ex.get("difficulty_level") or "intermediate"

        system = (
            "You are Louis Hall, CrewFit's founder and aviation performance coach. "
            "Write like a real coach: direct, practical, safety-aware. Never make "
            "medical claims. Never diagnose. Always assume the client has limited "
            "equipment and is on the road."
        )
        task = _KIND_TASK_PROMPTS[kind]
        prompt = (
            f"Exercise: {name}\nEquipment: {equipment}\nBody area: {body_area}\n"
            f"Difficulty: {difficulty}\n\n{task}\n\n"
            'OUTPUT: strict JSON. For lists: {"items": ["string", ...]}. '
            'For instructions: {"text": "one paragraph"}. '
            "No prose outside the JSON."
        )

        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"auto-content-{ex_id}-{kind}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929").with_params(max_tokens=500)
        reply = await chat.send_message(UserMessage(text=prompt))

        text = str(reply or "").strip()
        parsed: dict = {}
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = {}

        updates: dict = {"updated_at": now_iso()}

        if kind == "instructions":
            val = str(parsed.get("text") or text).strip()
            if not val:
                return
            updates[field] = val
        else:
            items = parsed.get("items") or []
            if not isinstance(items, list):
                items = []
            if not items and text:
                # Fallback: try to split lines when JSON parsing failed.
                items = [
                    ln.lstrip("-• 0123456789.").strip()
                    for ln in text.splitlines()
                    if ln.strip()
                ][:6]
            items = [str(i).strip() for i in items if str(i).strip()][:6]
            # Alternatives are hard-capped at 3 to bound depth-1 fan-out
            # cost (see recursion guard). Coach can still add more manually
            # via the Library UI if needed.
            if kind == "alternatives":
                items = items[:3]
            if not items:
                return
            updates[field] = items
            if kind == "coaching_points":
                updates["content_status.coaching_points"] = True
            if kind == "common_mistakes":
                updates["content_status.common_mistakes"] = True
            if kind == "alternatives":
                updates["content_status.alternatives"] = True

        if kind == "instructions":
            updates["content_status.instructions"] = True

        await db.exercises_v2.update_one({"id": ex_id}, {"$set": updates})

        # Atlas alternatives library backfill — mirrors the manual endpoint.
        # Each alternative name becomes (or resolves to) a real library
        # draft so the swap-menu and media queue can address them by id.
        if kind == "alternatives":
            alt_names = updates.get(field) or []
            if alt_names:
                try:
                    from feature_media_queue import resolve_or_draft_exercise
                    alt_ids: list[str] = []
                    # Use a lightweight "user" doc — resolve_or_draft_exercise
                    # only needs an id for audit + parent for equipment copy.
                    user_stub = {"id": creator, "role": "coach"}
                    for alt_name in alt_names:
                        try:
                            xid = await resolve_or_draft_exercise(
                                alt_name,
                                user=user_stub,
                                parent=ex,
                                reason=f"atlas_alternative_of:{ex.get('exercise_name') or ex_id}",
                                # RECURSION GUARD — the newly-created
                                # alternative draft may auto-generate
                                # primary image + coaching_points +
                                # common_mistakes, but NEVER another round
                                # of alternatives. Bounds cost at depth-1
                                # fan-out. Removing this argument re-opens
                                # unbounded cascade — do not do that.
                                suppress_auto_media_kinds=("alternatives",),
                            )
                            if xid:
                                alt_ids.append(xid)
                        except Exception:
                            logger.exception(
                                "auto_media_gen: alt resolve failed for %s → %s",
                                ex_id, alt_name,
                            )
                    if alt_ids:
                        await db.exercises_v2.update_one(
                            {"id": ex_id},
                            {"$set": {
                                "alternative_exercise_ids": alt_ids,
                                "updated_at": now_iso(),
                            }},
                        )
                except Exception:
                    logger.exception(
                        "auto_media_gen: alternatives backfill failed for %s", ex_id
                    )

        # Telemetry so we can see credit burn.
        try:
            await db.ai_usage.insert_one({
                "user_id": creator,
                "feature": f"auto_media_gen_{kind}",
                "exercise_id": ex_id,
                "tokens_estimate": 500,
                "created_at": now_iso(),
            })
        except Exception:
            pass

        try:
            from feature_exercise_content import _log
            await _log(
                ex_id, _AUTO_USER_ID, f"auto_{kind}",
                f"auto-generated {kind}",
            )
        except Exception:
            pass
    except Exception as e:
        # Budget-exceeded errors trip the global pause and stop remaining
        # tasks. Other exceptions just log so the coach can regen manually.
        if _is_budget_error(e):
            await _mark_budget_paused(str(e), ex_id=ex_id, kind=kind)
        logger.warning(
            f"auto_media_gen: {kind} generation failed for {ex_id}: {e}"
        )


# ---------------------------------------------------------------------------
# Public — small admin endpoint to toggle / inspect the flag
# ---------------------------------------------------------------------------
from fastapi import Depends
from server import api, require_role


@api.get("/coach/auto-media-gen/status")
async def auto_media_gen_status(_: dict = Depends(require_role("coach"))):
    toggles = await _load_kind_toggles()
    # Budget pause payload — surfaces the coach-facing banner.
    paused = await is_budget_paused()
    doc = {}
    try:
        doc = await db.settings.find_one(
            {"_id": _SETTINGS_DOC_ID},
            {"_id": 0, "budget_paused_at": 1, "budget_paused_reason": 1,
             "budget_paused_by_kind": 1, "budget_paused_by_exercise_id": 1,
             "budget_resumed_at": 1, "budget_resumed_by": 1},
        ) or {}
    except Exception:
        pass
    return {
        "enabled": AUTO_MEDIA_GEN_ENABLED,
        "default_slots": list(_AUTO_SLOTS),
        "auto_content_kinds": ["coaching_points", "common_mistakes",
                                "alternatives", "instructions"],
        "toggles": toggles,
        "labels": _KIND_LABELS,
        "env_kill_switches": {k: v for k, v in _KIND_ENV_OFF.items() if v},
        "budget_paused": paused,
        "budget_paused_at": doc.get("budget_paused_at"),
        "budget_paused_reason": doc.get("budget_paused_reason"),
        "budget_paused_by_kind": doc.get("budget_paused_by_kind"),
        "budget_paused_by_exercise_id": doc.get("budget_paused_by_exercise_id"),
        "budget_resumed_at": doc.get("budget_resumed_at"),
        "note": "Toggle per kind via PATCH /coach/auto-media-gen/settings. Env var *_OFF still wins.",
    }


@api.post("/coach/auto-media-gen/budget/resume")
async def auto_media_gen_budget_resume(
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Clear the global budget-paused flag once the coach has topped up
    credits on the Emergent Universal Key. Fresh auto-gen tasks will
    resume on the next exercise-create trigger."""
    payload = await _clear_budget_pause(by=coach.get("id") or "unknown")
    return {"ok": True, **payload}


@api.get("/coach/auto-media-gen/settings")
async def auto_media_gen_settings_get(_: dict = Depends(require_role("coach"))):
    return {
        "toggles": await _load_kind_toggles(),
        "labels": _KIND_LABELS,
        "env_kill_switches": {k: v for k, v in _KIND_ENV_OFF.items() if v},
    }


@api.patch("/coach/auto-media-gen/settings")
async def auto_media_gen_settings_patch(
    body: dict, coach: dict = Depends(require_role("coach")),
):
    """Coach flips one or more per-kind toggles.

    Body: {"toggles": {"images": false, "alternatives": true, ...}}

    Only the kinds sent in the body are changed; anything missing stays
    at its current value. Env-var kill switches still win at read time.
    """
    incoming = (body or {}).get("toggles") or {}
    if not isinstance(incoming, dict):
        return {"ok": False, "error": "toggles must be an object"}
    valid_kinds = set(_KIND_LABELS.keys())
    cleaned: dict = {}
    for k, v in incoming.items():
        if k not in valid_kinds:
            continue
        cleaned[k] = bool(v)
    if not cleaned:
        return {"ok": False, "error": "no valid kinds provided"}

    cleaned["updated_at"] = now_iso()
    cleaned["updated_by"] = coach.get("id")
    await db.settings.update_one(
        {"_id": _SETTINGS_DOC_ID},
        {"$set": cleaned},
        upsert=True,
    )
    return {
        "ok": True,
        "toggles": await _load_kind_toggles(),
        "changed": {k: v for k, v in cleaned.items() if k in valid_kinds},
    }


@api.post("/coach/exercises/{ex_id}/auto-generate")
async def auto_media_gen_manual_trigger(
    ex_id: str, coach: dict = Depends(require_role("coach")),
):
    """Explicit trigger — the coach can also force a re-queue if the
    background job never fired (e.g. AUTO_MEDIA_GEN was off at creation)."""
    return await auto_enqueue_media_for_exercise(ex_id, triggered_by=coach.get("id"))


# ---------------------------------------------------------------------------
# Backfill audit — active exercises missing any auto-generatable content
# ---------------------------------------------------------------------------

@api.get("/coach/auto-media-gen/backfill-report")
async def auto_media_gen_backfill_report(
    active_only: bool = True,
    limit: int = 500,
    coach: dict = Depends(require_role("coach")),
):
    """Report every active exercise that is missing coaching_points,
    common_mistakes, alternatives, client-facing instructions, or any of
    the three standard image slots. Coach-facing — used to decide which
    library entries need a backfill pass.

    Purely read-only. Zero LLM credits.
    """
    query: dict = {}
    if active_only:
        # "Active" = anything that isn't archived / deleted / retired.
        # `$nin` is case-sensitive so we normalise via $expr toLower.
        query["$and"] = [
            {"is_deleted": {"$ne": True}},
            {"$expr": {
                "$not": {"$in": [
                    {"$toLower": {"$ifNull": ["$status", ""]}},
                    ["archived", "retired", "deprecated"],
                ]}
            }},
        ]

    total = 0
    missing_coaching = 0
    missing_mistakes = 0
    missing_alts = 0
    missing_instr = 0
    missing_primary = 0
    missing_start = 0
    missing_end = 0
    approved = 0
    draft = 0

    per_ex: list[dict] = []
    async for ex in db.exercises_v2.find(query, {
        "_id": 0, "id": 1, "exercise_name": 1, "status": 1,
        "coaching_points": 1, "common_mistakes": 1, "alternatives": 1,
        "client_facing_instructions": 1,
        "primary_image_id": 1, "demo_start_image_id": 1, "demo_end_image_id": 1,
        "approval_status": 1, "approved_image_status": 1,
        "body_area": 1, "equipment_type": 1,
    }).limit(limit * 4):
        total += 1
        cp_missing = not (isinstance(ex.get("coaching_points"), list) and ex["coaching_points"])
        cm_missing = not (isinstance(ex.get("common_mistakes"), list) and ex["common_mistakes"])
        al_missing = not (isinstance(ex.get("alternatives"), list) and ex["alternatives"])
        instr_val = ex.get("client_facing_instructions")
        in_missing = not (isinstance(instr_val, str) and instr_val.strip())
        p_missing = not ex.get("primary_image_id")
        s_missing = not ex.get("demo_start_image_id")
        e_missing = not ex.get("demo_end_image_id")

        if cp_missing: missing_coaching += 1
        if cm_missing: missing_mistakes += 1
        if al_missing: missing_alts += 1
        if in_missing: missing_instr += 1
        if p_missing: missing_primary += 1
        if s_missing: missing_start += 1
        if e_missing: missing_end += 1

        status = str(ex.get("status") or "").lower()
        if status in ("approved", "live"):
            approved += 1
        else:
            draft += 1

        needs = [k for k, v in [
            ("coaching_points", cp_missing),
            ("common_mistakes", cm_missing),
            ("alternatives",    al_missing),
            ("instructions",    in_missing),
            ("image_primary",   p_missing),
            ("image_start",     s_missing),
            ("image_end",       e_missing),
        ] if v]

        if needs and len(per_ex) < limit:
            per_ex.append({
                "id": ex.get("id"),
                "name": ex.get("exercise_name"),
                "status": ex.get("status"),
                "body_area": ex.get("body_area"),
                "equipment": ex.get("equipment_type"),
                "needs": needs,
            })

    return {
        "total_active_exercises": total,
        "approved": approved,
        "draft": draft,
        "counts_missing": {
            "coaching_points": missing_coaching,
            "common_mistakes": missing_mistakes,
            "alternatives":    missing_alts,
            "instructions":    missing_instr,
            "image_primary":   missing_primary,
            "image_start":     missing_start,
            "image_end":       missing_end,
        },
        "exercises_needing_backfill": per_ex,
        "shown": len(per_ex),
        "truncated": len(per_ex) >= limit,
        "note": (
            "Use POST /api/coach/exercises/{id}/auto-generate to re-queue "
            "any exercise. Auto-media-gen is idempotent — populated fields "
            "are never overwritten."
        ),
    }


# ---------------------------------------------------------------------------
# Bulk backfill runner — coach explicitly opts in per batch.
# ---------------------------------------------------------------------------

@api.post("/coach/auto-media-gen/backfill-run")
async def auto_media_gen_backfill_run(
    body: dict, coach: dict = Depends(require_role("coach")),
):
    """Manually run auto-generation for a list of exercise ids.

    Body: {"exercise_ids": ["...", "..."], "dry_run": bool}

    dry_run=true just reports what WOULD fire without spending credits.
    Coach must send this explicitly per batch so we never accidentally
    re-generate hundreds of exercises in one go.
    """
    ex_ids = (body or {}).get("exercise_ids") or []
    dry_run = bool((body or {}).get("dry_run"))
    if not isinstance(ex_ids, list) or not ex_ids:
        return {"queued": 0, "skipped": [], "reason": "no exercise_ids"}
    # Hard cap so a slip of the paste doesn't drain credits.
    ex_ids = [str(x) for x in ex_ids][:50]

    results = []
    for ex_id in ex_ids:
        if dry_run:
            ex = await db.exercises_v2.find_one(
                {"id": ex_id},
                {"_id": 0, "id": 1, "exercise_name": 1,
                 "coaching_points": 1, "common_mistakes": 1,
                 "alternatives": 1, "client_facing_instructions": 1,
                 "primary_image_id": 1, "demo_start_image_id": 1, "demo_end_image_id": 1},
            )
            if not ex:
                results.append({"id": ex_id, "would_queue": [], "note": "not found"})
                continue
            would: list[str] = []
            if not (isinstance(ex.get("coaching_points"), list) and ex["coaching_points"]):
                would.append("coaching_points")
            if not (isinstance(ex.get("common_mistakes"), list) and ex["common_mistakes"]):
                would.append("common_mistakes")
            if not (isinstance(ex.get("alternatives"), list) and ex["alternatives"]):
                would.append("alternatives")
            v = ex.get("client_facing_instructions")
            if not (isinstance(v, str) and v.strip()):
                would.append("instructions")
            if not ex.get("primary_image_id"): would.append("image_primary")
            if not ex.get("demo_start_image_id"): would.append("image_start")
            if not ex.get("demo_end_image_id"): would.append("image_end")
            results.append({
                "id": ex_id, "name": ex.get("exercise_name"),
                "would_queue": would,
            })
        else:
            res = await auto_enqueue_media_for_exercise(
                ex_id, triggered_by=coach.get("id"),
            )
            results.append({"id": ex_id, **res})
    return {
        "dry_run": dry_run,
        "batch_size": len(ex_ids),
        "results": results,
    }


logger.info(
    f"feature_auto_media_gen: enabled={AUTO_MEDIA_GEN_ENABLED} "
    f"slots={_AUTO_SLOTS} kinds={list(_KIND_LABELS)} "
    f"env_kill_switches={[k for k,v in _KIND_ENV_OFF.items() if v] or 'none'}"
)


# ---------------------------------------------------------------------------
# Iter181 · Bulk Needs-Review backfill.
# ---------------------------------------------------------------------------
# Coach taps "RUN FOR ALL NEEDS REVIEW" → we spawn a single background
# worker that iterates the whole library, respecting:
#   · single-flight lock (only one sweep in flight globally)
#   · MANUAL_MODE / EXERCISE_BACKFILL_DISABLED kill-switches
#   · budget_paused settings marker
#   · bounded LLM concurrency (Semaphore(6))
#
# The HTTP endpoint returns HTTP 202 immediately with a `job_id`; the
# UI polls `GET /coach/auto-media-gen/backfill-status/{job_id}` every
# 2 s so the browser can never time out. Progress is persisted to the
# `backfill_jobs` collection so a worker recycle mid-sweep leaves an
# audit trail (job stays `running` until either finished or manually
# marked `failed`).
# ---------------------------------------------------------------------------
from fastapi import Response, HTTPException  # noqa: E402
from feature_exercise_dedup import (  # noqa: E402
    exercise_backfill_disabled,
    manual_mode_active,
)

# Single-flight lock. Protects the WORKER function, so a concurrent
# request can distinguish "sweep in flight" from "spawn a new one".
_BACKFILL_LOCK: asyncio.Lock = asyncio.Lock()


async def _record_job(job_id: str, patch: dict) -> None:
    """Idempotent upsert of the job doc; keeps updated_at fresh."""
    from datetime import datetime, timezone
    patch = {**patch, "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        await db.backfill_jobs.update_one(
            {"_id": job_id}, {"$set": patch}, upsert=True,
        )
    except Exception:
        logger.exception("backfill_jobs write failed for %s", job_id)


async def _backfill_worker(job_id: str, *, coach_id: str, skip_images: bool) -> None:
    """Runs under `_BACKFILL_LOCK`. Sweeps the whole library — no per-call
    limit — while respecting the shared semaphore.  Progress is persisted
    to `backfill_jobs` after every processed exercise so the polling UI
    can render a live counter."""
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat()
    try:
        async with _BACKFILL_LOCK:
            await _record_job(job_id, {
                "status": "running",
                "started_at": started,
                "coach_id": coach_id,
                "skip_images": skip_images,
                "processed": 0, "wrote": 0,
                "errors": {}, "results_sample": [],
            })

            # Same filter as the coach UI's NEEDS REVIEW + MISSING tabs.
            query = {
                "$and": [
                    {"$or": [
                        {"status": {"$in": ["draft_requested", "coach_review_needed", "draft", "Draft"]}},
                        {"approved_image_status": {"$in": ["Needs Review", "Missing", "missing"]}},
                        {"approval_status": {"$in": ["pending", "needs_review", "draft"]}},
                    ]},
                    {"$or": [
                        {"coaching_points":            {"$in": [None, [], ""]}},
                        {"common_mistakes":            {"$in": [None, [], ""]}},
                        {"client_facing_instructions": {"$in": [None, ""]}},
                    ]},
                    # Skip aliases — they resolve to canonical content.
                    {"$or": [
                        {"canonical_id": None},
                        {"canonical_id": {"$exists": False}},
                        {"$expr": {"$eq": ["$canonical_id", "$id"]}},
                    ]},
                ],
            }
            projection = {"_id": 0, "id": 1, "exercise_name": 1}
            exs = await db.exercises_v2.find(query, projection).to_list(length=1000)

            sem = asyncio.Semaphore(6)
            toggles = await _load_kind_toggles()
            _CONTENT_KINDS_BULK = ("coaching_points", "common_mistakes", "instructions")

            processed = 0
            wrote_total = 0
            errors: dict[str, int] = {}
            sample: list[dict] = []

            async def _process(ex: dict) -> dict:
                ex_id = ex["id"]
                full = await db.exercises_v2.find_one({"id": ex_id}) or {}
                if full.get("canonical_id") and full["canonical_id"] != ex_id:
                    return {"id": ex_id, "skipped": True, "reason": "alias"}
                if await is_budget_paused():
                    return {"id": ex_id, "skipped": True, "reason": "budget_paused"}
                wrote: list[str] = []
                errs: list[str] = []
                for kind in _CONTENT_KINDS_BULK:
                    if not toggles.get(kind, True):
                        continue
                    field = _kind_to_field(kind)
                    existing = full.get(field)
                    if (isinstance(existing, list) and existing) or (
                        isinstance(existing, str) and existing.strip()
                    ):
                        continue
                    try:
                        async with sem:
                            await _auto_generate_content(ex_id, kind, coach_id or _AUTO_USER_ID)
                        verify = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0, field: 1})
                        v = (verify or {}).get(field)
                        if (isinstance(v, list) and v) or (isinstance(v, str) and v.strip()):
                            wrote.append(kind)
                        else:
                            errs.append(f"{kind}:empty_after_run")
                    except Exception as e:
                        errs.append(f"{kind}:{str(e)[:80]}")
                        logger.warning(
                            "auto_media_gen.backfill: %s kind=%s failed: %s",
                            ex_id, kind, e,
                        )
                if not skip_images:
                    try:
                        async with sem:
                            img_res = await auto_enqueue_media_for_exercise(
                                ex_id, triggered_by=coach_id,
                            )
                        if img_res.get("queued_images"):
                            wrote += [f"image_{s}" for s in img_res["queued_images"]]
                    except Exception as e:
                        errs.append(f"images:{str(e)[:80]}")
                return {
                    "id": ex_id, "name": ex.get("exercise_name"),
                    "wrote": wrote, "errors": errs,
                }

            # Iterate in gather-batches of 12 so progress writes stay lively.
            _BATCH = 12
            for i in range(0, len(exs), _BATCH):
                chunk = exs[i:i + _BATCH]
                per_ex = await asyncio.gather(
                    *(_process(ex) for ex in chunk), return_exceptions=True,
                )
                for r in per_ex:
                    if isinstance(r, Exception):
                        errors["exception"] = errors.get("exception", 0) + 1
                        continue
                    processed += 1
                    if r.get("wrote"):
                        wrote_total += 1
                    for e in (r.get("errors") or []):
                        k = e.split(":", 1)[0]
                        errors[k] = errors.get(k, 0) + 1
                    if len(sample) < 20 and r.get("wrote"):
                        sample.append({"id": r.get("id"), "name": r.get("name"), "wrote": r.get("wrote")})
                # Flush progress after each batch.
                await _record_job(job_id, {
                    "processed": processed, "wrote": wrote_total,
                    "errors": errors, "results_sample": sample,
                    "total_in_scope": len(exs),
                    "budget_paused": await is_budget_paused(),
                })

            await _record_job(job_id, {
                "status": "complete",
                "processed": processed, "wrote": wrote_total,
                "errors": errors, "results_sample": sample,
                "total_in_scope": len(exs),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "budget_paused": await is_budget_paused(),
            })
    except Exception as e:
        logger.exception("backfill worker crashed job=%s", job_id)
        try:
            await _record_job(job_id, {
                "status": "failed",
                "error": str(e)[:200],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass


@api.post("/coach/auto-media-gen/backfill-needs-review")
async def auto_media_gen_backfill_needs_review(
    body: Optional[dict] = None,
    coach: dict = Depends(require_role("coach")),
    response: Response = None,
):
    """Fire-and-forget kickoff.

    Body (all optional):
        dry_run: bool     when true, returns the queue snapshot only.
        skip_images: bool default true — skips image kinds.

    Response 202 + {"job_id": ...} — poll `/backfill-status/{job_id}`
    every 2 s until `status ∈ ("complete","failed")`.

    Kill-switches (both return 403):
      · `MANUAL_MODE=true`
      · `EXERCISE_BACKFILL_DISABLED=true`

    Single-flight lock: if a sweep is already running, returns 409
    with the in-flight `job_id` so the UI can attach to it.
    """
    body = body or {}
    dry_run = bool(body.get("dry_run"))
    skip_images = bool(body.get("skip_images", True))

    # ---- Kill switches ------------------------------------------------
    if manual_mode_active():
        if response is not None:
            response.status_code = 403
        return {
            "status": "blocked",
            "reason": "MANUAL_MODE",
            "detail": "MANUAL_MODE=true — automatic sweeps are disabled. "
                      "Turn MANUAL_MODE off (or use per-exercise regen) to run this.",
        }
    if exercise_backfill_disabled():
        if response is not None:
            response.status_code = 403
        return {
            "status": "blocked",
            "reason": "EXERCISE_BACKFILL_DISABLED",
            "detail": "EXERCISE_BACKFILL_DISABLED=true — sweep is frozen. "
                      "Unset the env var to re-enable.",
        }

    # ---- Dry-run (fast path — no job spawned) -------------------------
    if dry_run:
        query = {
            "$and": [
                {"$or": [
                    {"status": {"$in": ["draft_requested", "coach_review_needed", "draft", "Draft"]}},
                    {"approved_image_status": {"$in": ["Needs Review", "Missing", "missing"]}},
                    {"approval_status": {"$in": ["pending", "needs_review", "draft"]}},
                ]},
                {"$or": [
                    {"coaching_points":            {"$in": [None, [], ""]}},
                    {"common_mistakes":            {"$in": [None, [], ""]}},
                    {"client_facing_instructions": {"$in": [None, ""]}},
                ]},
                {"$or": [
                    {"canonical_id": None},
                    {"canonical_id": {"$exists": False}},
                    {"$expr": {"$eq": ["$canonical_id", "$id"]}},
                ]},
            ],
        }
        n = await db.exercises_v2.count_documents(query)
        return {"dry_run": True, "would_queue_count": n}

    # ---- Single-flight lock check -------------------------------------
    if _BACKFILL_LOCK.locked():
        # Find the in-flight job so the UI can attach.
        in_flight = await db.backfill_jobs.find_one(
            {"status": "running"}, sort=[("started_at", -1)],
        )
        if response is not None:
            response.status_code = 409
        return {
            "status": "already_running",
            "reason": "single_flight",
            "job_id": (in_flight or {}).get("_id"),
            "detail": "A sweep is already in flight — attach to it via "
                      "`GET /coach/auto-media-gen/backfill-status/{job_id}`.",
        }

    # ---- Spawn background worker --------------------------------------
    from server import new_id
    job_id = new_id()
    await _record_job(job_id, {
        "status": "queued",
        "coach_id": coach.get("id"),
        "skip_images": skip_images,
    })
    _spawn_bg(_backfill_worker(job_id, coach_id=coach.get("id"), skip_images=skip_images))
    if response is not None:
        response.status_code = 202
    return {
        "status": "queued",
        "job_id": job_id,
        "poll_url": f"/api/coach/auto-media-gen/backfill-status/{job_id}",
    }


@api.get("/coach/auto-media-gen/backfill-status/{job_id}")
async def auto_media_gen_backfill_status(
    job_id: str,
    coach: dict = Depends(require_role("coach")),
):
    """Poll the progress of a backfill job spawned by the endpoint above.
    Safe to call as often as the UI wants — cheap single-doc read."""
    doc = await db.backfill_jobs.find_one({"_id": job_id})
    if not doc:
        return {"status": "unknown", "job_id": job_id}
    # Strip mongo _id key from the response for clean JSON.
    doc["job_id"] = doc.pop("_id")
    return doc


logger.info(
    "feature_auto_media_gen: MANUAL_MODE=%s EXERCISE_BACKFILL_DISABLED=%s",
    manual_mode_active(), exercise_backfill_disabled(),
)


# ---------------------------------------------------------------------------
# Iter182 · Sequential PRIMARY-IMAGE bulk generator.
# ---------------------------------------------------------------------------
# Coach taps "GENERATE MISSING PRIMARY IMAGES" on the Exercise Library →
# spawns a background worker that iterates every exercise whose primary
# image status is DRAFT_REQUESTED (status == "draft_requested") or
# MISSING (approved_image_status ∈ {Missing, missing}) and generates
# ONE primary-frame image per exercise.
#
# Distinct from the Needs-Review backfill:
#   · Images only — never touches text kinds.
#   · Only the `primary` slot — start / end frames stay untouched.
#   · SEQUENTIAL — one Gemini call at a time (no Semaphore, no gather)
#     so we don't hammer the API with parallel image requests.
#
# Same job pattern as the other backfill: 202 + `job_id`, progress in
# `backfill_jobs`, single-flight lock, MANUAL_MODE / kill-switch aware.
# ---------------------------------------------------------------------------

_BULK_IMAGE_LOCK: asyncio.Lock = asyncio.Lock()


def _bulk_primary_image_query() -> dict:
    """Shared query for the primary-image bulk sweep.

    Iter185 · Previously the bulk count reported 427 while the Library's
    "Needs Review" tab only surfaced ~65 — a 6× overshoot. Root causes:
      1. `content_status.images: False` legacy catch-all matched every
         Approved row whose flag hadn't been backfilled, ballooning the
         set beyond what the coach expected to review.
      2. No exclusion for archived / retired / deprecated / merged /
         rejected / soft-deleted rows (production DB has `Archived` and
         friends in the mix; preview only has 0 today).
      3. Case-sensitive `$in` on `status` missed lower-case `draft`
         entries and let mixed-case `Archived` slip past future filters.
      4. Alias rows (canonical_id != own id) were correctly skipped, but
         we now spell that out with an explicit invariant.

    This helper is used by BOTH the dry-run count endpoint and the
    worker query so the two can NEVER drift again. Both branches read
    the same rows; no duplicates, no archived leftovers, no soft-deleted
    ghosts.
    """
    return {
        "$and": [
            # ─── Alive: not soft-deleted ─────────────────────────────────
            {"is_deleted": {"$ne": True}},
            # ─── Alive: not archived / retired / deprecated / merged /
            #             rejected (case-insensitive via $toLower) ────────
            {"$expr": {"$not": {"$in": [
                {"$toLower": {"$ifNull": ["$status", ""]}},
                ["archived", "retired", "deprecated", "merged", "rejected"],
            ]}}},
            # ─── Actually missing a primary image ────────────────────────
            {"$or": [
                {"primary_image_id": None},
                {"primary_image_id": {"$exists": False}},
                {"primary_image_id": ""},
            ]},
            # ─── Match: DRAFT status OR explicit MISSING marker ──────────
            #     (case-insensitive on `status`; explicit list on
            #      `approved_image_status` for Approved-but-imageless rows)
            {"$or": [
                {"$expr": {"$in": [
                    {"$toLower": {"$ifNull": ["$status", ""]}},
                    ["draft_requested", "draft", "coach_review_needed"],
                ]}},
                {"approved_image_status": {"$in": ["Missing", "missing"]}},
            ]},
            # ─── Canonical only (skip aliases / duplicates) ──────────────
            {"$or": [
                {"canonical_id": None},
                {"canonical_id": {"$exists": False}},
                {"$expr": {"$eq": ["$canonical_id", "$id"]}},
            ]},
        ],
    }


async def _bulk_primary_image_worker(
    job_id: str, *, coach_id: Optional[str], persona: Optional[str] = None,
) -> None:
    """Sequentially generate ONE primary image per matching exercise.
    Persists progress to `backfill_jobs` after every exercise so the
    polling UI can render a live counter."""
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat()
    try:
        async with _BULK_IMAGE_LOCK:
            await _record_job(job_id, {
                "status": "running",
                "kind": "bulk_primary_images",
                "started_at": started,
                "coach_id": coach_id,
                "processed": 0, "wrote": 0,
                "errors": {}, "results_sample": [],
            })

            # Iter185 · Shared with the dry-run endpoint so the count
            # the coach saw before pressing GENERATE == the set the
            # worker actually processes. Filters out archived / deleted /
            # merged rows and alias duplicates.
            query = _bulk_primary_image_query()
            projection = {"_id": 0, "id": 1, "exercise_name": 1,
                          "primary_image_id": 1, "status": 1,
                          "approved_image_status": 1, "canonical_id": 1}
            exs = await db.exercises_v2.find(query, projection).to_list(length=1000)

            processed = 0
            wrote = 0
            errors: dict[str, int] = {}
            sample: list[dict] = []

            for ex in exs:
                ex_id = ex["id"]
                processed += 1
                # Budget guard — respected per iteration so a mid-run
                # pause stops the sweep cleanly.
                if await is_budget_paused():
                    errors["budget_paused"] = errors.get("budget_paused", 0) + 1
                    await _record_job(job_id, {
                        "processed": processed, "wrote": wrote,
                        "errors": errors, "results_sample": sample,
                        "total_in_scope": len(exs),
                        "budget_paused": True,
                    })
                    break

                try:
                    # Route through the standard enqueue so persona
                    # alternation + content_status.images + audit log all
                    # stay consistent with per-exercise regen. We suppress
                    # `start` + `end` slots + all text kinds so this run
                    # only spends credits on the primary frame.
                    res = await auto_enqueue_media_for_exercise(
                        ex_id, triggered_by=coach_id,
                        suppress_kinds=("image_start", "image_end",
                                        "coaching_points", "common_mistakes",
                                        "alternatives", "instructions"),
                        persona=persona,
                    )
                    if res.get("queued_images"):
                        wrote += 1
                        if len(sample) < 20:
                            sample.append({
                                "id": ex_id, "name": ex.get("exercise_name"),
                                "wrote": res["queued_images"],
                            })
                    elif res.get("skipped"):
                        # E.g. MANUAL_MODE or already has image (race).
                        r = str(res.get("reason") or "skipped")
                        errors[r] = errors.get(r, 0) + 1
                except Exception as e:
                    errors["exception"] = errors.get("exception", 0) + 1
                    logger.warning(
                        "bulk_primary_images: %s failed: %s", ex_id, e,
                    )

                # Small breather between requests — belt-and-braces so we
                # never fire back-to-back Gemini calls even when the
                # underlying image job returns instantly from the queue.
                await asyncio.sleep(0.4)

                # Flush progress every 5 exercises so the polling UI
                # doesn't stall (DB write cost is negligible).
                if processed % 5 == 0:
                    await _record_job(job_id, {
                        "processed": processed, "wrote": wrote,
                        "errors": errors, "results_sample": sample,
                        "total_in_scope": len(exs),
                        "budget_paused": await is_budget_paused(),
                    })

            await _record_job(job_id, {
                "status": "complete",
                "processed": processed, "wrote": wrote,
                "errors": errors, "results_sample": sample,
                "total_in_scope": len(exs),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "budget_paused": await is_budget_paused(),
            })
    except Exception as e:
        logger.exception("bulk_primary_images worker crashed job=%s", job_id)
        try:
            from datetime import datetime, timezone
            await _record_job(job_id, {
                "status": "failed",
                "error": str(e)[:200],
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass


@api.post("/coach/auto-media-gen/bulk-primary-images")
async def auto_media_gen_bulk_primary_images(
    body: Optional[dict] = None,
    coach: dict = Depends(require_role("coach")),
    response: Response = None,
):
    """Sequentially generate the primary image for every exercise whose
    status is DRAFT_REQUESTED or MISSING.

    Body (all optional):
        dry_run: bool     → return count only, no work.
        persona: str      → force "male"/"female" for every exercise
                            (defaults: alternate via persona counter).

    Response 202 + `{job_id}`; poll `/backfill-status/{job_id}` (shared
    with the Needs-Review backfill) every 2 s.
    """
    body = body or {}
    dry_run = bool(body.get("dry_run"))
    persona = body.get("persona")
    if persona is not None and persona not in ("male", "female"):
        raise HTTPException(400, "persona must be 'male' or 'female'")

    # Iter185 · Shared helper query — same filter the worker uses.
    # dry_run is READ-ONLY (just a count) and MUST NOT be blocked by
    # MANUAL_MODE / EXERCISE_BACKFILL_DISABLED — coaches need visibility
    # into what the sweep *would* touch even when manual mode is on.
    query = _bulk_primary_image_query()

    # Kill-switches — same semantics as the Needs-Review backfill.
    # Only enforced for the actual work path, not the dry-run count.
    if not dry_run:
        if manual_mode_active():
            if response is not None:
                response.status_code = 403
            return {"status": "blocked", "reason": "MANUAL_MODE"}
        if exercise_backfill_disabled():
            if response is not None:
                response.status_code = 403
            return {"status": "blocked", "reason": "EXERCISE_BACKFILL_DISABLED"}

    if dry_run:
        n = await db.exercises_v2.count_documents(query)
        # Iter185 · Transparency breakdown — coach can see which
        # exclusion rules cut the raw count down to `would_queue_count`.
        # All counts are read-only $count aggregates → cheap.
        raw_missing_primary = await db.exercises_v2.count_documents({
            "$or": [
                {"primary_image_id": None},
                {"primary_image_id": {"$exists": False}},
                {"primary_image_id": ""},
            ],
        })
        excluded_archived = await db.exercises_v2.count_documents({
            "$expr": {"$in": [
                {"$toLower": {"$ifNull": ["$status", ""]}},
                ["archived", "retired", "deprecated", "merged", "rejected"],
            ]},
        })
        excluded_deleted = await db.exercises_v2.count_documents({"is_deleted": True})
        excluded_aliases = await db.exercises_v2.count_documents({
            "$and": [
                {"canonical_id": {"$ne": None}},
                {"canonical_id": {"$exists": True}},
                {"$expr": {"$ne": ["$canonical_id", "$id"]}},
            ],
        })
        return {
            "dry_run": True,
            "would_queue_count": n,
            "breakdown": {
                "raw_missing_primary_image": raw_missing_primary,
                "excluded_archived_or_retired": excluded_archived,
                "excluded_soft_deleted": excluded_deleted,
                "excluded_alias_duplicates": excluded_aliases,
                "eligible_after_filters": n,
            },
        }

    # Single-flight lock — one primary-image sweep at a time.
    if _BULK_IMAGE_LOCK.locked():
        in_flight = await db.backfill_jobs.find_one(
            {"kind": "bulk_primary_images", "status": "running"},
            sort=[("started_at", -1)],
        )
        if response is not None:
            response.status_code = 409
        return {
            "status": "already_running",
            "reason": "single_flight",
            "job_id": (in_flight or {}).get("_id"),
        }

    from server import new_id
    job_id = new_id()
    await _record_job(job_id, {
        "status": "queued",
        "kind": "bulk_primary_images",
        "coach_id": coach.get("id"),
    })
    _spawn_bg(_bulk_primary_image_worker(
        job_id, coach_id=coach.get("id"), persona=persona,
    ))
    if response is not None:
        response.status_code = 202
    return {
        "status": "queued",
        "job_id": job_id,
        # Poll via the SHARED backfill-status endpoint — same collection.
        "poll_url": f"/api/coach/auto-media-gen/backfill-status/{job_id}",
    }

