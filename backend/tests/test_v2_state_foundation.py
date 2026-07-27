"""V2 Phase 1 — State foundation tests (feature-flagged; no V1 impact).

Verifies the critical invariants of the DRAFT/LIVE/VERSION layer:

  * Flag gate: without profile.v2_flags.state_foundation_enabled=True
    endpoints return 409.
  * Role gate: non-coach cannot call any /api/v2/coach/* endpoint.
  * Version immutability: once published, plan_versions rows carry
    immutable=True and are not mutated by subsequent approvals.
  * Non-destructive revert: reverting to an older version creates
    a NEW version pointing at a NEW snapshot; the older version
    remains intact.
  * DecisionRecord fires on every state transition.
  * Client-facing /api/v2/live/plan returns has_v2_plan=False
    when no version exists — proving V1 clients see nothing new.
"""
import os
import sys
import asyncio
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mongo_available() -> bool:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    return bool(os.environ.get("MONGO_URL"))


pytestmark = pytest.mark.skipif(
    not _mongo_available(), reason="Mongo not configured in test env"
)


def _run(coro_factory):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_factory(loop))
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _fresh_db(loop):
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"], io_loop=loop)
    return client[os.environ.get("DB_NAME", "crewfit_v1")]


def _make_client_doc(uid: str, flag_enabled: bool = True) -> dict:
    return {
        "id": uid,
        "email": f"{uid[:8]}@test.local",
        "name": f"Test {uid[:6]}",
        "role": "client",
        "profile": {
            "v2_flags": {"state_foundation_enabled": bool(flag_enabled)}
        },
    }


# ---------------------------------------------------------------------------
# Static tests — endpoint registration + role gating
# ---------------------------------------------------------------------------

def test_v2_endpoints_registered():
    from server import app
    routes = {r.path for r in app.routes if hasattr(r, "path")}
    expected = [
        "/api/v2/coach/clients/{client_id}/flags",
        "/api/v2/coach/clients/{client_id}/drafts",
        "/api/v2/coach/clients/{client_id}/drafts/{draft_id}",
        "/api/v2/coach/clients/{client_id}/drafts/{draft_id}/change-sets",
        "/api/v2/coach/clients/{client_id}/change-sets/{change_set_id}/resolve",
        "/api/v2/coach/clients/{client_id}/drafts/{draft_id}/approvals",
        "/api/v2/coach/clients/{client_id}/versions",
        "/api/v2/coach/clients/{client_id}/versions/{version_id}",
        "/api/v2/coach/clients/{client_id}/versions/revert",
        "/api/v2/coach/clients/{client_id}/locks",
        "/api/v2/coach/clients/{client_id}/locks/{lock_id}",
        "/api/v2/coach/clients/{client_id}/decisions",
        "/api/v2/live/plan",
    ]
    for p in expected:
        assert p in routes, f"route {p} missing"


def test_v2_coach_endpoints_require_coach_role():
    """Every /v2/coach/* endpoint should have a coach role dependency."""
    from server import app
    import inspect
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api/v2/coach/"):
            sig = inspect.signature(r.endpoint)
            assert "coach" in sig.parameters, f"{path} missing coach role dep"


# ---------------------------------------------------------------------------
# Behaviour tests — direct endpoint invocation
# ---------------------------------------------------------------------------

def test_flag_gate_blocks_without_v2_enabled():
    """A client without the flag on cannot use draft endpoints."""
    from feature_v2_state_foundation import draft_create, DraftCreateBody
    from fastapi import HTTPException

    async def go(loop):
        db = _fresh_db(loop)
        cid = f"test-{uuid.uuid4()}"
        await db.users.insert_one(_make_client_doc(cid, flag_enabled=False))
        try:
            # Monkey-patch the module's db handle to this test's DB
            import feature_v2_state_foundation as mod
            mod.db = db
            with pytest.raises(HTTPException) as exc:
                await draft_create(cid, DraftCreateBody(), coach={"id": "c1"})
            assert exc.value.status_code == 409
        finally:
            await db.users.delete_one({"id": cid})
    _run(go)


def test_draft_create_lists_and_second_create_discards_first():
    from feature_v2_state_foundation import (
        draft_create, draft_list, DraftCreateBody,
    )

    async def go(loop):
        db = _fresh_db(loop)
        cid = f"test-{uuid.uuid4()}"
        await db.users.insert_one(_make_client_doc(cid, True))
        try:
            import feature_v2_state_foundation as mod
            mod.db = db
            d1 = await draft_create(cid, DraftCreateBody(notes="first"), coach={"id": "c1"})
            d2 = await draft_create(cid, DraftCreateBody(notes="second"), coach={"id": "c1"})
            assert d1["id"] != d2["id"]
            # First was discarded
            d1_after = await db.plan_drafts.find_one({"id": d1["id"]}, {"_id": 0})
            assert d1_after["status"] == "discarded"
            listing = await draft_list(cid, coach={"id": "c1"})
            ids = [r["id"] for r in listing["drafts"]]
            assert d1["id"] in ids and d2["id"] in ids
        finally:
            await db.plan_drafts.delete_many({"client_id": cid})
            await db.decision_records.delete_many({"client_id": cid})
            await db.users.delete_one({"id": cid})
    _run(go)


def test_approval_creates_immutable_version_and_snapshot():
    from feature_v2_state_foundation import (
        draft_create, approve_draft,
        DraftCreateBody, ApprovalBody,
    )

    async def go(loop):
        db = _fresh_db(loop)
        cid = f"test-{uuid.uuid4()}"
        await db.users.insert_one(_make_client_doc(cid, True))
        try:
            import feature_v2_state_foundation as mod
            mod.db = db
            d = await draft_create(cid, DraftCreateBody(), coach={"id": "c1"})
            r1 = await approve_draft(
                cid, d["id"],
                ApprovalBody(scope="programme", scope_ref=d["programme_id"], notes="v1"),
                coach={"id": "c1"},
            )
            assert r1["version"] == 1
            # Version doc immutable flag
            v = await db.plan_versions.find_one({"id": r1["version_id"]}, {"_id": 0})
            assert v["immutable"] is True
            # Snapshot exists
            snap = await db.plan_snapshots.find_one({"id": r1["snapshot_id"]}, {"_id": 0})
            assert snap is not None and snap["draft_id"] == d["id"]
            # Draft now promoted
            d_after = await db.plan_drafts.find_one({"id": d["id"]}, {"_id": 0})
            assert d_after["status"] == "promoted"
        finally:
            await db.plan_drafts.delete_many({"client_id": cid})
            await db.plan_versions.delete_many({"client_id": cid})
            await db.plan_snapshots.delete_many({"client_id": cid})
            await db.approvals.delete_many({"client_id": cid})
            await db.decision_records.delete_many({"client_id": cid})
            await db.users.delete_one({"id": cid})
    _run(go)


def test_revert_is_non_destructive():
    """Reverting to v1 must produce v3 (new), leaving v1 and v2 intact."""
    from feature_v2_state_foundation import (
        draft_create, approve_draft, version_revert,
        DraftCreateBody, ApprovalBody, RevertBody,
    )

    async def go(loop):
        db = _fresh_db(loop)
        cid = f"test-{uuid.uuid4()}"
        await db.users.insert_one(_make_client_doc(cid, True))
        try:
            import feature_v2_state_foundation as mod
            mod.db = db
            # v1
            d1 = await draft_create(cid, DraftCreateBody(), coach={"id": "c1"})
            r1 = await approve_draft(
                cid, d1["id"],
                ApprovalBody(scope="programme", scope_ref=d1["programme_id"]),
                coach={"id": "c1"},
            )
            # v2
            d2 = await draft_create(cid, DraftCreateBody(), coach={"id": "c1"})
            r2 = await approve_draft(
                cid, d2["id"],
                ApprovalBody(scope="programme", scope_ref=d2["programme_id"]),
                coach={"id": "c1"},
            )
            assert r2["version"] == 2
            # revert to v1
            rev = await version_revert(
                cid,
                RevertBody(target_version_id=r1["version_id"], notes="undo"),
                coach={"id": "c1"},
            )
            assert rev["new_version"] == 3
            # All three still exist
            all_versions = await db.plan_versions.find(
                {"client_id": cid}, {"_id": 0}
            ).to_list(10)
            assert len(all_versions) == 3
            nums = sorted(v["version"] for v in all_versions)
            assert nums == [1, 2, 3]
            # v3 references v1
            v3 = next(v for v in all_versions if v["version"] == 3)
            assert v3["reverted_from_version_id"] == r1["version_id"]
        finally:
            for c in ("plan_drafts", "plan_versions", "plan_snapshots",
                      "approvals", "decision_records"):
                await db[c].delete_many({"client_id": cid})
            await db.users.delete_one({"id": cid})
    _run(go)


def test_client_live_endpoint_returns_no_v2_plan_by_default():
    """A client with no published V2 versions sees has_v2_plan=False —
    proving V1 clients aren't accidentally affected by module load."""
    from feature_v2_state_foundation import live_plan

    async def go(loop):
        db = _fresh_db(loop)
        cid = f"test-{uuid.uuid4()}"
        await db.users.insert_one(_make_client_doc(cid, True))
        try:
            import feature_v2_state_foundation as mod
            mod.db = db
            fake_client = {"id": cid, "role": "client"}
            res = await live_plan(user=fake_client)
            assert res["has_v2_plan"] is False
        finally:
            await db.users.delete_one({"id": cid})
    _run(go)


def test_decision_records_created_on_state_transitions():
    from feature_v2_state_foundation import (
        draft_create, approve_draft,
        DraftCreateBody, ApprovalBody,
    )

    async def go(loop):
        db = _fresh_db(loop)
        cid = f"test-{uuid.uuid4()}"
        await db.users.insert_one(_make_client_doc(cid, True))
        try:
            import feature_v2_state_foundation as mod
            mod.db = db
            d = await draft_create(cid, DraftCreateBody(), coach={"id": "c1"})
            await approve_draft(
                cid, d["id"],
                ApprovalBody(scope="programme", scope_ref=d["programme_id"]),
                coach={"id": "c1"},
            )
            rows = await db.decision_records.find(
                {"client_id": cid}, {"_id": 0}
            ).to_list(20)
            # At least draft creation + approval
            assert len(rows) >= 2
            layers = {r["layer"] for r in rows}
            assert "PUBLISH" in layers
        finally:
            for c in ("plan_drafts", "plan_versions", "plan_snapshots",
                      "approvals", "decision_records"):
                await db[c].delete_many({"client_id": cid})
            await db.users.delete_one({"id": cid})
    _run(go)


if __name__ == "__main__":
    import pytest as _pt
    _pt.main([__file__, "-v", "-s"])
