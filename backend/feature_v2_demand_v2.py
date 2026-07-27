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
    frequency_derivation: dict[str, Any] = field(default_factory=dict)
    dna_gaps: list[dict[str, Any]] = field(default_factory=list)

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


def _client_frequency_bounds(client_profile: dict, phase: PhaseSpec) -> tuple[int, int, dict]:
    """Return (min, max, derivation) sessions/week the client can accept.

    Falls back to phase caps if profile is missing.
    Never allows unlimited — missing DNA does NOT mean 'as many as you want'.
    The `derivation` dict records every input + fallback used so it can be
    surfaced to the coach in the draft.
    """
    prof = client_profile or {}
    raw_min = prof.get("sessions_per_week_min")
    raw_max = prof.get("sessions_per_week_max")
    raw_tdpw = prof.get("training_days_per_week")

    derivation: dict[str, Any] = {
        "inputs": {
            "sessions_per_week_min": raw_min,
            "sessions_per_week_max": raw_max,
            "training_days_per_week": raw_tdpw,
        },
        "fallbacks_used": [],
    }

    lo = raw_min
    hi = raw_max
    if lo is None:
        lo = raw_tdpw
        if lo is not None:
            derivation["fallbacks_used"].append(
                "sessions_per_week_min ← training_days_per_week")
    if hi is None:
        hi = raw_tdpw
        if hi is not None:
            derivation["fallbacks_used"].append(
                "sessions_per_week_max ← training_days_per_week")
    if lo is None:
        lo = 3  # explicit floor — never unlimited
        derivation["fallbacks_used"].append("sessions_per_week_min ← 3 (engine floor)")
    if hi is None:
        hi = 5  # explicit ceiling — never unlimited
        derivation["fallbacks_used"].append("sessions_per_week_max ← 5 (engine ceiling)")
    try:
        lo = max(1, int(lo)); hi = max(lo, int(hi))
    except Exception:
        lo, hi = 3, 5
        derivation["fallbacks_used"].append("frequency bounds ← 3–5 (invalid inputs)")

    # Phase-defined support cap
    hi_before_phase_clip = hi
    hi = min(hi, phase.hard_days_per_week_max + phase.strength_days_per_week_max + 3)  # +3 for supporting
    if hi < hi_before_phase_clip:
        derivation["fallbacks_used"].append(
            f"sessions_per_week_max clipped by phase to {hi}")
    derivation["effective_min"] = lo
    derivation["effective_max"] = hi
    return lo, hi, derivation


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
    lo_freq, hi_freq, freq_derivation = _client_frequency_bounds(client_profile, phase_spec)

    # ------ Compute DNA gaps ---------------------------------------------
    prof = client_profile or {}
    dna_gaps: list[dict[str, Any]] = []
    if prof.get("sessions_per_week_min") is None and prof.get("sessions_per_week_max") is None:
        if prof.get("training_days_per_week") is not None:
            dna_gaps.append({
                "field": "sessions_per_week_min/max",
                "severity": "info",
                "fallback": f"training_days_per_week={prof.get('training_days_per_week')}",
                "message": "Session count bounds derived from training_days_per_week",
            })
        else:
            dna_gaps.append({
                "field": "sessions_per_week_min/max",
                "severity": "needs_review",
                "fallback": "engine defaults 3–5",
                "message": "Engine used defaults 3-5 because DNA did not capture "
                           "session-count bounds — coach should confirm.",
            })
    if not prof.get("preferred_training_days"):
        dna_gaps.append({
            "field": "preferred_training_days",
            "severity": "info",
            "fallback": "no day-of-week preference applied",
            "message": "No preferred training days captured — scheduler will use "
                       "opportunity-based ranking only.",
        })
    if prof.get("preferred_session_length") in (None, 0, ""):
        dna_gaps.append({
            "field": "preferred_session_length",
            "severity": "info",
            "fallback": "phase quota duration used",
            "message": "No preferred session length captured — engine uses "
                       "phase-defined quota durations.",
        })
    if prof.get("max_home_minutes") in (None, 0, "") and prof.get("time_home_min") in (None, 0, ""):
        dna_gaps.append({
            "field": "max_home_minutes",
            "severity": "info",
            "fallback": "roster-context default cap",
            "message": "No home daily cap captured — engine uses roster-derived "
                       "available_time_min per day.",
        })

    # ------ Enumerate required exposures --------------------------------
    exposures: list[RequiredExposure] = []
    notes: list[str] = []
    total_target_per_week = 0
    quota_targets: dict[str, float] = {}
    for q in quotas:
        _, target_per_week, _ = q.exposures_per_week
        total_target_per_week += target_per_week
        quota_targets[q.kind] = target_per_week

    # Scale factor if the sum of quota targets exceeds client's weekly max
    scale = 1.0
    if total_target_per_week > hi_freq + 1e-6:
        scale = hi_freq / total_target_per_week
        notes.append(
            f"Quota total {total_target_per_week:.1f}/wk exceeds client max "
            f"{hi_freq}/wk — scaled by {scale:.2f}"
        )

    freq_derivation.update({
        "raw_quota_targets_per_week": quota_targets,
        "raw_quota_total_per_week": total_target_per_week,
        "client_effective_min_per_week": lo_freq,
        "client_effective_max_per_week": hi_freq,
        "phase_hard_days_per_week_max": phase_spec.hard_days_per_week_max,
        "phase_key_days_per_week_max": phase_spec.key_days_per_week_max,
        "phase_strength_days_per_week_max": phase_spec.strength_days_per_week_max,
        "scaling_factor": round(scale, 3),
        "scale_reason": (
            f"raw {total_target_per_week:.1f}/wk > client cap {hi_freq}/wk"
            if scale < 1.0 else "no scaling needed"
        ),
    })

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
        "strength_per_week_max": phase_spec.strength_days_per_week_max,
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
        frequency_derivation=freq_derivation,
        dna_gaps=dna_gaps,
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
    daily_time_cap_by_date: Optional[dict[_dt.date, int]] = None,
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
      6. After ALL placements are made, renumber `exposure_number` per
         objective_id in strictly chronological order (1..N by date). This
         guarantees the display sequence matches the calendar order.

    daily_time_cap_by_date: hard daily total-minutes cap per date. Falls back
        to each day_context's `available_time_min` if not provided.
    """
    if preferred_weekdays is None:
        preferred_weekdays = set()

    # Build daily time-cap lookup (union of arg and day_ctx.available_time_min)
    dtcap: dict[_dt.date, int] = {}
    for ctx in day_contexts:
        dtcap[ctx.date] = int(ctx.available_time_min)
    if daily_time_cap_by_date:
        for d, v in daily_time_cap_by_date.items():
            dtcap[d] = min(dtcap.get(d, v), int(v))

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
                    target_duration_min=exp.target_duration_min,
                    daily_time_cap_min=dtcap.get(ctx.date, ctx.available_time_min),
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

    # ---- Chronological renumbering per objective_id -----------------------
    # exposure_id remains the immutable identity from build_demand; but the
    # exposure_number displayed on the calendar must be 1..N in DATE order
    # for each objective family. This is what the validators + UI depend on.
    per_obj: dict[str, list[Placement]] = {}
    for p in plan.placements:
        per_obj.setdefault(p.objective_id, []).append(p)
    for obj_id, group in per_obj.items():
        group_sorted = sorted(group, key=lambda p: (p.date, p.exposure_id))
        for new_n, pl in enumerate(group_sorted, start=1):
            pl.exposure_number = new_n

    return ScheduleResult(
        placements=plan.placements,
        unfilled=unfilled,
        validation_notes=validation_notes,
    )


__all__ = [
    "RequiredExposure", "DemandPlan", "Unfilled", "ScheduleResult",
    "build_demand", "schedule_demand",
]
