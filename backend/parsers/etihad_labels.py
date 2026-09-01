"""
Etihad — automatic day labelling + traffic-light training decisions
-------------------------------------------------------------------

Turns a parsed Etihad `ParsedDay` (see parsers/etihad.py) into a rich set of
labels and training decisions that the CrewFit programme generator (and coach
dashboard) can consume.

Outputs (per day):
  * label            — technical label, one of DAY_LABELS below
  * client_label     — simple, human-friendly label (never mentions AI)
  * training_colour  — "green" | "amber" | "red" | "black"
  * recommended      — list of allowed session categories
  * blocked          — list of explicitly forbidden session categories
  * equipment        — assumed available equipment for the day
  * recovery_risk    — 0.0 – 1.0 estimate of fatigue risk
  * reason           — one-line explanation ("Heavy flying day", etc.)
  * needs_review     — whether Louis or client needs to look at it
  * chain_flag       — 'post_night' / 'post_long_duty' when previous day was heavy

Design principle (from Louis's brief):
    Bad automatic labelling will create bad training plans. If unsure,
    label as NEEDS_REVIEW and escalate to Louis — never silently guess.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

DAY_LABELS = {
    "OFF_DAY",
    "REST_DAY",
    "ROSTERED_OFF",
    "STANDBY_DAY",
    "EARLY_DUTY",
    "NORMAL_DUTY",
    "LATE_DUTY",
    "NIGHT_DUTY",
    "OVERNIGHT_DUTY",
    "TURNAROUND_DUTY",
    "MULTI_SECTOR_DUTY",
    "LONG_DUTY",
    "LAYOVER_OUTBOUND",
    "LAYOVER_DAY",
    "LAYOVER_RETURN",
    "POST_NIGHT_RECOVERY",
    "POST_LONG_DUTY_RECOVERY",
    "UNKNOWN_UNAVAILABLE",
    "NEEDS_REVIEW",
}

# All session-category tokens the plan generator understands.
SESSION_CATS = {
    "main_strength", "hotel_strength", "bodyweight",
    "long_run", "easy_run", "intervals", "tempo",
    "mobility", "recovery_walk", "rest",
    "steps_only",
}


@dataclass
class DayDecision:
    date: str
    label: str = "OFF_DAY"
    client_label: str = "Free day"
    training_colour: str = "green"        # green | amber | red | black
    recommended: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    equipment: str = "any"                # any | hotel_or_bodyweight | none | needs_confirmation
    recovery_risk: float = 0.1            # 0=fresh, 1=exhausted
    reason: str = ""
    needs_review: bool = False
    chain_flag: Optional[str] = None      # post_night | post_long_duty


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _time_to_min(t: Optional[str]) -> Optional[int]:
    if not t or ":" not in t:
        return None
    try:
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _duty_length_hours(report: Optional[str], release: Optional[str]) -> Optional[float]:
    r0, r1 = _time_to_min(report), _time_to_min(release)
    if r0 is None or r1 is None:
        return None
    length = r1 - r0
    if length < 0:                     # crossed midnight
        length += 24 * 60
    return length / 60.0


# ---------------------------------------------------------------------------
# The core labelling function — one day at a time, then a second pass for chains.
# ---------------------------------------------------------------------------

def decide_day(day, prev_decision: Optional[DayDecision] = None) -> DayDecision:
    """Assign a label + training colour + recommendations to a single ParsedDay."""
    dec = DayDecision(date=day.date)
    dt = day.day_type

    # --------------------------- OFF / REST / ROFF ---------------------------
    if dt == "off":
        dec.label = "OFF_DAY"
        dec.client_label = "Free day"
        dec.training_colour = "green"
        dec.recommended = ["main_strength", "long_run", "easy_run", "intervals", "tempo", "mobility"]
        dec.reason = "Full day free — good main-training slot."
        return _apply_chain(dec, prev_decision)

    if dt == "rest":
        dec.label = "REST_DAY"
        dec.client_label = "Rest day"
        dec.training_colour = "green"
        dec.recommended = ["easy_run", "mobility", "recovery_walk", "hotel_strength"]
        dec.blocked = ["intervals", "long_run"]
        dec.reason = "Scheduled rest — keep training light if used."
        return _apply_chain(dec, prev_decision)

    if dt == "rostered_off":
        dec.label = "ROSTERED_OFF"
        dec.client_label = "Rostered off"
        dec.training_colour = "green"
        dec.recommended = ["main_strength", "long_run", "easy_run", "mobility"]
        dec.reason = "Rostered off — full training available."
        return _apply_chain(dec, prev_decision)

    # ------------------------------- STANDBY ---------------------------------
    if dt == "standby":
        dec.label = "STANDBY_DAY"
        dec.client_label = "Standby"
        dec.training_colour = "amber"
        dec.recommended = ["mobility", "bodyweight", "easy_run", "steps_only", "hotel_strength"]
        dec.blocked = ["long_run", "intervals", "main_strength"]
        # Iter200 · Home-based standby must NOT inherit hotel equipment
        # assumptions. Only outstation/airport standby (which we cannot
        # detect at this stage) would need "hotel_or_bodyweight". Default
        # to "any" so the client trains at home like any other day.
        dec.equipment = "any"
        dec.reason = "On standby — light/short session in case you're called."
        return _apply_chain(dec, prev_decision)

    # ------------------------------- UNKNOWN ---------------------------------
    if dt == "unknown":
        dec.label = "UNKNOWN_UNAVAILABLE"
        dec.client_label = "Unclear — needs your check"
        dec.training_colour = "black"
        dec.blocked = list(SESSION_CATS)
        dec.equipment = "none"
        dec.needs_review = True
        dec.reason = "Duty details unclear — confirm before we plan a session."
        return dec

    # ------------------------------- FLIGHTS ---------------------------------
    # By this point dt is one of: flight, multi_sector_flight, flight_to_layover,
    # layover_day, return_from_layover, overnight_flight, turnaround.
    report_min = _time_to_min(day.report_time)
    release_min = _time_to_min(day.release_time)
    duty_hours = _duty_length_hours(day.report_time, day.release_time)
    crosses_midnight = release_min is not None and report_min is not None and release_min < report_min

    # ---------- LAYOVER_DAY (inferred blank column inside pairing) ----------
    if dt == "layover_day":
        dec.label = "LAYOVER_DAY"
        dec.client_label = f"Layover day{f' in {day.layover_city}' if day.layover_city else ''}"
        dec.training_colour = "amber"
        dec.recommended = ["hotel_strength", "bodyweight", "easy_run", "mobility"]
        dec.blocked = ["main_strength", "intervals", "long_run"]
        dec.equipment = "hotel_or_bodyweight"
        dec.needs_review = True    # hotel gym unknown until client confirms
        dec.reason = "Layover day — hotel/bodyweight only (confirm hotel gym)."
        return _apply_chain(dec, prev_decision)

    # ---------- OVERNIGHT_DUTY ----------
    if dt == "overnight_flight" or crosses_midnight:
        dec.label = "OVERNIGHT_DUTY"
        dec.client_label = "Overnight duty"
        dec.training_colour = "red"
        dec.recommended = ["mobility", "recovery_walk"]
        dec.blocked = ["main_strength", "long_run", "intervals", "tempo", "easy_run"]
        dec.recovery_risk = 0.85
        dec.reason = "Overnight duty — no hard session tonight; recovery focus next day."
        return _apply_chain(dec, prev_decision)

    # ---------- TURNAROUND ----------
    if day.is_turnaround:
        dec.label = "TURNAROUND_DUTY"
        dec.client_label = "Heavy flying day"
        dec.training_colour = "red"
        dec.recommended = ["mobility"]
        dec.blocked = ["main_strength", "long_run", "intervals"]
        dec.recovery_risk = 0.7
        dec.reason = "Same-day turnaround — no hard session, mobility only."
        return _apply_chain(dec, prev_decision)

    # ---------- MULTI_SECTOR ----------
    if dt == "multi_sector_flight" or (day.sector_count and day.sector_count >= 2):
        dec.label = "MULTI_SECTOR_DUTY"
        dec.client_label = "Heavy flying day"
        dec.training_colour = "red"
        dec.recommended = ["mobility"]
        dec.blocked = ["main_strength", "long_run", "intervals", "tempo"]
        dec.recovery_risk = 0.75
        dec.reason = "Multiple sectors — no hard session, mobility only."
        return _apply_chain(dec, prev_decision)

    # ---------- LAYOVER_OUTBOUND ----------
    if dt == "flight_to_layover":
        dec.label = "LAYOVER_OUTBOUND"
        dec.client_label = f"Flying to {day.end_location or 'layover'}"
        dec.training_colour = "amber" if (duty_hours or 0) < 6 else "red"
        dec.recommended = ["mobility", "bodyweight"] if dec.training_colour == "red" else ["mobility", "bodyweight", "hotel_strength"]
        dec.blocked = ["main_strength", "long_run", "intervals"]
        dec.equipment = "hotel_or_bodyweight"
        dec.recovery_risk = 0.5
        dec.reason = "Outbound flight — light session only after arrival."
        return _apply_chain(dec, prev_decision)

    # ---------- LAYOVER_RETURN ----------
    if dt == "return_from_layover":
        late_arrival = (release_min or 0) > 21 * 60
        overnight = crosses_midnight or (report_min or 0) < 4 * 60
        dec.label = "LAYOVER_RETURN"
        dec.client_label = f"Return from {day.start_location or 'layover'}"
        dec.training_colour = "red" if (late_arrival or overnight or (duty_hours or 0) > 10) else "amber"
        dec.recommended = ["mobility", "recovery_walk"] if dec.training_colour == "red" else ["mobility", "easy_run", "bodyweight"]
        dec.blocked = ["main_strength", "long_run", "intervals"]
        dec.recovery_risk = 0.55
        dec.reason = "Return flight — recovery focus based on release time."
        return _apply_chain(dec, prev_decision)

    # ---------- GENERIC FLIGHT ----------
    # Fine-grained early/normal/late classification.
    is_early = report_min is not None and report_min < 6 * 60
    is_late  = release_min is not None and release_min > 21 * 60
    is_long  = (duty_hours or 0) > 10

    if is_long:
        dec.label = "LONG_DUTY"
        dec.reason = "Long duty day — no hard session."
        dec.training_colour = "red"
    elif is_early:
        dec.label = "EARLY_DUTY"
        dec.reason = "Early report — no hard session before duty."
        dec.training_colour = "amber"
    elif is_late:
        dec.label = "LATE_DUTY"
        dec.reason = "Late release — no hard evening session."
        dec.training_colour = "amber"
    else:
        dec.label = "NORMAL_DUTY"
        dec.reason = "Standard flight day — light session only."
        dec.training_colour = "amber"

    dec.client_label = {
        "LONG_DUTY": "Long duty",
        "EARLY_DUTY": "Early duty",
        "LATE_DUTY": "Late duty",
        "NORMAL_DUTY": "Flying day",
    }[dec.label]

    if dec.training_colour == "red":
        dec.recommended = ["mobility"]
        dec.blocked = ["main_strength", "long_run", "intervals", "tempo", "easy_run"]
    else:
        dec.recommended = ["mobility", "bodyweight", "easy_run"]
        dec.blocked = ["main_strength", "long_run", "intervals"]

    dec.recovery_risk = 0.4 if not is_long else 0.7
    return _apply_chain(dec, prev_decision)


# ---------------------------------------------------------------------------
# Chain rule — POST_NIGHT_RECOVERY / POST_LONG_DUTY_RECOVERY based on prev day.
# ---------------------------------------------------------------------------

def _apply_chain(dec: DayDecision, prev: Optional[DayDecision]) -> DayDecision:
    """If yesterday was heavy, downgrade today's colour + attach chain_flag."""
    if not prev:
        return dec
    yesterday_heavy = prev.label in (
        "OVERNIGHT_DUTY", "LONG_DUTY", "MULTI_SECTOR_DUTY",
        "TURNAROUND_DUTY", "LATE_DUTY",
    )
    yesterday_night = prev.label == "OVERNIGHT_DUTY"
    if not yesterday_heavy:
        return dec

    # Only downgrade if today WOULD otherwise be green/amber. Never lift a
    # black/red into a lower risk category.
    if dec.training_colour in ("green", "amber"):
        chain_label = "POST_NIGHT_RECOVERY" if yesterday_night else "POST_LONG_DUTY_RECOVERY"
        # We keep the original label as-is if it's already a duty label; but
        # for OFF/REST/ROFF the chain label takes precedence.
        if dec.label in ("OFF_DAY", "REST_DAY", "ROSTERED_OFF"):
            dec.label = chain_label
            dec.client_label = "Post-night recovery" if yesterday_night else "Post-duty recovery"
            dec.training_colour = "amber"
            dec.recommended = ["mobility", "recovery_walk", "easy_run"]
            dec.blocked = ["main_strength", "long_run", "intervals", "tempo"]
            dec.reason = "After a heavy previous day — recovery focus."
        dec.chain_flag = "post_night" if yesterday_night else "post_long_duty"
    return dec


# ---------------------------------------------------------------------------
# Sequence labelling (whole month).
# ---------------------------------------------------------------------------

def label_month(days: list) -> list[DayDecision]:
    decisions: list[DayDecision] = []
    prev: Optional[DayDecision] = None
    for d in days:
        dec = decide_day(d, prev)
        decisions.append(dec)
        prev = dec
    return decisions


# ---------------------------------------------------------------------------
# Weekly summary — for coach dashboard and programme adjustment.
# ---------------------------------------------------------------------------

def weekly_windows(decisions: list[DayDecision]) -> list[dict]:
    """Group decisions into weeks (Mon-Sun) and return counts + suggested
    weekly training target."""
    from datetime import date as _date
    weeks: dict[tuple[int, int], list[DayDecision]] = {}
    for d in decisions:
        y, m, dd = (int(x) for x in d.date.split("-"))
        iso_year, iso_week, _ = _date(y, m, dd).isocalendar()
        weeks.setdefault((iso_year, iso_week), []).append(d)

    out: list[dict] = []
    for (iy, iw), group in sorted(weeks.items()):
        counts = {"green": 0, "amber": 0, "red": 0, "black": 0}
        for g in group:
            counts[g.training_colour] = counts.get(g.training_colour, 0) + 1
        # Suggested target: green + half of amber, capped at 5.
        target = min(5, counts["green"] + counts["amber"] // 2)
        out.append({
            "iso_year": iy,
            "iso_week": iw,
            "start": group[0].date,
            "end": group[-1].date,
            "day_count": len(group),
            "counts": counts,
            "suggested_target_sessions": target,
            "labels": [g.label for g in group],
        })
    return out
