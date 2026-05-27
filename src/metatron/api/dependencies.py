"""Shared FastAPI dependencies — DI for stores and services.

These Depends() functions provide access to initialized stores
and services. They pull instances from app.state (set during lifespan).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import (  # noqa: TC002 — FastAPI Depends parameters need runtime type
    HTTPException,
    Query,
    Request,
)

from metatron.core.config import Settings  # noqa: TC001 — runtime annotations in function bodies
from metatron.llm.telemetry import set_telemetry_context

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from metatron.agents.service import AgentRegistryService
    from metatron.knowledge.service import RawDocumentReadService
    from metatron.llm.telemetry import TelemetryContext
    from metatron.memory.health import MemoryHealthService
    from metatron.memory.service import MemoryService
    from metatron.memory.snapshot import MemorySnapshotService


async def get_settings(request: Request) -> Settings:
    """Get application settings from app state."""
    return request.app.state.settings


async def get_postgres(request: Request):  # type: ignore[no-untyped-def]
    """Get PostgresStore from app state.

    Returns:
        PostgresStore instance.
    """
    # TODO: implement once stores are initialized in lifespan
    # return request.app.state.postgres
    raise NotImplementedError("PostgresStore not initialized")


async def get_vector_store(request: Request):  # type: ignore[no-untyped-def]
    """Get QdrantVectorStore from app state."""
    # TODO: implement
    # return request.app.state.qdrant
    raise NotImplementedError("VectorStore not initialized")


async def get_graph_store(request: Request):  # type: ignore[no-untyped-def]
    """Get Neo4j GraphStore from app state."""
    # TODO: implement
    # return request.app.state.neo4j
    raise NotImplementedError("GraphStore not initialized")


async def get_llm_provider(request: Request):  # type: ignore[no-untyped-def]
    """Get LLM provider from app state."""
    # TODO: implement
    # return request.app.state.ollama
    raise NotImplementedError("LLMProvider not initialized")


def get_workspace_id(request: Request) -> str:
    """Resolve workspace_id from auth state or settings default.

    Never reads from query or body — workspace comes from the authenticated
    user. Route handlers should import this helper rather than re-implementing
    the fallback chain locally.
    """
    user = getattr(request.state, "user", {}) or {}
    workspace_ids = user.get("workspace_ids", [])
    if workspace_ids and workspace_ids[0] != "*":
        return str(workspace_ids[0])
    settings: Settings = request.app.state.settings
    return settings.default_workspace_id


# Backwards-compatible alias — older callers use the private name.
_resolve_workspace_id = get_workspace_id


def resolve_workspace_id(request: Request) -> str:
    """Resolve workspace_id from an optional ``?workspace_id`` query param,
    access-checked against the caller's JWT.

    - param absent (or literal ``"*"``) -> ``get_workspace_id(request)``
      (auth-derived, unchanged behaviour).
    - param present, caller is unscoped (empty ``workspace_ids`` — same
      "not confined to specific workspaces" meaning ``get_workspace_id`` already
      gives ``[]``) or holds ``"*"`` or the param is in the caller's
      ``workspace_ids`` -> the requested workspace is returned.
    - param present, caller is confined to specific workspaces that do not
      include it -> ``HTTPException(403)``.

    Reads only ``request.query_params`` and ``request.state.user`` — no
    WorkspaceManager lookup. A nonexistent workspace yields an empty result set
    downstream rather than a 404.

    Note: an empty ``workspace_ids`` is treated as unrestricted, matching both
    ``get_workspace_id`` (which falls back to the default workspace rather than
    denying) and the ``AUTH_ENABLED=false`` case (where ``request.state.user``
    is ``{}``). When a real multi-tenant RBAC model lands, revisit whether an
    empty list should mean "all" or "none".
    """
    requested = request.query_params.get("workspace_id")
    if not requested or requested == "*":
        return get_workspace_id(request)
    user = getattr(request.state, "user", {}) or {}
    allowed = user.get("workspace_ids", []) or []
    if not allowed or "*" in allowed or requested in allowed:
        return str(requested)
    raise HTTPException(status_code=403, detail=f"No access to workspace '{requested}'")


def workspace_scope(
    request: Request,
    workspace_id: str | None = Query(  # noqa: ARG001 — declared for OpenAPI; value read via request
        None,
        description="Target workspace (auth-checked; overrides the JWT-derived default)",
    ),
) -> str:
    """Router-level dependency for REST family B (agents / memory / knowledge /
    snapshots).

    Two jobs in one place so individual handlers stay clean:

    1. **Declares** ``?workspace_id`` as an optional query parameter — because it
       is attached to the router, FastAPI surfaces the param in the OpenAPI schema
       for *every* route under that router, so typed frontend clients can pass it.
    2. **Enforces** the JWT access check via :func:`resolve_workspace_id` — raises
       403 for a workspace the caller may not target. This runs even when a
       handler's service dependency is overridden in tests, so enforcement is
       uniform.

    The ``workspace_id`` parameter is intentionally unused in the body — the value
    is read from ``request.query_params`` by :func:`resolve_workspace_id`. Returns
    the resolved workspace id; service DI helpers re-resolve the same value.
    """
    return resolve_workspace_id(request)


def build_telemetry_context_cm(
    request: Request,
    *,
    source: str,
) -> AbstractContextManager[TelemetryContext]:
    """Build a TelemetryContext context-manager from the current request.

    Resolves workspace_id via :func:`get_workspace_id` (handles the ``*``
    admin case), pulls user_id from auth state, generates a fresh
    correlation_id. Returns the context-manager *unentered* — callers use
    ``with build_telemetry_context_cm(request, source="rest"): ...``.

    Centralising this here keeps chat / openai-compat / future routes from
    re-implementing the same five-line dance.
    """
    workspace_id = get_workspace_id(request)
    user = getattr(request.state, "user", {}) or {}
    user_id: str | None = user.get("id") or user.get("user_id")
    return set_telemetry_context(
        workspace_id=workspace_id,
        user_id=user_id,
        source=source,
        correlation_id=uuid4(),
    )


def get_memory_service(request: Request) -> MemoryService:
    """Return (and lazily construct) a per-workspace MemoryService.

    PostgreSQL engine, Redis cache and memory PG store are shared across
    workspaces on ``app.state``. Qdrant store and search service are per
    workspace because the Qdrant collection name is workspace-scoped.

    TODO: wire disposal of ``memory_pg_engine``, ``redis_cache`` and cached
    ``MemoryQdrantStore`` clients into the app lifespan shutdown handler —
    these connections currently outlive request scope but are never closed.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.memory.search import MemorySearchService
    from metatron.memory.service import MemoryService
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore
    from metatron.storage.memory_redis import RedisSessionCache
    from metatron.storage.redis import RedisStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

    services: dict[str, MemoryService] = getattr(
        request.app.state,
        "memory_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    redis_cache: RedisSessionCache | None = getattr(
        request.app.state,
        "redis_cache",
        None,
    )
    if redis_cache is None:
        redis_store = RedisStore(settings.redis_url)
        redis_cache = RedisSessionCache(
            redis_store,
            default_ttl=settings.memory_session_ttl,
        )
        request.app.state.redis_cache = redis_cache

    pg_store: MemoryPostgresStore | None = getattr(
        request.app.state,
        "memory_pg_store",
        None,
    )
    if pg_store is None:
        engine = getattr(request.app.state, "memory_pg_engine", None)
        if engine is None:
            engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
            request.app.state.memory_pg_engine = engine
        pg_store = MemoryPostgresStore(engine)
        request.app.state.memory_pg_store = pg_store

    qdrant_store = MemoryQdrantStore(
        workspace_id=workspace_id,
        host=settings.qdrant_host,
        port=settings.qdrant_http_port,
    )

    # Wire pg_store into search so graph-leg status post-filter works on the
    # REST path — parity with the MCP path (_memory_deps.py). MTRNIX-324.
    search = MemorySearchService(qdrant=qdrant_store, redis=redis_cache, pg_store=pg_store)

    # Wire freshness_store so review-queue REST endpoints work. MTRNIX-324.
    from metatron.storage.freshness_pg import FreshnessStore

    freshness_store = getattr(request.app.state, "memory_freshness_store", None)
    if freshness_store is None:
        # Engine is already initialised above — reuse it.
        engine = request.app.state.memory_pg_engine
        freshness_store = FreshnessStore(engine)
        request.app.state.memory_freshness_store = freshness_store

    plugin_manager = request.app.state.plugin_manager
    service = MemoryService(
        redis_cache=redis_cache,
        qdrant_store=qdrant_store,
        pg_store=pg_store,
        workspace_id=workspace_id,
        search=search,
        freshness_store=freshness_store,
        event_bus=plugin_manager.get_event_bus(),
    )

    services[workspace_id] = service
    request.app.state.memory_services = services
    return service


def get_agent_registry_service(request: Request) -> AgentRegistryService:
    """Return (and lazily construct) a per-workspace :class:`AgentRegistryService`.

    Shares the PostgreSQL async engine with :func:`get_memory_service` under
    ``app.state.memory_pg_engine``. If neither dependency has run yet, the
    engine is created here and stored under both keys so the first caller
    wins and subsequent callers reuse it.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.agents.persistence import AgentPersistence
    from metatron.agents.service import AgentRegistryService

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

    services: dict[str, AgentRegistryService] = getattr(
        request.app.state,
        "agent_registry_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    engine = getattr(request.app.state, "memory_pg_engine", None)
    if engine is None:
        engine = getattr(request.app.state, "agents_pg_engine", None)
    if engine is None:
        engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
        request.app.state.memory_pg_engine = engine
    request.app.state.agents_pg_engine = engine

    plugin_manager = request.app.state.plugin_manager
    repo = AgentPersistence(engine)
    service = AgentRegistryService(
        repo,
        workspace_id=workspace_id,
        event_bus=plugin_manager.get_event_bus(),
    )

    services[workspace_id] = service
    request.app.state.agent_registry_services = services
    return service


def get_memory_health_service(request: Request) -> MemoryHealthService:
    """Return (and lazily construct) a per-workspace :class:`MemoryHealthService`.

    Shares the PostgreSQL async engine / ``MemoryPostgresStore`` with
    :func:`get_memory_service` so a single connection pool serves both.
    Settings are read from ``app.state.settings``.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.memory.health import MemoryHealthService
    from metatron.storage.memory_postgres import MemoryPostgresStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

    services: dict[str, MemoryHealthService] = getattr(
        request.app.state,
        "memory_health_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    pg_store: MemoryPostgresStore | None = getattr(
        request.app.state,
        "memory_pg_store",
        None,
    )
    if pg_store is None:
        engine = getattr(request.app.state, "memory_pg_engine", None)
        if engine is None:
            engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
            request.app.state.memory_pg_engine = engine
        pg_store = MemoryPostgresStore(engine)
        request.app.state.memory_pg_store = pg_store

    health_service = MemoryHealthService(
        pg_store=pg_store,
        workspace_id=workspace_id,
        settings=settings,
    )

    services[workspace_id] = health_service
    request.app.state.memory_health_services = services
    return health_service


def get_memory_snapshot_service(request: Request) -> MemorySnapshotService:
    """Return (and lazily construct) a per-workspace :class:`MemorySnapshotService`.

    Shares the PostgreSQL async engine / ``MemoryPostgresStore`` with
    :func:`get_memory_service` so a single connection pool serves both. The
    Qdrant store is workspace-scoped (collection name embeds the workspace),
    so we construct it inline — same pattern as :func:`get_memory_service`.
    """
    from pathlib import Path

    from sqlalchemy.ext.asyncio import create_async_engine

    from metatron.memory.snapshot import MemorySnapshotService
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

    services: dict[str, MemorySnapshotService] = getattr(
        request.app.state,
        "memory_snapshot_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    pg_store: MemoryPostgresStore | None = getattr(
        request.app.state,
        "memory_pg_store",
        None,
    )
    if pg_store is None:
        engine = getattr(request.app.state, "memory_pg_engine", None)
        if engine is None:
            engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
            request.app.state.memory_pg_engine = engine
        pg_store = MemoryPostgresStore(engine)
        request.app.state.memory_pg_store = pg_store

    qdrant_store = MemoryQdrantStore(
        workspace_id=workspace_id,
        host=settings.qdrant_host,
        port=settings.qdrant_http_port,
    )

    plugin_manager = request.app.state.plugin_manager
    snapshot_service = MemorySnapshotService(
        pg_store=pg_store,
        qdrant_store=qdrant_store,
        workspace_id=workspace_id,
        snapshot_dir=Path(settings.snapshot_dir),
        max_file_bytes=settings.snapshot_max_file_bytes,
        event_bus=plugin_manager.get_event_bus(),
    )

    services[workspace_id] = snapshot_service
    request.app.state.memory_snapshot_services = services
    return snapshot_service


def get_raw_document_service(request: Request) -> RawDocumentReadService:
    """Return (and lazily construct) a per-workspace :class:`RawDocumentReadService`.

    Reuses ``app.state.postgres`` (the shared :class:`~metatron.storage.postgres.PostgresStore`
    initialised in the lifespan) so no new connection pool is created.  If the
    lifespan store is not yet available — e.g. in isolated test setups — a new
    ``PostgresStore`` is constructed from ``settings.postgres_dsn``.

    Cached per workspace on ``app.state.raw_document_services`` (same pattern
    as :func:`get_memory_health_service`).
    """
    from metatron.knowledge.service import RawDocumentReadService
    from metatron.storage.postgres import PostgresStore

    settings: Settings = request.app.state.settings
    workspace_id = resolve_workspace_id(request)

    services: dict[str, RawDocumentReadService] = getattr(
        request.app.state,
        "raw_document_services",
        {},
    )
    cached = services.get(workspace_id)
    if cached is not None:
        return cached

    # Prefer the shared PostgresStore created in lifespan (app.state.postgres).
    # Fall back to constructing a new one from settings if the lifespan store is
    # not present (common in minimal test-app setups).
    pg_store: PostgresStore | None = getattr(request.app.state, "postgres", None)
    if pg_store is None:
        pg_store = PostgresStore(settings.postgres_dsn)
        request.app.state.postgres = pg_store

    service = RawDocumentReadService(pg_store, workspace_id=workspace_id)

    services[workspace_id] = service
    request.app.state.raw_document_services = services
    return service
