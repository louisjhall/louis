"""ai_limits — AI usage quotas, cost telemetry and admin visibility.

Centralises three responsibilities so every LLM/vision/image/audio call in
CrewFit gets consistent treatment:

1. **Quota enforcement** — daily + monthly per-user caps by feature key.
   Raises HTTP 429 with a friendly message if the cap is reached.
2. **Cost telemetry** — every call is logged with feature, provider, model,
   token/image/second counts and an estimated USD cost. Rolls up nicely for
   admin dashboards.
3. **Ops visibility** — a single collection (`ai_usage`) that admins can query
   for per-user usage, per-feature spend, failure rate, and outliers.

Usage (recommended pattern):

    from ai_limits import ai_call
    async with ai_call(user, "photo_scan", model="claude-sonnet-4-5") as call:
        # ... do the LLM work ...
        call.set_tokens(in_=1500, out_=400)

Design notes:
 * Non-fatal: telemetry write errors never break the LLM call.
 * Zero-config: works with the existing Motor `db` instance from server.py.
 * Feature flag: set `AI_LIMITS_ENFORCED=0` to log-only without blocking.
"""
from __future__ import annotations

import os
import uuid
import time
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status

logger = logging.getLogger("ai_limits")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ENFORCED = os.environ.get("AI_LIMITS_ENFORCED", "1") == "1"

# Per-feature caps. Anything not listed is treated as unlimited-but-logged.
# `role` gate lets us keep some features coach-only.
# Tiers: `free` (default) and `paid` — the user doc can carry {"tier": "paid"}.
DEFAULT_QUOTAS: dict[str, dict[str, dict[str, int]]] = {
    "photo_scan":         {"free": {"day": 10, "month": 30},   "paid": {"day": 100, "month": 1000}},
    "atlas_message":      {"free": {"day": 5,  "month": 60},   "paid": {"day": 50,  "month": 1000}},
    "roster_parsing":     {"free": {"day": 3,  "month": 20},   "paid": {"day": 10,  "month": 100}},
    "workout_gen":        {"free": {"day": 5,  "month": 40},   "paid": {"day": 20,  "month": 500}},
    "checkin_summary":    {"free": {"day": 2,  "month": 10},   "paid": {"day": 5,   "month": 20}},
    "nutrition_insight":  {"free": {"day": 1,  "month": 6},    "paid": {"day": 2,   "month": 30}},
    "travel_guidance":    {"free": {"day": 5,  "month": 30},   "paid": {"day": 30,  "month": 500}},
    "habit_review":       {"free": {"day": 2,  "month": 10},   "paid": {"day": 5,   "month": 30}},
    "chat_atlas":         {"free": {"day": 10, "month": 100},  "paid": {"day": 100, "month": 2000}},
    # Coach-only features. Client `free` cap is effectively 0 to block misuse.
    "image_gen":          {"free": {"day": 0,  "month": 0},    "paid": {"day": 5,   "month": 30}, "coach": {"day": 20, "month": 100}},
    "social_gen":         {"free": {"day": 0,  "month": 0},    "paid": {"day": 5,   "month": 30}, "coach": {"day": 20, "month": 60}},
    "transcription":      {"free": {"day": 0,  "month": 0},    "paid": {"day": 5,   "month": 30}, "coach": {"day": 30, "month": 200}},
    # Free lookup — logged but unbounded.
    "barcode_lookup":     {"free": {"day": 999, "month": 9999},"paid": {"day": 999, "month": 9999}},
}

# Rough USD per unit. Sources: public Anthropic + Gemini + OpenAI pricing pages
# (June 2026). These are estimates — good enough for a dashboard, not billing.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # per 1M tokens
    "claude-sonnet-4-5-20250929":   {"in": 3.00,  "out": 15.00, "image_flat": 0.005},
    "claude-sonnet-4-5":            {"in": 3.00,  "out": 15.00, "image_flat": 0.005},
    "gpt-4o":                       {"in": 2.50,  "out": 10.00},
    "gpt-4o-mini":                  {"in": 0.15,  "out": 0.60},
    "gpt-5.2":                      {"in": 5.00,  "out": 20.00},
    "gemini-2.5-flash":             {"in": 0.075, "out": 0.30},
    "gemini-3-flash":               {"in": 0.15,  "out": 0.60},
    "gemini-3-pro":                 {"in": 3.50,  "out": 10.50},
    # Image models — per image flat
    "gemini-3.1-flash-image-preview": {"image_flat": 0.030},
    "nano-banana":                    {"image_flat": 0.030},
    "gpt-image-1":                    {"image_flat": 0.040},
    # Audio — per second billed as $/min ÷ 60
    "whisper-1":                    {"audio_per_sec": 0.006 / 60.0},
    "tts-1":                        {"tts_per_char": 15.00 / 1_000_000.0},
}


def estimate_cost_usd(model: str, *, tokens_in: int = 0, tokens_out: int = 0,
                     images: int = 0, audio_seconds: float = 0.0,
                     tts_chars: int = 0) -> float:
    price = MODEL_PRICING.get(model) or MODEL_PRICING.get(model.split(":")[0]) or {}
    total = 0.0
    if tokens_in and "in" in price:
        total += (tokens_in / 1_000_000.0) * price["in"]
    if tokens_out and "out" in price:
        total += (tokens_out / 1_000_000.0) * price["out"]
    if images:
        total += images * price.get("image_flat", 0.0)
    if audio_seconds and "audio_per_sec" in price:
        total += audio_seconds * price["audio_per_sec"]
    if tts_chars and "tts_per_char" in price:
        total += tts_chars * price["tts_per_char"]
    return round(total, 6)


def estimate_tokens_from_text(*texts: str) -> int:
    """Rough token estimate: chars ÷ 4. Fine for admin dashboards."""
    return int(sum(len(t or "") for t in texts) / 4)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _ymd(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")

def _ym(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Quota resolution
# ---------------------------------------------------------------------------

def _resolve_cap(user: dict, feature: str) -> dict[str, int]:
    q = DEFAULT_QUOTAS.get(feature)
    if not q:
        return {"day": 10_000, "month": 100_000}
    role = (user or {}).get("role", "client")
    tier = (user or {}).get("tier") or "free"
    # coach role overrides for coach-only features (image_gen, social_gen, transcription)
    if role == "coach" and "coach" in q:
        return q["coach"]
    return q.get(tier, q.get("free", {"day": 0, "month": 0}))


async def check_quota(db, user: dict, feature: str) -> dict[str, Any]:
    """Raise HTTPException 429 if the user has exceeded their quota.

    Returns the current usage snapshot for the given feature.
    """
    caps = _resolve_cap(user, feature)
    ymd = _ymd()
    ym = _ym()
    q_day = await db.ai_usage.count_documents({
        "user_id": user["id"], "feature": feature, "ymd": ymd,
        "success": True,
    })
    q_month = await db.ai_usage.count_documents({
        "user_id": user["id"], "feature": feature, "ym": ym,
        "success": True,
    })

    day_cap = caps.get("day", 0)
    month_cap = caps.get("month", 0)

    if ENFORCED:
        if q_day >= day_cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "quota_exceeded",
                    "scope": "daily",
                    "feature": feature,
                    "limit": day_cap,
                    "used": q_day,
                    "message": _cap_message(feature, "day", day_cap),
                },
            )
        if q_month >= month_cap:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "quota_exceeded",
                    "scope": "monthly",
                    "feature": feature,
                    "limit": month_cap,
                    "used": q_month,
                    "message": _cap_message(feature, "month", month_cap),
                },
            )

    return {"day": q_day, "month": q_month, "cap_day": day_cap, "cap_month": month_cap}


def _cap_message(feature: str, scope: str, cap: int) -> str:
    labels = {
        "photo_scan": "AI meal photo scans",
        "atlas_message": "Atlas message drafts",
        "roster_parsing": "roster imports",
        "workout_gen": "workout generations",
        "checkin_summary": "check-in summaries",
        "nutrition_insight": "nutrition insights",
        "travel_guidance": "travel guidance queries",
        "habit_review": "habit reviews",
        "chat_atlas": "Atlas chat messages",
        "image_gen": "AI image generations",
        "social_gen": "social media generations",
        "transcription": "transcription jobs",
    }
    label = labels.get(feature, feature)
    scope_word = "today" if scope == "day" else "this month"
    return f"You've reached your limit of {cap} {label} {scope_word}. Try again later or upgrade."


# ---------------------------------------------------------------------------
# Recording usage
# ---------------------------------------------------------------------------

async def record_usage(db, *, user_id: str, feature: str, model: str,
                      provider: str = "unknown",
                      tokens_in: int = 0, tokens_out: int = 0,
                      images: int = 0, audio_seconds: float = 0.0,
                      tts_chars: int = 0,
                      success: bool = True, error: Optional[str] = None,
                      duration_ms: int = 0,
                      meta: Optional[dict] = None) -> None:
    try:
        cost = estimate_cost_usd(
            model, tokens_in=tokens_in, tokens_out=tokens_out,
            images=images, audio_seconds=audio_seconds, tts_chars=tts_chars,
        )
        doc = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "feature": feature,
            "model": model,
            "provider": provider,
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
            "images": int(images or 0),
            "audio_seconds": float(audio_seconds or 0.0),
            "tts_chars": int(tts_chars or 0),
            "est_cost_usd": cost,
            "success": bool(success),
            "error": (error or "")[:500] if error else None,
            "duration_ms": int(duration_ms or 0),
            "ts": _now_iso(),
            "ymd": _ymd(),
            "ym": _ym(),
            "meta": meta or {},
        }
        await db.ai_usage.insert_one(doc)
    except Exception:
        logger.exception("ai_limits.record_usage failed (non-fatal)")


# ---------------------------------------------------------------------------
# Context manager wrapper — the recommended API
# ---------------------------------------------------------------------------

class _Call:
    """Mutable holder passed to the caller."""
    def __init__(self):
        self.tokens_in = 0
        self.tokens_out = 0
        self.images = 0
        self.audio_seconds = 0.0
        self.tts_chars = 0
        self.meta: dict = {}

    def set_tokens(self, in_: int = 0, out_: int = 0):
        if in_: self.tokens_in = in_
        if out_: self.tokens_out = out_

    def add_images(self, n: int = 1):
        self.images += n

    def add_audio_seconds(self, seconds: float):
        self.audio_seconds += seconds

    def add_tts_chars(self, n: int):
        self.tts_chars += n

    def set_meta(self, **kv):
        self.meta.update(kv)


@asynccontextmanager
async def ai_call(db, user: dict, feature: str, *, model: str,
                  provider: str = "emergent", enforce: bool = True):
    """Async context manager that gates + logs an AI call.

    * Runs `check_quota` first (unless `enforce=False`).
    * Yields a mutable `_Call` object the caller populates with tokens/images.
    * On success or exception, writes a row to `ai_usage`.
    """
    if enforce:
        await check_quota(db, user, feature)
    call = _Call()
    start = time.time()
    err: Optional[str] = None
    ok = True
    try:
        yield call
    except HTTPException:
        ok = False
        err = "http_exception"
        raise
    except Exception as e:
        ok = False
        err = str(e)[:500]
        raise
    finally:
        duration_ms = int((time.time() - start) * 1000)
        await record_usage(
            db,
            user_id=user.get("id", "unknown"),
            feature=feature,
            model=model,
            provider=provider,
            tokens_in=call.tokens_in,
            tokens_out=call.tokens_out,
            images=call.images,
            audio_seconds=call.audio_seconds,
            tts_chars=call.tts_chars,
            success=ok,
            error=err,
            duration_ms=duration_ms,
            meta=call.meta,
        )


# ---------------------------------------------------------------------------
# Admin dashboard helpers
# ---------------------------------------------------------------------------

async def user_quota_snapshot(db, user: dict) -> dict[str, Any]:
    """Return per-feature caps + current usage for the given user."""
    ymd = _ymd()
    ym = _ym()
    out: dict[str, Any] = {"user_id": user["id"], "tier": user.get("tier", "free"),
                           "role": user.get("role", "client"), "features": {}}
    for feature in DEFAULT_QUOTAS.keys():
        caps = _resolve_cap(user, feature)
        day = await db.ai_usage.count_documents({"user_id": user["id"], "feature": feature, "ymd": ymd, "success": True})
        month = await db.ai_usage.count_documents({"user_id": user["id"], "feature": feature, "ym": ym, "success": True})
        out["features"][feature] = {
            "day": day, "month": month,
            "cap_day": caps.get("day", 0), "cap_month": caps.get("month", 0),
            "remaining_day": max(0, caps.get("day", 0) - day),
            "remaining_month": max(0, caps.get("month", 0) - month),
        }
    return out


async def admin_daily_totals(db, days: int = 7) -> list[dict]:
    """Aggregate rollup by day + feature. Used by admin dashboard."""
    pipeline = [
        {"$sort": {"ts": -1}},
        {"$limit": 200_000},
        {"$group": {
            "_id": {"ymd": "$ymd", "feature": "$feature"},
            "calls": {"$sum": 1},
            "cost_usd": {"$sum": "$est_cost_usd"},
            "tokens_in": {"$sum": "$tokens_in"},
            "tokens_out": {"$sum": "$tokens_out"},
            "images": {"$sum": "$images"},
            "failures": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
        }},
        {"$sort": {"_id.ymd": -1}},
        {"$limit": days * 30},
    ]
    rows = await db.ai_usage.aggregate(pipeline).to_list(1000)
    for r in rows:
        r["ymd"] = r["_id"]["ymd"]
        r["feature"] = r["_id"]["feature"]
        r.pop("_id", None)
        r["cost_usd"] = round(r.get("cost_usd", 0.0), 4)
    return rows


async def admin_top_users(db, days: int = 7, limit: int = 20) -> list[dict]:
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {"ts": {"$gte": since}}},
        {"$group": {
            "_id": "$user_id",
            "calls": {"$sum": 1},
            "cost_usd": {"$sum": "$est_cost_usd"},
            "failures": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
        }},
        {"$sort": {"cost_usd": -1}},
        {"$limit": limit},
    ]
    rows = await db.ai_usage.aggregate(pipeline).to_list(limit)
    for r in rows:
        r["user_id"] = r["_id"]
        r.pop("_id", None)
        r["cost_usd"] = round(r.get("cost_usd", 0.0), 4)
    return rows
