"""
V2 Coach – Training Availability endpoint (Iter 130j).

Route: PATCH /api/v2/coach/clients/{client_id}/training-availability

Lets a coach lift a client's per-day / per-week training caps in one call
so the engine can honour the intended programme structure (e.g. 3 runs +
2 strength / week ⇒ training_days_per_week=5, max_home_minutes≥90).

Whitelist-only. Every change is logged into `coach_change_log` and the
`decision_records` audit trail.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, now_iso, logger
from feature_v2_common import write_decision


class TrainingAvailabilityBody(BaseModel):
    # Session-count semantics
    training_days_per_week: Optional[int] = Field(None, ge=1, le=7)
    sessions_per_week_min:  Optional[int] = Field(None, ge=1, le=14)
    sessions_per_week_max:  Optional[int] = Field(None, ge=1, le=14)
    preferred_training_days: Optional[list[str]] = None
    preferred_session_length: Optional[int] = Field(None, ge=10, le=240)
    # Daily time caps
    max_home_minutes: Optional[int] = Field(None, ge=15, le=240)
    time_home_min:    Optional[int] = Field(None, ge=15, le=240)
    time_layover_min: Optional[int] = Field(None, ge=15, le=240)
    # Cardio / variety / experience
    cardio_preference: Optional[str] = None
    variety_preference: Optional[str] = None
    training_experience: Optional[str] = None
    dislikes_running: Optional[bool] = None
    willing_to_train_layovers: Optional[bool] = None


# Explicit whitelist ensures we never accept unexpected profile fields.
_WHITELIST = {
    "training_days_per_week", "sessions_per_week_min", "sessions_per_week_max",
    "preferred_training_days", "preferred_session_length",
    "max_home_minutes", "time_home_min", "time_layover_min",
    "cardio_preference", "variety_preference", "training_experience",
    "dislikes_running", "willing_to_train_layovers",
}


@api.patch("/v2/coach/clients/{client_id}/training-availability")
async def coach_update_training_availability(
    client_id: str,
    body: TrainingAvailabilityBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    user = await db.users.find_one({"id": client_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, f"Client {client_id} not found")
    prev_profile = user.get("profile") or {}

    body_dict = body.model_dump(exclude_unset=True)
    updates: dict[str, Any] = {}
    diff: dict[str, Any] = {}
    for k, v in body_dict.items():
        if k not in _WHITELIST or v is None:
            continue
        # Normalise lowercase for cardio_preference / preferred_training_days
        if k == "cardio_preference":
            v = str(v).strip().lower().replace(" ", "_")
        if k == "preferred_training_days" and isinstance(v, list):
            v = [str(d).strip().lower() for d in v if d]
        if prev_profile.get(k) != v:
            diff[k] = {"from": prev_profile.get(k), "to": v}
        updates[f"profile.{k}"] = v

    if not updates:
        return {
            "ok": True,
            "client_id": client_id,
            "message": "No changes — payload matched existing profile.",
            "profile_snapshot": {k: prev_profile.get(k) for k in _WHITELIST},
        }

    updates["updated_at"] = now_iso()
    await db.users.update_one({"id": client_id}, {"$set": updates})

    # Cross-consistency guard: if only training_days_per_week was lifted but
    # sessions_per_week_max is still lower, silently raise sessions_per_week_max
    # to match so the engine's stacking budget can breathe.
    new_tdpw = body_dict.get("training_days_per_week", prev_profile.get("training_days_per_week"))
    new_spw_max = body_dict.get("sessions_per_week_max", prev_profile.get("sessions_per_week_max"))
    if new_tdpw and new_spw_max and int(new_spw_max) < int(new_tdpw):
        await db.users.update_one(
            {"id": client_id},
            {"$set": {"profile.sessions_per_week_max": int(new_tdpw)}},
        )
        diff["sessions_per_week_max_auto_synced"] = {
            "from": new_spw_max, "to": int(new_tdpw),
            "reason": "Auto-synced to match training_days_per_week",
        }

    # Log the change into coach_change_log + decision_records
    try:
        await db.coach_change_log.insert_one({
            "client_id": client_id,
            "coach_id": coach["id"],
            "coach_email": coach.get("email"),
            "category": "training_availability",
            "title": (f"Updated training availability for "
                       f"{user.get('name') or user.get('email')}"),
            "summary": ", ".join(
                f"{k}: {v.get('from')}→{v.get('to')}"
                if isinstance(v, dict) else str(v)
                for k, v in diff.items()
            ),
            "actor": "coach",
            "diff": diff,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"coach_change_log insert failed: {e}")
    try:
        await write_decision(
            actor="coach", layer="ORCHESTRATION",
            scope_kind="training_availability", scope_id=client_id,
            client_id=client_id, outcome="UPDATED",
            reason=(f"Coach {coach.get('email')} updated training availability "
                    f"({len(diff)} field(s))"),
        )
    except Exception as e:
        logger.warning(f"write_decision failed: {e}")

    # Return the updated snapshot
    new_user = await db.users.find_one({"id": client_id}, {"_id": 0, "profile": 1})
    new_prof = (new_user or {}).get("profile") or {}
    return {
        "ok": True,
        "client_id": client_id,
        "diff": diff,
        "profile_snapshot": {k: new_prof.get(k) for k in _WHITELIST},
        "next_step": (
            "Press 'Rebuild draft' on the coach dashboard to regenerate the "
            "programme with the updated caps."
        ),
    }


logger.info(
    "feature_v2_coach_training_availability: "
    "PATCH /api/v2/coach/clients/{cid}/training-availability registered"
)
