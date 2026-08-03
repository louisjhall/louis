"""
feature_hotel_conversion_repair — Hotel Gym Workout Conversion repair (fix pack).

This module fixes the audit findings against the hotel-gym conversion flow
without rebuilding the workout engine. It reuses:
  * `feature_v2_construction_v2.build_session_spec`   — unchanged
  * `feature_v2_resolver.create_exercise_request_if_missing` (via
    `feature_media_queue.resolve_or_draft_exercise`)  — canonical dedup path
  * `exercises_v2` main library                       — single source of truth
  * `_normalise_name`                                 — dedup normalization
  * Existing `plan_live_v2_implementations` collection — unchanged shape

What we ADD:
  * `resolve_hotel_spec_with_library(spec, *, allow_list, client, workout_date,
      workout_id, workout_kind)`  — post-processor that runs AFTER
      build_session_spec() and BEFORE the implementation row is written.
      Guarantees every exercise carries a real `exercise_id`, is inside the
      equipment allow-list, and is validated against client injuries.
  * `validate_hotel_spec(...)`   — deterministic validation gate. Returns
      an error dict (never raises) so the caller can decide the response.
  * `POST /api/admin/hotel-conversion/backfill`  — one-shot backfill of
      ACTIVE + UPCOMING plan_live_v2_implementations rows missing exercise
      IDs.

Design contracts:
  * Bodyweight is universally available unless the coach explicitly
    disables it via `client.profile.bodyweight_disabled == True`.
  * Equipment is a HARD constraint — LLMs are never consulted here; we
    only search the approved library and fall back to filing a draft.
  * Any newly created draft exercise gets `urgency_bumped_for_workout_date`
    set so the coach media queue can prioritise it (today > tomorrow > 7d).
  * Zero duplicate library rows — dedup is delegated to
    `create_exercise_request_if_missing` (case + punctuation insensitive).
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Optional

from fastapi import Depends, HTTPException

from server import api, db, require_role, logger, now_iso


# Reuse the canonical name normaliser from the resolver so dedup behaviour
# is IDENTICAL across the codebase.
try:
    from feature_v2_resolver import _normalise_name
except Exception:  # pragma: no cover — defensive
    _WORD_RE = re.compile(r"[a-z0-9]+")
    def _normalise_name(s: Optional[str]) -> str:  # type: ignore
        if not s:
            return ""
        return " ".join(_WORD_RE.findall(str(s).lower()))


APPROVED_STATUSES = ("Approved", "Live")

# The construction pool tags live in a smaller space than the exercises_v2
# `equipment_type` list (which is coach-tagged free-form). This map lets us
# check pool-equipment strings against library rows fairly.
_EQUIPMENT_SYNONYMS: dict[str, set[str]] = {
    "dumbbells":    {"dumbbells", "dumbbell", "db"},
    "kettlebell":   {"kettlebell", "kettlebells", "kb"},
    "bench":        {"bench", "adjustable_bench"},
    "barbell":      {"barbell", "bar"},
    "rack":         {"rack", "squat_rack", "power_rack"},
    "cable_stack":  {"cable_stack", "cable_machine", "cable", "lat_pulldown"},
    "smith_machine":{"smith_machine", "smith"},
    "treadmill":    {"treadmill"},
    "bike":         {"bike", "stationary_bike", "indoor_trainer", "spin"},
    "rowing_machine":{"rowing_machine", "rower", "ergometer"},
    "pull_up_bar":  {"pull_up_bar", "pullup_bar", "chin_up_bar"},
    "band":         {"band", "bands", "resistance_bands", "resistance_band"},
    "mat":          {"mat", "yoga_mat", "floor_space"},
    "bodyweight":   {"bodyweight", "no_equipment", "none"},
    "pool":         {"pool", "swimming_pool"},
    "trx":          {"trx", "suspension_trainer"},
    "medicine_ball":{"medicine_ball", "med_ball"},
    "foam_roller":  {"foam_roller", "roller"},
    "leg_press":    {"leg_press"},
}


def _normalise_equipment_token(raw: str) -> str:
    """Lowercase + collapse to canonical token for equipment membership."""
    t = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    for canon, syns in _EQUIPMENT_SYNONYMS.items():
        if t == canon or t in syns:
            return canon
    return t


def _canonical_allow_list(items: list[str], *, bodyweight_disabled: bool = False) -> set[str]:
    """Turn the client-selected chip list into a canonical allow-set. Bodyweight
    is always added unless the coach explicitly disabled it."""
    out: set[str] = {_normalise_equipment_token(x) for x in items or [] if x}
    if not bodyweight_disabled:
        out.add("bodyweight")
    return {t for t in out if t}


def _library_equipment_matches(cand_equip: list[str], allow_list: set[str]) -> bool:
    """OR semantics — for LIBRARY rows (exercises_v2.equipment_type).

    Library rows list implements that CAN be used (e.g. `["dumbbell",
    "kettlebell"]` means "either works"). Compatible if at least ONE tag
    is available, or the list is empty (bodyweight-safe)."""
    if not cand_equip:
        return True
    normalised = [_normalise_equipment_token(t) for t in cand_equip if t]
    normalised = [t for t in normalised if t]
    if not normalised:
        return True
    if "bodyweight" in normalised:
        return True
    return any(t in allow_list for t in normalised)


def _pool_equipment_satisfied(pool_equip: list[str], allow_list: set[str]) -> bool:
    """AND semantics — for CONSTRUCTION-POOL entries (equipment_used).

    Pool entries list what the exercise REQUIRES. Compatible only when
    every tag is in the allow-list (bodyweight is always available)."""
    if not pool_equip:
        return True
    for tag in pool_equip:
        canon = _normalise_equipment_token(tag)
        if canon and canon != "bodyweight" and canon not in allow_list:
            return False
    return True


def _name_conflicts_with_allow_list(name: str, allow_list: set[str]) -> bool:
    """Safety net for exercise names that leak forbidden equipment
    (e.g. 'Barbell Back Squat' when barbell isn't selected). Rejects a
    candidate whose NAME explicitly mentions equipment that isn't in
    the allow-list. Purely defensive — the `equipment_type` OR-check
    can mis-accept a compound movement whose name reveals a required
    implement."""
    n = str(name or "").lower()
    if not n:
        return False
    # Map "obvious" forbidden implements to their name tokens.
    hard_words = {
        "barbell":       ("barbell",),
        "smith_machine": ("smith",),
        "cable_stack":   ("cable",),
        "leg_press":     ("leg press",),
        "rack":          ("rack",),  # standalone; safe because "rack pull" implies barbell
        "kettlebell":    ("kettlebell",),
        "trx":           ("trx",),
        "band":          ("band ", "resistance band"),
        "pool":          ("swim", "pool"),
        "rowing_machine":("rowing machine", "ergometer", "erg row"),
        "treadmill":     ("treadmill",),
        "bike":          ("bike", "cycling"),
        "pull_up_bar":   ("pull-up", "pull up", "chin-up", "chin up"),
        "medicine_ball": ("medicine ball", "med ball"),
    }
    for canon, words in hard_words.items():
        if canon in allow_list:
            continue
        for w in words:
            if w in n:
                return True
    return False


def _injury_conflict(cand: dict, injuries: list[str]) -> bool:
    """Very light-touch injury filter. Rejects a candidate whose notes /
    contraindications explicitly mention a client injury. Purely defensive —
    coach can override on the workout screen."""
    if not injuries:
        return False
    notes = " ".join([
        str(cand.get("client_facing_instructions") or ""),
        str(cand.get("injury_considerations") or ""),
        str(cand.get("coach_notes") or ""),
    ]).lower()
    if not notes:
        return False
    for inj in injuries:
        inj = str(inj or "").strip().lower()
        if not inj:
            continue
        # Only reject when the note explicitly warns about it.
        if inj in notes and any(w in notes for w in
                                 ("avoid", "contraindicat", "not recommended",
                                  "caution", "skip if")):
            return True
    return False


# ---------------------------------------------------------------------------
# Library-first exercise resolution
# ---------------------------------------------------------------------------

async def _find_library_match(
    *, name: str, movement_pattern: Optional[str], allow_list: set[str],
    injuries: list[str],
) -> Optional[dict]:
    """Library-first resolution.

    1. Exact-normalised name match on any APPROVED row → attach id.
    2. Approved rows by movement_pattern whose equipment fits allow_list
       → return the highest-priority candidate.

    Never inflates rows outside APPROVED_STATUSES — we do not want the
    hotel conversion to auto-link to another pending draft (that would
    surface half-finished content to a live client).
    """
    norm = _normalise_name(name)
    if not norm:
        return None
    # Step 1 — exact normalised-name match on approved rows.
    exact_cursor = db.exercises_v2.find(
        {
            "status": {"$in": list(APPROVED_STATUSES)},
            "$or": [
                {"exercise_name": {"$regex": f"^{re.escape(name)}$",
                                    "$options": "i"}},
                {"requested_name_norm": norm},
                {"aliases": {"$in": [name, name.lower()]}},
            ],
        },
        {"_id": 0},
    )
    async for cand in exact_cursor:
        if not _library_equipment_matches(cand.get("equipment_type") or [], allow_list):
            continue
        if _name_conflicts_with_allow_list(cand.get("exercise_name") or "", allow_list):
            continue
        if _injury_conflict(cand, injuries):
            continue
        return cand

    # Step 2 — movement-pattern match. Rank by has-media + request_count.
    if not movement_pattern:
        return None
    mp = str(movement_pattern).strip().lower()
    cursor = db.exercises_v2.find(
        {
            "status": {"$in": list(APPROVED_STATUSES)},
            "movement_pattern": mp,
        },
        {"_id": 0},
    )
    candidates: list[dict] = []
    async for cand in cursor:
        if not _library_equipment_matches(cand.get("equipment_type") or [], allow_list):
            continue
        if _name_conflicts_with_allow_list(cand.get("exercise_name") or "", allow_list):
            continue
        if _injury_conflict(cand, injuries):
            continue
        candidates.append(cand)
    if not candidates:
        return None

    def _rank(c: dict) -> tuple[int, int, str]:
        has_media = int(bool(c.get("primary_image_url") or c.get("primary_video_url")))
        req = int(c.get("request_count") or 0)
        name_ = str(c.get("exercise_name") or "")
        return (-has_media, -req, name_)

    candidates.sort(key=_rank)
    return candidates[0]


def _urgency_for_date(workout_date: Optional[str]) -> tuple[str, int]:
    """Return a `(bucket, days_until)` tuple so a draft record can be
    prioritised on the coach media queue. Buckets:
      * "today"           → 0
      * "tomorrow"        → 1
      * "next_7"          → ≤7
      * "future"          → >7
      * "unknown"         → None
    """
    if not workout_date:
        return ("unknown", 9999)
    try:
        d = _dt.date.fromisoformat(str(workout_date)[:10])
    except Exception:
        return ("unknown", 9999)
    today = _dt.date.today()
    delta = (d - today).days
    if delta <= 0:
        return ("today", 0)
    if delta == 1:
        return ("tomorrow", 1)
    if delta <= 7:
        return ("next_7", delta)
    return ("future", delta)


async def _draft_library_record(
    *, name: str, movement_pattern: Optional[str], allow_list: set[str],
    equipment_used_by_pool: list[str], workout_date: Optional[str],
    workout_id: Optional[str], client: dict,
    reason_suffix: str,
) -> Optional[str]:
    """File a draft library record for an exercise that has no approved
    match. Bumps urgency counters on the created / matched row based on
    workout-date proximity so the coach queue's `used_in_tomorrow_workouts_count`
    ordering surfaces hotel gaps at the top."""
    try:
        from feature_media_queue import resolve_or_draft_exercise
    except Exception:
        logger.exception("hotel_repair: media_queue helper unavailable")
        return None
    # Restrict the equipment tags we persist to those inside the allow-list
    # so the coach doesn't see a bogus "requires barbell" flag on a draft
    # that came out of a dumbbell-only hotel setup.
    persisted_equip = [t for t in equipment_used_by_pool
                       if _normalise_equipment_token(t) in allow_list]
    parent = {
        "movement_pattern": movement_pattern,
        "equipment_type": persisted_equip or ["bodyweight"],
        "tags": ["hotel_conversion"],
        "difficulty_level": None,
    }
    xid = await resolve_or_draft_exercise(
        name,
        user=client,
        parent=parent,
        reason=f"hotel_conversion:{reason_suffix}",
        workout_id=workout_id,
    )
    if not xid:
        return None
    # Urgency bump — reuse the existing demand-queue counters that already
    # drive the coach exercise-library sort. `used_in_tomorrow_workouts_count`
    # >0 pins the draft to the top for tomorrow.
    bucket, _delta = _urgency_for_date(workout_date)
    inc: dict[str, int] = {}
    if bucket == "today" or bucket == "tomorrow":
        inc["used_in_tomorrow_workouts_count"] = 1
        inc["used_in_upcoming_workouts_count"] = 1
    elif bucket == "next_7":
        inc["used_in_upcoming_workouts_count"] = 1
    if inc:
        try:
            await db.exercises_v2.update_one(
                {"id": xid},
                {"$inc": inc,
                 "$set": {"hotel_conversion_urgency": bucket,
                          "hotel_conversion_workout_date": workout_date,
                          "updated_at": now_iso()}},
            )
        except Exception:
            logger.exception("hotel_repair: urgency bump failed for %s", xid)
    return xid


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------

async def resolve_hotel_spec_with_library(
    spec: dict, *,
    allow_list: set[str],
    client: dict,
    workout_date: Optional[str],
    workout_id: Optional[str] = None,
) -> tuple[dict, dict]:
    """Post-process a hotel-adaptation spec so every exercise carries a
    real `exercise_id` and is guaranteed to fit the equipment allow-list.

    Mutates `spec["payload"]["exercises"]` in place. Returns the (same)
    spec plus a summary of what happened::

        {
          "total_exercises": int,
          "matched_library": int,
          "drafts_created": int,
          "dropped_by_equipment": int,
          "dropped_by_injury": int,
          "warnings": [str, ...],
        }

    Never raises — callers decide whether validation errors should
    become an HTTP 400. Use `validate_hotel_spec()` for that.
    """
    payload = spec.get("payload") or {}
    exercises = payload.get("exercises") or []
    injuries = _injuries_from_client(client)
    summary = {
        "total_exercises": len(exercises),
        "matched_library": 0,
        "drafts_created": 0,
        "dropped_by_equipment": 0,
        "dropped_by_injury": 0,
        "warnings": [],
    }
    kept: list[dict] = []
    for ex in exercises:
        name = str(ex.get("name") or "").strip()
        if not name:
            continue
        # Hard equipment gate first — pool entries use AND semantics
        # (exercise requires EVERY listed implement). Also reject entries
        # whose name reveals a forbidden implement.
        pool_equip = list(ex.get("equipment_used") or ex.get("equipment") or [])
        if not _pool_equipment_satisfied(pool_equip, allow_list):
            summary["dropped_by_equipment"] += 1
            summary["warnings"].append(
                f"'{name}' dropped — needs {pool_equip} outside allow-list."
            )
            continue
        if _name_conflicts_with_allow_list(name, allow_list):
            summary["dropped_by_equipment"] += 1
            summary["warnings"].append(
                f"'{name}' dropped — name references equipment outside allow-list."
            )
            continue
        # Movement pattern is stored on the pool slot as `role` or `pattern`
        movement_pattern = (ex.get("pattern") or ex.get("role")
                             or ex.get("movement_pattern"))
        # Library-first lookup
        cand = await _find_library_match(
            name=name, movement_pattern=movement_pattern,
            allow_list=allow_list, injuries=injuries,
        )
        if cand:
            ex["exercise_id"] = cand["id"]
            ex["library_source"] = "approved_match"
            ex["library_status"] = cand.get("status")
            ex["media_ready"] = bool(
                cand.get("primary_image_url") or cand.get("primary_video_url")
            )
            # Narrow the equipment_used down to what the client will
            # ACTUALLY use for this session (intersection of library's OR
            # list with the allow-list). Falls back to bodyweight when the
            # library row is bodyweight-safe.
            lib_eq = [_normalise_equipment_token(t) for t
                       in (cand.get("equipment_type") or []) if t]
            usable = [t for t in lib_eq if t in allow_list]
            if not usable:
                usable = ["bodyweight"]
            ex["equipment_used"] = usable
            summary["matched_library"] += 1
            kept.append(ex)
            continue
        # No approved match → file a draft, attach its id.
        xid = await _draft_library_record(
            name=name, movement_pattern=movement_pattern,
            allow_list=allow_list, equipment_used_by_pool=pool_equip,
            workout_date=workout_date, workout_id=workout_id, client=client,
            reason_suffix=f"{workout_date or 'unknown'}",
        )
        if xid:
            ex["exercise_id"] = xid
            ex["library_source"] = "pending_draft"
            ex["library_status"] = "draft_requested"
            ex["media_ready"] = False
            summary["drafts_created"] += 1
            kept.append(ex)
        else:
            summary["warnings"].append(
                f"'{name}' could not be resolved to a library id."
            )
    payload["exercises"] = kept
    spec["payload"] = payload
    spec.setdefault("adapted_from_original", True)
    spec["equipment_allow_list"] = sorted(allow_list)
    spec["conversion_summary"] = summary
    return spec, summary


def _injuries_from_client(client: dict) -> list[str]:
    profile = client.get("profile") or {}
    raw = profile.get("injuries")
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


# ---------------------------------------------------------------------------
# Deterministic validation
# ---------------------------------------------------------------------------

def validate_hotel_spec(spec: dict, *, allow_list: set[str]) -> dict:
    """Deterministic pre-save validation. Returns ::
        {"ok": bool, "errors": [str, ...]}
    Never raises. Callers should convert !ok into a 400 with the joined
    error message."""
    errors: list[str] = []
    payload = spec.get("payload") or {}
    exs = payload.get("exercises") or []
    if not exs:
        errors.append("Converted workout has no exercises — nothing to do.")
    for i, ex in enumerate(exs):
        if not ex.get("exercise_id"):
            errors.append(f"exercise #{i + 1} '{ex.get('name')}' has no exercise_id.")
        eq = ex.get("equipment_used") or ex.get("equipment") or []
        if not _pool_equipment_satisfied(eq, allow_list):
            errors.append(
                f"exercise #{i + 1} '{ex.get('name')}' needs {eq} "
                f"outside allow-list {sorted(allow_list)}."
            )
        # sets/reps/duration sanity
        s = ex.get("sets")
        r = ex.get("reps")
        d = ex.get("duration_sec")
        if not (s or r or d):
            errors.append(
                f"exercise #{i + 1} '{ex.get('name')}' has no sets/reps/duration prescription."
            )
    return {"ok": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# One-shot backfill for existing active hotel conversions
# ---------------------------------------------------------------------------

@api.post("/admin/hotel-conversion/backfill")
async def hotel_conversion_backfill(
    admin: dict = Depends(require_role("coach")),
):
    """Scan every ACTIVE + UPCOMING `plan_live_v2_implementations` row and
    backfill exercise_id + equipment metadata on any exercise still stored
    as a free-text string.

    Only touches rows where `is_active == True` AND `date >= today` — never
    rewrites completed / historical sessions.
    """
    if not admin.get("is_admin"):
        raise HTTPException(403, "admin only")

    today = _dt.date.today().isoformat()
    cursor = db.plan_live_v2_implementations.find(
        {"is_active": True, "date": {"$gte": today}},
        {"_id": 0},
    )

    rows: list[dict] = []
    async for r in cursor:
        rows.append(r)

    summary = {
        "rows_scanned": len(rows),
        "rows_repaired": 0,
        "exercises_matched_library": 0,
        "drafts_created": 0,
        "warnings": [],
    }

    for row in rows:
        spec = dict(row.get("spec_snapshot") or {})
        exs = ((spec.get("payload") or {}).get("exercises") or [])
        if not exs:
            continue
        needs_fix = any(not e.get("exercise_id") for e in exs)
        if not needs_fix:
            continue
        client = await db.users.find_one({"id": row.get("client_id")}, {"_id": 0}) or {}
        allow_list = set(row.get("equipment") or [])
        # Match the runtime allow-list rules: normalise + always include bodyweight
        allow_list = _canonical_allow_list(
            list(allow_list),
            bodyweight_disabled=bool(
                (client.get("profile") or {}).get("bodyweight_disabled")
            ),
        )
        _spec_out, sub_summary = await resolve_hotel_spec_with_library(
            spec, allow_list=allow_list, client=client,
            workout_date=row.get("date"), workout_id=row.get("id"),
        )
        # Persist back
        try:
            await db.plan_live_v2_implementations.update_one(
                {"id": row["id"]},
                {"$set": {
                    "spec_snapshot": spec,
                    "repaired_at": now_iso(),
                    "repair_summary": sub_summary,
                }},
            )
            summary["rows_repaired"] += 1
            summary["exercises_matched_library"] += sub_summary["matched_library"]
            summary["drafts_created"] += sub_summary["drafts_created"]
            for w in (sub_summary.get("warnings") or []):
                summary["warnings"].append(f"{row.get('id')}: {w}")
        except Exception:
            logger.exception("hotel_conversion_backfill: persist failed for %s", row.get("id"))

    return {"ok": True, "summary": summary}


__all__ = [
    "resolve_hotel_spec_with_library",
    "validate_hotel_spec",
    "hotel_conversion_backfill",
    "_canonical_allow_list",
]
