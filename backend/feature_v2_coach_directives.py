"""
feature_v2_coach_directives — Coach Dashboard V2 · Structured Directive editor
+ Progressive generation status + Programme summary aggregate.

Bundles three closely-related coach-dashboard endpoints that fill out
Iteration 2 of the V2 coach dashboard build brief (§20, §24-25, §33-35).

All endpoints gated by the per-coach `coach_dashboard_v2_enabled` flag.
Nothing here mutates V1 collections.
"""
from __future__ import annotations

import datetime as _dt
from calendar import monthrange
from typing import Optional, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import write_decision, emit_metric


# ---------------------------------------------------------------------------
# Shared flag helper
# ---------------------------------------------------------------------------

async def _coach_has_v2_flag(coach_id: str) -> bool:
    coach = await db.users.find_one({"id": coach_id}, {"_id": 0, "profile.v2_flags": 1})
    if not coach:
        return False
    v2 = ((coach.get("profile") or {}).get("v2_flags") or {})
    return bool(v2.get("coach_dashboard_v2_enabled") or v2.get("v2_default"))


# ===========================================================================
# 1. Structured Directive editor (§33-35)
# ===========================================================================
#
# The Command Bar creates directives via LLM; the coach also needs to add
# them by hand. Both paths end up in the same `coach_directives` collection.
#
# Kinds:
#   avoid_movement  · pattern like "gait_run_tempo" / "deep_squat" / etc.
#   require_movement · pattern to force inclusion
#   limit_frequency · e.g. { discipline: "run", max_per_week: 2 }
#   limit_volume    · e.g. { delta_pct: -20 }
#   limit_intensity · e.g. { max_rpe: 7 }
#   note_only       · free-text memory for the coach, not the engine
#
# Scopes:
#   today | this_week | this_trip | phase | custom | until_changed
# ---------------------------------------------------------------------------

class DirectiveScope(BaseModel):
    scope_kind: Literal["today", "this_week", "this_trip", "phase", "custom", "until_changed"] = "until_changed"
    from_date: Optional[str] = None       # YYYY-MM-DD (custom)
    to_date: Optional[str] = None
    phase_id: Optional[str] = None
    trip_id: Optional[str] = None


class DirectiveBody(BaseModel):
    kind: Literal["avoid_movement", "require_movement", "limit_frequency",
                  "limit_volume", "limit_intensity", "note_only"] = "note_only"
    scope: DirectiveScope = Field(default_factory=DirectiveScope)
    parameters: dict = Field(default_factory=dict)     # kind-specific payload
    free_text: str = ""


@api.post("/v2/coach/clients/{client_id}/dashboard-directives")
async def dashboard_directive_create(
    client_id: str, body: DirectiveBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    if not await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Client not found")

    did = new_id()
    doc = {
        "id": did,
        "client_id": client_id,
        "coach_id": coach["id"],
        "kind": body.kind,
        "scope": body.scope.model_dump(),
        "parameters": body.parameters or {},
        "free_text": (body.free_text or "").strip(),
        "status": "active",
        "source": "coach_editor",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.coach_directives.insert_one(dict(doc))
    await write_decision(
        actor="coach", layer="ADAPT", scope_kind="coach_directive", scope_id=did,
        client_id=client_id, outcome="APPLIED",
        reason=f"Directive added ({body.kind} · scope={body.scope.scope_kind}): {body.free_text[:120]}",
    )
    await emit_metric("directive_created", client_id=client_id, coach_id=coach["id"],
                       numeric_value=1, labels={"kind": body.kind, "scope": body.scope.scope_kind})
    doc.pop("_id", None)
    return doc


@api.get("/v2/coach/clients/{client_id}/dashboard-directives")
async def dashboard_directive_list(
    client_id: str, status: Optional[str] = "active",
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    q: dict = {"client_id": client_id}
    if status:
        q["status"] = status
    rows = await db.coach_directives.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"directives": rows}


class DirectivePatchBody(BaseModel):
    status: Optional[Literal["active", "expired", "cancelled"]] = None
    free_text: Optional[str] = None
    parameters: Optional[dict] = None


@api.patch("/v2/coach/clients/{client_id}/dashboard-directives/{directive_id}")
async def dashboard_directive_patch(
    client_id: str, directive_id: str, body: DirectivePatchBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    updates = {"updated_at": now_iso()}
    if body.status is not None:      updates["status"] = body.status
    if body.free_text is not None:   updates["free_text"] = body.free_text
    if body.parameters is not None:  updates["parameters"] = body.parameters
    r = await db.coach_directives.update_one(
        {"id": directive_id, "client_id": client_id}, {"$set": updates}
    )
    if r.matched_count == 0:
        raise HTTPException(404, "Directive not found")
    if body.status:
        await write_decision(
            actor="coach", layer="ADAPT", scope_kind="coach_directive", scope_id=directive_id,
            client_id=client_id, outcome="APPLIED",
            reason=f"Directive status → {body.status}",
        )
    return await db.coach_directives.find_one({"id": directive_id}, {"_id": 0})


# ===========================================================================
# 2. Progressive generation status (§24-25)
# ===========================================================================
#
# One endpoint that returns a coach-friendly rollup of what CrewFit is
# doing right now for this client. Combines:
#   - roster jobs (parsing / confirming)
#   - V2 draft build jobs
#   - workout implementation build state
#
# UI polls this every ~2s while a build is in progress.
# ---------------------------------------------------------------------------

_STAGE_ORDER = [
    "roster_uploaded",
    "roster_parsed",
    "schedule_created",
    "planning_programme",
    "generating_workouts",
    "validating",
    "ready_for_review",
    "published",
]


@api.get("/v2/coach/clients/{client_id}/generation/status")
async def generation_status(
    client_id: str, month: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return a compact pipeline snapshot for the coach's Progressive UX banner."""
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")

    now = _dt.datetime.utcnow()
    stages: dict[str, dict] = {s: {"state": "pending"} for s in _STAGE_ORDER}

    # ---- roster job(s) in progress or recent
    rjob = await db.jobs.find_one(
        {"target_scope.client_id": client_id, "kind": {"$in": ["roster_parse", "roster_confirm"]}},
        {"_id": 0}, sort=[("scheduled_at", -1)]
    )
    if not rjob:
        # V1 fallback — look at V1 roster docs
        latest_roster = await db.rosters.find_one(
            {"user_id": client_id, "is_active": True}, {"_id": 0}, sort=[("created_at", -1)]
        )
        if latest_roster:
            stages["roster_uploaded"] = {
                "state": "done",
                "at": latest_roster.get("created_at") or latest_roster.get("uploaded_at"),
                "detail": f"Uploaded by {latest_roster.get('uploaded_by_role') or 'client'}",
            }
            stages["roster_parsed"] = {
                "state": "done",
                "at": latest_roster.get("parsed_at") or latest_roster.get("created_at"),
                "detail": f"{len(latest_roster.get('days') or [])} days parsed",
            }
    else:
        st = rjob.get("status")
        stages["roster_uploaded"] = {"state": "done", "at": rjob.get("scheduled_at")}
        if st in ("in_progress",):
            stages["roster_parsed"] = {"state": "in_progress",
                                        "detail": (rjob.get("progress") or {}).get("stage") or "parsing"}
        elif st in ("succeeded",):
            stages["roster_parsed"] = {"state": "done", "at": rjob.get("completed_at")}
        else:
            stages["roster_parsed"] = {"state": "error", "detail": rjob.get("error") or st}

    # ---- schedule_days for the month if provided
    if month:
        try:
            year, mo = int(month[:4]), int(month[5:7])
            _, last = monthrange(year, mo)
            sd_str = f"{year:04d}-{mo:02d}-01"
            ed_str = f"{year:04d}-{mo:02d}-{last:02d}"
            count = await db.schedule_days.count_documents(
                {"client_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str}}
            )
            if count > 0:
                stages["schedule_created"] = {"state": "done", "detail": f"{count} days"}
        except Exception:
            pass

    # ---- V2 draft build job(s)
    dbjob = await db.jobs.find_one(
        {"target_scope.client_id": client_id, "kind": "draft_build"},
        {"_id": 0}, sort=[("scheduled_at", -1)]
    )
    if dbjob:
        st = dbjob.get("status")
        if st == "in_progress":
            stages["planning_programme"] = {"state": "in_progress",
                                              "detail": (dbjob.get("progress") or {}).get("stage")}
        elif st == "succeeded":
            stages["planning_programme"] = {"state": "done", "at": dbjob.get("completed_at")}
            # Look at implementations vs assignments to infer generating stage
            asg_total = await db.workout_assignments.count_documents({"client_id": client_id})
            impl_total = await db.workout_implementations.count_documents({"client_id": client_id})
            if asg_total > 0:
                if impl_total >= asg_total:
                    stages["generating_workouts"] = {"state": "done",
                                                      "detail": f"{impl_total}/{asg_total} sessions built"}
                elif impl_total > 0:
                    stages["generating_workouts"] = {
                        "state": "in_progress",
                        "detail": f"{impl_total}/{asg_total} sessions built",
                    }
                else:
                    stages["generating_workouts"] = {"state": "pending"}
        elif st in ("failed", "dead_letter"):
            stages["planning_programme"] = {"state": "error", "detail": dbjob.get("error") or st}

    # Data-driven fallback — infer planning + generating stages from the DB
    # directly when the coach used the one-click kickoff endpoint (which
    # skips the async jobs infrastructure entirely).
    prog_row = await db.programmes_v2.find_one(
        {"client_id": client_id, "status": {"$in": ["active", "draft"]}}, {"_id": 0, "id": 1}
    )
    if prog_row and stages["planning_programme"].get("state") == "pending":
        obj_count = await db.training_objectives.count_documents(
            {"client_id": client_id, "programme_id": prog_row["id"]}
        )
        if obj_count > 0:
            stages["planning_programme"] = {
                "state": "done", "detail": f"{obj_count} objectives"
            }
    if stages["planning_programme"].get("state") == "done" \
            and stages["generating_workouts"].get("state") == "pending":
        asg_total = await db.workout_assignments.count_documents({"client_id": client_id})
        impl_total = await db.workout_implementations.count_documents({"client_id": client_id})
        if asg_total > 0:
            if impl_total >= asg_total:
                stages["generating_workouts"] = {"state": "done",
                                                  "detail": f"{impl_total}/{asg_total} sessions built"}
            elif impl_total > 0:
                stages["generating_workouts"] = {"state": "in_progress",
                                                  "detail": f"{impl_total}/{asg_total} sessions built"}

    # ---- open exceptions block "validating" until resolved
    open_exc = await db.exceptions.count_documents({"client_id": client_id, "status": "open"})
    if stages["generating_workouts"].get("state") == "done":
        stages["validating"] = ({"state": "done"} if open_exc == 0
                                 else {"state": "in_progress",
                                       "detail": f"{open_exc} exception(s) open"})

    # ---- ready-for-review draft
    draft = await db.plan_drafts.find_one(
        {"client_id": client_id, "status": {"$in": ["ready_for_review", "partially_approved"]}},
        {"_id": 0}
    )
    if draft:
        stages["ready_for_review"] = {"state": "done", "at": draft.get("updated_at"),
                                        "detail": (draft.get("metrics") or {}).get("assignments_count")}

    # ---- published (LIVE) version
    latest_v = await db.plan_versions.find_one(
        {"client_id": client_id}, {"_id": 0}, sort=[("version", -1)]
    )
    if latest_v:
        stages["published"] = {"state": "done", "at": latest_v.get("published_at"),
                                 "detail": f"v{latest_v.get('version')}"}

    # ---- summarise overall state
    overall = "idle"
    for s in _STAGE_ORDER:
        if stages[s]["state"] == "in_progress":
            overall = "in_progress"
            break
        if stages[s]["state"] == "error":
            overall = "error"
            break
    if overall == "idle":
        # any pending after done means work is still needed
        done_seen = False
        for s in _STAGE_ORDER:
            if stages[s]["state"] == "done":
                done_seen = True
            elif stages[s]["state"] == "pending" and done_seen:
                overall = "waiting_next_step"
                break

    return {
        "client_id": client_id,
        "month": month,
        "overall": overall,
        "stages": [{"stage": s, **stages[s]} for s in _STAGE_ORDER],
        "checked_at": now.isoformat() + "Z",
    }


# ===========================================================================
# 3. Programme summary panel (§20)
# ===========================================================================
#
# One aggregate call for the collapsible programme card in the workspace
# header. Combines: goal, phase strip, event countdown, adherence,
# per-discipline planning objective quota vs actual.
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/programme/summary")
async def programme_summary(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    if not await db.users.find_one({"id": client_id}, {"_id": 0, "id": 1}):
        raise HTTPException(404, "Client not found")

    prog = await db.programmes_v2.find_one(
        {"client_id": client_id, "status": {"$in": ["active", "draft"]}}, {"_id": 0}
    )
    if not prog:
        return {"present": False}

    # --- Goal (primary)
    goal = await db.goals_v2.find_one({"id": prog["primary_goal_id"]}, {"_id": 0})
    goal_def = await db.goal_definitions.find_one(
        {"goal_id_taxonomy": (goal or {}).get("goal_id_taxonomy")}, {"_id": 0}
    ) if goal else None
    goal_summary = {
        "id": (goal or {}).get("id"),
        "taxonomy": (goal or {}).get("goal_id_taxonomy"),
        "label": (goal_def or {}).get("label") or (goal or {}).get("goal_id_taxonomy") or "—",
        "priority": (goal or {}).get("priority"),
        "target_date": (goal or {}).get("target_date"),
        "timeline_class": (goal or {}).get("timeline_class"),
    }

    # --- Phase strip
    phases = await db.programme_phases_v2.find(
        {"programme_id": prog["id"], "client_id": client_id}, {"_id": 0}
    ).sort("ordinal", 1).to_list(50)
    today_iso = _dt.date.today().isoformat()
    phase_strip = []
    active_phase = None
    for p in phases:
        entry = {
            "id": p["id"],
            "ordinal": p.get("ordinal"),
            "phase_kind": p.get("phase_kind"),
            "label": (p.get("phase_kind") or "").replace("_", " ").title(),
            "planned_start_date": p.get("planned_start_date"),
            "planned_end_date": p.get("planned_end_date"),
            "status": p.get("status"),
            "current": False,
            "weeks": None,
        }
        try:
            s = _dt.date.fromisoformat(entry["planned_start_date"])
            e = _dt.date.fromisoformat(entry["planned_end_date"])
            weeks = round(((e - s).days + 1) / 7.0, 1)
            entry["weeks"] = weeks
            if s.isoformat() <= today_iso <= e.isoformat():
                entry["current"] = True
                active_phase = entry
        except Exception:
            pass
        phase_strip.append(entry)

    # --- Event countdown (V2 events_v2 then V1 events)
    event = await db.events_v2.find_one(
        {"client_id": client_id, "status": "active"}, {"_id": 0}, sort=[("date", 1)]
    )
    if not event:
        event = await db.events.find_one(
            {"user_id": client_id, "status": "active"}, {"_id": 0}, sort=[("date", 1)]
        )
    countdown = None
    if event and event.get("date"):
        try:
            d = _dt.date.fromisoformat(event["date"])
            days = (d - _dt.date.today()).days
            countdown = {
                "event_id": event.get("id"),
                "event_type": event.get("event_type") or event.get("category"),
                "location": event.get("location"),
                "date": event.get("date"),
                "days_to_event": days,
                "weeks_to_event": round(days / 7.0, 1),
            }
        except Exception:
            pass

    # --- Adherence (last 14 days), computed from performance_records vs assignments
    win_start = (_dt.date.today() - _dt.timedelta(days=14)).isoformat()
    win_end = _dt.date.today().isoformat()
    total_assign = await db.workout_assignments.count_documents(
        {"client_id": client_id, "date": {"$gte": win_start, "$lte": win_end}}
    )
    completed = await db.performance_records.count_documents(
        {"client_id": client_id, "date": {"$gte": win_start, "$lte": win_end},
         "session_completion_pct": {"$gte": 50}}
    )
    adherence_pct = round(100 * completed / total_assign, 1) if total_assign > 0 else None

    # --- Objective quotas (this active window: 7 forward days)
    fwd_end = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
    objectives = await db.training_objectives.find(
        {"programme_id": prog["id"], "client_id": client_id,
         "active_start_date": {"$lte": fwd_end},
         "active_end_date": {"$gte": today_iso}},
        {"_id": 0}
    ).to_list(100)
    obj_quota: dict[str, dict] = {}
    for o in objectives:
        disc = (o.get("discipline") or o.get("kind") or "other").lower()
        entry = obj_quota.setdefault(disc, {"target": 0, "scheduled": 0, "completed": 0})
        entry["target"] += int(o.get("target_exposures_per_window") or 0)
        # scheduled = assignments in the forward 7 days
        entry["scheduled"] += await db.workout_assignments.count_documents(
            {"client_id": client_id, "objective_id": o["id"],
             "date": {"$gte": today_iso, "$lte": fwd_end}}
        )
        # completed = performance_records in the last 7 days
        entry["completed"] += await db.performance_records.count_documents(
            {"client_id": client_id, "objective_id": o["id"],
             "date": {"$gte": (_dt.date.today() - _dt.timedelta(days=7)).isoformat(),
                      "$lte": today_iso}}
        )
    quota_rows = [{"discipline": k.replace("_", " ").title(), **v} for k, v in obj_quota.items()]

    return {
        "present": True,
        "programme": {
            "id": prog["id"],
            "status": prog.get("status"),
            "start_date": prog.get("start_date"),
            "end_date": prog.get("end_date"),
            "timeline_class": prog.get("timeline_class"),
            "live_plan_version": prog.get("live_plan_version") or 0,
        },
        "goal": goal_summary,
        "active_phase": active_phase,
        "phase_strip": phase_strip,
        "event_countdown": countdown,
        "adherence_pct": adherence_pct,
        "adherence_window_days": 14,
        "objective_quotas": quota_rows,
    }


logger.info("feature_v2_coach_directives: /api/v2/coach/clients/*/dashboard-directives + generation/status + programme/summary registered")
