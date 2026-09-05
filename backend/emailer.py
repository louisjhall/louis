"""CrewFit transactional email service (Iter200 · Resend).

Single source of truth for every outbound transactional email. Wraps
the synchronous ``resend`` SDK in an ``asyncio.to_thread`` shim so
FastAPI's event loop never blocks on network I/O.

Design rules
------------
1. **Env is read at import time only.** `_load_config()` returns a
   ``dataclass`` — everything downstream is pure. If the module is
   imported before the API key is set (unit tests) sends short-circuit
   into a no-op and log a warning; the app keeps running.
2. **Never raise into the caller's happy path.** Every send is guarded
   with try/except; the return value is the Resend email id (str) on
   success or ``None`` on failure. Callers decide whether to surface a
   503 or swallow the failure.
3. **Templates live in Python.** Small, inline, HTML-escaped where the
   payload is user-controlled. No Jinja / no separate .html files
   until we have more than 3 template shapes.
4. **Idempotency is mandatory.** Every send passes an ``idempotency_key``
   scoped to the logical event, so a retry (network flake, coach
   double-click) doesn't duplicate mail.
5. **Zero client-facing exposure.** ``RESEND_API_KEY`` never appears in
   any response body, log line, or error message.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from dotenv import load_dotenv

# Load .env from the backend root — same convention as server.py.
load_dotenv("/app/backend/.env")

logger = logging.getLogger("crewfit.emailer")

try:
    import resend  # type: ignore
    _RESEND_IMPORTED = True
except Exception:  # pragma: no cover
    resend = None  # type: ignore
    _RESEND_IMPORTED = False


@dataclass(frozen=True)
class _Config:
    api_key: Optional[str]
    from_email: str
    public_app_url: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and _RESEND_IMPORTED


def _load_config() -> _Config:
    key = os.environ.get("RESEND_API_KEY", "").strip() or None
    from_email = os.environ.get(
        "RESEND_FROM_EMAIL", "CrewFit <noreply@crewfit.uk>"
    ).strip()
    public_url = os.environ.get(
        "PUBLIC_APP_URL",
        "https://flight-fit-plans.preview.emergentagent.com",
    ).rstrip("/")
    return _Config(api_key=key, from_email=from_email, public_app_url=public_url)


_config = _load_config()

if _config.enabled:
    resend.api_key = _config.api_key  # type: ignore[union-attr]
    logger.info(
        "emailer: Resend configured (from=%s, public_app_url=%s)",
        _config.from_email, _config.public_app_url,
    )
else:
    logger.warning(
        "emailer: DISABLED — RESEND_API_KEY missing or SDK not installed. "
        "All send_* calls will no-op and return None."
    )


def is_enabled() -> bool:
    """External callers use this to short-circuit UI copy ("Reset link
    sent") when the service is disabled — never gate the send itself."""
    return _config.enabled


def public_app_url() -> str:
    return _config.public_app_url


# --------------------------------------------------------------------- #
# Low-level send                                                          #
# --------------------------------------------------------------------- #

async def _send(
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str,
    idempotency_key: str,
    reply_to: Optional[str] = None,
    tags: Optional[list[dict]] = None,
) -> Optional[str]:
    """Fire one email. Returns Resend email id on success, None otherwise.

    Never raises — a failed send must not tank a signup or roster save.
    """
    if not _config.enabled:
        logger.warning("emailer._send: disabled — dropping mail to %s (subject=%s)",
                       to, subject[:60])
        return None

    params: dict[str, Any] = {
        "from": _config.from_email,
        "to": [to],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    if reply_to:
        params["reply_to"] = reply_to
    if tags:
        params["tags"] = tags

    options = {"idempotency_key": idempotency_key}

    def _do_send() -> Any:
        # `resend.Emails.send` is synchronous under the hood.
        return resend.Emails.send(params, options)  # type: ignore[union-attr]

    try:
        response = await asyncio.to_thread(_do_send)
    except Exception as e:
        # Resend surfaces its own error types — we log the CLASS + short
        # message so we can debug without leaking the API key or the
        # full request body.
        logger.exception(
            "emailer._send: Resend rejected mail to=%s subject=%r type=%s msg=%s",
            to, subject[:60], type(e).__name__, str(e)[:200],
        )
        return None

    email_id: Any
    if isinstance(response, dict):
        email_id = response.get("id")
    else:
        email_id = getattr(response, "id", None)
    logger.info("emailer._send: OK to=%s subject=%r id=%s", to, subject[:60], email_id)
    return str(email_id) if email_id else None


# --------------------------------------------------------------------- #
# Public templates                                                        #
# --------------------------------------------------------------------- #

_BRAND_FOOTER = (
    "\n\nCrewFit — training built around your roster.\n"
    "If you didn't expect this email, ignore it — no action needed."
)
_BRAND_FOOTER_HTML = (
    '<hr style="border:none;border-top:1px solid #333;margin:24px 0" />'
    '<p style="color:#888;font-size:12px;line-height:18px">'
    'CrewFit — training built around your roster.<br/>'
    "If you didn't expect this email, ignore it — no action needed.</p>"
)


def _wrap_html(inner: str) -> str:
    """Minimal dark-mode-friendly HTML shell around each template body."""
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,'
        '\'Segoe UI\',Roboto,sans-serif;max-width:560px;margin:0 auto;'
        'padding:32px 24px;background:#0b0b0b;color:#f4f4f4">'
        '<div style="text-align:center;margin-bottom:24px">'
        '<span style="display:inline-block;padding:6px 14px;'
        'border-radius:999px;background:#e11d2e;color:#fff;'
        'font-weight:700;letter-spacing:2px;font-size:11px">CREWFIT</span>'
        '</div>'
        f'{inner}'
        f'{_BRAND_FOOTER_HTML}'
        '</div>'
    )


async def send_password_reset_email(
    *,
    recipient: str,
    reset_url: str,
    user_id: str,
    display_name: Optional[str] = None,
) -> Optional[str]:
    """Send the "reset your password" email.

    `reset_url` should be a fully-qualified https URL that the frontend
    knows how to handle (`/reset-password?token=<opaque>`). The token
    lives on the reset URL, so the idempotency key uses its tail to
    keep repeat sends of the SAME token deduped, while a genuinely new
    reset request (new token) gets its own email.
    """
    name = html.escape((display_name or "").strip() or "there")
    safe_url = html.escape(reset_url, quote=True)

    inner = (
        f'<h1 style="font-size:22px;margin:0 0 12px">Reset your password</h1>'
        f'<p style="color:#d9d9d9;line-height:22px;font-size:15px">'
        f'Hi {name},</p>'
        '<p style="color:#d9d9d9;line-height:22px;font-size:15px">'
        'Tap the button below to choose a new password. This link '
        'expires in <strong>15 minutes</strong> and can only be used '
        'once.</p>'
        '<p style="margin:28px 0;text-align:center">'
        f'<a href="{safe_url}" '
        'style="display:inline-block;padding:14px 26px;background:#e11d2e;'
        'color:#fff;border-radius:10px;font-weight:700;letter-spacing:1px;'
        'text-decoration:none;font-size:14px">RESET MY PASSWORD</a></p>'
        '<p style="color:#888;font-size:12px;line-height:18px">'
        "If the button doesn't work, copy this link into your browser:<br/>"
        f'<a href="{safe_url}" style="color:#888">{safe_url}</a></p>'
        '<p style="color:#888;font-size:12px;line-height:18px">'
        "If you didn't ask for a password reset, ignore this email — "
        "your password stays the same.</p>"
    )
    text = (
        f"Hi {display_name or 'there'},\n\n"
        "Reset your CrewFit password by opening this link "
        "(expires in 15 minutes, one-time use):\n\n"
        f"{reset_url}\n\n"
        "If you didn't request this, ignore this email."
        + _BRAND_FOOTER
    )

    return await _send(
        to=recipient,
        subject="Reset your CrewFit password",
        html_body=_wrap_html(inner),
        text_body=text,
        # Same reset token → same idempotency key, so an accidental
        # double-tap of "Send reset link" doesn't send two emails.
        idempotency_key=f"password-reset::{user_id}::{reset_url[-40:]}",
        tags=[{"name": "category", "value": "password_reset"}],
    )


async def send_welcome_email(
    *,
    recipient: str,
    user_id: str,
    display_name: Optional[str] = None,
) -> Optional[str]:
    """Send the "welcome to CrewFit" email on first signup."""
    name = html.escape((display_name or "").strip() or "crew")
    app_url = html.escape(_config.public_app_url, quote=True)

    inner = (
        f'<h1 style="font-size:22px;margin:0 0 12px">Welcome, {name}.</h1>'
        '<p style="color:#d9d9d9;line-height:22px;font-size:15px">'
        "You're in. Your CrewFit account is ready and Louis (your coach) "
        "will be in touch shortly.</p>"
        '<p style="color:#d9d9d9;line-height:22px;font-size:15px">'
        'Next step: upload your latest roster from the app so we can '
        'build a training plan that respects your flights, layovers '
        'and rest days.</p>'
        '<p style="margin:28px 0;text-align:center">'
        f'<a href="{app_url}" '
        'style="display:inline-block;padding:14px 26px;background:#e11d2e;'
        'color:#fff;border-radius:10px;font-weight:700;letter-spacing:1px;'
        'text-decoration:none;font-size:14px">OPEN CREWFIT</a></p>'
    )
    text = (
        f"Welcome, {display_name or 'crew'}.\n\n"
        "You're in. Your CrewFit account is ready and Louis (your coach) "
        "will be in touch shortly.\n\n"
        "Next step: upload your latest roster from the app so we can "
        "build a training plan that respects your flights, layovers "
        "and rest days.\n\n"
        f"Open the app: {_config.public_app_url}"
        + _BRAND_FOOTER
    )
    return await _send(
        to=recipient,
        subject="Welcome to CrewFit",
        html_body=_wrap_html(inner),
        text_body=text,
        idempotency_key=f"welcome::{user_id}",
        tags=[{"name": "category", "value": "welcome"}],
    )


async def send_roster_expiring_email(
    *,
    recipient: str,
    user_id: str,
    roster_id: str,
    threshold: str,           # "expiring_7" | "expiring_3" | "expired"
    days_remaining: int,      # negative when threshold == "expired"
    display_name: Optional[str] = None,
) -> Optional[str]:
    """Send the roster-expiring warning. Idempotent per (user, roster,
    threshold) so we can call it from a daily cron without duplicating.
    """
    name = html.escape((display_name or "").strip() or "there")
    app_url = html.escape(_config.public_app_url + "/roster-upload", quote=True)

    if threshold == "expired":
        subject = "Your CrewFit roster has expired"
        headline = "Your roster has expired"
        lead = (
            "Your latest roster is out of date. Upload your new one so "
            "your training plan stays accurate."
        )
        cta_label = "UPLOAD NEW ROSTER"
    elif threshold == "expiring_3":
        subject = "Your CrewFit roster expires in 3 days"
        headline = "Roster expires in 3 days"
        lead = (
            f"Your current roster only covers the next {max(days_remaining, 0)} "
            "days. Upload the next one when it drops so we can keep "
            "planning ahead."
        )
        cta_label = "UPLOAD NEXT ROSTER"
    else:  # expiring_7
        subject = "Your CrewFit roster is running low"
        headline = "Roster running low"
        lead = (
            f"You've got about {max(days_remaining, 0)} days of roster "
            "coverage left. When your next month is published, drop it "
            "in the app so your plan keeps stride."
        )
        cta_label = "UPLOAD ROSTER"

    inner = (
        f'<h1 style="font-size:22px;margin:0 0 12px">{html.escape(headline)}</h1>'
        f'<p style="color:#d9d9d9;line-height:22px;font-size:15px">'
        f'Hi {name},</p>'
        f'<p style="color:#d9d9d9;line-height:22px;font-size:15px">'
        f'{html.escape(lead)}</p>'
        '<p style="margin:28px 0;text-align:center">'
        f'<a href="{app_url}" '
        'style="display:inline-block;padding:14px 26px;background:#e11d2e;'
        'color:#fff;border-radius:10px;font-weight:700;letter-spacing:1px;'
        f'text-decoration:none;font-size:14px">{cta_label}</a></p>'
        '<p style="color:#888;font-size:12px;line-height:18px">'
        "Prefer to do it later? Just open the app — the same banner "
        "will be waiting on your home screen.</p>"
    )
    text = (
        f"Hi {display_name or 'there'},\n\n"
        f"{lead}\n\n"
        f"Upload here: {_config.public_app_url}/roster-upload"
        + _BRAND_FOOTER
    )

    return await _send(
        to=recipient,
        subject=subject,
        html_body=_wrap_html(inner),
        text_body=text,
        # One email per (roster, threshold) — a daily scheduler can call
        # this many times and Resend will only send once.
        idempotency_key=f"roster-expiring::{user_id}::{roster_id}::{threshold}",
        tags=[
            {"name": "category", "value": "roster_expiring"},
            {"name": "threshold", "value": threshold},
        ],
    )
