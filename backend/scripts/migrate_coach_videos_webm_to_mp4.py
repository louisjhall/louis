"""One-time migration: convert existing coach WebM videos to MP4.

Iter190 — WebM was the original recording format used by browser
MediaRecorder before we started transcoding on upload. Native iOS/Android
<video> players cannot play VP8/VP9-in-WebM, so we retro-actively convert
every stored WebM file to H.264/AAC MP4 (+faststart).

Behaviour:
  1. Query `db.weekly_videos` for docs whose `file_ext` == "webm" OR whose
     `storage_key` ends with ".webm".
  2. For each doc:
       a. Read the raw WebM bytes from the storage driver (R2 or disk).
       b. Transcode to MP4 via imageio-ffmpeg.
       c. Write the MP4 to a NEW storage key (same id, `.mp4` suffix).
       d. Verify the MP4 exists in storage after write.
       e. Update the mongo doc:
            file_ext          → "mp4"
            file_mime         → "video/mp4"
            storage_key       → the new `.mp4` key
            legacy_webm_key   → the OLD `.webm` key (kept for rollback)
            migrated_to_mp4_at→ ISO timestamp
       f. Leave the WebM bytes in R2 untouched — deletion is a separate
          follow-up once we've confirmed players can play the new MP4s.

Idempotency: docs that already have `migrated_to_mp4_at` set are skipped.
The script prints a summary and exits with rc=0 on success, rc=1 on any
transcode failures (though it still commits all successful conversions).

Usage:
    python /app/backend/scripts/migrate_coach_videos_webm_to_mp4.py
    python /app/backend/scripts/migrate_coach_videos_webm_to_mp4.py --dry-run
    python /app/backend/scripts/migrate_coach_videos_webm_to_mp4.py --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import os
import sys
from pathlib import Path

# Make `backend` importable when this script is run directly.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_BACKEND_ROOT / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from storage import storage  # noqa: E402


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _transcode_webm_to_mp4_sync(webm_bytes: bytes) -> bytes:
    """Same shape as server._transcode_webm_to_mp4_sync — duplicated here
    so the script has zero import-time coupling to the huge server.py
    module (which does a lot of work on import).
    """
    import subprocess
    import tempfile
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tin, \
         tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tout:
        in_path, out_path = tin.name, tout.name
        tin.write(webm_bytes)
        tin.flush()
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-y", "-loglevel", "error",
                "-i", in_path,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                out_path,
            ],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"ffmpeg rc={proc.returncode}: {err}")
        return Path(out_path).read_bytes()
    finally:
        for p in (in_path, out_path):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


async def migrate(dry_run: bool = False, limit: int | None = None) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME") or "test_database"
    if not mongo_url:
        print("ERROR: MONGO_URL not set", file=sys.stderr)
        return 2
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    q = {
        "$or": [
            {"file_ext": "webm"},
            {"storage_key": {"$regex": r"\.webm$"}},
        ],
        # Skip already-migrated docs so re-runs are cheap and idempotent.
        "migrated_to_mp4_at": {"$in": [None, ""]},
    }
    cursor = db.weekly_videos.find(q, {"_id": 0, "id": 1, "storage_key": 1, "file_ext": 1})
    if limit:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(length=1000)

    print(f"[migrate] driver={storage.name}  candidates={len(docs)}  dry_run={dry_run}")

    ok = 0
    failed: list[dict] = []
    skipped_no_bytes: list[str] = []
    for i, d in enumerate(docs, 1):
        vid = d.get("id")
        old_key = d.get("storage_key") or f"coach_videos/{vid}.webm"
        new_key = f"coach_videos/{vid}.mp4"
        print(f"[{i}/{len(docs)}] {vid}  {old_key} → {new_key}")
        webm = await storage.read_bytes(old_key)
        if not webm:
            print(f"    · SKIP  no bytes at {old_key}")
            skipped_no_bytes.append(vid)
            continue
        if dry_run:
            print(f"    · DRY-RUN  would transcode {len(webm)} bytes")
            ok += 1
            continue
        try:
            loop = asyncio.get_running_loop()
            mp4 = await loop.run_in_executor(None, _transcode_webm_to_mp4_sync, webm)
        except Exception as e:
            print(f"    · FAIL  transcode: {e}")
            failed.append({"id": vid, "stage": "transcode", "error": str(e)[:300]})
            continue
        try:
            await storage.write_bytes(new_key, mp4, content_type="video/mp4")
            # Verify the write landed before we flip the doc.
            if not await storage.exists(new_key):
                raise RuntimeError("post-write exists() returned False")
        except Exception as e:
            print(f"    · FAIL  upload: {e}")
            failed.append({"id": vid, "stage": "upload", "error": str(e)[:300]})
            continue
        # Flip the doc — but preserve the old webm key for rollback.
        await db.weekly_videos.update_one(
            {"id": vid},
            {"$set": {
                "storage_key": new_key,
                "file_ext": "mp4",
                "file_mime": "video/mp4",
                "legacy_webm_key": old_key,
                "migrated_to_mp4_at": _now_iso(),
            }},
        )
        print(f"    · OK    webm={len(webm)} → mp4={len(mp4)} bytes")
        ok += 1

    print("\n=== summary ===")
    print(f"  candidates:      {len(docs)}")
    print(f"  migrated:        {ok}")
    print(f"  failed:          {len(failed)}")
    print(f"  skipped_no_bytes:{len(skipped_no_bytes)}")
    if failed:
        for f in failed:
            print(f"    - {f}")
    if skipped_no_bytes:
        print(f"    missing bytes for: {skipped_no_bytes}")
    print("\nNote: legacy WebM bytes were NOT deleted — see `legacy_webm_key`")
    print("      on each migrated doc. Delete them via a follow-up script once")
    print("      clients have confirmed the MP4s play correctly.")
    return 0 if not failed else 1


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Report what would be migrated without writing anything")
    ap.add_argument("--limit", type=int, default=None, help="Process at most N candidates (useful for a smoke run)")
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    rc = asyncio.run(migrate(dry_run=args.dry_run, limit=args.limit))
    sys.exit(rc)
