"""
Coach Notes — Tier 1 per-client structured coaching overrides.

Purpose:
    Free-form coach corrections/preferences that persist on the user
    record and are injected into every future workout-generation LLM
    prompt. Complements (does NOT replace):
        * coach_dna / coaching_dna (long-term inferred profile)
        * parser_constraints (per-day roster safety rules)
        * coach_locked workouts (frozen sessions)

Schema (users.coach_notes):
    {
      "preferences": str,      # "Loves KBs, hates burpees"
      "cautions": str,         # "Left shoulder — no OHP until Aug"
      "goal_override": str,    # "Actually marathon in Nov"
      "weekly_shape": str,     # "Strength Mon/Wed/Fri, run Tue/Sat"
      "notes": str,            # Free-form catch-all
      "updated_at": iso,
      "updated_by": coach_id,
      "updated_by_name": coach_name,
    }

Endpoints:
    * GET  /api/coach/clients/{cid}/coach-notes
    * PUT  /api/coach/clients/{cid}/coach-notes
    * GET  /api/coach/coach-notes-for-prompt/{cid}   (internal helper — never called by UI)
"""
from __future__ import annotations
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, now_iso
import logging
logger = logging.getLogger("crewfit.coach_notes")


# Reasonable soft caps per slot — the coach can be verbose but the prompt
# stays fast to read and the LLM stays focused.
MAX_SLOT_LEN = 700
MAX_NOTES_LEN = 1500


class CoachNotesBody(BaseModel):
    preferences: str = Field(default="", max_length=MAX_SLOT_LEN)
    cautions: str = Field(default="", max_length=MAX_SLOT_LEN)
    goal_override: str = Field(default="", max_length=MAX_SLOT_LEN)
    weekly_shape: str = Field(default="", max_length=MAX_SLOT_LEN)
    notes: str = Field(default="", max_length=MAX_NOTES_LEN)


def _empty_notes() -> dict:
    return {
        "preferences": "", "cautions": "", "goal_override": "",
        "weekly_shape": "", "notes": "",
        "updated_at": None, "updated_by": None, "updated_by_name": None,
    }


def coach_notes_for_prompt(user_doc: dict | None) -> Optional[dict]:
    """Return a compact payload for injection into the plan generator's
    LLM prompt. Returns None if every slot is empty."""
    if not user_doc:
        return None
    notes = user_doc.get("coach_notes") or {}
    payload = {
        k: (notes.get(k) or "").strip()
        for k in ("preferences", "cautions", "goal_override", "weekly_shape", "notes")
    }
    if not any(payload.values()):
        return None
    payload["updated_at"] = notes.get("updated_at")
    payload["updated_by_name"] = notes.get("updated_by_name")
    return payload


# ---------------------------------------------------------------------------
# Iter 108 — extract structured signals from freeform coach_notes text and
# apply them as OVERRIDES to the profile before workout generation.
# ---------------------------------------------------------------------------

def _extract_frequency(text: str) -> Optional[int]:
    """Match phrases like "4-5 x training per week", "5x per week",
    "5 sessions a week", etc. Return the target integer (upper bound if
    a range is given) or None."""
    if not text:
        return None
    import re
    s = text.lower()
    # Range: "4-5 x training per week" / "4 to 5 per week"
    m = re.search(r"(\d)\s*(?:-|to)\s*(\d)[^\d]*?(?:per|a|/)\s*week", s)
    if m:
        return int(m.group(2))
    # Single: "5 x per week" / "5x/week" / "5 sessions a week" / "5 days per week"
    m = re.search(r"(\d)\s*(?:x|sessions?|times?|days?|training)[^\d]*?(?:per|a|/)\s*week", s)
    if m:
        return int(m.group(1))
    return None


def _detect_goal(text: str) -> Optional[str]:
    """Detect a canonical goal_type from freeform text."""
    if not text:
        return None
    s = text.lower()
    if any(kw in s for kw in ("marathon", "half-marathon", "half marathon", "10k", "5k", "ultra", "ironman", "triathlon", "race", "event", "endurance")):
        return "endurance"
    if any(kw in s for kw in ("hypertrophy", "muscle", "build size", "get bigger")):
        return "hypertrophy"
    if any(kw in s for kw in ("strength", "get stronger", "1rm", "powerlift")):
        return "strength"
    if any(kw in s for kw in ("weight loss", "fat loss", "lose weight", "cut", "leaner", "leaning up")):
        return "fat_loss"
    if any(kw in s for kw in ("general fitness", "stay fit", "maintenance", "overall health")):
        return "general_fitness"
    return None


def _detect_equipment(text: str) -> Optional[list[str]]:
    """Detect a canonical equipment list from freeform text."""
    if not text:
        return None
    s = text.lower()
    kit: list[str] = []
    if "dumbbell" in s or "dumbells" in s or "dbs" in s: kit.append("dumbbells")
    if "kettlebell" in s or "kb" in s: kit.append("kettlebells")
    if "barbell" in s or "rack" in s: kit.append("barbell")
    if "treadmill" in s: kit.append("treadmill")
    if "bike" in s or "cycle" in s or "spin" in s: kit.append("bike")
    if "resistance band" in s or "bands" in s: kit.append("bands")
    if "pull up" in s or "pull-up" in s or "pullup" in s: kit.append("pullup_bar")
    if "bodyweight" in s or "no equipment" in s: kit.append("bodyweight")
    return kit or None


def apply_coach_note_overrides(profile: dict, user_doc: dict | None) -> dict:
    """Return a NEW profile dict with coach-note overrides applied.

    - `goal_override` mentioning "marathon"/"race"/etc. → profile['goal_type']
      (only if profile['goal_type'] is empty/None).
    - Frequency phrases "4-5 x per week" → profile['training_days_per_week']
      (only if higher than what's on the profile — we never REDUCE the cap
      based on a note, since that could over-demote real training days).
    - Equipment mentions in preferences → profile['equipment'] hints
      (added, never removed).

    Non-destructive: original profile is not mutated. Missing user_doc
    returns the profile unchanged.
    """
    if not user_doc:
        return dict(profile or {})
    p = dict(profile or {})
    notes = user_doc.get("coach_notes") or {}
    override = " ".join([
        str(notes.get("goal_override") or ""),
        str(notes.get("weekly_shape") or ""),
        str(notes.get("notes") or ""),
    ])
    prefs = str(notes.get("preferences") or "")

    # Goal: only override if profile.goal_type is unset — coach notes always
    # win against a NULL profile field.
    if not p.get("goal_type") and not p.get("goal"):
        g = _detect_goal(override)
        if g:
            p["goal_type"] = g
            p["goal"] = g
            p["_coach_note_override_goal"] = True

    # Frequency: prefer the coach's number if higher than the profile's
    # (never LOWER — that'd risk dropping legitimate sessions the client
    # already agreed to).
    freq = _extract_frequency(override)
    if freq and freq >= 1 and freq <= 7:
        existing = p.get("training_days_per_week") or 0
        try:
            existing = int(existing)
        except Exception:
            existing = 0
        if freq > existing:
            p["training_days_per_week"] = freq
            p["_coach_note_override_days"] = True

    # Equipment hints: additive only.
    kit = _detect_equipment(prefs)
    if kit:
        existing_kit = list(p.get("equipment") or [])
        for k in kit:
            if k not in existing_kit:
                existing_kit.append(k)
        p["equipment"] = existing_kit
        p["_coach_note_override_equipment"] = True

    return p


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.get("/coach/clients/{client_id}/coach-notes")
async def get_coach_notes(
    client_id: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "coach_notes": 1, "name": 1, "email": 1})
    if not user:
        raise HTTPException(404, "Client not found")
    notes = user.get("coach_notes") or _empty_notes()
    # Fill missing keys
    for k, v in _empty_notes().items():
        notes.setdefault(k, v)
    return {
        "client": {"id": client_id, "name": user.get("name") or user.get("email")},
        "notes": notes,
        "max_slot_length": MAX_SLOT_LEN,
        "max_notes_length": MAX_NOTES_LEN,
    }


@api.put("/coach/clients/{client_id}/coach-notes")
async def put_coach_notes(
    client_id: str,
    body: CoachNotesBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Client not found")

    notes = {
        "preferences": (body.preferences or "").strip(),
        "cautions": (body.cautions or "").strip(),
        "goal_override": (body.goal_override or "").strip(),
        "weekly_shape": (body.weekly_shape or "").strip(),
        "notes": (body.notes or "").strip(),
        "updated_at": now_iso(),
        "updated_by": coach.get("id"),
        "updated_by_name": coach.get("name") or coach.get("email") or "Louis",
    }
    await db.users.update_one({"id": client_id}, {"$set": {"coach_notes": notes}})

    # Audit trail — small collection so we can show a history later.
    try:
        await db.coach_notes_history.insert_one({
            "user_id": client_id,
            "coach_id": coach.get("id"),
            "coach_name": notes["updated_by_name"],
            "at": notes["updated_at"],
            "snapshot": {k: notes[k] for k in ("preferences", "cautions", "goal_override", "weekly_shape", "notes")},
        })
    except Exception:
        logger.exception("Failed to write coach_notes_history (non-fatal)")

    return {"ok": True, "notes": notes}
