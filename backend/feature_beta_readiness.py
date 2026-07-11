"""feature_beta_readiness — Pre-beta wiring:

1. **Storage smoke test** — admin-only endpoint that writes a tiny file to
   whichever storage driver is currently active, reads it back, and
   deletes it. Confirms R2/S3 credentials work end-to-end before you
   invite real testers.

2. **Beta disclaimer acceptance** — tracks who has accepted the beta
   disclaimer so the frontend only shows it once per user.

3. **Sentry crash reporting hook** — initialised from env vars in
   ``server.py`` (see the `_init_sentry` block there). This file only
   exposes the runtime status endpoint so you can verify from the admin
   dashboard whether Sentry is active.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from server import api, db, current_user, require_admin, now_iso, logger
import storage as _storage


# ---------------------------------------------------------------------------
# 1. Storage smoke test
# ---------------------------------------------------------------------------

@api.post("/admin/storage/smoke-test")
async def storage_smoke_test(admin: dict = Depends(require_admin())):
    """Write → read → delete a tiny probe file through the active driver.

    Returns which driver ran, whether the round-trip worked, and the
    signed URL (if applicable).  Never touches user data.
    """
    driver = _storage.storage.name
    probe_key = f"_smoke/{uuid.uuid4().hex}.txt"
    payload = f"crewfit-storage-smoke-{now_iso()}".encode("utf-8")
    results = {"driver": driver, "is_cloud": _storage.is_cloud(), "key": probe_key}
    try:
        await _storage.storage.write_bytes(probe_key, payload, content_type="text/plain")
        results["write_ok"] = True
    except Exception as e:
        results["write_ok"] = False
        results["error"] = f"write failed: {e}"
        return results

    try:
        data = await _storage.storage.read_bytes(probe_key)
        results["read_ok"] = bool(data) and data == payload
        results["read_bytes"] = len(data) if data else 0
    except Exception as e:
        results["read_ok"] = False
        results["error"] = f"read failed: {e}"

    try:
        url = await _storage.storage.public_url(probe_key)
        results["url_ok"] = bool(url)
        results["url_present"] = url is not None
    except Exception as e:
        results["url_ok"] = False
        results["error"] = f"url failed: {e}"

    try:
        await _storage.storage.delete(probe_key)
        results["delete_ok"] = True
    except Exception as e:
        results["delete_ok"] = False
        results["error"] = f"delete failed: {e}"

    results["overall_ok"] = all(results.get(k) for k in ("write_ok", "read_ok", "delete_ok"))
    return results


# ---------------------------------------------------------------------------
# 2. Beta disclaimer acceptance
# ---------------------------------------------------------------------------

BETA_DISCLAIMER_VERSION = "v1"
BETA_DISCLAIMER_TEXT = (
    "CrewFit is currently in private beta. You can use your real profile, "
    "roster, workouts, nutrition and check-ins, but features may change and "
    "some test data may be reset before public launch. Please report anything "
    "that looks wrong."
)


class BetaAcceptReq(BaseModel):
    version: Optional[str] = None


@api.get("/beta/status")
async def beta_status(user: dict = Depends(current_user)):
    """Frontend uses this after login to decide whether to show the modal."""
    acc = user.get("beta_disclaimer_accepted_at")
    ver = user.get("beta_disclaimer_version")
    return {
        "required_version": BETA_DISCLAIMER_VERSION,
        "accepted": bool(acc) and ver == BETA_DISCLAIMER_VERSION,
        "accepted_at": acc,
        "accepted_version": ver,
        "disclaimer_text": BETA_DISCLAIMER_TEXT,
    }


@api.post("/beta/accept")
async def beta_accept(body: BetaAcceptReq, user: dict = Depends(current_user)):
    now = now_iso()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "beta_disclaimer_accepted_at": now,
            "beta_disclaimer_version": body.version or BETA_DISCLAIMER_VERSION,
        }},
    )
    logger.info("beta_accept: user=%s version=%s", user["id"],
                body.version or BETA_DISCLAIMER_VERSION)
    return {"ok": True, "accepted_at": now, "version": body.version or BETA_DISCLAIMER_VERSION}


# ---------------------------------------------------------------------------
# 3. Sentry status endpoint (init lives in server.py)
# ---------------------------------------------------------------------------

@api.get("/admin/sentry/status")
async def sentry_status(admin: dict = Depends(require_admin())):
    dsn_set = bool(os.environ.get("SENTRY_DSN"))
    enabled = os.environ.get("SENTRY_ENABLED", "1") == "1"
    active = False
    try:
        import sentry_sdk
        hub = sentry_sdk.Hub.current
        active = hub.client is not None
    except Exception:
        pass
    return {
        "backend": {
            "dsn_set": dsn_set,
            "enabled_env": enabled,
            "active": active,
            "env_name": os.environ.get("SENTRY_ENV", "unknown"),
        },
        "note": ("Backend Sentry runs when SENTRY_DSN is set and SENTRY_ENABLED != 0. "
                  "Frontend Sentry is controlled by EXPO_PUBLIC_SENTRY_DSN."),
    }


@api.post("/admin/sentry/test-error")
async def sentry_test_error(admin: dict = Depends(require_admin())):
    """Trigger a test exception so you can confirm the DSN is receiving."""
    # Cheap: if no DSN, tell the caller straight away.
    if not os.environ.get("SENTRY_DSN"):
        return {"ok": False, "note": "Sentry SDK not initialised (SENTRY_DSN env var missing)."}
    try:
        raise RuntimeError("CrewFit Sentry test — safe to ignore.")
    except Exception as e:
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
            return {"ok": True, "note": "Test exception captured. Check your Sentry inbox."}
        except Exception:
            return {"ok": False, "note": "sentry_sdk import failed."}
