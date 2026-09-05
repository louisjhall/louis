"""feature_on_demand — On Demand content library (Stage 1).

Foundation for a coach-curated, always-available content library. Ships
three content types:

* **workout** — a structured workout uploaded as JSON in the same shape
  used by the rest of the app. Attached to `db.workouts` when a client
  starts it so the Guided Flow / timers / alternatives all keep working
  identically. Stored raw on the item doc so we can rehydrate on demand.
* **video** — an educational or coaching video (mp4/webm/mov). Stored in
  R2 via `storage.write_bytes`.
* **audio** — a coach-recorded audio track (mp3/m4a/wav). Also in R2.

Coach management endpoints live under `/api/on-demand/coach/*` and
require the coach role. Read endpoints are exposed to any authenticated
user so we can wire the placeholder client screen later without another
migration.

Stage-1 scope explicitly excludes: premium gating, offline downloads,
background/lock-screen audio, member-facing browse UI. Those layer on
top of this foundation without schema changes.

Media delivery contract:
    Client calls `GET /api/on-demand/items/{id}/media-url` which returns
    a presigned URL (short TTL). The frontend then hands the URL to the
    <video>/<audio> element directly — the presigned link keeps R2 keys
    from leaking and matches the security posture the task doc
    specifies.
"""
from __future__ import annotations

import base64
import io
import os
import re
import zipfile
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from server import (
    api, db, current_user, require_role, new_id, now_iso, logger,
)
import storage as _storage


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------

CONTENT_TYPES = {"workout", "video", "audio"}

_VIDEO_EXTS = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "m4v": "video/mp4"}
_AUDIO_EXTS = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "aac": "audio/aac", "ogg": "audio/ogg"}
_IMAGE_EXTS = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

_MAX_MEDIA_BYTES = 500 * 1024 * 1024   # 500 MB hard cap per upload (defensive)
_MAX_IMAGE_BYTES = 10 * 1024 * 1024    # 10 MB thumbnail cap
_URL_TTL_SECONDS = 60 * 30              # 30 min presigned URLs (plenty for playback)


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s or "untagged"


def _decode_b64(payload: str) -> bytes:
    """Accept `data:mime;base64,XXXX` OR raw XXXX. Returns raw bytes."""
    if not payload:
        raise HTTPException(400, "empty file payload")
    core = payload.split(",", 1)[-1]
    try:
        return base64.b64decode(core, validate=False)
    except Exception as e:
        raise HTTPException(400, f"invalid base64 file: {e}")


def _pick_mime_ext(kind: str, hint_mime: str, hint_name: str) -> tuple[str, str]:
    """Return `(ext, mime)` normalised for `kind` ∈ {video, audio, image}."""
    if kind == "video":
        table = _VIDEO_EXTS
        default = ("mp4", "video/mp4")
    elif kind == "audio":
        table = _AUDIO_EXTS
        default = ("mp3", "audio/mpeg")
    elif kind == "image":
        table = _IMAGE_EXTS
        default = ("jpg", "image/jpeg")
    else:
        raise HTTPException(400, f"unknown media kind: {kind}")

    # First try mime hint.
    lower_mime = (hint_mime or "").lower()
    for ext, mime in table.items():
        if mime in lower_mime:
            return ext, mime
    # Then extension from filename.
    if hint_name and "." in hint_name:
        ext = hint_name.rsplit(".", 1)[-1].lower()
        if ext in table:
            return ext, table[ext]
    return default


def _clean_item_doc(doc: dict) -> dict:
    """Strip internal-only fields before returning to the client."""
    doc.pop("_id", None)
    # `workout_json` is potentially large — surface only for detail lookups
    # (endpoints that want it can re-fetch).
    return doc


# ---------------------------------------------------------------------------
# Pydantic bodies
# ---------------------------------------------------------------------------

class CategoryBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class TagBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)


class ItemMedia(BaseModel):
    """Inline base64 media payload — matches how coach_videos already ships."""
    file_b64: str
    file_mime: Optional[str] = None
    file_name: Optional[str] = None


class ItemBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=140)
    description: Optional[str] = Field(default="", max_length=4000)
    content_type: str                                # workout | video | audio
    category_id: Optional[str] = None
    tag_ids: list[str] = Field(default_factory=list)
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=60 * 60 * 6)
    thumbnail: Optional[ItemMedia] = None
    thumbnail_filename: Optional[str] = None          # Iter200 · bundled asset filename (e.g. `w-001.jpg`)
    media: Optional[ItemMedia] = None                 # video / audio bytes
    workout_json: Optional[dict[str, Any]] = None     # workout content
    published: bool = False
    external_ref: Optional[str] = None                # Iter200 · idempotent bulk-import key
    equipment: list[str] = Field(default_factory=list)  # Iter200 · normalised equipment list


class ItemPatchBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=140)
    description: Optional[str] = Field(default=None, max_length=4000)
    category_id: Optional[str] = None
    tag_ids: Optional[list[str]] = None
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=60 * 60 * 6)
    thumbnail: Optional[ItemMedia] = None
    thumbnail_filename: Optional[str] = None
    media: Optional[ItemMedia] = None
    workout_json: Optional[dict[str, Any]] = None
    published: Optional[bool] = None
    external_ref: Optional[str] = None
    equipment: Optional[list[str]] = None


class PublishBody(BaseModel):
    published: bool


# ---------------------------------------------------------------------------
# Categories — coach CRUD + public list
# ---------------------------------------------------------------------------

@api.get("/on-demand/categories")
async def od_list_categories(_: dict = Depends(current_user)):
    rows = await db.on_demand_categories.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    return {"categories": rows}


@api.post("/on-demand/coach/categories")
async def od_create_category(body: CategoryBody, coach: dict = Depends(require_role("coach"))):
    slug = _slugify(body.name)
    existing = await db.on_demand_categories.find_one({"slug": slug}, {"_id": 0})
    if existing:
        # Idempotent — return existing to avoid dupes when coach clicks twice.
        return {"category": existing, "already_exists": True}
    doc = {
        "id": new_id(),
        "name": body.name.strip(),
        "slug": slug,
        "created_at": now_iso(),
        "created_by": coach["id"],
    }
    await db.on_demand_categories.insert_one(doc)
    doc.pop("_id", None)
    return {"category": doc, "already_exists": False}


@api.patch("/on-demand/coach/categories/{cat_id}")
async def od_rename_category(cat_id: str, body: CategoryBody,
                             coach: dict = Depends(require_role("coach"))):
    slug = _slugify(body.name)
    r = await db.on_demand_categories.update_one(
        {"id": cat_id},
        {"$set": {"name": body.name.strip(), "slug": slug, "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "category_not_found")
    doc = await db.on_demand_categories.find_one({"id": cat_id}, {"_id": 0})
    return {"category": doc}


@api.delete("/on-demand/coach/categories/{cat_id}")
async def od_delete_category(cat_id: str, coach: dict = Depends(require_role("coach"))):
    # Detach from items so a stale category_id doesn't stay on published rows.
    await db.on_demand_items.update_many(
        {"category_id": cat_id}, {"$set": {"category_id": None}},
    )
    r = await db.on_demand_categories.delete_one({"id": cat_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "category_not_found")
    return {"ok": True, "deleted_id": cat_id}


# ---------------------------------------------------------------------------
# Tags — coach CRUD + public list
# ---------------------------------------------------------------------------

@api.get("/on-demand/tags")
async def od_list_tags(_: dict = Depends(current_user)):
    rows = await db.on_demand_tags.find({}, {"_id": 0}).sort("name", 1).to_list(500)
    return {"tags": rows}


@api.post("/on-demand/coach/tags")
async def od_create_tag(body: TagBody, coach: dict = Depends(require_role("coach"))):
    slug = _slugify(body.name)
    existing = await db.on_demand_tags.find_one({"slug": slug}, {"_id": 0})
    if existing:
        return {"tag": existing, "already_exists": True}
    doc = {
        "id": new_id(),
        "name": body.name.strip(),
        "slug": slug,
        "created_at": now_iso(),
        "created_by": coach["id"],
    }
    await db.on_demand_tags.insert_one(doc)
    doc.pop("_id", None)
    return {"tag": doc, "already_exists": False}


@api.patch("/on-demand/coach/tags/{tag_id}")
async def od_rename_tag(tag_id: str, body: TagBody,
                        coach: dict = Depends(require_role("coach"))):
    slug = _slugify(body.name)
    r = await db.on_demand_tags.update_one(
        {"id": tag_id},
        {"$set": {"name": body.name.strip(), "slug": slug, "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "tag_not_found")
    doc = await db.on_demand_tags.find_one({"id": tag_id}, {"_id": 0})
    return {"tag": doc}


@api.delete("/on-demand/coach/tags/{tag_id}")
async def od_delete_tag(tag_id: str, coach: dict = Depends(require_role("coach"))):
    # Pull the tag id from every item it was attached to so we don't
    # leak dangling references.
    await db.on_demand_items.update_many(
        {"tag_ids": tag_id}, {"$pull": {"tag_ids": tag_id}},
    )
    r = await db.on_demand_tags.delete_one({"id": tag_id})
    if r.deleted_count == 0:
        raise HTTPException(404, "tag_not_found")
    return {"ok": True, "deleted_id": tag_id}


# ---------------------------------------------------------------------------
# Items — coach CRUD
# ---------------------------------------------------------------------------

async def _validate_taxonomy(category_id: Optional[str], tag_ids: list[str]) -> None:
    if category_id:
        exists = await db.on_demand_categories.count_documents({"id": category_id})
        if not exists:
            raise HTTPException(400, f"category_not_found: {category_id}")
    if tag_ids:
        cnt = await db.on_demand_tags.count_documents({"id": {"$in": list(set(tag_ids))}})
        if cnt != len(set(tag_ids)):
            raise HTTPException(400, "one_or_more_tag_ids_not_found")


async def _persist_media(item_id: str, kind: str, payload: ItemMedia) -> dict:
    """Decode + store `payload.file_b64` under `on_demand/{kind}/{id}.{ext}`.

    Returns `{storage_key, ext, mime, size_bytes}`.
    """
    raw = _decode_b64(payload.file_b64)
    cap = _MAX_IMAGE_BYTES if kind == "image" else _MAX_MEDIA_BYTES
    if len(raw) > cap:
        raise HTTPException(413, f"{kind}_file_too_large ({len(raw)} > {cap} bytes)")
    ext, mime = _pick_mime_ext(kind, payload.file_mime or "", payload.file_name or "")
    key = f"on_demand/{kind}/{item_id}.{ext}"
    await _storage.storage.write_bytes(key, raw, content_type=mime)
    return {"storage_key": key, "ext": ext, "mime": mime, "size_bytes": len(raw)}


@api.get("/on-demand/coach/items")
async def od_coach_list_items(
    coach: dict = Depends(require_role("coach")),
    content_type: Optional[str] = None,
    category_id: Optional[str] = None,
    published: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 200,
):
    q: dict[str, Any] = {}
    if content_type in CONTENT_TYPES:
        q["content_type"] = content_type
    if category_id:
        q["category_id"] = category_id
    if published is not None:
        q["published"] = bool(published)
    if search:
        q["title"] = {"$regex": re.escape(search), "$options": "i"}
    rows = await db.on_demand_items.find(
        q,
        # Drop the heavy workout_json blob from list responses.
        {"_id": 0, "workout_json": 0},
    ).sort("created_at", -1).to_list(max(1, min(limit, 500)))
    return {"items": rows, "count": len(rows)}


@api.get("/on-demand/coach/items/{item_id}")
async def od_coach_get_item(item_id: str, coach: dict = Depends(require_role("coach"))):
    doc = await db.on_demand_items.find_one({"id": item_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "item_not_found")
    return {"item": doc}


@api.post("/on-demand/coach/items")
async def od_coach_create_item(body: ItemBody, coach: dict = Depends(require_role("coach"))):
    if body.content_type not in CONTENT_TYPES:
        raise HTTPException(400, f"content_type must be one of {sorted(CONTENT_TYPES)}")

    # Type-specific payload validation up-front so we don't leave orphan
    # bytes in R2 if the request is malformed.
    if body.content_type == "workout":
        if not body.workout_json or not isinstance(body.workout_json, dict):
            raise HTTPException(400, "workout content_type requires workout_json")
    else:
        if not body.media or not body.media.file_b64:
            raise HTTPException(400, f"{body.content_type} content_type requires media.file_b64")

    await _validate_taxonomy(body.category_id, body.tag_ids)

    item_id = new_id()
    thumb_meta: Optional[dict] = None
    media_meta: Optional[dict] = None

    if body.thumbnail and body.thumbnail.file_b64:
        thumb_meta = await _persist_media(item_id, "image", body.thumbnail)

    if body.content_type in ("video", "audio"):
        media_meta = await _persist_media(item_id, body.content_type, body.media)  # type: ignore[arg-type]

    doc = {
        "id": item_id,
        "title": body.title.strip(),
        "description": (body.description or "").strip(),
        "content_type": body.content_type,
        "category_id": body.category_id,
        "tag_ids": list(dict.fromkeys(body.tag_ids or [])),  # de-dupe, preserve order
        "duration_seconds": body.duration_seconds,
        "thumbnail_storage_key": (thumb_meta or {}).get("storage_key"),
        "thumbnail_mime":        (thumb_meta or {}).get("mime"),
        "thumbnail_ext":         (thumb_meta or {}).get("ext"),
        "thumbnail_filename":    (body.thumbnail_filename or None),
        "media_storage_key":     (media_meta or {}).get("storage_key"),
        "media_mime":            (media_meta or {}).get("mime"),
        "media_ext":             (media_meta or {}).get("ext"),
        "media_size_bytes":      (media_meta or {}).get("size_bytes"),
        "workout_json": body.workout_json if body.content_type == "workout" else None,
        "published": bool(body.published),
        "external_ref": body.external_ref or None,
        "equipment": list(dict.fromkeys(body.equipment or [])),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "created_by": coach["id"],
    }
    await db.on_demand_items.insert_one(doc)
    return {"item": _clean_item_doc(doc)}


@api.patch("/on-demand/coach/items/{item_id}")
async def od_coach_update_item(item_id: str, body: ItemPatchBody,
                               coach: dict = Depends(require_role("coach"))):
    doc = await db.on_demand_items.find_one({"id": item_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "item_not_found")

    updates: dict[str, Any] = {}
    if body.title is not None:            updates["title"] = body.title.strip()
    if body.description is not None:      updates["description"] = body.description.strip()
    if body.category_id is not None:      updates["category_id"] = body.category_id or None
    if body.tag_ids is not None:          updates["tag_ids"] = list(dict.fromkeys(body.tag_ids))
    if body.duration_seconds is not None: updates["duration_seconds"] = body.duration_seconds
    if body.published is not None:        updates["published"] = bool(body.published)
    if body.workout_json is not None and doc.get("content_type") == "workout":
        updates["workout_json"] = body.workout_json

    await _validate_taxonomy(
        updates.get("category_id", doc.get("category_id")),
        updates.get("tag_ids", doc.get("tag_ids") or []),
    )

    # Replace thumbnail bytes if a new one is provided.
    if body.thumbnail and body.thumbnail.file_b64:
        thumb_meta = await _persist_media(item_id, "image", body.thumbnail)
        # Best-effort delete of the old thumbnail if it lived under a
        # different key (e.g. extension change).
        old_key = doc.get("thumbnail_storage_key")
        if old_key and old_key != thumb_meta["storage_key"]:
            try:
                await _storage.storage.delete(old_key)
            except Exception:
                logger.exception("on_demand thumbnail cleanup failed for %s", old_key)
        updates["thumbnail_storage_key"] = thumb_meta["storage_key"]
        updates["thumbnail_mime"] = thumb_meta["mime"]
        updates["thumbnail_ext"] = thumb_meta["ext"]

    # Replace media bytes if a new one is provided (video/audio only).
    if body.media and body.media.file_b64 and doc.get("content_type") in ("video", "audio"):
        media_meta = await _persist_media(item_id, doc["content_type"], body.media)
        old_key = doc.get("media_storage_key")
        if old_key and old_key != media_meta["storage_key"]:
            try:
                await _storage.storage.delete(old_key)
            except Exception:
                logger.exception("on_demand media cleanup failed for %s", old_key)
        updates["media_storage_key"] = media_meta["storage_key"]
        updates["media_mime"] = media_meta["mime"]
        updates["media_ext"] = media_meta["ext"]
        updates["media_size_bytes"] = media_meta["size_bytes"]

    if not updates:
        return {"item": _clean_item_doc(doc)}
    updates["updated_at"] = now_iso()
    await db.on_demand_items.update_one({"id": item_id}, {"$set": updates})
    fresh = await db.on_demand_items.find_one({"id": item_id}, {"_id": 0})
    return {"item": fresh}


@api.post("/on-demand/coach/items/{item_id}/publish")
async def od_coach_publish(item_id: str, body: PublishBody,
                           coach: dict = Depends(require_role("coach"))):
    r = await db.on_demand_items.update_one(
        {"id": item_id},
        {"$set": {"published": bool(body.published), "updated_at": now_iso()}},
    )
    if r.matched_count == 0:
        raise HTTPException(404, "item_not_found")
    return {"ok": True, "id": item_id, "published": bool(body.published)}


@api.delete("/on-demand/coach/items/{item_id}")
async def od_coach_delete_item(item_id: str, coach: dict = Depends(require_role("coach"))):
    doc = await db.on_demand_items.find_one({"id": item_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "item_not_found")
    # Best-effort cleanup — we don't fail the delete if R2 hiccups.
    for k in ("thumbnail_storage_key", "media_storage_key"):
        key = doc.get(k)
        if key:
            try:
                await _storage.storage.delete(key)
            except Exception:
                logger.exception("on_demand storage cleanup failed for %s", key)
    await db.on_demand_items.delete_one({"id": item_id})
    return {"ok": True, "deleted_id": item_id}


# ---------------------------------------------------------------------------
# Public read + media delivery
# ---------------------------------------------------------------------------

@api.get("/on-demand/items")
async def od_public_list_items(
    user: dict = Depends(current_user),
    content_type: Optional[str] = None,
    category_id: Optional[str] = None,
    limit: int = 200,
):
    """Public list of On Demand items.

    Non-coach users only see PUBLISHED items. Coaches see everything so
    they can preview the browse experience without publishing first. The
    heavy `workout_json` blob is stripped — clients only need list-card
    metadata; workout starts pull the full doc via
    `/on-demand/items/{id}/start-workout`.
    """
    q: dict[str, Any] = {}
    if user.get("role") != "coach":
        q["published"] = True
    if content_type in CONTENT_TYPES:
        q["content_type"] = content_type
    if category_id:
        q["category_id"] = category_id
    rows = await db.on_demand_items.find(
        q,
        {"_id": 0, "workout_json": 0},
    ).sort("created_at", -1).to_list(max(1, min(limit, 500)))
    return {"items": rows, "count": len(rows)}


@api.get("/on-demand/items/{item_id}")
async def od_item_detail(item_id: str, user: dict = Depends(current_user)):
    """Return a single item. Coaches see drafts too; clients only see
    published items. Workout JSON is included so the guided flow can
    hydrate on start."""
    doc = await db.on_demand_items.find_one({"id": item_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "item_not_found")
    if not doc.get("published") and user.get("role") != "coach":
        raise HTTPException(404, "item_not_found")
    return {"item": doc}


@api.get("/on-demand/items/{item_id}/media-url")
async def od_item_media_url(item_id: str, user: dict = Depends(current_user)):
    """Return a short-lived presigned URL for the video/audio bytes.

    We do NOT emit a URL for workout items — clients hydrate `workout_json`
    directly and hand it to the existing Guided Flow.
    """
    doc = await db.on_demand_items.find_one(
        {"id": item_id},
        {"_id": 0, "media_storage_key": 1, "media_mime": 1, "content_type": 1, "published": 1},
    )
    if not doc:
        raise HTTPException(404, "item_not_found")
    if not doc.get("published") and user.get("role") != "coach":
        raise HTTPException(404, "item_not_found")
    if doc.get("content_type") == "workout":
        raise HTTPException(400, "workout items have no media url — use workout_json instead")
    key = doc.get("media_storage_key")
    if not key:
        raise HTTPException(404, "item_has_no_media")
    try:
        url = await _storage.storage.public_url(key, ttl=_URL_TTL_SECONDS, signed=True)
    except Exception as e:
        logger.exception("on_demand presign failed for %s", key)
        raise HTTPException(502, f"failed_to_sign_url: {e}")
    return {
        "url": url,
        "mime": doc.get("media_mime"),
        "expires_in": _URL_TTL_SECONDS,
        "driver": _storage.storage.name,
    }


@api.get("/on-demand/items/{item_id}/thumbnail-url")
async def od_item_thumbnail_url(item_id: str, user: dict = Depends(current_user)):
    """Presigned URL for the thumbnail image. Same visibility rules as
    the item itself."""
    doc = await db.on_demand_items.find_one(
        {"id": item_id},
        {"_id": 0, "thumbnail_storage_key": 1, "thumbnail_mime": 1, "published": 1},
    )
    if not doc:
        raise HTTPException(404, "item_not_found")
    if not doc.get("published") and user.get("role") != "coach":
        raise HTTPException(404, "item_not_found")
    key = doc.get("thumbnail_storage_key")
    if not key:
        raise HTTPException(404, "item_has_no_thumbnail")
    try:
        url = await _storage.storage.public_url(key, ttl=_URL_TTL_SECONDS, signed=True)
    except Exception as e:
        logger.exception("on_demand thumbnail presign failed for %s", key)
        raise HTTPException(502, f"failed_to_sign_url: {e}")
    return {"url": url, "mime": doc.get("thumbnail_mime"), "expires_in": _URL_TTL_SECONDS}


logger.info("feature_on_demand: /on-demand/* endpoints registered")


# ---------------------------------------------------------------------------
# Iter200 · Bulk import — taxonomy ensure + multi-item create
# ---------------------------------------------------------------------------

# Where the coach bulk-import endpoint writes unzipped thumbnails. Metro
# picks these up at BUILD time — new files only reach deployed builds
# after a redeploy. Kept configurable so tests / other environments can
# override without touching code.
_THUMBNAIL_TARGET_DIR = os.environ.get(
    "ONDEMAND_THUMBNAIL_DIR",
    "/app/frontend/assets/on-demand-thumbnails",
)
_THUMBNAIL_FILENAME_RE = re.compile(r"^w-\d{3}\.jpe?g$", re.IGNORECASE)
_THUMBNAIL_MAX_FILES = 500          # generous — 100 workouts + slack
_THUMBNAIL_MAX_BYTES_PER = 5 * 1024 * 1024   # 5 MB per file
_THUMBNAIL_MAX_ZIP_BYTES = 200 * 1024 * 1024  # 200 MB total (decoded zip)


class ThumbnailZipBody(BaseModel):
    """Base64-encoded zip payload from the coach bulk-import modal."""
    zip_b64: str


@api.post("/on-demand/coach/thumbnails/bulk-upload")
async def od_coach_thumbnails_bulk_upload(
    body: ThumbnailZipBody, coach: dict = Depends(require_role("coach")),
):
    """Unzip a coach-supplied zip into the on-demand thumbnails asset
    dir. Every file inside the zip MUST match ``w-\\d{3}\\.jpg`` (case-
    insensitive; a ``.jpeg`` variant is normalised to ``.jpg``). Anything
    else is rejected up-front — protects against path traversal and
    stray thumbnails.

    Metro bundles this directory at BUILD time so the coach still needs
    to redeploy for the new thumbnails to appear in shipped builds. The
    response surfaces this note verbatim so the UI can echo it.
    """
    raw = _decode_b64(body.zip_b64)
    if len(raw) > _THUMBNAIL_MAX_ZIP_BYTES:
        raise HTTPException(413, f"zip_too_large ({len(raw)} > {_THUMBNAIL_MAX_ZIP_BYTES})")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw), "r")
    except zipfile.BadZipFile as e:
        raise HTTPException(400, f"invalid_zip: {e}")

    entries = [i for i in zf.infolist() if not i.is_dir()]
    if len(entries) > _THUMBNAIL_MAX_FILES:
        raise HTTPException(413, f"too_many_files_in_zip ({len(entries)} > {_THUMBNAIL_MAX_FILES})")

    os.makedirs(_THUMBNAIL_TARGET_DIR, exist_ok=True)

    written: list[str] = []
    skipped: list[dict] = []
    for info in entries:
        # (a) Strip any leading directories the zip might carry; we only
        # care about the basename. This also blocks trivial path traversal
        # like `../../etc/passwd` — the split takes the tail component
        # so any `..` gets discarded.
        basename = os.path.basename(info.filename.replace("\\", "/"))
        if not basename or basename.startswith("."):
            skipped.append({"filename": info.filename, "reason": "empty_or_hidden"})
            continue

        # (b) Enforce the filename convention up-front. Normalise `.jpeg`
        # → `.jpg` and lower-case so the on-disk names always match the
        # `thumbnail_filename` slot the client uses (`resolveThumbnail`).
        lower = basename.lower()
        if not _THUMBNAIL_FILENAME_RE.match(lower):
            skipped.append({"filename": info.filename, "reason": "filename_does_not_match_w-NNN.jpg"})
            continue
        normalised = re.sub(r"\.jpeg$", ".jpg", lower)

        # (c) Size guard per-file.
        if info.file_size > _THUMBNAIL_MAX_BYTES_PER:
            skipped.append({"filename": info.filename, "reason": f"file_too_large ({info.file_size} > {_THUMBNAIL_MAX_BYTES_PER})"})
            continue

        # (d) Read + write.
        try:
            data = zf.read(info)
        except Exception as e:
            skipped.append({"filename": info.filename, "reason": f"unreadable: {e}"})
            continue
        # Sanity-check the first two bytes so we don't accept a PNG
        # masquerading as .jpg — Metro's build-time parser would still
        # reject it later, so we fail fast here.
        if not data.startswith(b"\xff\xd8"):
            skipped.append({"filename": info.filename, "reason": "not_a_jpeg_payload"})
            continue

        dest = os.path.join(_THUMBNAIL_TARGET_DIR, normalised)
        try:
            with open(dest, "wb") as fh:
                fh.write(data)
            written.append(normalised)
        except Exception as e:
            skipped.append({"filename": info.filename, "reason": f"write_failed: {e}"})

    logger.info(
        "on_demand.thumbnails_bulk_upload: %d written / %d skipped (target=%s)",
        len(written), len(skipped), _THUMBNAIL_TARGET_DIR,
    )
    return {
        "written": sorted(written),
        "skipped": skipped,
        "target_dir": _THUMBNAIL_TARGET_DIR,
        "total_files_in_zip": len(entries),
        "note": (
            "Metro bundles this directory at build time. New thumbnails "
            "appear in the current dev preview immediately but require a "
            "redeploy to reach production builds."
        ),
    }


class TaxonomyEnsureBody(BaseModel):
    """Upsert-by-name/slug taxonomy resolver.

    Any category / tag whose slug does not exist yet is created; existing
    ones are returned unchanged. Response contains fully-resolved ID maps
    keyed by both slug and (lower-cased) name so callers can dereference
    with whichever the source of truth had.
    """
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


async def _ensure_categories(names: list[str], coach_id: str) -> dict[str, dict]:
    """Ensure every name in ``names`` exists as a category. Returns
    ``{slug: doc, name_lower: doc}`` merged so callers can look up either."""
    out: dict[str, dict] = {}
    for raw in names:
        if not raw or not raw.strip():
            continue
        name = raw.strip()
        slug = _slugify(name)
        existing = await db.on_demand_categories.find_one({"slug": slug}, {"_id": 0})
        if existing:
            out[slug] = existing
            out[name.lower()] = existing
            continue
        doc = {
            "id": new_id(),
            "name": name,
            "slug": slug,
            "created_at": now_iso(),
            "created_by": coach_id,
        }
        await db.on_demand_categories.insert_one(doc)
        doc.pop("_id", None)
        out[slug] = doc
        out[name.lower()] = doc
    return out


async def _ensure_tags(names: list[str], coach_id: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for raw in names:
        if not raw or not raw.strip():
            continue
        name = raw.strip()
        slug = _slugify(name)
        existing = await db.on_demand_tags.find_one({"slug": slug}, {"_id": 0})
        if existing:
            out[slug] = existing
            out[name.lower()] = existing
            continue
        doc = {
            "id": new_id(),
            "name": name,
            "slug": slug,
            "created_at": now_iso(),
            "created_by": coach_id,
        }
        await db.on_demand_tags.insert_one(doc)
        doc.pop("_id", None)
        out[slug] = doc
        out[name.lower()] = doc
    return out


@api.post("/on-demand/coach/taxonomy/ensure")
async def od_coach_taxonomy_ensure(
    body: TaxonomyEnsureBody, coach: dict = Depends(require_role("coach")),
):
    """Idempotent upsert of categories + tags. Safe to call from an
    import script before it POSTs items so slugs are already resolvable.

    Response shape:
        {
          "categories": [{id, name, slug}, ...],   # union of existing+new
          "tags":       [{id, name, slug}, ...],
          "created":    {"categories": [slugs], "tags": [slugs]},
        }
    """
    # Snapshot which slugs existed before so we can report which ones we
    # actually created (useful for the import script's summary).
    incoming_cat_slugs = [_slugify(n) for n in body.categories if n and n.strip()]
    incoming_tag_slugs = [_slugify(n) for n in body.tags if n and n.strip()]
    pre_cats = {
        r["slug"]
        for r in await db.on_demand_categories.find(
            {"slug": {"$in": incoming_cat_slugs}}, {"_id": 0, "slug": 1},
        ).to_list(1000)
    }
    pre_tags = {
        r["slug"]
        for r in await db.on_demand_tags.find(
            {"slug": {"$in": incoming_tag_slugs}}, {"_id": 0, "slug": 1},
        ).to_list(1000)
    }
    cat_map = await _ensure_categories(body.categories, coach["id"])
    tag_map = await _ensure_tags(body.tags, coach["id"])
    cats_unique = {doc["id"]: doc for doc in cat_map.values()}.values()
    tags_unique = {doc["id"]: doc for doc in tag_map.values()}.values()
    return {
        "categories": list(cats_unique),
        "tags": list(tags_unique),
        "created": {
            "categories": [s for s in incoming_cat_slugs if s not in pre_cats],
            "tags":       [s for s in incoming_tag_slugs if s not in pre_tags],
        },
    }


class BulkItem(BaseModel):
    """One workout row for the bulk-import endpoint.

    Only ``title`` + ``workout_json`` are strictly required — everything
    else is optional and the endpoint fills defaults defensively.
    """
    title: str = Field(..., min_length=1, max_length=140)
    description: Optional[str] = Field(default="", max_length=4000)
    category_slug: Optional[str] = None
    tag_slugs: list[str] = Field(default_factory=list)
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=60 * 60 * 6)
    workout_json: dict[str, Any]
    thumbnail_filename: Optional[str] = None
    published: bool = False
    external_ref: Optional[str] = None
    equipment: list[str] = Field(default_factory=list)


class BulkItemsBody(BaseModel):
    items: list[BulkItem]
    default_published: bool = False    # global default (per-item value wins)
    enqueue_media: bool = True         # Iter200 · resolve exercises + queue media on import


def _extract_exercise_names_from_envelope(env: dict) -> dict[str, list[str]]:
    """Walk a `WorkoutEnvelopeItem`-shaped `workout_json` and return
    ``{"warmup": [names], "main": [names], "cooldown": [names]}``.

    Group blocks (superset / circuit / EMOM / AMRAP / etc.) are flattened
    so every `items[*].ref.name` is surfaced individually. Single main
    exercises pass through as-is. Empty / missing refs are silently
    skipped.
    """
    def _name_of(row: dict) -> Optional[str]:
        r = (row or {}).get("ref") or {}
        n = (r.get("name") or "").strip()
        return n or None

    def _flat_names(rows: list) -> list[str]:
        out: list[str] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if row.get("kind") == "group":
                for member in row.get("items") or []:
                    n = _name_of(member)
                    if n:
                        out.append(n)
            else:
                n = _name_of(row)
                if n:
                    out.append(n)
        return out

    return {
        "warmup":   _flat_names(env.get("warmup") or []),
        "main":     _flat_names(env.get("exercises") or []),
        "cooldown": _flat_names(env.get("cooldown") or []),
    }


async def _enqueue_media_for_ondemand_item(
    item_id: str,
    workout_json: dict,
    coach: dict,
) -> dict:
    """Iter200 · Resolve every exercise NAME inside a freshly-inserted
    on-demand item to an `exercises_v2` id (creating draft library rows
    for anything missing), then run the standard media-queue scan so
    exercises lacking image/video are queued for coach review.

    Wrapped in try/except at every step — a media-queue failure NEVER
    fails the import (matches the contract in `feature_media_queue.py`).

    Returns a small telemetry dict for the bulk-import report:
        {"resolved": N, "drafts_created": M, "queued_missing_media": K}
    """
    telemetry = {"resolved": 0, "drafts_created": 0, "queued_missing_media": 0}
    if not isinstance(workout_json, dict):
        return telemetry
    try:
        from feature_media_queue import (
            resolve_or_draft_exercise,
            scan_media_queue_for_sections,
        )
    except Exception:
        logger.exception("on_demand.bulk: cannot import feature_media_queue")
        return telemetry

    names_by_section = _extract_exercise_names_from_envelope(workout_json)
    # Cache name→id so duplicate names inside the same workout only hit
    # the resolver once (also keeps draft counters honest).
    name_to_id: dict[str, Optional[str]] = {}
    # We need to know which resolves resulted in a NEWLY-created draft
    # so the telemetry counter is meaningful — the resolver itself is
    # idempotent so a repeat call just returns the existing id.
    pre_existing_ids: set[str] = set()

    resolved_sections: dict[str, list[dict]] = {"warmup": [], "main": [], "cooldown": []}
    for section, names in names_by_section.items():
        for name in names:
            if name in name_to_id:
                xid = name_to_id[name]
            else:
                # Pre-check whether the library row exists so we can
                # count "drafts_created" accurately.
                try:
                    row = await db.exercises_v2.find_one(
                        {"exercise_name": {"$regex": f"^{name}$", "$options": "i"}},
                        {"_id": 0, "id": 1},
                    )
                    existed = bool(row)
                    if row:
                        pre_existing_ids.add(row["id"])
                except Exception:
                    existed = False
                try:
                    xid = await resolve_or_draft_exercise(
                        name,
                        user=coach,
                        reason=f"on_demand_bulk_import:{item_id}",
                        workout_id=None,  # on-demand items don't live in db.workouts yet
                    )
                except Exception:
                    logger.exception(
                        "on_demand.bulk: resolve_or_draft_exercise failed for %s",
                        name,
                    )
                    xid = None
                name_to_id[name] = xid
                if xid and not existed:
                    telemetry["drafts_created"] += 1
            if xid:
                telemetry["resolved"] += 1
                resolved_sections[section].append({"exercise_id": xid, "name": name})

    # Now run the media-queue scan against every resolved id — this is
    # what actually files "please generate image/video for this row"
    # requests for library rows that are still bare.
    try:
        queued = await scan_media_queue_for_sections(
            coach,
            resolved_sections,
            workout_id=None,
            reason=f"on_demand_bulk_import:{item_id}",
        )
        telemetry["queued_missing_media"] = len(queued or [])
    except Exception:
        logger.exception("on_demand.bulk: scan_media_queue_for_sections failed for %s", item_id)

    return telemetry


@api.post("/on-demand/coach/items/bulk")
async def od_coach_bulk_create(
    body: BulkItemsBody, coach: dict = Depends(require_role("coach")),
):
    """Bulk create on-demand workout items.

    Behaviour:
      * Every item is validated up-front. If ANY item fails structural
        validation we still process the rest — invalid rows land in
        ``errors[]`` with an index + reason.
      * Category / tag slugs are resolved to IDs via the existing
        taxonomy collections. Missing slugs → the row lands in
        ``errors[]`` (call `/taxonomy/ensure` first to auto-create).
      * ``external_ref`` deduplicates: if a doc with the same ref already
        exists the row lands in ``skipped[]`` (never overwrites; use the
        PATCH endpoint if you want to overwrite).
      * All items land as DRAFTS (``published=false``) unless the row
        itself sets ``published=true`` OR ``default_published=true`` is
        passed. This matches the "review before publish" workflow.
    """
    if not body.items:
        return {"created": [], "skipped": [], "errors": []}

    # Preload taxonomy so we don't hit the DB per row.
    cats = await db.on_demand_categories.find({}, {"_id": 0}).to_list(1000)
    tags = await db.on_demand_tags.find({}, {"_id": 0}).to_list(1000)
    cat_by_slug = {c["slug"]: c["id"] for c in cats}
    tag_by_slug = {t["slug"]: t["id"] for t in tags}

    # Preload existing external_refs for dedupe.
    incoming_refs = [it.external_ref for it in body.items if it.external_ref]
    existing_refs: set[str] = set()
    if incoming_refs:
        rows = await db.on_demand_items.find(
            {"external_ref": {"$in": incoming_refs}}, {"_id": 0, "external_ref": 1},
        ).to_list(1000)
        existing_refs = {r["external_ref"] for r in rows if r.get("external_ref")}

    created: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for idx, item in enumerate(body.items):
        # (1) External_ref dedupe — skip cleanly, not an error.
        if item.external_ref and item.external_ref in existing_refs:
            skipped.append({"index": idx, "external_ref": item.external_ref, "reason": "duplicate_external_ref"})
            continue

        # (2) Category / tag resolution.
        cat_id: Optional[str] = None
        if item.category_slug:
            slug = _slugify(item.category_slug)
            cat_id = cat_by_slug.get(slug)
            if not cat_id:
                errors.append({"index": idx, "title": item.title, "reason": f"unknown_category_slug: {slug}"})
                continue
        tag_ids: list[str] = []
        missing_tag: Optional[str] = None
        for ts in item.tag_slugs:
            slug = _slugify(ts)
            tid = tag_by_slug.get(slug)
            if not tid:
                missing_tag = slug
                break
            tag_ids.append(tid)
        if missing_tag:
            errors.append({"index": idx, "title": item.title, "reason": f"unknown_tag_slug: {missing_tag}"})
            continue

        # (3) Workout JSON sanity — must be a dict-shaped envelope.
        if not isinstance(item.workout_json, dict) or not item.workout_json:
            errors.append({"index": idx, "title": item.title, "reason": "workout_json_must_be_non_empty_dict"})
            continue

        # (4) Build the doc + insert.
        item_id = new_id()
        # per-item published flag wins; else the batch default.
        published_final = bool(item.published) or bool(body.default_published)
        doc = {
            "id": item_id,
            "title": item.title.strip(),
            "description": (item.description or "").strip(),
            "content_type": "workout",
            "category_id": cat_id,
            "tag_ids": list(dict.fromkeys(tag_ids)),
            "duration_seconds": item.duration_seconds,
            "thumbnail_storage_key": None,
            "thumbnail_mime": None,
            "thumbnail_ext": None,
            "thumbnail_filename": item.thumbnail_filename or None,
            "media_storage_key": None,
            "media_mime": None,
            "media_ext": None,
            "media_size_bytes": None,
            "workout_json": item.workout_json,
            "published": published_final,
            "external_ref": item.external_ref or None,
            "equipment": list(dict.fromkeys(item.equipment or [])),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "created_by": coach["id"],
        }
        try:
            await db.on_demand_items.insert_one(doc)
        except Exception as e:
            errors.append({"index": idx, "title": item.title, "reason": f"insert_failed: {e}"})
            continue

        # Remember this ref so a same-batch duplicate is skipped too.
        if item.external_ref:
            existing_refs.add(item.external_ref)

        # Iter200 · Push the workout's exercises into the media queue so
        # library drafts get created + missing media is queued for coach
        # review BEFORE any member starts the workout. Wrapped tight — a
        # media-queue failure never fails the import.
        media_telemetry = {"resolved": 0, "drafts_created": 0, "queued_missing_media": 0}
        if body.enqueue_media:
            try:
                media_telemetry = await _enqueue_media_for_ondemand_item(
                    item_id, item.workout_json, coach,
                )
            except Exception:
                logger.exception(
                    "on_demand.bulk: media enqueue failed for %s (non-fatal)", item_id,
                )

        created.append({
            "index": idx,
            "id": item_id,
            "title": doc["title"],
            "external_ref": doc["external_ref"],
            "published": doc["published"],
            "category_id": doc["category_id"],
            "thumbnail_filename": doc["thumbnail_filename"],
            "media_queue": media_telemetry,
        })

    logger.info(
        "on_demand.bulk_import complete: created=%d skipped=%d errors=%d",
        len(created), len(skipped), len(errors),
    )
    # Iter200 · aggregate media-queue telemetry across all created rows.
    mq_totals = {
        "resolved":              sum((c.get("media_queue") or {}).get("resolved", 0) for c in created),
        "drafts_created":        sum((c.get("media_queue") or {}).get("drafts_created", 0) for c in created),
        "queued_missing_media":  sum((c.get("media_queue") or {}).get("queued_missing_media", 0) for c in created),
    }
    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "summary": {
            "total_in": len(body.items),
            "created":  len(created),
            "skipped":  len(skipped),
            "errors":   len(errors),
            "media_queue": mq_totals,
        },
    }


# ---------------------------------------------------------------------------
# Iter193 · Stage 2 additions — featured pin + workout hydration
# ---------------------------------------------------------------------------

_FEATURED_SINGLETON_ID = "singleton"


class FeaturedBody(BaseModel):
    item_id: Optional[str] = None  # `null` clears the pin


async def _load_featured_doc() -> Optional[dict]:
    return await db.on_demand_featured.find_one({"id": _FEATURED_SINGLETON_ID}, {"_id": 0})


@api.get("/on-demand/featured")
async def od_get_featured(user: dict = Depends(current_user)):
    """Return the currently-featured On Demand item (or `{item: null}`).

    Non-coaches only see the featured item when it is published; if the
    coach has pinned an item and then unpublished it, clients see nothing
    until it's re-published or another item is pinned. Coaches always see
    the pin so they can manage it from the coach screen.
    """
    doc = await _load_featured_doc()
    item_id = (doc or {}).get("item_id")
    if not item_id:
        return {"item": None}
    item = await db.on_demand_items.find_one({"id": item_id}, {"_id": 0})
    if not item:
        return {"item": None}
    if not item.get("published") and user.get("role") != "coach":
        return {"item": None}
    # Strip the heavy workout_json — the Today card only needs light metadata.
    item.pop("workout_json", None)
    return {"item": item, "featured_at": (doc or {}).get("updated_at")}


@api.put("/on-demand/coach/featured")
async def od_set_featured(body: FeaturedBody, coach: dict = Depends(require_role("coach"))):
    """Coach pins (or clears) the featured On Demand item.

    Sending `{item_id: null}` clears the pin. Sending an id verifies the
    item exists and stamps the pin. Only one item can be featured at a
    time — this is a singleton doc keyed by `id="singleton"`.
    """
    if body.item_id:
        exists = await db.on_demand_items.count_documents({"id": body.item_id})
        if not exists:
            raise HTTPException(404, "item_not_found")
    await db.on_demand_featured.update_one(
        {"id": _FEATURED_SINGLETON_ID},
        {"$set": {
            "id": _FEATURED_SINGLETON_ID,
            "item_id": body.item_id or None,
            "updated_at": now_iso(),
            "updated_by": coach["id"],
        }},
        upsert=True,
    )
    return {"ok": True, "item_id": body.item_id or None}


# ---------------------------------------------------------------------------
# Workout hydration — client tap on a workout card creates a real workout doc
# in `db.workouts` so Guided Flow, timers, alternatives and completion
# tracking all "just work" without any extra plumbing.
# ---------------------------------------------------------------------------

def _flatten_flat_item(item: dict) -> dict:
    """Envelope FlatItem → guided-flow warmup/cooldown row.

    Guided Flow reads each drill as an object with a top-level `name`,
    `duration_sec` or `reps`, `rest_sec`, `notes`. Our envelope shape
    nests the exercise under `ref: {name}` — flatten it here.
    """
    ref = item.get("ref") or {}
    out: dict[str, Any] = {"name": ref.get("name") or "Drill"}
    for k in ("sets", "reps", "duration_sec", "rest_sec", "load", "tempo", "rpe", "notes"):
        if item.get(k) is not None:
            out[k] = item[k]
    if ref.get("exercise_id"):
        out["exercise_id"] = ref["exercise_id"]
    return out


def _flatten_main_block(block: dict) -> list[dict]:
    """Envelope MainExerciseBlock → 1..N guided-flow exercise rows.

    Single exercises produce one row. Group blocks are expanded to a
    sequence of rows (one per item, `rounds` × repeated) so the current
    Guided Flow can play them in order. Phase 4 (A1/A2 rotation UI) will
    later swap this expansion for a real group-aware renderer — but for
    Stage 2 we prioritise "playable everywhere" over "rendered as a
    superset". Every row carries a `group_hint` so the future renderer
    can regroup by that key without touching the DB.
    """
    kind = block.get("kind") or "single"
    if kind == "single":
        ref = block.get("ref") or {}
        row: dict[str, Any] = {
            "name": ref.get("name") or "Exercise",
        }
        for k in (
            "sets", "reps", "duration_sec", "rest_sec", "load",
            "tempo", "rpe", "notes", "equipment",
            "alternative_exercise_id", "alternative_name",
        ):
            if block.get(k) is not None:
                row[k] = block[k]
        if ref.get("exercise_id"):
            row["exercise_id"] = ref["exercise_id"]
        return [row]

    # kind == "group"
    group_type = block.get("group_type") or "group"
    group_label = block.get("group_label") or group_type.upper()
    rounds = int(block.get("rounds") or 1)
    rest_between_items = block.get("rest_between_items_sec")
    rest_between_rounds = block.get("rest_between_rounds_sec")
    items = block.get("items") or []
    rows: list[dict[str, Any]] = []
    for r in range(max(1, rounds)):
        for j, gi in enumerate(items):
            ref = gi.get("ref") or {}
            row: dict[str, Any] = {
                "name": ref.get("name") or "Exercise",
                "group_hint": group_label,
                "group_type": group_type,
                "group_round": r + 1,
                "group_index": j,
            }
            for k in ("reps", "duration_sec", "rest_sec", "load", "tempo", "notes"):
                if gi.get(k) is not None:
                    row[k] = gi[k]
            # If the group carries an item-level rest, prefer it; otherwise
            # inherit the group's between-items rest.
            if row.get("rest_sec") is None and rest_between_items is not None and j < len(items) - 1:
                row["rest_sec"] = rest_between_items
            if row.get("rest_sec") is None and rest_between_rounds is not None and j == len(items) - 1 and r < rounds - 1:
                row["rest_sec"] = rest_between_rounds
            if ref.get("exercise_id"):
                row["exercise_id"] = ref["exercise_id"]
            rows.append(row)
    return rows


def _hydrate_on_demand_workout(item: dict, user_id: str) -> dict:
    """Build a `db.workouts` doc from an On Demand workout item.

    Accepts the workout JSON in either shape:
      • Envelope: `{ workouts: [w0, ...] }` — takes the first workout.
      • Single object: `{ title, warmup, exercises, cooldown, ... }`.

    The output doc mirrors what the programme importer writes (`source`,
    `approved`, `manual_lock`, timestamps) so the rest of the app treats
    it identically to any other coach-authored workout.
    """
    wjson = item.get("workout_json") or {}
    if isinstance(wjson.get("workouts"), list) and wjson["workouts"]:
        wk = wjson["workouts"][0]
    else:
        wk = wjson

    warmup = [_flatten_flat_item(x) for x in (wk.get("warmup") or []) if isinstance(x, dict)]
    exercises: list[dict[str, Any]] = []
    for blk in (wk.get("exercises") or []):
        if isinstance(blk, dict):
            exercises.extend(_flatten_main_block(blk))
    cooldown = [_flatten_flat_item(x) for x in (wk.get("cooldown") or []) if isinstance(x, dict)]

    duration_min = wk.get("duration_min")
    if duration_min is None:
        d_sec = item.get("duration_seconds")
        if isinstance(d_sec, (int, float)) and d_sec > 0:
            duration_min = int(round(d_sec / 60))

    now_str = now_iso()
    today = now_str[:10]
    return {
        "id": new_id(),
        "user_id": user_id,
        "date": today,
        "title": item.get("title") or wk.get("title") or "On Demand workout",
        "focus": wk.get("workout_type") or "other",
        "workout_type": wk.get("workout_type") or "other",
        "location": wk.get("location"),
        "equipment_context": wk.get("equipment_context"),
        "duration_min": duration_min,
        "rpe": wk.get("rpe"),
        "coach_notes": wk.get("coach_notes") or item.get("description"),
        "warmup": warmup,
        "exercises": exercises,
        "cooldown": cooldown,
        "alternatives": {},
        # Same "manual + approved" markers the programme importer stamps
        # so the Today / Calendar / Guided Flow surfaces treat this as a
        # first-class workout — no extra approval step required.
        "source": "on_demand",
        "on_demand_item_id": item["id"],
        "manual_lock": True,
        "approved": True,
        "approved_at": now_str,
        "approved_source": "on_demand_start",
        "created_at": now_str,
        "updated_at": now_str,
        "original_date": today,
    }


@api.post("/on-demand/items/{item_id}/start-workout")
async def od_start_workout(item_id: str, user: dict = Depends(current_user)):
    """Client taps a workout card → hydrate a real workout doc & return its id.

    The client then navigates to the standard `/workout/{id}/guided`
    route which reads the workout via the existing endpoints. This keeps
    Guided Flow, timers, alternatives and completion tracking on the
    same code path used by manual builder + programme-import workouts.
    """
    item = await db.on_demand_items.find_one({"id": item_id}, {"_id": 0})
    if not item:
        raise HTTPException(404, "item_not_found")
    if item.get("content_type") != "workout":
        raise HTTPException(400, "item_is_not_a_workout")
    if not item.get("published") and user.get("role") != "coach":
        raise HTTPException(404, "item_not_found")
    if not item.get("workout_json"):
        raise HTTPException(400, "item_missing_workout_json")

    doc = _hydrate_on_demand_workout(item, user["id"])
    await db.workouts.insert_one(doc)
    return {"workout_id": doc["id"], "date": doc["date"]}

