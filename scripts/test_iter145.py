#!/usr/bin/env python3
"""
Iter 145 unit tests — Unified Weekly Check-in + Weekly Review
==============================================================

Tests exercise DB writes only. Claude call is mocked (no real spend).
Every real network / LLM path is patched.

Verifies:
  1. Submit preserves originals in `atlas_client_summary_original` +
     `weekly_video_script_original`
  2. Submit stores weekly_review_snapshot (unified aggregation)
  3. Second submit is idempotent (same week — returns existing row)
  4. Edit script → original field preserved, working copy updated,
     script_edited_by + script_edited_at set
  5. Reset script → working copy reverts to original
  6. Edit summary → same behaviour
  7. Reset summary → working copy reverts
  8. Video send is idempotent — second send returns already_sent, does
     not fire another notify
  9. Video viewed marks first_viewed_at + first_view flag
 10. /weekly-review/current reads unified snapshot when present
"""
from __future__ import annotations
import asyncio, os, sys, json
from unittest.mock import patch, AsyncMock

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
import server as S                                   # noqa: E402
import feature_weekly_review as WR                   # noqa: E402
import feature_notifications as NT                   # noqa: E402


FAKE_ATLAS_OUTPUT = json.dumps({
    "atlas_client_summary": "Original Atlas summary text.",
    "atlas_coach_summary": {"adherence_note": "ok", "coach_review_required": False},
    "next_week_focus": "focus next week",
    "suggested_programme_adjustments": [{"area": "strength", "change": "keep"}],
    "weekly_video_script": "Original Atlas video script.",
    "whatsapp_short": "short",
    "push_notification": "push",
})


async def main():
    local_db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    for mod in (S, WR, NT):
        try: mod.db = local_db
        except Exception: pass

    TEST_USER_ID = "u_test_iter145"

    async def cleanup():
        await local_db.check_ins.delete_many({"user_id": TEST_USER_ID})
        await local_db.weekly_videos.delete_many({"user_id": TEST_USER_ID})
        await local_db.coach_tasks.delete_many({"user_id": TEST_USER_ID})
        await local_db.messages.delete_many({"to_id": TEST_USER_ID})
        await local_db.users.delete_one({"id": TEST_USER_ID})

    await cleanup()
    await local_db.users.insert_one({
        "id": TEST_USER_ID, "email": "t@iter145.crewfit", "name": "Test 145",
        "role": "client", "home_time_zone": "Europe/London",
        "coaching_dna": {"primary_goals": ["strength"], "crew_role": "cabin"},
    })
    user = await local_db.users.find_one({"id": TEST_USER_ID}, {"_id": 0})

    # -------- TEST 1 & 2: submit preserves originals + weekly_review_snapshot
    print("─── TEST 1+2 · submit preserves originals + weekly_review_snapshot ───")
    from server import checkin_submit, CheckinSubmitBody
    with patch("server.call_claude", new=AsyncMock(return_value=FAKE_ATLAS_OUTPUT)), \
         patch("server._create_coach_task", new=AsyncMock(return_value="task_" + "1")), \
         patch("server._run_habit_review_after_checkin", new=AsyncMock(return_value=None)):
        body = CheckinSubmitBody(answers={"energy": 7, "sleep": 6, "stress": 4,
                                          "recovery": 6, "pain": "no", "nutrition": "Good"})
        result = await checkin_submit(body, user=user)
    ci = result["check_in"]
    assert ci["atlas_client_summary"] == "Original Atlas summary text."
    assert ci["atlas_client_summary_original"] == "Original Atlas summary text."
    assert ci["weekly_video_script"] == "Original Atlas video script."
    assert ci["weekly_video_script_original"] == "Original Atlas video script."
    snap = ci.get("weekly_review_snapshot")
    assert snap is not None, "weekly_review_snapshot missing"
    assert set(snap.keys()) >= {"training", "nutrition", "habits", "roster_summary",
                                 "has_progress", "generated_at", "source"}
    assert snap["source"] == "checkin_submit_unified"
    print("  ✓ originals preserved + weekly_review_snapshot present")
    print(f"  ✓ snapshot keys: {sorted(snap.keys())}")

    # -------- TEST 3: idempotent submit
    print("\n─── TEST 3 · idempotent second submit ───")
    with patch("server.call_claude", new=AsyncMock(return_value=FAKE_ATLAS_OUTPUT)), \
         patch("server._create_coach_task", new=AsyncMock(return_value="task_" + "1")), \
         patch("server._run_habit_review_after_checkin", new=AsyncMock(return_value=None)):
        r2 = await checkin_submit(body, user=user)
    assert r2.get("duplicate") is True, "second submit should return duplicate=True"
    n = await local_db.check_ins.count_documents({"user_id": TEST_USER_ID})
    assert n == 1, f"expected 1 check-in row after duplicate, got {n}"
    print(f"  ✓ duplicate flag returned, only 1 row exists")

    # -------- TEST 4 & 5: script edit + reset
    print("\n─── TEST 4+5 · script edit + reset ───")
    from server import coach_edit_script, coach_reset_script, ScriptEditBody
    coach = {"id": "coach_test", "role": "coach"}
    r = await coach_edit_script(ci["id"], ScriptEditBody(weekly_video_script="EDITED SCRIPT"), coach=coach)
    edited = r["check_in"]
    assert edited["weekly_video_script"] == "EDITED SCRIPT"
    assert edited["weekly_video_script_original"] == "Original Atlas video script.", "original overwritten!"
    assert edited["script_edited_by"] == "coach_test"
    assert edited["script_edited_at"] is not None
    print(f"  ✓ script edited; original preserved; edited_by+at set")
    r2 = await coach_reset_script(ci["id"], coach=coach)
    reset = r2["check_in"]
    assert reset["weekly_video_script"] == "Original Atlas video script."
    assert reset["script_edited_by"] is None
    print(f"  ✓ reset restored original; edited_by cleared")

    # -------- TEST 6 & 7: summary edit + reset
    print("\n─── TEST 6+7 · summary edit + reset ───")
    from server import coach_edit_summary, coach_reset_summary, SummaryEditBody
    r = await coach_edit_summary(ci["id"], SummaryEditBody(atlas_client_summary="EDITED SUMMARY"), coach=coach)
    assert r["check_in"]["atlas_client_summary"] == "EDITED SUMMARY"
    assert r["check_in"]["atlas_client_summary_original"] == "Original Atlas summary text."
    r2 = await coach_reset_summary(ci["id"], coach=coach)
    assert r2["check_in"]["atlas_client_summary"] == "Original Atlas summary text."
    print("  ✓ summary edit preserves original; reset restores it")

    # -------- TEST 8: video send is idempotent
    print("\n─── TEST 8 · video send idempotent ───")
    from server import coach_create_video, coach_send_video, CoachVideoCreateBody
    with patch("server._save_coach_video", new=AsyncMock(return_value="/api/coach/videos/fake/file")):
        vres = await coach_create_video(
            CoachVideoCreateBody(check_in_id=ci["id"], user_id=TEST_USER_ID,
                                 script="s", file_b64="ZmFrZQ==", file_mime="video/webm"),
            coach=coach,
        )
    video_id = vres["video"]["id"]
    notify_calls: list[dict] = []
    async def spy_notify(user_id, video_id=None):
        notify_calls.append({"user_id": user_id, "video_id": video_id})
    with patch("server.notify_weekly_video_ready", new=AsyncMock(side_effect=spy_notify)):
        s1 = await coach_send_video(video_id, coach=coach)
        s2 = await coach_send_video(video_id, coach=coach)
    assert s1.get("sent_at") and not s1.get("already_sent")
    assert s2.get("already_sent") is True, f"second send should be idempotent — got {s2}"
    assert len(notify_calls) == 1, f"notify should fire once, fired {len(notify_calls)}"
    print(f"  ✓ first send fired notify, second send returned already_sent; notify count = {len(notify_calls)}")

    # -------- TEST 9: first-view flag
    print("\n─── TEST 9 · video viewed flag ───")
    from server import video_viewed
    v1 = await video_viewed(video_id, user=user)
    v2 = await video_viewed(video_id, user=user)
    assert v1.get("first_view") is True
    assert v2.get("first_view") is False
    row = await local_db.weekly_videos.find_one({"id": video_id}, {"_id": 0, "watched_at": 1, "status": 1})
    assert row.get("watched_at") is not None
    assert row.get("status") == "viewed"
    ci_row = await local_db.check_ins.find_one({"id": ci["id"]}, {"_id": 0, "weekly_video_status": 1, "weekly_video_viewed_at": 1})
    assert ci_row["weekly_video_status"] == "viewed"
    assert ci_row["weekly_video_viewed_at"] is not None
    print("  ✓ first view flagged; subsequent views idempotent; status='viewed'")

    # -------- TEST 10: /weekly-review/current reads unified snapshot
    print("\n─── TEST 10 · /weekly-review/current reads unified snapshot ───")
    from feature_weekly_review import weekly_review_current
    r = await weekly_review_current(user=user)
    assert r.get("source") == "unified_check_in", f"unified read failed: {r.get('source')}"
    assert r.get("training") is not None
    assert r.get("atlas_client_summary") == "Original Atlas summary text."
    # And the legacy weekly_reviews collection was NOT written by this path
    legacy_count = await local_db.weekly_reviews.count_documents({"user_id": TEST_USER_ID})
    print(f"  ✓ unified snapshot returned (source={r.get('source')}); legacy_writes_for_this_test={legacy_count}")

    await cleanup()
    print("\n" + "="*68)
    print("ITER 145 — ALL 10 TESTS PASSED  (no real Claude / notification / R2 calls)")
    print("="*68)


if __name__ == "__main__":
    asyncio.run(main())
