"""
Iter 94t (Phase 3) — Dynamic goal-based progress + charts.

Backs the client Progress screen and the coach client-detail Progress view.
Data is stored across four collections:

  body_metrics      — weight / waist / hips / chest (client-controlled)
  progress_photos   — private; disk-stored under /uploads/progress_photos/
  running_metrics   — auto-populated when a run session is completed
  strength_metrics  — auto-populated when a strength set is logged
  progress_summaries — weekly rollup written by /progress/dashboard reads

The `GET /progress/dashboard` endpoint returns a goal-adaptive payload — a
fat-loss client sees weight+waist+photos, a running client sees long-run
duration + weekly runs, a strength client sees key lifts. General fitness
clients see consistency + habits + recovery.

Photos are stored on disk (not base64 in DB) so we stay App Store safe and
export/delete cleanly for GDPR. A short-lived signed token guards each
image URL.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import logging
import os
import secrets
from typing import Any, Optional

from fastapi import Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from server import (
    api, current_user, require_role, db, new_id, now_iso,
)

logger = logging.getLogger("crewfit.progress")

# ---------------------------------------------------------------------------
# Disk storage for progress photos.
# ---------------------------------------------------------------------------

PHOTO_DIR = os.environ.get("PROGRESS_PHOTO_DIR", "/app/backend/uploads/progress_photos")
os.makedirs(PHOTO_DIR, exist_ok=True)
PHOTO_SECRET = os.environ.get("PROGRESS_PHOTO_SECRET") or secrets.token_hex(32)
MAX_PHOTO_BYTES = 6 * 1024 * 1024   # 6 MB per file — plenty for a phone JPEG.

ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _sign_photo(photo_id: str, user_id: str, exp_epoch: int) -> str:
    msg = f"{photo_id}.{user_id}.{exp_epoch}".encode()
    return hmac.new(PHOTO_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:24]


def _verify_photo_token(photo_id: str, user_id: str, exp_epoch: int, token: str) -> bool:
    if exp_epoch < int(_dt.datetime.utcnow().timestamp()):
        return False
    expected = _sign_photo(photo_id, user_id, exp_epoch)
    return hmac.compare_digest(expected, token)


def _photo_url(photo_id: str, user_id: str) -> dict:
    exp = int((_dt.datetime.utcnow() + _dt.timedelta(hours=6)).timestamp())
    tok = _sign_photo(photo_id, user_id, exp)
    return {
        "id": photo_id,
        "url": f"/api/progress/photo/{photo_id}?u={user_id}&e={exp}&t={tok}",
        "expires_at_epoch": exp,
    }


# ---------------------------------------------------------------------------
# Goal detection.
# ---------------------------------------------------------------------------

FAT_LOSS_KEYS = {"fat_loss", "weight_loss", "body_composition", "recomposition", "recomp"}
RUNNING_KEYS = {"running", "run", "marathon", "half_marathon", "5k", "10k", "endurance"}
STRENGTH_KEYS = {"strength", "muscle", "hypertrophy", "power", "athletic"}
HEALTH_KEYS = {"health", "general_fitness", "wellness", "energy", "recovery", "return_to_training"}


def _detect_goal_class(profile: dict) -> str:
    keys = [
        str(profile.get("main_goal_key") or "").lower(),
        str(profile.get("primary_goal") or "").lower(),
    ]
    for g in (profile.get("secondary_goals") or []):
        keys.append(str(g).lower())
    hay = " ".join(keys)
    if any(k in hay for k in FAT_LOSS_KEYS):
        return "fat_loss"
    if any(k in hay for k in RUNNING_KEYS):
        return "running"
    if any(k in hay for k in STRENGTH_KEYS):
        return "strength"
    return "health"


# ---------------------------------------------------------------------------
# Body metrics
# ---------------------------------------------------------------------------

class BodyMetricBody(BaseModel):
    date: Optional[str] = None           # YYYY-MM-DD, default = today
    weight_kg: Optional[float] = Field(None, ge=20, le=400)
    waist_cm: Optional[float] = Field(None, ge=30, le=300)
    hips_cm:  Optional[float] = Field(None, ge=30, le=300)
    chest_cm: Optional[float] = Field(None, ge=30, le=300)
    notes: Optional[str] = None


@api.post("/progress/body")
async def log_body_metric(body: BodyMetricBody, user: dict = Depends(current_user)):
    if all(v is None for v in (body.weight_kg, body.waist_cm, body.hips_cm, body.chest_cm)):
        raise HTTPException(400, "At least one measurement is required.")
    d = body.date or _dt.date.today().isoformat()
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "date": d,
        "weight_kg": body.weight_kg,
        "waist_cm": body.waist_cm,
        "hips_cm": body.hips_cm,
        "chest_cm": body.chest_cm,
        "notes": body.notes,
        "created_at": now_iso(),
    }
    await db.body_metrics.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "metric": doc}


@api.get("/progress/body")
async def list_body_metrics(user: dict = Depends(current_user), days: int = Query(180, ge=7, le=730)):
    since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    rows = await db.body_metrics.find(
        {"user_id": user["id"], "date": {"$gte": since}}, {"_id": 0},
    ).sort("date", 1).to_list(500)
    return {"metrics": rows or []}


# ---------------------------------------------------------------------------
# Running metrics
# ---------------------------------------------------------------------------

class RunningMetricBody(BaseModel):
    date: Optional[str] = None
    duration_min: float = Field(..., ge=1, le=1000)
    distance_km: Optional[float] = Field(None, ge=0.1, le=200)
    rpe: Optional[float] = Field(None, ge=1, le=10)
    session_type: Optional[str] = "easy_run"   # long_run, tempo, intervals, easy_run
    workout_id: Optional[str] = None
    completed: bool = True
    notes: Optional[str] = None


@api.post("/progress/running")
async def log_running_metric(body: RunningMetricBody, user: dict = Depends(current_user)):
    d = body.date or _dt.date.today().isoformat()
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "date": d,
        "duration_min": body.duration_min,
        "distance_km": body.distance_km,
        "rpe": body.rpe,
        "session_type": body.session_type,
        "workout_id": body.workout_id,
        "completed": body.completed,
        "notes": body.notes,
        "created_at": now_iso(),
    }
    await db.running_metrics.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "metric": doc}


@api.get("/progress/running")
async def list_running_metrics(user: dict = Depends(current_user), weeks: int = Query(12, ge=1, le=52)):
    since = (_dt.date.today() - _dt.timedelta(days=weeks * 7)).isoformat()
    rows = await db.running_metrics.find(
        {"user_id": user["id"], "date": {"$gte": since}}, {"_id": 0},
    ).sort("date", 1).to_list(500)
    return {"metrics": rows or []}


# ---------------------------------------------------------------------------
# Strength metrics
# ---------------------------------------------------------------------------

class StrengthMetricBody(BaseModel):
    exercise_name: str = Field(..., min_length=1, max_length=120)
    date: Optional[str] = None
    sets: int = Field(..., ge=1, le=20)
    reps: int = Field(..., ge=1, le=100)
    load_kg: float = Field(..., ge=0, le=1000)
    rpe: Optional[float] = Field(None, ge=1, le=10)
    workout_id: Optional[str] = None
    notes: Optional[str] = None


@api.post("/progress/strength")
async def log_strength_metric(body: StrengthMetricBody, user: dict = Depends(current_user)):
    d = body.date or _dt.date.today().isoformat()
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        "date": d,
        "exercise_name": body.exercise_name.strip(),
        "exercise_key": body.exercise_name.strip().lower(),
        "sets": body.sets,
        "reps": body.reps,
        "load_kg": body.load_kg,
        "estimated_1rm_kg": round(body.load_kg * (1 + body.reps / 30.0), 1),
        "rpe": body.rpe,
        "workout_id": body.workout_id,
        "notes": body.notes,
        "created_at": now_iso(),
    }
    await db.strength_metrics.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "metric": doc}


@api.get("/progress/strength")
async def list_strength_metrics(user: dict = Depends(current_user), weeks: int = Query(12, ge=1, le=52)):
    since = (_dt.date.today() - _dt.timedelta(days=weeks * 7)).isoformat()
    rows = await db.strength_metrics.find(
        {"user_id": user["id"], "date": {"$gte": since}}, {"_id": 0},
    ).sort("date", 1).to_list(1000)
    return {"metrics": rows or []}


# ---------------------------------------------------------------------------
# Progress photos (private, disk-stored)
# ---------------------------------------------------------------------------

class PhotoUploadBody(BaseModel):
    angle: str = "front"           # "front" | "side" | "back"
    date: Optional[str] = None
    photo_b64: str
    mime: str = "image/jpeg"


@api.post("/progress/photo/base64")
async def upload_photo_base64(body: PhotoUploadBody, user: dict = Depends(current_user)):
    """Upload path optimised for the mobile client (base64 payload).

    We accept up to ~6 MB then persist to disk so nothing bloats Mongo.
    """
    if body.mime not in ALLOWED_MIME:
        raise HTTPException(400, f"Unsupported mime {body.mime}")
    ext = ALLOWED_MIME[body.mime]
    try:
        blob = base64.b64decode(body.photo_b64, validate=True)
    except Exception:
        raise HTTPException(400, "photo_b64 is not valid base64.")
    if len(blob) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo too large (max 6 MB).")
    if body.angle not in {"front", "side", "back"}:
        raise HTTPException(400, "angle must be front/side/back.")

    pid = new_id()
    fname = f"{pid}{ext}"
    with open(os.path.join(PHOTO_DIR, fname), "wb") as f:
        f.write(blob)

    doc = {
        "id": pid,
        "user_id": user["id"],
        "date": body.date or _dt.date.today().isoformat(),
        "angle": body.angle,
        "filename": fname,
        "mime": body.mime,
        "size_bytes": len(blob),
        "private": True,
        "created_at": now_iso(),
    }
    await db.progress_photos.insert_one(doc)
    doc.pop("_id", None)
    doc.update(_photo_url(pid, user["id"]))
    return {"ok": True, "photo": doc}


@api.get("/progress/photos")
async def list_photos(user: dict = Depends(current_user), months: int = Query(12, ge=1, le=60)):
    since = (_dt.date.today() - _dt.timedelta(days=months * 31)).isoformat()
    rows = await db.progress_photos.find(
        {"user_id": user["id"], "date": {"$gte": since}}, {"_id": 0},
    ).sort("date", -1).to_list(300)
    out = []
    for r in rows:
        r.update(_photo_url(r["id"], user["id"]))
        out.append(r)
    return {"photos": out}


@api.get("/progress/photo/{photo_id}")
async def get_photo(
    photo_id: str,
    u: str = Query(...),
    e: int = Query(...),
    t: str = Query(...),
):
    """Signed-URL image fetch. Token-only auth so <Image> tags work without headers."""
    if not _verify_photo_token(photo_id, u, e, t):
        raise HTTPException(403, "Invalid or expired photo token.")
    doc = await db.progress_photos.find_one({"id": photo_id, "user_id": u}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "photo not found")
    fpath = os.path.join(PHOTO_DIR, doc["filename"])
    if not os.path.exists(fpath):
        raise HTTPException(410, "photo missing from storage")
    with open(fpath, "rb") as f:
        blob = f.read()
    return Response(content=blob, media_type=doc.get("mime") or "image/jpeg")


@api.delete("/progress/photo/{photo_id}")
async def delete_photo(photo_id: str, user: dict = Depends(current_user)):
    doc = await db.progress_photos.find_one({"id": photo_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "photo not found")
    if user["role"] == "client" and doc.get("user_id") != user["id"]:
        raise HTTPException(403, "forbidden")
    try:
        os.remove(os.path.join(PHOTO_DIR, doc["filename"]))
    except FileNotFoundError:
        pass
    await db.progress_photos.delete_one({"id": photo_id})
    return {"ok": True, "deleted": photo_id}


# ---------------------------------------------------------------------------
# Goal-adaptive dashboard
# ---------------------------------------------------------------------------

async def _adherence_last_weeks(user_id: str, weeks: int) -> dict:
    since = (_dt.date.today() - _dt.timedelta(days=weeks * 7)).isoformat()
    total = await db.workouts.count_documents({
        "user_id": user_id, "date": {"$gte": since},
    })
    done = await db.workouts.count_documents({
        "user_id": user_id, "date": {"$gte": since}, "completed": True,
    })
    missed = await db.workouts.count_documents({
        "user_id": user_id,
        "date": {"$gte": since, "$lt": _dt.date.today().isoformat()},
        "completed": {"$ne": True},
        "skipped": {"$ne": True},
    })
    return {
        "weeks": weeks,
        "workouts_planned": total,
        "workouts_completed": done,
        "workouts_missed": missed,
        "adherence_pct": round((done / total) * 100) if total else None,
    }


async def _nutrition_averages(user_id: str, days: int) -> dict:
    since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    rows = await db.nutrition_logs.find(
        {"user_id": user_id, "date_local": {"$gte": since}}, {"_id": 0},
    ).to_list(2000) if hasattr(db, "nutrition_logs") else []
    if not rows:
        return {"days": days, "days_logged": 0, "avg_calories": 0, "avg_protein_g": 0}
    by_date: dict[str, dict[str, float]] = {}
    for r in rows:
        d = r.get("date_local")
        by_date.setdefault(d, {"cal": 0.0, "pro": 0.0})
        by_date[d]["cal"] += float(r.get("calories") or 0)
        by_date[d]["pro"] += float(r.get("protein_g") or 0)
    n = len(by_date)
    return {
        "days": days, "days_logged": n,
        "avg_calories": round(sum(v["cal"] for v in by_date.values()) / n),
        "avg_protein_g": round(sum(v["pro"] for v in by_date.values()) / n),
    }


async def _habit_completion_last_days(user_id: str, days: int) -> dict:
    since = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    if not hasattr(db, "habit_events"):
        return {"days": days, "completed": 0, "planned": 0, "pct": None}
    completed = await db.habit_events.count_documents({
        "user_id": user_id, "date": {"$gte": since}, "status": "done",
    })
    planned = await db.habit_events.count_documents({
        "user_id": user_id, "date": {"$gte": since},
    })
    return {
        "days": days, "completed": completed, "planned": planned,
        "pct": round((completed / planned) * 100) if planned else None,
    }


def _series_from_body(rows: list[dict], key: str) -> list[dict]:
    return [
        {"date": r["date"], "value": r[key]}
        for r in rows if r.get(key) is not None
    ]


def _running_summary(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "long_run_min": 0, "total_min": 0, "series": []}
    longest = max((r.get("duration_min") or 0) for r in rows)
    total = sum((r.get("duration_min") or 0) for r in rows)
    long_series = [
        {"date": r["date"], "value": r["duration_min"]}
        for r in rows if str(r.get("session_type") or "").lower() == "long_run"
    ]
    return {
        "count": len(rows),
        "long_run_min": round(longest),
        "total_min": round(total),
        "series": long_series,
    }


def _strength_summary(rows: list[dict]) -> dict:
    if not rows:
        return {"key_lifts": [], "sessions": 0}
    by_ex: dict[str, list[dict]] = {}
    for r in rows:
        k = r.get("exercise_key") or ""
        by_ex.setdefault(k, []).append(r)
    key_lifts = []
    for k, arr in by_ex.items():
        arr.sort(key=lambda x: x.get("date") or "")
        best = max(arr, key=lambda x: x.get("estimated_1rm_kg") or 0)
        first = arr[0]
        latest = arr[-1]
        key_lifts.append({
            "exercise": arr[0].get("exercise_name"),
            "sessions": len(arr),
            "first_1rm": first.get("estimated_1rm_kg"),
            "latest_1rm": latest.get("estimated_1rm_kg"),
            "best_1rm": best.get("estimated_1rm_kg"),
            "series": [
                {"date": r["date"], "value": r.get("estimated_1rm_kg") or 0}
                for r in arr
            ],
        })
    key_lifts.sort(key=lambda x: -(x.get("sessions") or 0))
    return {"key_lifts": key_lifts[:5], "sessions": len(rows)}


async def _dashboard_for(user: dict) -> dict:
    profile = user.get("profile") or {}
    goal_class = _detect_goal_class(profile)

    adherence = await _adherence_last_weeks(user["id"], 4)
    nutrition = await _nutrition_averages(user["id"], 14)
    habits = await _habit_completion_last_days(user["id"], 7)

    body_rows = (await db.body_metrics.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("date", 1).to_list(500)) or []
    running_rows = (await db.running_metrics.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("date", 1).to_list(500)) or []
    strength_rows = (await db.strength_metrics.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("date", 1).to_list(2000)) or []
    photo_rows = (await db.progress_photos.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("date", -1).to_list(60)) or []
    photos = [{**r, **_photo_url(r["id"], user["id"])} for r in photo_rows][:12]

    weight_series = _series_from_body(body_rows, "weight_kg")
    waist_series  = _series_from_body(body_rows, "waist_cm")
    weight_change = (
        (weight_series[-1]["value"] - weight_series[0]["value"])
        if len(weight_series) >= 2 else None
    )
    waist_change = (
        (waist_series[-1]["value"] - waist_series[0]["value"])
        if len(waist_series) >= 2 else None
    )
    running = _running_summary(running_rows)
    strength = _strength_summary(strength_rows)

    return {
        "goal_class": goal_class,
        "goal_label": profile.get("primary_goal") or profile.get("main_goal_key") or goal_class,
        "phase": profile.get("phase") or None,
        "adherence": adherence,
        "nutrition_last_14d": nutrition,
        "habits_last_7d": habits,
        "body": {
            "latest": body_rows[-1] if body_rows else None,
            "starting": body_rows[0] if body_rows else None,
            "weight_change_kg": round(weight_change, 1) if weight_change is not None else None,
            "waist_change_cm": round(waist_change, 1) if waist_change is not None else None,
            "series_weight": weight_series,
            "series_waist": waist_series,
        },
        "running": running,
        "strength": strength,
        "photos": photos,
    }


@api.get("/progress/dashboard")
async def progress_dashboard(user: dict = Depends(current_user)):
    return await _dashboard_for(user)


@api.get("/admin/client/{uid}/progress-dashboard")
async def admin_progress_dashboard(uid: str, user: dict = Depends(require_role("coach"))):
    client = await db.users.find_one({"id": uid}, {"_id": 0})
    if not client:
        raise HTTPException(404, "client not found")
    payload = await _dashboard_for(client)
    payload["client"] = {"id": client["id"], "name": client.get("name"), "email": client.get("email")}
    return payload


# Retain the File/Form/UploadFile imports so lint sees them used (multipart
# support is planned but base64 covers today's mobile flow).
_ = (File, Form, UploadFile)
