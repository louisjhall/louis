"""Seed a Tempo Back Squat workout for testclient@crewfit.net so we can
visually verify iter166 (logging_type is source of truth, tempo removed
from cardio regex, +2pt fonts, card spacing).

Run:
    cd /app/backend && python /app/scripts/seed_tempo_back_squat.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")


async def main() -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    user = await db.users.find_one({"email": "client@crewfit.com"})
    if not user:
        print("testclient user not found; aborting")
        return
    uid = user.get("id") or str(user["_id"])

    today = datetime.now(timezone.utc).date()
    # Remove any existing workout for today so we don't collide
    await db.workouts.delete_many({"user_id": uid, "date": today.isoformat()})

    wid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    exercises = [
        {
            "id": str(uuid.uuid4()),
            "name": "Tempo Back Squat",
            "sets": 4,
            "reps": 6,
            "load": "70",
            "rest_sec": 180,
            "tempo": "3-1-1-0",
            "logging_type": "strength",   # explicit — must NOT flip to cardio
            "notes": "Pause 1s in the hole. Drive knees out.",
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Bulgarian Split Squat",
            "sets": 3,
            "reps": 10,
            "load": "20",
            "rest_sec": 90,
            "logging_type": "strength",
        },
        {
            "id": str(uuid.uuid4()),
            "name": "Zone 2 Row",
            "duration_sec": 900,
            "logging_type": "cardio",     # sanity check — cardio still routes correctly
        },
    ]

    doc = {
        "id": wid,
        "user_id": uid,
        "date": today.isoformat(),
        "title": "Lower · Strength (Tempo Focus)",
        "workout_type": "strength",
        "duration_min": 55,
        "location": "home_gym",
        "coach_notes": "Iter166 verification workout — Tempo Back Squat must render kg + reps.",
        "warmup": [],
        "exercises": exercises,
        "cooldown": [],
        "source": "coach_manual",
        "manual_lock": True,
        "coach_locked": True,
        "approved": True,
        "created_at": now,
        "updated_at": now,
    }
    await db.workouts.insert_one(doc)
    print(f"Seeded workout {wid} for {uid} on {today.isoformat()}")
    print("Exercises:")
    for e in exercises:
        print(f"  - {e['name']}  logging_type={e['logging_type']}")


if __name__ == "__main__":
    asyncio.run(main())
