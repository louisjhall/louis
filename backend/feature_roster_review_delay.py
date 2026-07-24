"""
Iter 95n — Roster review delay (aka "Louis is looking over your week")

Purpose
-------
After a client uploads a roster, the workouts land in the database instantly
(so the coach can still see + tweak them from the demand queue), but they are
**hidden from the client** for ~12-20 minutes with a jittered `visible_from`
timestamp. During that window the home dashboard shows a "Louis is reviewing
your roster" placeholder. When the window elapses, the workouts light up in
the calendar and a short Louis chat message lands in the inbox.

Design goals
------------
* No frontend cron / background daemon — everything is data-driven off two
  fields (`visible_from` on workouts + messages, `programme_release_at` on
  roster) so restarts / cold-starts never lose state.
* Absolutely zero manual coach action — Louis's message is auto-selected from
  a rotating pool that never mentions specific roster details (safer if the
  parser mis-classified a duty).
* Coach dashboard is unaffected — the coach always sees the workouts, so they
  can intervene during the review window if needed.
* Fully idempotent — re-running for the same roster is a no-op.

Callers
-------
* server.py roster upload flow calls `apply_review_delay(...)` once, right
  after workouts are persisted.
* Home dashboard hits `GET /roster/status` to decide whether to show the
  placeholder.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import random
from typing import Any, Optional

from fastapi import APIRouter, Depends

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Louis message pool — deliberately generic. No cities, no flight numbers, no
# duty codes. Safe against parser errors and stays warm without over-claiming.
# ---------------------------------------------------------------------------
LOUIS_ACK_MESSAGES: list[str] = [
    "Roster's in. Read through it and applied your week. Message me if anything doesn't feel right.",
    "Uploaded, read, done. Kept it realistic around your flying. Yell if you want to tweak anything.",
    "Been through your week. Prioritised the days you're home for the harder work — everything else stays manageable. Let me know how you get on.",
    "Read your roster. Kept the load honest, nothing you can't do around the flying. Ping me if anything jars.",
    "Right, week's ready. Kept it simple and doable. Save the harder stuff for when I know you're rested.",
    "Programme's set. If your roster changes mid-week, upload the new one and I'll rework it. Simple.",
    "Roster reviewed. Trust the plan — anything feels off, I'll change it.",
    "Sent through. Focus on the KEY session, ease into the rest. Any injuries or aches to flag, tell me now.",
    "Had a look at your week. Kept it honest — nothing heroic, nothing lazy. Move if you can, rest when you should.",
    "Done. Load's balanced around your flying, so no surprises. Get after the KEY session, treat the rest as bonus.",
    "Week's in. Any doubts on any session, message me before you start — quicker than skipping it.",
    "Sorted. Kept the plan tight around your report times. If you're already knackered before a session, tell me and I'll trim.",
    "Reviewed and applied. Nothing overly ambitious this week — you don't need heroics, you need consistency.",
    "Sent. If a day suddenly turns into a delay or standby, tap into the mobility flow instead. Same benefit, half the fuss.",
    "Been over your week. Built to fit real crew life — you'll finish everything if you show up.",
    "Roster in, plan out. Same rules as always: KEY session non-negotiable, rest is flexible.",
    "Programme sent. If a hotel gym looks grim, everything I've planned works with just a mat.",
    "Read your week. If anything feels wrong when you're doing it, stop and message. That's what I'm here for.",
]

# ---------------------------------------------------------------------------
# Delay window — jittered 12–20 min so consecutive uploads don't look
# programmed. Change here if the product decides on a different range.
# ---------------------------------------------------------------------------
DELAY_MIN_SECONDS = 12 * 60
DELAY_MAX_SECONDS = 20 * 60
DELAY_UI_PROMISE_MINUTES = 20  # what the frontend tells the client ("within X min")


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _iso(dt: _dt.datetime) -> str:
    return dt.isoformat()


def _pick_message(user_id: str, roster_id: str, recent_body: Optional[str]) -> str:
    """Pick a message from the pool that isn't the same as the most recent
    one for this user. Uses a hashed seed so re-runs for the same roster get
    the same message (idempotent)."""
    seed = int(hashlib.sha1(f"{user_id}:{roster_id}".encode()).hexdigest(), 16)
    rng = random.Random(seed)
    ordered = LOUIS_ACK_MESSAGES[:]
    rng.shuffle(ordered)
    for candidate in ordered:
        if candidate != (recent_body or ""):
            return candidate
    return ordered[0]


async def apply_review_delay(db, user: dict, roster: dict) -> dict:
    """Attach a jittered `visible_from` timestamp to every workout that
    belongs to this roster, mark the roster with `programme_release_at`,
    and enqueue a Louis chat message that lands at the same moment.

    Idempotent — if `programme_release_at` is already set on the roster, this
    is a no-op and the existing value is returned.
    """
    user_id = user.get("id")
    roster_id = roster.get("id")
    if not user_id or not roster_id:
        return {"ok": False, "reason": "missing user_id or roster_id"}

    # Idempotency guard — if we already stamped this roster, don't touch it.
    existing = roster.get("programme_release_at")
    if existing:
        return {"ok": True, "unlocks_at": existing, "message_id": roster.get("programme_ack_message_id"), "reused": True}

    now = _now_utc()
    delay_seconds = random.randint(DELAY_MIN_SECONDS, DELAY_MAX_SECONDS)
    unlocks_at = now + _dt.timedelta(seconds=delay_seconds)
    unlocks_iso = _iso(unlocks_at)

    # 1. Hide every workout for this roster until `unlocks_at`.
    try:
        await db.workouts.update_many(
            {"user_id": user_id, "roster_id": roster_id, "visible_from": {"$exists": False}},
            {"$set": {"visible_from": unlocks_iso}},
        )
    except Exception:
        logger.exception("apply_review_delay: workouts.update_many failed")

    # 2. Pick + insert the Louis chat message, scheduled for the same moment.
    coach_id = user.get("assigned_coach_id") or user.get("coach_id")
    coach_name = user.get("assigned_coach_name") or "Louis Hall"
    recent = None
    try:
        recent_row = await db.messages.find_one(
            {"user_id": user_id, "sender_id": coach_id, "auto_kind": "roster_ack"},
            sort=[("created_at", -1)],
        )
        recent = (recent_row or {}).get("body")
    except Exception:
        recent = None
    body = _pick_message(user_id, roster_id, recent)

    message_id = f"m_ack_{roster_id[-10:]}"
    try:
        # Same collection the client-facing chat reads from. `visible_from`
        # is honoured by the messages read filter added alongside this feature.
        await db.messages.insert_one({
            "id": message_id,
            "from_user_id": coach_id,   # Louis is the sender
            "to_user_id": user_id,      # ...to the client
            "sender_id": coach_id,
            "sender_name": coach_name,
            "body": body,
            "text": body,               # some UIs read either key
            "created_at": unlocks_iso,  # timestamp reads as "just now" when it lands
            "visible_from": unlocks_iso,
            "auto_kind": "roster_ack",
            "roster_id": roster_id,
            "read": False,
        })
    except Exception:
        logger.exception("apply_review_delay: messages.insert_one failed")

    # 3. Stamp the roster so subsequent calls are idempotent and so
    # `/roster/status` can compute the placeholder state cheaply.
    try:
        await db.rosters.update_one(
            {"id": roster_id},
            {"$set": {
                "programme_release_at": unlocks_iso,
                "programme_ack_message_id": message_id,
                "programme_review_started_at": _iso(now),
            }},
        )
    except Exception:
        logger.exception("apply_review_delay: rosters.update_one failed")

    return {"ok": True, "unlocks_at": unlocks_iso, "message_id": message_id, "reused": False}


async def get_roster_status(db, user: dict) -> dict:
    """Return the current review-delay state for the client's active roster.

    Response shape:
      {
        "status": "reviewing" | "ready" | "none",
        "unlocks_at":  ISO timestamp or None,
        "eta_minutes": rough minutes until unlock (rounded up),
        "promise_minutes": what we told the UI to say ("within 20 min"),
      }
    """
    user_id = user.get("id")
    if not user_id:
        return {"status": "none"}

    try:
        roster = await db.rosters.find_one(
            {"user_id": user_id, "is_active": True},
            sort=[("created_at", -1)],
        )
    except Exception:
        roster = None
    if not roster:
        return {"status": "none"}

    unlocks_at = roster.get("programme_release_at")
    if not unlocks_at:
        return {"status": "ready"}

    try:
        due = _dt.datetime.fromisoformat(unlocks_at.replace("Z", "+00:00"))
    except Exception:
        return {"status": "ready"}
    now = _now_utc()
    if now >= due:
        return {"status": "ready", "unlocks_at": unlocks_at}

    remaining = (due - now).total_seconds()
    eta = max(1, int(remaining // 60) + (1 if remaining % 60 else 0))
    return {
        "status": "reviewing",
        "unlocks_at": unlocks_at,
        "eta_minutes": eta,
        "promise_minutes": DELAY_UI_PROMISE_MINUTES,
    }


# ---------------------------------------------------------------------------
# Read-side helper — used by workouts + messages endpoints so pending items
# don't leak to the client during the review window. Coach endpoints do NOT
# call this (they must see everything).
# ---------------------------------------------------------------------------
def prune_pending(docs: list[dict]) -> list[dict]:
    """Remove any doc whose `visible_from` is still in the future."""
    if not docs:
        return docs
    now_iso_val = _iso(_now_utc())
    out: list[dict] = []
    for d in docs:
        vf = d.get("visible_from")
        if not vf or vf <= now_iso_val:
            out.append(d)
    return out


# ---------------------------------------------------------------------------
# Router — a single lightweight status endpoint the frontend polls.
# Server.py wires this into its main api router at startup.
# ---------------------------------------------------------------------------
def make_router(db, current_user) -> APIRouter:
    r = APIRouter()

    @r.get("/roster/status")
    async def _roster_status(user: dict = Depends(current_user)):
        return await get_roster_status(db, user)

    return r
