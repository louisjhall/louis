"""
feature_layover_naming.py — Iter 102

Deterministic workout renaming for layover days.

When CrewFit detects a layover, the workout title must include the detected
destination (IATA code preferred, city fallback) so clients see at a glance
that the session was built around their actual roster.

Rules (per Iter 102 spec):

1. If the roster day has day_type containing "layover" (case-insensitive)
   OR day_label ∈ {LAYOVER_DAY, LAYOVER_REST_DAY, LONG_HAUL_LAYOVER, ...},
   apply the naming template:

       [DEST] Layover [Workout Type]

   Examples:
     ICN Layover Hotel Gym Strength     (hotel gym confirmed)
     BCN Layover Bodyweight Session     (hotel gym unavailable)
     MEX Layover Mobility               (mobility focus)
     NBO Layover Recovery               (recovery focus)
     ICN Layover Hotel/Bodyweight Session   (hotel gym state unknown)

2. Hotel gym state:
     - gym_available=True     → "Hotel Gym ..." variant
     - gym_available=False    → "Bodyweight ..." variant
     - gym_available=None     → "Hotel/Bodyweight ..." variant (unknown)

3. Destination unclear → fall back to a generic
     "Layover Mobility" / "Layover Recovery" / "Layover Bodyweight Session"
   AND flag `needs_destination_review=True` for coach review.

4. Every renamed workout gets a `layover_context` object populated with:
     - destination (str or None)
     - hotel_gym_state ∈ {"confirmed","unavailable","unknown"}
     - workout_type (human-readable)
     - client_reason (short line for the workout card)
     - coach_reason (longer line for Louis's dashboard)
     - needs_destination_review (bool)

5. Cross-airline: applied uniformly. The naming rule doesn't care about the
   airline field on the roster — only the parsed layover metadata.

6. Coach edits: if a workout has `title_manually_edited_by_coach=True` the
   renamer LEAVES it alone. Louis's manual overrides are respected.

Public entry point:
    apply_layover_naming(workouts: list[dict], roster: dict, airline: Optional[str]) -> dict
    → mutates workouts in place; returns a small stats dict for logging.

The renamer is safe to run multiple times (idempotent-ish — repeated calls
with the same inputs produce the same title without stacking prefixes).
"""
from __future__ import annotations
from typing import Optional


# ------------------------------- helpers -----------------------------------
_LAYOVER_MARKERS = ("layover", "long_haul_layover", "layover_rest", "layover_day",
                    "layover_full", "layover_arrival", "layover_departure")


def _is_layover_day(rday: dict) -> bool:
    dt = str((rday or {}).get("day_type") or "").strip().lower()
    if not dt:
        return False
    return any(m in dt for m in _LAYOVER_MARKERS)


def _extract_dest(rday: dict) -> Optional[str]:
    """Return the display destination for the title.

    Preference:
      1. layover_city if it is 3 uppercase letters (IATA)
      2. First flight `to` field if 3 uppercase letters (IATA)
      3. layover_city as-is if it's a short human name (<= 6 chars)
         — folded to uppercase (e.g. "Seoul" → "SEOUL" is too long, so we
         only accept short names to keep the title tight)
    Returns None when nothing usable was found.
    """
    if not rday:
        return None

    def _as_iata(v) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().upper()
        if len(s) == 3 and s.isalpha():
            return s
        return None

    # 1 & 2 — IATA-style codes
    for cand in (rday.get("layover_city"), *[f.get("to") for f in (rday.get("flights") or [])]):
        code = _as_iata(cand)
        if code:
            return code

    # 3 — short city name
    city = rday.get("layover_city")
    if city:
        s = str(city).strip()
        if 2 <= len(s) <= 6:
            return s.upper()

    return None


def _hotel_gym_state(rday: dict) -> str:
    """Return 'confirmed' | 'unavailable' | 'unknown'."""
    hotel = (rday or {}).get("hotel") or {}
    ga = hotel.get("gym_available")
    if ga is True:
        return "confirmed"
    if ga is False:
        return "unavailable"
    return "unknown"


def _detect_workout_type(workout: dict, hotel_state: str) -> str:
    """Map current workout focus / title into a short human descriptor.

    Order of precedence:
      recovery → Recovery
      mobility / stretch → Mobility
      conditioning / cardio → Conditioning
      strength / gym → varies by hotel state:
          confirmed   → "Hotel Gym Strength"
          unavailable → "Bodyweight Strength"
          unknown     → "Hotel/Bodyweight Strength"
      bodyweight (explicit) → "Bodyweight Session"
      else → default per hotel state:
          confirmed   → "Hotel Gym Session"
          unavailable → "Bodyweight Session"
          unknown     → "Hotel/Bodyweight Session"
    """
    focus = str(workout.get("focus") or "").strip().lower()
    title = str(workout.get("title") or "").strip().lower()
    combined = f"{focus} {title}"

    def _has(kw: str) -> bool:
        return kw in combined

    if _has("recovery"):
        return "Recovery"
    if _has("mobility") or _has("stretch"):
        return "Mobility"
    if _has("conditioning") or _has("cardio") or _has("intervals") or _has("tempo"):
        return "Conditioning"
    if _has("strength") or _has("gym") or _has("power"):
        return {
            "confirmed":   "Hotel Gym Strength",
            "unavailable": "Bodyweight Strength",
            "unknown":     "Hotel/Bodyweight Strength",
        }[hotel_state]
    if _has("bodyweight"):
        return "Bodyweight Session"
    # Default when the focus/title gives us no strong signal
    return {
        "confirmed":   "Hotel Gym Session",
        "unavailable": "Bodyweight Session",
        "unknown":     "Hotel/Bodyweight Session",
    }[hotel_state]


def _client_reason(dest: Optional[str], hotel_state: str) -> str:
    """Short line shown on the workout card. No AI / algorithm wording."""
    if not dest:
        return "CrewFit has adjusted this around your layover."
    if hotel_state == "confirmed":
        return f"Built around your {dest} layover with hotel gym access."
    if hotel_state == "unavailable":
        return f"Built around your {dest} layover — bodyweight-safe option."
    # unknown
    return f"Selected for your {dest} layover with hotel/bodyweight options."


def _coach_reason(dest: Optional[str], hotel_state: str, airline: Optional[str]) -> str:
    """Longer, coach-facing reason line for Louis's dashboard."""
    airline_bit = f" from {airline}" if airline else ""
    if not dest:
        return (
            f"Layover detected{airline_bit} roster but destination is unclear "
            "— needs manual review before publishing."
        )
    if hotel_state == "confirmed":
        return (
            f"{dest} layover detected{airline_bit} roster. "
            "Hotel gym confirmed — Hotel Gym variant selected."
        )
    if hotel_state == "unavailable":
        return (
            f"{dest} layover detected{airline_bit} roster. "
            "Hotel gym unavailable — bodyweight-safe option selected."
        )
    return (
        f"{dest} layover detected{airline_bit} roster. "
        "Hotel gym unknown — bodyweight-safe option selected."
    )


# ------------------------------- entrypoint --------------------------------
def apply_layover_naming(
    workouts: list[dict],
    roster: dict,
    airline: Optional[str] = None,
) -> dict:
    """Rewrite titles for layover-day workouts in place.

    - Skips workouts marked `title_manually_edited_by_coach=True`.
    - Skips workouts whose focus is 'rest' or 'off' (those become a rest card,
      not a workout, so renaming is meaningless).

    Returns a stats dict for logging: `{"renamed": n, "needs_review": m}`.
    """
    if not workouts or not isinstance(workouts, list):
        return {"renamed": 0, "needs_review": 0}

    days_by_date = {}
    for d in (roster or {}).get("days") or []:
        if isinstance(d, dict) and d.get("date"):
            days_by_date[d["date"]] = d

    airline_slug = None
    if airline:
        airline_slug = str(airline).strip().title() or None

    renamed = 0
    needs_review = 0

    for w in workouts:
        if not isinstance(w, dict):
            continue
        if w.get("title_manually_edited_by_coach"):
            continue
        focus = str(w.get("focus") or "").strip().lower()
        if focus in {"rest", "off"}:
            continue

        rday = days_by_date.get(w.get("date"))
        if not rday or not _is_layover_day(rday):
            # Not a layover day. If we've previously renamed this workout,
            # clear the stale layover_context so the frontend doesn't show a
            # stale reason line after a roster edit.
            w.pop("layover_context", None)
            continue

        dest = _extract_dest(rday)
        hotel_state = _hotel_gym_state(rday)
        wtype = _detect_workout_type(w, hotel_state)

        if dest:
            new_title = f"{dest} Layover {wtype}"
        else:
            # Fallback: strip hotel/bodyweight combinator noise when no dest.
            simple = (
                "Recovery" if wtype == "Recovery"
                else "Mobility" if wtype == "Mobility"
                else "Conditioning" if wtype == "Conditioning"
                else "Bodyweight Session"
                if "Bodyweight" in wtype or hotel_state != "confirmed"
                else "Hotel Gym Session"
            )
            new_title = f"Layover {simple}"
            needs_review += 1

        w["title"] = new_title
        w["layover_context"] = {
            "destination": dest,
            "hotel_gym_state": hotel_state,
            "workout_type": wtype,
            "client_reason": _client_reason(dest, hotel_state),
            "coach_reason": _coach_reason(dest, hotel_state, airline_slug),
            "needs_destination_review": dest is None,
            "airline": airline_slug,
        }
        renamed += 1

    return {"renamed": renamed, "needs_review": needs_review}
