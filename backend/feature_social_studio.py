"""
feature_social_studio — CrewFit Social Media Studio V1 (admin-only).

Endpoints:
  POST /social/generate                    — Atlas content idea + script + caption
  POST /social/posts                       — create post from a generated idea (or blank)
  GET  /social/posts                       — list posts (?status, ?platform, ?pillar, ?limit)
  GET  /social/posts/{id}                  — detail
  PATCH /social/posts/{id}                 — edit any field (also transitions status)
  POST /social/posts/{id}/regenerate       — regen with a tone/action (Shorter/Punchier/…/Regen hook)
  POST /social/posts/{id}/approve          — status → Approved
  POST /social/posts/{id}/schedule         — manual schedule (Buffer path deferred)
  POST /social/posts/{id}/mark-posted      — mark manually posted
  POST /social/posts/{id}/dismiss          — status → Dismissed
  GET  /social/analytics                   — counts by status / platform / pillar
  GET  /social/settings                    — daily task on/off + time + days + platforms + mix
  PUT  /social/settings                    — update settings
  POST /social/daily/generate              — force-create today's daily task (also auto-created by tick)
  POST /social/daily/regenerate            — replace today's suggestion (stash previous)

Content status machine:
  Idea → Draft → Approved → Scheduled → Posted
  Any → Dismissed / Archived / Failed
"""
from fastapi import Depends, HTTPException, UploadFile, File, Form, Query, Header, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Any, Optional
from pathlib import Path
import asyncio
import datetime as _dt
import json
import os
import random
import shutil

import jwt as _jwt

from server import (
    api, db, current_user, require_admin, new_id, now_iso, logger,
    call_claude, parse_json_from_text, _create_coach_task, _log_change,
    JWT_SECRET, JWT_ALGO,
)


# ---- Media storage --------------------------------------------------------

MEDIA_ROOT = Path(os.environ.get("SOCIAL_MEDIA_ROOT", "/app/backend/uploads/social_assets"))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 120 * 1024 * 1024   # 120 MB hard cap (~60s 1080p vertical)
ALLOWED_MIMES = {
    "video/mp4", "video/quicktime", "video/webm",
    "video/x-matroska", "video/mpeg", "video/3gpp",
    "audio/mpeg", "audio/wav",  # allow audio-only fallback if ever needed
}


def _asset_dir(post_id: str) -> Path:
    d = MEDIA_ROOT / post_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ext_for_mime(mime: str) -> str:
    return {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "video/x-matroska": ".mkv",
        "video/mpeg": ".mpeg",
        "video/3gpp": ".3gp",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
    }.get(mime, ".bin")


async def _admin_from_query_token(token: Optional[str]) -> dict:
    """Auth helper for <video> tag GET requests (which can't set Authorization header)."""
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except _jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Bad token: {e}")
    u = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if u.get("role") not in ("admin", "coach"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return u


# ---- Constants ------------------------------------------------------------

CONTENT_PILLARS = [
    "Roster-proof fitness",
    "Pilot and cabin crew fat loss",
    "Jet lag and recovery",
    "Hotel gym training",
    "Training around long-haul flying",
    "Strength and mobility for aviation",
    "Nutrition in airports and hotels",
    "Consistency without a perfect routine",
    "CrewFit app features",
    "Human-led coaching enhanced by Atlas",
    "Event training around flying",
    "Behind the scenes with Louis",
    "Common mistakes airline crew make",
    "Simple workouts for busy rosters",
    "Client wins and transformations",
]

PLATFORMS = ["LinkedIn", "Instagram", "TikTok", "Facebook", "YouTube Shorts", "X/Twitter"]

POST_TYPES = [
    "LinkedIn post", "Instagram caption", "Reel script", "TikTok hook",
    "short-form video script", "carousel idea", "carousel slide copy",
    "story post", "email-style post", "ad concept",
]

STATUSES = [
    "Idea", "Draft", "Script Ready", "Recording Needed", "Recorded",
    "Subtitles Generated", "Subtitle Review", "Approved", "Scheduled",
    "Sent to Buffer", "Posted", "Failed", "Archived", "Dismissed",
]

TONE_ACTIONS = {
    "shorter":       "Rewrite the post to be tighter — cut every word that does not earn its place.",
    "punchier":      "Rewrite with a sharper, more direct voice. Short sentences. Real edge.",
    "professional": "Rewrite in a more polished, LinkedIn-thought-leader tone (still direct, still human, never corporate).",
    "direct":       "Rewrite to be more direct. No filler. State the point in the first sentence.",
    "linkedin":     "Rewrite as a LinkedIn-native post: longer form, one clear takeaway, no hashtag spam, single-line paragraphs.",
    "tiktok":       "Rewrite as a TikTok-native hook + short script. High-hook first line. Under 30 seconds of voiceover.",
    "aviation":     "Add specific aviation examples (long-haul rest, layover jet lag, hotel gym constraints, roster gaps).",
    "cta":          "End with a CrewFit CTA that fits the platform. No cheesy hype.",
    "regen_hook":   "Regenerate ONLY the hook. Keep the rest of the post unchanged.",
    "regen_caption":"Regenerate ONLY the caption. Keep the rest unchanged.",
}


SOCIAL_SYSTEM = """You are Atlas, drafting social-media content in the voice of Louis Hall / CrewFit.

Voice: direct, practical, aviation-specific, confident, human. Never cheesy, never corporate,
never generic fitness-influencer. British English. Talk to pilots and cabin crew like a coach
who understands the roster.

AVOID: fake hype ("unlock your potential"), excessive emojis, hashtag spam, unrealistic claims,
medical claims, promising guaranteed results.

Anchor style examples:
  "Most pilots don't need a perfect training plan. They need a plan that survives the roster."
  "Hotel gyms are not the problem. The problem is trying to train like you have a normal week."
  "CrewFit builds training around the roster, not around an imaginary routine."

Return STRICT JSON only, matching the schema requested."""


DEFAULT_SETTINGS = {
    "daily_task_enabled": True,
    "daily_task_time_local": "09:00",
    "days": "every",                                # "every" | "weekdays" | "custom"
    "custom_days": [],                              # 0=Mon..6=Sun
    "default_platforms": ["LinkedIn", "Instagram", "TikTok"],
    "default_content_mix": [
        "education", "authority", "app_feature",
        "behind_the_scenes", "aviation_tip", "client_win",
    ],
}


# ---- Models ---------------------------------------------------------------

class GenerateBody(BaseModel):
    platform: Optional[str] = None
    audience: Optional[str] = None
    goal: Optional[str] = None
    topic: Optional[str] = None
    tone: Optional[str] = None
    post_type: Optional[str] = None
    length_seconds: Optional[int] = None
    cta: Optional[str] = None
    pillar: Optional[str] = None
    event: Optional[str] = None
    extra_instruction: Optional[str] = None

class PostCreateBody(BaseModel):
    title: str
    platform: str
    post_type: str
    content_pillar: Optional[str] = None
    audience: Optional[str] = None
    goal: Optional[str] = None
    hook: Optional[str] = None
    script: Optional[str] = None
    caption: Optional[str] = None
    hashtags: Optional[list[str]] = None
    cta: Optional[str] = None
    visual_notes: Optional[str] = None
    status: Optional[str] = "Draft"
    scheduled_local_datetime: Optional[str] = None
    scheduled_time_zone: Optional[str] = None

class PostPatchBody(BaseModel):
    title: Optional[str] = None
    platform: Optional[str] = None
    post_type: Optional[str] = None
    content_pillar: Optional[str] = None
    audience: Optional[str] = None
    goal: Optional[str] = None
    hook: Optional[str] = None
    script: Optional[str] = None
    caption: Optional[str] = None
    hashtags: Optional[list[str]] = None
    cta: Optional[str] = None
    visual_notes: Optional[str] = None
    status: Optional[str] = None
    scheduled_local_datetime: Optional[str] = None
    scheduled_time_zone: Optional[str] = None

class RegenerateBody(BaseModel):
    action: str                                       # one of TONE_ACTIONS keys
    extra_instruction: Optional[str] = None

class SocialSettingsBody(BaseModel):
    daily_task_enabled: Optional[bool] = None
    daily_task_time_local: Optional[str] = None
    days: Optional[str] = None
    custom_days: Optional[list[int]] = None
    default_platforms: Optional[list[str]] = None
    default_content_mix: Optional[list[str]] = None

class ScheduleBody(BaseModel):
    scheduled_local_datetime: str
    scheduled_time_zone: str
    channel_id: Optional[str] = None                  # placeholder for Buffer channel


# ---- Atlas generation -----------------------------------------------------

def _clean_doc(d: dict) -> dict:
    d.pop("_id", None)
    return d


async def _atlas_generate(ctx: dict) -> dict:
    """Ask Atlas to generate a full post. Returns strict-JSON dict with hook/script/caption/hashtags/etc."""
    schema_hint = (
        'Return strict JSON: {"title": str, "hook": str, "script": str, "teleprompter_script": str, '
        '"caption": str, "hashtags": [str, ...] (max 6), "cta": str, "visual_notes": str, '
        '"platform_recommendation": str, "post_type": str, "best_posting_time_local": str, '
        '"angle": str}'
    )
    prompt = f"Generate a CrewFit social post using this brief:\n\n{json.dumps(ctx, default=str, indent=2)}\n\n{schema_hint}"
    parsed: dict[str, Any] = {}
    try:
        raw = await call_claude(SOCIAL_SYSTEM, prompt, max_out=1400)
        parsed = parse_json_from_text(raw) or {}
    except Exception:
        logger.exception("Atlas social generation failed — using deterministic fallback")
    if not parsed.get("hook"):
        parsed = _fallback_post(ctx)
    parsed.setdefault("platform_recommendation", ctx.get("platform") or "LinkedIn")
    parsed.setdefault("post_type", ctx.get("post_type") or "LinkedIn post")
    return parsed


def _fallback_post(ctx: dict) -> dict:
    pillar = ctx.get("pillar") or "Roster-proof fitness"
    platform = ctx.get("platform") or "LinkedIn"
    hooks = {
        "Roster-proof fitness": "Most pilots don't need a perfect plan. They need one that survives the roster.",
        "Jet lag and recovery": "Jet lag isn't the enemy. Trying to train through it is.",
        "Hotel gym training":   "Hotel gyms aren't the problem. Trying to train like you have a normal week is.",
        "Nutrition in airports and hotels": "You can't out-discipline a roster that doesn't give you kitchen access.",
    }
    hook = hooks.get(pillar, f"CrewFit note — {pillar}.")
    return {
        "title": f"{pillar} · {platform}",
        "hook": hook,
        "script": f"{hook}\n\nHere's what actually works: build the week around the roster, not around a routine that doesn't exist yet.",
        "teleprompter_script": hook + " ... build the week around the roster, not around a routine that doesn't exist yet.",
        "caption": f"{hook}\n\nCrewFit builds training around the roster, not around an imaginary routine.",
        "hashtags": ["#pilotlife", "#cabincrew", "#aviationfitness", "#crewfit"],
        "cta": "If you want a plan that actually fits your roster, CrewFit is built for you.",
        "visual_notes": "Louis to camera. Wide shot. Add lower-third pillar tag.",
        "platform_recommendation": platform,
        "post_type": ctx.get("post_type") or ("Reel script" if platform in ("Instagram", "TikTok") else "LinkedIn post"),
        "best_posting_time_local": "09:00",
        "angle": f"{pillar} — direct and specific.",
    }


# ---- Post CRUD ------------------------------------------------------------

def _new_post_doc(admin_id: str, gen: dict, extra: Optional[dict] = None) -> dict:
    now = now_iso()
    doc = {
        "id": new_id(),
        "title": gen.get("title") or "Untitled post",
        "content_pillar": (extra or {}).get("content_pillar"),
        "platform": gen.get("platform_recommendation"),
        "post_type": gen.get("post_type"),
        "audience": (extra or {}).get("audience"),
        "goal": (extra or {}).get("goal"),
        "hook": gen.get("hook"),
        "script": gen.get("script"),
        "teleprompter_script": gen.get("teleprompter_script") or gen.get("script"),
        "caption": gen.get("caption"),
        "hashtags": gen.get("hashtags") or [],
        "cta": gen.get("cta"),
        "visual_notes": gen.get("visual_notes"),
        "best_posting_time_local": gen.get("best_posting_time_local"),
        "angle": gen.get("angle"),
        "media_id": None,
        "subtitle_id": None,
        "buffer_channel_id": None,
        "buffer_post_id": None,
        "scheduled_local_datetime": None,
        "scheduled_time_zone": None,
        "status": "Draft",
        "created_by": admin_id,
        "approved_by": None,
        "revision_history": [],                    # stash of previous versions
        "created_at": now,
        "updated_at": now,
        "approved_at": None,
        "sent_to_buffer_at": None,
        "posted_at": None,
        "failed_at": None,
        "error_message": None,
    }
    if extra:
        for k, v in extra.items():
            if v is not None and k in doc:
                doc[k] = v
    return doc


@api.post("/social/generate")
async def social_generate(body: GenerateBody, admin: dict = Depends(require_admin())):
    ctx = body.model_dump()
    if not ctx.get("pillar"):
        ctx["pillar"] = random.choice(CONTENT_PILLARS)
    gen = await _atlas_generate(ctx)
    return {"generated": gen, "context": ctx}


@api.post("/social/posts")
async def social_post_create(body: PostCreateBody, admin: dict = Depends(require_admin())):
    now = now_iso()
    doc = {
        "id": new_id(),
        "title": body.title,
        "content_pillar": body.content_pillar,
        "platform": body.platform,
        "post_type": body.post_type,
        "audience": body.audience,
        "goal": body.goal,
        "hook": body.hook,
        "script": body.script,
        "teleprompter_script": body.script,
        "caption": body.caption,
        "hashtags": body.hashtags or [],
        "cta": body.cta,
        "visual_notes": body.visual_notes,
        "status": body.status or "Draft",
        "created_by": admin["id"],
        "approved_by": None,
        "revision_history": [],
        "media_id": None,
        "subtitle_id": None,
        "buffer_channel_id": None,
        "buffer_post_id": None,
        "scheduled_local_datetime": body.scheduled_local_datetime,
        "scheduled_time_zone": body.scheduled_time_zone,
        "created_at": now,
        "updated_at": now,
        "approved_at": None,
        "sent_to_buffer_at": None,
        "posted_at": None,
        "failed_at": None,
        "error_message": None,
    }
    await db.social_posts.insert_one(doc)
    _clean_doc(doc)
    return {"post": doc}


@api.get("/social/posts")
async def social_posts_list(admin: dict = Depends(require_admin()),
                            status: Optional[str] = None, platform: Optional[str] = None,
                            pillar: Optional[str] = None, limit: int = 100):
    q: dict[str, Any] = {}
    if status:   q["status"] = status
    if platform: q["platform"] = platform
    if pillar:   q["content_pillar"] = pillar
    rows = await db.social_posts.find(q, {"_id": 0, "revision_history": 0}).sort("created_at", -1).to_list(limit)
    return {"posts": rows, "count": len(rows)}


@api.get("/social/posts/{post_id}")
async def social_post_get(post_id: str, admin: dict = Depends(require_admin())):
    doc = await db.social_posts.find_one({"id": post_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "post not found")
    return {"post": doc}


@api.patch("/social/posts/{post_id}")
async def social_post_patch(post_id: str, body: PostPatchBody, admin: dict = Depends(require_admin())):
    existing = await db.social_posts.find_one({"id": post_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "post not found")
    updates: dict[str, Any] = {"updated_at": now_iso()}
    for k, v in body.model_dump(exclude_none=True).items():
        updates[k] = v
    if body.status and body.status not in STATUSES:
        raise HTTPException(400, f"invalid status; must be one of {STATUSES}")
    await db.social_posts.update_one({"id": post_id}, {"$set": updates})
    saved = await db.social_posts.find_one({"id": post_id}, {"_id": 0})
    return {"post": saved}


@api.post("/social/posts/{post_id}/regenerate")
async def social_post_regenerate(post_id: str, body: RegenerateBody, admin: dict = Depends(require_admin())):
    if body.action not in TONE_ACTIONS:
        raise HTTPException(400, f"action must be one of {list(TONE_ACTIONS)}")
    existing = await db.social_posts.find_one({"id": post_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "post not found")
    ctx = {
        "current_post": {k: existing.get(k) for k in ("title", "hook", "script", "caption", "hashtags", "cta", "platform", "post_type", "content_pillar")},
        "regenerate_action": body.action,
        "instruction": TONE_ACTIONS[body.action] + (f"\n\n{body.extra_instruction}" if body.extra_instruction else ""),
        "platform": existing.get("platform"),
        "pillar": existing.get("content_pillar"),
    }
    gen = await _atlas_generate(ctx)
    # Preserve previous version
    history = existing.get("revision_history") or []
    history.append({
        "at": now_iso(),
        "action": body.action,
        "snapshot": {k: existing.get(k) for k in ("title", "hook", "script", "caption", "hashtags", "cta")},
    })
    # Apply per-action scope: regen_hook only replaces hook, regen_caption only caption
    updates: dict[str, Any] = {"updated_at": now_iso(), "revision_history": history[-10:]}
    if body.action == "regen_hook":
        updates["hook"] = gen.get("hook")
    elif body.action == "regen_caption":
        updates["caption"] = gen.get("caption")
    else:
        for k in ("title", "hook", "script", "caption", "hashtags", "cta", "visual_notes"):
            if gen.get(k):
                updates[k] = gen[k]
        updates["teleprompter_script"] = gen.get("teleprompter_script") or gen.get("script") or existing.get("teleprompter_script")
    await db.social_posts.update_one({"id": post_id}, {"$set": updates})
    saved = await db.social_posts.find_one({"id": post_id}, {"_id": 0})
    return {"post": saved, "generated": gen}


@api.post("/social/posts/{post_id}/approve")
async def social_post_approve(post_id: str, admin: dict = Depends(require_admin())):
    existing = await db.social_posts.find_one({"id": post_id})
    if not existing:
        raise HTTPException(404, "post not found")
    now = now_iso()
    await db.social_posts.update_one({"id": post_id}, {"$set": {
        "status": "Approved", "approved_by": admin["id"], "approved_at": now, "updated_at": now,
    }})
    return {"ok": True}


@api.post("/social/posts/{post_id}/schedule")
async def social_post_schedule(post_id: str, body: ScheduleBody, admin: dict = Depends(require_admin())):
    existing = await db.social_posts.find_one({"id": post_id})
    if not existing:
        raise HTTPException(404, "post not found")
    now = now_iso()
    await db.social_posts.update_one({"id": post_id}, {"$set": {
        "status": "Scheduled",
        "scheduled_local_datetime": body.scheduled_local_datetime,
        "scheduled_time_zone": body.scheduled_time_zone,
        "buffer_channel_id": body.channel_id,
        "updated_at": now,
    }})
    # Resolve related coach task
    await db.coach_tasks.update_many(
        {"payload.social_post_id": post_id, "status": {"$in": ["todo", "in_progress"]}},
        {"$set": {"status": "done", "completed_at": now}},
    )
    return {"ok": True}


@api.post("/social/posts/{post_id}/mark-posted")
async def social_post_mark_posted(post_id: str, admin: dict = Depends(require_admin())):
    now = now_iso()
    r = await db.social_posts.update_one({"id": post_id}, {"$set": {
        "status": "Posted", "posted_at": now, "updated_at": now,
    }})
    if r.matched_count == 0:
        raise HTTPException(404, "post not found")
    await db.coach_tasks.update_many(
        {"payload.social_post_id": post_id, "status": {"$in": ["todo", "in_progress"]}},
        {"$set": {"status": "done", "completed_at": now}},
    )
    return {"ok": True}


@api.post("/social/posts/{post_id}/dismiss")
async def social_post_dismiss(post_id: str, admin: dict = Depends(require_admin())):
    now = now_iso()
    r = await db.social_posts.update_one({"id": post_id}, {"$set": {
        "status": "Dismissed", "updated_at": now,
    }})
    if r.matched_count == 0:
        raise HTTPException(404, "post not found")
    await db.coach_tasks.update_many(
        {"payload.social_post_id": post_id, "status": {"$in": ["todo", "in_progress"]}},
        {"$set": {"status": "dismissed", "dismissed_at": now, "completed_at": now}},
    )
    return {"ok": True}


@api.get("/social/analytics")
async def social_analytics(admin: dict = Depends(require_admin())):
    pipeline_status = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
    pipeline_platform = [{"$group": {"_id": "$platform", "n": {"$sum": 1}}}]
    pipeline_pillar = [{"$group": {"_id": "$content_pillar", "n": {"$sum": 1}}}]
    async def _agg(p):
        return {r["_id"] or "unknown": r["n"] async for r in db.social_posts.aggregate(p)}
    return {
        "by_status": await _agg(pipeline_status),
        "by_platform": await _agg(pipeline_platform),
        "by_pillar": await _agg(pipeline_pillar),
        "counts": {
            "scheduled": await db.social_posts.count_documents({"status": "Scheduled"}),
            "posted":    await db.social_posts.count_documents({"status": "Posted"}),
            "failed":    await db.social_posts.count_documents({"status": "Failed"}),
            "draft":     await db.social_posts.count_documents({"status": "Draft"}),
        },
    }


# ---- Settings -------------------------------------------------------------

async def _get_settings() -> dict:
    doc = await db.social_settings.find_one({"id": "singleton"}, {"_id": 0}) or {}
    return {**DEFAULT_SETTINGS, **doc}


@api.get("/social/settings")
async def social_settings_get(admin: dict = Depends(require_admin())):
    return {"settings": await _get_settings(), "defaults": DEFAULT_SETTINGS,
            "pillars": CONTENT_PILLARS, "platforms": PLATFORMS, "post_types": POST_TYPES}


@api.put("/social/settings")
async def social_settings_put(body: SocialSettingsBody, admin: dict = Depends(require_admin())):
    updates = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "no updates")
    updates["updated_at"] = now_iso()
    await db.social_settings.update_one({"id": "singleton"}, {"$set": updates}, upsert=True)
    return {"settings": await _get_settings()}


# ---- Daily task -----------------------------------------------------------

def _pick_next_pillar(recent: list[dict]) -> str:
    """Rotate through pillars, avoiding the last 5."""
    recent_pillars = {p.get("content_pillar") for p in recent[:5]}
    for pillar in CONTENT_PILLARS:  # deterministic first-pass
        if pillar not in recent_pillars:
            return pillar
    return random.choice(CONTENT_PILLARS)


async def _create_daily_task(admin_id: str, target_date: str, force: bool = False) -> Optional[dict]:
    """Create today's daily social task + a Draft post seeded by Atlas."""
    # Idempotent: only one daily task per date
    existing_task = await db.coach_tasks.find_one({
        "task_type": "daily_social_media_post", "payload.for_date": target_date,
    }, {"_id": 0})
    if existing_task and not force:
        return existing_task
    settings = await _get_settings()
    recent = await db.social_posts.find({}, {"_id": 0, "content_pillar": 1}).sort("created_at", -1).to_list(20)
    pillar = _pick_next_pillar(recent)
    platforms = settings.get("default_platforms", ["LinkedIn", "Instagram", "TikTok"])
    platform = random.choice(platforms) if platforms else "LinkedIn"
    ctx = {"platform": platform, "pillar": pillar, "audience": "airline crew",
           "goal": "educate", "post_type": "Reel script" if platform in ("Instagram", "TikTok") else "LinkedIn post"}
    gen = await _atlas_generate(ctx)
    post = _new_post_doc(admin_id, gen, extra={"content_pillar": pillar, "audience": ctx["audience"], "goal": ctx["goal"]})
    await db.social_posts.insert_one(post)
    # Create the coach task
    admin_user = await db.users.find_one({"id": admin_id}, {"_id": 0, "name": 1, "email": 1, "id": 1, "current_time_zone": 1, "home_time_zone": 1})
    task_id = await _create_coach_task(
        admin_user or {"id": admin_id, "name": "Admin"},
        "daily_social_media_post",
        "Create today's social media post",
        (gen.get("hook") or "Atlas has prepared a CrewFit content idea for today.")[:200],
        priority="normal", category="other",
        payload={"social_post_id": post["id"], "for_date": target_date, "platform": platform, "pillar": pillar},
    )
    await _log_change(admin_id, None, "programme",
                      f"Daily social task created · {pillar} · {platform}",
                      (gen.get("hook") or "")[:180], actor="atlas",
                      meta={"task_id": task_id, "post_id": post["id"]})
    task = await db.coach_tasks.find_one({"id": task_id}, {"_id": 0})
    return task


@api.post("/social/daily/generate")
async def social_daily_generate(admin: dict = Depends(require_admin()), date: Optional[str] = None):
    target = date or _dt.date.today().isoformat()
    task = await _create_daily_task(admin["id"], target, force=False)
    return {"task": task}


@api.post("/social/daily/regenerate")
async def social_daily_regenerate(admin: dict = Depends(require_admin()), date: Optional[str] = None):
    target = date or _dt.date.today().isoformat()
    # Archive existing task's post (don't delete — keep revision history)
    task = await db.coach_tasks.find_one({"task_type": "daily_social_media_post", "payload.for_date": target})
    if task:
        old_post_id = (task.get("payload") or {}).get("social_post_id")
        if old_post_id:
            await db.social_posts.update_one({"id": old_post_id}, {"$set": {"status": "Archived", "updated_at": now_iso()}})
        await db.coach_tasks.update_one({"id": task["id"]}, {"$set": {"status": "dismissed", "dismissed_at": now_iso(), "completed_at": now_iso()}})
    new_task = await _create_daily_task(admin["id"], target, force=True)
    return {"task": new_task}


# ---- Ticker (called from server.py) ---------------------------------------

async def _tick_daily_social() -> None:
    """Runs from the reminder loop — creates the day's task at the admin's configured time."""
    settings = await _get_settings()
    if not settings.get("daily_task_enabled"):
        return
    # Find the first admin/coach user
    admin = await db.users.find_one({"role": {"$in": ["admin", "coach"]}}, {"_id": 0, "id": 1, "current_time_zone": 1, "home_time_zone": 1})
    if not admin:
        return
    now = _dt.datetime.utcnow()
    # Very light day-of-week filter
    days_mode = settings.get("days", "every")
    weekday = now.weekday()
    if days_mode == "weekdays" and weekday >= 5:
        return
    if days_mode == "custom" and weekday not in (settings.get("custom_days") or []):
        return
    # Idempotent creation for today
    target = _dt.date.today().isoformat()
    try:
        await _create_daily_task(admin["id"], target, force=False)
    except Exception:
        logger.exception("daily social task creation failed")


# ---- Recording Studio: media asset endpoints ------------------------------

@api.post("/social/posts/{post_id}/assets")
async def social_asset_upload(
    post_id: str,
    file: UploadFile = File(...),
    duration_seconds: Optional[float] = Form(None),
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    kind: str = Form("video"),           # "video" | "audio"
    label: Optional[str] = Form(None),
    admin: dict = Depends(require_admin()),
):
    """Upload a recorded video/audio draft for a Social Studio post.

    - Stores file on local disk under MEDIA_ROOT/<post_id>/<asset_id><ext>.
    - Persists metadata in `social_media_assets` collection.
    - Transitions post.status to 'Recorded' if it was <= 'Draft'/'Script Ready'.
    """
    post = await db.social_posts.find_one({"id": post_id}, {"_id": 0})
    if not post:
        raise HTTPException(404, "post not found")

    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIMES:
        raise HTTPException(400, f"unsupported content-type: {mime}")

    asset_id = new_id()
    ext = _ext_for_mime(mime)
    target_path = _asset_dir(post_id) / f"{asset_id}{ext}"

    total = 0
    try:
        with open(target_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)   # 1 MB chunks
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    out.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(413, "file exceeds 120MB limit")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception:
        logger.exception("social asset write failed")
        target_path.unlink(missing_ok=True)
        raise HTTPException(500, "failed to save asset")
    finally:
        await file.close()

    now = now_iso()
    doc = {
        "id": asset_id,
        "post_id": post_id,
        "kind": kind if kind in ("video", "audio") else "video",
        "label": label,
        "storage": "local",
        "file_path": str(target_path),
        "mime": mime,
        "extension": ext,
        "size_bytes": total,
        "duration_seconds": float(duration_seconds) if duration_seconds is not None else None,
        "width": width,
        "height": height,
        "status": "draft",             # draft | active | archived
        "subtitle_id": None,
        "created_by": admin["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.social_media_assets.insert_one(doc)
    doc.pop("_id", None)

    # Advance post status if still upstream
    upstream = {"Idea", "Draft", "Script Ready", "Recording Needed"}
    if post.get("status") in upstream:
        await db.social_posts.update_one(
            {"id": post_id},
            {"$set": {"status": "Recorded", "media_id": asset_id, "updated_at": now}},
        )
    else:
        await db.social_posts.update_one(
            {"id": post_id}, {"$set": {"media_id": asset_id, "updated_at": now}},
        )

    return {"asset": doc}


@api.get("/social/posts/{post_id}/assets")
async def social_asset_list(post_id: str, admin: dict = Depends(require_admin())):
    rows = await db.social_media_assets.find(
        {"post_id": post_id, "status": {"$ne": "archived"}},
        {"_id": 0, "file_path": 0},
    ).sort("created_at", -1).to_list(50)
    return {"assets": rows, "count": len(rows)}


@api.get("/social/assets/{asset_id}")
async def social_asset_get(asset_id: str, admin: dict = Depends(require_admin())):
    doc = await db.social_media_assets.find_one({"id": asset_id}, {"_id": 0, "file_path": 0})
    if not doc:
        raise HTTPException(404, "asset not found")
    return {"asset": doc}


@api.delete("/social/assets/{asset_id}")
async def social_asset_delete(asset_id: str, admin: dict = Depends(require_admin())):
    """Soft-archive an asset + delete the file from disk (used by Retake)."""
    doc = await db.social_media_assets.find_one({"id": asset_id})
    if not doc:
        raise HTTPException(404, "asset not found")
    path = doc.get("file_path")
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            logger.warning("failed to unlink asset file %s", path)
    await db.social_media_assets.update_one(
        {"id": asset_id},
        {"$set": {"status": "archived", "updated_at": now_iso(), "file_path": None}},
    )
    # If this was the post's primary media, unlink it
    await db.social_posts.update_many(
        {"media_id": asset_id},
        {"$set": {"media_id": None, "updated_at": now_iso()}},
    )
    return {"ok": True}


@api.get("/social/assets/{asset_id}/stream")
async def social_asset_stream(
    asset_id: str,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Serve the raw media file. Accepts either Authorization: Bearer <t> OR ?token=<t>
    query param so an HTML5 <video> element (which can't set custom headers) can play it."""
    if authorization and authorization.startswith("Bearer "):
        # Standard header-based auth
        u = await current_user(authorization=authorization)
        if u.get("role") not in ("admin", "coach"):
            raise HTTPException(403, "admin role required")
    else:
        await _admin_from_query_token(token)

    doc = await db.social_media_assets.find_one({"id": asset_id})
    if not doc:
        raise HTTPException(404, "asset not found")
    path = doc.get("file_path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "asset file missing")
    return FileResponse(path, media_type=doc.get("mime") or "application/octet-stream")


# ---- Whisper-1 subtitle pipeline ------------------------------------------

BURN_ROOT = MEDIA_ROOT   # burned files live alongside originals


def _fmt_ts(seconds: float, vtt: bool = False) -> str:
    if seconds is None or seconds < 0: seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000: ms, s = 0, s + 1
    sep = "." if vtt else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _segments_to_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_fmt_ts(seg.get('start', 0.0))} --> {_fmt_ts(seg.get('end', 0.0))}")
        lines.append((seg.get("text") or "").strip())
        lines.append("")
    return "\n".join(lines)


def _segments_to_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_fmt_ts(seg.get('start', 0.0), vtt=True)} --> {_fmt_ts(seg.get('end', 0.0), vtt=True)}")
        lines.append((seg.get("text") or "").strip())
        lines.append("")
    return "\n".join(lines)


async def _run_cmd(*args: str, timeout: int = 300) -> tuple[int, bytes, bytes]:
    """Run a subprocess without blocking the event loop."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(504, f"ffmpeg timed out after {timeout}s")
    return proc.returncode or 0, out, err


async def _extract_audio_mp3(video_path: Path, out_path: Path) -> None:
    """Extract compressed mono 64k mp3 to stay well under the 25MB Whisper cap."""
    code, _out, err = await _run_cmd(
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k",
        str(out_path),
        timeout=180,
    )
    if code != 0:
        raise HTTPException(500, f"audio extraction failed: {err.decode(errors='ignore')[-300:]}")


async def _burn_subtitles(video_path: Path, srt_path: Path, out_path: Path,
                          style: Optional[dict] = None) -> None:
    """Burn hard-subs onto the video using ffmpeg subtitles filter.

    Uses libx264/aac for broad Buffer/TikTok/LinkedIn compatibility.
    """
    # Escape SRT path for ffmpeg subtitles filter (colon + backslash sensitive)
    esc = str(srt_path).replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
    force_style = None
    if style:
        force_style = (
            f"Fontsize={int(style.get('font_size', 22))},"
            f"PrimaryColour=&H{style.get('primary_hex', 'FFFFFF')}&,"
            f"OutlineColour=&H{style.get('outline_hex', '000000')}&,"
            f"BorderStyle=1,Outline={int(style.get('outline', 2))},"
            f"Shadow=0,Alignment=2,MarginV={int(style.get('margin_v', 60))},"
            f"Bold={int(style.get('bold', 1))}"
        )
    vf = f"subtitles='{esc}'"
    if force_style:
        vf += f":force_style='{force_style}'"
    code, _out, err = await _run_cmd(
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
        timeout=900,
    )
    if code != 0:
        raise HTTPException(500, f"subtitle burn-in failed: {err.decode(errors='ignore')[-300:]}")


# Emergent LLM key (loaded from server module)
try:
    from server import EMERGENT_LLM_KEY as _EMERGENT_KEY
except Exception:
    _EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY", "")


async def _whisper_transcribe(audio_path: Path) -> dict:
    """Call whisper-1 via emergentintegrations and return {language, segments[], text}."""
    from emergentintegrations.llm.openai import OpenAISpeechToText
    stt = OpenAISpeechToText(api_key=_EMERGENT_KEY)
    # LiteLLM expects a file-like object, NOT a path string.
    with open(audio_path, "rb") as fh:
        resp = await stt.transcribe(
            file=fh,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    # LiteLLM/Whisper returns either a dict or an object with attrs
    def _get(obj, key, default=None):
        if isinstance(obj, dict): return obj.get(key, default)
        return getattr(obj, key, default)

    raw_segs = _get(resp, "segments", []) or []
    segments = []
    for i, s in enumerate(raw_segs):
        segments.append({
            "index": i,
            "start": float(_get(s, "start", 0.0) or 0.0),
            "end":   float(_get(s, "end", 0.0) or 0.0),
            "text":  (_get(s, "text", "") or "").strip(),
        })
    return {
        "language": _get(resp, "language", "en") or "en",
        "duration": float(_get(resp, "duration", 0.0) or 0.0),
        "text":     _get(resp, "text", "") or "",
        "segments": segments,
    }


DEFAULT_SUB_STYLE = {
    "primary_hex": "FFFFFF",     # ffmpeg ASS uses BBGGRR
    "outline_hex": "000000",
    "font_size": 22,
    "outline": 2,
    "margin_v": 90,
    "bold": 1,
}


async def _run_subtitle_job(subtitle_id: str) -> None:
    """Background worker: extract audio → whisper → write srt/vtt → done."""
    doc = await db.social_subtitles.find_one({"id": subtitle_id})
    if not doc:
        return
    asset = await db.social_media_assets.find_one({"id": doc["asset_id"]})
    if not asset or not asset.get("file_path"):
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "failed", "error": "asset missing", "updated_at": now_iso()}})
        return
    video_path = Path(asset["file_path"])
    if not video_path.exists():
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "failed", "error": "video file missing", "updated_at": now_iso()}})
        return

    audio_path = video_path.with_suffix(".mp3")
    try:
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "generating", "updated_at": now_iso()}})
        await _extract_audio_mp3(video_path, audio_path)
        result = await _whisper_transcribe(audio_path)
        srt = _segments_to_srt(result["segments"])
        vtt = _segments_to_vtt(result["segments"])
        srt_path = video_path.with_suffix(".srt")
        vtt_path = video_path.with_suffix(".vtt")
        srt_path.write_text(srt, encoding="utf-8")
        vtt_path.write_text(vtt, encoding="utf-8")
        await db.social_subtitles.update_one(
            {"id": subtitle_id},
            {"$set": {
                "status": "ready",
                "language": result["language"],
                "duration": result["duration"],
                "text": result["text"],
                "segments": result["segments"],
                "srt": srt,
                "vtt": vtt,
                "srt_path": str(srt_path),
                "vtt_path": str(vtt_path),
                "updated_at": now_iso(),
            }},
        )
    except HTTPException as he:
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "failed", "error": he.detail, "updated_at": now_iso()}})
    except Exception as e:
        logger.exception("subtitle job failed")
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "failed", "error": str(e)[:400], "updated_at": now_iso()}})
    finally:
        try: audio_path.unlink(missing_ok=True)
        except Exception: pass


class SubtitleGenerateBody(BaseModel):
    language: Optional[str] = None       # ISO-639-1 hint; whisper autodetects if None
    prompt: Optional[str] = None         # domain glossary hint (aviation, crew, roster…)


@api.post("/social/assets/{asset_id}/subtitles/generate")
async def social_subtitle_generate(asset_id: str,
                                   body: SubtitleGenerateBody = SubtitleGenerateBody(),
                                   admin: dict = Depends(require_admin())):
    """Kick off a real Whisper-1 transcription job (background)."""
    asset = await db.social_media_assets.find_one({"id": asset_id}, {"_id": 0})
    if not asset:
        raise HTTPException(404, "asset not found")
    # Reuse a still-pending job if it exists
    prior = await db.social_subtitles.find_one({"asset_id": asset_id, "status": {"$in": ["pending", "generating"]}})
    if prior:
        prior.pop("_id", None)
        return {"subtitle": prior, "note": "job already in progress"}

    sub_id = new_id()
    now = now_iso()
    doc = {
        "id": sub_id,
        "asset_id": asset_id,
        "post_id": asset.get("post_id"),
        "status": "pending",
        "provider": "whisper-1",
        "language": body.language or "en",
        "prompt": body.prompt,
        "srt": None, "vtt": None, "segments": [], "text": None,
        "burned_video_path": None,
        "burned_at": None,
        "created_by": admin["id"],
        "created_at": now,
        "updated_at": now,
    }
    await db.social_subtitles.insert_one(doc)
    await db.social_media_assets.update_one({"id": asset_id},
        {"$set": {"subtitle_id": sub_id, "updated_at": now}})
    # Fire and forget
    asyncio.create_task(_run_subtitle_job(sub_id))
    doc.pop("_id", None)
    return {"subtitle": doc, "note": "Whisper-1 job queued. Poll GET /social/subtitles/{id} for status."}


@api.get("/social/assets/{asset_id}/subtitles")
async def social_subtitle_get_by_asset(asset_id: str, admin: dict = Depends(require_admin())):
    """Latest subtitle doc for an asset (used by the subtitle editor screen)."""
    doc = await db.social_subtitles.find_one({"asset_id": asset_id}, {"_id": 0}, sort=[("created_at", -1)])
    return {"subtitle": doc}


@api.get("/social/subtitles/{subtitle_id}")
async def social_subtitle_get_by_id(subtitle_id: str, admin: dict = Depends(require_admin())):
    doc = await db.social_subtitles.find_one({"id": subtitle_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "subtitle not found")
    return {"subtitle": doc}


class SegmentBody(BaseModel):
    index: int
    start: float
    end: float
    text: str


class SubtitlePatchBody(BaseModel):
    segments: list[SegmentBody]


@api.patch("/social/subtitles/{subtitle_id}")
async def social_subtitle_patch(subtitle_id: str, body: SubtitlePatchBody,
                                admin: dict = Depends(require_admin())):
    """Save edited segment text/timing. Rebuilds SRT + VTT."""
    doc = await db.social_subtitles.find_one({"id": subtitle_id})
    if not doc:
        raise HTTPException(404, "subtitle not found")
    if doc.get("status") not in ("ready", "edited"):
        raise HTTPException(400, "subtitle not ready for editing")
    segs = [s.model_dump() for s in body.segments]
    srt = _segments_to_srt(segs)
    vtt = _segments_to_vtt(segs)
    # Write side files
    if doc.get("srt_path"):
        try: Path(doc["srt_path"]).write_text(srt, encoding="utf-8")
        except Exception: pass
    if doc.get("vtt_path"):
        try: Path(doc["vtt_path"]).write_text(vtt, encoding="utf-8")
        except Exception: pass
    await db.social_subtitles.update_one({"id": subtitle_id},
        {"$set": {"segments": segs, "srt": srt, "vtt": vtt,
                  "status": "edited", "updated_at": now_iso(),
                  "burned_video_path": None, "burned_at": None}})    # invalidate any old burn
    saved = await db.social_subtitles.find_one({"id": subtitle_id}, {"_id": 0})
    return {"subtitle": saved}


@api.get("/social/subtitles/{subtitle_id}/download")
async def social_subtitle_download(subtitle_id: str, fmt: str = "srt",
                                   token: Optional[str] = None,
                                   authorization: Optional[str] = Header(None)):
    """Download the SRT or VTT file. Accepts header OR query token auth."""
    if authorization and authorization.startswith("Bearer "):
        u = await current_user(authorization=authorization)
        if u.get("role") not in ("admin", "coach"):
            raise HTTPException(403, "admin role required")
    else:
        await _admin_from_query_token(token)
    doc = await db.social_subtitles.find_one({"id": subtitle_id})
    if not doc:
        raise HTTPException(404, "subtitle not found")
    if fmt not in ("srt", "vtt"):
        raise HTTPException(400, "fmt must be srt or vtt")
    content = (doc.get(fmt) or "").encode("utf-8")
    if not content:
        raise HTTPException(404, "no captions yet")
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="application/x-subrip" if fmt == "srt" else "text/vtt",
        headers={"Content-Disposition": f'attachment; filename="{subtitle_id}.{fmt}"'},
    )


class BurnBody(BaseModel):
    style: Optional[dict] = None            # override DEFAULT_SUB_STYLE fields


async def _run_burn_job(subtitle_id: str, style: Optional[dict]) -> None:
    doc = await db.social_subtitles.find_one({"id": subtitle_id})
    if not doc: return
    asset = await db.social_media_assets.find_one({"id": doc["asset_id"]})
    if not asset or not asset.get("file_path"): return
    video_path = Path(asset["file_path"])
    srt_path = Path(doc.get("srt_path") or (video_path.with_suffix(".srt")))
    if not srt_path.exists():
        # Regenerate SRT on the fly from the DB copy
        try: srt_path.write_text(doc.get("srt") or "", encoding="utf-8")
        except Exception: pass
    burned_path = video_path.with_name(f"{video_path.stem}_subtitled.mp4")
    try:
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "burning", "updated_at": now_iso()}})
        merged_style = {**DEFAULT_SUB_STYLE, **(style or {})}
        await _burn_subtitles(video_path, srt_path, burned_path, style=merged_style)
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {
                "status": "ready",
                "burned_video_path": str(burned_path),
                "burned_at": now_iso(),
                "burn_style": merged_style,
                "updated_at": now_iso(),
            }})
    except HTTPException as he:
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "burn_failed", "error": he.detail, "updated_at": now_iso()}})
    except Exception as e:
        logger.exception("burn job failed")
        await db.social_subtitles.update_one({"id": subtitle_id},
            {"$set": {"status": "burn_failed", "error": str(e)[:400], "updated_at": now_iso()}})


@api.post("/social/subtitles/{subtitle_id}/burn")
async def social_subtitle_burn(subtitle_id: str, body: BurnBody = BurnBody(),
                               admin: dict = Depends(require_admin())):
    doc = await db.social_subtitles.find_one({"id": subtitle_id})
    if not doc:
        raise HTTPException(404, "subtitle not found")
    if doc.get("status") not in ("ready", "edited", "burn_failed"):
        raise HTTPException(400, f"cannot burn while status={doc.get('status')}")
    if not doc.get("srt") and not doc.get("srt_path"):
        raise HTTPException(400, "no captions to burn")
    asyncio.create_task(_run_burn_job(subtitle_id, body.style))
    return {"ok": True, "note": "burn started; poll subtitle status for burned_video_path"}


@api.get("/social/subtitles/{subtitle_id}/burned/stream")
async def social_subtitle_burned_stream(subtitle_id: str,
                                        token: Optional[str] = None,
                                        authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        u = await current_user(authorization=authorization)
        if u.get("role") not in ("admin", "coach"):
            raise HTTPException(403, "admin role required")
    else:
        await _admin_from_query_token(token)
    doc = await db.social_subtitles.find_one({"id": subtitle_id})
    if not doc or not doc.get("burned_video_path"):
        raise HTTPException(404, "burned video not ready")
    path = Path(doc["burned_video_path"])
    if not path.exists():
        raise HTTPException(404, "burned video file missing")
    return FileResponse(str(path), media_type="video/mp4")
