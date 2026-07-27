"""
CrewFit V2 Engine V2 — Demand + Scheduling
============================================

The WHAT layer (Demand) and WHEN layer (Scheduling) live together because the
scheduler is a strict consumer of the Demand output — it never invents
sessions of its own accord.

Contract:

    build_demand(client_profile, goal_key, phase_kind, weeks_in_window,
                 progression_state)
        →  DemandPlan {
             required_exposures: [RequiredExposure(objective_id, kind,
                                                   exposure_number, priority,
                                                   target_duration_min,
                                                   intensity_target)],
             frequency_caps: { hard_per_week, key_per_week,
                              consecutive_training_days_max, ... },
             notes: str
           }

    schedule_demand(demand, day_contexts, goal, phase, existing_placements)
        →  ScheduleResult {
             placements: [Placement],
             unfilled: [Unfilled(exposure_id, reason, candidate_hint_dates)],
             validation_notes: [str]
           }

`existing_placements` allows adding sessions on top of an already-existing
plan (e.g. a KEY session that must persist through reschedules).

CRUCIAL: `target_duration_min` on each RequiredExposure comes from goal +
phase + progression. Availability caps duration during construction — it
NEVER increases it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from feature_v2_sport_configs import (
    GoalConfig, PhaseSpec, QuotaRule,
    get_goal_config, canonicalise_goal_key,
    required_exposures_for_phase, session_kind_meta,
    is_key_intensity, is_hard_session, session_family,
)
from feature_v2_sequencing import (
    Placement, PlacementPlan, PlacementCheck,
    validate_placement, apply_placement, week_key,
)
from feature_v2_roster_context import DayContext


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RequiredExposure:
    """A single required session in the planning window.

    exposure_id is stable across reschedules for the same client+goal+phase+
    objective+week+ordinal.
    """
    exposure_id: str
    objective_id: str
    kind: str
    priority: str                # KEY / IMPORTANT / SUPPORTING / OPTIONAL
    target_duration_min: int
    duration_min_min: int
    duration_max_min: int
    intensity_target: str
    week_index: int              # 0-indexed within the planning window
    ordinal_within_week: int     # 1st long_run of the week = 1
    can_skip_if_missed: bool
    quota_source: str            # e.g. "running.marathon.aerobic_base"


@dataclass
class DemandPlan:
    required_exposures: list[RequiredExposure]
    frequency_caps: dict[str, int]
    notes: list[str] = field(default_factory=list)
    goal_key: str = ""
    phase_kind: str = ""
    weeks: int = 0

    def sort_by_priority(self) -> list[RequiredExposure]:
        rank = {"KEY": 0, "IMPORTANT": 1, "SUPPORTING": 2, "OPTIONAL": 3}
        return sorted(self.required_exposures,
                      key=lambda e: (rank.get(e.priority.upper(), 9),
                                     e.week_index, e.ordinal_within_week))


@dataclass
class Unfilled:
    exposure_id: str
    objective_id: str
    kind: str
    priority: str
    reason_code: str
    human_reason: str
    candidate_hint_dates: list[str] = field(default_factory=list)


@dataclass
class ScheduleResult:
    placements: list[Placement]
    unfilled: list[Unfilled]
    validation_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_id(*parts) -> str:
    h = hashlib.sha1("::".join(str(p) for p in parts).encode()).hexdigest()
    return h[:24]


def _iso_year_week(d: _dt.date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


def _apply_progression(base_duration_target: int, week_index: int,
                       progression: dict) -> int:
    """Apply a progression rule to a base target duration.
    progression={field, per_week_delta, cap}"""
    if not progression:
        return base_duration_target
    field_name = progression.get("field") or ""
    if not field_name.startswith("duration_min"):
        return base_duration_target
    delta = float(progression.get("per_week_delta") or 0)
    cap = int(progression.get("cap") or 10_000)
    out = int(round(base_duration_target + delta * week_index))
    return max(1, min(cap, out))


def _client_frequency_bounds(client_profile: dict, phase: PhaseSpec) -> tuple[int, int]:
    """(min, max) sessions/week the client can accept.
    Falls back to phase caps if profile is missing.
    Never allows unlimited — missing DNA does NOT mean 'as many as you want'.
    """
    prof = client_profile or {}
    lo = prof.get("sessions_per_week_min")
    hi = prof.get("sessions_per_week_max")
    if lo is None:
        lo = prof.get("training_days_per_week")
    if hi is None:
        hi = prof.get("training_days_per_week")
    if lo is None:
        lo = 3      # explicit floor — never unlimited
    if hi is None:
        hi = 5      # explicit ceiling — never unlimited
    try:
        lo = max(1, int(lo)); hi = max(lo, int(hi))
    except Exception:
        lo, hi = 3, 5
    # Never exceed phase's own hard-day + key-day + supporting cap
    hi = min(hi, phase.hard_days_per_week_max + 3)  # +3 for supporting
    return lo, hi


# ---------------------------------------------------------------------------
# WHAT — build_demand
# ---------------------------------------------------------------------------

def build_demand(
    *,
    client_id: str,
    client_profile: dict,
    goal_key: str,
    phase_spec: PhaseSpec,
    week_start_dates: list[_dt.date],
    progression_state: Optional[dict] = None,
) -> DemandPlan:
    """Compute the set of required training exposures for the given planning
    window (one entry per week * per quota).

    `week_start_dates` — list of Monday dates for each week in the window,
    in order. Determines how many exposures to schedule per quota.
    """
    cfg = get_goal_config(goal_key)
    quotas = list(phase_spec.quotas)

    # ------ Client frequency preferences ---------------------------------
    lo_freq, hi_freq = _client_frequency_bounds(client_profile, phase_spec)

    # ------ Enumerate required exposures --------------------------------
    exposures: list[RequiredExposure] = []
    notes: list[str] = []
    total_target_per_week = 0
    for q in quotas:
        _, target_per_week, _ = q.exposures_per_week
        total_target_per_week += target_per_week

    # Scale factor if the sum of quota targets exceeds client's weekly max
    scale = 1.0
    if total_target_per_week > hi_freq + 1e-6:
        scale = hi_freq / total_target_per_week
        notes.append(
            f"Quota total {total_target_per_week:.1f}/wk exceeds client max "
            f"{hi_freq}/wk — scaled by {scale:.2f}"
        )

    for week_index, week_start in enumerate(week_start_dates):
        for q in quotas:
            _lo, _target, _hi = q.exposures_per_week
            desired = max(_lo, _target * scale)
            # Compute integer exposure count for this week
            whole = int(desired)
            frac = desired - whole
            n_this_week = whole + (1 if (frac >= 0.5) else 0)
            n_this_week = max(int(_lo), min(int(_hi), n_this_week))
            if n_this_week <= 0:
                continue

            # Stable objective_id per (client, goal, phase, quota_kind)
            obj_id = _stable_id(client_id, cfg.key, phase_spec.phase_kind, q.kind)

            for ordinal in range(1, n_this_week + 1):
                # Duration with progression
                dur = _apply_progression(q.duration_min[1], week_index, q.progression)
                # Never allow duration to drop below quota's absolute minimum
                dur = max(q.duration_min[0], min(q.duration_min[2], dur))

                exposures.append(RequiredExposure(
                    exposure_id=_stable_id(
                        client_id, cfg.key, phase_spec.phase_kind,
                        q.kind, str(week_start), ordinal,
                    ),
                    objective_id=obj_id,
                    kind=q.kind,
                    priority=q.priority,
                    target_duration_min=int(dur),
                    duration_min_min=int(q.duration_min[0]),
                    duration_max_min=int(q.duration_min[2]),
                    intensity_target=q.intensity_target,
                    week_index=week_index,
                    ordinal_within_week=ordinal,
                    can_skip_if_missed=q.can_skip_if_missed,
                    quota_source=f"{cfg.key}.{phase_spec.phase_kind}",
                ))

    caps = {
        "hard_per_week_max": phase_spec.hard_days_per_week_max,
        "key_per_week_max": phase_spec.key_days_per_week_max,
        "consecutive_training_days_max": phase_spec.consecutive_training_days_max,
        "client_sessions_per_week_min": lo_freq,
        "client_sessions_per_week_max": hi_freq,
    }
    return DemandPlan(
        required_exposures=exposures,
        frequency_caps=caps,
        notes=notes,
        goal_key=cfg.key,
        phase_kind=phase_spec.phase_kind,
        weeks=len(week_start_dates),
    )


# ---------------------------------------------------------------------------
# WHEN — schedule_demand
# ---------------------------------------------------------------------------

def schedule_demand(
    demand: DemandPlan,
    day_contexts: list[DayContext],
    goal: GoalConfig,
    phase: PhaseSpec,
    preferred_weekdays: Optional[set[int]] = None,
    existing_placements: Optional[list[Placement]] = None,
) -> ScheduleResult:
    """Place each required exposure onto the best-fit day it can validate on.

    Algorithm:
      1. Group day_contexts by ISO week.
      2. Sort required_exposures: KEY first, then IMPORTANT, then SUPPORTING.
      3. For each exposure, try days in its target week ranked by priority-
         weighted opportunity score. Try each until validate_placement passes.
      4. If none pass in target week, escalate to +/- 1 week window.
      5. If still no fit → Unfilled with candidate_hint_dates showing the
         top 3 candidates + why each failed.
    """
    if preferred_weekdays is None:
        preferred_weekdays = set()

    # Bootstrap plan (preserves any existing placements coach has already made)
    plan = PlacementPlan(placements=list(existing_placements or []))

    # Index days by week
    days_by_week: dict[tuple[int, int], list[DayContext]] = {}
    for ctx in day_contexts:
        wk = week_key(ctx.date)
        days_by_week.setdefault(wk, []).append(ctx)
    # Sort demand by priority + week
    ordered = demand.sort_by_priority()

    unfilled: list[Unfilled] = []
    validation_notes: list[str] = []

    # Map week_index to (iso_year, iso_week) using placement candidate dates
    # We infer week starts from the day_contexts (earliest date per index).
    all_dates = sorted(ctx.date for ctx in day_contexts)
    if not all_dates:
        return ScheduleResult(plan.placements, unfilled, ["no day_contexts provided"])
    first_monday = all_dates[0] - _dt.timedelta(days=all_dates[0].weekday())

    for exp in ordered:
        target_monday = first_monday + _dt.timedelta(days=7 * exp.week_index)
        target_wk = week_key(target_monday)
        candidate_weeks = [target_wk]
        # Allow +/- 1 week only for non-KEY
        if exp.priority.upper() != "KEY":
            candidate_weeks += [
                week_key(target_monday + _dt.timedelta(days=7)),
                week_key(target_monday - _dt.timedelta(days=7)),
            ]

        placement_made = False
        rejections: list[tuple[_dt.date, str, str]] = []

        for wk in candidate_weeks:
            wk_days = days_by_week.get(wk, [])
            # Rank days: high opportunity first, then preferred weekday bump,
            # then lower burden. Rest days are excluded.
            def rank_key(ctx: DayContext) -> tuple:
                pref_bump = 15 if ctx.date.weekday() in preferred_weekdays else 0
                return (
                    -(ctx.training_opportunity + pref_bump),
                    ctx.duty_burden_score,
                    ctx.date.toordinal(),
                )
            ranked = sorted(wk_days, key=rank_key)

            for ctx in ranked:
                if ctx.day_type in ("sickness", "sick", "sick_leave"):
                    rejections.append((ctx.date, "sick_day", "client on sick leave"))
                    continue
                check = validate_placement(
                    kind=exp.kind, date=ctx.date, plan=plan,
                    goal=goal, phase=phase,
                    day_ctx_burden=ctx.duty_burden_score,
                    day_ctx_opportunity=ctx.training_opportunity,
                    priority=exp.priority,
                )
                if check.ok:
                    apply_placement(
                        plan,
                        exposure_id=exp.exposure_id,
                        objective_id=exp.objective_id,
                        kind=exp.kind,
                        date=ctx.date,
                        priority=exp.priority,
                        intensity_target=exp.intensity_target,
                        target_duration_min=exp.target_duration_min,
                    )
                    placement_made = True
                    break
                rejections.append((ctx.date, check.reason_code, check.human_reason))
            if placement_made:
                break

        if not placement_made:
            # Build actionable Unfilled record
            top_alt = sorted(rejections, key=lambda r: str(r[0]))[:3]
            unfilled.append(Unfilled(
                exposure_id=exp.exposure_id,
                objective_id=exp.objective_id,
                kind=exp.kind,
                priority=exp.priority,
                reason_code="no_valid_slot",
                human_reason=(
                    f"Cannot place {exp.kind} (priority={exp.priority}) in the "
                    f"target week — {len(rejections)} candidate day(s) tried, "
                    f"all rejected."
                ),
                candidate_hint_dates=[
                    f"{d.isoformat()} — {code}: {reason}"
                    for d, code, reason in top_alt
                ],
            ))
            if exp.priority.upper() == "KEY":
                validation_notes.append(
                    f"KEY exposure {exp.kind} in week {exp.week_index} could not be placed"
                )

    return ScheduleResult(
        placements=plan.placements,
        unfilled=unfilled,
        validation_notes=validation_notes,
    )


__all__ = [
    "RequiredExposure", "DemandPlan", "Unfilled", "ScheduleResult",
    "build_demand", "schedule_demand",
]
