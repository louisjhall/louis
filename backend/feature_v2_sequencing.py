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
    session_kind_meta,
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
        n = 0
        for p in self.placements:
            iso = p.date.isocalendar()
            if iso[0] == iso_year and iso[1] == iso_week and is_hard_session(p.kind):
                n += 1
        return n

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
    min_opportunity_by_priority: Optional[dict[str, int]] = None,
) -> PlacementCheck:
    """Would placing `kind` on `date` violate any of:
       * hard-day cap for the ISO week
       * key-day cap for the ISO week
       * min recovery hours for this session family
       * forbidden sequence with the previous/next placement
       * consecutive training days cap
       * opportunity floor for this priority
       * duplicate placement on same date (unless mobility + activation etc.)
    """
    meta = session_kind_meta(kind)
    hard = bool(meta.get("hard"))
    key = is_key_intensity(kind)
    family = session_family(kind)

    # ---- Priority-based opportunity floor
    floors = min_opportunity_by_priority or {
        "KEY": 55, "IMPORTANT": 35, "SUPPORTING": 25, "OPTIONAL": 20,
    }
    floor = floors.get(priority.upper(), 25)
    if day_ctx_opportunity < floor and kind != "rest":
        return PlacementCheck(
            False, "opportunity_below_floor",
            f"Opportunity {day_ctx_opportunity} < floor {floor} for {priority}",
        )

    # ---- Weekly caps
    wk = week_key(date)
    if hard:
        if plan.hard_days_in_week(*wk) >= phase.hard_days_per_week_max:
            return PlacementCheck(
                False, "weekly_hard_cap",
                f"Week already has {phase.hard_days_per_week_max} hard days",
            )
    if key:
        if plan.key_days_in_week(*wk) >= phase.key_days_per_week_max:
            return PlacementCheck(
                False, "weekly_key_cap",
                f"Week already has {phase.key_days_per_week_max} key day(s)",
            )

    # ---- Same-day conflict — reject if another placement of the same family
    same_day = plan.by_date(date)
    for p in same_day:
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
        # Two HARD sessions on the same day — refuse
        if hard and is_hard_session(p.kind):
            return PlacementCheck(
                False, "same_day_two_hards",
                f"HARD {p.kind} already placed on {date}",
            )

    # ---- Min recovery from same family
    min_rec = session_recovery_hours(kind, goal.key, default=24)
    last = plan.last_of_family(family, before=date)
    if last:
        gap_h = (date - last.date).days * 24
        if gap_h < min_rec:
            return PlacementCheck(
                False, "insufficient_family_recovery",
                f"{gap_h}h since previous {family} < required {min_rec}h",
            )
    # Also check the NEXT of family (in case we're placing between two)
    nxt = plan.next_of_family(family, after=date)
    if nxt:
        gap_h = (nxt.date - date).days * 24
        if gap_h < min_rec:
            return PlacementCheck(
                False, "insufficient_family_recovery_next",
                f"Next {family} in {gap_h}h < required {min_rec}h",
            )

    # ---- Forbidden sequences (D-1 and D+1)
    for offset in (-1, +1):
        neighbour_date = date + _dt.timedelta(days=offset)
        for p in plan.by_date(neighbour_date):
            if offset == -1:
                # p happened yesterday → check (p.kind → kind)
                if is_forbidden_sequence(p.kind, kind, goal.key):
                    return PlacementCheck(
                        False, "forbidden_sequence",
                        f"{p.kind} on {p.date} → {kind} on {date} forbidden",
                    )
            else:
                # p tomorrow → check (kind → p.kind)
                if is_forbidden_sequence(kind, p.kind, goal.key):
                    return PlacementCheck(
                        False, "forbidden_sequence",
                        f"{kind} on {date} → {p.kind} on {p.date} forbidden",
                    )

    # ---- Two-day-out KEY spacing safeguard
    # If placing a KEY, ensure no KEY within 48h either side (regardless of family).
    if key:
        for offset in (-2, -1, +1, +2):
            neighbour = date + _dt.timedelta(days=offset)
            for p in plan.by_date(neighbour):
                if p.key:
                    gap_h = abs(offset) * 24
                    if gap_h < 48:
                        return PlacementCheck(
                            False, "key_spacing_48h",
                            f"KEY {p.kind} on {p.date} within 48h",
                        )

    # ---- Consecutive-training-days cap
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
