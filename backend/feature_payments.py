"""Stripe checkout + portal + membership-status (Iter201 · Phase 1 Payments).

All hosted-Checkout. No card fields in the app.

Endpoints:
  POST /api/payments/create-checkout-session  {tier, interval}
  POST /api/payments/create-portal-session
  GET  /api/payments/membership-status
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import stripe
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

logger = logging.getLogger("crewfit.payments")

_VALID_TIERS = {"access", "coaching", "performance"}
_VALID_INTERVALS = {"monthly", "quarterly", "biannual"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_price_map() -> dict[tuple[str, str, str], str]:
    """(tier, interval, audience) → env-provided Stripe price id."""
    keys = {
        ("access", "monthly", "public"): "STRIPE_PRICE_ACCESS_PUBLIC_MONTHLY",
        ("access", "quarterly", "public"): "STRIPE_PRICE_ACCESS_PUBLIC_QUARTERLY",
        ("access", "biannual", "public"): "STRIPE_PRICE_ACCESS_PUBLIC_BIANNUAL",
        ("access", "monthly", "founding"): "STRIPE_PRICE_ACCESS_FOUNDING_MONTHLY",
        ("access", "quarterly", "founding"): "STRIPE_PRICE_ACCESS_FOUNDING_QUARTERLY",
        ("access", "biannual", "founding"): "STRIPE_PRICE_ACCESS_FOUNDING_BIANNUAL",
        ("coaching", "monthly", "public"): "STRIPE_PRICE_COACHING_PUBLIC_MONTHLY",
        ("coaching", "quarterly", "public"): "STRIPE_PRICE_COACHING_PUBLIC_QUARTERLY",
        ("coaching", "biannual", "public"): "STRIPE_PRICE_COACHING_PUBLIC_BIANNUAL",
        ("coaching", "monthly", "founding"): "STRIPE_PRICE_COACHING_FOUNDING_MONTHLY",
        ("coaching", "quarterly", "founding"): "STRIPE_PRICE_COACHING_FOUNDING_QUARTERLY",
        ("coaching", "biannual", "founding"): "STRIPE_PRICE_COACHING_FOUNDING_BIANNUAL",
        ("performance", "monthly", "public"): "STRIPE_PRICE_PERFORMANCE_PUBLIC_MONTHLY",
        ("performance", "quarterly", "public"): "STRIPE_PRICE_PERFORMANCE_PUBLIC_QUARTERLY",
        ("performance", "biannual", "public"): "STRIPE_PRICE_PERFORMANCE_PUBLIC_BIANNUAL",
        ("performance", "monthly", "founding"): "STRIPE_PRICE_PERFORMANCE_FOUNDING_MONTHLY",
        ("performance", "quarterly", "founding"): "STRIPE_PRICE_PERFORMANCE_FOUNDING_QUARTERLY",
        ("performance", "biannual", "founding"): "STRIPE_PRICE_PERFORMANCE_FOUNDING_BIANNUAL",
    }
    out: dict[tuple[str, str, str], str] = {}
    missing = []
    for k, env in keys.items():
        v = os.environ.get(env, "").strip()
        if not v or not v.startswith("price_"):
            missing.append(env)
            continue
        out[k] = v
    if missing:
        logger.warning("payments: %d Stripe price env vars missing/invalid: %s",
                       len(missing), ",".join(missing[:6]))
    return out


class CheckoutBody(BaseModel):
    tier: str = Field(..., pattern=r"^(access|coaching|performance)$")
    interval: str = Field(..., pattern=r"^(monthly|quarterly|biannual)$")


def register(api: APIRouter, db: Any, *, current_user) -> None:
    price_map = build_price_map()
    logger.info("payments: %d/%d Stripe price ids loaded", len(price_map), 18)

    def _stripe_key() -> str:
        k = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        if not k or not k.startswith("sk_"):
            raise HTTPException(503, "stripe_not_configured")
        stripe.api_key = k
        return k

    async def _ensure_customer(user: dict) -> str:
        if user.get("stripe_customer_id"):
            return user["stripe_customer_id"]
        _stripe_key()
        cust = stripe.Customer.create(
            email=user["email"],
            name=user.get("name") or None,
            metadata={"crewfit_user_id": user["id"]},
        )
        await db.users.update_one(
            {"id": user["id"], "$or": [
                {"stripe_customer_id": {"$exists": False}},
                {"stripe_customer_id": None},
            ]},
            {"$set": {"stripe_customer_id": cust.id}},
        )
        return cust.id

    @api.post("/payments/create-checkout-session", tags=["payments"])
    async def create_checkout_session(body: CheckoutBody, user: dict = Depends(current_user)):
        _stripe_key()
        founding_eligible = bool(user.get("founding_eligible"))
        audience = "founding" if founding_eligible else "public"
        pk = (body.tier, body.interval, audience)
        price_id = price_map.get(pk)
        if not price_id:
            raise HTTPException(500, f"price_not_configured:{body.tier}/{body.interval}/{audience}")

        customer_id = await _ensure_customer(user)
        success = os.environ.get("STRIPE_SUCCESS_URL",
                                 "https://crewfit.uk/profile?tab=membership&checkout=success")
        cancel = os.environ.get("STRIPE_CANCEL_URL",
                                "https://crewfit.uk/profile?tab=membership&checkout=cancel")

        metadata = {
            "crewfit_user_id": user["id"],
            "tier": body.tier,
            "interval": body.interval,
            "founding_pricing_used": "true" if audience == "founding" else "false",
        }
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                client_reference_id=user["id"],
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=success + ("&" if "?" in success else "?") + "session_id={CHECKOUT_SESSION_ID}",
                cancel_url=cancel,
                metadata=metadata,
                subscription_data={"metadata": metadata},
                allow_promotion_codes=False,
            )
        except stripe.error.StripeError as e:
            logger.exception("stripe checkout failed for user %s", user["id"])
            raise HTTPException(502, f"stripe_error:{e.user_message or str(e)[:120]}")
        return {"url": session.url, "id": session.id}

    @api.post("/payments/create-portal-session", tags=["payments"])
    async def create_portal_session(user: dict = Depends(current_user)):
        _stripe_key()
        cid = user.get("stripe_customer_id")
        if not cid:
            raise HTTPException(400, "no_stripe_customer")
        return_url = os.environ.get("STRIPE_SUCCESS_URL",
                                     "https://crewfit.uk/profile?tab=membership")
        try:
            portal = stripe.billing_portal.Session.create(customer=cid, return_url=return_url)
        except stripe.error.StripeError as e:
            logger.exception("stripe portal failed for user %s", user["id"])
            raise HTTPException(502, f"stripe_error:{e.user_message or str(e)[:120]}")
        return {"url": portal.url}

    @api.get("/payments/membership-status", tags=["payments"])
    async def membership_status(user: dict = Depends(current_user)):
        fresh = await db.users.find_one(
            {"id": user["id"]},
            {"_id": 0, "membership_status": 1, "membership_tier": 1,
             "is_founding_member": 1, "founding_eligible": 1,
             "founding_price_locked": 1, "trial_ends_at": 1,
             "access_until": 1, "payment_required_at": 1,
             "stripe_customer_id": 1},
        ) or {}
        sub = await db.subscriptions.find_one(
            {"user_id": user["id"]},
            {"_id": 0, "current_period_end": 1, "cancel_at_period_end": 1,
             "interval": 1, "tier": 1, "status": 1, "is_founding": 1,
             "stripe_price_id": 1},
            sort=[("updated_at", -1)],
        )
        return {
            "membership_status": fresh.get("membership_status"),
            "membership_tier": fresh.get("membership_tier"),
            "is_founding_member": bool(fresh.get("is_founding_member")),
            "founding_eligible": bool(fresh.get("founding_eligible")),
            "founding_price_locked": bool(fresh.get("founding_price_locked")),
            "trial_ends_at": fresh.get("trial_ends_at"),
            "access_until": fresh.get("access_until"),
            "payment_required_at": fresh.get("payment_required_at"),
            "has_stripe_customer": bool(fresh.get("stripe_customer_id")),
            "subscription": sub,
        }
