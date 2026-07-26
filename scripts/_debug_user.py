import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

async def main():
    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    email = "pietrosangermano1992@hotmail.com"
    u = await db.users.find_one({"email": {"$regex": f"^{email}$", "$options": "i"}})
    if not u:
        print("USER NOT FOUND for exact email")
        print("\nSearching for pietro/sangermano...")
        async for x in db.users.find({"$or": [
            {"email": {"$regex": "pietro", "$options": "i"}},
            {"email": {"$regex": "sangermano", "$options": "i"}},
            {"name":  {"$regex": "pietro", "$options": "i"}},
            {"name":  {"$regex": "sangermano", "$options": "i"}},
        ]}):
            print(" match:", x.get("email"), "|", x.get("name"), "|", x.get("role"), "|", x.get("id"), "|", x.get("created_at"))
    else:
        print("FOUND USER:")
        for k, v in u.items():
            if k != "_id":
                print(f"  {k}: {v}")

    print("\nAll users right now:")
    async for x in db.users.find({}, {"email":1,"name":1,"role":1,"id":1,"created_at":1,"coach_id":1,"onboarding_complete":1,"_id":0}).sort("created_at", -1):
        print(" ", x)

asyncio.run(main())
