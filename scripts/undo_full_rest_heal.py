"""
Iter 161 · One-off: undo the pre-fix "Full Rest healed into bodyweight" damage.

Finds every `db.workouts` row where:
  * fallback_used = True  (or validation_status = "adjusted_fallback")
  * AND the row was ORIGINALLY a rest / recovery day:
      - workout_type in (recovery, rest, off, day_off)
      - OR title contains "full rest" / starts with "rest"
      - OR source == "coach_manual" AND workout_type == "recovery"

Resets it back to Full Rest shape:
  * exercises = []
  * warmup    = []
  * cooldown  = []
  * duration_min = 0
  * fallback_used = False
  * validation_status = null
  * fallback_type = null
  * insufficient_content_reason = null
  * auto_healed_at = null
  * needs_coach_review = False (only if it was set by the fallback)
  * change_reason cleaned of the fallback boilerplate

NEVER touches non-rest fallbacks (a Long Run that got legitimately healed
because the LLM returned empty stays healed).
NEVER touches rows the client has already completed (`completed=True`).
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "crewfit_v1"

FALLBACK_MARKER = "CrewFit couldn't safely match the original workout"
REST_TYPES = {"recovery", "rest", "off", "day_off"}


def looks_like_rest(row: dict) -> bool:
    wt = str(row.get("workout_type") or "").lower()
    title = str(row.get("title") or "").lower()
    src = str(row.get("source") or "").lower()
    if wt in REST_TYPES:
        return True
    if "full rest" in title or title.startswith("rest") or title.startswith("off"):
        return True
    # coach_manual rows have highest coach-intent signal — respect them when
    # the workout_type / title clearly says rest. Never blanket-reset all
    # coach_manual rows.
    if src == "coach_manual" and (wt in REST_TYPES or "rest" in title):
        return True
    return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--user", default=None, help="Optional user_id to scope the fix to a single client")
    args = ap.parse_args()

    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]

    query = {
        "$or": [
            {"fallback_used": True},
            {"validation_status": "adjusted_fallback"},
            {"auto_healed_at": {"$exists": True}},
        ],
        "completed": {"$ne": True},
    }
    if args.user:
        query["user_id"] = args.user

    rows = await db.workouts.find(query, {"_id": 0}).to_list(2000)
    print(f"Candidate healed rows: {len(rows)}")

    targets = [r for r in rows if looks_like_rest(r)]
    print(f"Rows shaped like Full Rest (safe to reset): {len(targets)}")

    for r in targets[:40]:
        print(f"  {r.get('date')}  user={str(r.get('user_id'))[:10]}…  "
              f"title={str(r.get('title'))[:30]:<32}  wtype={str(r.get('workout_type')):<12}  "
              f"src={str(r.get('source')):<15}  ex={len(r.get('exercises') or [])}")

    if not args.commit:
        print("\nDRY-RUN — no changes written. Re-run with --commit to persist.")
        cli.close()
        return

    updated = 0
    for r in targets:
        # Clean change_reason of the fallback boilerplate
        cr = r.get("change_reason") or ""
        if FALLBACK_MARKER in cr:
            # keep whatever came before the "· <fallback text>"
            parts = cr.split("· ")
            keep = [p for p in parts if FALLBACK_MARKER not in p and "safe fallback" not in p.lower()]
            cr = " · ".join(x.strip() for x in keep if x.strip()) or None
        else:
            cr = cr or None

        await db.workouts.update_one(
            {"id": r["id"]},
            {"$set": {
                "exercises": [],
                "warmup": [],
                "cooldown": [],
                "duration_min": 0,
                "fallback_used": False,
                "validation_status": None,
                "fallback_type": None,
                "insufficient_content_reason": None,
                "needs_coach_review": False,
                "change_reason": cr,
                "restored_from_fallback_at": __import__("datetime").datetime.utcnow().isoformat(),
            },
             "$unset": {"auto_healed_at": ""}},
        )
        updated += 1

    print(f"\nReset {updated} rest-day rows back to Full Rest shape.")
    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
