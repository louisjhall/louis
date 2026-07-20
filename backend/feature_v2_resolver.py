"""
feature_v2_resolver — Phase 5 of the Programme Generation Upgrade.

Enforces the rule that CLIENT-VISIBLE workouts only reference exercises that
live in the V2 Exercise Library (db.exercises_v2) AND are approved for
programming (status in {Approved, Live} AND visibility='client_visible' AND
safe_for_programming=True).

Flow (per workout, called AFTER the LLM has produced a draft workout):

  1. Load the approved exercise pool once per generation cycle.
  2. For each exercise the LLM produced, try to resolve it to a library entry
     by normalised name / movement pattern / equipment.
  3. If nothing suitable exists, pick the safest approved SUBSTITUTE and record
     `substitute_for` + `substitution_reason` on the exercise. The client sees
     the substitute; the LLM's original suggestion is filed as a draft
     exercise REQUEST (deduplicated) so Louis can review and approve it later.
  4. If we cannot even find a safe substitute, DROP the exercise from the
     client's workout (user directive: never expose unapproved names).

Companion helpers exist for validating a persisted workout end-to-end and
counting per-programme request output (capped at 5 requests per generation to
avoid coach-task spam).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api,
    db,
    current_user,
    require_role,
    new_id,
    now_iso,
    logger,
    _create_coach_task,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APPROVED_STATUSES = ("Approved", "Live")

# States a candidate exercise flows through.
DRAFT_STATUSES = ("draft_requested", "coach_review_needed")
FINAL_STATUSES = ("Approved", "Live", "rejected", "merged", "archived")

MAX_REQUESTS_PER_PROGRAMME = 5


_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(s: Optional[str]) -> set[str]:
    if not s:
        return set()
    return set(_WORD_RE.findall(str(s).lower()))


def _normalise_name(s: Optional[str]) -> str:
    if not s:
        return ""
    return " ".join(_WORD_RE.findall(str(s).lower()))


# ---------------------------------------------------------------------------
# Backfill visibility / safe_for_programming on legacy approved exercises.
# Idempotent — runs on module import; safe to call multiple times.
# ---------------------------------------------------------------------------

async def backfill_client_flags_once() -> int:
    """Ensure exercises with status Approved/Live have visibility=client_visible
    and safe_for_programming=True. Returns the number of docs touched."""
    try:
        res = await db.exercises_v2.update_many(
            {"status": {"$in": list(APPROVED_STATUSES)},
             "$or": [{"visibility": {"$exists": False}}, {"visibility": None},
                     {"safe_for_programming": {"$exists": False}}]},
            {"$set": {"visibility": "client_visible", "safe_for_programming": True,
                      "updated_at": now_iso()}},
        )
        # For anything not Approved/Live, default to coach_only if missing.
        await db.exercises_v2.update_many(
            {"status": {"$nin": list(APPROVED_STATUSES)},
             "$or": [{"visibility": {"$exists": False}}, {"visibility": None}]},
            {"$set": {"visibility": "coach_only", "safe_for_programming": False,
                      "updated_at": now_iso()}},
        )
        if res.modified_count:
            logger.info("v2_resolver: backfilled client_visible on %d exercises", res.modified_count)
        return int(res.modified_count or 0)
    except Exception:
        logger.exception("v2_resolver: backfill failed (non-fatal)")
        return 0


# ---------------------------------------------------------------------------
# Approved pool loader
# ---------------------------------------------------------------------------

async def get_approved_pool() -> list[dict]:
    """Load the client-safe exercise pool. This is called once per
    workout-generation cycle; the pool is small (<500 rows) so the extra I/O
    is negligible compared to the LLM call it accompanies."""
    rows = await db.exercises_v2.find(
        {"status": {"$in": list(APPROVED_STATUSES)},
         "safe_for_programming": True,
         "visibility": "client_visible"},
        {"_id": 0},
    ).to_list(500)
    for r in rows:
        r["_name_norm"] = _normalise_name(r.get("exercise_name"))
        r["_name_tokens"] = _tokens(r.get("exercise_name"))
        # Precompute a rough movement-pattern / body-area / equipment token set
        # so scoring is cheap. Include tags.
        agg = " ".join([
            str(r.get("movement_pattern") or ""),
            str(r.get("body_area") or ""),
            " ".join(r.get("equipment_type") or []),
            " ".join(r.get("tags") or []),
        ])
        r["_meta_tokens"] = _tokens(agg)
    return rows


# ---------------------------------------------------------------------------
# Scoring / matching
# ---------------------------------------------------------------------------

def _score_candidate(item: dict, cand: dict, client_ctx: Optional[dict]) -> float:
    """Return a match score (higher = better) for a raw LLM exercise `item`
    against a library candidate `cand`. Purely deterministic.
    - Exact name match: massive boost.
    - Token overlap on the name.
    - Token overlap on movement_pattern / body_area / equipment / tags.
    - Equipment compatibility with the client's available equipment (small boost).
    - Injury sensitivity: soft penalty if candidate is flagged unsafe for the
      client's known injuries."""
    item_name_norm = _normalise_name(item.get("name") or item.get("exercise_name"))
    if not item_name_norm:
        return 0.0
    score = 0.0
    if item_name_norm and item_name_norm == cand.get("_name_norm"):
        score += 100.0
    # Substring: candidate name fully contained in item name or vice versa.
    if cand.get("_name_norm") and (
        cand["_name_norm"] in item_name_norm or item_name_norm in cand["_name_norm"]
    ):
        score += 30.0
    item_tokens = _tokens(item.get("name") or item.get("exercise_name"))
    item_tokens |= _tokens(item.get("notes"))
    # Token overlap on name.
    overlap_name = len(item_tokens & cand["_name_tokens"])
    score += 5.0 * overlap_name
    # Token overlap on metadata (movement pattern / body_area / equipment / tags).
    overlap_meta = len(item_tokens & cand["_meta_tokens"])
    score += 2.0 * overlap_meta
    # Client context awareness (soft — pool is already filtered by visibility).
    if client_ctx:
        equip = set((client_ctx.get("equipment") or []))
        cand_equip = set((cand.get("equipment_type") or []))
        if cand_equip and equip:
            if cand_equip & equip:
                score += 4.0
            elif "bodyweight" in cand_equip or "no equipment" in cand_equip:
                score += 3.0  # bodyweight is always accessible
            else:
                score -= 3.0  # candidate needs something the client doesn't have
        injuries = str(client_ctx.get("injuries") or "").lower()
        contra = str(cand.get("notes") or "").lower()
        if injuries:
            for word in ("knee", "back", "shoulder", "elbow", "hip", "ankle", "wrist"):
                if word in injuries and word in contra:
                    # candidate note mentions the same area — often contraindicated.
                    if any(k in contra for k in ("avoid", "not recommended", "caution", "contraindicat")):
                        score -= 6.0
    return score


def resolve_exercise_need(
    item: dict,
    pool: list[dict],
    client_ctx: Optional[dict] = None,
    *,
    min_direct_match: float = 50.0,
    min_substitute_match: float = 10.0,
) -> dict:
    """Attempt to resolve a raw LLM exercise into a library entry.

    Returns a dict describing the resolution:
      {
        "kind": "matched" | "substituted" | "unresolved",
        "library": <cand dict or None>,
        "score": float,
        "reason": short human-readable string (why the choice was made),
      }
    """
    if not pool:
        return {"kind": "unresolved", "library": None, "score": 0.0, "reason": "empty pool"}

    scored = sorted(
        ((_score_candidate(item, c, client_ctx), c) for c in pool),
        key=lambda p: p[0], reverse=True,
    )
    if not scored:
        return {"kind": "unresolved", "library": None, "score": 0.0, "reason": "no candidates"}
    best_score, best = scored[0]

    if best_score >= min_direct_match:
        return {
            "kind": "matched", "library": best, "score": best_score,
            "reason": f"direct match: {best.get('exercise_name')}",
        }

    if best_score >= min_substitute_match:
        return {
            "kind": "substituted", "library": best, "score": best_score,
            "reason": f"closest approved match ({best.get('exercise_name')}) — no exact library entry for '{item.get('name')}'",
        }

    return {"kind": "unresolved", "library": None, "score": best_score,
            "reason": f"no approved exercise close to '{item.get('name')}'"}


# ---------------------------------------------------------------------------
# Draft exercise request (with deduplication + per-programme cap)
# ---------------------------------------------------------------------------

async def create_exercise_request_if_missing(
    item: dict,
    *,
    user: dict,
    programme_id: Optional[str] = None,
    workout_id: Optional[str] = None,
    substitute_used: Optional[dict] = None,
    reason: str = "",
) -> Optional[str]:
    """Idempotently record a draft-exercise request.

    Dedup rule: match by normalised requested_name (case/punctuation-insensitive)
    across ALL exercises_v2 records — draft OR approved. If a match exists,
    just bump `request_count` and append the current usage/programme context
    rather than creating a duplicate.

    Returns the exercise_v2 doc id (existing or newly created).
    """
    requested_name = (item.get("name") or item.get("exercise_name") or "").strip()
    if not requested_name:
        return None
    norm = _normalise_name(requested_name)
    # 1) De-dup against existing exercises (draft OR approved).
    existing = await db.exercises_v2.find_one(
        {"$or": [
            {"exercise_name": {"$regex": f"^{re.escape(requested_name)}$", "$options": "i"}},
            {"requested_name_norm": norm},
        ]},
        {"_id": 0},
    )
    if existing:
        usage_ctx = {
            "user_id": user.get("id"),
            "programme_id": programme_id,
            "workout_id": workout_id,
            "substitute_used_id": (substitute_used or {}).get("id"),
            "substitute_used_name": (substitute_used or {}).get("exercise_name"),
            "reason": reason,
            "at": now_iso(),
        }
        await db.exercises_v2.update_one(
            {"id": existing["id"]},
            {"$inc": {"request_count": 1},
             "$push": {"request_history": usage_ctx},
             "$set": {"updated_at": now_iso()}},
        )
        return existing["id"]

    # 2) Create fresh draft candidate.
    ex_id = new_id()
    doc = {
        "id": ex_id,
        "exercise_name": requested_name,
        "requested_name": requested_name,
        "requested_name_norm": norm,
        "suggested_name": requested_name,
        "category": item.get("category"),
        "movement_pattern": item.get("movement_pattern"),
        "body_area": item.get("body_area"),
        "equipment_type": item.get("equipment_type") or [],
        "difficulty_level": item.get("difficulty_level"),
        "tags": item.get("tags") or [],
        "goal_tags": item.get("goal_tags") or [],
        "injury_considerations": item.get("injury_considerations"),
        "aviation_use_case": item.get("aviation_use_case"),
        "reason_needed": reason,
        "client_context_summary": {
            "user_id": user.get("id"),
            "equipment": (user.get("profile") or {}).get("equipment"),
            "injuries": (user.get("profile") or {}).get("injuries"),
            "goal": (user.get("profile") or {}).get("main_goal_key"),
        },
        "safe_approved_substitute_used": {
            "id": (substitute_used or {}).get("id"),
            "name": (substitute_used or {}).get("exercise_name"),
        } if substitute_used else None,
        "requested_for_user_ids": [user.get("id")],
        "requested_for_programme_ids": [programme_id] if programme_id else [],
        "requested_for_workout_ids": [workout_id] if workout_id else [],
        "status": "draft_requested",
        "visibility": "coach_only",
        "safe_for_programming": False,
        "needs_louis_review": True,
        "request_count": 1,
        "request_history": [{
            "user_id": user.get("id"),
            "programme_id": programme_id,
            "workout_id": workout_id,
            "substitute_used_id": (substitute_used or {}).get("id"),
            "substitute_used_name": (substitute_used or {}).get("exercise_name"),
            "reason": reason,
            "at": now_iso(),
        }],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.exercises_v2.insert_one(doc)

    # 3) Coach task — one per newly-created draft so Louis sees it.
    try:
        await _create_coach_task(
            user,
            task_type="exercise_review",
            title=f"Exercise review needed: {requested_name}",
            description=(reason or "")
                + (f"\nSubstitute used: {(substitute_used or {}).get('exercise_name')}." if substitute_used else "")
                + "\nApprove, edit, reject, or merge with an existing exercise.",
            payload={
                "exercise_id": ex_id,
                "programme_id": programme_id,
                "workout_id": workout_id,
                "substitute_id": (substitute_used or {}).get("id"),
            },
        )
    except Exception:
        logger.exception("v2_resolver: coach task creation failed (non-fatal)")
    return ex_id


# ---------------------------------------------------------------------------
# Main orchestrator — apply resolver to a batch of workouts
# ---------------------------------------------------------------------------

async def apply_resolver_to_workouts(
    workouts: list[dict],
    *,
    user: dict,
    roster: Optional[dict] = None,
    programme_id: Optional[str] = None,
) -> dict:
    """Resolve every exercise in the given batch to a V2 library entry.

    Mutates each exercise IN PLACE with:
      - exercise_id / exercise_name / source='v2_library'
      - movement_pattern / equipment (copied from library entry)
      - substitute_for / substitution_reason (when a substitute was used)
    Exercises that cannot resolve at all are DROPPED from the workout.

    Also creates deduplicated draft exercise requests for unmatched items, up
    to MAX_REQUESTS_PER_PROGRAMME per call.

    Returns a summary dict: {matched, substituted, dropped, requests_created}.
    """
    pool = await get_approved_pool()
    profile = (user or {}).get("profile") or {}
    client_ctx = {
        "equipment": profile.get("equipment") or [],
        "injuries": profile.get("injuries"),
        "goal": profile.get("main_goal_key"),
    }
    stats = {"matched": 0, "substituted": 0, "dropped": 0, "requests_created": 0}
    requests_this_run = 0

    for w in workouts:
        exs_in = w.get("exercises") or []
        exs_out: list[dict] = []
        for item in exs_in:
            res = resolve_exercise_need(item, pool, client_ctx=client_ctx)
            if res["kind"] == "matched":
                lib = res["library"]
                item_out = dict(item)
                item_out.update({
                    "exercise_id": lib["id"],
                    "name": lib["exercise_name"],
                    "movement_pattern": lib.get("movement_pattern"),
                    "equipment": lib.get("equipment_type"),
                    "source": "v2_library",
                })
                exs_out.append(item_out)
                stats["matched"] += 1
            elif res["kind"] == "substituted":
                lib = res["library"]
                item_out = dict(item)
                original_name = item.get("name") or item.get("exercise_name")
                item_out.update({
                    "exercise_id": lib["id"],
                    "name": lib["exercise_name"],
                    "movement_pattern": lib.get("movement_pattern"),
                    "equipment": lib.get("equipment_type"),
                    "source": "v2_library",
                    "substitute_for": original_name,
                    "substitution_reason": res.get("reason"),
                })
                exs_out.append(item_out)
                stats["substituted"] += 1
                # Try to file a draft request (dedup-checked). Cap per programme.
                if requests_this_run < MAX_REQUESTS_PER_PROGRAMME:
                    try:
                        rid = await create_exercise_request_if_missing(
                            item,
                            user=user,
                            programme_id=programme_id,
                            workout_id=w.get("id"),
                            substitute_used=lib,
                            reason=(
                                f"LLM asked for '{original_name}' — no direct approved "
                                f"library match. Substituted with '{lib.get('exercise_name')}'."
                            ),
                        )
                        if rid:
                            requests_this_run += 1
                            stats["requests_created"] += 1
                    except Exception:
                        logger.exception("apply_resolver: request creation raised (non-fatal)")
            else:
                # Unresolved — drop from the client workout (user directive).
                stats["dropped"] += 1
                if requests_this_run < MAX_REQUESTS_PER_PROGRAMME:
                    try:
                        rid = await create_exercise_request_if_missing(
                            item,
                            user=user,
                            programme_id=programme_id,
                            workout_id=w.get("id"),
                            substitute_used=None,
                            reason=f"LLM asked for '{item.get('name')}' — no approved substitute exists yet.",
                        )
                        if rid:
                            requests_this_run += 1
                            stats["requests_created"] += 1
                    except Exception:
                        logger.exception("apply_resolver: unresolved request raised (non-fatal)")
        w["exercises"] = exs_out
        # Also try to resolve exercises inside the Green variant (if present).
        variants = w.get("variants") or {}
        green = variants.get("green") if isinstance(variants, dict) else None
        if isinstance(green, dict) and green.get("exercises"):
            green_out: list[dict] = []
            for item in green["exercises"]:
                res = resolve_exercise_need(item, pool, client_ctx=client_ctx)
                if res["kind"] in ("matched", "substituted"):
                    lib = res["library"]
                    item_out = dict(item)
                    item_out.update({
                        "exercise_id": lib["id"],
                        "name": lib["exercise_name"],
                        "source": "v2_library",
                    })
                    green_out.append(item_out)
                # else drop from variant (client never sees unresolved)
            green["exercises"] = green_out
    return stats


# ---------------------------------------------------------------------------
# Validation — used by feature_programme_quality.validate_programme
# ---------------------------------------------------------------------------

def summarise_workout_v2_health(workouts: list[dict]) -> dict:
    """Count how many exercises resolved to V2 vs are substitutes vs still
    have free-text names. Used by programme validation."""
    total = 0
    resolved = 0
    substituted = 0
    missing_id = 0
    for w in workouts or []:
        for e in (w.get("exercises") or []):
            total += 1
            if e.get("exercise_id"):
                resolved += 1
                if e.get("substitute_for"):
                    substituted += 1
            else:
                missing_id += 1
    return {
        "total_exercises": total,
        "resolved_to_v2": resolved,
        "substituted": substituted,
        "missing_exercise_id": missing_id,
        "substitute_ratio": (substituted / total) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Endpoints — Louis review workflow (minimal P0: list + reject + merge)
# ---------------------------------------------------------------------------

@api.get("/exercise-requests")
async def exercise_requests_list(
    status: Optional[str] = None,
    urgency: Optional[str] = None,
    admin: dict = Depends(require_role("coach")),
):
    """List draft/review-needed exercise requests. Default returns everything
    still awaiting review (draft_requested OR coach_review_needed). Also
    surfaces `request_count`, `substitute_used`, and affected client counts.

    NOTE: This lives at /exercise-requests (not /exercise-content/requests)
    because /exercise-content/{ex_id} is a wildcard route registered earlier
    in feature_exercise_content and would otherwise shadow this list."""
    q: dict[str, Any] = {}
    if status:
        q["status"] = status
    else:
        q["status"] = {"$in": list(DRAFT_STATUSES)}
    rows = await db.exercises_v2.find(q, {"_id": 0}).sort([("request_count", -1), ("updated_at", -1)]).to_list(200)
    for r in rows:
        r["clients_affected"] = len(set(r.get("requested_for_user_ids") or []))
        r["programmes_affected"] = len(set(r.get("requested_for_programme_ids") or []))
    return {"requests": rows, "count": len(rows)}


@api.get("/exercise-requests/grouped")
async def exercise_requests_grouped(admin: dict = Depends(require_role("coach"))):
    """Return draft requests bucketed by urgency for the coach demand queue:
      - needed_soon: draft requests referenced by workouts scheduled in the
        next 7 days (highest urgency)
      - awaiting_review: everything else with status='draft_requested'
      - recent: latest 15 drafts (any status) for context
      - history: rejected + merged
    Each list is capped for UI responsiveness.
    """
    import datetime as _dt

    drafts = await db.exercises_v2.find(
        {"status": {"$in": list(DRAFT_STATUSES)}}, {"_id": 0}
    ).sort([("request_count", -1), ("updated_at", -1)]).to_list(200)

    # Which drafts are referenced by a workout in the next 7 days?
    horizon_iso = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
    today_iso = _dt.date.today().isoformat()
    upcoming_workout_ids: set[str] = set()
    try:
        cur = db.workouts.find(
            {"date": {"$gte": today_iso, "$lte": horizon_iso}}, {"_id": 0, "id": 1}
        )
        async for w in cur:
            upcoming_workout_ids.add(w.get("id"))
    except Exception:
        pass

    def _enrich(r: dict) -> dict:
        r = dict(r)
        r["clients_affected"] = len(set(r.get("requested_for_user_ids") or []))
        r["programmes_affected"] = len(set(r.get("requested_for_programme_ids") or []))
        return r

    needed_soon: list[dict] = []
    awaiting_review: list[dict] = []
    for r in drafts:
        ref_ids = set(r.get("requested_for_workout_ids") or [])
        if ref_ids & upcoming_workout_ids:
            needed_soon.append(_enrich(r))
        else:
            awaiting_review.append(_enrich(r))

    recent = [
        _enrich(r) for r in await db.exercises_v2.find(
            {}, {"_id": 0}
        ).sort([("updated_at", -1)]).to_list(15)
    ]
    history = [
        _enrich(r) for r in await db.exercises_v2.find(
            {"status": {"$in": ["rejected", "merged"]}}, {"_id": 0}
        ).sort([("reviewed_at", -1)]).to_list(30)
    ]

    return {
        "needed_soon": needed_soon,
        "awaiting_review": awaiting_review,
        "recent": recent,
        "history": history,
        "counts": {
            "needed_soon": len(needed_soon),
            "awaiting_review": len(awaiting_review),
            "history": len(history),
            "total_pending": len(drafts),
        },
    }


class QuickApproveBody(BaseModel):
    name: Optional[str] = None                 # optional rename
    category: Optional[str] = None
    movement_pattern: Optional[str] = None
    body_area: Optional[str] = None
    equipment_type: Optional[list[str]] = None
    difficulty_level: Optional[str] = None
    coaching_points: Optional[list[str]] = None
    common_mistakes: Optional[list[str]] = None
    regressions: Optional[list[str]] = None
    progressions: Optional[list[str]] = None
    contraindications: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    trigger_media: bool = True                 # kick JIT media on approval


@api.post("/exercise-requests/{ex_id}/approve-quick")
async def exercise_request_quick_approve(
    ex_id: str,
    body: QuickApproveBody = QuickApproveBody(),
    admin: dict = Depends(require_role("coach")),
):
    """Quick approve path used by the Coach Demand Queue.

    Flips the draft to Approved + client_visible + safe_for_programming, applies
    any inline edits Louis made, and (if requested) triggers just-in-time media
    generation so the exercise ships with a demo image."""
    ex = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    if not ex:
        raise HTTPException(404, "Not found")
    now = now_iso()
    updates: dict[str, Any] = {
        "status": "Approved",
        "approval_status": "approved",
        "visibility": "client_visible",
        "safe_for_programming": True,
        "needs_louis_review": False,
        "reviewed_by": admin["id"],
        "reviewed_at": now,
        "approved_at": now,
        "approved_by": admin["id"],
        "updated_at": now,
    }
    inline = body.model_dump(exclude_none=True, exclude={"trigger_media"})
    if body.name:
        inline["exercise_name"] = body.name
        inline.pop("name", None)
    for k, v in inline.items():
        updates[k] = v
    await db.exercises_v2.update_one({"id": ex_id}, {"$set": updates})

    triggered_media = False
    if body.trigger_media:
        triggered_media = await _maybe_kick_media(ex_id)

    ex2 = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    return {"exercise": ex2, "media_triggered": triggered_media}


@api.post("/exercise-requests/{ex_id}/generate-media")
async def exercise_request_generate_media(
    ex_id: str,
    admin: dict = Depends(require_role("coach")),
):
    """Manual JIT media trigger — Louis can force-queue an image for an
    approved exercise from the Demand Queue."""
    triggered = await _maybe_kick_media(ex_id, force=True)
    return {"media_triggered": triggered}


# ---------------------------------------------------------------------------
# Just-in-time media generation
# ---------------------------------------------------------------------------

async def _has_primary_image(ex: dict) -> bool:
    """Cheap check — is a demo image already available for this exercise?"""
    if ex.get("primary_image") or ex.get("images"):
        return True
    if (ex.get("approved_image_status") or "").lower() == "approved":
        return True
    if (ex.get("content_status") or {}).get("images"):
        return True
    return False


async def _maybe_kick_media(ex_id: str, *, force: bool = False) -> bool:
    """If the exercise is approved and has no demo media yet, fire a background
    task through the existing exercise-content image pipeline so it lands in
    the same storage layout the ExerciseThumbnail component reads.
    Non-fatal: returns False on any error."""
    ex = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    if not ex:
        return False
    if not force and await _has_primary_image(ex):
        return False
    if ex.get("status") not in APPROVED_STATUSES and not force:
        return False
    try:
        import asyncio as _asyncio
        from feature_exercise_content import _build_ex_prompt, _run_image_job
        prompt = _build_ex_prompt(ex, "primary", None, False)
        image_id = new_id()
        now = now_iso()
        await db.exercise_content_images.insert_one({
            "id": image_id, "exercise_id": ex_id, "slot": "primary",
            "requested_slot": "primary", "gender": "male",
            "prompt": prompt, "status": "generating",
            "storage_path": None, "size_bytes": None, "mime": None,
            "created_by": "jit_media", "created_at": now, "updated_at": now,
        })
        await db.exercises_v2.update_one(
            {"id": ex_id},
            {"$set": {"primary_image_id": image_id,
                      "demo_slots.primary": image_id,
                      "approved_image_status": "Needs Review",
                      "content_status.images": True,
                      "updated_at": now}},
        )
        _asyncio.create_task(_run_image_job(image_id, prompt, use_louis_ref=True))
        logger.info("JIT media queued for %s (image_id=%s)", ex_id, image_id)
        return True
    except Exception:
        logger.exception("JIT media pipeline failed for %s", ex_id)
        return False


async def jit_media_sweep_once() -> dict[str, int]:
    """One pass of the scheduled sweep. For every approved exercise WITHOUT a
    demo image that is referenced by a workout in the next 7 days, kick a
    background media generation. Idempotent — checks image presence first."""
    import datetime as _dt

    horizon_iso = (_dt.date.today() + _dt.timedelta(days=7)).isoformat()
    today_iso = _dt.date.today().isoformat()

    # Collect exercise_ids referenced by upcoming workouts.
    upcoming_ids: set[str] = set()
    async for w in db.workouts.find(
        {"date": {"$gte": today_iso, "$lte": horizon_iso}},
        {"_id": 0, "exercises": 1},
    ):
        for e in (w.get("exercises") or []):
            if e.get("exercise_id"):
                upcoming_ids.add(e["exercise_id"])
    if not upcoming_ids:
        return {"queued": 0, "candidates": 0}

    triggered = 0
    for ex_id in list(upcoming_ids)[:20]:  # cap per sweep to avoid spikes
        try:
            ok = await _maybe_kick_media(ex_id, force=False)
            if ok:
                triggered += 1
        except Exception:
            continue
    return {"queued": triggered, "candidates": len(upcoming_ids)}


async def jit_media_sweep_loop() -> None:
    """Background loop: run the sweep every 15 minutes. Cancels cleanly."""
    import asyncio as _asyncio
    while True:
        try:
            stats = await jit_media_sweep_once()
            if stats.get("queued"):
                logger.info("JIT media sweep: %s", stats)
        except Exception:
            logger.exception("JIT media sweep loop error")
        await _asyncio.sleep(15 * 60)


class RejectBody(BaseModel):
    reason: Optional[str] = None


@api.post("/exercise-content/{ex_id}/reject")
async def exercise_reject(ex_id: str, body: RejectBody, admin: dict = Depends(require_role("coach"))):
    ex = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    if not ex:
        raise HTTPException(404, "Not found")
    await db.exercises_v2.update_one(
        {"id": ex_id},
        {"$set": {
            "status": "rejected",
            "visibility": "coach_only",
            "safe_for_programming": False,
            "rejected_reason": body.reason,
            "reviewed_by": admin["id"],
            "reviewed_at": now_iso(),
            "updated_at": now_iso(),
        }},
    )
    return {"ok": True}


class MergeBody(BaseModel):
    target_id: str    # id of the surviving (canonical) exercise


@api.post("/exercise-content/{ex_id}/merge")
async def exercise_merge(ex_id: str, body: MergeBody, admin: dict = Depends(require_role("coach"))):
    """Merge a draft request into an already-approved exercise. The target
    inherits the request context (usage history + counts) so Louis can see
    the demand signal on the canonical record. The draft is marked 'merged'."""
    src = await db.exercises_v2.find_one({"id": ex_id}, {"_id": 0})
    tgt = await db.exercises_v2.find_one({"id": body.target_id}, {"_id": 0})
    if not src or not tgt:
        raise HTTPException(404, "Not found")
    if src["id"] == tgt["id"]:
        raise HTTPException(400, "Cannot merge into itself")
    push_hist = src.get("request_history") or []
    inc_count = int(src.get("request_count") or 0)
    await db.exercises_v2.update_one(
        {"id": tgt["id"]},
        {"$inc": {"request_count": inc_count},
         "$push": {"request_history": {"$each": push_hist}},
         "$set": {"updated_at": now_iso()}},
    )
    await db.exercises_v2.update_one(
        {"id": src["id"]},
        {"$set": {"status": "merged", "merged_into_id": tgt["id"],
                  "visibility": "coach_only", "safe_for_programming": False,
                  "reviewed_by": admin["id"], "reviewed_at": now_iso(),
                  "updated_at": now_iso()}},
    )
    return {"ok": True, "merged_into": tgt["id"]}
