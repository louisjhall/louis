"""Iter188 · Audit workout-player timer classification.

Reads every exercise in the library (`exercises_v2`) AND every embedded
workout exercise (`workouts.exercises[]`) and reports which ones the
frontend classifier would put in the wrong bucket.

Categories flagged
------------------
  1. `cardio_but_typed_strength`     — name says cardio, `category` = strength
  2. `hold_but_typed_strength`       — name matches a hold, `category` = strength
  3. `numeric_reps_ambiguous`        — bare number like "45" on an unknown name
  4. `strength_but_named_hold`       — legit strength lift that hits the hold regex
                                        by accident (regression check)
  5. `active_workouts_affected`      — how many upcoming workouts reference each

Read-only. Zero writes.

Usage: `python /app/backend/scripts/audit_exercise_timer_classification.py`
"""
import asyncio
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


# ---------------------------------------------------------------------------
# Mirror of frontend classifier (workoutMode.ts::isTimeBased / isCardio)
# ---------------------------------------------------------------------------
CARDIO_RE = re.compile(
    r"\b(run|running|jog|zone[\s-]?[1235]|z[1235]|intervals?|treadmill|"
    r"row|rowing|erg|bike|biking|cycling|cycle|assault|swim|swimming|"
    r"sprint|ez pace|long run|fartlek|walk|walking|hike|hiking|ruck|"
    r"rucking|stair|stairs|stairmaster|stepper|incline\s?walk|"
    r"power\s?walk|brisk\s?walk|recovery\s?walk)\b",
    re.I,
)
STRENGTH_EXCLUDE_RE = re.compile(
    r"\b(walking\s+(lunge|plank|push|dead\s?bug)|bent[- ]?over\s?row|"
    r"barbell\s?row|dumbbell\s?row|db\s?row|kb\s?row|pendlay\s?row|"
    r"seal\s?row|meadows\s?row|chest[- ]?supported\s?row|inverted\s?row|"
    r"single[- ]?arm\s?row|renegade\s?row|t[- ]?bar\s?row|kroc\s?row|"
    r"upright\s?row|face\s?pull|cable\s?row|iso\s?row|smith\s?row|"
    r"helms\s?row|hip\s?thrust)\b",
    re.I,
)
HOLD_RE = re.compile(
    r"\b(side plank|front plank|plank|hollow hold|wall sit|dead ?hang|"
    r"l[- ]?sit|farmer'?s? (walk|carry)|suitcase carry|overhead carry|"
    r"superman hold|bridge hold|forearm plank|hollow rock|dish hold|"
    r"bear crawl hold|hanging (l[- ]?sit|leg hold)|copenhagen (hold|plank)|"
    r"couch stretch|pigeon (hold|stretch)|isometric)\b",
    re.I,
)
REPS_TIME_RE = re.compile(
    r"\b\d+\s*(s|sec|secs|second|seconds|min|mins|minute|minutes)\b|"
    r"^\d+:\d{2}$|\b(hold|for time|until failure|max time|steady)\b",
    re.I,
)


def name_hits_cardio(name: str) -> bool:
    hay = (name or "").lower()
    return bool(CARDIO_RE.search(hay)) and not bool(STRENGTH_EXCLUDE_RE.search(hay))


def name_hits_hold(name: str) -> bool:
    return bool(HOLD_RE.search((name or "").lower()))


def reps_hints_time(reps: str) -> bool:
    return bool(REPS_TIME_RE.search((reps or "").strip()))


async def main() -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ.get("DB_NAME", "test_database")]

    print("=" * 72)
    print("EXERCISE TIMER-CLASSIFICATION AUDIT")
    print(f"DB: {db.name} · at {datetime.now(timezone.utc).isoformat()}")
    print("=" * 72)

    # ----- Section 1: Library (exercises_v2) -------------------------------
    lib_total = await db.exercises_v2.count_documents({})
    print(f"\nLIBRARY  ({lib_total} exercises_v2 rows)")
    print("-" * 72)

    cardio_but_strength: list[dict] = []
    hold_but_strength: list[dict] = []
    strength_named_hold: list[dict] = []

    async for ex in db.exercises_v2.find(
        {"is_deleted": {"$ne": True}},
        {
            "_id": 0, "id": 1, "exercise_name": 1, "category": 1,
            "status": 1, "logging_type_override": 1, "logging_type": 1,
        },
    ):
        name = ex.get("exercise_name") or ""
        cat = str(ex.get("category") or "").lower()
        override = ex.get("logging_type_override")
        lt = str(ex.get("logging_type") or "").strip().lower()

        # Skip anything already explicitly overridden — the coach has already
        # dealt with these.
        if override:
            continue
        # Iter189m — skip rows the library has explicitly typed with a
        # positive time-based value. The frontend now trusts these.
        if lt in ("cardio", "timer", "hold", "time", "duration"):
            continue

        is_cardio_named = name_hits_cardio(name)
        is_hold_named = name_hits_hold(name)

        # Rule 1 — cardio name but typed as strength / anything but cardio
        if is_cardio_named and cat and cat != "cardio":
            cardio_but_strength.append({
                "id": ex.get("id"), "name": name,
                "category": ex.get("category"),
                "status": ex.get("status"),
            })

        # Rule 2 — hold name but typed as strength
        if is_hold_named and cat == "strength":
            hold_but_strength.append({
                "id": ex.get("id"), "name": name,
                "category": ex.get("category"),
                "status": ex.get("status"),
            })

        # Rule 4 — strength lift whose name accidentally hits the hold regex
        # (regression check for the strength exclude list).
        if is_hold_named and cat == "strength" and re.search(r"\b(bench|press|squat|deadlift|clean|snatch|jerk)\b", name.lower()):
            strength_named_hold.append({
                "id": ex.get("id"), "name": name,
                "category": ex.get("category"),
            })

    def _print_section(title: str, rows: list[dict], limit: int = 40) -> None:
        print(f"\n{title}  · {len(rows)} row(s)")
        print("-" * 72)
        if not rows:
            print("  ✅ None found.")
            return
        for r in rows[:limit]:
            status = f" [{r.get('status')}]" if r.get("status") else ""
            print(f"  · {r['name']}   (category={r.get('category')}){status}")
            print(f"      id={r['id']}")
        if len(rows) > limit:
            print(f"  … and {len(rows) - limit} more")

    _print_section("[1] CARDIO-NAMED, TYPED NON-CARDIO (highest risk)", cardio_but_strength)
    _print_section("[2] HOLD-NAMED, TYPED STRENGTH   (highest risk)", hold_but_strength)
    _print_section("[4] STRENGTH LIFT BUT REGEX HITS HOLD (regression check)", strength_named_hold)

    # ----- Section 2: Workouts (upcoming) ---------------------------------
    print("\n" + "=" * 72)
    print("WORKOUTS — upcoming (approved OR future date)")
    print("=" * 72)

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    upcoming_q = {
        "$or": [
            {"date": {"$gte": today_iso}},
            {"approved": True, "date": {"$gte": today_iso}},
        ],
    }
    total_upcoming = await db.workouts.count_documents(upcoming_q)
    print(f"\nTotal upcoming workouts: {total_upcoming}")

    # Look at every embedded exercise name; report ones the classifier
    # would drop into strength when the name suggests otherwise.
    name_hits: dict[str, dict] = defaultdict(lambda: {"count": 0, "reps_samples": set(), "workouts": set()})
    numeric_reps_no_hint: dict[str, int] = defaultdict(int)

    scanned_ex = 0
    async for w in db.workouts.find(upcoming_q, {"_id": 0, "id": 1, "exercises": 1, "user_id": 1}):
        for e in (w.get("exercises") or []):
            scanned_ex += 1
            name = e.get("name") or ""
            reps = str(e.get("reps") or "")
            hits_cardio = name_hits_cardio(name)
            hits_hold = name_hits_hold(name)
            hints_time = reps_hints_time(reps)

            # Rule 3 — bare number, no time hint, not a known cardio/hold name
            #          → will render as strength REPS/WEIGHT even though the
            #          intent might be seconds.
            if (
                not hits_cardio and not hits_hold
                and re.fullmatch(r"\s*\d+\s*", reps)
                and int(reps.strip() or "0") >= 20  # 20+ raises suspicion of seconds
            ):
                numeric_reps_no_hint[name] += 1

            # Bucket by name so we can show frequency across the whole roster
            if hits_cardio or hits_hold or hints_time:
                key = name.strip()
                slot = name_hits[key]
                slot["count"] += 1
                slot["reps_samples"].add(reps[:20])
                slot["workouts"].add(w.get("id"))

    print(f"Scanned {scanned_ex} embedded exercises in {total_upcoming} workouts.")

    print("\n[3] NUMERIC REPS WITHOUT TIME HINT (possible mislabel):")
    print("-" * 72)
    if not numeric_reps_no_hint:
        print("  ✅ None found.")
    else:
        for name, count in sorted(numeric_reps_no_hint.items(), key=lambda x: -x[1])[:30]:
            print(f"  · {name}   · appears {count} times")

    print("\nTIME-BASED EXERCISES DETECTED IN UPCOMING WORKOUTS:")
    print("-" * 72)
    if not name_hits:
        print("  ✅ None.")
    else:
        for name, meta in sorted(name_hits.items(), key=lambda x: -x[1]["count"])[:30]:
            print(f"  · {name}")
            print(f"      · used {meta['count']} times across {len(meta['workouts'])} workouts")
            print(f"      · reps samples: {sorted(meta['reps_samples'])[:5]}")

    print("\n" + "=" * 72)
    print("AUDIT COMPLETE")
    print("=" * 72)
    print("Fixes:")
    print("  · For rows in [1] / [2]: set logging_type_override='timer' via")
    print("    PATCH /api/coach/library/exercise/{id}/logging-type")
    print("  · For rows in [3]: check with the coach whether these are")
    print("    intended as reps or seconds; if seconds, set the reps field")
    print("    to include a unit e.g. '45s'.")
    print()

    client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
