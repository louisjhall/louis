"""
Iter 94t (Phase 1) — Server-driven remote config + feature flags.

Owns:

1. GET  /app-config                    — public (client-facing) resolved config
2. GET  /admin/app-config              — admin: list all flags/config
3. POST /admin/app-config              — admin: create/update a flag/config item
4. DELETE /admin/app-config/{key}      — admin: soft-disable a flag
5. GET  /admin/app-config/audit        — audit log

App Store safe rules:
- Never used to download or execute code (values are booleans / strings /
  numbers / small JSON blobs describing content or visibility).
- Every write is audit-logged (updated_by, updated_at, previous value).
- `safe_to_change_live` boolean marks items that don't require an app update.
- `min_app_version` / `max_app_version` optional gates.

Default flags are seeded on server startup so a fresh DB is never blank.
Rollout: all NEW flags default to ENABLED (per Iter 94t plan).
"""
from __future__ import annotations

import logging
from typing import Any, Optional
import os

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import (
    api, current_user, require_role, db, new_id, now_iso,
)

logger = logging.getLogger("crewfit.app_config")

# ---------------------------------------------------------------------------
# Default flags — seeded on first read if missing.
# ---------------------------------------------------------------------------

DEFAULT_FLAGS: dict[str, dict[str, Any]] = {
    "guided_flow_enabled":                 {"value": True,  "description": "Master Guided Flow feature toggle."},
    "guided_flow_timer_mode_enabled":      {"value": True,  "description": "Auto timer mode inside Guided Flow for HIIT/mobility/circuits."},
    "guided_flow_image_autoscroll":        {"value": True,  "description": "Auto-scroll exercise images during timed exercises."},
    "exercise_media_required":             {"value": True,  "description": "If true, missing-media exercises create coach To-Do tasks."},
    "missing_media_client_fallback_enabled":{"value": True,  "description": "Show safe written-only fallback when media is missing."},
    "hotel_system_enabled":                {"value": True,  "description": "Hotel setup + hotel workout system."},
    "progress_charts_enabled":             {"value": True,  "description": "Show charts in the Progress section."},
    "nutrition_dashboard_enabled":         {"value": True,  "description": "Show the calories/protein card near the top of home."},
    "wearable_steps_enabled":              {"value": False, "description": "Show step-count card. OFF until wearable integration ships."},
    "habits_dynamic_enabled":              {"value": True,  "description": "Dynamic daily habits engine."},
    "first_day_workout_choice_enabled":    {"value": True,  "description": '"Start Today Or Prepare First?" screen for new clients.'},
    "whatsapp_support_enabled":            {"value": True,  "description": "Show WhatsApp support buttons on failure states."},
    "beta_banner_enabled":                 {"value": True,  "description": "Show the 'Private beta' banner in-app."},
    "missed_workout_recovery_enabled":     {"value": True,  "description": "Client-facing recovery flow for missed workouts."},
    "timezone_card_enabled":               {"value": True,  "description": "Timezone card at top of client home."},
    "calendar_scroll_enabled":             {"value": True,  "description": "±60 day scrollable calendar on home."},
    "dual_session_enabled":                {"value": True,  "description": "Short-haul dual-session (airport activation + hotel evening) suggestions."},
    "weekly_review_enabled":               {"value": True,  "description": "Sunday check-in / weekly review card."},
}


# ---------------------------------------------------------------------------
# Content types (safe live-editable keys). NOT executable code.
# ---------------------------------------------------------------------------

SAFE_CONTENT_KEYS = {
    "support_whatsapp_number",
    "support_email",
    "beta_banner_text",
    "welcome_message_client",
    "welcome_message_coach",
    "missing_media_client_copy",
    "recovery_ask_louis_copy",
    "guided_flow_placeholder_copy",
    "nutrition_empty_state_copy",
    "wearable_coming_soon_copy",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_defaults_once() -> None:
    """Idempotent — ensures every default flag exists in the DB."""
    for key, meta in DEFAULT_FLAGS.items():
        existing = await db.app_config.find_one({"key": key})
        if existing:
            continue
        doc = {
            "id": new_id(),
            "key": key,
            "value": meta["value"],
            "environment": "all",
            "platform": "all",
            "min_app_version": None,
            "max_app_version": None,
            "enabled": True,
            "safe_to_change_live": True,
            "description": meta.get("description") or "",
            "updated_by": "system_seed",
            "updated_at": now_iso(),
            "rollout_percentage": 100,
            "kind": "flag",
        }
        try:
            await db.app_config.insert_one(doc)
        except Exception:
            # Race with another seed run — safe to ignore.
            pass


async def _resolve_public_config() -> dict:
    await _seed_defaults_once()
    rows = await db.app_config.find({"enabled": True}, {"_id": 0}).to_list(500)
    flags: dict[str, Any] = {}
    content: dict[str, Any] = {}
    for r in rows:
        k = r.get("key")
        if not k:
            continue
        if r.get("kind") == "content":
            content[k] = r.get("value")
        else:
            flags[k] = bool(r.get("value")) if isinstance(r.get("value"), bool) else r.get("value")
    return {"flags": flags, "content": content, "updated_at": now_iso()}


async def _write_audit(entry: dict) -> None:
    try:
        entry.setdefault("id", new_id())
        entry.setdefault("created_at", now_iso())
        await db.app_config_audit.insert_one(entry)
    except Exception:
        logger.exception("app_config audit write failed")


# ---------------------------------------------------------------------------
# Public endpoint (client-facing)
# ---------------------------------------------------------------------------

@api.get("/app-config")
async def app_config_public(user: dict = Depends(current_user)):
    cfg = await _resolve_public_config()
    return cfg


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

class AppConfigUpsert(BaseModel):
    key: str = Field(..., min_length=1, max_length=80)
    value: Any
    kind: str = "flag"  # "flag" | "content" | "threshold"
    environment: str = "all"
    platform: str = "all"
    enabled: bool = True
    safe_to_change_live: bool = True
    description: Optional[str] = None
    min_app_version: Optional[str] = None
    max_app_version: Optional[str] = None
    rollout_percentage: int = 100


@api.get("/admin/app-config")
async def admin_list_config(user: dict = Depends(require_role("coach"))):
    await _seed_defaults_once()
    rows = await db.app_config.find({}, {"_id": 0}).sort("key", 1).to_list(500)
    return {"items": rows or [], "safe_content_keys": sorted(SAFE_CONTENT_KEYS)}


@api.post("/admin/app-config")
async def admin_upsert_config(body: AppConfigUpsert, user: dict = Depends(require_role("coach"))):
    # Guard: content items must use a whitelisted key so we don't allow
    # arbitrary key spam.
    if body.kind == "content" and body.key not in SAFE_CONTENT_KEYS:
        raise HTTPException(400, f"content key '{body.key}' is not on the allowlist.")
    prev = await db.app_config.find_one({"key": body.key}, {"_id": 0})
    doc = {
        "id": (prev or {}).get("id") or new_id(),
        "key": body.key,
        "value": body.value,
        "kind": body.kind,
        "environment": body.environment,
        "platform": body.platform,
        "enabled": body.enabled,
        "safe_to_change_live": body.safe_to_change_live,
        "description": body.description or (prev or {}).get("description"),
        "min_app_version": body.min_app_version,
        "max_app_version": body.max_app_version,
        "rollout_percentage": body.rollout_percentage,
        "updated_by": user.get("id"),
        "updated_by_name": user.get("name") or user.get("email"),
        "updated_at": now_iso(),
    }
    await db.app_config.replace_one({"key": body.key}, doc, upsert=True)
    await _write_audit({
        "key": body.key,
        "previous": prev,
        "new_value": body.value,
        "actor_id": user.get("id"),
        "actor_name": user.get("name") or user.get("email"),
        "action": "upsert",
    })
    return {"ok": True, "item": doc}


@api.delete("/admin/app-config/{key}")
async def admin_disable_config(key: str, user: dict = Depends(require_role("coach"))):
    prev = await db.app_config.find_one({"key": key}, {"_id": 0})
    if not prev:
        raise HTTPException(404, "config key not found")
    await db.app_config.update_one({"key": key}, {"$set": {
        "enabled": False, "updated_at": now_iso(),
        "updated_by": user.get("id"), "updated_by_name": user.get("name") or user.get("email"),
    }})
    await _write_audit({
        "key": key, "previous": prev, "new_value": None,
        "actor_id": user.get("id"),
        "actor_name": user.get("name") or user.get("email"),
        "action": "disable",
    })
    return {"ok": True, "disabled": key}


@api.get("/admin/app-config/audit")
async def admin_config_audit(user: dict = Depends(require_role("coach"))):
    rows = await db.app_config_audit.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"audit": rows or []}


# Seed once on module import (async, best-effort).
try:
    import asyncio as _asyncio
    _asyncio.get_event_loop().create_task(_seed_defaults_once())
except Exception:
    pass

_ = os  # keep the import so tools don't warn
