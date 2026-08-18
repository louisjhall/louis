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
    reason = ((body.get("error") or {}).get("errors") or [{}])[0].get("reason", "unknown")
    raise HTTPException(resp.status_code, f"youtube_{reason}")


async def find_best_short(exercise_name: str) -> Optional[dict]:
    """Return the highest-quality ≤ 60 s embeddable video for `exercise_name`
    or None. Enforces channel bad-word filter, known-good channel priority,
    then like-ratio, then view count."""
    if not YOUTUBE_API_KEY:
        raise HTTPException(500, "YOUTUBE_API_KEY not configured")
    name = " ".join((exercise_name or "").split()).strip()
    if not name:
        return None

    async with httpx.AsyncClient(timeout=15) as http:
        try:
            search = await _yt_get(http, SEARCH_URL, {
                "part": "snippet", "q": f"{name} shorts", "type": "video",
                "videoDuration": "short", "videoEmbeddable": "true",
                "order": "relevance", "maxResults": 10,
            })
        except HTTPException as e:
            if "quotaExceeded" in e.detail or "dailyLimitExceeded" in e.detail:
                raise
            logger.warning("yt search failed for %r: %s", exercise_name, e.detail)
            return None

        cands = [
            it for it in (search.get("items") or [])
            if (it.get("id") or {}).get("kind") == "youtube#video"
            and _good_channel((it.get("snippet") or {}).get("channelTitle") or "")
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
            if dur > 60:
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
        return max(
            eligible, default=None,
            key=lambda v: (_known_good_priority(v["channel_name"] or ""),
                           v["like_ratio"], v["view_count"]),
        ) if eligible else None


async def _is_yt_enabled() -> bool:
    doc = await db.settings.find_one({"_id": "youtube_video_finder"})
    return bool((doc or {}).get("enabled"))


async def _record_yt_job(job_id: str, patch: dict) -> None:
    from datetime import datetime, timezone
    patch = {**patch, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.backfill_jobs.update_one({"_id": job_id}, {"$set": patch}, upsert=True)


async def _bulk_yt_worker(job_id: str, coach_id: Optional[str]) -> None:
    from datetime import datetime, timezone
    from feature_auto_media_gen import _spawn_bg  # noqa: F401 — shared bg-task set
    started = datetime.now(timezone.utc).isoformat()
    try:
        async with _YT_BULK_LOCK:
            await _record_yt_job(job_id, {
                "status": "running", "kind": "youtube_video_finder",
                "started_at": started, "coach_id": coach_id,
                "processed": 0, "wrote": 0, "errors": {}, "results_sample": [],
            })

            query = {
                "$and": [
                    {"$or": [
                        {"primary_video_url": None},
                        {"primary_video_url": {"$exists": False}},
                        {"primary_video_url": ""},
                    ]},
                    {"$or": [
                        {"canonical_id": None},
                        {"canonical_id": {"$exists": False}},
                        {"$expr": {"$eq": ["$canonical_id", "$id"]}},
                    ]},
                ],
            }
            exs = await db.exercises_v2.find(
                query, {"_id": 0, "id": 1, "exercise_name": 1},
            ).to_list(length=1000)

            processed = 0
            wrote = 0
            errors: dict[str, int] = {}
            sample: list[dict] = []
            for ex in exs:
                processed += 1
                try:
                    v = await find_best_short(ex.get("exercise_name") or "")
                    if v:
                        await db.exercises_v2.update_one(
                            {"id": ex["id"]},
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
                        if len(sample) < 20:
                            sample.append({
                                "id": ex["id"], "name": ex.get("exercise_name"),
                                "video_url": v["url"], "channel": v.get("channel_name"),
                                "duration": v.get("duration_seconds"),
                            })
                    else:
                        errors["no_match"] = errors.get("no_match", 0) + 1
                except HTTPException as e:
                    if "quota" in (e.detail or "").lower():
                        errors["quota_exceeded"] = errors.get("quota_exceeded", 0) + 1
                        await _record_yt_job(job_id, {
                            "status": "paused_quota",
                            "processed": processed, "wrote": wrote,
                            "errors": errors, "results_sample": sample,
                            "total_in_scope": len(exs),
                        })
                        return
                    errors[e.detail or "http_error"] = errors.get(e.detail or "http_error", 0) + 1
                except Exception as e:
                    errors["exception"] = errors.get("exception", 0) + 1
                    logger.warning("yt bulk %s failed: %s", ex.get("id"), e)

                # Sequential — 1 s spacing so we never burst the API.
                await asyncio.sleep(1.0)

                if processed % 5 == 0:
                    await _record_yt_job(job_id, {
                        "processed": processed, "wrote": wrote,
                        "errors": errors, "results_sample": sample,
                        "total_in_scope": len(exs),
                    })

            await _record_yt_job(job_id, {
                "status": "complete",
                "processed": processed, "wrote": wrote,
                "errors": errors, "results_sample": sample,
                "total_in_scope": len(exs),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        logger.exception("yt bulk worker crashed job=%s", job_id)
        await _record_yt_job(job_id, {
            "status": "failed", "error": str(e)[:200],
            "finished_at": now_iso(),
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

    query = {
        "$and": [
            {"$or": [
                {"primary_video_url": None},
                {"primary_video_url": {"$exists": False}},
                {"primary_video_url": ""},
            ]},
            {"$or": [
                {"canonical_id": None},
                {"canonical_id": {"$exists": False}},
                {"$expr": {"$eq": ["$canonical_id", "$id"]}},
            ]},
        ],
    }
    if dry_run:
        n = await db.exercises_v2.count_documents(query)
        return {"dry_run": True, "would_queue_count": n}

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
    job_id = new_id()
    await _record_yt_job(job_id, {"status": "queued",
                                  "kind": "youtube_video_finder",
                                  "coach_id": coach.get("id")})
    _spawn_bg(_bulk_yt_worker(job_id, coach_id=coach.get("id")))
    if response is not None:
        response.status_code = 202
    return {"status": "queued", "job_id": job_id,
            "poll_url": f"/api/coach/auto-media-gen/backfill-status/{job_id}"}


logger.info(
    "feature_youtube_video_finder: api_key=%s",
    "set" if YOUTUBE_API_KEY else "MISSING",
)
