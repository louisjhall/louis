"""feature_coach_docs — serve the coach-facing markdown docs
(`/app/docs/*.md`) over HTTP so the coach can open them in a browser
or link the URLs into ChatGPT-generated prompts.

Endpoints (public, no auth — these are read-only coach docs):
  GET /api/docs/programme-import-schema  → PROGRAMME_IMPORT_SCHEMA.md
  GET /api/docs/chatgpt-master-prompt    → CHATGPT_MASTER_PROMPT.md

Response is `text/markdown; charset=utf-8`. Browsers usually render as
plain text, which is fine for copy-paste-into-ChatGPT workflows.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from server import api, logger


DOCS_ROOT = Path("/app/docs")

_ALLOWED = {
    "programme-import-schema": "PROGRAMME_IMPORT_SCHEMA.md",
    "chatgpt-master-prompt": "CHATGPT_MASTER_PROMPT.md",
}


def _read_doc(slug: str) -> str:
    fname = _ALLOWED.get(slug)
    if not fname:
        raise HTTPException(404, f"unknown doc slug {slug!r}")
    path = DOCS_ROOT / fname
    if not path.exists():
        raise HTTPException(404, f"doc file missing on disk: {fname}")
    return path.read_text(encoding="utf-8")


@api.get("/docs/programme-import-schema", response_class=PlainTextResponse)
async def get_programme_import_schema_doc() -> PlainTextResponse:
    return PlainTextResponse(
        _read_doc("programme-import-schema"),
        media_type="text/markdown; charset=utf-8",
    )


@api.get("/docs/chatgpt-master-prompt", response_class=PlainTextResponse)
async def get_chatgpt_master_prompt_doc() -> PlainTextResponse:
    return PlainTextResponse(
        _read_doc("chatgpt-master-prompt"),
        media_type="text/markdown; charset=utf-8",
    )


logger.info(
    "feature_coach_docs: /api/docs/programme-import-schema + "
    "/api/docs/chatgpt-master-prompt registered",
)
