from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Any

from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from starlette.exceptions import HTTPException

from .call_graph.storage import CallGraphDB

# Per-request user — set by AuthMiddleware, read by get_current_user() and handlers.
_current_user: ContextVar[dict | None] = ContextVar("_current_user", default=None)

# DB reference set during server lifespan (or in tests via set_auth_db).
# Avoids passing db through middleware constructor and circular imports.
_auth_db: CallGraphDB | None = None


def set_auth_db(db: CallGraphDB) -> None:
    """Register the DB for use by AuthMiddleware. Call once during server startup."""
    global _auth_db
    _auth_db = db


def get_current_user() -> dict | None:
    """Return the authenticated user for the current request, or None."""
    return _current_user.get()


class AuthMiddleware(Middleware):
    """Resolve X-API-Key header to a user and store in request context."""

    async def on_message(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        raw_key = None
        with contextlib.suppress(Exception):
            raw_key = get_http_request().headers.get("X-API-Key")
        user = None
        if raw_key and _auth_db is not None:
            user = await _auth_db.get_user_by_key(raw_key)
        token = _current_user.set(user)
        try:
            return await call_next(context)
        finally:
            _current_user.reset(token)


async def check_permission(
    user: dict | None,
    project_id: str,
    operation: str,
    db: CallGraphDB,
) -> None:
    """Raise HTTPException if user may not perform operation on project_id.

    operation: "read" | "write"
    Raises 401 if user is None (unauthenticated).
    Raises 403 if authenticated but not permitted.
    Returns None on success.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    allowed = await db.check_project_access(user["id"], project_id, operation)
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")
