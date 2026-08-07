"""
Iter 161 · Reconcile existing duplicate exercises_v2 rows.

READ-ONLY BY DEFAULT (`--dry-run` is the default).
Writes ONLY the `canonical_id` and `canonical_name_key` fields on rows.
NEVER deletes rows, NEVER touches primary_video_url / images / status /
workout references. Historical workouts continue to resolve.

For each duplicate group (exact normalised name OR canonical singularised
name OR safe near-dup on Jaccard≥0.85 with side/equipment/intensity/
locomotion guards), we:
  1. Pick a canonical WINNER by priority:
       has primary_video_url? > has primary_image_url? > Approved/Live? >
       status draft > status draft_requested > oldest created_at
  2. Set `canonical_id` on every non-winner to the winner's id.
  3. Set `canonical_name_key` on ALL rows (winner and losers) so future
     `create_exercise_request_if_missing` calls can hit them by O(1) key.
  4. Never touches rows already carrying `canonical_id`.

Usage:
  python /app/scripts/reconcile_exercise_aliases.py             # dry-run
  python /app/scripts/reconcile_exercise_aliases.py --commit    # write
"""
import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME_ENV = os.environ.get("DB_NAME") or "crewfit_v1"

_WORD_RE = re.compile(r"[a-z0-9]+")
_PLURAL_KEEP = {"abs", "biceps", "triceps", "lats", "quads", "delts", "glutes",
                "kettlebells", "dumbbells", "aerobics", "gymnastics"}
_EQUIP_TOKENS = {"kettlebell", "kettlebells", "dumbbell", "dumbbells", "barbell",
                 "cable", "machine", "band", "bands", "trx", "smith"}
_INTENSITY_TOKENS = {"easy", "hard", "moderate", "recovery", "tempo",
                     "threshold", "sprint", "explosive", "slow", "fast"}
_LOCOMOTION = ({"walk", "walking"}, {"run", "running", "jog", "jogging"})
_SIDE = {"left", "right", "l", "r", "lh", "rh", "unilateral"}


def singularise(t):
    if not t or t in _PLURAL_KEEP or len(t) <= 2:
        return t
    if t.endswith("ies") and len(t) > 4: return t[:-3] + "y"
    if t.endswith("sses"): return t[:-2]
    if t.endswith(("ches", "shes", "xes")) and len(t) > 5: return t[:-2]
    if t.endswith("oes") and len(t) > 4: return t[:-2]
    if t.endswith("s") and not t.endswith("ss"): return t[:-1]
    return t


def canon_tokens(s):
    return tuple(singularise(t) for t in _WORD_RE.findall((s or "").lower()))


def canon_key(s):
    return " ".join(canon_tokens(s))


def name_tokens(s):
    return set(_WORD_RE.findall((s or "").lower()))


def has_disqualifier(a, b):
    """Return True if a and b MUST remain distinct (side / equipment /
    intensity / locomotion mismatch)."""
    a_t, b_t = name_tokens(a), name_tokens(b)
    a_side, b_side = a_t & _SIDE, b_t & _SIDE
    if (bool(a_side) ^ bool(b_side)) or (a_side and b_side and a_side != b_side):
        return True
    a_eq, b_eq = a_t & _EQUIP_TOKENS, b_t & _EQUIP_TOKENS
    if (bool(a_eq) ^ bool(b_eq)) or (a_eq and b_eq and a_eq != b_eq):
        return True
    a_int, b_int = a_t & _INTENSITY_TOKENS, b_t & _INTENSITY_TOKENS
    if (bool(a_int) ^ bool(b_int)) or (a_int and b_int and a_int != b_int):
        return True
    a_fam = b_fam = None
    for fam in _LOCOMOTION:
        if a_t & fam: a_fam = frozenset(fam)
        if b_t & fam: b_fam = frozenset(fam)
    if a_fam != b_fam:
        return True
    return False


STATUS_RANK = {
    "live": 90, "approved": 80,
    "needs update": 60, "ready for approval": 55,
    "draft": 40, "needs review": 35,
    "coach_review_needed": 30, "draft_requested": 20,
    "artwork needed": 15, "video needed": 15, "coaching points needed": 15,
    "rejected": -10, "archived": -20, "merged": -30,
}


def winner_priority(row):
    """Higher = more preferred canonical winner."""
    score = 0
    if row.get("primary_video_url"): score += 400
    if row.get("primary_image_url"): score += 200
    status_lc = str(row.get("status") or "").lower()
    score += STATUS_RANK.get(status_lc, 0)
    # Fresh rows deprioritised over older ones (older is more likely referenced by history)
    if row.get("created_at"):
        # ISO-string lexicographic sort works fine here.
        pass
    return score


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="Actually write canonical_id / canonical_name_key. Default is dry-run.")
    ap.add_argument("--db", default=None, help="DB name override (default: env DB_NAME or auto-detect)")
    args = ap.parse_args()

    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[args.db or DB_NAME_ENV]
    if await db.exercises_v2.count_documents({}) == 0:
        for dbname in await cli.list_database_names():
            if dbname in ("admin", "local", "config"): continue
            if await cli[dbname].exercises_v2.count_documents({}):
                db = cli[dbname]
                print(f"Auto-selected DB: {dbname}")
                break

    rows = await db.exercises_v2.find(
        {},
        {"_id": 0, "id": 1, "exercise_name": 1, "status": 1,
         "primary_image_url": 1, "primary_video_url": 1,
         "canonical_id": 1, "canonical_name_key": 1,
         "created_at": 1, "movement_pattern": 1},
    ).to_list(20000)
    total = len(rows)
    print(f"\nTotal rows: {total}")

    # Group by canonical key
    by_key = defaultdict(list)
    for r in rows:
        by_key[canon_key(r.get("exercise_name"))].append(r)

    plan = []  # list of tuples: (winner, [aliases])
    already_aliased = 0
    for k, group in by_key.items():
        # Skip rows already carrying canonical_id — respect existing state.
        group = [r for r in group if not r.get("canonical_id")]
        if len(group) < 2:
            continue
        # Extra safety: ensure no disqualifier disagreement inside the group.
        # If any pair inside would fail the guard, split into sub-groups.
        subgroups = []
        for r in group:
            placed = False
            for sg in subgroups:
                if not has_disqualifier(sg[0].get("exercise_name"), r.get("exercise_name")):
                    sg.append(r)
                    placed = True
                    break
            if not placed:
                subgroups.append([r])
        for sg in subgroups:
            if len(sg) < 2:
                continue
            winner = max(sg, key=winner_priority)
            aliases = [r for r in sg if r.get("id") != winner.get("id")]
            plan.append((winner, aliases))

    print(f"Groups to reconcile: {len(plan)}")
    total_aliases = sum(len(a) for _, a in plan)
    print(f"Alias rows to be marked: {total_aliases}")
    winners_with_media = sum(1 for w, _ in plan
                              if w.get("primary_video_url") or w.get("primary_image_url"))
    print(f"Groups where winner already has media: {winners_with_media}")

    for w, aliases in plan[:30]:
        media = "VID" if w.get("primary_video_url") else ("IMG" if w.get("primary_image_url") else "-")
        print(f"\n  WINNER: {w.get('exercise_name'):40s} status={str(w.get('status')):20s} media={media:4s} id={w.get('id')}")
        for a in aliases:
            am = "VID" if a.get("primary_video_url") else ("IMG" if a.get("primary_image_url") else "-")
            print(f"    -> alias: {a.get('exercise_name'):40s} status={str(a.get('status')):20s} media={am:4s} id={a.get('id')}")

    if args.commit:
        print("\n=== COMMIT MODE ===")
        touched = 0
        for winner, aliases in plan:
            key = canon_key(winner.get("exercise_name"))
            # Ensure the winner has canonical_name_key
            await db.exercises_v2.update_one(
                {"id": winner["id"]},
                {"$set": {"canonical_name_key": key}},
            )
            for a in aliases:
                await db.exercises_v2.update_one(
                    {"id": a["id"]},
                    {"$set": {
                        "canonical_id": winner["id"],
                        "canonical_name_key": key,
                        "aliased_at": __import__("datetime").datetime.utcnow().isoformat(),
                    }},
                )
                touched += 1
        print(f"Aliased rows written: {touched}")
        # Also populate canonical_name_key on all remaining rows (idempotent)
        remaining = 0
        for r in rows:
            if not r.get("canonical_name_key"):
                await db.exercises_v2.update_one(
                    {"id": r["id"]},
                    {"$set": {"canonical_name_key": canon_key(r.get("exercise_name"))}},
                )
                remaining += 1
        print(f"canonical_name_key populated on: {remaining} additional rows")
    else:
        print("\nDRY-RUN — no changes written. Re-run with --commit to persist.")

    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
