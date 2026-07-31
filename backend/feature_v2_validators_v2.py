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
    client_profile: Optional[dict] = None,
    session_specs: Optional[dict[str, dict]] = None,
    weeks: int = 0,
) -> ProgrammeValidation:
    """Enforce programme-level invariants:
       * KEY objectives not silently missing         → ERROR
       * IMPORTANT objectives with any missing quota → ERROR (needs coach review)
       * SUPPORTING missing                          → WARNING
       * OPTIONAL missing                            → info only
       * no duplicate exposures on same day
       * no more than key/hard cap per week
       * no forbidden sequence in placements
       * exposure numbering monotonic BY DATE per objective_id
       * strength weekly cap not exceeded
    """
    issues: list[Issue] = []

    # ---- Quota report -----------------------------------------------------
    placed_by_kind: dict[str, int] = {}
    for p in placements:
        placed_by_kind[p.kind] = placed_by_kind.get(p.kind, 0) + 1
    required_by_kind: dict[str, int] = {}
    priority_by_kind: dict[str, str] = {}
    for e in demand.required_exposures:
        required_by_kind[e.kind] = required_by_kind.get(e.kind, 0) + 1
        priority_by_kind[e.kind] = e.priority.upper()

    # ---- Unfilled by priority --------------------------------------------
    unfilled_key: list[str] = []
    unfilled_important: list[str] = []
    unfilled_supporting: list[str] = []
    unfilled_optional: list[str] = []
    for u in unfilled:
        pr = u.priority.upper()
        if pr == "KEY":
            unfilled_key.append(f"{u.kind} ({u.reason_code})")
            issues.append(Issue("key_unfilled", "error",
                                f"KEY {u.kind} could not be placed — {u.human_reason}"))
        elif pr == "IMPORTANT":
            unfilled_important.append(f"{u.kind} ({u.reason_code})")
            issues.append(Issue("important_unfilled", "error",
                                f"IMPORTANT {u.kind} required but could not be placed — "
                                f"{u.human_reason} (coach review required)"))
        elif pr == "SUPPORTING":
            unfilled_supporting.append(f"{u.kind} ({u.reason_code})")
            issues.append(Issue("supporting_unfilled", "warning",
                                f"SUPPORTING {u.kind} could not be placed — {u.human_reason}"))
        else:
            unfilled_optional.append(f"{u.kind} ({u.reason_code})")
            # info only

    # ---- Additional: required quotas partially fulfilled ------------------
    # Even without an explicit Unfilled record, if placed_by_kind is less than
    # required_by_kind we surface it.
    for kind, req in required_by_kind.items():
        placed_n = placed_by_kind.get(kind, 0)
        if placed_n < req:
            deficit = req - placed_n
            pr = priority_by_kind.get(kind, "OPTIONAL")
            # Already covered per-exposure via unfilled loop — but if placed<req
            # AND no unfilled entry for that kind, log it as a data-integrity
            # warning (this should be rare).
            unfilled_kinds = {u.kind for u in unfilled}
            if kind not in unfilled_kinds:
                sev = "error" if pr in ("KEY", "IMPORTANT") else "warning"
                issues.append(Issue("quota_deficit", sev,
                                    f"{pr} {kind}: required {req}, placed {placed_n} "
                                    f"(deficit {deficit} — no unfilled record)"))

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

    # ---- Weekly hard/key/strength caps -----------------------------------
    from feature_v2_sport_configs import (
        session_load_bucket, is_strength_session, is_endurance_hard,
        LOAD_BUCKET_ENDURANCE_KEY, LOAD_BUCKET_ENDURANCE_HARD,
    )
    weekly_hard: dict[tuple[int, int], int] = {}
    weekly_key: dict[tuple[int, int], int] = {}
    weekly_strength_dates: dict[tuple[int, int], set] = {}
    for p in placements:
        wk = week_key(p.date)
        if is_endurance_hard(p.kind):
            weekly_hard[wk] = weekly_hard.get(wk, 0) + 1
        if p.key:
            weekly_key[wk] = weekly_key.get(wk, 0) + 1
        if is_strength_session(p.kind):
            weekly_strength_dates.setdefault(wk, set()).add(p.date)
    weekly_strength = {wk: len(dates) for wk, dates in weekly_strength_dates.items()}
    for wk, n in weekly_hard.items():
        if n > phase.hard_days_per_week_max:
            issues.append(Issue("weekly_endurance_hard_cap_exceeded", "error",
                                f"Week {wk}: {n} endurance hard sessions > {phase.hard_days_per_week_max}"))
    for wk, n in weekly_key.items():
        if n > phase.key_days_per_week_max:
            issues.append(Issue("weekly_key_cap_exceeded", "error",
                                f"Week {wk}: {n} key sessions > {phase.key_days_per_week_max}"))
    for wk, n in weekly_strength.items():
        if n > phase.strength_days_per_week_max:
            issues.append(Issue("weekly_strength_cap_exceeded", "error",
                                f"Week {wk}: {n} strength days > {phase.strength_days_per_week_max}"))

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

    # ---- Exposure identity: chronologically monotonic per objective_id ----
    # The exposure_number, when placements are sorted by DATE, must be 1..N.
    per_obj: dict[str, list[Placement]] = {}
    for p in placements:
        per_obj.setdefault(p.objective_id, []).append(p)
    for obj_id, group in per_obj.items():
        by_date = sorted(group, key=lambda p: p.date)
        seq_by_date = [p.exposure_number for p in by_date]
        expected = list(range(1, len(by_date) + 1))
        if seq_by_date != expected:
            issues.append(Issue("exposure_numbering_non_chronological", "error",
                                f"Objective {obj_id} exposure numbers not chronological — "
                                f"by date: {seq_by_date}, expected: {expected}"))

    # ---- No two placements on same date with same family ------------------
    seen_family_by_date: dict[tuple[str, _dt.date], str] = {}
    for p in placements:
        key = (session_family(p.kind), p.date)
        if key in seen_family_by_date:
            issues.append(Issue("same_day_family_duplicate", "warning",
                                f"{p.kind} and {seen_family_by_date[key]} same family on {p.date}"))
        else:
            seen_family_by_date[key] = p.kind

    # ---- Daily total minutes cap (defensive check against daily stacking) -
    daily_totals: dict[_dt.date, int] = {}
    for p in placements:
        daily_totals[p.date] = daily_totals.get(p.date, 0) + int(p.target_duration_min or 0)

    # ---- Iter 130g — goal-family structural validators (deterministic) ---
    profile = client_profile or {}
    goal_family = getattr(goal, "family", "") or ""
    goal_key = getattr(goal, "key", "") or ""
    weeks_seen = sorted({week_key(p.date) for p in placements})
    n_weeks = max(1, weeks or len(weeks_seen))

    # Running-family: Long Run present each week + minimum 3 runs/week when
    # roster allows + strength survives.
    if goal_family == "running":
        run_kinds = {"run_easy", "run_long", "run_tempo", "run_threshold",
                      "run_intervals", "run_vo2", "run_marathon_pace",
                      "run_race_pace", "run_strides", "run_recovery"}
        strength_kinds = {"strength_full_body", "strength_upper", "strength_lower",
                           "strength_push", "strength_pull", "strength_maintenance"}
        # Long Run per week
        wk_longrun: dict[tuple[int, int], int] = {}
        wk_runs: dict[tuple[int, int], int] = {}
        wk_strength: dict[tuple[int, int], int] = {}
        for p in placements:
            wk = week_key(p.date)
            if p.kind == "run_long":
                wk_longrun[wk] = wk_longrun.get(wk, 0) + 1
            if p.kind in run_kinds:
                wk_runs[wk] = wk_runs.get(wk, 0) + 1
            if p.kind in strength_kinds:
                wk_strength[wk] = wk_strength.get(wk, 0) + 1

        # A phase MAY not require a long run (race_week etc.) — only enforce
        # when the phase quota lists run_long with MIN >= 1 OR non-skippable.
        long_run_expected = any(
            q.kind == "run_long" and (q.exposures_per_week[0] > 0
                                        or not q.can_skip_if_missed)
            for q in phase.quotas
        )
        for wk in weeks_seen:
            if long_run_expected and wk_longrun.get(wk, 0) == 0:
                issues.append(Issue("marathon_long_run_missing", "error",
                                    f"Week {wk}: Long Run missing — KEY anchor "
                                    f"for {goal_key}"))
        # Three-run structure — only enforce if phase's aggregate run MIN is >= 3
        run_min_per_week = sum(int(q.exposures_per_week[0])
                                for q in phase.quotas if q.kind in run_kinds
                                and q.exposures_per_week[0] >= 1)
        # promote fractional KEY MIN to 1 for the sum
        run_min_per_week += sum(1 for q in phase.quotas if q.kind in run_kinds
                                and q.priority.upper() == "KEY"
                                and 0 < q.exposures_per_week[0] < 1)
        if run_min_per_week >= 3:
            for wk in weeks_seen:
                if wk_runs.get(wk, 0) < 3:
                    issues.append(Issue("weekly_run_count_low", "warning",
                                        f"Week {wk}: only {wk_runs.get(wk, 0)} run(s) "
                                        f"(phase expects ≥ {run_min_per_week}). Coach "
                                        f"should confirm roster prevented a third run."))
        # Strength survives when the phase quota lists strength with MIN >= 1
        strength_min = sum(int(q.exposures_per_week[0]) for q in phase.quotas
                            if q.kind in strength_kinds)
        if strength_min >= 1:
            for wk in weeks_seen:
                if wk_strength.get(wk, 0) == 0:
                    issues.append(Issue("marathon_strength_dropped", "warning",
                                        f"Week {wk}: no strength session placed — "
                                        f"phase MIN={strength_min}. Coach should confirm "
                                        f"a training day was not available."))
        # Forbidden: heavy lower-body strength immediately before Long Run
        long_run_dates = {p.date for p in placements if p.kind == "run_long"}
        for p in placements:
            if p.kind not in ("strength_lower", "strength_full_body"):
                continue
            next_day = p.date + _dt.timedelta(days=1)
            if next_day in long_run_dates:
                issues.append(Issue("strength_before_long_run", "warning",
                                    f"{p.kind}@{p.date} → Long Run@{next_day} "
                                    f"— avoid demanding lower-body work "
                                    f"immediately before the Long Run."))

    # Fat-loss with running excluded: no run_* sessions + 3 strength/week
    # when roster allows + post-workout cardio present.
    if goal_key == "strength.fat_loss":
        dislikes_running = bool(profile.get("dislikes_running")) or (
            str(profile.get("cardio_preference") or "").lower()
            in ("elliptical", "rower", "recumbent_bike", "incline_walk",
                "walk", "bike", "stationary_bike")
        )
        strength_kinds = {"strength_full_body", "strength_upper", "strength_lower",
                           "strength_push", "strength_pull", "strength_maintenance"}
        cardio_kinds = {"aerobic_z2", "conditioning_mixed", "conditioning_intervals",
                         "bike_easy", "walk_z2"}
        run_kinds = {"run_easy", "run_long", "run_tempo", "run_threshold",
                      "run_intervals", "run_vo2", "run_marathon_pace",
                      "run_race_pace", "run_strides", "run_recovery"}
        if dislikes_running:
            for p in placements:
                if p.kind in run_kinds:
                    issues.append(Issue("running_prescribed_despite_preference",
                                        "error",
                                        f"{p.kind}@{p.date} — client preference "
                                        f"excludes running. Cardio must resolve to "
                                        f"a low-impact modality."))
        # 3 strength / week required when phase has strength MIN >= 2 or 3
        wk_strength: dict[tuple[int, int], int] = {}
        wk_cardio: dict[tuple[int, int], int] = {}
        for p in placements:
            wk = week_key(p.date)
            if p.kind in strength_kinds:
                wk_strength[wk] = wk_strength.get(wk, 0) + 1
            if p.kind in cardio_kinds:
                wk_cardio[wk] = wk_cardio.get(wk, 0) + 1
        strength_min = 0
        for q in phase.quotas:
            if q.kind in strength_kinds:
                lo = q.exposures_per_week[0]
                if q.priority.upper() == "KEY" and 0 < lo < 1:
                    strength_min += 1
                else:
                    strength_min += int(lo)
        for wk in weeks_seen:
            if strength_min >= 2 and wk_strength.get(wk, 0) < strength_min:
                issues.append(Issue("fatloss_strength_count_low", "warning",
                                    f"Week {wk}: only {wk_strength.get(wk, 0)} "
                                    f"strength session(s) (phase MIN={strength_min}). "
                                    f"Coach should confirm roster prevented more."))
            if wk_cardio.get(wk, 0) == 0 and strength_min >= 1:
                issues.append(Issue("fatloss_cardio_missing", "warning",
                                    f"Week {wk}: no cardio session placed. "
                                    f"Post-workout cardio expected on lifting days."))

        # Full-body A/B/C identity check — sessions in the same week should
        # NOT emit identical exercise anchor sets. Session specs indexed
        # by exposure_id.
        if session_specs:
            per_week_specs: dict[tuple[int, int], list[dict]] = {}
            for p in placements:
                if p.kind != "strength_full_body":
                    continue
                spec = session_specs.get(p.exposure_id) or {}
                per_week_specs.setdefault(week_key(p.date), []).append(spec)
            for wk, specs in per_week_specs.items():
                if len(specs) < 2:
                    continue
                # Compare anchor exercise name-set across sessions.
                anchor_sig = []
                for s in specs:
                    exs = ((s.get("payload") or {}).get("exercises") or [])
                    sig = tuple(sorted(
                        ex.get("name", "") for ex in exs
                        if str(ex.get("role", "")).startswith("primary_")
                    ))
                    anchor_sig.append(sig)
                if len(set(anchor_sig)) < len(anchor_sig):
                    issues.append(Issue("fullbody_sessions_identical",
                                        "warning",
                                        f"Week {wk}: full-body sessions share the "
                                        f"same anchor exercises. Full Body A/B/C "
                                        f"rotation may not be engaging."))

    # ---- Iter 130g — full-block progression check --------------------------
    # For each objective placed across ≥2 weeks, at least one of duration or
    # exposure count should change. Skip strength (per-week RPE progression
    # is captured in payload.progression, not target_duration).
    if session_specs and len(weeks_seen) >= 2:
        per_obj_by_week: dict[str, dict[tuple[int, int], list[Placement]]] = {}
        for p in placements:
            per_obj_by_week.setdefault(p.objective_id, {}).setdefault(
                week_key(p.date), []).append(p)
        _NON_PROGRESSING_KINDS = {"rest", "mobility", "recovery",
                                   "travel_recovery", "activation"}
        for obj_id, weeks_map in per_obj_by_week.items():
            if len(weeks_map) < 2:
                continue
            sample = next(iter(weeks_map.values()))[0]
            if sample.kind in _NON_PROGRESSING_KINDS:
                continue
            weekly_max_dur = [max((int(p.target_duration_min) for p in placements_w),
                                    default=0)
                                for placements_w in weeks_map.values()]
            weekly_counts = [len(placements_w) for placements_w in weeks_map.values()]
            all_same_dur = len(set(weekly_max_dur)) <= 1
            all_same_count = len(set(weekly_counts)) <= 1
            # Strength kinds progress via RPE (payload.progression), not duration
            strength_prefix = sample.kind.startswith("strength_")
            if all_same_dur and all_same_count and not strength_prefix:
                issues.append(Issue("progression_flat", "warning",
                                    f"{sample.kind}: duration and count identical "
                                    f"across weeks — no progression detected."))

    # ---- Report -----------------------------------------------------------
    quota_report = {
        "required_by_kind": required_by_kind,
        "placed_by_kind": placed_by_kind,
        "priority_by_kind": priority_by_kind,
        "unfilled_total": len(unfilled),
        "unfilled_key": unfilled_key,
        "unfilled_important": unfilled_important,
        "unfilled_supporting": unfilled_supporting,
        "unfilled_optional": unfilled_optional,
        "weekly_hard": {str(k): v for k, v in weekly_hard.items()},
        "weekly_key": {str(k): v for k, v in weekly_key.items()},
        "weekly_strength": {str(k): v for k, v in weekly_strength.items()},
        "daily_totals_min": {d.isoformat(): v for d, v in daily_totals.items()},
    }
    ok = not any(i.severity == "error" for i in issues)
    return ProgrammeValidation(ok=ok, issues=issues, quota_report=quota_report)


__all__ = [
    "Issue", "SessionValidation", "ProgrammeValidation",
    "validate_session", "validate_programme",
]
