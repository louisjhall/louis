"""
Iter 94s — Calendar Scroll + Missed Workout Recovery.

Owns:

1. GET  /calendar/range?from=YYYY-MM-DD&to=YYYY-MM-DD
     One-shot payload with day cards for the requested range. Each day carries:
       date, is_today, workout (with resolved badge), roster_day, activities,
       badges[]. This backs the scrollable client calendar (past + future).

2. GET  /workouts/missed?window=14
     Missed workouts still eligible for recovery — used by the home
     "You have N sessions you can recover" card.

3. POST /workouts/{wid}/recovery/suggestions
     Return up to 7 suitable candidate dates (today → today+21) each with a
     rating (good | okay | not_ideal | blocked) and reason. Runs safety checks
     against roster, existing sessions, key-session weighting, and coach lock.

4. POST /workouts/{wid}/recover
     Body: { target_date, action: "move" | "replace_today" | "add_today" }.
     Re-runs safety, then moves the workout. Preserves the original date and
     creates linkage fields (recovered_from_date, recovered_to_date, ...).
     Fires a coach task if the action clashes with a safety rule the client
     overrode ("hard on hard").

5. POST /workouts/{wid}/skip
     Marks a missed workout as skipped so it stops appearing in recovery
     surfaces. Optional reason.

All responses are pure JSON, all copy is client-safe (no AI wording),
and all timestamps are ISO strings.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from server import (
    api, current_user, db, new_id, now_iso, _create_coach_task,
)

logger = logging.getLogger("crewfit.calendar_recovery")


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------

# Missed-workout freshness window. Older than this and we suggest skip/ask.
MISSED_WINDOW_DAYS = 14
# How far ahead to search for recovery slots.
RECOVERY_FORWARD_DAYS = 21
# Hard-session focus tags. Anything with a red/amber load also counts.
HARD_FOCUS = {
    "strength_lower", "strength_full", "long_run", "long_ride",
    "intervals", "tempo", "hard_conditioning", "hyrox", "vo2max",
}
# Roster day types where hard training is unsafe.
HARD_UNSAFE_DUTY = {
    "long_haul", "long-haul", "long_haul_out", "long_haul_in",
    "night_flight", "night_duty", "red_eye",
}
OFF_LIKE = {"rest", "off", "day_off", "leave", "annual_leave", "sick"}


def _iso(d: _dt.date) -> str:
    return d.isoformat()


def _parse_date(s: Optional[str]) -> Optional[_dt.date]:
    if not s:
        return None
    try:
        return _dt.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _today() -> _dt.date:
    return _dt.date.today()


def _account_start_date(user: dict) -> Optional[_dt.date]:
    """The earliest date that should count for missed-session logic.

    Anything on the client's roster before this date was uploaded for
    historical context only and MUST NOT be counted as a missed session.

    Priority (newest wins so we're conservative):
      1. plan_start_at        — explicit start of programming
      2. onboarded_at         — when they finished onboarding
      3. signed_up_at         — when they created the account
      4. created_at           — DB creation timestamp
    """
    candidates: list[_dt.date] = []
    for k in ("plan_start_at", "onboarded_at", "signed_up_at", "created_at", "joined_at"):
        d = _parse_date(user.get(k))
        if d:
            candidates.append(d)
    if not candidates:
        return None
    # Use the newest date — anything older than that is "before I started".
    return max(candidates)


def _is_hard(w: dict) -> bool:
    """A workout is considered hard if intensity or focus flags it."""
    if not w:
        return False
    load = str(w.get("day_load") or "").lower()
    if load in {"red", "amber"}:
        return True
    focus = str(w.get("focus") or "").lower()
    st = str(w.get("session_type") or "").lower()
    if focus in HARD_FOCUS or st in HARD_FOCUS:
        return True
    if w.get("key_session"):
        return True
    return False


def _is_off_workout(w: Optional[dict]) -> bool:
    if not w:
        return True
    focus = str(w.get("focus") or "").lower()
    title = str(w.get("title") or "").lower()
    workout_type = str(w.get("workout_type") or "").lower()
    duration_min = w.get("duration_min")
    # Iter 161 · Any workout with focus=recovery OR duration_min=0 (a Full
    # Rest day from the JSON importer) OR workout_type=recovery/rest MUST
    # be treated as a rest/off day for the missed-session pipeline.
    # Otherwise a scheduled Full Rest that the client didn't tap gets
    # incorrectly badged MISSED and offered a "recover" action.
    if focus in OFF_LIKE or focus == "recovery":
        return True
    if workout_type in ("recovery", "rest", "off", "day_off"):
        return True
    if isinstance(duration_min, (int, float)) and int(duration_min) == 0:
        return True
    if title.startswith("rest") or title.startswith("off") or "full rest" in title:
        return True
    return False


def _is_optional(w: Optional[dict]) -> bool:
    """Optional recovery sessions never demand catch-up."""
    if not w:
        return False
    st = str(w.get("session_type") or "").lower()
    focus = str(w.get("focus") or "").lower()
    if st in {"optional_recovery", "mobility", "walk", "easy_walk"}:
        return True
    if focus in {"mobility", "recovery"}:
        return True
    if str(w.get("intensity") or "").lower() in {"optional", "recovery"}:
        return True
    return False


def _classify_priority(w: Optional[dict]) -> str:
    if not w:
        return "low_priority"
    if w.get("key_session") or _is_hard(w):
        return "key_session"
    if _is_optional(w):
        return "optional_recovery"
    return "support_session"


def _duty_type_for(row: Optional[dict]) -> str:
    if not row:
        return ""
    return str(row.get("day_type") or row.get("duty_type") or "").lower()


def _duty_is_hard(row: Optional[dict]) -> bool:
    dt = _duty_type_for(row)
    if not dt:
        return False
    for tag in HARD_UNSAFE_DUTY:
        if tag in dt:
            return True
    return False


def _duty_is_off(row: Optional[dict]) -> bool:
    dt = _duty_type_for(row)
    return any(tag in dt for tag in ("off", "rest", "leave", "annual", "recovery"))


def _badge_for(
    w: Optional[dict], the_date: _dt.date, today: _dt.date, roster_row: Optional[dict],
    *, account_start: Optional[_dt.date] = None,
) -> str:
    """Resolve a single primary badge for a day-card workout.

    Order matters — first match wins.
    """
    if not w:
        # Roster-based badges only.
        if roster_row and _duty_is_hard(roster_row):
            return "roster_adjusted"
        return "rest"
    if w.get("completed"):
        return "completed"
    if w.get("skipped") or str(w.get("recovery_status") or "").lower() == "skipped":
        return "skipped"
    if str(w.get("recovery_status") or "").lower() == "moved":
        return "moved"
    if w.get("recovered_from_date"):
        return "recovered"
    if _is_off_workout(w):
        return "rest"
    if the_date < today:
        # Iter 95f — historic dates that pre-date the account are NOT
        # "missed" — they were never actually assigned. Show them as
        # planned/rest so they don't inflate the recovery card.
        if account_start and the_date < account_start:
            return "rest"
        return "missed"
    if w.get("needs_coach_review"):
        return "awaiting_coach_review"
    if w.get("key_session"):
        return "key_session"
    if _is_optional(w):
        return "optional"
    return "planned"


def _client_copy_for_missed(w: dict) -> dict:
    priority = _classify_priority(w)
    if priority == "optional_recovery":
        return {
            "title": "Optional session missed",
            "body": "This was an optional recovery session, so you don't need to make it up.",
            "recommendation": "skip",
        }
    return {
        "title": "You missed this session",
        "body": "Roster, travel and recovery can get in the way. You can recover this session if it still fits your week.",
        "recommendation": "recover",
    }


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

async def _workouts_between(user_id: str, d_from: _dt.date, d_to: _dt.date) -> list[dict]:
    rows = await db.workouts.find(
        {"user_id": user_id, "date": {"$gte": _iso(d_from), "$lte": _iso(d_to)}},
        {"_id": 0},
    ).sort("date", 1).to_list(1000)
    return rows or []


async def _roster_days_between(user_id: str, d_from: _dt.date, d_to: _dt.date) -> dict[str, dict]:
    """Return merged roster days across ALL active rosters for this user.

    Historically this only queried the "latest" roster (find_one) using
    `status == "active"` — a field that isn't actually set anywhere in the
    codebase (rosters carry `is_active=True` + `status="confirmed"`). As a
    result the client dashboard silently lost visibility of any month that
    lived on a *previous* roster upload. Now we merge every currently-active
    roster's days by date so July + August (or any non-overlapping split
    across two uploads) both show up.
    """
    rosters = await db.rosters.find(
        {"user_id": user_id, "is_active": True},
        {"_id": 0, "raw_response": 0},
    ).sort("created_at", -1).to_list(60)
    if not rosters:
        return {}
    out: dict[str, dict] = {}
    for r in rosters:
        rid = r.get("id")
        for d in (r.get("days") or []):
            ds = str(d.get("date") or "")[:10]
            try:
                dd = _dt.date.fromisoformat(ds)
            except Exception:
                continue
            if not (d_from <= dd <= d_to):
                continue
            # Newest roster wins on conflict (rosters is sorted DESC by created_at).
            if ds in out:
                continue
            # Preserve which roster this day came from — needed by clients
            # that want to route long-press edits back to the correct roster.
            enriched = dict(d)
            enriched.setdefault("_source_roster_id", rid)
            out[ds] = enriched
    return out


async def _activities_between(user_id: str, d_from: _dt.date, d_to: _dt.date) -> dict[str, list[dict]]:
    rows = await db.personal_activities.find(
        {"user_id": user_id, "date_local": {"$gte": _iso(d_from), "$lte": _iso(d_to)}},
        {"_id": 0},
    ).sort("date_local", 1).to_list(500) if hasattr(db, "personal_activities") else []
    out: dict[str, list[dict]] = {}
    for a in rows or []:
        ds = str(a.get("date_local") or "")[:10]
        out.setdefault(ds, []).append(a)
    return out


# ---------------------------------------------------------------------------
# Safety scoring for candidate recovery slots
# ---------------------------------------------------------------------------

def _safety_score_for_slot(
    candidate: _dt.date,
    today: _dt.date,
    missed_workout: dict,
    workouts_by_date: dict[str, dict],
    roster_by_date: dict[str, dict],
    days_missed_ago: int,
) -> dict:
    """Return { rating, reason, existing_workout, roster, blocked }.

    rating in {"good","okay","not_ideal","blocked"}.
    """
    ds = _iso(candidate)
    existing = workouts_by_date.get(ds)
    roster = roster_by_date.get(ds)
    missed_is_hard = _is_hard(missed_workout)
    missed_is_key = bool(missed_workout.get("key_session"))

    reasons: list[str] = []
    rating = "good"

    # Block: coach-locked existing workout
    if existing and existing.get("coach_locked") and not existing.get("completed"):
        return {
            "rating": "blocked",
            "reason": "Coach-locked session on this day — ask Louis to move it.",
            "existing_workout": {"title": existing.get("title")} if existing else None,
            "roster": {"day_type": _duty_type_for(roster)} if roster else None,
            "blocked": True,
        }
    # Block: candidate day already has a completed workout on that date
    if existing and existing.get("completed") and candidate == today:
        return {
            "rating": "blocked",
            "reason": "You already completed today's session.",
            "existing_workout": {"title": existing.get("title"), "completed": True},
            "roster": {"day_type": _duty_type_for(roster)} if roster else None,
            "blocked": True,
        }

    # Hard-on-hard: existing hard session on the candidate day
    if existing and _is_hard(existing) and missed_is_hard:
        rating = "not_ideal"
        reasons.append("A hard session is already planned on this day.")
    # Hard training before a hard duty (long-haul, night flight)
    if missed_is_hard and _duty_is_hard(roster):
        rating = "not_ideal"
        reasons.append(f"Roster shows {_duty_type_for(roster) or 'a hard duty'} — better to rest before it.")

    # Existing support session + missed hard: still okay-ish
    if existing and not _is_hard(existing) and missed_is_hard and rating == "good":
        rating = "okay"
        reasons.append("A lighter session is already planned — you'd need to replace it.")

    # Off duty + no existing session → prime slot
    if not existing and _duty_is_off(roster) and rating == "good":
        reasons.append("Day off and no session planned.")

    # Roster day with light duty (e.g. short_haul, standby) → okay
    if not existing and roster and not _duty_is_off(roster) and not _duty_is_hard(roster) and rating == "good":
        reasons.append(f"Roster: {_duty_type_for(roster) or 'light duty'} — should still be manageable.")

    # No roster info + no existing session → decent default
    if not existing and not roster and rating == "good":
        reasons.append("Nothing else scheduled — should work.")

    # Very old miss (>7 days) softens the rating even if the day itself is fine.
    if days_missed_ago > 7 and rating == "good":
        rating = "okay"
        reasons.append(f"This session was originally {days_missed_ago} days ago — recover only if it still fits.")

    return {
        "rating": rating,
        "reason": " ".join(reasons) if reasons else "Good option.",
        "existing_workout": (
            {
                "id": existing.get("id"),
                "title": existing.get("title"),
                "hard": _is_hard(existing),
                "completed": bool(existing.get("completed")),
            }
            if existing else None
        ),
        "roster": (
            {
                "day_type": _duty_type_for(roster),
                "layover_city": roster.get("layover_city"),
            } if roster else None
        ),
        "blocked": False,
    }


# ---------------------------------------------------------------------------
# GET /calendar/range
# ---------------------------------------------------------------------------

@api.get("/calendar/range")
async def calendar_range(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    user: dict = Depends(current_user),
):
    today = _today()
    d_from = _parse_date(from_) or (today - _dt.timedelta(days=30))
    d_to = _parse_date(to) or (today + _dt.timedelta(days=30))
    if d_to < d_from:
        raise HTTPException(400, "to must be >= from")
    # Hard cap (60 days back / 60 days forward) so a bad client can't DoS us.
    d_from = max(d_from, today - _dt.timedelta(days=60))
    d_to = min(d_to, today + _dt.timedelta(days=60))

    workouts = await _workouts_between(user["id"], d_from, d_to)
    by_date: dict[str, dict] = {}
    for w in workouts:
        ds = str(w.get("date") or "")[:10]
        by_date[ds] = w
    # Iter 110 — Engine V2 client bridge: /calendar/range also drives the
    # client HOME schedule (ClientCalendarPanel), so V2 clients need their
    # plan_live_v2 placements merged in here too. Only fill dates that don't
    # already have a legacy workout — V2 clients don't have any in practice.
    try:
        from feature_v2_client_bridge import synth_workouts_for_user
        v2_rows = await synth_workouts_for_user(
            db, user["id"],
            start_iso=_iso(d_from), end_iso=_iso(d_to),
        )
        for r in v2_rows:
            ds = str(r.get("date") or "")[:10]
            if ds and ds not in by_date:
                by_date[ds] = r
    except Exception:
        # Never let the bridge break /calendar/range for anyone.
        pass
    roster_by_date = await _roster_days_between(user["id"], d_from, d_to)
    acts_by_date = await _activities_between(user["id"], d_from, d_to)

    # Iter 116 — Aviation Support Layer (Phase A). Deterministic, cheap,
    # decoupled from Engine V2 quotas. Recomputed on every read so a coach
    # override / roster edit is reflected without a background job.
    flight_support_by_date: dict[str, list[dict]] = {}
    try:
        from feature_aviation_support import (
            get_flight_support_by_date,
            summarise_training_by_date_from_workouts,
        )
        _training_summary = summarise_training_by_date_from_workouts(
            list(by_date.values()),
        )
        flight_support_by_date = await get_flight_support_by_date(
            db, user["id"], roster_by_date, _training_summary,
        )
    except Exception:
        # Aviation support must NEVER break /calendar/range for anyone.
        pass

    # Iter 95f — respect the client's account start so historic roster
    # days don't get flagged as missed.
    account_start = _account_start_date(user)

    days: list[dict] = []
    step = d_from
    while step <= d_to:
        ds = _iso(step)
        w = by_date.get(ds)
        rd = roster_by_date.get(ds)
        acts = acts_by_date.get(ds, [])
        badge = _badge_for(w, step, today, rd, account_start=account_start)
        card = {
            "date": ds,
            "is_today": step == today,
            "is_past": step < today,
            "badge": badge,
            "priority": _classify_priority(w) if w else None,
            "workout": (
                {
                    "id": w.get("id"),
                    "title": w.get("title"),
                    "focus": w.get("focus"),
                    "session_type": w.get("session_type"),
                    "day_load": w.get("day_load"),
                    "completed": bool(w.get("completed")),
                    "skipped": bool(w.get("skipped") or str(w.get("recovery_status") or "").lower() == "skipped"),
                    "key_session": bool(w.get("key_session")),
                    "coach_locked": bool(w.get("coach_locked")),
                    "location": w.get("location"),
                    "estimated_minutes": w.get("estimated_minutes") or w.get("duration_minutes"),
                    "recovered_from_date": w.get("recovered_from_date"),
                    "recovered_to_date": w.get("recovered_to_date"),
                    "hard": _is_hard(w),
                    # Iter 112 — Engine V2 rationale/priority surfacing.
                    # These fields are only present on V2 rows produced by
                    # feature_v2_client_bridge; legacy V1 rows leave them
                    # undefined so the frontend rationale line stays hidden.
                    "source": w.get("source"),
                    "rationale": w.get("rationale") or None,
                    "priority": w.get("v2_priority") or None,
                    "intensity_target": w.get("v2_intensity_target") or None,
                    "exposure_number": w.get("v2_exposure_number") or None,
                }
                if w else None
            ),
            "roster_day": (
                {
                    "day_type": rd.get("day_type"),
                    "layover_city": rd.get("layover_city"),
                    "flights": rd.get("flights") or [],
                    "load": rd.get("load"),
                }
                if rd else None
            ),
            "activities": acts,
            "client_copy": _client_copy_for_missed(w) if (w and badge == "missed") else None,
            # Iter 116 — Aviation Support (Phase A). Separate from `workout`;
            # NEVER affects Engine V2 quotas or adherence. Empty list for
            # non-pilot roles or non-duty days.
            "flight_support": flight_support_by_date.get(ds, []),
        }
        days.append(card)
        step += _dt.timedelta(days=1)

    # Also compute a rollup so the client can render summary widgets quickly.
    counts = {"missed": 0, "completed": 0, "planned": 0, "recovered": 0, "skipped": 0}
    for c in days:
        b = c.get("badge")
        if b in counts:
            counts[b] += 1
    return {
        "from": _iso(d_from),
        "to": _iso(d_to),
        "today": _iso(today),
        "days": days,
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# GET /workouts/missed
# ---------------------------------------------------------------------------

@api.get("/recovery/missed")
async def workouts_missed(
    window: int = Query(MISSED_WINDOW_DAYS, ge=1, le=60),
    user: dict = Depends(current_user),
):
    today = _today()
    # Iter 95f — don't count workouts that were on the roster BEFORE
    # the client had an account / a live plan. Those are historic
    # context only and were never actually assigned to the client.
    account_start = _account_start_date(user)
    window_start = today - _dt.timedelta(days=window)
    cutoff = max(window_start, account_start) if account_start else window_start
    rows = await db.workouts.find(
        {
            "user_id": user["id"],
            "date": {"$gte": _iso(cutoff), "$lt": _iso(today)},
            "completed": {"$ne": True},
            "skipped": {"$ne": True},
        },
        {"_id": 0},
    ).sort("date", 1).to_list(200)
    out: list[dict] = []
    for w in rows or []:
        if _is_off_workout(w):
            continue
        if str(w.get("recovery_status") or "").lower() in {"skipped", "moved"}:
            continue
        try:
            when = _dt.date.fromisoformat(str(w.get("date") or "")[:10])
        except Exception:
            continue
        days_ago = (today - when).days
        priority = _classify_priority(w)
        recommendation = "skip" if priority == "optional_recovery" else (
            "ask_louis" if days_ago > MISSED_WINDOW_DAYS else "recover"
        )
        out.append({
            "id": w.get("id"),
            "date": _iso(when),
            "days_ago": days_ago,
            "title": w.get("title"),
            "focus": w.get("focus"),
            "session_type": w.get("session_type"),
            "priority": priority,
            "key_session": bool(w.get("key_session")),
            "coach_locked": bool(w.get("coach_locked")),
            "recoverable": (
                not w.get("coach_locked") and priority != "optional_recovery"
                and days_ago <= MISSED_WINDOW_DAYS
            ),
            "recommendation": recommendation,
            "client_copy": _client_copy_for_missed(w),
        })
    # Cap the count returned to avoid overwhelming the client card.
    return {"missed": out, "count": len(out)}


# ---------------------------------------------------------------------------
# POST /workouts/{wid}/recovery/suggestions
# ---------------------------------------------------------------------------

async def _load_workout_or_403(wid: str, user: dict) -> dict:
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "Workout not found")
    if user["role"] == "client" and w.get("user_id") != user["id"]:
        raise HTTPException(403, "Forbidden")
    return w


@api.post("/recovery/{wid}/suggestions")
async def workout_recovery_suggestions(wid: str, user: dict = Depends(current_user)):
    w = await _load_workout_or_403(wid, user)
    if w.get("completed"):
        raise HTTPException(400, "Completed workouts can't be moved.")
    if w.get("coach_locked"):
        raise HTTPException(400, "This workout is locked by your coach — message Louis to move it.")

    today = _today()
    try:
        missed_date = _dt.date.fromisoformat(str(w.get("date"))[:10])
    except Exception:
        missed_date = today
    days_ago = max(0, (today - missed_date).days)

    horizon = today + _dt.timedelta(days=RECOVERY_FORWARD_DAYS)
    other_workouts = await _workouts_between(user["id"], today, horizon)
    workouts_by_date = {str(x.get("date") or "")[:10]: x for x in other_workouts if x.get("id") != w.get("id")}
    roster_by_date = await _roster_days_between(user["id"], today, horizon)

    suggestions: list[dict] = []
    step = today
    while step <= horizon and len(suggestions) < 12:
        s = _safety_score_for_slot(step, today, w, workouts_by_date, roster_by_date, days_ago)
        if not s["blocked"] or step == today:
            suggestions.append({
                "date": _iso(step),
                "days_from_today": (step - today).days,
                **s,
            })
        step += _dt.timedelta(days=1)

    # Global recommendation
    if days_ago > MISSED_WINDOW_DAYS:
        global_reco = "skip"
        global_reco_copy = "This session was more than two weeks ago — your plan has moved on. Skip and continue, or message Louis."
    elif _classify_priority(w) == "optional_recovery":
        global_reco = "skip"
        global_reco_copy = "This was an optional recovery session, so you don't need to make it up."
    else:
        good = [s for s in suggestions if s["rating"] == "good"]
        if good:
            global_reco = "recover"
            global_reco_copy = "Good to recover — your roster looks suitable on the highlighted day(s)."
        elif any(s["rating"] == "okay" for s in suggestions):
            global_reco = "move"
            global_reco_copy = "Better to move this to the next suitable day."
        else:
            global_reco = "ask_louis"
            global_reco_copy = "None of the upcoming days look ideal — Louis can help adjust the plan safely."

    return {
        "workout": {
            "id": w.get("id"),
            "title": w.get("title"),
            "date": w.get("date"),
            "hard": _is_hard(w),
            "key_session": bool(w.get("key_session")),
            "priority": _classify_priority(w),
            "days_ago": days_ago,
        },
        "recommendation": global_reco,
        "recommendation_copy": global_reco_copy,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# POST /workouts/{wid}/recover
# ---------------------------------------------------------------------------

class RecoverBody(BaseModel):
    target_date: str = Field(..., description="YYYY-MM-DD")
    action: str = Field(
        "move",
        description='"move" (default), "replace_today" (delete conflicting workout on target), or "add_today" (accept hard-on-hard override)',
    )
    override_safety: bool = False
    reason: Optional[str] = None


@api.post("/recovery/{wid}/recover")
async def workout_recover(wid: str, body: RecoverBody, user: dict = Depends(current_user)):
    w = await _load_workout_or_403(wid, user)
    if w.get("completed"):
        raise HTTPException(400, "Completed workouts can't be moved.")
    if w.get("coach_locked"):
        raise HTTPException(400, "This workout is locked by your coach — message Louis to move it.")

    target = _parse_date(body.target_date)
    if not target:
        raise HTTPException(400, "target_date must be YYYY-MM-DD")
    today = _today()
    if target < today:
        raise HTTPException(400, "You can only move a missed workout to today or a future day.")

    try:
        original = _dt.date.fromisoformat(str(w.get("date"))[:10])
    except Exception:
        original = today
    days_ago = (today - original).days

    horizon = today + _dt.timedelta(days=RECOVERY_FORWARD_DAYS)
    other_workouts = await _workouts_between(user["id"], today, horizon)
    workouts_by_date = {str(x.get("date") or "")[:10]: x for x in other_workouts if x.get("id") != w.get("id")}
    roster_by_date = await _roster_days_between(user["id"], today, horizon)
    score = _safety_score_for_slot(target, today, w, workouts_by_date, roster_by_date, days_ago)

    if score.get("blocked") and not body.override_safety:
        raise HTTPException(409, score.get("reason") or "This day isn't safe for this session.")

    # Handle conflicting workout on the target date
    existing = workouts_by_date.get(_iso(target))
    replaced_id: Optional[str] = None
    if existing and existing.get("completed"):
        raise HTTPException(400, "You already completed the session on that day — pick another.")
    if existing and body.action == "replace_today" and target == today:
        # Mark the current-today workout as replaced/skipped so it doesn't hang around.
        replaced_id = existing.get("id")
        await db.workouts.update_one(
            {"id": replaced_id},
            {"$set": {
                "skipped": True,
                "recovery_status": "replaced_by_recovery",
                "replaced_by_workout_id": w.get("id"),
                "updated_at": now_iso(),
            }},
        )
    elif existing and body.action in {"move", "replace_today"} and target != today:
        # Existing session on a future day — don't blow it up automatically.
        if not body.override_safety:
            raise HTTPException(
                409,
                "There's already a session on that day. Choose 'replace_today' only when moving to today.",
            )

    # Persist the move
    updates = {
        "date": _iso(target),
        "recovered_from_date": _iso(original),
        "recovered_to_date": _iso(target),
        "recovery_status": "recovered",
        "recovery_reason": body.reason or "Client recovered a missed session.",
        "rescheduled_by": "coach" if user["role"] == "coach" else "client",
        "rescheduled_at": now_iso(),
        "calendar_move_reason": body.action,
        "safety_check_status": "override" if score.get("blocked") else score.get("rating"),
        "skipped": False,
        "updated_at": now_iso(),
    }
    if replaced_id:
        updates["replaces_workout_id"] = replaced_id
    await db.workouts.update_one({"id": w.get("id")}, {"$set": updates})

    # Timeline event so the coach dashboard can render it.
    try:
        await db.timeline_events.insert_one({
            "id": new_id(),
            "user_id": user["id"],
            "kind": "workout_recovered",
            "workout_id": w.get("id"),
            "from_date": _iso(original),
            "to_date": _iso(target),
            "action": body.action,
            "safety": score.get("rating"),
            "override": bool(score.get("blocked") and body.override_safety),
            "created_at": now_iso(),
        })
    except Exception:
        logger.exception("failed to write timeline event for recovery")

    # Coach task if safety was overridden OR a key session was moved.
    try:
        if score.get("blocked") and body.override_safety:
            await _create_coach_task(
                user, "workout_recovery_review",
                f"Workout recovery review needed: {user.get('name') or user.get('email')}",
                f"Client overrode safety to move a session to {_iso(target)}. Reason: {score.get('reason')}",
                priority="high",
                category="programme_adherence",
                payload={"workout_id": w.get("id"), "target_date": _iso(target), "reason": score.get("reason")},
            )
        elif w.get("key_session"):
            await _create_coach_task(
                user, "workout_recovery_review",
                f"Key session recovered: {user.get('name') or user.get('email')}",
                f"Client moved a key session from {_iso(original)} to {_iso(target)}.",
                priority="normal",
                category="programme_adherence",
                payload={"workout_id": w.get("id"), "from": _iso(original), "to": _iso(target)},
            )
    except Exception:
        logger.exception("failed to create coach task for recovery")

    fresh = await db.workouts.find_one({"id": w.get("id")}, {"_id": 0})
    return {
        "ok": True,
        "workout": fresh,
        "message": (
            "Workout moved — your missed session has been placed on the next suitable day."
            if body.action != "replace_today"
            else "Workout recovered — this session replaced today's planned workout."
        ),
    }


class SkipBody(BaseModel):
    reason: Optional[str] = None


@api.post("/recovery/{wid}/skip")
async def workout_skip(wid: str, body: SkipBody, user: dict = Depends(current_user)):
    w = await _load_workout_or_403(wid, user)
    if w.get("completed"):
        raise HTTPException(400, "Completed workouts can't be skipped.")
    if w.get("coach_locked"):
        raise HTTPException(400, "Coach-locked — message Louis to change it.")
    await db.workouts.update_one(
        {"id": wid},
        {"$set": {
            "skipped": True,
            "recovery_status": "skipped",
            "recovery_reason": body.reason or "Client chose to skip and continue.",
            "rescheduled_by": "coach" if user["role"] == "coach" else "client",
            "rescheduled_at": now_iso(),
            "updated_at": now_iso(),
        }},
    )
    try:
        await db.timeline_events.insert_one({
            "id": new_id(),
            "user_id": user["id"],
            "kind": "workout_skipped",
            "workout_id": wid,
            "date": w.get("date"),
            "reason": body.reason,
            "created_at": now_iso(),
        })
    except Exception:
        logger.exception("failed to write timeline event for skip")

    if w.get("key_session"):
        try:
            await _create_coach_task(
                user, "key_session_skipped",
                f"Key session skipped: {user.get('name') or user.get('email')}",
                f"Client skipped a key session originally on {w.get('date')}.",
                priority="high",
                category="programme_adherence",
                payload={"workout_id": wid, "date": w.get("date")},
            )
        except Exception:
            logger.exception("failed to create coach task for key skip")
    return {"ok": True, "workout_id": wid}


# ---------------------------------------------------------------------------
# Iter 94v (Phase 4) — Coach recovery timeline
# ---------------------------------------------------------------------------

from server import require_role  # noqa: E402


@api.get("/admin/recovery/timeline")
async def admin_recovery_timeline(user: dict = Depends(require_role("coach")), limit: int = 100):
    """Coach view — recent recovery / skip events across all clients.

    Reads the timeline_events collection the recovery flow writes to. Adds
    the client's email/name so the coach dashboard can render a proper
    "who did what" list without a second lookup.
    """
    rows = await db.timeline_events.find(
        {"kind": {"$in": ["workout_recovered", "workout_skipped"]}}, {"_id": 0},
    ).sort("created_at", -1).to_list(min(500, max(10, int(limit)))) if hasattr(db, "timeline_events") else []
    # Batch-load users for the payload.
    user_ids = list({r.get("user_id") for r in rows if r.get("user_id")})
    users = {}
    if user_ids:
        async for u in db.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "name": 1, "email": 1}):
            users[u["id"]] = u
    for r in rows:
        c = users.get(r.get("user_id")) or {}
        r["client_name"] = c.get("name")
        r["client_email"] = c.get("email")
    return {"events": rows, "count": len(rows)}


@api.get("/admin/client/{uid}/recovery/timeline")
async def admin_client_recovery_timeline(uid: str, user: dict = Depends(require_role("coach")), limit: int = 100):
    rows = await db.timeline_events.find(
        {"user_id": uid, "kind": {"$in": ["workout_recovered", "workout_skipped"]}}, {"_id": 0},
    ).sort("created_at", -1).to_list(min(500, max(10, int(limit)))) if hasattr(db, "timeline_events") else []
    return {"events": rows or [], "count": len(rows or [])}
