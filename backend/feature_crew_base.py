"""
Iter 129 — Crew Base (Community MVP, Light).

Crew Base is the CrewFit COMMUNITY feed.

Design notes (kept intentionally small):
  * COACH creates posts (text / image / video). Publish now or Schedule.
  * CLIENTS view published posts, comment, and give one aviation-themed
    reaction ("wings" — airplane icon). Clients cannot create standalone
    posts in this MVP.
  * PRIVACY is first-class. Clients default to INITIALS identity — server
    NEVER returns a hidden client's full name / email / profile photo on
    the client-facing endpoints. Coach viewers additionally receive a
    `coach_only` block for moderation.
  * NOTIFICATIONS are gated by an independent `crew_base` toggle inside
    the existing notification_settings map. Turning it OFF must NOT
    affect Messages / Flight Support / Training notifications.
  * MESSAGES remains completely separate (private 1:1 coach ↔ client).

Reuses:
  * FastAPI + Motor DB access from server.py.
  * base64 media pattern (nutrition photos, progress photos, custom
    videos already do this).
  * feature_notifications.enqueue_notification for push + in-app row.
"""
from __future__ import annotations
import asyncio
import base64
import binascii
import datetime as _dt
import logging
from typing import Any, Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from server import (
    api, db, new_id, now_iso, current_user, require_role,
)

logger = logging.getLogger("crewfit.crew_base")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
POST_MEDIA_TYPES = {"none", "image", "video"}
POST_STATUSES = {"draft", "scheduled", "published", "deleted"}
IDENTITY_MODES = {"initials", "full_name"}
REACTION_KIND = "wings"          # single aviation-themed reaction
MAX_TEXT_LEN = 4000
MAX_COMMENT_LEN = 1500
MAX_MEDIA_BYTES = 10 * 1024 * 1024   # 10 MB — matches existing custom-video slot


# ---------------------------------------------------------------------------
# Identity & privacy resolver
# ---------------------------------------------------------------------------
def _initials(name: Optional[str]) -> str:
    """Return uppercase initials from a display name.

    "Pietro Sangermano" → "PS"
    "Louis Hall"        → "LH"
    "Cher"              → "C"
    "" / None           → "??"
    """
    if not name:
        return "??"
    parts = [p for p in str(name).strip().split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def _client_subtype(u: dict) -> Optional[str]:
    """Very light professional subtype for the community — pilot / cabin crew.

    Per spec §6 we may expose this ONLY if the profile intentionally
    stores it as community-visible. We check a small allow-list of
    canonical fields — never invent one."""
    prof = u.get("profile") or {}
    v = (prof.get("professional_role")
         or prof.get("role_label")
         or prof.get("crew_role")
         or "").strip().lower()
    if not v:
        return None
    if "pilot" in v:
        return "Pilot"
    if "cabin" in v or "crew" in v or "flight attendant" in v:
        return "Cabin Crew"
    return None


def _identity_mode(u: dict) -> str:
    prof = u.get("profile") or {}
    m = str(prof.get("crew_base_identity_mode") or "").lower().strip()
    return m if m in IDENTITY_MODES else "initials"   # Default: initials (§7)


def _public_identity(u: dict, *, viewer_is_coach: bool) -> dict:
    """Resolve a user's PUBLIC crew-base identity for feed rendering.

    Return shape:
      {
        "author_id": "<user_id>",
        "public_name": "PS" | "Pietro Sangermano" | "Louis Hall" | "Former Member",
        "avatar_kind": "initials" | "photo" | "coach",
        "avatar_initials": "PS",                 # always present
        "avatar_photo_url": "..."                # only when avatar_kind == "photo"
        "role": "client" | "coach",
        "subtype": "Pilot" | "Cabin Crew" | None,
      }

    For COACH viewers we additionally include a `coach_only` block for
    moderation. Client viewers NEVER receive that block.
    """
    if not u:
        return {
            "author_id": "",
            "public_name": "Former Member",
            "avatar_kind": "initials",
            "avatar_initials": "??",
            "role": "client",
            "subtype": None,
        }

    role = u.get("role") or "client"
    if role == "coach":
        # Coach always shows real branding — no anonymisation.
        name = u.get("display_name") or u.get("name") or "Coach"
        photo = (u.get("profile") or {}).get("avatar_url") or u.get("avatar_url")
        return {
            "author_id": u.get("id"),
            "public_name": name,
            "avatar_kind": "photo" if photo else "coach",
            "avatar_initials": _initials(name),
            "avatar_photo_url": photo,
            "role": "coach",
            "subtype": "Head Coach" if (u.get("is_primary_coach") or u.get("is_admin")) else "Coach",
        }

    mode = _identity_mode(u)
    name = u.get("display_name") or u.get("name") or ""
    initials = _initials(name)
    subtype = _client_subtype(u)

    if mode == "full_name":
        photo = (u.get("profile") or {}).get("avatar_url") or u.get("avatar_url")
        out = {
            "author_id": u.get("id"),
            "public_name": name or initials,
            "avatar_kind": "photo" if photo else "initials",
            "avatar_initials": initials,
            "role": "client",
            "subtype": subtype,
        }
        if photo:
            out["avatar_photo_url"] = photo
    else:
        # Initials mode — profile photo is HIDDEN from other clients (§42/§53).
        out = {
            "author_id": u.get("id"),
            "public_name": initials,
            "avatar_kind": "initials",
            "avatar_initials": initials,
            "role": "client",
            "subtype": subtype,
        }

    if viewer_is_coach:
        out["coach_only"] = {
            "real_name": name or "(unnamed client)",
            "email": u.get("email"),
            "identity_mode": mode,
        }
    return out


async def _resolve_identities(user_ids: list[str], *, viewer_is_coach: bool) -> dict[str, dict]:
    if not user_ids:
        return {}
    unique_ids = list({uid for uid in user_ids if uid})
    docs = await db.users.find(
        {"id": {"$in": unique_ids}},
        {"_id": 0, "password_hash": 0},
    ).to_list(len(unique_ids) + 5)
    by_id = {d["id"]: d for d in docs}
    return {
        uid: _public_identity(by_id.get(uid), viewer_is_coach=viewer_is_coach)
        for uid in unique_ids
    }


# ---------------------------------------------------------------------------
# Test-client filter (reuses convention from feature_v2_coach_home)
# ---------------------------------------------------------------------------
def _is_test_account(u: dict) -> bool:
    tags = set(u.get("tags") or [])
    if {"sandbox", "test", "reviewer", "qa"} & tags:
        return True
    email = (u.get("email") or "").lower()
    if any(k in email for k in ("reviewer@", "sandbox@", "+test@", "qa@")):
        return True
    if (u.get("account_type") or "").lower() in ("sandbox", "test", "reviewer"):
        return True
    return False


async def _active_operational_client_ids() -> list[str]:
    users = await db.users.find(
        {"role": "client"},
        {"_id": 0, "id": 1, "email": 1, "tags": 1, "account_type": 1, "status": 1, "archived_at": 1},
    ).to_list(5000)
    out: list[str] = []
    for u in users:
        if _is_test_account(u):
            continue
        if u.get("archived_at"):
            continue
        if (u.get("status") or "").lower() in ("archived", "deleted", "suspended"):
            continue
        out.append(u["id"])
    return out


# ---------------------------------------------------------------------------
# Notification preference helpers
# ---------------------------------------------------------------------------
def _crew_base_notifs_enabled(u: dict) -> bool:
    """Feature-specific toggle. Default TRUE (§13). Independent of every
    other CrewFit notification category."""
    ns = u.get("notification_settings") or {}
    v = ns.get("crew_base")
    if v is None:
        return True
    return bool(v)


# ---------------------------------------------------------------------------
# Media handling — base64 in-DB, matches existing app pattern
# ---------------------------------------------------------------------------
def _decode_media(b64: str, mime: str) -> tuple[bytes, str]:
    if not b64:
        raise HTTPException(400, "media_base64 required")
    # Strip data-URI prefix if present.
    if b64.startswith("data:"):
        try:
            b64 = b64.split(",", 1)[1]
        except Exception:
            raise HTTPException(400, "invalid base64")
    try:
        data = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "invalid base64")
    if len(data) > MAX_MEDIA_BYTES:
        raise HTTPException(413, f"media too large (max {MAX_MEDIA_BYTES // (1024*1024)} MB)")
    if not mime or "/" not in mime:
        raise HTTPException(400, "invalid mime")
    return data, mime


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------
class PostBody(BaseModel):
    text: str = Field("", max_length=MAX_TEXT_LEN)
    media_type: str = Field("none")
    media_base64: Optional[str] = None
    media_mime: Optional[str] = None
    status: str = Field("published")           # draft | scheduled | published
    scheduled_at: Optional[str] = None         # ISO datetime, required if status == scheduled


class PostPatch(BaseModel):
    text: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[str] = None
    media_type: Optional[str] = None
    media_base64: Optional[str] = None
    media_mime: Optional[str] = None


class CommentBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_COMMENT_LEN)


class SettingsPatch(BaseModel):
    crew_base_identity_mode: Optional[str] = None      # "initials" | "full_name"
    crew_base_notifications_enabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Post-shaper (privacy-aware)
# ---------------------------------------------------------------------------
def _post_public_shape(
    p: dict,
    author_id_map: dict[str, dict],
    reactions_summary: dict,
    comments_preview: list[dict],
    viewer_id: str,
    viewer_is_coach: bool,
) -> dict:
    author = author_id_map.get(p.get("author_id")) or _public_identity(None, viewer_is_coach=viewer_is_coach)
    out = {
        "id": p["id"],
        "author": author,
        "text": p.get("text") or "",
        "media_type": p.get("media_type") or "none",
        "media_url": p.get("media_url"),        # data URI or absolute URL
        "status": p.get("status"),
        "scheduled_at": p.get("scheduled_at"),
        "published_at": p.get("published_at"),
        "created_at": p.get("created_at"),
        "reactions": {
            "kind": REACTION_KIND,
            "count": reactions_summary.get("count", 0),
            "viewer_reacted": reactions_summary.get("viewer_reacted", False),
        },
        "comments_preview": comments_preview,
        "comments_count": reactions_summary.get("comments_count", 0),
    }
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

# ---- Coach: create post ---------------------------------------------------
@api.post("/crew-base/posts")
async def cb_create_post(body: PostBody, user: dict = Depends(require_role("coach"))):
    status = body.status if body.status in POST_STATUSES else "published"
    if status == "deleted":
        raise HTTPException(400, "cannot create as deleted")
    if body.media_type not in POST_MEDIA_TYPES:
        raise HTTPException(400, "invalid media_type")
    if not (body.text or "").strip() and body.media_type == "none":
        raise HTTPException(400, "post must have text or media")

    media_url = None
    if body.media_type in ("image", "video"):
        if not body.media_base64 or not body.media_mime:
            raise HTTPException(400, "media_base64 + media_mime required")
        data, mime = _decode_media(body.media_base64, body.media_mime)
        b64 = base64.b64encode(data).decode("ascii")
        media_url = f"data:{mime};base64,{b64}"

    scheduled_at = None
    published_at = None
    if status == "scheduled":
        if not body.scheduled_at:
            raise HTTPException(400, "scheduled_at required")
        try:
            _dt.datetime.fromisoformat(body.scheduled_at.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(400, "scheduled_at must be ISO datetime")
        scheduled_at = body.scheduled_at
    elif status == "published":
        published_at = now_iso()

    doc = {
        "id": new_id(),
        "author_id": user["id"],
        "text": (body.text or "").strip(),
        "media_type": body.media_type,
        "media_url": media_url,
        "status": status,
        "scheduled_at": scheduled_at,
        "published_at": published_at,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.crew_base_posts.insert_one(doc)
    doc.pop("_id", None)

    # Fan-out on publish
    if status == "published":
        await _dispatch_new_post_notifications(doc)

    return {"ok": True, "post": doc}


# ---- Coach: edit / delete / publish -----------------------------------------
@api.patch("/crew-base/posts/{post_id}")
async def cb_patch_post(post_id: str, body: PostPatch, user: dict = Depends(require_role("coach"))):
    p = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "post not found")
    if p.get("status") == "deleted":
        raise HTTPException(410, "post deleted")

    patch: dict[str, Any] = {"updated_at": now_iso()}
    if body.text is not None:
        patch["text"] = str(body.text)[:MAX_TEXT_LEN]
    if body.status is not None:
        if body.status not in POST_STATUSES:
            raise HTTPException(400, "invalid status")
        patch["status"] = body.status
        if body.status == "published" and not p.get("published_at"):
            patch["published_at"] = now_iso()
        if body.status == "scheduled":
            if not body.scheduled_at and not p.get("scheduled_at"):
                raise HTTPException(400, "scheduled_at required")
            if body.scheduled_at:
                patch["scheduled_at"] = body.scheduled_at
    elif body.scheduled_at is not None:
        patch["scheduled_at"] = body.scheduled_at
    if body.media_type is not None:
        if body.media_type not in POST_MEDIA_TYPES:
            raise HTTPException(400, "invalid media_type")
        patch["media_type"] = body.media_type
        if body.media_type == "none":
            patch["media_url"] = None
    if body.media_base64 and body.media_type in ("image", "video"):
        data, mime = _decode_media(body.media_base64, body.media_mime or "image/jpeg")
        b64 = base64.b64encode(data).decode("ascii")
        patch["media_url"] = f"data:{mime};base64,{b64}"

    await db.crew_base_posts.update_one({"id": post_id}, {"$set": patch})
    fresh = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0})

    # If the transition into "published" happened via edit, fan-out.
    became_published = (body.status == "published"
                        and (p.get("status") != "published"))
    if became_published:
        await _dispatch_new_post_notifications(fresh)
    return {"ok": True, "post": fresh}


@api.delete("/crew-base/posts/{post_id}")
async def cb_delete_post(post_id: str, user: dict = Depends(require_role("coach"))):
    p = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0, "id": 1})
    if not p:
        raise HTTPException(404, "post not found")
    await db.crew_base_posts.update_one(
        {"id": post_id},
        {"$set": {"status": "deleted", "deleted_at": now_iso(), "updated_at": now_iso()}},
    )
    return {"ok": True}


@api.post("/crew-base/posts/{post_id}/publish")
async def cb_publish_now(post_id: str, user: dict = Depends(require_role("coach"))):
    p = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "post not found")
    if p.get("status") == "published":
        return {"ok": True, "post": p}
    if p.get("status") == "deleted":
        raise HTTPException(410, "post deleted")
    await db.crew_base_posts.update_one(
        {"id": post_id},
        {"$set": {
            "status": "published",
            "published_at": now_iso(),
            "scheduled_at": None,
            "updated_at": now_iso(),
        }},
    )
    fresh = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0})
    await _dispatch_new_post_notifications(fresh)
    return {"ok": True, "post": fresh}


# ---- Coach: scheduled / drafts lists --------------------------------------
@api.get("/crew-base/coach/scheduled")
async def cb_coach_scheduled(user: dict = Depends(require_role("coach"))):
    rows = await db.crew_base_posts.find(
        {"status": "scheduled"}, {"_id": 0},
    ).sort("scheduled_at", 1).to_list(200)
    ident = await _resolve_identities([r["author_id"] for r in rows], viewer_is_coach=True)
    return {"posts": [{**r, "author": ident.get(r["author_id"])} for r in rows]}


@api.get("/crew-base/coach/drafts")
async def cb_coach_drafts(user: dict = Depends(require_role("coach"))):
    rows = await db.crew_base_posts.find(
        {"status": "draft"}, {"_id": 0},
    ).sort("updated_at", -1).to_list(200)
    ident = await _resolve_identities([r["author_id"] for r in rows], viewer_is_coach=True)
    return {"posts": [{**r, "author": ident.get(r["author_id"])} for r in rows]}


# ---- Feed (client + coach) -------------------------------------------------
async def _summarise_post(post_id: str, viewer_id: str) -> dict:
    react_count = await db.crew_base_reactions.count_documents({"post_id": post_id})
    viewer_reacted = bool(await db.crew_base_reactions.find_one(
        {"post_id": post_id, "user_id": viewer_id}, {"_id": 1}
    ))
    comments_count = await db.crew_base_comments.count_documents(
        {"post_id": post_id, "deleted_at": {"$in": [None, ""]}}
    )
    return {
        "count": react_count,
        "viewer_reacted": viewer_reacted,
        "comments_count": comments_count,
    }


@api.get("/crew-base/feed")
async def cb_feed(user: dict = Depends(current_user), limit: int = 40):
    limit = max(1, min(int(limit or 40), 80))
    viewer_is_coach = (user.get("role") == "coach")
    q = {"status": "published"}
    rows = await db.crew_base_posts.find(q, {"_id": 0}).sort("published_at", -1).to_list(limit)

    # Resolve author identities (coach + client authors both possible)
    author_ids = [r["author_id"] for r in rows]
    # Also include commenters for the preview
    post_ids = [r["id"] for r in rows]
    all_comments = await db.crew_base_comments.find(
        {"post_id": {"$in": post_ids}, "deleted_at": {"$in": [None, ""]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(len(post_ids) * 5 + 10)
    commenter_ids = [c["author_id"] for c in all_comments]
    ident = await _resolve_identities(author_ids + commenter_ids, viewer_is_coach=viewer_is_coach)

    # Preview: newest 2 comments per post, in chronological order
    preview_by_post: dict[str, list[dict]] = {}
    for c in all_comments:
        preview_by_post.setdefault(c["post_id"], []).append(c)
    for pid, cs in preview_by_post.items():
        cs.sort(key=lambda x: x.get("created_at") or "")
        preview_by_post[pid] = cs[-2:]

    out = []
    for r in rows:
        summary = await _summarise_post(r["id"], user["id"])
        preview = [{
            "id": c["id"],
            "text": c["text"],
            "author": ident.get(c["author_id"]),
            "created_at": c["created_at"],
        } for c in preview_by_post.get(r["id"], [])]
        out.append(_post_public_shape(r, ident, summary, preview, user["id"], viewer_is_coach))
    return {"posts": out, "count": len(out)}


# ---- Reactions -------------------------------------------------------------
@api.post("/crew-base/posts/{post_id}/react")
async def cb_toggle_reaction(post_id: str, user: dict = Depends(current_user)):
    p = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0, "status": 1})
    if not p or p.get("status") != "published":
        raise HTTPException(404, "post not available")
    existing = await db.crew_base_reactions.find_one(
        {"post_id": post_id, "user_id": user["id"]}, {"_id": 0, "id": 1}
    )
    if existing:
        await db.crew_base_reactions.delete_one({"id": existing["id"]})
        viewer_reacted = False
    else:
        await db.crew_base_reactions.insert_one({
            "id": new_id(),
            "post_id": post_id,
            "user_id": user["id"],
            "kind": REACTION_KIND,
            "created_at": now_iso(),
        })
        viewer_reacted = True
    count = await db.crew_base_reactions.count_documents({"post_id": post_id})
    return {"ok": True, "count": count, "viewer_reacted": viewer_reacted, "kind": REACTION_KIND}


# ---- Comments --------------------------------------------------------------
@api.get("/crew-base/posts/{post_id}/comments")
async def cb_list_comments(post_id: str, user: dict = Depends(current_user)):
    p = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0, "status": 1})
    if not p or p.get("status") != "published":
        raise HTTPException(404, "post not available")
    rows = await db.crew_base_comments.find(
        {"post_id": post_id, "deleted_at": {"$in": [None, ""]}},
        {"_id": 0},
    ).sort("created_at", 1).to_list(500)
    viewer_is_coach = (user.get("role") == "coach")
    ident = await _resolve_identities([r["author_id"] for r in rows], viewer_is_coach=viewer_is_coach)
    return {
        "comments": [{
            "id": c["id"],
            "text": c["text"],
            "author": ident.get(c["author_id"]),
            "created_at": c["created_at"],
        } for c in rows],
    }


@api.post("/crew-base/posts/{post_id}/comments")
async def cb_create_comment(post_id: str, body: CommentBody, user: dict = Depends(current_user)):
    p = await db.crew_base_posts.find_one({"id": post_id}, {"_id": 0, "status": 1, "author_id": 1})
    if not p or p.get("status") != "published":
        raise HTTPException(404, "post not available")
    doc = {
        "id": new_id(),
        "post_id": post_id,
        "author_id": user["id"],
        "text": body.text.strip()[:MAX_COMMENT_LEN],
        "created_at": now_iso(),
        "deleted_at": None,
    }
    await db.crew_base_comments.insert_one(doc)
    doc.pop("_id", None)

    # Notify post author when someone comments (relevant-reply case §15).
    if p.get("author_id") and p["author_id"] != user["id"]:
        try:
            from feature_notifications import enqueue_notification
            # §16 — respect the author's crew_base toggle before firing.
            target = await db.users.find_one({"id": p["author_id"]}, {"_id": 0, "notification_settings": 1, "role": 1})
            if _crew_base_notifs_enabled(target or {}):
                viewer_is_coach = (user.get("role") == "coach")
                display = _public_identity(user, viewer_is_coach=True)["public_name"]
                # For the coach post-author we always name the commenter internally.
                await enqueue_notification(
                    p["author_id"], "crew_base_reply",
                    "New reply on your post",
                    f"{display}: {doc['text'][:120]}",
                    action_url=f"/(coach)/crew-base?post={post_id}"
                    if viewer_is_coach is False   # commenter is client, author probably coach
                    else f"/(client)/base?post={post_id}",
                    related_id=post_id,
                    dedupe_key=f"cb_reply::{doc['id']}",
                )
        except Exception:
            logger.exception("crew_base reply notification failed")

    ident = await _resolve_identities([user["id"]], viewer_is_coach=(user.get("role") == "coach"))
    return {
        "ok": True,
        "comment": {
            "id": doc["id"], "text": doc["text"],
            "author": ident.get(user["id"]),
            "created_at": doc["created_at"],
        },
    }


@api.delete("/crew-base/comments/{comment_id}")
async def cb_delete_comment(comment_id: str, user: dict = Depends(require_role("coach"))):
    c = await db.crew_base_comments.find_one({"id": comment_id}, {"_id": 0, "id": 1})
    if not c:
        raise HTTPException(404, "comment not found")
    await db.crew_base_comments.update_one(
        {"id": comment_id},
        {"$set": {"deleted_at": now_iso(), "deleted_by": user["id"]}},
    )
    return {"ok": True}


# ---- Preferences -----------------------------------------------------------
@api.get("/crew-base/settings")
async def cb_get_settings(user: dict = Depends(current_user)):
    return {
        "crew_base_identity_mode": _identity_mode(user),
        "crew_base_notifications_enabled": _crew_base_notifs_enabled(user),
        "public_preview": _public_identity(user, viewer_is_coach=False),
    }


@api.patch("/crew-base/settings")
async def cb_patch_settings(body: SettingsPatch, user: dict = Depends(current_user)):
    updates: dict[str, Any] = {}
    if body.crew_base_identity_mode is not None:
        m = body.crew_base_identity_mode.lower().strip()
        if m not in IDENTITY_MODES:
            raise HTTPException(400, "invalid crew_base_identity_mode")
        updates["profile.crew_base_identity_mode"] = m
    if body.crew_base_notifications_enabled is not None:
        updates["notification_settings.crew_base"] = bool(body.crew_base_notifications_enabled)
    if updates:
        updates["updated_at"] = now_iso()
        await db.users.update_one({"id": user["id"]}, {"$set": updates})
    fresh = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {
        "ok": True,
        "crew_base_identity_mode": _identity_mode(fresh or {}),
        "crew_base_notifications_enabled": _crew_base_notifs_enabled(fresh or {}),
        "public_preview": _public_identity(fresh or {}, viewer_is_coach=False),
    }


# ---- Sidebar unread badge (light-touch) -----------------------------------
@api.get("/crew-base/unread-count")
async def cb_unread_count(user: dict = Depends(current_user)):
    seen = await db.crew_base_seen.find_one({"user_id": user["id"]}, {"_id": 0, "last_seen_at": 1})
    since = (seen or {}).get("last_seen_at") or "1970-01-01T00:00:00Z"
    count = await db.crew_base_posts.count_documents({
        "status": "published",
        "published_at": {"$gt": since},
        "author_id": {"$ne": user["id"]},
    })
    return {"count": count, "since": since}


@api.post("/crew-base/mark-seen")
async def cb_mark_seen(user: dict = Depends(current_user)):
    ts = now_iso()
    await db.crew_base_seen.update_one(
        {"user_id": user["id"]},
        {"$set": {"user_id": user["id"], "last_seen_at": ts}},
        upsert=True,
    )
    return {"ok": True, "last_seen_at": ts}


# ---------------------------------------------------------------------------
# Notification dispatch
# ---------------------------------------------------------------------------
async def _dispatch_new_post_notifications(post: dict) -> None:
    """Enqueue a `crew_base_new_post` notification for every active client
    whose Crew Base notifications toggle is ON.

    Independent from Messages / Flight Support / Training toggles (§16, §37,
    §38). We pre-check the crew_base preference per-user here so that OFF
    fully suppresses BOTH the push AND the in-app notification row (§16).
    """
    try:
        from feature_notifications import enqueue_notification
    except Exception:
        logger.exception("could not import enqueue_notification")
        return
    author = await db.users.find_one({"id": post.get("author_id")}, {"_id": 0, "name": 1, "display_name": 1, "role": 1})
    who = (author or {}).get("display_name") or (author or {}).get("name") or "Louis"
    body_text = (post.get("text") or "").strip()
    body_line = (body_text[:100] + "…") if len(body_text) > 100 else (body_text or "Tap to view.")

    for uid in await _active_operational_client_ids():
        if uid == post.get("author_id"):
            continue
        # Per §16 — OFF means no push AND no in-app row. Pre-check here.
        target = await db.users.find_one({"id": uid}, {"_id": 0, "notification_settings": 1})
        if not _crew_base_notifs_enabled(target or {}):
            continue
        try:
            await enqueue_notification(
                uid, "crew_base_new_post",
                "Crew Base",
                f"New community post from {who}. {body_line}",
                action_url="/(client)/base",
                related_id=post.get("id"),
                dedupe_key=f"cb_post::{post.get('id')}",
            )
        except Exception:
            logger.exception("crew_base fan-out failed for user %s", uid)


# ---------------------------------------------------------------------------
# Scheduler loop — publishes scheduled posts when their time arrives
# ---------------------------------------------------------------------------
async def _tick_crew_base_scheduler() -> None:
    now_dt = _dt.datetime.now(_dt.timezone.utc)
    now_iso_s = now_dt.isoformat()
    # Motor's find w/ $lte on ISO strings works because our timestamps are
    # UTC ISO-8601 with consistent formatting.
    rows = await db.crew_base_posts.find(
        {"status": "scheduled", "scheduled_at": {"$lte": now_iso_s}},
        {"_id": 0},
    ).to_list(200)
    for p in rows:
        try:
            await db.crew_base_posts.update_one(
                {"id": p["id"], "status": "scheduled"},
                {"$set": {
                    "status": "published",
                    "published_at": now_iso(),
                    "updated_at": now_iso(),
                }},
            )
            fresh = await db.crew_base_posts.find_one({"id": p["id"]}, {"_id": 0})
            if fresh:
                await _dispatch_new_post_notifications(fresh)
        except Exception:
            logger.exception("crew_base scheduler failed to publish post %s", p.get("id"))


async def _crew_base_scheduler_loop() -> None:
    """Background loop: every 60s, publish scheduled posts whose time has
    arrived. Fault-tolerant — always sleeps and retries on error."""
    while True:
        try:
            await _tick_crew_base_scheduler()
        except Exception:
            logger.exception("crew_base scheduler tick failed")
        await asyncio.sleep(60)


def start_crew_base_scheduler() -> None:
    """Called from server.py startup — kicks off the async publisher."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_crew_base_scheduler_loop())
        logger.info("crew_base scheduler started")
    except RuntimeError:
        # Called before loop exists — safe to skip; startup event will do it.
        logger.warning("crew_base scheduler: no running loop yet — deferred")


# Kick off on import (server.py already imports this module at startup).
try:
    _loop = asyncio.get_event_loop()
    if _loop.is_running():
        _loop.create_task(_crew_base_scheduler_loop())
    else:
        # Fallback — server startup event will pick it up if this doesn't fire.
        pass
except Exception:
    pass
