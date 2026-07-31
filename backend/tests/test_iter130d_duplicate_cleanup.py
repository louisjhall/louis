"""Iter 130d — Duplicate cleanup endpoints.

Verifies:
  * GET /api/coach/clients/{id}/duplicates returns every user row sharing
    the anchor's email, with V2-plan indicators.
  * POST /api/coach/clients/{id}/duplicates/delete hard-deletes the target
    row when it does NOT own an active V2 plan.
  * The endpoint refuses to delete the row that owns the active V2 plan
    (safety guard).
  * Login after cleanup still works and lands on the correct row.
"""
import os
import asyncio
import uuid
import bcrypt
import httpx


BASE_URL = os.environ.get("EXTERNAL_URL", "http://127.0.0.1:8001") + "/api"


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def test_duplicate_cleanup_flow():
    asyncio.run(_run())


async def _run():
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv()
    m = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = m[os.environ.get("DB_NAME", "crewfit")]

    email = f"iter130d-{uuid.uuid4().hex[:8]}@crewfit.example.com"
    pw = "SharedPassword123!"
    id_good = f"u_good_{uuid.uuid4().hex[:8]}"   # has active V2 plan → should be KEPT
    id_bad = f"u_bad_{uuid.uuid4().hex[:8]}"    # empty shell → should be DELETABLE
    coach_id = f"u_coach_{uuid.uuid4().hex[:8]}"

    await db.users.insert_many([
        {"id": coach_id, "email": f"coach-{uuid.uuid4().hex[:6]}@crewfit.example.com",
         "role": "coach", "name": "Test Coach",
         "password_hash": _hash("CoachPass!"), "status": "active",
         "is_primary_coach": True, "is_admin": True},
        {"id": id_good, "email": email, "role": "client",
         "name": "Pietro (with V2 plan)",
         "password_hash": _hash(pw), "status": "active",
         "coach_id": coach_id},
        {"id": id_bad, "email": email, "role": "client",
         "name": "Pietro (empty shell)",
         "password_hash": _hash(pw), "status": "active"},
    ])
    # Give the "good" row an active V2 plan.
    await db.plan_live_v2.insert_one({
        "id": f"plv2_{uuid.uuid4().hex[:8]}", "client_id": id_good,
        "active": True, "created_at": "2026-06-01T00:00:00Z",
    })

    try:
        async with httpx.AsyncClient(timeout=15) as api:
            # Coach login (uses email-based lookup).
            r = await api.post(f"{BASE_URL}/auth/login",
                               json={"email": f"coach-", "password": "wrong"})
            # We don't actually need coach login for this test — we can
            # forge the admin dependency by directly mutating. Instead,
            # skip API path here and just verify DB side effects via
            # calling the endpoint code directly.

            # Login as the client — should land on the row with V2 plan.
            r = await api.post(f"{BASE_URL}/auth/login",
                               json={"email": email, "password": pw})
            assert r.status_code == 200, f"login should work: {r.text}"
            landed_id = r.json()["user"]["id"]
            assert landed_id == id_good, f"Login should land on V2-plan row, got {landed_id}"

            # Coach login (real) so we can hit the coach endpoint.
            # Find any existing coach to use — or create a fresh one and log in.
            coach_email = f"clean-coach-{uuid.uuid4().hex[:6]}@crewfit.example.com"
            coach_pw = "CoachPass123!"
            await db.users.insert_one({
                "id": f"u_coach_real_{uuid.uuid4().hex[:8]}",
                "email": coach_email, "role": "coach", "name": "Cleanup Coach",
                "password_hash": _hash(coach_pw), "status": "active",
                "is_primary_coach": True, "is_admin": True,
            })
            r = await api.post(f"{BASE_URL}/auth/login",
                               json={"email": coach_email, "password": coach_pw})
            assert r.status_code == 200, f"coach login: {r.text}"
            token = r.json()["token"]
            H = {"Authorization": f"Bearer {token}"}

            # GET duplicates.
            r = await api.get(f"{BASE_URL}/coach/clients/{id_good}/duplicates", headers=H)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["total"] == 2, f"expected 2 rows, got {body}"
            ids = {row["id"] for row in body["rows"]}
            assert ids == {id_good, id_bad}
            # Recommend_keep should mark the V2-plan row.
            keep_row = next(r for r in body["rows"] if r["id"] == id_good)
            assert keep_row["has_v2_plan"], f"good row should have_v2_plan: {keep_row}"

            # Try to delete the row WITH the V2 plan → must be refused.
            r = await api.post(
                f"{BASE_URL}/coach/clients/{id_good}/duplicates/delete", headers=H,
                json={"target_id": id_good, "confirm_email": email},
            )
            assert r.status_code == 400, f"should refuse deleting V2 row: {r.status_code} {r.text}"
            assert "active V2 plan" in r.text

            # Delete the empty duplicate → must succeed.
            r = await api.post(
                f"{BASE_URL}/coach/clients/{id_good}/duplicates/delete", headers=H,
                json={"target_id": id_bad, "confirm_email": email},
            )
            assert r.status_code == 200, r.text
            assert r.json()["deleted_id"] == id_bad

            # Confirm only the good row remains.
            remaining = await db.users.count_documents({"email": email})
            assert remaining == 1, f"expected 1 remaining, got {remaining}"

            # Client login still works.
            r = await api.post(f"{BASE_URL}/auth/login",
                               json={"email": email, "password": pw})
            assert r.status_code == 200
            assert r.json()["user"]["id"] == id_good
    finally:
        await db.users.delete_many({"email": {"$in": [email]}})
        await db.users.delete_many({"role": "coach", "name": {"$in": ["Test Coach", "Cleanup Coach"]}})
        await db.plan_live_v2.delete_many({"client_id": {"$in": [id_good, id_bad]}})
