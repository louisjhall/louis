"""Iter189j · Backfill legacy `alternatives[]` → new `alternatives_meta[]`.

Context
=======
Iter189g introduced the new purpose-tagged shape:

    alternatives_meta: [
      {name, purpose: equipment_swap|easier_regression|injury_mobility_friendly, why}
    ]

But ~108 library rows carry the OLD flat shape:

    alternatives: ["Name A", "Name B", ...]

The `/api/exercises/alternatives` endpoint already falls back to the flat
list when `alternatives_meta` is empty, BUT the client UI cannot render
purpose badges for those rows. This script backfills a best-effort
`alternatives_meta` by mapping the first three items in `alternatives[]`
to the three purposes in order:
    1st → equipment_swap
    2nd → easier_regression
    3rd → injury_mobility_friendly

The mapping is not perfect (the flat list wasn't ordered by purpose),
but it's better than empty AND lets the coach quickly re-generate a
proper trio via the "Generate Alternatives" button.

Idempotent — skips any row that already has a non-empty
`alternatives_meta`. Safe to re-run.

Usage
=====

    # 1. Dry-run (default) — prints counts, changes nothing
    python3 scripts/backfill_alternatives_meta.py

    # 2. Commit
    python3 scripts/backfill_alternatives_meta.py --commit
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

PURPOSE_ORDER = ("equipment_swap", "easier_regression", "injury_mobility_friendly")
LEGACY_WHY = "Legacy alternative — regenerate for a purpose-labelled trio."


def _legacy_to_meta(raw_alts: list) -> list[dict]:
    """Best-effort map of the first 3 legacy names to purpose slots."""
    out: list[dict] = []
    seen_names: set[str] = set()
    for entry in raw_alts:
        if len(out) >= 3:
            break
        # Legacy shape: either a plain name string OR a dict without `purpose`.
        if isinstance(entry, str):
            name = entry.strip()
        elif isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
        else:
            continue
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())
        out.append({
            "name": name,
            "purpose": PURPOSE_ORDER[len(out)],
            "why": (
                entry.get("why") or entry.get("reason") or LEGACY_WHY
            ) if isinstance(entry, dict) else LEGACY_WHY,
            "backfilled": True,
        })
    return out


async def main(commit: bool) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME missing.", file=sys.stderr)
        return 2

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    # Candidates: has non-empty alternatives, AND (missing OR empty)
    # alternatives_meta.
    candidate_q = {
        "alternatives": {"$exists": True, "$ne": []},
        "$or": [
            {"alternatives_meta": {"$exists": False}},
            {"alternatives_meta": []},
            {"alternatives_meta": None},
        ],
    }
    candidates = await db.exercises_v2.count_documents(candidate_q)

    already_populated = await db.exercises_v2.count_documents(
        {"alternatives_meta": {"$exists": True, "$type": "array",
                               "$not": {"$size": 0}}},
    )
    total_with_alts = await db.exercises_v2.count_documents(
        {"alternatives": {"$exists": True, "$ne": []}},
    )

    print("=" * 66)
    print(f"alternatives_meta backfill — {'COMMIT' if commit else 'DRY-RUN'}")
    print("=" * 66)
    print(f"Rows with alternatives[] set:                 {total_with_alts}")
    print(f"  · Already have alternatives_meta:           {already_populated}")
    print(f"  · Need backfill (candidates):               {candidates}")
    if not candidates:
        print("\nNothing to backfill. Exiting.")
        return 0

    # Preview 10
    print("\nSample of what would be written (first 10):")
    i = 0
    async for row in db.exercises_v2.find(candidate_q).limit(10):
        i += 1
        raw = row.get("alternatives") or []
        meta = _legacy_to_meta(raw)
        nm = row.get("exercise_name") or "?"
        print(f"  {i:2d}. {nm[:40]:40s} → {len(meta)} meta items")
        for m in meta:
            print(f"       · {m['name'][:35]:35s}  [{m['purpose']}]")

    if not commit:
        print("\nDry-run complete. Re-run with --commit to apply.")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    async for row in db.exercises_v2.find(candidate_q):
        raw = row.get("alternatives") or []
        meta = _legacy_to_meta(raw)
        if not meta:
            continue
        await db.exercises_v2.update_one(
            {"id": row["id"]},
            {"$set": {
                "alternatives_meta": meta,
                "alternatives_meta_backfilled_at": now,
                "alternatives_meta_backfill_source": "iter189j_legacy_migration",
            }},
        )
        updated += 1

    print(f"\nBackfilled {updated} rows.")
    print("These can be regenerated later via the coach admin "
          "'Generate Alternatives' button for a proper purpose-labelled trio.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--commit", action="store_true",
        help="Actually apply the backfill (default is dry-run).",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(commit=args.commit)))
