"""Iter183 · YouTube exercise-demo finder.

Server-side search for short (≤ 60 s) exercise demo videos via the
YouTube Data API v3. Called from a background worker that iterates
exercises sequentially. Results are written to the exercise row's
`primary_video_url` field with `approved_video_status="Needs Review"` —
nothing is approved automatically.

Playbook via integration_playbook_expert_v2 (2026-08-18).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response

from server import api, db, require_role, new_id, now_iso  # noqa: E402

logger = logging.getLogger("crewfit.feature_youtube_video_finder")

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
BAD_CHANNEL_WORDS = ("podcast", "talk show", "interview", "vlog")
KNOWN_GOOD_CHANNELS = {
    "jeff nippard", "squat university", "renaissance periodization",
    "athlean-x", "athlean x", "built with science",
}

# Single-flight lock (mirrors bulk-primary-images pattern).
_YT_BULK_LOCK: asyncio.Lock = asyncio.Lock()

_DUR_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
)


def _iso_dur_seconds(value: str) -> int:
    m = _DUR_RE.fullmatch(value or "")
    if not m:
        return 999999
    p = {k: int(v or 0) for k, v in m.groupdict().items()}
    return p["days"] * 86400 + p["hours"] * 3600 + p["minutes"] * 60 + p["seconds"]


def _good_channel(name: str) -> bool:
    n = (name or "").casefold()
    return not any(w in n for w in BAD_CHANNEL_WORDS)


def _known_good_priority(name: str) -> int:
    n = (name or "").casefold()
    return int(any(k in n for k in KNOWN_GOOD_CHANNELS))


async def _yt_get(http: httpx.AsyncClient, url: str, params: dict) -> dict:
    resp = await http.get(url, params={**params, "key": YOUTUBE_API_KEY})
    if resp.is_success:
        return resp.json()
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    err = body.get("error") or {}
    errs = err.get("errors") or []
    reason = (errs[0].get("reason") if errs else "") or ""
    msg = err.get("message") or ""
    # Iter188 · Robust quota detection — Google's 429 body sometimes
    # omits `errors[].reason` and only carries `message`; also flag any
    # 429 as a quota signal regardless of reason. Detail always contains
    # the literal token "quota" so the worker can catch it upstream.
    if resp.status_code == 429 or "quota" in msg.lower() or "quota" in reason.lower():
        raise HTTPException(429, f"youtube_quota_exceeded reason={reason or 'rate_limit'} msg={msg[:120]}")
    raise HTTPException(resp.status_code, f"youtube_{reason or 'error'} msg={msg[:120]}")


async def find_best_short(
    exercise_name: str,
    loose: bool = False,
    *,
    debug: bool = False,
) -> Optional[dict]:
    """Return the highest-quality ≤ N s embeddable video for `exercise_name`
    or None.

    Iter189 · Filters REBALANCED per coach feedback ("finder found 2/400,
    filters too strict"). All candidates still go to Needs Review — coach
    manually approves — so we can afford to be permissive on the auto
    stage.

    Default mode (relaxed):
      * NO channel-name blocklist (podcast/talk/interview etc. still
        surface — coach can reject in review).
      * Duration cap raised 60 s → 120 s (still short-form).
      * Query = `"{name} exercise demo"` (adds the intent hint).
      * Rank by (known_good_channel, view_count) — reward reputable
        sources without hard-gating anyone else.

    Loose mode (diagnostic, `loose=true`):
      * Duration cap 180 s.
      * Query = raw name (broadest possible search).
      * No ranking heuristics beyond raw view count.

    `debug=True` returns a dict with `.rejections` breakdown instead of
    just the best match — used by the /health endpoint so the coach
    can see WHY a query returned 0.
    """
    if not YOUTUBE_API_KEY:
        raise HTTPException(500, "YOUTUBE_API_KEY not configured")
    name = " ".join((exercise_name or "").split()).strip()
    if not name:
        return None

    if loose:
        query = name
        max_dur = 180
    else:
        query = f"{name} exercise demo"
        max_dur = 120

    rejections = {
        "not_video_kind": 0,
        "too_long": 0,
        "not_embeddable": 0,
        "search_returned_zero": 0,
    }

    async with httpx.AsyncClient(timeout=15) as http:
        try:
            search = await _yt_get(http, SEARCH_URL, {
                "part": "snippet", "q": query, "type": "video",
                "videoDuration": "short", "videoEmbeddable": "true",
                "order": "relevance", "maxResults": 15,
            })
        except HTTPException as e:
            # Iter188 · Bubble quota errors UP so the worker pauses the
            # whole sweep instead of silently returning None for every
            # subsequent exercise.
            if "quota" in (e.detail or "").lower() or e.status_code == 429:
                raise
            logger.warning("yt search failed for %r: %s", exercise_name, e.detail)
            return None

        raw_items = search.get("items") or []
        if not raw_items:
            rejections["search_returned_zero"] = 1
            return {"rejections": rejections, "match": None, "query": query} if debug else None

        # Iter189 · NO channel-blocklist by default anymore.
        cands = [
            it for it in raw_items
            if (it.get("id") or {}).get("kind") == "youtube#video"
        ]
        rejections["not_video_kind"] = len(raw_items) - len(cands)
        ids = [it["id"]["videoId"] for it in cands if (it.get("id") or {}).get("videoId")]
        if not ids:
            return {"rejections": rejections, "match": None, "query": query} if debug else None

        details = await _yt_get(http, VIDEOS_URL, {
            "part": "contentDetails,snippet,statistics,status",
            "id": ",".join(ids),
        })

        eligible = []
        for it in (details.get("items") or []):
            dur = _iso_dur_seconds((it.get("contentDetails") or {}).get("duration") or "")
            if dur > max_dur:
                rejections["too_long"] += 1
                continue
            if not (it.get("status") or {}).get("embeddable"):
                rejections["not_embeddable"] += 1
                continue
            sn = it.get("snippet") or {}
            st = it.get("statistics") or {}
            views = int(st.get("viewCount") or 0)
            likes = int(st.get("likeCount") or 0)
            ratio = (likes / views) if views else 0.0
            eligible.append({
                "video_id": it["id"],
                "title": sn.get("title"),
                "channel_name": sn.get("channelTitle"),
                "channel_id": sn.get("channelId"),
                "thumbnail_url": ((sn.get("thumbnails") or {}).get("high") or {}).get("url"),
                "duration_seconds": dur,
                "view_count": views, "like_count": likes, "like_ratio": ratio,
                "url": f"https://www.youtube.com/watch?v={it['id']}",
                "shorts_url": f"https://www.youtube.com/shorts/{it['id']}",
            })
        if not eligible:
            return {"rejections": rejections, "match": None, "query": query} if debug else None
        if loose:
            best = max(eligible, key=lambda v: (_known_good_priority(v["channel_name"] or ""), v["view_count"]))
        else:
            # Iter189 · Ranking (not filtering!) — reward known-good
            # channels & popular videos but never hard-exclude.
            best = max(
                eligible,
                key=lambda v: (
                    _known_good_priority(v["channel_name"] or ""),
                    v["view_count"],
                    v["like_ratio"],
                ),
            )
        return {"rejections": rejections, "match": best, "query": query, "eligible_count": len(eligible)} if debug else best


async def _is_yt_enabled() -> bool:
    doc = await db.settings.find_one({"_id": "youtube_video_finder"})
    return bool((doc or {}).get("enabled"))


async def _record_yt_job(job_id: str, patch: dict) -> None:
    from datetime import datetime, timezone
    patch = {**patch, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.backfill_jobs.update_one({"_id": job_id}, {"$set": patch}, upsert=True)


def _bulk_yt_query(target: str = "library") -> dict:
    """Shared query for the YouTube video-finder bulk sweep.

    Iter189 · Tightened HARD after discovering the previous filter let
    ~943 rows through — 1,075 of which were `draft_requested` LLM
    fallback candidates (visibility=coach_only, safe_for_programming=
    False) never surfaced in the library UI. The sweep was burning
    quota on ghost rows.

    Iter189b · `target` parameter added for the coach's "sweep drafts
    too" flow. Draft candidates still get videos written; their status
    is NOT changed by the worker (only `primary_video_url`,
    `primary_video_source`, `primary_video_meta`, `approved_video_status`,
    `video_found_at` are set). Coach can review + approve manually.

    Targets:
      * "library" — Approved OR (client-visible + safe-for-programming).
                    Requires non-empty `exercise_name`.
      * "drafts"  — `status='draft_requested'` rows missing a video.
                    Uses `exercise_name` (falls back to `requested_name`
                    is handled at the worker level).
      * "both"    — Union of the two above.

    A row is in scope iff it also satisfies ALL of:
      * Not soft-deleted
      * Not archived / retired / deprecated / merged / rejected
      * Actually missing a primary video URL
      * Canonical only (`canonical_id` unset OR equals own `id`)
    """
    library_gate = {"$or": [
        {"status": "Approved"},
        {"$and": [
            {"visibility": "client_visible"},
            {"safe_for_programming": True},
        ]},
    ]}
    drafts_gate = {"status": "draft_requested"}

    if target == "drafts":
        role_gate = drafts_gate
    elif target == "both":
        role_gate = {"$or": [library_gate, drafts_gate]}
    else:  # "library" (default)
        role_gate = library_gate

    return {
        "$and": [
            # ─── Alive: not soft-deleted ─────────────────────────────────
            {"is_deleted": {"$ne": True}},
            # ─── Alive: not archived / retired / deprecated / merged /
            #             rejected (case-insensitive via $toLower) ────────
            {"$expr": {"$not": {"$in": [
                {"$toLower": {"$ifNull": ["$status", ""]}},
                ["archived", "retired", "deprecated", "merged", "rejected"],
            ]}}},
            # ─── Role gate: library / drafts / both ─────────────────────
            role_gate,
            # ─── Must have a non-empty exercise_name to query for ────────
            {"exercise_name": {"$exists": True, "$type": "string", "$ne": ""}},
            # ─── Actually missing a primary video URL ────────────────────
            {"$or": [
                {"primary_video_url": None},
                {"primary_video_url": {"$exists": False}},
                {"primary_video_url": ""},
            ]},
            # ─── Canonical only (skip aliases / duplicates) ──────────────
            {"$or": [
                {"canonical_id": None},
                {"canonical_id": {"$exists": False}},
                {"$expr": {"$eq": ["$canonical_id", "$id"]}},
            ]},
        ],
    }


async def _bulk_yt_worker(
    job_id: str,
    coach_id: Optional[str],
    resume: bool = False,
    loose: bool = False,
    target: str = "library",
) -> None:
    """Iter188 · Resumable, batched YouTube video-finder sweep.

    Design goals (from product spec 2026-06):
      * Process in small batches (default 10) so a pod recycle / request
        timeout never wipes out an hour of work.
      * Save progress AFTER every batch — the resume path skips any
        exercise whose id is already in `processed_ids`.
      * Filter archived / retired / soft-deleted / alias rows BEFORE the
        first batch runs (via `_bulk_yt_query`).
      * `processed` / `total_in_scope` on the job doc give the frontend
        a clean "45 / 527" counter to display.
    """
    from datetime import datetime, timezone
    from feature_auto_media_gen import _spawn_bg  # noqa: F401 — shared bg-task set

    BATCH_SIZE = 10        # exercises per batch — matches product spec
    SPACING_SEC = 1.0      # sequential spacing to stay under YouTube QPS

    started = datetime.now(timezone.utc).isoformat()

    # ---- Resume support -------------------------------------------------
    # Load any prior progress so we skip already-attempted exercises.
    existing = await db.backfill_jobs.find_one({"_id": job_id}) or {}
    processed_ids: set[str] = set(existing.get("processed_ids") or []) if resume else set()
    processed = len(processed_ids)
    wrote = int(existing.get("wrote") or 0) if resume else 0
    errors: dict[str, int] = dict(existing.get("errors") or {}) if resume else {}
    sample: list[dict] = list(existing.get("results_sample") or []) if resume else []

    try:
        async with _YT_BULK_LOCK:
            await _record_yt_job(job_id, {
                "status": "running", "kind": "youtube_video_finder",
                "started_at": existing.get("started_at") or started,
                "resumed_at": started if resume else None,
                "coach_id": coach_id,
                "processed": processed, "wrote": wrote,
                "errors": errors, "results_sample": sample,
                "processed_ids": list(processed_ids),
            })

            # Hardened query — active, non-archived, non-alias only.
            # Iter189b · target = "library" | "drafts" | "both"
            query = _bulk_yt_query(target=target)
            all_exs = await db.exercises_v2.find(
                query, {"_id": 0, "id": 1, "exercise_name": 1,
                        "requested_name": 1, "status": 1},
            ).to_list(length=5000)
            total_in_scope = len(all_exs)

            # Skip anything we've already touched on a previous run.
            remaining = [e for e in all_exs if e.get("id") not in processed_ids]

            # Persist total up front so the poller can show "0 / 527".
            await _record_yt_job(job_id, {
                "total_in_scope": total_in_scope,
                "batch_size": BATCH_SIZE,
                "remaining": len(remaining),
            })

            # ---- Batched processing -----------------------------------
            for batch_start in range(0, len(remaining), BATCH_SIZE):
                batch = remaining[batch_start:batch_start + BATCH_SIZE]
                batch_no = (processed // BATCH_SIZE) + 1

                for ex in batch:
                    ex_id = ex.get("id")
                    # Iter189b · Drafts often use `requested_name` before
                    # coach approval — fall back to it if `exercise_name`
                    # is missing.
                    ex_name = (ex.get("exercise_name")
                               or ex.get("requested_name") or "")
                    processed += 1
                    try:
                        v = await find_best_short(ex_name, loose=loose)
                        if v:
                            # Iter189b · CRITICAL — never modify `status`.
                            # Drafts stay drafts. Approved stays Approved.
                            # Only URL / meta / video-review state is set.
                            await db.exercises_v2.update_one(
                                {"id": ex_id},
                                {"$set": {
                                    "primary_video_url": v["url"],
                                    "primary_video_source": "youtube_auto",
                                    "primary_video_meta": v,
                                    # Iter183 · Never auto-approve. Coach reviews.
                                    "approved_video_status": "Needs Review",
                                    "video_found_at": now_iso(),
                                }},
                            )
                            wrote += 1
                            if len(sample) < 30:
                                sample.append({
                                    "id": ex_id, "name": ex_name,
                                    "status_untouched": ex.get("status"),
                                    "video_url": v["url"], "channel": v.get("channel_name"),
                                    "duration": v.get("duration_seconds"),
                                })
                        else:
                            errors["no_match"] = errors.get("no_match", 0) + 1
                    except HTTPException as e:
                        if "quota" in (e.detail or "").lower():
                            # Persist a "paused_quota" state so the coach can
                            # resume tomorrow after the daily quota resets.
                            errors["quota_exceeded"] = errors.get("quota_exceeded", 0) + 1
                            if ex_id: processed_ids.add(ex_id)
                            await _record_yt_job(job_id, {
                                "status": "paused_quota",
                                "processed": processed, "wrote": wrote,
                                "errors": errors, "results_sample": sample,
                                "processed_ids": list(processed_ids),
                                "total_in_scope": total_in_scope,
                                "paused_at": datetime.now(timezone.utc).isoformat(),
                                "resumable": True,
                            })
                            return
                        errors[e.detail or "http_error"] = errors.get(e.detail or "http_error", 0) + 1
                    except Exception as e:
                        errors["exception"] = errors.get("exception", 0) + 1
                        logger.warning("yt bulk %s failed: %s", ex_id, e)

                    if ex_id:
                        processed_ids.add(ex_id)
                    await asyncio.sleep(SPACING_SEC)

                # ---- Persist AFTER every batch --------------------
                await _record_yt_job(job_id, {
                    "status": "running",
                    "processed": processed, "wrote": wrote,
                    "errors": errors, "results_sample": sample,
                    "processed_ids": list(processed_ids),
                    "total_in_scope": total_in_scope,
                    "last_batch_no": batch_no,
                    "last_batch_at": datetime.now(timezone.utc).isoformat(),
                })

            await _record_yt_job(job_id, {
                "status": "complete",
                "processed": processed, "wrote": wrote,
                "errors": errors, "results_sample": sample,
                "processed_ids": list(processed_ids),
                "total_in_scope": total_in_scope,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "resumable": False,
            })
    except Exception as e:
        logger.exception("yt bulk worker crashed job=%s", job_id)
        # Iter188 · A crash mid-batch leaves `processed_ids` intact from
        # the last successful batch save, so the coach can hit Resume
        # and pick up right where we left off.
        await _record_yt_job(job_id, {
            "status": "failed", "error": str(e)[:200],
            "finished_at": now_iso(),
            "resumable": True,
        })


@api.get("/coach/youtube-finder/settings")
async def yt_finder_get(_coach: dict = Depends(require_role("coach"))):
    doc = await db.settings.find_one({"_id": "youtube_video_finder"}) or {}
    doc.pop("_id", None)
    return {"enabled": bool(doc.get("enabled", False)),
            "api_key_configured": bool(YOUTUBE_API_KEY)}


@api.put("/coach/youtube-finder/settings")
async def yt_finder_set(body: dict, coach: dict = Depends(require_role("coach"))):
    enabled = bool((body or {}).get("enabled"))
    await db.settings.update_one(
        {"_id": "youtube_video_finder"},
        {"$set": {"enabled": enabled, "updated_at": now_iso(),
                  "updated_by": coach["id"]}},
        upsert=True,
    )
    return {"enabled": enabled}


@api.post("/coach/youtube-finder/bulk-run")
async def yt_finder_bulk_run(
    body: Optional[dict] = None,
    coach: dict = Depends(require_role("coach")),
    response: Response = None,
):
    body = body or {}
    dry_run = bool(body.get("dry_run"))
    # Iter189b · target = "library" (default) | "drafts" | "both"
    target = (body.get("target") or "library").strip().lower()
    if target not in ("library", "drafts", "both"):
        target = "library"
    if not YOUTUBE_API_KEY:
        if response is not None:
            response.status_code = 500
        return {"status": "blocked", "reason": "YOUTUBE_API_KEY_MISSING"}
    if not await _is_yt_enabled():
        if response is not None:
            response.status_code = 403
        return {"status": "blocked", "reason": "youtube_finder_disabled"}

    # Iter188 · Shared hardened query — see `_bulk_yt_query` docstring.
    # Excludes archived / retired / deprecated / merged / rejected /
    # soft-deleted / alias-duplicate rows so the sweep only targets the
    # active library (or drafts, depending on `target`).
    query = _bulk_yt_query(target=target)
    if dry_run:
        n = await db.exercises_v2.count_documents(query)
        # Iter189 · Transparency breakdown — coach can see which
        # exclusion rules cut the raw count down to `would_queue_count`.
        # All counts are read-only $count aggregates → cheap.
        raw_missing_primary_video = await db.exercises_v2.count_documents({
            "$or": [
                {"primary_video_url": None},
                {"primary_video_url": {"$exists": False}},
                {"primary_video_url": ""},
            ],
        })
        excluded_archived = await db.exercises_v2.count_documents({
            "$expr": {"$in": [
                {"$toLower": {"$ifNull": ["$status", ""]}},
                ["archived", "retired", "deprecated", "merged", "rejected"],
            ]},
        })
        excluded_deleted = await db.exercises_v2.count_documents({"is_deleted": True})
        excluded_aliases = await db.exercises_v2.count_documents({
            "$and": [
                {"canonical_id": {"$ne": None}},
                {"canonical_id": {"$exists": True}},
                {"$expr": {"$ne": ["$canonical_id", "$id"]}},
            ],
        })
        excluded_draft_requested = await db.exercises_v2.count_documents({
            "status": "draft_requested",
        })
        excluded_not_library = await db.exercises_v2.count_documents({
            "status": {"$nin": ["Approved"]},
            "$or": [
                {"visibility": {"$ne": "client_visible"}},
                {"safe_for_programming": {"$ne": True}},
            ],
        })
        excluded_no_name = await db.exercises_v2.count_documents({
            "$or": [
                {"exercise_name": None},
                {"exercise_name": {"$exists": False}},
                {"exercise_name": ""},
            ],
        })
        return {
            "dry_run": True,
            "target": target,
            "would_queue_count": n,
            "breakdown": {
                "raw_missing_primary_video": raw_missing_primary_video,
                "excluded_archived_or_retired": excluded_archived,
                "excluded_soft_deleted": excluded_deleted,
                "excluded_alias_duplicates": excluded_aliases,
                "draft_requested_rows_total": excluded_draft_requested,
                "excluded_not_in_library": excluded_not_library,
                "excluded_missing_name": excluded_no_name,
                "eligible_after_filters": n,
            },
        }

    if _YT_BULK_LOCK.locked():
        in_flight = await db.backfill_jobs.find_one(
            {"kind": "youtube_video_finder", "status": "running"},
            sort=[("started_at", -1)],
        )
        if response is not None:
            response.status_code = 409
        return {"status": "already_running",
                "job_id": (in_flight or {}).get("_id")}

    from feature_auto_media_gen import _spawn_bg

    # Iter188 · Auto-resume behaviour — if the coach's most recent job is
    # resumable (paused_quota / failed / interrupted with processed_ids
    # remaining), pick up where we left off unless the request explicitly
    # asks for a fresh start (`body.fresh_start = true`).
    fresh_start = bool(body.get("fresh_start"))
    if not fresh_start:
        resumable = await db.backfill_jobs.find_one(
            {
                "kind": "youtube_video_finder",
                "status": {"$in": ["paused_quota", "failed"]},
                "resumable": True,
            },
            sort=[("started_at", -1)],
        )
        if resumable and resumable.get("_id"):
            _spawn_bg(_bulk_yt_worker(
                resumable["_id"], coach_id=coach.get("id"), resume=True,
                target=(resumable.get("target") or "library"),
                loose=bool(resumable.get("loose")),
            ))
            if response is not None:
                response.status_code = 202
            return {
                "status": "resumed",
                "job_id": resumable["_id"],
                "target": resumable.get("target") or "library",
                "processed": resumable.get("processed", 0),
                "total_in_scope": resumable.get("total_in_scope", 0),
                "poll_url": f"/api/coach/auto-media-gen/backfill-status/{resumable['_id']}",
            }

    job_id = new_id()
    await _record_yt_job(job_id, {"status": "queued",
                                  "kind": "youtube_video_finder",
                                  "coach_id": coach.get("id"),
                                  "target": target,
                                  "loose": bool(body.get("loose"))})
    _spawn_bg(_bulk_yt_worker(job_id, coach_id=coach.get("id"),
                              loose=bool(body.get("loose")),
                              target=target))
    if response is not None:
        response.status_code = 202
    return {"status": "queued", "job_id": job_id, "target": target,
            "poll_url": f"/api/coach/auto-media-gen/backfill-status/{job_id}"}


@api.get("/coach/youtube-finder/health")
async def yt_finder_health(
    q: str = "bench press",
    loose: bool = False,
    coach: dict = Depends(require_role("coach")),
):
    """Iter189 · One-shot diagnostic — checks that:
      1. YOUTUBE_API_KEY is loaded.
      2. The Search API returns SOMETHING for a simple query.
      3. Quota isn't exhausted.
      4. WHY was a video rejected? (rejection breakdown per candidate)

    Returns raw counts + a rejection breakdown so the coach can see
    which filter is culling their candidates. Costs 100 quota units.
    """
    if not YOUTUBE_API_KEY:
        return {"ok": False, "reason": "no_api_key", "advice": "Set YOUTUBE_API_KEY in backend .env"}
    try:
        result = await find_best_short(q, loose=loose, debug=True)
        if not result:
            return {
                "ok": False, "query": q, "loose": loose,
                "advice": "Query normalized to empty — pass a real exercise name.",
            }
        match = result.get("match")
        return {
            "ok": bool(match),
            "query": q,
            "effective_yt_query": result.get("query"),
            "loose": loose,
            "eligible_count": result.get("eligible_count", 0),
            "rejections": result.get("rejections", {}),
            "sample": match,
            "advice": (
                "Working — filters are permissive." if match
                else "API responded but no eligible video. Try loose=true, or check rejections breakdown."
            ),
        }
    except HTTPException as e:
        return {
            "ok": False,
            "query": q,
            "loose": loose,
            "reason": "http_error",
            "status": e.status_code,
            "detail": e.detail,
            "advice": (
                "Quota exhausted — wait until midnight PT for the daily reset."
                if e.status_code == 429 or "quota" in str(e.detail).lower()
                else str(e.detail)
            ),
        }


@api.post("/coach/youtube-finder/bulk-resume/{job_id}")
async def yt_finder_bulk_resume(
    job_id: str,
    coach: dict = Depends(require_role("coach")),
    response: Response = None,
):
    """Iter188 · Explicit resume of a specific job.

    Used by the coach admin UI when they want to resume a paused / failed
    job without kicking off a fresh sweep. Idempotent — a currently-running
    job returns `already_running` and does NOT queue a duplicate.
    """
    if _YT_BULK_LOCK.locked():
        if response is not None:
            response.status_code = 409
        return {"status": "already_running", "job_id": job_id}

    doc = await db.backfill_jobs.find_one({"_id": job_id})
    if not doc:
        if response is not None:
            response.status_code = 404
        return {"status": "not_found"}
    if doc.get("status") == "complete":
        return {"status": "already_complete", "job_id": job_id}

    from feature_auto_media_gen import _spawn_bg
    _spawn_bg(_bulk_yt_worker(job_id, coach_id=coach.get("id"), resume=True,
                              target=(doc.get("target") or "library"),
                              loose=bool(doc.get("loose"))))
    if response is not None:
        response.status_code = 202
    return {
        "status": "resumed",
        "job_id": job_id,
        "processed": doc.get("processed", 0),
        "total_in_scope": doc.get("total_in_scope", 0),
        "poll_url": f"/api/coach/auto-media-gen/backfill-status/{job_id}",
    }


logger.info(
    "feature_youtube_video_finder: api_key=%s",
    "set" if YOUTUBE_API_KEY else "MISSING",
)
