"""
feature_v2_coach_inline_editor — V2 Workout Implementation inline edit API.

Priority 5 of the Coach Dashboard V2 PRD:
  The coach should be able to tweak reps / sets / RPE / rest / equipment /
  exercise choice from INSIDE the workspace drawer without leaving the
  Roster+Plan context. These endpoints mutate the DRAFT workout_implementation
  in-place, mark the parent workout_assignment as coach-edited (status stays
  in DRAFT until the coach publishes), and log DecisionRecords.

  Endpoints (all coach-only, all V2-flagged):
    PATCH  /v2/coach/clients/{cid}/plan/implementations/{impl_id}
    PATCH  /v2/coach/clients/{cid}/plan/implementations/{impl_id}/exercises/{idx}
    DELETE /v2/coach/clients/{cid}/plan/implementations/{impl_id}/exercises/{idx}
    POST   /v2/coach/clients/{cid}/plan/implementations/{impl_id}/exercises
    POST   /v2/coach/clients/{cid}/plan/implementations/{impl_id}/exercises/reorder

Only DRAFT implementations can be edited. Once a `live_implementation_id`
matches this impl_id (i.e. it's LIVE), further edits create/promote a new
draft implementation via the standard pipeline (P6 rebuild). For V1
clients this module refuses (409).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import write_decision, emit_metric


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _coach_has_v2_flag(coach_id: str) -> bool:
    coach = await db.users.find_one({"id": coach_id}, {"_id": 0, "profile.v2_flags": 1})
    if not coach:
        return False
    v2 = ((coach.get("profile") or {}).get("v2_flags") or {})
    return bool(v2.get("coach_dashboard_v2_enabled") or v2.get("v2_default"))


async def _load_impl_editable(client_id: str, impl_id: str) -> dict:
    impl = await db.workout_implementations.find_one(
        {"id": impl_id, "client_id": client_id}, {"_id": 0}
    )
    if not impl:
        raise HTTPException(404, "Workout implementation not found")
    # Refuse to edit a LIVE implementation directly — need to fork a draft first.
    live_ref = await db.workout_assignments.find_one(
        {"client_id": client_id, "live_implementation_id": impl_id,
         "draft_implementation_id": {"$ne": impl_id}},
        {"_id": 0, "id": 1}
    )
    if live_ref:
        raise HTTPException(
            409,
            "This implementation is LIVE. Rebuild a draft first, then edit the draft.",
        )
    return impl


async def _mark_assignment_edited(client_id: str, impl_id: str, coach_id: str) -> None:
    a = await db.workout_assignments.find_one(
        {"client_id": client_id, "draft_implementation_id": impl_id},
        {"_id": 0, "id": 1, "status": 1, "draft_id": 1}
    )
    if not a:
        return
    upd = {
        "coach_edited": True,
        "coach_edited_at": now_iso(),
        "coach_edited_by": coach_id,
        "updated_at": now_iso(),
    }
    # If status was 'live' but now has a new draft impl, downgrade to coach_edited
    if a.get("status") == "live":
        upd["status"] = "coach_edited"
    await db.workout_assignments.update_one({"id": a["id"]}, {"$set": upd})


# ---------------------------------------------------------------------------
# PATCH meta
# ---------------------------------------------------------------------------

class ImplMetaPatch(BaseModel):
    title: Optional[str] = None
    duration_min: Optional[int] = None
    focus: Optional[str] = None
    rationale: Optional[str] = None
    key_session: Optional[bool] = None
    location_label: Optional[str] = None
    coach_notes: Optional[str] = None
    needs_coach_review: Optional[bool] = None


@api.patch("/v2/coach/clients/{client_id}/plan/implementations/{impl_id}")
async def impl_patch_meta(
    client_id: str, impl_id: str,
    body: ImplMetaPatch,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    impl = await _load_impl_editable(client_id, impl_id)

    upd: dict = {"updated_at": now_iso()}
    payload = body.model_dump(exclude_unset=True)
    had_change = False
    for k in ("title", "duration_min", "focus", "rationale", "location_label",
              "coach_notes"):
        if k in payload and payload[k] is not None:
            upd[k] = payload[k]
            had_change = True
    if "key_session" in payload:
        upd["key_session"] = bool(payload["key_session"])
        had_change = True
    if "needs_coach_review" in payload:
        upd["needs_coach_review"] = bool(payload["needs_coach_review"])
        had_change = True
    upd["last_edited_by"] = coach["id"]
    upd["last_edited_at"] = now_iso()

    if not had_change:
        return impl

    await db.workout_implementations.update_one(
        {"id": impl_id, "client_id": client_id}, {"$set": upd}
    )
    await _mark_assignment_edited(client_id, impl_id, coach["id"])

    await write_decision(
        actor="coach", layer="HOW", scope_kind="workout_implementation",
        scope_id=impl_id, client_id=client_id, outcome="EDITED",
        reason=f"Coach edited meta: {', '.join(k for k in upd if k not in ('updated_at','last_edited_by','last_edited_at'))}",
    )
    try:
        await emit_metric("impl_meta_edited", client_id=client_id, coach_id=coach["id"],
                          labels={"fields": sum(1 for k in upd if k not in ('updated_at','last_edited_by','last_edited_at'))})
    except Exception:
        pass
    return await db.workout_implementations.find_one(
        {"id": impl_id}, {"_id": 0}
    )


# ---------------------------------------------------------------------------
# PATCH exercise slot
# ---------------------------------------------------------------------------

class ExercisePatch(BaseModel):
    exercise_name_display: Optional[str] = None
    sets: Optional[int] = None
    reps: Optional[str] = None
    rest_sec: Optional[int] = None
    rpe: Optional[float] = None
    hr_zone: Optional[str] = None
    duration_sec: Optional[int] = None
    coaching_cue: Optional[str] = None
    slot_role: Optional[str] = None
    exercise_id: Optional[str] = None


@api.patch(
    "/v2/coach/clients/{client_id}/plan/implementations/{impl_id}/exercises/{idx}"
)
async def impl_exercise_patch(
    client_id: str, impl_id: str, idx: int,
    body: ExercisePatch,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    impl = await _load_impl_editable(client_id, impl_id)
    exs = list(impl.get("exercises") or [])
    if idx < 0 or idx >= len(exs):
        raise HTTPException(400, f"Exercise index {idx} out of range (0..{len(exs)-1})")

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        return impl

    exs[idx] = {**exs[idx], **patch}
    await db.workout_implementations.update_one(
        {"id": impl_id, "client_id": client_id},
        {"$set": {"exercises": exs, "updated_at": now_iso(),
                  "last_edited_by": coach["id"], "last_edited_at": now_iso()}},
    )
    await _mark_assignment_edited(client_id, impl_id, coach["id"])

    await write_decision(
        actor="coach", layer="HOW", scope_kind="workout_implementation",
        scope_id=impl_id, client_id=client_id, outcome="EDITED",
        reason=f"Coach edited exercise #{idx} ({', '.join(patch.keys())})",
    )
    return await db.workout_implementations.find_one(
        {"id": impl_id}, {"_id": 0}
    )


# ---------------------------------------------------------------------------
# DELETE exercise
# ---------------------------------------------------------------------------

@api.delete(
    "/v2/coach/clients/{client_id}/plan/implementations/{impl_id}/exercises/{idx}"
)
async def impl_exercise_delete(
    client_id: str, impl_id: str, idx: int,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    impl = await _load_impl_editable(client_id, impl_id)
    exs = list(impl.get("exercises") or [])
    if idx < 0 or idx >= len(exs):
        raise HTTPException(400, f"Exercise index {idx} out of range")
    removed = exs.pop(idx)
    await db.workout_implementations.update_one(
        {"id": impl_id, "client_id": client_id},
        {"$set": {"exercises": exs, "updated_at": now_iso(),
                  "last_edited_by": coach["id"], "last_edited_at": now_iso()}},
    )
    await _mark_assignment_edited(client_id, impl_id, coach["id"])
    await write_decision(
        actor="coach", layer="HOW", scope_kind="workout_implementation",
        scope_id=impl_id, client_id=client_id, outcome="EDITED",
        reason=f"Coach removed exercise: {removed.get('exercise_name_display','?')}",
    )
    return await db.workout_implementations.find_one({"id": impl_id}, {"_id": 0})


# ---------------------------------------------------------------------------
# ADD exercise (append)
# ---------------------------------------------------------------------------

class ExerciseAdd(BaseModel):
    exercise_name_display: str = Field(..., min_length=1)
    exercise_id: Optional[str] = None
    slot_role: Optional[str] = "accessory"
    sets: Optional[int] = 3
    reps: Optional[str] = "8-10"
    rest_sec: Optional[int] = 90
    rpe: Optional[float] = None
    hr_zone: Optional[str] = None
    duration_sec: Optional[int] = None
    coaching_cue: Optional[str] = None
    insert_at: Optional[int] = None   # None = append


@api.post(
    "/v2/coach/clients/{client_id}/plan/implementations/{impl_id}/exercises"
)
async def impl_exercise_add(
    client_id: str, impl_id: str,
    body: ExerciseAdd,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    impl = await _load_impl_editable(client_id, impl_id)
    exs = list(impl.get("exercises") or [])
    new_ex: dict = body.model_dump(exclude={"insert_at"}, exclude_unset=False)
    if body.insert_at is None or body.insert_at >= len(exs):
        exs.append(new_ex)
    else:
        exs.insert(max(0, body.insert_at), new_ex)
    await db.workout_implementations.update_one(
        {"id": impl_id, "client_id": client_id},
        {"$set": {"exercises": exs, "updated_at": now_iso(),
                  "last_edited_by": coach["id"], "last_edited_at": now_iso()}},
    )
    await _mark_assignment_edited(client_id, impl_id, coach["id"])
    await write_decision(
        actor="coach", layer="HOW", scope_kind="workout_implementation",
        scope_id=impl_id, client_id=client_id, outcome="EDITED",
        reason=f"Coach added exercise: {body.exercise_name_display}",
    )
    return await db.workout_implementations.find_one({"id": impl_id}, {"_id": 0})


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------

class ReorderBody(BaseModel):
    order: list[int]   # permutation of current indices


@api.post(
    "/v2/coach/clients/{client_id}/plan/implementations/{impl_id}/exercises/reorder"
)
async def impl_exercise_reorder(
    client_id: str, impl_id: str, body: ReorderBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    impl = await _load_impl_editable(client_id, impl_id)
    exs = list(impl.get("exercises") or [])
    if sorted(body.order) != list(range(len(exs))):
        raise HTTPException(400, f"Order must be a permutation of 0..{len(exs)-1}")
    new_exs = [exs[i] for i in body.order]
    await db.workout_implementations.update_one(
        {"id": impl_id, "client_id": client_id},
        {"$set": {"exercises": new_exs, "updated_at": now_iso(),
                  "last_edited_by": coach["id"], "last_edited_at": now_iso()}},
    )
    await _mark_assignment_edited(client_id, impl_id, coach["id"])
    await write_decision(
        actor="coach", layer="HOW", scope_kind="workout_implementation",
        scope_id=impl_id, client_id=client_id, outcome="EDITED",
        reason=f"Coach reordered exercises",
    )
    return await db.workout_implementations.find_one({"id": impl_id}, {"_id": 0})


logger.info(
    "feature_v2_coach_inline_editor: /api/v2/coach/clients/{cid}/plan/implementations/{iid}/* mutation endpoints registered"
)
