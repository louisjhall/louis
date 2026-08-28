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
import re
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
    media: Optional[ItemMedia] = None                 # video / audio bytes
    workout_json: Optional[dict[str, Any]] = None     # workout content
    published: bool = False


class ItemPatchBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=140)
    description: Optional[str] = Field(default=None, max_length=4000)
    category_id: Optional[str] = None
    tag_ids: Optional[list[str]] = None
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=60 * 60 * 6)
    thumbnail: Optional[ItemMedia] = None
    media: Optional[ItemMedia] = None
    workout_json: Optional[dict[str, Any]] = None
    published: Optional[bool] = None


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
        "media_storage_key":     (media_meta or {}).get("storage_key"),
        "media_mime":            (media_meta or {}).get("mime"),
        "media_ext":             (media_meta or {}).get("ext"),
        "media_size_bytes":      (media_meta or {}).get("size_bytes"),
        "workout_json": body.workout_json if body.content_type == "workout" else None,
        "published": bool(body.published),
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
