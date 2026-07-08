"""Shared dependencies for router modules.

Imports are intentionally lazy where possible to avoid circular imports with
server.py. This module is created during the incremental refactor of the
5000+ line server.py; over time more helpers will live here directly.
"""
from __future__ import annotations

from typing import Any

# These are re-exported from server.py so router modules have a single import
# surface. As modules are extracted, we can move the definitions here.
def _bind():
    import server  # type: ignore
    return {
        "db": server.db,
        "current_user": server.current_user,
        "require_role": server.require_role,
        "new_id": server.new_id,
        "now_iso": server.now_iso,
        "logger": server.logger,
    }


class Ctx:
    """Late-bound context object populated by server.py on startup."""
    db: Any = None
    current_user: Any = None
    require_role: Any = None
    new_id: Any = None
    now_iso: Any = None
    logger: Any = None


ctx = Ctx()


def bind_ctx(**kwargs: Any) -> None:
    """Called by server.py before mounting routers so modules can reference
    shared helpers without circular imports."""
    for k, v in kwargs.items():
        setattr(ctx, k, v)
