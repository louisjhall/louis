import asyncio, os
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')
from motor.motor_asyncio import AsyncIOMotorClient
async def check():
    c = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = c[os.environ['DB_NAME']]
    async for u in db.users.find({}, {'_id':0, 'email':1, 'role':1, 'profile.v2_flags':1}):
        v2 = ((u.get('profile') or {}).get('v2_flags') or {})
        cnt = sum(1 for k,v in v2.items() if isinstance(v, bool) and v)
        print(f"{u.get('email'):40s} role={u.get('role'):8s} v2_enabled_flags={cnt}")
asyncio.run(check())
