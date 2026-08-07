"""
READ-ONLY duplicate audit for db.exercises_v2 — no writes, no LLM calls.

Prints:
  * total exercises count
  * status distribution
  * count of primary_video_url present (i.e. approved manual videos on library rows)
  * exact-normalised name duplicate groups
  * canonical-token (singularised) duplicate groups
  * near-duplicate groups (Jaccard on canonical tokens, threshold 0.75)
  * per-group flag: which member(s) already have media (primary_image_url / video)
  * estimated media-generation savings if duplicates collapsed
"""
import asyncio
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "/app/backend")
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "crewfit"

_WORD_RE = re.compile(r"[a-z0-9]+")

_PLURAL_KEEP = {
    "abs", "biceps", "triceps", "lats", "quads", "delts", "glutes",
    "kettlebells", "dumbbells", "aerobics", "gymnastics",
}
_EQUIP_TOKENS = {
    "kettlebell", "kettlebells", "dumbbell", "dumbbells", "barbell",
    "cable", "machine", "band", "bands", "trx", "smith",
}
_INTENSITY_TOKENS = {
    "easy", "hard", "moderate", "recovery", "tempo", "threshold",
    "sprint", "explosive", "slow", "fast",
}
_LOCOMOTION_FAMILIES = ({"walk", "walking"}, {"run", "running", "jog", "jogging"})
_SIDE_MARKERS = {"left", "right", "l", "r", "lh", "rh", "unilateral"}


def singularise(t: str) -> str:
    if not t or t in _PLURAL_KEEP or len(t) <= 2:
        return t
    if t.endswith("ies") and len(t) > 4: return t[:-3] + "y"
    if t.endswith("sses"): return t[:-2]
    if t.endswith(("ches", "shes", "xes")) and len(t) > 5: return t[:-2]
    if t.endswith("oes") and len(t) > 4: return t[:-2]
    if t.endswith("s") and not t.endswith("ss"): return t[:-1]
    return t


def canon_tokens(s):
    return tuple(singularise(t) for t in _WORD_RE.findall((s or "").lower()))


def norm(s):
    return " ".join(_WORD_RE.findall((s or "").lower()))


def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 0.0


async def main():
    print(f"Connecting to {MONGO_URL} / {DB_NAME}")
    cli = AsyncIOMotorClient(MONGO_URL)
    # Try to auto-detect DB by looking for exercises_v2
    db = cli[DB_NAME]
    count = await db.exercises_v2.count_documents({})
    if count == 0:
        # Detect the right DB
        for dbname in await cli.list_database_names():
            if dbname in ("admin", "local", "config"):
                continue
            c = await cli[dbname].exercises_v2.count_documents({})
            if c:
                db = cli[dbname]
                count = c
                print(f"Auto-selected DB: {dbname}")
                break

    print(f"\n=== TOTAL exercises_v2: {count} ===")
    if count == 0:
        print("No exercises found — nothing to audit.")
        return

    rows = await db.exercises_v2.find(
        {},
        {"_id": 0, "id": 1, "exercise_name": 1, "status": 1,
         "primary_image_url": 1, "primary_video_url": 1,
         "movement_pattern": 1, "equipment_type": 1,
         "safe_for_programming": 1, "visibility": 1,
         "content_status": 1, "request_count": 1,
         "created_at": 1},
    ).to_list(10000)

    # Status distribution
    status_dist = defaultdict(int)
    have_video = 0
    have_image = 0
    for r in rows:
        status_dist[str(r.get("status") or "?")] += 1
        if r.get("primary_video_url"):
            have_video += 1
        if r.get("primary_image_url"):
            have_image += 1
    print("\n--- Status distribution ---")
    for k, v in sorted(status_dist.items(), key=lambda x: -x[1]):
        print(f"  {k:30s}  {v}")
    print(f"\nRows with primary_image_url: {have_image}")
    print(f"Rows with primary_video_url: {have_video}")

    # Exact normalised name duplicates
    by_norm = defaultdict(list)
    for r in rows:
        by_norm[norm(r.get("exercise_name"))].append(r)
    exact_dupes = {k: v for k, v in by_norm.items() if len(v) > 1 and k}
    print(f"\n=== A. EXACT normalised-name duplicate groups: {len(exact_dupes)} ===")
    exact_dupe_row_count = sum(len(v) for v in exact_dupes.values())
    print(f"Rows involved: {exact_dupe_row_count} (would reduce to {len(exact_dupes)})")
    for k, group in sorted(exact_dupes.items())[:20]:
        print(f"\n  [{k}]  ({len(group)} rows)")
        for m in group:
            media = []
            if m.get("primary_image_url"): media.append("IMG")
            if m.get("primary_video_url"): media.append("VID")
            print(f"    - {m.get('exercise_name'):40s}  status={str(m.get('status')):20s}  media={','.join(media) or 'none':10s}  id={m.get('id')}")

    # Canonical-token duplicates (singularised)
    by_canon = defaultdict(list)
    for r in rows:
        c = canon_tokens(r.get("exercise_name"))
        by_canon[c].append(r)
    canon_dupes = {k: v for k, v in by_canon.items() if len(v) > 1 and k}
    # Remove any already-covered by exact_dupes
    canon_new = {}
    for k, v in canon_dupes.items():
        # If all in same norm bucket already reported, skip
        norms_in_group = set(norm(m.get("exercise_name")) for m in v)
        if len(norms_in_group) > 1:
            canon_new[k] = v
    print(f"\n=== B. CANONICAL-TOKEN (singular/plural, capitalisation) duplicate groups: {len(canon_new)} ===")
    canon_row_count = sum(len(v) for v in canon_new.values())
    print(f"Rows involved (beyond exact matches): {canon_row_count} (would reduce to {len(canon_new)})")
    for k, group in list(canon_new.items())[:20]:
        print(f"\n  [{' '.join(k)}]  ({len(group)} rows)")
        for m in group:
            media = []
            if m.get("primary_image_url"): media.append("IMG")
            if m.get("primary_video_url"): media.append("VID")
            print(f"    - {m.get('exercise_name'):40s}  status={str(m.get('status')):20s}  media={','.join(media) or 'none':10s}  id={m.get('id')}")

    # Near-duplicates via Jaccard on canonical tokens (threshold 0.6 — LOOSE for audit)
    # But respect the resolver's disqualifiers (side, equipment, intensity, locomotion).
    print("\n=== C. NEAR-DUPLICATE candidate groups (Jaccard 0.60+ on canonical tokens, respecting side/equipment/intensity/locomotion guards) ===")
    seen_ids = set()
    groups = []
    for i, a in enumerate(rows):
        if a.get("id") in seen_ids:
            continue
        a_can = set(canon_tokens(a.get("exercise_name")))
        a_tok = set(_WORD_RE.findall((a.get("exercise_name") or "").lower()))
        if not a_can:
            continue
        a_side = a_tok & _SIDE_MARKERS
        a_eq = a_tok & _EQUIP_TOKENS
        a_int = a_tok & _INTENSITY_TOKENS
        a_fam = None
        for fam in _LOCOMOTION_FAMILIES:
            if a_tok & fam:
                a_fam = frozenset(fam); break

        cluster = [a]
        for b in rows[i+1:]:
            if b.get("id") in seen_ids:
                continue
            b_can = set(canon_tokens(b.get("exercise_name")))
            b_tok = set(_WORD_RE.findall((b.get("exercise_name") or "").lower()))
            b_side = b_tok & _SIDE_MARKERS
            b_eq = b_tok & _EQUIP_TOKENS
            b_int = b_tok & _INTENSITY_TOKENS
            b_fam = None
            for fam in _LOCOMOTION_FAMILIES:
                if b_tok & fam:
                    b_fam = frozenset(fam); break
            # Disqualifiers
            if (bool(a_side) ^ bool(b_side)) or (a_side and b_side and a_side != b_side):
                continue
            if bool(a_eq) ^ bool(b_eq) or (a_eq and b_eq and a_eq != b_eq):
                continue
            if bool(a_int) ^ bool(b_int) or (a_int and b_int and a_int != b_int):
                continue
            if a_fam != b_fam:
                continue
            score = jaccard(a_can, b_can)
            if score >= 0.6 and a_can != b_can:
                cluster.append(b)
        if len(cluster) > 1:
            for m in cluster:
                seen_ids.add(m.get("id"))
            groups.append(cluster)
    # Filter: don't report clusters where every row is already in an exact/canon dup group of size >1
    print(f"Near-dup clusters (Jaccard 0.60+): {len(groups)}")
    print(f"Rows in near-dup clusters: {sum(len(g) for g in groups)}")
    for g in groups[:20]:
        print(f"\n  ({len(g)} rows)")
        for m in g:
            media = []
            if m.get("primary_image_url"): media.append("IMG")
            if m.get("primary_video_url"): media.append("VID")
            print(f"    - {m.get('exercise_name'):45s}  status={str(m.get('status')):20s}  media={','.join(media) or 'none':10s}  id={m.get('id')}")

    # Compute unresolved rows (status draft_requested/coach_review_needed) that
    # are duplicates of an approved sibling -> those trigger avoidable auto-media.
    approved_map = {}
    for r in rows:
        if (r.get("status") or "").lower() in ("approved", "live"):
            approved_map[canon_tokens(r.get("exercise_name"))] = r
    avoidable = []
    for r in rows:
        if (r.get("status") or "").lower() in ("draft_requested", "coach_review_needed", "artwork needed", "coaching points needed", "video needed", "needs review", "ready for approval", "needs update"):
            ct = canon_tokens(r.get("exercise_name"))
            if ct in approved_map and approved_map[ct]["id"] != r["id"]:
                avoidable.append((r, approved_map[ct]))
    print(f"\n=== D. AVOIDABLE MEDIA GENERATIONS ===")
    print(f"Draft/pending rows whose canonical name already has an APPROVED/LIVE sibling: {len(avoidable)}")
    for r, sib in avoidable[:15]:
        print(f"  - draft: {r.get('exercise_name'):40s}  status={r.get('status'):25s}   -> already approved: {sib.get('exercise_name')}")

    # Cost estimate: default auto_media enqueues primary image + coaching_points + common_mistakes + alternatives.
    # Approx per-exercise generation cost (rough): ~$0.04 Nano Banana image + ~$0.01 Claude coaching + $0.01 mistakes + $0.02 alternatives ≈ $0.08/new draft.
    print(f"\nApprox avoidable spend if fuzzy match had already caught these {len(avoidable)} drafts: ~${0.08 * len(avoidable):.2f} at default kinds.")

    # Calf raises specific check
    print("\n=== E. Calf-raise example (as user reported) ===")
    calf_rows = [r for r in rows if "calf" in (r.get("exercise_name") or "").lower()]
    for m in calf_rows:
        media = []
        if m.get("primary_image_url"): media.append("IMG")
        if m.get("primary_video_url"): media.append("VID")
        print(f"  - {m.get('exercise_name'):45s} status={str(m.get('status')):22s} media={','.join(media) or 'none':10s} id={m.get('id')}")

    cli.close()


asyncio.run(main())
