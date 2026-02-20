"""Auth API — login endpoint."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from metatron.auth.jwt import create_token
from metatron.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    role: str


@router.post("/auth/login", response_model=LoginResponse)
def login(req: LoginRequest) -> LoginResponse:
    """Authenticate with shared password, get JWT token."""
    settings = get_settings()

    if req.password != settings.auth_password:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(
        user_id="admin",
        role="admin",
        workspace_ids=["*"],
        secret_key=settings.secret_key,
        expiry_hours=24,
    )

    logger.info("auth.login.success", user_id="admin")
    return LoginResponse(token=token, user_id="admin", role="admin")


@router.get("/auth/me")
def me() -> dict[str, str]:
    """Check if token is valid. Protected by middleware when auth enabled."""
    return {"status": "ok", "user_id": "admin", "role": "admin"}
