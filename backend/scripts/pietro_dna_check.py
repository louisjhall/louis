"""Pre-flight DNA check — dump Pietro's actual stored inputs before Engine V2 kickoff."""
import asyncio, os, json, datetime as dt
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

PIETRO_ID = 'c4c7c7dd-4303-4645-af2c-b70212495360'

async def main():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c['crewfit_v1']
    u = await db.users.find_one({'id': PIETRO_ID}, {'_id':0})
    p = u.get('profile') or {}
    print("### PROFILE KEYS")
    for k in sorted(p.keys()):
        v = p[k]
        s = str(v)[:80]
        print(f"  {k}: {s}")
    print()
    print("### EVENTS")
    async for e in db.events.find({'user_id': PIETRO_ID}, {'_id':0}):
        print(f"  {e.get('event_type')} on {e.get('event_date')} active={e.get('is_active')} id={e.get('id')}")
    print()
    print("### RESTRICTIONS")
    n = 0
    async for r in db.restrictions.find({'client_id': PIETRO_ID}, {'_id':0}):
        print(f"  {r.get('region')} sev={r.get('severity')} avoid={r.get('avoid_patterns')} src={r.get('source')}")
        n += 1
    print(f"  ({n} rows)")
    print()
    print("### EQUIPMENT CONTEXTS")
    async for ec in db.equipment_contexts.find({'client_id': PIETRO_ID}, {'_id':0}):
        print(f"  scope={ec.get('scope')} equipment={ec.get('equipment')} src={ec.get('source')}")
    print()
    print("### ROSTER SUMMARY")
    n = 0
    day_type_counter = {}
    date_min = None; date_max = None
    async for sd in db.schedule_days.find({'client_id': PIETRO_ID}, {'_id':0,'date':1,'day_type':1}):
        n += 1
        dt_key = sd.get('day_type') or '?'
        day_type_counter[dt_key] = day_type_counter.get(dt_key, 0) + 1
        d = sd.get('date','')
        if not date_min or d < date_min: date_min = d
        if not date_max or d > date_max: date_max = d
    print(f"  {n} schedule_days from {date_min} to {date_max}")
    for k, v in sorted(day_type_counter.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")
    print()
    print("### ACTIVE COACH DIRECTIVES")
    n = 0
    async for d in db.coach_directives.find({'client_id': PIETRO_ID, 'status':'active'}, {'_id':0}):
        print(f"  {d.get('kind')} — {d.get('free_text','')[:60]}")
        n += 1
    print(f"  ({n} active)")
    print()
    print("### ENGINE V2 FLAG")
    flags = (p.get('v2_flags') or {})
    print(f"  engine_v2 = {flags.get('engine_v2')}")
    print(f"  v2_default = {flags.get('v2_default')}")

asyncio.run(main())
