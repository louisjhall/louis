"""
feature_v2_coach_publish — Draft vs Live diff + selective publishing.

Implements Priority 4 of the V2 Coach Dashboard PRD:
  1) GET  /v2/coach/clients/{cid}/plan/diff?month=YYYY-MM
        Returns a side-by-side diff for every workout_assignment in that
        month, highlighting the delta between the currently LIVE
        implementation and the pending DRAFT implementation. Also lists
        every proposed change_set (from Directive engine + Command Bar
        + roster events) still awaiting resolution.

  2) POST /v2/coach/clients/{cid}/plan/publish
        Selectively promotes chosen assignments and/or change_sets from
        DRAFT to a new LIVE plan_version. Rejected change_sets are
        marked rejected in the same call. Non-selected changes stay in
        the DRAFT for next round.

Client-facing rule: only LIVE implementations are ever exposed to the
client app. The moment publish succeeds, `live_implementation_id` swaps
to the draft one and status flips to "live". No AI/bot wording.
"""
from __future__ import annotations

from calendar import monthrange
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, new_id, now_iso, logger
from feature_v2_common import (
    require_client_and_flag, write_decision, emit_metric
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _coach_has_v2_flag(coach_id: str) -> bool:
    coach = await db.users.find_one({"id": coach_id}, {"_id": 0, "profile.v2_flags": 1})
    if not coach:
        return False
    v2 = ((coach.get("profile") or {}).get("v2_flags") or {})
    return bool(v2.get("coach_dashboard_v2_enabled") or v2.get("v2_default"))


def _impl_signature(impl: Optional[dict]) -> dict:
    """Compact summary of an implementation for diffing."""
    if not impl:
        return {"present": False}
    exercises = impl.get("exercises") or []
    return {
        "present": True,
        "id": impl.get("id"),
        "title": impl.get("title"),
        "focus": impl.get("focus"),
        "duration_min": impl.get("duration_min"),
        "key_session": bool(impl.get("key_session")),
        "variant_type": impl.get("variant_type"),
        "equipment": ((impl.get("equipment_context") or {}).get("equipment") or []),
        "exercise_count": len(exercises),
        "exercise_names": [ex.get("exercise_name_display") or "" for ex in exercises],
        "needs_coach_review": bool(impl.get("needs_coach_review")),
    }


def _describe_delta(live: dict, draft: dict) -> list[str]:
    """Return short human-readable delta bullets between two impl signatures."""
    bullets: list[str] = []
    if not live.get("present") and draft.get("present"):
        bullets.append("Added to live plan")
        return bullets
    if live.get("present") and not draft.get("present"):
        bullets.append("Removed from draft")
        return bullets
    if live.get("title") != draft.get("title"):
        bullets.append(f"Title: {live.get('title') or '—'} → {draft.get('title') or '—'}")
    if (live.get("duration_min") or 0) != (draft.get("duration_min") or 0):
        bullets.append(f"Duration: {live.get('duration_min') or 0} → {draft.get('duration_min') or 0} min")
    if live.get("focus") != draft.get("focus"):
        bullets.append(f"Focus: {live.get('focus') or '—'} → {draft.get('focus') or '—'}")
    if live.get("key_session") != draft.get("key_session"):
        bullets.append("Key session marker changed")
    if (live.get("exercise_count") or 0) != (draft.get("exercise_count") or 0):
        bullets.append(
            f"Exercises: {live.get('exercise_count') or 0} → {draft.get('exercise_count') or 0}"
        )
    else:
        live_names = live.get("exercise_names") or []
        draft_names = draft.get("exercise_names") or []
        changed = [i for i, (a, b) in enumerate(zip(live_names, draft_names)) if (a or "") != (b or "")]
        if changed:
            bullets.append(f"{len(changed)} exercise swap{'s' if len(changed) > 1 else ''}")
    live_eq = set(live.get("equipment") or [])
    draft_eq = set(draft.get("equipment") or [])
    if live_eq != draft_eq:
        added = draft_eq - live_eq
        removed = live_eq - draft_eq
        parts = []
        if added:
            parts.append(f"+{', '.join(sorted(added))}")
        if removed:
            parts.append(f"-{', '.join(sorted(removed))}")
        if parts:
            bullets.append("Equipment: " + " ".join(parts))
    if not bullets:
        bullets.append("Refined details")
    return bullets


# ---------------------------------------------------------------------------
# GET /v2/coach/clients/{cid}/plan/diff?month=YYYY-MM
# ---------------------------------------------------------------------------

@api.get("/v2/coach/clients/{client_id}/plan/diff")
async def plan_diff(
    client_id: str,
    month: str,   # YYYY-MM
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Compute the full Draft vs Live delta for the given month.

    Returns:
      {
        client_id, month,
        live_version: { id, version, published_at } | null,
        draft: { id, status, notes } | null,
        summary: {
          total_assignments, changed, added, unchanged, live_only,
          change_sets_pending, change_sets_proposed
        },
        assignments: [
          {
            id, date, kind, kind_label,
            live: <impl_signature|null>,
            draft: <impl_signature|null>,
            delta_kind: 'unchanged'|'modified'|'added'|'removed',
            delta_bullets: [str, ...],
            locked, needs_coach_review,
          }, ...
        ],
        change_sets: [
          {
            id, kind, human_readable_summary, status,
            triggered_by, proposed_by, created_at,
            scope_assignment_ids
          }, ...
        ]
      }
    """
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")
    try:
        year, mo = int(month[:4]), int(month[5:7])
        _, last = monthrange(year, mo)
    except Exception:
        raise HTTPException(400, "month must be YYYY-MM")
    sd_str = f"{year:04d}-{mo:02d}-01"
    ed_str = f"{year:04d}-{mo:02d}-{last:02d}"

    client = await db.users.find_one(
        {"id": client_id}, {"_id": 0, "id": 1, "profile.v2_flags": 1}
    )
    if not client:
        raise HTTPException(404, "Client not found")

    # Draft + Live
    programme = await db.programmes_v2.find_one(
        {"client_id": client_id, "status": {"$in": ["active", "draft"]}}, {"_id": 0}
    )
    live_version = None
    draft = None
    if programme:
        live_version = await db.plan_versions.find_one(
            {"programme_id": programme["id"], "client_id": client_id},
            {"_id": 0}, sort=[("version", -1)],
        )
        draft = await db.plan_drafts.find_one(
            {"programme_id": programme["id"], "client_id": client_id,
             "status": {"$in": ["building", "ready_for_review", "partially_approved"]}},
            {"_id": 0}
        )

    # Assignments in month
    assignments = await db.workout_assignments.find(
        {"client_id": client_id, "date": {"$gte": sd_str, "$lte": ed_str}}, {"_id": 0}
    ).sort("date", 1).to_list(500)

    # Batch-load impls
    impl_ids = set()
    for a in assignments:
        for k in ("live_implementation_id", "draft_implementation_id"):
            if a.get(k):
                impl_ids.add(a[k])
    impls_map: dict[str, dict] = {}
    if impl_ids:
        for impl in await db.workout_implementations.find(
            {"id": {"$in": list(impl_ids)}}, {"_id": 0}
        ).to_list(1000):
            impls_map[impl["id"]] = impl

    # Objectives → label
    obj_ids = list({a.get("objective_id") for a in assignments if a.get("objective_id")})
    objs_map: dict[str, dict] = {}
    if obj_ids:
        for o in await db.training_objectives.find(
            {"id": {"$in": obj_ids}}, {"_id": 0, "id": 1, "kind": 1}
        ).to_list(500):
            objs_map[o["id"]] = o

    out_assignments = []
    n_changed = n_added = n_unchanged = 0
    for a in assignments:
        live_impl = impls_map.get(a.get("live_implementation_id")) if a.get("live_implementation_id") else None
        draft_impl = impls_map.get(a.get("draft_implementation_id")) if a.get("draft_implementation_id") else None
        live_sig = _impl_signature(live_impl)
        draft_sig = _impl_signature(draft_impl)

        if live_sig.get("present") and draft_sig.get("present"):
            if live_sig.get("id") == draft_sig.get("id"):
                delta_kind = "unchanged"
                bullets = []
                n_unchanged += 1
            else:
                delta_kind = "modified"
                bullets = _describe_delta(live_sig, draft_sig)
                n_changed += 1
        elif draft_sig.get("present") and not live_sig.get("present"):
            delta_kind = "added"
            bullets = ["New session (draft only)"]
            n_added += 1
        elif live_sig.get("present") and not draft_sig.get("present"):
            delta_kind = "live_only"
            bullets = ["Live session – no draft override"]
            n_unchanged += 1
        else:
            delta_kind = "unchanged"
            bullets = []
            n_unchanged += 1

        obj = objs_map.get(a.get("objective_id"))
        out_assignments.append({
            "id": a["id"],
            "date": a["date"],
            "kind": (obj or {}).get("kind"),
            "kind_label": ((obj or {}).get("kind") or "session").replace("_", " ").title(),
            "status": a.get("status"),
            "locked": bool(a.get("locked")),
            "live": live_sig,
            "draft": draft_sig,
            "delta_kind": delta_kind,
            "delta_bullets": bullets,
            "needs_coach_review": bool((draft_impl or {}).get("needs_coach_review")),
        })

    # Change sets
    change_sets: list[dict] = []
    change_sets_proposed = 0
    change_sets_pending = 0
    if draft:
        cs_rows = await db.change_sets.find(
            {"draft_id": draft["id"], "client_id": client_id},
            {"_id": 0}
        ).sort("created_at", -1).to_list(500)
        for cs in cs_rows:
            if cs.get("status") == "proposed":
                change_sets_proposed += 1
                change_sets_pending += 1
            change_sets.append({
                "id": cs["id"],
                "kind": cs.get("kind"),
                "human_readable_summary": cs.get("human_readable_summary") or "",
                "status": cs.get("status"),
                "triggered_by": cs.get("triggered_by"),
                "proposed_by": cs.get("proposed_by"),
                "created_at": cs.get("created_at"),
                "scope_assignment_ids": cs.get("scope_assignment_ids") or [],
                "before_snapshot": cs.get("before_snapshot"),
                "after_snapshot": cs.get("after_snapshot"),
            })

    return {
        "client_id": client_id,
        "month": month,
        "programme": {
            "id": (programme or {}).get("id"),
            "primary_goal_id": (programme or {}).get("primary_goal_id"),
            "timeline_class": (programme or {}).get("timeline_class"),
        },
        "live_version": {
            "id": (live_version or {}).get("id"),
            "version": (live_version or {}).get("version"),
            "published_at": (live_version or {}).get("published_at"),
        } if live_version else None,
        "draft": {
            "id": (draft or {}).get("id"),
            "status": (draft or {}).get("status"),
            "notes": (draft or {}).get("notes"),
        } if draft else None,
        "summary": {
            "total_assignments": len(assignments),
            "changed": n_changed,
            "added": n_added,
            "unchanged": n_unchanged,
            "change_sets_pending": change_sets_pending,
            "change_sets_proposed": change_sets_proposed,
        },
        "assignments": out_assignments,
        "change_sets": change_sets,
        "generated_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# POST /v2/coach/clients/{cid}/plan/publish
# ---------------------------------------------------------------------------

class PublishBody(BaseModel):
    draft_id: str
    assignment_ids: list[str] = []          # promote these assignments → live
    accept_change_set_ids: list[str] = []   # mark accepted + promoted
    reject_change_set_ids: list[str] = []   # mark rejected; leave DRAFT untouched
    notes: Optional[str] = None
    scope: str = "selected"                 # 'selected' | 'all'


@api.post("/v2/coach/clients/{client_id}/plan/publish")
async def plan_publish(
    client_id: str,
    body: PublishBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Selectively publish (promote) chosen draft assignments + accept/reject
    change_sets. Creates ONE new plan_version + snapshot capturing the
    accepted set. Rejected change_sets never become live.
    """
    if not await _coach_has_v2_flag(coach["id"]):
        raise HTTPException(409, "Coach Dashboard V2 not enabled")

    draft = await db.plan_drafts.find_one(
        {"id": body.draft_id, "client_id": client_id}, {"_id": 0}
    )
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft["status"] in ("promoted", "discarded"):
        raise HTTPException(409, f"Draft is {draft['status']}")

    programme_id = draft["programme_id"]

    # Resolve target assignments
    if body.scope == "all":
        assignments = await db.workout_assignments.find(
            {"client_id": client_id, "draft_id": body.draft_id,
             "locked": {"$ne": True}}, {"_id": 0}
        ).to_list(1000)
        # Fallback if draft_id link missing – use programme_id
        if not assignments:
            assignments = await db.workout_assignments.find(
                {"client_id": client_id, "programme_id": programme_id,
                 "locked": {"$ne": True}}, {"_id": 0}
            ).to_list(1000)
        assignment_ids = [a["id"] for a in assignments]
    else:
        assignment_ids = list(body.assignment_ids or [])
        if assignment_ids:
            assignments = await db.workout_assignments.find(
                {"client_id": client_id, "id": {"$in": assignment_ids},
                 "locked": {"$ne": True}}, {"_id": 0}
            ).to_list(1000)
        else:
            assignments = []

    # Promote each assignment: live_implementation_id ← draft_implementation_id, status='live'
    promoted_ids: list[str] = []
    real_promotions = 0     # count of actual live_impl swaps (excludes idempotent already-live)
    skipped_no_draft: list[str] = []
    for a in assignments:
        draft_impl = a.get("draft_implementation_id")
        if not draft_impl:
            skipped_no_draft.append(a["id"])
            continue
        if a.get("live_implementation_id") == draft_impl:
            # already live – idempotent
            promoted_ids.append(a["id"])
            continue
        upd = {
            "live_implementation_id": draft_impl,
            "status": "live",
            "updated_at": now_iso(),
        }
        await db.workout_assignments.update_one({"id": a["id"]}, {"$set": upd})
        promoted_ids.append(a["id"])
        real_promotions += 1

    # Accept change_sets
    accepted_ids = list(body.accept_change_set_ids or [])
    if accepted_ids:
        await db.change_sets.update_many(
            {"id": {"$in": accepted_ids}, "client_id": client_id,
             "status": "proposed"},
            {"$set": {"status": "accepted", "resolved_at": now_iso(),
                      "resolved_by": coach["id"]}}
        )

    # Reject change_sets (never promoted)
    rejected_ids = list(body.reject_change_set_ids or [])
    if rejected_ids:
        await db.change_sets.update_many(
            {"id": {"$in": rejected_ids}, "client_id": client_id,
             "status": "proposed"},
            {"$set": {"status": "rejected", "resolved_at": now_iso(),
                      "resolved_by": coach["id"],
                      "resolution_notes": body.notes or ""}}
        )
        for cs_id in rejected_ids:
            await write_decision(
                actor="coach", layer="PUBLISH", scope_kind="change_set",
                scope_id=cs_id, client_id=client_id, outcome="REJECTED",
                reason=body.notes or "Rejected during Publish",
            )

    # Bail early if nothing to publish (rejects still valid)
    if not promoted_ids and not accepted_ids:
        return {
            "published_count": 0,
            "rejected_count": len(rejected_ids),
            "skipped_assignment_ids": skipped_no_draft,
            "version_id": None,
            "version": None,
            "note": "Nothing to publish. Rejections applied.",
        }

    # Skip empty version row when nothing actually changed in DB
    # (all assignments were already live AND no change-sets to accept).
    if real_promotions == 0 and not accepted_ids:
        return {
            "published_count": len(promoted_ids),
            "accepted_change_sets": 0,
            "rejected_count": len(rejected_ids),
            "skipped_assignment_ids": skipped_no_draft,
            "version_id": None,
            "version": None,
            "note": "Selected assignments already live. No new version needed.",
        }

    # New plan_version + snapshot
    latest = await db.plan_versions.find_one(
        {"programme_id": programme_id}, {"_id": 0, "id": 1, "version": 1},
        sort=[("version", -1)]
    )
    version_no = int((latest or {}).get("version") or 0) + 1
    snap_id = new_id()
    await db.plan_snapshots.insert_one({
        "id": snap_id, "programme_id": programme_id, "client_id": client_id,
        "draft_id": body.draft_id,
        "scope": body.scope, "scope_ref": promoted_ids,
        "workout_assignments_snapshot": promoted_ids,
        "accepted_change_set_ids": accepted_ids,
        "rejected_change_set_ids": rejected_ids,
        "created_at": now_iso(),
    })
    version_id = new_id()
    await db.plan_versions.insert_one({
        "id": version_id, "programme_id": programme_id, "client_id": client_id,
        "version": version_no, "published_at": now_iso(), "published_by": coach["id"],
        "snapshot_id": snap_id,
        "supersedes_version_id": (latest or {}).get("id"),
        "approvals": [], "immutable": True,
    })
    ap_id = new_id()
    await db.approvals.insert_one({
        "id": ap_id, "programme_id": programme_id, "client_id": client_id,
        "draft_id": body.draft_id, "version_id": version_id,
        "scope": body.scope, "scope_ref": promoted_ids,
        "include_change_set_ids": accepted_ids,
        "notes": body.notes or "",
        "approved_by": coach["id"], "approved_at": now_iso(),
    })

    # Mark accepted change_sets as promoted in this version
    if accepted_ids:
        await db.change_sets.update_many(
            {"id": {"$in": accepted_ids}, "client_id": client_id},
            {"$set": {"promoted_in_version_id": version_id}}
        )

    # If the draft has no pending change_sets left AND all assignments promoted → mark 'promoted'
    remaining_proposed = await db.change_sets.count_documents(
        {"draft_id": body.draft_id, "status": "proposed"}
    )
    remaining_draft_only = await db.workout_assignments.count_documents({
        "client_id": client_id,
        "draft_id": body.draft_id,
        "$expr": {"$ne": ["$live_implementation_id", "$draft_implementation_id"]},
    })
    new_status = draft["status"]
    if remaining_proposed == 0 and remaining_draft_only == 0:
        new_status = "promoted"
    elif promoted_ids:
        new_status = "partially_approved"
    await db.plan_drafts.update_one(
        {"id": body.draft_id},
        {"$set": {"status": new_status, "updated_at": now_iso()}}
    )

    # Bump programme.live_plan_version metadata
    await db.programmes_v2.update_one(
        {"id": programme_id},
        {"$set": {"live_plan_version": version_no, "updated_at": now_iso()}}
    )

    await write_decision(
        actor="coach", layer="PUBLISH", scope_kind="plan_version",
        scope_id=version_id, client_id=client_id, outcome="APPLIED",
        reason=(
            f"Published {len(promoted_ids)} assignments · "
            f"{len(accepted_ids)} change sets accepted · "
            f"{len(rejected_ids)} rejected → v{version_no}"
        ),
        previous_state_ref=(latest or {}).get("id"),
        new_state_ref=version_id,
    )
    try:
        await emit_metric(
            "plan_published", client_id=client_id, coach_id=coach["id"],
            numeric_value=float(len(promoted_ids)),
            labels={"version": version_no, "scope": body.scope,
                    "accepted_change_sets": len(accepted_ids),
                    "rejected_change_sets": len(rejected_ids)},
        )
    except Exception:
        pass

    return {
        "published_count": len(promoted_ids),
        "accepted_change_sets": len(accepted_ids),
        "rejected_count": len(rejected_ids),
        "version_id": version_id,
        "version": version_no,
        "approval_id": ap_id,
        "draft_status": new_status,
        "skipped_assignment_ids": skipped_no_draft,
    }


logger.info("feature_v2_coach_publish: /api/v2/coach/clients/{cid}/plan/diff + /publish registered")
