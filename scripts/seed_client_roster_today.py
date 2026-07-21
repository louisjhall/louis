"""Seed a roster covering today for client@crewfit.com, and create matching workouts for testing the long-press day picker."""
import asyncio, os, sys
sys.path.insert(0, '/app/backend')
os.environ.setdefault("EMERGENT_LLM_KEY","x")
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import date, timedelta
import uuid

async def main():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    cli = AsyncIOMotorClient(mongo_url)
    db = cli[db_name]

    # Find client user
    user = await db.users.find_one({"email":"client@crewfit.com"})
    print("user:", user["id"], user.get("name"))

    # Deactivate existing rosters
    await db.rosters.update_many({"user_id": user["id"], "is_active": True}, {"$set": {"is_active": False}})

    today = date.today()
    start = today
    end = today + timedelta(days=6)
    rid = "r_test_" + uuid.uuid4().hex[:6]
    days = []
    types = ["Turnaround","Layover","Layover","Off","Standby","Off","Home"]
    for i in range(7):
        d = today + timedelta(days=i)
        days.append({
            "date": d.isoformat(),
            "day_type": types[i],
            "flights": [],
            "load": 5 if types[i] in ("Turnaround","Layover") else 2,
        })

    roster = {
        "id": rid,
        "user_id": user["id"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": days,
        "confirmed": True,
        "confirmed_at": None,
        "is_active": True,
        "created_at": today.isoformat(),
    }
    await db.rosters.insert_one(roster)
    print("Inserted roster:", rid, start, "->", end)

    # Delete any existing workouts in the 7-day window to avoid unique-index conflicts
    range_dates = [d["date"] for d in days]
    delete_res = await db.workouts.delete_many({"user_id": user["id"], "date": {"$in": range_dates}})
    print("deleted existing workouts:", delete_res.deleted_count)

    # Create simple workouts for the 7 days (except pure off/home) so we get workout rows to long-press.
    for i, day in enumerate(days):
        wid = "w_test_" + uuid.uuid4().hex[:6]
        w = {
            "id": wid,
            "user_id": user["id"],
            "date": day["date"],
            "title": f"Test Workout {i+1}",
            "duration_min": 30,
            "day_load": day["load"],
            "location": "Hotel Gym" if day["day_type"] == "Layover" else "Home",
            "exercises": [{"name":"Push-ups","sets":3,"reps":10}],
            "completed": False,
            "coach_locked": False,
            "needs_coach_review": False,
            "approved": True,
            "optional": False,
            "roster_id": rid,
        }
        await db.workouts.insert_one(w)
    print("Inserted 7 workouts")

    # Ensure onboarding done - not strictly needed but safe
    # verify
    r2 = await db.rosters.find_one({"id": rid}, {"_id":0})
    print("verify roster days:", len(r2["days"]), r2["start_date"], r2["end_date"])

asyncio.run(main())
