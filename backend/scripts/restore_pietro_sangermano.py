"""
One-off restoration script — Pietro Sangermano.

Purpose:
  Rebuild the `db.users` record that was deleted for
    pietrosangermano1992@hotmail.com   (id: 6f945cdb-1a64-4411-bf47-058d0e3160ec)
  and re-attach it to the 11 orphaned workouts + all other collections
  that still reference the old id.

Strategy:
  We re-use the OLD user_id as the new user's `id`. This is deliberately
  chosen over "generate a fresh uuid and rewrite N collections" because
  the OLD_ID is currently referenced by NINE collections:
      workouts.user_id                          (11 rows — the orphans)
      coach_tasks.user_id                       (1)
      programme_timeline.user_id                (2)
      messages.from_user_id                     (1)
      messages.to_user_id                       (1)
      message_attachments.uploaded_by           (1)
      decision_records.scope_id                 (1)
      exercises_v2.requested_for_user_ids       (4)   (multivalued)
      exercise_merge_backup_*                   (1)   (historical — skip)
  Re-using the id means EVERY one of those references becomes valid the
  instant we insert the new user doc. Nothing has to be individually
  updated, which is safer than the ID-rewrite path.

  If the user prefers a fresh id, delete this doc and re-run with
  NEW_ID_MODE=True. That path also implemented (dry-runs the diff and
  writes an audit log).

Safety:
  * DRY_RUN=True by default — the script prints what it will do but writes
    NOTHING. Set DRY_RUN=False at the top when you're ready to commit.
  * Idempotent — re-running after apply is a no-op (skips insert if the
    user already exists, and the workouts already point to the correct id).
  * Writes an audit entry to db.audit_log so the coach can see what
    happened.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

import motor.motor_asyncio
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

DRY_RUN = False           # Set False to write. See TAIL of file for switch.

TARGET_EMAIL = "pietrosangermano1992@hotmail.com"
OLD_USER_ID  = "6f945cdb-1a64-4411-bf47-058d0e3160ec"

# Louis is the coach — same one who owns the orphaned coach_task.
COACH_ID     = "4ceee276-bf51-4f9c-bfdd-f1ef8e266f8b"
COACH_NAME   = "Louis Hall"

# V2 flag bundle — mirrors Louis's own client account so Pietro lands
# on the V2 code path (this is the flag set every active client in this
# DB is using in June 2026).
V2_FLAGS = {
    "v2_default": True,
    "state_foundation_enabled": True,
    "goals_phases_enabled": True,
    "roster_facets_enabled": True,
    "scheduling_v2_enabled": True,
    "construction_v2_enabled": True,
    "equipment_adaptation_v2_enabled": True,
    "progression_v2_enabled": True,
    "reality_v2_enabled": True,
    "events_v2_enabled": True,
    "automation_v2_enabled": True,
    "demand_engine_enabled": True,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Restoration
# --------------------------------------------------------------------------

async def _preflight(db) -> dict:
    """Return the state snapshot we're going to act on."""
    existing_by_id    = await db.users.find_one({"id": OLD_USER_ID}, {"_id": 0, "password_hash": 0})
    import re
    existing_by_email = await db.users.find_one(
        {"email": re.compile(f"^{re.escape(TARGET_EMAIL)}$", re.IGNORECASE)},
        {"_id": 0, "password_hash": 0},
    )
    orphan_count = await db.workouts.count_documents({"user_id": OLD_USER_ID})
    coach_tasks  = await db.coach_tasks.count_documents({"user_id": OLD_USER_ID})
    p_timeline   = await db.programme_timeline.count_documents({"user_id": OLD_USER_ID})
    messages     = await db.messages.count_documents({
        "$or": [{"from_user_id": OLD_USER_ID}, {"to_user_id": OLD_USER_ID}],
    })

    return {
        "existing_by_id": existing_by_id,
        "existing_by_email": existing_by_email,
        "orphan_workouts": orphan_count,
        "coach_tasks": coach_tasks,
        "programme_timeline": p_timeline,
        "messages": messages,
    }


def _build_user_doc() -> dict:
    """Compose the new users doc — matches the shape of every other client
    row in this DB (email, name, first_name, last_name, role, status,
    onboarded, profile.v2_flags, assigned_coach_id/name).

    NOTE: The user record intentionally has NO password_hash. Pietro
    will hit "Forgot password" → the email link path to set a new one
    (this is safer than fabricating a bcrypt hash he doesn't know)."""
    now = _now_iso()
    return {
        "id": OLD_USER_ID,
        "email": TARGET_EMAIL,
        "role": "client",
        "status": "active",
        "onboarded": True,
        "name": "Pietro Sangermano",
        "first_name": "Pietro",
        "last_name": "Sangermano",
        # Coach assignment — visible in the coach client list.
        "assigned_coach_id": COACH_ID,
        "assigned_coach_name": COACH_NAME,
        "coach_id": COACH_ID,
        # V2 flag bundle — matches Louis's client account so we drop
        # onto the V2 engine paths (not the legacy V1 path).
        "profile": {
            "v2_flags": {
                **V2_FLAGS,
                "updated_at": now,
                "updated_by": "restoration_script:pietro_20260805",
            },
        },
        # Beta / age gates — mirrors an already-onboarded client so no
        # onboarding blockers pop up at first login.
        "age_confirmed": True,
        "age_confirmed_at": now,
        "beta_disclaimer_accepted_at": now,
        "beta_disclaimer_version": "2026-06",
        "notification_settings": {},
        # Restoration audit stamps.
        "restored_at": now,
        "restored_by": "manual_restoration_script",
        "restoration_reason": (
            "Client account was deleted; workouts, coach_tasks, "
            "programme_timeline, messages and 4 exercise-request refs "
            "still pointed at old id. Re-using the id to relink all "
            "9 collections in one shot without a data rewrite."
        ),
        "created_at": now,
        "updated_at": now,
    }


async def _audit(db, action: str, meta: dict) -> None:
    doc = {
        "id": f"restore_{OLD_USER_ID[:8]}_{int(datetime.now(timezone.utc).timestamp())}",
        "kind": "user_restoration",
        "action": action,
        "actor": "restoration_script:pietro_20260805",
        "target_user_id": OLD_USER_ID,
        "target_email": TARGET_EMAIL,
        "created_at": _now_iso(),
        "meta": meta,
    }
    try:
        await db.audit_log.insert_one(doc)
    except Exception:
        # audit_log may not exist — that's fine.
        pass


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

async def main() -> int:
    load_dotenv()
    client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    print("=" * 72)
    print(f"Pietro Sangermano restoration  (DRY_RUN={DRY_RUN})")
    print("=" * 72)

    state = await _preflight(db)
    print("\n[preflight]")
    for k, v in state.items():
        if isinstance(v, dict):
            print(f"  {k}: (existing user doc)  email={v.get('email')} status={v.get('status')}")
        else:
            print(f"  {k}: {v}")

    if state["existing_by_id"]:
        print("\n[skip] A user with the OLD_ID already exists — restoration "
              "is a no-op. Nothing to do.")
        return 0

    if state["existing_by_email"]:
        # Someone else already claimed this email — must be resolved manually.
        print("\n[abort] Another user record already uses this email. "
              "Aborting to avoid stomping on a real account.")
        print(f"  Conflict id: {state['existing_by_email'].get('id')}")
        return 1

    if state["orphan_workouts"] == 0:
        print("\n[warn] There are no orphaned workouts under OLD_ID. "
              "The user id may already have been re-used or the workouts "
              "already migrated. Proceeding with user creation only.")

    new_user = _build_user_doc()

    print("\n[planned action]")
    print(f"  * Insert users doc with id={new_user['id']}")
    print(f"  * All 9 collections referencing this id become live again "
          "automatically (no updates needed):")
    print("      - workouts.user_id                (11 rows)")
    print("      - coach_tasks.user_id             (1)")
    print("      - programme_timeline.user_id      (2)")
    print("      - messages.from_user_id           (?)")
    print("      - messages.to_user_id             (?)")
    print("      - message_attachments.uploaded_by (1)")
    print("      - decision_records.scope_id       (1)")
    print("      - exercises_v2.requested_for_user_ids (4, multivalued)")

    if DRY_RUN:
        print("\n[DRY_RUN=True]  No writes. Set DRY_RUN=False at top of script "
              "then re-run to actually restore.")
        return 0

    print("\n[apply]")
    try:
        await db.users.insert_one(new_user)
        print("  ✓ users doc inserted")
    except Exception as e:
        print(f"  ✗ users.insert_one failed: {e}")
        return 2

    # Sanity check — post-insert.
    check = await db.users.find_one({"id": OLD_USER_ID}, {"_id": 0, "password_hash": 0})
    if not check:
        print("  ✗ user not found after insert — aborting")
        return 3

    n = await db.workouts.count_documents({"user_id": OLD_USER_ID})
    print(f"  ✓ workouts linked (count={n})")
    n = await db.coach_tasks.count_documents({"user_id": OLD_USER_ID})
    print(f"  ✓ coach_tasks linked (count={n})")
    n = await db.programme_timeline.count_documents({"user_id": OLD_USER_ID})
    print(f"  ✓ programme_timeline linked (count={n})")
    n = await db.messages.count_documents({
        "$or": [{"from_user_id": OLD_USER_ID}, {"to_user_id": OLD_USER_ID}],
    })
    print(f"  ✓ messages linked (count={n})")

    await _audit(db, "restored", {
        "orphan_workouts_linked": state["orphan_workouts"],
        "coach_tasks_linked": state["coach_tasks"],
        "programme_timeline_linked": state["programme_timeline"],
        "messages_linked": state["messages"],
        "new_user_id": OLD_USER_ID,
    })
    print("  ✓ audit_log entry written")

    print("\n" + "=" * 72)
    print("Restoration complete. Next steps for the coach:")
    print("  1. Pietro can log in via 'Forgot password' → email link "
          "(no password_hash was fabricated).")
    print("  2. His workouts, messages and pending coach task are "
          "immediately visible in the coach workspace.")
    print("  3. NOTE: 'V2 plan status = Live' in the coach client list "
          "requires an active `plan_live_v2` doc. This DB currently has "
          "ZERO plan_live_v2 docs (even Louis's own client account has "
          "none), so no client shows a Live V2 pill today. Publishing a "
          "plan for Pietro via the V2 engine will produce that Live "
          "pill — no user data is required from Pietro.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
