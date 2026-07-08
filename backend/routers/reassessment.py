"""Living Profile — Re-assessment prompt endpoints.

STATUS: extraction template only. The endpoints are currently defined in
server.py; they will be migrated here in a future task. This module
demonstrates the router-factory pattern used throughout /app/backend/routers/.
"""
from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class ReassessmentDismissBody(BaseModel):
    prompt_id: Optional[str] = None
    kind: Optional[str] = None


def build_router(current_user, db, now_iso) -> APIRouter:
    """Factory used by server.py to mount the reassessment endpoints.

    Usage (in server.py, once these endpoints are removed from server.py):

        from routers.reassessment import build_router as build_reassessment_router
        api.include_router(build_reassessment_router(current_user, db, now_iso))
    """
    r = APIRouter(prefix="/reassessment", tags=["reassessment"])

    @r.get("/prompts")
    async def prompts(user: dict = Depends(current_user)):
        rows = await db.reassessment_prompts.find(
            {"user_id": user["id"], "dismissed": False},
            {"_id": 0},
        ).sort("created_at", -1).to_list(20)
        return {"prompts": rows}

    @r.post("/dismiss")
    async def dismiss(body: ReassessmentDismissBody, user: dict = Depends(current_user)):
        q: dict[str, Any] = {"user_id": user["id"], "dismissed": False}
        if body.prompt_id:
            q["id"] = body.prompt_id
        elif body.kind:
            q["kind"] = body.kind
        else:
            raise HTTPException(400, "prompt_id or kind required")
        res = await db.reassessment_prompts.update_many(
            q, {"$set": {"dismissed": True, "dismissed_at": now_iso()}}
        )
        return {"dismissed": res.modified_count}

    return r
