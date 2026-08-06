#!/usr/bin/env python3
"""
Phase C1 — Exercise Library Controlled Reset — DRY-RUN ONLY
============================================================

Reads exercises_v2, exercise_content_images, workouts and programmes for the
four active clients, produces:

  1. A timestamped backup at /app/backend/backups/phase_c_<ts>/
  2. A markdown report at /app/backend/backups/phase_c_<ts>/REPORT.md
  3. A machine-readable JSON summary at .../summary.json

Retention rules (Option A — retain approved core + rebuild the rest):
  RETAIN:
    - status in {Approved, Live}
    - OR approval_status == "approved"
    - OR referenced by an active workout (id OR normalised name)
    - OR referenced by an active programme's exercise list (any depth)
  DELETE (proposed):
    - Everything else — draft_requested, coach_review_needed, needs_review,
      in_progress, needs_media, rejected, merged, failed, archived, or any
      unreferenced duplicate.

NO WRITES. NO DELETIONS. Read-only. Safe to run any number of times.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import pathlib
import re
import sys
from collections import Counter, defaultdict
from typing import Any

# --- Set up sys.path so we can import from /app/backend --------------------
BACKEND = "/app/backend"
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND, ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

# --- Text normalisation — mirrors feature_v2_resolver.py -------------------
_WORD_RE = re.compile(r"[a-z0-9]+")
_PLURAL_KEEP = {
    "abs", "biceps", "triceps", "lats", "quads", "delts", "glutes",
    "kettlebells", "dumbbells", "aerobics", "gymnastics",
}

def _singularise_token(t: str) -> str:
    if not t or t in _PLURAL_KEEP or len(t) <= 2:
        return t
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("sses"):
        return t[:-2]
    if t.endswith(("ches", "shes", "xes")) and len(t) > 5:
        return t[:-2]
    if t.endswith("oes") and len(t) > 4:
        return t[:-2]
    if t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t

def _canon(s: Any) -> str:
    return " ".join(_singularise_token(t) for t in _WORD_RE.findall(str(s or "").lower()))

def _now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
async def main() -> None:
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
    out_dir = pathlib.Path(f"/app/backend/backups/phase_c_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[phase_c1] Output → {out_dir}")

    # ---------------- BACKUPS (read-only) ---------------------------------
    print("[phase_c1] Backing up exercises_v2 …")
    exercises = await db.exercises_v2.find({}, {"_id": 0}).to_list(length=None)
    (out_dir / "exercises_v2.json").write_text(json.dumps(exercises, default=str))

    print("[phase_c1] Backing up exercise_content_images …")
    images = await db.exercise_content_images.find({}, {"_id": 0}).to_list(length=None)
    (out_dir / "exercise_content_images.json").write_text(json.dumps(images, default=str))

    # ---------------- ACTIVE CLIENTS --------------------------------------
    # "Active" = users with role=client that have at least one workout or
    # programme in the DB. This intentionally does NOT hard-code the four —
    # any client with real data is considered protected.
    print("[phase_c1] Identifying active clients …")
    all_clients = await db.users.find(
        {"role": "client"}, {"_id": 0, "id": 1, "email": 1, "name": 1}
    ).to_list(length=None)

    active_clients: list[dict] = []
    for c in all_clients:
        uid = c.get("id")
        if not uid:
            continue
        has_workout = await db.workouts.count_documents({"user_id": uid}) > 0
        has_programme = await db.programmes.count_documents({"user_id": uid}) > 0 \
            if "programmes" in await db.list_collection_names() else False
        if has_workout or has_programme:
            active_clients.append(c)

    (out_dir / "active_clients.json").write_text(
        json.dumps(active_clients, default=str, indent=2)
    )
    print(f"[phase_c1]   {len(active_clients)} active client(s) with real data")

    active_client_ids = {c["id"] for c in active_clients}

    # ---------------- COLLECT REFERENCES FROM ACTIVE DATA -----------------
    # Active workout = ANY workout owned by an active client (future or past).
    # We include past because approved media should not be deleted just
    # because the workout completed.
    print("[phase_c1] Scanning active workouts for exercise references …")
    workout_query = {"user_id": {"$in": list(active_client_ids)}}
    workout_count = await db.workouts.count_documents(workout_query)

    ref_ids: set[str] = set()
    ref_norm_names: set[str] = set()
    ref_canon_names: set[str] = set()
    workout_ref_map: dict[str, set[str]] = defaultdict(set)  # canon → workout_ids
    workouts_scanned = 0

    async for w in db.workouts.find(workout_query, {
        "_id": 0, "id": 1, "user_id": 1, "date": 1,
        "exercises": 1, "warmup": 1, "cooldown": 1,
    }):
        workouts_scanned += 1
        items: list[dict] = []
        for k in ("exercises", "warmup", "cooldown"):
            v = w.get(k)
            if isinstance(v, list):
                items.extend([x for x in v if isinstance(x, dict)])
        for it in items:
            xid = it.get("exercise_id") or it.get("id")
            if xid:
                ref_ids.add(str(xid))
            nm = it.get("name") or it.get("exercise_name")
            if nm:
                canon = _canon(nm)
                if canon:
                    ref_canon_names.add(canon)
                    ref_norm_names.add(canon)  # canon already lowercased + singularised
                    workout_ref_map[canon].add(w.get("id") or "")

    print(f"[phase_c1]   scanned {workouts_scanned}/{workout_count} workouts")

    # Active programmes — same logic
    print("[phase_c1] Scanning active programmes for exercise references …")
    prog_refs_ids: set[str] = set()
    prog_refs_canon: set[str] = set()
    programmes_scanned = 0
    if "programmes" in await db.list_collection_names():
        async for p in db.programmes.find(
            {"user_id": {"$in": list(active_client_ids)}}, {"_id": 0}
        ):
            programmes_scanned += 1
            # programmes can be shaped many ways; walk all nested lists
            def walk(node: Any) -> None:
                if isinstance(node, dict):
                    xid = node.get("exercise_id")
                    if xid:
                        prog_refs_ids.add(str(xid))
                        ref_ids.add(str(xid))
                    nm = node.get("name") or node.get("exercise_name")
                    if nm and isinstance(nm, str):
                        c = _canon(nm)
                        if c:
                            prog_refs_canon.add(c)
                            ref_canon_names.add(c)
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
            walk(p)
    print(f"[phase_c1]   scanned {programmes_scanned} programmes")

    # ---------------- CATEGORISE exercises_v2 -----------------------------
    print("[phase_c1] Categorising exercises_v2 rows …")

    def is_approved(ex: dict) -> bool:
        st = str(ex.get("status") or "")
        aps = str(ex.get("approval_status") or "").lower()
        return st in ("Approved", "Live") or aps == "approved"

    def is_referenced(ex: dict) -> tuple[bool, str]:
        """Return (referenced, reason) so we know why a row is being kept."""
        eid = str(ex.get("id") or "")
        if eid and eid in ref_ids:
            return True, "id_ref"
        canon = _canon(ex.get("exercise_name"))
        if canon and canon in ref_canon_names:
            return True, "name_ref"
        # Fallback: many drafts store the original coach name under
        # `requested_name`. Check that too.
        rq = _canon(ex.get("requested_name") or ex.get("requested_name_norm"))
        if rq and rq in ref_canon_names:
            return True, "requested_name_ref"
        return False, ""

    retain_approved: list[dict] = []
    retain_referenced_only: list[dict] = []          # kept purely because a workout points at it
    delete_by_bucket: dict[str, list[dict]] = defaultdict(list)
    status_counter = Counter()
    approval_counter = Counter()

    # Duplicate detection within DELETE pile: canonical name → rows
    canon_groups: dict[str, list[dict]] = defaultdict(list)

    for ex in exercises:
        status_counter[str(ex.get("status") or "(none)")] += 1
        approval_counter[str(ex.get("approval_status") or "(none)")] += 1

        approved = is_approved(ex)
        referenced, ref_reason = is_referenced(ex)

        if approved:
            retain_approved.append(ex)
            continue
        if referenced:
            ex["_retain_reason"] = ref_reason
            retain_referenced_only.append(ex)
            continue

        # → DELETE
        st = str(ex.get("status") or "").lower()
        # bucket for reporting granularity
        if st in ("draft_requested",):
            bucket = "unapproved_generated_drafts"
        elif st in ("coach_review_needed", "needs_review"):
            bucket = "abandoned_review_items"
        elif st in ("failed",) or (ex.get("generation_status") == "failed"):
            bucket = "failed_or_obsolete_generation"
        elif st in ("rejected", "merged", "archived"):
            bucket = "rejected_or_merged_remnants"
        elif st in ("in_progress", "needs_media"):
            bucket = "abandoned_review_items"
        else:
            bucket = "other_unreferenced_rows"

        delete_by_bucket[bucket].append(ex)
        canon_groups[_canon(ex.get("exercise_name"))].append(ex)

    # Count unreferenced duplicates within the delete pile
    duplicate_rows_within_delete = 0
    for canon_key, rows in canon_groups.items():
        if canon_key and len(rows) > 1:
            duplicate_rows_within_delete += len(rows) - 1

    # ---------------- ORPHAN SAFETY CHECK ---------------------------------
    # If a workout points at an id/name that maps to NO exercises_v2 row at
    # all, that is an orphan reference — it will need rebuilding via
    # create_exercise_request_if_missing after C2. Report them explicitly.
    known_ids = {str(ex.get("id") or "") for ex in exercises}
    known_canons = {_canon(ex.get("exercise_name")) for ex in exercises}
    orphan_id_refs = ref_ids - known_ids
    orphan_name_refs = ref_canon_names - known_canons

    # Also: how many DELETE-pile rows would leave a dangling reference IF
    # they were deleted?  Answer: zero by construction — anything referenced
    # was moved into retain_referenced_only. Verify anyway for the report.
    unsafe_deletes = []
    for ex in [x for bucket in delete_by_bucket.values() for x in bucket]:
        eid = str(ex.get("id") or "")
        canon = _canon(ex.get("exercise_name"))
        if (eid and eid in ref_ids) or (canon and canon in ref_canon_names):
            unsafe_deletes.append({"id": eid, "name": ex.get("exercise_name")})

    # ---------------- REQUIRED-NAMES REBUILD PLAN -------------------------
    # Unique canonical names required by active workouts+programmes
    required_canons = ref_canon_names
    covered_by_retain = set()
    for ex in retain_approved + retain_referenced_only:
        c = _canon(ex.get("exercise_name"))
        if c:
            covered_by_retain.add(c)
    rebuild_needed = required_canons - covered_by_retain

    # ---------------- OBSOLETE MEDIA-JOB ROWS -----------------------------
    # There is no separate media_jobs collection; media state lives on
    # exercises_v2 fields and in exercise_content_images. Report both:
    #   - exercise_content_images rows tied to would-be-deleted exercise ids
    #   - "job-like" flags on delete-pile rows
    delete_ids = {str(ex.get("id") or "") for bucket in delete_by_bucket.values()
                  for ex in bucket if ex.get("id")}
    orphan_images = [img for img in images
                     if str(img.get("exercise_id") or "") in delete_ids]

    # ---------------- WRITE REPORT ---------------------------------------
    summary = {
        "generated_at": _now(),
        "db_name": DB_NAME,
        "backup_dir": str(out_dir),
        "totals": {
            "exercises_v2_total": len(exercises),
            "retain_total": len(retain_approved) + len(retain_referenced_only),
            "retain_approved_core": len(retain_approved),
            "retain_referenced_only": len(retain_referenced_only),
            "delete_total": sum(len(v) for v in delete_by_bucket.values()),
        },
        "delete_breakdown": {k: len(v) for k, v in delete_by_bucket.items()},
        "duplicate_rows_within_delete_pile": duplicate_rows_within_delete,
        "active_clients": [
            {"id": c["id"], "email": c.get("email"), "name": c.get("name")}
            for c in active_clients
        ],
        "workouts_scanned": workouts_scanned,
        "programmes_scanned": programmes_scanned,
        "active_workout_exercise_refs": {
            "unique_ids": len(ref_ids),
            "unique_canonical_names": len(ref_canon_names),
        },
        "unique_required_exercises_across_clients": len(required_canons),
        "rebuild_needed_after_reset": len(rebuild_needed),
        "orphan_refs": {
            "workout_ids_pointing_to_missing_rows": len(orphan_id_refs),
            "workout_names_with_no_matching_row": len(orphan_name_refs),
        },
        "unsafe_deletes_detected": len(unsafe_deletes),
        "obsolete_exercise_content_images": len(orphan_images),
        "status_counts": dict(status_counter),
        "approval_status_counts": dict(approval_counter),
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    # Also dump the id/name lists so C2 can consume them without re-scanning
    (out_dir / "delete_ids.json").write_text(json.dumps(
        [ex.get("id") for bucket in delete_by_bucket.values() for ex in bucket
         if ex.get("id")], indent=2))
    (out_dir / "retain_ids.json").write_text(json.dumps(
        [ex.get("id") for ex in retain_approved + retain_referenced_only
         if ex.get("id")], indent=2))
    (out_dir / "rebuild_names.json").write_text(json.dumps(sorted(rebuild_needed), indent=2))
    (out_dir / "orphan_name_refs.json").write_text(json.dumps(sorted(orphan_name_refs), indent=2))

    # Human-readable Markdown
    md = []
    md.append(f"# Phase C1 — Exercise Library Reset — DRY-RUN Report")
    md.append(f"_Generated: {summary['generated_at']}_")
    md.append(f"_Backup dir: `{out_dir}`_\n")
    md.append("## ⚖️ Retention Rule (Option A)")
    md.append("**RETAIN** if any of:")
    md.append("- `status ∈ {Approved, Live}` OR `approval_status == \"approved\"`  → *approved core*")
    md.append("- Referenced by an active client's workout (by id or normalised name)")
    md.append("- Referenced by an active client's programme")
    md.append("\n**PROPOSED FOR DELETION** = everything else.\n")

    md.append("## 📊 Headline Numbers")
    md.append(f"- **Total rows in `exercises_v2`**: {summary['totals']['exercises_v2_total']}")
    md.append(f"- **Total to RETAIN**: {summary['totals']['retain_total']}")
    md.append(f"  - Approved / Live core: {summary['totals']['retain_approved_core']}")
    md.append(f"  - Retained ONLY because referenced by active data: {summary['totals']['retain_referenced_only']}")
    md.append(f"- **Total PROPOSED FOR DELETION**: {summary['totals']['delete_total']}")
    md.append("")
    md.append("### Delete pile — sub-buckets")
    for k, n in summary["delete_breakdown"].items():
        md.append(f"- {k}: {n}")
    md.append(f"- (unreferenced duplicate rows folded into the above): {summary['duplicate_rows_within_delete_pile']}")

    md.append("\n## 👥 Active Clients")
    for c in active_clients:
        md.append(f"- {c.get('name') or '(no name)'} — `{c.get('email')}` — id `{c['id']}`")
    md.append(f"\nWorkouts scanned: **{workouts_scanned}**  |  Programmes scanned: **{programmes_scanned}**")

    md.append("\n## 🔗 Active Workout / Programme Exercise References")
    md.append(f"- Unique exercise ids referenced by active data: **{len(ref_ids)}**")
    md.append(f"- Unique canonical exercise names referenced: **{len(ref_canon_names)}**")
    md.append(f"- Unique exercises actually required across the {len(active_clients)} active client(s): **{len(required_canons)}**")

    md.append("\n## 🛠️ Rebuild Plan")
    md.append(f"- Names already covered by retained rows: **{len(covered_by_retain & required_canons)}**")
    md.append(f"- Names to be rebuilt via `create_exercise_request_if_missing` (Needs Review / Needs Media): **{len(rebuild_needed)}**")
    md.append("- All rebuilt entries go through **Phase B fuzzy-dedup**, so re-adding the same movement won't create a second row.")

    md.append("\n## 🛡️ Safety Checks")
    md.append(f"- Workout refs pointing to a `exercises_v2` id that **doesn't exist**: **{len(orphan_id_refs)}** (pre-existing orphans — will be rebuilt during rescan)")
    md.append(f"- Workout names that don't match ANY current row (case-insensitive, singularised): **{len(orphan_name_refs)}** (pre-existing orphans — will be rebuilt)")
    md.append(f"- **Deletes that would break a live reference**: **{len(unsafe_deletes)}**  ← must be 0")
    if unsafe_deletes:
        md.append("  ⚠️ Unsafe deletes detected — first 10:")
        for u in unsafe_deletes[:10]:
            md.append(f"  - `{u['id']}` — {u['name']!r}")

    md.append("\n## 🖼️ Obsolete Media Metadata")
    md.append(f"- `exercise_content_images` rows tied to to-be-deleted `exercises_v2` ids: **{len(orphan_images)}**")
    md.append("- These metadata rows would be removed in C2. **R2 objects themselves stay intact** (per scope).")

    md.append("\n## 🔄 Auto-Repopulation Surfaces (would recreate drafts unless guarded)")
    md.append("The following code paths automatically create new rows in `exercises_v2` by calling `create_exercise_request_if_missing`:")
    md.append("1. `GET /api/exercise-requests/grouped` → auto-runs `backfill_missing_exercise_requests_from_workouts` on every coach visit (14d back / 21d fwd, cap 100).")
    md.append("2. `POST /api/exercise-requests/scan-workouts` → manual coach button (60d/60d, cap 500).")
    md.append("3. `feature_v2_resolver.py` V2 generation path — writes drafts as workouts are constructed.")
    md.append("4. `feature_programme_import.py` — Monthly JSON Import files a draft for any unknown name.")
    md.append("5. `feature_coach_manual_workouts.py` — manual-builder saves trigger the resolver.")
    md.append("6. `feature_flight_support_media.py` / mobility flow — writes drafts for pre/post-flight moves.")
    md.append("7. `feature_traffic_light.py` → `backfill_exercise_ids`.")
    md.append("8. `feature_auto_media_gen.py` — mutates media state on `exercises_v2` and `exercise_content_images`.")
    md.append("9. `server.py` startup migrations (idempotent — do not recreate deleted rows unless flagged).")

    md.append("\n### Proposed Guard (for C2)")
    md.append("- Introduce env flag `EXERCISE_BACKFILL_DISABLED=true` guarding **all** call sites above (single early return + log).")
    md.append("- Toggle to `false` only during the **controlled rescan** step of C2, with the window narrowed to future workouts only.")
    md.append("- Confirms via unit assertion that historical workouts (>0 days in the past) do not create drafts while the flag is set.")

    md.append("\n## 📜 Exact C2 Deletion Criteria (reference for later approval)")
    md.append("```")
    md.append("DELETE FROM exercises_v2 WHERE")
    md.append("    NOT (status IN ('Approved','Live') OR approval_status = 'approved')")
    md.append("  AND id NOT IN <active_workout+programme id refs>")
    md.append("  AND canonical(exercise_name) NOT IN <active canonical name refs>")
    md.append("  AND canonical(requested_name)  NOT IN <active canonical name refs>")
    md.append("```")
    md.append("Companion deletion:")
    md.append("```")
    md.append("DELETE FROM exercise_content_images WHERE exercise_id IN <delete_ids>")
    md.append("```")
    md.append("Companion action:")
    md.append("- After deletion, run `backfill_missing_exercise_requests_from_workouts` once with a **future-only** window (`days_back=0`, `days_forward=60`) for the 4 active clients only — everything else stays quiet.")

    md.append("\n## 📁 Artefacts Written (no DB writes performed)")
    md.append(f"- `{out_dir}/exercises_v2.json` — full collection backup")
    md.append(f"- `{out_dir}/exercise_content_images.json` — full media metadata backup")
    md.append(f"- `{out_dir}/active_clients.json`")
    md.append(f"- `{out_dir}/delete_ids.json` — ids that C2 would delete")
    md.append(f"- `{out_dir}/retain_ids.json` — ids that C2 would keep")
    md.append(f"- `{out_dir}/rebuild_names.json` — canonical names to rebuild after reset")
    md.append(f"- `{out_dir}/orphan_name_refs.json` — pre-existing orphaned workout refs")
    md.append(f"- `{out_dir}/summary.json` — machine-readable")

    (out_dir / "REPORT.md").write_text("\n".join(md))

    # Also print a short summary to stdout
    print("\n" + "=" * 72)
    print("PHASE C1 DRY-RUN — SHORT SUMMARY")
    print("=" * 72)
    for k, v in summary["totals"].items():
        print(f"  {k:35s}: {v}")
    print(f"  active_clients                       : {len(active_clients)}")
    print(f"  workouts_scanned                     : {workouts_scanned}")
    print(f"  programmes_scanned                   : {programmes_scanned}")
    print(f"  unique_required_exercises            : {len(required_canons)}")
    print(f"  rebuild_needed_after_reset           : {len(rebuild_needed)}")
    print(f"  unsafe_deletes_detected              : {len(unsafe_deletes)}")
    print(f"  obsolete_exercise_content_images     : {len(orphan_images)}")
    print("=" * 72)
    print(f"Report: {out_dir}/REPORT.md")
    print(f"Backup dir: {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
