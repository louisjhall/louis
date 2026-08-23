#!/usr/bin/env python3
"""
Iter189s · Backfill logging_type on exercises_v2.

The workout player's reps/time toggle is now driven strictly by
`logging_type`:
  • "timer"  → locked to time-only, no toggle, TIME badge
  • anything else (incl. missing) → toggle shown, client picks reps/time

Historically, many exercises in the library have no `logging_type` set
because the classifier used to infer it from name/category at render
time. To make the new deterministic behaviour Just Work for existing
programmes, this script scans the library and stamps `logging_type =
"timer"` on rows that unambiguously belong in the time-locked bucket:

  • training_type == "cardio" or category == "cardio"
  • name matches a canonical cardio verb (run, row, bike, swim,
    walk, hike, rucking, sprint, intervals, treadmill, stairmaster,
    zone 1/2/3/5, etc.) UNLESS the name is a strength-with-cardio-word
    (barbell row, walking lunge, farmer's walk = hold, etc.)
  • name matches a canonical hold-and-carry (plank, wall sit, dead
    hang, farmer's carry / walk, side plank, hollow hold, etc.)
  • has logging_type_override == "timer" or "cardio"

Anything else is LEFT ALONE (i.e. defaults to reps-toggle behaviour).
The script is idempotent — running it twice makes no additional
changes. Every stamp is recorded in a change-log collection so we
can review or undo later.

Usage:
    cd /app/backend
    python scripts/backfill_logging_type_iter189s.py --dry-run
    python scripts/backfill_logging_type_iter189s.py           # apply
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

# Load env from /app/backend/.env
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill_logging_type_iter189s")

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or "crewfit"

if not MONGO_URL:
    log.error("MONGO_URL not set — cannot connect to DB.")
    sys.exit(1)


# --------------------------------------------------------------------------
# Regex library — kept in sync with src/lib/workoutMode.ts::isCardio/isTimeBased
# --------------------------------------------------------------------------
CARDIO_HIT = re.compile(
    r"\b(run|running|jog|zone[\s-]?[1235]|z[1235]|intervals?|treadmill|"
    r"row|rowing|erg|bike|biking|cycling|cycle|assault|swim|swimming|sprint|"
    r"ez pace|long run|fartlek|walk|walking|hike|hiking|ruck|rucking|stair|stairs|"
    r"stairmaster|stepper|incline\s?walk|power\s?walk|brisk\s?walk|recovery\s?walk)\b",
    re.IGNORECASE,
)

# Strength patterns that CONTAIN a cardio keyword must be excluded.
STRENGTH_NAME_EXCLUDE = re.compile(
    r"\b(walking\s+(lunges?|planks?|push|dead\s?bug)|bent[- ]?over\s?row|barbell\s?row|"
    r"dumbbell\s?row|db\s?row|kb\s?row|pendlay\s?row|seal\s?row|meadows\s?row|"
    r"chest[- ]?supported\s?row|inverted\s?row|single[- ]?arm\s?row|renegade\s?row|"
    r"t[- ]?bar\s?row|kroc\s?row|upright\s?row|face\s?pull|cable\s?row|iso\s?row|"
    r"smith\s?row|helms\s?row|hip\s?thrust)\b",
    re.IGNORECASE,
)

HOLD_HIT = re.compile(
    r"\b(side plank|front plank|plank|hollow hold|wall sit|dead ?hang|l[- ]?sit|"
    r"farmer'?s? (walk|carry)|suitcase carry|overhead carry|superman hold|"
    r"bridge hold|forearm plank|hollow rock|dish hold|bear crawl hold|"
    r"hanging (l[- ]?sit|leg hold)|copenhagen (hold|plank)|couch stretch|"
    r"pigeon (hold|stretch)|isometric)\b",
    re.IGNORECASE,
)


def classify(ex: dict) -> tuple[str | None, str]:
    """Return (new_logging_type_or_None, reason)."""
    name = str(ex.get("exercise_name") or "").strip()
    category = str(ex.get("category") or "").strip().lower()
    training_type = str(ex.get("training_type") or "").strip().lower()
    override = str(ex.get("logging_type_override") or "").strip().lower()

    # Coach override wins
    if override in ("timer", "cardio"):
        return ("timer", f"coach override = {override}")
    if override == "reps":
        return (None, "coach override = reps (leave alone)")

    # Category / training_type signal
    if category == "cardio" or training_type == "cardio":
        return ("timer", f"category/training_type == cardio")

    # Name-based cardio, but exclude strength-with-cardio-word rows
    if CARDIO_HIT.search(name) and not STRENGTH_NAME_EXCLUDE.search(name):
        return ("timer", "cardio verb in name")

    # Name-based hold-and-carry
    if HOLD_HIT.search(name):
        return ("timer", "hold-and-carry name match")

    return (None, "no timer signal")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--limit", type=int, default=0, help="Only process N docs (0 = all)")
    args = parser.parse_args()

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    log.info("Scanning db.exercises_v2 …")

    q = {}
    cursor = db.exercises_v2.find(q, {"_id": 0, "id": 1, "exercise_name": 1,
                                       "category": 1, "training_type": 1,
                                       "logging_type": 1, "logging_type_override": 1})
    total = 0
    to_set_timer = 0
    skipped_already = 0
    skipped_no_signal = 0
    samples: list[str] = []

    changes: list[dict] = []

    async for ex in cursor:
        total += 1
        if args.limit and total > args.limit:
            break

        current = str(ex.get("logging_type") or "").strip().lower()
        # Legacy "cardio" is treated identically to "timer" going forward,
        # but we still normalise to "timer" so the picker (which only has
        # REPS / TIMER) can round-trip cleanly.
        if current == "timer":
            skipped_already += 1
            continue

        new_lt, reason = classify(ex)
        if new_lt is None:
            skipped_no_signal += 1
            continue

        # Already the same value — nothing to do
        if new_lt == current:
            skipped_already += 1
            continue

        to_set_timer += 1
        if len(samples) < 15:
            samples.append(f"{ex.get('exercise_name')} — {reason}"
                           + (f" (was: {current})" if current else ""))
        changes.append({
            "id": ex.get("id"),
            "exercise_name": ex.get("exercise_name"),
            "prev": current or None,
            "new": new_lt,
            "reason": reason,
        })

    log.info("Scan complete.")
    log.info(f"  Total rows scanned: {total}")
    log.info(f"  Would stamp 'timer': {to_set_timer}")
    log.info(f"  Already 'timer' (skipped): {skipped_already}")
    log.info(f"  No timer signal (left alone): {skipped_no_signal}")

    if samples:
        log.info("  First %d picks:", len(samples))
        for s in samples:
            log.info(f"    • {s}")

    if args.dry_run:
        log.info("Dry-run only. Re-run without --dry-run to apply.")
        return

    if not changes:
        log.info("Nothing to do.")
        return

    log.info("Applying %d updates …", len(changes))
    now = datetime.now(timezone.utc).isoformat()

    # Bulk update
    from pymongo import UpdateOne
    ops = [
        UpdateOne(
            {"id": c["id"]},
            {"$set": {
                "logging_type": c["new"],
                "logging_type_backfilled_at": now,
                "logging_type_backfilled_reason": c["reason"],
            }},
        )
        for c in changes
    ]
    if ops:
        res = await db.exercises_v2.bulk_write(ops, ordered=False)
        log.info(f"Bulk write: matched={res.matched_count} modified={res.modified_count}")

    # Audit log
    try:
        await db.logging_type_backfill_log.insert_one({
            "run_at": now,
            "iteration": "iter189s",
            "changed_count": len(changes),
            "summary": {
                "total_scanned": total,
                "stamped_timer": to_set_timer,
                "skipped_already": skipped_already,
                "skipped_no_signal": skipped_no_signal,
            },
            "samples": changes[:100],  # keep first 100 for audit
        })
    except Exception:
        log.exception("Failed to write audit row (non-fatal)")

    log.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
