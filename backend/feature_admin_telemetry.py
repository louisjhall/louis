"""feature_admin_telemetry — Admin dashboard endpoints for AI usage + cost.

All endpoints require the admin/coach role. Read-only.

Routes:
  GET /api/admin/telemetry/summary          — top-line totals + failures
  GET /api/admin/telemetry/daily            — per-day per-feature rollup
  GET /api/admin/telemetry/top-users        — highest spenders (last N days)
  GET /api/admin/telemetry/user/{user_id}   — per-user quota snapshot
  GET /api/admin/telemetry/outliers         — unusually high usage flags
  GET /api/admin/telemetry/quotas           — feature quota configuration
  GET /api/user/quota                       — CURRENT USER's own quota view
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import Depends, Query, HTTPException

from server import api, db, current_user, require_admin
import ai_limits


@api.get("/admin/telemetry/summary")
async def admin_telemetry_summary(days: int = 7, user: dict = Depends(require_admin())):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    pipeline = [
        {"$match": {"ts": {"$gte": since}}},
        {"$group": {
            "_id": None,
            "calls": {"$sum": 1},
            "cost_usd": {"$sum": "$est_cost_usd"},
            "tokens_in": {"$sum": "$tokens_in"},
            "tokens_out": {"$sum": "$tokens_out"},
            "images": {"$sum": "$images"},
            "failures": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
        }},
    ]
    rows = await db.ai_usage.aggregate(pipeline).to_list(1)
    r = rows[0] if rows else {"calls": 0, "cost_usd": 0, "tokens_in": 0, "tokens_out": 0, "images": 0, "failures": 0}
    r["cost_usd"] = round(r.get("cost_usd", 0.0), 4)
    r.pop("_id", None)
    # unique users
    r["unique_users"] = len(await db.ai_usage.distinct("user_id", {"ts": {"$gte": since}}))
    r["days"] = days
    return r


@api.get("/admin/telemetry/daily")
async def admin_telemetry_daily(days: int = 7, user: dict = Depends(require_admin())):
    rows = await ai_limits.admin_daily_totals(db, days=days)
    return {"days": days, "rows": rows}


@api.get("/admin/telemetry/top-users")
async def admin_telemetry_top_users(days: int = 7, limit: int = 20,
                                    user: dict = Depends(require_admin())):
    rows = await ai_limits.admin_top_users(db, days=days, limit=limit)
    # enrich with user emails when available
    ids = [r["user_id"] for r in rows]
    users = {u["id"]: u async for u in db.users.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1, "tier": 1}
    )}
    for r in rows:
        u = users.get(r["user_id"], {})
        r["email"] = u.get("email")
        r["name"] = u.get("name")
        r["role"] = u.get("role")
        r["tier"] = u.get("tier", "free")
    return {"days": days, "rows": rows}


@api.get("/admin/telemetry/user/{user_id}")
async def admin_telemetry_user(user_id: str, user: dict = Depends(require_admin())):
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(404, "user not found")
    snap = await ai_limits.user_quota_snapshot(db, u)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = await db.ai_usage.find({"user_id": user_id, "ts": {"$gte": since}},
                                    {"_id": 0}).sort("ts", -1).to_list(200)
    monthly_cost = sum(r.get("est_cost_usd", 0.0) for r in recent)
    return {"user": {"id": u["id"], "email": u.get("email"), "name": u.get("name"),
                     "role": u.get("role"), "tier": u.get("tier", "free")},
            "quota": snap,
            "recent_calls": len(recent),
            "monthly_cost_usd": round(monthly_cost, 4),
            "last_30_days": recent[:50]}


@api.get("/admin/telemetry/outliers")
async def admin_telemetry_outliers(days: int = 1, threshold_multiplier: float = 3.0,
                                    user: dict = Depends(require_admin())):
    """Flag users whose usage is > threshold_multiplier × the P90 of all users
    (per-feature). Simple and cheap."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    per_user = {}
    async for r in db.ai_usage.find({"ts": {"$gte": since}, "success": True}, {"_id": 0}):
        key = (r["user_id"], r["feature"])
        per_user[key] = per_user.get(key, 0) + 1
    if not per_user:
        return {"days": days, "outliers": []}
    # Aggregate feature distributions
    by_feature: dict[str, list[int]] = {}
    for (_, feat), n in per_user.items():
        by_feature.setdefault(feat, []).append(n)
    p90: dict[str, float] = {}
    for feat, vals in by_feature.items():
        vals.sort()
        idx = int(len(vals) * 0.9)
        p90[feat] = float(vals[min(idx, len(vals) - 1)])
    outliers = []
    for (uid, feat), n in per_user.items():
        thresh = p90.get(feat, 0) * threshold_multiplier
        if thresh and n > thresh:
            outliers.append({"user_id": uid, "feature": feat, "count": n,
                             "p90": p90[feat], "multiplier": round(n / p90[feat], 2)})
    outliers.sort(key=lambda x: -x["multiplier"])
    return {"days": days, "outliers": outliers[:50]}


@api.get("/admin/telemetry/quotas")
async def admin_telemetry_quotas(user: dict = Depends(require_admin())):
    return {"enforced": ai_limits.ENFORCED, "quotas": ai_limits.DEFAULT_QUOTAS}


@api.get("/user/quota")
async def user_own_quota(user: dict = Depends(current_user)):
    """Users can see their own quota status (drives 'X of Y left today' UI)."""
    return await ai_limits.user_quota_snapshot(db, user)
