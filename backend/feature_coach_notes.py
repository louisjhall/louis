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
