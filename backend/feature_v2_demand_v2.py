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

    Window ownership (Correctness Patch #2):
      * target_week_start / _end  → canonical week the exposure BELONGS to.
      * allowed_window_start / _end → the interval a scheduler MAY use if the
        canonical week has no viable slot. Spillover placements outside the
        target week still consume THIS exposure's quota (they never
        accidentally satisfy another exposure).

    Cadence (Correctness Patch #1):
      * preferred_cadence_days   → ideal gap since last placement of the same
        objective_id. E.g. Long Run = 7 in marathon foundation.
      * cadence_range_days       → (soft_min, soft_max) — softly discouraged
        outside this band but still legal if hard-min recovery is respected.
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
    target_week_start: Optional[_dt.date] = None
    target_week_end: Optional[_dt.date] = None
    allowed_window_start: Optional[_dt.date] = None
    allowed_window_end: Optional[_dt.date] = None
    preferred_cadence_days: Optional[int] = None
    cadence_range_days: Optional[tuple[int, int]] = None


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
    """Return (min_sessions, max_sessions, derivation) sessions/week the
    client can accept.

    Semantics (Correctness Patch #3):
      * `training_days_per_week`  = distinct DATES the client can train.
                                    Support-stacking (e.g. mobility on the
                                    same day as an easy run) does NOT
                                    increase the training-days count.
      * `sessions_per_week_*`     = total SESSION count (exposures) per week.
                                    May exceed training_days_per_week when
                                    stacking occurs.

    Effective mapping used by the engine:
      * `max_training_days_per_week`  ← `training_days_per_week` (fallback 5)
      * `max_sessions_per_week`       ← `sessions_per_week_max` if provided,
                                        else `training_days_per_week + 2`
                                        (support-stacking slack) capped by
                                        phase.
      * `min_sessions_per_week`       ← `sessions_per_week_min` if provided,
                                        else `training_days_per_week`.

    Never allows unlimited — missing DNA falls back to explicit defaults.
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

    # Distinct-days constraint (max training days per week)
    if raw_tdpw is None:
        max_training_days = 5
        derivation["fallbacks_used"].append("training_days_per_week ← 5 (engine default)")
    else:
        try:
            max_training_days = max(1, int(raw_tdpw))
        except Exception:
            max_training_days = 5
            derivation["fallbacks_used"].append("training_days_per_week invalid → 5")

    # Sessions/week (may exceed training-days due to support-stacking)
    if raw_min is not None:
        try:
            lo = max(1, int(raw_min))
        except Exception:
            lo = max_training_days
            derivation["fallbacks_used"].append("sessions_per_week_min invalid → training_days_per_week")
    else:
        lo = max_training_days
        derivation["fallbacks_used"].append("sessions_per_week_min ← training_days_per_week")

    if raw_max is not None:
        try:
            hi = max(lo, int(raw_max))
        except Exception:
            hi = max_training_days
            derivation["fallbacks_used"].append("sessions_per_week_max invalid → training_days_per_week")
    else:
        # No explicit sessions cap — treat sessions = training days.
        # Support-stacking still fits under the same session budget; this
        # preserves the meaning of `training_days_per_week` consistently.
        hi = max_training_days
        derivation["fallbacks_used"].append(
            "sessions_per_week_max ← training_days_per_week (no explicit cap)"
        )

    # Phase clip (never more than the sum of hard + strength + support)
    phase_max_sessions = (phase.hard_days_per_week_max +
                          phase.strength_days_per_week_max + 3)
    hi_before_phase = hi
    hi = min(hi, phase_max_sessions)
    if hi < hi_before_phase:
        derivation["fallbacks_used"].append(
            f"sessions_per_week_max clipped by phase to {hi}"
        )

    derivation["effective_min_sessions_per_week"] = lo
    derivation["effective_max_sessions_per_week"] = hi
    derivation["effective_max_training_days_per_week"] = max_training_days
    # Backward compat
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
    window_start: Optional[_dt.date] = None,
    window_end: Optional[_dt.date] = None,
    effective_start_date: Optional[_dt.date] = None,
) -> DemandPlan:
    """Compute the set of required training exposures for the given planning
    window (one entry per week * per quota).

    `week_start_dates` — list of Monday dates for each week in the window,
    in order. Determines how many exposures to schedule per quota.

    `window_start` / `window_end` (optional) — the outer planning window
    bounds.

    `effective_start_date` (optional, Iter 131d) — the FIRST date on which
    the client can actually train. Kickoff sets this to `today` because
    days before today are in the past. Used to compute usable-days-in-week
    for the partial-week gate. If absent, we fall back to `window_start`,
    and if that's also absent, we assume every week is a full 7-day week.
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
    # Expose the four canonical frequency concepts for the coach UI
    freq_derivation["semantics"] = {
        "max_training_days_per_week": freq_derivation.get(
            "effective_max_training_days_per_week"),
        "min_sessions_per_week": freq_derivation.get("effective_min_sessions_per_week"),
        "max_sessions_per_week": freq_derivation.get("effective_max_sessions_per_week"),
        "note": (
            "training_days = distinct dates. sessions = total exposures. "
            "Support stacking (mobility on an easy-run day) adds sessions "
            "without adding training days."
        ),
    }

    # Iter 121c — Priority-aware main-training-day cap.
    # `training_days_per_week` is the ceiling for MAIN sessions (KEY + IMPORTANT).
    # SUPPORTING / OPTIONAL are stackable — they are permitted to add on top
    # of MAIN days up to a small auto stacking budget (default 2), which
    # allows mobility / conditioning to attach to existing training days
    # without creating a new independent training day. The scheduler is
    # responsible for actually placing them onto compatible days; if no
    # compatible day exists the placement is skipped.
    main_day_cap = freq_derivation.get("effective_max_training_days_per_week") or hi_freq

    # If the client set sessions_per_week_max explicitly HIGHER than
    # training_days_per_week, honour that as extra stackable capacity.
    # Otherwise grant a default auto stacking budget of 2.
    auto_stack_budget = max(2, hi_freq - main_day_cap)

    def _round(desired: float, lo: int, hi: int) -> int:
        whole = int(desired)
        frac = desired - whole
        n = whole + (1 if frac >= 0.5 else 0)
        return max(lo, min(hi, n))

    # Split quotas by priority tier.
    MAIN_PRIOS = {"KEY", "IMPORTANT"}
    main_quotas = [q for q in quotas if q.priority.upper() in MAIN_PRIOS]
    support_quotas = [q for q in quotas if q.priority.upper() not in MAIN_PRIOS]

    def _per_quota_counts(qs, cap):
        """Assign per-quota exposure counts respecting `cap` total.
        KEY MIN is protected first, then TARGET is filled by declaration order.

        Iter 130f — Bug fix: a KEY quota declared with a fractional min
        (e.g. run_long (0.5, 1, 1) meaning "at least every other week")
        must never round down to zero via ``int(lo)`` — that silently
        deletes the anchor. For KEY priority with ``0 < lo < 1`` we
        promote to ``1`` so the anchor is always seeded. Non-KEY
        fractional mins continue to floor as before.
        """
        counts: dict[str, int] = {}
        remaining = cap
        # Pass 1 — every quota's MIN is guaranteed (KEY MIN protected first)
        for q in sorted(qs, key=lambda q: (0 if q.priority.upper() == "KEY" else 1)):
            lo, target, hi = q.exposures_per_week
            if q.priority.upper() == "KEY" and 0 < lo < 1:
                n_min = 1
            else:
                n_min = int(lo)
            if n_min <= remaining:
                counts[q.kind] = n_min
                remaining -= n_min
            else:
                counts[q.kind] = n_min if q.priority.upper() == "KEY" else 0
                if q.priority.upper() == "KEY":
                    remaining = max(0, remaining - n_min)
        # Pass 2 — fill up to TARGET within remaining budget
        for q in qs:
            lo, target, hi = q.exposures_per_week
            already = counts.get(q.kind, 0)
            headroom = min(int(hi), int(round(target))) - already
            if headroom > 0 and remaining > 0:
                add = min(headroom, remaining)
                counts[q.kind] = already + add
                remaining -= add
        return counts, remaining

    # Iter 130g — MAIN MIN allocation may spill into the stacking budget so
    # that a marathon plan with training_days_per_week=3 still receives its
    # KEY Long Run + IMPORTANT Easy Runs + IMPORTANT Strength MIN (i.e.
    # 3 runs + 2 strength minimum) without silently dropping the strength.
    # Rule: MAIN gets `main_day_cap` primary budget; if MAIN MINs need more,
    # they may borrow up to `auto_stack_budget` (support-stacking capacity).
    # SUPPORT gets whatever remains of the stacking budget after MAIN MINs.
    total_session_budget = main_day_cap + auto_stack_budget

    def _per_quota_counts_priority_preserving(qs, primary_cap, borrow_cap):
        """Two-phase allocator that guarantees MINs across the combined
        primary + borrow budget while preserving priority order.

        Pass 1 (MINs, KEY→IMPORTANT→SUPPORTING→OPTIONAL): fill each quota's
        minimum, drawing from primary first then borrow. KEY fractional MIN
        (0<lo<1) rounds up to 1 (never silently deleted).
        Pass 2 (TARGETs, same order): fill remaining headroom up to
        ``min(int(hi), round(target))`` from primary first then borrow.

        Returns (counts_by_kind, primary_used, borrow_used).
        """
        rank = {"KEY": 0, "IMPORTANT": 1, "SUPPORTING": 2, "OPTIONAL": 3}
        counts: dict[str, int] = {}
        primary_used = 0
        borrow_used = 0
        pri = primary_cap
        bor = borrow_cap

        def _draw(n: int) -> int:
            """Draw up to n from primary then borrow; returns amount drawn."""
            nonlocal pri, bor, primary_used, borrow_used
            take_pri = min(n, pri)
            pri -= take_pri
            primary_used += take_pri
            remaining = n - take_pri
            take_bor = min(remaining, bor)
            bor -= take_bor
            borrow_used += take_bor
            return take_pri + take_bor

        sorted_qs = sorted(qs, key=lambda q: rank.get(q.priority.upper(), 9))
        for q in sorted_qs:
            lo, tgt, hi = q.exposures_per_week
            if q.priority.upper() == "KEY" and 0 < lo < 1:
                n_min = 1
            else:
                n_min = int(lo)
            got = _draw(n_min)
            counts[q.kind] = got
        for q in sorted_qs:
            lo, tgt, hi = q.exposures_per_week
            already = counts.get(q.kind, 0)
            headroom = min(int(hi), int(round(tgt))) - already
            if headroom > 0:
                add = _draw(headroom)
                counts[q.kind] = already + add
        return counts, primary_used, borrow_used

    all_counts, pri_used, bor_used = _per_quota_counts_priority_preserving(
        quotas, main_day_cap, auto_stack_budget,
    )
    # Split back to main/support for reporting only
    main_counts = {q.kind: all_counts.get(q.kind, 0) for q in main_quotas}
    support_counts = {q.kind: all_counts.get(q.kind, 0) for q in support_quotas}

    per_quota_counts_by_kind: dict[str, int] = dict(all_counts)
    freq_derivation["priority_clip"] = {
        "main_day_cap": main_day_cap,
        "auto_stack_budget": auto_stack_budget,
        "total_session_budget": total_session_budget,
        "primary_budget_used": pri_used,
        "stacking_budget_used": bor_used,
        "main_counts": main_counts,
        "support_counts": support_counts,
        "allocation_note": (
            "MAIN MINs may borrow from stacking budget so KEY+IMPORTANT "
            "minima survive when training_days_per_week is tight. TARGETs "
            "still fill up to combined budget in priority order."
        ),
    }

    # Iter 130f — deterministic KEY-anchor guardrail. A non-skippable KEY
    # quota (e.g. marathon Long Run) must never resolve to zero. If it
    # does, we forcibly demote one lower-priority IMPORTANT slot to make
    # room. This is a safety net that catches any future scaling / cap
    # edge cases without another silent long-run deletion.
    dropped_key_anchors: list[str] = []
    for q in main_quotas:
        if q.priority.upper() != "KEY":
            continue
        if getattr(q, "can_skip_if_missed", True):
            continue
        if main_counts.get(q.kind, 0) >= 1:
            continue
        # Anchor was dropped — try to reclaim from the largest IMPORTANT bucket.
        candidates = [k for k in main_counts
                      if main_counts[k] > 0
                      and not any(x.kind == k and x.priority.upper() == "KEY" for x in main_quotas)]
        candidates.sort(key=lambda k: main_counts[k], reverse=True)
        if candidates:
            main_counts[candidates[0]] -= 1
            main_counts[q.kind] = 1
            dropped_key_anchors.append(
                f"reclaimed 1 slot from {candidates[0]} → {q.kind} (KEY anchor rescue)"
            )
        else:
            dropped_key_anchors.append(
                f"⚠ {q.kind} (KEY, non-skippable) still resolves to 0 — no lower-priority slot to reclaim from"
            )
    if dropped_key_anchors:
        freq_derivation["priority_clip"]["key_anchor_rescues"] = dropped_key_anchors

    # ------ Iter 131c — partial-week detection ---------------------------
    #   A week is "partial" if fewer than 5 of its 7 days fall inside the
    #   planning window. In a partial week we do NOT emit compulsory
    #   (KEY / IMPORTANT non-skippable) exposures — those would otherwise
    #   produce validator errors and unfillable blockers that no amount of
    #   scheduling can satisfy.
    FULL_WEEK_MIN_DAYS = 5

    def _usable_days_in_week(wk_start: _dt.date) -> int:
        # Iter 131d — lower bound is max(window_start, effective_start_date).
        # Days before the effective start (i.e. in the past) do NOT count as
        # usable, even when window_start is aligned to the Monday of the
        # current week (which kickoff always does).
        eff_lower = None
        if effective_start_date is not None:
            eff_lower = effective_start_date
        elif window_start is not None:
            eff_lower = window_start
        if eff_lower is None and window_end is None:
            return 7  # backward-compat: assume full weeks when bounds absent
        count = 0
        for _i in range(7):
            _d = wk_start + _dt.timedelta(days=_i)
            if eff_lower is not None and _d < eff_lower:
                continue
            if window_end is not None and _d > window_end:
                continue
            count += 1
        return count

    partial_week_notes: list[str] = []

    for week_index, week_start in enumerate(week_start_dates):
        usable_days = _usable_days_in_week(week_start)
        is_partial = usable_days < FULL_WEEK_MIN_DAYS
        if is_partial:
            partial_week_notes.append(
                f"partial_week: {week_start.isoformat()} — "
                f"{usable_days} of 7 days in window "
                f"(compulsory quotas waived; supporting proportionally scaled)"
            )
        for q in quotas:
            _lo, _target, _hi = q.exposures_per_week
            n_this_week = per_quota_counts_by_kind.get(q.kind, 0)
            if n_this_week <= 0:
                continue

            # Iter 131c partial-week gate --------------------------------
            if is_partial:
                is_compulsory = (
                    q.priority.upper() == "KEY"
                    or (q.priority.upper() == "IMPORTANT" and not q.can_skip_if_missed)
                )
                if is_compulsory:
                    # Skip compulsory quotas in partial weeks entirely.
                    # No exposure generated → validator cannot mark it unfilled.
                    continue
                # SUPPORTING / OPTIONAL: scale down proportionally to the
                # usable window. E.g. a 2-day partial week gets ~2/7 of the
                # target support sessions. Always keep at least 0 (may drop
                # a quota completely if it rounds down).
                scaled = int(round(n_this_week * usable_days / 7.0))
                n_this_week = max(0, min(n_this_week, scaled))
                if n_this_week <= 0:
                    continue

            # Stable objective_id per (client, goal, phase, quota_kind)
            obj_id = _stable_id(client_id, cfg.key, phase_spec.phase_kind, q.kind)

            # Per-quota cadence + spillover defaults
            pref_cadence = q.preferred_cadence_days
            if pref_cadence is None:
                # Derive from exposures_per_week: 1/wk -> 7d, 2/wk -> 3-4d, ...
                _, tgt, _ = q.exposures_per_week
                pref_cadence = max(2, round(7.0 / max(tgt, 0.5)))
            cadence_range = q.cadence_range_days
            if cadence_range is None:
                # +/- 25% around preferred cadence (min hard floor 2 days)
                lo_c = max(2, int(round(pref_cadence * 0.7)))
                hi_c = int(round(pref_cadence * 1.4))
                cadence_range = (lo_c, hi_c)
            spillover_wk = q.spillover_window_weeks
            if spillover_wk is None:
                spillover_wk = {"KEY": 0, "IMPORTANT": 1,
                                 "SUPPORTING": 2, "OPTIONAL": 2}.get(q.priority.upper(), 1)

            target_week_end = week_start + _dt.timedelta(days=6)
            allowed_start = week_start - _dt.timedelta(days=7 * spillover_wk)
            allowed_end = target_week_end + _dt.timedelta(days=7 * spillover_wk)

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
                    target_week_start=week_start,
                    target_week_end=target_week_end,
                    allowed_window_start=allowed_start,
                    allowed_window_end=allowed_end,
                    preferred_cadence_days=int(pref_cadence),
                    cadence_range_days=tuple(cadence_range),
                ))

    caps = {
        "hard_per_week_max": phase_spec.hard_days_per_week_max,
        "key_per_week_max": phase_spec.key_days_per_week_max,
        "strength_per_week_max": phase_spec.strength_days_per_week_max,
        "consecutive_training_days_max": phase_spec.consecutive_training_days_max,
        "client_sessions_per_week_min": lo_freq,
        "client_sessions_per_week_max": hi_freq,
        "client_training_days_per_week_max": freq_derivation.get(
            "effective_max_training_days_per_week"),
    }
    return DemandPlan(
        required_exposures=exposures,
        frequency_caps=caps,
        notes=notes + partial_week_notes,
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

    # Distinct-training-days cap per week (Correctness Patch #3 semantics)
    max_training_days_per_week = int(
        (demand.frequency_caps or {}).get("client_training_days_per_week_max") or 7
    )

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
        # ---- Determine allowed placement window & target window ---------
        if exp.target_week_start and exp.allowed_window_start:
            target_start = exp.target_week_start
            target_end = exp.target_week_end
            allowed_start = exp.allowed_window_start
            allowed_end = exp.allowed_window_end
        else:
            # Legacy fallback (should not happen with new build_demand)
            target_start = first_monday + _dt.timedelta(days=7 * exp.week_index)
            target_end = target_start + _dt.timedelta(days=6)
            if exp.priority.upper() == "KEY":
                allowed_start, allowed_end = target_start, target_end
            else:
                allowed_start = target_start - _dt.timedelta(days=7)
                allowed_end = target_end + _dt.timedelta(days=7)

        # Collect candidate days inside the ALLOWED window
        candidate_days = [
            ctx for ctx in day_contexts
            if allowed_start <= ctx.date <= allowed_end
        ]

        # Reference cadence: last placement of same objective (across all weeks)
        # for cadence scoring
        cadence_target = exp.preferred_cadence_days or 7
        cadence_soft_min, cadence_soft_max = (
            exp.cadence_range_days if exp.cadence_range_days else (cadence_target - 1, cadence_target + 2)
        )
        last_same_obj = None
        for p in plan.placements:
            if p.objective_id == exp.objective_id:
                if last_same_obj is None or p.date > last_same_obj:
                    last_same_obj = p.date

        def _cadence_penalty(candidate_date: _dt.date) -> int:
            """Return an integer penalty (higher = worse) based on how far the
            candidate is from the preferred cadence relative to the previous
            same-objective placement. Zero-anchor case → no penalty."""
            if last_same_obj is None:
                # No prior placement of this objective yet — prefer candidates
                # in the target window over spillover
                if target_start <= candidate_date <= target_end:
                    return 0
                # Penalize spillover distance from target window
                if candidate_date < target_start:
                    return int((target_start - candidate_date).days) * 8
                return int((candidate_date - target_end).days) * 8
            gap = (candidate_date - last_same_obj).days
            if gap <= 0:
                return 500  # candidate is before or equal to last — bad
            if cadence_soft_min <= gap <= cadence_soft_max:
                # Inside soft range — small penalty proportional to deviation
                return abs(gap - cadence_target)
            # Outside soft range — larger penalty proportional to deviation
            if gap < cadence_soft_min:
                # Too close to previous → heavy penalty (clustering)
                return (cadence_soft_min - gap) * 15
            # gap > cadence_soft_max → too far → heavy penalty (rhythm gap)
            return (gap - cadence_soft_max) * 12

        def rank_key(ctx: DayContext) -> tuple:
            pref_bump = 15 if ctx.date.weekday() in preferred_weekdays else 0
            in_target_window = target_start <= ctx.date <= target_end
            # Ordering priority (all minimised):
            #   1. IN-target-window before spillover (0/1)
            #   2. Cadence penalty (small = better)
            #   3. -opportunity (higher opp = better)
            #   4. burden (lower = better)
            #   5. date (deterministic tiebreaker)
            return (
                0 if in_target_window else 1,
                _cadence_penalty(ctx.date),
                -(ctx.training_opportunity + pref_bump),
                ctx.duty_burden_score,
                ctx.date.toordinal(),
            )

        placement_made = False
        rejections: list[tuple[_dt.date, str, str]] = []

        ranked = sorted(candidate_days, key=rank_key)
        # Determine whether THIS exposure adds a NEW training day (a placement
        # of a non-support kind that no other placement uses on that date).
        from feature_v2_sport_configs import (
            session_load_bucket, LOAD_BUCKET_EASY, LOAD_BUCKET_RECOVERY,
        )
        exp_bucket = session_load_bucket(exp.kind)
        exp_is_support = exp_bucket in (LOAD_BUCKET_EASY, LOAD_BUCKET_RECOVERY)

        for ctx in ranked:
            if ctx.day_type in ("sickness", "sick", "sick_leave"):
                rejections.append((ctx.date, "sick_day", "client on sick leave"))
                continue
            # Distinct-training-days cap: an anchor session on a NEW date
            # counts as +1 training day. Support stacking on an already-used
            # date does not.
            wk = ctx.date.isocalendar()
            distinct_days_in_wk = plan.distinct_training_dates_in_week(wk[0], wk[1])
            date_already_used = any(p.date == ctx.date for p in plan.placements)
            adds_new_day = (not date_already_used) and (not exp_is_support or not date_already_used)
            # Support may open a new day too if no anchor exists, so keep the
            # cap even for support (it's still an occupied training date).
            if adds_new_day and distinct_days_in_wk >= max_training_days_per_week:
                rejections.append((ctx.date, "weekly_training_days_cap",
                                    f"Week already uses {distinct_days_in_wk} training days "
                                    f"of client cap {max_training_days_per_week}"))
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

        if not placement_made:
            top_alt = sorted(rejections, key=lambda r: str(r[0]))[:3]
            unfilled.append(Unfilled(
                exposure_id=exp.exposure_id,
                objective_id=exp.objective_id,
                kind=exp.kind,
                priority=exp.priority,
                reason_code="no_valid_slot",
                human_reason=(
                    f"Cannot place {exp.kind} (priority={exp.priority}) "
                    f"target week {target_start.isoformat()}..{target_end.isoformat()} "
                    f"allowed window {allowed_start.isoformat()}..{allowed_end.isoformat()} "
                    f"— {len(rejections)} candidate day(s) tried, all rejected."
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

    # ---- Iter 131a — Compulsory-exposure rescue post-pass -----------------
    # After the greedy pass, some compulsory exposures may be unfilled because
    # a lower-priority exposure earlier claimed the only remaining training
    # date in the week. Run one rescue pass covering both:
    #   1. KEY exposures                       (always compulsory)
    #   2. IMPORTANT with can_skip_if_missed=False   (protected non-skippable)
    #
    # For each unfilled compulsory exposure, we look ONLY within that
    # exposure's TARGET week for a lower-priority placement that opened a
    # new training date (SUPPORTING or OPTIONAL only — a compulsory
    # exposure is never evicted). We temporarily evict it, retry the
    # compulsory exposure on that date, and either keep the swap or
    # restore the lower-priority placement exactly if the retry still
    # fails. KEY exposures are processed BEFORE IMPORTANT so KEY always
    # wins any tie. Single pass, no recursion.
    if unfilled:
        # Preserve original exposure metadata so we can rebuild + retry.
        exp_by_id: dict[str, Any] = {e.exposure_id: e for e in ordered}

        def _priority_rank(pr: str) -> int:
            return {"KEY": 0, "IMPORTANT": 1, "SUPPORTING": 2,
                    "OPTIONAL": 3}.get((pr or "").upper(), 9)

        def _is_compulsory(pr: str, can_skip: bool) -> bool:
            p = (pr or "").upper()
            if p == "KEY":
                return True
            if p == "IMPORTANT" and not can_skip:
                return True
            return False

        # Split unfilled into (rescueable compulsory, everything else).
        # Order: KEY first, then IMPORTANT non-skippable. Non-compulsory
        # unfilled entries pass through untouched.
        rescue_queue: list[Unfilled] = []
        passthrough: list[Unfilled] = []
        for uf in unfilled:
            exp = exp_by_id.get(uf.exposure_id)
            can_skip = bool(getattr(exp, "can_skip_if_missed", True)) if exp else True
            if exp is not None and _is_compulsory(uf.priority, can_skip):
                rescue_queue.append(uf)
            else:
                passthrough.append(uf)
        rescue_queue.sort(key=lambda u: (_priority_rank(u.priority),
                                          u.exposure_id))

        remaining_unfilled: list[Unfilled] = list(passthrough)

        for uf in rescue_queue:
            comp_exp = exp_by_id.get(uf.exposure_id)
            if comp_exp is None:
                remaining_unfilled.append(uf)
                continue

            # Target + allowed windows for the compulsory exposure.
            c_allowed_start = comp_exp.allowed_window_start or (
                first_monday + _dt.timedelta(days=7 * comp_exp.week_index) - _dt.timedelta(days=7)
            )
            c_allowed_end = comp_exp.allowed_window_end or (
                first_monday + _dt.timedelta(days=7 * comp_exp.week_index + 6) + _dt.timedelta(days=7)
            )
            c_target_start = comp_exp.target_week_start or (
                first_monday + _dt.timedelta(days=7 * comp_exp.week_index)
            )
            c_target_end = comp_exp.target_week_end or (
                c_target_start + _dt.timedelta(days=6)
            )

            # Candidate DATES to reclaim (Iter 131c — bundle-aware):
            #  * Every placement on the date must be SUPPORTING or OPTIONAL
            #    (never evict another compulsory placement).
            #  * At least one placement exists on that date.
            #  * Date sits inside the compulsory exposure's TARGET week AND
            #    its allowed window.
            # We evict the WHOLE bundle atomically, retry the compulsory
            # exposure on the cleared date, and — if the retry succeeds —
            # try to re-add any Mobility placement from the evicted bundle
            # if it still fits within the daily time cap. Non-mobility
            # lower-priority sessions from the bundle are moved to the
            # unfilled list (the coach can decide whether to re-add later).
            date_bundles: dict[_dt.date, list[Placement]] = {}
            for p in plan.placements:
                p_pri = (p.priority or "").upper()
                if p_pri not in ("SUPPORTING", "OPTIONAL"):
                    # Compulsory placement on this date → date is off-limits.
                    date_bundles.pop(p.date, None)
                    date_bundles[p.date] = []  # sentinel: has a compulsory
                    continue
                if not (c_target_start <= p.date <= c_target_end):
                    continue
                if not (c_allowed_start <= p.date <= c_allowed_end):
                    continue
                if date_bundles.get(p.date) is None:
                    date_bundles[p.date] = []
                # Only append if the sentinel hasn't already been set to empty
                # (meaning this date contains a compulsory placement).
                if p.date not in date_bundles or date_bundles[p.date] != []:
                    date_bundles.setdefault(p.date, []).append(p)
                # Note: sentinel-empty case above stays empty (compulsory).
            # Filter: keep only dates whose bundle is non-empty AND we haven't
            # blacklisted (blacklist = we set to empty list because of a
            # compulsory placement seen on that date).
            candidates: list[tuple[_dt.date, list[Placement]]] = []
            # Recompute cleanly to avoid the sentinel/append race above:
            date_bundles = {}
            date_has_compulsory: set[_dt.date] = set()
            for p in plan.placements:
                p_pri = (p.priority or "").upper()
                if p_pri not in ("SUPPORTING", "OPTIONAL"):
                    date_has_compulsory.add(p.date)
                    continue
                if not (c_target_start <= p.date <= c_target_end):
                    continue
                if not (c_allowed_start <= p.date <= c_allowed_end):
                    continue
                date_bundles.setdefault(p.date, []).append(p)
            for d, bundle in date_bundles.items():
                if d in date_has_compulsory:
                    continue  # date shared with a compulsory placement
                if not bundle:
                    continue
                ctx = next((c for c in day_contexts if c.date == d), None)
                if ctx is None:
                    continue
                candidates.append((d, bundle))

            rescued = False
            for evict_date, bundle in candidates:
                ctx = next((c for c in day_contexts if c.date == evict_date), None)
                if ctx is None:
                    continue
                # Evict entire bundle atomically.
                for evicted_p in bundle:
                    if evicted_p in plan.placements:
                        plan.placements.remove(evicted_p)
                # Retry compulsory on cleared date.
                check = validate_placement(
                    kind=comp_exp.kind, date=ctx.date, plan=plan,
                    goal=goal, phase=phase,
                    day_ctx_burden=ctx.duty_burden_score,
                    day_ctx_opportunity=ctx.training_opportunity,
                    priority=comp_exp.priority,
                    target_duration_min=comp_exp.target_duration_min,
                    daily_time_cap_min=dtcap.get(ctx.date, ctx.available_time_min),
                )
                if not check.ok:
                    # Restore bundle exactly if compulsory still fails.
                    for evicted_p in bundle:
                        plan.placements.append(evicted_p)
                    continue
                # Compulsory validates — apply it.
                apply_placement(
                    plan,
                    exposure_id=comp_exp.exposure_id,
                    objective_id=comp_exp.objective_id,
                    kind=comp_exp.kind,
                    date=ctx.date,
                    priority=comp_exp.priority,
                    intensity_target=comp_exp.intensity_target,
                    target_duration_min=comp_exp.target_duration_min,
                )
                # Try to re-add Mobility from the evicted bundle if it still
                # fits under the daily cap after the compulsory session lands.
                # Non-mobility lower-priority items (Aerobic Z2, run_easy,
                # etc.) are moved to unfilled — the coach can choose to
                # re-place them elsewhere.
                readded_mobility_ids: set[str] = set()
                for evicted_p in bundle:
                    if evicted_p.kind != "mobility":
                        continue
                    mob_check = validate_placement(
                        kind=evicted_p.kind, date=ctx.date, plan=plan,
                        goal=goal, phase=phase,
                        day_ctx_burden=ctx.duty_burden_score,
                        day_ctx_opportunity=ctx.training_opportunity,
                        priority=evicted_p.priority,
                        target_duration_min=evicted_p.target_duration_min,
                        daily_time_cap_min=dtcap.get(ctx.date, ctx.available_time_min),
                    )
                    if mob_check.ok:
                        plan.placements.append(evicted_p)
                        readded_mobility_ids.add(evicted_p.exposure_id)

                validation_notes.append(
                    f"compulsory-rescue: cleared {len(bundle)} lower-priority "
                    f"session(s) on {ctx.date} for {comp_exp.priority} "
                    f"{comp_exp.kind}. Re-added mobility: "
                    f"{len(readded_mobility_ids)}."
                )
                for evicted_p in bundle:
                    if evicted_p.exposure_id in readded_mobility_ids:
                        continue
                    remaining_unfilled.append(Unfilled(
                        exposure_id=evicted_p.exposure_id,
                        objective_id=evicted_p.objective_id,
                        kind=evicted_p.kind,
                        priority=evicted_p.priority,
                        reason_code="displaced_by_compulsory_rescue",
                        human_reason=(
                            f"{evicted_p.priority} {evicted_p.kind} on {ctx.date} "
                            f"was evicted to make room for compulsory "
                            f"{comp_exp.priority} {comp_exp.kind} (Iter 131c bundle rescue)"
                        ),
                        candidate_hint_dates=[],
                    ))
                rescued = True
                break
            if not rescued:
                remaining_unfilled.append(uf)
        unfilled = remaining_unfilled

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
