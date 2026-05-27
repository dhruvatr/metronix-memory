# API

## Overview
L6 — top layer. FastAPI application factory, lifespan management, middleware stack,
and all REST endpoints. Creates the app via `create_app(settings)` factory for
isolated testing. Mounts MCP server at `/mcp`.

## Files

### `app.py`
`create_app(settings) -> FastAPI` — application factory.

**Startup order in `create_app()`:**
1. Plugin discovery — `PluginManager()` + `discover_plugins(manager)`
2. CORS middleware — origins from `Settings.cors_origins_list`
3. Plugin middlewares — wired via `plugin_manager.apply_to_app()`
4. `OptionalAuthMiddleware` — outermost, runs first
5. Core routers included at `/api/v1/...`
6. Plugin routers included after core
7. MCP ASGI handler mounted at `/mcp` (GET, POST, DELETE)

**`lifespan()` startup:**
1. `configure_logging()`
2. Auto-run DB migrations via `asyncio.to_thread(run_migrations_sync, ...)`
3. `mcp_server.session_manager.run()` (async context manager)

**Note:** Store initialization (Postgres, Qdrant, Neo4j, Ollama) is TODOed in
lifespan — currently all `get_postgres/vector/graph/llm` dependencies raise `NotImplementedError`.

`main()` — entry point for `python -m metatron.api.app`, runs uvicorn with `factory=True`.

### `middleware.py`
`OptionalAuthMiddleware(BaseHTTPMiddleware)` — JWT gate.

- Always sets `request.state.user = {}` (downstream never gets AttributeError)
- If `AUTH_ENABLED=False` → passes through
- `PUBLIC_PATHS`: `/health`, `/ready`, `/metrics`, `/metrics/reset`, `/api/v1/auth/login`
- OPTIONS requests always pass through (CORS preflight)
- Validates `Bearer` token via `jwt.verify_token()`, sets `request.state.user` dict on success
- Returns 401 JSON on missing or invalid token

### `dependencies.py`
Shared `Depends()` functions:
- `get_settings(request) -> Settings` — from `app.state.settings`
- `get_postgres(request)` — **NotImplementedError** (TODO: return `app.state.postgres`)
- `get_vector_store(request)` — **NotImplementedError**
- `get_graph_store(request)` — **NotImplementedError**
- `get_llm_provider(request)` — **NotImplementedError**

## Routes

### `routes/health.py`
`GET /health` — liveness: `{"status": "ok"}`
`GET /ready` — readiness: checks Qdrant, Neo4j, Ollama async via `asyncio.to_thread()`

### `routes/auth.py`
`POST /api/v1/auth/login` — shared-password login, returns JWT token.
Password validated against `Settings.auth_password`. Issues token for `"admin"` user with `workspace_ids=["*"]`.

### `routes/chat.py`
`POST /api/v1/chat` — main Q&A endpoint. Calls `await hybrid_search_and_answer()` (async).
`POST /api/v1/chat/stream` — SSE streaming via `EventSourceResponse`.
`POST /api/v1/upload` — file upload + immediate ingestion into workspace.
In-memory conversation history keyed by `user_id` (thread-safe with `threading.Lock`).

### `routes/admin.py`
`GET /api/v1/admin/cleanup/preview` — show what would be deleted (Qdrant + Neo4j)
`POST /api/v1/admin/cleanup` — delete all data (requires `ALLOW_CLEANUP=true`)
`POST /api/v1/admin/cleanup/{workspace_id}` — delete workspace data

### `routes/connections.py`
Full CRUD for DB-based connections + sync trigger. Uses `PostgresStore` for persistence,
`connectors/schemas.py` for validation/masking, and Fernet encryption for credentials.

**New DB-backed CRUD endpoints:**
- `GET /api/v1/connections/schemas` — all connector schemas for UI form rendering
- `POST /api/v1/connections` — create connection (validates config, encrypts, 201)
- `GET /api/v1/connections` — list connections for workspace (masked secrets). Optional `?category=connector|channel` filter
- `GET /api/v1/connections/{id}` — single connection (masked secrets, workspace-scoped)
- `PUT /api/v1/connections/{id}` — update name/config/enabled (handles `***` secret merge)
- `DELETE /api/v1/connections/{id}` — delete (204, workspace-scoped)
- `POST /api/v1/connections/{id}/test` — test connection via `connector.configure()`. Updates error_message on failure
- `POST /api/v1/connections/{id}/sync` — trigger background sync from DB config (connectors only, not channels). After sync, triggers `process_all_unsynced_graphs()` for decoupled graph extraction.

**Helpers:**
- `_get_workspace_id(request)` — extracts from `request.state.user` or falls back to `settings.default_workspace_id`
- `_get_fernet_key(request)` — from `settings.fernet_key` (500 if not set)
- `_get_store(request)` — lazy-inits `PostgresStore` on `app.state.postgres`
- `_run_connection_sync(...)` — background sync task for DB-based connections, updates connection status on completion

**Workspace isolation:** all read/update/delete endpoints verify `workspace_id` matches the current user's workspace.

### `routes/documents.py`
`GET /api/v1/documents/{document_id}/history` — paginated version history.

### `routes/files.py`
`POST /api/v1/files/` — upload file, store on disk, SHA-256, PostgreSQL record
`GET /api/v1/files/` — list files for workspace
`GET /api/v1/files/{id}` — file metadata
`GET /api/v1/files/{id}/verify` — SHA-256 integrity check

### `routes/graph.py`
`GET /api/v1/graph/overview` — all nodes/edges for workspace (max 500 nodes)
`GET /api/v1/graph/expand/{node_id}` — neighborhood expansion for a node
Uses Neo4j directly (neo4j driver). Handles `ServiceUnavailable`/`SessionExpired`.

### `routes/skills.py`
`GET/POST /api/v1/skills` — list / create skills
`GET/PUT/DELETE /api/v1/skills/{id}` — read / update / delete

### `routes/snapshots.py`
Cross-snapshot REST endpoints (MTRNIX-272). Listing and creation live under `/agents/{id}/snapshots`
so agent context is explicit; these routes cover operations where the snapshot id is the primary key.

| Method | Path | RBAC | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/snapshots/{id}/restore` | editor+ | SHA-256 verify → auto `pre_restore` snapshot → PG `BEGIN; DELETE; INSERT; COMMIT` → best-effort Qdrant+Neo4j. Returns `{snapshot_id, pre_restore_snapshot, restored_count}`. 404 if missing, 422 if corrupt |
| GET | `/api/v1/snapshots/diff` | viewer+ | Compare two snapshots of the **same** agent via `?from=<id>&to=<id>&key=source\|content_hash`. Cross-agent → 400. Returns `{from_snapshot_id, to_snapshot_id, key, added, removed, changed}` |

DI helper: `get_memory_snapshot_service(request)` — lazily constructs `MemorySnapshotService` per workspace, shares PG engine with `get_memory_service`.

**Workspace isolation:** snapshot id is resolved through the authenticated workspace — a snapshot id from another workspace resolves to 404.

### `routes/workspaces.py`
`GET/POST /api/v1/workspaces` — list / create workspaces
`GET/PUT/DELETE /api/v1/workspaces/{id}` — read / update / delete
Uses `get_workspace_manager()` singleton.

### `routes/users.py`
`GET /api/v1/users/platform-mappings` — list all platform mappings
`GET /api/v1/users/{user_id}/platform-mappings` — mappings for a specific user
`PUT /api/v1/users/{user_id}/platform-mappings` — update platform mapping
`DELETE /api/v1/users/{user_id}/platform-mappings/{platform}/{platform_user_id}` — delete mapping

### `routes/sync.py`
`GET /api/v1/sync/status` — sync status per connection (TODO stub)
`GET /api/v1/sync/logs` — recent sync log entries (TODO stub)

### `routes/benchmarker.py`
`POST /api/v1/query/trace` — run query with 7-step timing trace for benchmarking.

### `routes/openai_compat.py`
OpenAI-compatible API endpoints for Open WebUI integration:
- `GET /v1/models` — list models (one per workspace)
- `POST /v1/chat/completions` — chat completions (streaming + non-streaming)
- `GET /v1/openapi.json` — stub for connection verification

### `routes/openwebui_import.py`
`POST /api/v1/admin/import-openwebui-users` — import users from existing Open WebUI instance.

### `routes/config.py`
`GET /api/v1/config/features` — feature flag status for UI.

### `routes/finops.py`
`GET /api/v1/finops/time-savings` — time savings metrics.
See `routes/.claude/finops.md` for full documentation.

### `routes/memory.py`
Memory REST API endpoints (workspace-scoped, RBAC-gated):

| Method | Path | RBAC | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/memory/records` | editor+ | Create record — `service.save()` (PG→Qdrant→Neo4j) or `service.cache_session()` for SESSION scope. Returns 201 |
| POST | `/api/v1/memory/search` | viewer+ | Hybrid search via `MemorySearchService.hybrid_search()`. Accepts `status_filter: list[LifecycleStatus] \| None`; **default excludes ARCHIVED + SUPERSEDED**. 503 if search not configured |
| GET | `/api/v1/memory/records` | viewer+ | List records. Query params: `agent_id`, `scope`, `session_id`, `limit` (1..200), `offset` (0..10000), `status_filter` (no default exclusion). Routes to `list_session` or `list_records` |
| DELETE | `/api/v1/memory/records/{id}` | editor+ | Delete record via `service.delete()`. 204 on success, 404 if not in PG |
| GET | `/api/v1/memory/records/{id}` | viewer+ | Single-record fetch by ID. 404 if not found or in a different workspace (cross-workspace isolation enforced) |
| GET | `/api/v1/memory/graph` | viewer+ | Neighbourhood traversal. Required: `seed_record_id`. Optional: `depth` (1..3, default 1), `agent_id`. Returns `{nodes: MemoryRecordResponse[], edges: MemoryGraphEdge[]}`. Bridge edges (REMEMBERS\|ABOUT\|FROM_SESSION\|DERIVED_FROM) are always 2-hop; `depth` controls only the `LINKED_TO` chain. Graceful Neo4j-down |
| GET | `/api/v1/memory/review` | viewer+ | Paginated review queue. Query params: `reason` (optional filter), `limit`, `offset`. Returns `{entries, count, total, limit, offset}`. 503 if `freshness_store` not configured |
| POST | `/api/v1/memory/review/{id}` | editor+ | Resolve review entry. Body: `{action: keep\|archive\|merge_into\|discard, target_record_id?: str (required iff merge_into), notes?: str}`. Returns 204. Emits `MachineEvent` with `actor=user.id`. 503 if `freshness_store` not configured |

**DI helper:** `get_memory_service(request)` — per-workspace cache on `app.state.memory_services`; shared PG engine on `app.state.memory_pg_engine`. Now also wires `freshness_store` (required for the review endpoints) and passes `pg_store` to `MemorySearchService` for graph-leg post-filter parity with the MCP path (MTRNIX-324).

**Workspace resolution:** uses `resolve_workspace_id(request)` from `api.dependencies` — auth-derived by default, with an optional access-checked `?workspace_id` query override on REST family-B endpoints (agents/memory/knowledge); a caller may only target a workspace its JWT grants (`*` or membership), else 403. `get_workspace_id` remains the auth-only base (still used by telemetry / `build_telemetry_context_cm`).

**Schemas:** pydantic v2 request/response models live inline in `routes/memory.py` per codebase convention.

### `routes/agents.py`
Agent registry REST endpoints + memory snapshot sub-routes (MTRNIX-270, MTRNIX-272, MTRNIX-323):

Agent CRUD and lifecycle endpoints follow the pattern from `agents/service.py`. Memory snapshot
endpoints added in MTRNIX-272:

| Method | Path | RBAC | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/agents/{id}/reset` | editor+ | Wipe agent memory. Auto `pre_reset` snapshot before wipe. Returns `{snapshot_id, deleted_count}`. 413 on >10k overflow, 422 if snapshot corrupt, 500 with `snapshot_id` in `detail` when wipe fails after snapshot succeeds |
| POST | `/api/v1/agents/{id}/snapshots` | editor+ | Manual snapshot. Body `{label?: str}`. Returns `MemorySnapshotResponse` (201). 413 on overflow, 422 if corrupt |
| GET | `/api/v1/agents/{id}/snapshots` | viewer+ | List snapshots for agent, newest-first. Returns `{snapshots, count}` |
| GET | `/api/v1/agents/{id}/memory/health` | viewer+ | Read-only memory health snapshot (MTRNIX-277): total ACTIVE / archived counts, 30-day growth timeseries, unused-record count, near-duplicate cluster metrics (SimHash), source distribution. 404 on unknown/cross-workspace agent |

Response models: `MemorySnapshotResponse` (id, workspace_id, agent_id, label, trigger, record_count, content_hash, size_bytes, storage_path, created_at); `MemorySnapshotListResponse` ({snapshots, count}).
Helper `_snapshot_to_response` converts `MemorySnapshot` core model to the response shape.

`MemoryHealthResponse` / `GrowthBucketResponse` — inline pydantic models for the health endpoint.
DI helper: `get_memory_health_service(request)` — per-workspace cache on `app.state.memory_health_services`; shares PG engine with `get_memory_service`.

### `routes/dashboard/__init__.py`
Aggregates 3 sub-routers under `/api/v1/dashboard`.

### `routes/dashboard/overview.py`
`GET /api/v1/dashboard/overview` — workspace stats (doc count, chunk count, etc.)
`GET /api/v1/dashboard/activity` — recent activity timeline
`get_valid_workspace()` — shared dependency for workspace validation.

### `routes/dashboard/sync.py`
`GET /api/v1/dashboard/sync/history` — recent sync history entries with status/duration.

### `routes/dashboard/graph.py`
`GET /api/v1/dashboard/graph/lineage` — raw_documents → chunks → graph_nodes counts
`GET /api/v1/dashboard/graph/orphans` — nodes with no edges

## Key Patterns
- **Factory pattern** — `create_app(settings)` enables isolated test instances
- **Middleware order** — `OptionalAuthMiddleware` is outermost (added last via `add_middleware`), runs first on every request
- **Store dependencies are stubs** — `get_postgres/vector/graph/llm` all raise `NotImplementedError`; routes that need stores import directly (e.g. `from metatron.storage.qdrant import get_hybrid_store`)
- **MCP mount** — uses `StarletteRoute` directly (not `Mount`) to avoid 405 on POST without trailing slash
- **Plugin route isolation** — plugin routes included after all core routes

## Dependencies
- **Depends on**: `core`, `auth`, `storage`, `retrieval`, `connectors`, `workspaces`, `mcp`, `ingestion`, `observability`
- **Depended on by**: nothing (top of the stack)
