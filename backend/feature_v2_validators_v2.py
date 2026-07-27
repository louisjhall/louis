"""
CrewFit V2 Engine V2 — Programme + Session Validators
======================================================

Programme cannot go READY until every invariant passes. Session cannot go
READY until every session-scoped invariant passes.

Public API:

    validate_session(session_spec, placement, day_ctx, restrictions)
        → SessionValidation

    validate_programme(demand, placements, session_specs, phase, goal)
        → ProgrammeValidation

Both return (ok, issues[]) where each issue has {code, severity, message}.
Severity: "error" (blocks READY) | "warning" (surface but non-blocking).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Optional

from feature_v2_sport_configs import (
    GoalConfig, PhaseSpec, session_kind_meta, is_key_intensity,
    session_family, is_forbidden_sequence,
)
from feature_v2_sequencing import Placement, PlacementPlan, week_key
from feature_v2_demand_v2 import DemandPlan, Unfilled


@dataclass
class Issue:
    code: str
    severity: str        # "error" | "warning"
    message: str
    scope: str = ""      # session_id / programme / phase


@dataclass
class SessionValidation:
    ok: bool
    issues: list[Issue] = field(default_factory=list)


@dataclass
class ProgrammeValidation:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    quota_report: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session validators
# ---------------------------------------------------------------------------

def validate_session(session_spec: dict, placement: Placement,
                     day_ctx_available_time: int,
                     restrictions: set[str]) -> SessionValidation:
    issues: list[Issue] = []
    if session_spec.get("spec_kind") == "unbuildable":
        issues.append(Issue("session_unbuildable", "error",
                            session_spec.get("review_reason") or "unbuildable"))
    dur = int(session_spec.get("duration_min") or 0)
    if dur <= 0 and placement.kind != "rest":
        issues.append(Issue("zero_duration", "error", "Duration must be > 0 for non-rest sessions"))
    if placement.kind != "rest" and dur > day_ctx_available_time:
        issues.append(Issue("duration_exceeds_availability", "warning",
                            f"Duration {dur} > available {day_ctx_available_time}"))
    if placement.kind != "rest":
        payload = session_spec.get("payload") or {}
        sk = session_spec.get("spec_kind")
        if sk == "running" and not payload.get("main"):
            issues.append(Issue("empty_running_main", "error", "Running session missing main block"))
        if sk == "strength" and not payload.get("exercises"):
            issues.append(Issue("empty_strength", "error", "Strength session has no exercises"))
        if sk in ("mobility", "recovery", "travel_recovery", "activation") and not payload.get("flow_blocks"):
            issues.append(Issue("empty_flow", "error", f"{sk} has no flow blocks"))
        if sk == "brick" and not payload.get("segments"):
            issues.append(Issue("empty_brick", "error", "Brick has no segments"))
    # Restriction check
    if restrictions:
        used = " ".join(session_spec.get("equipment_used") or []).lower()
        rationale = (session_spec.get("rationale") or "").lower()
        for r in restrictions:
            r = r.lower()
            if r and (r in used or r in rationale):
                issues.append(Issue("restriction_conflict", "warning",
                                    f"Session references restricted region '{r}'"))
    ok = not any(i.severity == "error" for i in issues)
    return SessionValidation(ok=ok, issues=issues)


# ---------------------------------------------------------------------------
# Programme validators
# ---------------------------------------------------------------------------

def validate_programme(
    demand: DemandPlan,
    placements: list[Placement],
    phase: PhaseSpec,
    goal: GoalConfig,
    unfilled: list[Unfilled],
) -> ProgrammeValidation:
    """Enforce programme-level invariants:
       * KEY objectives not silently missing
       * no duplicate exposures on same day
       * no more than key/hard cap per week
       * no forbidden sequence in placements
       * exposure numbering monotonic per objective_id
       * progression coherent (target durations within bounds)
    """
    issues: list[Issue] = []

    # ---- Quota report ------------------------------------------------------
    placed_by_kind: dict[str, int] = {}
    for p in placements:
        placed_by_kind[p.kind] = placed_by_kind.get(p.kind, 0) + 1
    required_by_kind: dict[str, int] = {}
    key_required_by_kind: dict[str, int] = {}
    for e in demand.required_exposures:
        required_by_kind[e.kind] = required_by_kind.get(e.kind, 0) + 1
        if e.priority.upper() == "KEY":
            key_required_by_kind[e.kind] = key_required_by_kind.get(e.kind, 0) + 1

    unfilled_key: list[str] = []
    for u in unfilled:
        if u.priority.upper() == "KEY":
            unfilled_key.append(f"{u.kind} ({u.reason_code})")
            issues.append(Issue("key_unfilled", "error",
                                f"KEY {u.kind} could not be placed — {u.human_reason}"))

    # ---- No forbidden sequences in the placement list --------------------
    for i, p in enumerate(placements):
        for j in range(i + 1, len(placements)):
            q = placements[j]
            if abs((q.date - p.date).days) > 1:
                continue
            if q.date == p.date + _dt.timedelta(days=1):
                if is_forbidden_sequence(p.kind, q.kind, goal.key):
                    issues.append(Issue("forbidden_sequence", "error",
                                        f"{p.kind}@{p.date} → {q.kind}@{q.date} forbidden"))
            elif p.date == q.date + _dt.timedelta(days=1):
                if is_forbidden_sequence(q.kind, p.kind, goal.key):
                    issues.append(Issue("forbidden_sequence", "error",
                                        f"{q.kind}@{q.date} → {p.kind}@{p.date} forbidden"))

    # ---- Weekly hard/key caps --------------------------------------------
    weekly_hard: dict[tuple[int, int], int] = {}
    weekly_key: dict[tuple[int, int], int] = {}
    for p in placements:
        wk = week_key(p.date)
        meta = session_kind_meta(p.kind)
        if meta.get("hard"):
            weekly_hard[wk] = weekly_hard.get(wk, 0) + 1
        if p.key:
            weekly_key[wk] = weekly_key.get(wk, 0) + 1
    for wk, n in weekly_hard.items():
        if n > phase.hard_days_per_week_max:
            issues.append(Issue("weekly_hard_cap_exceeded", "error",
                                f"Week {wk}: {n} hard sessions > {phase.hard_days_per_week_max}"))
    for wk, n in weekly_key.items():
        if n > phase.key_days_per_week_max:
            issues.append(Issue("weekly_key_cap_exceeded", "error",
                                f"Week {wk}: {n} key sessions > {phase.key_days_per_week_max}"))

    # ---- Consecutive training days ----------------------------------------
    if placements:
        dates_sorted = sorted({p.date for p in placements})
        streak = 1
        max_streak = 1
        for i in range(1, len(dates_sorted)):
            if (dates_sorted[i] - dates_sorted[i - 1]).days == 1:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 1
        if max_streak > phase.consecutive_training_days_max:
            issues.append(Issue("consecutive_days_exceeded", "warning",
                                f"Max streak {max_streak} > cap {phase.consecutive_training_days_max}"))

    # ---- Exposure identity: monotonic per objective_id --------------------
    per_obj: dict[str, list[int]] = {}
    for p in placements:
        per_obj.setdefault(p.objective_id, []).append(p.exposure_number)
    for obj_id, seq in per_obj.items():
        sorted_seq = sorted(seq)
        if sorted_seq != list(range(1, len(sorted_seq) + 1)):
            issues.append(Issue("exposure_numbering", "warning",
                                f"Objective {obj_id} exposure numbers not monotonic: {sorted_seq}"))

    # ---- No two placements on same date with same family ------------------
    seen_family_by_date: dict[tuple[str, _dt.date], str] = {}
    for p in placements:
        key = (session_family(p.kind), p.date)
        if key in seen_family_by_date:
            issues.append(Issue("same_day_family_duplicate", "warning",
                                f"{p.kind} and {seen_family_by_date[key]} same family on {p.date}"))
        else:
            seen_family_by_date[key] = p.kind

    # ---- Report -----------------------------------------------------------
    quota_report = {
        "required_by_kind": required_by_kind,
        "placed_by_kind": placed_by_kind,
        "unfilled_total": len(unfilled),
        "unfilled_key": unfilled_key,
        "weekly_hard": {str(k): v for k, v in weekly_hard.items()},
        "weekly_key": {str(k): v for k, v in weekly_key.items()},
    }
    ok = not any(i.severity == "error" for i in issues)
    return ProgrammeValidation(ok=ok, issues=issues, quota_report=quota_report)


__all__ = [
    "Issue", "SessionValidation", "ProgrammeValidation",
    "validate_session", "validate_programme",
]
