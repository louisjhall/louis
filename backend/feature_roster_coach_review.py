"""
Iter186 — Roster coach-review state machine.

Purpose
-------
After a client uploads and confirms their roster, the client is LOCKED out
of re-uploading (and the upload screen is replaced with a success/lock
card) until one of the following happens:

  1. Coach explicitly clicks APPROVE  → state = ``coach_approved``.
  2. Coach explicitly clicks REQUEST NEW UPLOAD → state = ``coach_rejected``.
     Client can re-upload.
  3. 24 h elapse without coach action → auto-flip to ``coach_approved`` +
     drop a Louis chat message. Prevents the client from being trapped
     if the coach never opens the app.

State machine
-------------
::

    ┌────────┐  client uploads   ┌────────────┐  BG parses   ┌──────────────────────────┐
    │  none  │──────────────────▶│ processing │─────────────▶│ awaiting_client_confirm  │
    └────────┘                   └────────────┘              └──────────────────────────┘
                                                                       │  client confirms
                                                                       ▼
                                                          ┌─────────────────────────────┐
                                                          │  awaiting_coach_review      │
                                                          └─────────────────────────────┘
                                            coach APPROVE / │       │  \  coach REJECT / new upload
                                                24-h tick   ▼       ▼   \
                                       ┌────────────────┐  ┌───────────────────┐
                                       │ coach_approved │  │  coach_rejected   │
                                       └────────────────┘  └───────────────────┘

Endpoints
---------
* ``GET  /api/roster/submission-state``
    Client-facing. Returns a single object the client screen keys off.
* ``POST /api/coach/rosters/{rid}/review``
    Body: ``{"outcome": "approved" | "rejected"}``. Coach-only.
* ``GET  /api/coach/rosters-awaiting-review``
    Coach-only. Returns ``{"count": N, "clients": [...]}`` for the sidebar
    badge on the coach v2-home.

Fields written to ``db.rosters``
--------------------------------
* ``coach_review_state``      : "awaiting_review" | "approved" | "rejected"
* ``coach_review_at``         : ISO string, when coach acted (or 24 h auto)
* ``coach_review_actor``      : "coach" | "auto_24h"
* ``coach_review_reviewer_id``: coach user id (null for auto)
* ``awaiting_review_since``   : ISO — set once, drives the 24 h tick

Idempotency
-----------
Every write is guarded by ``coach_review_state`` so re-runs are no-ops.
Auto-approve tick queries only rosters whose state is ``awaiting_review``
AND whose ``awaiting_review_since`` is older than 24 h.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

AUTO_APPROVE_HOURS = 24

# Louis auto-approve message pool — reused from review-delay so voice
# stays consistent. Kept short so it doesn't clog the chat.
AUTO_APPROVE_MESSAGE = (
    "Your programme is live — I've had a look and you're all set. "
    "Yell if anything doesn't sit right."
)


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# STATE COMPUTATION — client-facing "what should we show?" reducer.
# ---------------------------------------------------------------------------
async def compute_submission_state(db, user: dict) -> dict:
    """Compute the client-facing roster submission state.

    Returns a JSON-serialisable dict — see module docstring for shape.
    """
    user_id = user.get("id")
    if not user_id:
        return {"state": "none"}

    # 1. Active upload job? If any parse job is currently in flight for
    #    this user, we're in `processing`.
    try:
        job = await db.roster_jobs.find_one(
            {"user_id": user_id, "status": {"$in": ["queued", "processing"]}},
            sort=[("created_at", -1)],
        )
    except Exception:
        job = None
    if job:
        return {
            "state": "processing",
            "job_id": job.get("id"),
            "job_status": job.get("status"),
            "job_stage": job.get("stage"),
            "progress": int(job.get("progress") or 0),
            "message": job.get("message"),
        }

    # 2. Pending confirmation? A parsed roster is waiting for the client
    #    to confirm duties on `/roster/confirm/[id]`.
    try:
        pending = await db.rosters.find_one(
            {"user_id": user_id, "status": "pending_confirmation"},
            sort=[("created_at", -1)],
        )
    except Exception:
        pending = None
    if pending:
        return {
            "state": "awaiting_client_confirmation",
            "pending_roster_id": pending.get("id"),
            "submitted_at": pending.get("created_at"),
        }

    # 3. Any roster with coach_review_state? Pick the newest one that
    #    represents the client's current lock state.
    try:
        latest = await db.rosters.find_one(
            {
                "user_id": user_id,
                "coach_review_state": {"$in": ["awaiting_review", "approved", "rejected"]},
            },
            sort=[("awaiting_review_since", -1), ("created_at", -1)],
        )
    except Exception:
        latest = None
    if latest:
        state_map = {
            "awaiting_review": "awaiting_coach_review",
            "approved": "coach_approved",
            "rejected": "coach_rejected",
        }
        state = state_map.get(str(latest.get("coach_review_state") or ""), "none")
        return {
            "state": state,
            "roster_id": latest.get("id"),
            "submitted_at": latest.get("confirmed_at") or latest.get("created_at"),
            "awaiting_review_since": latest.get("awaiting_review_since"),
            "coach_review_at": latest.get("coach_review_at"),
            "coach_review_actor": latest.get("coach_review_actor"),
        }

    # 4. Backward-compat: legacy rosters that pre-date this feature (i.e.
    #    were confirmed BEFORE we started stamping `coach_review_state`).
    #
    #    Iter186 fix · The very first cohort of rosters that confirmed
    #    *between* the frontend Publish and the backend redeploy will
    #    have `is_active=True` but no `coach_review_state`. If we naively
    #    treat every legacy roster as `coach_approved` we'd never show
    #    the lock card for those clients, which is the exact bug the
    #    coach reported after the first roll-out. Fix: bucket recent
    #    (< 24 h) legacy confirmations as `awaiting_coach_review` so the
    #    UX matches what the client experienced (they *just* confirmed),
    #    and stamp them so the coach inbox picks them up too.
    try:
        legacy = await db.rosters.find_one(
            {"user_id": user_id, "is_active": True},
            sort=[("confirmed_at", -1), ("created_at", -1)],
        )
    except Exception:
        legacy = None
    if legacy:
        confirmed_at = legacy.get("confirmed_at") or legacy.get("created_at") or ""
        recent = False
        try:
            if confirmed_at:
                ts = _dt.datetime.fromisoformat(str(confirmed_at).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_dt.timezone.utc)
                recent = (_now_utc() - ts) < _dt.timedelta(hours=AUTO_APPROVE_HOURS)
        except Exception:
            recent = False

        if recent:
            # Best-effort stamp so the coach inbox picks this up on the
            # very next refresh. Ignored if it fails — the state we
            # return below is what the client screen keys off.
            try:
                await db.rosters.update_one(
                    {"id": legacy["id"], "coach_review_state": {"$exists": False}},
                    {"$set": {
                        "coach_review_state": "awaiting_review",
                        "awaiting_review_since": confirmed_at or _iso(_now_utc()),
                    }},
                )
            except Exception:
                logger.exception("legacy-stamp failed for %s", legacy.get("id"))
            return {
                "state": "awaiting_coach_review",
                "roster_id": legacy.get("id"),
                "submitted_at": confirmed_at,
                "awaiting_review_since": confirmed_at,
                "legacy_backfill": True,
            }

        return {
            "state": "coach_approved",
            "roster_id": legacy.get("id"),
            "submitted_at": confirmed_at,
            "legacy_backfill": True,
        }

    return {"state": "none"}


# ---------------------------------------------------------------------------
# STATE WRITE — called by feature_roster_confirmation when client confirms.
# ---------------------------------------------------------------------------
async def mark_awaiting_coach_review(db, roster: dict) -> None:
    """Called immediately after a roster transitions to confirmed / active.

    Idempotent — if `coach_review_state` already set on this roster, do
    nothing so we don't clobber a coach's earlier approval.
    """
    if not roster or not roster.get("id"):
        return
    if roster.get("coach_review_state"):
        return  # idempotent — already stamped
    now_iso = _iso(_now_utc())
    try:
        await db.rosters.update_one(
            {"id": roster["id"], "coach_review_state": {"$exists": False}},
            {"$set": {
                "coach_review_state": "awaiting_review",
                "awaiting_review_since": now_iso,
            }},
        )
    except Exception:
        logger.exception("mark_awaiting_coach_review failed for %s", roster.get("id"))


# ---------------------------------------------------------------------------
# 24-HOUR AUTO-APPROVE TICK — safety net so client is never permanently
# locked out if the coach never opens the app. Runs from the reminder tick.
# ---------------------------------------------------------------------------
async def _tick_auto_approve_stale_reviews(db, enqueue_message=None) -> int:
    """Flip any roster in `awaiting_review` older than 24 h → `approved`.

    Also drops a Louis chat message so the client sees something the moment
    the auto-approve fires (matches product copy: "we'll notify you when
    it's ready").

    Returns the number of rosters auto-approved.
    """
    cutoff_iso = _iso(_now_utc() - _dt.timedelta(hours=AUTO_APPROVE_HOURS))
    approved = 0
    try:
        stale = db.rosters.find({
            "coach_review_state": "awaiting_review",
            "awaiting_review_since": {"$lte": cutoff_iso},
        })
        async for r in stale:
            try:
                await _do_approve(db, r, actor="auto_24h", reviewer_id=None)
                approved += 1
            except Exception:
                logger.exception("auto-approve failed for roster %s", r.get("id"))
    except Exception:
        logger.exception("auto-approve tick query failed")
    return approved


async def _do_approve(db, roster: dict, *, actor: str, reviewer_id: Optional[str]) -> None:
    """Common approve-write used by both explicit coach action and the
    24-h auto-approve tick. Drops a Louis chat message and stamps the
    roster with the review metadata.

    ``actor`` is one of ``"coach"`` or ``"auto_24h"``.
    """
    if not roster or not roster.get("id"):
        return
    rid = roster["id"]
    user_id = roster.get("user_id")
    now = _iso(_now_utc())

    # Idempotent: only write if not already approved/rejected.
    res = await db.rosters.update_one(
        {"id": rid, "coach_review_state": "awaiting_review"},
        {"$set": {
            "coach_review_state": "approved",
            "coach_review_at": now,
            "coach_review_actor": actor,
            "coach_review_reviewer_id": reviewer_id,
        }},
    )
    if res.modified_count == 0:
        return  # someone else already acted

    # Iter187 · Push + in-app notification the moment a roster flips to
    # `approved`. Fires for BOTH explicit coach approval and the 24-h
    # auto-approve tick — clients care about the outcome, not the actor.
    # Lazy import to avoid a circular dependency with feature_notifications
    # which itself imports from `server`.
    if user_id:
        try:
            from feature_notifications import notify_roster_approved
            await notify_roster_approved(user_id, roster_id=rid)
        except Exception:
            logger.exception("roster-approved notify failed for %s", rid)

    # Louis chat message — only for the auto-approve path so we don't
    # spam when the coach explicitly clicked (the coach usually messages
    # anyway right after). Feature-flag via caller if we want to change.
    if actor == "auto_24h" and user_id:
        try:
            coach_id = None
            client_user = await db.users.find_one({"id": user_id}, {"_id": 0})
            if client_user:
                coach_id = client_user.get("assigned_coach_id") or client_user.get("coach_id")
            msg_id = f"m_autoapprove_{rid[-10:]}"
            await db.messages.insert_one({
                "id": msg_id,
                "from_user_id": coach_id,
                "to_user_id": user_id,
                "sender_id": coach_id,
                "sender_name": (client_user or {}).get("assigned_coach_name") or "Louis Hall",
                "body": AUTO_APPROVE_MESSAGE,
                "text": AUTO_APPROVE_MESSAGE,
                "created_at": now,
                "auto_kind": "roster_auto_approve",
                "roster_id": rid,
                "read": False,
            })
        except Exception:
            logger.exception("auto-approve Louis message insert failed for roster %s", rid)


async def _do_reject(db, roster: dict, *, reviewer_id: str) -> None:
    """Coach explicitly requests a new upload. Client is un-locked and can
    upload again. We DON'T deactivate the roster document itself — the
    coach may still want to reference it for the next upload — but we do
    mark it so the client sees the rejection state on the lock card."""
    if not roster or not roster.get("id"):
        return
    now = _iso(_now_utc())
    await db.rosters.update_one(
        {"id": roster["id"], "coach_review_state": "awaiting_review"},
        {"$set": {
            "coach_review_state": "rejected",
            "coach_review_at": now,
            "coach_review_actor": "coach",
            "coach_review_reviewer_id": reviewer_id,
        }},
    )


# ---------------------------------------------------------------------------
# API — factory pattern so server.py can wire in the shared db + user deps.
# ---------------------------------------------------------------------------
class ReviewOutcomeBody(BaseModel):
    outcome: str  # "approved" | "rejected"


def make_router(db, current_user, require_role) -> APIRouter:
    r = APIRouter()

    @r.get("/roster/submission-state")
    async def _roster_submission_state(user: dict = Depends(current_user)):
        return await compute_submission_state(db, user)

    @r.post("/coach/rosters/{rid}/review")
    async def _coach_review(rid: str, body: ReviewOutcomeBody, coach: dict = Depends(require_role("coach"))):
        outcome = (body.outcome or "").strip().lower()
        if outcome not in ("approved", "rejected"):
            raise HTTPException(400, "outcome must be 'approved' or 'rejected'")
        roster = await db.rosters.find_one({"id": rid}, {"_id": 0})
        if not roster:
            raise HTTPException(404, "Roster not found")
        if outcome == "approved":
            await _do_approve(db, roster, actor="coach", reviewer_id=coach["id"])
        else:
            await _do_reject(db, roster, reviewer_id=coach["id"])
        fresh = await db.rosters.find_one({"id": rid}, {"_id": 0})
        return {"ok": True, "roster": fresh}

    @r.get("/coach/rosters-awaiting-review")
    async def _coach_awaiting_review(coach: dict = Depends(require_role("coach"))):
        """Return the list of rosters awaiting THIS coach's review.

        Filters on `users.assigned_coach_id == coach.id` so a coach sees
        only their own clients (head coaches see everyone via a separate
        endpoint if we ever add one; for MVP we scope by assignment).
        """
        try:
            # Find client user ids assigned to this coach.
            my_clients = await db.users.find(
                {"role": "client", "assigned_coach_id": coach["id"]},
                {"_id": 0, "id": 1, "first_name": 1, "last_name": 1, "email": 1},
            ).to_list(500)
            client_ids = [c["id"] for c in my_clients if c.get("id")]
            if not client_ids:
                return {"count": 0, "clients": []}
            rows = await db.rosters.find(
                {"user_id": {"$in": client_ids}, "coach_review_state": "awaiting_review"},
                {"_id": 0, "id": 1, "user_id": 1, "awaiting_review_since": 1, "start_date": 1, "end_date": 1},
            ).sort("awaiting_review_since", 1).to_list(200)
            client_map = {c["id"]: c for c in my_clients}
            enriched = [
                {
                    **row,
                    "client_first_name": client_map.get(row["user_id"], {}).get("first_name"),
                    "client_last_name":  client_map.get(row["user_id"], {}).get("last_name"),
                }
                for row in rows
            ]
            return {"count": len(enriched), "clients": enriched}
        except Exception:
            logger.exception("coach rosters-awaiting-review query failed")
            return {"count": 0, "clients": []}

    return r
