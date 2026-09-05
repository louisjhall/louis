"""One-shot: strip every `thumbnail_storage_key` off `on_demand_items`
and delete the corresponding stub objects from R2.

Symmetric partner to `backfill_on_demand_r2_thumbnails.py`. Run this
BEFORE uploading a fresh, full-size thumbnail ZIP so the pipeline is
guaranteed to be clean — no orphan keys, no stub bytes lingering in
R2.

Report at the end so you can eyeball the numbers before the fresh
import.

Run:
    cd /app/backend && python3 scripts/clear_on_demand_r2_thumbnails.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_BACKEND / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
import storage as _storage  # noqa: E402


async def main() -> int:
    print(f"storage driver: {_storage.storage.name}")

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # (1) Collect every non-null storage key currently on any on-demand item.
    rows = await db.on_demand_items.find(
        {"thumbnail_storage_key": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "thumbnail_storage_key": 1},
    ).to_list(2000)
    keys = sorted({r["thumbnail_storage_key"] for r in rows if r.get("thumbnail_storage_key")})
    print(f"items with key: {len(rows)}")
    print(f"unique keys:    {len(keys)}")

    # (2) Delete every key from R2. Errors are logged, not fatal — a missing
    # key just means somebody else already cleaned it up.
    deleted = 0
    delete_errors: list[tuple[str, str]] = []
    for k in keys:
        try:
            await _storage.storage.delete(k)
            deleted += 1
        except Exception as e:
            delete_errors.append((k, str(e)))
    print(f"R2 deletes ok: {deleted}")
    if delete_errors:
        print(f"R2 delete errors ({len(delete_errors)}):")
        for k, e in delete_errors[:5]:
            print(f"  - {k}: {e}")

    # (3) Strip the DB fields. `$unset` so the shape stays clean — the
    # backfill script keys off the ABSENCE of these fields.
    r = await db.on_demand_items.update_many(
        {"thumbnail_storage_key": {"$exists": True}},
        {"$unset": {
            "thumbnail_storage_key": "",
            "thumbnail_mime": "",
            "thumbnail_ext": "",
        }},
    )
    print(f"docs updated:  {r.modified_count}")

    # (4) Post-check.
    remaining = await db.on_demand_items.count_documents({
        "thumbnail_storage_key": {"$exists": True, "$ne": None},
    })
    print(f"post-check: {remaining} docs still carry a key (target: 0)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
