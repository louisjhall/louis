"""Stripe webhook processor (Iter201 · Phase 1 Payments).

Signature-verified, idempotent by ``stripe_event_id``. All state
mutation flows from Stripe → CrewFit through this endpoint.

Idempotency store
-----------------
Reuses the ``processed_notifications`` collection if it exists,
otherwise falls back to ``stripe_webhook_events``. Uniqueness on
``stripe_event_id`` prevents double-processing.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import stripe
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("crewfit.stripe_webhook")

_EVENT_COLL = "stripe_webhook_events"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_from_ts(ts: Optional[int]) -> Optional[str]:
    if not ts:
        return None
    return _iso(datetime.fromtimestamp(int(ts), tz=timezone.utc))


def _iso_now() -> str:
    return _iso(datetime.now(timezone.utc))


async def _resolve_user(db: Any, *, session=None, subscription=None,
                        customer_id: Optional[str] = None) -> Optional[dict]:
    """Preferred order: session.client_reference_id → session/subscription
    metadata.crewfit_user_id → users.stripe_customer_id → email fallback."""
    uid = None
    if session:
        uid = session.get("client_reference_id") or (session.get("metadata") or {}).get("crewfit_user_id")
    if not uid and subscription:
        uid = (subscription.get("metadata") or {}).get("crewfit_user_id")
    if uid:
        u = await db.users.find_one({"id": uid})
        if u:
            return u
    if customer_id:
        u = await db.users.find_one({"stripe_customer_id": customer_id})
        if u:
            return u
    if session and session.get("customer_email"):
        u = await db.users.find_one({"email": (session["customer_email"] or "").lower()})
        if u:
            return u
    return None


def _sub_row(sub: dict, user_id: str, is_founding: bool) -> dict:
    item = (sub.get("items") or {}).get("data", [{}])[0]
    price = item.get("price") or {}
    interval_map = {"month": "monthly", "year": "yearly"}
    price_interval = (price.get("recurring") or {}).get("interval")
    interval_count = (price.get("recurring") or {}).get("interval_count") or 1
    # Best-effort human name; the checkout metadata wins if present.
    metadata_interval = (sub.get("metadata") or {}).get("interval")
    if metadata_interval:
        interval = metadata_interval
    elif price_interval == "month" and interval_count == 3:
        interval = "quarterly"
    elif price_interval == "month" and interval_count == 6:
        interval = "biannual"
    elif price_interval == "month":
        interval = "monthly"
    else:
        interval = interval_map.get(price_interval or "", price_interval or "")
    return {
        "stripe_subscription_id": sub["id"],
        "user_id": user_id,
        "tier": (sub.get("metadata") or {}).get("tier"),
        "interval": interval,
        "stripe_price_id": price.get("id"),
        "status": sub.get("status"),
        "is_founding": is_founding,
        "current_period_end": _iso_from_ts(item.get("current_period_end") or sub.get("current_period_end")),
        "cancel_at_period_end": bool(sub.get("cancel_at_period_end")),
        "updated_at": _iso_now(),
    }


def register(api: APIRouter, db: Any) -> None:

    @api.post("/payments/stripe-webhook", tags=["payments"])
    async def stripe_webhook(request: Request):
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        sk = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        if not secret or not secret.startswith("whsec_") or not sk.startswith("sk_"):
            # Prevent someone from probing an unconfigured endpoint. Return
            # 503 rather than 200 so Stripe retries when it becomes real.
            raise HTTPException(503, "stripe_webhook_not_configured")
        stripe.api_key = sk

        payload = await request.body()
        sig = request.headers.get("stripe-signature") or ""
        try:
            event = stripe.Webhook.construct_event(payload, sig, secret)
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.warning("stripe webhook: signature invalid: %s", e)
            raise HTTPException(400, "invalid_signature")

        event_id = event.get("id")
        event_type = event.get("type")
        # ----- idempotency gate -----
        existing = await db[_EVENT_COLL].find_one({"stripe_event_id": event_id})
        if existing:
            return {"received": True, "duplicate": True}

        obj = (event.get("data") or {}).get("object") or {}

        try:
            if event_type == "checkout.session.completed":
                await _handle_checkout_completed(db, obj)
            elif event_type in ("customer.subscription.created",
                                "customer.subscription.updated"):
                await _handle_subscription_upsert(db, obj)
            elif event_type == "customer.subscription.deleted":
                await _handle_subscription_deleted(db, obj)
            elif event_type == "invoice.paid":
                await _handle_invoice_paid(db, obj)
            elif event_type == "invoice.payment_failed":
                await _handle_invoice_payment_failed(db, obj)
            else:
                logger.info("stripe webhook: ignoring type=%s id=%s", event_type, event_id)
        except Exception:
            logger.exception("stripe webhook: handler failed type=%s id=%s", event_type, event_id)
            # Do NOT mark processed — let Stripe retry.
            raise HTTPException(500, "handler_failed")

        # Only mark processed once handler succeeded.
        try:
            await db[_EVENT_COLL].insert_one({
                "stripe_event_id": event_id,
                "event_type": event_type,
                "processed_at": _iso_now(),
            })
        except Exception:
            # duplicate key from a race — ignore. State is already applied.
            pass
        return {"received": True}


# --------------------------------------------------------------------- #
# Handlers                                                                #
# --------------------------------------------------------------------- #

async def _handle_checkout_completed(db: Any, session: dict) -> None:
    user = await _resolve_user(
        db, session=session, customer_id=session.get("customer"),
    )
    if not user:
        logger.warning("checkout.session.completed: no user for session=%s", session.get("id"))
        return
    metadata = session.get("metadata") or {}
    tier = metadata.get("tier")
    founding_used = str(metadata.get("founding_pricing_used") or "").lower() == "true"
    updates: dict[str, Any] = {
        "membership_status": "active",
        "trial_ends_at": None,
    }
    if tier:
        updates["membership_tier"] = tier
    if session.get("customer") and not user.get("stripe_customer_id"):
        updates["stripe_customer_id"] = session["customer"]
    if founding_used:
        updates["is_founding_member"] = True
        updates["founding_price_locked"] = True
    await db.users.update_one({"id": user["id"]}, {"$set": updates})

    # Try to sync the subscription row now — the full customer.subscription.*
    # events will fill in cancel/period fields idempotently.
    sub_id = session.get("subscription")
    if sub_id:
        try:
            sub = stripe.Subscription.retrieve(sub_id)
            row = _sub_row(sub, user["id"], is_founding=founding_used)
            row["created_at"] = _iso_now()
            await db.subscriptions.update_one(
                {"stripe_subscription_id": sub_id},
                {"$set": row, "$setOnInsert": {"created_at": _iso_now()}},
                upsert=True,
            )
        except Exception:
            logger.exception("checkout.session.completed: subscription fetch failed sub_id=%s", sub_id)


async def _handle_subscription_upsert(db: Any, sub: dict) -> None:
    customer_id = sub.get("customer")
    user = await _resolve_user(db, subscription=sub, customer_id=customer_id)
    if not user:
        logger.warning("subscription upsert: no user for sub=%s customer=%s", sub.get("id"), customer_id)
        return
    is_founding = bool(user.get("is_founding_member"))
    row = _sub_row(sub, user["id"], is_founding=is_founding)
    await db.subscriptions.update_one(
        {"stripe_subscription_id": sub["id"]},
        {"$set": row, "$setOnInsert": {"created_at": _iso_now()}},
        upsert=True,
    )

    updates: dict[str, Any] = {}
    if sub.get("cancel_at_period_end"):
        updates["membership_status"] = "cancellation_scheduled"
    elif sub.get("status") == "active":
        # Revert cancellation_scheduled → active if the user re-enabled auto-renew.
        cur = user.get("membership_status")
        if cur in ("cancellation_scheduled", "past_due"):
            updates["membership_status"] = "active"
    if row["current_period_end"]:
        updates["access_until"] = row["current_period_end"]
    if row["tier"]:
        updates["membership_tier"] = row["tier"]
    if updates:
        await db.users.update_one({"id": user["id"]}, {"$set": updates})


async def _handle_subscription_deleted(db: Any, sub: dict) -> None:
    customer_id = sub.get("customer")
    user = await _resolve_user(db, subscription=sub, customer_id=customer_id)
    if not user:
        return
    await db.subscriptions.update_one(
        {"stripe_subscription_id": sub["id"]},
        {"$set": {"status": "canceled", "cancel_at_period_end": False,
                  "updated_at": _iso_now()}},
    )
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "membership_status": "cancelled",
            "membership_tier": "none",
            "founding_price_locked": False,
            "founding_eligible": False,
            "is_founding_member": False,
        }},
    )


async def _handle_invoice_paid(db: Any, invoice: dict) -> None:
    customer_id = invoice.get("customer")
    user = await db.users.find_one({"stripe_customer_id": customer_id})
    if not user:
        return
    # Update access_until from the invoice line's period end when we can.
    period_end = None
    lines = ((invoice.get("lines") or {}).get("data") or [])
    if lines:
        period = lines[0].get("period") or {}
        period_end = _iso_from_ts(period.get("end"))
    updates = {"membership_status": "active", "payment_required_at": None}
    if period_end:
        updates["access_until"] = period_end
    await db.users.update_one({"id": user["id"]}, {"$set": updates})
    sub_id = invoice.get("subscription")
    if sub_id:
        sub_updates = {"status": "active", "updated_at": _iso_now()}
        if period_end:
            sub_updates["current_period_end"] = period_end
        await db.subscriptions.update_one(
            {"stripe_subscription_id": sub_id}, {"$set": sub_updates},
        )


async def _handle_invoice_payment_failed(db: Any, invoice: dict) -> None:
    customer_id = invoice.get("customer")
    user = await db.users.find_one({"stripe_customer_id": customer_id})
    if not user:
        return
    grace = datetime.now(timezone.utc) + timedelta(days=7)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "membership_status": "past_due",
            "access_until": _iso(grace),
        }},
    )
