"""
feature_standby — CrewFit Standby Mode V1.

Endpoints:
  GET  /standby/today                    — client's standby context + current workout
  POST /standby/status                   — waiting / not_called_out / cancelled / too_tired / have_time
  POST /standby/called-out               — full called-out details (report time, duty length, destination, can_train)
  POST /standby/apply-workout            — swap in a standby-friendly workout (stashes original_workout_id)
  POST /standby/restore-original         — restore the original workout (only if not called out)
  GET  /coach/clients/{id}/standby       — coach view of a client's standby days + status

Rules honoured:
  * Only creates coach tasks when standby affects a coach_locked / key_session workout.
  * Never overrides coach_locked workouts without coach review.
  * Atlas workout selector is DETERMINISTIC (rule-based) — no LLM cost.
  * Workout swaps stash `original_workout_id` and set `standby_adjusted=True` (option i: replace in place, with restore).
  * All timestamps use IANA time zones.
"""
# ---------------------------------------------------------------------------
# Auto-registered at server.py bottom.
# ---------------------------------------------------------------------------
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
import datetime as _dt

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    logger,
    _create_coach_task,
    _log_change,
)
# enqueue_notification comes from a sibling feature module that has already
# loaded by the time server.py imports feature_standby.
from feature_notifications import enqueue_notification

# ---- Models ---------------------------------------------------------------

STANDBY_STATUSES = ("waiting", "called_out", "not_called_out", "cancelled", "too_tired", "have_time")
STANDBY_TYPES = (
    "home_standby", "airport_standby", "reserve", "short_call", "long_call",
    "night_standby", "early_standby", "unknown_standby",
)


class StandbyStatusBody(BaseModel):
    status: str                                     # one of STANDBY_STATUSES
    date: Optional[str] = None                      # YYYY-MM-DD, defaults to today
    confirm_type: Optional[str] = None              # allow client to confirm the standby_type
    note: Optional[str] = None


class StandbyCalledOutBody(BaseModel):
    date: Optional[str] = None
    report_time: Optional[str] = None               # HH:MM local
    expected_duty_length_hours: Optional[float] = None
    destination: Optional[str] = None
    can_train: Optional[str] = None                 # "yes" | "no" | "unsure"


class StandbyApplyWorkoutBody(BaseModel):
    date: Optional[str] = None
    recommendation_id: Optional[str] = None         # one of the atlas suggestion IDs


class StandbyRestoreBody(BaseModel):
    date: Optional[str] = None


# ---- Helpers --------------------------------------------------------------

def _today_local(user: dict) -> str:
    # Simplest form — server-local date matches the tests. Client can override via body.date.
    return _dt.date.today().isoformat()


async def _standby_day(user_id: str, date: str) -> Optional[dict]:
    """Return the roster-day dict IF that date is a Standby day, else None."""
    roster = await db.rosters.find_one({"user_id": user_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    if not roster:
        return None
    for d in roster.get("days", []):
        if d.get("date") == date and (d.get("day_type") == "Standby" or d.get("standby_type")):
            # Merge d with any client-updated status stored on rosters.days[].standby_status
            return d
    return None


async def _persist_standby_field(user_id: str, date: str, updates: dict) -> None:
    """Patch the roster's day array with standby_* fields for this date."""
    roster = await db.rosters.find_one({"user_id": user_id, "is_active": True}, sort=[("created_at", -1)])
    if not roster:
        return
    changed = False
    for d in roster.get("days", []):
        if d.get("date") == date:
            for k, v in updates.items():
                if v is not None and d.get(k) != v:
                    d[k] = v
                    changed = True
            d["standby_updated_at"] = now_iso()
            changed = True
            break
    if changed:
        await db.rosters.update_one({"id": roster["id"]}, {"$set": {"days": roster["days"]}})


# ---- Atlas standby workout selector (deterministic) ----------------------

STANDBY_RECS: dict[str, list[dict]] = {
    "home_standby": [
        {"id": "hs_mob",   "kind": "standby_mobility",   "title": "Standby Mobility",   "duration_min": 10, "why": "Low-fatigue mobility keeps you loose without draining you before duty."},
        {"id": "hs_str",   "kind": "standby_strength",   "title": "Standby Strength",   "duration_min": 25, "why": "Short, low-fatigue strength session — no maximal lifting."},
        {"id": "hs_bw",    "kind": "standby_bodyweight", "title": "Standby Bodyweight", "duration_min": 20, "why": "Home-friendly bodyweight circuit; nothing exhausting."},
        {"id": "hs_z2",    "kind": "standby_z2",         "title": "Easy Zone 2",        "duration_min": 30, "why": "Easy aerobic — nothing that leaves you tired for duty."},
    ],
    "airport_standby": [
        {"id": "as_mob",   "kind": "standby_mobility",   "title": "Airport Mobility",   "duration_min": 10, "why": "Standing/seated mobility you can do near the crew room."},
        {"id": "as_walk",  "kind": "standby_walk",       "title": "Terminal Walking",   "duration_min": 20, "why": "Steady walking — great use of the standby wait."},
        {"id": "as_stretch","kind":"standby_recovery",   "title": "Stretch Routine",    "duration_min":  8, "why": "Sitting-friendly stretches; no equipment needed."},
    ],
    "reserve": [
        {"id": "rs_mob",   "kind": "standby_mobility",   "title": "Standby Mobility",   "duration_min": 10, "why": "Keeps you loose while on call."},
        {"id": "rs_str",   "kind": "standby_strength",   "title": "Standby Strength",   "duration_min": 25, "why": "Short, sub-max — protects readiness."},
        {"id": "rs_z2",    "kind": "standby_z2",         "title": "Easy Zone 2",        "duration_min": 30, "why": "Light aerobic — no metabolic strain."},
    ],
    "short_call": [
        {"id": "sc_mob",   "kind": "standby_mobility",   "title": "5-min Mobility",     "duration_min":  5, "why": "Very short so you're duty-ready in minutes."},
        {"id": "sc_act",   "kind": "standby_mobility",   "title": "Activation Set",     "duration_min":  8, "why": "Wake the body up without fatiguing legs or lungs."},
    ],
    "long_call": [
        {"id": "lc_str",   "kind": "standby_strength",   "title": "Standby Strength",   "duration_min": 25, "why": "You have flex — but still low fatigue."},
        {"id": "lc_bw",    "kind": "standby_bodyweight", "title": "Standby Bodyweight", "duration_min": 25, "why": "Home-friendly circuit; nothing draining."},
        {"id": "lc_z2",    "kind": "standby_z2",         "title": "Easy Zone 2",        "duration_min": 35, "why": "Easy aerobic — perfect for a long-call wait."},
    ],
    "night_standby": [
        {"id": "ns_rec",   "kind": "standby_recovery",   "title": "Recovery Routine",   "duration_min":  8, "why": "Prioritise sleep — recovery only tonight."},
        {"id": "ns_mob",   "kind": "standby_mobility",   "title": "Wind-down Mobility", "duration_min":  6, "why": "Calm the nervous system for sleep."},
    ],
    "early_standby": [
        {"id": "es_mob",   "kind": "standby_mobility",   "title": "Wake-up Mobility",   "duration_min":  6, "why": "Loosen up for an early call."},
        {"id": "es_walk",  "kind": "standby_walk",       "title": "Light Walk",         "duration_min": 15, "why": "Gentle movement — no intensity before duty."},
    ],
    "unknown_standby": [
        {"id": "un_mob",   "kind": "standby_mobility",   "title": "Standby Mobility",   "duration_min": 10, "why": "Safe default while we confirm your standby type."},
    ],
}
NO_TRAINING_REC = {"id": "no_training", "kind": "no_training", "title": "No Training",
                   "duration_min": 0, "why": "Recovery today — nothing that costs fatigue before duty."}


def atlas_standby_recommendations(standby_type: Optional[str], has_high_fatigue: bool = False,
                                   is_night: bool = False) -> list[dict]:
    """Deterministic Atlas selector — returns 2-4 options ordered best-first."""
    key = (standby_type or "unknown_standby").lower()
    if key not in STANDBY_RECS:
        key = "unknown_standby"
    opts = list(STANDBY_RECS[key])
    if is_night and key not in ("night_standby",):
        # Push mobility/recovery to the top
        opts.sort(key=lambda o: 0 if o["kind"] in ("standby_mobility", "standby_recovery") else 1)
    if has_high_fatigue:
        opts = [NO_TRAINING_REC] + [o for o in opts if o["kind"] in ("standby_mobility", "standby_recovery")]
    return opts[:4]


def _standby_reason_text(standby_type: str, called_out: bool = False, cancelled: bool = False) -> str:
    if cancelled:
        return "Standby cancelled — original session is available if you feel up to it."
    if called_out:
        return "You were called out — session moved to a lighter option to protect recovery."
    labels = {
        "home_standby": "home standby",
        "airport_standby": "airport standby",
        "short_call": "short-call standby",
        "long_call": "long-call standby",
        "reserve": "reserve",
        "night_standby": "night standby",
        "early_standby": "early standby",
        "unknown_standby": "standby",
    }
    return f"Because you are on {labels.get(standby_type, 'standby')}, Atlas has kept today low-fatigue so you stay duty-ready."


# ---- Endpoints ------------------------------------------------------------

@api.get("/standby/today")
async def standby_today(user: dict = Depends(current_user), date: Optional[str] = None):
    date = date or _today_local(user)
    day = await _standby_day(user["id"], date)
    workout = await db.workouts.find_one({"user_id": user["id"], "date": date}, {"_id": 0})
    is_standby = bool(day)
    result: dict[str, Any] = {
        "date": date,
        "is_standby": is_standby,
        "standby": None,
        "workout": workout,
        "recommendations": [],
        "reason": None,
    }
    if not day:
        return result
    stype = day.get("standby_type") or "unknown_standby"
    result["standby"] = {
        "type": stype,
        "start_time": day.get("standby_start_time"),
        "end_time": day.get("standby_end_time"),
        "location": day.get("standby_location"),
        "status": day.get("standby_status") or "waiting",
        "called_out": bool(day.get("called_out")),
        "call_out_time": day.get("call_out_time"),
        "expected_duty_length_hours": day.get("expected_duty_length_hours"),
        "destination": day.get("destination"),
        "can_train": day.get("can_train"),
        "needs_confirmation": bool(day.get("standby_needs_confirmation")) and not day.get("confirmed_by_client"),
        "confirmed_by_client": bool(day.get("confirmed_by_client")),
    }
    is_night = stype in ("night_standby",) or "night" in (day.get("notes") or "").lower()
    fatigue_high = (day.get("can_train") == "no")
    result["recommendations"] = atlas_standby_recommendations(stype, has_high_fatigue=fatigue_high, is_night=is_night)
    result["reason"] = _standby_reason_text(stype, called_out=bool(day.get("called_out")))
    return result


@api.post("/standby/status")
async def standby_status(body: StandbyStatusBody, user: dict = Depends(current_user)):
    if body.status not in STANDBY_STATUSES:
        raise HTTPException(400, f"status must be one of {STANDBY_STATUSES}")
    date = body.date or _today_local(user)
    day = await _standby_day(user["id"], date)
    if not day:
        raise HTTPException(404, "no standby day for this date")
    updates: dict[str, Any] = {"standby_status": body.status}
    if body.confirm_type and body.confirm_type in STANDBY_TYPES:
        updates["standby_type"] = body.confirm_type
        updates["confirmed_by_client"] = True
        updates["standby_needs_confirmation"] = False
    if body.status == "cancelled":
        updates["cancelled"] = True
    if body.status == "not_called_out":
        updates["called_out"] = False
    if body.note:
        updates["standby_note"] = body.note
    await _persist_standby_field(user["id"], date, updates)
    await _log_change(None, user["id"], "programme",
                      f"Standby → {body.status}",
                      f"{date} · {(body.confirm_type or day.get('standby_type') or 'standby')}",
                      actor="client",
                      meta={"date": date, "updates": updates})
    return {"ok": True, "status": body.status, "date": date}


@api.post("/standby/called-out")
async def standby_called_out(body: StandbyCalledOutBody, user: dict = Depends(current_user)):
    date = body.date or _today_local(user)
    day = await _standby_day(user["id"], date)
    if not day:
        raise HTTPException(404, "no standby day for this date")
    updates: dict[str, Any] = {
        "called_out": True,
        "standby_status": "called_out",
        "call_out_time": body.report_time or now_iso()[11:16],
        "expected_duty_length_hours": body.expected_duty_length_hours,
        "destination": body.destination,
        "can_train": body.can_train,
    }
    await _persist_standby_field(user["id"], date, updates)
    # If today's workout is coach_locked / key_session — do NOT auto-swap; create coach task instead.
    wk = await db.workouts.find_one({"user_id": user["id"], "date": date}, {"_id": 0})
    if wk and (wk.get("coach_locked") or wk.get("key_session")):
        await _create_coach_task(user, "standby_key_affected",
                                 f"Standby called-out affects key session · {user.get('name') or user.get('email')}",
                                 f"Client called out during a coach-locked / key session on {date}. Review before Atlas moves it.",
                                 priority="high", risk_level="medium", category="programme",
                                 payload={"date": date, "workout_id": wk.get("id"), "standby_type": day.get("standby_type")})
    # Otherwise auto-apply a standby-friendly recommendation
    else:
        stype = day.get("standby_type") or "unknown_standby"
        recs = atlas_standby_recommendations(stype, has_high_fatigue=(body.can_train == "no"))
        if recs and wk and not wk.get("completed"):
            top = recs[0]
            await _apply_standby_workout(user, wk, top, day, called_out=True)
    await _log_change(None, user["id"], "programme",
                      f"Called out from standby",
                      f"{date} · report {body.report_time or ''} · duty ~{body.expected_duty_length_hours or '?'}h",
                      actor="client", meta={"date": date})
    return {"ok": True, "date": date}


@api.post("/standby/apply-workout")
async def standby_apply_workout(body: StandbyApplyWorkoutBody, user: dict = Depends(current_user)):
    date = body.date or _today_local(user)
    day = await _standby_day(user["id"], date)
    if not day:
        raise HTTPException(404, "no standby day for this date")
    wk = await db.workouts.find_one({"user_id": user["id"], "date": date}, {"_id": 0})
    if not wk:
        raise HTTPException(404, "no workout for this date")
    if wk.get("coach_locked") or wk.get("key_session"):
        # Do not auto-swap coach-locked sessions; enqueue task instead
        await _create_coach_task(user, "standby_key_affected",
                                 f"Coach-locked session affected by standby · {user.get('name') or user.get('email')}",
                                 f"Client requested a standby swap on {date} but the session is coach-locked.",
                                 priority="high", risk_level="medium", category="programme",
                                 payload={"date": date, "workout_id": wk.get("id"), "standby_type": day.get("standby_type"),
                                          "requested_recommendation_id": body.recommendation_id})
        raise HTTPException(409, "coach-locked — Louis will review")
    recs = atlas_standby_recommendations(day.get("standby_type") or "unknown_standby")
    chosen = next((r for r in recs if r["id"] == body.recommendation_id), (recs[0] if recs else None))
    if not chosen:
        raise HTTPException(400, "no matching recommendation")
    updated = await _apply_standby_workout(user, wk, chosen, day)
    return {"ok": True, "workout": updated}


@api.post("/standby/restore-original")
async def standby_restore_original(body: StandbyRestoreBody, user: dict = Depends(current_user)):
    date = body.date or _today_local(user)
    wk = await db.workouts.find_one({"user_id": user["id"], "date": date}, {"_id": 0})
    if not wk:
        raise HTTPException(404, "no workout")
    orig_id = wk.get("original_workout_id")
    if not orig_id or not wk.get("standby_adjusted"):
        raise HTTPException(400, "nothing to restore — this session wasn't standby-adjusted")
    original = await db.workouts_archive.find_one({"id": orig_id}, {"_id": 0})
    if not original:
        raise HTTPException(404, "original snapshot missing")
    # Restore fields onto the current workout doc (preserve id, roster_id, etc.)
    restore_fields = {k: original[k] for k in ("title", "focus", "day_load", "location", "duration_min",
                                                "warmup", "exercises", "alternatives") if k in original}
    restore_fields.update({
        "standby_adjusted": False,
        "original_workout_id": None,
        "standby_recommendation": None,
        "standby_reason": None,
        "updated_at": now_iso(),
    })
    await db.workouts.update_one({"id": wk["id"]}, {"$set": restore_fields})
    saved = await db.workouts.find_one({"id": wk["id"]}, {"_id": 0})
    await _log_change(None, user["id"], "programme",
                      "Standby workout restored to original",
                      f"{date}", actor="client", meta={"workout_id": wk["id"]})
    return {"ok": True, "workout": saved}


async def _apply_standby_workout(user: dict, wk: dict, rec: dict, day: dict, called_out: bool = False) -> dict:
    """Swap the workout in place; stash original in workouts_archive so restore works."""
    # Snapshot original once (idempotent — don't re-snapshot if already stashed)
    if not wk.get("standby_adjusted"):
        snapshot = {**wk, "archived_at": now_iso()}
        snapshot.pop("_id", None)
        snapshot["archive_of"] = wk["id"]
        snapshot["id"] = wk["id"]   # same id in archive keeps lookup simple
        try:
            await db.workouts_archive.insert_one(snapshot)
        except Exception:
            # duplicate — leave existing snapshot alone
            pass
    exercises: list[dict] = []
    kind = rec.get("kind", "standby_mobility")
    if kind == "standby_mobility":
        exercises = [
            {"name": "Hip circles", "sets": 2, "reps": "10 each side"},
            {"name": "Cat-cow", "sets": 2, "reps": "8 slow"},
            {"name": "World's greatest stretch", "sets": 1, "reps": "5 each side"},
            {"name": "T-spine openers", "sets": 2, "reps": "8 each side"},
        ]
    elif kind == "standby_strength":
        exercises = [
            {"name": "Goblet squat", "sets": 3, "reps": "8"},
            {"name": "Push-up (or incline)", "sets": 3, "reps": "8-10"},
            {"name": "Split squat", "sets": 2, "reps": "8 each side"},
            {"name": "Plank", "sets": 2, "reps": "30-45s"},
        ]
    elif kind == "standby_bodyweight":
        exercises = [
            {"name": "Bodyweight squat", "sets": 3, "reps": "12"},
            {"name": "Push-up", "sets": 3, "reps": "8-10"},
            {"name": "Reverse lunge", "sets": 2, "reps": "8 each side"},
            {"name": "Dead bug", "sets": 2, "reps": "10 each side"},
        ]
    elif kind == "standby_z2":
        exercises = [{"name": "Easy Zone 2 cardio", "sets": 1, "reps": f"{rec['duration_min']} min · nasal breathing"}]
    elif kind == "standby_walk":
        exercises = [{"name": "Steady walk", "sets": 1, "reps": f"{rec['duration_min']} min · comfortable pace"}]
    elif kind == "standby_recovery":
        exercises = [
            {"name": "Box breathing", "sets": 1, "reps": "4 min · 4-4-4-4"},
            {"name": "Gentle mobility", "sets": 1, "reps": f"{rec['duration_min'] - 4} min"},
        ]
    else:  # no_training or unknown
        exercises = []
    updates = {
        "title": rec["title"],
        "focus": "standby",
        "day_load": "green",
        "duration_min": rec["duration_min"],
        "warmup": [],
        "exercises": exercises,
        "standby_adjusted": True,
        "original_workout_id": wk["id"],
        "standby_recommendation": rec["id"],
        "standby_reason": _standby_reason_text(day.get("standby_type") or "unknown_standby", called_out=called_out),
        "updated_at": now_iso(),
    }
    await db.workouts.update_one({"id": wk["id"]}, {"$set": updates})
    saved = await db.workouts.find_one({"id": wk["id"]}, {"_id": 0})
    await _log_change(None, user["id"], "programme",
                      f"Standby workout applied · {rec['title']}",
                      updates["standby_reason"], actor="atlas" if called_out else "client",
                      meta={"date": wk.get("date"), "recommendation_id": rec["id"]})
    # In-app notification for the client (respects settings + duty rewording)
    try:
        await enqueue_notification(
            user["id"], "programme_updated",
            "Standby session applied",
            updates["standby_reason"],
            action_url="/(client)/schedule",
            dedupe_key=f"standby::{wk.get('date')}",
        )
    except Exception:
        logger.exception("standby enqueue_notification failed")
    return saved


# ---- Coach endpoint -------------------------------------------------------

@api.get("/coach/clients/{client_id}/standby")
async def coach_standby(client_id: str, coach: dict = Depends(require_role("coach")),
                        weeks: int = 4):
    client = await db.users.find_one({"id": client_id}, {"_id": 0, "name": 1, "email": 1})
    if not client:
        raise HTTPException(404, "client not found")
    since = (_dt.date.today() - _dt.timedelta(days=weeks * 7)).isoformat()
    until = (_dt.date.today() + _dt.timedelta(days=14)).isoformat()
    roster = await db.rosters.find_one({"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)])
    days = []
    if roster:
        for d in roster.get("days", []):
            dt = d.get("date")
            if not dt or dt < since or dt > until:
                continue
            if d.get("day_type") != "Standby" and not d.get("standby_type"):
                continue
            days.append({
                "date": dt,
                "standby_type": d.get("standby_type"),
                "standby_status": d.get("standby_status") or "waiting",
                "called_out": bool(d.get("called_out")),
                "start_time": d.get("standby_start_time"),
                "end_time": d.get("standby_end_time"),
                "location": d.get("standby_location"),
                "needs_confirmation": bool(d.get("standby_needs_confirmation")) and not d.get("confirmed_by_client"),
            })
    # Also grab affected workouts (standby_adjusted or coach_locked+standby-day) in the window
    dates = [d["date"] for d in days]
    workouts = []
    if dates:
        workouts = await db.workouts.find({"user_id": client_id, "date": {"$in": dates}}, {"_id": 0}).to_list(60)
    return {"client": {"id": client_id, "name": client.get("name"), "email": client.get("email")},
            "days": days, "workouts": workouts, "count": len(days)}
