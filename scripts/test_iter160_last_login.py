"""
Iter 160 — last_login_at end-to-end verification.

Covers:
  A. /auth/login stamps last_login_at on the user doc and returns it.
  B. Directory row for coach client list carries last_login_at through.
  C. relTime helper contract (verified by string-checking the source of
     app/(coach)/clients.tsx — cheap regression guard).

Run:
    cd /app/backend && python /app/scripts/test_iter160_last_login.py
"""
import asyncio
import sys

sys.path.insert(0, "/app/backend")


async def main():
    import server as srv

    # ------------------------------------------------------------------
    # A. /auth/login stamps last_login_at on the user and echoes it back.
    # ------------------------------------------------------------------
    stored = {
        "id": "u-1", "email": "test@example.com", "role": "client",
        "password_hash": "hash", "status": "active",
    }
    updates: list[tuple] = []

    class FakeCursor:
        def __init__(self, docs): self._docs = docs
        async def to_list(self, _n): return list(self._docs)

    class FakeUsers:
        def find(self, *_a, **_kw):
            return FakeCursor([dict(stored)])
        async def update_one(self, q, upd):
            updates.append((q, upd))
            if q.get("id") == stored["id"]:
                stored.update(upd.get("$set") or {})
            return type("R", (), {"modified_count": 1})()
        async def count_documents(self, *_a, **_kw): return 0

    class FakeZero:
        async def count_documents(self, *_a, **_kw): return 0

    class FakeDB:
        users = FakeUsers()
        plan_live_v2 = FakeZero()
        plan_live_v2_implementations = FakeZero()
        schedule_days = FakeZero()

    orig_db = srv.db
    orig_verify = srv.verify_pw
    orig_token = srv.make_token
    srv.db = FakeDB()  # type: ignore
    srv.verify_pw = lambda *_a, **_kw: True  # type: ignore
    srv.make_token = lambda uid, role: f"tok-{uid}"  # type: ignore
    try:
        body = srv.LoginBody(email="test@example.com", password="pw")
        result = await srv.login(body)
    finally:
        srv.db = orig_db  # type: ignore
        srv.verify_pw = orig_verify  # type: ignore
        srv.make_token = orig_token  # type: ignore

    # Update should have been fired with $set: last_login_at.
    assert any(
        (u.get("$set") or {}).get("last_login_at") for (_q, u) in updates
    ), f"login must $set last_login_at, updates={updates}"
    assert result["user"].get("last_login_at"), "returned user must include last_login_at"
    assert result["user"]["last_login_at"] == stored["last_login_at"]
    print(f"A OK — /auth/login stamped last_login_at={result['user']['last_login_at']}")

    # ------------------------------------------------------------------
    # B. Coach clients directory carries last_login_at through.
    # ------------------------------------------------------------------
    import feature_v2_coach_home as home

    # Read source and confirm the projection + row build include last_login_at.
    src = open("/app/backend/feature_v2_coach_home.py").read()
    assert '"last_login_at": 1' in src, "users.find projection must include last_login_at"

    row_idx = src.index('rows.append(')
    row_block = src[row_idx : row_idx + 1400]
    assert '"last_login_at": c.get("last_login_at")' in row_block, \
        "row payload must include last_login_at from the user doc"
    print("B OK — coach directory projects + returns last_login_at.")

    # ------------------------------------------------------------------
    # C. Frontend relTime contract — cheap source-level checks.
    # ------------------------------------------------------------------
    fe = open("/app/frontend/app/(coach)/clients.tsx").read()
    assert "function relTime(" in fe, "relTime helper must be defined"
    assert 'return "Never"' in fe, "relTime must fallback to Never for null/invalid"
    assert "LAST SEEN" in fe, "LAST SEEN column header must be present"
    assert "colLastSeen" in fe, "colLastSeen style must be present"
    assert 'testID={`client-last-seen-${row.id}`}' in fe, "row cell must expose testID"
    print("C OK — frontend LAST SEEN column wired: relTime + Never fallback + column style + testID.")

    print("\nAll Iter 160 contracts verified.")


if __name__ == "__main__":
    asyncio.run(main())
