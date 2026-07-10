"""feature_nutrition_travel — Roster / airport / hotel / time-zone travel
guidance for CrewFit Nutrition Centre (Phase 4).

All four endpoints share the same Atlas engine: build a structured prompt from
the client's goal + situation, call Claude Sonnet 4.5, and coerce the response
to a well-defined JSON shape.  Results are cached per (user, intent, params
hash, day) so repeat views don't burn API calls.

Endpoints:
    POST /nutrition/travel/decision   — Atlas Meal Decision
    POST /nutrition/travel/airport    — Airport Survival Mode
    POST /nutrition/travel/timing     — Time-zone meal timing
    POST /nutrition/travel/guide      — Travel-Food Guides (multi-topic)
    GET  /nutrition/travel/context    — client-side prefill (goal, targets, remaining)
"""
from __future__ import annotations

import os
import json
import re
import hashlib
import datetime as _dt
from typing import Any, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api, db, current_user, new_id, now_iso, logger, EMERGENT_LLM_KEY,
)
from feature_nutrition import _active_target, _totals_for_day, _hydration_for_day, _today_iso

TRAVEL_MODEL = os.environ.get("NUTR_TRAVEL_MODEL", "claude-sonnet-4-5-20250929")

# ---------------------------------------------------------------------------
# Shared vocab (mirrors Phase-1 domain)
# ---------------------------------------------------------------------------

SITUATIONS = [
    "airport", "hotel_breakfast", "hotel_buffet", "layover",
    "night_flight", "only_snacks", "about_to_train", "just_landed",
    "really_hungry", "stay_on_track", "long_haul_flight",
]

GUIDE_TOPICS = [
    "airport_strategy", "hotel_breakfast", "hotel_buffet", "crew_meal",
    "long_haul", "night_flight", "early_start",
    "fat_loss_layover", "muscle_gain_travel", "endurance_fuelling",
    "hydration_caffeine",
]

BANNED_WORDS = ["cheat meal", "cheat", "diet", "bad food", "dirty food", "failed"]

# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def _system() -> str:
    return (
        "You are Atlas, CrewFit's aviation-nutrition coach. Airline crew, "
        "pilots and cabin crew are your clients. Reply with STRICT JSON only "
        "(no markdown, no prose). Never diagnose medical conditions. Never say "
        "'diet', 'cheat', 'failed', 'bad food', 'dirty food'. Use 'protein-led', "
        "'hydration', 'timing', 'lighter meal', 'supportive choice'. Estimates only."
    )


async def _context_summary(user: dict) -> dict:
    target = await _active_target(user["id"])
    today = _today_iso()
    totals = await _totals_for_day(user["id"], today)
    hydration_ml = await _hydration_for_day(user["id"], today)
    remaining = {
        "calories": max(0, int((target.get("calories") or 0) - totals["calories"])),
        "protein_g": max(0.0, round(float(target.get("protein_g") or 0) - totals["protein_g"], 1)),
        "hydration_ml": max(0, int((target.get("hydration_ml") or 0) - hydration_ml)),
    }
    return {
        "goal": target.get("goal") or "general_health",
        "target_calories": target.get("calories"),
        "target_protein_g": target.get("protein_g"),
        "target_hydration_ml": target.get("hydration_ml"),
        "today_calories": totals["calories"],
        "today_protein_g": totals["protein_g"],
        "hydration_ml_today": hydration_ml,
        "remaining": remaining,
        "logs_today": totals["count"],
    }


def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if m: t = m.group(0)
    try:
        return json.loads(t)
    except Exception:
        logger.warning("bad JSON from travel llm: %s", (text or "")[:400])
        raise HTTPException(502, "Atlas returned invalid JSON")


async def _call_atlas(prompt: str, session_seed: str, user: dict | None = None,
                       feature: str = "travel_guidance", enforce: bool = True) -> dict:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    # Rate limit + telemetry gate. Callers that pre-check the quota can pass
    # enforce=False to avoid a double check_quota round-trip.
    import ai_limits
    if user is not None and enforce:
        await ai_limits.check_quota(db, user, feature)
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"travel-{session_seed}-{new_id()}",
        system_message=_system(),
    ).with_model("anthropic", TRAVEL_MODEL)
    resp = await chat.send_message(UserMessage(text=prompt))
    text = resp or ""
    # Non-blocking usage log so admin dashboard sees this feature.
    if user is not None:
        try:
            await ai_limits.record_usage(
                db, user_id=user["id"], feature=feature,
                model=TRAVEL_MODEL, provider="anthropic",
                tokens_in=ai_limits.estimate_tokens_from_text(_system(), prompt),
                tokens_out=ai_limits.estimate_tokens_from_text(text),
                success=True,
            )
        except Exception:
            pass
    return _parse_json(text)


def _sanitise(text: str) -> str:
    """Best-effort scrub of banned wording."""
    out = text or ""
    replacements = {
        "cheat meal": "higher-calorie meal",
        "cheat": "flexible choice",
        "diet ": "nutrition ",
        "diets ": "nutrition plans ",
        "bad food": "less-supportive choice",
        "dirty food": "less-supportive choice",
        "failed": "adjusted",
    }
    for k, v in replacements.items():
        out = re.sub(k, v, out, flags=re.IGNORECASE)
    return out


def _clean_dict(x: Any) -> Any:
    if isinstance(x, str): return _sanitise(x).strip()
    if isinstance(x, list): return [_clean_dict(v) for v in x]
    if isinstance(x, dict): return {k: _clean_dict(v) for k, v in x.items()}
    return x


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(user_id: str, intent: str, params: dict) -> str:
    payload = json.dumps(params, sort_keys=True, default=str)
    h = hashlib.sha256(f"{user_id}|{intent}|{payload}".encode()).hexdigest()[:16]
    return f"{intent}:{h}"


async def _cache_get(user_id: str, key: str) -> Optional[dict]:
    row = await db.nutrition_travel_cache.find_one(
        {"user_id": user_id, "key": key, "date_local": _today_iso()},
        {"_id": 0, "payload": 1},
    )
    return (row or {}).get("payload")


async def _cache_put(user_id: str, key: str, payload: dict) -> None:
    await db.nutrition_travel_cache.update_one(
        {"user_id": user_id, "key": key, "date_local": _today_iso()},
        {"$set": {
            "user_id": user_id, "key": key, "date_local": _today_iso(),
            "payload": payload, "created_at": now_iso(),
        }},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class DecisionIn(BaseModel):
    situation: str                         # one of SITUATIONS
    hunger_level: Optional[str] = None     # "low"|"medium"|"high"
    next_context: Optional[str] = None     # "sleep_soon"|"training"|"duty"|"free"
    time_zone: Optional[str] = None
    notes: Optional[str] = None


@api.get("/nutrition/travel/context")
async def travel_context(user: dict = Depends(current_user)):
    return {"context": await _context_summary(user)}


@api.post("/nutrition/travel/decision")
async def travel_decision(body: DecisionIn, user: dict = Depends(current_user)):
    if body.situation not in SITUATIONS:
        raise HTTPException(400, "invalid situation")
    params = body.model_dump()
    ctx = await _context_summary(user)
    key = _cache_key(user["id"], "decision", {"params": params, "ctx_goal": ctx["goal"]})
    cached = await _cache_get(user["id"], key)
    if cached:
        return {"decision": cached, "cached": True, "context": ctx}

    prompt = f"""
Client is in this situation: {body.situation}.
Hunger level: {body.hunger_level or 'medium'}.
Next context: {body.next_context or 'unknown'}.
Time zone: {body.time_zone or 'unknown'}.
Notes: {body.notes or 'none'}.
Nutrition context: {json.dumps(ctx)}.

Give a practical Atlas meal decision — one clear coaching call for THIS moment.

Return STRICT JSON only:
{{
  "headline": "Choose a protein-led meal now.",
  "reason": "Because … (1-2 short sentences, aviation coaching tone).",
  "do_this": ["…", "…", "…"],
  "avoid": ["…", "…"],
  "protein_led_options": ["…", "…", "…"],
  "hydration_note": "one short line",
  "confidence": "medium"
}}
Headline ≤ 12 words. Each list item ≤ 15 words. No markdown.
""".strip()

    raw = await _call_atlas(prompt, "decision", user)
    decision = _clean_dict({
        "headline": raw.get("headline", ""),
        "reason": raw.get("reason", ""),
        "do_this": raw.get("do_this", [])[:5],
        "avoid": raw.get("avoid", [])[:5],
        "protein_led_options": raw.get("protein_led_options", [])[:5],
        "hydration_note": raw.get("hydration_note", ""),
        "confidence": (raw.get("confidence") or "medium"),
    })
    await _cache_put(user["id"], key, decision)
    return {"decision": decision, "cached": False, "context": ctx}


class AirportIn(BaseModel):
    airport_code: Optional[str] = None     # e.g. "DXB"
    airport_name: Optional[str] = None
    time_available_min: Optional[int] = 45
    hunger_level: Optional[str] = "medium"
    next_context: Optional[str] = "duty"   # duty|sleep_soon|training|free|layover


@api.post("/nutrition/travel/airport")
async def travel_airport(body: AirportIn, user: dict = Depends(current_user)):
    params = body.model_dump()
    ctx = await _context_summary(user)
    key = _cache_key(user["id"], "airport", {"params": params, "goal": ctx["goal"]})
    cached = await _cache_get(user["id"], key)
    if cached:
        return {"plan": cached, "cached": True, "context": ctx}

    prompt = f"""
Airport code: {body.airport_code or 'unknown'}
Airport name: {body.airport_name or 'unknown'}
Time available before boarding: {body.time_available_min or 45} minutes
Hunger level: {body.hunger_level or 'medium'}
Next context: {body.next_context or 'duty'}
Nutrition context: {json.dumps(ctx)}

You do NOT have live airport-restaurant data — use general airport-food logic
(most large airports have kiosks, cafés, grab-and-go, sandwich shops, fast food).
NEVER claim specific restaurants exist unless the airport is world-famous
(e.g. Dubai T3, LHR T5, JFK T4). Prefer generic food-type advice.

Return STRICT JSON only:
{{
  "headline": "Protein-led meal before boarding.",
  "best_moves": ["…", "…"],
  "ok_moves": ["…", "…"],
  "avoid_if_possible": ["…", "…"],
  "snack_backup": ["…", "…"],
  "hydration_reminder": "one short line",
  "if_time_is_short": "one short line",
  "confidence": "medium"
}}
Each list item ≤ 18 words. Give 2-4 items per list. No markdown.
""".strip()

    raw = await _call_atlas(prompt, "airport", user)
    plan = _clean_dict({
        "headline": raw.get("headline", ""),
        "best_moves": raw.get("best_moves", [])[:5],
        "ok_moves": raw.get("ok_moves", [])[:5],
        "avoid_if_possible": raw.get("avoid_if_possible", [])[:5],
        "snack_backup": raw.get("snack_backup", [])[:5],
        "hydration_reminder": raw.get("hydration_reminder", ""),
        "if_time_is_short": raw.get("if_time_is_short", ""),
        "confidence": (raw.get("confidence") or "medium"),
    })
    await _cache_put(user["id"], key, plan)
    return {"plan": plan, "cached": False, "context": ctx}


class TimingIn(BaseModel):
    home_tz: Optional[str] = None          # e.g. "Europe/London"
    current_tz: Optional[str] = None       # e.g. "Asia/Dubai"
    flight_context: Optional[str] = None   # "long_haul"|"short_haul"|"turnaround"|"layover_arrival"|"just_landed"
    planned_sleep_local: Optional[str] = None  # HH:MM in local tz
    next_workout_context: Optional[str] = None # "tomorrow_am"|"today_pm"|"none"


@api.post("/nutrition/travel/timing")
async def travel_timing(body: TimingIn, user: dict = Depends(current_user)):
    params = body.model_dump()
    ctx = await _context_summary(user)
    key = _cache_key(user["id"], "timing", {"params": params, "goal": ctx["goal"]})
    cached = await _cache_get(user["id"], key)
    if cached:
        return {"timing": cached, "cached": True, "context": ctx}

    prompt = f"""
Home time zone: {body.home_tz or 'unknown'}
Current time zone: {body.current_tz or 'unknown'}
Flight context: {body.flight_context or 'unknown'}
Planned sleep (local): {body.planned_sleep_local or 'unknown'}
Next workout: {body.next_workout_context or 'unknown'}
Nutrition context: {json.dumps(ctx)}

Give practical time-zone-aware meal timing coaching. NEVER make medical sleep
claims. Prefer 'lighter meal', 'protein-led', 'caffeine cut-off', 'hydration'.

Return STRICT JSON only:
{{
  "headline": "Lighter, protein-based meal before sleep.",
  "meal_plan": [
    {{"when": "Now", "what": "…"}},
    {{"when": "Pre-sleep window", "what": "…"}}
  ],
  "caffeine_cutoff": "one short line",
  "hydration_focus": "one short line",
  "post_flight_recovery_meal": "one short line",
  "confidence": "medium"
}}
Keep entries ≤ 20 words. 2-4 meal_plan entries. No markdown.
""".strip()

    raw = await _call_atlas(prompt, "timing", user)
    mp = raw.get("meal_plan") or []
    if not isinstance(mp, list): mp = []
    plan = _clean_dict({
        "headline": raw.get("headline", ""),
        "meal_plan": [{"when": str((x or {}).get("when") or "").strip(),
                       "what": str((x or {}).get("what") or "").strip()} for x in mp[:6]],
        "caffeine_cutoff": raw.get("caffeine_cutoff", ""),
        "hydration_focus": raw.get("hydration_focus", ""),
        "post_flight_recovery_meal": raw.get("post_flight_recovery_meal", ""),
        "confidence": (raw.get("confidence") or "medium"),
    })
    await _cache_put(user["id"], key, plan)
    return {"timing": plan, "cached": False, "context": ctx}


class GuideIn(BaseModel):
    topic: str                             # one of GUIDE_TOPICS


@api.post("/nutrition/travel/guide")
async def travel_guide(body: GuideIn, user: dict = Depends(current_user)):
    if body.topic not in GUIDE_TOPICS:
        raise HTTPException(400, "invalid topic")
    ctx = await _context_summary(user)
    key = _cache_key(user["id"], "guide", {"topic": body.topic, "goal": ctx["goal"]})
    cached = await _cache_get(user["id"], key)
    if cached:
        return {"guide": cached, "cached": True, "context": ctx}

    topic_label = body.topic.replace("_", " ").title()
    prompt = f"""
Write a compact travel-nutrition guide for airline crew.
Topic: {topic_label}.
Personalise for client goal: {ctx['goal']}. Nutrition context: {json.dumps(ctx)}.

Return STRICT JSON only:
{{
  "title": "Hotel Buffet Strategy",
  "one_liner": "How to win the hotel buffet without turning it into a binge.",
  "steps": ["Protein first.", "…", "…", "…"],
  "watchouts": ["…", "…"],
  "if_goal_is_fat_loss": "one short line",
  "if_goal_is_muscle_gain": "one short line",
  "if_goal_is_endurance": "one short line"
}}
5-7 steps. Each ≤ 18 words. No markdown.
""".strip()

    raw = await _call_atlas(prompt, f"guide_{body.topic}", user)
    guide = _clean_dict({
        "topic": body.topic,
        "title": raw.get("title") or topic_label,
        "one_liner": raw.get("one_liner", ""),
        "steps": raw.get("steps", [])[:8],
        "watchouts": raw.get("watchouts", [])[:5],
        "if_goal_is_fat_loss": raw.get("if_goal_is_fat_loss", ""),
        "if_goal_is_muscle_gain": raw.get("if_goal_is_muscle_gain", ""),
        "if_goal_is_endurance": raw.get("if_goal_is_endurance", ""),
    })
    await _cache_put(user["id"], key, guide)
    return {"guide": guide, "cached": False, "context": ctx}
