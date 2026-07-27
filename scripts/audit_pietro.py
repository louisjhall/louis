import asyncio, os, json
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
from motor.motor_asyncio import AsyncIOMotorClient

async def _():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    CID = 'dee691ca-6b11-40b8-8c75-88560f690d68'

    u = await db.users.find_one({'id': CID}, {'_id': 0})
    print("=== PROFILE ===")
    profile = u.get('profile') or {}
    for k in ['primary_goal','goal','goal_type','goal_notes','target_event',
              'event_type','event_date','training_history','days_per_week',
              'preferred_session_length','equipment','injuries']:
        if profile.get(k) is not None:
            print(f"  profile.{k}: {profile.get(k)}")

    ev = await db.client_events.find_one({'user_id': CID}, {'_id':0}, sort=[('event_date',-1)])
    if ev:
        print("\n=== CLIENT_EVENTS ===")
        for k in ['title','event_type','event_date','distance','notes']:
            if ev.get(k) is not None:
                print(f"  {k}: {ev.get(k)}")

    print("\n=== PROGRAMMES_V2 ===")
    async for p in db.programmes_v2.find({'client_id': CID}, {'_id':0}):
        g = await db.goals_v2.find_one({'id': p.get('primary_goal_id')}, {'_id':0})
        print(f"  status={p.get('status')} goal={g.get('goal_id_taxonomy') if g else '?'} "
              f"timeline={p.get('timeline_class')} start={p.get('start_date')} end={p.get('end_date')}")

    print("\n=== ASSIGNMENTS PER STATUS ===")
    from collections import Counter
    cnt = Counter()
    async for a in db.workout_assignments.find({'client_id': CID}, {'_id':0,'status':1,'draft_implementation_id':1}):
        cnt[a.get('status')] += 1
        if not a.get('draft_implementation_id'):
            cnt['NO_IMPL'] += 1
    print(f"  {dict(cnt)}")

    print("\n=== DECISION RECORDS (recent 10) ===")
    async for d in db.decision_records.find({'client_id': CID}, {'_id':0}).sort('created_at',-1).limit(10):
        print(f"  [{d.get('layer'):15s}] {d.get('scope_kind')}={d.get('scope_id','')[:8]} → {d.get('outcome')} :: {d.get('human_readable_reason') or d.get('reason','?')}")

asyncio.run(_())
