"""
One-off audit script — Flight Support session exercises missing from library.

Read-only. Makes NO writes to the database.

Steps:
  1. Query db.workouts for active client workouts with date >= today (UTC).
  2. Keep only sessions where the "type" is 'Flight Support'. We check
     every plausible field (title, focus, workout_type, event_phase,
     tags, category, type, session_type) case-insensitively. If the
     literal 'Flight Support' isn't found anywhere, fall back to any
     workout whose title matches 'flight' (Pre-/Post-Flight etc.) and
     report which criterion matched so the human reviewer can confirm.
  3. Collect every unique exercise NAME across warmup + exercises +
     cooldown of those sessions.
  4. Cross-reference each name against db.exercises_v2 by
       (a) exercise_id (if the workout row carries one), and
       (b) exact-name (case-insensitive), and
       (c) normalised requested_name (case + punctuation insensitive).
     A name that fails all three is reported as MISSING.
  5. Output ONLY the list of missing names.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timezone

import motor.motor_asyncio
from dotenv import load_dotenv

# Reuse the exact resolver name-normaliser so the audit matches the
# platform's own reuse-first behaviour.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")
try:
    from feature_v2_resolver import _normalise_name  # type: ignore
except Exception:  # very defensive — small fallback
    def _normalise_name(s: str | None) -> str:
        s = (s or "").lower().strip()
        return re.sub(r"[^a-z0-9]+", " ", s).strip()


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

FLIGHT_SUPPORT_LITERAL = "flight support"
FALLBACK_FLIGHT_TERM = "flight"          # umbrella broadening if literal is absent
CANDIDATE_FIELDS = (
    "title",
    "focus",
    "workout_type",
    "event_phase",
    "category",
    "type",
    "session_type",
    "kind",
)
ACTIVE_STATE_FIELDS_TO_EXCLUDE_IF_TRUE = ("deleted", "archived", "removed")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _iter_exercise_names(workout: dict) -> list[tuple[str, str | None]]:
    """Return (name, exercise_id-or-None) tuples for every drill in the workout."""
    out: list[tuple[str, str | None]] = []
    for section in ("warmup", "exercises", "cooldown"):
        for row in (workout.get(section) or []):
            if not isinstance(row, dict):
                continue
            nm = (row.get("name") or "").strip()
            if not nm:
                continue
            out.append((nm, row.get("exercise_id")))
    return out


def _matches_flight_support(workout: dict, mode: str) -> tuple[bool, str | None]:
    """`mode` = 'literal' (exact 'flight support') or 'umbrella' (contains 'flight').
    Returns (matched, matched_field)."""
    target = FLIGHT_SUPPORT_LITERAL if mode == "literal" else FALLBACK_FLIGHT_TERM
    for f in CANDIDATE_FIELDS:
        v = workout.get(f)
        if v is None:
            continue
        if isinstance(v, list):
            for it in v:
                if isinstance(it, str) and target in it.lower():
                    return True, f
            continue
        if isinstance(v, str) and target in v.lower():
            return True, f
    return False, None


async def _library_lookup_maps(db) -> tuple[set[str], set[str], set[str]]:
    """Load light index maps from db.exercises_v2 for fast local lookup:
       - set of ids
       - set of normalised exercise_names (both exercise_name + requested_name_norm)
    """
    ids: set[str] = set()
    names_norm: set[str] = set()

    cur = db.exercises_v2.find({}, {
        "_id": 0, "id": 1, "exercise_name": 1,
        "requested_name": 1, "requested_name_norm": 1,
    })
    async for row in cur:
        if row.get("id"):
            ids.add(row["id"])
        for k in ("exercise_name", "requested_name"):
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                names_norm.add(_normalise_name(v))
        rnn = row.get("requested_name_norm")
        if isinstance(rnn, str) and rnn.strip():
            names_norm.add(rnn.strip().lower())

    # Second copy of names_norm to mirror the app's two-column dedupe path.
    return ids, names_norm, names_norm


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

async def main() -> int:
    load_dotenv()
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Fetch candidate workouts. Date is stored as 'YYYY-MM-DD' string,
    # so a lexicographic >= comparison works.
    base_query: dict = {"date": {"$gte": today_iso}}
    # Exclude obvious inactive markers if present.
    for f in ACTIVE_STATE_FIELDS_TO_EXCLUDE_IF_TRUE:
        base_query[f] = {"$ne": True}

    projection = {
        "_id": 0, "id": 1, "user_id": 1, "date": 1,
        "title": 1, "focus": 1, "workout_type": 1, "event_phase": 1,
        "category": 1, "type": 1, "session_type": 1, "tags": 1, "kind": 1,
        "warmup": 1, "exercises": 1, "cooldown": 1,
        "source": 1, "completed": 1, "coach_locked": 1,
    }

    all_future = []
    async for w in db.workouts.find(base_query, projection):
        all_future.append(w)

    print(f"[info] scanned {len(all_future)} workouts on/after {today_iso} (UTC)")

    # 2. Filter to Flight Support.
    literal_hits: list[dict] = []
    umbrella_hits: list[dict] = []
    for w in all_future:
        ok, _ = _matches_flight_support(w, mode="literal")
        if ok:
            literal_hits.append(w)
        else:
            ok2, _ = _matches_flight_support(w, mode="umbrella")
            if ok2:
                umbrella_hits.append(w)

    if literal_hits:
        filtered = literal_hits
        criterion = "literal 'Flight Support' (case-insensitive)"
    elif umbrella_hits:
        filtered = umbrella_hits
        criterion = ("umbrella fallback — no workout carried the literal "
                     "'Flight Support'. Treated any workout with 'flight' in "
                     "its title/focus as flight-related.")
    else:
        filtered = []
        criterion = "no matches"

    print(f"[info] Flight Support filter: {len(filtered)} sessions "
          f"({len(literal_hits)} literal, {len(umbrella_hits)} umbrella)")
    print(f"[info] filter criterion used: {criterion}")

    if not filtered:
        print("\n[result] No Flight Support sessions found today or later. Nothing to audit.")
        return 0

    # Log a quick per-session summary so the human reviewer can sanity-check.
    print(f"\n[info] matched sessions (first 10 of {len(filtered)}):")
    for w in filtered[:10]:
        print(f"        {w['date']}  {str(w.get('title'))[:60]:60}  "
              f"focus={w.get('focus')!r:12}  workout_type={w.get('workout_type')!r}")

    # 3. Collect unique exercise names + ids.
    name_to_ids: dict[str, set[str | None]] = {}
    for w in filtered:
        for nm, xid in _iter_exercise_names(w):
            name_to_ids.setdefault(nm, set()).add(xid)

    unique_names = sorted(name_to_ids.keys(), key=lambda s: s.lower())
    print(f"\n[info] {len(unique_names)} unique exercise names across matched sessions")

    # 4. Build library index maps.
    lib_ids, lib_names_norm, _ = await _library_lookup_maps(db)
    print(f"[info] library index: {len(lib_ids)} ids, {len(lib_names_norm)} normalised names")

    # 5. Cross-reference. A name counts as PRESENT if any of:
    #    (a) its exercise_id (if any) exists in exercises_v2,
    #    (b) its normalised name matches a library exercise_name / requested_name.
    missing: list[str] = []
    present_via_id_only: list[str] = []
    for nm in unique_names:
        norm = _normalise_name(nm)
        ids = {i for i in (name_to_ids.get(nm) or set()) if i}
        id_hit = any(i in lib_ids for i in ids)
        name_hit = norm in lib_names_norm
        if not id_hit and not name_hit:
            missing.append(nm)
        elif id_hit and not name_hit:
            present_via_id_only.append(nm)

    print(f"[info] {len(missing)} names missing, {len(present_via_id_only)} matched by id only")

    # 6. Final output — names only, one per line.
    print("\n" + "=" * 60)
    print(f"MISSING EXERCISE NAMES ({len(missing)}) — no matching library record")
    print("=" * 60)
    for nm in missing:
        print(nm)

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
