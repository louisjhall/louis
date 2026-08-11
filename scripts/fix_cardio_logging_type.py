"""Iter167 · Correct logging_type for Easy Run / Easy Walk / Long Run —
Steady Pace across:
  · db.exercises_v2  (canonical library rows)
  · db.exercises      (legacy library rows, if any)
  · db.workouts       (embedded exercise blobs — warmup / exercises / cooldown)
  · db.workouts.variants{green,amber,red}.exercises  (scaled variants)

All docs that currently have logging_type: 'weighted' get flipped to
'cardio'. Docs that already have 'cardio' are left alone. A dry-run mode
prints candidates without writing.

Run:
    cd /app/backend && python /app/scripts/fix_cardio_logging_type.py            # dry
    cd /app/backend && python /app/scripts/fix_cardio_logging_type.py --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

TARGET_NAMES = [
    "Easy Run",
    "Easy Walk",
    "Long Run — Steady Pace",
    "Long Run - Steady Pace",   # ASCII hyphen fallback (some importers strip em-dashes)
    "Long Run – Steady Pace",   # en-dash fallback
]
NAME_REGEXES = [
    re.compile(rf"^\s*{re.escape(n)}\s*$", re.IGNORECASE)
    for n in TARGET_NAMES
]


def _name_matches(name: str | None) -> bool:
    if not name:
        return False
    return any(rx.match(name) for rx in NAME_REGEXES)


async def _fix_library(db, apply: bool) -> tuple[int, int]:
    """Fix db.exercises_v2 + db.exercises. Returns (found, updated)."""
    found = 0
    updated = 0
    for coll_name in ("exercises_v2", "exercises"):
        coll = db[coll_name]
        # Case-insensitive OR of exact names.
        or_clause = [{"name": {"$regex": rx.pattern, "$options": "i"}} for rx in NAME_REGEXES]
        cursor = coll.find({"$or": or_clause})
        async for doc in cursor:
            found += 1
            lt_before = doc.get("logging_type")
            name = doc.get("name")
            if lt_before == "cardio":
                print(f"  [{coll_name}] SKIP  '{name}'  already cardio")
                continue
            print(f"  [{coll_name}] FIX   '{name}'  {lt_before!r} → 'cardio'")
            if apply:
                await coll.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"logging_type": "cardio"}},
                )
                updated += 1
    return found, updated


async def _fix_workouts(db, apply: bool) -> tuple[int, int]:
    """Walk every workout doc, patch embedded exercises whose name matches.
    Also patches variants{green|amber|red}.exercises for iter 133+ variant
    storage.

    Returns (workouts_touched, exercises_patched)."""
    workouts_touched = 0
    exercises_patched = 0
    coll = db.workouts

    async for w in coll.find({}, {"exercises": 1, "warmup": 1, "cooldown": 1, "variants": 1}):
        patched_any = False
        patch_paths: dict = {}

        # Top-level lists.
        for list_key in ("exercises", "warmup", "cooldown"):
            arr = w.get(list_key) or []
            for i, ex in enumerate(arr):
                if not isinstance(ex, dict):
                    continue
                if _name_matches(ex.get("name")) and ex.get("logging_type") != "cardio":
                    patch_paths[f"{list_key}.{i}.logging_type"] = "cardio"
                    exercises_patched += 1
                    patched_any = True

        # Variants.
        variants = w.get("variants") or {}
        for vkey in ("green", "amber", "red"):
            v = variants.get(vkey)
            if not isinstance(v, dict):
                continue
            for list_key in ("exercises", "warmup", "cooldown"):
                arr = v.get(list_key) or []
                for i, ex in enumerate(arr):
                    if not isinstance(ex, dict):
                        continue
                    if _name_matches(ex.get("name")) and ex.get("logging_type") != "cardio":
                        patch_paths[f"variants.{vkey}.{list_key}.{i}.logging_type"] = "cardio"
                        exercises_patched += 1
                        patched_any = True

        if patched_any:
            workouts_touched += 1
            print(f"  [workouts] {w['_id']}  → patch {len(patch_paths)} exercise(s)")
            if apply:
                await coll.update_one({"_id": w["_id"]}, {"$set": patch_paths})

    return workouts_touched, exercises_patched


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. Default is dry-run.")
    args = parser.parse_args()
    apply = bool(args.apply)

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    banner = "APPLY" if apply else "DRY-RUN"
    print(f"=== iter167 cardio-logging-type fix · {banner} ===")

    print("\n[1/2] Library (exercises_v2 + exercises)…")
    found_lib, updated_lib = await _fix_library(db, apply)

    print("\n[2/2] Workouts (embedded exercises + variants)…")
    touched_w, patched_ex = await _fix_workouts(db, apply)

    print("\n=== Summary ===")
    print(f"  library rows found:              {found_lib}")
    print(f"  library rows {'updated' if apply else 'would update'}:            {updated_lib}")
    print(f"  workout docs {'patched' if apply else 'would patch'}:            {touched_w}")
    print(f"  embedded exercises {'patched' if apply else 'would patch'}:      {patched_ex}")

    if not apply:
        print("\n(dry-run — re-run with --apply to actually write)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
