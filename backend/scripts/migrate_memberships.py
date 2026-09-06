"""One-shot idempotent migration (Iter201 · Phase 1 Payments).

Actions:
1. Log every distinct `role` value in `db.users` and how many docs.
2. Identify which role values are treated as "client/member" — for CrewFit
   only ``role == "client"`` is a member. Everything else (`coach`, `admin`)
   is excluded.
3. Count how many client accounts have `membership_status == null OR missing`.
4. Set `membership_status = "complimentary"` on those. NEVER overwrite a
   docs that already carries a status value.
5. Ensure indexes exist on `subscriptions` and `stripe_webhook_events`.

Safe to re-run.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_BACKEND / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


async def main() -> int:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # (1) distinct roles
    roles = await db.users.aggregate([
        {"$group": {"_id": "$role", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]).to_list(50)
    print("=== distinct role values ===")
    for r in roles:
        print(f"  role={r['_id']!r:24s}  count={r['count']}")

    client_roles = ["client"]  # explicit — do NOT auto-widen
    print(f"\nclient/member roles being migrated: {client_roles}")

    # (2) audit + count
    target_filter = {
        "role": {"$in": client_roles},
        "$or": [
            {"membership_status": {"$exists": False}},
            {"membership_status": None},
        ],
    }
    to_update = await db.users.count_documents(target_filter)
    total_clients = await db.users.count_documents({"role": {"$in": client_roles}})
    already_set = await db.users.count_documents({
        "role": {"$in": client_roles},
        "membership_status": {"$exists": True, "$ne": None},
    })
    print(f"\ntotal client accounts:              {total_clients}")
    print(f"already have membership_status set: {already_set}")
    print(f"about to update to 'complimentary': {to_update}")

    # (3) apply
    if to_update > 0:
        r = await db.users.update_many(target_filter, {"$set": {
            "membership_status": "complimentary",
        }})
        print(f"\nmodified: {r.modified_count}")
    else:
        print("\nnothing to update — migration is a no-op.")

    # (4) indexes
    await db.subscriptions.create_index("stripe_subscription_id", unique=True)
    await db.subscriptions.create_index([("user_id", 1), ("status", 1)])
    await db.stripe_webhook_events.create_index("stripe_event_id", unique=True)
    print("\nindexes ensured: subscriptions, stripe_webhook_events")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
