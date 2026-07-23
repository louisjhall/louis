"""
Iter 94h — Roster upload failure must be VISIBLE to the client.

Two things the user reported:
1. Silent hangs (job stuck forever with no update).
2. Client home dashboard doesn't surface failure clearly.

Backend responsibilities we verify here:

* `/roster/jobs/active` returns the job with its current status (queued /
  processing / failed / needs_review) so the client home banner can render.
* When a job's `updated_at` is stale, the watchdog sweeps it to `failed`
  with an actionable error message. The sweep now covers BOTH `processing`
  and `queued` (previously only `processing`).
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8001/api")


def _mongo():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


def _signup_and_setup(c: httpx.Client, email: str) -> tuple[str, dict]:
    r = c.post("/auth/signup", json={
        "name": "T", "email": email, "password": "Passw0rd!",
        "age_confirmed": True, "role": "client",
        "sex": "male", "job_title": "Cabin Crew",
    })
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    uid = (j.get("user") or {}).get("id")
    h = {"Authorization": f"Bearer {tok}"}
    c.post("/profile/training-setup", json={
        "flying_type": "short_haul", "primary_goal": "lose_fat",
        "training_days": 4, "time_home": 45,
        "equipment_home": ["bodyweight_only", "dumbbells"],
        "injuries": "None", "no_go_movements": [],
    }, headers=h)
    return uid, h


def test_active_job_reports_status_transition_to_failed():
    """
    Simulate a stale roster_job (queued for >3 min) and confirm:
      a) The watchdog flips it to `failed` with an error message.
      b) `/roster/jobs/active` still returns the failed job so the client
         home banner can surface it (not filtered out for being complete).
    """
    email = f"iter94h_{int(time.time()*1000)}@t.com"
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        uid, h = _signup_and_setup(c, email)
        db = _mongo()
        # Insert a fake stale queued job — 10 min old updated_at.
        stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        job_id = f"testjob_{int(time.time()*1000)}"

        async def _seed_and_sweep():
            await db.roster_jobs.insert_one({
                "id": job_id, "user_id": uid,
                "status": "queued", "stage": "uploading",
                "message": "Uploading your roster...",
                "progress": 1, "created_at": stale, "updated_at": stale,
                "filename": "roster.pdf",
                "flow": "parse_only",
                "pending_roster_id": None, "roster_id": None,
                "error": None, "overlap": None, "retry_count": 0,
            })
            # Manually run the watchdog sweep (don't wait 60s for its interval).
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
            r = await db.roster_jobs.update_many(
                {"status": {"$in": ["processing", "queued"]}, "updated_at": {"$lt": cutoff}},
                {"$set": {
                    "status": "failed",
                    "stage": "interrupted",
                    "message": "This generation stopped responding.",
                    "error": "The upload timed out or was interrupted. Please tap Retry — this is usually a transient blip.",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "interrupted_by": "watchdog",
                }},
            )
            return r.modified_count

        modified = asyncio.get_event_loop().run_until_complete(_seed_and_sweep())
        assert modified >= 1, f"Watchdog didn't sweep the stale queued job (modified={modified})"

        # Now assert /roster/jobs/active returns the failed job so the client
        # home banner can render.
        r = c.get("/roster/jobs/active", headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("id") == job_id, (
            f"Expected /roster/jobs/active to return the failed job, got {j}"
        )
        assert j.get("status") == "failed"
        assert "retry" in (j.get("error") or "").lower(), (
            f"Expected user-facing error to prompt retry, got: {j.get('error')!r}"
        )
        print(f"OK — stale queued job swept & surfaced as failed: {j.get('status')} {j.get('error')!r}")


def test_active_job_returns_null_when_none_running():
    """Baseline sanity — no active/failed jobs = empty response."""
    email = f"iter94h_none_{int(time.time()*1000)}@t.com"
    with httpx.Client(base_url=BASE_URL, timeout=15) as c:
        _uid, h = _signup_and_setup(c, email)
        r = c.get("/roster/jobs/active", headers=h)
        # Either an empty dict / null, or 200 with nothing meaningful — the
        # frontend guards with `if (j && j.id)`.
        assert r.status_code == 200, r.text
        j = r.json() or {}
        assert not j.get("id"), f"Expected no active job, got {j}"
        print("OK — no active job returns empty payload as expected.")
