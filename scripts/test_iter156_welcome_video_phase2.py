"""
Iter 156 — Welcome Video Phase 2 backend verification.

Covers the two branches added on top of Phase 1:

  A. /coach/videos/{id}/send correctly SKIPS the check-in / coach-task
     stamping when the video is a welcome kind (no check_in_id present).
  B. /coach/videos/{id}/send inserts a `welcome_video` kind message
     (instead of `weekly_video`) for welcome videos.
  C. /coach/videos/{id}/viewed correctly SKIPS the check-in update when
     the video has no check_in_id (welcome kind), still flipping
     `status -> viewed` on the video doc.
  D. video_viewed still updates the check-in row for weekly videos.

Run:
    cd /app/backend && python /app/scripts/test_iter156_welcome_video_phase2.py
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")


async def main():
    import server as srv

    # ---- Fake collections ------------------------------------------------
    videos_store: dict[str, dict] = {}
    checkins_store: dict[str, dict] = {}
    coach_tasks_updates: list[tuple] = []
    messages_store: list[dict] = []

    class FakeVideos:
        async def find_one(self, q, _proj=None):
            for v in videos_store.values():
                if all(v.get(k) == val for k, val in q.items()):
                    return dict(v)
            return None

        async def update_one(self, q, upd):
            for v in videos_store.values():
                if all(v.get(k) == val for k, val in q.items()):
                    v.update(upd.get("$set") or {})
                    return type("R", (), {"modified_count": 1})()
            return type("R", (), {"modified_count": 0})()

    class FakeCheckins:
        async def find_one(self, q, _proj=None):
            for c in checkins_store.values():
                if all(c.get(k) == val for k, val in q.items()):
                    return dict(c)
            return None

        async def update_one(self, q, upd):
            # A `None` id means the caller wasn't guarded properly — treat
            # that as a hard failure so the guard bug can't come back.
            if q.get("id") is None:
                raise AssertionError("check_ins.update_one called with id=None")
            for c in checkins_store.values():
                if all(c.get(k) == val for k, val in q.items()):
                    c.update(upd.get("$set") or {})
                    return type("R", (), {"modified_count": 1})()
            return type("R", (), {"modified_count": 0})()

    class FakeCoachTasks:
        async def update_many(self, q, upd):
            coach_tasks_updates.append((q, upd))
            return type("R", (), {"modified_count": 0})()

    class FakeMessages:
        async def insert_one(self, doc):
            messages_store.append(dict(doc))
            return type("R", (), {"inserted_id": doc.get("id")})()

    orig_db = srv.db
    class FakeDB:
        weekly_videos = FakeVideos()
        check_ins = FakeCheckins()
        coach_tasks = FakeCoachTasks()
        messages = FakeMessages()
    srv.db = FakeDB()  # type: ignore

    # Silence the push-notify path.
    async def noop_notify(*_a, **_kw): pass
    orig_notify = srv.notify_weekly_video_ready
    srv.notify_weekly_video_ready = noop_notify  # type: ignore

    try:
        # ---- Setup ------------------------------------------------------
        videos_store["v-welcome"] = {
            "id": "v-welcome",
            "user_id": "u-client",
            "coach_id": "u-coach",
            "check_in_id": None,
            "video_kind": "welcome",
            "status": "recorded",
            "file_url": "/api/coach/videos/v-welcome/file",
        }
        videos_store["v-weekly"] = {
            "id": "v-weekly",
            "user_id": "u-client",
            "coach_id": "u-coach",
            "check_in_id": "c-1",
            "video_kind": "weekly",
            "status": "recorded",
            "file_url": "/api/coach/videos/v-weekly/file",
        }
        checkins_store["c-1"] = {"id": "c-1", "user_id": "u-client", "weekly_video_status": "recorded"}

        # ---- A/B — /send with welcome video --------------------------
        r_send_welcome = await srv.coach_send_video("v-welcome", coach={"id": "u-coach", "role": "coach"})
        assert r_send_welcome["ok"] is True
        assert videos_store["v-welcome"]["status"] == "sent"
        # Check-in row must NOT have been touched (there was none).
        assert checkins_store["c-1"]["weekly_video_status"] == "recorded", "welcome-send must not affect weekly check-in"
        # No coach-task update_many should have fired for a welcome video.
        assert not coach_tasks_updates, f"welcome-send must not update coach_tasks, got {coach_tasks_updates}"
        # Message kind must be welcome_video.
        m_welcome = [m for m in messages_store if m["video_id"] == "v-welcome"]
        assert m_welcome and m_welcome[0]["kind"] == "welcome_video", m_welcome
        assert "welcome" in m_welcome[0]["body"].lower()
        print("A+B OK — welcome video send skips check-in / coach-task updates and uses welcome_video kind.")

        # ---- Weekly still works normally --------------------------------
        r_send_weekly = await srv.coach_send_video("v-weekly", coach={"id": "u-coach", "role": "coach"})
        assert r_send_weekly["ok"] is True
        assert checkins_store["c-1"]["weekly_video_status"] == "sent"
        assert coach_tasks_updates, "weekly-send must update coach_tasks"
        m_weekly = [m for m in messages_store if m["video_id"] == "v-weekly"]
        assert m_weekly and m_weekly[0]["kind"] == "weekly_video"
        print("B.2 OK — weekly send path unchanged (check-in + coach-task + weekly_video message).")

        # ---- C — /viewed with welcome video ------------------------------
        r_viewed_welcome = await srv.video_viewed("v-welcome", user={"id": "u-client", "role": "client"})
        assert r_viewed_welcome["ok"] is True and r_viewed_welcome.get("first_view") is True
        assert videos_store["v-welcome"]["status"] == "viewed"
        # Check-in row unchanged (we already asserted sent above; nothing new here).
        print("C OK — welcome viewed flips video status without touching check-ins.")

        # ---- D — /viewed with weekly video still updates check-in --------
        r_viewed_weekly = await srv.video_viewed("v-weekly", user={"id": "u-client", "role": "client"})
        assert r_viewed_weekly["ok"] is True
        assert checkins_store["c-1"]["weekly_video_status"] == "viewed"
        print("D OK — weekly viewed still updates weekly_video_status on the check-in.")

    finally:
        srv.db = orig_db  # type: ignore
        srv.notify_weekly_video_ready = orig_notify  # type: ignore

    print("\nAll Phase-2 backend contracts verified.")


if __name__ == "__main__":
    asyncio.run(main())
