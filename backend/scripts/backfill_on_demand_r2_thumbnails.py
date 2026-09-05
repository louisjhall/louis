"""One-shot backfill: mirror local `on-demand-thumbnails/*.jpg` to R2
and stamp `thumbnail_storage_key` on every `on_demand_items` doc that
has a `thumbnail_filename` but no `thumbnail_storage_key`.

Why this exists
---------------
The bulk-import pipeline was extended to mirror thumbnails to R2 so
they survive a pod redeploy, but ~100 items were imported BEFORE that
code went live. Those rows have `thumbnail_filename` set (points at
`/frontend/assets/on-demand-thumbnails/w-XXX.jpg`) but no R2 key, so
after redeploy — when Metro's on-disk copies get wiped — the client
falls all the way through to the placeholder icon.

This script reads each local JPEG and uploads it to R2 under the same
key layout the live endpoint uses (`on_demand/thumbnails/bulk/w-XXX.jpg`),
then updates the Mongo doc. Idempotent: rows with a key already are
skipped.

Run:
    cd /app/backend && python3 scripts/backfill_on_demand_r2_thumbnails.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure the backend package root is importable when run from anywhere.
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_BACKEND / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
import storage as _storage  # noqa: E402

THUMBNAIL_DIR = Path(
    os.environ.get(
        "ONDEMAND_THUMBNAIL_DIR",
        "/app/frontend/assets/on-demand-thumbnails",
    )
)


async def main() -> int:
    print(f"storage driver: {_storage.storage.name}")
    if _storage.storage.name == "disk":
        print("!! WARNING: R2 not configured — backfill will write to local disk "
              "and NOT survive redeploy. Configure R2_* env vars first.")

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    q = {
        "thumbnail_filename": {"$exists": True, "$ne": None},
        "$or": [
            {"thumbnail_storage_key": {"$exists": False}},
            {"thumbnail_storage_key": None},
        ],
    }
    total = await db.on_demand_items.count_documents(q)
    print(f"candidates: {total}")

    cursor = db.on_demand_items.find(q, {"_id": 0, "id": 1, "thumbnail_filename": 1})
    uploaded = 0
    updated = 0
    missing_files: list[str] = []
    errors: list[str] = []

    async for doc in cursor:
        item_id = doc["id"]
        fname = str(doc["thumbnail_filename"]).lower()
        if not fname.endswith((".jpg", ".jpeg")):
            errors.append(f"{item_id}: bad filename {fname!r}")
            continue

        # Normalise `.jpeg` → `.jpg` to match the live endpoint.
        normalised = fname.replace(".jpeg", ".jpg")
        src = THUMBNAIL_DIR / normalised
        if not src.exists():
            missing_files.append(str(src))
            continue

        try:
            data = src.read_bytes()
        except Exception as e:
            errors.append(f"{item_id}: read failed for {src}: {e}")
            continue

        if not data.startswith(b"\xff\xd8"):
            errors.append(f"{item_id}: {src} is not a JPEG")
            continue

        key = f"on_demand/thumbnails/bulk/{normalised}"
        try:
            await _storage.storage.write_bytes(key, data, content_type="image/jpeg")
            uploaded += 1
        except Exception as e:
            errors.append(f"{item_id}: R2 write failed for {key}: {e}")
            continue

        r = await db.on_demand_items.update_one(
            {"id": item_id},
            {"$set": {
                "thumbnail_storage_key": key,
                "thumbnail_mime": "image/jpeg",
                "thumbnail_ext": "jpg",
            }},
        )
        if r.modified_count:
            updated += 1

    print(f"uploaded: {uploaded}")
    print(f"db updated: {updated}")
    print(f"missing files ({len(missing_files)}): {missing_files[:5]}"
          f"{' …' if len(missing_files) > 5 else ''}")
    print(f"errors ({len(errors)}): {errors[:5]}"
          f"{' …' if len(errors) > 5 else ''}")

    # Post-check
    remaining = await db.on_demand_items.count_documents({
        "thumbnail_filename": {"$exists": True, "$ne": None},
        "$or": [
            {"thumbnail_storage_key": {"$exists": False}},
            {"thumbnail_storage_key": None},
        ],
    })
    with_key = await db.on_demand_items.count_documents({
        "thumbnail_storage_key": {"$exists": True, "$ne": None},
    })
    print(f"post-check: {with_key} items with storage_key, "
          f"{remaining} still missing")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
