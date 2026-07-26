"""
Emirates day-label enrichment
-----------------------------
The Emirates parser (parsers/emirates.py) already assigns `training_colour`
and `equipment_assumption` per day. This module adds the two remaining
fields the plan generator needs:

    * client_label — human-friendly one-liner ("Layover in JFK", "SIM training")
    * blocked      — list of session categories forbidden on this day

Kept as a small pure-Python module so it can be reused by the roster
confirmation pipeline and by any admin CLI that back-fills legacy rosters.
"""
from __future__ import annotations
from typing import Any


# All session-category tokens the plan generator understands.
_ALL_CATS = [
    "main_strength", "hotel_strength", "bodyweight",
    "long_run", "easy_run", "intervals", "tempo",
    "mobility", "recovery_walk", "rest",
]


def _client_label_for(day: dict) -> str:
    """Simple, warm, coach-voice label. No AI wording."""
    label = str(day.get("label") or day.get("auto_label") or "").upper()
    layover_city = day.get("layover_city") or day.get("end_location")
    dtype = str(day.get("day_type") or "").lower()

    if label == "DAY_OFF" or dtype == "day_off":
        return "Free day"
    if label == "REST_DAY" or dtype in ("rest", "rest_day"):
        return "Rest day"
    if label == "SIM_TRAINING" or dtype == "sim_training":
        return "SIM training"
    if label == "LONG_HAUL_OUTBOUND":
        return f"Flying to {layover_city}" if layover_city else "Long-haul outbound"
    if label == "LONG_HAUL_RETURN":
        return f"Return from {layover_city}" if layover_city else "Long-haul return"
    if label == "LONG_HAUL_SECTOR" or label == "LAYOVER_REST_DAY":
        return f"Layover in {layover_city}" if layover_city else "Layover day"
    if label == "OVERNIGHT_TURNAROUND":
        return "Overnight turnaround"
    if label == "TURNAROUND_DUTY":
        return "Turnaround duty"
    if label == "POST_LONG_HAUL_RECOVERY":
        return "Post long-haul recovery"
    if label == "POST_NIGHT_RECOVERY":
        return "Post-night recovery"
    if label == "EARLY_PICKUP":
        return "Early pickup"
    if label == "NEEDS_REVIEW":
        return "Unclear — needs your check"
    # Fallbacks
    if "layover" in dtype:
        return f"Layover in {layover_city}" if layover_city else "Layover day"
    if "flight" in dtype:
        return f"Flying to {layover_city}" if layover_city else "Flying day"
    return day.get("client_label") or "Flying day"


def _blocked_for(day: dict) -> list[str]:
    """Determine which session categories are unsafe on this day based on
    training_colour + label + layover status.
    """
    colour = str(day.get("training_colour") or "").lower()
    label = str(day.get("label") or day.get("auto_label") or "").upper()
    dtype = str(day.get("day_type") or "").lower()

    # Rest / off / SIM day → nothing blocked (client may still choose
    # light activity), colour is green, block only heavy running to be safe.
    if label in ("DAY_OFF",) or dtype == "day_off":
        return []
    if label == "REST_DAY" or dtype in ("rest", "rest_day"):
        return ["intervals", "long_run"]

    # SIM training is mentally taxing but not physical → block hard sessions
    if label == "SIM_TRAINING":
        return ["main_strength", "long_run", "intervals"]

    # Any parser 'NEEDS_REVIEW' day → block everything until Louis checks it
    if label == "NEEDS_REVIEW" or colour == "black":
        return list(_ALL_CATS)

    # Layover full day (in destination, no duty) — green/amber depending on
    # jetlag; block main_strength when out-of-base w/o hotel gym confirmed.
    if label in ("LONG_HAUL_SECTOR", "LAYOVER_REST_DAY"):
        eq = str(day.get("equipment_assumption") or "").lower()
        blocked = ["intervals", "long_run"]
        if eq in ("hotel_or_bodyweight_only", "hotel_or_bodyweight"):
            blocked.append("main_strength")
        return blocked

    # Long-haul outbound / return / turnarounds — hard duty day
    if label in ("LONG_HAUL_OUTBOUND", "LONG_HAUL_RETURN",
                 "OVERNIGHT_TURNAROUND", "TURNAROUND_DUTY"):
        base = ["main_strength", "long_run", "intervals"]
        if label in ("LONG_HAUL_RETURN", "OVERNIGHT_TURNAROUND"):
            base.append("tempo")
        return base

    # Post-night / post-long recovery day
    if label in ("POST_LONG_HAUL_RECOVERY", "POST_NIGHT_RECOVERY"):
        return ["main_strength", "long_run", "intervals", "tempo"]

    # Early pickup — moderate day
    if label == "EARLY_PICKUP":
        return ["long_run", "intervals"]

    # Default by colour
    if colour == "red":
        return ["main_strength", "long_run", "intervals", "tempo"]
    if colour == "amber":
        return ["long_run", "intervals"]
    return []


def enrich_emirates_days(days: list[dict]) -> None:
    """In-place: attach client_label and blocked[] to every Emirates day
    that doesn't already have them.
    """
    for d in days or []:
        if str(d.get("source") or "") != "emirates_parser_v1":
            continue
        if "client_label" not in d or not d.get("client_label"):
            d["client_label"] = _client_label_for(d)
        if "blocked" not in d or d.get("blocked") is None:
            d["blocked"] = _blocked_for(d)
        # Coalesce equipment_assumption values that the parser leaves as
        # non-standard strings ("any" is fine; "hotel_or_bodyweight_only" is fine).
        eq = str(d.get("equipment_assumption") or "").strip()
        if not eq:
            d["equipment_assumption"] = "any"
