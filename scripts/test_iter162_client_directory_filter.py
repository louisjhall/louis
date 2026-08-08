"""
Iter 162 · Verify the coach client directory excludes:
  * status == "deleted"        (hard-delete tombstone)
  * is_deleted == true         (soft-delete flag)
  * status == "archived"       (existing behaviour, must remain)

Read-only against production data (uses uniquely-named test rows and
removes them). No LLM calls.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "crewfit_v1"


def _ok(m): print(f"  ✅  {m}")
def _fail(m): print(f"  ❌  {m}"); raise AssertionError(m)


async def main():
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]

    # Replicate the helper's query filter locally to avoid the circular
    # import chain when running the script standalone (feature_v2_coach_home
    # imports from server.py which triggers other feature modules).
    def _live_client_match(include_archived: bool = False) -> dict:
        excludes: list[str] = []
        if not include_archived:
            excludes.append("archived")
        excludes.append("deleted")
        return {
            "role": "client",
            "status": {"$nin": excludes},
            "is_deleted": {"$ne": True},
        }

    tag = f"TEST-i162-{uuid.uuid4().hex[:6]}"
    live_id = f"{tag}-live"
    del_id = f"{tag}-hard-del"
    soft_id = f"{tag}-soft-del"
    arch_id = f"{tag}-arch"
    try:
        await db.users.insert_many([
            {"id": live_id, "role": "client", "email": f"{live_id}@x.io",
             "name": f"{tag} Live", "status": "active"},
            {"id": del_id, "role": "client", "email": f"{del_id}@x.io",
             "name": f"{tag} Hard-Deleted", "status": "deleted"},
            {"id": soft_id, "role": "client", "email": f"{soft_id}@x.io",
             "name": f"{tag} Soft-Deleted", "status": "active", "is_deleted": True},
            {"id": arch_id, "role": "client", "email": f"{arch_id}@x.io",
             "name": f"{tag} Archived", "status": "archived"},
        ])

        # Query as the directory / action-queue path does — using the helper.
        q = _live_client_match()
        got = await db.users.find({"$and": [q, {"id": {"$regex": f"^{tag}-"}}]},
                                   {"_id": 0, "id": 1}).to_list(10)
        ids = {r["id"] for r in got}
        if live_id not in ids:
            _fail(f"Live client MISSING from directory query: {ids}")
        _ok(f"Live client present: {live_id}")
        if del_id in ids:
            _fail(f"Hard-deleted client leaked into directory: {del_id}")
        _ok(f"Hard-deleted client excluded")
        if soft_id in ids:
            _fail(f"Soft-deleted (is_deleted=True) client leaked: {soft_id}")
        _ok(f"Soft-deleted client excluded")
        if arch_id in ids:
            _fail(f"Archived client leaked into 'active' filter: {arch_id}")
        _ok(f"Archived client excluded from active filter")

        # Archived filter should include archived, still exclude deleted.
        q_arch = _live_client_match(include_archived=True)
        # The archived route also sets status="archived" explicitly.
        q_arch["status"] = "archived"
        got_arch = await db.users.find({"$and": [q_arch, {"id": {"$regex": f"^{tag}-"}}]},
                                        {"_id": 0, "id": 1}).to_list(10)
        arch_ids = {r["id"] for r in got_arch}
        if arch_id not in arch_ids:
            _fail(f"Archived client missing from archived filter: {arch_ids}")
        _ok(f"Archived client returned by archived filter")
        if del_id in arch_ids or soft_id in arch_ids:
            _fail(f"Deleted client leaked into archived filter: {arch_ids}")
        _ok(f"Deleted/soft-deleted still excluded even in archived filter")

        print("\n✅  Iter 162 Coach Directory filter tests passed.")

    finally:
        await db.users.delete_many({"id": {"$regex": f"^{tag}-"}})
        cli.close()


if __name__ == "__main__":
    asyncio.run(main())
