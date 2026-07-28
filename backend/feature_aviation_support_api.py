"""
feature_aviation_support_api — Phase B endpoints
================================================

Coach + client control surface for the Aviation Support layer (Phase A).

Contract:
- Coach endpoints require role=coach.
- Client endpoints require role=client (own data).
- NO endpoint mutates Engine V2 (no plan_live_v2 / plan_drafts_v2 /
  workouts / workout_implementations writes anywhere in this module).
- Overrides live in `db.flight_support_overrides`.
- Client completion status lives in `db.flight_support_activity`.
- All override + completion records carry `client_id + date + protocol_key`
  so re-computation is idempotent (roster changes re-derive; overrides
  are looked up by the same (date, protocol_key) tuple).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Depends, Query, Body
from pydantic import BaseModel, Field

# Imports that must succeed once the module is loaded by server.py
from server import api, db, current_user, require_role
from feature_aviation_support import (
    PROTOCOLS,
    get_flight_support_by_date,
    summarise_training_by_date_from_workouts,
    resolve_aviation_role,
    select_interventions_for_day,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _load_client_for_coach(coach: dict, client_id: str) -> dict:
    client = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "Client not found.")
    if client.get("role") not in ("client",) and not client.get("client_of"):
        # Ensure this is genuinely a client account — never let a coach
        # write overrides on another coach's profile.
        raise HTTPException(400, "Target user is not a client.")
    return client


async def _roster_days_between(user_id: str, d_from: str, d_to: str) -> dict[str, dict]:
    """Small dedup of feature_calendar_recovery._roster_days_between — kept
    local so this file doesn't reach across the module boundary for one
    private helper."""
    days: dict[str, dict] = {}
    async for r in db.rosters.find(
        {"user_id": user_id, "is_active": True, "confirmed": True},
        {"_id": 0, "days": 1},
    ):
        for d in r.get("days") or []:
            ds = str(d.get("date") or "")[:10]
            if not ds:
                continue
            if d_from <= ds <= d_to:
                days[ds] = d
    return days


async def _training_by_date_between(user_id: str, d_from: str, d_to: str) -> dict[str, dict]:
    """Aggregate legacy V1 workouts + V2 synth rows into a per-date summary
    the aviation selector can consume."""
    rows: list[dict] = []
    async for w in db.workouts.find(
        {"user_id": user_id, "date": {"$gte": d_from, "$lte": d_to}},
        {"_id": 0, "date": 1, "title": 1, "focus": 1, "day_load": 1,
         "key_session": 1},
    ):
        rows.append(w)
    try:
        from feature_v2_client_bridge import synth_workouts_for_user
        v2_rows = await synth_workouts_for_user(
            db, user_id, start_iso=d_from, end_iso=d_to,
        )
        for r in v2_rows:
            rows.append(r)
    except Exception:
        pass
    return summarise_training_by_date_from_workouts(rows)


async def _flight_support_for_range(user_id: str, d_from: str, d_to: str) -> dict[str, list[dict]]:
    roster_days = await _roster_days_between(user_id, d_from, d_to)
    training = await _training_by_date_between(user_id, d_from, d_to)
    return await get_flight_support_by_date(
        db, user_id, roster_days, training,
    )


def _bundle_interventions(items: list[dict]) -> list[dict]:
    """Collapse interventions sharing the same `bundle_key` into one row so
    the client sees "Arrival Reset · 15 min" instead of two rows. Preserves
    a `sub_interventions` list for the expand-detail view."""
    if not items:
        return []
    buckets: dict[str, list[dict]] = {}
    solo: list[dict] = []
    for it in items:
        bk = it.get("bundle_key")
        if bk:
            buckets.setdefault(bk, []).append(it)
        else:
            solo.append(it)
    out: list[dict] = list(solo)
    for bk, group in buckets.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        first = group[0]
        total = sum(int(i.get("duration_min") or 0) for i in group)
        families = sorted({i.get("family") for i in group if i.get("family")})
        reasons = [i.get("trigger_reason") for i in group if i.get("trigger_reason")]
        out.append({
            "id": f"{bk}:bundle",
            "date": first.get("date"),
            "protocol_key": "bundle",
            "role": first.get("role"),
            "title": first.get("bundle_title") or "Support Reset",
            "family": "reset" if len(families) > 1 else (families[0] if families else "reset"),
            "intensity": "low",
            "duration_min": total,
            "cues": [
                f"{'+'.join([str(i.get('title')) for i in group])}"
                " — flow through both in order.",
            ],
            "equipment": sorted({
                e for i in group for e in (i.get("equipment") or [])
            }),
            "blocks": [
                {"name": (i.get("title") or ""), "duration_min": i.get("duration_min"),
                 "cue": (i.get("cues") or [""])[0] if i.get("cues") else ""}
                for i in group
            ],
            "bundle_key": bk,
            "bundle_title": first.get("bundle_title"),
            "sub_interventions": [i for i in group],
            "trigger_reason": "  ·  ".join(reasons),
            "is_flight_support": True,
            "is_bundle": True,
        })
    # Preserve chronological (all same date so nothing to sort) but keep
    # bundles first for visual anchoring.
    out.sort(key=lambda x: (0 if x.get("is_bundle") else 1))
    return out


async def _apply_completions(user_id: str, items: list[dict]) -> list[dict]:
    """Attach `completion_status` / `completed_at` per intervention id from
    `db.flight_support_activity`. Bundle IDs pool their children states.

    Also propagates completion state into `sub_interventions[]` so the
    expandable bundle view can show per-child ticks in the UI.
    """
    if not items:
        return items
    ids = []
    for it in items:
        ids.append(it["id"])
        for sub in (it.get("sub_interventions") or []):
            ids.append(sub["id"])
    activities: dict[str, dict] = {}
    async for a in db.flight_support_activity.find(
        {"user_id": user_id, "intervention_id": {"$in": ids}}, {"_id": 0},
    ):
        activities[a["intervention_id"]] = a
    for it in items:
        act = activities.get(it["id"])
        if act:
            it["completion_status"] = act.get("status")
            it["completed_at"] = act.get("completed_at")
            it["skip_reason"] = act.get("skip_reason")
        else:
            it["completion_status"] = "not_started"
        # Mirror onto sub_interventions
        for sub in (it.get("sub_interventions") or []):
            sub_act = activities.get(sub["id"])
            if sub_act:
                sub["completion_status"] = sub_act.get("status")
                sub["completed_at"] = sub_act.get("completed_at")
                sub["skip_reason"] = sub_act.get("skip_reason")
            else:
                sub["completion_status"] = "not_started"
        # For bundles: derive an aggregate state from children when the
        # bundle itself hasn't been marked directly.
        if it.get("is_bundle"):
            child_states = [
                (activities.get(s["id"]) or {}).get("status") or "not_started"
                for s in it.get("sub_interventions") or []
            ]
            bundle_direct = activities.get(it["id"])
            if not bundle_direct:
                if child_states and all(s == "completed" for s in child_states):
                    it["completion_status"] = "completed"
                elif any(s == "completed" for s in child_states):
                    it["completion_status"] = "partial"
                elif child_states and all(s == "skipped" for s in child_states):
                    it["completion_status"] = "skipped"
    return items


# ---------------------------------------------------------------------------
# COACH endpoints
# ---------------------------------------------------------------------------

@api.get("/v2/coach/protocols/flight-support")
async def coach_list_protocols(
    role: str = Query("pilot"),
    coach: dict = Depends(require_role("coach")),
) -> dict:
    role = (role or "pilot").lower()
    out = []
    for k, p in PROTOCOLS.items():
        if p.role != role:
            continue
        out.append({
            "key": p.key, "title": p.display_title,
            "family": p.family, "intensity": p.intensity,
            "duration_min": p.duration_min,
            "duration_range": list(p.duration_range),
            "cues": p.cues, "equipment": p.equipment,
        })
    return {"protocols": out, "role": role}


@api.get("/v2/coach/clients/{client_id}/flight-support")
async def coach_list_flight_support(
    client_id: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return flight support (with completion state + overrides) for a
    client over a date range. Read-only. Includes derived role status so
    coach can see 'Aviation role required' if ambiguous."""
    client = await _load_client_for_coach(coach, client_id)
    role = resolve_aviation_role(client)
    by_date = await _flight_support_for_range(client_id, from_date, to_date)
    # Bundle + hydrate completion per date
    out: dict[str, list[dict]] = {}
    for d, items in by_date.items():
        bundled = _bundle_interventions(items)
        bundled = await _apply_completions(client_id, bundled)
        out[d] = bundled
    disabled_globally = bool(
        (client.get("profile") or {}).get("flight_support", {}).get("disabled")
    )
    return {
        "client_id": client_id,
        "role": role,
        "role_status": ("ok" if role in ("pilot", "cabin_crew") else "role_unknown"),
        "auto_flight_support_enabled": not disabled_globally,
        "range": {"from": from_date, "to": to_date},
        "days": out,
    }


class OverrideBody(BaseModel):
    date: str = Field(..., description="ISO date YYYY-MM-DD")
    action: str = Field(..., description=(
        "disable | replace | custom | add_custom | disable_day"
    ))
    protocol_key: Optional[str] = Field(
        None, description="Original protocol key targeted by this override "
                          "(required for disable / replace / custom)."
    )
    intervention_id: Optional[str] = Field(
        None, description="Original intervention id (alternative selector)."
    )
    replace_key: Optional[str] = None
    custom_intervention: Optional[dict] = None
    reason: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/flight-support/override")
async def coach_apply_override(
    client_id: str,
    body: OverrideBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    _ = await _load_client_for_coach(coach, client_id)

    action = body.action.strip().lower()
    if action not in ("disable", "replace", "custom", "add_custom", "disable_day"):
        raise HTTPException(400, f"Unknown action: {action}")

    if action in ("disable", "replace", "custom") and not (
        body.protocol_key or body.intervention_id
    ):
        raise HTTPException(
            400, "protocol_key or intervention_id required for this action.",
        )
    if action == "replace":
        if not body.replace_key or body.replace_key not in PROTOCOLS:
            raise HTTPException(400, "replace_key must be a known protocol.")
    if action in ("custom", "add_custom"):
        ci = body.custom_intervention or {}
        if not ci.get("title") or not (ci.get("duration_min") or 0):
            raise HTTPException(
                400,
                "custom_intervention.title and duration_min are required.",
            )
        # Safety §7 — custom support must NEVER be storeable in a shape
        # that Engine V2 could pick up.
        ci["is_flight_support"] = True
        ci.pop("exposure_id", None)
        ci.pop("objective_id", None)

    override_doc = {
        "id": str(uuid.uuid4()),
        "user_id": client_id,
        "date": body.date,
        "action": action,
        "protocol_key": body.protocol_key,
        "intervention_id": body.intervention_id,
        "replace_key": body.replace_key,
        "custom_intervention": body.custom_intervention,
        "reason": body.reason,
        "coach_id": coach.get("id"),
        "created_at": _now(),
    }

    # Idempotency: replace/disable/custom on same (date, protocol_key) — one
    # active row wins. add_custom is additive, so no dedup.
    if action != "add_custom":
        query = {
            "user_id": client_id,
            "date": body.date,
            "action": action,
        }
        if body.protocol_key:
            query["protocol_key"] = body.protocol_key
        elif body.intervention_id:
            query["intervention_id"] = body.intervention_id
        await db.flight_support_overrides.delete_many(query)

    await db.flight_support_overrides.insert_one(override_doc)
    return {"ok": True, "override": {k: v for k, v in override_doc.items() if k != "_id"}}


class RemoveOverrideBody(BaseModel):
    override_id: Optional[str] = None
    date: Optional[str] = None
    protocol_key: Optional[str] = None


@api.post("/v2/coach/clients/{client_id}/flight-support/override/remove")
async def coach_remove_override(
    client_id: str,
    body: RemoveOverrideBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    _ = await _load_client_for_coach(coach, client_id)
    query = {"user_id": client_id}
    if body.override_id:
        query["id"] = body.override_id
    else:
        if not body.date:
            raise HTTPException(400, "override_id or date required.")
        query["date"] = body.date
        if body.protocol_key:
            query["protocol_key"] = body.protocol_key
    res = await db.flight_support_overrides.delete_many(query)
    return {"ok": True, "removed": res.deleted_count}


class ClientGlobalToggleBody(BaseModel):
    enabled: bool


@api.post("/v2/coach/clients/{client_id}/flight-support/toggle")
async def coach_toggle_flight_support(
    client_id: str,
    body: ClientGlobalToggleBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Global on/off switch for automatic Flight Support for one client."""
    _ = await _load_client_for_coach(coach, client_id)
    await db.users.update_one(
        {"id": client_id},
        {"$set": {"profile.flight_support.disabled": (not body.enabled),
                  "profile.flight_support.updated_at": _now(),
                  "profile.flight_support.updated_by": coach.get("id")}},
    )
    return {"ok": True, "enabled": body.enabled}


# ---------------------------------------------------------------------------
# CLIENT endpoints
# ---------------------------------------------------------------------------

@api.get("/client/flight-support")
async def client_list_flight_support(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    user: dict = Depends(current_user),
) -> dict:
    """Client view of flight support over a range (defaults to today +14)."""
    from datetime import date, timedelta
    if not from_date:
        from_date = date.today().isoformat()
    if not to_date:
        to_date = (date.fromisoformat(from_date) + timedelta(days=14)).isoformat()
    role = resolve_aviation_role(user)
    by_date = await _flight_support_for_range(user["id"], from_date, to_date)
    out: dict[str, list[dict]] = {}
    for d, items in by_date.items():
        bundled = _bundle_interventions(items)
        bundled = await _apply_completions(user["id"], bundled)
        out[d] = bundled
    return {
        "user_id": user["id"], "role": role,
        "range": {"from": from_date, "to": to_date},
        "days": out,
    }


@api.get("/client/today")
async def client_today(
    user: dict = Depends(current_user),
) -> dict:
    """Aggregate client Today snapshot: Training + Flight Support + Roster.

    Zero mutations. Composed at read-time from:
      - Engine V2 Live plan (via feature_v2_client_bridge) OR
        legacy `db.workouts` (V1 clients)
      - Confirmed roster day for today
      - Flight support selector (deterministic)
      - Completion status from `flight_support_activity`
    """
    from datetime import date, datetime
    today_iso = date.today().isoformat()

    # --- Training (V2 first, fall back to V1)
    training: list[dict] = []
    try:
        from feature_v2_client_bridge import synth_workouts_for_user
        v2 = await synth_workouts_for_user(
            db, user["id"], start_iso=today_iso, end_iso=today_iso,
        )
        for w in v2:
            training.append(w)
    except Exception:
        pass
    if not training:
        async for w in db.workouts.find(
            {"user_id": user["id"], "date": today_iso}, {"_id": 0},
        ):
            training.append(w)

    # --- Roster context
    roster_days = await _roster_days_between(user["id"], today_iso, today_iso)
    roster_today = roster_days.get(today_iso)

    # --- Flight Support (deterministic + overrides + completion)
    training_summary = summarise_training_by_date_from_workouts(training)
    fs = await get_flight_support_by_date(
        db, user["id"], roster_days, training_summary,
    )
    fs_today = _bundle_interventions(fs.get(today_iso, []))
    fs_today = await _apply_completions(user["id"], fs_today)

    role = resolve_aviation_role(user)
    disabled_globally = bool(
        (user.get("profile") or {}).get("flight_support", {}).get("disabled")
    )

    # --- Classification badges the UI can render
    is_rest_from_training = len(training) == 0
    has_flight_support = len(fs_today) > 0

    return {
        "date": today_iso,
        "user_id": user["id"],
        "role": role,
        "auto_flight_support_enabled": not disabled_globally,
        "roster_day": roster_today,
        "training": {
            "is_rest": is_rest_from_training,
            "workouts": training,
        },
        "flight_support": fs_today,
        "labels": {
            "training_state": (
                "rest_day" if is_rest_from_training else "session_planned"
            ),
            "flight_support_state": (
                "present" if has_flight_support
                else ("disabled" if disabled_globally else "none")
            ),
        },
    }


class CompletionBody(BaseModel):
    intervention_id: str = Field(..., description="Full intervention id or "
                                                    "bundle id.")
    status: str = Field(..., description="completed | skipped | not_started")
    skip_reason: Optional[str] = None
    date: Optional[str] = None
    protocol_key: Optional[str] = None
    duration_min: Optional[int] = None


@api.post("/client/flight-support/complete")
async def client_mark_completion(
    body: CompletionBody,
    user: dict = Depends(current_user),
) -> dict:
    """Record a completion / skip against a flight-support intervention.

    §13: This is completely separate from workout completion. A skipped
    Flight Support MUST NOT create a missed_workout event, alter training
    adherence, or trigger missed-session rescheduling.
    """
    status = body.status.strip().lower()
    if status not in ("completed", "skipped", "not_started"):
        raise HTTPException(400, "status must be completed | skipped | not_started")

    # Handle bundle IDs (fs:<date>:bundle:...) — write children too so
    # both bundle-level and per-child queries see the state.
    is_bundle = body.intervention_id.endswith(":bundle")

    def _extract_date(iid: str) -> Optional[str]:
        # id shape: fs:<date>:<key>[:idx] or bundle:<label>:<date>:bundle
        parts = iid.split(":")
        if len(parts) >= 2 and parts[0] == "fs":
            return parts[1]
        if is_bundle and len(parts) >= 3:
            return parts[2]
        return None

    resolved_date = body.date or _extract_date(body.intervention_id)

    activity_doc = {
        "user_id": user["id"],
        "intervention_id": body.intervention_id,
        "protocol_key": body.protocol_key,
        "status": status,
        "skip_reason": body.skip_reason if status == "skipped" else None,
        "completed_at": _now() if status == "completed" else None,
        "duration_min": body.duration_min,
        "date": resolved_date,
        "updated_at": _now(),
        # Explicit isolation marker so consumers of the activity log
        # (analytics / adherence) can filter out flight support easily.
        "is_flight_support": True,
    }
    await db.flight_support_activity.update_one(
        {"user_id": user["id"], "intervention_id": body.intervention_id},
        {"$set": activity_doc,
         "$setOnInsert": {"id": str(uuid.uuid4()),
                          "created_at": _now()}},
        upsert=True,
    )

    # If a bundle was updated, mirror the state onto each child so both
    # views (aggregate + expanded) stay consistent.
    if is_bundle and resolved_date:
        # Recompute the child interventions for this date to know their ids
        roster_days = await _roster_days_between(user["id"], resolved_date, resolved_date)
        training_summary = await _training_by_date_between(user["id"], resolved_date, resolved_date)
        fs = await get_flight_support_by_date(
            db, user["id"], roster_days, training_summary,
        )
        # Find matching bundle
        parent_bk = body.intervention_id.rsplit(":", 1)[0]  # strip :bundle
        for it in fs.get(resolved_date, []):
            if it.get("bundle_key") == parent_bk:
                child_doc = {
                    **activity_doc,
                    "intervention_id": it["id"],
                    "protocol_key": it.get("protocol_key"),
                    "duration_min": it.get("duration_min"),
                }
                await db.flight_support_activity.update_one(
                    {"user_id": user["id"], "intervention_id": it["id"]},
                    {"$set": child_doc,
                     "$setOnInsert": {"id": str(uuid.uuid4()),
                                      "created_at": _now()}},
                    upsert=True,
                )

    return {"ok": True, "status": status,
            "intervention_id": body.intervention_id}


# ---------------------------------------------------------------------------
# Roster-change reconciliation hook (§15/§16)
# ---------------------------------------------------------------------------

async def reconcile_overrides_after_roster_change(
    user_id: str, changed_dates: list[str],
) -> dict:
    """Called when a roster confirms / re-parses. Applies deterministic
    reconciliation:

    - For each changed date, recompute the deterministic protocol set.
    - If an override targeted a protocol that is NO LONGER selected on
      that date, mark it as `stale: true` in the override doc (audit
      trail) rather than deleting. This surfaces a coach-visible flag
      without silently dropping their work.
    - Overrides with `action=add_custom` are always preserved (they are
      coach-added, not tied to a deterministic protocol).

    Returns: {reconciled_dates, stale_overrides}
    """
    if not changed_dates:
        return {"reconciled_dates": 0, "stale_overrides": 0}

    d_from, d_to = min(changed_dates), max(changed_dates)
    roster_days = await _roster_days_between(user_id, d_from, d_to)
    training = await _training_by_date_between(user_id, d_from, d_to)

    # Recompute the set of (date, protocol_key) pairs that WOULD be
    # selected right now.
    active_set: set[tuple[str, str]] = set()
    for d in changed_dates:
        rd = roster_days.get(d)
        if not rd:
            continue
        for it in select_interventions_for_day(
            role="pilot",  # role_unknown branch will yield [] anyway
            roster_day=rd,
            date=d,
            has_training_today=(d in training),
            training_intensity=(training.get(d) or {}).get("intensity"),
        ):
            active_set.add((d, it.protocol_key))

    stale_count = 0
    async for ov in db.flight_support_overrides.find(
        {"user_id": user_id, "date": {"$in": changed_dates},
         "action": {"$in": ["disable", "replace", "custom"]}},
        {"_id": 0, "id": 1, "date": 1, "protocol_key": 1, "stale": 1},
    ):
        pkey = ov.get("protocol_key")
        d = ov.get("date")
        if pkey and (d, pkey) not in active_set:
            await db.flight_support_overrides.update_one(
                {"id": ov["id"]},
                {"$set": {"stale": True, "stale_at": _now(),
                          "stale_reason": "roster_change"}},
            )
            stale_count += 1
        elif ov.get("stale"):
            # Recovered — the protocol is selected again after the roster
            # change was reverted.
            await db.flight_support_overrides.update_one(
                {"id": ov["id"]},
                {"$set": {"stale": False},
                 "$unset": {"stale_at": "", "stale_reason": ""}},
            )
    return {"reconciled_dates": len(changed_dates),
            "stale_overrides": stale_count}


__all__ = [
    "reconcile_overrides_after_roster_change",
]
