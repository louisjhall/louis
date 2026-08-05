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
# Per-kind toggles — coach flips at runtime without a redeploy.
# ---------------------------------------------------------------------------

# All kinds we know about. Each maps to a friendly label the coach sees.
_KIND_LABELS: dict[str, str] = {
    "images":          "Images (Nano Banana × 3 slots)",
    "coaching_points": "Coaching points (Louis-voice)",
    "common_mistakes": "Common mistakes",
    "alternatives":    "Alternative exercises (+ library drafts)",
    "instructions":    "Client-facing instructions",
}

# Env-var overrides (checked last as a hard kill-switch — flipping any of
# these to "false" beats the DB toggle so cost blow-outs can be stopped
# via an env change even if the DB is unreachable).
_KIND_ENV_OFF = {
    "images":          str(os.environ.get("AUTO_MEDIA_GEN_IMAGES", "true")).lower()          not in ("1", "true", "yes", "on"),
    "coaching_points": str(os.environ.get("AUTO_MEDIA_GEN_COACHING", "true")).lower()        not in ("1", "true", "yes", "on"),
    "common_mistakes": str(os.environ.get("AUTO_MEDIA_GEN_MISTAKES", "true")).lower()        not in ("1", "true", "yes", "on"),
    "alternatives":    str(os.environ.get("AUTO_MEDIA_GEN_ALTERNATIVES", "true")).lower()    not in ("1", "true", "yes", "on"),
    "instructions":    str(os.environ.get("AUTO_MEDIA_GEN_INSTRUCTIONS", "true")).lower()    not in ("1", "true", "yes", "on"),
}

_SETTINGS_DOC_ID = "auto_media_gen"


async def _load_kind_toggles() -> dict:
    """Return {kind: bool} — merge of DB settings (source of truth) and
    env-var kill switches (env-false ALWAYS wins). Falls back to all-on
    when the DB doc is missing so behaviour matches the previous version."""
    defaults = {k: True for k in _KIND_LABELS}
    try:
        doc = await db.settings.find_one({"_id": _SETTINGS_DOC_ID}) or {}
    except Exception as e:
        logger.warning(f"auto_media_gen: settings load failed ({e}), using defaults")
        doc = {}
    toggles: dict[str, bool] = {}
    for k in _KIND_LABELS:
        val = doc.get(k) if k in doc else defaults[k]
        if not isinstance(val, bool):
            val = defaults[k]
        # Env kill-switch wins
        if _KIND_ENV_OFF.get(k):
            val = False
        toggles[k] = val
    return toggles


async def _kind_enabled(kind: str) -> bool:
    return (await _load_kind_toggles()).get(kind, True)



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
    skipped_by_toggle: list[str] = []

    toggles = await _load_kind_toggles()

    # ---- Images (only for slots that are still empty) ----
    if not toggles.get("images", True):
        skipped_by_toggle.append("images")
    else:
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
            asyncio.create_task(_auto_generate_content(ex_id, kind, creator))
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
        "Return 3–5 alternative exercises that train the same movement "
        "pattern, ordered by similarity. Only the exercise names, no "
        "explanation."
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
    return {
        "enabled": AUTO_MEDIA_GEN_ENABLED,
        "default_slots": list(_AUTO_SLOTS),
        "auto_content_kinds": ["coaching_points", "common_mistakes",
                                "alternatives", "instructions"],
        "toggles": toggles,
        "labels": _KIND_LABELS,
        "env_kill_switches": {k: v for k, v in _KIND_ENV_OFF.items() if v},
        "note": "Toggle per kind via PATCH /coach/auto-media-gen/settings. Env var *_OFF still wins.",
    }


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
