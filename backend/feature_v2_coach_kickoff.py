"""
feature_v2_coach_kickoff — One-click V2 pipeline scaffold.

When a coach uploads a roster for a client that has no V2 programme yet,
the workspace pipeline gets stuck at "Planning programme" because P5
requires a Programme → Phases → Objectives chain.

This module ships a single endpoint:

    POST /api/v2/coach/clients/{cid}/plan/kickoff
        Body: { goal_id_taxonomy?, weeks?, month?, force?: bool }

that scaffolds the missing pieces and runs P5 + P6 in one shot:

    1. Seed a `goals_v2` row (default: general.longevity) if none exists
    2. Create a `programmes_v2` doc starting today for `weeks` weeks (default 8)
    3. Build a phase sequence: foundation → maintenance
    4. Build training_objectives + objective_exposures via P3
    5. Run P5 plan_build to materialise workout_assignments
    6. Run P6 build-implementations to materialise workout_implementations

Idempotent-ish: if a programme already exists and force!=True, it just
runs P5+P6 for the current programme.

Requires: coach role + client v2_default flag.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import write_decision, emit_metric


DEFAULT_GOAL = "general.longevity"
DEFAULT_PHASES = [
    {"phase_kind": "foundation",   "weeks": 4},
    {"phase_kind": "maintenance",  "weeks": 4},
]


class KickoffBody(BaseModel):
    goal_id_taxonomy: Optional[str] = None
    weeks: Optional[int] = 8
    month: Optional[str] = None          # YYYY-MM — anchor P5 range
    force: bool = False                   # rebuild programme even if one exists


async def _ensure_goal(client_id: str, taxonomy: str) -> dict:
    """Return an existing goals_v2 row or create one from goal_definitions."""
    existing = await db.goals_v2.find_one(
        {"client_id": client_id, "goal_id_taxonomy": taxonomy, "status": "active"},
        {"_id": 0}
    )
    if existing:
        return existing
    gd = await db.goal_definitions.find_one({"goal_id_taxonomy": taxonomy}, {"_id": 0})
    if not gd:
        raise HTTPException(400, f"Unknown goal_id_taxonomy: {taxonomy}")
    doc = {
        "id": new_id(),
        "client_id": client_id,
        "goal_id_taxonomy": taxonomy,
        "label": gd.get("label"),
        "priority": "primary",
        "weight": 1.0,
        "timeline_class": "maintenance" if not gd.get("standard_prep_weeks") else "developmental",
        "status": "active",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": "kickoff",
    }
    await db.goals_v2.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _ensure_programme(client_id: str, goal: dict, weeks: int, coach_id: str,
                             force: bool) -> dict:
    if not force:
        existing = await db.programmes_v2.find_one(
            {"client_id": client_id, "status": {"$in": ["active", "draft"]}}, {"_id": 0}
        )
        if existing:
            return existing
    # Supersede any old programme
    await db.programmes_v2.update_many(
        {"client_id": client_id, "status": "active"},
        {"$set": {"status": "superseded", "updated_at": now_iso()}},
    )
    start = _dt.date.today()
    end = start + _dt.timedelta(weeks=weeks) - _dt.timedelta(days=1)
    pid = new_id()
    doc = {
        "id": pid,
        "client_id": client_id,
        "primary_goal_id": goal["id"],
        "secondary_goal_ids": [],
        "event_ids": [],
        "timeline_class": goal.get("timeline_class") or "maintenance",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "status": "draft",
        "phase_sequence": [],
        "live_plan_version": 0,
        "draft_plan_version": 1,
        "created_by": coach_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    await db.programmes_v2.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


async def _seed_phases(programme: dict, coach_id: str) -> list[str]:
    """Create phase docs directly. Simpler than calling the P2 endpoint
    because it avoids re-entering FastAPI auth."""
    client_id = programme["client_id"]
    programme_id = programme["id"]
    await db.programme_phases_v2.delete_many({"programme_id": programme_id})

    cursor = _dt.date.fromisoformat(programme["start_date"])
    programme_end = _dt.date.fromisoformat(programme["end_date"])
    phase_ids: list[str] = []
    remaining = (programme_end - cursor).days + 1
    for ordinal, entry in enumerate(DEFAULT_PHASES, start=1):
        weeks = int(entry.get("weeks") or 4)
        span_days = min(remaining, weeks * 7)
        if span_days <= 0:
            break
        end = cursor + _dt.timedelta(days=span_days - 1)
        pd_def = await db.phase_definitions.find_one({"phase_kind": entry["phase_kind"]}, {"_id": 0})
        if not pd_def:
            logger.warning("kickoff: unknown phase_kind=%s, skipping", entry.get("phase_kind"))
            continue
        phid = new_id()
        await db.programme_phases_v2.insert_one({
            "id": phid,
            "programme_id": programme_id,
            "client_id": client_id,
            "phase_kind": entry["phase_kind"],
            "ordinal": ordinal,
            "planned_start_date": cursor.isoformat(),
            "planned_end_date": end.isoformat(),
            "actual_start_date": None, "actual_end_date": None,
            "entry_criteria": pd_def.get("entry_criteria", []),
            "exit_criteria": pd_def.get("exit_criteria", []),
            "status": "active" if ordinal == 1 else "upcoming",
            "purpose_summary": f"{entry['phase_kind'].replace('_',' ').title()} block",
            "training_priorities": pd_def.get("training_priorities", []),
            "volume_bias": pd_def.get("volume_bias"),
            "intensity_bias": pd_def.get("intensity_bias"),
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        phase_ids.append(phid)
        cursor = end + _dt.timedelta(days=1)
        remaining = (programme_end - cursor).days + 1

    if phase_ids:
        await db.programmes_v2.update_one(
            {"id": programme_id},
            {"$set": {"phase_sequence": phase_ids, "updated_at": now_iso()}}
        )
    return phase_ids


@api.post("/v2/coach/clients/{client_id}/plan/kickoff")
async def plan_kickoff(
    client_id: str, body: KickoffBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """One-click plan build. See module docstring."""
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found")
    v2 = ((client.get("profile") or {}).get("v2_flags") or {})
    if not (v2.get("v2_default") or v2.get("state_foundation_enabled")):
        raise HTTPException(409, "Client is not V2-flagged")

    goal_tax = body.goal_id_taxonomy or DEFAULT_GOAL
    weeks = max(1, min(52, body.weeks or 8))

    goal = await _ensure_goal(client_id, goal_tax)
    programme = await _ensure_programme(client_id, goal, weeks, coach["id"], body.force)
    phase_ids = await _seed_phases(programme, coach["id"])
    if not phase_ids:
        raise HTTPException(400, "Could not seed phases")

    # Step 4 — P3 demand: build training_objectives + exposures
    from feature_v2_p3_demand import objectives_build, BuildDemandBody  # type: ignore
    p3_res = await objectives_build(client_id, BuildDemandBody(programme_id=programme["id"]), coach=coach)

    # Step 5 — P5 scheduling: allocate workout_assignments across schedule_days
    #   Range: today → min(programme_end, today + weeks weeks)
    start = _dt.date.today()
    end = min(_dt.date.fromisoformat(programme["end_date"]),
              start + _dt.timedelta(weeks=weeks) - _dt.timedelta(days=1))
    from feature_v2_p5_scheduling import plan_build as p5_plan_build, BuildPlanBody
    p5_res = await p5_plan_build(
        client_id,
        BuildPlanBody(
            programme_id=programme["id"],
            from_date=start.isoformat(),
            to_date=end.isoformat(),
        ),
        coach=coach,
    )

    # Step 6 — P6 construction: build workout_implementations for assignments
    from feature_v2_p6_construction import implementations_build, BuildImplBody
    p6_res = await implementations_build(
        client_id,
        BuildImplBody(
            programme_id=programme["id"],
            from_date=start.isoformat(),
            to_date=end.isoformat(),
        ),
        coach=coach,
    )

    # Ensure a plan_draft exists so the workspace can highlight "Ready for review"
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
            "notes": "Auto-scaffolded by kickoff",
            "created_by": coach["id"],
            "created_at": now_iso(), "updated_at": now_iso(),
            "metrics": {
                "assignments_count": int(p5_res.get("assignments_created", 0)),
                "implementations_count": int(p6_res.get("implementations_created", 0)),
            },
        })
        draft = await db.plan_drafts.find_one({"id": draft_id}, {"_id": 0})

    # Backfill assignments with draft_id for the publisher endpoint
    if draft and draft.get("id"):
        await db.workout_assignments.update_many(
            {"client_id": client_id, "programme_id": programme["id"], "draft_id": None},
            {"$set": {"draft_id": draft["id"]}}
        )

    await write_decision(
        actor="coach", layer="ORCHESTRATION", scope_kind="programme",
        scope_id=programme["id"], client_id=client_id, outcome="APPLIED",
        reason=(
            f"Plan kickoff: goal={goal_tax}, {len(phase_ids)} phases, "
            f"{p3_res.get('objectives_created')} objectives, "
            f"{p5_res.get('assignments_created')} sessions, "
            f"{p6_res.get('implementations_created')} implementations"
        ),
    )
    try:
        await emit_metric(
            "plan_kickoff_completed", client_id=client_id, coach_id=coach["id"],
            labels={
                "assignments": int(p5_res.get("assignments_created", 0)),
                "impls": int(p6_res.get("implementations_created", 0)),
                "phases": len(phase_ids),
            },
        )
    except Exception:
        pass

    return {
        "status": "ok",
        "programme_id": programme["id"],
        "draft_id": (draft or {}).get("id"),
        "goal": goal_tax,
        "phases": len(phase_ids),
        "objectives_created": p3_res.get("objectives_created"),
        "assignments_created": p5_res.get("assignments_created"),
        "implementations_created": p6_res.get("implementations_created"),
    }


logger.info("feature_v2_coach_kickoff: /api/v2/coach/clients/{cid}/plan/kickoff registered")
