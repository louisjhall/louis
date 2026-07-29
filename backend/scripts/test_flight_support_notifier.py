import asyncio, os
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv(Path("/app/backend/.env"))

from feature_flight_support_notifier import (
    _plan_day_events, in_active_flight_window, _airport_iana, _local_to_utc,
    flight_support_scheduler_tick,
)
from feature_notifications import enqueue_notification, NOTIF_CATEGORY, DEFAULT_NOTIFICATION_SETTINGS
import datetime as _dt

async def main():
    c = AsyncIOMotorClient(os.getenv('MONGO_URL'))
    db = c[os.getenv('DB_NAME','test_database')]

    print("=" * 60)
    print("1) NOTIF_CATEGORY has flight_support entries?")
    for k in ("flight_support_pre_flight","flight_support_post_flight","flight_support_layover","flight_support_turnaround"):
        print(f"   {k}: {NOTIF_CATEGORY.get(k)}")
    print(f"   DEFAULT_NOTIFICATION_SETTINGS['flight_support'] = {DEFAULT_NOTIFICATION_SETTINGS.get('flight_support')}")
    
    print("\n2) IATA→IANA lookup:")
    for code in ["LHR","DXB","JFK","SIN","LGW","CMB","AUH","XYZ"]:
        print(f"   {code} → {_airport_iana(code)}")
    
    print("\n3) UTC conversion — 'report at 07:15 local LHR on 2026-08-10':")
    utc = _local_to_utc("2026-08-10","07:15","Europe/London")
    print(f"   → {utc}  (should be 06:15 UTC in BST)")
    
    print("\n4) Real-roster event plan:")
    r = await db.rosters.find_one({"confirmed": True, "is_active": True})
    if r:
        print(f"   roster user_id={r.get('user_id')} days={len(r.get('days',[]))}")
        found = 0
        for d in (r.get('days') or [])[:14]:
            events = _plan_day_events(d)
            if events:
                found += len(events)
                print(f"\n   {d.get('date')} ({d.get('day_type')}):")
                for (etype, when, meta) in events:
                    print(f"     · {etype:32s}  fires @ {when.isoformat()}")
                    print(f"       meta: {meta}")
        print(f"\n   >>> total planned events across roster: {found}")

    print("\n5) Duty-safe check — around first sector's dep_time:")
    if r:
        for d in (r.get('days') or []):
            flights = d.get('flights') or []
            if flights:
                dep = _local_to_utc(d.get('date'), flights[0].get('dep_time'), _airport_iana(flights[0].get('origin')))
                if dep:
                    for offset_min in [-60, -30, 0, +30, +90]:
                        t = dep + _dt.timedelta(minutes=offset_min)
                        in_win = await in_active_flight_window(db, r.get('user_id'), t)
                        print(f"     dep{offset_min:+d}m ({t.isoformat()}): in_active_flight_window = {in_win}")
                    break

    print("\n6) Scheduler tick run:")
    result = await flight_support_scheduler_tick(db, enqueue_notification)
    print(f"   {result}")

asyncio.run(main())
