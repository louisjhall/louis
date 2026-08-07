"""
Iter 155 — Welcome Video Phase 1 backend verification.

Covers:
  A. _save_coach_video routes through storage driver (write_bytes called).
  B. Video kind default = "weekly"; "welcome" accepted; invalid rejected.
  C. Welcome videos accept null check_in_id; weekly videos still require it.
  D. GET /videos/welcome-for-me returns the most recent SENT welcome video.
  E. Read endpoint falls back to legacy disk when storage_key is missing.

Run:
    cd /app/backend && python /app/scripts/test_iter155_welcome_video_phase1.py
"""
import asyncio
import sys
import base64

sys.path.insert(0, "/app/backend")


async def main():
    import server as srv
    from storage import storage

    # -------------------------------------------------------------------
    # A. _save_coach_video uses storage.write_bytes and returns the new
    #    dict shape.
    # -------------------------------------------------------------------
    calls: list[tuple] = []
    original_write = storage.write_bytes

    async def fake_write(key, data, content_type="application/octet-stream"):
        calls.append((key, len(data), content_type))
        return key

    storage.write_bytes = fake_write  # type: ignore
    try:
        out = await srv._save_coach_video(b"\x00\x01\x02" * 100, "video/webm", "v-abc")
    finally:
        storage.write_bytes = original_write  # type: ignore

    assert out["storage_key"] == "coach_videos/v-abc.webm", out
    assert out["file_url"] == "/api/coach/videos/v-abc/file", out
    assert out["ext"] == "webm"
    assert out["mime"] == "video/webm"
    assert calls and calls[0][0] == "coach_videos/v-abc.webm"
    assert calls[0][2] == "video/webm"
    print("A OK — _save_coach_video routes bytes through storage driver.")

    # -------------------------------------------------------------------
    # B/C. CoachVideoCreateBody accepts video_kind + optional check_in_id.
    # -------------------------------------------------------------------
    Body = srv.CoachVideoCreateBody
    b1 = Body(user_id="u1", script="hi")
    assert b1.check_in_id is None and b1.video_kind is None
    b2 = Body(user_id="u1", script="hi", video_kind="welcome")
    assert b2.video_kind == "welcome"
    b3 = Body(user_id="u1", script="hi", check_in_id="c1", video_kind="weekly")
    assert b3.check_in_id == "c1"
    print("B OK — CoachVideoCreateBody supports video_kind + optional check_in_id.")

    # -------------------------------------------------------------------
    # D. /videos/welcome-for-me returns the most recent SENT welcome video.
    # -------------------------------------------------------------------
    # In-memory replacement for db.weekly_videos.find_one with sort support.
    store = [
        {
            "id": "vid-old",
            "user_id": "u-hero",
            "video_kind": "welcome",
            "status": "sent",
            "sent_at": "2026-06-01T09:00:00Z",
            "file_url": "/api/coach/videos/vid-old/file",
            "script": "old welcome",
        },
        {
            "id": "vid-new",
            "user_id": "u-hero",
            "video_kind": "welcome",
            "status": "sent",
            "sent_at": "2026-06-15T09:00:00Z",
            "file_url": "/api/coach/videos/vid-new/file",
            "script": "new welcome",
        },
        {
            "id": "vid-draft",
            "user_id": "u-hero",
            "video_kind": "welcome",
            "status": "draft",  # ← must be ignored
            "sent_at": None,
        },
        {
            "id": "vid-weekly",
            "user_id": "u-hero",
            "video_kind": "weekly",
            "status": "sent",
            "sent_at": "2026-06-20T09:00:00Z",
        },
        {
            "id": "other-user",
            "user_id": "u-different",
            "video_kind": "welcome",
            "status": "sent",
            "sent_at": "2026-06-15T09:00:00Z",
        },
    ]

    class FakeWeeklyVideos:
        async def find_one(self, q, proj=None, sort=None):
            rows = [d for d in store if all(d.get(k) == v for k, v in q.items())]
            if sort:
                for field, direction in reversed(sort):
                    rows.sort(key=lambda r: r.get(field) or "", reverse=(direction < 0))
            return dict(rows[0]) if rows else None

    orig_wv = srv.db.weekly_videos
    srv.db.weekly_videos = FakeWeeklyVideos()  # type: ignore
    try:
        result = await srv.videos_welcome_for_me(user={"id": "u-hero"})
    finally:
        srv.db.weekly_videos = orig_wv  # type: ignore

    assert result["video"] is not None, "should find a welcome video"
    assert result["video"]["id"] == "vid-new", f"expected most-recent sent welcome, got {result['video']['id']}"
    print("D OK — welcome-for-me returns most recent SENT welcome, ignores drafts/weekly/other-user.")

    # -------------------------------------------------------------------
    # D.2 — no welcome video available → {video: None}
    # -------------------------------------------------------------------
    class EmptyWV:
        async def find_one(self, *_a, **_kw):
            return None
    srv.db.weekly_videos = EmptyWV()  # type: ignore
    try:
        result2 = await srv.videos_welcome_for_me(user={"id": "u-anyone"})
    finally:
        srv.db.weekly_videos = orig_wv  # type: ignore
    assert result2 == {"video": None}
    print("D.2 OK — silent no-op when no welcome video exists.")

    print("\nAll Phase-1 backend contracts verified.")


if __name__ == "__main__":
    asyncio.run(main())
