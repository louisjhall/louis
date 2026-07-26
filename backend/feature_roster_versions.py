"""
Roster Versions + Overlap Resolution — Phase 3.

Endpoints:
    * POST /api/roster/pending/{rid}/resolve-overlap
        body: {mode: "replace" | "merge" | "keep_both"}
        - "replace"   → When this pending roster is confirmed, any prior
                       overlapping active roster is marked `superseded`.
        - "merge"     → Immediately patch overlapping/new days from THIS
                       pending roster into the existing active roster, then
                       discard this pending doc.
        - "keep_both" → No supersession. Both rosters coexist. Louis gets a
                       review task so someone eyeballs the two versions.

    * GET  /api/coach/clients/{cid}/roster/versions/{yyyy_mm}
        Returns every roster covering that month with metadata + a diff
        against the current primary version.

    * GET  /api/coach/clients/{cid}/roster/diff?a={rid}&b={rid}&yyyy_mm={key}
        Returns a per-date diff (added / removed / changed / unchanged).
"""
from __future__ import annotations
import calendar
from typing import Any, Optional
from datetime import date as _date

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, require_role, current_user, new_id, now_iso
import logging
logger = logging.getLogger("crewfit.roster_versions")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _month_key(d: str) -> str:
    if not d or len(d) < 7:
        return ""
    return d[:7]


def _month_label(key: str) -> str:
    if not key or len(key) != 7:
        return key or "Unknown"
    try:
        y, m = key.split("-")
        return f"{calendar.month_name[int(m)]} {y}"
    except Exception:
        return key


def _fingerprint_day(d: dict) -> tuple:
    """Comparable tuple for a single day. Two days are considered
    equal iff their fingerprints match."""
    flights = tuple(
        (f.get("from"), f.get("to"), f.get("flight_number"))
        for f in (d.get("flights") or [])
    )
    return (
        d.get("day_type"),
        d.get("training_colour"),
        d.get("client_label"),
        d.get("layover_city"),
        d.get("report_time"),
        d.get("release_time") or d.get("duty_end_time"),
        flights,
    )


def _diff_two_rosters(a_days: list[dict], b_days: list[dict],
                      month_filter: Optional[str] = None) -> dict:
    """Day-by-day diff between two rosters. Returns per-date buckets:
       added (in B but not A), removed (in A but not B),
       changed (in both, fingerprints differ), unchanged.
    """
    def _in_month(d: str) -> bool:
        if not month_filter:
            return True
        return _month_key(d) == month_filter

    a_map = {d.get("date"): d for d in (a_days or []) if d.get("date") and _in_month(d["date"])}
    b_map = {d.get("date"): d for d in (b_days or []) if d.get("date") and _in_month(d["date"])}
    all_dates = sorted(set(a_map) | set(b_map))
    added: list[dict] = []
    removed: list[dict] = []
    changed: list[dict] = []
    unchanged: list[str] = []
    for dt in all_dates:
        ad = a_map.get(dt)
        bd = b_map.get(dt)
        if ad and not bd:
            removed.append({"date": dt, "prev": {
                "day_type": ad.get("day_type"),
                "client_label": ad.get("client_label"),
                "training_colour": ad.get("training_colour"),
            }})
        elif bd and not ad:
            added.append({"date": dt, "new": {
                "day_type": bd.get("day_type"),
                "client_label": bd.get("client_label"),
                "training_colour": bd.get("training_colour"),
            }})
        elif ad and bd:
            if _fingerprint_day(ad) != _fingerprint_day(bd):
                changed.append({
                    "date": dt,
                    "prev": {
                        "day_type": ad.get("day_type"),
                        "client_label": ad.get("client_label"),
                        "training_colour": ad.get("training_colour"),
                        "layover_city": ad.get("layover_city"),
                        "report_time": ad.get("report_time"),
                    },
                    "new": {
                        "day_type": bd.get("day_type"),
                        "client_label": bd.get("client_label"),
                        "training_colour": bd.get("training_colour"),
                        "layover_city": bd.get("layover_city"),
                        "report_time": bd.get("report_time"),
                    },
                })
            else:
                unchanged.append(dt)
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": len(unchanged),
        "total_dates": len(all_dates),
    }


# ---------------------------------------------------------------------------
# Overlap resolution
# ---------------------------------------------------------------------------

class ResolveOverlapBody(BaseModel):
    mode: str  # "replace" | "merge" | "keep_both"


@api.post("/roster/pending/{rid}/resolve-overlap")
async def roster_pending_resolve_overlap(
    rid: str,
    body: ResolveOverlapBody,
    user: dict = Depends(current_user),
) -> dict:
    """Client-side declaration of what to do about the overlapping roster.
    Mode is stored on the pending roster so the confirm-flow honours it."""
    if body.mode not in ("replace", "merge", "keep_both"):
        raise HTTPException(400, "mode must be replace|merge|keep_both")

    pending = await db.rosters.find_one(
        {"id": rid, "user_id": user["id"], "status": "pending_confirmation"},
        {"_id": 0},
    )
    if not pending:
        raise HTTPException(404, "Pending roster not found")

    if body.mode == "merge":
        # Find the active roster this overlaps with — take the one with the
        # most overlapping dates.
        active = await db.rosters.find(
            {"user_id": user["id"], "is_active": True, "confirmed": True},
            {"_id": 0},
        ).to_list(20)
        if not active:
            # Nothing to merge INTO — degrade to "replace" semantics.
            await db.rosters.update_one(
                {"id": rid}, {"$set": {"overlap_mode": "replace", "updated_at": now_iso()}}
            )
            return {"mode": "replace", "merged": False,
                    "message": "No prior active roster found — will replace on confirm."}

        pending_days_by_date = {d.get("date"): d for d in (pending.get("days") or []) if d.get("date")}
        best = None
        best_overlap = 0
        for a in active:
            overlap = sum(1 for d in (a.get("days") or []) if d.get("date") in pending_days_by_date)
            if overlap > best_overlap:
                best_overlap = overlap
                best = a
        if best is None or best_overlap == 0:
            await db.rosters.update_one(
                {"id": rid}, {"$set": {"overlap_mode": "replace", "updated_at": now_iso()}}
            )
            return {"mode": "replace", "merged": False,
                    "message": "No overlap found — treating as replace."}

        # Merge: new days win for overlapping dates, prior days survive for
        # non-overlapping dates.
        merged_days_by_date = {d.get("date"): d for d in (best.get("days") or []) if d.get("date")}
        for dt, nd in pending_days_by_date.items():
            merged_days_by_date[dt] = nd
        merged_days = [merged_days_by_date[dt] for dt in sorted(merged_days_by_date)]

        # Update the primary roster in-place; log the merge event.
        await db.rosters.update_one(
            {"id": best["id"]},
            {"$set": {
                "days": merged_days,
                "updated_at": now_iso(),
                "last_merge_from": rid,
                "day_count": len(merged_days),
            }},
        )
        # Track version history reference
        await db.rosters.update_one(
            {"id": best["id"]},
            {"$push": {
                "version_history": {
                    "id": new_id(),
                    "at": now_iso(),
                    "action": "merged",
                    "merged_from_pending": rid,
                    "merged_dates": sorted(pending_days_by_date.keys()),
                    "changed_count": best_overlap,
                }
            }},
        )
        # Discard the pending doc.
        await db.rosters.delete_one({"id": rid, "status": "pending_confirmation"})
        return {
            "mode": "merge",
            "merged": True,
            "into_roster_id": best["id"],
            "changed_dates": best_overlap,
            "total_dates_after_merge": len(merged_days),
        }

    # replace | keep_both — just record intent for the confirm step.
    await db.rosters.update_one(
        {"id": rid},
        {"$set": {"overlap_mode": body.mode, "updated_at": now_iso()}},
    )
    return {"mode": body.mode, "recorded": True}


# ---------------------------------------------------------------------------
# Coach — Roster versions for a month
# ---------------------------------------------------------------------------

@api.get("/coach/clients/{client_id}/roster/versions/{yyyy_mm}")
async def coach_client_roster_versions(
    client_id: str,
    yyyy_mm: str,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Return every roster covering the given month, most-recent-first,
    with a diff against the current primary."""
    if len(yyyy_mm) != 7 or yyyy_mm[4] != "-":
        raise HTTPException(400, "Month must be YYYY-MM")

    user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(404, "Client not found")

    rosters = await db.rosters.find(
        {"user_id": client_id},
        {"_id": 0, "raw_response": 0},
    ).sort("created_at", -1).to_list(60)
    matching = [
        r for r in rosters
        if any(_month_key(d.get("date") or "") == yyyy_mm for d in (r.get("days") or []))
    ]
    if not matching:
        return {
            "month_key": yyyy_mm,
            "month_label": _month_label(yyyy_mm),
            "versions": [],
            "primary_id": None,
        }

    def _rank(r: dict) -> tuple[int, str]:
        if r.get("is_active") and r.get("confirmed"):
            score = 4
        elif r.get("confirmed"):
            score = 3
        elif r.get("status") == "pending_confirmation":
            score = 2
        else:
            score = 1
        return (score, str(r.get("created_at") or ""))

    ordered = sorted(matching, key=_rank, reverse=True)
    primary = ordered[0]

    versions_out: list[dict] = []
    for r in ordered:
        version_entry = {
            "id": r.get("id"),
            "created_at": r.get("created_at"),
            "confirmed": bool(r.get("confirmed")),
            "is_active": bool(r.get("is_active")),
            "is_primary": (r.get("id") == primary.get("id")),
            "status": r.get("status"),
            "confidence_avg": r.get("confidence_avg"),
            "source_filename": r.get("source_filename"),
            "parser_source": r.get("parser_source"),
            "start_date": r.get("start_date"),
            "end_date": r.get("end_date"),
            "day_count": r.get("day_count"),
        }
        if r.get("id") != primary.get("id"):
            version_entry["diff_vs_primary"] = _diff_two_rosters(
                primary.get("days") or [],
                r.get("days") or [],
                month_filter=yyyy_mm,
            )
        versions_out.append(version_entry)

    return {
        "month_key": yyyy_mm,
        "month_label": _month_label(yyyy_mm),
        "primary_id": primary.get("id"),
        "versions": versions_out,
    }


@api.get("/coach/clients/{client_id}/roster/diff")
async def coach_client_roster_diff(
    client_id: str,
    a: str,
    b: str,
    yyyy_mm: Optional[str] = None,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Diff two arbitrary roster versions for a client (optionally
    restricted to a single month)."""
    user = await db.users.find_one({"id": client_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(404, "Client not found")
    ra = await db.rosters.find_one({"id": a, "user_id": client_id}, {"_id": 0, "raw_response": 0})
    rb = await db.rosters.find_one({"id": b, "user_id": client_id}, {"_id": 0, "raw_response": 0})
    if not ra or not rb:
        raise HTTPException(404, "One or both rosters not found")
    return {
        "a": {"id": ra.get("id"), "source_filename": ra.get("source_filename"),
              "created_at": ra.get("created_at"), "confirmed": bool(ra.get("confirmed"))},
        "b": {"id": rb.get("id"), "source_filename": rb.get("source_filename"),
              "created_at": rb.get("created_at"), "confirmed": bool(rb.get("confirmed"))},
        "diff": _diff_two_rosters(ra.get("days") or [], rb.get("days") or [], month_filter=yyyy_mm),
    }
