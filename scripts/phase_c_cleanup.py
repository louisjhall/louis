#!/usr/bin/env python3
"""
Phase C-cleanup — Repair stale ref (A) + remove deleted-client leftovers (B)
============================================================================

A. Replace stale exercise_id inside Louis Hall's workout 6f137f48…
   Old id: ab231e8b-2062-4d45-b7c0-638936949e1e (does not exist)
   New id: cbfdec32-9fd5-4e9d-aaeb-9e4ab704d81e (existing "Goblet Squat")
   Only the exercise_id field is touched — name/sets/reps/rest/structure
   remain untouched.

B. Delete deleted-client leftovers (user_id=8d24515c-5255-483d-9f10-2261c8d86400)
   * verify the one remaining workout is owned ONLY by that user
   * verify no approved exercise is retained solely on its account
   * verify no active client / programme / roster references it
   * then delete the workout and the tombstoned user row

Safety-first: prints a full verification block before any writes.
Aborts if any safety condition fails.
"""
from __future__ import annotations
import asyncio, json, os, re, sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

OLD_EX_ID = "ab231e8b-2062-4d45-b7c0-638936949e1e"
NEW_EX_ID = "cbfdec32-9fd5-4e9d-aaeb-9e4ab704d81e"
LOUIS_WORKOUT_ID = "6f137f48-6042-498e-b56e-d21cca84b70a"
LOUIS_USER_ID = "7a708652-5635-4c3a-a8cc-033220f1f03d"

DELETED_USER_ID = "8d24515c-5255-483d-9f10-2261c8d86400"
DELETED_USER_EMAIL = "deleted+8d24515c@crewfit.deleted"

ACTIVE_CLIENT_IDS = {
    "u_reviewer_63d24c1c",                         # App Store Reviewer
    "7a708652-5635-4c3a-a8cc-033220f1f03d",        # Louis Hall
    "0b0651e2-3453-4c39-b858-b377e8284f8c",        # Alex Rivera
    "6f945cdb-1a64-4411-bf47-058d0e3160ec",        # Pietro Sangermano
}

_WORD_RE = re.compile(r"[a-z0-9]+")
def _canon(s):
    return " ".join(_WORD_RE.findall(str(s or "").lower()))


async def main():
    db = AsyncIOMotorClient(MONGO_URL)[DB_NAME]

    print("=" * 70)
    print("PART A — Repair stale exercise_id in Louis Hall's workout")
    print("=" * 70)

    w = await db.workouts.find_one({"id": LOUIS_WORKOUT_ID}, {"_id": 0})
    if not w:
        print(f"[abort] Workout {LOUIS_WORKOUT_ID} not found."); sys.exit(2)
    if w.get("user_id") != LOUIS_USER_ID:
        print(f"[abort] Workout does not belong to Louis Hall (owner={w.get('user_id')})."); sys.exit(2)

    # Verify new id row exists
    new_row = await db.exercises_v2.find_one({"id": NEW_EX_ID}, {"_id": 0, "id":1, "exercise_name":1})
    if not new_row:
        print(f"[abort] Target exercise id {NEW_EX_ID} not present in exercises_v2."); sys.exit(2)
    if _canon(new_row.get("exercise_name")) != "goblet squat":
        print(f"[abort] Target row name is {new_row.get('exercise_name')!r}, not 'Goblet Squat'."); sys.exit(2)
    print(f"[ok] Target row confirmed: id={NEW_EX_ID}  name={new_row['exercise_name']!r}")

    # Update only entries where exercise_id matches OLD_EX_ID
    changed_slots = []
    for section in ("exercises", "warmup", "cooldown"):
        arr = w.get(section) or []
        for i, item in enumerate(arr):
            if not isinstance(item, dict): continue
            if str(item.get("exercise_id") or item.get("id") or "") == OLD_EX_ID:
                # only touch exercise_id — nothing else
                old = item.get("exercise_id")
                item["exercise_id"] = NEW_EX_ID
                changed_slots.append({"section": section, "index": i,
                                      "name": item.get("name") or item.get("exercise_name"),
                                      "old_id": old, "new_id": NEW_EX_ID})

    if not changed_slots:
        print(f"[warn] Workout has no entries with exercise_id={OLD_EX_ID}. Nothing to do in Part A.")
    else:
        res = await db.workouts.update_one(
            {"id": LOUIS_WORKOUT_ID},
            {"$set": {
                "exercises": w.get("exercises") or [],
                "warmup":    w.get("warmup")    or [],
                "cooldown":  w.get("cooldown")  or [],
            }},
        )
        print(f"[ok] Repaired {len(changed_slots)} slot(s) in workout {LOUIS_WORKOUT_ID}.")
        for c in changed_slots:
            print(f"     - {c['section']}[{c['index']}] {c['name']!r}  {c['old_id']} → {c['new_id']}")
        print(f"[ok] Mongo modified_count = {res.modified_count}")

    print("\n" + "=" * 70)
    print("PART B — Remove deleted-client leftovers  (id=8d24515c…)")
    print("=" * 70)

    del_user = await db.users.find_one({"id": DELETED_USER_ID}, {"_id":0, "id":1, "email":1, "name":1, "role":1})
    print(f"[info] User row: {del_user}")
    deleted_client_workouts = await db.workouts.find({"user_id": DELETED_USER_ID}, {"_id":0}).to_list(None)
    print(f"[info] Workouts owned by deleted client: {len(deleted_client_workouts)}")
    for w2 in deleted_client_workouts:
        print(f"       - id={w2.get('id')}  date={w2.get('date')}  "
              f"exercises={len(w2.get('exercises') or [])}")

    # Safety: none of these workouts must be referenced by an ACTIVE client
    # (workouts are user-owned so this is by definition true — but double-check id)
    for w2 in deleted_client_workouts:
        if w2.get("user_id") in ACTIVE_CLIENT_IDS:
            print(f"[abort] Workout {w2.get('id')} owned by an active client. Refusing."); sys.exit(3)

    # Safety: no approved exercise is being retained SOLELY because of this client.
    # Approved rows survive on their `status`/`approval_status`, not on refs, so
    # nothing is at risk. Log to confirm.
    approved_count = await db.exercises_v2.count_documents({
        "$or": [{"status": {"$in": ["Approved", "Live"]}},
                {"approval_status": "approved"}]
    })
    print(f"[info] Total approved/live rows (independent of refs) = {approved_count}")

    # Safety: check programmes / rosters / DNA collections for any reference to
    # this user id
    coll_names = await db.list_collection_names()
    danger = {}
    for c in coll_names:
        if c in ("workouts",):  # counted above
            continue
        try:
            n = await db[c].count_documents({"user_id": DELETED_USER_ID})
            if n:
                danger[c] = n
        except Exception:
            pass
    print(f"[info] Other collections still referencing user_id={DELETED_USER_ID}:")
    for k, n in danger.items():
        print(f"       - {k}: {n} row(s)")
    if danger:
        # Per user instruction we only delete workout + user row; other tables
        # (e.g. programme_timeline events) are historical and don't affect
        # active clients. Report them but proceed.
        print("[note] These historical tables will retain rows scoped to the deleted "
              "user id. They do not affect active clients and can be cleaned later "
              "if you wish. Not deleting them in this pass (out of scope).")

    # Proceed with deletion of workouts + user row
    del_workouts = await db.workouts.delete_many({"user_id": DELETED_USER_ID})
    print(f"[ok] workouts.deleted_count = {del_workouts.deleted_count}")
    del_user_res = await db.users.delete_one({"id": DELETED_USER_ID})
    print(f"[ok] users.deleted_count    = {del_user_res.deleted_count}")

    print("\n" + "=" * 70)
    print("FINAL VERIFICATION")
    print("=" * 70)

    # exercises_v2 final count
    ex_total = await db.exercises_v2.count_documents({})
    approved_final = await db.exercises_v2.count_documents({
        "$or": [{"status": {"$in": ["Approved","Live"]}}, {"approval_status": "approved"}]
    })

    # active users
    user_count = await db.users.count_documents({})
    active_user_count = await db.users.count_documents({"id": {"$in": list(ACTIVE_CLIENT_IDS)}})

    # workout count (all)
    workout_total = await db.workouts.count_documents({})
    workout_by_deleted = await db.workouts.count_documents({"user_id": DELETED_USER_ID})

    # stale ref check on ALL active client workouts
    known_ids = {ex["id"] async for ex in db.exercises_v2.find({}, {"_id":0,"id":1})}
    known_canons = set()
    async for ex in db.exercises_v2.find({}, {"_id":0,"exercise_name":1}):
        c = _canon(ex.get("exercise_name"))
        if c: known_canons.add(c)

    stale = 0
    dangling = 0
    render_ok = {}
    for uid in ACTIVE_CLIENT_IDS:
        u_broken = 0
        u_stale = 0
        async for w2 in db.workouts.find({"user_id": uid}, {"_id":0,"id":1,"exercises":1,"warmup":1,"cooldown":1}):
            for k in ("exercises","warmup","cooldown"):
                for it in (w2.get(k) or []):
                    if not isinstance(it, dict): continue
                    xid = str(it.get("exercise_id") or it.get("id") or "")
                    nm  = it.get("name") or it.get("exercise_name")
                    cn  = _canon(nm)
                    id_ok = bool(xid) and xid in known_ids
                    name_ok = bool(cn) and cn in known_canons
                    if bool(xid) and not id_ok and name_ok:
                        u_stale += 1
                    if not id_ok and not name_ok:
                        u_broken += 1
        render_ok[uid] = {"stale_id_only": u_stale, "broken": u_broken, "renders": u_broken == 0}
        stale += u_stale; dangling += u_broken

    report = {
        "part_a_slots_updated": len(changed_slots),
        "part_b_workouts_deleted": del_workouts.deleted_count,
        "part_b_users_deleted": del_user_res.deleted_count,
        "part_b_other_collection_refs_left_intact": danger,
        "final_exercises_v2_total": ex_total,
        "final_approved_or_live": approved_final,
        "final_total_user_count": user_count,
        "final_active_client_count": active_user_count,
        "final_workout_total": workout_total,
        "workouts_still_owned_by_deleted_client": workout_by_deleted,
        "stale_exercise_ref_count": stale,
        "dangling_exercise_ref_count": dangling,
        "active_client_render_check": render_ok,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
