"""One-off admin script to wipe all non-baseline user accounts.

Run from /app/backend:  python3 scripts/wipe_users.py

Keeps ONLY:
  - louis@crewfit.net    (admin / main coach)
  - preview@crewfit.test (persistent New Client Preview sandbox)
  - client@crewfit.com   (demo client used in test suites)
  - coach@crewfit.com    (legacy coach, kept archived for test compat)

Every other user + ALL their data is deleted so their emails become
available for fresh signups. Safe to run repeatedly.
"""
import asyncio
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

KEEP_EMAILS = {
    "louis@crewfit.net",
    "preview@crewfit.test",
    "client@crewfit.com",
    "coach@crewfit.com",
}


async def go() -> None:
    c = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = c[os.getenv("DB_NAME", "crewfit")]

    to_delete = await db.users.find(
        {"email": {"$nin": list(KEEP_EMAILS)}},
        {"_id": 0, "id": 1, "email": 1, "role": 1},
    ).to_list(10000)

    if not to_delete:
        print("Nothing to wipe — user table already at baseline.")
        return

    print(f"Wiping {len(to_delete)} accounts:")
    for u in to_delete:
        print(f"  - {u.get('email')} ({u.get('role')})")

    ids = [u["id"] for u in to_delete]

    collections = [
        "users",
        "rosters", "roster_jobs", "roster_confirmations",
        "workouts", "workout_sets", "workout_exercise_swaps",
        "habits", "habit_logs", "habit_reviews", "habit_starter_recommendations",
        "nutrition_logs", "nutrition_targets", "nutrition_favourites",
        "nutrition_insights", "nutrition_travel_cache", "nutrition_checkin_answers",
        "checkins", "messages", "message_drafts", "coach_alerts",
        "day_overrides", "day_change_log", "standby_days", "sickness_days",
        "schedule_events", "events", "coaching_dna", "assessments",
        "programmes", "personal_activities", "personal_records",
        "gen_jobs", "reassessment_prompts", "notification_events",
        "notification_settings", "push_tokens", "coaching_dna_answers",
        "change_log", "audit_logs", "preview_audit",
    ]

    for coll in collections:
        try:
            if coll == "users":
                r = await db.users.delete_many({"id": {"$in": ids}})
            else:
                r = await db[coll].delete_many({"user_id": {"$in": ids}})
            if r.deleted_count:
                print(f"  {coll}: -{r.deleted_count}")
        except Exception as e:
            print(f"  {coll}: skipped ({e})")

    remaining = await db.users.count_documents({})
    print(f"\nRemaining users: {remaining}")
    async for u in db.users.find({}, {"_id": 0, "email": 1, "role": 1, "status": 1}):
        print(f"  - {u.get('email')} ({u.get('role')}, {u.get('status', 'active')})")


if __name__ == "__main__":
    asyncio.run(go())
