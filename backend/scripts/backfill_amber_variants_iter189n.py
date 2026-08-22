"""Iter189n · Re-derive amber variants for workouts generated with the
old cardio-detection logic (logging_type-only, missed cardio-by-name
& cardio-by-duration).

Behaviour
---------
* For every workout with a populated `variants.green.exercises`, we
  re-derive amber via `_derive_amber(green)` (the hardened iter189n
  version) and update `variants.amber` in place.
* Idempotent: safe to re-run. Rows already carrying the iter189n stamp
  (`variants.amber._derived_source == "iter189n_amber_recalc"`) are
  skipped in `--skip-stamped` mode.
* Preserves whatever variants.red carries — we only touch amber.
* Dry-run by default. Pass `--commit` to actually write.

Reads
-----
* Reads `MONGO_URL` and `DB_NAME` (defaults to `test_database`).

Usage
-----
  python /app/backend/scripts/backfill_amber_variants_iter189n.py         # dry-run
  python /app/backend/scripts/backfill_amber_variants_iter189n.py --commit
  python /app/backend/scripts/backfill_amber_variants_iter189n.py --commit --skip-stamped
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

# Import after load_dotenv so feature_traffic_light picks up envs.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feature_traffic_light import _derive_amber, _is_cardio_ex  # noqa: E402


STAMP_SOURCE = "iter189n_amber_recalc"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Write to DB (default: dry-run).")
    ap.add_argument("--skip-stamped", action="store_true",
                    help="Skip rows already stamped by this script.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap number of workouts scanned (0 = all).")
    args = ap.parse_args()

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]

    now = datetime.now(timezone.utc).isoformat()
    print(f"{'=' * 72}")
    print(f"ITER189N · AMBER VARIANT RE-DERIVATION  ({db.name}) · {now}")
    print(f"mode = {'COMMIT ✅' if args.commit else 'DRY-RUN 🧪'}"
          f"   skip_stamped={args.skip_stamped}")
    print(f"{'=' * 72}")

    q: dict = {"variants.green.exercises": {"$exists": True, "$ne": []}}
    if args.skip_stamped:
        q["variants.amber._derived_source"] = {"$ne": STAMP_SOURCE}
    total = await db.workouts.count_documents(q)
    print(f"Total workouts to consider: {total}")

    scanned = 0
    changed = 0
    cardio_touching = 0
    skipped_no_green = 0
    sample_before_after: list[dict] = []
    projection = {
        "_id": 0, "id": 1, "user_id": 1, "date": 1,
        "variants": 1, "title": 1,
    }
    cursor = db.workouts.find(q, projection)
    if args.limit:
        cursor = cursor.limit(args.limit)

    async for w in cursor:
        scanned += 1
        variants = w.get("variants") or {}
        green = variants.get("green") or {}
        old_amber = variants.get("amber") or {}
        if not green.get("exercises"):
            skipped_no_green += 1
            continue

        new_amber = _derive_amber(green)
        # Preserve any pre-existing keys we don't overwrite (e.g. LLM's
        # intensity_note) by merging on top of new_amber, not replacing.
        merged_amber = {**old_amber, **new_amber}
        merged_amber["_derived_source"] = STAMP_SOURCE
        merged_amber["_derived_at"] = now

        # Diff: did anything actually change?
        old_exs = [_exercise_shape(e) for e in (old_amber.get("exercises") or [])]
        new_exs = [_exercise_shape(e) for e in (new_amber.get("exercises") or [])]
        did_change = old_exs != new_exs
        touches_cardio = any(_is_cardio_ex(e) for e in (green.get("exercises") or []))
        if touches_cardio:
            cardio_touching += 1

        if did_change:
            changed += 1
            if len(sample_before_after) < 5 and touches_cardio:
                sample_before_after.append({
                    "id": w.get("id"),
                    "date": w.get("date"),
                    "title": w.get("title"),
                    "green_ex_names": [e.get("name") for e in green.get("exercises") or []][:5],
                    "old_amber": old_exs[:5],
                    "new_amber": new_exs[:5],
                })
            if args.commit:
                await db.workouts.update_one(
                    {"id": w["id"]},
                    {"$set": {"variants.amber": merged_amber}},
                )

    print(f"\nScanned:            {scanned}")
    print(f"Would-update:       {changed}")
    print(f"With cardio in ex.: {cardio_touching}")
    print(f"Skipped (no green): {skipped_no_green}")

    if sample_before_after:
        print("\nSample cardio-touching before/after diffs:")
        for s in sample_before_after:
            print(f"  · {s['date']} · {s['title']}")
            print(f"      exercises: {s['green_ex_names']}")
            print(f"      old_amber: {s['old_amber']}")
            print(f"      new_amber: {s['new_amber']}")

    print("\nDone.")
    client.close()


def _exercise_shape(e: dict) -> dict:
    """Extract the fields amber actually diffs on so we can detect real
    changes and ignore noise from re-serialising equal shapes."""
    if not isinstance(e, dict):
        return {}
    return {
        "name": e.get("name"),
        "sets": e.get("sets"),
        "reps": e.get("reps"),
        "duration_sec": e.get("duration_sec"),
        "duration_min": e.get("duration_min"),
        "distance_m": e.get("distance_m"),
        "distance_km": e.get("distance_km"),
        "rpe": e.get("rpe"),
        "rest_sec": e.get("rest_sec"),
        "logging_type": e.get("logging_type"),
    }


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
