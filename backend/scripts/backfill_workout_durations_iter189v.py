#!/usr/bin/env python3
"""
Iter189v · One-shot backfill for imported workouts.

Root cause: when ChatGPT-generated workouts were imported (or when a coach
authored a main-section cardio row), the guided-flow enricher would only
fill `duration_sec` for warm-up / cool-down / mobility rows. Main-section
cardio like `Zone 2 Walk/Light Jog · reps="25 min"` therefore had no
`duration_sec`, and its `logging_type` also missed if the exercise wasn't
in exercises_v2 (fresh import). Guided flow then displayed "25 reps" and
capped the timer to 10:00.

This script scans db.workouts and, for every exercise in
warmup[]/exercises[]/cooldown[] where:
   1. duration_sec is missing / 0
   2. reps carries a time hint ("25 min", "45 sec", "5:00", …)
… fills BOTH:
   • duration_sec  = parsed seconds (upper bound of any range)
   • logging_type  = "timer" (if not already 'timer' | 'cardio')

Idempotent. Preserves coach-set values. Never touches roster / activity
data.

Usage:
    python scripts/backfill_workout_durations_iter189v.py --dry-run
    python scripts/backfill_workout_durations_iter189v.py           # apply
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_workout_durations_iter189v")

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or "crewfit"

if not MONGO_URL:
    log.error("MONGO_URL not set — cannot connect to DB.")
    sys.exit(1)


_REPS_TIME_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?)\s*)?"
    r"(hr|hrs|hour|hours|min|mins|minute|minutes|s|sec|secs|second|seconds)\b",
    re.I,
)
_REPS_MMSS_RE = re.compile(r"^\s*(\d+):(\d{2})\s*$")


def _parse_reps_time_to_seconds(reps: str) -> int | None:
    if not reps:
        return None
    s = str(reps).strip()
    mmss = _REPS_MMSS_RE.match(s)
    if mmss:
        return int(mmss.group(1)) * 60 + int(mmss.group(2))
    m = _REPS_TIME_UNIT_RE.search(s)
    if not m:
        return None
    lo = float(m.group(1))
    hi = float(m.group(2)) if m.group(2) else lo
    n = hi
    unit = m.group(3).lower()
    if unit.startswith(("hr", "hour")):
        return int(round(n * 3600))
    if unit.startswith(("min", "minute")):
        return int(round(n * 60))
    return int(round(n))


def _apply_to_row(row: dict) -> tuple[bool, dict]:
    """Return (changed, patched_row)."""
    changed = False
    if not isinstance(row, dict):
        return False, row

    # Only touch when duration_sec is empty/zero.
    try:
        current = int(row.get("duration_sec") or 0)
    except (TypeError, ValueError):
        current = 0
    if current > 0:
        return False, row

    secs = _parse_reps_time_to_seconds(row.get("reps") or "")
    if not secs:
        return False, row

    row["duration_sec"] = secs
    row["duration_sec_estimated"] = True
    changed = True

    lt = str(row.get("logging_type") or "").strip().lower()
    if lt not in ("timer", "cardio"):
        row["logging_type"] = "timer"
        row["logging_type_estimated"] = True
        changed = True

    return changed, row


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    log.info("Scanning db.workouts …")
    cursor = db.workouts.find({}, {"_id": 0, "id": 1, "date": 1, "title": 1,
                                   "warmup": 1, "exercises": 1, "cooldown": 1})
    total = 0
    wrote = 0
    rows_patched = 0
    samples: list[str] = []

    from pymongo import UpdateOne
    ops: list[UpdateOne] = []

    async for w in cursor:
        total += 1
        if args.limit and total > args.limit:
            break

        w_changed = False
        for section in ("warmup", "exercises", "cooldown"):
            items = w.get(section) or []
            if not isinstance(items, list):
                continue
            for row in items:
                changed, _ = _apply_to_row(row)
                if changed:
                    w_changed = True
                    rows_patched += 1
                    if len(samples) < 15:
                        samples.append(
                            f"{w.get('date', '?'):>10}  {row.get('name'):<40}  "
                            f"reps={row.get('reps')!r:<15}  → duration_sec={row.get('duration_sec')}"
                        )

        if w_changed:
            wrote += 1
            ops.append(
                UpdateOne(
                    {"id": w["id"]},
                    {"$set": {
                        "warmup": w.get("warmup"),
                        "exercises": w.get("exercises"),
                        "cooldown": w.get("cooldown"),
                        "duration_backfilled_at_iter189v": datetime.now(timezone.utc).isoformat(),
                    }},
                )
            )

    log.info(f"Scanned:            {total}")
    log.info(f"Workouts patched:   {wrote}")
    log.info(f"Rows patched:       {rows_patched}")
    if samples:
        log.info("Sample rows:")
        for s in samples:
            log.info(f"  • {s}")

    if args.dry_run:
        log.info("Dry-run only. Re-run without --dry-run to apply.")
        return

    if ops:
        res = await db.workouts.bulk_write(ops, ordered=False)
        log.info(f"Bulk write matched={res.matched_count} modified={res.modified_count}")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
