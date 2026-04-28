# Memory MCP Tools Expansion

**Date:** 2026-04-18
**Author:** Konstantin Kuzmin
**Status:** Approved — ready for implementation plan

## Context

Metatron's WS1 Agent Memory system provides three MCP tools: `memory_store`,
`memory_search`, `memory_delete`. Hermes agent integration (15/15 tests passing)
revealed three missing operations needed for production use:

1. **Batch import** — migrating existing memory (MEMORY.md, USER.md) requires
   calling `memory_store` one-by-one. For 50+ facts this is impractical.
2. **List all records** — no way to enumerate what an agent knows without
   searching. Needed for debugging, auditing, and "what do I know about X" flows.
3. **Update in place** — changing a fact (e.g., timezone changed) requires
   delete + re-create, which breaks Neo4j relationships and loses history.

## Scope

Three new MCP tools. No schema changes to `MemoryRecord` or database migrations.
`user_id` isolation is explicitly out of scope (separate spec).

## Design

### 1. `memory_batch_store`

Persist multiple memory records in a single call. Sequential processing for
correct deduplication (content hash depends on order).

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `records` | list[object] | yes | — | Array of records (max 100) |
| `records[].content` | string | yes | — | Memory content |
| `records[].tags` | list[string] | no | `[]` | Per-record tags |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `agent_id` | string | yes | — | Agent identity (same for all records) |
| `scope` | string | no | `"per_agent"` | Scope for all records: `global`, `per_agent`, `session` |
| `importance_score` | float | no | `0.5` | Importance for all records (0.0–1.0) |
| `source_type` | string | no | `""` | Origin label for all records |
| `session_id` | string | no | `null` | Required when `scope=session` |

`agent_id`, `scope`, `importance_score`, `source_type`, and `session_id` are
batch-level — same for all records. `content` and `tags` are per-record.

**Response:**

```json
{
  "stored": 2,
  "deduped": 0,
  "results": [
    {"id": "abc...", "content_hash": "e3b...", "deduped": false},
    {"id": "def...", "content_hash": "f4c...", "deduped": false}
  ]
}
```

**Implementation:**
- New file: `src/metatron/mcp/tools/memory_batch_store.py`
- Iterates `records`, creates `MemoryRecord` for each, calls `service.save()`
  or `service.cache_session()` sequentially
- Limit: 100 records per call (returns `INVALID_PARAMS` if exceeded)
- Each record gets its own dedup check via existing content hash logic
- Errors on individual records do not abort the batch — failed records are
  reported in `results` with an `error` field instead of `id`

### 2. `memory_list`

Enumerate all memory records for an agent with pagination and optional filters.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `agent_id` | string | yes | — | Agent identity |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `scope` | string | no | `null` | Filter by scope |
| `tags` | list[string] | no | `null` | Filter by tags (intersection) |
| `limit` | integer | no | `20` | Results per page (1–100) |
| `offset` | integer | no | `0` | Pagination offset |

**Response:**

```json
{
  "records": [
    {
      "id": "abc...",
      "content": "user prefers dark mode",
      "agent_id": "hermes",
      "scope": "per_agent",
      "tags": ["preference"],
      "importance_score": 0.8,
      "content_hash": "e3b...",
      "created_at": "2026-04-17T10:00:00+00:00"
    }
  ],
  "count": 1,
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

**Implementation:**
- New file: `src/metatron/mcp/tools/memory_list.py`
- Delegates to existing `MemoryPostgresStore.list_records(workspace_id,
  agent_id, scope, limit, offset)` — already supports these filters
- `total` requires a separate COUNT query in `MemoryPostgresStore` (new method
  `count_records(workspace_id, agent_id, scope)`)
- `tags` post-filter: PG `list_records` does not filter by tags — apply in the
  tool layer after fetch (tags are stored as JSONB array, PG filter possible
  but not currently implemented)
- `agent_id` is required — listing all records across agents is not exposed

### 3. `memory_update`

Update an existing memory record in place. Preserves Neo4j relationships and
record identity.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `record_id` | string | yes | — | Record ID to update |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `content` | string | no | `null` | New content (triggers re-embedding) |
| `tags` | list[string] | no | `null` | Replace tags |
| `importance_score` | float | no | `null` | New importance (0.0–1.0) |

All fields except `record_id` and `workspace_id` are optional. Only provided
fields are updated.

**Response:**

```json
{
  "id": "abc-123-def",
  "content_hash": "new-hash...",
  "updated_fields": ["content", "tags", "importance_score"]
}
```

**Implementation:**
- New file: `src/metatron/mcp/tools/memory_update.py`
- New method: `MemoryPostgresStore.update(workspace_id, record_id, **fields)`
  — partial UPDATE, recalculates `content_hash` if content changed, sets
  `updated_at`
- If `content` changed:
  - Recompute `content_hash`
  - Re-embed and upsert to Qdrant (`MemoryQdrantStore.upsert()`)
  - Update Neo4j node properties (`upsert_memory_node()` — already does MERGE)
- If only `tags` or `importance_score` changed:
  - PG update only
  - Qdrant payload update (no re-embedding)
  - Neo4j node property update
- Returns `DOCUMENT_NOT_FOUND` if record_id does not exist in PG

### Response Models

New models in `src/metatron/mcp/tools/models.py`:

```python
class MemoryBatchStoreResult(BaseModel):
    id: str | None = None
    content_hash: str | None = None
    deduped: bool = False
    error: str | None = None

class MemoryBatchStoreResponse(BaseModel):
    stored: int
    deduped: int
    results: list[MemoryBatchStoreResult]

class MemoryListResponse(BaseModel):
    records: list[MemoryRecordDTO]
    count: int
    total: int
    limit: int
    offset: int

class MemoryUpdateResponse(BaseModel):
    id: str
    content_hash: str
    updated_fields: list[str]
```

### Service Layer Changes

`MemoryService` (L3):
- No new methods needed for batch — tool calls `save()` in loop
- No new methods needed for list — tool calls `pg_store.list_records()` directly

`MemoryPostgresStore` (L1):
- New: `count_records(workspace_id, agent_id, scope?) -> int` — COUNT query
- New: `update(workspace_id, record_id, **fields) -> MemoryRecord | None`
  — partial UPDATE, returns updated record or None if not found

`MemoryQdrantStore` (L1):
- New: `update_payload(record_id, payload_updates: dict) -> None`
  — updates payload fields without re-embedding (for tags/importance only)
- Existing `upsert()` used when content changes (full re-embed)

### Tool Registration

All three tools registered via `@mcp.tool()` decorator in their respective
files. Imported in `src/metatron/mcp/tools/__init__.py` (side-effect import
pattern, same as existing tools).

### Error Handling

Same pattern as existing memory tools:
- `INVALID_PARAMS` for validation errors
- `DOCUMENT_NOT_FOUND` for missing record_id
- `INTERNAL_ERROR` for unexpected exceptions
- All wrapped via `handle_tool_error()`

### Testing

Unit tests for each tool (mocked service/store):
- `tests/unit/test_memory_batch_store.py`
- `tests/unit/test_memory_list.py`
- `tests/unit/test_memory_update.py`

Key test cases:
- Batch: happy path, dedup detection, over-limit (>100), empty records, mixed success/failure
- List: pagination, scope filter, tags filter, empty results
- Update: content change (re-embed), tags-only change (no re-embed), nonexistent record

## Out of Scope

- `user_id` field on MemoryRecord (separate spec)
- Assertion lifecycle (automatic fact extraction from dialogues)
- IdP/SSO integration
- Session-scoped records in `memory_list` (session records live in Redis, not PG)
