"""feature_nutrition_barcode — Barcode + food-database lookup (Phase 2).

Provider abstraction so we can add Nutritionix / FatSecret / Edamam later
without touching call-sites:
    ProviderResult(source, name, brand, image, calories, protein_g, carbs_g,
                   fats_g, serving_size_g, serving_size_text, ingredients, raw)

Currently ships with Open Food Facts (free, no API key required) and a
placeholder Nutritionix hook (returns None until keys are provided).

Barcode lookups are cached in `barcode_cache` for 30 days to avoid burning the
provider and to keep offline scans instantaneous.
"""
from __future__ import annotations

import os
import asyncio
import datetime as _dt
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import (
    api, db, current_user, new_id, now_iso, logger,
)

# ---------------------------------------------------------------------------
# Provider result contract
# ---------------------------------------------------------------------------

class ProviderResult(dict):
    """Thin dict wrapper for provider results."""
    @classmethod
    def make(cls, *, source: str, name: str, brand: Optional[str] = None,
             image_url: Optional[str] = None,
             calories: Optional[float] = None,
             protein_g: Optional[float] = None,
             carbs_g: Optional[float] = None,
             fats_g: Optional[float] = None,
             serving_size_g: Optional[float] = None,
             serving_size_text: Optional[str] = None,
             ingredients: Optional[str] = None,
             raw: Optional[dict] = None) -> "ProviderResult":
        return cls({
            "source": source,
            "name": name,
            "brand": brand,
            "image_url": image_url,
            "calories": _round(calories),
            "protein_g": _round(protein_g),
            "carbs_g": _round(carbs_g),
            "fats_g": _round(fats_g),
            "serving_size_g": _round(serving_size_g),
            "serving_size_text": serving_size_text,
            "ingredients": ingredients,
            "raw": raw,
        })


def _round(v: Optional[float]) -> Optional[float]:
    if v is None: return None
    try:
        f = float(v)
        return round(f, 1)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Provider: Open Food Facts (free)
# ---------------------------------------------------------------------------

OFF_ENDPOINT = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_TIMEOUT_S = float(os.environ.get("OFF_TIMEOUT_S", "6"))
OFF_USER_AGENT = os.environ.get(
    "OFF_USER_AGENT",
    "CrewFit/1.0 (nutrition@crewfit.app)",
)


async def off_lookup(barcode: str) -> Optional[ProviderResult]:
    """Fetch a product from Open Food Facts. Returns None if not found or
    missing minimal nutrition data."""
    url = OFF_ENDPOINT.format(code=barcode)
    try:
        async with httpx.AsyncClient(timeout=OFF_TIMEOUT_S) as client:
            r = await client.get(url, headers={"User-Agent": OFF_USER_AGENT})
    except Exception as e:
        logger.warning("off_lookup network error for %s: %s", barcode, e)
        return None

    if r.status_code != 200:
        return None
    data = r.json() or {}
    if data.get("status") != 1:
        return None
    product = data.get("product") or {}
    name = (product.get("product_name") or product.get("generic_name") or "").strip()
    if not name:
        return None
    n = product.get("nutriments") or {}
    # Prefer per-serving values; fall back to per-100g.
    def pick(*keys: str) -> Optional[float]:
        for k in keys:
            v = n.get(k)
            if v is not None:
                try: return float(v)
                except Exception: pass
        return None

    calories = pick("energy-kcal_serving", "energy-kcal_100g", "energy_serving", "energy_100g")
    protein_g = pick("proteins_serving", "proteins_100g")
    carbs_g = pick("carbohydrates_serving", "carbohydrates_100g")
    fats_g = pick("fat_serving", "fat_100g")
    serving_size_g = None
    serving_size_text = (product.get("serving_size") or "").strip() or None
    ssq = product.get("serving_quantity")
    if ssq:
        try: serving_size_g = float(ssq)
        except Exception: pass

    return ProviderResult.make(
        source="open_food_facts",
        name=name,
        brand=(product.get("brands") or "").split(",")[0].strip() or None,
        image_url=product.get("image_front_url") or product.get("image_url"),
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fats_g=fats_g,
        serving_size_g=serving_size_g,
        serving_size_text=serving_size_text,
        ingredients=(product.get("ingredients_text_en") or product.get("ingredients_text") or None),
        raw=None,
    )


# ---------------------------------------------------------------------------
# Provider: Nutritionix (placeholder — plugs in when keys exist)
# ---------------------------------------------------------------------------

async def nutritionix_lookup(barcode: str) -> Optional[ProviderResult]:
    app_id = os.environ.get("NUTRITIONIX_APP_ID")
    app_key = os.environ.get("NUTRITIONIX_APP_KEY")
    if not app_id or not app_key:
        return None
    url = f"https://trackapi.nutritionix.com/v2/search/item?upc={barcode}"
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(url, headers={
                "x-app-id": app_id, "x-app-key": app_key,
            })
    except Exception as e:
        logger.warning("nutritionix_lookup network error: %s", e)
        return None
    if r.status_code != 200:
        return None
    data = r.json() or {}
    foods = data.get("foods") or []
    if not foods:
        return None
    f = foods[0]
    return ProviderResult.make(
        source="nutritionix",
        name=f.get("food_name") or "Product",
        brand=f.get("brand_name"),
        image_url=(f.get("photo") or {}).get("highres"),
        calories=f.get("nf_calories"),
        protein_g=f.get("nf_protein"),
        carbs_g=f.get("nf_total_carbohydrate"),
        fats_g=f.get("nf_total_fat"),
        serving_size_g=f.get("serving_weight_grams"),
        serving_size_text=(f.get("serving_qty") and f.get("serving_unit"))
            and f"{f.get('serving_qty')} {f.get('serving_unit')}" or None,
        ingredients=f.get("nf_ingredient_statement"),
    )


# Ordered list — first hit wins.
PROVIDERS = [
    ("nutritionix", nutritionix_lookup),   # will noop until keys are set
    ("open_food_facts", off_lookup),
]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_TTL_DAYS = 30


async def _cache_get(barcode: str) -> Optional[dict]:
    row = await db.barcode_cache.find_one({"barcode": barcode}, {"_id": 0})
    if not row:
        return None
    try:
        expires = _dt.datetime.fromisoformat(row.get("expires_at"))
        if expires < _dt.datetime.utcnow():
            return None
    except Exception:
        return None
    return row.get("product")


async def _cache_put(barcode: str, product: dict) -> None:
    expires = (_dt.datetime.utcnow() + _dt.timedelta(days=CACHE_TTL_DAYS)).isoformat()
    await db.barcode_cache.update_one(
        {"barcode": barcode},
        {"$set": {
            "barcode": barcode,
            "product": product,
            "cached_at": now_iso(),
            "expires_at": expires,
        }},
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _valid_barcode(code: str) -> bool:
    code = (code or "").strip()
    return code.isdigit() and 6 <= len(code) <= 14


@api.get("/nutrition/barcode/lookup")
async def barcode_lookup(code: str, user: dict = Depends(current_user)):
    """Look up a barcode via cache → Nutritionix → Open Food Facts.

    Returns:
        { "found": bool, "barcode": str, "product": ProviderResult|null,
          "source": str|null, "cached": bool }
    """
    code = (code or "").strip()
    if not _valid_barcode(code):
        raise HTTPException(400, "invalid barcode")

    cached = await _cache_get(code)
    if cached:
        return {"found": True, "barcode": code, "product": cached,
                "source": cached.get("source"), "cached": True}

    for _name, fn in PROVIDERS:
        try:
            result = await fn(code)
        except Exception:
            logger.exception("provider %s failed", _name)
            continue
        if result:
            await _cache_put(code, dict(result))
            return {"found": True, "barcode": code, "product": dict(result),
                    "source": result["source"], "cached": False}

    # Not found — cache the negative result briefly (1 day) to avoid re-hitting.
    await db.barcode_cache.update_one(
        {"barcode": code},
        {"$set": {
            "barcode": code, "product": None,
            "cached_at": now_iso(),
            "expires_at": (_dt.datetime.utcnow() + _dt.timedelta(days=1)).isoformat(),
        }},
        upsert=True,
    )
    return {"found": False, "barcode": code, "product": None,
            "source": None, "cached": False}


# ---------------------------------------------------------------------------
# Log-from-barcode helper (adjusts by servings, writes to nutrition_logs)
# ---------------------------------------------------------------------------

class BarcodeLogIn(BaseModel):
    barcode: str
    servings: float = 1.0
    meal_type: str = "snack"
    roster_context: Optional[str] = None
    location_context: Optional[str] = None
    notes: Optional[str] = None
    save_as_favourite: bool = False


@api.post("/nutrition/logs/from-barcode")
async def log_from_barcode(body: BarcodeLogIn, user: dict = Depends(current_user)):
    if not _valid_barcode(body.barcode):
        raise HTTPException(400, "invalid barcode")
    if body.servings <= 0 or body.servings > 20:
        raise HTTPException(400, "invalid servings")

    # Look up product (cache-first, same path as /barcode/lookup)
    product = await _cache_get(body.barcode)
    if not product:
        for _name, fn in PROVIDERS:
            try:
                r = await fn(body.barcode)
            except Exception:
                continue
            if r:
                product = dict(r)
                await _cache_put(body.barcode, product)
                break
    if not product:
        raise HTTPException(404, "product not found")

    mult = float(body.servings)
    kcal = int(round(float(product.get("calories") or 0) * mult))
    pro = round(float(product.get("protein_g") or 0) * mult, 1)
    carb = round(float(product.get("carbs_g") or 0) * mult, 1)
    fat = round(float(product.get("fats_g") or 0) * mult, 1)

    from feature_nutrition import _today_iso, MEAL_TYPES, ROSTER_CONTEXTS
    meal_type = body.meal_type if body.meal_type in MEAL_TYPES else "snack"
    roster = body.roster_context if body.roster_context in ROSTER_CONTEXTS else None

    now = now_iso()
    doc = {
        "id": new_id(), "user_id": user["id"], "date_local": _today_iso(),
        "meal_type": meal_type,
        "food_name": product.get("name") or "Scanned product",
        "calories": kcal, "protein_g": pro, "carbs_g": carb, "fats_g": fat,
        "portion": (f"{mult}x " + (product.get("serving_size_text") or "serving")).strip(),
        "notes": body.notes,
        "source": "barcode",
        "barcode": body.barcode,
        "location_context": body.location_context,
        "roster_context": roster,
        "photo_url": product.get("image_url"),
        "brand": product.get("brand"),
        "created_at": now, "updated_at": now,
    }
    await db.nutrition_logs.insert_one(doc)

    if body.save_as_favourite:
        await db.nutrition_favourites.insert_one({
            "id": new_id(), "user_id": user["id"],
            "name": doc["food_name"],
            "meal_type": meal_type,
            "calories": kcal, "protein_g": pro, "carbs_g": carb, "fats_g": fat,
            "portion": doc["portion"],
            "barcode": body.barcode,
            "created_at": now,
        })

    doc.pop("_id", None)
    return {"log": doc, "product": product}


# ---------------------------------------------------------------------------
# Search (name-based) — useful for manual "not found" fallback (Phase 2.1)
# ---------------------------------------------------------------------------

@api.get("/nutrition/food/search")
async def food_search(q: str, limit: int = 8, user: dict = Depends(current_user)):
    """Free-text search for foods using Open Food Facts search endpoint.

    Note: OFF's free search is not perfect, but it's a good starting point.
    """
    q = (q or "").strip()
    if len(q) < 2:
        return {"results": []}
    limit = max(1, min(20, int(limit)))
    url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={q}&search_simple=1&action=process&json=1&page_size={limit}"
    try:
        async with httpx.AsyncClient(timeout=OFF_TIMEOUT_S) as client:
            r = await client.get(url, headers={"User-Agent": OFF_USER_AGENT})
    except Exception:
        return {"results": []}
    if r.status_code != 200:
        return {"results": []}
    products = ((r.json() or {}).get("products") or [])[:limit]
    out: list[dict] = []
    for p in products:
        n = p.get("nutriments") or {}
        name = (p.get("product_name") or "").strip()
        if not name:
            continue
        out.append({
            "code": p.get("code"),
            "name": name,
            "brand": (p.get("brands") or "").split(",")[0].strip() or None,
            "image_url": p.get("image_front_small_url") or p.get("image_thumb_url"),
            "calories": _round(n.get("energy-kcal_100g") or n.get("energy-kcal_serving")),
            "protein_g": _round(n.get("proteins_100g") or n.get("proteins_serving")),
            "carbs_g": _round(n.get("carbohydrates_100g") or n.get("carbohydrates_serving")),
            "fats_g": _round(n.get("fat_100g") or n.get("fat_serving")),
        })
    return {"results": out}
