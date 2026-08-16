"""Shared exercise-creation dedup / upsert helpers.

Consolidates the four independent creation paths that previously all
wrote to `exercises_v2` without a common gate:

  1. `feature_exercise_content.py::ex_create`               (manual coach add)
  2. `feature_exercise_content.py` subs_allowed auto-stub
  3. `feature_v2_resolver.py::create_exercise_request_if_missing`
  4. `feature_admin_migrations.py` migration insert

Public surface:
  * `canonical_key(name)`                 O(1) singular/plural fingerprint
  * `check_duplicate_candidate(name, …)`  fuzzy pre-insert check (≥80 %)
  * `safe_upsert_exercise(doc, …)`        upsert-on-conflict wrapper
  * `ensure_indexes()`                    creates the unique partial index
  * `record_duplicate_flag(...)`          audit-log for coach review

Kill-switch helpers:
  * `manual_mode_active()`
  * `exercise_backfill_disabled()`

Similarity gates (either can trigger — used to flag for coach review):
  * Existing token-Jaccard from `feature_v2_resolver._find_fuzzy_match`
    stays as the STRONG signal (≥ 0.85 with equipment / side / intensity
    disqualifiers).
  * NEW: `difflib.SequenceMatcher` char-level ratio ≥ 0.80 catches the
    "one-typo / partial rename" cases the token gate misses (e.g.
    "Kettlebell Swing" vs "Kettlebel Swing").
"""
from __future__ import annotations

import difflib
import logging
import os
import re
from typing import Any, Optional

from pymongo.errors import DuplicateKeyError

from server import db

logger = logging.getLogger("crewfit.feature_exercise_dedup")


# ---------------------------------------------------------------------------
# Kill-switch env helpers — read at every call so operators can flip flags
# without a full backend restart.
# ---------------------------------------------------------------------------

def manual_mode_active() -> bool:
    """Global MANUAL_MODE guard. When ON, all *automatic* exercise-creation
    and auto-media triggers must short-circuit. Coach-triggered manual
    actions (typing a new exercise into the admin form) still proceed —
    those go through the 409-conflict path if a similar row already exists.
    """
    return os.environ.get("MANUAL_MODE", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def exercise_backfill_disabled() -> bool:
    """Hard-freeze for the coach-tapped auto-media backfill endpoint.
    Independent of MANUAL_MODE — operators can freeze library churn
    without turning off the whole automatic workflow."""
    return os.environ.get("EXERCISE_BACKFILL_DISABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ---------------------------------------------------------------------------
# Canonical key — string form of the singular/plural-collapsed token tuple.
# Delegates to feature_v2_resolver so both files can't drift.
# ---------------------------------------------------------------------------

def canonical_key(name: Optional[str]) -> str:
    from feature_v2_resolver import _canonical_key
    return _canonical_key(name or "")


def _normalise(name: Optional[str]) -> str:
    from feature_v2_resolver import _normalise_name
    return _normalise_name(name or "")


# ---------------------------------------------------------------------------
# Duplicate-candidate check.
# ---------------------------------------------------------------------------
# Threshold: coach requested 80 %+ similarity fires a flag. We combine:
#   • existing feature_v2_resolver._find_fuzzy_match (token-Jaccard 0.85
#     with movement/equipment/side/intensity disqualifiers) — the STRONG
#     precision gate. Never returns a false-positive across obvious
#     variants (e.g. left vs right, kettlebell vs dumbbell).
#   • NEW `difflib.SequenceMatcher.ratio()` char-level ≥ 0.80 — catches
#     partial renames / typos the token gate misses.
#
# Either passes → we return a "duplicate candidate" record. Caller decides
# whether to silent-link (auto paths: backfill, alternatives, subs_allowed)
# or reject with 409 (manual coach add).
# ---------------------------------------------------------------------------

_SEQ_MATCH_THRESHOLD = 0.80


async def check_duplicate_candidate(
    name: str,
    *,
    movement_pattern: Optional[str] = None,
    equipment_type: Optional[list] = None,
    exclude_ids: Optional[list[str]] = None,
) -> Optional[dict]:
    """Return the best matching existing exercises_v2 row (as a dict with
    `id`, `exercise_name`, `score`, `gate`) IFF one is found at or above
    the coach-configured similarity threshold.  Returns None otherwise.

    `gate` is one of:
        "exact"    — exact canonical_key match (safe to silently reuse).
        "jaccard"  — passed the token-Jaccard 0.85 gate.
        "seqmatch" — passed the char-level 0.80 gate only.
    """
    name = (name or "").strip()
    if not name:
        return None
    exclude = set(exclude_ids or [])

    # 1) Exact canonical-key match  (O(1) via canonical_name_key)
    ck = canonical_key(name)
    if ck:
        exact = await db.exercises_v2.find_one(
            {"canonical_name_key": ck,
             "id": {"$nin": list(exclude)} if exclude else {"$exists": True}},
            {"_id": 0, "id": 1, "exercise_name": 1, "canonical_id": 1},
        )
        if exact:
            # Follow alias → canonical
            target = exact
            if exact.get("canonical_id") and exact["canonical_id"] != exact["id"]:
                canon = await db.exercises_v2.find_one(
                    {"id": exact["canonical_id"]},
                    {"_id": 0, "id": 1, "exercise_name": 1},
                )
                if canon:
                    target = canon
            return {
                "id": target["id"],
                "exercise_name": target.get("exercise_name"),
                "score": 1.0,
                "gate": "exact",
            }

    # 2) Token-Jaccard  (strong gate — delegates to existing resolver)
    try:
        from feature_v2_resolver import _find_fuzzy_match
        j = await _find_fuzzy_match(name, movement_pattern, equipment_type or [])
    except Exception:
        logger.exception("check_duplicate_candidate: jaccard gate failed")
        j = None
    if j and j.get("id") not in exclude:
        return {
            "id": j["id"],
            "exercise_name": j.get("exercise_name"),
            "score": float(j.get("score") or 0.85),
            "gate": "jaccard",
        }

    # 3) Char-level SequenceMatcher  (catches typos / partial renames)
    #    Pre-filter with the same shared-token cursor as _find_fuzzy_match
    #    to keep this O(few dozen) per call.
    from feature_v2_resolver import _canonical_tokens
    tokens = [t for t in _canonical_tokens(name) if len(t) >= 3]
    if not tokens:
        return None
    or_clauses = [
        {"exercise_name": {"$regex": re.escape(t), "$options": "i"}}
        for t in tokens
    ]
    norm_incoming = _normalise(name)
    best: Optional[tuple[float, dict]] = None
    cursor = db.exercises_v2.find(
        {"$or": or_clauses,
         "status": {"$nin": ["rejected", "archived", "merged"]},
         "id": {"$nin": list(exclude)} if exclude else {"$exists": True}},
        {"_id": 0, "id": 1, "exercise_name": 1, "canonical_id": 1},
    ).limit(60)
    async for cand in cursor:
        cname = cand.get("exercise_name") or ""
        norm_cand = _normalise(cname)
        if not norm_cand:
            continue
        r = difflib.SequenceMatcher(None, norm_incoming, norm_cand).ratio()
        if r >= _SEQ_MATCH_THRESHOLD:
            if best is None or r > best[0]:
                best = (r, cand)
    if best:
        r, cand = best
        target = cand
        if cand.get("canonical_id") and cand["canonical_id"] != cand["id"]:
            canon = await db.exercises_v2.find_one(
                {"id": cand["canonical_id"]},
                {"_id": 0, "id": 1, "exercise_name": 1},
            )
            if canon:
                target = canon
        return {
            "id": target["id"],
            "exercise_name": target.get("exercise_name"),
            "score": round(r, 3),
            "gate": "seqmatch",
        }

    return None


# ---------------------------------------------------------------------------
# Duplicate-flag audit log.
# ---------------------------------------------------------------------------
# Every dedup hit lands here so the coach has a review trail. Never blocks
# — failure to write is logged and swallowed.
# ---------------------------------------------------------------------------

async def record_duplicate_flag(
    *,
    proposed_name: str,
    matched_id: str,
    matched_name: str,
    score: float,
    gate: str,
    source: str,
    triggered_by: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    from feature_v2_resolver import now_iso  # local import to avoid cycles
    try:
        await db.exercise_duplicate_candidates.insert_one({
            "proposed_name": proposed_name,
            "matched_id": matched_id,
            "matched_name": matched_name,
            "score": score,
            "gate": gate,
            "source": source,           # "backfill" | "alternatives" | "subs_allowed" | "resolver" | "manual"
            "triggered_by": triggered_by,
            "extra": extra or {},
            "created_at": now_iso(),
            "reviewed": False,
        })
    except Exception:
        logger.exception("record_duplicate_flag: non-fatal write failure")


# ---------------------------------------------------------------------------
# Upsert-on-conflict wrapper.
# ---------------------------------------------------------------------------
# Path 1 — no duplicate found (or dedup skipped) → tries the raw insert.
# Path 2 — DuplicateKeyError raised by the new unique partial index
#          (concurrent race between two workers) → re-query and return
#          the winner's id.  Idempotent from the caller's POV.
# ---------------------------------------------------------------------------

async def safe_upsert_exercise(doc: dict) -> dict:
    """Insert `doc` into exercises_v2, or return the existing row if a
    unique-index conflict fires.

    Returns
        {"id": …, "inserted": bool, "existing": Optional[dict]}
    """
    try:
        await db.exercises_v2.insert_one(doc)
        return {"id": doc["id"], "inserted": True, "existing": None}
    except DuplicateKeyError:
        # Race: another worker beat us to the same canonical_name_key.
        # Re-query and return the winner. Never raises to the caller.
        ck = doc.get("canonical_name_key") or canonical_key(doc.get("exercise_name"))
        existing = await db.exercises_v2.find_one(
            {"canonical_name_key": ck,
             "canonical_id": None},
            {"_id": 0},
        )
        if existing:
            logger.info(
                "safe_upsert_exercise: DuplicateKeyError → returning existing "
                "id=%s name=%r for proposed name=%r",
                existing.get("id"), existing.get("exercise_name"),
                doc.get("exercise_name"),
            )
            return {"id": existing["id"], "inserted": False, "existing": existing}
        # Shouldn't happen, but return the intended id so caller doesn't crash.
        return {"id": doc["id"], "inserted": False, "existing": None}


# ---------------------------------------------------------------------------
# One-time index creation. Called from server lifespan startup.
# ---------------------------------------------------------------------------

async def ensure_indexes() -> None:
    """Create the unique partial index on `canonical_name_key`.
    Idempotent — safe to run on every startup."""
    try:
        # Step 1: normalise canonical_id — the partial filter cannot use
        # $exists, so we set the field explicitly to null on winners.
        await db.exercises_v2.update_many(
            {"canonical_id": {"$exists": False}},
            {"$set": {"canonical_id": None}},
        )
        # Step 2: null-out canonical_name_key on ALIAS rows — they resolve
        # via canonical_id and their key would collide with the winner's.
        await db.exercises_v2.update_many(
            {"canonical_id": {"$type": "string"},
             "canonical_name_key": {"$type": "string"}},
            {"$unset": {"canonical_name_key": ""}},
        )
        # Step 3: collapse remaining CANONICAL duplicates (rows that
        # share canonical_name_key but have canonical_id=null). Keep the
        # oldest / most-completed as winner; convert the rest to aliases.
        pipe = [
            {"$match": {"canonical_id": None,
                        "canonical_name_key": {"$type": "string", "$ne": ""}}},
            {"$group": {"_id": "$canonical_name_key", "docs":
                {"$push": {"id": "$id",
                           "created_at": "$created_at",
                           "status": "$status",
                           "approval_status": "$approval_status"}}}},
            {"$match": {"docs.1": {"$exists": True}}},  # >1 in group
        ]
        collapsed = 0
        async for grp in db.exercises_v2.aggregate(pipe):
            docs = grp["docs"]
            # Winner = most-approved first, then oldest.
            def _rank(d):
                st = (d.get("approval_status") or "").lower()
                score = 0
                if st in ("approved", "live"):
                    score = 100
                elif st in ("pending", "needs_review"):
                    score = 50
                return (-score, d.get("created_at") or "")
            docs.sort(key=_rank)
            winner = docs[0]
            for loser in docs[1:]:
                await db.exercises_v2.update_one(
                    {"id": loser["id"]},
                    {"$set": {"canonical_id": winner["id"],
                              "collapsed_at": None},
                     "$unset": {"canonical_name_key": ""}},
                )
                collapsed += 1
        if collapsed:
            logger.info(
                "feature_exercise_dedup: collapsed %d duplicate canonicals "
                "into their winners", collapsed,
            )

        # Step 4: create the unique partial index.
        await db.exercises_v2.create_index(
            [("canonical_name_key", 1)],
            unique=True,
            name="uniq_canonical_name_key_canonical",
            partialFilterExpression={
                "canonical_name_key": {"$type": "string"},
                "canonical_id": {"$type": "null"},
            },
        )
        logger.info("feature_exercise_dedup: unique canonical_name_key index ensured")
    except Exception:
        logger.exception("feature_exercise_dedup: ensure_indexes failed (non-fatal)")

    # Supporting index on the duplicate-candidates audit log for FIFO reads.
    try:
        await db.exercise_duplicate_candidates.create_index(
            [("created_at", -1)], name="dup_cand_created_desc",
        )
    except Exception:
        logger.exception("feature_exercise_dedup: dup-cand index failed (non-fatal)")
