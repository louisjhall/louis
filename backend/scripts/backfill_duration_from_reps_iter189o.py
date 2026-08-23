"""Iter189o · Back-fill duration_sec on existing warm-up / cool-down /
mobility rows across db.workouts so the guided player renders a timer
instead of a bare reps checkbox.

* Reads: db.workouts.warmup[], .exercises[] (mobility only), .cooldown[]
* Writes: `duration_sec` (int) + `duration_sec_estimated: True` marker
  on rows where duration_sec is currently missing / falsy AND reps is a
  bare count (never overwrites explicit coach-set durations).
* Idempotent: skips rows already carrying `duration_sec_estimated` OR
  a real duration_sec.

Usage:
  python /app/backend/scripts/backfill_duration_from_reps_iter189o.py           # dry-run
  python /app/backend/scripts/backfill_duration_from_reps_iter189o.py --commit
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feature_coach_manual_workouts import _approx_duration_from_reps  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Write to DB (default: dry-run).")
    ap.add_argument("--limit", type=int, default=0, help="Cap number of workouts (0=all).")
    args = ap.parse_args()

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]

    now_iso = datetime.now(timezone.utc).isoformat()
    print("=" * 72)
    print(f"ITER189O · REPS → DURATION BACKFILL   ({db.name}) · {now_iso}")
    print(f"mode = {'COMMIT ✅' if args.commit else 'DRY-RUN 🧪'}")
    print("=" * 72)

    total = await db.workouts.count_documents({})
    print(f"Total workouts: {total}")

    scanned_rows = 0
    would_update_rows = 0
    workouts_touched = 0
    sample: list[dict] = []

    q: dict = {}
    proj = {"_id": 0, "id": 1, "date": 1, "title": 1,
            "warmup": 1, "exercises": 1, "cooldown": 1, "workout_type": 1}
    cursor = db.workouts.find(q, proj)
    if args.limit:
        cursor = cursor.limit(args.limit)

    async for w in cursor:
        did_change = False
        changes_this_wo = []
        wtype = str(w.get("workout_type") or "").lower()
        for section in ("warmup", "exercises", "cooldown"):
            rows = w.get(section) or []
            new_rows: list[dict] = []
            for row in rows:
                if not isinstance(row, dict):
                    new_rows.append(row); continue
                scanned_rows += 1
                # Section context — the item may already carry section, but
                # be tolerant: fall back to iteration section name.
                sec = str(row.get("section") or section).lower()
                if section == "exercises":
                    sec = "main"  # main rows never auto-fill unless mobility lt/cat
                # Idempotency + never overwrite explicit durations.
                if row.get("duration_sec") or row.get("duration_sec_estimated"):
                    new_rows.append(row); continue
                # Guard: skip cardio rows entirely (their own scaling path).
                lt = str(row.get("logging_type") or "").strip().lower()
                if lt in ("cardio", "timer"):
                    new_rows.append(row); continue

                est = _approx_duration_from_reps(
                    row.get("reps"),
                    sec,
                    logging_type=lt,
                    category=row.get("category"),
                )
                if est:
                    new_row = dict(row)
                    new_row["duration_sec"] = est
                    new_row["duration_sec_estimated"] = True
                    new_rows.append(new_row)
                    would_update_rows += 1
                    did_change = True
                    changes_this_wo.append({
                        "name": row.get("name"),
                        "reps": row.get("reps"),
                        "section": sec,
                        "estimated_sec": est,
                    })
                else:
                    new_rows.append(row)
            w[section] = new_rows
        if did_change:
            workouts_touched += 1
            if len(sample) < 5:
                sample.append({
                    "date": w.get("date"),
                    "title": w.get("title"),
                    "changes": changes_this_wo[:6],
                })
            if args.commit:
                await db.workouts.update_one(
                    {"id": w["id"]},
                    {"$set": {
                        "warmup": w["warmup"],
                        "exercises": w["exercises"],
                        "cooldown": w["cooldown"],
                    }},
                )

    print(f"\nScanned rows:      {scanned_rows}")
    print(f"Would-update rows: {would_update_rows}")
    print(f"Workouts touched:  {workouts_touched}")

    if sample:
        print("\nSample changes:")
        for s in sample:
            print(f"  · {s['date']} · {s['title']}")
            for c in s["changes"]:
                print(f"      {c['name']!r}  ({c['section']}, reps={c['reps']!r}) → "
                      f"duration_sec={c['estimated_sec']}")

    print("\nDone.")
    client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
