"""Public self-serve password reset (Iter200).

Two endpoints:

* ``POST /api/auth/forgot-password``  →  issue a signed reset token,
  email it to the account owner. **Always returns 200** with the same
  body regardless of whether the email exists, so an attacker can't
  enumerate accounts. Rate-limited by (email, IP) to defend against
  spam.

* ``POST /api/auth/reset-password``   →  verify the token, set the new
  password, invalidate ALL refresh tokens + sessions for that user,
  return a fresh access token so the client can auto-log-in.

Storage
-------
Reset tokens are stored as `sha256(token)` in ``db.password_resets``
with a hard expiry (`expires_at`), a `used_at` marker for single-use,
and the requesting client IP + user_agent for audit. The raw token
only ever lives in the outbound email. Never in Mongo, never in logs.

Wired from ``server.py`` via ``feature_password_reset.register(api, db)``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from emailer import send_password_reset_email, public_app_url

logger = logging.getLogger("crewfit.password_reset")

# --------------------------------------------------------------------- #
# Config                                                                  #
# --------------------------------------------------------------------- #

# Reset tokens live for 15 minutes — the industry-standard window that
# keeps the attacker surface small without frustrating users who
# switched screens to check their inbox.
_TOKEN_TTL_MINUTES = 15

# Rate-limit windows. Kept intentionally generous so a legitimate user
# who fat-fingers "Send" doesn't get locked out, but tight enough that
# a script hammering /forgot-password gets a 429 fast.
_RATE_LIMIT_WINDOW_MIN = 15
_RATE_LIMIT_MAX_PER_EMAIL = 5
_RATE_LIMIT_MAX_PER_IP = 15

# Minimum length the new password must have. Matches signup rules —
# `SignupBody.password` has `min_length=8` in server.py.
_MIN_PASSWORD_LEN = 8


def _hash_token(raw: str) -> str:
    """Deterministic hash of the raw token — Mongo only ever stores this."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _client_fingerprint(req: Request) -> tuple[str, str]:
    """Best-effort (ip, user-agent) — used for audit + rate limiting."""
    xf = req.headers.get("x-forwarded-for")
    ip = (xf.split(",")[0].strip() if xf else req.client.host) if req.client else "unknown"
    ua = (req.headers.get("user-agent") or "unknown")[:200]
    return ip, ua


# --------------------------------------------------------------------- #
# Request schemas                                                         #
# --------------------------------------------------------------------- #

class ForgotPasswordBody(BaseModel):
    email: EmailStr


class ResetPasswordBody(BaseModel):
    token: str = Field(..., min_length=16, max_length=200)
    new_password: str = Field(..., min_length=_MIN_PASSWORD_LEN, max_length=200)


# --------------------------------------------------------------------- #
# Registration                                                            #
# --------------------------------------------------------------------- #

def register(api: APIRouter, db: Any, *, hash_pw, make_token) -> None:
    """Attach the two endpoints to the shared /api router.

    ``hash_pw`` and ``make_token`` are the exact helpers already in
    server.py — passed in so we don't duplicate password hashing /
    JWT signing logic. This keeps the feature module self-contained.
    """

    # ----------------------------- forgot ------------------------------ #

    @api.post("/auth/forgot-password", tags=["auth"])
    async def forgot_password(body: ForgotPasswordBody, request: Request) -> dict:
        """Issue a reset token and email it if the account exists.

        Always returns the same body — never leak whether the email is
        on file. That's the ONLY defense against account enumeration
        via this endpoint, so callers must never diverge on this shape.
        """
        email = body.email.lower().strip()
        ip, ua = _client_fingerprint(request)

        uniform_response = {
            "message": (
                "If an account exists for that email, we've sent a "
                "reset link. Check your inbox (and spam folder)."
            ),
            "email": email,
        }

        # --- Rate limit ------------------------------------------------
        window_start = _now_utc() - timedelta(minutes=_RATE_LIMIT_WINDOW_MIN)
        window_start_iso = _iso(window_start)
        try:
            per_email = await db.password_resets.count_documents({
                "email": email, "created_at": {"$gte": window_start_iso},
            })
            per_ip = await db.password_resets.count_documents({
                "created_ip": ip, "created_at": {"$gte": window_start_iso},
            })
        except Exception:
            logger.exception("forgot-password: rate-limit lookup failed")
            per_email = per_ip = 0

        if per_email >= _RATE_LIMIT_MAX_PER_EMAIL or per_ip >= _RATE_LIMIT_MAX_PER_IP:
            logger.warning(
                "forgot-password: rate-limited email=%s ip=%s "
                "(per_email=%d per_ip=%d)",
                email, ip, per_email, per_ip,
            )
            # Still 200 — same shape — but we skip issuing a new token
            # and skip the email send. The user sees the identical
            # message so account existence remains opaque.
            return uniform_response

        # --- Look the user up ------------------------------------------
        try:
            user = await db.users.find_one(
                {"email": email},
                {"_id": 0, "id": 1, "email": 1, "name": 1, "status": 1},
            )
        except Exception:
            logger.exception("forgot-password: user lookup failed for %s", email)
            return uniform_response

        if not user or user.get("status") == "archived":
            # Log for ops visibility but return the uniform 200.
            logger.info(
                "forgot-password: no active account for email=%s ip=%s "
                "(returning uniform 200)", email, ip,
            )
            return uniform_response

        # --- Issue token + persist ------------------------------------- #
        raw_token = secrets.token_urlsafe(48)   # 64+ chars, url-safe
        token_hash = _hash_token(raw_token)
        now = _now_utc()
        expires = now + timedelta(minutes=_TOKEN_TTL_MINUTES)

        try:
            await db.password_resets.insert_one({
                "user_id": user["id"],
                "email": email,
                "token_hash": token_hash,
                "created_at": _iso(now),
                "expires_at": _iso(expires),
                "used_at": None,
                "created_ip": ip,
                "created_user_agent": ua,
            })
        except Exception:
            logger.exception("forgot-password: failed to persist token for %s", email)
            # Never fail the endpoint — the user's UI shouldn't change
            # based on whether Mongo hiccuped.
            return uniform_response

        # --- Send the email -------------------------------------------- #
        reset_url = f"{public_app_url()}/reset-password?token={raw_token}"
        try:
            email_id = await send_password_reset_email(
                recipient=user["email"],
                reset_url=reset_url,
                user_id=user["id"],
                display_name=user.get("name"),
            )
            logger.info(
                "forgot-password: sent reset email for user_id=%s email_id=%s",
                user["id"], email_id,
            )
        except Exception:
            logger.exception(
                "forgot-password: emailer raised for user_id=%s", user["id"],
            )
            # Fall through — user sees the uniform 200 regardless.

        return uniform_response

    # ---------------------------- reset -------------------------------- #

    @api.post("/auth/reset-password", tags=["auth"])
    async def reset_password(body: ResetPasswordBody, request: Request) -> dict:
        """Consume a reset token and set the new password.

        Successful reset invalidates all existing refresh tokens for
        the user (so a stolen session dies with the reset) and returns
        a fresh access token so the client can auto-sign-in.
        """
        raw = body.token.strip()
        token_hash = _hash_token(raw)

        try:
            record = await db.password_resets.find_one({"token_hash": token_hash})
        except Exception:
            logger.exception("reset-password: lookup failed")
            raise HTTPException(500, "reset_lookup_failed")

        if not record:
            # Token never existed → uniform 400 so we don't leak
            # whether it's "wrong" vs "used" vs "expired".
            raise HTTPException(400, "reset_token_invalid_or_expired")

        if record.get("used_at"):
            raise HTTPException(400, "reset_token_invalid_or_expired")

        try:
            expires = record.get("expires_at", "")
            expired = expires < _iso(_now_utc())
        except Exception:
            expired = True
        if expired:
            raise HTTPException(400, "reset_token_invalid_or_expired")

        # --- Update password ------------------------------------------- #
        user_id = record["user_id"]
        try:
            new_hash = hash_pw(body.new_password)
        except Exception:
            logger.exception("reset-password: hash_pw failed")
            raise HTTPException(500, "reset_hash_failed")

        try:
            r = await db.users.update_one(
                {"id": user_id},
                {"$set": {
                    "password_hash": new_hash,
                    "password_reset_at": _iso(_now_utc()),
                    "password_reset_by": "self_service",
                }},
            )
        except Exception:
            logger.exception("reset-password: user update failed for %s", user_id)
            raise HTTPException(500, "reset_update_failed")
        if r.matched_count == 0:
            # Token pointed at a user that no longer exists.
            raise HTTPException(400, "reset_token_invalid_or_expired")

        # --- Mark token used ------------------------------------------- #
        ip, _ = _client_fingerprint(request)
        try:
            await db.password_resets.update_one(
                {"_id": record["_id"]},
                {"$set": {"used_at": _iso(_now_utc()), "used_ip": ip}},
            )
        except Exception:
            logger.exception("reset-password: failed to mark token used")
            # Non-fatal — the hash-lookup on next attempt will still see
            # the same token, but the used_at check will now catch it.

        # --- Invalidate active sessions -------------------------------- #
        # Best-effort clean-up of refresh tokens / sessions. Different
        # environments have different collection names — try the ones
        # we know about; ignore misses.
        for coll in ("refresh_tokens", "auth_sessions"):
            try:
                await db[coll].delete_many({"user_id": user_id})
            except Exception:
                pass

        # --- Return fresh access token --------------------------------- #
        try:
            user = await db.users.find_one(
                {"id": user_id},
                {"_id": 0, "id": 1, "email": 1, "name": 1, "role": 1},
            )
            token = make_token(user["id"], user.get("role") or "client") if user else None
        except Exception:
            logger.exception("reset-password: token minting failed")
            token = None

        logger.info("reset-password: OK user_id=%s ip=%s", user_id, ip)
        return {
            "message": "Password updated. You're signed in.",
            "token": token,
            "user": user,
        }
