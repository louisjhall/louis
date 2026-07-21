"""
feature_progression — Phase 3 of MASTER FIX PROMPT.

Reactive weekly progression: when a client completes the LAST scheduled workout
of their ISO week, compute a progression_status for that week and persist it as
a snapshot. The next workout regeneration reads this to adjust load.

Statuses:
  * "progressing_well" — adherence ≥80%, RPE in 6-8 band, no missed key sessions
                          → next week can bump load / volume ~5%
  * "maintain"         — adherence 60-79%, RPE 7-9
                          → hold current load, small technique focus
  * "reduce_load"      — adherence <60% OR RPE ≥9 average
                          → drop next week's working weights ~10%
  * "deload"           — RPE ≥9.5 sustained AND session count high
                          → planned deload week (~40% volume reduction)

Also emits a plain-english `reason` string for the client "Your Progress" card
and `coach_note` for the coach dashboard.

Trigger:
  * `on_workout_completed(db, user, workout)` — called from
    POST /api/workouts/{wid}/complete. If this workout is the last completed
    session of the ISO week AND at least one session in this week is planned
    AND we haven't already snapshotted this week → compute + persist.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constants / thresholds
# ---------------------------------------------------------------------------

STATUS_PROGRESSING = "progressing_well"
STATUS_MAINTAIN = "maintain"
STATUS_REDUCE = "reduce_load"
STATUS_DELOAD = "deload"

STATUS_LABELS = {
    STATUS_PROGRESSING: "PROGRESSING",
    STATUS_MAINTAIN: "STEADY",
    STATUS_REDUCE: "PULL BACK",
    STATUS_DELOAD: "DELOAD",
}

STATUS_COPY = {
    STATUS_PROGRESSING: "Solid week — adherence and effort are dialled in. Next week we push the load a little.",
    STATUS_MAINTAIN: "Steady week — we'll hold the current load and sharpen technique next week.",
    STATUS_REDUCE: "You've been pushing hard — we're pulling back the load next week to keep you fresh.",
    STATUS_DELOAD: "Time for a planned deload — lighter volume next week to consolidate gains.",
}

STATUS_COACH_NOTE = {
    STATUS_PROGRESSING: "Client on track: adherence + RPE band healthy. Progressive overload OK.",
    STATUS_MAINTAIN: "Client holding: partial adherence. Maintain load, focus on execution.",
    STATUS_REDUCE: "Client under strain — high RPE or dropped sessions. Reduce load next block.",
    STATUS_DELOAD: "Deload triggered — client showing sustained max effort. Cut volume ~40% next week.",
}


# ---------------------------------------------------------------------------
# Week helpers (ISO week bounds)
# ---------------------------------------------------------------------------

def iso_week_bounds(day: _dt.date) -> tuple[_dt.date, _dt.date]:
    """Return (Monday, Sunday) of the ISO week containing `day`."""
    monday = day - _dt.timedelta(days=day.weekday())
    sunday = monday + _dt.timedelta(days=6)
    return monday, sunday


def week_key(day: _dt.date) -> str:
    """Stable string key for the week — e.g. '2026-W30'."""
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------------------
# Core calculator
# ---------------------------------------------------------------------------

def _get_rpe(w: dict[str, Any]) -> Optional[float]:
    """Extract RPE from a workout completion. Prefers workout.completion.rpe."""
    comp = w.get("completion") or {}
    r = comp.get("rpe")
    if isinstance(r, (int, float)):
        return float(r)
    r2 = w.get("rpe")
    if isinstance(r2, (int, float)):
        return float(r2)
    return None


def _is_key_session(w: dict[str, Any]) -> bool:
    return bool(w.get("key_session"))


def compute_status(
    workouts: list[dict[str, Any]],
    *,
    week_start: str,
    week_end: str,
) -> dict[str, Any]:
    """
    Given all workouts for a client for a given ISO week (planned + completed),
    return a progression snapshot dict:

      {
        status: "progressing_well" | "maintain" | "reduce_load" | "deload",
        status_label: "PROGRESSING",
        reason: "Solid week — adherence and effort are dialled in.",
        coach_note: "...",
        metrics: {
          sessions_planned: 4,
          sessions_completed: 3,
          adherence_pct: 75.0,
          avg_rpe: 7.8,
          key_missed: 0,
          skipped_reasons: [ ... ]
        },
        week_start, week_end,
        computed_at: <iso>,
      }
    """
    planned = [w for w in workouts if _is_planned(w)]
    completed = [w for w in planned if bool(w.get("completed"))]
    missed = [w for w in planned if not bool(w.get("completed"))]
    key_missed = sum(1 for w in missed if _is_key_session(w))
    rpes = [r for r in (_get_rpe(w) for w in completed) if r is not None]

    n_planned = len(planned)
    n_completed = len(completed)
    adherence_pct = (n_completed / n_planned * 100.0) if n_planned else 0.0
    avg_rpe = round(sum(rpes) / len(rpes), 2) if rpes else None
    high_rpe_count = sum(1 for r in rpes if r >= 9.0)
    very_high_rpe_count = sum(1 for r in rpes if r >= 9.5)

    # ---- Rule engine (order matters — first hit wins) ----
    if very_high_rpe_count >= 2 and n_completed >= 3:
        status = STATUS_DELOAD
    elif adherence_pct < 60.0:
        status = STATUS_REDUCE
    elif avg_rpe is not None and avg_rpe >= 9.0:
        status = STATUS_REDUCE
    elif key_missed >= 1 and adherence_pct < 80.0:
        status = STATUS_REDUCE
    elif adherence_pct >= 80.0 and (avg_rpe is None or 6.0 <= avg_rpe <= 8.5):
        status = STATUS_PROGRESSING
    else:
        status = STATUS_MAINTAIN

    return {
        "status": status,
        "status_label": STATUS_LABELS[status],
        "reason": STATUS_COPY[status],
        "coach_note": STATUS_COACH_NOTE[status],
        "metrics": {
            "sessions_planned": n_planned,
            "sessions_completed": n_completed,
            "adherence_pct": round(adherence_pct, 1),
            "avg_rpe": avg_rpe,
            "high_rpe_count": high_rpe_count,
            "very_high_rpe_count": very_high_rpe_count,
            "key_missed": key_missed,
        },
        "week_start": week_start,
        "week_end": week_end,
    }


def _is_planned(w: dict[str, Any]) -> bool:
    """A workout is 'planned' if it has real content — not a placeholder."""
    exs = w.get("exercises") or []
    warmup = w.get("warmup") or []
    return bool(exs or warmup)


# ---------------------------------------------------------------------------
# DB integration — trigger + persistence
# ---------------------------------------------------------------------------

async def _week_workouts(db, user_id: str, monday_str: str, sunday_str: str) -> list[dict[str, Any]]:
    """Return all workouts for this user with date in [monday, sunday]."""
    rows = await db.workouts.find(
        {"user_id": user_id, "date": {"$gte": monday_str, "$lte": sunday_str}},
        {"_id": 0},
    ).to_list(50)
    return rows


async def _get_existing_snapshot(db, user_id: str, week_str: str) -> Optional[dict[str, Any]]:
    return await db.progression_snapshots.find_one(
        {"user_id": user_id, "week_key": week_str}, {"_id": 0}
    )


async def compute_and_store_week(
    db, user_id: str, week_date: _dt.date, *, force: bool = False
) -> Optional[dict[str, Any]]:
    """Compute progression for the ISO week containing `week_date` and store it.

    If a snapshot already exists and `force=False`, returns the existing one.
    """
    monday, sunday = iso_week_bounds(week_date)
    monday_str = monday.isoformat()
    sunday_str = sunday.isoformat()
    wk = week_key(week_date)

    existing = await _get_existing_snapshot(db, user_id, wk)
    if existing and not force:
        return existing

    workouts = await _week_workouts(db, user_id, monday_str, sunday_str)
    snap = compute_status(workouts, week_start=monday_str, week_end=sunday_str)
    snap["user_id"] = user_id
    snap["week_key"] = wk
    snap["computed_at"] = _dt.datetime.utcnow().isoformat() + "Z"

    if existing:
        # Preserve id but replace metrics
        snap["id"] = existing.get("id") or f"snap_{user_id}_{wk}"
        await db.progression_snapshots.update_one(
            {"user_id": user_id, "week_key": wk},
            {"$set": snap},
            upsert=True,
        )
    else:
        snap["id"] = f"snap_{user_id}_{wk}"
        await db.progression_snapshots.insert_one(snap)
    return {k: v for k, v in snap.items() if k != "_id"}


async def on_workout_completed(db, user: dict[str, Any], workout: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Called from POST /api/workouts/{wid}/complete AFTER the workout has been
    persisted as completed.

    Logic:
      1. Determine the ISO week of this workout's date.
      2. If there are no other PLANNED workouts in that week that are still
         incomplete → this was the LAST session of the week. Compute and store
         a progression snapshot.
      3. Otherwise → do nothing (wait for the next completion).

    Returns the snapshot dict when one was created, else None.
    """
    d = workout.get("date")
    if not d:
        return None
    try:
        day = _dt.date.fromisoformat(str(d)[:10])
    except Exception:
        return None
    monday, sunday = iso_week_bounds(day)
    monday_str, sunday_str = monday.isoformat(), sunday.isoformat()
    week_wkts = await _week_workouts(db, user["id"], monday_str, sunday_str)
    # Only count real planned sessions
    planned = [w for w in week_wkts if _is_planned(w)]
    if not planned:
        return None
    remaining = [w for w in planned if not w.get("completed")]
    if remaining:
        # Not the last one yet — don't compute
        return None
    # This was the final session — recompute and store
    return await compute_and_store_week(db, user["id"], day, force=True)


async def latest_snapshot(db, user_id: str) -> Optional[dict[str, Any]]:
    """Return the most recent progression snapshot for a user, or None."""
    snap = await db.progression_snapshots.find_one(
        {"user_id": user_id},
        {"_id": 0},
        sort=[("week_key", -1)],
    )
    return snap


async def snapshot_history(db, user_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return the last `limit` snapshots, most recent first."""
    rows = await db.progression_snapshots.find(
        {"user_id": user_id}, {"_id": 0},
    ).sort([("week_key", -1)]).limit(limit).to_list(limit)
    return rows
