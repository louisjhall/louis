"""
feature_equipment_guard.py — Iter 95h

Prevents the class of bug where a client with real equipment (dumbbells,
kettlebells, barbell, bench, cable, rower) still ends up with a workout
that only uses bodyweight movements.

Called from `_heal_workouts_batch` after every heal, and from
`apply_resolver_to_workouts` after resolution. If a mismatch is detected
we:
  1. Flag the workout with `equipment_mismatch: true`.
  2. Create a coach task so Louis is notified BEFORE the client sees it.
  3. Emit a telemetry event for the coach dashboard tile.

Zero LLM spend. Pure guard.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

logger = logging.getLogger("crewfit.equipment_guard")

# What we consider "resistance equipment" — if the client owns any of these
# and the workout doesn't use any, we flag.
_RESISTANCE_KEYWORDS = (
    "dumbbell", "kettlebell", "barbell", "bench", "cable", "rower",
    "band", "resistance", "trx", "sandbag", "sled", "machine",
)

_ENDURANCE_KEYWORDS = ("rower", "treadmill", "assault bike", "bike", "cycle")


def _has_equipment_string(equipment: list, keywords: tuple[str, ...]) -> bool:
    for e in equipment or []:
        low = str(e).lower()
        if any(kw in low for kw in keywords):
            return True
    return False


def workout_uses_equipment(workout: dict) -> set[str]:
    """Return the set of equipment keywords actually used inside the workout's
    exercises (not warmup/cooldown)."""
    used: set[str] = set()
    for ex in workout.get("exercises") or []:
        name = str(ex.get("name") or "").lower()
        eq = ex.get("equipment") or ex.get("equipment_type") or []
        # Names carry the truth 80% of the time.
        for kw in _RESISTANCE_KEYWORDS:
            if kw in name:
                used.add(kw)
        for e in eq:
            low = str(e).lower()
            for kw in _RESISTANCE_KEYWORDS:
                if kw in low:
                    used.add(kw)
    return used


def is_pure_bodyweight_workout(workout: dict) -> bool:
    """True if every non-mobility exercise in the workout is bodyweight."""
    exs = workout.get("exercises") or []
    if not exs:
        return False   # empty workout — different issue, not our problem here
    used = workout_uses_equipment(workout)
    return len(used) == 0


def check_alignment(workout: dict, client_equipment: list, *, workout_type: str = "") -> dict:
    """Return {ok: bool, reason: str, missing_tiers: [...]}."""
    if not client_equipment:
        return {"ok": True, "reason": "no client equipment declared", "missing_tiers": []}

    has_resistance_kit = _has_equipment_string(client_equipment, _RESISTANCE_KEYWORDS)
    if not has_resistance_kit:
        return {"ok": True, "reason": "client is bodyweight-only", "missing_tiers": []}

    # Endurance / recovery / mobility sessions are allowed to be bodyweight.
    wt = str(workout_type or workout.get("focus") or workout.get("session_type") or "").lower()
    if any(k in wt for k in ("run", "swim", "bike", "cycle", "mobility", "recovery", "rest", "walk")):
        return {"ok": True, "reason": f"endurance/recovery session ({wt})", "missing_tiers": []}

    if is_pure_bodyweight_workout(workout):
        # Which tiers did the client own that were ignored?
        missing = []
        for kw in _RESISTANCE_KEYWORDS:
            if _has_equipment_string(client_equipment, (kw,)):
                missing.append(kw)
        return {
            "ok": False,
            "reason": (
                f"Client owns {', '.join(missing)} but this workout uses only "
                "bodyweight movements — likely a resolver fallback bug."
            ),
            "missing_tiers": missing,
        }
    return {"ok": True, "reason": "workout uses at least one of client's equipment types", "missing_tiers": []}


async def enforce_and_notify(
    db,
    user: dict,
    workout: dict,
    *,
    reason_source: str = "heal",
) -> Optional[dict]:
    """Run the guard on a workout. If mismatched, mark it, log a telemetry
    event and create a coach task. Returns the alignment dict."""
    profile = (user or {}).get("profile") or {}
    equipment = (
        (user or {}).get("equipment")
        or (user or {}).get("home_equipment")
        or profile.get("equipment")
        or profile.get("home_equipment")
        or []
    )
    result = check_alignment(workout, equipment)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    if not result["ok"]:
        wid = workout.get("id") or workout.get("_id")
        # 1. Flag the workout doc.
        try:
            await db.workouts.update_one(
                {"id": wid},
                {"$set": {
                    "equipment_mismatch": True,
                    "equipment_mismatch_reason": result["reason"],
                    "equipment_mismatch_at": now,
                    "equipment_mismatch_source": reason_source,
                }},
            )
        except Exception:
            logger.exception("failed to flag workout equipment mismatch")

        # 2. Telemetry event for the coach dashboard tile.
        try:
            await db.equipment_mismatches.update_one(
                {"user_id": user.get("id"), "workout_id": wid},
                {"$setOnInsert": {
                    "user_id": user.get("id"),
                    "user_email": user.get("email"),
                    "workout_id": wid,
                    "workout_date": workout.get("date"),
                    "workout_title": workout.get("title"),
                    "missing_tiers": result["missing_tiers"],
                    "reason": result["reason"],
                    "source": reason_source,
                    "detected_at": now,
                    "resolved": False,
                }},
                upsert=True,
            )
        except Exception:
            logger.exception("failed to write equipment_mismatches telemetry")

        # 3. Coach task — idempotent per workout.
        try:
            await db.coach_tasks.update_one(
                {"user_id": user.get("id"), "task_type": "equipment_mismatch",
                 "payload.workout_id": wid},
                {"$setOnInsert": {
                    "id": f"equip-{wid}",
                    "user_id": user.get("id"),
                    "task_type": "equipment_mismatch",
                    "title": (
                        f"Workout used only bodyweight — {user.get('name') or user.get('email')}"
                    ),
                    "body": (
                        f"{result['reason']} · Workout: {workout.get('title')} on {workout.get('date')}."
                    ),
                    "priority": "high",
                    "category": "quality",
                    "status": "todo",
                    "created_at": now,
                    "payload": {"workout_id": wid,
                                "missing_tiers": result["missing_tiers"]},
                }},
                upsert=True,
            )
        except Exception:
            logger.exception("failed to create equipment_mismatch coach task")

    return result


# ---------------------------------------------------------------------------
# Coach dashboard endpoints (Iter 95h #4)
# ---------------------------------------------------------------------------

from fastapi import Depends, HTTPException           # noqa: E402
from server import api, current_user, db as _db      # noqa: E402


@api.get("/coach/equipment-mismatches")
async def coach_equipment_mismatches(
    window_days: int = 14,
    user: dict = Depends(current_user),
):
    """Summary tile — how many client workouts fell back to bodyweight
    despite the client owning real equipment, in the last N days.
    """
    if user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Coach only")
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=window_days)).isoformat()
    rows = await _db.equipment_mismatches.find(
        {"detected_at": {"$gte": cutoff}, "resolved": {"$ne": True}},
        {"_id": 0},
    ).sort("detected_at", -1).to_list(200)
    # Group by user for a clean tile.
    by_user: dict[str, dict] = {}
    for r in rows:
        uid = r.get("user_id") or ""
        by_user.setdefault(uid, {
            "user_id": uid, "user_email": r.get("user_email"),
            "count": 0, "latest": r.get("detected_at"),
            "example_workout": r.get("workout_title"),
        })
        by_user[uid]["count"] += 1
    return {
        "total_workouts": len(rows),
        "clients_affected": len(by_user),
        "window_days": window_days,
        "by_user": sorted(by_user.values(), key=lambda x: -x["count"]),
        "items": rows[:50],
    }


@api.post("/coach/equipment-mismatches/{workout_id}/resolve")
async def coach_equipment_mismatch_resolve(
    workout_id: str, user: dict = Depends(current_user),
):
    if user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Coach only")
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    await _db.equipment_mismatches.update_many(
        {"workout_id": workout_id},
        {"$set": {"resolved": True, "resolved_at": now, "resolved_by": user.get("id")}},
    )
    return {"ok": True, "workout_id": workout_id}


# ---------------------------------------------------------------------------
# Verify-now scan (Iter 95h — safety-net #3)
# ---------------------------------------------------------------------------

@api.post("/coach/equipment-mismatches/scan-now")
async def coach_equipment_scan_now(user: dict = Depends(current_user)):
    """Runs the guard across every FUTURE workout in the DB right now.
    Returns a per-user summary. Coach-only. Idempotent (safe to spam)."""
    if user.get("role") != "coach":
        raise HTTPException(status_code=403, detail="Coach only")
    today = _dt.date.today().isoformat()

    # Preload users once, index by id.
    users = {u["id"]: u async for u in _db.users.find({}, {"_id": 0})}

    scanned = 0
    flagged = 0
    per_user: dict[str, int] = {}

    async for w in _db.workouts.find(
        {"date": {"$gte": today}, "completed": {"$ne": True}},
        {"_id": 0},
    ):
        uid = w.get("user_id")
        u = users.get(uid)
        if not u:
            continue
        scanned += 1
        res = await enforce_and_notify(_db, u, w, reason_source="scan_now")
        if not res.get("ok"):
            flagged += 1
            per_user[u.get("email") or uid] = per_user.get(u.get("email") or uid, 0) + 1

    return {
        "ok": True,
        "scanned": scanned,
        "flagged": flagged,
        "per_user": per_user,
        "run_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# On-write guard (Iter 95h — safety-net #2)
# ---------------------------------------------------------------------------

async def guard_after_workout_write(user_id: Optional[str], workout_id: str) -> Optional[dict]:
    """Call this after ANY code writes a workout doc. Idempotent + safe.

    Any future code path that inserts/updates a workout should call this
    once with (user_id, workout.id). If they forget, the scan-now endpoint
    picks it up as a safety net.
    """
    if not user_id or not workout_id:
        return None
    try:
        u = await _db.users.find_one({"id": user_id}, {"_id": 0})
        w = await _db.workouts.find_one({"id": workout_id}, {"_id": 0})
        if not u or not w:
            return None
        # Skip completed / already-flagged workouts.
        if w.get("completed") or w.get("equipment_mismatch"):
            return None
        return await enforce_and_notify(_db, u, w, reason_source="on_write")
    except Exception:
        logger.exception("guard_after_workout_write failed (non-fatal)")
        return None


# ---------------------------------------------------------------------------
# Global on-write hook (Iter 95h — safety-net #2, module init)
# ---------------------------------------------------------------------------
# Monkey-patches db.workouts.insert_one and .replace_one so ANY code path
# that writes a workout gets guarded automatically — even future code
# added by someone else who doesn't know this guard exists.

import asyncio as _asyncio  # noqa: E402


def _install_workout_write_hook():
    coll = _db.workouts
    if getattr(coll, "_crewfit_guard_installed", False):
        return
    original_insert = coll.insert_one
    original_replace = coll.replace_one

    async def _guarded_insert(doc, *args, **kwargs):
        result = await original_insert(doc, *args, **kwargs)
        try:
            uid = doc.get("user_id"); wid = doc.get("id")
            if uid and wid:
                # Fire-and-forget so we never block the write.
                _asyncio.create_task(guard_after_workout_write(uid, wid))
        except Exception:
            logger.exception("on-write hook (insert) failed non-fatally")
        return result

    async def _guarded_replace(filter_, replacement, *args, **kwargs):
        result = await original_replace(filter_, replacement, *args, **kwargs)
        try:
            uid = (replacement or {}).get("user_id") or (filter_ or {}).get("user_id")
            wid = (replacement or {}).get("id") or (filter_ or {}).get("id")
            if uid and wid:
                _asyncio.create_task(guard_after_workout_write(uid, wid))
        except Exception:
            logger.exception("on-write hook (replace) failed non-fatally")
        return result

    coll.insert_one = _guarded_insert       # type: ignore[assignment]
    coll.replace_one = _guarded_replace     # type: ignore[assignment]
    coll._crewfit_guard_installed = True    # type: ignore[attr-defined]
    logger.info("Iter 95h — workout on-write guard installed")


_install_workout_write_hook()
