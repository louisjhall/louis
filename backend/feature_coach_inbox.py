"""
Iter 129d — Coach Messages workspace aggregation endpoints.

Small, targeted endpoints so the redesigned 3-panel coach Messages page can
render without N+1 requests per row:

  * GET /coach/inbox                — inbox list (partner + latest msg + unread)
  * GET /coach/client-context/{id}  — small right-panel context bundle

Both endpoints are coach-only, respect the existing `_is_operational_client`
gate, and reuse existing collections (messages, plan_live_v2, check_ins,
users). No new schemas, no new messaging semantics — spec §39.
"""
from __future__ import annotations
import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException, Query
from server import api, db, require_role  # noqa: E402
from feature_v2_coach_home import _is_operational_client  # noqa: E402


def _initials(name: Optional[str]) -> str:
    if not name:
        return "??"
    parts = [p for p in str(name).strip().split() if p]
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def _client_subtype(u: dict) -> Optional[str]:
    """Small, non-authoritative professional label for the header. Only
    surfaces values the profile actually stored."""
    prof = u.get("profile") or {}
    role = (prof.get("professional_role") or prof.get("role_label")
            or prof.get("crew_role") or "").strip()
    if not role:
        return None
    role_l = role.lower()
    if "pilot" in role_l:
        subtype = "Pilot"
    elif "cabin" in role_l or "attendant" in role_l or "crew" in role_l:
        subtype = "Cabin Crew"
    else:
        subtype = role.title()
    airline = (prof.get("airline") or prof.get("employer") or "").strip()
    return f"{subtype} · {airline}" if airline else subtype


# ---------------------------------------------------------------------------
# Inbox — one document per partner, with latest message + unread count.
# ---------------------------------------------------------------------------
@api.get("/coach/inbox")
async def coach_inbox(
    include_test: bool = Query(False),
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return every client (partner) the coach might have a conversation
    with, sorted by unread first then most-recent activity.

    Reuses the existing `db.messages` collection — no new schema.
    """
    coach_id = coach["id"]

    # Candidate clients: either explicitly linked to this coach OR every
    # client (fallback behaviour mirrors `GET /messages`).
    clients = await db.users.find(
        {"role": "client", "coach_id": coach_id},
        {"_id": 0, "password_hash": 0},
    ).to_list(500)
    if not clients:
        clients = await db.users.find(
            {"role": "client"},
            {"_id": 0, "password_hash": 0},
        ).to_list(500)
    if not include_test:
        clients = [c for c in clients if _is_operational_client(c)
                   and (c.get("status") or "").lower() not in {"archived", "deletion_pending", "suspended", "deleted"}
                   and not c.get("archived_at")
                   # Filter tagged test accounts (crew_base convention)
                   and not (set(c.get("tags") or []) & {"sandbox", "test", "reviewer", "qa"})
                   # Filter emails that end in .local or contain 'cbtest'
                   and "cbtest" not in (c.get("email") or "").lower()]

    client_ids = [c["id"] for c in clients]
    if not client_ids:
        return {"conversations": []}

    # Latest message per (coach ↔ client) pair — use an aggregation pipeline.
    pipeline = [
        {"$match": {
            "$or": [
                {"from_user_id": coach_id, "to_user_id": {"$in": client_ids}},
                {"to_user_id": coach_id, "from_user_id": {"$in": client_ids}},
            ],
            # Hide un-landed scheduled messages the same way threads do.
            "$and": [{
                "$or": [
                    {"visible_from": {"$exists": False}},
                    {"visible_from": {"$lte": _dt.datetime.now(_dt.timezone.utc).isoformat()}},
                ],
            }],
        }},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": {
                "$cond": [
                    {"$eq": ["$from_user_id", coach_id]},
                    "$to_user_id",
                    "$from_user_id",
                ],
            },
            "latest_text": {"$first": "$text"},
            "latest_at": {"$first": "$created_at"},
            "latest_from": {"$first": "$from_user_id"},
        }},
    ]
    latest_by_client: dict[str, dict] = {}
    async for r in db.messages.aggregate(pipeline):
        latest_by_client[r["_id"]] = r

    # Unread counts per client (client → coach messages that are unread)
    unread_counts: dict[str, int] = {}
    async for r in db.messages.aggregate([
        {"$match": {
            "to_user_id": coach_id,
            "from_user_id": {"$in": client_ids},
            "read": {"$ne": True},
        }},
        {"$group": {"_id": "$from_user_id", "n": {"$sum": 1}}},
    ]):
        unread_counts[r["_id"]] = int(r.get("n") or 0)

    # Iter 165b · Pending check-in indicator per client.
    # Sources (any-of):
    #   1. coach_tasks with task_type=check_in_review + status=todo
    #   2. check_ins with coach_review_status=pending
    #   3. reality_events with status=ask_coach (legacy signal, kept
    #      for backward compat with existing rows)
    pending_checkin: dict[str, dict] = {}
    async for r in db.coach_tasks.aggregate([
        {"$match": {
            "user_id": {"$in": client_ids},
            "task_type": "check_in_review",
            "status": "todo",
        }},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}, "latest": {"$max": "$created_at"}}},
    ]):
        pending_checkin[r["_id"]] = {"count": int(r["n"]), "at": r.get("latest"), "source": "coach_task"}
    async for r in db.check_ins.aggregate([
        {"$match": {
            "user_id": {"$in": client_ids},
            "coach_review_status": "pending",
        }},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}, "latest": {"$max": "$submitted_at"}}},
    ]):
        if r["_id"] not in pending_checkin:
            pending_checkin[r["_id"]] = {"count": int(r["n"]), "at": r.get("latest"), "source": "check_in"}
        else:
            pending_checkin[r["_id"]]["count"] += int(r["n"])
    async for r in db.reality_events.aggregate([
        {"$match": {
            "user_id": {"$in": client_ids},
            "status": "ask_coach",
        }},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}, "latest": {"$max": "$created_at"}}},
    ]):
        if r["_id"] not in pending_checkin:
            pending_checkin[r["_id"]] = {"count": int(r["n"]), "at": r.get("latest"), "source": "reality_event"}
        else:
            pending_checkin[r["_id"]]["count"] += int(r["n"])

    out = []
    for c in clients:
        cid = c["id"]
        latest = latest_by_client.get(cid) or {}
        name = c.get("display_name") or c.get("name") or c.get("email") or "(unnamed)"
        checkin_info = pending_checkin.get(cid)
        out.append({
            "id": cid,
            "name": name,
            "avatar_url": c.get("avatar_url") or (c.get("profile") or {}).get("avatar_url"),
            "initials": _initials(name),
            "subtype": _client_subtype(c),
            "latest": {
                "text": (latest.get("latest_text") or "")[:280],
                "at": latest.get("latest_at"),
                "from_me": bool(latest.get("latest_from") == coach_id),
            } if latest else None,
            "unread_count": int(unread_counts.get(cid, 0)),
            # Iter 165b · Pending check-in indicator — surfaced as a small
            # red dot / label in the coach Messages sidebar.
            "pending_checkin": bool(checkin_info),
            "pending_checkin_count": int((checkin_info or {}).get("count") or 0),
            "pending_checkin_source": (checkin_info or {}).get("source"),
        })

    # Sort: unread first (desc), then latest activity descending, then name.
    def _key(row: dict):
        latest_at = (row.get("latest") or {}).get("at") or ""
        # Iter 165b · Rows with a pending check-in float alongside unread
        # so the coach sees them near the top of the sidebar.
        checkin_boost = 1 if row.get("pending_checkin") else 0
        return (-(row["unread_count"] + checkin_boost), -1 if latest_at else 0, latest_at, row["name"])
    out.sort(key=_key, reverse=True)
    return {"conversations": out}


# ---------------------------------------------------------------------------
# Client context bundle — for the right panel.
# ---------------------------------------------------------------------------
@api.get("/coach/client-context/{client_id}")
async def coach_client_context(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    u = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(404, "client not found")

    name = u.get("display_name") or u.get("name") or "(unnamed)"
    prof = u.get("profile") or {}

    # Goal / phase / plan_state — pulled from the current active Live plan.
    goal_label = None
    phase_label = None
    plan_state = None
    next_session = None
    live = await db.plan_live_v2.find_one(
        {"client_id": client_id, "active": True},
        {"_id": 0, "planning_window": 1, "goals": 1, "phase_kind": 1, "placements": 1, "session_specs": 1},
    )
    if live:
        plan_state = "Live"
        goals = live.get("goals") or []
        if isinstance(goals, list) and goals:
            g = goals[0]
            if isinstance(g, dict):
                goal_label = (g.get("label") or g.get("kind") or "").replace("_", " ").title() or None
            elif isinstance(g, str):
                goal_label = g.replace("_", " ").title()
        phase = live.get("phase_kind")
        if phase:
            phase_label = str(phase).replace("_", " ").title()

        # Next non-rest placement on or after today
        today_iso = _dt.date.today().isoformat()
        upcoming = [p for p in (live.get("placements") or [])
                    if (p.get("date") or "") >= today_iso and p.get("kind") != "rest"]
        upcoming.sort(key=lambda p: p.get("date") or "")
        if upcoming:
            first = upcoming[0]
            specs = live.get("session_specs") or {}
            if not isinstance(specs, dict):
                specs = {s.get("exposure_id"): s for s in specs if isinstance(s, dict)}
            spec = specs.get(first.get("exposure_id") or "") or {}
            label = (spec.get("label") or spec.get("spec_kind") or first.get("kind") or "Session")
            next_session = {
                "date": first.get("date"),
                "label": str(label).replace("_", " ").title(),
            }
    else:
        # Not currently on a Live plan
        drafted = await db.plan_drafts_v2.find_one(
            {"client_id": client_id, "status": {"$ne": "archived"}},
            {"_id": 0, "status": 1},
        )
        plan_state = "Draft" if drafted else None

    if not goal_label:
        # Fallback — profile goal string
        g = (prof.get("goal") or prof.get("primary_goal") or "").strip()
        if g:
            goal_label = g.replace("_", " ").title()

    # Latest check-in
    latest_checkin = None
    ci = await db.check_ins.find_one(
        {"user_id": client_id},
        {"_id": 0, "week_start": 1, "coach_reviewed": 1, "coach_reviewed_at": 1, "submitted_at": 1, "status": 1},
        sort=[("week_start", -1)],
    )
    if ci:
        if ci.get("coach_reviewed"):
            state = "Reviewed"
        elif ci.get("status") == "submitted" or ci.get("submitted_at"):
            state = "Needs Review"
        else:
            state = "Open"
        latest_checkin = {
            "week_start": ci.get("week_start"),
            "state": state,
        }

    # Optional: pinned notes — reuse coach client-note if available.
    pinned_notes = None
    try:
        note = await db.coach_client_notes.find_one(
            {"client_id": client_id, "pinned": True},
            {"_id": 0, "text": 1, "updated_at": 1},
        )
        if note:
            pinned_notes = {"text": (note.get("text") or "").strip()[:500], "updated_at": note.get("updated_at")}
    except Exception:
        pinned_notes = None

    return {
        "identity": {
            "id": client_id,
            "name": name,
            "initials": _initials(name),
            "avatar_url": u.get("avatar_url") or prof.get("avatar_url"),
            "subtype": _client_subtype(u),
            "email": u.get("email"),
        },
        "goal": goal_label,
        "phase": phase_label,
        "plan_state": plan_state,
        "next_session": next_session,
        "latest_checkin": latest_checkin,
        "pinned_notes": pinned_notes,
    }
