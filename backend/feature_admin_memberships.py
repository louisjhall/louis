"""Coach/admin membership overrides (Iter201 · Phase 1 Payments).

Never talks to Stripe. Manual state overrides only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

logger = logging.getLogger("crewfit.admin_memberships")

_STATUS_ENUM = {
    "beta", "complimentary", "payment_required", "active",
    "past_due", "cancellation_scheduled", "cancelled", "expired",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class UserIdBody(BaseModel):
    user_id: str


def register(api: APIRouter, db: Any, *, require_role) -> None:

    async def _load_target(user_id: str) -> dict:
        u = await db.users.find_one({"id": user_id})
        if not u:
            raise HTTPException(404, "user_not_found")
        return u

    @api.post("/admin/memberships/set-payment-required", tags=["admin"])
    async def set_payment_required(body: UserIdBody, coach: dict = Depends(require_role("coach"))):
        await _load_target(body.user_id)
        await db.users.update_one({"id": body.user_id}, {"$set": {
            "membership_status": "payment_required",
            "payment_required_at": _iso_now(),
        }})
        logger.info("admin_memberships: payment_required set by=%s user=%s", coach["id"], body.user_id)
        return {"ok": True}

    @api.post("/admin/memberships/grant-complimentary", tags=["admin"])
    async def grant_complimentary(body: UserIdBody, coach: dict = Depends(require_role("coach"))):
        await _load_target(body.user_id)
        await db.users.update_one({"id": body.user_id}, {"$set": {
            "membership_status": "complimentary",
            "payment_required_at": None,
        }})
        logger.info("admin_memberships: complimentary granted by=%s user=%s", coach["id"], body.user_id)
        return {"ok": True}

    @api.post("/admin/memberships/restore-founding-eligibility", tags=["admin"])
    async def restore_founding_eligibility(body: UserIdBody, coach: dict = Depends(require_role("coach"))):
        await _load_target(body.user_id)
        await db.users.update_one({"id": body.user_id}, {"$set": {
            "founding_eligible": True,
            "founding_price_locked": False,
            # is_founding_member intentionally NOT touched here — it flips
            # only after a successful founding checkout.
        }})
        logger.info("admin_memberships: founding restored by=%s user=%s", coach["id"], body.user_id)
        return {"ok": True}

    # ------------------------------------------------------------------ #
    # Coach dashboard read endpoints — Payments Centre                    #
    # ------------------------------------------------------------------ #

    @api.get("/admin/memberships/overview", tags=["admin"])
    async def memberships_overview(_: dict = Depends(require_role("coach"))):
        """Counts strip for the coach's Payments Centre header."""
        pipeline = [
            {"$match": {"role": "client"}},
            {"$group": {"_id": {
                "status": "$membership_status",
                "tier": "$membership_tier",
            }, "count": {"$sum": 1}}},
        ]
        cur = db.users.aggregate(pipeline)
        counts_by_status: dict[str, int] = {}
        counts_by_tier: dict[str, int] = {}
        active_paid = 0
        async for doc in cur:
            k = doc["_id"] or {}
            status = k.get("status") or "unknown"
            tier = k.get("tier") or "none"
            counts_by_status[status] = counts_by_status.get(status, 0) + doc["count"]
            counts_by_tier[tier] = counts_by_tier.get(tier, 0) + doc["count"]
            if status == "active" and tier in ("access", "coaching", "performance"):
                active_paid += doc["count"]
        return {
            "counts_by_status": counts_by_status,
            "counts_by_tier": counts_by_tier,
            "active_paid": active_paid,
        }

    @api.get("/admin/memberships/clients", tags=["admin"])
    async def memberships_clients(_: dict = Depends(require_role("coach"))):
        """Full client list for the Payments Centre table."""
        rows = await db.users.find(
            {"role": "client"},
            {"_id": 0, "id": 1, "name": 1, "email": 1,
             "membership_status": 1, "membership_tier": 1,
             "is_founding_member": 1, "founding_eligible": 1,
             "payment_required_at": 1, "stripe_customer_id": 1},
        ).to_list(5000)

        # Enrich with the latest subscription (single query per user is fine
        # for the coach dashboard scale — hundreds of users, not millions).
        for r in rows:
            sub = await db.subscriptions.find_one(
                {"user_id": r["id"]},
                {"_id": 0, "status": 1, "interval": 1,
                 "current_period_end": 1, "cancel_at_period_end": 1},
                sort=[("updated_at", -1)],
            )
            r["subscription"] = sub
        return {"clients": rows, "count": len(rows)}
