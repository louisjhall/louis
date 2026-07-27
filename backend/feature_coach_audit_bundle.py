"""
feature_coach_audit_bundle — serves the collated Coach Dashboard audit
(5 companion documents combined into a single markdown file) at a stable URL.

No auth required — same pattern as `/api/coach/videos/{id}/file`. Change
to a signed URL if this is ever exposed beyond internal coach use.
"""
from __future__ import annotations

from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from server import api, logger

BUNDLE_PATH = Path("/app/backend/uploads/coach_dashboard_audit_bundle.md")


@api.get("/coach/dashboard-audit/bundle")
async def coach_audit_bundle():
    """Serves the collated audit as a single markdown file."""
    if not BUNDLE_PATH.exists():
        raise HTTPException(404, "Audit bundle not built yet")
    return FileResponse(
        str(BUNDLE_PATH),
        media_type="text/markdown; charset=utf-8",
        filename="crewfit_coach_dashboard_audit_bundle.md",
    )


@api.get("/coach/dashboard-audit/bundle.txt")
async def coach_audit_bundle_txt():
    """Same content served as plain-text for browsers that would rather render inline."""
    if not BUNDLE_PATH.exists():
        raise HTTPException(404, "Audit bundle not built yet")
    return PlainTextResponse(
        BUNDLE_PATH.read_text(),
        media_type="text/plain; charset=utf-8",
    )


logger.info("feature_coach_audit_bundle: /api/coach/dashboard-audit/bundle registered")
