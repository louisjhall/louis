"""
feature_flight_support_coverage — Manual Mode Stage C.

Flight Support ships hardcoded protocol specs in
`feature_aviation_support.PROTOCOLS` where each spec has a `blocks: [...]`
list of drills — e.g. "Thoracic rotation", "Air squats", "Legs-up-the-wall".
Historically these names are STRINGS ONLY — they have no `exercises_v2`
library record, so the coach can't queue media for them and they never show
up in the exercise atlas.

This module provides a one-shot backfill:
  * Iterate every registered protocol.
  * Collect the unique block names.
  * For each name, ensure an `exercises_v2` record exists — matching by name
    first (dedup), otherwise filing a draft-requested library record.
  * Return an audit summary the admin UI can display.

Endpoint:
  * POST /api/admin/flight-support/backfill-library
      → { ok, unique_blocks, matched_existing, drafts_created,
          per_block: [{name, exercise_id, kind: "matched"|"drafted"}] }

The endpoint is idempotent — running it repeatedly is safe. Dedup happens
inside `create_exercise_request_if_missing` (case + punctuation insensitive
match against `exercise_name` and `requested_name_norm`).
"""
from __future__ import annotations

from typing import Any
from fastapi import Depends, HTTPException

from server import api, db, require_role, logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iter_flight_support_block_names() -> list[dict]:
    """Return a deduped list of {name, cue, families, intensities} entries
    across every registered protocol. Cues + families are aggregated so the
    draft library record carries useful context on creation.

    Import-time protection: we import `PROTOCOLS` lazily so a broken
    protocol module can't crash this module's import."""
    try:
        from feature_aviation_support import PROTOCOLS
    except Exception:
        logger.exception("flight_support_coverage: cannot import PROTOCOLS")
        return []
    by_name: dict[str, dict[str, Any]] = {}
    for proto in PROTOCOLS.values():
        for block in proto.blocks or []:
            name = (block.get("name") or "").strip()
            if not name:
                continue
            entry = by_name.setdefault(name, {
                "name": name,
                "cues": set(),
                "families": set(),
                "intensities": set(),
                "roles": set(),
                "equipment": set(),
            })
            cue = (block.get("cue") or "").strip()
            if cue:
                entry["cues"].add(cue)
            entry["families"].add(proto.family)
            entry["intensities"].add(proto.intensity)
            entry["roles"].add(proto.role)
            for eq in (proto.equipment or []):
                if eq:
                    entry["equipment"].add(eq)
    # Materialise sets → sorted lists for JSON-serialisable output.
    out: list[dict] = []
    for name in sorted(by_name.keys()):
        e = by_name[name]
        out.append({
            "name": e["name"],
            "cues": sorted(e["cues"]),
            "families": sorted(e["families"]),
            "intensities": sorted(e["intensities"]),
            "roles": sorted(e["roles"]),
            "equipment": sorted(e["equipment"]),
        })
    return out


def _tags_for_block(entry: dict) -> list[str]:
    """Reasonable default tags for a Flight-Support-only exercise."""
    tags: list[str] = ["flight_support"]
    for f in entry.get("families") or []:
        tags.append(f"family:{f}")
    for r in entry.get("roles") or []:
        tags.append(f"role:{r}")
    return tags


def _movement_pattern_hint(name: str, families: list[str]) -> str | None:
    """Best-effort movement_pattern classification so drafts land in the
    right coach filter buckets. Purely name-based heuristics — coach can
    override on approval."""
    n = name.lower()
    if "squat" in n:
        return "squat"
    if "bridge" in n:
        return "hinge"
    if "row" in n:
        return "pull"
    if "walk" in n:
        return "conditioning"
    if any(w in n for w in ("breath", "breathing", "box breath")):
        return "breathwork"
    if any(w in n for w in ("stretch", "opener", "mobility", "release",
                             "rotation", "twist", "roll", "circle", "reach",
                             "fold", "hip", "t-spine", "shoulder", "neck",
                             "calf", "ankle", "pigeon", "legs-up")):
        return "mobility"
    if "activation" in families or "reset" in families:
        return "mobility"
    return None


# ---------------------------------------------------------------------------
# Admin endpoint
# ---------------------------------------------------------------------------

@api.post("/admin/flight-support/backfill-library")
async def flight_support_backfill_library(
    admin: dict = Depends(require_role("coach")),
):
    """Iterate every hardcoded Flight Support protocol, collect its unique
    block names, and ensure each has a corresponding `exercises_v2` record.

    Requires coach role. Idempotent — safe to run repeatedly.
    """
    if not admin.get("is_admin"):
        raise HTTPException(403, "admin only")
    entries = _iter_flight_support_block_names()
    if not entries:
        return {"ok": True, "unique_blocks": 0, "matched_existing": 0,
                "drafts_created": 0, "per_block": []}

    try:
        from feature_media_queue import resolve_or_draft_exercise
    except Exception:
        logger.exception("flight_support_coverage: cannot import media queue helper")
        raise HTTPException(500, "media_queue module unavailable")

    per_block: list[dict] = []
    matched = 0
    drafted = 0

    for entry in entries:
        name = entry["name"]
        # Match against existing library first (fast pre-check, avoids the
        # draft-write path when we can just link an existing record).
        import re
        rx = {"$regex": f"^{re.escape(name)}$", "$options": "i"}
        existing = await db.exercises_v2.find_one(
            {"$or": [{"exercise_name": rx}]},
            {"_id": 0, "id": 1, "status": 1, "exercise_name": 1},
        )
        if existing:
            per_block.append({
                "name": name, "exercise_id": existing["id"],
                "kind": "matched",
                "status": existing.get("status"),
            })
            matched += 1
            continue

        # Not matched — file a draft with the richest context we have.
        parent_like = {
            "movement_pattern": _movement_pattern_hint(name, entry.get("families") or []),
            "equipment_type": entry.get("equipment") or [],
            "tags": _tags_for_block(entry),
            "difficulty_level": "beginner",  # Flight Support drills are low-effort by design
        }
        xid = await resolve_or_draft_exercise(
            name,
            user=admin,
            parent=parent_like,
            reason="flight_support_coverage_backfill",
        )
        if xid:
            per_block.append({
                "name": name, "exercise_id": xid, "kind": "drafted",
            })
            drafted += 1
            # Stamp aviation_use_case + coach-friendly cue on the fresh row
            # (safe merge — never overwrites existing coach edits).
            try:
                cue_seed = "\n".join(entry.get("cues") or [])
                await db.exercises_v2.update_one(
                    {"id": xid, "aviation_use_case": {"$in": [None, ""]}},
                    {"$set": {
                        "aviation_use_case": (
                            f"Flight Support drill · used in "
                            f"{', '.join(entry.get('families') or [])} protocols."
                        ),
                        "coach_notes_seed": cue_seed,
                    }},
                )
            except Exception:
                logger.exception("flight_support_coverage: post-create metadata patch failed for %s", xid)
        else:
            per_block.append({"name": name, "exercise_id": None, "kind": "skipped"})

    return {
        "ok": True,
        "unique_blocks": len(entries),
        "matched_existing": matched,
        "drafts_created": drafted,
        "per_block": per_block,
    }


@api.get("/admin/flight-support/coverage-preview")
async def flight_support_coverage_preview(
    admin: dict = Depends(require_role("coach")),
):
    """DRY-RUN — report every Flight Support block name and its current
    library-coverage status without writing anything. Handy for the coach
    dashboard to preview what a backfill would do."""
    if not admin.get("is_admin"):
        raise HTTPException(403, "admin only")
    entries = _iter_flight_support_block_names()
    if not entries:
        return {"ok": True, "unique_blocks": 0, "already_in_library": 0,
                "missing_from_library": 0, "per_block": []}

    import re
    per_block: list[dict] = []
    matched = 0
    missing = 0
    for entry in entries:
        name = entry["name"]
        rx = {"$regex": f"^{re.escape(name)}$", "$options": "i"}
        existing = await db.exercises_v2.find_one(
            {"exercise_name": rx},
            {"_id": 0, "id": 1, "status": 1},
        )
        if existing:
            per_block.append({
                "name": name, "exercise_id": existing["id"],
                "status": existing.get("status"), "kind": "in_library",
            })
            matched += 1
        else:
            per_block.append({"name": name, "kind": "missing"})
            missing += 1
    return {
        "ok": True,
        "unique_blocks": len(entries),
        "already_in_library": matched,
        "missing_from_library": missing,
        "per_block": per_block,
    }


__all__ = ["flight_support_backfill_library", "flight_support_coverage_preview"]
