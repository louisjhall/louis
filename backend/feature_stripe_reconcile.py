"""Nightly Stripe → CrewFit reconciliation (Iter201 · Phase 1 Payments).

For every user with a ``stripe_customer_id`` we ask Stripe for ALL of
that customer's subscriptions (any status) and rewrite the local
subscription row + user membership fields to match.

Also downgrades ``past_due`` users whose 7-day ``access_until`` grace
window has elapsed without an ``invoice.paid`` — this covers the
edge case where Stripe stopped retrying but never issued a definitive
``customer.subscription.deleted``.

Fully idempotent. Called from server.py startup and re-runs on a
24-hour loop.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import stripe

from feature_stripe_webhook import _sub_row, _iso, _iso_from_ts, _iso_now

logger = logging.getLogger("crewfit.stripe_reconcile")


async def reconcile_all(db: Any) -> dict:
    sk = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not sk.startswith("sk_"):
        logger.info("stripe reconcile: STRIPE_SECRET_KEY not configured, skipping")
        return {"skipped": True}
    stripe.api_key = sk

    total = 0
    changed = 0
    grace_expired = 0

    now_iso = _iso_now()
    users = db.users.find(
        {"stripe_customer_id": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1, "email": 1, "stripe_customer_id": 1,
         "membership_status": 1, "membership_tier": 1,
         "access_until": 1, "is_founding_member": 1},
    )
    async for u in users:
        total += 1
        cid = u["stripe_customer_id"]
        try:
            # `status="all"` covers active, past_due, unpaid, trialing,
            # canceled, incomplete — every state a customer's live
            # subscriptions can be in.
            subs = stripe.Subscription.list(customer=cid, status="all", limit=100)
        except Exception:
            logger.exception("stripe reconcile: list failed for customer=%s", cid)
            continue

        live_sub = None
        for s in subs.auto_paging_iter():
            row = _sub_row(s, u["id"], is_founding=bool(u.get("is_founding_member")))
            existing = await db.subscriptions.find_one(
                {"stripe_subscription_id": s["id"]},
                {"status": 1, "cancel_at_period_end": 1, "current_period_end": 1},
            )
            differ = (
                not existing
                or existing.get("status") != row["status"]
                or existing.get("cancel_at_period_end") != row["cancel_at_period_end"]
                or existing.get("current_period_end") != row["current_period_end"]
            )
            if differ:
                await db.subscriptions.update_one(
                    {"stripe_subscription_id": s["id"]},
                    {"$set": row, "$setOnInsert": {"created_at": _iso_now()}},
                    upsert=True,
                )
                changed += 1
            if s.get("status") in ("active", "trialing", "past_due"):
                live_sub = (s, row)

        # Sync user's summary fields to the winning live sub, if any.
        if live_sub:
            s, row = live_sub
            desired_status = None
            if s.get("cancel_at_period_end"):
                desired_status = "cancellation_scheduled"
            elif s.get("status") == "active":
                desired_status = "active"
            elif s.get("status") == "past_due":
                desired_status = "past_due"
            elif s.get("status") == "trialing":
                desired_status = "active"  # trials get full access

            updates: dict = {}
            if desired_status and u.get("membership_status") != desired_status:
                # NEVER stomp complimentary — coaches manually grant it
                # and Stripe truth should not override.
                if u.get("membership_status") != "complimentary":
                    updates["membership_status"] = desired_status
            if row.get("current_period_end") and u.get("access_until") != row["current_period_end"]:
                updates["access_until"] = row["current_period_end"]
            if row.get("tier") and u.get("membership_tier") != row["tier"]:
                updates["membership_tier"] = row["tier"]
            if updates:
                await db.users.update_one({"id": u["id"]}, {"$set": updates})
                changed += 1
        else:
            # No live subscription at all — if the user is currently
            # marked active/past_due/cancellation_scheduled, they should
            # be transitioned to cancelled UNLESS complimentary.
            cur_status = u.get("membership_status")
            if cur_status in ("active", "past_due", "cancellation_scheduled"):
                await db.users.update_one({"id": u["id"]}, {"$set": {
                    "membership_status": "cancelled",
                    "membership_tier": "none",
                }})
                changed += 1

        # Past-due grace expiry.
        if u.get("membership_status") == "past_due":
            au = u.get("access_until")
            if au and au < now_iso:
                await db.users.update_one({"id": u["id"]}, {"$set": {
                    "membership_status": "expired",
                }})
                grace_expired += 1
                changed += 1

    logger.info("stripe reconcile: users=%d changed=%d grace_expired=%d",
                total, changed, grace_expired)
    return {"users_seen": total, "changed": changed, "grace_expired": grace_expired}
