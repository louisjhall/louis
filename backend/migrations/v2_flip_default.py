"""
Phase A + Phase C migration — flip V2 flags on for every user, and
optionally delete all V1 test client data.

Usage (from /app/backend):

    # Just flip V2 flags — safe, non-destructive
    python migrations/v2_flip_default.py --flags-only

    # Full reset: flip flags AND delete all client data (per user request:
    # 'you can delete any user data')
    python migrations/v2_flip_default.py --wipe-clients

Coach accounts (louis@crewfit.net + reviewer@crewfit.net) are always
preserved. Everything else is fair game.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Make backend imports resolve when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

# Load .env from /app/backend/.env
_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
load_dotenv(_BACKEND_DIR / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from feature_v2_defaults import (  # noqa: E402
    default_client_v2_flags, default_coach_v2_flags,
)


# Collections that hold client-scoped state and should be wiped for a
# full reset. This list is intentionally comprehensive — the user said
# "you can delete any user data".
CLIENT_SCOPED_COLLECTIONS: list[str] = [
    # V2 pipeline
    "programmes_v2",
    "training_objectives",
    "phase_plans",
    "plan_drafts",
    "plan_versions",
    "plan_snapshots",
    "approvals",
    "workout_assignments",
    "workout_implementations",
    "change_sets",
    "coach_directives",
    "decision_records",
    "reality_events",
    "target_events",
    "progression_signals",
    "demand_queue_items",
    "roster_facets",
    "goals_v2",
    "phase_transitions",
    # V1 pipeline
    "workouts",
    "checkins",
    "checkin_answers",
    "programmes",
    "programme_history",
    "roster_entries",
    "rosters",
    "roster_uploads",
    "messages",
    "scheduled_messages",
    "coach_notes",
    "client_events",
    "training_history",
    "achievements",
    "personal_records",
    "meal_plans",
    "nutrition_logs",
    "habit_reviews",
    "assessment_answers",
    "reassessments",
    "audit_logs",
    "reality_history",
]


PRESERVED_EMAILS = {
    "louis@crewfit.net",
    "reviewer@crewfit.net",
}


async def flip_flags(db, dry_run: bool = False) -> dict:
    """Enable V2 flags for every user in the DB.

    Clients get the full client flag bundle, coaches get the coach
    dashboard bundle."""
    updated_clients = 0
    updated_coaches = 0
    skipped = 0
    async for u in db.users.find({}, {"_id": 0, "id": 1, "email": 1, "role": 1, "profile.v2_flags": 1}):
        role = u.get("role")
        if role == "client":
            flags = default_client_v2_flags()
        elif role == "coach":
            flags = default_coach_v2_flags()
        else:
            skipped += 1
            continue
        flags = {**flags, "updated_at": "2026-06-01T00:00:00Z", "updated_by": "migration_v2_default"}
        if dry_run:
            print(f"[dry-run] would update {u.get('email')} ({role})")
        else:
            await db.users.update_one(
                {"id": u["id"]},
                {"$set": {"profile.v2_flags": flags}},
            )
        if role == "client":
            updated_clients += 1
        else:
            updated_coaches += 1
    return {
        "clients_flipped": updated_clients,
        "coaches_flipped": updated_coaches,
        "skipped_other_roles": skipped,
    }


async def wipe_clients(db, dry_run: bool = False) -> dict:
    """Delete every client user + all client-scoped collections.

    Coach accounts in PRESERVED_EMAILS are kept intact.
    """
    # 1) Delete all client users except preserved ones
    clients_deleted = 0
    async for u in db.users.find({"role": "client"}, {"_id": 0, "id": 1, "email": 1}):
        email = (u.get("email") or "").lower()
        if email in PRESERVED_EMAILS:
            continue
        if dry_run:
            print(f"[dry-run] would delete client {email} ({u['id']})")
        else:
            await db.users.delete_one({"id": u["id"]})
        clients_deleted += 1

    # 2) Wipe all client-scoped collections wholesale.
    coll_stats: dict[str, int] = {}
    for coll in CLIENT_SCOPED_COLLECTIONS:
        try:
            cnt = await db[coll].count_documents({})
            if cnt == 0:
                continue
            if dry_run:
                print(f"[dry-run] would drop {cnt} docs from '{coll}'")
                coll_stats[coll] = cnt
            else:
                res = await db[coll].delete_many({})
                coll_stats[coll] = res.deleted_count
        except Exception as e:
            print(f"! could not wipe {coll}: {e}")

    return {"clients_deleted": clients_deleted, "collections_wiped": coll_stats}


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--flags-only", action="store_true",
                   help="Only flip V2 flags. Do not delete any user data.")
    p.add_argument("--wipe-clients", action="store_true",
                   help="Also delete all client accounts and client-scoped collections.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print planned changes without touching the DB.")
    args = p.parse_args()

    if not (args.flags_only or args.wipe_clients):
        p.error("Choose one of --flags-only or --wipe-clients (or both).")

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "crewfit_v1")]

    print(f"Connected: {os.environ.get('MONGO_URL')} · db={os.environ.get('DB_NAME')}")
    if args.dry_run:
        print("=== DRY RUN — nothing will be modified ===")

    if args.wipe_clients:
        print("\n=== WIPING CLIENT DATA ===")
        w = await wipe_clients(db, dry_run=args.dry_run)
        print(f"  clients_deleted: {w['clients_deleted']}")
        for c, n in w["collections_wiped"].items():
            print(f"  wiped {n:>6} docs from {c}")

    print("\n=== FLIPPING V2 FLAGS ===")
    f = await flip_flags(db, dry_run=args.dry_run)
    print(f"  clients flipped: {f['clients_flipped']}")
    print(f"  coaches flipped: {f['coaches_flipped']}")
    print(f"  skipped (other roles): {f['skipped_other_roles']}")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
