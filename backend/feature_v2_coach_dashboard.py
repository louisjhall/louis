"""
feature_v2_coach_dashboard — Coach Dashboard V2 aggregate endpoints.

Per the build brief §63, all Roster+Plan workspace data loads through ONE
aggregate endpoint per (client, month). This avoids the V1 fragmentation
where the coach dashboard fetches roster / calendar / programme / workouts
separately for the same underlying schedule.

Also serves the cross-client Attention queue (§4-5) and the global Today
summary (§6).

Ships behind `v2_flags.coach_dashboard_v2_enabled` (per-coach flag). V1
dashboard remains fully functional; nothing in V1 is mutated.
"""
from __future__ import annotations

import datetime as _dt
from calendar import monthrange
from typing import Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, ensure_indexes, bg, flag_on
)


# ---------------------------------------------------------------------------
# Flag helpers — per-coach flag (not per-client)
# ---------------------------------------------------------------------------

async def _coach_has_v2_flag(coach_id: str) -> bool:
    coach = await db.users.find_one({"id": coach_id}, {"_id": 0, "profile.v2_flags": 1})
    if not coach:
        return False
    v2 = ((coach.get("profile") or {}).get("v2_flags") or {})
    return bool(v2.get("coach_dashboard_v2_enabled") or v2.get("v2_default"))


class CoachDashboardFlagBody(BaseModel):
    coach_dashboard_v2_enabled: Optional[bool] = None


@api.patch("/v2/coach/me/dashboard-flag")
async def coach_dashboard_flag_set(
    body: CoachDashboardFlagBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Coach toggles the Dashboard V2 preview flag on themselves."""
    updates: dict = {}
    if body.coach_dashboard_v2_enabled is not None:
        updates["profile.v2_flags.coach_dashboard_v2_enabled"] = bool(body.coach_dashboard_v2_enabled)
    if not updates:
        return {"ok": True, "enabled": await _coach_has_v2_flag(coach["id"])}
    updates["profile.v2_flags.updated_at"] = now_iso()
    await db.users.update_one({"id": coach["id"]}, {"$set": updates})
    return {"ok": True, "enabled": await _coach_has_v2_flag(coach["id"])}


@api.get("/v2/coach/me/dashboard-flag")
async def coach_dashboard_flag_get(coach: dict = Depends(require_role("coach"))) -> dict:
    return {"enabled": await _coach_has_v2_flag(coach["id"])}


# ---------------------------------------------------------------------------
# Cross-client Attention queue (§4, §5)
# ---------------------------------------------------------------------------

async def _client_v2_flag(client: dict, flag: str) -> bool:
    v2 = ((client.get("profile") or {}).get("v2_flags") or {})
    return bool(v2.get(flag) or v2.get("v2_default"))


async def _client_kind(client: dict) -> str:
    """Return 'v2' if any of the state-foundation flags are on, else 'v1'."""
    v2 = ((client.get("profile") or {}).get("v2_flags") or {})
    if v2.get("v2_default") or v2.get("state_foundation_enabled"):
        return "v2"
    return "v1"


async def _client_attention_items(client: dict) -> list[dict]:
    """Produce attention rows for a single client (V2 flag-gated)."""
    cid = client["id"]
    kind = await _client_kind(client)
    items: list[dict] = []

    if kind != "v2":
        return items

    # Open exceptions (severity ≥ warning) — from P5 validator
    exc = await db.exceptions.find(
        {"client_id": cid, "status": "open", "severity": {"$in": ["warning", "blocker"]}},
        {"_id": 0}
    ).to_list(20)
    for e in exc:
        items.append({
            "kind": _map_exception_kind(e.get("kind")),
            "severity": e.get("severity"),
            "reason": e.get("human_readable_reason") or e.get("kind") or "Exception raised",
            "created_at": e.get("triggered_at"),
            "scope_ref": e.get("scope_ref"),
            "source": "exception",
            "source_id": e.get("id"),
        })

    # Ready-for-review drafts (P1) with counts of ready vs review
    drafts = await db.plan_drafts.find(
        {"client_id": cid, "status": {"$in": ["ready_for_review", "partially_approved"]}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(5)
    for d in drafts:
        metrics = d.get("metrics") or {}
        # Compute live counts from assignments in this draft
        counts = await _assignment_counts(cid, draft_id=d["id"])
        if counts["ready"] + counts["review"] + counts["conflict"] > 0:
            items.append({
                "kind": "programme_ready",
                "severity": "warning" if counts["conflict"] > 0 else "info",
                "reason": _summary_reason(counts),
                "created_at": d.get("updated_at") or d.get("build_completed_at"),
                "scope_ref": d.get("id"),
                "source": "plan_draft",
                "source_id": d.get("id"),
                "counts": counts,
            })

    # Recent readiness that says coach_review
    rs = await db.readiness_states.find_one(
        {"client_id": cid}, {"_id": 0}, sort=[("as_of_date", -1)]
    )
    if rs and rs.get("band") == "coach_review":
        pain_flags = (rs.get("signals") or {}).get("pain_flags") or []
        if pain_flags:
            regions = ", ".join((p.get("region") or "") for p in pain_flags[:2]) or "unknown"
            items.append({
                "kind": "pain_reported",
                "severity": "warning",
                "reason": f"Pain reported ({regions})",
                "created_at": rs.get("computed_at"),
                "scope_ref": rs.get("id"),
                "source": "readiness_state",
                "source_id": rs.get("id"),
            })
        else:
            items.append({
                "kind": "checkin_concern",
                "severity": "warning",
                "reason": "Readiness moved to coach_review band",
                "created_at": rs.get("computed_at"),
                "scope_ref": rs.get("id"),
                "source": "readiness_state",
                "source_id": rs.get("id"),
            })

    # Failed / dead-letter jobs
    dead = await db.jobs.count_documents(
        {"target_scope.client_id": cid, "status": {"$in": ["dead_letter", "failed"]}}
    )
    if dead > 0:
        items.append({
            "kind": "generation_failure",
            "severity": "warning",
            "reason": f"{dead} background job(s) failed",
            "created_at": now_iso(),
            "scope_ref": None,
            "source": "jobs",
            "source_id": None,
        })

    return items


def _map_exception_kind(k: str) -> str:
    mapping = {
        "roster_change": "roster_changed",
        "insufficient_recovery": "conflict",
        "session_cannot_fit": "conflict",
        "event_session_unscheduled": "event_at_risk",
        "objective_missed": "missed_key_session",
        "multi_a_conflict": "conflict",
        "coach_directive_conflict": "conflict",
        "low_confidence_roster_parse": "roster_parsing",
        "unrealistic_timeline": "event_at_risk",
        "pain_reported": "pain_reported",
    }
    return mapping.get(k or "", "needs_review")


def _summary_reason(counts: dict) -> str:
    parts = []
    if counts["ready"]:    parts.append(f"{counts['ready']} Ready")
    if counts["review"]:   parts.append(f"{counts['review']} Review")
    if counts["conflict"]: parts.append(f"{counts['conflict']} Conflict")
    return " · ".join(parts) or "Draft available"


async def _assignment_counts(client_id: str, *, draft_id: Optional[str] = None,
                              date_from: Optional[str] = None,
                              date_to: Optional[str] = None) -> dict:
    q: dict = {"client_id": client_id}
    if draft_id:  q["draft_id"] = draft_id
    if date_from or date_to:
        q["date"] = {}
        if date_from: q["date"]["$gte"] = date_from
        if date_to:   q["date"]["$lte"] = date_to
    rows = await db.workout_assignments.find(q, {"_id": 0}).to_list(500)
    counts = {"ready": 0, "review": 0, "conflict": 0, "coach_edited": 0,
              "approved": 0, "live": 0, "locked": 0, "total": len(rows)}
    for a in rows:
        st = a.get("status") or ""
        if st == "ready":                 counts["ready"] += 1
        if st == "live":                  counts["live"] += 1
        if a.get("locked"):               counts["locked"] += 1
        # Review = ready but flagged for coach review OR has an open exception on it
        if a.get("needs_coach_review"):   counts["review"] += 1
    # Conflicts: open exceptions with blocker severity attached to any assignment in range
    exc_q: dict = {"client_id": client_id, "status": "open", "severity": "blocker"}
    counts["conflict"] = await db.exceptions.count_documents(exc_q)
    # Approvals: rows that appear inside a published plan_version snapshot
    if draft_id:
        pv_ids = await db.approvals.distinct("version_id", {"draft_id": draft_id, "client_id": client_id})
        counts["approved"] = len(pv_ids)
    return counts


@api.get("/v2/coach/dashboard/attention")
async def dashboard_attention(
    limit: int = Query(50, ge=1, le=200),
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return the cross-client attention queue. V1-only clients contribute
    nothing here (their existing V1 dashboard handles them)."""
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")

    clients = await db.users.find(
        # Iter 162 · exclude deleted / soft-deleted alongside archived
        {"role": "client",
         "status": {"$nin": ["archived", "deleted"]},
         "is_deleted": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "display_name": 1, "email": 1,
         "profile.v2_flags": 1, "profile.avatar_url": 1}
    ).to_list(500)

    rows: list[dict] = []
    for c in clients:
        items = await _client_attention_items(c)
        for it in items:
            rows.append({
                "client_id": c["id"],
                "client_name": c.get("display_name") or c.get("name") or c.get("email") or "Client",
                **it,
            })
    # Order: blocker > warning > info; then newest first
    severity_order = {"blocker": 0, "warning": 1, "info": 2}
    rows.sort(key=lambda r: (severity_order.get(r.get("severity") or "info", 3),
                              r.get("created_at") or ""), reverse=False)
    return {"attention": rows[:limit], "count": len(rows)}


# ---------------------------------------------------------------------------
# Global summary (§6)
# ---------------------------------------------------------------------------

@api.get("/v2/coach/dashboard/summary")
async def dashboard_summary(coach: dict = Depends(require_role("coach"))) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")

    active_clients = await db.users.count_documents(
        # Iter 162 · exclude deleted / soft-deleted rows from the KPI.
        {"role": "client",
         "status": {"$nin": ["archived", "deleted"]},
         "is_deleted": {"$ne": True}}
    )
    attention = await dashboard_attention(limit=1000, coach=coach)
    at_rows = attention.get("attention") or []

    programmes_ready = sum(1 for r in at_rows if r.get("kind") == "programme_ready")
    roster_changes = sum(1 for r in at_rows if r.get("kind") == "roster_changed")
    checkin_concerns = sum(1 for r in at_rows if r.get("kind") in ("checkin_concern", "pain_reported"))
    unique_clients_need_attention = len({r["client_id"] for r in at_rows})

    return {
        "active_clients": active_clients,
        "need_attention": unique_clients_need_attention,
        "programmes_ready": programmes_ready,
        "roster_changes": roster_changes,
        "checkin_concerns": checkin_concerns,
        "at": now_iso(),
    }


# ---------------------------------------------------------------------------
# Client list with V2 state (§7)
# ---------------------------------------------------------------------------

@api.get("/v2/coach/dashboard/clients")
async def dashboard_clients(
    filter: Optional[str] = None,      # all | attention | programme_ready | roster_changed | event | quiet
    q: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")

    # Iter 162 · exclude deleted / soft-deleted rows from the client list.
    query: dict = {
        "role": "client",
        "status": {"$nin": ["archived", "deleted"]},
        "is_deleted": {"$ne": True},
    }
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"display_name": {"$regex": q, "$options": "i"}},
        ]
    clients = await db.users.find(
        query, {"_id": 0, "id": 1, "name": 1, "display_name": 1, "email": 1,
                 "profile.v2_flags": 1, "profile.airline": 1, "profile.avatar_url": 1,
                 "profile.main_goal_key": 1}
    ).sort("name", 1).to_list(500)

    today = _dt.date.today().isoformat()
    out = []
    for c in clients:
        kind = await _client_kind(c)
        attn = await _client_attention_items(c) if kind == "v2" else []
        # Today's status: read the schedule_day derived classification (V2) or fallback to V1 rosters
        sd = await db.schedule_days.find_one({"client_id": c["id"], "date": today}, {"_id": 0})
        today_label = "Home Day"
        if sd:
            cls = (sd.get("derived") or {}).get("classification") or "home"
            today_label = _humanise_classification(cls)
        # Primary goal (best-effort)
        goal = None
        v2goal = await db.goals_v2.find_one(
            {"client_id": c["id"], "status": "active", "priority": "A"}, {"_id": 0}
        )
        if v2goal:
            goal = _humanise_goal(v2goal.get("goal_id_taxonomy"))
        else:
            goal = _humanise_goal((c.get("profile") or {}).get("main_goal_key"))

        # Current phase (V2 only)
        phase = None
        prog = await db.programmes_v2.find_one(
            {"client_id": c["id"], "status": {"$in": ["active", "draft"]}}, {"_id": 0}
        )
        if prog:
            active_phase = await db.programme_phases_v2.find_one(
                {"programme_id": prog["id"], "status": "active"}, {"_id": 0}
            )
            if active_phase:
                phase = _humanise(active_phase.get("phase_kind"))

        # Status chip based on attention items
        status_chip = "ready"
        chip_detail = "No action required"
        if any(a["kind"] == "programme_ready" for a in attn):
            status_chip = "review"
            row = next(a for a in attn if a["kind"] == "programme_ready")
            chip_detail = row["reason"]
        elif any(a["kind"] in ("conflict",) for a in attn):
            status_chip = "conflict"
            chip_detail = "Conflict requires attention"
        elif any(a["kind"] == "roster_changed" for a in attn):
            status_chip = "roster_changed"
            chip_detail = "Roster changed"
        elif any(a["kind"] in ("checkin_concern", "pain_reported") for a in attn):
            status_chip = "checkin"
            chip_detail = next(a["reason"] for a in attn if a["kind"] in ("checkin_concern", "pain_reported"))
        elif not attn:
            status_chip = "ready"
            chip_detail = "No action required"

        row = {
            "client_id": c["id"],
            "name": c.get("display_name") or c.get("name") or c.get("email"),
            "email": c.get("email"),
            "avatar_url": (c.get("profile") or {}).get("avatar_url"),
            "kind": kind,
            "goal": goal,
            "phase": phase,
            "today_label": today_label,
            "attention_count": len(attn),
            "status_chip": status_chip,
            "chip_detail": chip_detail,
        }

        if filter == "attention":
            if len(attn) == 0:
                continue
        elif filter == "programme_ready":
            if not any(a["kind"] == "programme_ready" for a in attn):
                continue
        elif filter == "roster_changed":
            if not any(a["kind"] == "roster_changed" for a in attn):
                continue
        elif filter == "quiet":
            if len(attn) > 0:
                continue

        out.append(row)

    return {"clients": out, "count": len(out)}


def _humanise(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return s.replace("_", " ").title()


def _humanise_goal(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    label_map = {
        "body_composition.fat_loss": "Fat loss",
        "body_composition.muscle_gain": "Muscle gain",
        "strength.general": "General strength",
        "running.5k": "Run 5K",
        "running.10k": "Run 10K",
        "running.half_marathon": "Half marathon",
        "running.marathon": "Marathon",
        "triathlon.70_3": "Ironman 70.3",
        "general.longevity": "Longevity",
    }
    return label_map.get(s) or s.replace(".", " · ").replace("_", " ").title()


def _humanise_classification(cls: str) -> str:
    labels = {
        "rest": "Rest",
        "layover_arrival": "Layover Arrival",
        "layover_full": "Layover",
        "layover_departure": "Layover Departure",
        "layover": "Layover",
        "turnaround": "Turnaround",
        "standby": "Standby",
        "home": "Home Day",
        "home_day": "Home Day",
        "leave": "Leave",
        "annual_leave": "Annual Leave",
        "sick": "Sick",
        "sickness": "Sick",
        "flight": "Flight Duty",
        "duty": "Duty",
        "training": "Training",
        "off": "Off",
        "other": "Other",
    }
    return labels.get(cls, _humanise(cls) or "Home Day")


# ---------------------------------------------------------------------------
# Per-client month workspace (§10-11) — the ONE aggregate call
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/workspace/months")
async def workspace_months_list(
    client_id: str, coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return the list of months for which we have schedule_days OR a V1 roster.
    Newest first."""
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    months = set()

    async for row in db.schedule_days.find(
        {"client_id": client_id}, {"_id": 0, "date": 1}
    ):
        d = row.get("date") or ""
        if len(d) >= 7:
            months.add(d[:7])

    # Also include V1 rosters so we don't lose historical months
    async for r in db.rosters.find(
        {"user_id": client_id}, {"_id": 0, "days": 1}
    ):
        for day in (r.get("days") or []):
            d = day.get("date") or ""
            if len(d) >= 7:
                months.add(d[:7])

    lst = sorted(months, reverse=True)
    return {"months": lst, "current": _dt.date.today().isoformat()[:7]}


@api.get("/v2/coach/clients/{client_id}/workspace/{month}")
async def workspace_month(
    client_id: str, month: str,   # "YYYY-MM"
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """ONE aggregate call producing every field the Roster+Plan workspace needs
    for a given month. Any additional detail (e.g. exercise list) is lazy."""
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    try:
        year, mo = int(month[:4]), int(month[5:7])
        _, last = monthrange(year, mo)
    except Exception:
        raise HTTPException(400, "month must be YYYY-MM")
    sd_str = f"{year:04d}-{mo:02d}-01"
    ed_str = f"{year:04d}-{mo:02d}-{last:02d}"

    client = await db.users.find_one(
        {"id": client_id}, {"_id": 0, "id": 1, "name": 1, "display_name": 1,
                             "email": 1, "profile": 1}
    )
    if not client:
        raise HTTPException(404, "Client not found")

    kind = await _client_kind(client)

    # --- Schedule days
    sched_days = await db.schedule_days.find(
        {"client_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str}}, {"_id": 0}
    ).sort("date", 1).to_list(50)

    # If no V2 schedule_days but there is a V1 roster, expose V1 days as read-only
    if not sched_days:
        roster_days = []
        r_docs = await db.rosters.find(
            {"user_id": client_id, "is_active": True}, {"_id": 0}
        ).to_list(10)
        for r in r_docs:
            for d in (r.get("days") or []):
                if (d.get("date") or "").startswith(f"{year:04d}-{mo:02d}"):
                    roster_days.append({
                        "id": None, "client_id": client_id,
                        "date": d.get("date"), "derived": {
                            "classification": d.get("classification") or ("rest" if not d.get("duties") else "flight"),
                            "duty_burden_band": None,
                            "duty_burden_score": None,
                            "training_opportunity": None,
                            "recommended_intensity_ceiling": None,
                            "available_time_min": None,
                        },
                        "duties": [],
                        "v1_source": True,
                    })
        sched_days = roster_days

    # --- Assignments (V2)
    assignments = await db.workout_assignments.find(
        {"client_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str}}, {"_id": 0}
    ).sort("date", 1).to_list(200)

    # For V1-only clients: expose V1 workouts as read-only rows.
    # For V2 clients: still surface manual workouts (source=coach_manual) so
    # the Plan calendar shows them alongside V2 assignments.
    v1_workouts = []
    if kind == "v1":
        v1_workouts = await db.workouts.find(
            {"user_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str}}, {"_id": 0}
        ).sort("date", 1).to_list(200)
    else:
        v1_workouts = await db.workouts.find(
            {"user_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str},
             "source": "coach_manual"}, {"_id": 0}
        ).sort("date", 1).to_list(200)

    # Implementations (only fetch summaries — not full exercise lists — for the header row)
    impl_ids = [a.get("draft_implementation_id") or a.get("live_implementation_id") for a in assignments]
    impl_ids = [i for i in impl_ids if i]
    impls_map = {}
    if impl_ids:
        for impl in await db.workout_implementations.find(
            {"id": {"$in": impl_ids}},
            {"_id": 0, "id": 1, "title": 1, "duration_min": 1, "equipment_context": 1,
             "focus": 1, "needs_coach_review": 1, "variant_type": 1, "key_session": 1}
        ).to_list(500):
            impls_map[impl["id"]] = impl

    # Objectives (only fields we need for exposure display)
    obj_ids = list({a.get("objective_id") for a in assignments if a.get("objective_id")})
    objs_map = {}
    if obj_ids:
        for o in await db.training_objectives.find(
            {"id": {"$in": obj_ids}},
            {"_id": 0, "id": 1, "kind": 1, "importance": 1, "phase_id": 1}
        ).to_list(500):
            objs_map[o["id"]] = o

    # Exposure sequences
    expo_ids = [a.get("objective_exposure_id") for a in assignments if a.get("objective_exposure_id")]
    expos_map = {}
    if expo_ids:
        for e in await db.objective_exposures.find(
            {"id": {"$in": expo_ids}},
            {"_id": 0, "id": 1, "sequence": 1, "status": 1}
        ).to_list(500):
            expos_map[e["id"]] = e

    # --- Draft + LIVE meta
    programme = await db.programmes_v2.find_one(
        {"client_id": client_id, "status": {"$in": ["active", "draft"]}}, {"_id": 0}
    )
    live_version = None
    draft = None
    if programme:
        live_version = await db.plan_versions.find_one(
            {"programme_id": programme["id"], "client_id": client_id},
            {"_id": 0}, sort=[("version", -1)],
        )
        draft = await db.plan_drafts.find_one(
            {"programme_id": programme["id"], "client_id": client_id,
             "status": {"$in": ["building", "ready_for_review", "partially_approved"]}},
            {"_id": 0}
        )

    # --- Open exceptions in this month
    exc = await db.exceptions.find(
        {"client_id": client_id, "status": "open"}, {"_id": 0}
    ).sort("triggered_at", -1).to_list(50)

    # --- Compose per-day rows
    days_by_date: dict[str, dict] = {}
    # start with schedule_days (whether V2 or V1-derived)
    for sd in sched_days:
        derived = sd.get("derived") or {}
        # Prefer derived.classification (V2 facets); fall back to top-level
        # day_type set by the roster parser. Never silently render "home" when
        # the day is actually a layover/turnaround/standby.
        classification = (derived.get("classification")
                          or sd.get("day_type")
                          or "home")
        days_by_date[sd["date"]] = {
            "date": sd["date"],
            "schedule": {
                "classification": classification,
                "classification_label": _humanise_classification(classification),
                "duty_burden_band": derived.get("duty_burden_band"),
                "duty_burden_score": derived.get("duty_burden_score"),
                "training_opportunity": derived.get("training_opportunity"),
                "recommended_intensity_ceiling": derived.get("recommended_intensity_ceiling"),
                "available_time_min": derived.get("available_time_min"),
                "overnight_location": sd.get("overnight_location"),
                "v1_source": sd.get("v1_source", False),
            },
            "assignments": [],
            "v1_workouts": [],
        }

    for a in assignments:
        d = a["date"]
        if d not in days_by_date:
            days_by_date[d] = {"date": d, "schedule": None, "assignments": [], "v1_workouts": []}
        impl = impls_map.get(a.get("draft_implementation_id") or a.get("live_implementation_id"))
        obj = objs_map.get(a.get("objective_id"))
        expo = expos_map.get(a.get("objective_exposure_id"))
        status_label, status_kind = _assignment_status_label(a, impl)
        days_by_date[d]["assignments"].append({
            "id": a["id"],
            "kind": (obj or {}).get("kind"),
            "kind_label": _humanise((obj or {}).get("kind")) or "Session",
            "importance": (obj or {}).get("importance") or a.get("importance"),
            "duration_min": (impl or {}).get("duration_min") or a.get("planned_duration_min"),
            "equipment": ((impl or {}).get("equipment_context") or {}).get("equipment") or [],
            "focus": (impl or {}).get("focus") or (obj or {}).get("kind"),
            "exposure_sequence": (expo or {}).get("sequence"),
            "objective_id": a.get("objective_id"),
            "status": a.get("status"),
            "status_label": status_label,
            "status_kind": status_kind,
            "needs_coach_review": bool((impl or {}).get("needs_coach_review")),
            "locked": bool(a.get("locked")),
            "live_implementation_id": a.get("live_implementation_id"),
            "draft_implementation_id": a.get("draft_implementation_id"),
            "key_session": bool((impl or {}).get("key_session")),
            "variant_type": (impl or {}).get("variant_type"),
        })

    for w in v1_workouts:
        d = w.get("date")
        if not d: continue
        if d not in days_by_date:
            days_by_date[d] = {"date": d, "schedule": None, "assignments": [], "v1_workouts": []}
        days_by_date[d]["v1_workouts"].append({
            "id": w.get("id"),
            "title": w.get("title") or w.get("focus") or "Session",
            "duration_min": w.get("duration_min"),
            "focus": w.get("focus"),
            "approved": bool(w.get("approved")),
            "coach_locked": bool(w.get("coach_locked")),
            "needs_coach_review": bool(w.get("needs_coach_review")),
            "completed": bool(w.get("completed")),
            "source": w.get("source"),
            "manual_lock": bool(w.get("manual_lock")),
        })

    # --- Engine V2 placements (plan_live_v2 preferred, else active draft preview)
    # This is the bridge that turns Engine V2's placements + session_specs into
    # calendar cards for the coach's Roster + Plan workspace. Without this the
    # V2 publish would leave the calendar empty (the classic "I published but
    # nothing appeared" bug).
    v2_live = await db.plan_live_v2.find_one(
        {"client_id": client_id, "active": True}, {"_id": 0},
    )
    v2_source_doc = v2_live
    v2_source_kind = "live" if v2_live else None
    if not v2_live:
        # Fall back to the active draft so the coach can *preview* placements
        # on the calendar even before publishing.
        v2_draft = await db.plan_drafts_v2.find_one(
            {"client_id": client_id,
             "status": {"$in": ["needs_review", "ready_for_review"]}},
            {"_id": 0}, sort=[("created_at", -1)],
        )
        if v2_draft:
            v2_source_doc = v2_draft
            v2_source_kind = "draft"

    if v2_source_doc:
        placements = v2_source_doc.get("placements") or []
        specs = v2_source_doc.get("session_specs") or {}
        source_id = v2_source_doc.get("id")
        for p in placements:
            d = p.get("date")
            if not d:
                continue
            if not (sd_str <= d <= ed_str):
                continue
            if d not in days_by_date:
                days_by_date[d] = {
                    "date": d, "schedule": None,
                    "assignments": [], "v1_workouts": [],
                }
            # Skip duplicates if the same day already has a real assignment
            # for the same objective_id (defensive; V2 flow doesn't create
            # workout_assignments today).
            eid = p.get("exposure_id") or ""
            objective_id = p.get("objective_id")
            already = any(
                a.get("objective_id") and a.get("objective_id") == objective_id
                for a in days_by_date[d]["assignments"]
            )
            if already:
                continue
            spec = specs.get(eid) or {}
            spec_kind = spec.get("spec_kind") or ""
            equipment = list(spec.get("equipment_used") or [])
            env = spec.get("environment")
            if env and env not in ("any", "none", "?"):
                # Prepend environment as a badge (e.g. "outdoor", "treadmill")
                equipment = [env] + [e for e in equipment if e != env]
            status_kind = "live" if v2_source_kind == "live" else "review"
            status_label = "Live" if status_kind == "live" else "Draft"
            if p.get("kind") == "rest":
                # Don't render rest as a card — the day cell already says "Rest"
                continue
            _kind = p.get("kind") or spec.get("kind") or "session"
            days_by_date[d]["assignments"].append({
                "id": f"v2p:{source_id}:{eid}",
                "kind": _kind,
                "kind_label": _humanise(_kind) or "Session",
                "importance": p.get("priority"),
                "duration_min": (spec.get("duration_min")
                                  or p.get("target_duration_min")),
                "equipment": equipment,
                "focus": spec.get("rationale") or spec_kind or _kind,
                "exposure_sequence": p.get("exposure_number"),
                "objective_id": objective_id,
                "status": "live" if status_kind == "live" else "draft",
                "status_label": status_label,
                "status_kind": status_kind,
                "needs_coach_review": bool(spec.get("coach_review_required")),
                "locked": False,
                "live_implementation_id": None,
                "draft_implementation_id": None,
                "key_session": bool(p.get("key")),
                "variant_type": spec_kind or None,
                # Extra hints for the frontend drawer
                "v2_source": v2_source_kind,
                "v2_source_id": source_id,
                "v2_exposure_id": eid,
                "v2_intensity_target": (p.get("intensity_target")
                                         or spec.get("intensity_target")),
            })

    days = [days_by_date[k] for k in sorted(days_by_date.keys())]

    # Roster duty enrichment — attach flight/duty/hotel details from the
    # existing parsed roster (db.rosters.days[]) to each schedule day so
    # the coach can plan workouts around the real duty pattern instead of
    # only a broad classification. Read-only. Flight Support unaffected.
    try:
        from feature_roster_duty_details import (
            build_duty_details_map, enrich_schedule_with_duty,
        )
        duty_map = await build_duty_details_map(client_id, sd_str, ed_str)
        for d in days:
            d["schedule"] = enrich_schedule_with_duty(d.get("schedule"), duty_map.get(d["date"]))
    except Exception as e:
        logger.warning(f"duty details enrichment failed for {client_id}: {e}")

    # Iter 117 — Aviation Support (Phase B). Inject per-day flight support
    # into the workspace so the coach sees Roster + Training + Flight
    # Support all in one place. Never affects the counts below.
    try:
        from feature_aviation_support_api import (
            _flight_support_for_range, _bundle_interventions, _apply_completions,
        )
        fs_by_date = await _flight_support_for_range(client_id, sd_str, ed_str)
        for d in days:
            items = fs_by_date.get(d["date"], [])
            if items:
                bundled = _bundle_interventions(items)
                bundled = await _apply_completions(client_id, bundled)
                d["flight_support"] = bundled
            else:
                d["flight_support"] = []
    except Exception:
        # Aviation support must NEVER break the coach workspace.
        for d in days:
            d["flight_support"] = []

    # --- Counts (per §9)
    counts = {"ready": 0, "review": 0, "conflict": 0, "coach_edited": 0,
              "approved": 0, "live": 0, "locked": 0, "total": 0}
    for d in days:
        for a in d.get("assignments") or []:
            counts["total"] += 1
            if a["status_kind"] == "ready":    counts["ready"] += 1
            if a["status_kind"] == "review":   counts["review"] += 1
            if a["status_kind"] == "conflict": counts["conflict"] += 1
            if a["status_kind"] == "approved": counts["approved"] += 1
            if a["status"] == "live":          counts["live"] += 1
            if a.get("locked"):                counts["locked"] += 1

    return {
        "client": {
            "id": client["id"],
            "name": client.get("display_name") or client.get("name") or client.get("email"),
            "kind": kind,
        },
        "month": month,
        "days": days,
        "counts": counts,
        "programme": _programme_summary(programme, live_version, draft),
        "exceptions": exc,
        "generated_at": now_iso(),
    }


def _assignment_status_label(a: dict, impl: Optional[dict]) -> tuple[str, str]:
    """Return (human_label, semantic_kind ∈ ready|review|conflict|approved|coach_edited|live|locked)."""
    if a.get("locked"):
        return ("Locked", "locked")
    if a.get("status") == "live":
        return ("Live", "live")
    if a.get("status") == "completed":
        return ("Completed", "approved")
    if impl and impl.get("needs_coach_review"):
        return ("Needs Review", "review")
    if a.get("status") == "ready":
        return ("Ready", "ready")
    if a.get("status") == "proposed":
        return ("Ready", "ready")
    if a.get("status") == "in_progress":
        return ("In Progress", "approved")
    return (str(a.get("status") or "Ready").title(), "ready")


def _programme_summary(prog: Optional[dict], live_v: Optional[dict], draft: Optional[dict]) -> dict:
    if not prog:
        return {"present": False}
    return {
        "present": True,
        "id": prog["id"],
        "status": prog.get("status"),
        "primary_goal_id": prog.get("primary_goal_id"),
        "timeline_class": prog.get("timeline_class"),
        "start_date": prog.get("start_date"),
        "end_date": prog.get("end_date"),
        "live_version_id": (live_v or {}).get("id"),
        "live_version_number": (live_v or {}).get("version"),
        "live_published_at": (live_v or {}).get("published_at"),
        "draft_id": (draft or {}).get("id"),
        "draft_status": (draft or {}).get("status"),
    }


# ---------------------------------------------------------------------------
# Batch approve Ready (§28)
# ---------------------------------------------------------------------------

class ApproveReadyBody(BaseModel):
    month: str                  # YYYY-MM
    draft_id: Optional[str] = None
    notes: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/plan/approve-ready")
async def plan_approve_ready(
    client_id: str, body: ApproveReadyBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Batch-approve every Ready (status=ready, not needs_coach_review, not locked)
    assignment in the given month. Creates ONE plan_version + snapshot capturing
    all approved assignment IDs."""
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    await require_client_and_flag(client_id, "state_foundation_enabled")

    try:
        year, mo = int(body.month[:4]), int(body.month[5:7])
        _, last = monthrange(year, mo)
    except Exception:
        raise HTTPException(400, "month must be YYYY-MM")
    sd_str = f"{year:04d}-{mo:02d}-01"
    ed_str = f"{year:04d}-{mo:02d}-{last:02d}"

    q: dict = {
        "client_id": client_id,
        "date": {"$gte": sd_str, "$lte": ed_str},
        "status": {"$in": ["proposed", "ready"]},
        "locked": {"$ne": True},
    }
    if body.draft_id:
        q["draft_id"] = body.draft_id
    ready_rows = await db.workout_assignments.find(q, {"_id": 0}).to_list(500)

    # Filter out those flagged as needs_coach_review by their draft implementation
    impl_ids = [r.get("draft_implementation_id") for r in ready_rows if r.get("draft_implementation_id")]
    review_flags = {}
    if impl_ids:
        for i in await db.workout_implementations.find(
            {"id": {"$in": impl_ids}}, {"_id": 0, "id": 1, "needs_coach_review": 1}
        ).to_list(500):
            review_flags[i["id"]] = bool(i.get("needs_coach_review"))

    approved_ids: list[str] = []
    for r in ready_rows:
        impl_id = r.get("draft_implementation_id")
        if impl_id and review_flags.get(impl_id):
            continue   # skip review-flagged
        approved_ids.append(r["id"])

    if not approved_ids:
        return {"approved_count": 0, "note": "No Ready items to approve"}

    # Advance assignments to live and set live_implementation_id
    for r in ready_rows:
        if r["id"] not in approved_ids:
            continue
        upd = {"status": "live", "updated_at": now_iso()}
        if r.get("draft_implementation_id"):
            upd["live_implementation_id"] = r["draft_implementation_id"]
        await db.workout_assignments.update_one({"id": r["id"]}, {"$set": upd})

    # Create a plan_version + snapshot
    prog = await db.programmes_v2.find_one({"client_id": client_id, "status": {"$in": ["active", "draft"]}}, {"_id": 0})
    programme_id = (prog or {}).get("id") or f"programme:{client_id}"
    latest = await db.plan_versions.find_one({"programme_id": programme_id}, {"_id": 0, "version": 1},
                                             sort=[("version", -1)])
    version_no = int((latest or {}).get("version") or 0) + 1

    snap_id = new_id()
    await db.plan_snapshots.insert_one({
        "id": snap_id, "programme_id": programme_id, "client_id": client_id,
        "scope": "batch_ready", "scope_ref": approved_ids,
        "workout_assignments_snapshot": approved_ids,
        "created_at": now_iso(),
    })
    version_id = new_id()
    await db.plan_versions.insert_one({
        "id": version_id, "programme_id": programme_id, "client_id": client_id,
        "version": version_no, "published_at": now_iso(), "published_by": coach["id"],
        "snapshot_id": snap_id, "supersedes_version_id": None,
        "approvals": [], "immutable": True,
    })
    ap_id = new_id()
    await db.approvals.insert_one({
        "id": ap_id, "programme_id": programme_id, "client_id": client_id,
        "draft_id": body.draft_id, "version_id": version_id,
        "scope": "batch_ready", "scope_ref": approved_ids,
        "include_change_set_ids": [],
        "notes": body.notes or "", "approved_by": coach["id"], "approved_at": now_iso(),
    })
    if prog:
        await db.programmes_v2.update_one({"id": prog["id"]},
                                            {"$set": {"live_plan_version": version_no, "updated_at": now_iso()}})

    await write_decision(
        actor="coach", layer="PUBLISH", scope_kind="plan_version", scope_id=version_id,
        client_id=client_id, outcome="APPLIED",
        reason=f"Batch Approve Ready ({body.month}): {len(approved_ids)} assignments → v{version_no}",
    )
    return {"approved_count": len(approved_ids), "version_id": version_id, "version": version_no,
             "approval_id": ap_id}


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap() -> None:
    await ensure_indexes("plan_snapshots", [
        ([("programme_id", 1)], False, "snap_prog"),
    ])
    await ensure_indexes("approvals", [
        ([("programme_id", 1)], False, "approvals_prog"),
    ])

bg(_bootstrap())


logger.info("feature_v2_coach_dashboard: /api/v2/coach/dashboard/* + /workspace/* registered")
