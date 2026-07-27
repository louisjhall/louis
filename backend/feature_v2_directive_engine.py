"""
feature_v2_directive_engine — the missing bridge between coach directives
and the V2 planner + change-set applier + roster-change detector.

Wires three previously-decorative pieces to the actual planning engine:

  1. `active_directives_for(client_id, date)` — returns coach_directives
     whose scope covers a given date. Consulted by P5/P6 at plan-build.
  2. `apply_change_set(cs)` — mutates a DRAFT assignment according to
     a `change_sets` row (move / edit_duration / lock / skip / convert_to_mobility).
     Marks the change_set `applied`. Idempotent.
  3. `apply_pending_change_sets_for(client_id, draft_id)` — walks all
     `status=proposed` change_sets for a draft and applies them in order.
  4. `emit_roster_change_exceptions(client_id, old_days, new_days)` —
     diffs classification/duty burden per date; emits an `exceptions` row
     (kind=roster_change) for each materially-changed date; also creates
     assignment-level change_sets so the applier picks them up.
  5. `write_assignment_decision(...)` — helper P5/P6 use to write a
     `decision_records` row with `scope_id=<assignment_id>` (fixes the
     empty "Why this?" drawer).

All are gated by their upstream feature flags (state_foundation +
scheduling_v2 + reality_v2). Nothing here touches V1.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from server import db, new_id, now_iso, logger
from feature_v2_common import write_decision


# ---------------------------------------------------------------------------
# 1. Directive resolution
# ---------------------------------------------------------------------------

async def _resolve_active_phase_id(client_id: str, on_date: _dt.date) -> Optional[str]:
    """Return the phase_id whose planned window covers `on_date`."""
    ph = await db.programme_phases_v2.find_one(
        {"client_id": client_id,
         "planned_start_date": {"$lte": on_date.isoformat()},
         "planned_end_date": {"$gte": on_date.isoformat()}},
        {"_id": 0, "id": 1},
    )
    return (ph or {}).get("id")


async def active_directives_for(client_id: str, on_date: _dt.date) -> list[dict]:
    """Return active `coach_directives` whose scope covers `on_date`."""
    rows = await db.coach_directives.find(
        {"client_id": client_id, "status": "active"}, {"_id": 0}
    ).to_list(200)
    today = _dt.date.today()
    week_end = today + _dt.timedelta(days=7)
    active_phase_id = None
    kept: list[dict] = []
    for d in rows:
        scope = (d.get("scope") or {})
        kind = scope.get("scope_kind") or "until_changed"
        if kind == "until_changed":
            kept.append(d); continue
        if kind == "today":
            if on_date == today:
                kept.append(d); continue
        elif kind == "this_week":
            if today <= on_date <= week_end:
                kept.append(d); continue
        elif kind == "custom":
            try:
                f = _dt.date.fromisoformat(scope.get("from_date") or "9999-01-01")
                t = _dt.date.fromisoformat(scope.get("to_date") or "0001-01-01")
                if f <= on_date <= t:
                    kept.append(d); continue
            except Exception:
                pass
        elif kind == "phase":
            # Resolve lazily then persist so we don't recompute
            phase_id = scope.get("phase_id")
            if not phase_id:
                if active_phase_id is None:
                    active_phase_id = await _resolve_active_phase_id(client_id, on_date)
                if active_phase_id:
                    await db.coach_directives.update_one(
                        {"id": d["id"]},
                        {"$set": {"scope.phase_id": active_phase_id, "updated_at": now_iso()}},
                    )
                    phase_id = active_phase_id
            if phase_id and phase_id == await _resolve_active_phase_id(client_id, on_date):
                kept.append(d); continue
        elif kind == "this_trip":
            # Best-effort: treat as this_week for now (trip resolution needs sector data)
            if today <= on_date <= week_end:
                kept.append(d); continue
    return kept


def directive_forbids_kind(directives: list[dict], objective_kind: Optional[str]) -> bool:
    """Return True if any active directive forbids `objective_kind`."""
    if not objective_kind:
        return False
    ok = objective_kind.lower()
    for d in directives:
        if d.get("kind") != "avoid_movement":
            continue
        pattern = ((d.get("parameters") or {}).get("pattern") or "").lower()
        if not pattern:
            # No specific pattern → assume "no running" if the free text mentions run
            txt = (d.get("free_text") or "").lower()
            if "run" in txt and ("run" in ok or ok.startswith("run") or ok.endswith("_run")):
                return True
            continue
        if pattern in ok or ok in pattern:
            return True
        # Family checks
        if pattern.startswith("gait_run") and ("run" in ok):
            return True
    return False


def directive_intensity_ceiling(directives: list[dict]) -> Optional[str]:
    """If a `limit_intensity` directive is active, return the RPE ceiling string
    (e.g. "rpe7"). Returns None if not present."""
    for d in directives:
        if d.get("kind") != "limit_intensity":
            continue
        amt = str(((d.get("parameters") or {}).get("amount") or "")).lower()
        if "rpe" in amt:
            # Best-effort parse — "max RPE 7" or "rpe 7"
            for tok in amt.replace("rpe", " ").split():
                tok = tok.strip(" .,;:")
                if tok.isdigit():
                    n = int(tok)
                    if 3 <= n <= 10:
                        return f"rpe{n}"
        # Fallback — treat any limit_intensity as rpe7 ceiling
        return "rpe7"
    return None


# ---------------------------------------------------------------------------
# 2/3. ChangeSet applier
# ---------------------------------------------------------------------------

async def apply_change_set(cs: dict) -> tuple[bool, str]:
    """Apply one change_set row to the DRAFT. Returns (applied, reason)."""
    if cs.get("status") not in ("proposed", None):
        return (False, f"skip status={cs.get('status')}")
    kind = cs.get("kind")
    after = cs.get("after_snapshot") or {}
    scope_ids = cs.get("scope_assignment_ids") or []
    client_id = cs.get("client_id")

    # Resolve the target assignment (if provided)
    aid = scope_ids[0] if scope_ids else after.get("assignment_id")
    assignment = None
    if aid:
        assignment = await db.workout_assignments.find_one(
            {"id": aid, "client_id": client_id}, {"_id": 0}
        )
    if not assignment and kind not in ("coach_directive_applied", "exposure_deferred"):
        await _mark_cs(cs, "rejected", "assignment not found")
        return (False, "assignment not found")
    if assignment and assignment.get("locked"):
        await _mark_cs(cs, "rejected", "assignment locked")
        return (False, "assignment locked")

    if kind == "assignment_moved":
        new_date = after.get("new_date") or after.get("target_date")
        if not new_date:
            await _mark_cs(cs, "rejected", "no new_date")
            return (False, "no new_date")
        sd = await db.schedule_days.find_one({"client_id": client_id, "date": new_date}, {"_id": 0})
        if not sd:
            await _mark_cs(cs, "rejected", f"no schedule_day for {new_date}")
            return (False, "no schedule_day")
        await db.workout_assignments.update_one(
            {"id": assignment["id"]},
            {"$set": {"date": new_date, "schedule_day_id": sd["id"], "updated_at": now_iso()}},
        )
        await write_decision(
            actor="system", layer="WHEN", scope_kind="assignment", scope_id=assignment["id"],
            client_id=client_id, outcome="APPLIED",
            reason=f"ChangeSet {cs['id']} moved assignment {assignment.get('date')} → {new_date}",
            rule_or_prompt={"id": "change_set_applier", "kind": "engine", "version": "1"},
        )
        await _mark_cs(cs, "applied", f"moved to {new_date}")
        return (True, f"moved to {new_date}")

    if kind == "implementation_changed":
        # For duration_min override / convert_to_mobility we shortcut through P7 flow
        target_min = after.get("duration_min_new") or after.get("duration_min_override")
        if target_min:
            await db.workout_assignments.update_one(
                {"id": assignment["id"]},
                {"$set": {"planned_duration_min": int(target_min), "updated_at": now_iso()}},
            )
        if after.get("convert_to_mobility") or after.get("convert_to_recovery"):
            # Mark the assignment needs a rebuild (P6 will pick up via draft_implementation_id=None)
            await db.workout_assignments.update_one(
                {"id": assignment["id"]},
                {"$set": {"draft_implementation_id": None, "updated_at": now_iso()}},
            )
        await write_decision(
            actor="system", layer="HOW", scope_kind="assignment", scope_id=assignment["id"],
            client_id=client_id, outcome="APPLIED",
            reason=f"ChangeSet {cs['id']} implementation change: "
                    + (f"duration→{target_min}min" if target_min else "")
                    + (" · convert-to-mobility" if after.get("convert_to_mobility") else "")
                    + (" · convert-to-recovery" if after.get("convert_to_recovery") else ""),
            rule_or_prompt={"id": "change_set_applier", "kind": "engine", "version": "1"},
        )
        await _mark_cs(cs, "applied", "impl updated")
        return (True, "impl updated")

    if kind == "exposure_deferred":
        # Skip session — mark assignment as skipped and defer the exposure
        await db.workout_assignments.update_one(
            {"id": assignment["id"]}, {"$set": {"status": "skipped", "updated_at": now_iso()}}
        )
        await db.objective_exposures.update_one(
            {"assignment_id": assignment["id"]},
            {"$set": {"status": "deferred", "assignment_id": None, "updated_at": now_iso()}},
        )
        await write_decision(
            actor="system", layer="WHEN", scope_kind="assignment", scope_id=assignment["id"],
            client_id=client_id, outcome="APPLIED",
            reason=f"ChangeSet {cs['id']} skipped session; exposure deferred",
            rule_or_prompt={"id": "change_set_applier", "kind": "engine", "version": "1"},
        )
        await _mark_cs(cs, "applied", "deferred")
        return (True, "deferred")

    if kind == "coach_directive_applied":
        # Directive was already persisted separately by command-bar apply.
        await _mark_cs(cs, "applied", "directive persisted")
        return (True, "directive persisted")

    await _mark_cs(cs, "rejected", f"unknown kind {kind}")
    return (False, f"unknown kind {kind}")


async def _mark_cs(cs: dict, status: str, reason: str) -> None:
    await db.change_sets.update_one(
        {"id": cs["id"]},
        {"$set": {"status": status, "applied_at": now_iso(),
                   "application_reason": reason}},
    )


async def apply_pending_change_sets_for(client_id: str, draft_id: Optional[str] = None) -> dict:
    q: dict = {"client_id": client_id, "status": "proposed"}
    if draft_id:
        q["draft_id"] = draft_id
    rows = await db.change_sets.find(q, {"_id": 0}).sort("created_at", 1).to_list(500)
    applied, rejected = 0, 0
    for cs in rows:
        ok, _ = await apply_change_set(cs)
        if ok: applied += 1
        else:  rejected += 1
    return {"applied": applied, "rejected": rejected, "seen": len(rows)}


# ---------------------------------------------------------------------------
# 4. Roster change detection
# ---------------------------------------------------------------------------

async def emit_roster_change_exceptions(
    client_id: str, prior_days: dict[str, dict], new_days: dict[str, dict]
) -> int:
    """Diff (date → derived) maps; emit an exceptions row for each date whose
    classification or duty_burden materially changed. Returns count."""
    changed = 0
    all_dates = set(prior_days) | set(new_days)
    for d in sorted(all_dates):
        old = (prior_days.get(d) or {}).get("derived") or {}
        new = (new_days.get(d) or {}).get("derived") or {}
        if not old and not new:
            continue
        material = (
            old.get("classification") != new.get("classification")
            or old.get("duty_burden_band") != new.get("duty_burden_band")
        )
        if not material:
            continue
        old_desc = old.get("classification") or "—"
        new_desc = new.get("classification") or "—"
        await db.exceptions.insert_one({
            "id": new_id(),
            "client_id": client_id,
            "kind": "roster_change",
            "severity": "warning",
            "scope_ref": d,
            "triggered_at": now_iso(),
            "human_readable_reason": f"Roster changed on {d}: {old_desc} → {new_desc}",
            "status": "open",
            "proposed_resolutions": [],
        })
        # If there is an existing assignment on that date, emit a change_set so
        # the applier reconsiders it.
        aa = await db.workout_assignments.find_one(
            {"client_id": client_id, "date": d,
             "status": {"$in": ["proposed", "ready", "live"]}}, {"_id": 0}
        )
        if aa and not aa.get("locked"):
            await db.change_sets.insert_one({
                "id": new_id(), "draft_id": aa.get("draft_id"),
                "client_id": client_id, "kind": "implementation_changed",
                "scope_assignment_ids": [aa["id"]],
                "before_snapshot": {"classification": old_desc},
                "after_snapshot": {"classification": new_desc,
                                    "duration_min_override": None,
                                    "convert_to_mobility": new_desc in ("layover_departure", "layover_arrival"),
                                    "note": f"roster changed to {new_desc}"},
                "triggered_by": "roster_change",
                "triggered_event_id": None,
                "proposed_by": "system",
                "status": "proposed",
                "human_readable_summary": f"{d}: adjust to fit new duty ({new_desc})",
                "created_at": now_iso(),
            })
        changed += 1
    return changed


# ---------------------------------------------------------------------------
# 5. Assignment-scoped decision helper (fixes "Why this?" empty drawer)
# ---------------------------------------------------------------------------

async def write_assignment_decision(
    *, assignment_id: str, client_id: str, reason: str,
    layer: str = "WHEN", outcome: str = "APPLIED",
    rule_id: str = "planner_v1",
) -> str:
    return await write_decision(
        actor="system", layer=layer, scope_kind="assignment", scope_id=assignment_id,
        client_id=client_id, outcome=outcome, reason=reason,
        rule_or_prompt={"id": rule_id, "kind": "engine", "version": "1"},
    )


logger.info("feature_v2_directive_engine: directive resolver + change-set applier + roster-change emitter loaded")
