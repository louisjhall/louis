"""
feature_v2_coach_kickoff — Goal-aware V2 pipeline scaffold.

Reads the client's real DNA (profile + events) to build a plan that
actually reflects what they told us:

  1. Resolve primary goal:
       events.event_type = "marathon"  →  running.marathon
       events.event_type = "half_marathon" → running.half_marathon
       profile.primary_goal_id / profile.main_goal_key → taxonomy
       fallback: general.longevity
  2. If an active event with a future event_date exists, timeline_class
     becomes "developmental" and the programme end is anchored to the
     event date (or today + prep_weeks if no event).
  3. Phase sequence chosen by taxonomy family:
       running.* / triathlon.*  → foundation → aerobic_base → build → specific_prep → taper → race_week
       strength.* / body_comp   → foundation → hypertrophy → strength → peak
       general.longevity        → foundation → maintenance
  4. Phase weeks scale proportionally to total prep weeks so we always
     fit the client's actual timeline (not a hardcoded 8 weeks).
  5. P3 builds training_objectives from taxonomy.key_stimuli.
  6. P5 schedules across the client's schedule_days.
  7. P6 builds workout_implementations with the client's equipment.

Endpoint:  POST /api/v2/coach/clients/{cid}/plan/kickoff
Body:      { goal_id_taxonomy?, weeks?, month?, force?, event_id? }
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import write_decision, emit_metric


# ---------------------------------------------------------------------------
# Goal + phase math
# ---------------------------------------------------------------------------

# Map free-text or V1 profile IDs → V2 taxonomy IDs.
GOAL_ALIASES: dict[str, str] = {
    "marathon": "running.marathon",
    "half_marathon": "running.half_marathon",
    "half marathon": "running.half_marathon",
    "10k": "running.10k",
    "5k": "running.5k",
    "70.3": "triathlon.70_3",
    "triathlon": "triathlon.70_3",
    "fat_loss": "body_composition.fat_loss",
    "weight_loss": "body_composition.fat_loss",
    "muscle_gain": "body_composition.muscle_gain",
    "hypertrophy": "body_composition.muscle_gain",
    "strength": "strength.general",
    "general_fitness": "general.longevity",
    "longevity": "general.longevity",
    "general": "general.longevity",
}


# Phase templates by taxonomy family — proportions expressed as fractions of
# the total prep window. They sum to 1.0; we round to whole weeks and top
# up the longest phase to make the timeline exact.
PHASE_BLUEPRINTS: dict[str, list[tuple[str, float, str]]] = {
    "running": [
        ("foundation",    0.10, "Movement quality, aerobic re-introduction, tissue prep."),
        ("aerobic_base",  0.35, "Build aerobic ceiling with easy runs + first long runs."),
        ("build",         0.30, "Tempo + intervals; introduce marathon-pace efforts."),
        ("specific_prep", 0.15, "Long runs with marathon-pace segments; race-day dress rehearsal."),
        ("taper",         0.08, "Volume down ~50%, keep intensity, sharpen."),
        ("race_week",     0.02, "Race-week freshness; only easy shake-outs."),
    ],
    "triathlon": [
        ("foundation",    0.10, "Discipline balance + tissue prep."),
        ("aerobic_base",  0.30, "Build volume across swim/bike/run."),
        ("build",         0.30, "Tempo bike + tempo run + brick blocks."),
        ("specific_prep", 0.20, "Race-simulation bricks at target pace."),
        ("taper",         0.08, "Volume drops, freshness rises."),
        ("race_week",     0.02, "Race-week easy shake-outs."),
    ],
    "strength": [
        ("foundation",   0.20, "Movement prep + baseline volume."),
        ("hypertrophy",  0.40, "Volume-heavy hypertrophy blocks."),
        ("strength",     0.30, "Intensity phase — 3–5 RM work."),
        ("peak",         0.10, "Deload → 1-RM test week."),
    ],
    "body_composition": [
        ("foundation",  0.20, "Baseline movement + habit build."),
        ("hypertrophy", 0.50, "Volume + progressive overload."),
        ("strength",    0.20, "Intensity blocks to preserve LBM."),
        ("recovery",    0.10, "Deload / off-cycle."),
    ],
    "general": [
        ("foundation",  0.30, "Movement + aerobic re-intro."),
        ("maintenance", 0.70, "Sustain across strength + cardio + mobility."),
    ],
}


class KickoffBody(BaseModel):
    goal_id_taxonomy: Optional[str] = None    # coach override
    weeks: Optional[int] = None                # coach override for prep length
    force: bool = False                        # rebuild programme even if one exists
    event_id: Optional[str] = None             # override event selection


async def _resolve_goal(client: dict, coach_override: Optional[str]) -> tuple[dict, str]:
    """Return (goal_definition, source_string_used_for_audit)."""
    if coach_override:
        gd = await db.goal_definitions.find_one({"goal_id_taxonomy": coach_override}, {"_id": 0})
        if not gd:
            raise HTTPException(400, f"Unknown goal taxonomy: {coach_override}")
        return gd, f"coach_override:{coach_override}"

    profile = client.get("profile") or {}
    candidates: list[tuple[str, str]] = []
    for key in ("primary_goal_id", "main_goal_key", "main_goal", "primary_goal", "goal", "event_type_pref"):
        v = profile.get(key)
        if isinstance(v, str) and v.strip():
            candidates.append((f"profile.{key}", v.strip().lower()))
    async for e in db.events.find(
        {"user_id": client["id"], "is_active": True}, {"_id": 0}
    ).sort("event_date", 1):
        if e.get("event_type"):
            candidates.append((f"events.{e['id'][:8]}", str(e["event_type"]).lower()))
            break

    for source, raw in candidates:
        taxonomy = GOAL_ALIASES.get(raw, raw)
        if not taxonomy or taxonomy == raw and "." not in taxonomy:
            # unknown alias; try as-is anyway
            taxonomy = raw
        gd = await db.goal_definitions.find_one({"goal_id_taxonomy": taxonomy}, {"_id": 0})
        if gd:
            return gd, source

    # No match anywhere — fall back to longevity, but flag it in audit.
    gd = await db.goal_definitions.find_one({"goal_id_taxonomy": "general.longevity"}, {"_id": 0})
    return gd, "fallback:general.longevity"


async def _resolve_event(client_id: str, event_id: Optional[str]) -> Optional[dict]:
    if event_id:
        return await db.events.find_one({"id": event_id, "user_id": client_id}, {"_id": 0})
    return await db.events.find_one(
        {"user_id": client_id, "is_active": True,
         "event_date": {"$gte": _dt.date.today().isoformat()}},
        {"_id": 0}, sort=[("event_date", 1)]
    )


def _blueprint_family(taxonomy: str) -> str:
    if taxonomy.startswith("running."):
        return "running"
    if taxonomy.startswith("triathlon."):
        return "triathlon"
    if taxonomy.startswith("strength."):
        return "strength"
    if taxonomy.startswith("body_composition."):
        return "body_composition"
    return "general"


def _split_phase_weeks(total_weeks: int, blueprint: list[tuple[str, float, str]]) -> list[tuple[str, int, str]]:
    """Distribute total_weeks across blueprint using the fractional shares."""
    raw = [(kind, max(1, round(total_weeks * frac)), rationale) for kind, frac, rationale in blueprint]
    diff = total_weeks - sum(n for _, n, _ in raw)
    if diff != 0:
        # Adjust the biggest phase to close the gap
        idx = max(range(len(raw)), key=lambda i: raw[i][1])
        kind, n, r = raw[idx]
        raw[idx] = (kind, max(1, n + diff), r)
    return raw


# ---------------------------------------------------------------------------
# Ensure primitives
# ---------------------------------------------------------------------------

async def _ensure_goal(client_id: str, gd: dict) -> dict:
    existing = await db.goals_v2.find_one(
        {"client_id": client_id, "goal_id_taxonomy": gd["goal_id_taxonomy"], "status": "active"},
        {"_id": 0}
    )
    if existing:
        return existing
    tl = "developmental" if gd.get("standard_prep_weeks") else "maintenance"
    doc = {
        "id": new_id(),
        "client_id": client_id,
        "goal_id_taxonomy": gd["goal_id_taxonomy"],
        "label": gd.get("label"),
        "priority": "primary",
        "weight": 1.0,
        "timeline_class": tl,
        "status": "active",
        "created_at": now_iso(), "updated_at": now_iso(),
        "created_by": "kickoff",
    }
    await db.goals_v2.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _ensure_programme(client_id: str, goal: dict, start: _dt.date, end: _dt.date,
                             event: Optional[dict], coach_id: str, force: bool) -> dict:
    if not force:
        existing = await db.programmes_v2.find_one(
            {"client_id": client_id, "status": {"$in": ["active", "draft"]}}, {"_id": 0}
        )
        if existing:
            # Update start/end + primary_goal_id if they drifted from what we resolved
            upd = {
                "primary_goal_id": goal["id"],
                "timeline_class": goal.get("timeline_class") or "maintenance",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "event_ids": [event["id"]] if event else [],
                "updated_at": now_iso(),
            }
            await db.programmes_v2.update_one({"id": existing["id"]}, {"$set": upd})
            existing.update(upd)
            return existing

    # Supersede any prior
    await db.programmes_v2.update_many(
        {"client_id": client_id, "status": "active"},
        {"$set": {"status": "superseded", "updated_at": now_iso()}},
    )
    pid = new_id()
    doc = {
        "id": pid,
        "client_id": client_id,
        "primary_goal_id": goal["id"],
        "secondary_goal_ids": [],
        "event_ids": [event["id"]] if event else [],
        "timeline_class": goal.get("timeline_class") or "maintenance",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "status": "draft",
        "phase_sequence": [],
        "live_plan_version": 0,
        "draft_plan_version": 1,
        "created_by": coach_id,
        "created_at": now_iso(), "updated_at": now_iso(),
        "version": 1,
    }
    await db.programmes_v2.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _seed_phases(programme: dict, phase_plan: list[tuple[str, int, str]]) -> list[str]:
    client_id = programme["client_id"]
    programme_id = programme["id"]
    await db.programme_phases_v2.delete_many({"programme_id": programme_id})

    cursor = _dt.date.fromisoformat(programme["start_date"])
    programme_end = _dt.date.fromisoformat(programme["end_date"])
    phase_ids: list[str] = []
    for ordinal, (kind, weeks, rationale) in enumerate(phase_plan, start=1):
        end = min(cursor + _dt.timedelta(days=weeks * 7 - 1), programme_end)
        if end < cursor:
            break
        pd_def = await db.phase_definitions.find_one({"phase_kind": kind}, {"_id": 0})
        if not pd_def:
            logger.warning("kickoff: unknown phase_kind=%s, skipping", kind)
            continue
        phid = new_id()
        await db.programme_phases_v2.insert_one({
            "id": phid,
            "programme_id": programme_id,
            "client_id": client_id,
            "phase_kind": kind,
            "ordinal": ordinal,
            "planned_start_date": cursor.isoformat(),
            "planned_end_date": end.isoformat(),
            "actual_start_date": None, "actual_end_date": None,
            "entry_criteria": pd_def.get("entry_criteria", []),
            "exit_criteria": pd_def.get("exit_criteria", []),
            "status": "active" if ordinal == 1 else "upcoming",
            "purpose_summary": rationale,
            "training_priorities": pd_def.get("training_priorities", []),
            "volume_bias": pd_def.get("volume_bias"),
            "intensity_bias": pd_def.get("intensity_bias"),
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        phase_ids.append(phid)
        cursor = end + _dt.timedelta(days=1)
        if cursor > programme_end:
            break

    if phase_ids:
        await db.programmes_v2.update_one(
            {"id": programme_id},
            {"$set": {"phase_sequence": phase_ids, "updated_at": now_iso()}}
        )
    return phase_ids


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@api.post("/v2/coach/clients/{client_id}/plan/kickoff")
async def plan_kickoff(
    client_id: str, body: KickoffBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """One-click plan build — goal- and event-aware.

    Returns a fully-populated audit trail so the coach can see EXACTLY
    why the plan looks the way it does.
    """
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")
    v2 = ((client.get("profile") or {}).get("v2_flags") or {})
    if not (v2.get("v2_default") or v2.get("state_foundation_enabled")):
        raise HTTPException(409, "Client is not V2-flagged")

    # 1. Goal + event resolution ---------------------------------------------
    gd, goal_source = await _resolve_goal(client, body.goal_id_taxonomy)
    if not gd:
        raise HTTPException(400, "No goal could be resolved — seed goal_definitions")

    event = await _resolve_event(client_id, body.event_id)
    today = _dt.date.today()

    # 2. Compute prep window --------------------------------------------------
    if body.weeks:
        weeks = max(2, min(52, body.weeks))
        end_date = today + _dt.timedelta(weeks=weeks) - _dt.timedelta(days=1)
    elif event and event.get("event_date"):
        try:
            ed = _dt.date.fromisoformat(event["event_date"])
        except Exception:
            ed = today + _dt.timedelta(weeks=gd.get("standard_prep_weeks") or 8)
        if ed <= today:
            ed = today + _dt.timedelta(weeks=gd.get("standard_prep_weeks") or 8)
        weeks = max(2, (ed - today).days // 7 + 1)
        end_date = ed
    else:
        weeks = gd.get("standard_prep_weeks") or 8
        end_date = today + _dt.timedelta(weeks=weeks) - _dt.timedelta(days=1)

    start_date = today
    family = _blueprint_family(gd["goal_id_taxonomy"])
    blueprint = PHASE_BLUEPRINTS[family]
    phase_plan = _split_phase_weeks(weeks, blueprint)

    # 3. Seed primitives ------------------------------------------------------
    goal = await _ensure_goal(client_id, gd)
    programme = await _ensure_programme(client_id, goal, start_date, end_date,
                                         event, coach["id"], body.force)
    phase_ids = await _seed_phases(programme, phase_plan)
    if not phase_ids:
        raise HTTPException(400, "Could not seed phases")

    # 4. P3 demand → objectives + exposures
    from feature_v2_p3_demand import objectives_build, BuildDemandBody
    p3_res = await objectives_build(
        client_id, BuildDemandBody(programme_id=programme["id"]), coach=coach
    )

    # 5. P5 scheduling
    from feature_v2_p5_scheduling import plan_build as p5_plan_build, BuildPlanBody
    p5_end = min(end_date, start_date + _dt.timedelta(weeks=min(weeks, 8)) - _dt.timedelta(days=1))
    p5_res = await p5_plan_build(
        client_id,
        BuildPlanBody(
            programme_id=programme["id"],
            from_date=start_date.isoformat(),
            to_date=p5_end.isoformat(),
        ),
        coach=coach,
    )

    # 6. P6 construction
    from feature_v2_p6_construction import implementations_build, BuildImplBody
    p6_res = await implementations_build(
        client_id,
        BuildImplBody(
            programme_id=programme["id"],
            from_date=start_date.isoformat(),
            to_date=p5_end.isoformat(),
        ),
        coach=coach,
    )

    # 7. Draft
    draft = await db.plan_drafts.find_one(
        {"programme_id": programme["id"], "client_id": client_id,
         "status": {"$in": ["building", "ready_for_review", "partially_approved"]}},
        {"_id": 0}
    )
    if not draft:
        draft_id = new_id()
        await db.plan_drafts.insert_one({
            "id": draft_id,
            "programme_id": programme["id"],
            "client_id": client_id,
            "status": "ready_for_review",
            "notes": (
                f"Scaffolded from {goal_source}. Goal={gd['goal_id_taxonomy']}, "
                f"event={event['event_type']+' '+event['event_date'] if event else 'none'}, "
                f"{len(phase_ids)} phases across {weeks}w."
            ),
            "created_by": coach["id"],
            "created_at": now_iso(), "updated_at": now_iso(),
            "metrics": {
                "assignments_count": int(p5_res.get("assignments_created", 0)),
                "implementations_count": int(p6_res.get("implementations_created", 0)),
            },
        })
        draft = await db.plan_drafts.find_one({"id": draft_id}, {"_id": 0})
    if draft and draft.get("id"):
        await db.workout_assignments.update_many(
            {"client_id": client_id, "programme_id": programme["id"], "draft_id": None},
            {"$set": {"draft_id": draft["id"]}}
        )

    # 8. Decision record — the "WHY" the coach will read
    rationale = _rationale_summary(
        gd=gd, goal_source=goal_source, event=event,
        weeks=weeks, phase_plan=phase_plan, client=client,
        p3=p3_res, p5=p5_res, p6=p6_res,
    )
    await write_decision(
        actor="coach", layer="ORCHESTRATION", scope_kind="programme",
        scope_id=programme["id"], client_id=client_id, outcome="APPLIED",
        reason=rationale,
    )
    try:
        await emit_metric(
            "plan_kickoff_completed", client_id=client_id, coach_id=coach["id"],
            labels={
                "taxonomy": gd["goal_id_taxonomy"],
                "prep_weeks": weeks,
                "assignments": int(p5_res.get("assignments_created", 0)),
                "impls": int(p6_res.get("implementations_created", 0)),
            },
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "programme_id": programme["id"],
        "draft_id": (draft or {}).get("id"),
        "goal": {
            "taxonomy": gd["goal_id_taxonomy"],
            "label": gd.get("label"),
            "source": goal_source,
            "key_stimuli": gd.get("key_stimuli") or [],
        },
        "event": ({
            "id": event["id"],
            "event_type": event["event_type"],
            "event_date": event["event_date"],
            "weeks_out": (
                (_dt.date.fromisoformat(event["event_date"]) - today).days // 7
                if event.get("event_date") else None
            ),
        } if event else None),
        "prep_window": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "weeks": weeks,
        },
        "phase_plan": [
            {"phase_kind": k, "weeks": w, "rationale": r}
            for (k, w, r) in phase_plan
        ],
        "phases_created": len(phase_ids),
        "objectives_created": p3_res.get("objectives_created"),
        "assignments_created": p5_res.get("assignments_created"),
        "implementations_created": p6_res.get("implementations_created"),
        "rationale": rationale,
    }


def _rationale_summary(*, gd, goal_source, event, weeks, phase_plan,
                       client, p3, p5, p6) -> str:
    prof = client.get("profile") or {}
    dpw = prof.get("training_days_per_week") or prof.get("training_days")
    equip = prof.get("equipment") or prof.get("home_equipment") or []
    phases_str = " → ".join(f"{k} ({w}w)" for k, w, _ in phase_plan)
    event_str = (
        f"target event: {event['event_type']} on {event['event_date']}"
        if event else "no target event"
    )
    return (
        f"Goal={gd['goal_id_taxonomy']} (source={goal_source}); "
        f"{event_str}; window={weeks}w; phases: {phases_str}; "
        f"client cap: {dpw or '?'} sessions/wk, equipment={equip}; "
        f"P3→{p3.get('objectives_created', 0)} objectives, "
        f"P5→{p5.get('assignments_created', 0)} sessions, "
        f"P6→{p6.get('implementations_created', 0)} implementations."
    )


logger.info("feature_v2_coach_kickoff: /api/v2/coach/clients/{cid}/plan/kickoff (goal-aware) registered")
