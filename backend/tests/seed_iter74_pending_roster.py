"""Seed a pending roster for iter74 UI verification.

- Logs in as client to fetch their user_id
- Deletes any existing pending rosters for that client
- Inserts a fresh 'pending_confirmation' rosters doc with a mix of
  green (confirmed / normal) days and one amber (needs_review) day
- Prints the roster id + auth token so the playwright script can pick it up
"""
import asyncio, os, sys, json, uuid
from datetime import datetime, timezone
import requests
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

BASE = "https://flight-fit-plans.preview.emergentagent.com"
API = f"{BASE}/api"
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

CLIENT_EMAIL = "client@crewfit.com"
CLIENT_PASSWORD = "Client123!"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def main() -> None:
    r = requests.post(
        f"{API}/auth/login",
        json={"email": CLIENT_EMAIL, "password": CLIENT_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    user = body.get("user") or {}
    user_id = user.get("id")
    assert token and user_id, f"missing token/user in login response: {body}"

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Purge previous pendings for this user to keep the test deterministic
    await db.rosters.delete_many(
        {"user_id": user_id, "status": "pending_confirmation"}
    )

    rid = "iter74-" + uuid.uuid4().hex[:8]
    days = [
        {
            "date": "2026-08-04",
            "day_type": "Home",
            "load": "green",
            "home_or_away": "home",
            "confidence": 0.95,
            "_confirmed_by_user": True,
        },
        {
            "date": "2026-08-05",
            "day_type": "Flight",
            "load": "amber",
            "home_or_away": "away",
            "report_time": "05:00",
            "duty_end_time": "13:00",
            "confidence": 0.9,
            "_confirmed_by_user": True,
        },
        {
            "date": "2026-08-06",
            "day_type": "Layover",
            "layover_city": "Bangkok",
            "layover_nights": 1,
            "load": "amber",
            "home_or_away": "away",
            "confidence": 0.88,
            "_confirmed_by_user": True,
        },
        {
            "date": "2026-08-07",
            "day_type": "Off",
            "load": "green",
            "home_or_away": "home",
            "confidence": 0.9,
            "_confirmed_by_user": True,
        },
        # Amber – needs_review
        {
            "date": "2026-08-08",
            "day_type": "Unknown/Needs Confirmation",
            "load": "grey",
            "home_or_away": "home",
            "confidence": 0.2,
        },
    ]

    await db.rosters.insert_one(
        {
            "id": rid,
            "user_id": user_id,
            "created_at": now_iso(),
            "week_start": days[0]["date"],
            "start_date": days[0]["date"],
            "end_date": days[-1]["date"],
            "days": days,
            "confirmed": False,
            "confirmed_at": None,
            "is_active": False,
            "status": "pending_confirmation",
            "raw_response": "",
            "source_filename": "iter74-seed",
            "upload_job_id": "iter74-job",
            "day_count": len(days),
            "confidence_avg": 0.77,
            "review_flags": {"low_confidence_count": 1},
        }
    )

    # Sanity: GET via API so we know the app can see it
    hh = {"Authorization": f"Bearer {token}"}
    gr = requests.get(f"{API}/roster/pending/{rid}", headers=hh, timeout=10)
    assert gr.status_code == 200, f"pending get failed: {gr.status_code} {gr.text}"
    info = {
        "roster_id": rid,
        "user_id": user_id,
        "token": token,
        "days": [d["date"] for d in days],
        "amber_dates": [d["date"] for d in days if d.get("day_type", "").lower().startswith("unknown")],
    }
    with open("/tmp/iter74_seed.json", "w") as f:
        json.dump(info, f)
    print(json.dumps(info))


if __name__ == "__main__":
    asyncio.run(main())
