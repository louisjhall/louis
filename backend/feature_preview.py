"""feature_preview — Coach/Admin "Preview as Client" mode.

How it works:
 * `POST /api/coach/preview/impersonate` — coach chooses a target client;
   we return a short-lived JWT that identifies the coach as the client but
   carries a `preview: true` claim + the *real* coach id in `preview_by`.
 * `POST /api/coach/preview/exit` — no-op; the frontend just deletes the
   preview token and restores the coach's original token.
 * `POST /api/coach/preview/demo-seed` — idempotent seeder for the demo
   aviation client used for previews.
 * `POST /api/coach/preview/new-client` — creates a throwaway client for
   "preview the new-user onboarding flow", auto-purged after 24h.
 * `POST /api/preview/ui-issue` — report a UI bug seen while in preview.
 * `GET  /api/admin/ui-issues` — list all reported issues.

Write-guard middleware lives in server.py; it inspects the JWT and blocks
all POST/PUT/PATCH/DELETE requests when `preview: true` is set (with a
small allow-list for exit + issue reporting).
"""
from __future__ import annotations

import os
import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import (
    api, db, current_user, require_admin, hash_pw, now_iso, new_id,
    JWT_SECRET, JWT_ALGO, logger,
)

PREVIEW_TOKEN_TTL_HOURS = 2   # short-lived by design


# ---------------------------------------------------------------------------
# Impersonation
# ---------------------------------------------------------------------------

class ImpersonateReq(BaseModel):
    target_user_id: str


@api.post("/coach/preview/impersonate")
async def preview_impersonate(body: ImpersonateReq, coach: dict = Depends(require_admin())):
    target = await db.users.find_one({"id": body.target_user_id}, {"_id": 0, "password_hash": 0})
    if not target:
        raise HTTPException(404, "target user not found")
    if target.get("role") == "coach":
        raise HTTPException(400, "cannot preview as another coach")
    if target.get("deleted_at"):
        raise HTTPException(400, "cannot preview a soft-deleted account")
    payload = {
        "sub": target["id"],
        "role": target.get("role", "client"),
        "preview": True,
        "preview_by": coach["id"],
        "preview_by_email": coach.get("email"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=PREVIEW_TOKEN_TTL_HOURS),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    await db.preview_audit.insert_one({
        "id": str(uuid.uuid4()),
        "coach_id": coach["id"],
        "target_id": target["id"],
        "target_email": target.get("email"),
        "target_name": target.get("name"),
        "action": "impersonate",
        "ts": now_iso(),
    })
    logger.info("preview: coach=%s impersonating client=%s", coach["id"], target["id"])
    return {
        "token": token,
        "target": {
            "id": target["id"], "name": target.get("name"), "email": target.get("email"),
            "role": target.get("role"),
        },
        "expires_hours": PREVIEW_TOKEN_TTL_HOURS,
    }


@api.post("/coach/preview/exit")
async def preview_exit(user: dict = Depends(current_user)):
    """No-op endpoint the frontend calls for symmetry."""
    await db.preview_audit.insert_one({
        "id": str(uuid.uuid4()),
        "coach_id": user.get("_preview_by") or user["id"],
        "target_id": user["id"],
        "action": "exit",
        "ts": now_iso(),
    })
    return {"ok": True}


# ---------------------------------------------------------------------------
# Demo client
# ---------------------------------------------------------------------------

DEMO_EMAIL = "demo.pilot@crewfit.com"
DEMO_PASSWORD = "Demo123!"


@api.post("/coach/preview/demo-seed")
async def preview_demo_seed(coach: dict = Depends(require_admin())):
    """Idempotently (re)create the demo aviation client used for previews."""
    existing = await db.users.find_one({"email": DEMO_EMAIL})
    if existing:
        uid = existing["id"]
        # Refresh key mutable fields but leave core identity alone.
        await db.users.update_one({"id": uid}, {"$set": {
            "name": "Demo Pilot (BA)", "onboarded": True,
            "age_confirmed": True, "age_confirmed_at": now_iso(),
            "profile": {
                "role": "pilot", "airline": "British Airways", "base": "LHR",
                "aircraft": "B787", "years_flying": 8,
            },
            "updated_at": now_iso(),
        }})
        action = "refreshed"
    else:
        uid = new_id()
        await db.users.insert_one({
            "id": uid, "email": DEMO_EMAIL, "name": "Demo Pilot (BA)",
            "role": "client", "password_hash": hash_pw(DEMO_PASSWORD),
            "created_at": now_iso(), "onboarded": True, "coach_id": coach["id"],
            "age_confirmed": True, "age_confirmed_at": now_iso(),
            "profile": {
                "role": "pilot", "airline": "British Airways", "base": "LHR",
                "aircraft": "B787", "years_flying": 8,
            },
        })
        action = "created"

    # Nutrition targets (idempotent)
    await db.nutrition_targets.update_one(
        {"user_id": uid},
        {"$set": {"user_id": uid, "calories": 2400, "protein_g": 160,
                  "carbs_g": 260, "fats_g": 80, "hydration_ml": 3000,
                  "target_type": "maintain", "updated_at": now_iso()}},
        upsert=True,
    )

    # Wipe + reseed the demo-specific data (keep it small + realistic)
    for coll in ("habits", "habit_logs", "workouts", "workout_sets",
                 "nutrition_logs", "checkins", "messages", "schedule_events"):
        await db[coll].delete_many({"user_id": uid})

    today = datetime.now(timezone.utc)
    ymd = lambda d: d.strftime("%Y-%m-%d")

    # 3 core aviation habits
    for i, h in enumerate([
        {"name": "Hydration 3L", "cadence": "daily"},
        {"name": "Steps 10k", "cadence": "daily"},
        {"name": "20 min mobility", "cadence": "weekday"},
    ]):
        hid = new_id()
        await db.habits.insert_one({
            "id": hid, "user_id": uid, "name": h["name"],
            "cadence": h["cadence"], "active": True, "created_at": now_iso(),
        })
        # 21 days of history, mostly successful
        for d in range(21):
            when = today - timedelta(days=d)
            status = "done" if (d % 4 != 3) else "missed"
            await db.habit_logs.insert_one({
                "id": new_id(), "user_id": uid, "habit_id": hid,
                "date_local": ymd(when), "status": status, "ts": when.isoformat(),
            })

    # 5 workouts logged in the past 2 weeks
    for i, name in enumerate(["Upper Push A", "Lower Pull A", "Hotel Full-Body",
                                "Long-Haul Recovery", "Standby Strength"]):
        wid = new_id()
        when = today - timedelta(days=i * 3)
        await db.workouts.insert_one({
            "id": wid, "user_id": uid, "title": name, "status": "completed",
            "duration_min": 40 + i * 5, "created_at": when.isoformat(),
            "completed_at": when.isoformat(),
            "date": ymd(when),
            "date_local": ymd(when),
        })

    # 5 nutrition entries today
    for i, (meal, kcal, p, c, f) in enumerate([
        ("breakfast", 480, 32, 55, 14),
        ("snack", 220, 18, 20, 8),
        ("lunch", 640, 45, 60, 22),
        ("snack", 180, 12, 20, 6),
        ("dinner", 720, 50, 70, 24),
    ]):
        await db.nutrition_logs.insert_one({
            "log_id": new_id(), "user_id": uid, "date_local": ymd(today),
            "meal_type": meal, "source": "manual",
            "estimated_macros": {"calories": kcal, "protein_g": p, "carbs_g": c, "fats_g": f},
            "food_items": [{"name": f"Demo {meal} item"}],
            "ts": now_iso(),
        })

    # 2 recent check-ins
    for i in range(2):
        wk = today - timedelta(days=7 * i)
        await db.checkins.insert_one({
            "id": new_id(), "user_id": uid,
            "week_start": ymd(wk - timedelta(days=wk.weekday())),
            "submitted_at": wk.isoformat(),
            "answers": {
                "energy": 7, "stress": 4, "sleep_hours": 7.2,
                "note": "Good week. Managed 4 workouts and stayed on hydration.",
            },
        })

    # 3 coach messages
    for i, txt in enumerate([
        "Welcome to CrewFit! Let me know how the roster looks this month.",
        "Great job on the layover session in NYC.",
        "Try to swap the second snack for something protein-rich.",
    ]):
        when = today - timedelta(days=i * 3)
        await db.messages.insert_one({
            "id": new_id(), "user_id": uid, "from_user_id": coach["id"],
            "to_user_id": uid, "body": txt, "role": "coach",
            "ts": when.isoformat(), "read": False,
        })

    # A minimal roster: 4 flying days ahead
    for i, (day_type, note) in enumerate([
        ("flight", "LHR-JFK (day)"),
        ("layover", "NYC 24h"),
        ("flight", "JFK-LHR (night)"),
        ("rest", "Home recovery"),
    ]):
        when = today + timedelta(days=i + 1)
        await db.schedule_events.insert_one({
            "id": new_id(), "user_id": uid, "date_local": ymd(when),
            "day_type": day_type, "note": note,
            "source": "demo_seed", "ts": when.isoformat(),
        })

    return {
        "action": action, "user_id": uid,
        "email": DEMO_EMAIL, "password_hint": "Demo123! (for direct login testing)",
    }


@api.post("/coach/preview/new-client")
async def preview_new_client(coach: dict = Depends(require_admin())):
    """Create a fresh throwaway client to preview the new-user onboarding flow.
    Auto-purged after 24h by the daily cron."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    email = f"preview-newclient-{stamp}@crewfit.local"
    uid = new_id()
    now = now_iso()
    await db.users.insert_one({
        "id": uid, "email": email,
        "name": "New Client Preview", "role": "client",
        "password_hash": hash_pw("Preview123!"),
        "created_at": now, "onboarded": False, "coach_id": None,
        "age_confirmed": True, "age_confirmed_at": now,
        "profile": {},
        "is_preview_throwaway": True,
        "purge_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
    })
    # Impersonate immediately
    payload = {
        "sub": uid, "role": "client",
        "preview": True, "preview_by": coach["id"],
        "preview_by_email": coach.get("email"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=PREVIEW_TOKEN_TTL_HOURS),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
    await db.preview_audit.insert_one({
        "id": str(uuid.uuid4()), "coach_id": coach["id"],
        "target_id": uid, "target_email": email,
        "action": "new_client_preview", "ts": now,
    })
    return {"token": token, "target": {"id": uid, "name": "New Client Preview",
            "email": email, "role": "client"}, "expires_hours": PREVIEW_TOKEN_TTL_HOURS}


# ---------------------------------------------------------------------------
# UI issue reporter
# ---------------------------------------------------------------------------

class UIIssueReq(BaseModel):
    screen: str = Field(..., description="route path or screen name")
    note: str = Field(..., min_length=3, max_length=1500)
    issue_type: str = "visual"    # visual | copy | broken | other
    priority: str = "medium"      # low | medium | high
    screenshot_data_url: Optional[str] = None  # base64 data URL from web


@api.post("/preview/ui-issue")
async def preview_ui_issue(body: UIIssueReq, user: dict = Depends(current_user)):
    # Anyone who is authenticated can file, but we mark it as coach-flagged
    # when the token has preview: true or the user is admin.
    is_preview = bool(user.get("_is_preview"))
    reporter_role = user.get("role", "unknown")
    doc = {
        "id": str(uuid.uuid4()),
        "screen": body.screen[:200],
        "note": body.note,
        "issue_type": body.issue_type[:24],
        "priority": body.priority if body.priority in ("low", "medium", "high") else "medium",
        "screenshot_data_url": body.screenshot_data_url,
        "reporter_id": user.get("_preview_by") or user["id"],
        "reporter_email": user.get("_preview_by_email") or user.get("email"),
        "reporter_role": reporter_role,
        "viewed_as_user_id": user["id"] if is_preview else None,
        "viewed_as_email": user.get("email") if is_preview else None,
        "is_preview": is_preview,
        "status": "open",
        "ts": now_iso(),
    }
    await db.ui_issues.insert_one(doc)
    return {"ok": True, "id": doc["id"]}


@api.get("/admin/ui-issues")
async def admin_ui_issues(status_filter: str = "open", limit: int = 200,
                          coach: dict = Depends(require_admin())):
    q = {} if status_filter == "all" else {"status": status_filter}
    rows = await db.ui_issues.find(q, {"_id": 0}).sort("ts", -1).to_list(limit)
    # Strip large screenshots in the list view
    for r in rows:
        if r.get("screenshot_data_url"):
            r["has_screenshot"] = True
            r["screenshot_data_url"] = None
    counts = {}
    for s in ("open", "resolved", "ignored"):
        counts[s] = await db.ui_issues.count_documents({"status": s})
    return {"issues": rows, "counts": counts}


@api.get("/admin/ui-issues/{issue_id}")
async def admin_ui_issue_detail(issue_id: str, coach: dict = Depends(require_admin())):
    r = await db.ui_issues.find_one({"id": issue_id}, {"_id": 0})
    if not r: raise HTTPException(404, "issue not found")
    return r


class UIIssueUpdate(BaseModel):
    status: str  # open | resolved | ignored


@api.patch("/admin/ui-issues/{issue_id}")
async def admin_ui_issue_update(issue_id: str, body: UIIssueUpdate,
                                 coach: dict = Depends(require_admin())):
    if body.status not in ("open", "resolved", "ignored"):
        raise HTTPException(400, "invalid status")
    await db.ui_issues.update_one({"id": issue_id},
        {"$set": {"status": body.status, "updated_at": now_iso()}})
    return {"ok": True}


# ---------------------------------------------------------------------------
# Purge job for throwaway new-client previews (called from daily cron)
# ---------------------------------------------------------------------------

async def preview_purge_throwaways() -> dict:
    now = now_iso()
    victims = await db.users.find({
        "is_preview_throwaway": True,
        "purge_at": {"$lte": now},
    }, {"_id": 0, "id": 1}).to_list(100)
    purged = 0
    for v in victims:
        uid = v["id"]
        try:
            await db.users.delete_one({"id": uid})
            purged += 1
        except Exception:
            logger.exception("preview purge failed for %s", uid)
    if purged:
        logger.info("preview_purge: removed %d throwaway preview users", purged)
    return {"purged": purged}
