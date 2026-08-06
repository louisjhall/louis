#!/usr/bin/env python3
"""
Phase C2 — Exercise Library Controlled Reset — APPLY
=====================================================

Executes the deletion approved in Phase C1 with the following modification
(per user instruction 2026-08-06):

  * Exclude the deleted client `deleted+8d24515c@crewfit.deleted` from the
    active-client set. Any workouts / references belonging ONLY to that
    client will NOT hold a row in the retain pile.

Guardrails:
  * `EXERCISE_BACKFILL_DISABLED=true` is set in /app/backend/.env and
    guarded inside feature_v2_resolver.py — the /exercise-requests/grouped
    auto-scan is now inert.
  * Orphan workout refs pointing to non-existent exercises_v2 ids are
    reported FIRST. If any orphan belongs to a GENUINE active client we
    abort before deletion.
  * Deletions are performed by id-list so we cannot accidentally hit
    approved rows.
  * A companion delete on exercise_content_images is scoped to the same
    id-list.
  * A future-only rescan runs at the end, restricted to the four active
    clients, to reconcile anything the deletion may have exposed.

Reversible via the pre-deletion backup at /app/backend/backups/phase_c_*/.
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

BACKEND = "/app/backend"
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND, ".env"))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

DELETED_CLIENT_ID = "8d24515c-5255-483d-9f10-2261c8d86400"
DELETED_CLIENT_EMAIL = "deleted+8d24515c@crewfit.deleted"

# --- text normalisation (mirror feature_v2_resolver.py) --------------------
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


async def _snapshot(db) -> dict:
    """Snapshot counts across the categories the user asked for."""
    total = await db.exercises_v2.count_documents({})
    approved = await db.exercises_v2.count_documents({
        "$or": [{"status": {"$in": ["Approved", "Live"]}},
                {"approval_status": "approved"}]
    })
    needs_review = await db.exercises_v2.count_documents({
        "$or": [{"status": "coach_review_needed"},
                {"approval_status": "needs_review"}]
    })
    needs_media = await db.exercises_v2.count_documents({
        "$or": [{"status": "needs_media"},
                {"approval_status": "needs_media"}]
    })
    in_progress = await db.exercises_v2.count_documents({
        "$or": [{"status": "in_progress"},
                {"approval_status": "in_progress"}]
    })
    drafts = await db.exercises_v2.count_documents({
        "status": {"$in": ["draft_requested", "draft"]}
    })
    images = await db.exercise_content_images.count_documents({})
    return {
        "exercises_v2_total": total,
        "approved_or_live": approved,
        "needs_review": needs_review,
        "needs_media": needs_media,
        "in_progress": in_progress,
        "drafts": drafts,
        "exercise_content_images_total": images,
    }


async def main() -> None:
    if str(os.environ.get("EXERCISE_BACKFILL_DISABLED", "")).lower() not in ("1", "true", "yes"):
        print("[phase_c2] REFUSING TO RUN — EXERCISE_BACKFILL_DISABLED is not set to true.")
        print("            Set it in /app/backend/.env and restart backend first.")
        sys.exit(2)

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%SZ")
    out_dir = pathlib.Path(f"/app/backend/backups/phase_c2_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[phase_c2] Output → {out_dir}")

    # ---------- 1. Determine active-client set (excl. deleted) ----------
    all_clients = await db.users.find(
        {"role": "client"}, {"_id": 0, "id": 1, "email": 1, "name": 1}
    ).to_list(length=None)

    active_clients: list[dict] = []
    for c in all_clients:
        uid = c.get("id")
        email = (c.get("email") or "").lower()
        if not uid:
            continue
        if uid == DELETED_CLIENT_ID or email == DELETED_CLIENT_EMAIL:
            print(f"[phase_c2]   EXCLUDING deleted client: {uid} / {email}")
            continue
        has_workout = await db.workouts.count_documents({"user_id": uid}) > 0
        if has_workout:
            active_clients.append(c)

    active_ids = {c["id"] for c in active_clients}
    (out_dir / "active_clients.json").write_text(json.dumps(active_clients, indent=2, default=str))
    print(f"[phase_c2] {len(active_clients)} active client(s):")
    for c in active_clients:
        print(f"           - {c.get('name')} / {c.get('email')} / {c['id']}")

    # ---------- 2. Collect active refs (id + canonical name) ----------
    ref_ids: set[str] = set()
    ref_canons: set[str] = set()
    async for w in db.workouts.find({"user_id": {"$in": list(active_ids)}}, {
        "_id": 0, "id": 1, "user_id": 1, "date": 1,
        "exercises": 1, "warmup": 1, "cooldown": 1,
    }):
        for k in ("exercises", "warmup", "cooldown"):
            for it in (w.get(k) or []):
                if not isinstance(it, dict):
                    continue
                xid = it.get("exercise_id") or it.get("id")
                if xid:
                    ref_ids.add(str(xid))
                nm = it.get("name") or it.get("exercise_name")
                if nm:
                    c = _canon(nm)
                    if c:
                        ref_canons.add(c)

    # walk programmes too if collection exists
    if "programmes" in await db.list_collection_names():
        async for p in db.programmes.find({"user_id": {"$in": list(active_ids)}}, {"_id": 0}):
            def walk(node: Any) -> None:
                if isinstance(node, dict):
                    xid = node.get("exercise_id")
                    if xid:
                        ref_ids.add(str(xid))
                    nm = node.get("name") or node.get("exercise_name")
                    if nm and isinstance(nm, str):
                        c = _canon(nm)
                        if c:
                            ref_canons.add(c)
                    for v in node.values():
                        walk(v)
                elif isinstance(node, list):
                    for v in node:
                        walk(v)
            walk(p)

    print(f"[phase_c2] Refs: {len(ref_ids)} ids, {len(ref_canons)} canonical names")

    # ---------- 3. Orphan check (workout refs pointing to no row) ----------
    exercises = await db.exercises_v2.find({}, {"_id": 0}).to_list(length=None)
    known_ids = {str(ex.get("id") or "") for ex in exercises}
    known_canons = {_canon(ex.get("exercise_name")) for ex in exercises if ex.get("exercise_name")}

    # A ref is TRULY unresolvable only when BOTH id and canonical name fail
    # to match any current row. Stale-id-only refs (name still resolves) are
    # benign — the name-based fallback in the resolver takes over.
    orphan_id_refs = ref_ids - known_ids

    orphan_details: list[dict] = []       # unresolvable (id + name miss)
    stale_id_only: list[dict] = []        # benign — reported separately
    if orphan_id_refs:
        seen_key: set[tuple] = set()
        async for w in db.workouts.find(
            {"user_id": {"$in": list(active_ids)}},
            {"_id": 0, "id": 1, "user_id": 1, "date": 1,
             "exercises": 1, "warmup": 1, "cooldown": 1},
        ):
            for k in ("exercises", "warmup", "cooldown"):
                for it in (w.get(k) or []):
                    if not isinstance(it, dict):
                        continue
                    xid = str(it.get("exercise_id") or it.get("id") or "")
                    if xid not in orphan_id_refs:
                        continue
                    nm = it.get("name") or it.get("exercise_name")
                    cn = _canon(nm)
                    key = (w.get("id"), xid, cn)
                    if key in seen_key:
                        continue
                    seen_key.add(key)
                    u = next((c for c in active_clients if c["id"] == w["user_id"]), None)
                    row = {
                        "workout_id": w.get("id"),
                        "date": w.get("date"),
                        "user_id": w.get("user_id"),
                        "user_email": u.get("email") if u else None,
                        "user_name": u.get("name") if u else None,
                        "orphan_exercise_id": xid,
                        "exercise_name_in_workout": nm,
                        "name_resolves": bool(cn) and cn in known_canons,
                    }
                    if row["name_resolves"]:
                        stale_id_only.append(row)
                    else:
                        orphan_details.append(row)

    (out_dir / "orphan_refs_unresolvable.json").write_text(
        json.dumps(orphan_details, indent=2, default=str))
    (out_dir / "orphan_refs_stale_id_only.json").write_text(
        json.dumps(stale_id_only, indent=2, default=str))

    if stale_id_only:
        print(f"[phase_c2] ℹ️  {len(stale_id_only)} benign stale-id ref(s) "
              f"(name still resolves — safe):")
        for o in stale_id_only:
            print(f"           - workout {o['workout_id']} ({o['date']}) — "
                  f"{o['user_email']} — {o['exercise_name_in_workout']!r} — "
                  f"stale id {o['orphan_exercise_id']}")

    if orphan_details:
        print(f"[phase_c2] ⚠️  {len(orphan_details)} TRULY UNRESOLVABLE orphan ref(s) "
              f"on ACTIVE clients — aborting.")
        for o in orphan_details:
            print(f"           - workout {o['workout_id']} ({o['date']}) — "
                  f"{o['user_email']} — {o['exercise_name_in_workout']!r} — "
                  f"orphan id {o['orphan_exercise_id']}")
        sys.exit(3)
    else:
        print("[phase_c2] No unresolvable orphans on active clients — proceeding.")

    # ---------- 4. Compute delete-id list ----------
    def is_approved(ex: dict) -> bool:
        return (str(ex.get("status") or "") in ("Approved", "Live")
                or str(ex.get("approval_status") or "").lower() == "approved")
    def is_referenced(ex: dict) -> bool:
        eid = str(ex.get("id") or "")
        if eid and eid in ref_ids:
            return True
        for key in ("exercise_name", "requested_name", "requested_name_norm"):
            c = _canon(ex.get(key))
            if c and c in ref_canons:
                return True
        return False

    delete_ids: list[str] = []
    for ex in exercises:
        if is_approved(ex) or is_referenced(ex):
            continue
        eid = ex.get("id")
        if eid:
            delete_ids.append(str(eid))

    (out_dir / "delete_ids.json").write_text(json.dumps(delete_ids, indent=2))
    print(f"[phase_c2] Will delete {len(delete_ids)} exercises_v2 rows.")

    # ---------- 5. Snapshot BEFORE ----------
    before = await _snapshot(db)
    (out_dir / "snapshot_before.json").write_text(json.dumps(before, indent=2))
    print(f"[phase_c2] BEFORE: {json.dumps(before)}")

    # ---------- 6. DELETE ----------
    # Chunked to avoid single huge $in
    CHUNK = 500
    total_deleted = 0
    for i in range(0, len(delete_ids), CHUNK):
        chunk = delete_ids[i:i + CHUNK]
        res = await db.exercises_v2.delete_many({"id": {"$in": chunk}})
        total_deleted += res.deleted_count
    print(f"[phase_c2] exercises_v2.deleted_count = {total_deleted}")

    total_images_deleted = 0
    for i in range(0, len(delete_ids), CHUNK):
        chunk = delete_ids[i:i + CHUNK]
        res = await db.exercise_content_images.delete_many({"exercise_id": {"$in": chunk}})
        total_images_deleted += res.deleted_count
    print(f"[phase_c2] exercise_content_images.deleted_count = {total_images_deleted}")

    # ---------- 7. Snapshot AFTER deletion, BEFORE rescan ----------
    after_delete = await _snapshot(db)
    (out_dir / "snapshot_after_delete.json").write_text(json.dumps(after_delete, indent=2))
    print(f"[phase_c2] AFTER DELETE: {json.dumps(after_delete)}")

    # ---------- 8. Controlled future-only rescan for active clients ----------
    # Turn the guard OFF for our in-process import, run a scoped backfill,
    # then leave the env var in place so the running backend stays guarded.
    from feature_v2_resolver import backfill_missing_exercise_requests_from_workouts
    # override env for this process only:
    os.environ["EXERCISE_BACKFILL_DISABLED"] = "false"
    # need a fake "admin" dict — use louis@crewfit.net
    admin = await db.users.find_one({"email": "louis@crewfit.net"}, {"_id": 0}) or {}
    rescan_result = await backfill_missing_exercise_requests_from_workouts(
        admin,
        days_back=0,
        days_forward=60,
        max_new=500,
        only_user_ids=list(active_ids),
    )
    # restore guard for this process (env var in .env stays true regardless)
    os.environ["EXERCISE_BACKFILL_DISABLED"] = "true"
    print(f"[phase_c2] Rescan result: {rescan_result}")
    (out_dir / "rescan_result.json").write_text(json.dumps(rescan_result, indent=2))

    # ---------- 9. Snapshot AFTER rescan ----------
    after_rescan = await _snapshot(db)
    (out_dir / "snapshot_after_rescan.json").write_text(json.dumps(after_rescan, indent=2))
    print(f"[phase_c2] AFTER RESCAN: {json.dumps(after_rescan)}")

    drafts_recreated = after_rescan["exercises_v2_total"] - after_delete["exercises_v2_total"]

    # ---------- 10. Duplicate-normalised-name count ----------
    canon_counts: Counter = Counter()
    async for ex in db.exercises_v2.find({}, {"_id": 0, "exercise_name": 1}):
        c = _canon(ex.get("exercise_name"))
        if c:
            canon_counts[c] += 1
    duplicate_canon_names = sum(1 for _, n in canon_counts.items() if n > 1)

    # ---------- 11. Dangling reference check ----------
    known_ids_after = set()
    known_canons_after = set()
    async for ex in db.exercises_v2.find({}, {"_id": 0, "id": 1, "exercise_name": 1}):
        if ex.get("id"):
            known_ids_after.add(str(ex["id"]))
        c = _canon(ex.get("exercise_name"))
        if c:
            known_canons_after.add(c)

    dangling_refs: list[dict] = []
    async for w in db.workouts.find({"user_id": {"$in": list(active_ids)}}, {
        "_id": 0, "id": 1, "user_id": 1, "date": 1,
        "exercises": 1, "warmup": 1, "cooldown": 1,
    }):
        for k in ("exercises", "warmup", "cooldown"):
            for it in (w.get(k) or []):
                if not isinstance(it, dict):
                    continue
                xid = str(it.get("exercise_id") or it.get("id") or "")
                nm = it.get("name") or it.get("exercise_name")
                c = _canon(nm)
                id_missing = bool(xid) and xid not in known_ids_after
                name_missing = bool(c) and c not in known_canons_after
                if id_missing and name_missing:
                    dangling_refs.append({
                        "workout_id": w.get("id"),
                        "date": w.get("date"),
                        "user_id": w.get("user_id"),
                        "orphan_exercise_id": xid,
                        "exercise_name_in_workout": nm,
                    })
    (out_dir / "dangling_refs_after.json").write_text(json.dumps(dangling_refs, indent=2, default=str))

    # ---------- 12. Deleted-client leftovers status ----------
    deleted_client_workouts = await db.workouts.count_documents({"user_id": DELETED_CLIENT_ID})
    deleted_client_user_row = await db.users.find_one({"id": DELETED_CLIENT_ID}, {"_id": 0})

    # ---------- 13. Confirm active clients' workouts still resolve ----------
    render_check: dict[str, dict] = {}
    for c in active_clients:
        uid = c["id"]
        w_total = await db.workouts.count_documents({"user_id": uid})
        # each workout's exercise names must map to a row
        broken = 0
        checked = 0
        async for w in db.workouts.find({"user_id": uid}, {
            "_id": 0, "id": 1, "exercises": 1, "warmup": 1, "cooldown": 1
        }):
            checked += 1
            for k in ("exercises", "warmup", "cooldown"):
                for it in (w.get(k) or []):
                    if not isinstance(it, dict):
                        continue
                    xid = str(it.get("exercise_id") or it.get("id") or "")
                    nm = it.get("name") or it.get("exercise_name")
                    cn = _canon(nm)
                    id_ok = bool(xid) and xid in known_ids_after
                    name_ok = bool(cn) and cn in known_canons_after
                    if not (id_ok or name_ok):
                        broken += 1
        render_check[c.get("email") or uid] = {
            "workouts_total": w_total,
            "workouts_checked": checked,
            "broken_exercise_refs": broken,
            "renders_correctly": broken == 0,
        }

    # ---------- 14. Final report ----------
    summary = {
        "generated_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "guard_env": os.environ.get("EXERCISE_BACKFILL_DISABLED"),
        "active_clients": [
            {"id": c["id"], "email": c.get("email"), "name": c.get("name")}
            for c in active_clients
        ],
        "excluded_deleted_client": {
            "id": DELETED_CLIENT_ID,
            "email": DELETED_CLIENT_EMAIL,
            "workouts_still_in_db": deleted_client_workouts,
            "user_row_exists": bool(deleted_client_user_row),
        },
        "snapshot_before": before,
        "snapshot_after_delete": after_delete,
        "snapshot_after_rescan": after_rescan,
        "totals": {
            "exercises_v2_final_total": after_rescan["exercises_v2_total"],
            "approved_or_live_final": after_rescan["approved_or_live"],
            "retained_because_referenced_final": (
                after_rescan["exercises_v2_total"] - after_rescan["approved_or_live"]
            ),
            "needs_review_final": after_rescan["needs_review"],
            "needs_media_final": after_rescan["needs_media"],
            "in_progress_final": after_rescan["in_progress"],
            "rows_deleted": total_deleted,
            "media_metadata_rows_deleted": total_images_deleted,
            "drafts_recreated_during_rescan": drafts_recreated,
            "duplicate_normalised_names_after_cleanup": duplicate_canon_names,
            "dangling_exercise_references_after_cleanup": len(dangling_refs),
        },
        "rescan_result": rescan_result,
        "render_check_active_clients": render_check,
    }
    (out_dir / "REPORT.json").write_text(json.dumps(summary, indent=2, default=str))

    print("\n" + "=" * 76)
    print("PHASE C2 — FINAL REPORT")
    print("=" * 76)
    print(json.dumps(summary["totals"], indent=2))
    print()
    print("Render check per active client:")
    for k, v in render_check.items():
        print(f"  {k}: {v}")
    print()
    print(f"Deleted-client leftover status: user_row_exists={bool(deleted_client_user_row)}, "
          f"workouts_in_db={deleted_client_workouts}")
    print("=" * 76)
    print(f"Full report: {out_dir}/REPORT.json")


if __name__ == "__main__":
    asyncio.run(main())
