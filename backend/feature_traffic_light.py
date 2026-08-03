"""
feature_traffic_light — Phase 3 of the Programme Generation Upgrade.

Traffic Light variants let the client dial the session up or down without
losing coaching context:

* GREEN  — the full planned session (as generated).
* AMBER  — ~65% volume: fewer sets, tighter exercise list, shorter duration.
           Purpose: "I'm tired / short on time but still want to move."
* RED    — recovery mode: mobility + parasympathetic breathwork.
           Content is context-aware based on the day's roster type
           (long-haul recovery, night-flight, layover, etc.).

Storage: each workout doc has `variants: {green, amber, red}` (stub added in
Phase 1). Newly generated workouts populate all three inline via the LLM.
Legacy workouts (empty stubs) are lazily backfilled on read using the
algorithmic derivers below, then persisted so the fill happens once per doc.

Frontend surface: three chips (Green / Amber / Red) on the workout screen.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException

from server import api, db, current_user, now_iso, logger


VARIANT_KEYS = ("green", "amber", "red")


# ---------------------------------------------------------------------------
# Algorithmic derivation (for lazy backfill on legacy workouts)
# ---------------------------------------------------------------------------

def _scale_reps(reps: Any, factor: float) -> Any:
    """Reduce a reps value proportionally. Accepts int, str ('12'), or a range
    ('8-10', '10-12'). Ranges are shrunk by `factor` and rejoined.
    Non-parseable values pass through untouched."""
    try:
        if isinstance(reps, int):
            return max(4, int(round(reps * factor)))
        if isinstance(reps, str):
            s = reps.strip()
            if "-" in s:
                a, _, b = s.partition("-")
                a2 = max(4, int(round(int(a.strip()) * factor)))
                b2 = max(a2, int(round(int(b.strip()) * factor)))
                return f"{a2}-{b2}"
            if s.isdigit():
                return str(max(4, int(round(int(s) * factor))))
            return s
    except Exception:
        return reps
    return reps


def _derive_amber(green: dict) -> dict:
    """Amber = ~65% volume of Green. Keeps the same movement pattern so the
    client still gets the training stimulus, just lighter."""
    factor = 0.65
    exs_in = green.get("exercises") or []
    # Drop the last exercise for sessions with 5+ movements (accessory culls first).
    keep = exs_in if len(exs_in) <= 4 else exs_in[:-1]
    exs_out = []
    for e in keep:
        e2 = dict(e)
        try:
            sets = int(e.get("sets") or 3)
            e2["sets"] = max(2, int(round(sets * factor)))
        except Exception:
            pass
        e2["reps"] = _scale_reps(e.get("reps"), 0.85)  # reps taper less than sets
        try:
            rest = int(e.get("rest_sec") or 60)
            e2["rest_sec"] = max(30, rest)
        except Exception:
            pass
        if e.get("rpe") is not None:
            try:
                e2["rpe"] = max(5, int(e.get("rpe")) - 1)
            except Exception:
                pass
        exs_out.append(e2)
    duration = green.get("duration_min") or 40
    try:
        new_dur = max(20, int(round(int(duration) * factor)))
    except Exception:
        new_dur = 25
    return {
        "title": f"{green.get('title', 'Session')} — LIGHTER",
        "duration_min": new_dur,
        "focus": green.get("focus", "full"),
        "warmup": green.get("warmup") or [],
        "exercises": exs_out,
        "rationale": (
            "Reduced-volume version of today's plan — same movement pattern, "
            "fewer sets and a shorter session so you still make progress on a "
            "low-energy day."
        ),
        "intensity_note": "Aim for RPE 6. Stop 2 reps shy of failure.",
    }


def _red_template(context_tag: str) -> dict:
    """Context-aware Red variants. `context_tag` is derived from the roster
    day: long_haul / night_flight / layover / standby / recovery / default."""
    templates = {
        "long_haul": {
            "title": "Post-flight Recovery",
            "duration_min": 12,
            "focus": "recovery",
            "warmup": [],
            "exercises": [
                {"name": "Legs-up-the-wall", "sets": 1, "reps": "3 minutes", "rest_sec": 0, "notes": "Drain the calves and lower back after a long sit."},
                {"name": "Couch stretch (per side)", "sets": 1, "reps": "90 seconds", "rest_sec": 30, "notes": "Open the hip flexors compressed by seated flight."},
                {"name": "Cat / cow", "sets": 1, "reps": "10 slow", "rest_sec": 0},
                {"name": "Thoracic openers", "sets": 1, "reps": "8 per side", "rest_sec": 0, "notes": "Restore rotation."},
                {"name": "Box breathing 4-4-4-4", "sets": 1, "reps": "5 minutes", "rest_sec": 0, "notes": "Down-regulate the nervous system."},
            ],
            "rationale": "Long-haul recovery flow: calf drain, hip flexor release, thoracic reset, and box breathing to bring your nervous system back to baseline.",
            "intensity_note": "Slow and easy. This should feel restorative, not effortful.",
        },
        "night_flight": {
            "title": "Night-flight Reset",
            "duration_min": 10,
            "focus": "recovery",
            "warmup": [],
            "exercises": [
                {"name": "Gentle spinal roll-downs", "sets": 1, "reps": "6 slow", "rest_sec": 0},
                {"name": "Child's pose", "sets": 1, "reps": "90 seconds", "rest_sec": 0},
                {"name": "Neck circles + shoulder rolls", "sets": 1, "reps": "8 per direction", "rest_sec": 0},
                {"name": "Physiological sigh", "sets": 3, "reps": "12 breaths", "rest_sec": 30, "notes": "Double inhale, long exhale — drops sympathetic drive fast."},
                {"name": "4-7-8 breath", "sets": 1, "reps": "5 minutes", "rest_sec": 0, "notes": "Prime your body for sleep."},
            ],
            "rationale": "Gentle mobility and parasympathetic breathwork to bring you down from night-flight arousal so you actually sleep.",
            "intensity_note": "Zero exertion. Prioritise long exhales.",
        },
        "layover": {
            "title": "Layover Reset",
            "duration_min": 15,
            "focus": "recovery",
            "warmup": [],
            "exercises": [
                {"name": "World's greatest stretch (per side)", "sets": 1, "reps": "5", "rest_sec": 0},
                {"name": "Hip flexor + T-spine combo", "sets": 1, "reps": "6 per side", "rest_sec": 0},
                {"name": "Loaded carry (bag as weight)", "sets": 2, "reps": "40 seconds", "rest_sec": 40, "notes": "Suitcase carry — grip and core."},
                {"name": "Nasal breathing walk", "sets": 1, "reps": "5 minutes", "rest_sec": 0, "notes": "Around the hotel corridor is fine."},
            ],
            "rationale": "Layover flow — open up what got compressed on the flight and prime the body without burning recovery you need for the return leg.",
            "intensity_note": "Feel-good, no soreness.",
        },
        "standby": {
            "title": "Standby Mobility",
            "duration_min": 12,
            "focus": "recovery",
            "warmup": [],
            "exercises": [
                {"name": "Full body flow (sun salutation)", "sets": 3, "reps": "1 round", "rest_sec": 30},
                {"name": "Deep squat hold", "sets": 1, "reps": "60 seconds", "rest_sec": 0},
                {"name": "Box breathing 4-4-4-4", "sets": 1, "reps": "5 minutes", "rest_sec": 0},
            ],
            "rationale": "Short, quiet flow you can do without changing clothes — keeps you loose while you wait on the call-out.",
            "intensity_note": "Ready to fly at 30 minutes notice — no lactic burn.",
        },
        "default": {
            "title": "Recovery Session",
            "duration_min": 12,
            "focus": "recovery",
            "warmup": [],
            "exercises": [
                {"name": "Cat / cow", "sets": 1, "reps": "10 slow", "rest_sec": 0},
                {"name": "Child's pose to cobra flow", "sets": 1, "reps": "8", "rest_sec": 0},
                {"name": "Hip 90/90 (per side)", "sets": 1, "reps": "6", "rest_sec": 0},
                {"name": "Thoracic openers", "sets": 1, "reps": "8 per side", "rest_sec": 0},
                {"name": "Box breathing 4-4-4-4", "sets": 1, "reps": "5 minutes", "rest_sec": 0},
            ],
            "rationale": "Full-body mobility flow plus box breathing — the right call on a genuinely low-energy day.",
            "intensity_note": "Move slow. If it feels like effort, back off.",
        },
    }
    return templates.get(context_tag) or templates["default"]


def _context_tag_for_workout(w: dict, roster: Optional[dict]) -> str:
    """Pick a Red template based on the roster day matching this workout."""
    if not roster:
        return "default"
    date = w.get("date")
    day = next((d for d in (roster.get("days") or []) if d.get("date") == date), None)
    if not day:
        return "default"
    day_type = str(day.get("day_type") or "").lower()
    flights = day.get("flights") or []
    # Long-haul cue: any flight >= 6h or explicit day_type mention.
    for f in flights:
        try:
            dur = float(f.get("flight_time_hours") or 0)
            if dur >= 6:
                return "long_haul"
        except Exception:
            pass
    if "night" in day_type or any((f.get("night_flight") for f in flights)):
        return "night_flight"
    if "layover" in day_type:
        return "layover"
    if "standby" in day_type or "reserve" in day_type:
        return "standby"
    return "default"


def _green_from_workout(w: dict) -> dict:
    """Extract a Green variant snapshot from the workout's primary fields."""
    return {
        "title": w.get("title", "Session"),
        "duration_min": w.get("duration_min", 40),
        "focus": w.get("focus", "full"),
        "warmup": w.get("warmup") or [],
        "exercises": w.get("exercises") or [],
        "rationale": w.get("rationale") or "",
        "intensity_note": "Full planned session — aim for the prescribed RPE.",
    }


async def _resolve_variant_library_ids(variant: dict, *, owner: dict, workout_id: str,
                                       reason: str) -> None:
    """Manual Mode Stage B — every exercise inside a variant must be
    backed by an `exercises_v2` record so it appears in the coach media
    queue and its media can be reviewed. Amber inherits Green's exercise
    ids (already resolved). Red comes from hardcoded templates with names
    only — we look each name up (or file a draft) so it becomes real.

    Mutates `variant["exercises"]` in place. Never raises."""
    try:
        from feature_media_queue import backfill_exercise_ids
        exs = variant.get("exercises") or []
        if not exs:
            return
        await backfill_exercise_ids(
            exs, user=owner, reason=reason, workout_id=workout_id,
        )
    except Exception:
        logger.exception("traffic_light: variant library backfill failed for wid=%s", workout_id)


async def derive_variants(w: dict) -> dict:
    """Algorithmic backfill for legacy workouts. Green from the primary
    fields, Amber via `_derive_amber`, Red from `_red_template` picked by
    the workout's roster-day context."""
    green = _green_from_workout(w)
    amber = _derive_amber(green)
    roster = None
    rid = w.get("roster_id")
    if rid:
        try:
            roster = await db.rosters.find_one({"id": rid}, {"_id": 0})
        except Exception:
            roster = None
    tag = _context_tag_for_workout(w, roster)
    red = _red_template(tag)
    red["context_tag"] = tag
    return {"green": green, "amber": amber, "red": red}


def _variants_populated(variants: Optional[dict]) -> bool:
    if not isinstance(variants, dict):
        return False
    return all(isinstance(variants.get(k), dict) and variants[k] for k in VARIANT_KEYS)


async def ensure_variants(w: dict, *, persist: bool = True) -> dict:
    """Guarantee `w['variants']` is fully populated. If not, derive them and
    optionally persist to the DB. Idempotent.

    Manual Mode Stage B/F — after deriving, we (a) resolve every variant
    exercise name to a real `exercises_v2` record (creating a draft if
    missing) so the coach media queue picks them up, and (b) scan the
    combined variant sections through the shared media-queue helper so
    missing media gets queued exactly once."""
    if _variants_populated(w.get("variants")):
        return w["variants"]
    variants = await derive_variants(w)

    # Resolve library ids for every variant so the coach media queue works.
    # `owner` is the client whose workout this is — we surface the user_id
    # on the draft library rows so demand-based urgency scoring is correct.
    owner: dict = {"id": w.get("user_id")}
    wid = w.get("id") or ""
    for v_key in VARIANT_KEYS:
        try:
            await _resolve_variant_library_ids(
                variants.get(v_key) or {},
                owner=owner, workout_id=wid,
                reason=f"traffic_light_{v_key}_backfill",
            )
        except Exception:
            logger.exception("ensure_variants: %s library backfill failed for wid=%s", v_key, wid)

    # Media queue scan across all three variants — deduped internally.
    try:
        from feature_media_queue import scan_media_queue_for_sections
        sections = {
            k: (variants.get(k) or {}).get("exercises") or []
            for k in VARIANT_KEYS
        }
        await scan_media_queue_for_sections(
            owner, sections, workout_id=wid,
            reason="traffic_light_variants",
        )
    except Exception:
        logger.exception("ensure_variants: media queue scan failed for wid=%s", wid)

    if persist:
        try:
            await db.workouts.update_one(
                {"id": w["id"]},
                {"$set": {"variants": variants, "variants_source": "derived", "updated_at": now_iso()}},
            )
        except Exception:
            logger.exception("ensure_variants: persist failed for wid=%s", w.get("id"))
    return variants


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.get("/workouts/{wid}/variants")
async def workout_variants(wid: str, user: dict = Depends(current_user)):
    """Return the three variants for a workout, backfilling on the fly for
    legacy workouts. Client hits this once and then toggles locally."""
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "Not found")
    if user["role"] == "client" and w.get("user_id") != user["id"]:
        raise HTTPException(403, "Forbidden")
    variants = await ensure_variants(w)
    return {
        "workout_id": wid,
        "variants": variants,
        "source": w.get("variants_source") if _variants_populated(w.get("variants")) else "derived",
    }


class SelectVariantBody(__import__("pydantic").BaseModel):
    variant: str  # "green" | "amber" | "red"


@api.post("/workouts/{wid}/select-variant")
async def workout_select_variant(wid: str, body: SelectVariantBody, user: dict = Depends(current_user)):
    """Record the client's selected variant for the session (analytics + so
    the coach dashboard can see whether the client dialled sessions down)."""
    if body.variant not in VARIANT_KEYS:
        raise HTTPException(400, f"variant must be one of {VARIANT_KEYS}")
    w = await db.workouts.find_one({"id": wid}, {"_id": 0})
    if not w:
        raise HTTPException(404, "Not found")
    if user["role"] == "client" and w.get("user_id") != user["id"]:
        raise HTTPException(403, "Forbidden")
    await db.workouts.update_one(
        {"id": wid},
        {"$set": {"selected_variant": body.variant, "selected_variant_at": now_iso(), "updated_at": now_iso()}},
    )
    return {"ok": True, "variant": body.variant}
