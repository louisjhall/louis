"""Iter189 · One-time cleanup — archive orphan `draft_requested` rows.

Context
=======
The dormant V2 AI-generation fallback (see handoff summary §"Issue 1")
has been inserting rows into `exercises_v2` with `status='draft_requested'`,
`visibility='coach_only'`, and `safe_for_programming=False`. These
rows never surface in the coach's library UI but WERE being scanned by
the YouTube video finder — burning ~10k quota units per sweep on ghost
exercises.

Root cause: `feature_v2_resolver.py::apply_resolver` (lines 833-839)
can insert `exercise_id = None` and defer library creation, but never
cleans up when the workout is later hand-crafted.

This script marks all such rows as `status='archived'` (soft, reversible)
with an audit trail — it does NOT delete anything. Rows can be
unarchived with:

    db.exercises_v2.update_many(
        {"status": "archived", "archived_reason": "iter189_draft_requested_cleanup"},
        {"$set": {"status": "draft_requested"}, "$unset": {"archived_reason": ""}}
    )

Usage
=====

    # 1. Dry-run (default) — prints counts, changes nothing
    python3 scripts/archive_draft_requested_ghosts.py

    # 2. Commit
    python3 scripts/archive_draft_requested_ghosts.py --commit
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()


async def main(commit: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME missing from environment.", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    query = {"status": "draft_requested"}
    count = await db.exercises_v2.count_documents(query)

    print("=" * 66)
    print(f"draft_requested ghost cleanup — {'COMMIT' if commit else 'DRY-RUN'}")
    print("=" * 66)
    print(f"Rows matching status='draft_requested': {count}")

    # Extra safety diagnostics before we touch anything
    with_video = await db.exercises_v2.count_documents({
        **query,
        "primary_video_url": {"$exists": True, "$nin": [None, ""]},
    })
    with_image = await db.exercises_v2.count_documents({
        **query,
        "primary_image_url": {"$exists": True, "$nin": [None, ""]},
    })
    print(f"  · of which already have a video: {with_video}")
    print(f"  · of which already have an image: {with_image}")

    # Sample first 5
    print("\nSample (first 5):")
    async for doc in db.exercises_v2.find(query).limit(5):
        name = doc.get("exercise_name") or doc.get("requested_name") or "?"
        vis = doc.get("visibility")
        safe = doc.get("safe_for_programming")
        print(f"  · {name[:44]:44s}  visibility={vis!r:15s} safe_for_programming={safe}")

    if not commit:
        print("\nDry-run complete. Re-run with --commit to archive these rows.")
        return 0

    if count == 0:
        print("\nNothing to archive. Exiting.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    result = await db.exercises_v2.update_many(
        query,
        {
            "$set": {
                "status": "archived",
                "archived_reason": "iter189_draft_requested_cleanup",
                "archived_at": now,
                "previous_status": "draft_requested",
            },
        },
    )
    print(f"\nArchived {result.modified_count} rows.")
    print("Reversible with the unarchive command in this script's docstring.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--commit", action="store_true",
        help="Actually apply the archive (default is dry-run).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(commit=args.commit)))
