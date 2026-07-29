"""
CrewFit — Coach Home Action Queue (Iter 128g)
==============================================

Deterministic aggregator that answers **"what needs the coach's attention
right now?"**. Home is *not* an event log or validation dump — it is the
operational action queue.

Design rules
------------
- Derive tasks from **current state**, not historical events.
- **One task per actionable problem** per client (aggregate underlying
  issues, don't spam one row per exception).
- Tasks disappear automatically when the underlying state resolves.
- No LLM calls. No new task collection. Reuse authoritative V2 state
  (plan_drafts_v2, plan_live_v2, schedule_days, reality_events, messages,
  users.profile).
- Uses **stable dedupe keys** so repeated events don't create duplicate rows.
- Coach-facing language only. No `validator.ok`, `opportunity`, `floor`,
  `exposure_sequence`, `V1/V2` etc. leaks into the coach UX.

Endpoints (all `coach` role required)
-------------------------------------
    GET /api/v2/coach/home/action-queue
        →  {date, counts, needs_attention[], upcoming[], waiting_on_client[]}
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import Depends

from server import api, db, require_role, now_iso

# `_extract_exceptions` and `_ACTIVE_DRAFT_FILTER` live in the publish
# module. Importing here keeps a single source of truth for exception
# derivation — Home *counts* them but never re-implements the classifier.
from feature_v2_engine_v2_publish import (
    _extract_exceptions,
    _ACTIVE_DRAFT_FILTER,
)
from feature_v2_sport_configs import canonicalise_goal_key


# ---------------------------------------------------------------------------
# Task type registry
# ---------------------------------------------------------------------------
#
# priority   → coach-facing urgency band
#              "urgent"    (red)     – blocking, coach cannot proceed
#              "attention" (amber)   – needs coach action today
#              "upcoming"  (neutral) – approaching but not yet a problem
#              "waiting"   (neutral) – no coach action possible; ball is
#                                      in the client's court
#
# Each derived task has a **stable id** so the UI can dedupe across polls.
# Stable-id shape:  <type>:<client_id>[:<scope>]

# Essential DNA fields that genuinely block programme work. Anything not
# listed here is *not* an urgent Home task even if missing.
_ESSENTIAL_DNA_KEYS = (
    "main_goal_key",           # primary goal
    "training_days_per_week",  # scheduling constraint
    "session_duration_min",    # scheduling constraint
)


def _display_name(u: dict) -> str:
    return u.get("display_name") or u.get("name") or u.get("email") or "Client"


def _client_subtitle(u: dict, has_live: bool) -> str:
    """One-line context under the client name: goal + Live/Draft state."""
    goal_key = ((u.get("profile") or {}).get("main_goal_key")) or ""
    label = ""
    if goal_key:
        # Coach-friendly rendering, e.g. running.marathon → "Marathon"
        try:
            canonical = canonicalise_goal_key(goal_key)
            tail = canonical.split(".")[-1]
            label = tail.replace("_", " ").title()
        except Exception:
            label = goal_key.split(".")[-1].replace("_", " ").title()
    if has_live:
        return f"{label} · Live" if label else "Live"
    return label or "New client"


def _humanise_iso(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    try:
        # Trim to compact "X ago"
        t = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = _dt.datetime.now(_dt.timezone.utc)
        delta = now - t.astimezone(_dt.timezone.utc)
        secs = int(delta.total_seconds())
        if secs < 60:      return "just now"
        if secs < 3600:    return f"{secs // 60}m ago"
        if secs < 86_400:  return f"{secs // 3600}h ago"
        return f"{secs // 86_400}d ago"
    except Exception:
        return None


async def _client_tasks(client: dict) -> list[dict]:
    """Return the list of derived Home tasks for one client.

    Deterministic. Reads only current-state collections. No historical
    event replay, no LLM."""
    cid = client["id"]
    name = _display_name(client)
    tasks: list[dict] = []

    # -----------------------------------------------------------
    # Prefetch: current programme state. Nearly every task below
    # depends on whether an active Draft or Live exists.
    # -----------------------------------------------------------
    active_draft = await db.plan_drafts_v2.find_one(
        {"client_id": cid, **_ACTIVE_DRAFT_FILTER},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    active_live = await db.plan_live_v2.find_one(
        {"client_id": cid, "active": True},
        {"_id": 0, "id": 1, "activated_at": 1, "planning_window": 1, "roster_range": 1},
    )
    has_live = bool(active_live)
    has_draft = bool(active_draft)

    # -----------------------------------------------------------
    # 1. Profile blocker — only surface when the *missing* DNA
    #    genuinely prevents programme work. If the client already has
    #    a live plan or an active draft, the coach has clearly
    #    proceeded past those gaps.
    # -----------------------------------------------------------
    if not has_live and not has_draft:
        profile = client.get("profile") or {}
        missing = [k for k in _ESSENTIAL_DNA_KEYS if not profile.get(k)]
        if missing:
            labels_map = {
                "main_goal_key": "main goal",
                "training_days_per_week": "training days",
                "session_duration_min": "session duration",
            }
            labels = ", ".join(labels_map[k] for k in missing)
            tasks.append({
                "id": f"profile_blocker:{cid}",
                "type": "profile_blocker",
                "priority": "urgent",
                "client_id": cid,
                "client_name": name,
                "client_subtitle": _client_subtitle(client, has_live=False),
                "title": "Profile incomplete",
                "context": f"Missing: {labels}",
                "meta": None,
                "action_label": "Complete profile",
                "deep_link": f"/coach/client/{cid}/workspace",
            })

    # -----------------------------------------------------------
    # 2. Programme state (Draft / Live)
    # -----------------------------------------------------------
    if has_draft:
        # Aggregate every underlying issue into one row.
        raw = _extract_exceptions(active_draft)
        resolved = {r.get("exception_id") for r in (active_draft.get("exception_resolutions") or [])}
        blocking = 0
        important = 0
        for e in raw:
            if e["id"] in resolved:
                continue
            if e.get("priority") == "KEY" and e.get("category") in (
                "unfilled_objective", "validator_error", "dna_gap"
            ):
                blocking += 1
            elif e.get("priority") == "IMPORTANT" and e.get("category") in (
                "unfilled_objective", "validator_error", "dna_gap"
            ):
                important += 1
        total_issues = blocking + important

        if total_issues > 0:
            # Draft needs review — coach cannot publish
            context_bits = []
            if total_issues == 1:
                context_bits.append("1 planning issue requires coach review.")
            else:
                context_bits.append(f"{total_issues} planning issues require coach review.")
            meta = "Live plan remains active." if has_live else "No live plan yet."
            tasks.append({
                "id": f"draft_review:{cid}:{active_draft['id']}",
                "type": "draft_review",
                "priority": "urgent" if not has_live else "attention",
                "client_id": cid,
                "client_name": name,
                "client_subtitle": _client_subtitle(client, has_live),
                "title": "New draft needs review",
                "context": " ".join(context_bits),
                "meta": meta,
                "action_label": "Review draft",
                "deep_link": f"/coach/client/{cid}/workspace",
                "counts": {"blocking": blocking, "important": important, "total": total_issues},
            })
        else:
            # Draft is validated — ready to publish
            placements = active_draft.get("placement_map") or []
            n_sessions = len(placements)
            window = (active_draft.get("planning_window") or {})
            window_txt = ""
            if window.get("start") and window.get("end"):
                try:
                    s = _dt.date.fromisoformat(window["start"])
                    window_txt = f"{s.strftime('%b')} planning window"
                except Exception:
                    pass
            context = (f"{n_sessions} sessions" +
                       (f" · {window_txt}" if window_txt else "")) if n_sessions else "Plan ready"
            tasks.append({
                "id": f"ready_to_publish:{cid}:{active_draft['id']}",
                "type": "ready_to_publish",
                "priority": "attention",
                "client_id": cid,
                "client_name": name,
                "client_subtitle": _client_subtitle(client, has_live),
                "title": "Plan ready to publish",
                "context": context,
                "meta": ("Replaces current Live plan." if has_live else "First plan for this client."),
                "action_label": "Review & publish",
                "deep_link": f"/coach/client/{cid}/workspace",
            })
    else:
        # No active draft. If there's a Live and it's ending soon, surface
        # "plan ending" as an UPCOMING (not urgent) reminder.
        if has_live:
            try:
                end_iso = ((active_live.get("planning_window") or {}).get("end")
                           or (active_live.get("roster_range") or {}).get("end"))
                if end_iso:
                    end_d = _dt.date.fromisoformat(end_iso)
                    days_to_end = (end_d - _dt.date.today()).days
                    if 0 <= days_to_end <= 7:
                        tasks.append({
                            "id": f"plan_ending:{cid}:{active_live['id']}",
                            "type": "plan_ending",
                            "priority": "upcoming",
                            "client_id": cid,
                            "client_name": name,
                            "client_subtitle": _client_subtitle(client, has_live),
                            "title": (f"Plan ends in {days_to_end} day"
                                       + ("s" if days_to_end != 1 else "")),
                            "context": f"Plan window ends {end_d.strftime('%d %b %Y')}.",
                            "meta": None,
                            "action_label": "Prepare next plan",
                            "deep_link": f"/coach/client/{cid}/workspace",
                        })
            except Exception:
                pass

    # -----------------------------------------------------------
    # 3. Roster required — client has no roster on file. Only surfaced
    #    when the coach can't proceed (no draft, no live).
    # -----------------------------------------------------------
    if not has_draft and not has_live:
        n_sched = await db.schedule_days.count_documents({"client_id": cid})
        if n_sched == 0:
            # Only add roster_required if we didn't already emit a
            # profile_blocker for this client. The profile is the earlier
            # dependency — coach needs to fix that first.
            already_blocked = any(t["type"] == "profile_blocker" for t in tasks)
            if not already_blocked:
                tasks.append({
                    "id": f"roster_required:{cid}",
                    "type": "roster_required",
                    "priority": "waiting",
                    "client_id": cid,
                    "client_name": name,
                    "client_subtitle": _client_subtitle(client, has_live=False),
                    "title": "Roster required",
                    "context": "Roster needed to build first plan.",
                    "meta": None,
                    "action_label": "Open roster",
                    "deep_link": f"/coach/client/{cid}/workspace",
                })

    # -----------------------------------------------------------
    # 4. Check-in review — reality_events with status=ask_coach are the
    #    canonical "client submitted, coach must respond" signal.
    # -----------------------------------------------------------
    ci = await db.reality_events.find_one(
        {"user_id": cid, "status": "ask_coach"},
        {"_id": 0, "id": 1, "date": 1, "reality_label": 1, "created_at": 1},
        sort=[("created_at", -1)],
    )
    if ci:
        ago = _humanise_iso(ci.get("created_at")) or ""
        tasks.append({
            "id": f"checkin_review:{cid}:{ci['id']}",
            "type": "checkin_review",
            "priority": "attention",
            "client_id": cid,
            "client_name": name,
            "client_subtitle": _client_subtitle(client, has_live),
            "title": "Check-in needs review",
            "context": ci.get("reality_label") or "Awaiting your response.",
            "meta": f"Submitted {ago}" if ago else None,
            "action_label": "Review check-in",
            "deep_link": f"/coach/client/{cid}/workspace",
        })

    # -----------------------------------------------------------
    # 5. Unread message — the most recent unread message from the client
    #    to any coach is surfaced. All older unread from the same client
    #    fold into that one task (single dedupe key).
    # -----------------------------------------------------------
    msg = await db.messages.find_one(
        {"from_user_id": cid, "read": {"$ne": True}},
        {"_id": 0, "id": 1, "body": 1, "created_at": 1, "thread_id": 1},
        sort=[("created_at", -1)],
    )
    if msg:
        ago = _humanise_iso(msg.get("created_at")) or ""
        preview = (msg.get("body") or "").strip().splitlines()[0] if msg.get("body") else ""
        if len(preview) > 90:
            preview = preview[:87] + "…"
        tasks.append({
            "id": f"message:{cid}:{msg.get('thread_id') or msg.get('id')}",
            "type": "message",
            "priority": "attention",
            "client_id": cid,
            "client_name": name,
            "client_subtitle": _client_subtitle(client, has_live),
            "title": "New message",
            "context": f'"{preview}"' if preview else "New message from client.",
            "meta": ago or None,
            "action_label": "Reply",
            "deep_link": f"/coach/client/{cid}/workspace?tab=messages",
        })

    return tasks


# ---------------------------------------------------------------------------
# Sorting + priority bucketing
# ---------------------------------------------------------------------------
_PRIORITY_ORDER = {"urgent": 0, "attention": 1, "upcoming": 2, "waiting": 3, "normal": 4}
_TYPE_ORDER = {
    "profile_blocker":   0,
    "draft_review":      1,
    "ready_to_publish":  2,
    "checkin_review":    3,
    "message":           4,
    "plan_ending":       5,
    "roster_required":   6,
}


def _sort_key(t: dict) -> tuple:
    return (
        _PRIORITY_ORDER.get(t.get("priority") or "normal", 9),
        _TYPE_ORDER.get(t.get("type") or "", 9),
        (t.get("client_name") or "").lower(),
    )


@api.get("/v2/coach/home/action-queue")
async def endpoint_coach_home_action_queue(
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Aggregate the coach's action queue from current V2 state."""
    clients = await db.users.find(
        {"role": "client", "status": {"$ne": "archived"}},
        {"_id": 0, "id": 1, "name": 1, "display_name": 1, "email": 1,
         "profile": 1},
    ).to_list(500)

    all_tasks: list[dict] = []
    for c in clients:
        try:
            items = await _client_tasks(c)
        except Exception:
            # A single client's failure must never poison the whole queue.
            items = []
        all_tasks.extend(items)

    # Split by priority band into the three visible sections.
    needs_attention = [t for t in all_tasks if t["priority"] in ("urgent", "attention")]
    upcoming        = [t for t in all_tasks if t["priority"] == "upcoming"]
    waiting         = [t for t in all_tasks if t["priority"] == "waiting"]

    needs_attention.sort(key=_sort_key)
    upcoming.sort(key=_sort_key)
    waiting.sort(key=_sort_key)

    # Summary counts that power the top summary cards. Each card is a
    # deterministic slice of needs_attention/upcoming — no vanity metrics.
    counts = {
        "needs_action":      len(needs_attention),
        "ready_to_publish":  sum(1 for t in all_tasks if t["type"] == "ready_to_publish"),
        "messages":          sum(1 for t in all_tasks if t["type"] == "message"),
        "checkins":          sum(1 for t in all_tasks if t["type"] == "checkin_review"),
        "upcoming":          len(upcoming),
        "waiting":           len(waiting),
        "active_clients":    len(clients),
    }

    return {
        "date": _dt.date.today().isoformat(),
        "counts": counts,
        "needs_attention": needs_attention,
        "upcoming": upcoming,
        "waiting_on_client": waiting,
        "at": now_iso(),
    }
