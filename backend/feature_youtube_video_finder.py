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


async def find_best_short(exercise_name: str, loose: bool = False) -> Optional[dict]:
    """Return the highest-quality ≤ N s embeddable video for `exercise_name`
    or None.

    Iter188 · Added `loose` diagnostic mode:
      * Query without the "shorts" suffix (broader results).
      * Max duration bumped 60 s → 180 s.
      * Skip like-ratio ranking; sort purely by (known_good, views).
      * Skip the BAD_CHANNEL_WORDS filter — surface EVERYTHING so we
        can see whether the API is returning zero results because of
        our filters or because it's quota-exhausted.
    """
    if not YOUTUBE_API_KEY:
        raise HTTPException(500, "YOUTUBE_API_KEY not configured")
    name = " ".join((exercise_name or "").split()).strip()
    if not name:
        return None

    query = name if loose else f"{name} shorts"
    max_dur = 180 if loose else 60

    async with httpx.AsyncClient(timeout=15) as http:
        try:
            search = await _yt_get(http, SEARCH_URL, {
                "part": "snippet", "q": query, "type": "video",
                "videoDuration": "short", "videoEmbeddable": "true",
                "order": "relevance", "maxResults": 10,
            })
        except HTTPException as e:
            # Iter188 · Bubble quota errors UP so the worker pauses the
            # whole sweep instead of silently returning None for every
            # subsequent exercise.
            if "quota" in (e.detail or "").lower() or e.status_code == 429:
                raise
            logger.warning("yt search failed for %r: %s", exercise_name, e.detail)
            return None

        cands = [
            it for it in (search.get("items") or [])
            if (it.get("id") or {}).get("kind") == "youtube#video"
            and (loose or _good_channel((it.get("snippet") or {}).get("channelTitle") or ""))
        ]
        ids = [it["id"]["videoId"] for it in cands if (it.get("id") or {}).get("videoId")]
        if not ids:
            return None

        details = await _yt_get(http, VIDEOS_URL, {
            "part": "contentDetails,snippet,statistics,status",
            "id": ",".join(ids),
        })

        eligible = []
        for it in (details.get("items") or []):
            dur = _iso_dur_seconds((it.get("contentDetails") or {}).get("duration") or "")
            if dur > max_dur:
                continue
            if not (it.get("status") or {}).get("embeddable"):
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
            return None
        if loose:
            return max(eligible, key=lambda v: (_known_good_priority(v["channel_name"] or ""), v["view_count"]))
        return max(
            eligible,
            key=lambda v: (_known_good_priority(v["channel_name"] or ""),
                           v["like_ratio"], v["view_count"]),
        )


async def _is_yt_enabled() -> bool:
    doc = await db.settings.find_one({"_id": "youtube_video_finder"})
    return bool((doc or {}).get("enabled"))


async def _record_yt_job(job_id: str, patch: dict) -> None:
    from datetime import datetime, timezone
    patch = {**patch, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.backfill_jobs.update_one({"_id": job_id}, {"$set": patch}, upsert=True)


def _bulk_yt_query() -> dict:
    """Shared query for the YouTube video-finder bulk sweep.

    Iter188 · Mirrors the hardening we applied to the primary-image
    sweep in `feature_auto_media_gen._bulk_primary_image_query`. Previous
    version fed the sweep every one of the ~667 rows in `exercises_v2`,
    including archived, retired, deprecated, merged, rejected, soft-
    deleted, and alias-duplicate rows — burning YouTube quota on rows
    the library never surfaces. This helper is used by BOTH the dry-run
    count and the worker so the two can NEVER drift.

    Filters applied (all must pass):
      * `is_deleted != True`             — not soft-deleted
      * `status` (case-insensitive) NOT in {archived, retired, deprecated,
        merged, rejected}
      * missing / empty `primary_video_url`
      * canonical-only (skip aliases — either `canonical_id` unset OR
        equal to the row's own `id`)
    """
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
            query = _bulk_yt_query()
            all_exs = await db.exercises_v2.find(
                query, {"_id": 0, "id": 1, "exercise_name": 1},
            ).to_list(length=2000)
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
                    processed += 1
                    try:
                        v = await find_best_short(ex.get("exercise_name") or "", loose=loose)
                        if v:
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
                                    "id": ex_id, "name": ex.get("exercise_name"),
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
    # active library.
    query = _bulk_yt_query()
    if dry_run:
        n = await db.exercises_v2.count_documents(query)
        # Iter188 · Transparency breakdown — coach can see which
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
        return {
            "dry_run": True,
            "would_queue_count": n,
            "breakdown": {
                "raw_missing_primary_video": raw_missing_primary_video,
                "excluded_archived_or_retired": excluded_archived,
                "excluded_soft_deleted": excluded_deleted,
                "excluded_alias_duplicates": excluded_aliases,
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
            ))
            if response is not None:
                response.status_code = 202
            return {
                "status": "resumed",
                "job_id": resumable["_id"],
                "processed": resumable.get("processed", 0),
                "total_in_scope": resumable.get("total_in_scope", 0),
                "poll_url": f"/api/coach/auto-media-gen/backfill-status/{resumable['_id']}",
            }

    job_id = new_id()
    await _record_yt_job(job_id, {"status": "queued",
                                  "kind": "youtube_video_finder",
                                  "coach_id": coach.get("id"),
                                  "loose": bool(body.get("loose"))})
    _spawn_bg(_bulk_yt_worker(job_id, coach_id=coach.get("id"), loose=bool(body.get("loose"))))
    if response is not None:
        response.status_code = 202
    return {"status": "queued", "job_id": job_id,
            "poll_url": f"/api/coach/auto-media-gen/backfill-status/{job_id}"}


@api.get("/coach/youtube-finder/health")
async def yt_finder_health(
    q: str = "bench press",
    loose: bool = False,
    coach: dict = Depends(require_role("coach")),
):
    """Iter188 · One-shot diagnostic — checks that:
      1. YOUTUBE_API_KEY is loaded.
      2. The Search API returns SOMETHING for a simple query.
      3. Quota isn't exhausted.

    Returns raw counts + the first 3 titles so the coach can see with
    their own eyes whether the API works. Costs 100 quota units.
    """
    if not YOUTUBE_API_KEY:
        return {"ok": False, "reason": "no_api_key", "advice": "Set YOUTUBE_API_KEY in backend .env"}
    try:
        v = await find_best_short(q, loose=loose)
        return {
            "ok": bool(v),
            "query": q,
            "loose": loose,
            "sample": v,
            "advice": "Working" if v else "API responded but no eligible video (try loose=true)",
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
    _spawn_bg(_bulk_yt_worker(job_id, coach_id=coach.get("id"), resume=True))
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
