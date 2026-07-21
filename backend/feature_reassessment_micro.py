"""
feature_reassessment_micro — short, kind-specific questionnaires so a client
never has to run the full adaptive assessment from scratch just because they
missed sessions or uploaded a new roster.

Rules:
  * The full `/assessment` flow is reserved for a genuine goal shift or a
    Louis-initiated fresh DNA rebuild.
  * Every other reassessment prompt gets a targeted MICRO form (3-6 qs).
  * Answers are stored in `db.reassessment_responses` and:
      - open a coach task with the client's exact answers,
      - update a small, well-defined slice of `users.profile` where relevant
        (e.g. training_days_per_week from an availability check),
      - never touch coaching_dna.

Endpoints:
  * GET  /api/reassessment/short-form?kind=... → { questions, meta }
  * POST /api/reassessment/short-form          → { thanks, coach_task_id? }
"""

from __future__ import annotations

from typing import Any, Optional
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api,
    db,
    current_user,
    new_id,
    now_iso,
    logger,
    _create_coach_task,
)


# ---------------------------------------------------------------------------
# Question catalogues per prompt kind
# ---------------------------------------------------------------------------

MICRO_FORMS: dict[str, dict[str, Any]] = {
    "missed_workouts": {
        "title": "Quick check-in",
        "intro": "Life gets busy — help CrewFit understand what happened so Louis can adapt.",
        "coach_task_title": "Missed sessions — client feedback",
        "duration_estimate": "60s",
        "questions": [
            {
                "id": "reason",
                "text": "What's been going on?",
                "type": "single_select",
                "options": [
                    {"id": "too_tired", "label": "Too tired / worn out"},
                    {"id": "too_busy", "label": "Too busy with life or work"},
                    {"id": "roster_changed", "label": "My roster or shifts changed"},
                    {"id": "injured", "label": "Something hurt or felt off"},
                    {"id": "lost_motivation", "label": "Lost motivation"},
                    {"id": "just_break", "label": "I just needed a break"},
                    {"id": "life_event", "label": "Something big in life"},
                    {"id": "other", "label": "Other"},
                ],
            },
            {
                "id": "energy_level",
                "text": "How's your energy this week?",
                "type": "range",
                "meta": {"min": 1, "max": 5, "step": 1, "left_label": "Low", "right_label": "High"},
            },
            {
                "id": "adjust_plan",
                "text": "How should CrewFit adjust this week?",
                "type": "single_select",
                "options": [
                    {"id": "lighter", "label": "Go lighter — mobility / short sessions"},
                    {"id": "keep", "label": "Keep as-is — I'll get back on it"},
                    {"id": "restart", "label": "Fresh start next week"},
                ],
            },
            {
                "id": "note",
                "text": "Anything Louis should know? (optional)",
                "type": "long_text",
                "optional": True,
            },
        ],
    },
    "life_change": {
        "title": "Quick update",
        "intro": "You've made a change — let's align your plan without redoing everything.",
        "coach_task_title": "Life change — client update",
        "duration_estimate": "60s",
        "questions": [
            {
                "id": "what_changed",
                "text": "What changed?",
                "type": "multi_select",
                "options": [
                    {"id": "goal", "label": "My primary goal"},
                    {"id": "availability", "label": "How many days I can train"},
                    {"id": "injury", "label": "An injury or physical thing"},
                    {"id": "roster", "label": "Roster or route pattern"},
                    {"id": "equipment", "label": "Equipment I have access to"},
                    {"id": "family", "label": "Family / personal situation"},
                    {"id": "other", "label": "Something else"},
                ],
            },
            {
                "id": "priority",
                "text": "Priority for the next 4 weeks?",
                "type": "single_select",
                "options": [
                    {"id": "consistency", "label": "Consistency"},
                    {"id": "recovery", "label": "Recovery / feel better"},
                    {"id": "strength", "label": "Build strength"},
                    {"id": "fat_loss", "label": "Fat loss"},
                    {"id": "endurance", "label": "Endurance / running fitness"},
                    {"id": "event_prep", "label": "Event / race prep"},
                ],
            },
            {
                "id": "note",
                "text": "Anything Louis should know? (optional)",
                "type": "long_text",
                "optional": True,
            },
        ],
    },
    "roster_uploaded": {
        "title": "Quick availability check",
        "intro": "You've uploaded a new roster — a 60-second check so CrewFit adapts perfectly.",
        "coach_task_title": "New roster — client availability confirmed",
        "duration_estimate": "60s",
        "questions": [
            {
                "id": "training_days_per_week",
                "text": "How many days a week can you realistically train this month?",
                "type": "single_select",
                "options": [
                    {"id": "2", "label": "2 days"},
                    {"id": "3", "label": "3 days"},
                    {"id": "4", "label": "4 days"},
                    {"id": "5", "label": "5 days"},
                    {"id": "6", "label": "6 days"},
                ],
            },
            {
                "id": "energy_baseline",
                "text": "Baseline energy this cycle?",
                "type": "range",
                "meta": {"min": 1, "max": 5, "step": 1, "left_label": "Low", "right_label": "High"},
            },
            {
                "id": "injury_note",
                "text": "Any current injury or niggle Louis should watch? (optional)",
                "type": "long_text",
                "optional": True,
            },
            {
                "id": "note",
                "text": "Anything else Louis should know? (optional)",
                "type": "long_text",
                "optional": True,
            },
        ],
    },
    "event_completed": {
        "title": "Event debrief",
        "intro": "Well done — tell Louis how it went so the next phase fits you.",
        "coach_task_title": "Event completed — client debrief",
        "duration_estimate": "60s",
        "questions": [
            {
                "id": "how_it_went",
                "text": "How did it go?",
                "type": "single_select",
                "options": [
                    {"id": "great", "label": "Great — hit or beat my goal"},
                    {"id": "solid", "label": "Solid — happy overall"},
                    {"id": "tough", "label": "Tougher than expected"},
                    {"id": "dnf_or_missed", "label": "DNF / had to pull out"},
                ],
            },
            {
                "id": "next_focus",
                "text": "What's next?",
                "type": "single_select",
                "options": [
                    {"id": "recover", "label": "Recover — take it easy for a bit"},
                    {"id": "another_event", "label": "Another event"},
                    {"id": "strength_phase", "label": "Strength / gym phase"},
                    {"id": "maintain", "label": "Just maintain fitness"},
                    {"id": "not_sure", "label": "Not sure yet"},
                ],
            },
            {
                "id": "note",
                "text": "Anything Louis should know? (optional)",
                "type": "long_text",
                "optional": True,
            },
        ],
    },
}


def _button_label_for(kind: str) -> str:
    """Client-facing label for the CTA on the home prompt card."""
    return {
        "missed_workouts": "QUICK CHECK-IN",
        "life_change":     "QUICK UPDATE",
        "roster_uploaded": "QUICK CHECK",
        "event_completed": "DEBRIEF",
    }.get(kind, "TAKE 60s")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.get("/reassessment/short-form")
async def reassessment_short_form_get(kind: str, user: dict = Depends(current_user)):
    """Return the questions + intro for a specific reassessment kind."""
    form = MICRO_FORMS.get(kind)
    if not form:
        raise HTTPException(404, f"No short form for kind '{kind}'")
    return {
        "kind": kind,
        "title": form["title"],
        "intro": form["intro"],
        "duration_estimate": form["duration_estimate"],
        "questions": form["questions"],
        "button_label": _button_label_for(kind),
    }


class ShortFormSubmit(BaseModel):
    prompt_id: Optional[str] = None
    kind: str
    answers: dict[str, Any]


@api.post("/reassessment/short-form")
async def reassessment_short_form_submit(body: ShortFormSubmit, user: dict = Depends(current_user)):
    """Persist the short-form answers + create a coach task + apply targeted
    profile updates. NEVER touches coaching_dna."""
    form = MICRO_FORMS.get(body.kind)
    if not form:
        raise HTTPException(404, f"No short form for kind '{body.kind}'")

    # 1. Persist response
    doc_id = new_id()
    await db.reassessment_responses.insert_one({
        "id": doc_id,
        "user_id": user["id"],
        "kind": body.kind,
        "prompt_id": body.prompt_id,
        "answers": body.answers,
        "created_at": now_iso(),
    })

    # 2. Apply targeted profile updates (only for known safe fields)
    profile_updates: dict[str, Any] = {}
    if body.kind == "roster_uploaded":
        td = body.answers.get("training_days_per_week")
        if td is not None:
            try:
                profile_updates["training_days_per_week"] = int(td)
            except Exception:
                pass
    if profile_updates:
        try:
            set_doc = {f"profile.{k}": v for k, v in profile_updates.items()}
            set_doc["profile.updated_at"] = now_iso()
            await db.users.update_one({"id": user["id"]}, {"$set": set_doc})
        except Exception:
            logger.exception("short-form profile update failed")

    # 3. Coach task with the client's exact answers so Louis has full context
    lines = [f"Client filled the {body.kind.replace('_', ' ')} short form."]
    for q in form["questions"]:
        val = body.answers.get(q["id"])
        if val in (None, "", []):
            continue
        label = q["text"]
        # Try to render the human label of a select answer
        if q["type"] in ("single_select", "multi_select"):
            options = {o["id"]: o["label"] for o in (q.get("options") or [])}
            if isinstance(val, list):
                val = ", ".join(options.get(v, v) for v in val)
            else:
                val = options.get(val, val)
        lines.append(f"  • {label} → {val}")
    description = "\n".join(lines)

    priority = "high" if body.kind in ("missed_workouts", "life_change") else "normal"
    task_id = None
    try:
        task_id = await _create_coach_task(
            user,
            task_type="reassessment_response",
            title=f"{form['coach_task_title']}: {user.get('name') or user.get('email')}",
            description=description,
            priority=priority,
            category="reviews",
            payload={
                "kind": body.kind,
                "response_id": doc_id,
                "answers": body.answers,
                "profile_updates": profile_updates,
            },
        )
    except Exception:
        logger.exception("short-form coach task creation failed (non-fatal)")

    # 4. Dismiss any matching prompts so they don't re-appear
    if body.prompt_id:
        try:
            await db.reassessment_prompts.update_many(
                {"id": body.prompt_id, "user_id": user["id"]},
                {"$set": {"dismissed": True, "dismissed_at": now_iso(), "resolved_via": "short_form"}},
            )
        except Exception:
            pass
    else:
        # Cool-down by kind — clear any active prompts of the same kind
        try:
            await db.reassessment_prompts.update_many(
                {"user_id": user["id"], "kind": body.kind, "dismissed": False},
                {"$set": {"dismissed": True, "dismissed_at": now_iso(), "resolved_via": "short_form"}},
            )
        except Exception:
            pass

    return {
        "ok": True,
        "response_id": doc_id,
        "coach_task_id": task_id,
        "profile_updates": list(profile_updates.keys()),
        "message": "Thanks — Louis has been notified. Your plan will adapt where needed.",
    }
