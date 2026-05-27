"""agents list endpoint honours ?workspace_id with a JWT access check."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from metatron.agents.service import AgentRegistryService
from metatron.api.dependencies import get_agent_registry_service
from metatron.api.routes.agents import router as agents_router
from metatron.auth.dependencies import get_current_user
from metatron.core.config import Settings
from metatron.core.models import Role, User


def _settings() -> Settings:
    return Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=False,
        METATRON_SECRET_KEY="test-secret",
    )


def _user() -> User:
    return User(
        id="u1",
        username="t",
        email="t@x.com",
        role=Role.VIEWER,
        workspace_ids=["*"],
    )


def _client(workspace_ids: list[str], service: AsyncMock) -> TestClient:
    app = FastAPI()
    app.state.settings = _settings()
    app.include_router(agents_router, prefix="/api/v1")
    app.dependency_overrides[get_agent_registry_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: _user()

    @app.middleware("http")
    async def _inject(request, call_next):  # type: ignore[no-untyped-def]
        request.state.user = {"workspace_ids": workspace_ids}
        return await call_next(request)

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def service() -> AsyncMock:
    mock = AsyncMock(spec=AgentRegistryService)
    mock.list_agents.return_value = []
    return mock


def test_list_returns_200_with_workspace_param(service: AsyncMock) -> None:
    client = _client(["*"], service)
    resp = client.get("/api/v1/agents/?workspace_id=ws-x")
    assert resp.status_code == 200


def test_list_forbidden_for_non_member(service: AsyncMock) -> None:
    client = _client(["ws-a"], service)
    resp = client.get("/api/v1/agents/?workspace_id=ws-x")
    assert resp.status_code == 403


def test_workspace_id_declared_on_resource_keyed_paths(service: AsyncMock) -> None:
    """Router-level workspace_scope dependency must surface ?workspace_id in the
    OpenAPI schema for EVERY agents route, incl. resource-keyed ones (variant B)."""
    client = _client(["*"], service)
    schema = client.app.openapi()  # type: ignore[attr-defined]

    checked = 0
    for path, item in schema["paths"].items():
        if not path.startswith("/api/v1/agents"):
            continue
        for method, op in item.items():
            if method not in {"get", "post", "put", "delete"}:
                continue
            names = {p["name"] for p in op.get("parameters", [])}
            assert "workspace_id" in names, f"{method.upper()} {path} missing workspace_id"
            checked += 1
    # Sanity: we actually inspected resource-keyed operations, not just the list.
    assert checked >= 5
