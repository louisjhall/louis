"""Iter200 · On-Demand bulk-import runner.

Reads a JSON file (or a URL) that contains 100 workout envelopes and
POSTs them to the bulk-import endpoint in order.

Usage
-----
    # from a local JSON file
    python scripts/run_import.py --source /path/to/crewfit_100_workouts.import.json

    # from a URL (e.g. artifact bucket)
    python scripts/run_import.py --source https://…/crewfit_100_workouts.import.json

Input shape (loose — the runner fills defaults):
    {"items": [
        {
          "external_ref":  "W-001",           # optional; auto-derived from position if absent
          "title":         "Full-Body Hotel Gym — 20 Min",
          "description":   "…",
          "workout_type":  "strength",        # defaults to "other"
          "duration_min":  20,                # auto-summed from blocks if absent
          "location":      "hotel",
          "equipment":     ["dumbbells","bench"],
          "category":      "Strength & Gym", # any of the 8 canonical names
          "warmup":        [...],
          "exercises":     [...],            # discriminated Single/Group blocks
          "cooldown":      [...],
        },
        ...
    ]}

Behaviour
---------
  1. Ensures the 8 canonical categories exist (creates missing).
  2. Auto-derives `thumbnail_filename` = `w-001.jpg` … `w-100.jpg`
     using PDF order (position in the array).
  3. Fills in `duration_min` by summing block times when absent.
  4. Defaults `workout_type` to `"other"` when absent.
  5. Wraps every workout as the on-demand `workout_json` payload the
     Guided Flow expects (envelope compatible with
     `feature_programme_import.py :: WorkoutEnvelopeItem`).
  6. Calls `POST /api/on-demand/coach/items/bulk` and prints the
     `created / skipped / errors` report.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv


# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #

CANONICAL_CATEGORIES = [
    "Strength & Gym",
    "Hotel Room",
    "Aviation Mobility",
    "Core & Posture",
    "Cardio & Running",
    "Recovery & Low Energy",
    "Layover & Travel",
    "Pain Relief & Injury Support",
]

# Loose alias table so the JSON can use variants and we still land on
# a canonical bucket. Everything is lower-cased for the compare.
CATEGORY_ALIASES = {
    "strength & gym": "Strength & Gym",
    "strength": "Strength & Gym",
    "gym": "Strength & Gym",
    "hotel room": "Hotel Room",
    "hotel room & small space": "Hotel Room",
    "hotel": "Hotel Room",
    "aviation mobility": "Aviation Mobility",
    "mobility": "Aviation Mobility",
    "core & posture": "Core & Posture",
    "core": "Core & Posture",
    "posture": "Core & Posture",
    "cardio & running": "Cardio & Running",
    "cardio": "Cardio & Running",
    "running": "Cardio & Running",
    "recovery & low energy": "Recovery & Low Energy",
    "recovery": "Recovery & Low Energy",
    "low energy": "Recovery & Low Energy",
    "layover & travel": "Layover & Travel",
    "layover": "Layover & Travel",
    "travel": "Layover & Travel",
    "pain relief & injury support": "Pain Relief & Injury Support",
    "pain relief": "Pain Relief & Injury Support",
    "injury support": "Pain Relief & Injury Support",
}

ALLOWED_WORKOUT_TYPES = {"strength", "run", "cardio", "mobility", "recovery", "other"}


def slugify(text: str) -> str:
    """Mirror of the backend's `_slugify` — kebab-case, alnum only."""
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s or "untagged"


def canonicalise_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    key = raw.strip().lower()
    return CATEGORY_ALIASES.get(key)


def infer_duration_seconds(workout: dict) -> Optional[int]:
    """Sum every timed component. Returns seconds (not minutes).

    Rules (approximate — this is a fallback for entries that ship
    without `duration_min`):
      * `duration_sec` accumulates verbatim
      * `reps × 3 s` for rep-based exercises
      * `rest_sec` and `rest_between_rounds_sec × rounds` add to the
        block time
      * Groups multiply by their `rounds` count
    """
    def block_seconds(items: list[dict], mult: int = 1) -> int:
        total = 0
        for it in items or []:
            if it.get("kind") == "group":
                inner = 0
                for m in it.get("items", []) or []:
                    if m.get("duration_sec"):
                        inner += int(m["duration_sec"])
                    elif m.get("reps"):
                        try:
                            reps = int(str(m["reps"]).split("-")[0].split("/")[0])
                            inner += reps * 3
                        except Exception:
                            inner += 30
                    inner += int(m.get("rest_sec") or 0)
                rounds = int(it.get("rounds") or 1)
                rest_r = int(it.get("rest_between_rounds_sec") or 0)
                total += inner * rounds + rest_r * max(0, rounds - 1)
            else:
                if it.get("duration_sec"):
                    total += int(it["duration_sec"])
                elif it.get("reps"):
                    try:
                        reps = int(str(it["reps"]).split("-")[0].split("/")[0])
                        total += reps * 3
                    except Exception:
                        total += 30
                sets = int(it.get("sets") or 1)
                total += (total * 0)  # noqa — sets multiply below
                if sets > 1 and it.get("duration_sec"):
                    total = int(total + int(it["duration_sec"]) * (sets - 1))
                total += int(it.get("rest_sec") or 0) * max(0, sets - 1)
        return total * mult

    total = 0
    total += block_seconds(workout.get("warmup") or [])
    total += block_seconds(workout.get("exercises") or [])
    total += block_seconds(workout.get("cooldown") or [])
    return total or None


def wrap_as_workout_json(raw: dict) -> dict:
    """The bulk endpoint stores `workout_json` verbatim. The Guided
    Flow re-uses the `WorkoutEnvelopeItem`-style envelope, so this is
    just a light normaliser — it enforces the required keys and drops
    stray fields the schema doesn't know about.
    """
    envelope = {
        "date": raw.get("date") or "",           # not used by on-demand hydration
        "title": raw.get("title") or "",
        "workout_type": (raw.get("workout_type") or "other").strip().lower(),
        "duration_min": raw.get("duration_min"),
        "location": raw.get("location"),
        "equipment_context": raw.get("equipment_context") or (
            ", ".join(raw.get("equipment") or []) if isinstance(raw.get("equipment"), list) else raw.get("equipment")
        ),
        "rpe": raw.get("rpe"),
        "coach_notes": raw.get("coach_notes") or raw.get("notes"),
        "warmup": raw.get("warmup") or [],
        "exercises": raw.get("exercises") or [],
        "cooldown": raw.get("cooldown") or [],
        "external_ref": raw.get("external_ref"),
    }
    if envelope["workout_type"] not in ALLOWED_WORKOUT_TYPES:
        envelope["workout_type"] = "other"
    return envelope


def normalise_input(raw_items: list[dict]) -> list[dict]:
    """Convert raw PDF-JSON rows into the shape the bulk endpoint wants.

    Returns items in the same order — the caller relies on 1-indexed
    position to derive thumbnail filenames.
    """
    out: list[dict] = []
    for idx, raw in enumerate(raw_items, start=1):
        # (a) External ref — prefer provided, otherwise derive from position.
        ext_ref = (raw.get("external_ref") or f"W-{idx:03d}").strip()

        # (b) Thumbnail filename — always position-based, w-001…w-100.
        thumb = raw.get("thumbnail_filename") or f"w-{idx:03d}.jpg"

        # (c) Category → slug. Canonicalise via alias table.
        cat_name = canonicalise_category(raw.get("category")) or None
        cat_slug = slugify(cat_name) if cat_name else None

        # (d) Duration — prefer explicit duration_min; else compute; else None.
        dur_sec: Optional[int]
        if raw.get("duration_min"):
            dur_sec = int(raw["duration_min"]) * 60
        elif raw.get("duration_seconds"):
            dur_sec = int(raw["duration_seconds"])
        else:
            dur_sec = infer_duration_seconds(raw)

        # (e) Equipment — normalised list of strings.
        eq = raw.get("equipment")
        if isinstance(eq, str):
            equipment = [t.strip() for t in eq.split(",") if t.strip()]
        elif isinstance(eq, list):
            equipment = [str(t).strip() for t in eq if str(t).strip()]
        else:
            equipment = []

        # (f) Tag slugs — anything the JSON already ships as tags[]
        tag_slugs_raw = raw.get("tag_slugs") or raw.get("tags") or []
        if isinstance(tag_slugs_raw, str):
            tag_slugs_raw = [t.strip() for t in tag_slugs_raw.split(",") if t.strip()]
        tag_slugs = [slugify(t) for t in tag_slugs_raw if t and str(t).strip()]

        out.append({
            "external_ref": ext_ref,
            "title": (raw.get("title") or f"Workout {idx}").strip(),
            "description": (raw.get("description") or "").strip(),
            "category_slug": cat_slug,
            "tag_slugs": tag_slugs,
            "duration_seconds": dur_sec,
            "workout_json": wrap_as_workout_json(raw),
            "thumbnail_filename": thumb,
            "published": bool(raw.get("published")),
            "equipment": equipment,
        })
    return out


# --------------------------------------------------------------------------- #
# HTTP client                                                                 #
# --------------------------------------------------------------------------- #

async def _login_as_coach(client: httpx.AsyncClient, api_base: str) -> str:
    """Login using SEED_LOUIS_PASSWORD (or default) and return a JWT."""
    email = os.getenv("SEED_LOUIS_EMAIL", "louis@crewfit.net")
    pw = os.getenv("SEED_LOUIS_PASSWORD", "Louis123!")
    r = await client.post(f"{api_base}/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    data = r.json()
    tok = data.get("token") or data.get("access_token") or data.get("jwt")
    if not tok:
        raise RuntimeError(f"login response missing token: {list(data.keys())}")
    return tok


async def _load_input(source: str) -> list[dict]:
    if source.lower().startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(source)
            r.raise_for_status()
            data = r.json()
    else:
        p = Path(source).expanduser().resolve()
        data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    if isinstance(data, list):
        return data
    raise RuntimeError("input must be a JSON array or {items:[...]}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Path or URL to the workouts JSON file.")
    ap.add_argument("--api-base", default=os.getenv("IMPORT_API_BASE", "http://localhost:8001/api"),
                    help="Backend API base (default: http://localhost:8001/api).")
    ap.add_argument("--publish", action="store_true",
                    help="Publish every item immediately. Default = import as DRAFT.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Normalise + print summary without POSTing to the API.")
    args = ap.parse_args()

    load_dotenv()

    raw = await _load_input(args.source)
    print(f"→ loaded {len(raw)} workouts from {args.source}")

    items = normalise_input(raw)
    print(f"→ normalised {len(items)} rows (thumbnails w-001.jpg .. w-{len(items):03d}.jpg)")

    if args.dry_run:
        print(json.dumps({
            "would_post": len(items),
            "first_row_preview": items[0] if items else None,
        }, indent=2, default=str))
        return 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        token = await _login_as_coach(client, args.api_base)
        h = {"Authorization": f"Bearer {token}"}

        # 1) Ensure the 8 canonical categories exist.
        r = await client.post(
            f"{args.api_base}/on-demand/coach/taxonomy/ensure",
            headers=h,
            json={"categories": CANONICAL_CATEGORIES, "tags": []},
        )
        r.raise_for_status()
        tax = r.json()
        created_slugs = tax.get("created", {}).get("categories", [])
        print(f"→ taxonomy ensured. {len(tax.get('categories', []))} total categories in DB "
              f"({len(created_slugs)} newly created: {created_slugs or 'none'})")

        # 2) Ensure all referenced tag slugs exist (idempotent).
        tag_slugs = sorted({s for it in items for s in (it.get("tag_slugs") or [])})
        if tag_slugs:
            r = await client.post(
                f"{args.api_base}/on-demand/coach/taxonomy/ensure",
                headers=h,
                json={"categories": [], "tags": tag_slugs},
            )
            r.raise_for_status()
            print(f"→ tag taxonomy ensured ({len(tag_slugs)} incoming, "
                  f"{len(r.json().get('created', {}).get('tags', []))} newly created)")

        # 3) Bulk import.
        r = await client.post(
            f"{args.api_base}/on-demand/coach/items/bulk",
            headers=h,
            json={"items": items, "default_published": bool(args.publish)},
        )
        r.raise_for_status()
        report = r.json()
        s = report.get("summary", {})
        print("\n=== BULK IMPORT REPORT ===")
        print(f"  in       : {s.get('total_in')}")
        print(f"  created  : {s.get('created')}")
        print(f"  skipped  : {s.get('skipped')}")
        print(f"  errors   : {s.get('errors')}")
        mq = s.get("media_queue") or {}
        if mq:
            print(f"  media    : resolved={mq.get('resolved',0)} "
                  f"new_drafts={mq.get('drafts_created',0)} "
                  f"queued_missing_media={mq.get('queued_missing_media',0)}")
        if report.get("errors"):
            print("\n--- Errors ---")
            for e in report["errors"]:
                print(f"  [{e.get('index')}] {e.get('title')}: {e.get('reason')}")
        if report.get("skipped"):
            print("\n--- Skipped (duplicate external_ref) ---")
            for s2 in report["skipped"][:10]:
                print(f"  [{s2.get('index')}] {s2.get('external_ref')}: {s2.get('reason')}")
            if len(report["skipped"]) > 10:
                print(f"  ... and {len(report['skipped']) - 10} more")
        return 0 if not report.get("errors") else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
