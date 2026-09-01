"""Iter199 · Read-only diff report — old vs new roster classifications.

Rehydrates each stored `db.rosters` document's `days[]` JSON into the
parser's ``ParsedDay`` / ``Sector`` dataclasses, re-runs the new
``_post_process`` (with the ground-time gate) and prints a per-day diff
against the currently-persisted ``day_type`` / ``layover_city``.

**No DB writes — this is purely diagnostic.** The output is designed to
be eyeballed by the coach before we commit to backfilling the stored
day_types.

Usage:
    python /app/backend/scripts/diff_layover_reclassification.py
    python /app/backend/scripts/diff_layover_reclassification.py --user-id <id>
    python /app/backend/scripts/diff_layover_reclassification.py --limit 5

Exit code is always 0. Report goes to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_BACKEND_ROOT / ".env")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from parsers.etihad import ParsedDay, Sector, _post_process  # noqa: E402


def _rehydrate_days(raw_days: list[dict]) -> list[ParsedDay]:
    """Turn the stored JSON list back into `ParsedDay` objects.

    Only copies the fields `_post_process` actually reads — anything
    else stays whatever the dataclass default is.
    """
    out: list[ParsedDay] = []
    for r in raw_days or []:
        d = ParsedDay(date=r.get("date") or "")
        d.day_type = r.get("day_type") or "unknown"
        d.report_time = r.get("report_time")
        d.release_time = r.get("release_time")
        d.start_location = r.get("start_location")
        d.end_location = r.get("end_location")
        d.layover_city = r.get("layover_city")
        d.is_out_of_base = bool(r.get("is_out_of_base"))
        d.is_overnight = bool(r.get("is_overnight"))
        d.is_layover_day = bool(r.get("is_layover_day"))
        d.is_turnaround = bool(r.get("is_turnaround"))
        d.training_impact = r.get("training_impact") or "green"
        d.parse_confidence = float(r.get("parse_confidence") or 0.7)
        d.needs_client_review = bool(r.get("needs_client_review"))
        d.notes = list(r.get("notes") or [])
        d.warnings = list(r.get("warnings") or [])
        sectors: list[Sector] = []
        for s in r.get("sectors") or []:
            sec = Sector(
                flight_number=s.get("flight_number") or "",
                origin=s.get("origin"),
                destination=s.get("destination"),
                departure_time=s.get("departure_time"),
                arrival_time=s.get("arrival_time"),
                report_time=s.get("report_time"),
            )
            # Some rosters keep an explicit arrival_date on midnight-cross sectors.
            if "arrival_date" in s and s["arrival_date"]:
                setattr(sec, "arrival_date", s["arrival_date"])
            if "departure_date" in s and s["departure_date"]:
                setattr(sec, "departure_date", s["departure_date"])
            sectors.append(sec)
        d.sectors = sectors
        d.sector_count = len(sectors)
        out.append(d)
    return out


def _fmt(d: ParsedDay) -> str:
    return f"{d.day_type:<28} city={d.layover_city or '-':<5} impact={d.training_impact}"


async def run(user_id: str | None, limit: int | None) -> int:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME") or "test_database"
    if not mongo_url:
        print("ERROR: MONGO_URL not set", file=sys.stderr)
        return 2
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    q: dict = {}
    if user_id:
        q["user_id"] = user_id
    cursor = db.rosters.find(q, {"_id": 0}).sort("created_at", -1)
    if limit:
        cursor = cursor.limit(limit)
    rosters = await cursor.to_list(length=500)

    print(f"[diff] scanning {len(rosters)} roster documents "
          f"({'user='+user_id if user_id else 'all users'}, limit={limit or '∞'})\n")

    grand_totals = {
        "rosters_scanned": 0,
        "rosters_with_change": 0,
        "days_changed": 0,
        "would_flip_to_midnight_crossing": 0,
        "would_flip_to_short_turn": 0,
        "would_lose_layover_city": 0,
        "days_unchanged": 0,
    }

    for r in rosters:
        grand_totals["rosters_scanned"] += 1
        raw_days = r.get("days") or []
        if not raw_days:
            continue
        before = _rehydrate_days(raw_days)
        # Snapshot "before" strings BEFORE re-running the post-processor —
        # otherwise mutating the shared dataclasses would confuse the diff.
        before_snap = [(d.day_type, d.layover_city, d.training_impact) for d in before]

        after = _post_process(_rehydrate_days(raw_days))

        row_changes = []
        for i, (old, d) in enumerate(zip(before_snap, after)):
            new = (d.day_type, d.layover_city, d.training_impact)
            if new != old:
                row_changes.append((i, old, new, d))

        if not row_changes:
            grand_totals["days_unchanged"] += len(before)
            continue

        grand_totals["rosters_with_change"] += 1
        header = (f"roster {r.get('id')}  user={r.get('user_id')}  "
                  f"airline={r.get('airline') or '?'}  "
                  f"{r.get('start_date') or '?'} → {r.get('end_date') or '?'}")
        print("=" * 88)
        print(header)
        print("-" * 88)
        for i, old, new, d in row_changes:
            grand_totals["days_changed"] += 1
            if new[0] == "midnight_crossing_flight" or new[0] == "midnight_crossing_return":
                grand_totals["would_flip_to_midnight_crossing"] += 1
            if new[0] == "short_turn":
                grand_totals["would_flip_to_short_turn"] += 1
            if old[1] and not new[1]:
                grand_totals["would_lose_layover_city"] += 1
            print(f"  {d.date}   OLD: {old[0]:<28} city={old[1] or '-':<5} impact={old[2]}")
            print(f"              NEW: {new[0]:<28} city={new[1] or '-':<5} impact={new[2]}")
        grand_totals["days_unchanged"] += len(before) - len(row_changes)
        print()

    print("\n" + "=" * 88)
    print("SUMMARY")
    print("=" * 88)
    for k, v in grand_totals.items():
        print(f"  {k:<40} {v}")
    print("\nNo DB writes performed. Re-run with `--limit N` or `--user-id ID` to narrow.")
    return 0


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user-id", type=str, default=None,
                    help="Only diff rosters for this user id")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap the number of rosters scanned")
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    rc = asyncio.run(run(args.user_id, args.limit))
    sys.exit(rc)
