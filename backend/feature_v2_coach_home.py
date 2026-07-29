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


# ---------------------------------------------------------------------------
# Client Directory (Iter 128h — CLIENTS page consolidation)
# ---------------------------------------------------------------------------
#
# Answers: "Who do I coach and what is their current coaching state?"
#
# Returns ONE compact row per client with the five columns the coach cares
# about: IDENTITY, GOAL, PLAN STATE, ROSTER STATE, NEXT ACTION.
#
# Reuses `_client_tasks` so the next-action logic is *literally the same*
# as the Home Action Queue — no competing status engine.

_TASK_TYPE_TO_PLAN_STATE = {
    "draft_review":     ("live_plus_draft", "New Draft", "2"),  # tuple placeholder — resolved dynamically
    "ready_to_publish": ("ready", "Ready to publish", None),
}


def _plan_state(has_live: bool, has_draft: bool, draft_needs_review: bool) -> dict:
    """Return the coach-facing plan-state pill data."""
    if has_live and has_draft:
        return {
            "kind": "live_plus_draft",
            "label": "Live",
            "tint": "green",
            "sub": "New Draft" + (" · needs review" if draft_needs_review else ""),
            "sub_tint": "amber",
        }
    if has_draft and not has_live:
        return {
            "kind": "draft_only",
            "label": "Draft",
            "tint": "amber",
            "sub": "Needs review" if draft_needs_review else "Ready to publish",
            "sub_tint": "amber",
        }
    if has_live:
        return {
            "kind": "live",
            "label": "Live",
            "tint": "green",
            "sub": "On track",
            "sub_tint": "dim",
        }
    return {
        "kind": "no_plan",
        "label": "No plan",
        "tint": "dim",
        "sub": None,
        "sub_tint": "dim",
    }


def _roster_state(has_roster: bool, roster_range: Optional[dict],
                   has_draft: bool, has_live: bool) -> dict:
    """Return the coach-facing roster-state pill data.

    We do NOT visualise the full timeline here — Clients page is a directory,
    not a calendar. Just a status word + optional month + updated-N-days ago
    context.
    """
    if not has_roster:
        return {
            "kind": "required" if not (has_draft or has_live) else "missing",
            "label": "Roster required",
            "tint": "amber",
            "sub": "Upload roster to build plan",
        }
    label = "Loaded"
    month_txt = None
    if roster_range and roster_range.get("start"):
        try:
            s = _dt.date.fromisoformat(roster_range["start"])
            month_txt = s.strftime("%b roster")
        except Exception:
            pass
    return {
        "kind": "loaded",
        "label": month_txt or "Roster loaded",
        "tint": "green",
        "sub": label,
    }


def _primary_next_action(tasks: list[dict], has_draft: bool, has_live: bool,
                          has_roster: bool) -> dict:
    """Reduce all a client's tasks to ONE primary next action.

    Priority: urgent > attention > upcoming > waiting. Within a band, use
    _TYPE_ORDER (profile_blocker before draft_review before ready_to_publish
    etc.). Falls back to "Open Client" if nothing needs the coach yet."""
    if tasks:
        # tasks are already emitted in creation order; sort by our band.
        best = sorted(tasks, key=_sort_key)[0]
        return {
            "label": best["action_label"],
            "deep_link": best["deep_link"],
            "priority": best["priority"],
            "task_type": best["type"],
        }
    # Nothing to do — soft "Open" fallback.
    return {
        "label": "Open client",
        "deep_link": None,   # set by caller with client id
        "priority": "normal",
        "task_type": None,
    }


@api.get("/v2/coach/clients/directory")
async def endpoint_coach_clients_directory(
    q: Optional[str] = None,
    filter: Optional[str] = "active",
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return the compact client directory used by the Clients page.

    Filters: `active` (default) · `needs_attention` · `archived`.
    """
    # Base query: role=client, honour archived filter.
    match: dict = {"role": "client"}
    if filter == "archived":
        match["status"] = "archived"
    else:
        match["status"] = {"$ne": "archived"}

    if q:
        match["$or"] = [
            {"name":         {"$regex": q, "$options": "i"}},
            {"display_name": {"$regex": q, "$options": "i"}},
            {"email":        {"$regex": q, "$options": "i"}},
            {"profile.airline":   {"$regex": q, "$options": "i"}},
            {"profile.job_title": {"$regex": q, "$options": "i"}},
        ]

    clients = await db.users.find(
        match,
        {"_id": 0, "id": 1, "name": 1, "display_name": 1, "email": 1,
         "profile": 1, "status": 1},
    ).sort("name", 1).to_list(500)

    rows: list[dict] = []
    for c in clients:
        cid = c["id"]

        active_draft = await db.plan_drafts_v2.find_one(
            {"client_id": cid, **_ACTIVE_DRAFT_FILTER},
            {"_id": 0, "id": 1, "status": 1},
            sort=[("created_at", -1)],
        )
        active_live = await db.plan_live_v2.find_one(
            {"client_id": cid, "active": True},
            {"_id": 0, "id": 1, "roster_range": 1, "planning_window": 1, "activated_at": 1},
        )
        has_draft = bool(active_draft)
        has_live  = bool(active_live)

        # Roster range: prefer the live roster_range, else derive from
        # schedule_days min/max, else null. Cheap two-count read.
        roster_range = None
        has_roster = False
        n_sched = await db.schedule_days.count_documents({"client_id": cid})
        has_roster = n_sched > 0
        if has_roster:
            first = await db.schedule_days.find(
                {"client_id": cid}, {"_id": 0, "date": 1}
            ).sort("date", 1).limit(1).to_list(1)
            last = await db.schedule_days.find(
                {"client_id": cid}, {"_id": 0, "date": 1}
            ).sort("date", -1).limit(1).to_list(1)
            if first and last:
                roster_range = {"start": first[0]["date"], "end": last[0]["date"], "days": n_sched}

        tasks = await _client_tasks(c)
        # Filter for "needs_attention" bucket
        if filter == "needs_attention":
            if not any(t["priority"] in ("urgent", "attention") for t in tasks):
                continue

        plan = _plan_state(has_live, has_draft,
                           draft_needs_review=(active_draft or {}).get("status") == "needs_review")
        # For live+draft, tweak `sub` to include the issue count if we know it
        if plan["kind"] == "live_plus_draft":
            dr = next((t for t in tasks if t["type"] == "draft_review"), None)
            if dr:
                n = (dr.get("counts") or {}).get("total")
                if n:
                    plan["sub"] = f"New Draft · {n} issue" + ("s" if n != 1 else "")
            else:
                # Draft ready to publish (no unresolved issues)
                plan["sub"] = "New Draft · ready to publish"
                plan["sub_tint"] = "green"

        roster = _roster_state(has_roster, roster_range, has_draft, has_live)

        next_action = _primary_next_action(tasks, has_draft, has_live, has_roster)
        if not next_action.get("deep_link"):
            next_action["deep_link"] = f"/coach/client/{cid}/workspace"

        # Goal + phase (coach-facing labels)
        profile = c.get("profile") or {}
        goal_key = profile.get("main_goal_key") or ""
        goal_label = ""
        if goal_key:
            try:
                canonical = canonicalise_goal_key(goal_key)
                tail = canonical.split(".")[-1]
                goal_label = tail.replace("_", " ").title()
            except Exception:
                goal_label = goal_key.split(".")[-1].replace("_", " ").title()

        # Phase — best-effort read of active programme phase.
        phase_label = None
        prog = await db.programmes_v2.find_one(
            {"client_id": cid, "status": {"$in": ["active", "draft"]}},
            {"_id": 0, "id": 1},
        )
        if prog:
            active_phase = await db.programme_phases_v2.find_one(
                {"programme_id": prog["id"], "status": "active"},
                {"_id": 0, "phase_kind": 1},
            )
            if active_phase and active_phase.get("phase_kind"):
                phase_label = str(active_phase["phase_kind"]).replace("_", " ").title()

        rows.append({
            "id": cid,
            "name": (c.get("display_name") or c.get("name") or c.get("email") or "Client"),
            "email": c.get("email"),
            "avatar_url": (c.get("profile") or {}).get("avatar_url"),
            "role_line": _build_role_line(profile),
            "goal": {
                "label": goal_label or "General fitness",
                "phase": phase_label,
            },
            "plan": plan,
            "roster": roster,
            "next_action": next_action,
            "attention_count": sum(1 for t in tasks if t["priority"] in ("urgent", "attention")),
            "status": c.get("status") or "active",
        })

    # Global counts for the filter tabs (independent of current filter)
    counts_all = {
        "active":          await db.users.count_documents({"role": "client", "status": {"$ne": "archived"}}),
        "archived":        await db.users.count_documents({"role": "client", "status": "archived"}),
    }
    # Compute needs_attention against the *active* set only.
    counts_all["needs_attention"] = 0
    if filter != "needs_attention":
        # We already iterated; re-derive from a fresh pass on active only when needed
        active_clients = clients if filter == "active" and not q else await db.users.find(
            {"role": "client", "status": {"$ne": "archived"}},
            {"_id": 0, "id": 1, "profile": 1, "name": 1, "display_name": 1, "email": 1},
        ).to_list(500)
        for ac in active_clients:
            ts = await _client_tasks(ac)
            if any(t["priority"] in ("urgent", "attention") for t in ts):
                counts_all["needs_attention"] += 1
    else:
        counts_all["needs_attention"] = len(rows)

    return {
        "clients": rows,
        "counts": counts_all,
        "filter": filter or "active",
        "q": q or "",
        "at": now_iso(),
    }


def _build_role_line(profile: dict) -> str:
    """Format 'Pilot · Etihad' style role line from profile."""
    parts: list[str] = []
    job = (profile or {}).get("job_title") or (profile or {}).get("role")
    if job:
        parts.append(str(job).replace("_", " ").title())
    airline = (profile or {}).get("airline")
    if airline:
        parts.append(str(airline))
    return " · ".join(parts)
