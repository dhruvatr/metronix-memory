"""X-Agent-Id middleware — populates the ``current_agent_id`` contextvar.

Applied in ``create_app()`` for mounted paths (REST, OpenAI-compat, /mcp) and
separately inside ``mcp/server.py:run_http()`` for the standalone streamable-HTTP
transport (wired in later tasks). Invalid or missing header → contextvar stays
``None``; the request is NOT rejected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

from metronix.activity.context import bind_agent_id, current_agent_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = structlog.get_logger(__name__)

_HEADER = "X-Agent-Id"
_MAX_LEN = 64


def _validate(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) == 0 or len(value) > _MAX_LEN:
        return None
    # Printable ASCII only — no control chars, no UTF-8 surprises
    if not all(32 <= ord(c) < 127 for c in value):
        return None
    return value


class AgentIdContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw = request.headers.get(_HEADER)
        value = _validate(raw)
        if raw is not None and value is None:
            logger.warning(
                "agent_id.header_rejected",
                header_len=len(raw),
            )

        token = bind_agent_id(value)
        try:
            return await call_next(request)
        finally:
            current_agent_id.reset(token)
