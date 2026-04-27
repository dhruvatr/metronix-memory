# Activity

## Overview
L3 — WS4 S6 observability foundation. Persists every meaningful interaction
with Metatron's surface to the append-only `agent_activity_log` table.

## Files

### `context.py`
`current_agent_id: ContextVar[str | None]` — request-scoped agent id. Set by
`api.middleware.agent_id.AgentIdContextMiddleware`, read by MCP tool wrapper
and `retrieval.search.hybrid_search_and_answer`. `bind_agent_id(value)` returns
a token; callers must `current_agent_id.reset(token)` in a `finally` block.

### `logger.py`
`ActivityLogger(store)` — EventBus subscriber. Constructed once in
`api/app.py:create_app()` when `METATRON_ACTIVITY_LOG_ENABLED` is true.
`.subscribe(bus)` registers handlers for 12 event topics (memory, agent,
search, tool, error). Payloads without a resolvable `agent_id` (neither in the
payload nor in the contextvar) are dropped with a structlog
`activity_log.skipped_no_agent_id` info line — never persisted as orphan rows.

### `service.py`
`ActivityService(store, workspace_id)` — read-side facade for
`/api/v1/agents/{id}/activity` and `/activity/summary`. Thin — builds the
list/summary queries, enforces the period vocabulary (`1d|7d|30d|90d`) and
does `limit+1 → has_more` math.

## Layer Rules
- Can import from: `core/` (L0), `storage/activity_pg` (L1).
- Must NOT import from: `api/`, `agent/`, `channels/`.

## Key Decisions
- **Append-only by convention.** No UPDATE or DELETE in the store API. Retention is Phase 4.
- **`agent_id` is NOT NULL.** Events without a resolvable agent are dropped at the logger, not persisted as orphans.
- **Free-string `event_type`.** No enum — ready for outer events (push ingestion) without migrations.
- **EventBus-only emission.** `ActivityLogger` never reaches into services; it only listens. All emission points call `EventBus.emit(...)`.
- **8 KiB cap on `tool.called.arguments`.** Oversized payloads become `{"__truncated__": True, "preview": "..."}`.
- **`correlation_id` links `query.processed` with sibling `document.accessed` events.** Generated in `retrieval.search` before emission.
- **Emission cost when flag is off.** When `METATRON_ACTIVITY_LOG_ENABLED=false`, `ActivityLogger` is never constructed and never subscribes — but the emission call sites (`MemoryService`, `AgentRegistryService`, search pipeline, MCP tool wrapper) still call `EventBus.emit(...)`. Cost is a dict-lookup + early return per emit (`event_bus.py` returns when `handlers` is empty). Negligible vs. real I/O on the request path; emissions are intentionally NOT gated on the flag so a runtime toggle does not require restart.
- **Argument / document-id caps log a structlog warning.** `tool.called.arguments` truncation at 8 KiB and `document.accessed.document_ids` cap at 50 each fire `activity_log.arguments_truncated` / `activity_log.document_ids_capped` so operators can spot oversized payloads.
- **`event_bus_not_wired` warning fires once per service instance** if `event_bus` was constructed `None`. Surfaces a misconfigured deployment without flooding the log on every emit.
