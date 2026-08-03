"""
CrewFit V2 Engine V2 — Sequencing Engine
=========================================

Every session placement decision must consider what came BEFORE and what is
coming AFTER — not only the day itself. This module is the sole authority on
"is X on date D compatible with the current placement plan?"

Public API:

    validate_placement(kind, date, plan, goal_key, phase_spec, day_ctx)
        → PlacementCheck(ok, reason_code, human_reason, alternatives_hint)

    apply_placement(kind, date, plan, exposure_id)
        → mutates the plan in place, appending the placement

    week_key(date) → (iso_year, iso_week)   for weekly-cap accounting

The scheduler NEVER writes to placement state except via this module.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Optional

from feature_v2_sport_configs import (
    GoalConfig, PhaseSpec, QuotaRule,
    is_hard_session, is_key_intensity, session_family,
    is_forbidden_sequence, session_recovery_hours,
    session_kind_meta, session_load_bucket, is_strength_session,
    is_endurance_hard,
    LOAD_BUCKET_STRENGTH_HARD, LOAD_BUCKET_ENDURANCE_HARD,
    LOAD_BUCKET_ENDURANCE_KEY, LOAD_BUCKET_REST,
    LOAD_BUCKET_EASY, LOAD_BUCKET_RECOVERY, LOAD_BUCKET_MODERATE,
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Placement:
    """A single scheduled exposure inside a plan-in-progress."""
    exposure_id: str
    objective_id: str
    kind: str
    date: _dt.date
    priority: str
    exposure_number: int   # monotonic within (objective_id)
    intensity_class: str
    target_duration_min: int
    intensity_target: str
    key: bool


@dataclass
class PlacementPlan:
    """The in-progress schedule of placements. Never a persisted document —
    used only by the scheduler to build up a coherent week/month."""
    placements: list[Placement] = field(default_factory=list)

    def by_date(self, d: _dt.date) -> list[Placement]:
        return [p for p in self.placements if p.date == d]

    def in_range(self, start: _dt.date, end: _dt.date) -> list[Placement]:
        return [p for p in self.placements if start <= p.date <= end]

    def last_of_family(self, family: str, before: _dt.date) -> Optional[Placement]:
        cands = [p for p in self.placements
                 if session_family(p.kind) == family and p.date < before]
        return max(cands, key=lambda p: p.date) if cands else None

    def next_of_family(self, family: str, after: _dt.date) -> Optional[Placement]:
        cands = [p for p in self.placements
                 if session_family(p.kind) == family and p.date > after]
        return min(cands, key=lambda p: p.date) if cands else None

    def hard_days_in_week(self, iso_year: int, iso_week: int) -> int:
        """Count ENDURANCE hard placements in a given ISO week.

        Strength placements do NOT contribute here — they count against the
        dedicated `strength_days_per_week_max` bucket (see
        `strength_days_in_week`).
        """
        n = 0
        for p in self.placements:
            iso = p.date.isocalendar()
            if iso[0] == iso_year and iso[1] == iso_week and is_endurance_hard(p.kind):
                n += 1
        return n

    def strength_days_in_week(self, iso_year: int, iso_week: int) -> int:
        """Count distinct DATES with a strength placement in the ISO week."""
        dates = set()
        for p in self.placements:
            iso = p.date.isocalendar()
            if iso[0] == iso_year and iso[1] == iso_week and is_strength_session(p.kind):
                dates.add(p.date)
        return len(dates)

    def key_days_in_week(self, iso_year: int, iso_week: int) -> int:
        n = 0
        for p in self.placements:
            iso = p.date.isocalendar()
            if iso[0] == iso_year and iso[1] == iso_week and p.key:
                n += 1
        return n

    def consecutive_training_days_around(self, d: _dt.date) -> int:
        """Length of the training streak that would exist if a session were
        placed on `d`. Walks back and forward from `d` counting days with
        placements OR duty-training combined."""
        days_with = {p.date for p in self.placements}
        days_with.add(d)
        n = 1
        cur = d - _dt.timedelta(days=1)
        while cur in days_with:
            n += 1
            cur -= _dt.timedelta(days=1)
        cur = d + _dt.timedelta(days=1)
        while cur in days_with:
            n += 1
            cur += _dt.timedelta(days=1)
        return n

    def exposure_number_for(self, objective_id: str) -> int:
        """Return the NEXT exposure number for this objective (1-indexed)."""
        n = 0
        for p in self.placements:
            if p.objective_id == objective_id:
                n = max(n, p.exposure_number)
        return n + 1

    def scheduled_minutes_on(self, d: _dt.date) -> int:
        """Sum of `target_duration_min` across placements on `d`."""
        return sum(int(p.target_duration_min or 0) for p in self.placements if p.date == d)

    def distinct_training_dates_in_week(self, iso_year: int, iso_week: int) -> int:
        dates = set()
        for p in self.placements:
            iso = p.date.isocalendar()
            if iso[0] == iso_year and iso[1] == iso_week:
                dates.add(p.date)
        return len(dates)


@dataclass
class PlacementCheck:
    ok: bool
    reason_code: str = "ok"
    human_reason: str = ""
    alternatives_hint: tuple[str, ...] = ()


def week_key(d: _dt.date) -> tuple[int, int]:
    iso = d.isocalendar()
    return (iso[0], iso[1])


# ---------------------------------------------------------------------------
# validate_placement — the sole gatekeeper
# ---------------------------------------------------------------------------

def validate_placement(
    kind: str,
    date: _dt.date,
    plan: PlacementPlan,
    goal: GoalConfig,
    phase: PhaseSpec,
    day_ctx_burden: int,
    day_ctx_opportunity: int,
    priority: str,
    target_duration_min: int = 0,
    daily_time_cap_min: Optional[int] = None,
    min_opportunity_by_priority: Optional[dict[str, int]] = None,
    allow_support_stacking: bool = True,
) -> PlacementCheck:
    """Would placing `kind` on `date` violate any of:
       * ENDURANCE hard-day cap for the ISO week
       * STRENGTH days cap for the ISO week (separate bucket)
       * key-day cap for the ISO week
       * min recovery hours for this session family
       * forbidden sequence with the previous/next placement (goal-configured)
       * consecutive training days cap
       * opportunity floor for this priority
       * duplicate placement on same date (same family)
       * TOTAL DAILY MINUTES exceeding daily_time_cap_min
       * daily "hardness" (two hard sessions on the same day)
    Support (mobility / activation / recovery) sessions MAY stack on the same
    day as another session if:
        * allow_support_stacking is True
        * the combined day minutes stay within daily_time_cap_min
        * they are NOT the same family
    """
    meta = session_kind_meta(kind)
    bucket = session_load_bucket(kind)
    endurance_hard = bucket in (LOAD_BUCKET_ENDURANCE_KEY, LOAD_BUCKET_ENDURANCE_HARD)
    strength_hard = bucket == LOAD_BUCKET_STRENGTH_HARD
    is_strength = is_strength_session(kind)
    is_support = bucket in (LOAD_BUCKET_EASY, LOAD_BUCKET_RECOVERY)  # mobility/activation/recovery
    key = is_key_intensity(kind)
    family = session_family(kind)

    # ---- Priority-based opportunity floor
    floors = min_opportunity_by_priority or {
        "KEY": 55, "IMPORTANT": 35, "SUPPORTING": 25, "OPTIONAL": 20,
    }
    floor = floors.get(priority.upper(), 25)
    # Support sessions stacking on a day that ALREADY has a placement do NOT
    # need to clear the day's opportunity floor — the anchor session already did.
    same_day_existing = plan.by_date(date)
    stacking_on_existing = bool(same_day_existing) and is_support and allow_support_stacking
    if not stacking_on_existing:
        if day_ctx_opportunity < floor and kind != "rest":
            return PlacementCheck(
                False, "opportunity_below_floor",
                f"Opportunity {day_ctx_opportunity} < floor {floor} for {priority}",
            )

    # ---- Weekly caps ------------------------------------------------------
    wk = week_key(date)
    if endurance_hard:
        if plan.hard_days_in_week(*wk) >= phase.hard_days_per_week_max:
            return PlacementCheck(
                False, "weekly_endurance_hard_cap",
                f"Week already has {phase.hard_days_per_week_max} endurance hard days",
            )
    if is_strength:
        # Counts ALL strength kinds (hard + moderate/maintenance/support) against
        # the weekly cap — matches feature_v2_validators_v2.is_strength_session,
        # which flags weekly_strength_cap_exceeded for every strength kind
        # regardless of hard/moderate. Previously this only fired for
        # bucket==strength_hard, so maintenance/support sessions could stack
        # past the cap during placement and only get caught later by the
        # validator, producing a week the scheduler itself thought was valid.
        #
        # Check strength cap only if THIS date is not already a strength day
        # (multiple strength placements on same date is disallowed by same-day
        # family conflict below anyway, but this keeps the count clean).
        strength_days = plan.strength_days_in_week(*wk)
        already_strength_today = any(
            is_strength_session(p.kind) for p in same_day_existing
        )
        if not already_strength_today and strength_days >= phase.strength_days_per_week_max:
            return PlacementCheck(
                False, "weekly_strength_cap",
                f"Week already has {phase.strength_days_per_week_max} strength days",
            )
    if key:
        if plan.key_days_in_week(*wk) >= phase.key_days_per_week_max:
            return PlacementCheck(
                False, "weekly_key_cap",
                f"Week already has {phase.key_days_per_week_max} key day(s)",
            )

    # ---- Same-day conflicts ----------------------------------------------
    for p in same_day_existing:
        if session_family(p.kind) == family:
            return PlacementCheck(
                False, "same_day_family_conflict",
                f"{p.kind} already placed on {date}",
            )
        # Two KEY sessions on the same day is never acceptable
        if key and p.key:
            return PlacementCheck(
                False, "same_day_two_keys",
                f"KEY {p.kind} already placed on {date}",
            )
        # Two ENDURANCE-HARD sessions on the same day — refuse
        if endurance_hard and is_endurance_hard(p.kind):
            return PlacementCheck(
                False, "same_day_two_endurance_hards",
                f"Endurance hard {p.kind} already placed on {date}",
            )
        # Endurance-hard + strength-hard same day is aggressive — refuse unless
        # phase explicitly allows it via concurrent_notes containing "same_day_ok"
        if endurance_hard and is_strength_session(p.kind):
            return PlacementCheck(
                False, "same_day_endurance_and_strength",
                f"Strength {p.kind} already placed on {date}",
            )
        if strength_hard and is_endurance_hard(p.kind):
            return PlacementCheck(
                False, "same_day_endurance_and_strength",
                f"Endurance hard {p.kind} already placed on {date}",
            )
        # Two strength-hard sessions same day → refuse
        if strength_hard and is_strength_session(p.kind):
            return PlacementCheck(
                False, "same_day_two_strengths",
                f"Strength {p.kind} already placed on {date}",
            )
        # Non-support session stacking on top of another non-support is heavy.
        # Only support (mobility/activation/recovery) may stack alongside.
        if not is_support and bucket == LOAD_BUCKET_MODERATE:
            # e.g. a run_easy stacking with another run_easy family is already
            # blocked above; but stacking a run_easy on a day that already has
            # a KEY or HARD anchor is allowed provided daily minutes fit.
            pass

    # ---- Daily total minutes cap ------------------------------------------
    if daily_time_cap_min is not None and kind != "rest":
        already = plan.scheduled_minutes_on(date)
        prospective = int(target_duration_min or 0)
        if prospective <= 0:
            # If target unknown, use a conservative estimate: 30 min for support,
            # else the day's cap itself so it fails-safe when cap is tight.
            prospective = 30 if is_support else max(30, int(daily_time_cap_min * 0.75))
        if already + prospective > int(daily_time_cap_min):
            return PlacementCheck(
                False, "daily_time_cap_exceeded",
                f"Daily minutes would be {already + prospective} > cap {daily_time_cap_min}",
            )

    # ---- Min recovery from same family ------------------------------------
    min_rec = session_recovery_hours(kind, goal.key, default=24)
    last = plan.last_of_family(family, before=date)
    if last:
        gap_h = (date - last.date).days * 24
        if gap_h < min_rec:
            return PlacementCheck(
                False, "insufficient_family_recovery",
                f"{gap_h}h since previous {family} < required {min_rec}h",
            )
    nxt = plan.next_of_family(family, after=date)
    if nxt:
        gap_h = (nxt.date - date).days * 24
        if gap_h < min_rec:
            return PlacementCheck(
                False, "insufficient_family_recovery_next",
                f"Next {family} in {gap_h}h < required {min_rec}h",
            )

    # ---- Forbidden sequences (D-1 and D+1) --------------------------------
    for offset in (-1, +1):
        neighbour_date = date + _dt.timedelta(days=offset)
        for p in plan.by_date(neighbour_date):
            if offset == -1:
                if is_forbidden_sequence(p.kind, kind, goal.key):
                    return PlacementCheck(
                        False, "forbidden_sequence",
                        f"{p.kind} on {p.date} → {kind} on {date} forbidden",
                    )
            else:
                if is_forbidden_sequence(kind, p.kind, goal.key):
                    return PlacementCheck(
                        False, "forbidden_sequence",
                        f"{kind} on {date} → {p.kind} on {p.date} forbidden",
                    )

    # ---- Two-day-out KEY spacing safeguard (cross-family only) -----------
    # Iter 131a: this rule previously blocked ANY KEY within 48h of ANY other
    # KEY, which prevented legitimate 3× strength_full weeks and near-consecutive
    # A/B/C sessions. Same-family KEY-to-KEY spacing is now the exclusive
    # responsibility of `session_family_recovery_hours` (the goal's authoritative
    # same-family control). This safeguard now only fires when the two KEYs are
    # of DIFFERENT families (e.g. strength_full KEY beside a run_long KEY).
    if key:
        this_family = session_family(kind)
        for offset in (-2, -1, +1, +2):
            neighbour = date + _dt.timedelta(days=offset)
            for p in plan.by_date(neighbour):
                if p.key and session_family(p.kind) != this_family:
                    gap_h = abs(offset) * 24
                    if gap_h < 48:
                        return PlacementCheck(
                            False, "key_spacing_48h_cross_family",
                            f"KEY {p.kind} on {p.date} within 48h (cross-family)",
                        )

    # ---- Consecutive-training-days cap ------------------------------------
    if plan.consecutive_training_days_around(date) > phase.consecutive_training_days_max:
        return PlacementCheck(
            False, "consecutive_training_days_cap",
            f"Would exceed {phase.consecutive_training_days_max} consecutive training days",
        )

    return PlacementCheck(True, "ok", "")


def apply_placement(
    plan: PlacementPlan,
    *,
    exposure_id: str,
    objective_id: str,
    kind: str,
    date: _dt.date,
    priority: str,
    intensity_target: str,
    target_duration_min: int,
    exposure_number: Optional[int] = None,
) -> Placement:
    if exposure_number is None:
        exposure_number = plan.exposure_number_for(objective_id)
    meta = session_kind_meta(kind)
    p = Placement(
        exposure_id=exposure_id,
        objective_id=objective_id,
        kind=kind,
        date=date,
        priority=priority,
        exposure_number=exposure_number,
        intensity_class=meta.get("intensity_class") or "moderate",
        target_duration_min=int(target_duration_min),
        intensity_target=intensity_target,
        key=is_key_intensity(kind),
    )
    plan.placements.append(p)
    return p


__all__ = [
    "Placement", "PlacementPlan", "PlacementCheck",
    "validate_placement", "apply_placement", "week_key",
]
