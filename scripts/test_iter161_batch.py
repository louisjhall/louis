"""
Iter 161 · Backend verification for the 6-issue batch.

Exercises:
  1. Full Rest protection — _ensure_workout_content leaves rest days alone.
  2. Canonical duplicate prevention — create_exercise_request_if_missing
     reuses an existing alias by singular/plural key.
  3. Genuinely different exercises stay distinct.
  4. Auto-media generation skips alias rows.
  5. Library video wins over YouTube cache via GET /exercises/video.

NO LLM calls, NO writes to production data (uses temporary docs it cleans
up), NO paid media generation.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, "/app/backend")
# Iter 161 · Force auto-media OFF for all resolver tests. We only enable it
# inside test [4] via a targeted monkeypatch — this prevents accidental LLM
# spend when create_exercise_request_if_missing() inserts fresh test rows.
os.environ["AUTO_MEDIA_GEN"] = "false"

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "crewfit_v1"


def _ok(msg): print(f"  ✅  {msg}")
def _fail(msg): print(f"  ❌  {msg}"); raise AssertionError(msg)


async def test_full_rest_protection():
    print("\n[1] Full Rest protection in _ensure_workout_content")
    from server import _ensure_workout_content

    # Case A: Pietro-shaped Full Rest day
    doc = {
        "id": "T-full-rest-1", "user_id": "u1", "date": "2026-08-10",
        "title": "Full Rest", "workout_type": "recovery",
        "duration_min": 0, "exercises": [], "warmup": [], "cooldown": [],
        "source": "coach_manual",
    }
    out = _ensure_workout_content(dict(doc), {"id": "u1"})
    if out.get("exercises"):
        _fail(f"Full Rest was healed! exercises={out.get('exercises')}")
    if out.get("fallback_used"):
        _fail("Full Rest wrongly marked fallback_used")
    _ok("Full Rest / coach_manual / duration_min=0 → left untouched")

    # Case B: workout_type=recovery with title="Recovery"
    doc = {
        "id": "T-rec-2", "user_id": "u1", "date": "2026-08-11",
        "title": "Recovery", "workout_type": "recovery",
        "duration_min": 60, "exercises": [], "source": "generator",
    }
    out = _ensure_workout_content(dict(doc), {"id": "u1"})
    if out.get("fallback_used"):
        _fail("workout_type=recovery healed to bodyweight — regression")
    _ok("workout_type=recovery (non-manual) → left untouched")

    # Case C: Genuine training day with empty exercises should STILL be healed
    doc = {
        "id": "T-legit-empty", "user_id": "u1", "date": "2026-08-12",
        "title": "Upper Body", "workout_type": "strength",
        "duration_min": 45, "exercises": [], "focus": "push",
        "source": "generator",
    }
    out = _ensure_workout_content(dict(doc), {"id": "u1"})
    # Should be healed (fallback_used True OR exercises populated)
    if not (out.get("fallback_used") or out.get("exercises")):
        _fail("Legit empty upper-body day was left broken — expected heal")
    _ok("Empty strength day still gets safe fallback (heal preserved)")


async def test_canonical_dedup(db):
    print("\n[2] Canonical duplicate prevention in create_exercise_request_if_missing")
    from feature_v2_resolver import create_exercise_request_if_missing, _canonical_key

    # Seed a canonical row first
    canon_id = f"TEST-canon-{uuid.uuid4().hex[:6]}"
    canon_name = f"Test Calf Raise {uuid.uuid4().hex[:4]}"
    key = _canonical_key(canon_name)
    await db.exercises_v2.insert_one({
        "id": canon_id,
        "exercise_name": canon_name,
        "requested_name_norm": canon_name.lower(),
        "canonical_name_key": key,
        "status": "Approved",
        "primary_video_url": "https://youtu.be/DUMMY_VIDEO_ID_ABC",
        "created_at": "2026-01-01T00:00:00",
    })

    user = {"id": "u-test-1", "profile": {}}

    # Request plural / capitalisation variant — must reuse canon_id
    plural = canon_name + "s"
    rid = await create_exercise_request_if_missing(
        {"name": plural}, user=user, reason="test",
    )
    if rid != canon_id:
        _fail(f"Plural '{plural}' created a new row instead of reusing {canon_id} (got {rid})")
    _ok(f"'{plural}' → reused {canon_id}")

    # Request lowercase punctuation-shifted variant — must reuse
    variant = canon_name.lower() + "s"
    rid = await create_exercise_request_if_missing(
        {"name": variant}, user=user, reason="test",
    )
    if rid != canon_id:
        _fail(f"lowercase plural did not reuse (got {rid})")
    _ok(f"'{variant}' → reused {canon_id}")

    # Cleanup
    await db.exercises_v2.delete_one({"id": canon_id})


async def test_variant_stays_distinct(db):
    print("\n[3] Genuine variants stay distinct")
    from feature_v2_resolver import create_exercise_request_if_missing

    # Seed standing calf raise
    standing_id = f"TEST-standing-{uuid.uuid4().hex[:6]}"
    await db.exercises_v2.insert_one({
        "id": standing_id,
        "exercise_name": "Standing Test Calf Raise",
        "requested_name_norm": "standing test calf raise",
        "canonical_name_key": "standing test calf raise",
        "status": "Approved",
        "created_at": "2026-01-01T00:00:00",
    })
    user = {"id": "u-test-2", "profile": {}}
    seated_id = await create_exercise_request_if_missing(
        {"name": "Seated Test Calf Raise"}, user=user, reason="test",
    )
    if seated_id == standing_id:
        _fail("Seated & Standing were wrongly merged!")
    _ok(f"Standing ({standing_id[:8]}…) and Seated ({seated_id[:8]}…) kept distinct")

    await db.exercises_v2.delete_one({"id": standing_id})
    await db.exercises_v2.delete_one({"id": seated_id})


async def test_auto_media_skips_alias(db):
    print("\n[4] auto_enqueue_media_for_exercise skips alias rows")
    import feature_auto_media_gen as amg
    # Force ENABLED and un-paused for THIS test ONLY — we're proving the
    # alias branch short-circuits BEFORE anything expensive can happen.
    # Save & restore so subsequent tests don't accidentally inherit ON.
    original_enabled = amg.AUTO_MEDIA_GEN_ENABLED
    original_paused = amg.is_budget_paused
    amg.AUTO_MEDIA_GEN_ENABLED = True

    async def _not_paused():
        return False
    amg.is_budget_paused = _not_paused

    try:
        # Insert a fake alias row pointing to a fake canonical
        canon_id = f"TEST-canon-{uuid.uuid4().hex[:6]}"
        alias_id = f"TEST-alias-{uuid.uuid4().hex[:6]}"
        await db.exercises_v2.insert_many([
            {"id": canon_id, "exercise_name": "Canon Test Ex",
             "status": "Approved", "primary_video_url": "https://x/x"},
            {"id": alias_id, "exercise_name": "Canon Test Exes",
             "status": "draft_requested", "canonical_id": canon_id},
        ])
        result = await amg.auto_enqueue_media_for_exercise(alias_id, triggered_by="tester")
        if not result.get("skipped") or result.get("reason") != "alias_of_canonical":
            _fail(f"Alias auto-media was not skipped: {result}")
        _ok("Alias row correctly returned skipped=alias_of_canonical")

        await db.exercises_v2.delete_many({"id": {"$in": [canon_id, alias_id]}})
    finally:
        amg.AUTO_MEDIA_GEN_ENABLED = original_enabled
        amg.is_budget_paused = original_paused


async def test_library_video_wins(db):
    print("\n[5] GET /exercises/video prefers Library primary_video_url")
    from server import _resolve_library_video

    # Insert a fake library exercise with a Library video (11-char YT id).
    ex_id = f"TEST-lib-vid-{uuid.uuid4().hex[:6]}"
    ex_name = f"Zulu Test Move {uuid.uuid4().hex[:4]}"
    YT_ID = "LibWins123X"  # 11 chars, valid YT format
    await db.exercises_v2.insert_one({
        "id": ex_id, "exercise_name": ex_name,
        "status": "Approved",
        "primary_video_url": f"https://youtu.be/{YT_ID}",
        "canonical_name_key": " ".join(w.lower() for w in ex_name.split()),
    })
    v = await _resolve_library_video(exercise_id=ex_id)
    if not v or v.get("video_id") != YT_ID:
        _fail(f"Library video did not resolve by id: {v}")
    _ok(f"By exercise_id → Library video {v.get('video_id')}")
    v = await _resolve_library_video(exercise_name=ex_name)
    if not v or v.get("video_id") != YT_ID:
        _fail(f"Library video did not resolve by name: {v}")
    _ok(f"By exercise_name → Library video {v.get('video_id')}")

    # canonical_id follow-through
    alias_id = f"TEST-alias-vid-{uuid.uuid4().hex[:6]}"
    await db.exercises_v2.insert_one({
        "id": alias_id, "exercise_name": ex_name + " Alt",
        "status": "draft_requested", "canonical_id": ex_id,
    })
    v = await _resolve_library_video(exercise_id=alias_id)
    if not v or v.get("video_id") != YT_ID:
        _fail(f"canonical_id follow-through failed: {v}")
    _ok("Alias exercise_id → canonical Library video")

    await db.exercises_v2.delete_many({"id": {"$in": [ex_id, alias_id]}})


async def main():
    cli = AsyncIOMotorClient(MONGO_URL)
    db = cli[DB_NAME]
    await test_full_rest_protection()
    await test_canonical_dedup(db)
    await test_variant_stays_distinct(db)
    await test_auto_media_skips_alias(db)
    await test_library_video_wins(db)
    print("\n✅  All 5 verification suites passed.")
    cli.close()


if __name__ == "__main__":
    asyncio.run(main())
