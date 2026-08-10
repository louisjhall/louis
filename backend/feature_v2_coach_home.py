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
            placements = active_draft.get("placements") or []
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
    "media_required":    3,   # Iter 128k — system media task ranks above check-ins
    "checkin_review":    4,
    "message":           5,
    "plan_ending":       6,
    "roster_required":   7,
    "exercise_review":   8,
}


# ---------------------------------------------------------------------------
# Media aggregator (Iter 128k)
# ---------------------------------------------------------------------------
#
# Home surfaces media work as a SYSTEM task, not a per-client task. It
# reads the two existing needs-media surfaces (coach_tasks for training and
# media_queue for Flight Support), deduplicates by canonical exercise_id,
# and returns a single grouped counter that the UI renders as one row.
#
# Any exercise reference that cannot resolve to a canonical `exercises_v2`
# row is surfaced separately as `exercise_review` — never as a media item
# (per brief §4/§31/§43).


async def _media_summary() -> dict:
    """Return deduplicated counts and breakdown for the Home Needs-Media card.

    Sources (§16/§30/§42):
      - `coach_tasks` rows with `task_type` starting `exercise_needs_`
        → training-side media work.
      - `media_queue` rows with `status == "needs_media"` → Flight Support
        (and any future unified) media work.

    Deduplication key: `exercise_id`. If both surfaces flag the same
    exercise it counts once.
    """
    training_ids: set[str] = set()
    fs_ids: set[str] = set()
    orphan_names: set[str] = set()   # unresolved names → exercise_review

    async for row in db.coach_tasks.find(
        {"status": "open", "task_type": {"$regex": "^exercise_needs_"}},
        {"_id": 0, "exercise_id": 1, "exercise_name": 1, "task_type": 1},
    ):
        ex_id = row.get("exercise_id")
        if ex_id:
            training_ids.add(ex_id)
        else:
            nm = (row.get("exercise_name") or "").strip()
            if nm:
                orphan_names.add(nm)

    async for row in db.media_queue.find(
        {"status": "needs_media"},
        {"_id": 0, "exercise_id": 1, "exercise_name": 1, "family": 1, "preferred_persona": 1},
    ):
        ex_id = row.get("exercise_id")
        if ex_id:
            # If also present in training set, dedupe (same canonical id).
            if ex_id not in training_ids:
                fs_ids.add(ex_id)
        else:
            nm = (row.get("exercise_name") or "").strip()
            if nm:
                orphan_names.add(nm)

    # Cross-check against `exercises_v2.used_in_upcoming_workouts_count`
    # for the client-facing subset. This is the authoritative live-exposure
    # counter maintained by `_bump_usage_counts`.
    all_ids = training_ids | fs_ids
    client_facing = 0
    if all_ids:
        client_facing = await db.exercises_v2.count_documents({
            "id": {"$in": list(all_ids)},
            "used_in_upcoming_workouts_count": {"$gt": 0},
        })

    total = len(training_ids) + len(fs_ids)
    return {
        "total": total,
        "training": len(training_ids),
        "flight_support": len(fs_ids),
        "client_facing": client_facing,
        "unresolved": len(orphan_names),
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
    clients_raw = await db.users.find(
        _live_client_match(),
        {"_id": 0, "id": 1, "name": 1, "display_name": 1, "email": 1,
         "profile": 1},
    ).to_list(500)
    # Iter 128k — production Home defaults to operational clients only
    # (§18). Test / sandbox / reviewer accounts remain in the DB and are
    # reachable via `?include_test=1` on the client-directory endpoint,
    # but they do NOT pollute the coach's action queue.
    clients = [c for c in clients_raw if _is_operational_client(c)]

    all_tasks: list[dict] = []
    for c in clients:
        try:
            items = await _client_tasks(c)
        except Exception:
            # A single client's failure must never poison the whole queue.
            items = []
        all_tasks.extend(items)

    # Iter 128k — SYSTEM tasks (not per-client). Media work is one row that
    # summarises deduplicated media_queue + coach_tasks (exercise_needs_*)
    # gaps. Only surfaced when there is actual work.
    system_tasks: list[dict] = []
    media = await _media_summary()
    if media["total"] > 0:
        # Priority derives from actual client exposure (§3). If any of the
        # canonical rows are already used in an upcoming workout, this is
        # NEEDS ACTION (client-facing); otherwise it's UPCOMING (Library
        # cleanup) — never surfaced above real client work.
        priority = "attention" if media["client_facing"] > 0 else "upcoming"
        breakdown = []
        if media["training"]:      breakdown.append(f"{media['training']} Training")
        if media["flight_support"]:breakdown.append(f"{media['flight_support']} Flight Support")
        context = f"{media['total']} movement{'s' if media['total'] != 1 else ''} need media"
        if media["client_facing"]:
            context += f" · {media['client_facing']} client-facing"
        meta = " · ".join(breakdown) if breakdown else None
        system_tasks.append({
            "id": "media_required:system",
            "type": "media_required",
            "priority": priority,
            "scope": "system",
            "title": "Media required",
            "context": context,
            "meta": meta,
            "action_label": "Open Media Queue",
            "deep_link": "/(coach)/library?filter=needs_media",
            "counts": {
                "total": media["total"],
                "client_facing": media["client_facing"],
                "training": media["training"],
                "flight_support": media["flight_support"],
                "unresolved": media["unresolved"],
            },
        })
    if media["unresolved"] > 0:
        # Orphan exercise names (§4/§31). Separate task so we never inflate
        # media counts with duplicates or free-text ghosts.
        system_tasks.append({
            "id": "exercise_review:system",
            "type": "exercise_review",
            "priority": "upcoming",
            "scope": "system",
            "title": "Exercise names need review",
            "context": f"{media['unresolved']} movement name{'s' if media['unresolved'] != 1 else ''} need canonical review before media can be produced.",
            "meta": None,
            "action_label": "Review exercises",
            "deep_link": "/(coach)/library?filter=needs_review",
            "counts": {"unresolved": media["unresolved"]},
        })

    combined = all_tasks + system_tasks

    # Split by priority band into the three visible sections.
    needs_attention = [t for t in combined if t["priority"] in ("urgent", "attention")]
    upcoming        = [t for t in combined if t["priority"] == "upcoming"]
    waiting         = [t for t in combined if t["priority"] == "waiting"]

    needs_attention.sort(key=_sort_key)
    upcoming.sort(key=_sort_key)
    waiting.sort(key=_sort_key)

    # Summary counts that power the top summary cards. Each card is a
    # deterministic slice of needs_attention/upcoming — no vanity metrics.
    counts = {
        "needs_action":              len(needs_attention),
        "ready_to_publish":          sum(1 for t in all_tasks if t["type"] == "ready_to_publish"),
        "needs_media":               media["total"],
        "needs_media_client_facing": media["client_facing"],
        "needs_media_training":      media["training"],
        "needs_media_flight_support":media["flight_support"],
        "needs_media_unresolved":    media["unresolved"],
        "messages":                  sum(1 for t in all_tasks if t["type"] == "message"),
        "checkins":                  sum(1 for t in all_tasks if t["type"] == "checkin_review"),
        "upcoming":                  len(upcoming),
        "waiting":                   len(waiting),
        "active_clients":            len(clients),
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
    # Base query: role=client, honour archived filter, exclude deleted rows.
    if filter == "archived":
        match: dict = _live_client_match(include_archived=True)
        # Override the status filter to require archived
        match["status"] = "archived"
    else:
        match = _live_client_match()

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
         "profile": 1, "status": 1, "password_hash": 1, "coach_id": 1,
         "assigned_coach_id": 1, "created_at": 1, "last_login_at": 1},
    ).sort("name", 1).to_list(500)

    # Iter 130a — de-duplicate by email. If the production DB ever ends up
    # with two rows for the same email (e.g. a stale signup + a coach-
    # created row), collapse to the "best" one so the coach doesn't see
    # two identical entries. Ranking: has_password > has_coach > newest.
    def _rank(c: dict) -> tuple:
        return (
            1 if c.get("password_hash") else 0,
            1 if (c.get("coach_id") or c.get("assigned_coach_id")) else 0,
            str(c.get("created_at") or ""),
        )
    by_email: dict[str, dict] = {}
    for c in clients:
        key = (c.get("email") or "").strip().lower()
        if not key:
            by_email[c.get("id") or ""] = c  # never drop rows with no email
            continue
        if key not in by_email or _rank(c) > _rank(by_email[key]):
            by_email[key] = c
    clients = list(by_email.values())
    # Strip fields we only needed for dedup ranking before returning.
    for c in clients:
        c.pop("password_hash", None)
        c.pop("coach_id", None)
        c.pop("assigned_coach_id", None)
        c.pop("created_at", None)

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
        #
        # Iter 165 · The JSON monthly-programme importer writes into
        # `db.workouts` (keyed by `user_id`) but never touches
        # `db.schedule_days`. Treat EITHER collection as evidence of a
        # roster so imported clients don't render as "No roster".
        roster_range = None
        has_roster = False
        n_sched = await db.schedule_days.count_documents({"client_id": cid})
        n_wk = await db.workouts.count_documents({"user_id": cid})
        has_roster = (n_sched > 0) or (n_wk > 0)
        if n_sched > 0:
            first = await db.schedule_days.find(
                {"client_id": cid}, {"_id": 0, "date": 1}
            ).sort("date", 1).limit(1).to_list(1)
            last = await db.schedule_days.find(
                {"client_id": cid}, {"_id": 0, "date": 1}
            ).sort("date", -1).limit(1).to_list(1)
            if first and last:
                roster_range = {"start": first[0]["date"], "end": last[0]["date"], "days": n_sched}
        elif n_wk > 0:
            wfirst = await db.workouts.find({"user_id": cid}, {"_id": 0, "date": 1}).sort("date", 1).limit(1).to_list(1)
            wlast  = await db.workouts.find({"user_id": cid}, {"_id": 0, "date": 1}).sort("date", -1).limit(1).to_list(1)
            if wfirst and wlast:
                roster_range = {"start": wfirst[0].get("date"), "end": wlast[0].get("date"),
                                "days": n_wk, "source": "workouts"}

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
            # Iter 160 — coach client list "LAST SEEN" column.
            # null when the user has never logged in since the stamp was
            # added. Frontend renders that as "Never".
            "last_login_at": c.get("last_login_at"),
        })

    # Global counts for the filter tabs (independent of current filter)
    counts_all = {
        "active":          await db.users.count_documents(_live_client_match()),
        "archived":        await db.users.count_documents({"role": "client", "status": "archived", "is_deleted": {"$ne": True}}),
    }
    # Compute needs_attention against the *active* set only.
    counts_all["needs_attention"] = 0
    if filter != "needs_attention":
        # We already iterated; re-derive from a fresh pass on active only when needed
        active_clients = clients if filter == "active" and not q else await db.users.find(
            _live_client_match(),
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


# ---------------------------------------------------------------------------
# Coach Calendar V2 (Iter 128i)
# ---------------------------------------------------------------------------
#
# Cross-client operational calendar. Uses ONLY current authoritative V2 state:
#   - schedule_days  → roster classification per day
#   - plan_live_v2   → active Live placements + session_specs
#   - db.workouts    → manual coach-authored workouts (source=coach_manual,
#                       manual_lock=True). Manual workouts OVERRIDE any V2
#                       generated placements on the same day.
#   - flight support helpers
#
# Draft state is exposed as a per-client badge, never mixed into Live cells.


def _is_operational_client(u: dict) -> bool:
    """Return True if the client should appear on the coach's operational
    calendar by default. Filters out test/sandbox/reviewer accounts via
    explicit account metadata first, then a small email/name fallback.
    """
    profile = u.get("profile") or {}
    ak = str(profile.get("account_kind") or "").lower()
    if ak in ("test", "sandbox", "reviewer", "demo", "preview"):
        return False
    email = (u.get("email") or "").lower()
    if email.endswith("@test.com"):
        return False
    if "test" in email.split("@")[0]:
        return False
    name = (u.get("display_name") or u.get("name") or "").lower()
    if "reviewer" in name or "briefing test" in name:
        return False
    return True


# Iter 162 · Shared "live client" filter — excludes archived, deleted and
# soft-deleted user rows so the coach's dashboard doesn't render "[deleted
# client]" ghosts. Callers can spread this into their Mongo query and add
# extra clauses.
_STATUS_EXCLUDE_FROM_DIRECTORY = ("archived", "deleted")


def _live_client_match(include_archived: bool = False) -> dict:
    """Base Mongo filter for coach directory / calendar queries.

    Excludes:
      * `status: "archived"`  (unless include_archived=True)
      * `status: "deleted"`   (hard-delete tombstone)
      * `is_deleted: true`    (soft-delete flag)
    """
    excludes: list[str] = []
    if not include_archived:
        excludes.append("archived")
    excludes.append("deleted")
    return {
        "role": "client",
        "status": {"$nin": excludes},
        "is_deleted": {"$ne": True},
    }


@api.get("/v2/coach/calendar")
async def endpoint_coach_calendar(
    days: int = 7,
    start: Optional[str] = None,
    include_test: bool = False,
    q: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return the cross-client operational calendar.

    - `days` clamped to [1, 28] (7 / 14 / 28 are the supported UX modes).
    - `start` optional ISO date; default today.
    - `include_test` surfaces sandbox/test/reviewer accounts (dev use).
    - `q` narrows by client name/email/airline/role.
    """
    days = max(1, min(int(days or 7), 28))
    try:
        d0 = _dt.date.fromisoformat(start) if start else _dt.date.today()
    except Exception:
        d0 = _dt.date.today()
    dates = [(d0 + _dt.timedelta(days=i)).isoformat() for i in range(days)]
    date_from, date_to = dates[0], dates[-1]

    # Load clients
    match: dict = _live_client_match()
    if q:
        match["$or"] = [
            {"name":         {"$regex": q, "$options": "i"}},
            {"display_name": {"$regex": q, "$options": "i"}},
            {"email":        {"$regex": q, "$options": "i"}},
            {"profile.airline":   {"$regex": q, "$options": "i"}},
            {"profile.job_title": {"$regex": q, "$options": "i"}},
        ]
    clients_raw = await db.users.find(
        match,
        {"_id": 0, "id": 1, "name": 1, "display_name": 1, "email": 1, "profile": 1},
    ).sort("name", 1).to_list(500)

    excluded_test_count = 0
    if include_test:
        clients = clients_raw
    else:
        clients = []
        for u in clients_raw:
            if _is_operational_client(u):
                clients.append(u)
            else:
                excluded_test_count += 1

    rows: list[dict] = []
    for c in clients:
        cid = c["id"]

        # --- Roster (schedule_days)
        sched = await db.schedule_days.find(
            {"client_id": cid, "date": {"$gte": date_from, "$lte": date_to}},
            {"_id": 0, "date": 1, "day_type": 1, "derived": 1},
        ).to_list(500)
        sched_by_date: dict[str, dict] = {}
        for sd in sched:
            derived = sd.get("derived") or {}
            # `day_type` (top-level) is the canonical classification; fall back to
            # `derived.classification` for older docs.
            classification = sd.get("day_type") or derived.get("classification") or ""
            sched_by_date[sd["date"]] = {
                "classification": classification,
                "classification_label": _humanise_classification(classification),
                "duty_burden_band": derived.get("duty_burden_band"),
            }

        # --- Active Live placements
        live = await db.plan_live_v2.find_one(
            {"client_id": cid, "active": True},
            {"_id": 0, "id": 1, "placements": 1, "session_specs": 1, "planning_window": 1},
        )
        specs: dict[str, dict] = {}
        placements_by_date: dict[str, list[dict]] = {}
        if live:
            _raw_specs = live.get("session_specs") or {}
            if isinstance(_raw_specs, dict):
                # session_specs stored as {exposure_id: spec}
                for k, v in _raw_specs.items():
                    if isinstance(v, dict):
                        specs[k] = v
            elif isinstance(_raw_specs, list):
                for s in _raw_specs:
                    if isinstance(s, dict) and s.get("exposure_id"):
                        specs[s["exposure_id"]] = s
            for p in (live.get("placements") or []):
                d = p.get("date")
                if not d or d < date_from or d > date_to:
                    continue
                if p.get("kind") == "rest":
                    continue
                spec = specs.get(p.get("exposure_id") or "") or {}
                placements_by_date.setdefault(d, []).append({
                    "id": f"v2p:{live['id']}:{p.get('exposure_id') or ''}",
                    "kind":  p.get("kind") or spec.get("kind") or "session",
                    "label": _humanise_kind(spec.get("spec_kind") or p.get("kind") or "session"),
                    "duration_min": (spec.get("duration_min") or p.get("target_duration_min")),
                    "key": bool(p.get("key")),
                    "intensity": p.get("intensity_target") or spec.get("intensity_target"),
                })

        # --- Manual workouts (db.workouts, source=coach_manual)
        # Fold coach-authored manual workouts into the calendar cells.
        # `manual_lock=True` is authoritative — we do NOT check `approved`.
        # If a date has BOTH a generated V2 plan and a manual workout, the
        # manual workout wins (see cell build below).
        manual_rows = await db.workouts.find(
            {
                "user_id": cid,
                "date": {"$gte": date_from, "$lte": date_to},
                "source": "coach_manual",
                "manual_lock": True,
            },
            {
                "_id": 0, "id": 1, "date": 1, "title": 1,
                "workout_type": 1, "focus": 1, "duration_min": 1,
            },
        ).to_list(500)
        manual_by_date: dict[str, list[dict]] = {}
        for mw in manual_rows:
            md = mw.get("date")
            if not md or md < date_from or md > date_to:
                continue
            m_kind = mw.get("workout_type") or mw.get("focus") or "session"
            m_title = (mw.get("title") or "").strip()
            m_label = m_title or _humanise_kind(m_kind)
            manual_by_date.setdefault(md, []).append({
                "id": f"manual:{mw.get('id')}",
                "kind": m_kind,
                "label": m_label,
                "duration_min": mw.get("duration_min"),
                "key": False,
                "intensity": None,
                "source": "manual",
            })

        # --- Flight support
        fs_by_date: dict[str, list[dict]] = {}
        try:
            from feature_aviation_support_api import (
                _flight_support_for_range, _bundle_interventions,
            )
            raw_fs = await _flight_support_for_range(cid, date_from, date_to)
            for d, items in raw_fs.items():
                bundled = _bundle_interventions(items) if items else []
                fs_by_date[d] = [{
                    "id": f.get("id"),
                    "title": f.get("title"),
                    "duration_min": f.get("duration_min"),
                    "family": f.get("family"),
                    "is_bundle": bool(f.get("is_bundle")),
                } for f in bundled]
        except Exception:
            fs_by_date = {}

        # --- Draft badge (existence only; NO Draft sessions in cells)
        active_draft = await db.plan_drafts_v2.find_one(
            {"client_id": cid, **_ACTIVE_DRAFT_FILTER},
            {"_id": 0, "id": 1, "status": 1},
            sort=[("created_at", -1)],
        )

        # Build day cells
        cells = []
        has_any_content = False
        for d in dates:
            roster = sched_by_date.get(d)
            manuals   = manual_by_date.get(d, [])
            generated = placements_by_date.get(d, [])
            # Manual override rule: if the day has BOTH a manual workout and a
            # generated plan, the manual workout wins. Do not merge; a manual
            # workout represents an authoritative coach decision for that day.
            trainings = manuals if manuals else generated
            flights   = fs_by_date.get(d, [])
            if roster or trainings or flights:
                has_any_content = True
            cells.append({
                "date": d,
                "roster": roster,
                "trainings": trainings,
                "flight_support": flights,
                "is_rest": (not trainings) and bool(roster),
            })

        # --- Goal + phase (coach-facing)
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

        phase_label = None
        prog = await db.programmes_v2.find_one(
            {"client_id": cid, "status": {"$in": ["active", "draft"]}}, {"_id": 0, "id": 1},
        )
        if prog:
            active_phase = await db.programme_phases_v2.find_one(
                {"programme_id": prog["id"], "status": "active"},
                {"_id": 0, "phase_kind": 1},
            )
            if active_phase and active_phase.get("phase_kind"):
                phase_label = str(active_phase["phase_kind"]).replace("_", " ").title()

        rows.append({
            "client_id": cid,
            "name": c.get("display_name") or c.get("name") or c.get("email") or "Client",
            "role_line": _build_role_line(profile),
            "avatar_url": profile.get("avatar_url"),
            "goal_label": goal_label or "General fitness",
            "phase_label": phase_label,
            "plan_state":  "live" if live else ("draft_only" if active_draft else "no_plan"),
            # Iter 165 · JSON-imported programmes only touch `db.workouts`,
            # not `db.schedule_days`; check both so the roster indicator is
            # correct for both manual builder AND JSON import flows.
            "has_roster":  bool(sched) or (await db.workouts.count_documents({"user_id": cid, "date": {"$gte": date_from, "$lte": date_to}}) > 0),
            "has_new_draft": bool(active_draft and live),  # newer Draft alongside Live
            "days": cells,
            "content_present": has_any_content,
        })

    return {
        "start_date": date_from,
        "end_date":   date_to,
        "days_count": days,
        "dates": dates,
        "clients": rows,
        "excluded_test_count": excluded_test_count,
        "at": now_iso(),
    }


def _humanise_kind(k: str) -> str:
    if not k:
        return "Session"
    label_map = {
        "running":        "Run",
        "cycling":        "Ride",
        "swimming":       "Swim",
        "strength":       "Strength",
        "mobility":       "Mobility",
        "recovery":       "Recovery",
        "brick":          "Brick",
        "activation":     "Activation",
        "travel_recovery":"Travel Recovery",
    }
    if k in label_map:
        return label_map[k]
    return k.replace("_", " ").title()


# Roster classification labels — coach-facing single-word tags.
_ROSTER_LABELS = {
    "home_day":         "Home",
    "layover":          "Layover",
    "layover_departure":"Layover ✈",
    "layover_arrival":  "Layover ✈",
    "flight":           "Flight",
    "turnaround":       "Turnaround",
    "standby":          "Standby",
    "off":              "Off",
    "duty":             "Duty",
    "training":         "Training",
    "reserve":          "Reserve",
    "vacation":         "Vacation",
    "sick":             "Sick",
    "unknown":          "-",
}


def _humanise_classification(c: str) -> str:
    if not c:
        return ""
    key = str(c).lower()
    if key in _ROSTER_LABELS:
        return _ROSTER_LABELS[key]
    return key.replace("_", " ").title()
