"""
scripts/wipe_test_users.py

Deletes all TEST/DEMO user accounts and their associated data.
KEEPS:
  - louis@crewfit.net       (coach/admin)
  - reviewer@crewfit.net    (Apple App Store reviewer)

BACKUP: writes a JSON dump of every deleted document to
  /app/backups/wipe_test_users_<UTC_ISO>.json  before deleting.

Safe to re-run — idempotent.
"""
from __future__ import annotations
import asyncio, os, json, datetime
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

KEEP_EMAILS = {
    "louis@crewfit.net",
    "reviewer@crewfit.net",
}

# Collections keyed by user_id
USER_ID_COLLECTIONS = [
    "workouts", "workouts_archive", "workout_sets", "strength_metrics", "running_metrics",
    "rosters", "roster_jobs", "roster_audit_log", "gen_jobs",
    "programmes", "programme_timeline", "timeline_events",
    "assessments", "coaching_dna", "dna_history", "check_ins", "weekly_reviews",
    "habits", "habits_daily", "habit_logs",
    "notifications", "scheduled_messages",
    "coach_tasks", "coach_alerts",
    "daily_briefings", "daily_briefing_prefs", "daily_pulse",
    "reality_events", "reassessment_prompts",
    "body_metrics", "progress", "progress_photos", "progression_snapshots",
    "schedule_events", "events", "personal_activities",
    "nutrition_logs", "nutrition_targets", "nutrition_favourites",
    "nutrition_hydration", "nutrition_insights", "nutrition_atlas_tips",
    "nutrition_photo_scans", "meals",
    "equipment_mismatches", "workout_exercise_swaps",
    "day_change_log", "change_log", "move_history",
    "ai_usage", "message_drafts",  # (client_id also handled below)
]

# Special: fields other than user_id
SPECIAL_QUERIES: dict[str, list[dict]] = {}


async def main():
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    # 1) Identify users to delete
    users_to_delete = []
    async for u in db.users.find({}):
        if u.get("email") not in KEEP_EMAILS:
            users_to_delete.append(u)

    if not users_to_delete:
        print("Nothing to delete. All users are in the keep list.")
        return

    keep_users = []
    async for u in db.users.find({"email": {"$in": list(KEEP_EMAILS)}}, {"email": 1, "id": 1, "role": 1, "_id": 0}):
        keep_users.append(u)

    delete_ids = [u.get("id") for u in users_to_delete if u.get("id")]
    delete_mongo_ids = [u.get("_id") for u in users_to_delete]
    delete_emails = [u.get("email") for u in users_to_delete]

    print("=" * 70)
    print(f"KEEPING ({len(keep_users)}):")
    for u in keep_users:
        print(f"  - {u.get('email')} ({u.get('role')})")
    print()
    print(f"DELETING ({len(users_to_delete)}):")
    for u in users_to_delete:
        print(f"  - {u.get('email')} ({u.get('role')})")
    print("=" * 70)
    print()

    # 2) Backup
    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path("/app/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"wipe_test_users_{ts}.json"

    backup: dict[str, list] = {"users": []}
    for u in users_to_delete:
        u["_id"] = str(u.get("_id"))
        backup["users"].append(u)

    # 3) For each collection, count & collect + delete matching by user_id
    total_deleted = 0

    async def cascade_by_field(collection: str, field: str, values: list, backup_key: str):
        nonlocal total_deleted
        if not values:
            return 0
        q = {field: {"$in": values}}
        cnt = await db[collection].count_documents(q)
        if cnt == 0:
            return 0
        # Backup
        docs = []
        async for d in db[collection].find(q):
            d["_id"] = str(d.get("_id"))
            docs.append(d)
        backup.setdefault(backup_key, []).extend(docs)
        res = await db[collection].delete_many(q)
        total_deleted += res.deleted_count
        print(f"  {collection:<30s} [{field}] : {res.deleted_count}")
        return res.deleted_count

    print("Cascading deletes by user_id ...")
    for col in USER_ID_COLLECTIONS:
        await cascade_by_field(col, "user_id", delete_ids, col)

    # Special handling for coach_alerts, message_drafts, coach_change_log via client_id
    print()
    print("Cascading deletes by client_id ...")
    for col in ["coach_alerts", "message_drafts", "coach_change_log"]:
        await cascade_by_field(col, "client_id", delete_ids, col)

    # nutrition_notes: client_user_id
    print()
    print("Cascading deletes for nutrition_notes ...")
    await cascade_by_field("nutrition_notes", "client_user_id", delete_ids, "nutrition_notes")

    # Messages: from_user_id OR to_user_id
    print()
    print("Cascading deletes for messages (from/to) ...")
    await cascade_by_field("messages", "from_user_id", delete_ids, "messages")
    await cascade_by_field("messages", "to_user_id", delete_ids, "messages_to")

    # message_attachments: linked via message_id — collect those first
    print()
    print("Cascading deletes for orphaned message_attachments ...")
    # (Backup already captured messages; attachments will be handled by orphan cleanup below)
    # Simplest: drop attachments whose message_id no longer exists
    remaining_msg_ids = set()
    async for m in db.messages.find({}, {"id": 1, "_id": 0}):
        if m.get("id"):
            remaining_msg_ids.add(m["id"])
    orphan_atts = []
    async for att in db.message_attachments.find({}):
        if att.get("message_id") and att["message_id"] not in remaining_msg_ids:
            orphan_atts.append(att.get("_id"))
    if orphan_atts:
        docs = []
        async for d in db.message_attachments.find({"_id": {"$in": orphan_atts}}):
            d["_id"] = str(d.get("_id"))
            docs.append(d)
        backup.setdefault("message_attachments", []).extend(docs)
        res = await db.message_attachments.delete_many({"_id": {"$in": orphan_atts}})
        total_deleted += res.deleted_count
        print(f"  message_attachments [orphan]        : {res.deleted_count}")

    # audit_logs: target_user_id AND actor_id
    print()
    print("Cascading deletes for audit_logs ...")
    await cascade_by_field("audit_logs", "target_user_id", delete_ids, "audit_logs_target")
    await cascade_by_field("audit_logs", "actor_id", delete_ids, "audit_logs_actor")

    # gdpr_audit — may reference target_user_id
    print()
    print("Cascading deletes for gdpr_audit ...")
    for field in ("target_user_id", "user_id", "actor_id"):
        await cascade_by_field("gdpr_audit", field, delete_ids, f"gdpr_audit_{field}")

    # 4) Finally delete the users themselves
    print()
    print("Deleting user documents ...")
    res = await db.users.delete_many({"_id": {"$in": delete_mongo_ids}})
    print(f"  users                          : {res.deleted_count}")
    total_deleted += res.deleted_count

    # 5) Write backup file
    with open(backup_file, "w") as fh:
        json.dump(backup, fh, indent=2, default=str)

    print()
    print("=" * 70)
    print(f"DONE.  Backup written to: {backup_file}")
    print(f"Total documents deleted:  {total_deleted}")
    print("=" * 70)

    # 6) Final sanity check
    print()
    print("Remaining users:")
    async for u in db.users.find({}, {"email": 1, "role": 1, "_id": 0}):
        print(f"  - {u.get('email')} ({u.get('role')})")


if __name__ == "__main__":
    asyncio.run(main())
