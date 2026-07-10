"""storage — Media storage abstraction.

One shared interface for meal photos, brand images, social videos, and
subtitled MP4s. Two drivers ship in-tree:

* **DiskDriver** (default, matches today's behaviour). Writes under
  `/app/backend/uploads/{namespace}/{key}` and serves via the existing
  per-feature FileResponse endpoints. Zero external dependency.
* **R2Driver**. Cloudflare R2 (S3-compatible). Activates automatically the
  moment the ``R2_*`` env vars are present.  Zero egress fees + presigned
  URLs so meal photos remain private.

Extending:
    Add a new driver by subclassing ``StorageDriver`` and returning it from
    ``_pick_driver()`` when its env vars are set. All feature code should
    only import ``storage`` from this module — never touch the driver
    directly.

Usage:
    from storage import storage
    key = await storage.write_bytes("nutrition/photos/abc.jpg", data,
                                    content_type="image/jpeg")
    url = await storage.public_url(key)           # signed if private
    data = await storage.read_bytes(key)
    await storage.delete(key)
"""
from __future__ import annotations

import os
import asyncio
import io
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("storage")

DEFAULT_TTL = int(os.environ.get("STORAGE_URL_TTL", "3600"))
UPLOAD_ROOT = Path(os.environ.get("STORAGE_DISK_ROOT", "/app/backend/uploads"))


# ---------------------------------------------------------------------------
# Base driver
# ---------------------------------------------------------------------------

class StorageDriver:
    name: str = "base"

    async def write_bytes(self, key: str, data: bytes,
                          content_type: str = "application/octet-stream") -> str:
        raise NotImplementedError

    async def read_bytes(self, key: str) -> Optional[bytes]:
        raise NotImplementedError

    async def public_url(self, key: str, *, ttl: int = DEFAULT_TTL,
                         signed: bool = True) -> str:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def exists(self, key: str) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Disk driver (default / dev fallback)
# ---------------------------------------------------------------------------

class DiskDriver(StorageDriver):
    name = "disk"

    def __init__(self, root: Path = UPLOAD_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Normalise + prevent path traversal
        rel = Path(key).as_posix().lstrip("/")
        if ".." in rel.split("/"):
            raise ValueError("invalid key")
        return self.root / rel

    async def write_bytes(self, key: str, data: bytes,
                          content_type: str = "application/octet-stream") -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)

        def _write():
            p.write_bytes(data)
        await asyncio.get_running_loop().run_in_executor(None, _write)
        return key

    async def read_bytes(self, key: str) -> Optional[bytes]:
        p = self._path(key)
        if not p.exists():
            return None
        def _read(): return p.read_bytes()
        return await asyncio.get_running_loop().run_in_executor(None, _read)

    async def public_url(self, key: str, *, ttl: int = DEFAULT_TTL,
                         signed: bool = True) -> str:
        # Disk driver relies on the per-feature FileResponse endpoints
        # (e.g. /api/nutrition/photo/{id}/image?token=…). We return the
        # relative key so callers know to keep serving via their existing
        # route. Callers should NOT put this URL directly in HTML tags —
        # feature routers already resolve it.
        return key

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            def _rm(): p.unlink(missing_ok=True)
            await asyncio.get_running_loop().run_in_executor(None, _rm)

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()


# ---------------------------------------------------------------------------
# Cloudflare R2 driver (S3-compatible via boto3)
# ---------------------------------------------------------------------------

class R2Driver(StorageDriver):
    name = "r2"

    def __init__(self, *, account_id: str, access_key: str, secret_key: str,
                 bucket: str, public_hostname: Optional[str] = None,
                 endpoint_url: Optional[str] = None):
        try:
            import boto3            # noqa: F401
            from botocore.config import Config
        except Exception as e:
            raise RuntimeError(f"boto3 not available for R2 driver: {e}")
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.public_hostname = public_hostname or ""
        endpoint = endpoint_url or f"https://{account_id}.r2.cloudflarestorage.com"
        # R2 requires the S3v4 signature style.
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", region_name="auto",
                          retries={"max_attempts": 3}),
        )

    async def write_bytes(self, key: str, data: bytes,
                          content_type: str = "application/octet-stream") -> str:
        loop = asyncio.get_running_loop()
        def _put():
            self._client.put_object(
                Bucket=self.bucket, Key=key, Body=data,
                ContentType=content_type,
            )
        await loop.run_in_executor(None, _put)
        return key

    async def read_bytes(self, key: str) -> Optional[bytes]:
        loop = asyncio.get_running_loop()
        def _get():
            try:
                r = self._client.get_object(Bucket=self.bucket, Key=key)
                return r["Body"].read()
            except Exception:
                return None
        return await loop.run_in_executor(None, _get)

    async def public_url(self, key: str, *, ttl: int = DEFAULT_TTL,
                         signed: bool = True) -> str:
        if not signed and self.public_hostname:
            base = self.public_hostname.rstrip("/")
            return f"{base}/{key}"
        loop = asyncio.get_running_loop()
        def _sign():
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=ttl,
            )
        return await loop.run_in_executor(None, _sign)

    async def delete(self, key: str) -> None:
        loop = asyncio.get_running_loop()
        def _del():
            try:
                self._client.delete_object(Bucket=self.bucket, Key=key)
            except Exception:
                pass
        await loop.run_in_executor(None, _del)

    async def exists(self, key: str) -> bool:
        loop = asyncio.get_running_loop()
        def _h():
            try:
                self._client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False
        return await loop.run_in_executor(None, _h)


# ---------------------------------------------------------------------------
# Factory + singleton
# ---------------------------------------------------------------------------

def _pick_driver() -> StorageDriver:
    account = os.environ.get("R2_ACCOUNT_ID")
    key = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET")
    if account and key and secret and bucket:
        try:
            drv = R2Driver(
                account_id=account, access_key=key, secret_key=secret,
                bucket=bucket,
                public_hostname=os.environ.get("R2_PUBLIC_HOSTNAME"),
                endpoint_url=os.environ.get("R2_ENDPOINT_URL"),
            )
            logger.info("storage: using R2 driver (bucket=%s)", bucket)
            return drv
        except Exception:
            logger.exception("storage: R2 configured but failed to init — falling back to disk")
    logger.info("storage: using DISK driver (uploads=%s)", UPLOAD_ROOT)
    return DiskDriver()


storage: StorageDriver = _pick_driver()


def is_cloud() -> bool:
    """Return True when the active driver is a cloud/object store."""
    return storage.name != "disk"


# ---------------------------------------------------------------------------
# Backfill helper — used by the admin endpoint (scripts/backfill).
# ---------------------------------------------------------------------------

async def backfill_from_disk(subpaths: list[str] | None = None,
                             dry_run: bool = True) -> dict:
    """Walk /app/backend/uploads and upload each file to the active cloud
    driver. Returns a summary dict.  Safe to run multiple times — files that
    already exist on the cloud are skipped."""
    if storage.name == "disk":
        return {"skipped": True, "reason": "no cloud driver configured", "uploaded": 0}
    root = UPLOAD_ROOT
    total = 0
    uploaded = 0
    skipped = 0
    errors: list[dict] = []
    subs = subpaths or ["brand_images", "nutrition", "coach_videos", "social_studio"]
    for sub in subs:
        base = root / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            total += 1
            key = str(p.relative_to(root))
            try:
                if await storage.exists(key):
                    skipped += 1
                    continue
                if dry_run:
                    continue
                data = p.read_bytes()
                await storage.write_bytes(key, data, content_type=_guess_mime(p))
                uploaded += 1
            except Exception as e:
                errors.append({"key": key, "error": str(e)})
    return {"total": total, "uploaded": uploaded, "skipped": skipped,
            "errors": errors[:20], "driver": storage.name,
            "dry_run": dry_run}


def _guess_mime(p: Path) -> str:
    ext = p.suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".mp4": "video/mp4", ".mov": "video/quicktime",
        ".srt": "application/x-subrip",
    }.get(ext, "application/octet-stream")
