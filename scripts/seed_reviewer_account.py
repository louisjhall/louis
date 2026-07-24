"""
Iter 95l — Seed / refresh the Apple App Store reviewer test account.

Creates or resets:
    email:    reviewer@crewfit.net
    password: CrewFitReview2026!

Populates every essential DNA field, a 7-day active roster, and 5 sample
workouts so the reviewer sees a fully functional experience the moment
they log in (no onboarding gate, no empty-state screens).

Idempotent — safe to run multiple times.
"""
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")
os.environ.setdefault("EMERGENT_LLM_KEY", "x")

import bcrypt
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

EMAIL = "reviewer@crewfit.net"
PASSWORD = "CrewFitReview2026!"
DISPLAY_NAME = "App Store Reviewer"


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main() -> None:
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = cli[os.environ.get("DB_NAME", "test_database")]

    # 1. Find Louis so we can assign him as coach
    louis = await db.users.find_one(
        {"email": "louis@crewfit.net"}, {"_id": 0, "id": 1, "name": 1}
    )
    if not louis:
        # Any coach will do as a fallback.
        louis = await db.users.find_one({"role": "coach"}, {"_id": 0, "id": 1, "name": 1})
    louis_id = (louis or {}).get("id")
    louis_name = (louis or {}).get("name") or "Louis Hall"

    # 2. Build the reviewer user document with a complete profile so no
    #    onboarding / DNA-assessment gate triggers.
    now = now_iso()
    profile = {
        "age": 32,
        "sex": "male",
        "biological_sex": "male",
        "height_cm": 180,
        "weight_kg": 78,
        "airline": "British Airways",
        "job_title": "First Officer",
        "crew_role": "pilot",
        "home_base": "London Heathrow",
        "timezone": "Europe/London",
        # 8 essential DNA fields — all present so the app never blocks.
        "primary_goal": "general_fitness",
        "main_goal_key": "general_fitness",
        "secondary_goals": ["build_strength", "improve_recovery"],
        "flying_type": "mixed",
        "training_days": 4,
        "time_home": 45,
        "time_layover": 30,
        "equipment_home": ["dumbbells", "kettlebell", "resistance_bands", "mat"],
        "hotel_gyms": "sometimes",
        "injuries": [],
        "no_go_movements": [],
        "setup_completed_at": now,
    }
    user_doc = {
        "email": EMAIL,
        "name": DISPLAY_NAME,
        "first_name": "App Store",
        "last_name": "Reviewer",
        "role": "client",
        "password_hash": hash_pw(PASSWORD),
        "onboarded": True,
        "age_confirmed": True,
        "age_confirmed_at": now,
        "status": "active",
        "profile": profile,
        "assigned_coach_id": louis_id,
        "assigned_coach_name": louis_name,
        "coach_id": louis_id,
        "updated_at": now,
    }

    # 3. Upsert (create fresh id on insert, keep existing id on update).
    existing = await db.users.find_one({"email": EMAIL}, {"_id": 0, "id": 1})
    if existing and existing.get("id"):
        uid = existing["id"]
        await db.users.update_one({"id": uid}, {"$set": user_doc})
        print(f"[user] updated existing reviewer  id={uid}")
    else:
        uid = "u_reviewer_" + uuid.uuid4().hex[:8]
        user_doc["id"] = uid
        user_doc["created_at"] = now
        await db.users.insert_one(user_doc)
        print(f"[user] inserted new reviewer      id={uid}")

    # 4. Seed a completed DNA assessment so downstream views don't nag.
    assessment_id = "a_reviewer_" + uid[-8:]
    assessment_answers = []
    for qid, val in [
        ("primary_goal", "general_fitness"),
        ("secondary_goals", ["build_strength", "improve_recovery"]),
        ("flying_type", "mixed"),
        ("training_days", 4),
        ("time_home", 45),
        ("time_layover", 30),
        ("equipment_home", ["dumbbells", "kettlebell", "resistance_bands", "mat"]),
        ("hotel_gyms", "sometimes"),
        ("injuries", []),
        ("no_go_movements", []),
        ("biological_sex", "male"),
        ("crew_role", "pilot"),
    ]:
        assessment_answers.append({"question_id": qid, "answer": val, "answered_at": now})
    await db.assessments.update_one(
        {"user_id": uid},
        {"$set": {
            "id": assessment_id,
            "user_id": uid,
            "answers": assessment_answers,
            "finalized": True,
            "finalized_at": now,
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    print(f"[assessment] seeded finalised DNA for reviewer")

    # 5. Deactivate any prior roster and drop a fresh 7-day one starting today.
    await db.rosters.update_many(
        {"user_id": uid, "is_active": True}, {"$set": {"is_active": False}}
    )
    today = date.today()
    rid = "r_reviewer_" + uuid.uuid4().hex[:6]
    day_types = ["Home", "Layover", "Layover", "Turnaround", "Off", "Home", "Home"]
    loads = [3, 5, 5, 4, 1, 3, 3]
    layover_cities = [None, "Dubai", "Dubai", None, None, None, None]
    days = []
    for i in range(7):
        d = (today + timedelta(days=i)).isoformat()
        days.append({
            "date": d,
            "day_type": day_types[i],
            "flights": ([{"number": "BA113", "from": "LHR", "to": "DXB"}] if i == 1 else []),
            "load": loads[i],
            "layover_city": layover_cities[i],
        })
    await db.rosters.insert_one({
        "id": rid,
        "user_id": uid,
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=6)).isoformat(),
        "days": days,
        "confirmed": True,
        "is_active": True,
        "created_at": now,
    })
    print(f"[roster] inserted 7-day roster       id={rid}")

    # 6. Fresh workouts across the week so the calendar and guided flow
    #    show meaningful content immediately.
    range_dates = [d["date"] for d in days]
    deleted = await db.workouts.delete_many(
        {"user_id": uid, "date": {"$in": range_dates}}
    )
    print(f"[workouts] cleared existing        n={deleted.deleted_count}")

    workout_plan = [
        # (offset_days, title, minutes, location, exercises)
        (0, "Home Strength — Full Body", 40, "Home", [
            {"name": "Goblet Squat", "sets": 3, "reps": 10, "rest_sec": 60},
            {"name": "Dumbbell Row", "sets": 3, "reps": 10, "rest_sec": 60},
            {"name": "Push-Up", "sets": 3, "reps": 12, "rest_sec": 60},
            {"name": "Glute Bridge", "sets": 3, "reps": 15, "rest_sec": 45},
        ]),
        (1, "Pre-Flight Mobility", 15, "Home", [
            {"name": "Cat-Cow", "sets": 1, "reps": 8, "rest_sec": 0},
            {"name": "Thoracic Rotation (Quadruped)", "sets": 1, "reps": 8, "rest_sec": 0},
            {"name": "90/90 Hip Stretch", "sets": 1, "reps": 8, "rest_sec": 0},
        ]),
        (2, "Hotel Mobility Flow", 20, "Hotel", [
            {"name": "Deep breathing x 5", "sets": 1, "reps": 5, "rest_sec": 0},
            {"name": "Cat-Cow", "sets": 1, "reps": 8, "rest_sec": 0},
            {"name": "Single-leg glute bridge", "sets": 2, "reps": 10, "rest_sec": 30},
            {"name": "World's Greatest Stretch", "sets": 1, "reps": 6, "rest_sec": 0},
        ]),
        (3, "Post-Flight Recovery", 25, "Home", [
            {"name": "Foam Roll — Calves", "sets": 1, "reps": 8, "rest_sec": 0},
            {"name": "Glute Bridge", "sets": 3, "reps": 12, "rest_sec": 45},
            {"name": "Dead Bug", "sets": 3, "reps": 10, "rest_sec": 30},
        ]),
        (5, "Strength for Runners", 45, "Home", [
            {"name": "Bulgarian Split Squat", "sets": 3, "reps": 8, "rest_sec": 75},
            {"name": "Romanian Deadlift", "sets": 3, "reps": 10, "rest_sec": 75},
            {"name": "Single-leg glute bridge", "sets": 3, "reps": 10, "rest_sec": 45},
            {"name": "Plank", "sets": 3, "reps": 30, "rest_sec": 30},
        ]),
    ]
    for offset, title, minutes, location, exercises in workout_plan:
        d = (today + timedelta(days=offset)).isoformat()
        w = {
            "id": "w_reviewer_" + uuid.uuid4().hex[:8],
            "user_id": uid,
            "date": d,
            "title": title,
            "duration_min": minutes,
            "estimated_minutes": minutes,
            "day_load": 5 if minutes >= 40 else 3,
            "location": location,
            "warmup": [
                {"name": "Deep breathing x 5", "duration_sec": 45},
                {"name": "Cat-cow x 6", "duration_sec": 45},
            ],
            "exercises": exercises,
            "completed": False,
            "coach_locked": False,
            "needs_coach_review": False,
            "approved": True,
            "optional": False,
            "key_session": (offset == 0),
            "roster_id": rid,
            "created_at": now,
            "updated_at": now,
        }
        await db.workouts.insert_one(w)
        print(f"[workouts] +{offset}d  {title!r}  ({minutes}min, {location})")

    print("\n✅ Reviewer account ready:")
    print(f"   Email:    {EMAIL}")
    print(f"   Password: {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
