"""Seed the Zone 2 Walk/Light Jog test workout for iter189v UI test."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or "crewfit"
CLIENT_ID = "0b0651e2-3453-4c39-b858-b377e8284f8c"
WID = "iter189v_zone2_test_workout"
DATE = "2027-01-27"


async def main():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Delete any prior on same date to avoid unique-index collisions
    await db.workouts.delete_many({"id": WID})
    await db.workouts.delete_many({"user_id": CLIENT_ID, "date": DATE})

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": WID,
        "user_id": CLIENT_ID,
        "date": DATE,
        "title": "Zone 2 Row - Recovery Aerobic",
        "workout_type": "cardio",
        "focus": "cardio",
        "duration_min": 35,
        "warmup": [{
            "name": "Dynamic warm-up routine",
            "sets": 1, "reps": "5 min", "section": "warmup",
            "duration_sec": 300, "logging_type": "timer",
            "duration_sec_estimated": True,
        }],
        "exercises": [{
            "name": "Zone 2 Walk/Light Jog",
            "sets": 1, "reps": "25 min", "rest_sec": 0, "rpe": 4,
            "section": "main",
            "duration_sec": 1500,
            "logging_type": "timer",
            "duration_sec_estimated": True,
            "notes": "Keep this conversational and finish feeling fresh.",
        }],
        "cooldown": [{
            "name": "Walk", "sets": 1, "reps": "5 min", "section": "cooldown",
            "duration_sec": 300, "logging_type": "timer",
        }],
        "alternatives": {},
        "source": "TEST_iter189v_ui",
        "manual_lock": True,
        "coach_locked": True,
        "coach_edited": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.workouts.insert_one(doc)
    print(f"OK seeded workout id={WID} date={DATE} for user={CLIENT_ID}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
