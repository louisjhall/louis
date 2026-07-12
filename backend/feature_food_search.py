"""feature_food_search — Food database search for the Nutrition Centre.

Wraps the existing Open Food Facts (OFF) search with a curated *local
fallback DB* of common aviation-crew-friendly foods so the search UI still
works when OFF is slow, rate-limited, or the query is too generic to give
useful branded results (e.g. "chicken breast" → OFF returns dozens of
sauces before the plain protein).

Also exposes:

* ``/nutrition/food/recent`` – de-duplicated recent foods the user has
  actually logged, ready for one-tap re-add.
* ``/nutrition/food/estimate`` – Atlas fallback that uses the Emergent LLM
  key to *estimate* macros for foods no provider indexes ("Hotel buffet
  eggs and toast"). Always returned as an ``estimated: true`` payload so
  the UI can label it clearly and require user confirmation.

All values are per-100 g unless the local row explicitly gives a common
serving; the UI applies the serving scale.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger("crewfit.food_search")

# ---------------------------------------------------------------------------
# Local fallback DB — hand-curated for aviation crew. Values are approximate
# and always labelled "estimate" in the UI.
# Each row: name, brand (optional), calories, protein_g, carbs_g, fats_g,
# serving_size (usually per 100 g), keywords (search hits).
# ---------------------------------------------------------------------------
_LOCAL_FOODS: list[dict] = [
    # Proteins
    {"name": "Chicken Breast, Cooked", "cat": "protein", "kcal": 165, "p": 31, "c": 0, "f": 3.6, "serving": "100g", "keywords": ["chicken", "breast", "poultry"]},
    {"name": "Chicken Thigh, Cooked", "cat": "protein", "kcal": 209, "p": 26, "c": 0, "f": 10.9, "serving": "100g", "keywords": ["chicken", "thigh", "poultry"]},
    {"name": "Salmon, Cooked", "cat": "protein", "kcal": 208, "p": 22, "c": 0, "f": 13, "serving": "100g", "keywords": ["salmon", "fish"]},
    {"name": "Tuna, Canned in Water", "cat": "protein", "kcal": 116, "p": 26, "c": 0, "f": 1, "serving": "100g", "keywords": ["tuna", "fish", "canned"]},
    {"name": "Eggs, Whole (2 large)", "cat": "protein", "kcal": 143, "p": 12.6, "c": 0.7, "f": 9.5, "serving": "2 eggs", "keywords": ["egg", "eggs", "whole egg"]},
    {"name": "Egg Whites (4 large)", "cat": "protein", "kcal": 68, "p": 14.4, "c": 1, "f": 0.2, "serving": "4 whites", "keywords": ["egg white", "whites"]},
    {"name": "Beef Steak, Sirloin", "cat": "protein", "kcal": 206, "p": 29, "c": 0, "f": 9, "serving": "100g", "keywords": ["steak", "beef", "sirloin"]},
    {"name": "Turkey Breast, Cooked", "cat": "protein", "kcal": 135, "p": 30, "c": 0, "f": 1, "serving": "100g", "keywords": ["turkey", "poultry"]},
    {"name": "Whey Protein Powder", "cat": "protein", "kcal": 120, "p": 24, "c": 3, "f": 1.5, "serving": "1 scoop (30g)", "keywords": ["whey", "protein powder", "protein shake"]},
    {"name": "Protein Shake, RTD", "cat": "protein", "kcal": 150, "p": 30, "c": 5, "f": 2, "serving": "1 bottle (330ml)", "keywords": ["protein shake", "rtd", "drink"]},
    {"name": "Protein Bar", "cat": "protein", "kcal": 220, "p": 20, "c": 24, "f": 6, "serving": "1 bar (60g)", "keywords": ["protein bar", "bar", "snack"]},
    {"name": "Greek Yoghurt, Plain 0%", "cat": "protein", "kcal": 59, "p": 10, "c": 3.6, "f": 0.4, "serving": "100g", "keywords": ["greek yoghurt", "yogurt", "greek"]},
    {"name": "Cottage Cheese", "cat": "protein", "kcal": 98, "p": 11, "c": 3.4, "f": 4.3, "serving": "100g", "keywords": ["cottage cheese"]},
    # Carbs
    {"name": "Oats / Porridge, Dry", "cat": "carb", "kcal": 379, "p": 13, "c": 68, "f": 6.5, "serving": "40g dry", "keywords": ["oats", "porridge", "oatmeal"]},
    {"name": "White Rice, Cooked", "cat": "carb", "kcal": 130, "p": 2.7, "c": 28, "f": 0.3, "serving": "100g", "keywords": ["rice", "white rice"]},
    {"name": "Brown Rice, Cooked", "cat": "carb", "kcal": 111, "p": 2.6, "c": 23, "f": 0.9, "serving": "100g", "keywords": ["brown rice", "rice"]},
    {"name": "Pasta, Cooked", "cat": "carb", "kcal": 131, "p": 5, "c": 25, "f": 1.1, "serving": "100g", "keywords": ["pasta", "spaghetti", "penne"]},
    {"name": "Potato, Boiled", "cat": "carb", "kcal": 87, "p": 1.9, "c": 20, "f": 0.1, "serving": "100g", "keywords": ["potato", "potatoes"]},
    {"name": "Sweet Potato, Baked", "cat": "carb", "kcal": 90, "p": 2, "c": 21, "f": 0.2, "serving": "100g", "keywords": ["sweet potato", "yam"]},
    {"name": "Bread, Whole Wheat (1 slice)", "cat": "carb", "kcal": 82, "p": 4, "c": 14, "f": 1.1, "serving": "1 slice (40g)", "keywords": ["bread", "wholewheat", "wholemeal", "toast"]},
    {"name": "Wrap, Tortilla (medium)", "cat": "carb", "kcal": 218, "p": 5.5, "c": 36, "f": 5, "serving": "1 wrap", "keywords": ["wrap", "tortilla", "flatbread"]},
    {"name": "Cereal, Cornflakes", "cat": "carb", "kcal": 357, "p": 7, "c": 84, "f": 0.9, "serving": "40g", "keywords": ["cereal", "cornflakes", "breakfast"]},
    {"name": "Bagel, Plain", "cat": "carb", "kcal": 250, "p": 10, "c": 49, "f": 1.5, "serving": "1 bagel (95g)", "keywords": ["bagel", "bread"]},
    # Fruit
    {"name": "Banana", "cat": "fruit", "kcal": 89, "p": 1.1, "c": 23, "f": 0.3, "serving": "1 medium (118g)", "keywords": ["banana"]},
    {"name": "Apple", "cat": "fruit", "kcal": 52, "p": 0.3, "c": 14, "f": 0.2, "serving": "1 medium (180g)", "keywords": ["apple"]},
    {"name": "Mixed Berries", "cat": "fruit", "kcal": 43, "p": 0.7, "c": 10, "f": 0.5, "serving": "100g", "keywords": ["berries", "blueberry", "strawberry", "raspberry"]},
    {"name": "Orange", "cat": "fruit", "kcal": 47, "p": 0.9, "c": 12, "f": 0.1, "serving": "1 medium (130g)", "keywords": ["orange"]},
    # Fats / other
    {"name": "Avocado", "cat": "fat", "kcal": 160, "p": 2, "c": 9, "f": 15, "serving": "100g", "keywords": ["avocado"]},
    {"name": "Peanut Butter", "cat": "fat", "kcal": 588, "p": 25, "c": 20, "f": 50, "serving": "2 tbsp (32g)", "keywords": ["peanut butter", "pb"]},
    {"name": "Almonds", "cat": "fat", "kcal": 579, "p": 21, "c": 22, "f": 50, "serving": "30g (handful)", "keywords": ["almonds", "nuts"]},
    {"name": "Olive Oil", "cat": "fat", "kcal": 884, "p": 0, "c": 0, "f": 100, "serving": "1 tbsp (15g)", "keywords": ["olive oil", "oil"]},
    # Salads / meals
    {"name": "Chicken Salad", "cat": "meal", "kcal": 200, "p": 20, "c": 10, "f": 9, "serving": "1 bowl (300g)", "keywords": ["chicken salad", "salad"]},
    {"name": "Caesar Salad with Chicken", "cat": "meal", "kcal": 470, "p": 30, "c": 15, "f": 32, "serving": "1 bowl (400g)", "keywords": ["caesar", "chicken", "salad"]},
    {"name": "Chicken & Rice Bowl", "cat": "meal", "kcal": 480, "p": 40, "c": 55, "f": 10, "serving": "1 bowl (450g)", "keywords": ["chicken rice", "bowl", "meal"]},
    {"name": "Sushi (6 pieces)", "cat": "meal", "kcal": 300, "p": 12, "c": 55, "f": 3, "serving": "6 pcs", "keywords": ["sushi", "roll"]},
    # Legumes / beans
    {"name": "Lentils, Cooked", "cat": "protein", "kcal": 116, "p": 9, "c": 20, "f": 0.4, "serving": "100g", "keywords": ["lentils", "legumes"]},
    {"name": "Black Beans, Cooked", "cat": "protein", "kcal": 132, "p": 8.9, "c": 24, "f": 0.5, "serving": "100g", "keywords": ["beans", "black beans"]},
    {"name": "Chickpeas, Cooked", "cat": "protein", "kcal": 164, "p": 9, "c": 27, "f": 2.6, "serving": "100g", "keywords": ["chickpeas", "garbanzo", "hummus"]},
    # Dairy / drinks
    {"name": "Milk, Semi-Skimmed", "cat": "drink", "kcal": 50, "p": 3.4, "c": 4.8, "f": 1.8, "serving": "200ml", "keywords": ["milk", "semi skimmed", "dairy"]},
    {"name": "Almond Milk, Unsweetened", "cat": "drink", "kcal": 17, "p": 0.6, "c": 0.3, "f": 1.5, "serving": "200ml", "keywords": ["almond milk", "plant milk"]},
    {"name": "Coffee, Black", "cat": "drink", "kcal": 2, "p": 0.3, "c": 0, "f": 0, "serving": "1 cup (240ml)", "keywords": ["coffee", "black coffee", "americano"]},
    {"name": "Latte (Semi-Skimmed)", "cat": "drink", "brand": "generic", "kcal": 120, "p": 8, "c": 12, "f": 4, "serving": "1 medium (330ml)", "keywords": ["latte", "coffee", "starbucks", "costa"]},
    {"name": "Cappuccino (Semi-Skimmed)", "cat": "drink", "brand": "generic", "kcal": 80, "p": 5, "c": 6, "f": 3, "serving": "1 medium (240ml)", "keywords": ["cappuccino", "coffee"]},
    # Airport / hotel typical
    {"name": "Pret-Style Chicken Sandwich", "cat": "meal", "brand": "airport-style", "kcal": 445, "p": 30, "c": 45, "f": 15, "serving": "1 sandwich", "keywords": ["sandwich", "pret", "chicken", "airport"]},
    {"name": "Hotel Buffet Scrambled Eggs & Toast", "cat": "meal", "brand": "hotel-style", "kcal": 380, "p": 20, "c": 30, "f": 20, "serving": "1 plate", "keywords": ["hotel", "buffet", "eggs", "toast", "breakfast"]},
    {"name": "Crew Meal Chicken & Vegetables", "cat": "meal", "brand": "crew-meal", "kcal": 550, "p": 35, "c": 50, "f": 22, "serving": "1 tray", "keywords": ["crew", "meal", "chicken", "in-flight"]},
]


# Aviation-specific quick-chip presets → search seed.
QUICK_CHIPS: list[dict] = [
    {"label": "Airport meal",   "query": "airport chicken sandwich"},
    {"label": "Hotel breakfast", "query": "hotel eggs toast"},
    {"label": "Crew meal",       "query": "crew meal chicken"},
    {"label": "High protein",    "query": "chicken breast"},
    {"label": "Low prep",        "query": "protein bar"},
    {"label": "Snack",           "query": "protein bar"},
    {"label": "Coffee",          "query": "latte"},
    {"label": "Protein bar",     "query": "protein bar"},
    {"label": "Sandwich",        "query": "chicken sandwich"},
    {"label": "Salad",           "query": "chicken salad"},
]


def _score_local(row: dict, q: str) -> int:
    q = q.lower().strip()
    if not q:
        return 0
    name = row.get("name", "").lower()
    kws = row.get("keywords", [])
    score = 0
    if q == name:
        score += 100
    if name.startswith(q):
        score += 40
    if q in name:
        score += 30
    for kw in kws:
        if kw == q:
            score += 40
        elif q in kw or kw in q:
            score += 15
    # Any token match bonus.
    for tok in re.split(r"\W+", q):
        if not tok:
            continue
        if any(tok in kw for kw in kws) or tok in name:
            score += 5
    return score


def _to_search_result(row: dict) -> dict:
    return {
        "id": f"local-{row['name'].lower().replace(' ', '-').replace(',', '').replace('/', '-')}",
        "source": "local",
        "name": row["name"],
        "brand": row.get("brand") or None,
        "image_url": None,
        "calories": row["kcal"],
        "protein_g": row["p"],
        "carbs_g": row["c"],
        "fats_g": row["f"],
        "serving_size": row.get("serving"),
        "per_100g": (row.get("serving") == "100g"),
    }


def search_local(q: str, limit: int = 8) -> list[dict]:
    if not q or len(q.strip()) < 2:
        return []
    scored = [(_score_local(r, q), r) for r in _LOCAL_FOODS]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: -x[0])
    return [_to_search_result(r) for _, r in scored[:limit]]


def register(api: APIRouter, *, db, current_user, emergent_llm_key: Optional[str] = None):
    """Register the enhanced search + recent + estimate endpoints on the api router."""

    # -----------------------------------------------------------------
    # /nutrition/food/search — merges OFF (best-effort) + local fallback.
    # Replaces the older OFF-only endpoint that lived in the barcode file
    # by taking priority on the route via ``register()`` order.
    # -----------------------------------------------------------------
    @api.get("/nutrition/food-search")
    async def food_search_v2(
        q: str = Query(..., min_length=1),
        limit: int = Query(8, ge=1, le=20),
        user: dict = Depends(current_user),
    ):
        q = q.strip()
        if len(q) < 2:
            return {"results": [], "chips": QUICK_CHIPS}
        # First, always compute the local fallback so we can guarantee useful
        # results even if OFF times out.
        local = search_local(q, limit=limit)
        off: list[dict] = []
        try:
            import httpx  # noqa: WPS433
            url = (
                "https://world.openfoodfacts.org/cgi/search.pl?"
                f"search_terms={q}&search_simple=1&action=process&json=1&page_size={limit}"
            )
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.get(url, headers={"User-Agent": "CrewFit/1.0 (louis@crewfit.net)"})
                if r.status_code == 200:
                    products = ((r.json() or {}).get("products") or [])[:limit]
                    for p in products:
                        n = p.get("nutriments") or {}
                        name = (p.get("product_name") or "").strip()
                        if not name:
                            continue
                        kcal = _round(n.get("energy-kcal_100g") or n.get("energy-kcal_serving"))
                        if kcal is None:
                            continue  # skip rows with no macros
                        off.append({
                            "id": f"off-{p.get('code') or name.lower().replace(' ', '-')}",
                            "source": "off",
                            "name": name,
                            "brand": (p.get("brands") or "").split(",")[0].strip() or None,
                            "image_url": p.get("image_front_small_url") or p.get("image_thumb_url"),
                            "calories": kcal,
                            "protein_g": _round(n.get("proteins_100g") or n.get("proteins_serving")),
                            "carbs_g": _round(n.get("carbohydrates_100g") or n.get("carbohydrates_serving")),
                            "fats_g": _round(n.get("fat_100g") or n.get("fat_serving")),
                            "serving_size": "100g",
                            "per_100g": True,
                        })
        except Exception:
            logger.warning("food_search: OFF unavailable, using local fallback only")

        # Merge — put local best-matches first (they're curated), then OFF.
        merged: list[dict] = local + [x for x in off if x["name"].lower() not in {r["name"].lower() for r in local}]
        return {"results": merged[:limit * 2], "chips": QUICK_CHIPS}

    # -----------------------------------------------------------------
    # /nutrition/food/recent — recent user logs, de-duped.
    # -----------------------------------------------------------------
    @api.get("/nutrition/food-recent")
    async def food_recent(limit: int = 8, user: dict = Depends(current_user)):
        limit = max(1, min(20, limit))
        rows = await db.nutrition_logs.find(
            {"user_id": user["id"]}, {"_id": 0}
        ).sort("created_at", -1).to_list(80)
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            key = (r.get("food_name") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({
                "food_name": r.get("food_name"),
                "meal_type": r.get("meal_type") or "snack",
                "calories": r.get("calories") or 0,
                "protein_g": r.get("protein_g") or 0,
                "carbs_g": r.get("carbs_g") or 0,
                "fats_g": r.get("fats_g") or 0,
                "portion": r.get("portion"),
                "source": r.get("source"),
            })
            if len(out) >= limit:
                break
        return {"results": out}

    # -----------------------------------------------------------------
    # /nutrition/food/estimate — Atlas fallback via Emergent LLM.
    # -----------------------------------------------------------------
    @api.post("/nutrition/food-estimate")
    async def food_estimate(payload: dict, user: dict = Depends(current_user)):
        description = (payload or {}).get("description", "").strip()
        if len(description) < 3:
            raise HTTPException(400, "Provide a short description of the food.")
        if not emergent_llm_key:
            # Best-effort local heuristic so beta doesn't dead-end if the key is missing.
            local = search_local(description, limit=1)
            if local:
                out = local[0].copy()
                out["estimated"] = True
                out["source"] = "atlas-local"
                out["explanation"] = "Matched to a similar item in the local database. Please verify."
                return out
            return {
                "name": description[:60],
                "brand": None,
                "calories": 350, "protein_g": 20, "carbs_g": 35, "fats_g": 12,
                "serving_size": "1 serving",
                "per_100g": False,
                "estimated": True,
                "source": "atlas-placeholder",
                "explanation": "Rough placeholder. Please edit macros to match the actual food.",
            }
        # Call Claude via emergentintegrations (already installed in the env).
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            chat = LlmChat(
                api_key=emergent_llm_key,
                session_id=f"food-est-{user['id']}",
                system_message=(
                    "You estimate calories and macros for a single food/meal from a short description. "
                    "Return STRICT JSON with keys: name, calories, protein_g, carbs_g, fats_g, "
                    "serving_size (short human string like '1 sandwich' or '150g'), notes (one sentence). "
                    "Never diagnose, never mention brand names you can't verify. "
                    "Values must be integers (calories) or 1-decimal floats (macros). "
                    "Assume a typical adult portion unless the description specifies otherwise."
                ),
            ).with_model("anthropic", "claude-sonnet-4-5-20250929").with_params(max_tokens=400)
            reply = await chat.send_message(UserMessage(text=f"Estimate for: {description}"))
            text = (reply or "").strip()
            # Extract JSON from any wrapping.
            m = re.search(r"\{[\s\S]*\}", text)
            data = json.loads(m.group(0)) if m else {}
        except Exception as e:
            logger.warning("food_estimate atlas failed: %s", e)
            data = {}
        out = {
            "name": (data.get("name") or description)[:80],
            "brand": None,
            "calories": int(data.get("calories") or 0) or 350,
            "protein_g": float(data.get("protein_g") or 0) or 20,
            "carbs_g": float(data.get("carbs_g") or 0) or 30,
            "fats_g": float(data.get("fats_g") or 0) or 12,
            "serving_size": data.get("serving_size") or "1 serving",
            "per_100g": False,
            "estimated": True,
            "source": "atlas",
            "explanation": data.get("notes") or "This is an estimate. Adjust if needed.",
        }
        # Cheap usage record so the telemetry dashboard can see it.
        try:
            await db.ai_usage.insert_one({
                "user_id": user["id"],
                "feature": "food_estimate",
                "date": (payload.get("_today") or ""),
                "tokens_estimate": 400,
                "created_at": _iso_now(),
            })
        except Exception:
            pass
        return out

    logger.info("feature_food_search: registered (search+recent+estimate, %d local rows)", len(_LOCAL_FOODS))


def _round(v):
    try:
        if v is None: return None
        return round(float(v), 1)
    except Exception:
        return None


def _iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
