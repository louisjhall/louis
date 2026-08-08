"""
Iter 161 · One-time cleanup for workouts where the TOP-LEVEL exercises/
warmup/cooldown arrays are empty (e.g. reverted Full Rest days) but the
Traffic-Light variants (green / amber / red) still carry the pre-fix
bodyweight-fallback exercises.

The revert step in `_heal_workouts_batch` was extended (Iter 161) to also
clear variants on live reads, but this script forces the same clean on
every existing row in one pass so we don't wait for a client fetch.

READ-ONLY BY DEFAULT (--dry-run). Never deletes rows.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "crewfit_v1"


def has_stale_variants(w: dict) -> bool:
    """Top-level exercises empty AND at least one variant has content."""
    top = w.get("exercises") or []
    if top:
        return False
    variants = w.get("variants") or {}
    if not isinstance(variants, dict):
        return False
    for v in variants.values():
        if not isinstance(v, dict):
            continue
        if (v.get("exercises") or v.get("warmup") or v.get("cooldown")):
            return True
    return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]

    # Only workouts with empty top-level exercises and non-empty variants.
    # Never touch completed workouts.
    cursor = db.workouts.find(
        {
            "$or": [{"exercises": {"$size": 0}}, {"exercises": {"$in": [None]}}],
            "completed": {"$ne": True},
        },
        {"_id": 0, "id": 1, "user_id": 1, "date": 1, "title": 1,
         "workout_type": 1, "duration_min": 1, "exercises": 1, "variants": 1},
    )
    targets = []
    async for w in cursor:
        if has_stale_variants(w):
            targets.append(w)

    print(f"Rows with empty top-level exercises AND populated variants: {len(targets)}")
    for w in targets[:40]:
        variants = w.get("variants") or {}
        sig = []
        for k in ("green", "amber", "red"):
            v = variants.get(k) or {}
            if isinstance(v, dict):
                ex_n = len(v.get("exercises") or [])
                wu_n = len(v.get("warmup") or [])
                cd_n = len(v.get("cooldown") or [])
                if ex_n or wu_n or cd_n:
                    sig.append(f"{k}=(ex:{ex_n}, wu:{wu_n}, cd:{cd_n})")
        print(f"  {w.get('date')}  user={str(w.get('user_id'))[:10]}…  title={w.get('title')!r:<25}  wtype={w.get('workout_type')!r}  " + " ".join(sig))

    if not args.commit:
        print("\nDRY-RUN — no changes written. Re-run with --commit to persist.")
        cli.close()
        return

    touched = 0
    for w in targets:
        variants = w.get("variants") or {}
        cleaned: dict = {}
        for k, v in variants.items():
            if not isinstance(v, dict):
                cleaned[k] = v
                continue
            vv = dict(v)
            vv["exercises"] = []
            vv["warmup"] = []
            vv["cooldown"] = []
            vv["duration_min"] = 0
            cleaned[k] = vv
        await db.workouts.update_one(
            {"id": w["id"]},
            {"$set": {"variants": cleaned,
                      "variants_cleaned_at": datetime.utcnow().isoformat()}},
        )
        touched += 1

    print(f"\nCleaned variants on {touched} workouts.")
    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
