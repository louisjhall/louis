"""feature_nutrition — CrewFit Nutrition Centre (V1 · Phase 1).

Practical, travel-aware nutrition coaching for airline crew.  Phase-1 scope:
    • Coach-editable targets per client (with safety guardrails)
    • Manual food logging + edit + delete + favourites
    • Simple daily hydration ticker (+250ml)
    • Today totals endpoint (calories, protein, carbs, fats, hydration)
    • 7-day nutrition history + weekly summary
    • Atlas short daily insight via Claude Sonnet 4.5 (Emergent LLM key)
    • Coach dashboard endpoints (list clients w/ nutrition summary + edit targets)

Deliberately NOT built in V1 (routes exist as placeholders in the frontend):
    • Barcode scanning + food-DB provider layer
    • AI photo meal scanner + hotel-buffet scanner
    • Roster/time-zone/location travel guidance & Atlas decision tools
    • Adaptive weekly Atlas insights + auto Coach-To-Do integration

Endpoints (all prefixed with /api):
    GET/POST /api/nutrition/targets                       — self read + upsert (client)
    GET      /api/nutrition/targets/mine                  — resolved active targets w/ defaults
    POST     /api/nutrition/logs                          — create manual log
    GET      /api/nutrition/logs?date=YYYY-MM-DD&days=N   — day or range
    PATCH    /api/nutrition/logs/{id}                     — edit
    DELETE   /api/nutrition/logs/{id}                     — remove
    GET      /api/nutrition/today                         — totals+targets+atlas tip
    GET      /api/nutrition/summary                       — 7-day summary
    POST     /api/nutrition/hydration                     — +ml body{amount_ml}
    GET      /api/nutrition/hydration/today
    GET      /api/nutrition/favourites
    POST     /api/nutrition/favourites
    DELETE   /api/nutrition/favourites/{id}
    GET      /api/nutrition/atlas-tip                     — Claude Sonnet 4.5 one-liner
    -- Coach --
    GET      /api/coach/nutrition/clients                 — one-row-per-client summary
    GET      /api/coach/nutrition/clients/{user_id}       — deep dive
    PATCH    /api/coach/nutrition/targets/{user_id}       — coach set/override
    POST     /api/coach/nutrition/notes                   — add nutrition note (client)
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional
import datetime as _dt

from server import (
    api, db, current_user, require_admin, new_id, now_iso, logger,
    EMERGENT_LLM_KEY,
)

# ---------------------------------------------------------------------------
# Constants + safety guardrails
# ---------------------------------------------------------------------------

# Absolute floors — coach cannot go below these values via API.
MIN_CALORIES = 1500       # never allow sub-1500 kcal targets by default
MIN_PROTEIN_G = 60        # minimum protein floor
MAX_CALORIES = 5000
MAX_PROTEIN_G = 400
MIN_HYDRATION_ML = 1500

# Roster-context tags (mirror Standby + WorkoutMode categories)
ROSTER_CONTEXTS = [
    "home", "home_training", "flight_day", "turnaround", "layover_arrival",
    "layover_full", "layover_departure", "long_haul", "short_haul",
    "night_flight", "early_start", "standby", "rest_day", "recovery",
]

MEAL_TYPES = [
    "breakfast", "lunch", "dinner", "snack",
    "pre_flight", "in_flight", "post_flight",
    "post_workout", "hotel_meal", "airport_meal", "crew_meal",
]

SOURCES = ["manual", "barcode", "photo", "favourite", "coach"]

GOALS = ["fat_loss", "muscle_gain", "endurance", "general_health", "recovery"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TargetIn(BaseModel):
    calories: Optional[int] = None
    protein_g: Optional[int] = None
    carbs_g: Optional[int] = None
    fats_g: Optional[int] = None
    hydration_ml: Optional[int] = None
    goal: Optional[str] = None
    target_type: Optional[str] = "coach"  # coach | atlas
    active_from: Optional[str] = None
    notes: Optional[str] = None


class LogIn(BaseModel):
    date_local: Optional[str] = None            # YYYY-MM-DD (defaults today)
    meal_type: str = "snack"
    food_name: str
    calories: int = 0
    protein_g: float = 0
    carbs_g: float = 0
    fats_g: float = 0
    portion: Optional[str] = None
    notes: Optional[str] = None
    source: str = "manual"                      # manual|barcode|photo|favourite|coach
    barcode: Optional[str] = None
    location_context: Optional[str] = None      # e.g. "Dubai Layover"
    roster_context: Optional[str] = None        # one of ROSTER_CONTEXTS
    time_zone: Optional[str] = None
    photo_url: Optional[str] = None
    confidence_level: Optional[str] = None      # low|medium|high (photo scan)


class LogPatch(BaseModel):
    meal_type: Optional[str] = None
    food_name: Optional[str] = None
    calories: Optional[int] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fats_g: Optional[float] = None
    portion: Optional[str] = None
    notes: Optional[str] = None
    location_context: Optional[str] = None
    roster_context: Optional[str] = None


class HydrationIn(BaseModel):
    amount_ml: int = 250
    date_local: Optional[str] = None


class FavouriteIn(BaseModel):
    name: str
    calories: int = 0
    protein_g: float = 0
    carbs_g: float = 0
    fats_g: float = 0
    meal_type: str = "snack"
    portion: Optional[str] = None


class CoachNoteIn(BaseModel):
    client_user_id: str
    note: str
    kind: str = "nutrition"  # nutrition | flag | reminder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _defaults_for(user: dict) -> dict:
    """Reasonable default targets when the coach hasn't set anything yet.

    Uses weight (kg) if present in user profile; otherwise falls back to
    safe generic targets that will not break anything.
    """
    weight_kg = 0
    for k in ("weight_kg", "weight", "profile_weight_kg"):
        v = (user or {}).get(k)
        if v:
            try: weight_kg = float(v); break
            except Exception: pass
    if not weight_kg:
        # Try nested profile
        p = (user or {}).get("profile") or {}
        v = p.get("weight_kg") or p.get("weight")
        if v:
            try: weight_kg = float(v)
            except Exception: pass

    # Conservative defaults: 30 kcal/kg, 1.8g protein/kg, 3L hydration
    if weight_kg:
        calories = max(MIN_CALORIES, int(round(weight_kg * 30)))
        protein_g = max(MIN_PROTEIN_G, int(round(weight_kg * 1.8)))
    else:
        calories = 2200
        protein_g = 140

    fats_g = max(50, int(round((calories * 0.28) / 9)))
    carbs_g = max(150, int(round((calories - protein_g * 4 - fats_g * 9) / 4)))

    return {
        "calories": calories, "protein_g": protein_g,
        "carbs_g": carbs_g, "fats_g": fats_g,
        "hydration_ml": 2500,
        "goal": "general_health",
        "target_type": "atlas_default",
        "notes": "Atlas default target — your coach can adjust anytime.",
    }


def _sanitize_target(t: dict) -> dict:
    """Enforce safety floors/ceilings before persisting a target row."""
    out = dict(t)
    if "calories" in out and out["calories"] is not None:
        out["calories"] = max(MIN_CALORIES, min(MAX_CALORIES, int(out["calories"])))
    if "protein_g" in out and out["protein_g"] is not None:
        out["protein_g"] = max(MIN_PROTEIN_G, min(MAX_PROTEIN_G, int(out["protein_g"])))
    if "hydration_ml" in out and out["hydration_ml"] is not None:
        out["hydration_ml"] = max(MIN_HYDRATION_ML, min(6000, int(out["hydration_ml"])))
    if "carbs_g" in out and out["carbs_g"] is not None:
        out["carbs_g"] = max(50, min(700, int(out["carbs_g"])))
    if "fats_g" in out and out["fats_g"] is not None:
        out["fats_g"] = max(30, min(250, int(out["fats_g"])))
    return out


async def _active_target(user_id: str) -> dict:
    """Return the active target for a user, falling back to Atlas defaults."""
    doc = await db.nutrition_targets.find_one(
        {"user_id": user_id, "active": True}, {"_id": 0}
    )
    if doc:
        return doc
    # Look up user to compute defaults
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0}) or {}
    d = _defaults_for(u)
    d["user_id"] = user_id
    d["active"] = True
    d["is_default"] = True
    return d


async def _totals_for_day(user_id: str, date_local: str) -> dict:
    logs = await db.nutrition_logs.find(
        {"user_id": user_id, "date_local": date_local}, {"_id": 0}
    ).to_list(500)
    totals = {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fats_g": 0.0, "count": len(logs)}
    for row in logs:
        totals["calories"] += int(row.get("calories") or 0)
        totals["protein_g"] += float(row.get("protein_g") or 0)
        totals["carbs_g"] += float(row.get("carbs_g") or 0)
        totals["fats_g"] += float(row.get("fats_g") or 0)
    totals["protein_g"] = round(totals["protein_g"], 1)
    totals["carbs_g"] = round(totals["carbs_g"], 1)
    totals["fats_g"] = round(totals["fats_g"], 1)
    return totals


async def _hydration_for_day(user_id: str, date_local: str) -> int:
    row = await db.nutrition_hydration.find_one(
        {"user_id": user_id, "date_local": date_local}, {"_id": 0}
    )
    return int((row or {}).get("amount_ml") or 0)


# ---------------------------------------------------------------------------
# Client endpoints
# ---------------------------------------------------------------------------

@api.get("/nutrition/targets/mine")
async def targets_mine(user: dict = Depends(current_user)):
    t = await _active_target(user["id"])
    return {"target": t, "guardrails": {
        "min_calories": MIN_CALORIES, "min_protein_g": MIN_PROTEIN_G,
        "max_calories": MAX_CALORIES, "max_protein_g": MAX_PROTEIN_G,
        "min_hydration_ml": MIN_HYDRATION_ML,
    }}


@api.post("/nutrition/targets")
async def targets_upsert(body: TargetIn, user: dict = Depends(current_user)):
    """A client can set their own targets (best-effort, gets flagged for coach)."""
    payload = _sanitize_target({k: v for k, v in body.model_dump().items() if v is not None})
    now = now_iso()
    # Deactivate previous
    await db.nutrition_targets.update_many(
        {"user_id": user["id"], "active": True}, {"$set": {"active": False, "active_until": now}}
    )
    doc = {
        "id": new_id(), "user_id": user["id"], "active": True,
        "active_from": now, "created_by": user["id"],
        "created_at": now, "updated_at": now,
        **payload,
    }
    await db.nutrition_targets.insert_one(doc)
    doc.pop("_id", None)
    return {"target": doc}


@api.post("/nutrition/logs")
async def log_create(body: LogIn, user: dict = Depends(current_user)):
    if body.meal_type not in MEAL_TYPES:
        body.meal_type = "snack"
    if body.source not in SOURCES:
        body.source = "manual"
    if body.roster_context and body.roster_context not in ROSTER_CONTEXTS:
        body.roster_context = None
    now = now_iso()
    payload = body.model_dump()
    payload["date_local"] = payload.get("date_local") or _today_iso()
    doc = {
        "id": new_id(),
        "user_id": user["id"],
        **payload,
        "created_at": now, "updated_at": now,
    }
    await db.nutrition_logs.insert_one(doc)
    doc.pop("_id", None)
    return {"log": doc}


@api.get("/nutrition/logs")
async def log_list(date: Optional[str] = None, days: int = 1, user: dict = Depends(current_user)):
    if days > 31: days = 31
    target_date = date or _today_iso()
    if days == 1:
        query: dict = {"user_id": user["id"], "date_local": target_date}
    else:
        # last N days including today
        end = _dt.date.fromisoformat(target_date)
        start = end - _dt.timedelta(days=days - 1)
        dates = [(start + _dt.timedelta(days=i)).isoformat() for i in range(days)]
        query = {"user_id": user["id"], "date_local": {"$in": dates}}
    rows = await db.nutrition_logs.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return {"logs": rows, "count": len(rows)}


@api.patch("/nutrition/logs/{log_id}")
async def log_patch(log_id: str, body: LogPatch, user: dict = Depends(current_user)):
    row = await db.nutrition_logs.find_one({"id": log_id, "user_id": user["id"]})
    if not row: raise HTTPException(404, "not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates: return {"log": {**row, "_id": None}}
    if "meal_type" in updates and updates["meal_type"] not in MEAL_TYPES:
        raise HTTPException(400, "invalid meal_type")
    updates["updated_at"] = now_iso()
    await db.nutrition_logs.update_one({"id": log_id}, {"$set": updates})
    row = await db.nutrition_logs.find_one({"id": log_id}, {"_id": 0})
    return {"log": row}


@api.delete("/nutrition/logs/{log_id}")
async def log_delete(log_id: str, user: dict = Depends(current_user)):
    r = await db.nutrition_logs.delete_one({"id": log_id, "user_id": user["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "not found")
    return {"ok": True}


@api.get("/nutrition/today")
async def nutrition_today(user: dict = Depends(current_user)):
    date_local = _today_iso()
    target = await _active_target(user["id"])
    totals = await _totals_for_day(user["id"], date_local)
    hydration_ml = await _hydration_for_day(user["id"], date_local)
    return {
        "date_local": date_local,
        "target": target,
        "totals": totals,
        "hydration_ml": hydration_ml,
        "remaining": {
            "calories": max(0, int((target.get("calories") or 0) - totals["calories"])),
            "protein_g": max(0.0, round(float(target.get("protein_g") or 0) - totals["protein_g"], 1)),
            "hydration_ml": max(0, int((target.get("hydration_ml") or 0) - hydration_ml)),
        },
    }


@api.get("/nutrition/week-summary")
async def nutrition_week_summary(user: dict = Depends(current_user)):
    """Simple 7-day summary — average kcal / protein / logging days."""
    end = _dt.date.today()
    start = end - _dt.timedelta(days=6)
    dates = [(start + _dt.timedelta(days=i)).isoformat() for i in range(7)]
    rows = await db.nutrition_logs.find(
        {"user_id": user["id"], "date_local": {"$in": dates}}, {"_id": 0}
    ).to_list(2000)
    per_day: dict[str, dict] = {d: {"calories": 0, "protein_g": 0.0} for d in dates}
    for r in rows:
        d = r.get("date_local")
        if d in per_day:
            per_day[d]["calories"] += int(r.get("calories") or 0)
            per_day[d]["protein_g"] += float(r.get("protein_g") or 0)
    days_logged = sum(1 for v in per_day.values() if v["calories"] > 0)
    avg_cal = int(round(sum(v["calories"] for v in per_day.values()) / max(1, days_logged))) if days_logged else 0
    avg_pro = round(sum(v["protein_g"] for v in per_day.values()) / max(1, days_logged), 1) if days_logged else 0.0
    return {
        "days_logged": days_logged, "days_total": 7,
        "avg_calories": avg_cal, "avg_protein_g": avg_pro,
        "per_day": [{"date": d, **v} for d, v in per_day.items()],
    }


@api.post("/nutrition/hydration")
async def hydration_add(body: HydrationIn, user: dict = Depends(current_user)):
    amount = max(-3000, min(3000, int(body.amount_ml)))  # allow negatives for undo
    date_local = body.date_local or _today_iso()
    now = now_iso()
    row = await db.nutrition_hydration.find_one({"user_id": user["id"], "date_local": date_local})
    if row:
        new_amt = max(0, int(row.get("amount_ml") or 0) + amount)
        await db.nutrition_hydration.update_one(
            {"user_id": user["id"], "date_local": date_local},
            {"$set": {"amount_ml": new_amt, "updated_at": now}},
        )
        return {"amount_ml": new_amt}
    new_amt = max(0, amount)
    await db.nutrition_hydration.insert_one({
        "id": new_id(), "user_id": user["id"], "date_local": date_local,
        "amount_ml": new_amt, "created_at": now, "updated_at": now,
    })
    return {"amount_ml": new_amt}


@api.get("/nutrition/hydration/today")
async def hydration_today(user: dict = Depends(current_user)):
    ml = await _hydration_for_day(user["id"], _today_iso())
    return {"amount_ml": ml, "date_local": _today_iso()}


@api.get("/nutrition/favourites")
async def favourites_list(user: dict = Depends(current_user)):
    rows = await db.nutrition_favourites.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return {"favourites": rows}


@api.post("/nutrition/favourites")
async def favourites_add(body: FavouriteIn, user: dict = Depends(current_user)):
    doc = {
        "id": new_id(), "user_id": user["id"],
        **body.model_dump(),
        "created_at": now_iso(),
    }
    await db.nutrition_favourites.insert_one(doc)
    doc.pop("_id", None)
    return {"favourite": doc}


@api.delete("/nutrition/favourites/{fav_id}")
async def favourites_delete(fav_id: str, user: dict = Depends(current_user)):
    r = await db.nutrition_favourites.delete_one({"id": fav_id, "user_id": user["id"]})
    if not r.deleted_count:
        raise HTTPException(404, "not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Atlas tip (Claude Sonnet 4.5)
# ---------------------------------------------------------------------------

# Cache tips per (user, date) so repeated visits don't burn API calls.
async def _cached_atlas_tip(user_id: str, date_local: str) -> Optional[str]:
    row = await db.nutrition_atlas_tips.find_one(
        {"user_id": user_id, "date_local": date_local}, {"_id": 0, "text": 1}
    )
    return (row or {}).get("text")


async def _store_atlas_tip(user_id: str, date_local: str, text: str) -> None:
    await db.nutrition_atlas_tips.update_one(
        {"user_id": user_id, "date_local": date_local},
        {"$set": {"user_id": user_id, "date_local": date_local, "text": text, "updated_at": now_iso()}},
        upsert=True,
    )


async def _build_atlas_tip(user: dict) -> str:
    date_local = _today_iso()
    cached = await _cached_atlas_tip(user["id"], date_local)
    if cached:
        return cached

    target = await _active_target(user["id"])
    totals = await _totals_for_day(user["id"], date_local)
    hydration_ml = await _hydration_for_day(user["id"], date_local)

    goal = target.get("goal") or "general_health"
    target_cal = target.get("calories") or 2200
    target_pro = target.get("protein_g") or 140
    target_hyd = target.get("hydration_ml") or 2500

    context = (
        f"Client goal: {goal}. "
        f"Today so far: {totals['calories']}/{target_cal} kcal · "
        f"{totals['protein_g']:.0f}/{target_pro}g protein · "
        f"{hydration_ml}/{target_hyd}ml hydration. "
        f"Logs: {totals['count']}."
    )

    prompt = (
        "You are Atlas, CrewFit's nutrition coach for airline crew. "
        "Give ONE practical coaching sentence (≤ 32 words) tailored to the client's "
        "current daily progress. Aviation-professional tone. Never diagnose, never "
        "use words like 'diet' / 'cheat' / 'failed' / 'bad food'. Prefer 'protein-led', "
        "'hydration', 'timing'. If protein is behind, prioritise it. If hydration is "
        "behind, mention it. If everything is on track, encourage keeping it simple.\n\n"
        f"Context: {context}\n\nRespond with just the sentence, no preamble."
    )

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"nutrition-tip-{user['id']}-{date_local}",
            system_message="You are Atlas, CrewFit's aviation-nutrition coach. Practical, brief, kind.",
        )
        chat.with_model("anthropic", "claude-sonnet-4-5-20250929")
        resp = await chat.send_message(UserMessage(text=prompt))
        text = (resp or "").strip().strip('"').strip()
        if not text:
            text = _fallback_tip(totals, target, hydration_ml)
    except Exception:
        logger.exception("atlas nutrition tip failed")
        text = _fallback_tip(totals, target, hydration_ml)

    await _store_atlas_tip(user["id"], date_local, text)
    return text


def _fallback_tip(totals: dict, target: dict, hydration_ml: int) -> str:
    """Offline fallback if the LLM isn't reachable — always safe copy."""
    pro_missing = max(0, float(target.get("protein_g") or 0) - float(totals.get("protein_g") or 0))
    hyd_missing = max(0, int(target.get("hydration_ml") or 0) - int(hydration_ml))
    if pro_missing >= 30:
        return f"Protein is {int(pro_missing)}g behind — make your next meal protein-led."
    if hyd_missing >= 800:
        return "Hydration is behind today — a glass of water before your next duty."
    return "You're on a solid line today — keep meals simple and hydration steady."


@api.get("/nutrition/atlas-tip")
async def nutrition_atlas_tip(user: dict = Depends(current_user)):
    txt = await _build_atlas_tip(user)
    return {"tip": txt, "date_local": _today_iso()}


# ---------------------------------------------------------------------------
# Coach endpoints
# ---------------------------------------------------------------------------

@api.get("/coach/nutrition/clients")
async def coach_nutr_clients(admin: dict = Depends(require_admin())):
    users = await db.users.find({"role": "client"}, {"_id": 0, "password_hash": 0}).to_list(500)
    today = _today_iso()
    seven_ago = (_dt.date.today() - _dt.timedelta(days=6)).isoformat()
    out: list[dict] = []
    for u in users:
        uid = u["id"]
        target = await _active_target(uid)
        totals = await _totals_for_day(uid, today)
        # 7-day consistency
        dates = [(_dt.date.today() - _dt.timedelta(days=i)).isoformat() for i in range(7)]
        rows = await db.nutrition_logs.find(
            {"user_id": uid, "date_local": {"$in": dates}}, {"_id": 0, "date_local": 1, "calories": 1, "protein_g": 1}
        ).to_list(1000)
        days_logged = len({r["date_local"] for r in rows if int(r.get("calories") or 0) > 0})
        avg_cal = int(round(sum(int(r.get("calories") or 0) for r in rows) / max(1, days_logged))) if days_logged else 0
        avg_pro = round(sum(float(r.get("protein_g") or 0) for r in rows) / max(1, days_logged), 1) if days_logged else 0
        # Flag: protein below 75% of target on 4+ days
        low_pro_days = 0
        target_pro = float(target.get("protein_g") or 0)
        if target_pro:
            by_day: dict[str, float] = {}
            for r in rows:
                d = r.get("date_local")
                by_day[d] = by_day.get(d, 0.0) + float(r.get("protein_g") or 0)
            low_pro_days = sum(1 for v in by_day.values() if v < 0.75 * target_pro)
        out.append({
            "user_id": uid,
            "name": u.get("name") or u.get("email") or "Client",
            "email": u.get("email"),
            "goal": target.get("goal"),
            "target_calories": target.get("calories"),
            "target_protein_g": target.get("protein_g"),
            "today_calories": totals["calories"],
            "today_protein_g": totals["protein_g"],
            "avg_calories_7d": avg_cal,
            "avg_protein_g_7d": avg_pro,
            "days_logged_7d": days_logged,
            "flag_low_protein": low_pro_days >= 4,
            "target_is_default": bool(target.get("is_default")),
        })
    return {"clients": out}


@api.get("/coach/nutrition/clients/{user_id}")
async def coach_nutr_client_detail(user_id: str, admin: dict = Depends(require_admin())):
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not u: raise HTTPException(404, "user not found")
    target = await _active_target(user_id)
    dates = [(_dt.date.today() - _dt.timedelta(days=i)).isoformat() for i in range(7)]
    rows = await db.nutrition_logs.find(
        {"user_id": user_id, "date_local": {"$in": dates}}, {"_id": 0}
    ).sort("created_at", -1).to_list(1000)
    notes = await db.nutrition_notes.find(
        {"client_user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    return {"user": u, "target": target, "recent_logs": rows, "notes": notes}


@api.patch("/coach/nutrition/targets/{user_id}")
async def coach_nutr_targets_set(user_id: str, body: TargetIn, admin: dict = Depends(require_admin())):
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not u: raise HTTPException(404, "user not found")
    payload = _sanitize_target({k: v for k, v in body.model_dump().items() if v is not None})
    now = now_iso()
    await db.nutrition_targets.update_many(
        {"user_id": user_id, "active": True}, {"$set": {"active": False, "active_until": now}}
    )
    doc = {
        "id": new_id(), "user_id": user_id, "active": True, "active_from": now,
        "created_by": admin["id"], "created_at": now, "updated_at": now,
        "target_type": "coach",
        **payload,
    }
    await db.nutrition_targets.insert_one(doc)
    doc.pop("_id", None)
    return {"target": doc}


@api.post("/coach/nutrition/notes")
async def coach_nutr_note_add(body: CoachNoteIn, admin: dict = Depends(require_admin())):
    u = await db.users.find_one({"id": body.client_user_id}, {"_id": 0})
    if not u: raise HTTPException(404, "user not found")
    doc = {
        "id": new_id(),
        "client_user_id": body.client_user_id,
        "coach_user_id": admin["id"],
        "note": body.note[:2000],
        "kind": body.kind,
        "created_at": now_iso(),
    }
    await db.nutrition_notes.insert_one(doc)
    doc.pop("_id", None)
    return {"note": doc}
