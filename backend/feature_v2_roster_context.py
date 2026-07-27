"""
CrewFit V2 Engine V2 — Rolling Roster Context (WHEN inputs)
============================================================

Replaces the previous isolated-day categorisation with a rolling 72h context
model. Every scheduling decision must consider WHAT HAPPENED BEFORE AND WHAT
IS COMING NEXT, not only the label on today.

Given the client's roster + schedule_days, this module computes for each
candidate date:

    DayContext(
        date,
        day_type,                 # raw roster label (home_day, layover, ...)
        duty_burden_score,        # 0..100  (rolling, contextual)
        training_opportunity,     # 0..100  (rolling, contextual)
        available_time_min,       # a CAP, never a prescription
        recommended_intensity_ceiling,  # rpe4 / rpe6 / rpe7 / rpe8 / any
        recovery_state,           # fresh / normal / accumulated / depleted
        recent_hard_days_48h,     # how many "hard" duties in past 48h
        upcoming_hard_days_48h,   # how many hard duties in next 48h
        sleep_opportunity,        # low / normal / good
        tz_shift_last_48h,        # absolute hours crossed recently
        layover_length_hours,     # if currently on layover
        reasons                   # ordered list of scoring rationale strings
    )

The output is pure data — no DB writes. Consumers (scheduler) MUST NOT modify
schedule_days off the back of this.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Categorical HINTS (not verdicts)
# ---------------------------------------------------------------------------
# These are starting points ONLY. The rolling context can override them.
# Layover arrival after a short 4h hop from a nearby city is not the same as
# layover arrival after a 14h ULR — this module distinguishes.

_BASELINE_BURDEN_HINT: dict[str, int] = {
    "layover_arrival":   55,
    "layover_departure": 45,
    "turnaround":        55,
    "flight":            50,
    "duty":              45,
    "standby":           30,
    "sim":               35,
    "training":          25,
    "medical":           20,
    "layover_full":      20,
    "layover":           25,
    "hotel":             20,
    "home_day":          8,
    "home":              8,
    "off":               3,
    "rest":              3,
    "day_off":           3,
    "leave":             0,
    "vacation":          0,
    "annual_leave":      0,
    "sickness":          0,
    "sick":              0,
    "sick_leave":        0,
}


def _resolve_day_type(day: dict) -> str:
    raw = day.get("day_type") or day.get("classification") or ""
    return str(raw).lower().strip()


def _iso_date(s) -> _dt.date:
    if isinstance(s, _dt.date):
        return s
    return _dt.date.fromisoformat(str(s)[:10])


def _duty_duration_min(duties: list[dict]) -> int:
    total = 0
    for d in duties or []:
        try:
            if d.get("duty_start_time") and d.get("duty_finish_time"):
                s = _dt.datetime.fromisoformat(d["duty_start_time"])
                f = _dt.datetime.fromisoformat(d["duty_finish_time"])
                mins = int((f - s).total_seconds() / 60)
                if mins < 0:
                    mins += 24 * 60
                total += mins
        except Exception:
            pass
    return total


def _has_ulr(duties: list[dict]) -> bool:
    for d in duties or []:
        if d.get("ulr"):
            return True
        n = (d.get("notes") or "").upper()
        if "ULR" in n or "ULTRA" in n:
            return True
    return False


def _sectors(duties: list[dict]) -> int:
    return sum(len(d.get("sectors") or []) for d in (duties or []))


def _report_hour(duties: list[dict]) -> Optional[int]:
    for d in duties or []:
        try:
            if d.get("report_time"):
                return _dt.datetime.fromisoformat(d["report_time"]).hour
        except Exception:
            pass
    return None


def _is_hard_duty(day: dict) -> bool:
    """Would this day itself leave the client fatigued for the next day?"""
    dt = _resolve_day_type(day)
    if dt in ("layover_arrival", "layover_departure", "turnaround", "flight", "duty"):
        return True
    if dt == "standby":
        return False
    return _duty_duration_min(day.get("duties") or []) > 8 * 60


# ---------------------------------------------------------------------------
# DayContext — the immutable per-date object every scheduler consumes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DayContext:
    date: _dt.date
    day_type: str
    duty_burden_score: int
    training_opportunity: int
    available_time_min: int
    recommended_intensity_ceiling: str
    recovery_state: str
    recent_hard_days_48h: int
    upcoming_hard_days_48h: int
    consecutive_duty_days: int
    sleep_opportunity: str
    tz_shift_last_48h: int
    layover_length_hours: int
    duty_duration_min_today: int
    reasons: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# The main computation
# ---------------------------------------------------------------------------

def build_day_contexts(schedule_days: list[dict]) -> list[DayContext]:
    """Given a list of raw schedule_day rows (V1 or V2 shape), compute rolling
    DayContext per date. Input list must be sortable by 'date'.

    Rolling window: 72h back + 48h forward.
    """
    if not schedule_days:
        return []
    sorted_days = sorted(schedule_days, key=lambda d: str(d.get("date", "")))
    by_date: dict[_dt.date, dict] = {}
    for d in sorted_days:
        try:
            by_date[_iso_date(d["date"])] = d
        except Exception:
            continue
    dates = sorted(by_date.keys())
    out: list[DayContext] = []
    for d in dates:
        raw = by_date[d]
        out.append(_context_for(d, raw, by_date))
    return out


def _context_for(date: _dt.date, raw: dict, by_date: dict[_dt.date, dict]) -> DayContext:
    day_type = _resolve_day_type(raw)
    duties = raw.get("duties") or []
    duty_min = _duty_duration_min(duties)

    # ---- Baseline hint ------------------------------------------------------
    burden = _BASELINE_BURDEN_HINT.get(day_type, 25)
    reasons: list[str] = [f"day_type={day_type} baseline_hint={burden}"]

    # ---- Rolling look-back (past 72h) --------------------------------------
    recent_hard = 0
    consecutive_duty = 0
    tz_shift = 0
    for delta in (1, 2, 3):
        prev = by_date.get(date - _dt.timedelta(days=delta))
        if not prev:
            continue
        p_type = _resolve_day_type(prev)
        if _is_hard_duty(prev) and delta <= 2:
            recent_hard += 1
        if p_type not in ("home_day", "home", "off", "rest", "day_off",
                          "leave", "vacation", "annual_leave"):
            consecutive_duty += 1
        else:
            # any home/off breaks the streak
            if delta == 1:
                consecutive_duty = 0
        try:
            tz_shift += abs(int(prev.get("tz_offset_from_base_hours") or 0))
        except Exception:
            pass

    # Own tz shift adds
    try:
        tz_shift += abs(int(raw.get("tz_offset_from_base_hours") or 0))
    except Exception:
        pass

    # ---- Rolling look-ahead (next 48h) -------------------------------------
    upcoming_hard = 0
    for delta in (1, 2):
        nxt = by_date.get(date + _dt.timedelta(days=delta))
        if not nxt:
            continue
        if _is_hard_duty(nxt):
            upcoming_hard += 1

    # ---- Additive load on TODAY -------------------------------------------
    if duty_min > 12 * 60:
        burden += 20; reasons.append(f"duty>12h +20")
    elif duty_min > 9 * 60:
        burden += 15; reasons.append(f"duty>9h +15")
    elif duty_min > 6 * 60:
        burden += 10; reasons.append(f"duty>6h +10")
    elif duty_min > 3 * 60:
        burden += 5;  reasons.append(f"duty>3h +5")

    if _has_ulr(duties):
        burden += 20; reasons.append("ULR +20")

    sc = _sectors(duties)
    if sc >= 3:
        burden += 10; reasons.append(f"{sc} sectors +10")
    elif sc == 2:
        burden += 5;  reasons.append("2 sectors +5")

    rh = _report_hour(duties)
    if rh is not None:
        if rh <= 5:
            burden += 10; reasons.append(f"early report {rh}h +10")
        elif rh <= 7:
            burden += 5;  reasons.append(f"early report {rh}h +5")

    # Prior recovery window
    prior_recovery = raw.get("recovery_window_hours_from_prior_duty")
    if isinstance(prior_recovery, (int, float)):
        if prior_recovery < 12:
            burden += 12; reasons.append(f"prior recovery {prior_recovery}h +12")
        elif prior_recovery < 18:
            burden += 6;  reasons.append(f"prior recovery {prior_recovery}h +6")

    # TZ shift carryover
    if tz_shift >= 12:
        burden += 15; reasons.append(f"tz shift {tz_shift}h +15")
    elif tz_shift >= 7:
        burden += 10; reasons.append(f"tz shift {tz_shift}h +10")
    elif tz_shift >= 4:
        burden += 5;  reasons.append(f"tz shift {tz_shift}h +5")

    # Recent hard days accumulate
    if recent_hard >= 2:
        burden += 10; reasons.append("2+ recent hard days +10")
    elif recent_hard == 1:
        burden += 5;  reasons.append("1 recent hard day +5")

    if consecutive_duty >= 4:
        burden += 8; reasons.append(f"consecutive duty streak {consecutive_duty} +8")
    elif consecutive_duty >= 3:
        burden += 4; reasons.append(f"consecutive duty streak {consecutive_duty} +4")

    # ---- Layover-specific adjustments --------------------------------------
    # A layover_arrival AFTER a short flight from a nearby city is much less
    # burden than after a ULR. If duty_min < 4h AND tz_shift < 3, downgrade.
    layover_length_hours = 0
    if day_type == "layover_arrival":
        if duty_min > 0 and duty_min < 4 * 60 and tz_shift < 3:
            burden -= 15
            reasons.append("short-hop layover -15")
        # Very late arrival kills sleep
        if rh is not None and rh >= 22:
            burden += 8
            reasons.append(f"late arrival {rh}h +8")
    if day_type == "layover_full":
        # Multi-night layover: check yesterday too was a layover
        prev = by_date.get(date - _dt.timedelta(days=1))
        if prev and _resolve_day_type(prev) in ("layover_full", "layover_arrival", "layover"):
            burden -= 5
            reasons.append("mid-stay layover -5")
            layover_length_hours = 48  # rough

    # Sickness/leave clamp
    if day_type in ("sickness", "sick", "sick_leave"):
        burden = 0
        reasons.append("sick clamp to 0")
    if day_type in ("leave", "vacation", "annual_leave"):
        burden = max(0, min(burden, 10))
        reasons.append("leave clamp ≤10")

    burden = max(0, min(100, burden))

    # ---- Opportunity computation ------------------------------------------
    # Categorical ceiling. This is the MAXIMUM opportunity permitted; rolling
    # signals push it further down but never up.
    opp_ceilings: dict[str, int] = {
        "layover_arrival":   45,
        "layover_departure": 35,
        "turnaround":        30,
        "flight":            35,
        "duty":              40,
        "standby":           60,
        "sim":               50,
        "training":          60,
        "medical":           45,
        "layover_full":      85,
        "layover":           75,
        "hotel":             75,
        "home_day":          95,
        "home":              95,
        "off":               100,
        "rest":              100,
        "day_off":           100,
        "leave":              90,
        "vacation":           90,
        "annual_leave":       90,
        "sickness":           0,
        "sick":               0,
        "sick_leave":         0,
    }
    ceiling = opp_ceilings.get(day_type, 60)
    # Burden bites from opportunity proportionally to intensity_class.
    opp = ceiling - int(burden * 0.55)

    # Rolling penalties
    if recent_hard >= 2:
        opp -= 10; reasons.append("recent hard streak → opp -10")
    if upcoming_hard >= 2:
        opp -= 8;  reasons.append("upcoming hard streak → opp -8")
    if tz_shift >= 8:
        opp -= 8;  reasons.append("tz jetlag → opp -8")
    if consecutive_duty >= 4:
        opp -= 6

    # Categorical FLOORS for rest-like days
    floors = {
        "home_day": 55, "home": 55,
        "off": 70, "rest": 70, "day_off": 70,
    }
    opp = max(floors.get(day_type, 0), opp)
    opp = max(0, min(100, opp))

    # ---- Available time (a CAP) -------------------------------------------
    # NOTE: This module doesn't know the client — a caller may want to
    # further clip via profile.max_home_minutes / time_layover_min etc.
    time_by_type: dict[str, int] = {
        "home_day": 120, "home": 120,
        "off": 150, "rest": 150, "day_off": 150,
        "leave": 120, "vacation": 120, "annual_leave": 120,
        "layover_full": 75, "layover": 60, "hotel": 60,
        "layover_arrival": 30, "layover_departure": 25, "turnaround": 20,
        "flight": 25, "duty": 30, "standby": 60, "sim": 40, "training": 45,
        "sickness": 0, "sick": 0, "sick_leave": 0,
    }
    avail = time_by_type.get(day_type, 45)
    if burden >= 75:
        avail = min(avail, 30)
    elif burden >= 55:
        avail = min(avail, 45)

    # ---- Intensity ceiling ------------------------------------------------
    if day_type in ("layover_arrival", "layover_departure", "turnaround"):
        rec_int = "rpe4"
    elif burden >= 75:
        rec_int = "rpe4"
    elif burden >= 55:
        rec_int = "rpe6"
    elif burden >= 30:
        rec_int = "rpe7"
    elif burden >= 10:
        rec_int = "rpe8"
    else:
        rec_int = "any"

    # ---- Recovery state ----------------------------------------------------
    if recent_hard >= 2 and burden >= 45:
        rec_state = "depleted"
    elif recent_hard >= 1 or burden >= 50:
        rec_state = "accumulated"
    elif consecutive_duty >= 3:
        rec_state = "accumulated"
    elif burden < 15 and recent_hard == 0:
        rec_state = "fresh"
    else:
        rec_state = "normal"

    # ---- Sleep opportunity -------------------------------------------------
    if day_type in ("off", "rest", "day_off", "home_day", "home", "leave",
                    "vacation", "annual_leave", "layover_full"):
        sleep = "good"
    elif day_type in ("standby", "layover", "hotel"):
        sleep = "normal"
    elif day_type in ("layover_arrival", "layover_departure", "turnaround",
                       "flight", "duty"):
        sleep = "low"
    else:
        sleep = "normal"

    return DayContext(
        date=date,
        day_type=day_type,
        duty_burden_score=int(burden),
        training_opportunity=int(opp),
        available_time_min=int(avail),
        recommended_intensity_ceiling=rec_int,
        recovery_state=rec_state,
        recent_hard_days_48h=recent_hard,
        upcoming_hard_days_48h=upcoming_hard,
        consecutive_duty_days=consecutive_duty,
        sleep_opportunity=sleep,
        tz_shift_last_48h=tz_shift,
        layover_length_hours=layover_length_hours,
        duty_duration_min_today=duty_min,
        reasons=tuple(reasons),
    )


# ---------------------------------------------------------------------------
# Convenience: emit derived fields back into a schedule_day dict for DB write
# ---------------------------------------------------------------------------

def context_to_derived(ctx: DayContext) -> dict:
    """Serialise a DayContext into the `derived` dict shape expected by the
    schedule_days collection. Downstream endpoints read this shape."""
    return {
        "duty_burden_score": ctx.duty_burden_score,
        "duty_burden_band": _band_from_score(ctx.duty_burden_score),
        "training_opportunity": ctx.training_opportunity,
        "recommended_intensity_ceiling": ctx.recommended_intensity_ceiling,
        "available_time_min": ctx.available_time_min,
        "recovery_state": ctx.recovery_state,
        "sleep_opportunity": ctx.sleep_opportunity,
        "recent_hard_days_48h": ctx.recent_hard_days_48h,
        "upcoming_hard_days_48h": ctx.upcoming_hard_days_48h,
        "consecutive_duty_days": ctx.consecutive_duty_days,
        "tz_shift_last_48h": ctx.tz_shift_last_48h,
        "duty_duration_min_today": ctx.duty_duration_min_today,
        "reasons": list(ctx.reasons),
    }


def _band_from_score(s: int) -> str:
    if s < 20:  return "light"
    if s < 50:  return "moderate"
    if s < 75:  return "heavy"
    return "extreme"


__all__ = ["DayContext", "build_day_contexts", "context_to_derived"]
