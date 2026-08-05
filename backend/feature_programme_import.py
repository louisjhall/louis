"""
feature_programme_import — Phase 1 · Monthly Programme JSON Import (preview only).

Provides:
  * POST /api/coach/programme-import/preview
        Validate a ChatGPT-generated (or hand-written) month-programme
        JSON envelope, resolve every exercise against the V2 library
        via the shared deterministic resolver, flatten supersets /
        circuits into flat exercise rows, count what would be queued
        for the coach media pipeline, and stash the transformed result
        so a future POST /apply can commit it without re-parsing.

Design notes:
  * NO LLM calls. Matching uses `feature_v2_resolver.resolve_exercise_need`,
    the same deterministic scorer already used for LLM-side output.
  * NOTHING is written to the workout / exercise / media-queue collections
    during preview. Drafts are counted, not created.
  * A single preview row is persisted (TTL 10 min) so the Phase 2 apply
    endpoint can trust the transformed workouts blob without re-parsing.
  * All response shapes intentionally match §3.2 of
    /app/memory/MONTHLY_PROGRAMME_JSON_IMPORT_DESIGN.md — the frontend
    contract is fixed there.

This module is a Phase 1 slice: it deliberately does NOT expose an
apply endpoint. Phase 2 will add /apply and route through the shared
manual-workout create helper.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional, Union

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server import (
    api,
    db,
    require_role,
    logger,
    new_id,
    now_iso,
)

# We reuse — never rebuild — the deterministic resolver and media-queue
# helpers. If either module is unavailable (e.g. import-order edge cases
# during tests) we raise at call time so the operator sees a clear error.


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEMA_ID = "crewfit://programme-import/v1"
MAX_WORKOUTS = 62
MAX_PAYLOAD_BYTES = 512 * 1024
PREVIEW_TTL_SECONDS = 600  # 10 minutes

ALLOWED_WORKOUT_TYPES = {"strength", "run", "cardio", "mobility", "recovery", "other"}
ALLOWED_GROUP_TYPES = {
    "superset", "triset", "giantset", "circuit",
    "emom", "amrap", "tabata", "interval", "complex",
}
ALLOWED_POLICIES = {"reject_conflicts", "replace_conflicts", "skip_conflicts"}

MANUAL_SOURCE = "coach_manual"

# Direct-match / substitute score thresholds (mirror feature_v2_resolver defaults)
_MIN_DIRECT_MATCH = 50.0
_MIN_SUBSTITUTE_MATCH = 10.0


# ---------------------------------------------------------------------------
# Pydantic models — envelope, workout, ref, item, group
# ---------------------------------------------------------------------------

class ExerciseRef(BaseModel):
    """Reference to an exercise in the V2 library.

    Exactly one of exercise_id or name is required. ``aliases`` are extra
    tokens fed into the fuzzy scorer (name-only path).
    """
    exercise_id: Optional[str] = None
    name: Optional[str] = None
    aliases: Optional[list[str]] = None


class FlatItem(BaseModel):
    """Warm-up / cool-down drill — flat prescription."""
    ref: ExerciseRef
    sets: Optional[int] = None
    reps: Optional[Union[int, str]] = None
    duration_sec: Optional[int] = None
    rest_sec: Optional[int] = None
    load: Optional[str] = None
    tempo: Optional[str] = None
    rpe: Optional[float] = None
    notes: Optional[str] = None


class SingleMainExercise(BaseModel):
    """Standalone main-work exercise."""
    kind: Literal["single"] = "single"
    ref: ExerciseRef
    sets: Optional[int] = None
    reps: Optional[Union[int, str]] = None
    duration_sec: Optional[int] = None
    rest_sec: Optional[int] = None
    load: Optional[str] = None
    tempo: Optional[str] = None
    rpe: Optional[float] = None
    notes: Optional[str] = None
    equipment: Optional[str] = None
    alternative_exercise_id: Optional[str] = None
    alternative_name: Optional[str] = None


class GroupMemberItem(BaseModel):
    """One station inside a superset / circuit / EMOM / AMRAP block."""
    ref: ExerciseRef
    reps: Optional[Union[int, str]] = None
    duration_sec: Optional[int] = None
    rest_sec: Optional[int] = None
    load: Optional[str] = None
    tempo: Optional[str] = None
    rpe: Optional[float] = None
    notes: Optional[str] = None


class GroupBlock(BaseModel):
    """Grouped main-work block (superset, circuit, EMOM, AMRAP, tabata …)."""
    kind: Literal["group"] = "group"
    group_type: str
    group_label: Optional[str] = None
    rounds: Optional[int] = None
    rest_between_rounds_sec: Optional[int] = None
    rest_between_items_sec: Optional[int] = None
    work_sec: Optional[int] = None
    rest_sec: Optional[int] = None
    cap_min: Optional[int] = None
    notes: Optional[str] = None
    items: list[GroupMemberItem]


# Discriminated union — pydantic picks the model by the "kind" field.
MainExerciseBlock = Union[SingleMainExercise, GroupBlock]


class WorkoutEnvelopeItem(BaseModel):
    date: str
    title: str
    workout_type: str = "other"
    duration_min: Optional[int] = None
    location: Optional[str] = None
    equipment_context: Optional[str] = None
    rpe: Optional[float] = None
    coach_notes: Optional[str] = None
    warmup: list[FlatItem] = Field(default_factory=list)
    exercises: list[MainExerciseBlock] = Field(default_factory=list)
    cooldown: list[FlatItem] = Field(default_factory=list)
    external_ref: Optional[str] = None


class ImportMeta(BaseModel):
    client_email: Optional[str] = None
    client_id: Optional[str] = None
    month: str
    timezone: Optional[str] = None
    generated_by: Optional[str] = None
    source_prompt_hash: Optional[str] = None
    author_notes: Optional[str] = None


class ProgrammeImportEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_id: str = Field(alias="$schema")
    meta: ImportMeta
    roster_hints: Optional[dict[str, Any]] = None
    workouts: list[WorkoutEnvelopeItem]
    override_policy: str = "replace_conflicts"


# ---------------------------------------------------------------------------
# Helpers — client resolution, month validation
# ---------------------------------------------------------------------------

async def _resolve_client(meta: ImportMeta) -> dict:
    """Look up the target client by email (primary) or id (fallback).

    Email lookup is case-insensitive (mirrors the manual builder pattern
    across the app).
    """
    if meta.client_email:
        rx = re.compile(f"^{re.escape(meta.client_email.strip())}$", re.IGNORECASE)
        u = await db.users.find_one(
            {"email": rx},
            {"_id": 0, "password_hash": 0},
        )
        if u:
            return u
    if meta.client_id:
        u = await db.users.find_one(
            {"id": meta.client_id},
            {"_id": 0, "password_hash": 0},
        )
        if u:
            return u
    if not meta.client_email and not meta.client_id:
        raise HTTPException(400, "meta.client_email OR meta.client_id is required")
    raise HTTPException(
        404,
        f"client not found (email={meta.client_email!r}, id={meta.client_id!r})",
    )


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _parse_month(month: str) -> tuple[int, int]:
    m = _MONTH_RE.match(month or "")
    if not m:
        raise HTTPException(400, f"meta.month must be YYYY-MM, got {month!r}")
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12):
        raise HTTPException(400, f"meta.month {month!r} has an invalid month")
    return y, mo


def _parse_date(d: str) -> datetime:
    if not _DATE_RE.match(d or ""):
        raise HTTPException(400, f"workout date must be YYYY-MM-DD, got {d!r}")
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except ValueError as e:
        raise HTTPException(400, f"workout date {d!r} is not a valid calendar date: {e}")


def _month_span(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


# ---------------------------------------------------------------------------
# Exercise matching (reuse feature_v2_resolver)
# ---------------------------------------------------------------------------

async def _match_ref(
    ref: ExerciseRef,
    pool: list[dict],
) -> dict:
    """Resolve a single ExerciseRef against the library.

    Returns a dict with:
      * exercise_id: matched V2 id, or None if unresolved
      * resolution: 'direct' | 'matched' | 'substituted' | 'unresolved'
                    | 'unknown_id' | 'missing_ref'
      * matched_name: canonical library name if a row was found
      * score: match score (matched / substituted only)
      * warning: preview-facing dict (fuzzy_match or unresolved_exercise)
                  populated for anything not clean-direct.
      * raw_name / raw_id: input for audit / display
    """
    # 1) Direct exercise_id lookup (accepts drafts too, unlike the pool).
    if ref.exercise_id:
        v2 = await db.exercises_v2.find_one(
            {"id": ref.exercise_id},
            {"_id": 0, "id": 1, "exercise_name": 1, "status": 1,
             "primary_image_url": 1, "primary_video_url": 1},
        )
        if not v2:
            return {
                "exercise_id": None,
                "resolution": "unknown_id",
                "raw_id": ref.exercise_id,
                "raw_name": ref.name,
                "warning": {
                    "code": "unknown_exercise_id",
                    "raw_ref_id": ref.exercise_id,
                },
            }
        return {
            "exercise_id": v2["id"],
            "resolution": "direct",
            "matched_name": v2.get("exercise_name"),
            "raw_id": ref.exercise_id,
            "raw_name": ref.name,
        }

    # 2) Name-based fuzzy match via the shared deterministic scorer.
    raw_name = (ref.name or "").strip()
    if not raw_name:
        return {
            "exercise_id": None,
            "resolution": "missing_ref",
            "raw_name": None,
            "warning": {
                "code": "missing_ref",
                "message": "ref.exercise_id and ref.name both empty",
            },
        }

    # Aliases are appended as extra tokens so the token-based scorer
    # (feature_v2_resolver._score_candidate) picks them up naturally.
    search_name = raw_name
    if ref.aliases:
        alias_tokens = " ".join(a for a in ref.aliases if a).strip()
        if alias_tokens:
            search_name = f"{raw_name} {alias_tokens}"

    try:
        from feature_v2_resolver import resolve_exercise_need
    except Exception as e:  # pragma: no cover
        logger.exception("programme_import: resolver unavailable")
        raise HTTPException(500, f"exercise resolver unavailable: {e}")

    result = resolve_exercise_need(
        {"name": search_name},
        pool,
        min_direct_match=_MIN_DIRECT_MATCH,
        min_substitute_match=_MIN_SUBSTITUTE_MATCH,
    )
    kind = result.get("kind")
    lib = result.get("library") or {}
    score = float(result.get("score") or 0.0)

    if kind == "matched":
        return {
            "exercise_id": lib.get("id"),
            "resolution": "matched",
            "matched_name": lib.get("exercise_name"),
            "score": score,
            "raw_name": raw_name,
        }
    if kind == "substituted":
        return {
            "exercise_id": lib.get("id"),
            "resolution": "substituted",
            "matched_name": lib.get("exercise_name"),
            "score": score,
            "raw_name": raw_name,
            "warning": {
                "code": "fuzzy_match",
                "raw_name": raw_name,
                "matched": lib.get("exercise_name"),
                "score": round(score, 1),
            },
        }
    # unresolved — will become a draft library entry at apply time.
    return {
        "exercise_id": None,
        "resolution": "unresolved",
        "raw_name": raw_name,
        "score": score,
        "will_be_drafted": True,
        "warning": {
            "code": "unresolved_exercise",
            "raw_name": raw_name,
            "reason": (
                f"no library match ≥ {_MIN_SUBSTITUTE_MATCH:.0f}; "
                "will be queued as draft at apply time"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Section normalisation — mirrors feature_coach_manual_workouts._norm_exercise
# but returns *previewable* dicts (no HTTPException on empty ref: the resolver
# already recorded the problem via a warning).
# ---------------------------------------------------------------------------

def _flat_item_to_row(
    item: FlatItem,
    match: dict,
    section: str,
    idx: int,
) -> dict:
    """Convert a FlatItem + match result into an on-disk workout row."""
    return {
        "exercise_id": match.get("exercise_id"),
        "name": match.get("matched_name") or match.get("raw_name") or (item.ref.name or ""),
        "sets": item.sets,
        "reps": item.reps,
        "duration_sec": item.duration_sec,
        "load": item.load,
        "rest_sec": item.rest_sec,
        "tempo": item.tempo,
        "rpe": item.rpe,
        "notes": item.notes,
        "cue": item.notes,  # guided-flow narration parity
        "equipment": None,
        "alternative_exercise_id": None,
        "section": section,
        "order": idx,
        "_import_meta": {
            "resolution": match.get("resolution"),
            "score": match.get("score"),
            "raw_name": match.get("raw_name"),
            "raw_id": match.get("raw_id"),
        },
    }


def _single_to_row(
    item: SingleMainExercise,
    match: dict,
    idx: int,
) -> dict:
    """Convert a SingleMainExercise + match result into an on-disk row."""
    return {
        "exercise_id": match.get("exercise_id"),
        "name": match.get("matched_name") or match.get("raw_name") or (item.ref.name or ""),
        "sets": item.sets,
        "reps": item.reps,
        "duration_sec": item.duration_sec,
        "load": item.load,
        "rest_sec": item.rest_sec,
        "tempo": item.tempo,
        "rpe": item.rpe,
        "notes": item.notes,
        "cue": item.notes,
        "equipment": item.equipment,
        "alternative_exercise_id": item.alternative_exercise_id,
        "section": "main",
        "order": idx,
        "_import_meta": {
            "resolution": match.get("resolution"),
            "score": match.get("score"),
            "raw_name": match.get("raw_name"),
            "raw_id": match.get("raw_id"),
        },
    }


def _group_to_rows(
    group: GroupBlock,
    matches: list[dict],
    starting_order: int,
) -> list[dict]:
    """Flatten a group block into per-item rows carrying group_* metadata.

    Row-level ``sets`` becomes the group's ``rounds`` so downstream
    consumers that ignore group_id still see a sensible prescription.
    Row-level ``rest_sec`` defaults to the group's ``rest_between_items_sec``
    if the item doesn't override it.
    """
    gid = f"grp_{new_id()[:8]}"
    rounds = group.rounds if group.rounds and group.rounds > 0 else 1
    default_item_rest = group.rest_between_items_sec
    rows: list[dict] = []
    for pos, (mem, match) in enumerate(zip(group.items, matches)):
        row = {
            "exercise_id": match.get("exercise_id"),
            "name": match.get("matched_name") or match.get("raw_name") or (mem.ref.name or ""),
            "sets": rounds,
            "reps": mem.reps,
            "duration_sec": mem.duration_sec,
            "load": mem.load,
            "rest_sec": mem.rest_sec if mem.rest_sec is not None else default_item_rest,
            "tempo": mem.tempo,
            "rpe": mem.rpe,
            "notes": mem.notes,
            "cue": mem.notes,
            "equipment": None,
            "alternative_exercise_id": None,
            "section": "main",
            "order": starting_order + pos,
            # Group metadata (opt-in for readers that understand groups).
            "group_id": gid,
            "group_type": group.group_type,
            "group_position": pos,
            "group_rounds": rounds,
            "group_rest_between_rounds_sec": group.rest_between_rounds_sec,
            "group_label": group.group_label,
            # Interval / EMOM / tabata prescriptions live on the group.
            "group_work_sec": group.work_sec,
            "group_rest_sec": group.rest_sec,
            "group_cap_min": group.cap_min,
            "_import_meta": {
                "resolution": match.get("resolution"),
                "score": match.get("score"),
                "raw_name": match.get("raw_name"),
                "raw_id": match.get("raw_id"),
            },
        }
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

async def _detect_conflict(client_id: str, date: str, policy: str) -> dict:
    """Return the conflict/action for a single date under the given policy.

    Never mutates state. Return shape:
      { has_conflict: bool, action: 'insert'|'replace'|'skip'|'error',
        existing_workout_id?: str, existing_source?: str,
        error?: {code, message} }
    """
    existing = await db.workouts.find_one(
        {"user_id": client_id, "date": date},
        {"_id": 0, "id": 1, "source": 1, "manual_lock": 1, "completed": 1},
    )
    if not existing:
        return {"has_conflict": False, "action": "insert"}

    src = existing.get("source") or "legacy"
    completed = bool(existing.get("completed"))

    if completed:
        return {
            "has_conflict": True,
            "action": "error",
            "existing_workout_id": existing["id"],
            "existing_source": src,
            "error": {
                "code": "conflict_completed",
                "message": (
                    "Cannot overwrite a completed workout on this date "
                    "(would destroy client history)."
                ),
            },
        }

    if policy == "reject_conflicts":
        return {
            "has_conflict": True,
            "action": "error",
            "existing_workout_id": existing["id"],
            "existing_source": src,
            "error": {
                "code": "conflict_reject",
                "message": (
                    "Target date already has a workout and "
                    "override_policy=reject_conflicts."
                ),
            },
        }

    if policy == "skip_conflicts":
        return {
            "has_conflict": True,
            "action": "skip",
            "existing_workout_id": existing["id"],
            "existing_source": src,
        }

    # replace_conflicts — the default. Manual rows are never silently
    # overwritten; the coach must delete them explicitly.
    if src == MANUAL_SOURCE:
        return {
            "has_conflict": True,
            "action": "error",
            "existing_workout_id": existing["id"],
            "existing_source": src,
            "error": {
                "code": "conflict_manual",
                "message": (
                    "Cannot silently overwrite a manual workout — delete it "
                    "first or set override_policy=skip_conflicts."
                ),
            },
        }
    return {
        "has_conflict": True,
        "action": "replace",
        "existing_workout_id": existing["id"],
        "existing_source": src,
    }


# ---------------------------------------------------------------------------
# Media queue dry-run
# ---------------------------------------------------------------------------

async def _simulate_media_queue(
    client: dict,
    sections: dict[str, list[dict]],
) -> list[dict]:
    """Delegate to the shared scan helper with dry_run=True.

    Falling back to a self-contained scan if the shared helper isn't
    available keeps preview robust even in test isolation.
    """
    try:
        from feature_media_queue import scan_media_queue_for_sections
        return await scan_media_queue_for_sections(
            client, sections, workout_id=None,
            reason="programme_import_dry_run",
            dry_run=True,
        )
    except Exception:
        logger.exception("programme_import: media queue dry-run helper failed; "
                         "falling back to inline scan")
        return await _inline_media_scan(sections)


async def _inline_media_scan(sections: dict[str, list[dict]]) -> list[dict]:
    """Fallback: identical logic to feature_media_queue.scan_media_queue_for_sections
    but 100% self-contained. Kept for defensive robustness."""
    queued: list[dict] = []
    seen: set[str] = set()
    for _section, items in (sections or {}).items():
        for e in (items or []):
            xid = e.get("exercise_id")
            if not xid:
                # Unresolved by matcher → will become draft at apply time.
                queued.append({"exercise_id": None,
                               "name": e.get("name") or "(unresolved)",
                               "reason": "will_draft"})
                continue
            if xid in seen:
                continue
            seen.add(xid)
            v2 = await db.exercises_v2.find_one(
                {"id": xid},
                {"_id": 0, "id": 1, "exercise_name": 1, "status": 1,
                 "primary_image_url": 1, "primary_video_url": 1},
            )
            if not v2:
                queued.append({"exercise_id": xid,
                               "name": e.get("name") or xid,
                               "reason": "missing_library_row"})
                continue
            has_media = bool(v2.get("primary_image_url")) or bool(v2.get("primary_video_url"))
            status = (v2.get("status") or "").lower()
            approved = status in ("approved", "live")
            if not (approved and has_media):
                queued.append({"exercise_id": xid,
                               "name": v2.get("exercise_name") or e.get("name") or xid,
                               "reason": "missing_media"})
    return queued


# ---------------------------------------------------------------------------
# Preview orchestration
# ---------------------------------------------------------------------------

async def _process_workout(
    w: WorkoutEnvelopeItem,
    client: dict,
    pool: list[dict],
    policy: str,
) -> dict:
    """Process a single envelope workout. Returns:
       { preview: dict for API response, transformed: dict for storage }
    """
    warnings: list[dict] = []
    errors: list[dict] = []

    # ------------------------------------------------------------------
    # 1. Match every ExerciseRef (warmup + exercises + cooldown).
    # ------------------------------------------------------------------
    warm_matches: list[dict] = []
    for it in w.warmup:
        warm_matches.append(await _match_ref(it.ref, pool))

    exercises_matches: list[list[dict]] = []
    for blk in w.exercises:
        if isinstance(blk, GroupBlock):
            g_matches = [await _match_ref(mem.ref, pool) for mem in blk.items]
            exercises_matches.append(g_matches)
        else:  # SingleMainExercise
            exercises_matches.append([await _match_ref(blk.ref, pool)])

    cool_matches: list[dict] = []
    for it in w.cooldown:
        cool_matches.append(await _match_ref(it.ref, pool))

    # Collect warnings (and index each exercise so the frontend can show
    # the offending row).
    def _add_warnings(matches: list[dict], section: str, base_idx: int) -> None:
        for i, m in enumerate(matches):
            warn = m.get("warning")
            if not warn:
                continue
            payload = {**warn, "section": section, "exercise_index": base_idx + i}
            # missing_ref / unknown_exercise_id are hard errors, not
            # warnings — no library row can ever back them.
            if warn.get("code") in ("missing_ref", "unknown_exercise_id"):
                errors.append(payload)
            else:
                warnings.append(payload)

    _add_warnings(warm_matches, "warmup", 0)
    flat_pos = 0
    for blk_idx, blk in enumerate(w.exercises):
        blk_matches = exercises_matches[blk_idx]
        _add_warnings(blk_matches, "exercises", flat_pos)
        flat_pos += len(blk_matches)
    _add_warnings(cool_matches, "cooldown", 0)

    # ------------------------------------------------------------------
    # 2. Group flatten → transformed exercise rows.
    # ------------------------------------------------------------------
    warm_rows = [_flat_item_to_row(it, m, "warmup", i)
                 for i, (it, m) in enumerate(zip(w.warmup, warm_matches))]

    main_rows: list[dict] = []
    order = 0
    supersets = circuits = emom_amrap = 0
    for blk, blk_matches in zip(w.exercises, exercises_matches):
        if isinstance(blk, GroupBlock):
            # Validate group_type here so a bad enum doesn't slip past
            # pydantic (we accept it as a plain string on the model to
            # keep forward-compat, but flag anything unknown loudly).
            if blk.group_type not in ALLOWED_GROUP_TYPES:
                errors.append({
                    "code": "invalid_group_type",
                    "section": "exercises",
                    "group_type": blk.group_type,
                    "allowed": sorted(ALLOWED_GROUP_TYPES),
                })
                continue
            rows = _group_to_rows(blk, blk_matches, order)
            main_rows.extend(rows)
            order += len(rows)
            gt = blk.group_type.lower()
            if gt in ("superset", "triset", "giantset"):
                supersets += 1
            elif gt == "circuit":
                circuits += 1
            elif gt in ("emom", "amrap", "tabata"):
                emom_amrap += 1
        else:
            row = _single_to_row(blk, blk_matches[0], order)
            main_rows.append(row)
            order += 1

    cool_rows = [_flat_item_to_row(it, m, "cooldown", i)
                 for i, (it, m) in enumerate(zip(w.cooldown, cool_matches))]

    # ------------------------------------------------------------------
    # 3. Structural validation — every workout must have >=1 main row,
    #    EXCEPT recovery days (rest days, walks, etc.) which are allowed
    #    to have empty exercises[]. The importer still writes a workout
    #    doc so the calendar day is "owned" by the coach.
    # ------------------------------------------------------------------
    if not main_rows and not errors and (w.workout_type or "").lower() != "recovery":
        # (If earlier errors already exist we bubble those up first.)
        errors.append({
            "code": "empty_main",
            "message": "workout has no main exercises after group expansion",
        })

    # ------------------------------------------------------------------
    # 4. workout_type enum validation.
    # ------------------------------------------------------------------
    if w.workout_type not in ALLOWED_WORKOUT_TYPES:
        errors.append({
            "code": "invalid_workout_type",
            "workout_type": w.workout_type,
            "allowed": sorted(ALLOWED_WORKOUT_TYPES),
        })

    # ------------------------------------------------------------------
    # 5. Conflict scan — but check import_ref idempotency FIRST so a
    # re-preview of an already-applied envelope doesn't get tripped up
    # by the manual-lock on rows we ourselves wrote.
    # ------------------------------------------------------------------
    conflict = None
    if w.external_ref:
        existing_import = await db.workouts.find_one(
            {"user_id": client["id"], "import_ref": w.external_ref},
            {"_id": 0, "id": 1, "date": 1},
        )
        if existing_import:
            conflict = {
                "has_conflict": True,
                "action": "already_imported",
                "existing_workout_id": existing_import["id"],
                "existing_source": "programme_import",
            }
    if conflict is None:
        conflict = await _detect_conflict(client["id"], w.date, policy)
    if conflict.get("action") == "error":
        errors.append({**conflict.get("error", {}),
                       "existing_workout_id": conflict.get("existing_workout_id"),
                       "existing_source": conflict.get("existing_source")})

    # ------------------------------------------------------------------
    # 6. Media queue dry-run (only if the workout is otherwise viable —
    #    no point counting media for a workout we can't write).
    # ------------------------------------------------------------------
    media_queued: list[dict] = []
    if not errors:
        media_queued = await _simulate_media_queue(
            client, {"warmup": warm_rows, "main": main_rows, "cooldown": cool_rows},
        )

    # ------------------------------------------------------------------
    # 7. Build the per-workout preview + transformed row.
    # ------------------------------------------------------------------
    status = "ready"
    if errors:
        status = "blocked"
    elif conflict.get("action") == "skip":
        status = "skip"
    elif conflict.get("action") == "already_imported":
        status = "already_imported"

    preview = {
        "date": w.date,
        "title": w.title,
        "workout_type": w.workout_type,
        "status": status,
        "warnings": warnings,
        "errors": errors,
        "conflict": {
            "has_conflict": bool(conflict.get("has_conflict")),
            "action": conflict.get("action"),
            "existing_workout_id": conflict.get("existing_workout_id"),
            "existing_source": conflict.get("existing_source"),
        } if conflict.get("has_conflict") else None,
        "counts": {
            "warmup": len(warm_rows),
            "main": len(main_rows),
            "cooldown": len(cool_rows),
            "supersets": supersets,
            "circuits": circuits,
            "emom_amrap": emom_amrap,
            "media_queue_new_items": len(media_queued),
        },
    }

    transformed = {
        "date": w.date,
        "title": (w.title or "").strip() or "Manual workout",
        "workout_type": w.workout_type,
        "duration_min": w.duration_min,
        "location": w.location,
        "equipment_context": w.equipment_context,
        "rpe": w.rpe,
        "coach_notes": w.coach_notes,
        "warmup": warm_rows,
        "exercises": main_rows,
        "cooldown": cool_rows,
        "external_ref": w.external_ref,
        # Conflict decision cached so apply doesn't re-derive.
        "_conflict_action": conflict.get("action"),
        "_conflict_existing_id": conflict.get("existing_workout_id"),
        "_blocked": bool(errors),
    }

    return {"preview": preview, "transformed": transformed}


def _envelope_hash(env: ProgrammeImportEnvelope) -> str:
    payload = json.dumps(env.model_dump(by_alias=True), sort_keys=True,
                         default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _ensure_previews_indexes() -> None:
    """Create the TTL index on programme_import_previews. Idempotent."""
    try:
        await db.programme_import_previews.create_index(
            [("expires_at", 1)], expireAfterSeconds=0,
            name="expires_at_ttl",
        )
        await db.programme_import_previews.create_index(
            [("coach_id", 1), ("created_at", -1)],
            name="coach_created",
        )
    except Exception:  # pragma: no cover
        logger.exception("programme_import: ensure_indexes failed (non-fatal)")


# ---------------------------------------------------------------------------
# HTTP endpoint — POST /coach/programme-import/preview
# ---------------------------------------------------------------------------

@api.post("/coach/programme-import/preview")
async def coach_programme_import_preview(
    envelope: ProgrammeImportEnvelope,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Dry-run a monthly programme import.

    Writes NOTHING to the workout / exercise / media collections. Returns
    a preview payload (see /app/memory/MONTHLY_PROGRAMME_JSON_IMPORT_DESIGN.md
    §3.2) plus a preview_id that Phase 2's /apply endpoint will accept.
    """
    # --- Envelope-level validation ---
    if envelope.schema_id != SCHEMA_ID:
        raise HTTPException(400,
            f"$schema must be {SCHEMA_ID!r}, got {envelope.schema_id!r}")
    if envelope.override_policy not in ALLOWED_POLICIES:
        raise HTTPException(400,
            f"override_policy must be one of {sorted(ALLOWED_POLICIES)}, "
            f"got {envelope.override_policy!r}")
    if not envelope.workouts:
        raise HTTPException(400, "workouts[] cannot be empty")
    if len(envelope.workouts) > MAX_WORKOUTS:
        raise HTTPException(400,
            f"envelope has {len(envelope.workouts)} workouts; hard cap is {MAX_WORKOUTS}")

    # Payload size guard (rough but effective — pydantic already parsed
    # it once, but re-serialising the model gives us a stable measure).
    payload_bytes = len(json.dumps(envelope.model_dump(by_alias=True), default=str))
    if payload_bytes > MAX_PAYLOAD_BYTES:
        raise HTTPException(413,
            f"envelope payload {payload_bytes} bytes exceeds cap {MAX_PAYLOAD_BYTES}")

    # --- Client resolution ---
    client = await _resolve_client(envelope.meta)

    # --- Month + date validation (envelope-wide) ---
    year, month = _parse_month(envelope.meta.month)
    month_start, month_end = _month_span(year, month)
    seen_dates: set[str] = set()
    duplicate_dates: list[str] = []
    out_of_month: list[str] = []
    for w in envelope.workouts:
        d = _parse_date(w.date)
        if w.date in seen_dates:
            duplicate_dates.append(w.date)
        seen_dates.add(w.date)
        # Allow up to 3 days of slop either side (e.g. a Sun 30th that
        # rolls into the following month's programme).
        slop = timedelta(days=3)
        if not (month_start - slop <= d < month_end + slop):
            out_of_month.append(w.date)
    if duplicate_dates:
        raise HTTPException(400,
            {"code": "duplicate_dates", "dates": sorted(set(duplicate_dates))})
    if out_of_month:
        # Non-fatal — surface as a top-level warning rather than a 400.
        logger.info("programme_import: %d dates outside %s: %s",
                    len(out_of_month), envelope.meta.month, out_of_month[:5])

    # --- Load the approved exercise pool ONCE ---
    try:
        from feature_v2_resolver import get_approved_pool
    except Exception as e:  # pragma: no cover
        logger.exception("programme_import: resolver unavailable at import")
        raise HTTPException(500, f"exercise resolver unavailable: {e}")
    pool = await get_approved_pool()

    # --- Process every workout ---
    per_workout: list[dict] = []
    transformed_workouts: list[dict] = []

    counters = {
        "workouts_ready": 0,
        "workouts_blocked": 0,
        "workouts_skipped": 0,
        "exercises_resolved": 0,
        "exercises_direct_id": 0,
        "exercises_fuzzy_substituted": 0,
        "exercises_new_drafts": 0,
        "media_queue_new_items": 0,
        "date_conflicts": 0,
        "supersets": 0,
        "circuits": 0,
        "emom_amrap": 0,
    }

    for w in envelope.workouts:
        result = await _process_workout(w, client, pool, envelope.override_policy)
        p = result["preview"]
        per_workout.append(p)
        transformed_workouts.append(result["transformed"])

        # Counter aggregation
        if p["status"] == "ready":
            counters["workouts_ready"] += 1
        elif p["status"] == "skip":
            counters["workouts_skipped"] += 1
        elif p["status"] == "already_imported":
            counters["workouts_skipped"] += 1
        else:
            counters["workouts_blocked"] += 1

        # Walk warnings/matches to count resolution kinds
        for row in (result["transformed"]["warmup"]
                    + result["transformed"]["exercises"]
                    + result["transformed"]["cooldown"]):
            meta = row.get("_import_meta") or {}
            res = meta.get("resolution")
            if res in ("matched", "direct"):
                counters["exercises_resolved"] += 1
                if res == "direct":
                    counters["exercises_direct_id"] += 1
            elif res == "substituted":
                counters["exercises_resolved"] += 1
                counters["exercises_fuzzy_substituted"] += 1
            elif res == "unresolved":
                counters["exercises_new_drafts"] += 1

        counters["media_queue_new_items"] += p["counts"]["media_queue_new_items"]
        counters["supersets"] += p["counts"]["supersets"]
        counters["circuits"] += p["counts"]["circuits"]
        counters["emom_amrap"] += p["counts"]["emom_amrap"]
        if p.get("conflict"):
            counters["date_conflicts"] += 1

    blocking_errors = counters["workouts_blocked"]

    # --- Build next-action hints (short human-readable suggestions) ---
    next_actions: list[str] = []
    unresolved_names = sorted({
        (row.get("_import_meta") or {}).get("raw_name")
        for tw in transformed_workouts
        for row in (tw["warmup"] + tw["exercises"] + tw["cooldown"])
        if (row.get("_import_meta") or {}).get("resolution") == "unresolved"
        and (row.get("_import_meta") or {}).get("raw_name")
    })
    if unresolved_names:
        preview_names = ", ".join(list(unresolved_names)[:3])
        more = "" if len(unresolved_names) <= 3 else f" (+{len(unresolved_names) - 3} more)"
        next_actions.append(
            f"Unresolved exercises will be queued as drafts: {preview_names}{more}. "
            "Rename them in the envelope to match library entries if you want "
            "immediate media coverage."
        )
    manual_conflicts = [p for p in per_workout
                        if any(e.get("code") == "conflict_manual" for e in p.get("errors", []))]
    if manual_conflicts:
        dates = ", ".join(p["date"] for p in manual_conflicts[:3])
        next_actions.append(
            f"Manual workouts already exist on {dates} — delete them first "
            "or set override_policy=skip_conflicts."
        )
    completed_conflicts = [p for p in per_workout
                           if any(e.get("code") == "conflict_completed" for e in p.get("errors", []))]
    if completed_conflicts:
        dates = ", ".join(p["date"] for p in completed_conflicts[:3])
        next_actions.append(
            f"Completed workouts exist on {dates} — those dates will always block."
        )
    if out_of_month:
        next_actions.append(
            f"{len(out_of_month)} workout date(s) sit outside {envelope.meta.month}. "
            "Confirm the calendar boundaries are intentional."
        )

    # --- Persist the preview ---
    await _ensure_previews_indexes()

    preview_id = f"pv_{new_id()[:12]}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=PREVIEW_TTL_SECONDS)

    doc = {
        "id": preview_id,
        "coach_id": coach.get("id"),
        "client_id": client["id"],
        "client_email": client.get("email"),
        "envelope_hash": _envelope_hash(envelope),
        "envelope": envelope.model_dump(by_alias=True),
        "transformed_workouts": transformed_workouts,
        "summary": counters,
        "blocking_errors": blocking_errors,
        "override_policy": envelope.override_policy,
        "month": envelope.meta.month,
        "created_at": now,
        "created_at_iso": now_iso(),
        "expires_at": expires_at,
        "expires_at_iso": expires_at.isoformat().replace("+00:00", "Z"),
    }
    try:
        await db.programme_import_previews.insert_one(doc)
    except Exception:
        logger.exception("programme_import: failed to persist preview")
        raise HTTPException(500, "failed to persist preview")

    return {
        "preview_id": preview_id,
        "expires_at": doc["expires_at_iso"],
        "meta": {
            "client_id": client["id"],
            "client_email": client.get("email"),
            "client_display": client.get("full_name") or client.get("email"),
            "month": envelope.meta.month,
            "workout_count": len(envelope.workouts),
            "days_covered": len({w.date for w in envelope.workouts}),
            "override_policy": envelope.override_policy,
            "out_of_month_dates": out_of_month,
        },
        "summary": counters,
        "per_workout": per_workout,
        "blocking_errors": blocking_errors,
        "next_actions": next_actions,
        "schema_id": SCHEMA_ID,
    }


# ---------------------------------------------------------------------------
# HTTP endpoint — POST /coach/programme-import/apply (Phase 2)
# ---------------------------------------------------------------------------

class ApplyBody(BaseModel):
    """Request body for /apply.

    Only requires ``preview_id`` — everything else lives on the preview
    doc so the request stays tiny and the coach can't sneak past the
    preview's validation gate.
    """
    preview_id: str


async def _ensure_apply_indexes() -> None:
    """Partial unique index on (user_id, import_ref) so re-imports are
    idempotent. A workout that has already been written by an import
    can never be inserted a second time — the second attempt is caught
    up-front (idempotency check below) or by this index as a defence
    in depth. Legacy workouts without ``import_ref`` are unaffected
    thanks to the partial filter."""
    try:
        await db.workouts.create_index(
            [("user_id", 1), ("import_ref", 1)],
            unique=True,
            name="workouts_user_import_ref_uniq",
            partialFilterExpression={
                "import_ref": {"$exists": True, "$type": "string"},
            },
        )
    except Exception:  # pragma: no cover — non-fatal (index may already exist)
        logger.exception(
            "programme_import: ensure_apply_indexes failed (non-fatal)"
        )


def _clean_row_for_write(
    row: dict[str, Any], section: str, idx: int,
) -> dict[str, Any]:
    """Strip preview-internal metadata; keep group_* and prescription fields.

    We deliberately don't route through ``feature_coach_manual_workouts._norm_exercise``
    because it strips group metadata (it doesn't know about supersets/circuits).
    Our transformed rows already have the shape ``_norm_exercise`` would
    produce PLUS the six group_* fields — we just clean the diagnostic
    ``_import_meta`` and reset ``section``/``order``.
    """
    out = dict(row)
    out.pop("_import_meta", None)
    out["section"] = section
    out["order"] = idx
    return out


@api.post("/coach/programme-import/apply")
async def coach_programme_import_apply(
    body: ApplyBody,
    coach: dict = Depends(require_role("coach")),
) -> dict:
    """Apply a validated preview to db.workouts.

    Contract:
      * The preview MUST exist, MUST belong to the calling coach, MUST NOT
        be expired, MUST have blocking_errors == 0, and MUST NOT have been
        applied already.
      * For every transformed_workout on the preview:
        - unresolved exercise rows are turned into draft library entries
          via the shared ``create_exercise_request_if_missing`` helper,
        - existing non-manual rows on the target date are deleted when
          the conflict_action is ``replace`` (manual rows always error),
        - the workout is inserted with source=coach_manual + manual_lock,
        - cool-down items are copied into ``exercises[]`` via the shared
          Guided-Flow helper,
        - the shared media-queue scanner is invoked with the real (not
          dry-run) flag,
        - a per-workout audit-log entry is written.
      * A single batch audit-log entry is written at the end.
    """
    # ------------------------------------------------------------------
    # 1. Load and gate the preview.
    # ------------------------------------------------------------------
    preview = await db.programme_import_previews.find_one(
        {"id": body.preview_id}, {"_id": 0},
    )
    if not preview:
        raise HTTPException(404, f"preview {body.preview_id!r} not found")
    if preview.get("coach_id") != coach.get("id"):
        raise HTTPException(403, "preview belongs to a different coach")

    # Expiry check (defensive — TTL job may lag by up to ~60s).
    expires_at = preview.get("expires_at")
    if isinstance(expires_at, datetime):
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp:
            raise HTTPException(410, "preview expired — re-run /preview")

    if preview.get("blocking_errors", 0) > 0:
        raise HTTPException(
            400,
            {
                "code": "blocking_errors_present",
                "message": (
                    f"preview has {preview['blocking_errors']} blocking error(s); "
                    "fix the envelope and re-preview."
                ),
                "blocking_errors": preview["blocking_errors"],
            },
        )
    if preview.get("applied_at"):
        raise HTTPException(
            409,
            {
                "code": "preview_already_applied",
                "message": "this preview has already been applied",
                "applied_at": preview["applied_at"],
                "applied_workout_ids": preview.get("applied_workout_ids") or [],
            },
        )

    # ------------------------------------------------------------------
    # 2. Reload client (in case the record changed since preview).
    # ------------------------------------------------------------------
    client = await db.users.find_one(
        {"id": preview["client_id"]}, {"_id": 0, "password_hash": 0},
    )
    if not client:
        raise HTTPException(404, "client no longer exists")

    # ------------------------------------------------------------------
    # 3. Ensure indexes + import shared helpers.
    # ------------------------------------------------------------------
    await _ensure_apply_indexes()

    try:
        from feature_v2_resolver import create_exercise_request_if_missing
        from feature_coach_manual_workouts import (
            _enrich_for_guided, _merge_cooldown_into_exercises,
        )
        from feature_media_queue import scan_media_queue_for_sections
    except Exception as e:  # pragma: no cover
        logger.exception("programme_import_apply: shared helpers unavailable")
        raise HTTPException(500, f"shared helpers unavailable: {e}")

    # Try to grab _log_change directly (avoids `import server` cycles at
    # module top). Falls through to a no-op logger if unavailable.
    try:
        from server import _log_change  # type: ignore
    except Exception:  # pragma: no cover
        _log_change = None  # type: ignore

    now_str = now_iso()
    coach_id = coach.get("id")

    results: list[dict[str, Any]] = []
    counters: dict[str, int] = {
        "inserted": 0,
        "replaced": 0,
        "skipped": 0,
        "already_imported": 0,
        "failed": 0,
        "drafts_created": 0,
        "media_queue_added": 0,
    }
    inserted_ids: list[str] = []

    envelope_meta = (preview.get("envelope") or {}).get("meta") or {}
    import_source_label = (
        envelope_meta.get("generated_by") or "programme_import"
    )

    # ------------------------------------------------------------------
    # 4. Walk every transformed workout.
    # ------------------------------------------------------------------
    for tw in preview.get("transformed_workouts", []):
        date = tw.get("date")
        title = (tw.get("title") or "Imported workout").strip() or "Imported workout"

        # Defensive: skip anything that was flagged blocked in the preview.
        if tw.get("_blocked"):
            results.append({
                "date": date, "status": "skipped_blocked",
                "reason": "workout had blocking errors in preview",
            })
            counters["skipped"] += 1
            continue

        action = tw.get("_conflict_action") or "insert"
        if action == "skip":
            results.append({
                "date": date, "status": "skipped_conflict",
                "reason": "override_policy=skip_conflicts and date has existing workout",
            })
            counters["skipped"] += 1
            continue
        if action == "already_imported":
            # Preview already spotted the import_ref match — surface the
            # existing workout id in the results and move on.
            existing_id = None
            if ext_ref := tw.get("external_ref"):
                _existing = await db.workouts.find_one(
                    {"user_id": client["id"], "import_ref": ext_ref},
                    {"_id": 0, "id": 1},
                )
                existing_id = (_existing or {}).get("id")
            results.append({
                "date": date, "status": "already_imported",
                "workout_id": existing_id,
                "reason": "workout with this external_ref already exists",
            })
            counters["already_imported"] += 1
            continue
        if action == "error":
            results.append({
                "date": date, "status": "skipped_error",
                "reason": "preview marked this date as an error",
            })
            counters["skipped"] += 1
            continue

        # -------------------------------------------------------------
        # 4a. Idempotency check — same client + external_ref already
        # written? Skip silently. This makes re-runs safe.
        # -------------------------------------------------------------
        ext_ref = tw.get("external_ref")
        if ext_ref:
            already = await db.workouts.find_one(
                {"user_id": client["id"], "import_ref": ext_ref},
                {"_id": 0, "id": 1},
            )
            if already:
                results.append({
                    "date": date, "status": "already_imported",
                    "workout_id": already["id"],
                    "reason": f"workout with external_ref={ext_ref!r} already exists",
                })
                counters["already_imported"] += 1
                continue

        # -------------------------------------------------------------
        # 4b. Draft-create any unresolved rows so every write row has an
        # exercise_id. `create_exercise_request_if_missing` dedupes by
        # normalised name so the same "Cluster deadlift" across 5 days
        # only ever produces 1 draft.
        # -------------------------------------------------------------
        drafts_created_here = 0

        async def _resolve_row(row: dict[str, Any]) -> Optional[dict[str, Any]]:
            nonlocal drafts_created_here
            if row.get("exercise_id"):
                return row
            raw_name = (
                (row.get("_import_meta") or {}).get("raw_name")
                or row.get("name")
            )
            if not raw_name:
                # No name at all — cannot draft. Drop the row.
                return None
            try:
                draft_id = await create_exercise_request_if_missing(
                    {"name": raw_name},
                    user=client, programme_id=None, workout_id=None,
                    reason="programme_import_apply",
                )
            except Exception:
                logger.exception(
                    "programme_import_apply: draft create failed for %r", raw_name,
                )
                return None
            if not draft_id:
                return None
            row["exercise_id"] = draft_id
            row["name"] = raw_name
            drafts_created_here += 1
            return row

        raw_warm = tw.get("warmup") or []
        raw_main = tw.get("exercises") or []
        raw_cool = tw.get("cooldown") or []
        warmup_rows: list[dict] = []
        for r in raw_warm:
            out = await _resolve_row(dict(r))
            if out is not None:
                warmup_rows.append(out)
        main_rows: list[dict] = []
        for r in raw_main:
            out = await _resolve_row(dict(r))
            if out is not None:
                main_rows.append(out)
        cooldown_rows: list[dict] = []
        for r in raw_cool:
            out = await _resolve_row(dict(r))
            if out is not None:
                cooldown_rows.append(out)

        # Recovery workouts (rest days) may legitimately have zero main
        # exercises — we still write the workout doc so the coach "owns"
        # that calendar day. Everything else must have at least one row.
        workout_type = (tw.get("workout_type") or "").lower()
        if not main_rows and workout_type != "recovery":
            results.append({
                "date": date, "status": "skipped_empty",
                "reason": "no main exercises left after draft resolution",
            })
            counters["skipped"] += 1
            continue

        # -------------------------------------------------------------
        # 4c. Clean rows (strip preview metadata) — preserves group_*
        # fields intact so supersets / circuits / EMOM / AMRAP persist.
        # -------------------------------------------------------------
        warmup_rows = [_clean_row_for_write(r, "warmup", i)
                       for i, r in enumerate(warmup_rows)]
        main_rows = [_clean_row_for_write(r, "main", i)
                     for i, r in enumerate(main_rows)]
        cooldown_rows = [_clean_row_for_write(r, "cooldown", i)
                         for i, r in enumerate(cooldown_rows)]

        # Guided-Flow enrichment (logging_type, category, movement_pattern).
        try:
            await _enrich_for_guided(warmup_rows)
            await _enrich_for_guided(main_rows)
            await _enrich_for_guided(cooldown_rows)
        except Exception:
            logger.exception(
                "programme_import_apply: _enrich_for_guided failed for %s", date,
            )

        # -------------------------------------------------------------
        # 4d. Conflict handling — replace policy deletes existing non-
        # manual rows on the target date. Manual rows always error
        # (never silently overwritten), even if the preview somehow got
        # a stale read.
        # -------------------------------------------------------------
        replaced_workout_id: Optional[str] = None
        if action == "replace":
            existing = await db.workouts.find_one(
                {"user_id": client["id"], "date": date},
                {"_id": 0, "id": 1, "source": 1, "manual_lock": 1, "completed": 1},
            )
            if existing:
                if existing.get("completed"):
                    results.append({
                        "date": date, "status": "skipped_completed",
                        "reason": "existing workout is completed — cannot overwrite",
                    })
                    counters["skipped"] += 1
                    continue
                if (existing.get("source") == MANUAL_SOURCE
                        or existing.get("manual_lock")):
                    # Defence in depth against a race between preview and apply.
                    results.append({
                        "date": date, "status": "skipped_manual_lock",
                        "reason": (
                            "target date has a manual workout — delete it first "
                            "or set override_policy=skip_conflicts."
                        ),
                    })
                    counters["skipped"] += 1
                    continue
                replaced_workout_id = existing["id"]
                await db.workouts.delete_many(
                    {"user_id": client["id"], "date": date},
                )

        # -------------------------------------------------------------
        # 4e. Merge cool-down into exercises[] for Guided Flow parity
        # with the manual builder.
        # -------------------------------------------------------------
        main_with_cooldown = _merge_cooldown_into_exercises(
            main_rows, cooldown_rows,
        )

        # -------------------------------------------------------------
        # 4f. Build + insert the workout doc.
        # -------------------------------------------------------------
        wid = new_id()
        doc: dict[str, Any] = {
            "id": wid,
            "user_id": client["id"],
            "date": date,
            "title": title,
            "focus": tw.get("workout_type") or "other",
            "workout_type": tw.get("workout_type") or "other",
            "location": tw.get("location"),
            "equipment_context": tw.get("equipment_context"),
            "duration_min": tw.get("duration_min"),
            "rpe": tw.get("rpe"),
            "coach_notes": tw.get("coach_notes"),
            "warmup": warmup_rows,
            "exercises": main_with_cooldown,
            "cooldown": cooldown_rows,
            "alternatives": {},
            # Manual markers — identical to coach_create_manual_workout.
            "source": MANUAL_SOURCE,
            "manual_lock": True,
            "coach_locked": True,
            "coach_locked_by": coach_id,
            "coach_locked_at": now_str,
            "coach_id": coach_id,
            "coach_edited": True,
            "edited_by": coach_id,
            "edited_at": now_str,
            "created_at": now_str,
            "updated_at": now_str,
            "original_date": date,
            # Programme-import stamps.
            "import_source": import_source_label,
            "import_preview_id": preview["id"],
            "import_envelope_hash": preview.get("envelope_hash"),
            "audit": [{
                "action": "programme_import_create",
                "by": coach_id,
                "at": now_str,
                "preview_id": preview["id"],
                "replaced_workout_id": replaced_workout_id,
            }],
        }
        if ext_ref:
            doc["import_ref"] = ext_ref

        try:
            await db.workouts.insert_one(doc)
        except Exception as e:
            logger.exception(
                "programme_import_apply: insert failed for %s", date,
            )
            results.append({
                "date": date, "status": "failed_insert",
                "reason": str(e)[:200],
            })
            counters["failed"] += 1
            continue

        inserted_ids.append(wid)
        if replaced_workout_id:
            counters["replaced"] += 1
        else:
            counters["inserted"] += 1
        counters["drafts_created"] += drafts_created_here

        # -------------------------------------------------------------
        # 4g. Media queue scan (real writes).
        # -------------------------------------------------------------
        media_added: list[dict] = []
        try:
            media_added = await scan_media_queue_for_sections(
                client,
                {
                    "warmup": warmup_rows,
                    "main": main_rows,
                    "cooldown": cooldown_rows,
                },
                workout_id=wid,
                reason="programme_import_apply",
            )
            counters["media_queue_added"] += len(media_added or [])
        except Exception:
            logger.exception(
                "programme_import_apply: media queue scan failed for %s", wid,
            )

        # -------------------------------------------------------------
        # 4h. Per-workout audit entry.
        # -------------------------------------------------------------
        if _log_change:
            try:
                await _log_change(
                    coach_id=coach_id, client_id=client["id"],
                    category="workout", kind="programme_import_workout",
                    title=f"Programme-import workout for {date}",
                    description=(
                        f"{title} · {len(main_rows)} main exercises · "
                        f"from preview {preview['id']}"
                    ),
                    actor="coach",
                    meta={
                        "workout_id": wid,
                        "date": date,
                        "preview_id": preview["id"],
                        "action": "replaced" if replaced_workout_id else "inserted",
                        "replaced_workout_id": replaced_workout_id,
                        "drafts_created": drafts_created_here,
                        "missing_media_count": len(media_added or []),
                        "external_ref": ext_ref,
                    },
                )
            except Exception:
                logger.exception(
                    "programme_import_apply: _log_change (per-workout) failed for %s",
                    wid,
                )

        results.append({
            "date": date,
            "status": "replaced" if replaced_workout_id else "inserted",
            "workout_id": wid,
            "replaced_workout_id": replaced_workout_id,
            "drafts_created": drafts_created_here,
            "media_queue_added": len(media_added or []),
        })

    # ------------------------------------------------------------------
    # 5. Batch audit log — one row per import so the whole month is
    # visible as a single event alongside per-workout entries.
    # ------------------------------------------------------------------
    if _log_change:
        try:
            await _log_change(
                coach_id=coach_id, client_id=client["id"],
                category="workout", kind="programme_import",
                title=(
                    f"Programme import applied · {counters['inserted']} inserted"
                    f", {counters['replaced']} replaced"
                ),
                description=(
                    f"Preview {preview['id']} · month {preview.get('month')} · "
                    f"{len(inserted_ids)} workouts written"
                ),
                actor="coach",
                meta={
                    "preview_id": preview["id"],
                    "month": preview.get("month"),
                    "workout_ids": inserted_ids,
                    "counters": counters,
                    "envelope_hash": preview.get("envelope_hash"),
                    "override_policy": preview.get("override_policy"),
                    "import_source": import_source_label,
                    "per_workout": results,
                },
            )
        except Exception:
            logger.exception(
                "programme_import_apply: batch _log_change failed for preview %s",
                preview["id"],
            )

    # ------------------------------------------------------------------
    # 6. Mark preview applied so it can never be replayed.
    # ------------------------------------------------------------------
    try:
        await db.programme_import_previews.update_one(
            {"id": preview["id"]},
            {"$set": {
                "applied_at": now_str,
                "applied_by": coach_id,
                "applied_workout_ids": inserted_ids,
                "apply_counters": counters,
            }},
        )
    except Exception:
        logger.exception(
            "programme_import_apply: preview stamp failed for %s", preview["id"],
        )

    return {
        "ok": True,
        "preview_id": preview["id"],
        "client_id": client["id"],
        "client_email": client.get("email"),
        "month": preview.get("month"),
        "counters": counters,
        "workout_ids": inserted_ids,
        "results": results,
    }


__all__ = [
    "SCHEMA_ID",
    "MAX_WORKOUTS",
    "MAX_PAYLOAD_BYTES",
    "PREVIEW_TTL_SECONDS",
    "ALLOWED_WORKOUT_TYPES",
    "ALLOWED_GROUP_TYPES",
    "ALLOWED_POLICIES",
    "ProgrammeImportEnvelope",
    "ImportMeta",
    "WorkoutEnvelopeItem",
    "ExerciseRef",
    "FlatItem",
    "SingleMainExercise",
    "GroupMemberItem",
    "GroupBlock",
    "ApplyBody",
    "coach_programme_import_preview",
    "coach_programme_import_apply",
]
