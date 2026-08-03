"""
feature_client_issues — Report an Issue / Client Issues inbox.

Lean bug-report loop reusing existing infrastructure:
  * `db.client_issues`               NEW — single small collection per report.
  * `db.coach_tasks` (existing)      Auto-creates a `client_issue_new`
                                     task per submission → badges the coach
                                     dashboard via the existing task queue.
  * `db.client_issue_groups`         NEW — deterministic grouping index.
                                     Signature = sha1(category|route|workout|
                                     exercise|error_code). Groups grow as new
                                     reports arrive with the same signature.
  * Base64 screenshot storage        (embedded in the issue row — same as
                                     the rest of the app's image storage
                                     model — no new bucket, no S3, no new
                                     provider).

Endpoints:
  Client:
    POST   /api/client/issues              Submit a new report.
    GET    /api/client/issues              List the caller's own reports.
    GET    /api/client/issues/{id}         View one own report (with reply).
  Coach / Admin:
    GET    /api/coach/client-issues        Inbox (grouped + sorted).
    GET    /api/coach/client-issues/{id}   Full report + technical context.
    PATCH  /api/coach/client-issues/{id}   status / internal_note /
                                           coach_reply / assigned_area /
                                           duplicate_of.

Security: reuses the existing require_auth / require_role gates. Clients see
only their own reports; coaches see everyone's.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from server import (
    api, db, current_user, require_role, logger, new_id, now_iso,
    _create_coach_task, _log_change,
)


ISSUE_STATUSES = ("new", "reviewing", "fix_in_progress", "waiting_for_client",
                  "resolved", "closed")

ISSUE_CATEGORIES = (
    "workout_not_working", "exercise_or_media", "roster", "flight_support",
    "todays_reality", "app_button_or_screen", "login_or_account",
    "progress_or_habit", "other",
)


def _normalise_desc(s: Optional[str]) -> str:
    """Cheap deterministic normalisation for grouping — no LLM."""
    if not s:
        return ""
    # Lowercase, strip URLs / ids, collapse whitespace, keep first ~60 chars.
    t = re.sub(r"https?://\S+", "", str(s).lower())
    t = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{20,}\b", "", t)  # uuids
    t = re.sub(r"\b\d+\b", "", t)                          # numbers
    t = re.sub(r"[^a-z ]+", " ", t)                        # punctuation
    return re.sub(r"\s+", " ", t).strip()[:60]


def _signature_for(category: str, route: Optional[str],
                   workout_id: Optional[str], exercise_id: Optional[str],
                   error_code: Optional[str], description: str,
                   app_version: Optional[str]) -> str:
    """Deterministic grouping key. Same signature → same group."""
    parts = [
        category or "",
        (route or "").split("?")[0],  # ignore query strings
        workout_id or "",
        exercise_id or "",
        error_code or "",
        _normalise_desc(description),
        (app_version or "").split("+")[0],  # ignore build tag
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:24]


async def _upsert_group_for(issue: dict) -> str:
    """Increment the group's affected counters. Idempotent."""
    sig = issue.get("signature")
    if not sig:
        return ""
    now = now_iso()
    await db.client_issue_groups.update_one(
        {"signature": sig},
        {
            "$setOnInsert": {
                "id": new_id(),
                "signature": sig,
                "first_category": issue.get("category"),
                "first_route": issue.get("route"),
                "first_workout_id": issue.get("workout_id"),
                "first_exercise_id": issue.get("exercise_id"),
                "first_reported_at": now,
                "created_at": now,
            },
            "$addToSet": {
                "client_ids": issue.get("user_id"),
                "platforms": issue.get("platform") or "unknown",
                "builds": issue.get("app_build") or issue.get("app_version") or "unknown",
                "issue_ids": issue.get("id"),
            },
            "$inc": {"report_count": 1},
            "$set": {"last_reported_at": now, "updated_at": now},
        },
        upsert=True,
    )
    grp = await db.client_issue_groups.find_one({"signature": sig}, {"_id": 0, "id": 1})
    return (grp or {}).get("id") or ""


# ---------------------------------------------------------------------------
# Pydantic bodies
# ---------------------------------------------------------------------------

class ClientIssueBody(BaseModel):
    category: str = Field(..., description="One of ISSUE_CATEGORIES")
    description: str = Field(..., min_length=3, max_length=4000)
    what_should_happen: Optional[str] = Field(None, max_length=4000)
    urgency: str = Field("normal", description="normal | blocking")
    screenshot_base64: Optional[str] = Field(None, max_length=6_000_000)
    contact_permission: bool = True
    # Technical context — client sends what it knows; server never trusts.
    route: Optional[str] = None
    app_version: Optional[str] = None
    app_build: Optional[str] = None
    platform: Optional[str] = None  # ios | android | web
    timezone: Optional[str] = None
    workout_id: Optional[str] = None
    workout_date: Optional[str] = None
    exercise_id: Optional[str] = None
    exercise_name: Optional[str] = None
    roster_id: Optional[str] = None
    flight_support_id: Optional[str] = None
    reality_selection: Optional[str] = None
    variant: Optional[str] = None
    error_code: Optional[str] = None


class ClientIssuePatchBody(BaseModel):
    status: Optional[str] = None
    internal_note: Optional[str] = None
    coach_reply: Optional[str] = None
    assigned_area: Optional[str] = None
    duplicate_of: Optional[str] = None


# ---------------------------------------------------------------------------
# Client endpoints
# ---------------------------------------------------------------------------

@api.post("/client/issues")
async def client_issue_create(body: ClientIssueBody,
                              user: dict = Depends(current_user)):
    if body.category not in ISSUE_CATEGORIES:
        raise HTTPException(400, f"unknown category: {body.category}")
    if body.urgency not in ("normal", "blocking"):
        raise HTTPException(400, "urgency must be 'normal' or 'blocking'")
    desc = (body.description or "").strip()
    if not desc:
        raise HTTPException(400, "description is required")

    sig = _signature_for(
        body.category, body.route, body.workout_id, body.exercise_id,
        body.error_code, desc, body.app_version,
    )
    issue_id = new_id()
    now = now_iso()
    doc = {
        "id": issue_id,
        "user_id": user["id"],
        "user_name": user.get("name") or user.get("email"),
        "user_email": user.get("email"),
        "category": body.category,
        "description": desc,
        "what_should_happen": (body.what_should_happen or "").strip() or None,
        "urgency": body.urgency,
        "contact_permission": bool(body.contact_permission),
        "screenshot_base64": body.screenshot_base64 or None,
        "route": body.route,
        "app_version": body.app_version,
        "app_build": body.app_build,
        "platform": body.platform,
        "timezone": body.timezone,
        "workout_id": body.workout_id,
        "workout_date": body.workout_date,
        "exercise_id": body.exercise_id,
        "exercise_name": body.exercise_name,
        "roster_id": body.roster_id,
        "flight_support_id": body.flight_support_id,
        "reality_selection": body.reality_selection,
        "variant": body.variant,
        "error_code": body.error_code,
        "signature": sig,
        "status": "new",
        "coach_reply": None,
        "internal_notes": [],
        "assigned_area": None,
        "duplicate_of": None,
        "created_at": now,
        "updated_at": now,
    }

    # Duplicate-tap guard — if the same user submitted a report with the
    # same signature in the last 60s, refuse the second insert and return
    # the existing one.
    recent = await db.client_issues.find_one(
        {"user_id": user["id"], "signature": sig,
         "created_at": {"$gte": _iso_secs_ago(60)}},
        {"_id": 0},
    )
    if recent:
        return {"ok": True, "issue": recent, "deduped": True}

    await db.client_issues.insert_one(doc)
    doc.pop("_id", None)  # never leak ObjectId — not JSON serialisable
    group_id = await _upsert_group_for(doc)
    if group_id:
        await db.client_issues.update_one({"id": issue_id},
                                           {"$set": {"group_id": group_id}})
        doc["group_id"] = group_id

    # Coach task = badge + inbox card. Reuses the existing task queue.
    try:
        await _create_coach_task(
            user=user,
            task_type="client_issue_new",
            title=f"{'🚨 ' if body.urgency == 'blocking' else '📩 '}"
                  f"Issue reported: {_category_label(body.category)}",
            description=(desc[:180] + ("…" if len(desc) > 180 else "")),
            priority="urgent" if body.urgency == "blocking" else "normal",
            category="urgent_safety" if body.urgency == "blocking" else "other",
            payload={
                "issue_id": issue_id,
                "category": body.category,
                "urgency": body.urgency,
                "route": body.route,
                "workout_id": body.workout_id,
                "signature": sig,
                "group_id": doc.get("group_id"),
            },
        )
    except Exception:
        logger.exception("client_issue: coach_task creation failed")

    return {"ok": True, "issue": _safe_issue(doc), "deduped": False}


def _iso_secs_ago(secs: int) -> str:
    import datetime as _dt
    return (_dt.datetime.utcnow() - _dt.timedelta(seconds=secs)).isoformat()


def _safe_issue(doc: dict) -> dict:
    """Never return the raw screenshot base64 in list responses — clients
    fetch a single issue when they need the picture."""
    return {k: v for k, v in doc.items() if k not in ("screenshot_base64",)}


def _category_label(c: str) -> str:
    return {
        "workout_not_working":   "Workout not working",
        "exercise_or_media":     "Exercise / media",
        "roster":                "Roster",
        "flight_support":        "Flight Support",
        "todays_reality":        "Today's Reality",
        "app_button_or_screen":  "App button or screen",
        "login_or_account":      "Login / account",
        "progress_or_habit":     "Progress / habit",
        "other":                 "Other",
    }.get(c, c)


@api.get("/client/issues")
async def client_issue_list(user: dict = Depends(current_user)):
    cursor = db.client_issues.find(
        {"user_id": user["id"]}, {"_id": 0, "screenshot_base64": 0},
    ).sort("created_at", -1)
    rows = await cursor.to_list(200)
    return {"issues": rows}


@api.get("/client/issues/{issue_id}")
async def client_issue_get(issue_id: str, user: dict = Depends(current_user)):
    doc = await db.client_issues.find_one(
        {"id": issue_id, "user_id": user["id"]}, {"_id": 0},
    )
    if not doc:
        raise HTTPException(404, "issue not found")
    return {"issue": doc}


# ---------------------------------------------------------------------------
# Coach / admin endpoints
# ---------------------------------------------------------------------------

@api.get("/coach/client-issues")
async def coach_client_issue_list(
    status: Optional[str] = Query(None),
    coach: dict = Depends(require_role("coach")),
):
    q: dict = {}
    if status and status != "all":
        q["status"] = status
    # Sort: blocking + new first, then most recent.
    cursor = db.client_issues.find(q, {"_id": 0, "screenshot_base64": 0}) \
        .sort([("urgency", -1), ("created_at", -1)])
    issues = await cursor.to_list(500)
    # Fetch group summaries in one pass for the frontend to render badges.
    sigs = sorted({i.get("signature") for i in issues if i.get("signature")})
    groups: dict[str, dict] = {}
    if sigs:
        async for g in db.client_issue_groups.find(
            {"signature": {"$in": sigs}}, {"_id": 0},
        ):
            groups[g["signature"]] = g
    for i in issues:
        g = groups.get(i.get("signature") or "")
        if g:
            i["group_summary"] = {
                "group_id":       g.get("id"),
                "report_count":   g.get("report_count", 1),
                "clients":        len(g.get("client_ids") or []),
                "platforms":      g.get("platforms") or [],
                "builds":         g.get("builds") or [],
                "first_reported_at": g.get("first_reported_at"),
                "last_reported_at":  g.get("last_reported_at"),
            }
    open_count = await db.client_issues.count_documents({"status": "new"})
    blocking_count = await db.client_issues.count_documents(
        {"status": {"$in": ["new", "reviewing", "fix_in_progress"]}, "urgency": "blocking"},
    )
    return {"issues": issues, "counts": {"new": open_count, "blocking": blocking_count}}


@api.get("/coach/client-issues/{issue_id}")
async def coach_client_issue_get(issue_id: str,
                                  coach: dict = Depends(require_role("coach"))):
    doc = await db.client_issues.find_one({"id": issue_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "issue not found")
    grp = None
    sig = doc.get("signature")
    if sig:
        grp = await db.client_issue_groups.find_one({"signature": sig}, {"_id": 0})
        if grp:
            # Include the linked issue rows so the coach can jump between them.
            linked = await db.client_issues.find(
                {"signature": sig, "id": {"$ne": issue_id}},
                {"_id": 0, "screenshot_base64": 0},
            ).sort("created_at", -1).to_list(50)
            grp["linked_issues"] = linked
    return {"issue": doc, "group": grp}


@api.patch("/coach/client-issues/{issue_id}")
async def coach_client_issue_patch(
    issue_id: str, body: ClientIssuePatchBody,
    coach: dict = Depends(require_role("coach")),
):
    doc = await db.client_issues.find_one({"id": issue_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "issue not found")
    updates: dict = {}
    if body.status is not None:
        if body.status not in ISSUE_STATUSES:
            raise HTTPException(400, f"invalid status: {body.status}")
        updates["status"] = body.status
    if body.assigned_area is not None:
        updates["assigned_area"] = body.assigned_area.strip() or None
    if body.duplicate_of is not None:
        updates["duplicate_of"] = body.duplicate_of.strip() or None
        if body.duplicate_of and body.status is None:
            updates["status"] = "closed"
    if body.coach_reply is not None:
        updates["coach_reply"] = body.coach_reply.strip() or None
        updates["coach_reply_at"] = now_iso()
        updates["coach_reply_by"] = coach.get("id")
    if body.internal_note is not None and body.internal_note.strip():
        notes = list(doc.get("internal_notes") or [])
        notes.append({
            "text": body.internal_note.strip(),
            "by": coach.get("id"),
            "at": now_iso(),
        })
        updates["internal_notes"] = notes
    if not updates:
        raise HTTPException(400, "nothing to update")
    updates["updated_at"] = now_iso()
    await db.client_issues.update_one({"id": issue_id}, {"$set": updates})
    # Complete the linked coach task when the issue moves out of `new` /
    # `reviewing` — keeps the coach dashboard clean.
    if updates.get("status") in ("resolved", "closed"):
        try:
            await db.coach_tasks.update_many(
                {"payload.issue_id": issue_id,
                 "status": {"$in": ["todo", "in_progress"]}},
                {"$set": {"status": "done", "completed_at": now_iso()}},
            )
        except Exception:
            logger.exception("client_issue: coach_task auto-close failed for %s", issue_id)
    saved = await db.client_issues.find_one({"id": issue_id}, {"_id": 0})
    try:
        await _log_change(
            coach.get("id"), doc.get("user_id"), "support",
            f"Coach updated issue #{issue_id[:8]}",
            "", actor="coach",
            meta={"issue_id": issue_id, "diff": updates},
        )
    except Exception:
        pass
    return {"ok": True, "issue": saved}


__all__ = [
    "ISSUE_CATEGORIES",
    "ISSUE_STATUSES",
]
