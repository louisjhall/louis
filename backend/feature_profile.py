"""feature_profile — CrewFit V1.5 profile assets + location.

Adds:
  POST /user/profile/photo            — multipart upload, saves to disk, sets user.profile_photo_url
  DELETE /user/profile/photo          — remove current photo
  GET  /user/profile/photo/{user_id}  — token-signed public read (used by client + coach dashboards)
  POST /user/location                 — accept manual or GPS-derived {city, country, tz, permission_status}
  POST /user/location/permission      — record permission state (granted/denied/not_requested)

Storage: /app/backend/uploads/profile_photos/<user_id>/<file>.<ext>
Only image mimes accepted; hard 5 MB cap.
"""
from __future__ import annotations

from fastapi import Depends, File, Form, HTTPException, Header, Query, UploadFile
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
import os

import jwt as _jwt

from server import (
    api, db, current_user, new_id, now_iso, logger,
    JWT_SECRET, JWT_ALGO,
)


PHOTO_ROOT = Path(os.environ.get("PROFILE_PHOTO_ROOT", "/app/backend/uploads/profile_photos"))
PHOTO_ROOT.mkdir(parents=True, exist_ok=True)

MAX_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_PHOTO_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


def _photo_ext(mime: str) -> str:
    return {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "image/heic": ".heic", "image/heif": ".heif",
    }.get(mime, ".bin")


async def _user_from_token(token: Optional[str]) -> dict:
    if not token:
        raise HTTPException(401, "Missing token")
    try:
        payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except _jwt.PyJWTError as e:
        raise HTTPException(401, f"Bad token: {e}")
    u = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(401, "User not found")
    return u


# ---- Photo upload ---------------------------------------------------------

@api.post("/user/profile/photo")
async def user_profile_photo_upload(
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_PHOTO_MIMES:
        raise HTTPException(400, f"unsupported image type: {mime}")

    user_dir = PHOTO_ROOT / user["id"]
    user_dir.mkdir(parents=True, exist_ok=True)
    ext = _photo_ext(mime)
    photo_id = new_id()
    target = user_dir / f"{photo_id}{ext}"

    total = 0
    try:
        with open(target, "wb") as out:
            while True:
                chunk = await file.read(512 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PHOTO_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(413, "photo exceeds 5MB limit")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception:
        logger.exception("profile photo write failed")
        target.unlink(missing_ok=True)
        raise HTTPException(500, "failed to save photo")
    finally:
        await file.close()

    # Delete any previously-linked file
    prev = user.get("profile_photo_path")
    if prev and prev != str(target):
        try: Path(prev).unlink(missing_ok=True)
        except Exception: pass

    now = now_iso()
    photo_url = f"/api/user/profile/photo/{user['id']}"        # frontend appends ?token=
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "profile_photo_url": photo_url,
            "profile_photo_path": str(target),
            "profile_photo_mime": mime,
            "profile_photo_size": total,
            "profile_photo_updated_at": now,
            "updated_at": now,
        }},
    )
    return {"ok": True, "profile_photo_url": photo_url,
            "profile_photo_size": total, "profile_photo_mime": mime}


@api.delete("/user/profile/photo")
async def user_profile_photo_delete(user: dict = Depends(current_user)):
    prev = user.get("profile_photo_path")
    if prev:
        try: Path(prev).unlink(missing_ok=True)
        except Exception: pass
    await db.users.update_one(
        {"id": user["id"]},
        {"$unset": {
            "profile_photo_url": "", "profile_photo_path": "",
            "profile_photo_mime": "", "profile_photo_size": "",
            "profile_photo_updated_at": "",
        }, "$set": {"updated_at": now_iso()}},
    )
    return {"ok": True}


@api.get("/user/profile/photo/{user_id}")
async def user_profile_photo_get(
    user_id: str,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """Serve the raw image. Accepts either header or ?token=... query auth.
    ANY authenticated user can view any user's profile photo (coach ↔ client is expected)."""
    if authorization and authorization.startswith("Bearer "):
        await current_user(authorization=authorization)
    else:
        await _user_from_token(token)
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "profile_photo_path": 1, "profile_photo_mime": 1})
    if not u or not u.get("profile_photo_path"):
        raise HTTPException(404, "no photo")
    p = Path(u["profile_photo_path"])
    if not p.exists():
        raise HTTPException(404, "photo file missing")
    return FileResponse(str(p), media_type=u.get("profile_photo_mime") or "image/jpeg")


# ---- Location + permission ------------------------------------------------

class LocationBody(BaseModel):
    city: Optional[str] = None
    country: Optional[str] = None
    tz: Optional[str] = None                        # IANA (e.g. "Europe/London")
    source: Optional[str] = "manual"                # manual | gps | ip
    permission_status: Optional[str] = None         # granted | denied | not_requested


class LocationPermissionBody(BaseModel):
    status: str                                     # granted | denied | not_requested
    platform: Optional[str] = None


@api.post("/user/location")
async def user_location_upsert(body: LocationBody, user: dict = Depends(current_user)):
    now = now_iso()
    updates: dict = {"location_last_updated_at": now, "updated_at": now}
    if body.city is not None:    updates["current_location_city"] = body.city
    if body.country is not None: updates["current_location_country"] = body.country
    if body.tz is not None:      updates["current_time_zone"] = body.tz
    if body.source is not None:  updates["location_source"] = body.source
    if body.permission_status is not None:
        updates["location_permission_status"] = body.permission_status
    if not updates:
        raise HTTPException(400, "no updates")
    await db.users.update_one({"id": user["id"]}, {"$set": updates})
    u = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {"user": u}


@api.post("/user/location/permission")
async def user_location_permission(body: LocationPermissionBody, user: dict = Depends(current_user)):
    if body.status not in ("granted", "denied", "not_requested"):
        raise HTTPException(400, "invalid status")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "location_permission_status": body.status,
            "location_permission_platform": body.platform,
            "location_permission_updated_at": now_iso(),
            "updated_at": now_iso(),
        }},
    )
    return {"ok": True, "status": body.status}
