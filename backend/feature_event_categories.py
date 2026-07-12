"""
feature_event_categories — Category-aware Event Training / Goal Event system.

Legacy events treated everything as a race. This module introduces categories:
  race         — running, cycling, swimming, triathlon, obstacle
  medical      — airline medical renewal, health check, physio review
  aviation_work — sim check, line check, recurrent training, base move
  sport_hobby  — tennis, padel, football, diving, hiking, ...
  personal     — holiday, wedding, photoshoot, uniform confidence

Each category has its own display language ("Days to race" vs "Days to review"),
suggested focus areas, safety disclaimer (for medical), and colour/icon.

We add:
  * GET /api/events/catalog          — Frontend picker source
  * A helper `enrich_event(ev)`      — Adds category-derived fields
  * Backfill on startup              — One-time re-categorisation of legacy rows

Existing endpoints in server.py call `enrich_event()` so cards adapt without
changing the storage schema.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Optional

from fastapi import Depends

from server import (
    api,
    db,
    current_user,
    logger,
    now_iso,
)

# ---------------------------------------------------------------------------
# Category metadata — the single source of truth for labels and copy.
# ---------------------------------------------------------------------------

CATEGORY_META: dict[str, dict[str, Any]] = {
    "race": {
        "label": "Race / Endurance",
        "short_label": "Race",
        "days_label": "days to race",
        "focus_label": "Suggested focus",
        "icon": "flag",
        "colour": "#EF4444",
        "focus_defaults": ["Base", "Build", "Peak", "Taper", "Recovery"],
    },
    "medical": {
        "label": "Medical / Aviation Health",
        "short_label": "Medical",
        "days_label": "days to review",
        "focus_label": "Suggested focus",
        "icon": "medical",
        "colour": "#DC2626",
        "focus_defaults": ["Consistency", "Sleep", "Hydration", "Nutrition", "Moderate training"],
        "safety_note": (
            "CrewFit can support healthier habits, general fitness and consistency around your review. "
            "It does not provide medical advice — please speak to your doctor or aviation medical examiner "
            "for medical guidance, and never stop or change medication without their input."
        ),
    },
    "aviation_work": {
        "label": "Aviation / Work",
        "short_label": "Work",
        "days_label": "days to assessment",
        "focus_label": "Work readiness",
        "icon": "airplane",
        "colour": "#F59E0B",
        "focus_defaults": ["Sleep", "Energy", "Recovery", "Confidence", "Avoid overload"],
    },
    "sport_hobby": {
        "label": "Sport / Hobby",
        "short_label": "Activity",
        "days_label": "days to activity",
        "focus_label": "Training support",
        "icon": "fitness",
        "colour": "#22C55E",
        "focus_defaults": ["Freshness", "Mobility", "Recovery"],
    },
    "personal": {
        "label": "Personal Goal",
        "short_label": "Personal",
        "days_label": "days to event",
        "focus_label": "Personal target",
        "icon": "star",
        "colour": "#8B5CF6",
        "focus_defaults": ["Consistency", "Confidence", "Habits", "Progress"],
    },
}

# ---------------------------------------------------------------------------
# Event type catalog. Each entry maps a display-friendly slug to a category
# and suggested UI defaults. Callers can extend `event_type` freely — anything
# unknown is inferred by `_categorise_by_name()`.
# ---------------------------------------------------------------------------

EVENT_CATALOG: list[dict[str, Any]] = [
    # --- Race / Endurance ---
    {"slug": "5k", "label": "5K", "category": "race", "icon": "walk", "duration_min": 20},
    {"slug": "10k", "label": "10K", "category": "race", "icon": "walk", "duration_min": 45},
    {"slug": "half_marathon", "label": "Half Marathon", "category": "race", "icon": "walk", "duration_min": 100},
    {"slug": "marathon", "label": "Marathon", "category": "race", "icon": "flag", "duration_min": 220},
    {"slug": "ultramarathon", "label": "Ultra Marathon", "category": "race", "icon": "flag", "duration_min": 480},
    {"slug": "sprint_tri", "label": "Sprint Triathlon", "category": "race", "icon": "speedometer"},
    {"slug": "olympic_tri", "label": "Olympic Triathlon", "category": "race", "icon": "medal-outline"},
    {"slug": "ironman_70_3", "label": "Ironman 70.3", "category": "race", "icon": "trophy"},
    {"slug": "full_ironman", "label": "Full Ironman", "category": "race", "icon": "trophy"},
    {"slug": "cycling_event", "label": "Cycling Event", "category": "race", "icon": "bicycle"},
    {"slug": "swimming_event", "label": "Swimming Event", "category": "race", "icon": "water"},
    {"slug": "hyrox", "label": "HYROX", "category": "race", "icon": "flame"},
    {"slug": "obstacle_race", "label": "Obstacle Race", "category": "race", "icon": "flame"},
    # --- Medical / Health ---
    {"slug": "airline_medical", "label": "Airline Medical Renewal", "category": "medical", "icon": "medical"},
    {"slug": "blood_pressure", "label": "Blood Pressure Check", "category": "medical", "icon": "heart"},
    {"slug": "cholesterol", "label": "Cholesterol Check", "category": "medical", "icon": "pulse"},
    {"slug": "body_comp", "label": "Body Composition Target", "category": "medical", "icon": "body"},
    {"slug": "gp_review", "label": "GP / Health Review", "category": "medical", "icon": "medkit"},
    {"slug": "physio_review", "label": "Physio / Injury Review", "category": "medical", "icon": "bandage"},
    {"slug": "return_to_training", "label": "Return To Training", "category": "medical", "icon": "refresh"},
    {"slug": "fitness_to_fly", "label": "Fitness To Fly Assessment", "category": "medical", "icon": "shield-checkmark"},
    # --- Aviation / Work ---
    {"slug": "simulator", "label": "Simulator Assessment", "category": "aviation_work", "icon": "airplane"},
    {"slug": "line_check", "label": "Line Check", "category": "aviation_work", "icon": "clipboard"},
    {"slug": "recurrent", "label": "Recurrent Training", "category": "aviation_work", "icon": "school"},
    {"slug": "new_roster_block", "label": "New Roster Block", "category": "aviation_work", "icon": "calendar"},
    {"slug": "busy_month", "label": "Busy Flying Month", "category": "aviation_work", "icon": "trending-up"},
    {"slug": "return_to_flying", "label": "Return To Flying", "category": "aviation_work", "icon": "airplane"},
    {"slug": "base_move", "label": "Base Move", "category": "aviation_work", "icon": "swap-horizontal"},
    {"slug": "training_course", "label": "Training Course", "category": "aviation_work", "icon": "book"},
    # --- Sport / Hobby ---
    {"slug": "tennis", "label": "Tennis", "category": "sport_hobby", "icon": "tennisball"},
    {"slug": "padel", "label": "Padel", "category": "sport_hobby", "icon": "tennisball"},
    {"slug": "football", "label": "Football", "category": "sport_hobby", "icon": "football"},
    {"slug": "diving", "label": "Diving", "category": "sport_hobby", "icon": "water"},
    {"slug": "hiking", "label": "Hiking", "category": "sport_hobby", "icon": "trail-sign"},
    {"slug": "skiing", "label": "Skiing", "category": "sport_hobby", "icon": "snow"},
    {"slug": "golf", "label": "Golf", "category": "sport_hobby", "icon": "golf"},
    {"slug": "surfing", "label": "Surfing", "category": "sport_hobby", "icon": "water"},
    {"slug": "climbing", "label": "Climbing", "category": "sport_hobby", "icon": "trending-up"},
    {"slug": "martial_arts", "label": "Martial Arts", "category": "sport_hobby", "icon": "flame"},
    {"slug": "yoga_retreat", "label": "Yoga Retreat", "category": "sport_hobby", "icon": "leaf"},
    {"slug": "fitness_holiday", "label": "Fitness Holiday", "category": "sport_hobby", "icon": "sunny"},
    # --- Personal ---
    {"slug": "holiday", "label": "Holiday", "category": "personal", "icon": "sunny"},
    {"slug": "wedding", "label": "Wedding", "category": "personal", "icon": "heart"},
    {"slug": "photoshoot", "label": "Photoshoot", "category": "personal", "icon": "camera"},
    {"slug": "confidence_goal", "label": "Confidence Goal", "category": "personal", "icon": "star"},
    {"slug": "uniform_confidence", "label": "Uniform Confidence Goal", "category": "personal", "icon": "shirt"},
    {"slug": "milestone", "label": "General Milestone", "category": "personal", "icon": "flag"},
    {"slug": "custom", "label": "Custom Event", "category": "personal", "icon": "add-circle"},
]

_CATALOG_BY_SLUG = {e["slug"]: e for e in EVENT_CATALOG}


def _categorise_by_name(name: str, event_type: str = "") -> tuple[str, Optional[dict]]:
    """
    Best-effort category inference for legacy or free-text events.
    Returns (category, catalog_entry_or_None).
    """
    hay = f"{name or ''} {event_type or ''}".lower()
    # First: direct catalog slug match
    for slug, meta in _CATALOG_BY_SLUG.items():
        if slug in hay or meta["label"].lower() in hay:
            return meta["category"], meta

    def hit(*keywords: str) -> bool:
        return any(k in hay for k in keywords)

    if hit("medical", "renewal", "blood pressure", "cholesterol", "gp ", "gp appointment",
           "physio", "injury review", "fit to fly", "fitness to fly", "airline medical",
           "health check", "body composition"):
        return "medical", None
    if hit("simulator", "sim check", "line check", "recurrent", "roster block",
           "busy month", "return to flying", "base move", "training course"):
        return "aviation_work", None
    if hit("tennis", "padel", "football", "diving", "hiking", "skiing", "golf",
           "surfing", "climbing", "martial", "yoga", "fitness holiday"):
        return "sport_hobby", None
    if hit("holiday", "wedding", "photoshoot", "confidence", "uniform", "milestone"):
        return "personal", None
    if hit("5k", "10k", "marathon", "triathlon", "ironman", "hyrox", "cycling",
           "swim event", "obstacle", "race"):
        return "race", None
    # Fallback: race for backwards compatibility.
    return "race", None


def _days_between(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        d = _dt.date.fromisoformat(iso[:10])
    except Exception:
        return None
    return (d - _dt.date.today()).days


def enrich_event(ev: Optional[dict]) -> Optional[dict]:
    """Add category-derived UI fields to an event doc. Non-destructive."""
    if not ev:
        return ev
    cat = ev.get("category")
    if not cat:
        cat, _ = _categorise_by_name(ev.get("event_name", ""), ev.get("event_type", ""))
    meta = CATEGORY_META.get(cat) or CATEGORY_META["race"]
    days = _days_between(ev.get("event_date"))
    ev["category"] = cat
    ev["category_label"] = meta["label"]
    ev["category_short"] = meta["short_label"]
    ev["days_label"] = meta["days_label"]
    ev["days_value"] = days
    ev["focus_label"] = meta["focus_label"]
    ev["focus_defaults"] = meta.get("focus_defaults") or []
    ev["category_icon"] = meta["icon"]
    ev["category_colour"] = meta["colour"]
    if meta.get("safety_note"):
        ev["safety_note"] = meta["safety_note"]
    # Legacy-friendly duplicate: keep phase_info if already there.
    ev.setdefault("is_race", cat == "race")
    return ev


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@api.get("/events/catalog")
async def events_catalog(_: dict = Depends(current_user)):
    return {
        "categories": [{"key": k, **v} for k, v in CATEGORY_META.items()],
        "events": EVENT_CATALOG,
    }


@api.post("/events/backfill-categories")
async def events_backfill(_: dict = Depends(current_user)):
    """Coach/admin-callable safety net: re-categorise any events that don't yet
    have a category (or where the stored category is missing/None)."""
    q = {"$or": [{"category": {"$in": [None, "", "unknown"]}}, {"category": {"$exists": False}}]}
    rows = await db.events.find(q, {"_id": 0}).to_list(2000)
    updated = 0
    for r in rows:
        cat, _meta = _categorise_by_name(r.get("event_name", ""), r.get("event_type", ""))
        await db.events.update_one({"id": r["id"]}, {"$set": {"category": cat, "updated_at": now_iso()}})
        updated += 1
    return {"updated": updated, "total_missing": len(rows)}


# ---------------------------------------------------------------------------
# Startup backfill (best-effort, non-fatal).
# ---------------------------------------------------------------------------

async def _startup_backfill() -> None:
    try:
        q = {"$or": [{"category": {"$in": [None, "", "unknown"]}}, {"category": {"$exists": False}}]}
        rows = await db.events.find(q, {"_id": 0}).to_list(5000)
        for r in rows:
            cat, _meta = _categorise_by_name(r.get("event_name", ""), r.get("event_type", ""))
            await db.events.update_one({"id": r["id"]}, {"$set": {"category": cat, "updated_at": now_iso()}})
        if rows:
            logger.info("event_categories: backfilled %d event(s)", len(rows))
    except Exception:
        logger.exception("event_categories: startup backfill failed (non-fatal)")


import asyncio as _asyncio  # noqa: E402
try:
    _asyncio.get_event_loop().create_task(_startup_backfill())
except Exception:
    # If no loop yet (imported at module time before the app starts), skip.
    pass
