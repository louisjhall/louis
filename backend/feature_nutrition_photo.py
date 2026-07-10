"""feature_nutrition_photo — AI Photo Meal Scanner (Phase 3).

Uses Claude Sonnet 4.5 vision (via emergentintegrations LlmChat) to estimate the
contents and macros of a plated meal photo. The prompt returns strict JSON:

    {
      "items": [{"name": "...", "portion": "..."}],
      "calories": int,
      "protein_g": float,
      "carbs_g": float,
      "fats_g": float,
      "confidence": "low"|"medium"|"high",
      "atlas_tip": "short coaching sentence",
      "warnings": []
    }

Photos are stored on disk under /app/backend/uploads/nutrition/{user_id}/{img_id}.jpg
(same pattern as feature_brand_images) and served through
GET /api/nutrition/photo/{scan_id}/image with token auth.

Endpoints:
    POST /api/nutrition/photo/analyse        — body: base64 image + optional context
    GET  /api/nutrition/photo/{scan_id}      — read a saved scan
    GET  /api/nutrition/photo/{scan_id}/image — file
    POST /api/nutrition/photo/{scan_id}/save-log — persist to nutrition_logs (after edits)
    POST /api/nutrition/photo/{scan_id}/patch — update scan estimates (from client edits)
"""
from __future__ import annotations

import os
import base64
import json
import re
import asyncio
import datetime as _dt
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server import (
    api, db, current_user, new_id, now_iso, logger, EMERGENT_LLM_KEY,
)
import storage as _storage

UPLOADS_ROOT = Path(os.environ.get("NUTR_UPLOAD_DIR", "/app/backend/uploads/nutrition"))
UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)

CLAUDE_VISION_MODEL = os.environ.get("NUTR_VISION_MODEL", "claude-sonnet-4-5-20250929")
MAX_IMAGE_BYTES = 8 * 1024 * 1024   # 8 MB per photo
ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AnalyseIn(BaseModel):
    image_base64: str = Field(..., description="Base64-encoded JPEG/PNG/WEBP; may contain data-URI prefix.")
    mime: Optional[str] = "image/jpeg"
    mode: str = "meal"                # meal | hotel_buffet
    meal_type: Optional[str] = None
    goal: Optional[str] = None        # if omitted, pulled from user's active target
    roster_context: Optional[str] = None
    notes: Optional[str] = None


class PatchScanIn(BaseModel):
    items: Optional[list[dict]] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fats_g: Optional[float] = None
    atlas_tip: Optional[str] = None
    notes: Optional[str] = None


class SaveLogIn(BaseModel):
    meal_type: str = "snack"
    roster_context: Optional[str] = None
    location_context: Optional[str] = None
    save_as_favourite: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_image(image_b64: str, mime: str) -> tuple[bytes, str, str]:
    """Return (bytes, mime, ext). Strips data-URI prefix if present."""
    b64 = image_b64.strip()
    if b64.startswith("data:"):
        # data:image/png;base64,....
        m = re.match(r"data:(?P<mime>[^;]+);base64,(?P<data>.+)$", b64, re.DOTALL)
        if not m:
            raise HTTPException(400, "invalid data URI")
        mime = m.group("mime")
        b64 = m.group("data")
    mime = (mime or "image/jpeg").lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(415, f"unsupported mime {mime}")
    try:
        data = base64.b64decode(b64, validate=False)
    except Exception:
        raise HTTPException(400, "bad base64")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "image too large (>8MB)")
    ext = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}[mime]
    return data, mime, ext


def _system_prompt(mode: str, goal: Optional[str]) -> str:
    base = (
        "You are Atlas, CrewFit's aviation-nutrition coach. Analyse the meal photo "
        "and return STRICT JSON only (no markdown, no prose). "
        "Never diagnose medical conditions. Never use words like 'diet', 'cheat', "
        "'failed', or 'bad food'. Estimates only — nutrition varies per portion."
    )
    if mode == "hotel_buffet":
        base += (
            " HOTEL-BUFFET MODE: describe every recognisable item on the plate. "
            "Then give one practical coaching call: is this a good recovery plate, "
            "protein-led enough, likely too high in fat/sauce, or well-balanced? "
            "Assume airline crew context."
        )
    if goal:
        base += f" Client goal: {goal}."
    return base


def _user_prompt(mode: str, meal_type: Optional[str], roster_ctx: Optional[str], notes: Optional[str]) -> str:
    ctx = []
    if meal_type: ctx.append(f"meal type: {meal_type}")
    if roster_ctx: ctx.append(f"roster context: {roster_ctx}")
    if notes: ctx.append(f"client note: {notes}")
    ctx_line = f"Context — {', '.join(ctx)}." if ctx else ""

    schema = """
Respond with STRICT JSON:
{
  "items": [{"name": "chicken breast", "portion": "~150g"}, ...],
  "calories": 620,
  "protein_g": 45,
  "carbs_g": 70,
  "fats_g": 18,
  "confidence": "medium",
  "atlas_tip": "Good protein choice — watch the sauce if fat-loss is the goal.",
  "warnings": []
}
Keep atlas_tip <= 32 words. Use the phrase 'Atlas has estimated' or similar hedging tone. Do not add fields.
""".strip()

    return f"{ctx_line}\n\n{schema}" if ctx_line else schema


async def _call_vision(image_b64_no_prefix: str, mime: str, system: str, user: str) -> dict:
    """Send to Claude Sonnet 4.5 vision and parse JSON."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"nutr-photo-{new_id()}",
        system_message=system,
    ).with_model("anthropic", CLAUDE_VISION_MODEL)

    resp = await chat.send_message(UserMessage(
        text=user,
        file_contents=[ImageContent(image_base64=image_b64_no_prefix)],
    ))
    raw = (resp or "").strip()
    return _parse_json(raw)


def _parse_json(text: str) -> dict:
    """Extract the JSON object from an LLM response, being lenient about fences."""
    if not text:
        raise HTTPException(502, "empty vision response")
    # Strip markdown fences
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    # Sometimes prose precedes/follows; grab the first JSON object.
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m:
        t = m.group(0)
    try:
        return json.loads(t)
    except Exception:
        logger.warning("bad JSON from vision: %s", text[:500])
        raise HTTPException(502, "vision returned invalid JSON")


def _normalise(payload: dict, mode: str) -> dict:
    """Coerce shape + apply guardrails on numeric values."""
    items = payload.get("items") or []
    if not isinstance(items, list): items = []
    items = [{"name": str(x.get("name") or "").strip(),
              "portion": str(x.get("portion") or "").strip()}
             for x in items if isinstance(x, dict) and x.get("name")]
    def num(v: Any) -> float:
        try: return float(v)
        except Exception: return 0.0
    calories = max(0, min(3000, int(round(num(payload.get("calories"))))))
    protein_g = max(0.0, min(200.0, round(num(payload.get("protein_g")), 1)))
    carbs_g = max(0.0, min(300.0, round(num(payload.get("carbs_g")), 1)))
    fats_g = max(0.0, min(200.0, round(num(payload.get("fats_g")), 1)))
    conf = str(payload.get("confidence") or "medium").lower()
    if conf not in ("low", "medium", "high"): conf = "medium"
    tip = str(payload.get("atlas_tip") or "").strip()
    if not tip:
        tip = "Atlas has estimated this meal. Please adjust anything that looks wrong."
    warnings = payload.get("warnings") or []
    if not isinstance(warnings, list): warnings = []
    warnings = [str(w).strip() for w in warnings if str(w).strip()]
    return {
        "items": items,
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fats_g": fats_g,
        "confidence": conf,
        "atlas_tip": tip,
        "warnings": warnings,
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api.post("/nutrition/photo/analyse")
async def photo_analyse(body: AnalyseIn, user: dict = Depends(current_user)):
    # Rate limit + telemetry gate. Raises HTTP 429 if the user is over cap.
    import ai_limits
    await ai_limits.check_quota(db, user, "photo_scan")

    data, mime, ext = _decode_image(body.image_base64, body.mime or "image/jpeg")

    # Resolve goal from user's active target if not supplied.
    goal = body.goal
    if not goal:
        try:
            tdoc = await db.nutrition_targets.find_one(
                {"user_id": user["id"], "active": True}, {"_id": 0, "goal": 1},
            )
            goal = (tdoc or {}).get("goal")
        except Exception:
            goal = None

    system = _system_prompt(body.mode, goal)
    user_prompt = _user_prompt(body.mode, body.meal_type, body.roster_context, body.notes)

    # Save the image to disk first so the client can display it via the URL
    # even if the vision call fails.
    scan_id = new_id()
    day = _dt.date.today().isoformat()
    # Write via storage abstraction — DiskDriver by default, R2 when configured.
    storage_key = f"nutrition/{user['id']}/{day}/{scan_id}.{ext}"
    await _storage.storage.write_bytes(storage_key, data, content_type=mime)
    # For back-compat with the existing FileResponse endpoint, also record the
    # equivalent on-disk path when disk driver is active. When R2 is active
    # the DiskDriver falls away and we serve via presigned URL.
    disk_path = None
    if not _storage.is_cloud():
        user_dir = UPLOADS_ROOT / user["id"] / day
        user_dir.mkdir(parents=True, exist_ok=True)
        disk_path = user_dir / f"{scan_id}.{ext}"
        disk_path.write_bytes(data)

    # Base64 for the LLM (strip any data-URI prefix that may have been present)
    image_b64 = base64.b64encode(data).decode("ascii")

    try:
        raw = await _call_vision(image_b64, mime, system, user_prompt)
        est = _normalise(raw, body.mode)
        # Log a successful photo scan for telemetry + quota accounting.
        try:
            await ai_limits.record_usage(
                db, user_id=user["id"], feature="photo_scan",
                model=CLAUDE_VISION_MODEL, provider="anthropic",
                tokens_in=ai_limits.estimate_tokens_from_text(system, user_prompt),
                tokens_out=ai_limits.estimate_tokens_from_text(json.dumps(raw)),
                images=1, success=True,
            )
        except Exception:
            pass
    except HTTPException:
        # Best-effort fallback so the client still sees something meaningful.
        try:
            await ai_limits.record_usage(
                db, user_id=user["id"], feature="photo_scan",
                model=CLAUDE_VISION_MODEL, provider="anthropic",
                images=1, success=False, error="vision_http_exception",
            )
        except Exception:
            pass
        est = {
            "items": [], "calories": 0, "protein_g": 0, "carbs_g": 0, "fats_g": 0,
            "confidence": "low", "atlas_tip": "Atlas couldn't estimate this meal — please log it manually.",
            "warnings": ["vision unavailable"], "mode": body.mode,
        }
    except Exception:
        logger.exception("vision unexpected error")
        try:
            await ai_limits.record_usage(
                db, user_id=user["id"], feature="photo_scan",
                model=CLAUDE_VISION_MODEL, provider="anthropic",
                images=1, success=False, error="vision_error",
            )
        except Exception:
            pass
        est = {
            "items": [], "calories": 0, "protein_g": 0, "carbs_g": 0, "fats_g": 0,
            "confidence": "low", "atlas_tip": "Atlas couldn't estimate this meal — please log it manually.",
            "warnings": ["vision error"], "mode": body.mode,
        }

    doc = {
        "id": scan_id,
        "user_id": user["id"],
        "created_at": now_iso(),
        "storage_key": storage_key,
        "storage_path": str(disk_path) if disk_path else None,
        "mime": mime,
        "size_bytes": len(data),
        "mode": body.mode,
        "meal_type": body.meal_type,
        "roster_context": body.roster_context,
        "goal": goal,
        "notes": body.notes,
        "estimate": est,
        "saved_log_id": None,
    }
    await db.nutrition_photo_scans.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("storage_path", None)   # never expose disk paths
    return {"scan": doc}


@api.get("/nutrition/photo/{scan_id}")
async def photo_get(scan_id: str, user: dict = Depends(current_user)):
    doc = await db.nutrition_photo_scans.find_one(
        {"id": scan_id, "user_id": user["id"]},
        {"_id": 0, "storage_path": 0},
    )
    if not doc:
        raise HTTPException(404, "scan not found")
    return {"scan": doc}


@api.get("/nutrition/photo/{scan_id}/image")
async def photo_image(scan_id: str, token: Optional[str] = None,
                      authorization: Optional[str] = Header(None)):
    """Serve the stored meal photo. Supports either Authorization: Bearer <token>
    OR ?token=... query-string (needed for <Image src=...> tags on RN-Web).
    """
    if authorization and authorization.startswith("Bearer "):
        actual = authorization.split(" ", 1)[1]
        from feature_profile import _user_from_token
        user = await _user_from_token(actual)
    elif token:
        from feature_profile import _user_from_token
        user = await _user_from_token(token)
    else:
        raise HTTPException(401, "missing token")
    doc = await db.nutrition_photo_scans.find_one({"id": scan_id, "user_id": user["id"]})
    if not doc:
        raise HTTPException(404, "not found")
    # Prefer storage_key (works for both disk + R2). Fall back to legacy disk path.
    key = doc.get("storage_key")
    mime = doc.get("mime") or "image/jpeg"
    if key and _storage.is_cloud():
        # Redirect to a short-lived signed URL — client `<Image>` follows the 302.
        from fastapi.responses import RedirectResponse
        url = await _storage.storage.public_url(key, ttl=600, signed=True)
        return RedirectResponse(url, status_code=302)
    path = doc.get("storage_path")
    if path and Path(path).exists():
        return FileResponse(path, media_type=mime)
    if key:
        # Disk driver via abstraction (post-migration path)
        data = await _storage.storage.read_bytes(key)
        if data:
            from fastapi.responses import Response
            return Response(content=data, media_type=mime)
    raise HTTPException(404, "image missing")


@api.post("/nutrition/photo/{scan_id}/patch")
async def photo_patch(scan_id: str, body: PatchScanIn, user: dict = Depends(current_user)):
    doc = await db.nutrition_photo_scans.find_one({"id": scan_id, "user_id": user["id"]})
    if not doc:
        raise HTTPException(404, "not found")
    est = dict(doc.get("estimate") or {})
    payload = body.model_dump()
    for k in ("items", "calories", "protein_g", "carbs_g", "fats_g", "atlas_tip"):
        v = payload.get(k)
        if v is not None:
            est[k] = v
    est = _normalise(est, est.get("mode") or "meal")
    updates: dict = {"estimate": est, "updated_at": now_iso()}
    if body.notes is not None:
        updates["notes"] = body.notes
    await db.nutrition_photo_scans.update_one({"id": scan_id}, {"$set": updates})
    doc = await db.nutrition_photo_scans.find_one(
        {"id": scan_id}, {"_id": 0, "storage_path": 0},
    )
    return {"scan": doc}


@api.post("/nutrition/photo/{scan_id}/save-log")
async def photo_save_log(scan_id: str, body: SaveLogIn, user: dict = Depends(current_user)):
    doc = await db.nutrition_photo_scans.find_one({"id": scan_id, "user_id": user["id"]})
    if not doc:
        raise HTTPException(404, "not found")
    if doc.get("saved_log_id"):
        # Already saved once — return existing log
        row = await db.nutrition_logs.find_one({"id": doc["saved_log_id"]}, {"_id": 0})
        return {"log": row, "already_saved": True}

    est = doc.get("estimate") or {}
    from feature_nutrition import _today_iso, MEAL_TYPES, ROSTER_CONTEXTS
    meal_type = body.meal_type if body.meal_type in MEAL_TYPES else "snack"
    roster = body.roster_context if body.roster_context in ROSTER_CONTEXTS else None
    # Human-readable food name from the top items
    items = est.get("items") or []
    if items:
        head = ", ".join(i["name"] for i in items[:3] if i.get("name"))
        food_name = head or "Scanned meal"
    else:
        food_name = "Scanned meal"

    now = now_iso()
    log_id = new_id()
    log_doc = {
        "id": log_id,
        "user_id": user["id"],
        "date_local": _today_iso(),
        "meal_type": meal_type,
        "food_name": food_name,
        "calories": int(est.get("calories") or 0),
        "protein_g": float(est.get("protein_g") or 0),
        "carbs_g": float(est.get("carbs_g") or 0),
        "fats_g": float(est.get("fats_g") or 0),
        "portion": None,
        "notes": doc.get("notes"),
        "source": "photo",
        "location_context": body.location_context,
        "roster_context": roster,
        "photo_scan_id": scan_id,
        "photo_url": f"/api/nutrition/photo/{scan_id}/image",
        "confidence_level": est.get("confidence"),
        "created_at": now, "updated_at": now,
    }
    await db.nutrition_logs.insert_one(log_doc)
    await db.nutrition_photo_scans.update_one(
        {"id": scan_id}, {"$set": {"saved_log_id": log_id, "saved_at": now}},
    )
    if body.save_as_favourite:
        await db.nutrition_favourites.insert_one({
            "id": new_id(), "user_id": user["id"],
            "name": food_name, "meal_type": meal_type,
            "calories": log_doc["calories"], "protein_g": log_doc["protein_g"],
            "carbs_g": log_doc["carbs_g"], "fats_g": log_doc["fats_g"],
            "created_at": now,
        })
    log_doc.pop("_id", None)
    return {"log": log_doc, "already_saved": False}
