"""Beta → paid conversion layer (Iter202 · Phase 2A).

Reads:
  * `db.users` — filtered strictly to `membership_status == "beta"`.
    Complimentary / active / cancelled / expired accounts are IGNORED
    by every code path in this file (hard requirement from the spec).

Writes:
  * `db.beta_milestone_deliveries` — one row per (user, milestone).
    Unique compound index ensures idempotency across nightly ticks.
  * `db.beta_survey_responses` — one row per user (unique on user_id).
  * `db.users` — on Day 30 sets `membership_status: "expired"` if still
    beta. **Never** touches `founding_eligible`.

Endpoints:
  * GET  /api/beta/next-prompt          — returns the next un-delivered
                                          in-app milestone (day21/25/28/30)
                                          for the calling beta user, or {}
  * POST /api/beta/milestone/dismiss    — marks a prompt as delivered so it
                                          never shows twice
  * POST /api/beta/survey               — persists a survey response
  * GET  /api/beta/survey/mine          — returns the caller's response
                                          (or null) so the client can skip
                                          the survey trigger if already done
  * GET  /api/admin/beta/conversion-cohort — coach-facing cohort table
  * GET  /api/admin/beta/survey-results   — coach-facing raw survey table
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("crewfit.beta_conversion")

# ---- Milestone keys — MUST match spec verbatim ---- #
_M_DAY21_PROMPT = "day21_prompt"
_M_DAY25_SURVEY = "day25_survey"
_M_DAY25_PUSH   = "day25_push"
_M_DAY28_PROMPT = "day28_prompt"
_M_DAY28_PUSH   = "day28_push"
_M_DAY30_EXPIRY = "day30_expiry"
_M_DAY30_EMAIL  = "day30_email"

# Days-remaining thresholds. All trigger when days_remaining <= X (so a user
# who's on 9 days remaining fires day21, and continues to fire nothing new
# until 5 days remaining triggers day25, etc). Idempotency store prevents
# double-firing across nights.
_THRESHOLDS = [
    (9,  _M_DAY21_PROMPT),
    (5,  _M_DAY25_SURVEY),
    (5,  _M_DAY25_PUSH),
    (2,  _M_DAY28_PROMPT),
    (2,  _M_DAY28_PUSH),
    (0,  _M_DAY30_EXPIRY),
    (0,  _M_DAY30_EMAIL),
]

# In-app milestone display copy. Server-side so the client is dumb.
_PROMPT_COPY = {
    _M_DAY21_PROMPT: {
        "title": "Your Founding Member offer is ready.",
        "body":  "Continue with CrewFit after your free access and keep "
                 "your special Founding Member rate.",
        "cta":   "View Memberships",
        "tone":  "soft",
    },
    _M_DAY25_SURVEY: {
        "title": "Would you like to continue with CrewFit?",
        "body":  "Your Founding Member pricing is available when you're "
                 "ready to continue.",
        "cta":   "View Memberships",
        "survey_cta": "Take a 2-minute survey",
        "tone":  "mid",
    },
    _M_DAY28_PROMPT: {
        "title": "2 days left of your free CrewFit access.",
        "body":  "Keep your training, progress and roster-aware support "
                 "going by choosing your membership.",
        "cta":   "Choose Membership",
        "tone":  "strong",
    },
    _M_DAY30_EXPIRY: {
        "title": "Your free access has ended.",
        "body":  "Your data and progress are safe. Choose a membership "
                 "whenever you're ready to continue.",
        "cta":   "Choose Membership",
        "tone":  "expired",
        # `founding_still_available` is filled in at request time based on
        # the caller's current founding_eligible flag.
    },
}

_PUSH_COPY = {
    _M_DAY25_PUSH: {
        "title": "CrewFit",
        "body":  "Your CrewFit free access is nearly over. Tell us what "
                 "you think and keep your momentum going.",
    },
    _M_DAY28_PUSH: {
        "title": "CrewFit",
        "body":  "2 days left of your free CrewFit access. Choose your "
                 "membership to keep training with CrewFit.",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_now() -> str:
    return _iso(_now())


def _parse_iso(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _days_remaining(user: dict) -> Optional[int]:
    trial_end = _parse_iso(user.get("trial_ends_at"))
    if trial_end is None:
        return None
    delta = (trial_end - _now()).total_seconds() / 86400.0
    # Ceiling for "days left" — 4.3 days remaining reads as 5.
    import math
    return max(0, math.ceil(delta)) if delta >= 0 else int(delta)


def beta_expired_now(user: dict) -> bool:
    """Safety-fallback used by the entitlement guard in server.current_user.

    Returns True when the user is nominally still `beta` but their
    `trial_ends_at` has already elapsed. Callers should treat these
    users as `expired` (restricted access) even before the nightly job
    persists the state change.
    """
    if (user.get("membership_status") or "") != "beta":
        return False
    trial_end = _parse_iso(user.get("trial_ends_at"))
    if trial_end is None:
        return False
    return trial_end <= _now()


# ===================================================================== #
# Milestone runner — called from server.py sibling loop                   #
# ===================================================================== #

async def run_beta_milestones(db: Any) -> dict:
    """Walk every beta user, decide which milestones are ripe, fire the
    side effects (push / email / DB flip), and record delivery so no
    milestone ever fires twice.
    """
    fired: dict[str, int] = {}

    cursor = db.users.find(
        # HARD FILTER — never widen. `complimentary`, `active` etc must
        # never appear here.
        {"membership_status": "beta"},
        {"_id": 0, "id": 1, "email": 1, "name": 1,
         "trial_ends_at": 1, "founding_eligible": 1,
         "membership_status": 1, "role": 1},
    )
    async for u in cursor:
        # role guard — coach/admin should never be `beta`, but belt-and-braces
        if u.get("role") not in (None, "client"):
            continue
        days = _days_remaining(u)
        if days is None:
            continue

        for threshold, milestone in _THRESHOLDS:
            if days > threshold:
                continue
            # Idempotency gate — one delivery per (user, milestone), ever.
            try:
                res = await db.beta_milestone_deliveries.update_one(
                    {"user_id": u["id"], "milestone": milestone},
                    {"$setOnInsert": {"delivered_at": _iso_now()}},
                    upsert=True,
                )
            except Exception:
                logger.exception("milestone: idempotency store failed user=%s ms=%s",
                                 u["id"], milestone)
                continue
            # If the doc already existed the upsert is a no-op — skip side effects.
            if not (res.upserted_id or (res.matched_count == 0 and res.modified_count == 0)):
                # matched_count > 0 → duplicate; skip.
                if res.matched_count > 0:
                    continue

            try:
                if milestone in (_M_DAY25_PUSH, _M_DAY28_PUSH):
                    await _fire_push(db, u, milestone)
                elif milestone == _M_DAY30_EXPIRY:
                    await _flip_to_expired(db, u)
                elif milestone == _M_DAY30_EMAIL:
                    await _fire_expired_email(u)
                # day21/day25_survey/day28 in-app prompts have NO server
                # side effect at fire-time — the delivery row is enough.
                # They surface when the client polls /beta/next-prompt.
            except Exception:
                # Rollback the idempotency row so the next tick retries.
                logger.exception("milestone: side effect failed user=%s ms=%s",
                                 u["id"], milestone)
                try:
                    await db.beta_milestone_deliveries.delete_one(
                        {"user_id": u["id"], "milestone": milestone},
                    )
                except Exception:
                    pass
                continue

            fired[milestone] = fired.get(milestone, 0) + 1

    logger.info("beta milestones: %s", fired or "no-op")
    return {"fired": fired}


async def _fire_push(db: Any, user: dict, milestone: str) -> None:
    """Reuse existing push infra. Never fails the milestone if push
    disabled — the delivery row is still valid because we tried."""
    copy = _PUSH_COPY[milestone]
    try:
        # Re-import defensively — feature_notifications may not always
        # be importable at module load time.
        from feature_notifications import enqueue_notification
    except Exception:
        logger.warning("beta push: feature_notifications unavailable; skipping")
        return
    await enqueue_notification(
        user["id"],
        "beta_conversion",
        copy["title"],
        copy["body"],
        action_url="/membership",
        related_id=None,
        dedupe_key=f"beta::{milestone}::{user['id']}",
    )


async def _flip_to_expired(db: Any, user: dict) -> None:
    """Only touches `membership_status`. Founding eligibility, tier,
    trial_ends_at and all history remain intact by design."""
    r = await db.users.update_one(
        {"id": user["id"], "membership_status": "beta"},
        {"$set": {"membership_status": "expired"}},
    )
    if r.modified_count:
        logger.info("beta expired: user=%s", user["id"])


async def _fire_expired_email(user: dict) -> None:
    """One-time expired email via the existing Resend module."""
    try:
        from emailer import send_beta_expired_email  # added in emailer.py
    except Exception:
        logger.warning("beta email: send_beta_expired_email unavailable")
        return
    await send_beta_expired_email(
        recipient=user["email"],
        user_id=user["id"],
        display_name=user.get("name"),
        founding_eligible=bool(user.get("founding_eligible")),
    )


# ===================================================================== #
# HTTP surface                                                            #
# ===================================================================== #

class SurveyBody(BaseModel):
    experience_rating: int = Field(..., ge=1, le=5)
    most_valuable: Optional[str] = Field(default=None, max_length=2000)
    could_be_better: Optional[str] = Field(default=None, max_length=2000)
    recommendation_rating: int = Field(..., ge=1, le=5)
    continuation_blocker: Optional[str] = Field(default=None, max_length=2000)


class DismissBody(BaseModel):
    milestone: str = Field(..., pattern=r"^day\d{2}_(prompt|survey)$")


def register(api: APIRouter, db: Any, *, current_user, require_role, new_id) -> None:

    # --------- Client-facing ---------

    @api.get("/beta/next-prompt", tags=["beta"])
    async def next_prompt(user: dict = Depends(current_user)):
        """Return the next un-delivered in-app milestone for the caller.

        Skips users who aren't currently `beta`. Empty response `{}`
        means the client should render nothing.
        """
        # Complimentary / active / etc → no prompts, ever.
        # Note: server.current_user has already applied the expiry safety
        # fallback, so a beta user past `trial_ends_at` will come through
        # here reading `expired`.
        fresh = await db.users.find_one(
            {"id": user["id"]},
            {"_id": 0, "membership_status": 1, "trial_ends_at": 1,
             "founding_eligible": 1},
        ) or {}
        status = fresh.get("membership_status")

        # The Day 30 EXPIRED prompt is shown on the FIRST render after
        # expiry — regardless of whether the user is still `beta` (grace
        # window) or already `expired` (nightly flipped them). We use
        # the delivery row on `day30_expiry` as the flag.
        expired_delivered = await db.beta_milestone_deliveries.find_one(
            {"user_id": user["id"], "milestone": _M_DAY30_EXPIRY},
        )
        expired_dismissed = await db.beta_milestone_deliveries.find_one(
            {"user_id": user["id"], "milestone": "day30_prompt_dismissed"},
        )
        if status == "expired" and expired_delivered and not expired_dismissed:
            payload = dict(_PROMPT_COPY[_M_DAY30_EXPIRY])
            payload["milestone"] = "day30_prompt"
            payload["founding_still_available"] = bool(fresh.get("founding_eligible"))
            return payload

        if status != "beta":
            return {}

        days = _days_remaining(fresh)
        if days is None or days < 0:
            return {}

        # Pick the tightest in-app milestone that (a) is due and
        # (b) hasn't been dismissed yet.
        for threshold, ms in ((2, _M_DAY28_PROMPT),
                              (5, _M_DAY25_SURVEY),
                              (9, _M_DAY21_PROMPT)):
            if days > threshold:
                continue
            already = await db.beta_milestone_deliveries.find_one(
                {"user_id": user["id"], "milestone": f"{ms}_dismissed"},
            )
            if already:
                continue
            payload = dict(_PROMPT_COPY[ms])
            payload["milestone"] = ms
            payload["days_remaining"] = days
            return payload
        return {}

    @api.post("/beta/milestone/dismiss", tags=["beta"])
    async def dismiss_milestone(body: DismissBody, user: dict = Depends(current_user)):
        await db.beta_milestone_deliveries.update_one(
            {"user_id": user["id"], "milestone": f"{body.milestone}_dismissed"},
            {"$setOnInsert": {"delivered_at": _iso_now()}},
            upsert=True,
        )
        return {"ok": True}

    @api.get("/beta/survey/mine", tags=["beta"])
    async def my_survey(user: dict = Depends(current_user)):
        s = await db.beta_survey_responses.find_one(
            {"user_id": user["id"]}, {"_id": 0},
        )
        return s or {}

    @api.post("/beta/survey", tags=["beta"])
    async def submit_survey(body: SurveyBody, user: dict = Depends(current_user)):
        # One response per user forever.
        existing = await db.beta_survey_responses.find_one({"user_id": user["id"]})
        if existing:
            return {"ok": True, "already_submitted": True}
        row = {
            "id": new_id(),
            "user_id": user["id"],
            "submitted_at": _iso_now(),
            "experience_rating": body.experience_rating,
            "most_valuable": (body.most_valuable or "").strip() or None,
            "could_be_better": (body.could_be_better or "").strip() or None,
            "recommendation_rating": body.recommendation_rating,
            "continuation_blocker": (body.continuation_blocker or "").strip() or None,
        }
        await db.beta_survey_responses.insert_one(row)
        return {"ok": True}

    # --------- Coach-facing ---------

    @api.get("/admin/beta/conversion-cohort", tags=["admin"])
    async def conversion_cohort(_: dict = Depends(require_role("coach"))):
        """Cohort = anyone who was ever plausibly beta.

        Cheapest reliable definition without a new tracking system:
        `trial_ends_at IS NOT NULL AND (membership_status IN (beta, expired)
         OR beta_milestone_deliveries has any row for this user)`.

        Anyone who had a beta window (`trial_ends_at`) is included;
        conversion is inferred from their CURRENT membership_status
        being `active` / `cancellation_scheduled` (paid Stripe sub) —
        `complimentary` explicitly does NOT count as conversion.
        """
        # Fast path: users with a milestone row → they were beta at some point.
        ever_beta_ids = await db.beta_milestone_deliveries.distinct("user_id")

        # Plus current beta / expired users who may not have hit a milestone yet.
        current = await db.users.find(
            {"$or": [
                {"membership_status": {"$in": ["beta", "expired"]}},
                {"id": {"$in": ever_beta_ids}},
            ]},
            {"_id": 0, "id": 1, "name": 1, "email": 1,
             "membership_status": 1, "membership_tier": 1,
             "trial_ends_at": 1, "founding_eligible": 1,
             "is_founding_member": 1},
        ).to_list(5000)

        # Bulk-fetch surveys + last milestone delivery per user (client-side join).
        surveys = {s["user_id"]: s async for s in db.beta_survey_responses.find(
            {}, {"_id": 0, "user_id": 1, "submitted_at": 1},
        )}
        # Last non-dismissed milestone per user for "current milestone" column.
        last_ms: dict[str, dict] = {}
        cur = db.beta_milestone_deliveries.find(
            {"milestone": {"$in": [_M_DAY21_PROMPT, _M_DAY25_SURVEY,
                                   _M_DAY28_PROMPT, _M_DAY30_EXPIRY]}},
            {"_id": 0, "user_id": 1, "milestone": 1, "delivered_at": 1},
        ).sort([("delivered_at", 1)])
        async for row in cur:
            last_ms[row["user_id"]] = row  # last write wins → most recent

        out = []
        for u in current:
            uid = u["id"]
            trial_end = _parse_iso(u.get("trial_ends_at"))
            days_left = None
            if trial_end is not None:
                delta = (trial_end - _now()).total_seconds() / 86400.0
                import math
                days_left = math.ceil(delta) if delta >= 0 else int(delta)

            status = u.get("membership_status")
            converted = status in ("active", "cancellation_scheduled", "past_due")
            out.append({
                "id": uid,
                "name": u.get("name"),
                "email": u.get("email"),
                "current_membership_status": status,
                "days_remaining": days_left,
                "current_milestone": (last_ms.get(uid) or {}).get("milestone"),
                "survey_completed": uid in surveys,
                "converted": converted,
                "converted_tier": u.get("membership_tier") if converted else None,
                "founding_eligible": bool(u.get("founding_eligible")),
                "is_founding_member": bool(u.get("is_founding_member")),
            })
        # Sort: current beta first, then expired, then converted.
        rank = {"beta": 0, "expired": 1}
        out.sort(key=lambda r: (rank.get(r["current_membership_status"], 2),
                                r.get("days_remaining") or 999))
        return {"cohort": out, "count": len(out)}

    @api.get("/admin/beta/survey-results", tags=["admin"])
    async def survey_results(_: dict = Depends(require_role("coach"))):
        rows = await db.beta_survey_responses.find(
            {}, {"_id": 0},
        ).sort([("submitted_at", -1)]).to_list(2000)
        # Enrich with client name/email for the coach view.
        user_ids = [r["user_id"] for r in rows]
        users = {u["id"]: u async for u in db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "name": 1, "email": 1},
        )}
        for r in rows:
            u = users.get(r["user_id"]) or {}
            r["client_name"] = u.get("name")
            r["client_email"] = u.get("email")
        return {"responses": rows, "count": len(rows)}


# ===================================================================== #
# One-shot index ensure — called from server.py startup                   #
# ===================================================================== #

async def ensure_indexes(db: Any) -> None:
    await db.beta_milestone_deliveries.create_index(
        [("user_id", 1), ("milestone", 1)], unique=True,
    )
    await db.beta_survey_responses.create_index("user_id", unique=True)
