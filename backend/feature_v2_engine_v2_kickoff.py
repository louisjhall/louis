"""
CrewFit V2 Engine V2 — Kickoff Orchestrator
=============================================

Wires the new WHAT → WHEN → HOW → VALIDATE pipeline behind a per-client
`profile.v2_flags.engine_v2` feature flag.

Rollout contract:
    * Existing Live plans are NEVER touched.
    * Turning the flag on causes the orchestrator to produce Draft/Shadow
      output only.
    * Turning the flag off restores the previous engine unconditionally.

Public HTTP endpoint:
    POST /api/v2/coach/clients/{cid}/engine-v2/kickoff
         → generates a Draft using engine v2 into plan_drafts_v2.
    GET  /api/v2/coach/clients/{cid}/engine-v2/draft
         → returns the current shadow draft with full context.
    PATCH /api/v2/coach/me/engine-v2/enable-for/{cid}
    PATCH /api/v2/coach/me/engine-v2/disable-for/{cid}

Nothing here writes to workout_assignments or workout_implementations. The
shadow output lives in dedicated collections:
    * plan_drafts_v2               (top-level draft record)
    * assignments_v2_draft         (placements)
    * implementations_v2_draft     (session specs)
    * exceptions_v2_draft          (unfilled + validator errors)
    * decision_records             (audit trail, WHAT/WHEN/HOW/VALIDATE)
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger

from feature_v2_sport_configs import (
    canonicalise_goal_key, get_goal_config, resolve_phase_plan,
)
from feature_v2_roster_context import build_day_contexts, context_to_derived
from feature_v2_demand_v2 import (
    build_demand, schedule_demand, RequiredExposure, Unfilled,
)
from feature_v2_sequencing import Placement, week_key
from feature_v2_construction_v2 import build_session_spec, SessionSpec
from feature_v2_validators_v2 import (
    validate_session, validate_programme, Issue,
)
from feature_v2_common import (
    sync_dna_to_v2_collections, write_decision, emit_metric,
)


# ---------------------------------------------------------------------------
# Feature-flag helpers
# ---------------------------------------------------------------------------

async def _is_engine_v2_enabled(client_id: str) -> bool:
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "profile": 1})
    if not user:
        return False
    flags = ((user.get("profile") or {}).get("v2_flags") or {})
    return bool(flags.get("engine_v2"))


async def _set_engine_v2_flag(client_id: str, enabled: bool) -> None:
    await db.users.update_one(
        {"id": client_id},
        {"$set": {"profile.v2_flags.engine_v2": bool(enabled),
                  "updated_at": now_iso()}},
    )


# ---------------------------------------------------------------------------
# Client context extraction
# ---------------------------------------------------------------------------

async def _load_effective_context(client_id: str) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, f"Client {client_id} not found")
    profile = user.get("profile") or {}
    event = await db.events.find_one(
        {"user_id": client_id, "is_active": True,
         "event_date": {"$gte": _dt.date.today().isoformat()}},
        {"_id": 0}, sort=[("event_date", 1)],
    )
    # Recent training history — count last 8 weeks
    since = (_dt.date.today() - _dt.timedelta(weeks=8)).isoformat()
    recent = await db.workout_sessions.count_documents({
        "client_id": client_id, "date": {"$gte": since}, "completion_status": "completed",
    }) if hasattr(db, "workout_sessions") else 0

    # Restrictions + equipment (already synced by sync_dna helper)
    restrictions_rows = await db.restrictions.find(
        {"client_id": client_id, "status": "active"}, {"_id": 0}
    ).to_list(50)
    restrictions_set: set[str] = set()
    for r in restrictions_rows:
        if r.get("region"):
            restrictions_set.add(str(r["region"]).lower())
        for p in (r.get("avoid_patterns") or []):
            restrictions_set.add(str(p).lower())

    equip_ctx = await db.equipment_contexts.find_one(
        {"client_id": client_id, "scope": "permanent"}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    equipment_set: set[str] = set(equip_ctx.get("equipment") or []) if equip_ctx else set()
    equipment_set.add("bodyweight")

    return {
        "user": user,
        "profile": profile,
        "event": event,
        "recent_sessions_8w": recent,
        "restrictions": restrictions_set,
        "equipment": equipment_set,
    }


# ---------------------------------------------------------------------------
# Endpoint bodies
# ---------------------------------------------------------------------------

class EngineV2KickoffBody(BaseModel):
    planning_window_weeks: int = Field(default=4, ge=1, le=12)
    include_shadow_report: bool = True


# ---------------------------------------------------------------------------
# Kickoff endpoint
# ---------------------------------------------------------------------------

@api.post("/v2/coach/clients/{client_id}/engine-v2/kickoff")
async def engine_v2_kickoff(
    client_id: str,
    body: EngineV2KickoffBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Runs the WHAT→WHEN→HOW→VALIDATE pipeline for the next N weeks.

    Writes results to plan_drafts_v2 + associated shadow collections. Never
    touches Live workout_assignments / workout_implementations.
    """
    if not await _is_engine_v2_enabled(client_id):
        raise HTTPException(409, "Engine V2 not enabled for this client. "
                                  "Enable via /engine-v2/enable-for.")

    t0 = time.time()

    # ---- 1. Effective context ------------------------------------------
    ctx = await _load_effective_context(client_id)
    # DNA sync (idempotent)
    await sync_dna_to_v2_collections(client_id)
    # Refresh restrictions + equipment after sync
    ctx = await _load_effective_context(client_id)
    profile = ctx["profile"]
    event = ctx["event"]

    # ---- 2. Resolve goal + phase plan ---------------------------------
    # Read from every known DNA field name in priority order. If NONE
    # produce a recognised goal, fail-loud instead of silently falling to
    # general.fitness — per the directive: "Do not silently substitute
    # permissive defaults."
    from feature_v2_sport_configs import _GOAL_ALIASES, SPORT_CONFIGS
    goal_candidates = [
        profile.get("primary_goal_type"),
        profile.get("primary_goal"),
        profile.get("primary_goal_id"),
        profile.get("goal"),
        profile.get("main_goal"),
        profile.get("main_goal_key"),
        profile.get("event_type_pref"),
    ]
    raw_goal = None
    for c in goal_candidates:
        if not c:
            continue
        canon = canonicalise_goal_key(c)
        # canonicalise falls back to general.fitness on unknown; only accept
        # a canonical match if the input itself resolves via aliases or exact
        k = str(c).strip().lower().replace(" ", "_")
        if k in SPORT_CONFIGS or k in _GOAL_ALIASES:
            raw_goal = c
            break
    if raw_goal is None:
        # Critical DNA missing — refuse to guess.
        # Iter 130e — surface the exact raw candidate values so future
        # frontend/backend goal-key mismatches (e.g. onboarding writes
        # "lose_fat" but backend only knows "fat_loss") are debuggable
        # in <30 seconds without spelunking through code.
        return {
            "ok": False,
            "code": "critical_dna_missing",
            "message": "No recognisable goal on profile. Coach must set primary_goal_type / main_goal / event_type_pref before Engine V2 can plan.",
            "checked_fields": ["primary_goal_type", "primary_goal", "primary_goal_id", "goal", "main_goal", "main_goal_key", "event_type_pref"],
            "raw_candidates": [str(c) if c is not None else None for c in goal_candidates],
        }
    goal_key = canonicalise_goal_key(raw_goal)
    goal = get_goal_config(goal_key)

    today = _dt.date.today()
    end_date = None
    if event and event.get("event_date"):
        try:
            end_date = _dt.date.fromisoformat(event["event_date"])
        except Exception:
            end_date = None
    if not end_date or end_date <= today:
        end_date = today + _dt.timedelta(weeks=goal.default_prep_weeks)
    prep_weeks = max(goal.min_prep_weeks, ((end_date - today).days + 6) // 7)
    phase_plan = resolve_phase_plan(goal_key, prep_weeks)

    # Which phase is "current"?
    cum = today
    current_phase = phase_plan[0]
    for ph in phase_plan:
        block_end = cum + _dt.timedelta(weeks=ph.weeks_target) - _dt.timedelta(days=1)
        if today <= block_end:
            current_phase = ph
            break
        cum += _dt.timedelta(weeks=ph.weeks_target)

    # ---- 3. Planning window -------------------------------------------
    # If the coach passed the DEFAULT weeks (4), auto-extend the window to
    # cover the entire uploaded roster range (capped at 12 weeks to keep
    # generation bounded). If the coach explicitly passed a different value,
    # honour it verbatim.
    window_start = today - _dt.timedelta(days=today.weekday())   # this Monday
    if int(body.planning_window_weeks) == 4:
        max_sd = await db.schedule_days.find(
            {"client_id": client_id, "date": {"$gte": window_start.isoformat()}},
            {"_id": 0, "date": 1},
        ).sort("date", -1).limit(1).to_list(1)
        if max_sd:
            roster_end = _dt.date.fromisoformat(max_sd[0]["date"])
            # Match the last COMPLETE week inside the remaining roster —
            # never plan on weeks with zero roster coverage. Allow as few as
            # 1 week if that is all the roster provides.
            span_days = (roster_end - window_start).days + 1
            derived_weeks = max(1, span_days // 7)
            window_weeks = min(12, derived_weeks)
        else:
            window_weeks = 4
    else:
        window_weeks = int(body.planning_window_weeks)
    week_starts: list[_dt.date] = [
        window_start + _dt.timedelta(days=7 * i) for i in range(window_weeks)
    ]
    window_end = week_starts[-1] + _dt.timedelta(days=6)

    # ---- 4. Load schedule_days for the window -------------------------
    sd_rows = await db.schedule_days.find({
        "client_id": client_id,
        "date": {"$gte": window_start.isoformat(), "$lte": window_end.isoformat()},
    }, {"_id": 0}).to_list(200)

    # If there are no schedule_days, we can't proceed — surface as validation error
    if not sd_rows:
        return {
            "ok": False,
            "code": "no_schedule_days",
            "message": (
                "Cannot generate — client has no schedule_days in this window. "
                "Ensure roster has been uploaded and processed."
            ),
            "goal_key": goal_key,
            "phase": current_phase.phase_kind,
        }

    day_contexts = build_day_contexts(sd_rows)
    # Honour client's explicit per-context session maxes from DNA.
    prof_max_home = profile.get("max_home_minutes") or profile.get("time_home_min")
    prof_max_layover = profile.get("time_layover_min")
    if prof_max_home or prof_max_layover:
        from feature_v2_roster_context import DayContext as _DC
        clipped: list = []
        for ctx_day in day_contexts:
            cap = ctx_day.available_time_min
            dt = ctx_day.day_type
            if prof_max_home and dt in ("home_day", "home", "off", "rest", "day_off",
                                          "leave", "vacation", "annual_leave"):
                cap = min(cap, int(prof_max_home))
            elif prof_max_layover and dt in ("layover_arrival", "layover_departure",
                                              "layover_full", "layover", "hotel",
                                              "turnaround"):
                cap = min(cap, int(prof_max_layover))
            clipped.append(_DC(
                date=ctx_day.date, day_type=ctx_day.day_type,
                duty_burden_score=ctx_day.duty_burden_score,
                training_opportunity=ctx_day.training_opportunity,
                available_time_min=cap,
                recommended_intensity_ceiling=ctx_day.recommended_intensity_ceiling,
                recovery_state=ctx_day.recovery_state,
                recent_hard_days_48h=ctx_day.recent_hard_days_48h,
                upcoming_hard_days_48h=ctx_day.upcoming_hard_days_48h,
                consecutive_duty_days=ctx_day.consecutive_duty_days,
                sleep_opportunity=ctx_day.sleep_opportunity,
                tz_shift_last_48h=ctx_day.tz_shift_last_48h,
                layover_length_hours=ctx_day.layover_length_hours,
                duty_duration_min_today=ctx_day.duty_duration_min_today,
                reasons=ctx_day.reasons + (f"clipped_by_profile:{cap}",),
            ))
        day_contexts = clipped
    # Persist derived context back into schedule_days
    for ctx_day in day_contexts:
        derived = context_to_derived(ctx_day)
        await db.schedule_days.update_one(
            {"client_id": client_id, "date": ctx_day.date.isoformat()},
            {"$set": {"derived": derived, "derived_updated_at": now_iso()}},
        )

    # ---- 5. WHAT — build demand ---------------------------------------
    demand = build_demand(
        client_id=client_id,
        client_profile=profile,
        goal_key=goal_key,
        phase_spec=current_phase,
        week_start_dates=week_starts,
    )

    # ---- 6. WHEN — schedule -------------------------------------------
    pref_wd_raw = profile.get("preferred_training_days") or []
    _wd = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
           "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
           "friday": 4, "saturday": 5, "sunday": 6}
    preferred_weekdays: set[int] = set()
    if isinstance(pref_wd_raw, list):
        for w in pref_wd_raw:
            key = str(w).strip().lower()
            if key in _wd:
                preferred_weekdays.add(_wd[key])

    # Build the per-date daily time-cap map — profile clip AND roster
    # available_time_min act as ceiling for TOTAL daily training minutes.
    from feature_v2_sport_configs import profile_daily_cap_for_day_type
    _dt_by_date = {d["date"]: (d.get("day_type") or "") for d in sd_rows}
    daily_time_cap_by_date: dict[_dt.date, int] = {}
    for ctx_day in day_contexts:
        dt = _dt_by_date.get(ctx_day.date.isoformat(), ctx_day.day_type)
        prof_cap = profile_daily_cap_for_day_type(
            profile, dt, default_cap=ctx_day.available_time_min,
        )
        daily_time_cap_by_date[ctx_day.date] = min(prof_cap, ctx_day.available_time_min)

    schedule = schedule_demand(
        demand=demand,
        day_contexts=day_contexts,
        goal=goal,
        phase=current_phase,
        preferred_weekdays=preferred_weekdays,
        daily_time_cap_by_date=daily_time_cap_by_date,
    )

    # ---- 7. HOW — build session specs per placement -------------------
    day_type_by_date = {d["date"]: (d.get("day_type") or "") for d in sd_rows}
    avail_by_date = {
        ctx_day.date.isoformat(): ctx_day.available_time_min for ctx_day in day_contexts
    }
    intensity_ceiling_by_date = {
        ctx_day.date.isoformat(): ctx_day.recommended_intensity_ceiling for ctx_day in day_contexts
    }

    session_specs: dict[str, dict] = {}   # keyed by exposure_id
    session_validations: dict[str, list[dict]] = {}
    for pl in schedule.placements:
        avail = avail_by_date.get(pl.date.isoformat(), 60)
        # Availability CAP — never a prescription
        effective_duration = min(int(pl.target_duration_min), int(avail)) if pl.kind != "rest" else 0
        # But guardrail — never drop below quota's absolute min
        quota_min = 0
        for e in demand.required_exposures:
            if e.exposure_id == pl.exposure_id:
                quota_min = e.duration_min_min
                break
        if pl.kind != "rest" and effective_duration < quota_min:
            # Session cannot fit into availability — flag it, don't shrink below min
            effective_duration = quota_min

        spec = build_session_spec(
            kind=pl.kind,
            duration_min=effective_duration,
            intensity_target=pl.intensity_target,
            phase_kind=current_phase.phase_kind,
            day_type=day_type_by_date.get(pl.date.isoformat(), "home_day"),
            equipment_ctx=ctx["equipment"],
            avoid_patterns=ctx["restrictions"],
            intensity_ceiling=intensity_ceiling_by_date.get(pl.date.isoformat(), "any"),
        )
        sv = validate_session(spec.to_dict(), pl, avail, ctx["restrictions"])
        session_specs[pl.exposure_id] = spec.to_dict()
        session_validations[pl.exposure_id] = [i.__dict__ for i in sv.issues]

    # ---- 8. VALIDATE programme ----------------------------------------
    prog_val = validate_programme(
        demand=demand,
        placements=schedule.placements,
        phase=current_phase,
        goal=goal,
        unfilled=schedule.unfilled,
    )

    # ---- 9. Persist Draft V2 -------------------------------------------
    draft_id = new_id()
    # Draft status semantics:
    #   ready_for_review   → no errors, may still have warnings
    #   needs_review       → one or more validator errors (unfilled IMPORTANT,
    #                         cap breaches, exposure numbering, etc.)
    if prog_val.ok:
        draft_status = "ready_for_review"
    else:
        draft_status = "needs_review"

    # Supersede any prior ACTIVE drafts (needs_review / ready_for_review) so
    # only the newest kickoff is treated as "the active draft" by the coach
    # dashboard. Published + superseded drafts stay untouched (audit history).
    await db.plan_drafts_v2.update_many(
        {"client_id": client_id,
         "status": {"$in": ["needs_review", "ready_for_review"]}},
        {"$set": {"status": "superseded_by_newer",
                   "superseded_at": now_iso(),
                   "superseded_reason": "New Engine V2 kickoff produced a fresher draft"}},
    )
    await db.plan_drafts_v2.insert_one({
        "id": draft_id,
        "client_id": client_id,
        "coach_id": coach["id"],
        "created_at": now_iso(),
        "planning_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "weeks": window_weeks,
        },
        "effective_context": {
            "goal_key": goal_key,
            "goal_display": goal.display_name,
            "event": (event or None) and {
                "id": event["id"], "date": event.get("event_date"),
                "type": event.get("event_type"),
            } or None,
            "current_phase": current_phase.phase_kind,
            "phase_plan": [{"phase_kind": p.phase_kind, "weeks": p.weeks_target} for p in phase_plan],
            "prep_weeks": prep_weeks,
            "training_days_per_week": profile.get("training_days_per_week"),
            "preferred_training_days": profile.get("preferred_training_days"),
            "sessions_per_week_min": profile.get("sessions_per_week_min"),
            "sessions_per_week_max": profile.get("sessions_per_week_max"),
            "preferred_session_length": profile.get("preferred_session_length"),
            "restrictions": sorted(ctx["restrictions"]),
            "equipment": sorted(ctx["equipment"]),
            "recent_sessions_8w": ctx["recent_sessions_8w"],
        },
        "demand": {
            "required_exposures": [
                {
                    "exposure_id": e.exposure_id,
                    "objective_id": e.objective_id,
                    "kind": e.kind, "priority": e.priority,
                    "target_duration_min": e.target_duration_min,
                    "duration_min_min": e.duration_min_min,
                    "duration_max_min": e.duration_max_min,
                    "intensity_target": e.intensity_target,
                    "week_index": e.week_index,
                    "ordinal_within_week": e.ordinal_within_week,
                    "can_skip_if_missed": e.can_skip_if_missed,
                    "quota_source": e.quota_source,
                    "target_week_start": e.target_week_start.isoformat() if e.target_week_start else None,
                    "target_week_end": e.target_week_end.isoformat() if e.target_week_end else None,
                    "allowed_window_start": e.allowed_window_start.isoformat() if e.allowed_window_start else None,
                    "allowed_window_end": e.allowed_window_end.isoformat() if e.allowed_window_end else None,
                    "preferred_cadence_days": e.preferred_cadence_days,
                    "cadence_range_days": list(e.cadence_range_days) if e.cadence_range_days else None,
                }
                for e in demand.required_exposures
            ],
            "frequency_caps": demand.frequency_caps,
            "frequency_derivation": demand.frequency_derivation,
            "dna_gaps": demand.dna_gaps,
            "notes": demand.notes,
        },
        "daily_time_caps_min": {
            d.isoformat(): v for d, v in daily_time_cap_by_date.items()
        },
        "placements": [
            {
                "exposure_id": p.exposure_id,
                "objective_id": p.objective_id,
                "kind": p.kind,
                "date": p.date.isoformat(),
                "priority": p.priority,
                "exposure_number": p.exposure_number,
                "intensity_class": p.intensity_class,
                "target_duration_min": p.target_duration_min,
                "intensity_target": p.intensity_target,
                "key": p.key,
            }
            for p in schedule.placements
        ],
        "session_specs": session_specs,
        "session_validations": session_validations,
        "unfilled": [
            {
                "exposure_id": u.exposure_id, "objective_id": u.objective_id,
                "kind": u.kind, "priority": u.priority,
                "reason_code": u.reason_code, "human_reason": u.human_reason,
                "candidate_hint_dates": u.candidate_hint_dates,
            }
            for u in schedule.unfilled
        ],
        "programme_validation": {
            "ok": prog_val.ok,
            "issues": [{"code": i.code, "severity": i.severity, "message": i.message} for i in prog_val.issues],
            "quota_report": prog_val.quota_report,
        },
        "status": draft_status,
        "engine_version": "v2",
    })

    await write_decision(
        actor="system", layer="WHAT", scope_kind="plan_draft_v2",
        scope_id=draft_id, client_id=client_id,
        outcome="COMPUTED",
        reason=f"Engine V2 kickoff — goal={goal_key} phase={current_phase.phase_kind} "
               f"{len(demand.required_exposures)} required exposures, "
               f"{len(schedule.placements)} placed, {len(schedule.unfilled)} unfilled",
    )
    await emit_metric("engine_v2_kickoff", client_id=client_id,
                       coach_id=coach["id"],
                       numeric_value=(time.time() - t0),
                       labels={"goal": goal_key, "phase": current_phase.phase_kind})

    return {
        "ok": prog_val.ok,
        "draft_id": draft_id,
        "status": draft_status,
        "goal_key": goal_key,
        "goal_display": goal.display_name,
        "phase": current_phase.phase_kind,
        "phase_plan": [{"phase_kind": p.phase_kind, "weeks": p.weeks_target} for p in phase_plan],
        "planning_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "weeks": window_weeks,
        },
        "counts": {
            "required_exposures": len(demand.required_exposures),
            "placements": len(schedule.placements),
            "unfilled": len(schedule.unfilled),
            "validation_errors": sum(1 for i in prog_val.issues if i.severity == "error"),
            "validation_warnings": sum(1 for i in prog_val.issues if i.severity == "warning"),
        },
        "frequency_derivation": demand.frequency_derivation,
        "dna_gaps": demand.dna_gaps,
        "quota_report": prog_val.quota_report,
        "validation_summary": [
            {"code": i.code, "severity": i.severity, "message": i.message}
            for i in prog_val.issues
        ],
        "took_seconds": round(time.time() - t0, 3),
    }


# ---------------------------------------------------------------------------
# Draft accessor
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/engine-v2/draft")
async def engine_v2_get_draft(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return the most recent Draft V2 with full context, placements, specs."""
    d = await db.plan_drafts_v2.find_one(
        {"client_id": client_id}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not d:
        raise HTTPException(404, "No Engine V2 draft found. Run kickoff first.")
    return d


@api.get("/v2/coach/clients/{client_id}/engine-v2/status")
async def engine_v2_status(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    enabled = await _is_engine_v2_enabled(client_id)
    latest = await db.plan_drafts_v2.find_one(
        {"client_id": client_id}, {"_id": 0, "id": 1, "status": 1,
                                    "planning_window": 1, "created_at": 1,
                                    "programme_validation": 1},
        sort=[("created_at", -1)],
    )
    return {
        "enabled": enabled,
        "latest_draft": latest,
    }


# ---------------------------------------------------------------------------
# Enable / Disable per client
# ---------------------------------------------------------------------------

@api.patch("/v2/coach/clients/{client_id}/engine-v2/enable")
async def engine_v2_enable(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _set_engine_v2_flag(client_id, True)
    await write_decision(
        actor="coach", layer="ORCHESTRATION", scope_kind="engine_v2_flag",
        scope_id=client_id, client_id=client_id,
        outcome="ENABLED",
        reason=f"Coach {coach.get('email')} enabled Engine V2 for client",
    )
    return {"ok": True, "enabled": True}


@api.patch("/v2/coach/clients/{client_id}/engine-v2/disable")
async def engine_v2_disable(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    await _set_engine_v2_flag(client_id, False)
    await write_decision(
        actor="coach", layer="ORCHESTRATION", scope_kind="engine_v2_flag",
        scope_id=client_id, client_id=client_id,
        outcome="DISABLED",
        reason=f"Coach {coach.get('email')} disabled Engine V2 for client",
    )
    return {"ok": True, "enabled": False}


logger.info("feature_v2_engine_v2_kickoff: /api/v2/coach/clients/{cid}/engine-v2/* registered")
