"""
feature_aviation_support — Operational Support Layer
====================================================

*Runs alongside* Engine V2, never inside it.

Engine V2 owns the athletic programme (WHAT → WHEN → HOW → VALIDATE) and its
outputs (LongRun, EasyRun, Strength, Programme Mobility, etc.). This module
adds a *separate* deterministic layer that prescribes short, supportive
operational interventions for pilots (and later cabin crew) based on their
actual duty context.

CRUCIALLY: interventions produced here NEVER:
  • satisfy any Engine V2 quota (run / strength / mobility / KEY / hard)
  • count toward sessions_per_week / training_days_per_week
  • change ObjectiveExposure identities
  • trigger "missed workout" adherence penalties
  • block a scheduled Engine V2 workout on the same day

Interventions are cheap, deterministic and re-computable on every read; there
is no MongoDB writer here. A separate `flight_support_overrides` collection
(read in from `get_overrides_for_range`) lets coaches disable / customise a
specific intervention without mutating this compute path.

Public surface:
  - PROTOCOLS: dict[str, ProtocolSpec]
  - select_interventions_for_day(...) → list[Intervention]
  - get_flight_support_by_date(db, user_id, d_from, d_to) → dict[iso_date, list]
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from datetime import time


# ---------------------------------------------------------------------------
# Protocol library
# ---------------------------------------------------------------------------
# Each protocol is a small, self-contained micro-intervention. They are
# purposely short (2–20 min) and intentionally not "programmed workouts".
# Composition (e.g. Arrival Reset = walk + mobility) is expressed by the
# selector returning TWO Intervention entries — not one bundle — so the UI
# can show them as separate cards while both carrying `bundle_key` so the
# client sees they belong together.

@dataclass
class ProtocolSpec:
    """A named, deterministic operational protocol.

    Attributes:
      key: stable machine identifier (e.g. "pilot_post_flight_walk_15").
      display_title: what the client sees ("Post-Flight Walk").
      family: high-level category — "walk" | "mobility" | "activation" |
              "recovery" | "reset" | "movement_break".
      intensity: "very_low" | "low" (never higher — see spec §10).
      duration_min: default duration.
      duration_range: (min, max) if the coach later customises.
      role: which crew role this protocol targets ("pilot" | "cabin_crew").
      cues: short descriptive cues rendered under the card.
      equipment: any equipment hints (walking_shoes, mat …).
      blocks: composable inner block list (rendered when the client taps in).
    """
    key: str
    display_title: str
    family: str
    intensity: str
    duration_min: int
    duration_range: tuple[int, int]
    role: str
    cues: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)


# Pilot library. Cabin-crew variants land in Phase C — the loader looks up
# by `role`, so adding new keys later is non-invasive.
PROTOCOLS: dict[str, ProtocolSpec] = {}


def _register(p: ProtocolSpec) -> None:
    PROTOCOLS[p.key] = p


_register(ProtocolSpec(
    key="pilot_pre_flight_mobility_6",
    display_title="Pre-Flight Mobility",
    family="mobility", intensity="low",
    duration_min=6, duration_range=(5, 8), role="pilot",
    cues=[
        "Prime the joints you'll load in the cockpit.",
        "Slow, controlled — this is not a workout.",
    ],
    equipment=["mat_optional"],
    blocks=[
        {"name": "Thoracic rotation",  "duration_sec": 60,
         "cue": "Half-kneel, hand behind head, rotate open"},
        {"name": "Hip opener",         "duration_sec": 90,
         "cue": "Runner's lunge with reach — each side"},
        {"name": "Ankle mobility",     "duration_sec": 60,
         "cue": "Knee-over-toe rocking"},
        {"name": "Glute activation",   "duration_sec": 60,
         "cue": "Standing glute squeeze + hip extension"},
        {"name": "Breathing reset",    "duration_sec": 90,
         "cue": "4s in / 6s out — box breathing"},
    ],
))

_register(ProtocolSpec(
    key="pilot_pre_flight_activation_6",
    display_title="Pre-Flight Activation",
    family="activation", intensity="low",
    duration_min=6, duration_range=(5, 10), role="pilot",
    cues=["Wake the posterior chain before a long duty."],
    equipment=[],
    blocks=[
        {"name": "Air squats",          "duration_sec": 45,
         "cue": "Controlled tempo, full range"},
        {"name": "Glute bridges",       "duration_sec": 60,
         "cue": "Squeeze at the top"},
        {"name": "Standing rows",       "duration_sec": 45,
         "cue": "Elbows tight, retract"},
        {"name": "Calf pumps",          "duration_sec": 45,
         "cue": "Both feet, then single"},
        {"name": "Nasal breathing",     "duration_sec": 90,
         "cue": "Steady, no mouth breathing"},
    ],
))

_register(ProtocolSpec(
    key="pilot_post_flight_reset_10",
    display_title="Post-Flight Reset",
    family="reset", intensity="low",
    duration_min=10, duration_range=(5, 12), role="pilot",
    cues=["Reset the tissues you've been sitting on. Very gentle."],
    equipment=["mat_optional"],
    blocks=[
        {"name": "Slow walk in place",  "duration_sec": 120,
         "cue": "Loosen ankles, sway shoulders"},
        {"name": "Hip flexor mobility", "duration_sec": 120,
         "cue": "Couch stretch — each side"},
        {"name": "T-spine openers",     "duration_sec": 90,
         "cue": "Reach and open, exhale"},
        {"name": "Breathing decompress","duration_sec": 90,
         "cue": "Legs up wall or supine"},
    ],
))

_register(ProtocolSpec(
    key="pilot_post_flight_walk_15",
    display_title="Post-Flight Walk",
    family="walk", intensity="very_low",
    duration_min=15, duration_range=(10, 20), role="pilot",
    cues=["Comfortable pace. Nose breathing. RPE 2–3."],
    equipment=["walking_shoes"],
    blocks=[
        {"name": "Easy walk", "duration_sec": 15 * 60,
         "cue": "Loose shoulders, natural stride — not exercise"},
    ],
))

_register(ProtocolSpec(
    key="pilot_layover_walk_20",
    display_title="Layover Walk",
    family="walk", intensity="very_low",
    duration_min=20, duration_range=(15, 30), role="pilot",
    cues=["Explore the layover on foot. Zone 1, comfortable pace."],
    equipment=["walking_shoes"],
    blocks=[
        {"name": "Comfortable walk", "duration_sec": 20 * 60,
         "cue": "Get some daylight, hydrate, keep it easy"},
    ],
))

_register(ProtocolSpec(
    key="pilot_arrival_walk_10",
    display_title="Arrival Walk",
    family="walk", intensity="very_low",
    duration_min=10, duration_range=(10, 15), role="pilot",
    cues=["Ten easy minutes on arrival, then mobility."],
    equipment=["walking_shoes"],
    blocks=[
        {"name": "Easy arrival walk", "duration_sec": 10 * 60,
         "cue": "Just get moving after sitting"},
    ],
))

_register(ProtocolSpec(
    key="pilot_arrival_mobility_5",
    display_title="Arrival Mobility",
    family="mobility", intensity="low",
    duration_min=5, duration_range=(4, 8), role="pilot",
    cues=["Short arrival mobility. Focus on hips + spine."],
    equipment=["mat_optional"],
    blocks=[
        {"name": "Hip opener",    "duration_sec": 90, "cue": "Each side"},
        {"name": "T-spine reach", "duration_sec": 90, "cue": "Deep exhale"},
        {"name": "Breathing",     "duration_sec": 120, "cue": "4-6 count"},
    ],
))

_register(ProtocolSpec(
    key="pilot_movement_break_5",
    display_title="Movement Break",
    family="movement_break", intensity="very_low",
    duration_min=5, duration_range=(3, 10), role="pilot",
    cues=["Micro-break to counter prolonged sitting."],
    equipment=[],
    blocks=[
        {"name": "Stand and reach", "duration_sec": 60, "cue": "Full body reach"},
        {"name": "Hip circles",     "duration_sec": 90, "cue": "Both directions"},
        {"name": "Walk in place",   "duration_sec": 150, "cue": "Loose ankles"},
    ],
))

_register(ProtocolSpec(
    key="pilot_turnaround_reset_5",
    display_title="Turnaround Reset",
    family="reset", intensity="very_low",
    duration_min=5, duration_range=(3, 8), role="pilot",
    cues=["Tiny reset between sectors."],
    equipment=[],
    blocks=[
        {"name": "Quick walk",     "duration_sec": 120, "cue": "Anywhere you can"},
        {"name": "Hip mobility",   "duration_sec": 90,  "cue": "Fast + gentle"},
        {"name": "Breathing",      "duration_sec": 90,  "cue": "Down-regulate"},
    ],
))

_register(ProtocolSpec(
    key="pilot_travel_recovery_8",
    display_title="Travel Recovery",
    family="recovery", intensity="low",
    duration_min=8, duration_range=(5, 15), role="pilot",
    cues=["After long transit. Restorative, not stimulating."],
    equipment=["mat_optional"],
    blocks=[
        {"name": "Supine breathing",       "duration_sec": 180, "cue": "Nasal only"},
        {"name": "Legs-up-the-wall",       "duration_sec": 180, "cue": "Palms up"},
        {"name": "Gentle spinal twist",    "duration_sec": 120, "cue": "Each side"},
    ],
))


# ---------------------------------------------------------------------------
# Intervention (compute output)
# ---------------------------------------------------------------------------

@dataclass
class Intervention:
    """One resolved instance of a protocol on a specific date. Not
    persisted — recomputed on every read from roster + training context."""
    id: str                       # `fs:<date>:<protocol_key>[:i]` — stable, dedup-safe
    date: str
    protocol_key: str
    role: str
    title: str
    family: str
    intensity: str
    duration_min: int
    cues: list[str]
    equipment: list[str]
    blocks: list[dict]
    bundle_key: Optional[str]     # matches sibling interventions of a bundle (e.g. Arrival Reset)
    bundle_title: Optional[str]   # bundle display name shown by client UI
    trigger_reason: str           # short human-readable why (for coach dashboard)
    is_flight_support: bool = True

    def to_client_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Selector — deterministic rule engine (no LLM)
# ---------------------------------------------------------------------------

# Roster labels that are "flying" for our purposes. Anything not on this list
# is considered "not flying today" (home / annual leave / rest / standby is
# also handled specifically below).
_FLIGHT_LABELS = {
    "flight", "flying", "duty", "flight_duty",
    "sector", "line_check",
}
_LAYOVER_ARRIVAL = {"layover_arrival", "layover_in", "arrival"}
_LAYOVER_DEPARTURE = {"layover_departure", "layover_out", "departure"}
_LAYOVER_FULL = {"layover_full", "layover", "layover_middle"}
_TURNAROUND = {"turnaround", "turnaround_duty"}
_STANDBY = {"standby", "reserve", "airport_standby"}
_HOME_ISH = {"home_day", "home", "off", "rest", "annual_leave", "day_off"}


def _norm(day_type: Optional[str]) -> str:
    return (day_type or "").strip().lower()


def _has_flight(roster_day: dict) -> bool:
    flights = roster_day.get("flights") or []
    return len(flights) > 0


def _is_long_haul(roster_day: dict) -> bool:
    """Duty hours >= 8, else fall back to any leg with arr-dep >= 5h."""
    dh = roster_day.get("duty_hours")
    if isinstance(dh, (int, float)) and dh >= 8:
        return True
    for f in roster_day.get("flights") or []:
        dep, arr = f.get("dep_time"), f.get("arr_time")
        if not dep or not arr:
            continue
        try:
            dep_h, dep_m = [int(x) for x in dep.split(":")[:2]]
            arr_h, arr_m = [int(x) for x in arr.split(":")[:2]]
            dur = (arr_h * 60 + arr_m) - (dep_h * 60 + dep_m)
            if dur < 0:
                dur += 24 * 60  # crossed midnight
            if dur >= 5 * 60:
                return True
        except Exception:
            continue
    return False


def _finish_time_late(roster_day: dict) -> bool:
    """True when the last leg lands after 22:00 or before 06:00 (crossing
    midnight) — long walks aren't appropriate then."""
    flights = roster_day.get("flights") or []
    if not flights:
        return False
    last = flights[-1]
    arr = last.get("arr_time")
    if not arr:
        return False
    try:
        h = int(arr.split(":")[0])
    except Exception:
        return False
    return h >= 22 or h < 6


def _mk(
    *,
    date: str, key: str, role: str,
    reason: str, bundle_key: Optional[str] = None,
    bundle_title: Optional[str] = None, idx: int = 0,
    duration_override: Optional[int] = None,
) -> Intervention:
    p = PROTOCOLS[key]
    duration = duration_override or p.duration_min
    return Intervention(
        id=f"fs:{date}:{key}:{idx}",
        date=date,
        protocol_key=key,
        role=role,
        title=p.display_title,
        family=p.family,
        intensity=p.intensity,
        duration_min=duration,
        cues=list(p.cues),
        equipment=list(p.equipment),
        blocks=list(p.blocks),
        bundle_key=bundle_key,
        bundle_title=bundle_title,
        trigger_reason=reason,
    )


def select_interventions_for_day(
    *,
    role: str,
    roster_day: Optional[dict],
    date: str,
    has_training_today: bool,
    training_intensity: Optional[str] = None,
) -> list[Intervention]:
    """Deterministic selection of Flight Support interventions for one day.

    Rules (locked in this MVP):
      - Non-pilot role → return []. Cabin-crew arrives in Phase C.
      - No roster_day → return []. Aviation support only exists in
        response to duty context.
      - Home / rest / annual-leave / off → return []. Training-only day.
      - Standby → optional 5-min movement break only if no training today.
      - Turnaround → Turnaround Reset (single card, 5 min).
      - Layover Full → optional Layover Walk if no training. Skip entirely
        if the client already trained today (spec §17: avoid over-prescribing).
      - Layover Arrival → Arrival Walk + Arrival Mobility (two cards, same
        bundle_key). If finish time is late, drop the walk (spec §8).
      - Layover Departure → Pre-Flight Mobility. If duty is long-haul, also
        add a Movement Break earlier in the day for hydration cue.
      - Flight duty →
          * Long-haul  → Pre-Flight Mobility + Post-Flight Walk (or Reset
            if landing late/short-window). Two cards, no bundle.
          * Short-haul → just Pre-Flight Mobility unless client already
            trained (then skip).
      - Any other unrecognised duty label → no intervention (safe default).

    Never returns duplicates. Never returns >3 interventions for one day.
    """
    if (role or "").lower() != "pilot":
        return []
    if not roster_day:
        return []

    day_type = _norm(roster_day.get("day_type"))
    if day_type in _HOME_ISH and not _has_flight(roster_day):
        return []

    out: list[Intervention] = []
    long_haul = _is_long_haul(roster_day)
    late_finish = _finish_time_late(roster_day)
    heavy_training = (training_intensity or "").lower() in ("high", "key", "hard")

    if day_type in _STANDBY:
        if not has_training_today:
            out.append(_mk(
                date=date, key="pilot_movement_break_5", role=role,
                reason="Standby day: gentle movement to counter waiting.",
            ))
        return out

    if day_type in _TURNAROUND:
        out.append(_mk(
            date=date, key="pilot_turnaround_reset_5", role=role,
            reason="Turnaround: tiny reset between sectors.",
        ))
        return out

    if day_type in _LAYOVER_ARRIVAL:
        bkey = f"bundle:arrival:{date}"
        if not late_finish:
            out.append(_mk(
                date=date, key="pilot_arrival_walk_10", role=role,
                reason="Arrival after sitting — 10-min easy walk.",
                bundle_key=bkey, bundle_title="Arrival Reset", idx=0,
            ))
        out.append(_mk(
            date=date, key="pilot_arrival_mobility_5", role=role,
            reason="Post-arrival mobility for hips + spine.",
            bundle_key=bkey, bundle_title="Arrival Reset", idx=1,
        ))
        return out

    if day_type in _LAYOVER_FULL:
        if has_training_today:
            # Spec §17: don't over-prescribe when the client already trains.
            return []
        out.append(_mk(
            date=date, key="pilot_layover_walk_20", role=role,
            reason="Layover day: comfortable walk to move.",
        ))
        return out

    if day_type in _LAYOVER_DEPARTURE:
        out.append(_mk(
            date=date, key="pilot_pre_flight_mobility_6", role=role,
            reason="Layover departure: prime for prolonged sitting.",
        ))
        if long_haul:
            out.append(_mk(
                date=date, key="pilot_movement_break_5", role=role,
                reason="Long-haul departure: pre-duty movement break.",
            ))
        return out

    # Explicit flight labels + fallback: any day_type containing "flight"/"duty"
    # or with actual flights is treated as flight duty.
    is_flight = day_type in _FLIGHT_LABELS or "flight" in day_type or "duty" in day_type or _has_flight(roster_day)
    if is_flight:
        # Always safe: short pre-flight mobility.
        out.append(_mk(
            date=date, key="pilot_pre_flight_mobility_6", role=role,
            reason="Pre-flight: 6 min mobility for cockpit-loaded joints.",
        ))
        # Post-flight recovery — walk unless finish is late, then reset.
        if long_haul or _has_flight(roster_day):
            if late_finish:
                out.append(_mk(
                    date=date, key="pilot_post_flight_reset_10", role=role,
                    reason="Late finish — gentle reset (walking unsuitable).",
                ))
            else:
                # If client already did a heavy programme workout today, keep
                # the post-flight intervention smaller (spec §16/17).
                if heavy_training:
                    out.append(_mk(
                        date=date, key="pilot_movement_break_5", role=role,
                        reason="Heavy training scheduled — light post-flight movement.",
                    ))
                else:
                    out.append(_mk(
                        date=date, key="pilot_post_flight_walk_15", role=role,
                        reason="Post-flight walk to counter prolonged sitting.",
                    ))
        return out

    return out


# ---------------------------------------------------------------------------
# High-level entry point for read endpoints
# ---------------------------------------------------------------------------

async def get_flight_support_by_date(
    db, user_id: str, roster_days_by_date: dict[str, dict],
    training_by_date: dict[str, dict],
    role: str = "pilot",
) -> dict[str, list[dict]]:
    """Compute flight-support interventions for a range, in one pass.

    Args:
      roster_days_by_date: {"YYYY-MM-DD": {day_type, flights, ...}}
      training_by_date: {"YYYY-MM-DD": {kind, intensity, key_session, ...}}
      role: "pilot" by default. Cabin-crew skipped (Phase C).

    Coach overrides (`db.flight_support_overrides`) are applied here:
      { user_id, date, action: "disable" | "replace" | "custom",
        replace_key?: <new protocol key>,
        custom_intervention?: { title, family, duration_min, cues, blocks } }
    Overrides are per-date; if `action=disable` we drop everything from
    the deterministic selector for that date.
    """
    if not roster_days_by_date:
        return {}

    # Coach-level toggle to disable Aviation Support entirely
    user_doc = await db.users.find_one(
        {"id": user_id}, {"_id": 0, "profile": 1, "role": 1},
    )
    profile = (user_doc or {}).get("profile") or {}
    if (profile.get("flight_support") or {}).get("disabled"):
        return {}
    # Role resolution priority:
    #   1. profile.aviation_role (new explicit setting, editable by coach)
    #   2. profile.job_title (existing free-text) matched to pilot / cabin_crew
    #   3. profile.role or top-level role — but only if it's an aviation role
    #      (the DB's top-level `role` is typically "client" / "coach" so we
    #      ignore it unless it explicitly says pilot / cabin_crew).
    #   4. Default: "pilot" (MVP; safe because non-pilot roles are ignored
    #      by the selector's role check anyway).
    def _resolve_role() -> str:
        av = (profile.get("aviation_role") or "").strip().lower()
        if av in ("pilot", "cabin_crew"):
            return av
        jt = (profile.get("job_title") or "").strip().lower()
        _pilot_kw = ("pilot", "captain", "first officer",
                     "co-pilot", "co pilot", "fo", "cpt")
        _cc_kw = ("cabin", "attendant", "steward", "purser",
                  "flight attendant")
        if any(k in jt for k in _pilot_kw):
            return "pilot"
        if any(k in jt for k in _cc_kw):
            return "cabin_crew"
        top = ((profile.get("role") or "")
                or (user_doc.get("role") if user_doc else "")).strip().lower()
        if top in ("pilot", "cabin_crew"):
            return top
        return "pilot"

    resolved_role = _resolve_role()
    if resolved_role not in ("pilot",):  # cabin_crew handled in Phase C
        return {}

    # Load overrides once
    overrides: dict[str, list[dict]] = {}
    async for o in db.flight_support_overrides.find(
        {"user_id": user_id,
         "date": {"$in": list(roster_days_by_date.keys())}},
        {"_id": 0},
    ):
        overrides.setdefault(o["date"], []).append(o)

    result: dict[str, list[dict]] = {}
    for date, rd in roster_days_by_date.items():
        ov = overrides.get(date) or []
        # Full disable for this date?
        if any(o.get("action") == "disable_day" for o in ov):
            continue
        training = training_by_date.get(date)
        has_training = bool(training)
        training_intensity = (training or {}).get("intensity") if training else None
        interventions = select_interventions_for_day(
            role=resolved_role, roster_day=rd, date=date,
            has_training_today=has_training,
            training_intensity=training_intensity,
        )

        # Apply per-intervention overrides (replace / custom)
        picked: list[dict] = []
        for it in interventions:
            override = next(
                (o for o in ov
                 if o.get("protocol_key") == it.protocol_key
                 or o.get("intervention_id") == it.id),
                None,
            )
            if override and override.get("action") == "disable":
                continue
            if override and override.get("action") == "replace":
                new_key = override.get("replace_key")
                if new_key in PROTOCOLS:
                    picked.append(_mk(
                        date=date, key=new_key, role=resolved_role,
                        reason=f"Coach override: {it.trigger_reason}",
                        bundle_key=it.bundle_key,
                        bundle_title=it.bundle_title,
                    ).to_client_dict())
                    continue
            if override and override.get("action") == "custom":
                custom = override.get("custom_intervention") or {}
                picked.append({
                    **it.to_client_dict(),
                    "title": custom.get("title") or it.title,
                    "family": custom.get("family") or it.family,
                    "duration_min": custom.get("duration_min") or it.duration_min,
                    "cues": custom.get("cues") or it.cues,
                    "blocks": custom.get("blocks") or it.blocks,
                    "trigger_reason": f"Coach custom: {it.trigger_reason}",
                })
                continue
            picked.append(it.to_client_dict())

        # Add any "custom" interventions that are not replacements of a
        # deterministic protocol (net-new coach additions).
        for o in ov:
            if o.get("action") == "add_custom":
                custom = o.get("custom_intervention") or {}
                picked.append({
                    "id": f"fs:{date}:custom:{o.get('id') or 'x'}",
                    "date": date,
                    "protocol_key": "custom",
                    "role": resolved_role,
                    "title": custom.get("title") or "Custom Support",
                    "family": custom.get("family") or "custom",
                    "intensity": custom.get("intensity") or "low",
                    "duration_min": custom.get("duration_min") or 5,
                    "cues": custom.get("cues") or [],
                    "equipment": custom.get("equipment") or [],
                    "blocks": custom.get("blocks") or [],
                    "bundle_key": None, "bundle_title": None,
                    "trigger_reason": "Coach custom intervention",
                    "is_flight_support": True,
                })

        if picked:
            result[date] = picked
    return result


def summarise_training_by_date_from_workouts(rows: list[dict]) -> dict[str, dict]:
    """Reduce a list of legacy-shaped workout rows (V1 or V2-bridged) to a
    per-date summary the selector can consume. Keeps the aviation module
    fully decoupled from the workouts collection shape."""
    out: dict[str, dict] = {}
    for w in rows:
        d = w.get("date")
        if not d:
            continue
        key_session = bool(w.get("key_session"))
        intensity = ("hard" if w.get("day_load") == 3 or key_session
                     else "moderate")
        # First writer wins per date — matches /calendar/range dedup
        if d not in out:
            out[d] = {
                "kind": w.get("focus") or w.get("title"),
                "intensity": intensity,
                "key_session": key_session,
            }
    return out


__all__ = [
    "PROTOCOLS", "ProtocolSpec", "Intervention",
    "select_interventions_for_day",
    "get_flight_support_by_date",
    "summarise_training_by_date_from_workouts",
]
