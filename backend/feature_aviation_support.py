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
    # Variety Engine additions ---
    # Injury regions this protocol should be AVOIDED for
    # (e.g. ["knee", "hip"] means "skip if the client has a knee or hip injury").
    restricted_regions: list[str] = field(default_factory=list)
    # Equipment this protocol strictly REQUIRES. Optional hints (e.g. mat_optional,
    # walking_shoes) still live in `equipment` above. Empty list = no requirements.
    required_equipment: list[str] = field(default_factory=list)
    # Environment this protocol suits best ("indoor" | "outdoor" | "any").
    # Used as a soft bonus when the trigger context indicates a preference.
    environment: str = "any"


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
    restricted_regions=["back"],
    environment="indoor",
))


# ---------------------------------------------------------------------------
# Variety pool — additional protocols
# ---------------------------------------------------------------------------
# These are alternates the Variety Engine can rotate through so pilots never
# get the same session on repeat. Each variant is *safety-equivalent* to its
# sibling protocol but stresses a slightly different focus (breathing vs
# mobility vs activation) so the client experience feels fresh.

_register(ProtocolSpec(
    key="pilot_pre_flight_breathing_5",
    display_title="Pre-Flight Breathing",
    family="mobility", intensity="low",
    duration_min=5, duration_range=(3, 8), role="pilot",
    cues=["Down-regulate before duty. Nasal breathing only."],
    equipment=[],
    blocks=[
        {"name": "Box breathing",     "duration_sec": 120, "cue": "4s in / 4s hold / 4s out / 4s hold"},
        {"name": "Standing sway",     "duration_sec": 60,  "cue": "Loose shoulders, gentle sway"},
        {"name": "4-6 breath",        "duration_sec": 120, "cue": "Longer exhale to settle"},
    ],
    environment="any",
))

_register(ProtocolSpec(
    key="pilot_pre_flight_neck_shoulder_5",
    display_title="Pre-Flight Neck & Shoulder",
    family="mobility", intensity="low",
    duration_min=5, duration_range=(4, 8), role="pilot",
    cues=["Loosen the upper body before headset + shoulder harness."],
    equipment=[],
    blocks=[
        {"name": "Neck half-circles",   "duration_sec": 60, "cue": "Slow, chin to chest, ear to shoulder"},
        {"name": "Scap circles",        "duration_sec": 60, "cue": "Both directions"},
        {"name": "Doorway pec stretch", "duration_sec": 60, "cue": "Each arm"},
        {"name": "Chin tucks",          "duration_sec": 60, "cue": "Tall spine, gentle"},
    ],
    restricted_regions=["neck", "shoulder"],
    environment="any",
))

_register(ProtocolSpec(
    key="pilot_pre_flight_hip_opener_7",
    display_title="Pre-Flight Hip Opener",
    family="mobility", intensity="low",
    duration_min=7, duration_range=(5, 10), role="pilot",
    cues=["Deeper hip focus for long-duty sitting."],
    equipment=["mat_optional"],
    blocks=[
        {"name": "90/90 hip switches",  "duration_sec": 90,  "cue": "Slow transitions"},
        {"name": "World's greatest",    "duration_sec": 90,  "cue": "Each side, deep lunge"},
        {"name": "Pigeon prep",         "duration_sec": 90,  "cue": "Each side"},
        {"name": "Bridge with hold",    "duration_sec": 60,  "cue": "Squeeze at top"},
        {"name": "Breathing reset",     "duration_sec": 90,  "cue": "Nasal, deep"},
    ],
    restricted_regions=["hip", "knee"],
    environment="indoor",
))

_register(ProtocolSpec(
    key="pilot_post_flight_stretch_10",
    display_title="Post-Flight Gentle Stretch",
    family="reset", intensity="low",
    duration_min=10, duration_range=(6, 12), role="pilot",
    cues=["Slow full-body stretch after sitting. Nothing forced."],
    equipment=["mat_optional"],
    blocks=[
        {"name": "Standing forward fold", "duration_sec": 90,  "cue": "Soft knees, hang"},
        {"name": "Standing side bend",    "duration_sec": 90,  "cue": "Each side"},
        {"name": "Calf stretch on wall",  "duration_sec": 90,  "cue": "Each leg"},
        {"name": "Seated hamstring",      "duration_sec": 90,  "cue": "Each leg, gentle"},
        {"name": "Shoulder rolls",        "duration_sec": 60,  "cue": "Slow, both directions"},
        {"name": "Breathing down-reg",    "duration_sec": 120, "cue": "6s exhale"},
    ],
    environment="any",
))

_register(ProtocolSpec(
    key="pilot_post_flight_legs_up_wall_8",
    display_title="Legs-Up-The-Wall Reset",
    family="recovery", intensity="very_low",
    duration_min=8, duration_range=(5, 12), role="pilot",
    cues=["Fully restorative. Set a timer and just breathe."],
    equipment=["mat_optional"],
    blocks=[
        {"name": "Setup + settle",  "duration_sec": 60,  "cue": "Hips to wall, arms wide"},
        {"name": "Legs-up-the-wall","duration_sec": 300, "cue": "Nasal breathing, palms up"},
        {"name": "Gentle roll-out", "duration_sec": 60,  "cue": "Roll to one side before rising"},
    ],
    restricted_regions=["back"],
    environment="indoor",
))

_register(ProtocolSpec(
    key="pilot_layover_walk_30",
    display_title="Layover Explore Walk",
    family="walk", intensity="very_low",
    duration_min=30, duration_range=(20, 45), role="pilot",
    cues=["Longer explore. Zone 1, comfortable. Hydrate on the way."],
    equipment=["walking_shoes"],
    blocks=[
        {"name": "Comfortable walk", "duration_sec": 30 * 60,
         "cue": "Daylight, points of interest, easy pace"},
    ],
    restricted_regions=["foot", "ankle"],
    environment="outdoor",
))

_register(ProtocolSpec(
    key="pilot_layover_park_walk_25",
    display_title="Layover Park Walk",
    family="walk", intensity="very_low",
    duration_min=25, duration_range=(15, 35), role="pilot",
    cues=["Find green space. Zone 1. Nose breathe."],
    equipment=["walking_shoes"],
    blocks=[
        {"name": "Green-space walk", "duration_sec": 25 * 60,
         "cue": "Trees, water, low-traffic paths"},
    ],
    restricted_regions=["foot", "ankle"],
    environment="outdoor",
))

_register(ProtocolSpec(
    key="pilot_arrival_breathing_5",
    display_title="Arrival Breathing Reset",
    family="mobility", intensity="low",
    duration_min=5, duration_range=(4, 8), role="pilot",
    cues=["Slow breathing after arrival. Set the nervous system down."],
    equipment=[],
    blocks=[
        {"name": "4-6 breath",       "duration_sec": 120, "cue": "Extended exhale"},
        {"name": "Shoulder release", "duration_sec": 60,  "cue": "Roll, shrug, release"},
        {"name": "Gentle T-spine",   "duration_sec": 120, "cue": "Reach and open"},
    ],
    environment="any",
))

_register(ProtocolSpec(
    key="pilot_movement_break_stretch_3",
    display_title="Micro Stretch Break",
    family="movement_break", intensity="very_low",
    duration_min=3, duration_range=(2, 6), role="pilot",
    cues=["3-minute reset. Anywhere, anytime."],
    equipment=[],
    blocks=[
        {"name": "Reach + fold",   "duration_sec": 45, "cue": "Slow, full stretch"},
        {"name": "Chest opener",   "duration_sec": 45, "cue": "Interlace behind back"},
        {"name": "Hip flexor",     "duration_sec": 60, "cue": "Each side, gentle"},
        {"name": "Neck rolls",     "duration_sec": 30, "cue": "Very slow"},
    ],
    environment="any",
))

_register(ProtocolSpec(
    key="pilot_movement_break_walk_5",
    display_title="Walking Break",
    family="movement_break", intensity="very_low",
    duration_min=5, duration_range=(3, 10), role="pilot",
    cues=["Get out of the seat, walk anywhere for 5."],
    equipment=[],
    blocks=[
        {"name": "Slow walk", "duration_sec": 5 * 60, "cue": "Loose, easy pace"},
    ],
    restricted_regions=["foot"],
    environment="any",
))

_register(ProtocolSpec(
    key="pilot_turnaround_breathing_3",
    display_title="Turnaround Breathing",
    family="reset", intensity="very_low",
    duration_min=3, duration_range=(2, 5), role="pilot",
    cues=["Quick down-regulate between sectors."],
    equipment=[],
    blocks=[
        {"name": "Box breathing", "duration_sec": 90, "cue": "4-4-4-4"},
        {"name": "Neck release",  "duration_sec": 45, "cue": "Slow half circles"},
        {"name": "Shoulder rolls","duration_sec": 45, "cue": "Both directions"},
    ],
    environment="any",
))


# ---------------------------------------------------------------------------
# Variety Engine — pools + deterministic scorer
# ---------------------------------------------------------------------------
# Each pool represents ONE trigger slot (e.g. "pre-flight mobility card") and
# contains protocol keys that are safety-equivalent alternates. The Variety
# Engine picks ONE key per pool per date using deterministic scoring.

POOLS: dict[str, list[str]] = {
    # Pre-flight mobility card (short, before duty)
    "pre_flight_light": [
        "pilot_pre_flight_mobility_6",
        "pilot_pre_flight_activation_6",
        "pilot_pre_flight_breathing_5",
        "pilot_pre_flight_neck_shoulder_5",
        "pilot_pre_flight_hip_opener_7",
    ],
    # Post-flight walk card (unless finish is late)
    "post_flight_walk": [
        "pilot_post_flight_walk_15",
    ],
    # Post-flight reset card (late finish OR when a walk isn't appropriate)
    "post_flight_reset": [
        "pilot_post_flight_reset_10",
        "pilot_post_flight_stretch_10",
        "pilot_post_flight_legs_up_wall_8",
        "pilot_travel_recovery_8",
    ],
    # Layover-full walk card
    "layover_full": [
        "pilot_layover_walk_20",
        "pilot_layover_walk_30",
        "pilot_layover_park_walk_25",
    ],
    # Arrival walk (short walk-out from sitting)
    "arrival_walk": [
        "pilot_arrival_walk_10",
    ],
    # Arrival mobility (paired with arrival walk in the Arrival Reset bundle)
    "arrival_mobility": [
        "pilot_arrival_mobility_5",
        "pilot_arrival_breathing_5",
    ],
    # Movement / micro breaks
    "movement_break": [
        "pilot_movement_break_5",
        "pilot_movement_break_stretch_3",
        "pilot_movement_break_walk_5",
    ],
    # Turnaround reset between sectors
    "turnaround_reset": [
        "pilot_turnaround_reset_5",
        "pilot_turnaround_breathing_3",
    ],
    # Layover departure prep (before returning to duty)
    "layover_departure_prep": [
        "pilot_pre_flight_mobility_6",
        "pilot_pre_flight_breathing_5",
        "pilot_pre_flight_neck_shoulder_5",
    ],
}

# How many recent Flight Support activities to look back at for the recency
# penalty. Session default per product spec: 5 (recommended).
VARIETY_LOOKBACK = 5


def _deterministic_tiebreak(*parts: str) -> int:
    """Stable, deterministic integer key derived from string parts. Kept
    intentionally simple (no salt, no crypto) — this is *not* security-
    sensitive, we just need the same inputs to always produce the same
    ordering across process restarts."""
    import hashlib
    joined = "\x1f".join(str(p) for p in parts)
    return int(hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8], 16)


def pick_from_pool(
    *,
    pool_key: str,
    user_id: str,
    date: str,
    history_keys: Optional[list[str]] = None,
    restrictions: Optional[list[str]] = None,
    equipment_available: Optional[list[str]] = None,
    environment_pref: Optional[str] = None,
    time_budget_min: Optional[int] = None,
    preferred_family: Optional[str] = None,
) -> Optional[str]:
    """Deterministically pick ONE protocol key from a variety pool.

    Priority order (per spec):
      1. Safety (restrictions) — hard filter.
      2. Environment / equipment — hard filter for strict requirements.
      3. Time budget — hard filter if provided.
      4. Objective — bonus for matching preferred_family.
      5. Environment preference — soft bonus.
      6. Media availability — future extension (no-op for MVP).
      7. Recent repetition — heavy penalty when protocol is in history.
      8. Deterministic tiebreak.

    Returns the chosen protocol key, or the first pool candidate if every
    option was hard-filtered out (safety-preserving fallback).
    """
    history = list(history_keys or [])
    restr = [r.lower() for r in (restrictions or [])]
    have_eq = set((equipment_available or []) + ["mat_optional"])
    # mat_optional is treated as "if you have one great, if not fine" — the
    # protocol will still work without it, so we never hard-block on it.

    candidates = POOLS.get(pool_key) or []
    if not candidates:
        return None

    scored: list[tuple[int, int, str]] = []  # (score, tiebreak, key)
    fallback = candidates[0]

    for key in candidates:
        p = PROTOCOLS.get(key)
        if not p:
            continue
        # 1. Safety — hard filter
        if any(r in [x.lower() for x in (p.restricted_regions or [])] for r in restr):
            continue
        # 2. Environment / equipment — hard filter on strict requirements only
        strict_eq = set(e for e in (p.required_equipment or []) if e and e != "mat_optional")
        if strict_eq and not strict_eq.issubset(have_eq):
            continue
        # 3. Time budget — hard filter (must fit budget)
        if time_budget_min is not None and p.duration_min > time_budget_min:
            continue

        score = 0

        # 4. Objective / family match
        if preferred_family and p.family == preferred_family:
            score += 4

        # 5. Environment preference (soft bonus)
        if environment_pref and p.environment in (environment_pref, "any"):
            score += 2
        elif environment_pref and p.environment != environment_pref:
            score -= 1

        # 6. Media availability — deferred (MVP)

        # 7. Recent repetition penalty. Weight recent uses more heavily.
        # `history` is ordered newest-first; each hit deducts more the newer it is.
        for i, past_key in enumerate(history[:VARIETY_LOOKBACK]):
            if past_key == key:
                # Newest gets -10, next -8, ... down to -2 for oldest in window.
                score -= max(2, 10 - i * 2)

        tiebreak = _deterministic_tiebreak(user_id, date, pool_key, key)
        scored.append((score, tiebreak, key))

    if not scored:
        # All candidates hard-filtered (restrictions/equipment/time). Return the
        # SAFEST fallback — first candidate that passes only the safety filter.
        for key in candidates:
            p = PROTOCOLS.get(key)
            if p and not any(
                r in [x.lower() for x in (p.restricted_regions or [])] for r in restr
            ):
                return key
        return fallback

    # Highest score first; ties broken by the deterministic hash (ascending).
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][2]


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
    pool_key: Optional[str] = None   # Variety pool this intervention was picked from

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
    pool_key: Optional[str] = None,
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
        pool_key=pool_key,
    )


def _pick(
    pool_key: str, *, user_id: str, date: str,
    history_keys: Optional[list[str]] = None,
    restrictions: Optional[list[str]] = None,
    equipment_available: Optional[list[str]] = None,
    environment_pref: Optional[str] = None,
    time_budget_min: Optional[int] = None,
    preferred_family: Optional[str] = None,
) -> Optional[str]:
    """Thin wrapper around `pick_from_pool` for use inside the selector."""
    return pick_from_pool(
        pool_key=pool_key,
        user_id=user_id or "anonymous",
        date=date,
        history_keys=history_keys,
        restrictions=restrictions,
        equipment_available=equipment_available,
        environment_pref=environment_pref,
        time_budget_min=time_budget_min,
        preferred_family=preferred_family,
    )


def select_interventions_for_day(
    *,
    role: str,
    roster_day: Optional[dict],
    date: str,
    has_training_today: bool,
    training_intensity: Optional[str] = None,
    user_id: Optional[str] = None,
    history_keys: Optional[list[str]] = None,
    restrictions: Optional[list[str]] = None,
    equipment_available: Optional[list[str]] = None,
) -> list[Intervention]:
    """Deterministic selection of Flight Support interventions for one day.

    The Variety Engine is now used to pick ONE protocol per pool per day
    with a strong penalty for anything the client has done in the last
    ~5 Flight Support sessions (see VARIETY_LOOKBACK). Selection is:

      - Safety-first (restrictions never override).
      - History-aware (recent repeats are heavily penalised).
      - Deterministic (same inputs → same output across restarts).
      - Backward-compatible (existing callers that pass no history/user_id
        still work; they just receive the first pool candidate).

    Rules (unchanged from Phase A, only the *choice* inside each rule is
    now variety-aware):
      - Non-pilot role → return [].
      - No roster_day → return [].
      - Home / rest / annual-leave / off → return [].
      - Standby → optional movement break only if no training today.
      - Turnaround → Turnaround Reset pool.
      - Layover Full → optional walk pool if no training. Skip entirely
        if the client already trained today.
      - Layover Arrival → Arrival walk + Arrival mobility bundle (walk
        dropped if finish is late).
      - Layover Departure → Pre-flight prep. If long-haul, add a
        Movement Break earlier.
      - Flight duty → Pre-flight prep + post-flight walk OR post-flight
        reset (if late finish). Heavy training triggers a lighter
        Movement Break instead of a walk.
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

    # Shared kwargs for pool picking. `user_id` gives the deterministic
    # tiebreak per-client so two crews on the same roster don't
    # accidentally get the same rotation in lock-step.
    pk = {
        "user_id": user_id or "anonymous",
        "date": date,
        "history_keys": history_keys or [],
        "restrictions": restrictions or [],
        "equipment_available": equipment_available or [],
    }

    if day_type in _STANDBY:
        if not has_training_today:
            key = _pick("movement_break", **pk) or "pilot_movement_break_5"
            out.append(_mk(
                date=date, key=key, role=role,
                reason="Standby day: gentle movement to counter waiting.",
                pool_key="movement_break",
            ))
        return out

    if day_type in _TURNAROUND:
        key = _pick("turnaround_reset", **pk) or "pilot_turnaround_reset_5"
        out.append(_mk(
            date=date, key=key, role=role,
            reason="Turnaround: tiny reset between sectors.",
            pool_key="turnaround_reset",
        ))
        return out

    if day_type in _LAYOVER_ARRIVAL:
        bkey = f"bundle:arrival:{date}"
        if not late_finish:
            walk_key = _pick("arrival_walk", **pk) or "pilot_arrival_walk_10"
            out.append(_mk(
                date=date, key=walk_key, role=role,
                reason="Arrival after sitting — 10-min easy walk.",
                bundle_key=bkey, bundle_title="Arrival Reset", idx=0,
                pool_key="arrival_walk",
            ))
        mob_key = _pick("arrival_mobility", **pk) or "pilot_arrival_mobility_5"
        out.append(_mk(
            date=date, key=mob_key, role=role,
            reason="Post-arrival mobility for hips + spine.",
            bundle_key=bkey, bundle_title="Arrival Reset", idx=1,
            pool_key="arrival_mobility",
        ))
        return out

    if day_type in _LAYOVER_FULL:
        if has_training_today:
            # Spec §17: don't over-prescribe when the client already trains.
            return []
        key = _pick("layover_full", environment_pref="outdoor", **pk) or "pilot_layover_walk_20"
        out.append(_mk(
            date=date, key=key, role=role,
            reason="Layover day: comfortable walk to move.",
            pool_key="layover_full",
        ))
        return out

    if day_type in _LAYOVER_DEPARTURE:
        key = _pick("layover_departure_prep", **pk) or "pilot_pre_flight_mobility_6"
        out.append(_mk(
            date=date, key=key, role=role,
            reason="Layover departure: prime for prolonged sitting.",
            pool_key="layover_departure_prep",
        ))
        if long_haul:
            mb_key = _pick("movement_break", **pk) or "pilot_movement_break_5"
            out.append(_mk(
                date=date, key=mb_key, role=role,
                reason="Long-haul departure: pre-duty movement break.",
                pool_key="movement_break",
            ))
        return out

    # Explicit flight labels + fallback: any day_type containing "flight"/"duty"
    # or with actual flights is treated as flight duty.
    is_flight = day_type in _FLIGHT_LABELS or "flight" in day_type or "duty" in day_type or _has_flight(roster_day)
    if is_flight:
        # Always safe: short pre-flight mobility (variety-picked).
        pre_key = _pick("pre_flight_light", **pk) or "pilot_pre_flight_mobility_6"
        out.append(_mk(
            date=date, key=pre_key, role=role,
            reason="Pre-flight: short mobility for cockpit-loaded joints.",
            pool_key="pre_flight_light",
        ))
        # Post-flight recovery — walk unless finish is late, then reset.
        if long_haul or _has_flight(roster_day):
            if late_finish:
                key = _pick("post_flight_reset", **pk) or "pilot_post_flight_reset_10"
                out.append(_mk(
                    date=date, key=key, role=role,
                    reason="Late finish — gentle reset (walking unsuitable).",
                    pool_key="post_flight_reset",
                ))
            else:
                # If client already did a heavy programme workout today, keep
                # the post-flight intervention smaller (spec §16/17).
                if heavy_training:
                    mb_key = _pick("movement_break", **pk) or "pilot_movement_break_5"
                    out.append(_mk(
                        date=date, key=mb_key, role=role,
                        reason="Heavy training scheduled — light post-flight movement.",
                        pool_key="movement_break",
                    ))
                else:
                    walk_key = _pick("post_flight_walk", **pk) or "pilot_post_flight_walk_15"
                    out.append(_mk(
                        date=date, key=walk_key, role=role,
                        reason="Post-flight walk to counter prolonged sitting.",
                        pool_key="post_flight_walk",
                    ))
        return out

    return out


# ---------------------------------------------------------------------------
# High-level entry point for read endpoints
# ---------------------------------------------------------------------------

# Free-text → injury region keywords. Kept intentionally shallow — the
# Engine V2 module has a richer keyword map (feature_v2_common._INJURY_KEYWORDS)
# but Flight Support only needs to know the region, not the pattern.
_INJURY_REGION_KEYWORDS = {
    "knee": "knee", "acl": "knee", "meniscus": "knee", "patella": "knee",
    "hip": "hip", "groin": "hip", "psoas": "hip",
    "back": "back", "lumbar": "back", "lower back": "back", "sciatic": "back",
    "shoulder": "shoulder", "rotator cuff": "shoulder", "labrum": "shoulder",
    "neck": "neck", "cervical": "neck",
    "ankle": "ankle", "achilles": "ankle", "shin": "ankle",
    "foot": "foot", "plantar": "foot", "toe": "foot",
    "wrist": "wrist", "elbow": "wrist",
}


def _extract_injury_regions(text: str) -> list[str]:
    """Very lightweight free-text → list[region] extractor. Returns empty
    list for 'none' / empty. Duplicates are stripped."""
    t = (text or "").strip().lower()
    if not t or t in ("none", "no", "no injuries", "no restrictions",
                       "n/a", "na", "-"):
        return []
    seen: list[str] = []
    for kw, region in _INJURY_REGION_KEYWORDS.items():
        if kw in t and region not in seen:
            seen.append(region)
    return seen


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
    #   1. profile.aviation_role (explicit setting, editable by coach)
    #   2. profile.job_title confidently identifies pilot → "pilot"
    #   3. profile.job_title confidently identifies cabin crew → "cabin_crew"
    #   4. Otherwise → "role_unknown" (NEVER default to pilot; Phase B §9)
    #
    # A "role_unknown" outcome short-circuits selection so a non-pilot with
    # missing role data cannot accidentally receive cockpit-specific
    # protocols. The coach must set `profile.aviation_role` explicitly
    # before any support is prescribed.
    def _resolve_role() -> str:
        av = (profile.get("aviation_role") or "").strip().lower()
        if av in ("pilot", "cabin_crew"):
            return av
        jt = (profile.get("job_title") or "").strip().lower()
        _pilot_kw = ("pilot", "captain", "first officer",
                     "co-pilot", "co pilot", " fo ", "cpt",
                     "capt.", "airline pilot", "commercial pilot")
        _cc_kw = ("cabin crew", "cabin", "flight attendant",
                  "attendant", "steward", "stewardess", "purser")
        # Cabin crew keywords take priority so "cabin crew — pilot flying"
        # oddities still classify correctly.
        if any(k in jt for k in _cc_kw):
            return "cabin_crew"
        if any(k in jt for k in _pilot_kw):
            return "pilot"
        top = ((profile.get("role") or "")
                or (user_doc.get("role") if user_doc else "")).strip().lower()
        if top in ("pilot", "cabin_crew"):
            return top
        return "role_unknown"

    resolved_role = _resolve_role()
    if resolved_role != "pilot":  # cabin_crew (Phase C) + role_unknown → silent
        return {}

    # --- Variety Engine inputs ---------------------------------------------
    # 1. History: last N Flight Support activities the client has done (any
    #    status = completed / skipped / not_started counts as "prescribed").
    #    Ordered newest-first so the recency penalty scales correctly.
    history_keys: list[str] = []
    try:
        async for a in db.flight_support_activity.find(
            {"user_id": user_id},
            {"_id": 0, "protocol_key": 1, "date": 1, "updated_at": 1},
        ).sort([("date", -1), ("updated_at", -1)]).limit(VARIETY_LOOKBACK * 4):
            pk = a.get("protocol_key")
            if pk and pk in PROTOCOLS:
                history_keys.append(pk)
            if len(history_keys) >= VARIETY_LOOKBACK:
                break
    except Exception:
        history_keys = []

    # 2. Restrictions: derived from user profile injuries + persistent list.
    #    Regions are lowercased ("knee", "back", ...).
    restrictions: list[str] = []
    try:
        inj = profile.get("injuries") or profile.get("injury") or ""
        if isinstance(inj, str) and inj.strip():
            restrictions.extend(_extract_injury_regions(inj))
        elif isinstance(inj, list):
            for item in inj:
                if isinstance(item, str):
                    restrictions.extend(_extract_injury_regions(item))
                elif isinstance(item, dict) and item.get("region"):
                    restrictions.append(str(item["region"]).lower())
        for r in profile.get("persistent_restrictions") or []:
            if isinstance(r, dict) and r.get("region"):
                restrictions.append(str(r["region"]).lower())
    except Exception:
        restrictions = []

    # 3. Equipment: soft input to the picker. We accept any equipment the
    #    client has flagged in profile.equipment as available for Flight
    #    Support. Empty list means "no strict equipment" which is fine —
    #    Flight Support protocols default to zero required equipment.
    equipment_available: list[str] = []
    try:
        eq = profile.get("equipment") or []
        if isinstance(eq, list):
            for e in eq:
                if isinstance(e, str):
                    equipment_available.append(e.lower())
                elif isinstance(e, dict) and e.get("key"):
                    equipment_available.append(str(e["key"]).lower())
    except Exception:
        equipment_available = []

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
            user_id=user_id,
            history_keys=history_keys,
            restrictions=restrictions,
            equipment_available=equipment_available,
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


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def resolve_aviation_role(user_doc: dict) -> str:
    """Public role resolver — used by coach endpoints to show
    'Aviation role required' when the client's role is ambiguous.

    Returns one of: "pilot", "cabin_crew", "role_unknown".
    """
    profile = (user_doc or {}).get("profile") or {}
    av = (profile.get("aviation_role") or "").strip().lower()
    if av in ("pilot", "cabin_crew"):
        return av
    jt = (profile.get("job_title") or "").strip().lower()
    _pilot_kw = ("pilot", "captain", "first officer",
                 "co-pilot", "co pilot", " fo ", "cpt",
                 "capt.", "airline pilot", "commercial pilot")
    _cc_kw = ("cabin crew", "cabin", "flight attendant",
              "attendant", "steward", "stewardess", "purser")
    if any(k in jt for k in _cc_kw):
        return "cabin_crew"
    if any(k in jt for k in _pilot_kw):
        return "pilot"
    top = ((profile.get("role") or "")
            or (user_doc.get("role") or "")).strip().lower()
    if top in ("pilot", "cabin_crew"):
        return top
    return "role_unknown"


__all__ = [
    "PROTOCOLS", "POOLS", "ProtocolSpec", "Intervention",
    "VARIETY_LOOKBACK", "pick_from_pool",
    "select_interventions_for_day",
    "get_flight_support_by_date",
    "summarise_training_by_date_from_workouts",
    "resolve_aviation_role",
]
