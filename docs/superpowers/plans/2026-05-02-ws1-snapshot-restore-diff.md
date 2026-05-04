# WS1 S4-5: Memory snapshot / restore / diff (MTRNIX-272)

**Date:** 2026-05-02
**Branch:** `feature/MTRNIX-272`
**Sprint:** W5 (May 5-9)
**Stage:** WS1 stages 4-5

## Goal

Enterprise-grade backup/restore for agent memory with integrity checks. Three
user-visible capabilities:

1. **Reset** an agent's memory with an automatic pre-reset snapshot.
2. **Snapshot/restore** an agent's memory as JSONL+gzip with SHA-256 integrity.
3. **Diff** two snapshots of the same agent.

## What's already in place

- `migrations/versions/013_memory_system.py` — `memory_snapshots` table:
  `id, workspace_id, agent_id, label, trigger, record_count, content_hash,
  size_bytes, storage_path, created_at` + index `(workspace_id, agent_id)`.
- `core/models.py:379` — `MemorySnapshot` dataclass.
- `storage/memory_postgres.py:664-731` — `MemoryPostgresStore.save_snapshot /
  get_snapshot / delete_snapshot / list_snapshots` (metadata CRUD).
- `core/events.py:48-49` — `MEMORY_SNAPSHOT_CREATED`, `MEMORY_RESTORED` constants
  with documented payload shape.
- `core/exceptions.py:71` — `SnapshotCorruptError(AgentMemoryError)`.
- `core/interfaces.py:388-401` — `MemoryStoreInterface.create_snapshot /
  restore_snapshot` ABC methods (currently unimplemented).
- `MemoryService.reset(ws, *, agent_id, scope)` — `DELETE … RETURNING id` in PG
  + per-id Qdrant + Neo4j cleanup, emits `MEMORY_RESET`.

**No new alembic migration is needed.**

## What's missing — this PR

1. `memory/snapshot.py` (new, L3) — `MemorySnapshotService` orchestrator and
   file IO helpers.
2. `api/routes/snapshots.py` (new, L6) — `/api/v1/snapshots/{id}/restore` and
   `/api/v1/snapshots/diff`.
3. Extensions to `api/routes/agents.py` (L6) — `/{id}/reset`, `/{id}/snapshots`
   POST + GET.
4. `api/dependencies.py` — `get_memory_snapshot_service(request)`.
5. Two new `Settings` fields — snapshot dir + max file size.
6. Wiring in `api/app.py` — include the new router.
7. Unit tests (snapshot service round-trip, checksum tampering, workspace
   isolation, diff semantics, route RBAC + cross-workspace defence).

## Design decisions (confirmed in conversation)

| # | Decision |
|---|---|
| 1 | "Bulk soft-delete" = call existing `MemoryService.reset(agent_id=…)`. PG hard-delete + per-id Qdrant + Neo4j cleanup. Reversible only via the auto-snapshot taken immediately before. |
| 2 | Restore = transaction replace: PG `BEGIN; DELETE … WHERE agent_id=…; INSERT …; COMMIT;` + best-effort Qdrant/Neo4j re-population. Conflicting `id`s do not occur (we just deleted them); use plain `INSERT`. |
| 3 | Embeddings are NOT in the snapshot. Restore re-embeds via `MemoryQdrantStore.upsert(record)`. Pro: portable across embedding model versions. Con: slower restore (acceptable — bounded by record count, not record size). |
| 4 | Diff: same-agent only. `from.workspace_id == to.workspace_id == auth.workspace_id` and `from.agent_id == to.agent_id` enforced server-side; otherwise 400. |
| 5 | `expires_at` retention: deferred. Keep schema as-is; cron pruning is a follow-up. |

## Layer map

```
L6  api/routes/snapshots.py            (new)
L6  api/routes/agents.py               (extend with /reset, /snapshots)
L6  api/dependencies.py                (add get_memory_snapshot_service)
L6  api/app.py                         (mount new router)
L3  memory/snapshot.py                 (new — service + file IO)
L3  memory/__init__.py                 (re-export)
L1  storage/memory_postgres.py         (already done — no changes)
L0  core/config.py                     (add 2 fields)
L0  core/events.py                     (already done — no changes)
L0  core/exceptions.py                 (already done — no changes)
L0  core/models.py                     (already done — no changes)
```

No upward imports introduced. `memory/snapshot.py` depends on `core/`, `storage/`,
and the existing `memory/service.py`.

## File format

```
data/snapshots/{workspace_id}/{agent_id}/{snapshot_id}.jsonl.gz
data/snapshots/{workspace_id}/{agent_id}/{snapshot_id}.sha256
```

- `*.jsonl.gz` — gzip-wrapped JSON-Lines.
  - **Line 1 = manifest:**
    ```json
    {"_kind": "manifest", "version": 1, "workspace_id": "...",
     "agent_id": "...", "snapshot_id": "...", "created_at": "ISO-8601",
     "trigger": "manual|pre_reset|pre_restore", "label": "...",
     "record_count": N}
    ```
  - **Lines 2..N+1 = `MemoryRecord` JSON** (one per line, lifecycle fields
    included: `status`, `verification_state`, `superseded_by`, `valid_from`,
    `valid_until`, `evidence_count`, `freshness_score`, `content_hash`).
- `*.sha256` — single line: `<hex digest>  <basename>.jsonl.gz`. Sidecar so the
  checksum can be verified before reading the gzip body.

The `MemorySnapshot.content_hash` column stores the same SHA-256 (semantically
"file checksum", not "memory record content hash" — tracked across the codebase
under the existing column name to avoid a migration).

## Service API — `memory/snapshot.py`

```python
class MemorySnapshotService:
    def __init__(
        self,
        memory_service: MemoryService,
        pg_store: MemoryPostgresStore,
        *,
        workspace_id: str,
        snapshot_dir: Path,
        event_bus: EventBus | None = None,
        max_file_bytes: int = 256 * 1024 * 1024,
    ) -> None: ...

    async def create(
        self, agent_id: str, *, label: str = "", trigger: str = "manual"
    ) -> MemorySnapshot: ...
    async def restore(self, snapshot_id: str) -> tuple[MemorySnapshot, int]: ...
        # returns (auto_pre_restore_snapshot, restored_count)
    async def get(self, snapshot_id: str) -> MemorySnapshot: ...     # raises MemoryNotFoundError
    async def list(self, agent_id: str) -> list[MemorySnapshot]: ...
    async def diff(
        self, from_id: str, to_id: str, *, key: str = "source"
    ) -> SnapshotDiff: ...
        # key in {"source", "content_hash"}
```

`SnapshotDiff` dataclass:

```python
@dataclass
class SnapshotDiff:
    from_id: str
    to_id: str
    key: str
    added: list[str]     # record ids present only in `to`
    removed: list[str]   # record ids present only in `from`
    changed: list[str]   # same key, different content_hash
```

## Workflow details

### `create(agent_id, label, trigger)`

1. `pg_store.list_records(workspace_id, agent_id=agent_id, limit=10_000)` —
   pull **all** records for the agent. (Caveat: snapshots over 10k records will
   need pagination — note as TODO; not in v1 scope.)
2. Build manifest dict + serialize records as JSONL.
3. Stream to a temporary file on disk via `gzip.open(..., "wt")`, computing
   SHA-256 of the **compressed bytes** as we write.
4. Reject if `tmp.stat().st_size > max_file_bytes` → raise `SnapshotCorruptError`
   (admin-tunable safety cap).
5. Atomic rename to final path `{snapshot_dir}/{ws}/{agent_id}/{snapshot_id}.jsonl.gz`.
6. Write `.sha256` sidecar.
7. `pg_store.save_snapshot(MemorySnapshot(...))`.
8. Emit `MEMORY_SNAPSHOT_CREATED` with `{workspace_id, agent_id, snapshot_id, trigger}`.

### `restore(snapshot_id)`

1. `pg_store.get_snapshot(workspace_id, snapshot_id)` → 404 → `MemoryNotFoundError`.
2. Verify checksum:
   - Read sidecar `.sha256`. If missing, fall back to recomputing from `.jsonl.gz`.
   - Recompute SHA-256 of the `.jsonl.gz` bytes; compare with stored
     `content_hash` AND the sidecar (when present).
   - Mismatch → `SnapshotCorruptError`.
3. Read+verify the manifest (line 1) — workspace/agent must match the row.
4. Take `pre_restore` auto-snapshot of current state via `self.create(...)`.
5. PG transaction:
   - `DELETE FROM memory_records WHERE workspace_id = :ws AND agent_id = :ag`
   - `INSERT` each record from the snapshot in the same transaction.
6. Best-effort Qdrant: `qdrant_store.delete_by_agent(agent_id)` then
   `qdrant_store.upsert(record)` per record (re-embeds).
7. Best-effort Neo4j: `delete_agent_memories(...)` then `save_memory_to_graph(...)`.
8. Emit `MEMORY_RESTORED` with `{workspace_id, agent_id, snapshot_id, count}`.

### `diff(from_id, to_id, key)`

1. Load both `MemorySnapshot` rows. Both must be in the auth workspace AND same
   `agent_id` → otherwise raise `ValueError` (route maps to 400).
2. Verify both file checksums (defense in depth — diff must not silently consume
   tampered snapshots).
3. Stream-read each file, build `dict[key_value, content_hash]` mappings.
   - For `key="source"`, the key is `f"{record.source_type}:{record.metadata.get('source_id', '')}"`
     when source_id present; falls back to `record.id` when empty (so records
     without a source still appear in the diff but only match by id).
   - For `key="content_hash"`, the key is `record.content_hash` itself; "changed"
     never fires (it's tautological).
4. Compute `added` / `removed` / `changed` as documented above.
5. Return `SnapshotDiff` — endpoint serializes to JSON.

## REST endpoints

| Method | Path | RBAC | Notes |
|---|---|---|---|
| POST | `/api/v1/agents/{id}/reset` | editor+ | Creates `pre_reset` snapshot, then calls `MemoryService.reset(agent_id=id)`. Returns `{snapshot_id, deleted_count}`. |
| POST | `/api/v1/agents/{id}/snapshots` | editor+ | Body `{label?: str}`. Returns the created `MemorySnapshot`. |
| GET | `/api/v1/agents/{id}/snapshots` | viewer+ | Returns `{snapshots: [...], count}` (newest first, no pagination in v1 — list is bounded by usage). |
| POST | `/api/v1/snapshots/{id}/restore` | editor+ | Returns `{auto_snapshot_id, restored_count}`. |
| GET | `/api/v1/snapshots/diff?from=<id>&to=<id>&key=source\|content_hash` | viewer+ | 400 on cross-agent or unknown id. |

All endpoints derive `workspace_id` from auth (never body/query). Cross-workspace
snapshot ids return 404 (`MemoryNotFoundError` from PG store).

## Configuration

```python
# core/config.py
snapshot_dir: str = Field(
    "./data/snapshots", alias="METATRON_SNAPSHOT_DIR"
)
snapshot_max_file_bytes: int = Field(
    256 * 1024 * 1024, alias="METATRON_SNAPSHOT_MAX_FILE_BYTES"
)
```

256 MiB cap is generous (handful of MB per 10k records typical) — protects
against runaway disk consumption from bug or hostile content.

## Error model

| Failure | Raised | HTTP |
|---|---|---|
| Snapshot id not in workspace | `MemoryNotFoundError` | 404 |
| File missing on disk | `SnapshotCorruptError` | 422 |
| Checksum mismatch | `SnapshotCorruptError` | 422 |
| Workspace mismatch in manifest | `SnapshotCorruptError` | 422 |
| Diff across agents | `ValueError` | 400 |
| File exceeds cap | `SnapshotCorruptError` | 422 |
| Agent does not exist (for `/reset`) | `AgentNotFoundError` | 404 |

## Test plan — unit only (no live services)

1. **`test_snapshot_service_create_roundtrip`** — create snapshot → manifest +
   N records on disk → SHA-256 matches stored `content_hash`.
2. **`test_snapshot_service_restore_roundtrip`** — create → reset → restore →
   PG state matches the snapshot.
3. **`test_snapshot_service_restore_creates_auto_pre_restore_snapshot`** — verify
   there are now 2 snapshot rows with `trigger=pre_restore` for the second.
4. **`test_snapshot_service_restore_rejects_tampered_file`** — flip a byte in
   the gzip body → `SnapshotCorruptError`.
5. **`test_snapshot_service_restore_rejects_workspace_mismatch_in_manifest`**.
6. **`test_snapshot_service_diff_added_removed_changed`** — fixture with
   3 records in `from`, 3 in `to` (1 same, 1 changed-content, 1 added, 1 removed).
7. **`test_snapshot_service_diff_rejects_cross_agent`**.
8. **`test_snapshot_service_workspace_isolation`** — service bound to ws_A
   refuses to create/restore for snapshot rows owned by ws_B (404).
9. **`test_routes_reset_creates_snapshot_and_deletes`** — RBAC + happy path
   via TestClient with an in-memory fake of `MemoryService` + `MemorySnapshotService`.
10. **`test_routes_restore_workspace_cross_leak`** — a foreign workspace id in
    the URL never resolves to another workspace's data.
11. **`test_routes_diff_400_on_cross_agent`**.
12. **`test_routes_rbac_viewer_blocked_from_writes`**.

Tests live in `tests/unit/memory/test_snapshot_service.py` and
`tests/unit/api/test_snapshot_routes.py` (mirrors existing `test_memory_routes.py`
fixture style).

## Risks and follow-ups

- **Re-embedding cost on restore** — pulls the embedding provider for every
  record. For an agent with thousands of records this can take seconds-to-minutes.
  Acceptable for v1; revisit only if a customer reports slow restores.
- **No retention/cleanup** — snapshots accumulate on disk forever. Tracked as
  follow-up: add `expires_at` column + cron sweep.
- **No PG/Qdrant/Neo4j atomicity** — same as the rest of `MemoryService`. PG is
  source of truth; if Qdrant/Neo4j re-population fails midway the next search
  query may miss some records until a re-save fixes it. Documented, not fixed
  in v1.
- **10k record cap on `create()`** — `pg_store.list_records` is called once;
  paginate when this becomes real.

## Out of scope

- New alembic migration (table already exists).
- Cross-agent diff (separate endpoint when needed).
- Retention/cleanup of old snapshots.
- MCP tool exposure (REST only for v1; MCP tools follow when external agents
  need them).
- Snapshot encryption at rest (deferred until any customer/compliance ask
  triggers it).
