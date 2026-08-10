"""
seed_landing_demo.py — TEMPORARY seed for landing-page screenshots only.
Populates Alex Rivera's roster + a few workouts + a nutrition entry so
the calendar, workout player, and nutrition screens render cleanly.
Safe to re-run — idempotent-ish: it replaces Alex's active roster and
inserts workouts/nutrition only if missing for that date.

Zero LLM calls. Zero external network. Local Mongo only.
"""
import asyncio, os, sys
from datetime import date, timedelta, datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import uuid

load_dotenv("/app/backend/.env")
UID = "0b0651e2-3453-4c39-b858-b377e8284f8c"
TODAY = date.today()

def _iso_now():
    return datetime.now(timezone.utc).isoformat()

def _mk_day(d: date, day_type: str, **k):
    # day_type: home_day, training, duty, standby, layover, turnaround, rest
    presets = {
        "home_day":   dict(client_label="Home", training_colour="green", load="blue",
                           reason="Full day free — good main-training slot.",
                           recommended=["main_strength","intervals","tempo","mobility"], blocked=[]),
        "training":   dict(client_label="Training", training_colour="green", load="blue",
                           reason="Scheduled training day.",
                           recommended=["main_strength","hyrox","intervals"], blocked=[]),
        "duty":       dict(client_label="Duty", training_colour="amber", load="amber",
                           reason="On duty — short mobility recommended.",
                           recommended=["mobility","hotel_strength","easy_run"],
                           blocked=["long_run","intervals","main_strength"]),
        "standby":    dict(client_label="Standby", training_colour="amber", load="amber",
                           reason="On standby — light/short session in case you're called.",
                           recommended=["mobility","bodyweight","easy_run"],
                           blocked=["long_run","intervals","main_strength"]),
        "layover":    dict(client_label="Layover", training_colour="amber", load="amber",
                           reason="Layover — hotel-friendly session.",
                           recommended=["hotel_strength","bodyweight","easy_run"],
                           blocked=["heavy_barbell"]),
        "turnaround": dict(client_label="Turnaround", training_colour="red", load="red",
                           reason="Turnaround day — recovery only.",
                           recommended=["mobility","walk"], blocked=["intervals","main_strength"]),
        "rest":       dict(client_label="Rest", training_colour="green", load="blue",
                           reason="Recovery day.", recommended=["walk","mobility"], blocked=[]),
    }
    p = presets[day_type]
    row = {
        "date": d.isoformat(),
        "weekday": d.strftime("%a"),
        "day_type": day_type,
        "report_time": k.get("report_time"),
        "release_time": k.get("release_time"),
        "standby_start": k.get("standby_start"),
        "standby_end": k.get("standby_end"),
        "layover_city": k.get("layover_city"),
        "flights": k.get("flights", []),
        "sector_count": len(k.get("flights", [])),
        "is_out_of_base": bool(k.get("layover_city")),
        "is_overnight": day_type in ("layover", "turnaround"),
        "is_turnaround": day_type == "turnaround",
        "is_layover_day": day_type == "layover",
        "training_impact": p["training_colour"],
        "confidence": 0.98,
        "notes": None,
        "warnings": [],
        "needs_review": False,
        "source": "landing_demo_seed",
        "load": p["load"],
        "home_or_away": "away" if p.get("layover_city") or day_type in ("layover", "turnaround") else "home",
        "label": day_type.upper(),
        "client_label": p["client_label"],
        "training_colour": p["training_colour"],
        "recommended": p["recommended"],
        "blocked": p["blocked"],
        "equipment_assumption": "hotel_or_bodyweight" if day_type in ("standby","layover","duty","turnaround") else "any",
        "recovery_risk": 0.2,
        "reason": p["reason"],
        "chain_flag": None,
    }
    return row


async def main():
    c = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = c[os.getenv("DB_NAME", "crewfit_v1")]

    # ----- Build a rolling roster window: 10 days back → 25 days ahead -----
    start = TODAY - timedelta(days=10)
    end   = TODAY + timedelta(days=25)

    # Sensible mix — home / training / duty / standby / layover / turnaround / rest
    cycle = [
        ("home_day", {}),
        ("training", {}),
        ("duty",     {"report_time": "06:15", "release_time": "10:30",
                      "flights": [{"number":"CF412","from":"LHR","to":"AMS"},
                                  {"number":"CF413","from":"AMS","to":"LHR"}]}),
        ("home_day", {}),
        ("standby",  {"standby_start":"05:00","standby_end":"13:00"}),
        ("duty",     {"report_time":"14:20","release_time":"20:10",
                      "flights":[{"number":"CF884","from":"LHR","to":"MAD"},
                                 {"number":"CF885","from":"MAD","to":"LHR"}]}),
        ("training", {}),
        ("layover",  {"layover_city":"New York",
                      "flights":[{"number":"CF178","from":"LHR","to":"JFK"}]}),
        ("layover",  {"layover_city":"New York"}),
        ("turnaround", {"flights":[{"number":"CF179","from":"JFK","to":"LHR"}]}),
        ("rest",     {}),
        ("home_day", {}),
        ("training", {}),
        ("duty",     {"report_time":"07:00","release_time":"12:15",
                      "flights":[{"number":"CF221","from":"LHR","to":"CDG"},
                                 {"number":"CF222","from":"CDG","to":"LHR"}]}),
    ]

    days = []
    for i, d in enumerate([start + timedelta(days=n) for n in range((end - start).days + 1)]):
        day_type, extras = cycle[i % len(cycle)]
        days.append(_mk_day(d, day_type, **extras))

    # Deactivate old rosters; upsert one new active roster
    await db.rosters.update_many({"user_id": UID}, {"$set": {"is_active": False}})
    rid = f"r_landing_{uuid.uuid4().hex[:8]}"
    await db.rosters.insert_one({
        "id": rid,
        "user_id": UID,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "is_active": True,
        "status": "confirmed",
        "days": days,
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "airline_detected": "Demo Airline",
        "source": "landing_demo_seed",
    })

    # ----- Workouts for today + a few upcoming/past -----
    # Delete existing landing-seed workouts to be idempotent
    await db.workouts.delete_many({"user_id": UID, "source": "landing_demo_seed"})

    def _wk(d, title, focus, minutes, exercises, completed=False):
        return {
            "id": str(uuid.uuid4()),
            "user_id": UID,
            "date": d.isoformat(),
            "date_local": d.isoformat(),
            "title": title,
            "focus": focus,
            "session_type": focus,
            "workout_type": focus,
            "location": "home",
            "equipment_context": "dumbbells",
            "duration_min": minutes,
            "estimated_minutes": minutes,
            "duration_minutes": minutes,
            "completed": completed,
            "status": "completed" if completed else "planned",
            "approved": True,
            "coach_notes": ("Warm up 5 min. Keep intensity RPE 7. "
                           "Rest 60s between sets. Log RPE at end."),
            "warmup": [
                {"name":"Dynamic Warm-up", "duration_sec":300},
            ],
            "exercises": exercises,
            "source": "landing_demo_seed",
            "created_at": _iso_now(),
        }

    def _ex(name, sets, reps, rest, image_url=None, video_url=None, coaching_cue=None):
        return {
            "exercise_id": str(uuid.uuid4()),
            "name": name,
            "sets": sets,
            "reps": reps,
            "volume": reps,
            "unit": "reps",
            "rest_sec": rest,
            "rest_seconds": rest,
            "image_url": image_url or "https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?w=800",
            "primary_video_url": video_url,
            "coaching_cue": coaching_cue or "Brace core, control the eccentric.",
            "notes": coaching_cue or "Brace core, control the eccentric.",
        }

    workouts = []
    # Traffic-light story: match workout intensity to day_type
    workout_plans = [
        # (offset_days, title, focus, minutes, exercises_key, completed)
        (-9, "Home Strength — Upper Body", "strength", 55, "upper_home", True),
        (-8, "Layover Mobility — Hotel Reset", "mobility", 25, "mobility", True),
        (-6, "Post-Duty Reset", "mobility", 20, "mobility", True),
        (-5, "Home Conditioning — HYROX Style", "conditioning", 40, "hyrox", True),
        (-3, "Layover Strength — Full Body", "strength", 40, "layover", True),
        (-2, "Home Strength — Full Body", "strength", 45, "fullbody_home", True),
        (-1, "Post-Duty Mobility", "mobility", 20, "mobility", True),
        (0,  "Layover Strength — Hotel", "strength", 40, "layover", False),
        (1,  "Post-Duty Mobility", "mobility", 20, "mobility", False),
        (2,  "Home Strength — Lower Body", "strength", 50, "lower_home", False),
        (3,  "Layover Cardio — Hotel Treadmill", "cardio", 30, "cardio", False),
        (5,  "Home Strength — Push", "strength", 45, "push_home", False),
        (7,  "Layover Mobility — Recovery", "mobility", 25, "mobility", False),
        (9,  "Home Conditioning", "conditioning", 35, "hyrox", False),
        (11, "Post-Duty Reset", "mobility", 20, "mobility", False),
        (13, "Home Strength — Full Body", "strength", 50, "fullbody_home", False),
    ]
    ex_bank = {
        "upper_home": [
            _ex("Dumbbell Bench Press", 4, 8, 90, coaching_cue="Tuck elbows ~45°; drive feet."),
            _ex("Dumbbell Row", 4, 10, 75, coaching_cue="Pull elbow to hip; squeeze."),
            _ex("Overhead Press", 3, 8, 90, coaching_cue="Ribs down; brace core."),
            _ex("Face Pull", 3, 15, 45, coaching_cue="Elbows high; pull to eyes."),
        ],
        "layover": [
            _ex("Goblet Squat", 4, 10, 60,
                image_url="https://images.unsplash.com/photo-1517836357463-d25dfeac3438?w=800",
                coaching_cue="Sit between your heels; drive knees out."),
            _ex("Dumbbell Row", 3, 12, 60,
                image_url="https://images.unsplash.com/photo-1584464491033-06628f3a6b7b?w=800",
                coaching_cue="Pull elbow to hip; squeeze shoulder blade."),
            _ex("Push-Up", 3, 12, 45,
                image_url="https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?w=800",
                coaching_cue="Full body plank; nose brushes the floor."),
            _ex("Plank", 3, 45, 45,
                image_url="https://images.unsplash.com/photo-1518611012118-696072aa579a?w=800",
                coaching_cue="Squeeze glutes; ribs down; breathe."),
        ],
        "mobility": [
            _ex("World's Greatest Stretch", 2, 5, 30, coaching_cue="Slow, deliberate reach."),
            _ex("90/90 Hip Switch", 2, 8, 30, coaching_cue="Even weight on both hips."),
            _ex("Cat-Cow", 2, 10, 20, coaching_cue="Move with your breath."),
        ],
        "hyrox": [
            _ex("Kettlebell Swing", 5, 20, 60, coaching_cue="Hips snap; arms relax."),
            _ex("Burpee", 5, 10, 60, coaching_cue="Chest to floor; explode up."),
            _ex("Row 250m", 5, 250, 90, coaching_cue="Legs → hips → arms."),
        ],
        "fullbody_home": [
            _ex("Back Squat", 4, 6, 90, coaching_cue="Big brace. Sit into hips."),
            _ex("Bench Press", 4, 6, 90, coaching_cue="Tuck elbows ~45°."),
            _ex("Pull-Up", 3, 8, 60, coaching_cue="Lead with chest to bar."),
        ],
        "lower_home": [
            _ex("Back Squat", 5, 5, 120, coaching_cue="Sit between your heels."),
            _ex("Romanian Deadlift", 4, 8, 90, coaching_cue="Push hips back; feel hamstrings."),
            _ex("Bulgarian Split Squat", 3, 10, 60, coaching_cue="Front-leg dominant."),
        ],
        "push_home": [
            _ex("Bench Press", 5, 5, 120, coaching_cue="Tuck elbows; drive feet."),
            _ex("Overhead Press", 4, 6, 90, coaching_cue="Ribs down; brace core."),
            _ex("Dip", 3, 10, 60, coaching_cue="Chest forward; lockout at top."),
        ],
        "cardio": [
            _ex("Treadmill Warm-up", 1, 5, 0, coaching_cue="Easy pace."),
            _ex("Zone-2 Intervals", 6, 3, 60, coaching_cue="Nasal breathing; conversational."),
            _ex("Cool-down Walk", 1, 5, 0, coaching_cue="Slow to nasal breathing."),
        ],
    }
    for offset, title, focus, minutes, bank_key, completed in workout_plans:
        d = TODAY + timedelta(days=offset)
        workouts.append(_wk(d, title, focus, minutes, ex_bank[bank_key], completed=completed))
    if workouts:
        await db.workouts.insert_many(workouts)

    # ----- Nutrition log for today so the nutrition screen isn't empty -----
    await db.nutrition_logs.delete_many({"user_id": UID, "source": "landing_demo_seed"})
    meals = [
        ("breakfast", 480, 34, 55, 14, "Oats, banana, whey shake"),
        ("lunch",     640, 45, 60, 22, "Grilled chicken, rice, salad"),
        ("snack",     180, 15, 20, 6,  "Greek yoghurt & berries"),
    ]
    now = _iso_now()
    for i,(m,k,p,c_,f,label) in enumerate(meals):
        await db.nutrition_logs.insert_one({
            "log_id": str(uuid.uuid4()),
            "user_id": UID,
            "date_local": TODAY.isoformat(),
            "meal_type": m,
            "source": "landing_demo_seed",
            "calories": k,
            "protein_g": p,
            "carbs_g": c_,
            "fats_g": f,
            "estimated_macros": {"calories":k,"protein_g":p,"carbs_g":c_,"fats_g":f},
            "food_items":[{"name":label}],
            "ts": now,
        })
    # Seed hydration for today (used by /nutrition/today)
    await db.nutrition_hydration.update_one(
        {"user_id": UID, "date_local": TODAY.isoformat()},
        {"$set": {"user_id": UID, "date_local": TODAY.isoformat(), "amount_ml": 1600, "updated_at": now}},
        upsert=True,
    )

    # Confirm
    print("Seeded rolling roster:", rid, "days=", len(days))
    print("Seeded workouts today ± =", await db.workouts.count_documents({"user_id": UID, "source": "landing_demo_seed"}))
    print("Seeded nutrition today =", await db.nutrition_logs.count_documents({"user_id": UID, "source": "landing_demo_seed"}))

if __name__ == "__main__":
    asyncio.run(main())
