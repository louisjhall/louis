"""OAuth sign-in endpoints (Iter200 · Emergent Google + Apple).

Two endpoints, one philosophy: each provider's job is to hand us a
verified identity (email + name). Once verified, we upsert into the
existing ``db.users`` collection and mint a JWT via the SAME
``make_token()`` helper the email/password flow uses. The frontend
receives the identical ``{token, user}`` shape and every downstream
protected endpoint continues to work unchanged.

Providers
---------
* **Emergent Auth (Google broker).**
  Frontend redirects the user to ``auth.emergentagent.com`` and lands
  back with a one-time ``session_id`` on the URL. It POSTs that here.
  We exchange it exactly once against Emergent's session-data API and
  discard both ``session_id`` and Emergent's ``session_token`` after
  extracting email/name/picture.

* **Apple Sign-In (native iOS).**
  Client-side ``expo-apple-authentication`` returns an ``identity_token``
  (a JWT signed by Apple with RS256). We verify the signature against
  Apple's JWKS, check ``iss`` + ``aud`` + ``exp``, and extract
  ``sub`` / ``email``. Apple only reveals real email on FIRST auth —
  subsequent auths may omit it, which is why we upsert by (provider,
  provider_subject) OR email.

Sessions are all JWT — no parallel session model, no changes to
``current_user()``.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import httpx
import jwt
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger("crewfit.oauth")

# --------------------------------------------------------------------- #
# Config                                                                  #
# --------------------------------------------------------------------- #

_EMERGENT_SESSION_URL = (
    "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
)
_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"

# The audience Apple embeds in the identity token = the iOS bundle id
# that requested the sign-in. We default to the CrewFit bundle already
# in app.json, but let ops override via env if a new bundle ships.
_APPLE_AUDIENCE_DEFAULT = "net.crewfit.app"

# Emergent OAuth allows repeat callbacks (react-strict-mode double-mount,
# hot deep links). We remember the session_ids we've already exchanged
# in-process so duplicate submissions from the SAME device return the
# cached user rather than a 401 from Emergent's second call. This is a
# best-effort dedupe — 32 slots is plenty for a single process lifetime.
_EMERGENT_RECENT_SIDS: dict[str, tuple[str, str, bool]] = {}
_EMERGENT_RECENT_MAX = 32


# --------------------------------------------------------------------- #
# Public request schemas                                                  #
# --------------------------------------------------------------------- #

class EmergentSessionBody(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=200)


class AppleSignInBody(BaseModel):
    identity_token: str = Field(..., min_length=32)
    # Optional — Apple only ships them on the FIRST sign-in and only if
    # the user granted "share name" scope. We use them to prime the
    # user record but never overwrite an existing name.
    given_name: Optional[str] = Field(default=None, max_length=80)
    family_name: Optional[str] = Field(default=None, max_length=80)


# --------------------------------------------------------------------- #
# Shared identity → user upsert                                           #
# --------------------------------------------------------------------- #

async def _upsert_oauth_user(
    db: Any,
    *,
    email: str,
    display_name: Optional[str],
    provider: str,
    provider_subject: str,
    picture: Optional[str] = None,
    new_id_fn,
) -> tuple[dict, bool]:
    """Find-or-create the user by (provider, provider_subject) or email.

    Returns ``(user_doc, created)``. Never overwrites an existing name,
    photo, or role — OAuth linking is additive.
    """
    email = email.lower().strip()
    now = _iso_now()

    # (1) Prefer the exact provider+subject match — deterministic if
    #     the user has already logged in via this provider before.
    existing = await db.users.find_one(
        {"oauth_providers.provider": provider,
         "oauth_providers.subject": provider_subject},
        {"_id": 0, "password_hash": 0},
    )

    # (2) Fallback to email match — links to an existing email/password
    #     account seamlessly.
    if not existing and email:
        existing = await db.users.find_one(
            {"email": email}, {"_id": 0, "password_hash": 0},
        )

    if existing:
        # Stamp the provider link if it's not already recorded so a
        # future sign-in hits path (1).
        provs = existing.get("oauth_providers") or []
        has_link = any(
            p.get("provider") == provider and p.get("subject") == provider_subject
            for p in provs
        )
        updates: dict[str, Any] = {}
        if not has_link:
            provs = list(provs) + [{
                "provider": provider,
                "subject": provider_subject,
                "linked_at": now,
            }]
            updates["oauth_providers"] = provs
        # Prime name/photo ONLY on empty existing fields — never overwrite.
        if display_name and not (existing.get("name") or "").strip():
            updates["name"] = display_name
        if picture and not existing.get("photo_base64") and not existing.get("photo_url"):
            updates["photo_url"] = picture
        if updates:
            await db.users.update_one({"id": existing["id"]}, {"$set": updates})
            existing.update(updates)
        return existing, False

    # (3) Truly new — create a fresh CLIENT account. Coach accounts are
    #     only created by Louis via the coach onboarding flow (matches
    #     the guard in the existing /auth/signup endpoint).
    user_id = new_id_fn()
    doc: dict[str, Any] = {
        "id": user_id,
        "email": email,
        "name": (display_name or email.split("@")[0]).strip(),
        "role": "client",
        "created_at": now,
        "onboarded": False,
        "coach_id": None,
        "profile": {},
        "age_confirmed": True,           # OAuth providers gate their own age
        "age_confirmed_at": now,
        "status": "active",
        "oauth_providers": [{
            "provider": provider,
            "subject": provider_subject,
            "linked_at": now,
        }],
    }
    if picture:
        doc["photo_url"] = picture

    # Auto-assign new clients to Louis so messaging routes work — mirrors
    # the /auth/signup behaviour.
    try:
        louis = await db.users.find_one(
            {"email": "louis@crewfit.net"},
            {"_id": 0, "id": 1, "name": 1},
        )
        if louis and louis.get("id"):
            doc["assigned_coach_id"] = louis["id"]
            doc["assigned_coach_name"] = louis.get("name") or "Louis Hall"
    except Exception:
        pass

    await db.users.insert_one(doc)
    return doc, True


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------- #
# Apple identity-token verification                                       #
# --------------------------------------------------------------------- #

_apple_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_APPLE_JWKS_TTL_SECONDS = 3600  # keys rotate infrequently


async def _fetch_apple_jwks() -> list[dict]:
    """Fetch Apple's public signing keys, cached for one hour."""
    now = time.time()
    if _apple_jwks_cache["keys"] and (now - _apple_jwks_cache["fetched_at"] < _APPLE_JWKS_TTL_SECONDS):
        return _apple_jwks_cache["keys"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(_APPLE_JWKS_URL)
        r.raise_for_status()
        keys = r.json().get("keys") or []
    _apple_jwks_cache["keys"] = keys
    _apple_jwks_cache["fetched_at"] = now
    return keys


def _pick_apple_key(keys: list[dict], kid: str) -> Optional[dict]:
    for k in keys:
        if k.get("kid") == kid:
            return k
    return None


async def _verify_apple_identity_token(identity_token: str) -> dict:
    """Verify signature + claims and return the decoded payload.

    Raises HTTPException(401) on any verification failure so the
    frontend gets a clean, uniform error to show.
    """
    audience = os.environ.get("APPLE_AUDIENCE", _APPLE_AUDIENCE_DEFAULT)
    try:
        unverified_header = jwt.get_unverified_header(identity_token)
    except Exception as e:
        logger.warning("apple: token header unreadable: %s", e)
        raise HTTPException(401, "apple_token_invalid")

    kid = unverified_header.get("kid")
    alg = unverified_header.get("alg")
    if alg != "RS256" or not kid:
        raise HTTPException(401, "apple_token_invalid")

    try:
        keys = await _fetch_apple_jwks()
    except Exception:
        logger.exception("apple: JWKS fetch failed")
        raise HTTPException(503, "apple_key_service_unavailable")

    key_dict = _pick_apple_key(keys, kid)
    if not key_dict:
        # Cached keys may be stale on a rotation — force one refresh.
        _apple_jwks_cache["fetched_at"] = 0.0
        try:
            keys = await _fetch_apple_jwks()
            key_dict = _pick_apple_key(keys, kid)
        except Exception:
            pass
    if not key_dict:
        raise HTTPException(401, "apple_token_invalid")

    try:
        public_key = jwt.PyJWK(key_dict).key
        payload = jwt.decode(
            identity_token,
            public_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=_APPLE_ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "apple_token_expired")
    except jwt.InvalidAudienceError:
        logger.warning("apple: aud mismatch (expected=%s)", audience)
        raise HTTPException(401, "apple_token_invalid")
    except jwt.PyJWTError as e:
        logger.warning("apple: verify failed: %s", e)
        raise HTTPException(401, "apple_token_invalid")

    if not payload.get("sub"):
        raise HTTPException(401, "apple_token_invalid")
    return payload


# --------------------------------------------------------------------- #
# Registration                                                            #
# --------------------------------------------------------------------- #

def register(api: APIRouter, db: Any, *, make_token, new_id, clean_doc) -> None:
    """Attach the two OAuth endpoints to the shared /api router."""

    # ------------------------ Emergent (Google) ----------------------- #

    @api.post("/auth/oauth/emergent-session", tags=["auth"])
    async def exchange_emergent_session(body: EmergentSessionBody) -> dict:
        """Exchange a one-time Emergent `session_id` for a CrewFit JWT.

        The frontend hits this AFTER redirect back from
        ``auth.emergentagent.com``. We call Emergent exactly once
        against ``session-data`` to prove the session_id is real, upsert
        the user, and hand back the same ``{token, user}`` payload
        ``/auth/login`` returns.
        """
        sid = body.session_id.strip()

        # In-process de-dupe: React strict mode + native deep-link
        # listeners often fire the same session_id twice within a
        # second. The SECOND call to Emergent would 401. Cache the
        # user we already minted a JWT for and short-circuit.
        cached = _EMERGENT_RECENT_SIDS.get(sid)
        if cached:
            token_cached, user_id, created_cached = cached
            user = await db.users.find_one(
                {"id": user_id}, {"_id": 0, "password_hash": 0},
            )
            if user:
                return {"token": token_cached, "user": user, "created": created_cached}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    _EMERGENT_SESSION_URL,
                    headers={"X-Session-ID": sid},
                )
        except Exception:
            logger.exception("emergent: session-data lookup failed (network)")
            raise HTTPException(503, "oauth_broker_unavailable")

        if r.status_code != 200:
            logger.info("emergent: session-data rejected sid (status=%s body=%s)",
                        r.status_code, r.text[:200])
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "oauth_session_invalid")

        try:
            data = r.json()
        except Exception:
            raise HTTPException(502, "oauth_broker_bad_response")

        email = (data.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(400, "oauth_email_missing")
        name = (data.get("name") or "").strip() or None
        picture = data.get("picture") or None
        # Emergent's `session_token` is deliberately DISCARDED — we
        # mint our own JWT below so the existing `current_user`
        # dependency (JWT-only) keeps working.

        user, _created = await _upsert_oauth_user(
            db,
            email=email,
            display_name=name,
            provider="emergent_google",
            provider_subject=email,   # Emergent doesn't surface a stable Google sub — use email
            picture=picture,
            new_id_fn=new_id,
        )

        token = make_token(user["id"], user.get("role") or "client")

        # Cache for de-dupe. LRU-ish eviction — cheap and good enough.
        if len(_EMERGENT_RECENT_SIDS) >= _EMERGENT_RECENT_MAX:
            _EMERGENT_RECENT_SIDS.pop(next(iter(_EMERGENT_RECENT_SIDS)))
        _EMERGENT_RECENT_SIDS[sid] = (token, user["id"], _created)

        clean_doc(user)
        return {"token": token, "user": user, "created": _created}

    # ----------------------------- Apple ------------------------------ #

    @api.post("/auth/oauth/apple", tags=["auth"])
    async def exchange_apple_identity(body: AppleSignInBody) -> dict:
        """Verify an Apple identity token and mint a CrewFit JWT.

        The frontend calls ``expo-apple-authentication`` which returns
        an ``identity_token``. We RS256-verify against Apple's JWKS,
        extract ``sub`` + ``email``, upsert, and return the standard
        ``{token, user}`` shape.
        """
        payload = await _verify_apple_identity_token(body.identity_token)

        apple_sub = payload["sub"]
        email = (payload.get("email") or "").strip().lower()
        # Apple ONLY includes email on the very first sign-in, and only
        # if the user tapped "share email". Subsequent sign-ins may drop
        # it — we then rely on the (provider, subject) match to find
        # the user we created before.
        if not email:
            existing = await db.users.find_one(
                {"oauth_providers.provider": "apple",
                 "oauth_providers.subject": apple_sub},
                {"_id": 0, "password_hash": 0},
            )
            if not existing:
                # No email + no prior link → we can't create a usable
                # account. Ask the client to retry the FIRST-run flow
                # so Apple re-issues the email.
                raise HTTPException(400, "apple_email_missing_repeat_first_run")
            email = existing["email"]

        # Compose a display name if Apple gave us one — only used when
        # the user is brand new.
        display = " ".join(
            p for p in [body.given_name or "", body.family_name or ""] if p
        ).strip() or None

        user, _created = await _upsert_oauth_user(
            db,
            email=email,
            display_name=display,
            provider="apple",
            provider_subject=apple_sub,
            new_id_fn=new_id,
        )

        token = make_token(user["id"], user.get("role") or "client")
        clean_doc(user)
        return {"token": token, "user": user, "created": _created}
