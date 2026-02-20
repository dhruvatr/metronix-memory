"""Optional JWT auth middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from metatron.auth.jwt import verify_token
from metatron.core.config import Settings

PUBLIC_PATHS = {
    "/health", "/ready", "/metrics", "/metrics/reset",
    "/api/v1/auth/login",
}


class OptionalAuthMiddleware(BaseHTTPMiddleware):
    """When AUTH_ENABLED=true, require JWT on /api/v1/ endpoints."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        settings: Settings = request.app.state.settings

        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path.rstrip("/")
        if path in PUBLIC_PATHS:
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]
        try:
            verify_token(token, settings.secret_key)
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
