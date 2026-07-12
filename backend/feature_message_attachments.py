"""feature_message_attachments — private 1:1 media attachments.

Clients can attach voice notes, images and videos to their messages to Louis.
Files are stored via the shared ``storage`` abstraction (R2 in production,
local disk in dev), never as base64 in Mongo. Only the sender and the
addressed coach can download the file (checked on every read).

Beta safety limits are enforced server-side so a bad client cannot exceed
them by editing the app:

* max 5 images per message
* max 1 video per message (≤ 60 s, ≤ 100 MB pre-compression)
* max 5-minute voice note (≤ 15 MB after client compression)
* max 20 uploads per user per rolling 24 hours
"""
from __future__ import annotations

import logging
import mimetypes
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response

logger = logging.getLogger("crewfit.msg_attachments")

# ---------------------------------------------------------------------------
# Beta guard-rails — override with env vars if a tester needs more headroom.
# ---------------------------------------------------------------------------
MAX_IMAGE_BYTES = int(os.environ.get("MSG_MAX_IMAGE_BYTES", 10 * 1024 * 1024))       # 10 MB
MAX_VIDEO_BYTES = int(os.environ.get("MSG_MAX_VIDEO_BYTES", 100 * 1024 * 1024))      # 100 MB
MAX_VOICE_BYTES = int(os.environ.get("MSG_MAX_VOICE_BYTES", 15 * 1024 * 1024))       #  15 MB
MAX_VOICE_SECONDS = int(os.environ.get("MSG_MAX_VOICE_SECONDS", 5 * 60))             #   5 min
MAX_VIDEO_SECONDS = int(os.environ.get("MSG_MAX_VIDEO_SECONDS", 60))                 #  60 s
DAILY_UPLOAD_CAP = int(os.environ.get("MSG_DAILY_UPLOAD_CAP", 20))

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}
ALLOWED_VIDEO_MIME = {"video/mp4", "video/quicktime", "video/x-msvideo", "video/webm"}
ALLOWED_VOICE_MIME = {"audio/m4a", "audio/mp4", "audio/aac", "audio/mpeg", "audio/wav", "audio/webm", "audio/ogg"}


def register(api: APIRouter, *, db, current_user, storage, new_id, now_iso, clean_doc, send_push=None):
    """Wire the attachment endpoints onto the existing ``/api`` router.

    We take everything as arguments to avoid a circular import with
    ``server.py`` (which owns the router + the auth dependency).
    """

    def _type_for(mime: str) -> Optional[str]:
        m = (mime or "").lower()
        if m in ALLOWED_IMAGE_MIME:
            return "image"
        if m in ALLOWED_VIDEO_MIME:
            return "video"
        if m in ALLOWED_VOICE_MIME:
            return "voice"
        return None

    def _max_bytes(kind: str) -> int:
        return {"image": MAX_IMAGE_BYTES, "video": MAX_VIDEO_BYTES, "voice": MAX_VOICE_BYTES}[kind]

    async def _check_daily_cap(user_id: str):
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        n = await db.message_attachments.count_documents({
            "uploaded_by": user_id, "created_at": {"$gte": since},
        })
        if n >= DAILY_UPLOAD_CAP:
            raise HTTPException(429, {
                "error": "daily_upload_cap",
                "detail": f"Daily attachment cap of {DAILY_UPLOAD_CAP} reached. Try again tomorrow or contact Louis.",
                "cap": DAILY_UPLOAD_CAP,
            })

    async def _may_access(user: dict, doc: dict) -> bool:
        """Sender or the current message recipient may access. Any other
        client is denied; coaches always may (so Louis can view any client
        attachment addressed to him via a message)."""
        if not doc:
            return False
        if user.get("role") == "coach":
            # Coach can only see attachments referenced by a message they
            # are the recipient/sender of. Enforce via the referenced msg.
            mid = doc.get("message_id")
            if not mid:
                # Uploaded but not yet attached to a message: only the uploader can access.
                return doc.get("uploaded_by") == user["id"]
            m = await db.messages.find_one({"id": mid}, {"from_user_id": 1, "to_user_id": 1})
            if not m:
                return False
            return user["id"] in (m.get("from_user_id"), m.get("to_user_id"))
        # Client: strict — must be uploader OR party to the referenced message.
        if doc.get("uploaded_by") == user["id"]:
            return True
        mid = doc.get("message_id")
        if not mid:
            return False
        m = await db.messages.find_one({"id": mid}, {"from_user_id": 1, "to_user_id": 1})
        if not m:
            return False
        return user["id"] in (m.get("from_user_id"), m.get("to_user_id"))

    # -----------------------------------------------------------------
    # Upload — multipart. Returns the attachment metadata; the client then
    # references it via `attachment_ids` in POST /api/messages.
    # -----------------------------------------------------------------
    @api.post("/messages/attachments")
    async def upload_attachment(
        file: UploadFile = File(...),
        kind: str = Form(...),
        duration_seconds: Optional[float] = Form(None),
        user: dict = Depends(current_user),
    ):
        kind = (kind or "").lower()
        if kind not in {"image", "video", "voice"}:
            raise HTTPException(400, {"error": "bad_kind", "detail": "kind must be image, video or voice"})

        await _check_daily_cap(user["id"])

        # Read up to the max allowed for this kind + 1 byte so we can detect over-limit.
        max_bytes = _max_bytes(kind)
        data = await file.read(max_bytes + 1)
        if not data:
            raise HTTPException(400, {"error": "empty_file"})
        if len(data) > max_bytes:
            human = {"image": "10 MB", "video": "100 MB", "voice": "15 MB"}[kind]
            raise HTTPException(413, {
                "error": "file_too_large",
                "detail": f"This file is too large. Max is {human} for {kind}s.",
                "kind": kind, "max_bytes": max_bytes,
            })

        # Validate mime.
        mime = (file.content_type or mimetypes.guess_type(file.filename or "")[0] or "").lower()
        detected = _type_for(mime)
        if detected is None or detected != kind:
            raise HTTPException(415, {
                "error": "unsupported_type",
                "detail": f"Unsupported {kind} type ({mime or 'unknown'}). Try JPG, PNG, MP4 or M4A.",
                "mime": mime,
            })

        # Validate duration for time-based media.
        if kind == "video" and duration_seconds and duration_seconds > MAX_VIDEO_SECONDS + 2:
            raise HTTPException(413, {
                "error": "video_too_long",
                "detail": "This video is too large. Please send a shorter clip.",
                "kind": "video",
            })
        if kind == "voice" and duration_seconds and duration_seconds > MAX_VOICE_SECONDS + 2:
            raise HTTPException(413, {
                "error": "voice_too_long",
                "detail": "Voice note over 5 minutes. Please shorten and retry.",
                "kind": "voice",
            })

        att_id = new_id()
        ext = os.path.splitext(file.filename or "")[1].lower() or {
            "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
            "image/heic": ".heic", "image/heif": ".heif",
            "video/mp4": ".mp4", "video/quicktime": ".mov",
            "audio/m4a": ".m4a", "audio/mp4": ".m4a", "audio/aac": ".aac",
            "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/webm": ".webm",
        }.get(mime, "")
        storage_key = f"messages/{user['id']}/{att_id}{ext}"
        await storage.write_bytes(storage_key, data, content_type=mime)

        doc = {
            "id": att_id,
            "message_id": None,           # filled when the message is sent
            "uploaded_by": user["id"],
            "type": kind,
            "mime_type": mime,
            "file_size": len(data),
            "duration_seconds": float(duration_seconds) if duration_seconds else None,
            "storage_key": storage_key,
            "thumbnail_key": None,
            "status": "uploaded",
            "created_at": now_iso(),
        }
        await db.message_attachments.insert_one(doc)
        doc.pop("_id", None)
        clean_doc(doc)
        # Provide a URL the client can immediately show while the message is being drafted.
        doc["url"] = f"/api/messages/attachments/{att_id}/file"
        return doc

    # -----------------------------------------------------------------
    # Download — auth-gated. Streams bytes back with the original mime.
    # -----------------------------------------------------------------
    @api.get("/messages/attachments/{att_id}/file")
    async def download_attachment(att_id: str, user: dict = Depends(current_user)):
        doc = await db.message_attachments.find_one({"id": att_id})
        if not doc:
            raise HTTPException(404, "not found")
        if not await _may_access(user, doc):
            raise HTTPException(403, "forbidden")
        data = await storage.read_bytes(doc["storage_key"])
        if not data:
            raise HTTPException(410, "missing")
        return Response(
            content=data,
            media_type=doc.get("mime_type") or "application/octet-stream",
            headers={"Cache-Control": "private, max-age=600"},
        )

    # -----------------------------------------------------------------
    # Metadata (used by chat rehydration + coach dashboard summaries).
    # -----------------------------------------------------------------
    @api.get("/messages/attachments/{att_id}")
    async def get_attachment(att_id: str, user: dict = Depends(current_user)):
        doc = await db.message_attachments.find_one({"id": att_id}, {"_id": 0})
        if not doc:
            raise HTTPException(404, "not found")
        if not await _may_access(user, doc):
            raise HTTPException(403, "forbidden")
        doc["url"] = f"/api/messages/attachments/{att_id}/file"
        return doc

    # -----------------------------------------------------------------
    # Discard — used when the composer cancels before send. Only the
    # uploader may delete, and only if the attachment isn't already
    # bound to a delivered message.
    # -----------------------------------------------------------------
    @api.delete("/messages/attachments/{att_id}")
    async def delete_attachment(att_id: str, user: dict = Depends(current_user)):
        doc = await db.message_attachments.find_one({"id": att_id})
        if not doc:
            return {"ok": True}
        if doc.get("uploaded_by") != user["id"]:
            raise HTTPException(403, "forbidden")
        if doc.get("message_id"):
            raise HTTPException(409, "already sent")
        try:
            await storage.delete(doc["storage_key"])
        except Exception:
            logger.exception("delete_attachment storage remove failed")
        await db.message_attachments.delete_one({"id": att_id})
        return {"ok": True}

    logger.info("feature_message_attachments: registered (image/video/voice limits + 24h cap)")


async def hydrate_message_attachments(db, doc: dict) -> dict:
    """Attach a hydrated ``attachments`` list to a message dict.

    Called by the messages endpoints so the chat UI can render bubbles
    inline. Adds a relative `url` for each attachment (auth-checked on
    fetch by the download endpoint).
    """
    ids = doc.get("attachment_ids") or []
    if not ids:
        doc["attachments"] = []
        return doc
    rows = await db.message_attachments.find({"id": {"$in": ids}}, {"_id": 0}).to_list(20)
    for r in rows:
        r["url"] = f"/api/messages/attachments/{r['id']}/file"
    # Preserve client-side order.
    order = {i: n for n, i in enumerate(ids)}
    rows.sort(key=lambda r: order.get(r.get("id"), 99))
    doc["attachments"] = rows
    return doc
