"""Unit tests for resolve_workspace_id — query-aware workspace resolution
with a JWT access check (family-B Control Center scoping)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from metatron.api.dependencies import resolve_workspace_id
from metatron.core.config import Settings


def _request(*, workspace_ids: list[str], query: dict[str, str] | None = None) -> Any:
    """Minimal stand-in for a FastAPI Request consumed by resolve_workspace_id."""
    settings = Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=False,
        METATRON_SECRET_KEY="test-secret",
    )
    state = SimpleNamespace(user={"workspace_ids": workspace_ids})
    app = SimpleNamespace(state=SimpleNamespace(settings=settings))
    return SimpleNamespace(state=state, app=app, query_params=query or {})


def test_absent_param_falls_back_to_auth_derived() -> None:
    # workspace_ids[0] (not "*") -> returned, query ignored
    req = _request(workspace_ids=["ws-a", "ws-b"], query={})
    assert resolve_workspace_id(req) == "ws-a"


def test_absent_param_star_token_uses_default() -> None:
    req = _request(workspace_ids=["*"], query={})
    # default_workspace_id from Settings
    assert resolve_workspace_id(req) == req.app.state.settings.default_workspace_id


def test_star_token_grants_any_requested_workspace() -> None:
    req = _request(workspace_ids=["*"], query={"workspace_id": "ws-x"})
    assert resolve_workspace_id(req) == "ws-x"


def test_member_token_grants_listed_workspace() -> None:
    req = _request(workspace_ids=["ws-a", "ws-b"], query={"workspace_id": "ws-b"})
    assert resolve_workspace_id(req) == "ws-b"


def test_non_member_request_is_forbidden() -> None:
    req = _request(workspace_ids=["ws-a"], query={"workspace_id": "ws-x"})
    with pytest.raises(HTTPException) as exc:
        resolve_workspace_id(req)
    assert exc.value.status_code == 403


def test_empty_workspace_ids_is_unrestricted() -> None:
    # Empty list == unscoped (mirrors get_workspace_id's fallback semantics and
    # the AUTH_ENABLED=false {} case). The default admin token has [].
    req = _request(workspace_ids=[], query={"workspace_id": "ws-x"})
    assert resolve_workspace_id(req) == "ws-x"


def test_no_user_state_is_unrestricted() -> None:
    # AUTH_ENABLED=false -> request.state.user == {} -> allowed == [] -> permit.
    from types import SimpleNamespace

    settings = Settings(
        METATRON_ENV="development",
        AUTH_ENABLED=False,
        METATRON_SECRET_KEY="test-secret",
    )
    req = SimpleNamespace(
        state=SimpleNamespace(user={}),
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
        query_params={"workspace_id": "ws-x"},
    )
    assert resolve_workspace_id(req) == "ws-x"


def test_explicit_star_value_is_ignored() -> None:
    # "*" is not a real workspace; treat as absent -> auth-derived
    req = _request(workspace_ids=["*"], query={"workspace_id": "*"})
    assert resolve_workspace_id(req) == req.app.state.settings.default_workspace_id
