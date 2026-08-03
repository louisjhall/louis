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


async def auto_enqueue_media_for_exercise(
    ex_id: str, *, triggered_by: Optional[str] = None,
) -> dict:
    """Kick off auto-generation for one exercise. Returns a summary dict.

    Fires and forgets — the actual LLM calls run in background tasks.
    Safe to call repeatedly; slots already populated are skipped.

    `triggered_by` is a user id (coach) for the audit log, when the
    creation is directly attributable. If None we use the system marker.
    """
    if not AUTO_MEDIA_GEN_ENABLED:
        return {"skipped": True, "reason": "AUTO_MEDIA_GEN disabled"}

    ex = await db.exercises_v2.find_one({"id": ex_id})
    if not ex:
        return {"skipped": True, "reason": "exercise not found"}

    # Do NOT run against fully-approved exercises — respect coach's finished work.
    if ex.get("approval_status") == "approved" and ex.get("approved_image_status") == "Approved":
        return {"skipped": True, "reason": "already approved"}

    creator = triggered_by or _AUTO_USER_ID
    queued_images: list[str] = []
    queued_content: list[str] = []

    # ---- Images (only for slots that are still empty) ----
    try:
        from feature_exercise_content import (
            _build_ex_prompt, _run_image_job, _resolve_persona,
            _slot_map_field_for_persona,
        )
        persona = _resolve_persona(None, False)  # default male-louis frame
        slot_map_field = _slot_map_field_for_persona(persona)

        legacy_key_by_slot = {
            "primary": "primary_image_id",
            "start":   "demo_start_image_id",
            "end":     "demo_end_image_id",
        }
        set_updates: dict = {}
        for slot in _AUTO_SLOTS:
            legacy_key = legacy_key_by_slot[slot]
            # Skip if already populated (via legacy or persona map).
            if ex.get(legacy_key):
                continue
            slot_map = ex.get(slot_map_field) or {}
            if slot_map.get(slot):
                continue

            image_id = new_id()
            prompt = _build_ex_prompt(ex, slot, None, persona=persona)
            await db.exercise_content_images.insert_one({
                "id": image_id, "exercise_id": ex_id, "slot": slot,
                "requested_slot": slot,
                "gender": "male",
                "persona": persona,
                "prompt": prompt, "status": "generating",
                "storage_path": None, "size_bytes": None, "mime": None,
                "created_by": creator, "auto": True,
                "created_at": now_iso(), "updated_at": now_iso(),
            })
            set_updates[f"{slot_map_field}.{slot}"] = image_id
            set_updates[legacy_key] = image_id
            queued_images.append(slot)
            asyncio.create_task(_run_image_job(image_id, prompt, use_louis_ref=True))

        if set_updates:
            set_updates["approved_image_status"] = "Needs Review"
            set_updates["content_status.images"] = True
            set_updates["updated_at"] = now_iso()
            await db.exercises_v2.update_one({"id": ex_id}, {"$set": set_updates})
    except Exception as e:
        logger.warning(f"auto_media_gen: image queue failed for {ex_id}: {e}")

    # ---- Coaching points (only if empty) ----
    try:
        if not (ex.get("coaching_points") or []):
            asyncio.create_task(_auto_generate_coaching_points(ex_id))
            queued_content.append("coaching_points")
    except Exception as e:
        logger.warning(f"auto_media_gen: content queue failed for {ex_id}: {e}")

    if queued_images or queued_content:
        try:
            from feature_exercise_content import _log
            await _log(
                ex_id, creator, "auto_media_gen_enqueued",
                f"images={','.join(queued_images) or '-'} content={','.join(queued_content) or '-'}",
            )
        except Exception:
            pass

    return {
        "skipped": False,
        "queued_images": queued_images,
        "queued_content": queued_content,
    }


async def _auto_generate_coaching_points(ex_id: str) -> None:
    """Background — generate a coaching-points draft via Claude.

    Mirrors the manual /exercise-content/{id}/generate-content endpoint
    but runs without a coach in the loop. Never raises.
    """
    try:
        ex = await db.exercises_v2.find_one({"id": ex_id})
        if not ex:
            return
        if ex.get("coaching_points"):
            return  # coach already added them; do nothing

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
        prompt = (
            f"Exercise: {name}\nEquipment: {equipment}\nBody area: {body_area}\n"
            f"Difficulty: {difficulty}\n\n"
            "Return 4–6 short concise coaching points (imperative, one line each). "
            "Focus on technique cues an aviation-crew client can execute in a "
            "hotel gym.\n\n"
            'OUTPUT: strict JSON {"items": ["string", ...]}. No prose outside the JSON.'
        )

        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"auto-content-{ex_id}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-4-5-20250929").with_params(max_tokens=500)
        reply = await chat.send_message(UserMessage(text=prompt))

        text = str(reply or "").strip()
        items: list[str] = []
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                parsed = json.loads(m.group(0))
                if isinstance(parsed.get("items"), list):
                    items = [str(i).strip() for i in parsed["items"] if str(i).strip()][:6]
            except Exception:
                pass
        if not items and text:
            items = [ln.lstrip("-• 0123456789.").strip() for ln in text.splitlines() if ln.strip()][:6]

        if items:
            await db.exercises_v2.update_one(
                {"id": ex_id},
                {"$set": {
                    "coaching_points": items,
                    "content_status.coaching_points": True,
                    "updated_at": now_iso(),
                }},
            )
            try:
                from feature_exercise_content import _log
                await _log(ex_id, _AUTO_USER_ID, "auto_coaching_points",
                           f"generated {len(items)} points")
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"auto_media_gen: coaching-points generation failed for {ex_id}: {e}")


# ---------------------------------------------------------------------------
# Public — small admin endpoint to toggle / inspect the flag
# ---------------------------------------------------------------------------
from fastapi import Depends
from server import api, require_role


@api.get("/coach/auto-media-gen/status")
async def auto_media_gen_status(_: dict = Depends(require_role("coach"))):
    return {
        "enabled": AUTO_MEDIA_GEN_ENABLED,
        "default_slots": list(_AUTO_SLOTS),
        "note": "Toggle via AUTO_MEDIA_GEN env var. Coach still has to approve.",
    }


@api.post("/coach/exercises/{ex_id}/auto-generate")
async def auto_media_gen_manual_trigger(
    ex_id: str, coach: dict = Depends(require_role("coach")),
):
    """Explicit trigger — the coach can also force a re-queue if the
    background job never fired (e.g. AUTO_MEDIA_GEN was off at creation)."""
    return await auto_enqueue_media_for_exercise(ex_id, triggered_by=coach.get("id"))


logger.info(
    f"feature_auto_media_gen: enabled={AUTO_MEDIA_GEN_ENABLED} "
    f"slots={_AUTO_SLOTS}"
)
