"""
reset_welcome_video.py — one-off idempotent reset for a single welcome
video row so the client sees it again after Iter 165's persistence fix.

Usage:
    python3 scripts/reset_welcome_video.py [VIDEO_ID]

Defaults to the ID supplied by the coach (ad16c546-16db-4cd1-900e-682e47a859da).
Safe to re-run: sets status=sent, clears watched_at.
"""
import asyncio, os, sys
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

DEFAULT_ID = "ad16c546-16db-4cd1-900e-682e47a859da"


async def main() -> int:
    vid = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ID
    c = AsyncIOMotorClient(os.getenv("MONGO_URL"))
    db = c[os.getenv("DB_NAME", "crewfit_v1")]

    row = await db.weekly_videos.find_one(
        {"id": vid}, {"_id": 0, "id": 1, "status": 1, "watched_at": 1, "user_id": 1, "video_kind": 1}
    )
    if not row:
        print(f"[warn] video {vid} not found in db.weekly_videos.")
        return 1

    print(f"Before:  status={row.get('status')!r}  watched_at={row.get('watched_at')!r}")
    res = await db.weekly_videos.update_one(
        {"id": vid},
        {"$set": {"status": "sent"}, "$unset": {"watched_at": ""}},
    )
    print(f"Matched={res.matched_count}  Modified={res.modified_count}")
    after = await db.weekly_videos.find_one(
        {"id": vid}, {"_id": 0, "status": 1, "watched_at": 1}
    )
    print(f"After:   status={after.get('status')!r}  watched_at={after.get('watched_at')!r}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
