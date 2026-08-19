"""Iter188 · Coach-facing override for how the workout player renders
each library exercise (timer vs reps vs cardio).

The frontend classifier in `src/lib/workoutMode.ts::isTimeBased` catches
90 %+ of hold / cardio / carry exercises via a name-regex + reps-regex.
For the long tail (unusual names, coach-imported strength lifts that
should actually be held, etc.) the coach can pin an explicit
`logging_type_override` on the library row and the classifier will
respect it.

Field
-----
  `exercises_v2.logging_type_override` ∈ {null, "timer", "reps", "cardio"}

  · null      — classifier decides
  · "timer"   — force hold-timer UI (planks, wall sits, carries)
  · "cardio"  — force cardio stopwatch UI (bike, treadmill, run)
  · "reps"    — force strength REPS/WEIGHT UI (regression escape hatch)

Endpoints
---------
  GET   /api/coach/library/logging-overrides
        · Lightweight lookup map for the client-side classifier.
        · Returns { by_id: {id → type}, by_name: {name_lower → type} }.
        · Cache-friendly (5-min TTL suggested on the frontend).

  PATCH /api/coach/library/exercise/{id}/logging-type
        · Body: { logging_type: "timer" | "cardio" | "reps" | null }
        · Sets or clears the override. Returns the updated row.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import Depends, HTTPException, APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("crewfit.feature_logging_type_override")

router = APIRouter()

# Values the frontend classifier recognises.
LoggingOverride = Literal["timer", "cardio", "reps"]


class LoggingOverrideBody(BaseModel):
    logging_type: Optional[LoggingOverride] = Field(
        default=None,
        description="null clears the override; otherwise timer/cardio/reps",
    )


def register(
    api: APIRouter,
    db,
    require_role,
) -> None:
    """Wire the two endpoints onto the main /api router.

    Kept as a `register(...)` fn rather than module-level decorators so the
    override module doesn't need to import `server.py` (avoids a circular).
    """

    @api.get("/coach/library/logging-overrides")
    async def _get_overrides(_coach: dict = Depends(require_role("coach"))):
        """Lightweight map for the client-side classifier. Only rows with a
        non-null override are returned (typically < 100 rows), so the
        payload stays tiny even on a 1000-exercise library."""
        by_id: dict[str, str] = {}
        by_name: dict[str, str] = {}
        async for r in db.exercises_v2.find(
            {"logging_type_override": {"$in": ["timer", "cardio", "reps"]}},
            {"_id": 0, "id": 1, "exercise_name": 1, "logging_type_override": 1},
        ):
            lt = r.get("logging_type_override")
            if r.get("id"):
                by_id[r["id"]] = lt
            nm = str(r.get("exercise_name") or "").strip().lower()
            if nm:
                by_name[nm] = lt
        return {"by_id": by_id, "by_name": by_name}

    @api.patch("/coach/library/exercise/{exercise_id}/logging-type")
    async def _patch_override(
        exercise_id: str,
        body: LoggingOverrideBody,
        coach: dict = Depends(require_role("coach")),
    ):
        """Set or clear the logging-type override on a library row."""
        res = await db.exercises_v2.update_one(
            {"id": exercise_id},
            {"$set": {
                "logging_type_override": body.logging_type,  # null clears
                "logging_type_override_by": coach.get("id"),
                "logging_type_override_at": _now_iso(),
            }},
        )
        if res.matched_count == 0:
            raise HTTPException(404, "exercise not found")
        row = await db.exercises_v2.find_one(
            {"id": exercise_id},
            {"_id": 0, "id": 1, "exercise_name": 1, "logging_type_override": 1},
        )
        return {"exercise": row}

    logger.info(
        "feature_logging_type_override: /coach/library/logging-overrides + "
        "PATCH /coach/library/exercise/{id}/logging-type registered"
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
