# Memory MCP Tools Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three MCP tools (`memory_batch_store`, `memory_list`, `memory_update`) to Metatron's agent memory surface.

**Architecture:** New MCP tools delegate to `MemoryService` (L3) and storage layer (L1). Two new methods on `MemoryPostgresStore` (`count_records`, `update`), one on `MemoryQdrantStore` (`update_payload`). Response models added to `models.py`. Tools registered via side-effect import in `__init__.py`.

**Tech Stack:** Python 3.12, FastAPI/MCP (FastMCP), asyncpg (SQLAlchemy async), qdrant-client, pytest

**Jira:** MTRNIX-310
**Spec:** `docs/superpowers/specs/2026-04-18-memory-mcp-tools-expansion-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/metatron/mcp/tools/models.py` | Add 4 new response models |
| Modify | `src/metatron/storage/memory_postgres.py` | Add `count_records()`, `update()` |
| Modify | `src/metatron/storage/memory_qdrant.py` | Add `update_payload()` |
| Create | `src/metatron/mcp/tools/memory_batch_store.py` | Batch store MCP tool |
| Create | `src/metatron/mcp/tools/memory_list.py` | List MCP tool |
| Create | `src/metatron/mcp/tools/memory_update.py` | Update MCP tool |
| Modify | `src/metatron/mcp/tools/__init__.py` | Register new tools |
| Create | `tests/unit/test_memory_batch_store.py` | Batch store tests |
| Create | `tests/unit/test_memory_list.py` | List tests |
| Create | `tests/unit/test_memory_update.py` | Update tests |
| Modify | `docs/MCP_API.md` | Document new tools |

---

### Task 1: Response Models

**Files:**
- Modify: `src/metatron/mcp/tools/models.py`

- [ ] **Step 1: Add response models**

Add these classes at the end of `models.py`, after existing models:

```python
class MemoryBatchStoreResult(BaseModel):
    """Result for a single record in a batch store operation."""

    id: str | None = None
    content_hash: str | None = None
    deduped: bool = False
    error: str | None = None


class MemoryBatchStoreResponse(BaseModel):
    """Response from memory_batch_store tool."""

    stored: int
    deduped: int
    results: list[MemoryBatchStoreResult]


class MemoryListResponse(BaseModel):
    """Response from memory_list tool."""

    records: list[MemoryRecordDTO]
    count: int
    total: int
    limit: int
    offset: int


class MemoryUpdateResponse(BaseModel):
    """Response from memory_update tool."""

    id: str
    content_hash: str
    updated_fields: list[str]
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from metatron.mcp.tools.models import MemoryBatchStoreResponse, MemoryListResponse, MemoryUpdateResponse; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/metatron/mcp/tools/models.py
git commit -m "feat(MTRNIX-310): add response models for batch_store, list, update"
```

---

### Task 2: MemoryPostgresStore — count_records() and update()

**Files:**
- Modify: `src/metatron/storage/memory_postgres.py`
- Create: `tests/unit/test_memory_update.py` (partial — storage layer tests)

- [ ] **Step 1: Write failing test for count_records**

Create `tests/unit/test_memory_update.py`:

```python
"""Tests for MemoryPostgresStore.count_records() and update()."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.storage.memory_postgres import MemoryPostgresStore


def _make_store() -> tuple[MemoryPostgresStore, MagicMock]:
    engine = MagicMock()
    store = MemoryPostgresStore(engine)
    return store, engine


def _mock_conn(engine: MagicMock) -> AsyncMock:
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine.begin.return_value = ctx
    return conn


class TestCountRecords:
    async def test_count_returns_scalar(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(engine)
        result = MagicMock()
        result.scalar.return_value = 42
        conn.execute.return_value = result

        count = await store.count_records("ws1", agent_id="agent1")

        assert count == 42
        conn.execute.assert_called_once()

    async def test_count_with_scope_filter(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(engine)
        result = MagicMock()
        result.scalar.return_value = 10
        conn.execute.return_value = result

        count = await store.count_records("ws1", agent_id="a1", scope=MemoryScope.GLOBAL)

        assert count == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_update.py::TestCountRecords -v`
Expected: FAIL — `AttributeError: 'MemoryPostgresStore' object has no attribute 'count_records'`

- [ ] **Step 3: Implement count_records()**

Add to `MemoryPostgresStore` in `src/metatron/storage/memory_postgres.py`, after `list_records()`:

```python
    async def count_records(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        scope: MemoryScope | None = None,
    ) -> int:
        """Count memory records matching filters."""
        conditions = ["workspace_id = :workspace_id"]
        params: dict[str, Any] = {"workspace_id": workspace_id}
        if agent_id is not None:
            conditions.append("agent_id = :agent_id")
            params["agent_id"] = agent_id
        if scope is not None:
            conditions.append("scope = :scope")
            params["scope"] = scope.value
        where = " AND ".join(conditions)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"SELECT count(*) FROM memory_records WHERE {where}"),
                params,
            )
            return result.scalar() or 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_memory_update.py::TestCountRecords -v`
Expected: PASS

- [ ] **Step 5: Write failing test for update()**

Append to `tests/unit/test_memory_update.py`:

```python
class TestUpdate:
    async def test_update_content(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(engine)
        # Simulate existing record found
        row = MagicMock()
        row._mapping = {
            "id": "rec1",
            "workspace_id": "ws1",
            "agent_id": "a1",
            "scope": "per_agent",
            "source_type": "conversation",
            "content": "old content",
            "tags": ["tag1"],
            "importance_score": 0.5,
            "ttl_expires_at": None,
            "content_hash": "oldhash",
            "session_id": None,
            "metadata": {},
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
        select_result = MagicMock()
        select_result.first.return_value = row
        update_result = MagicMock()
        conn.execute.side_effect = [select_result, update_result]

        record = await store.update(
            "ws1", "rec1", content="new content", tags=["tag2"]
        )

        assert record is not None
        assert record.content == "new content"
        assert record.tags == ["tag2"]
        assert conn.execute.call_count == 2

    async def test_update_not_found(self) -> None:
        store, engine = _make_store()
        conn = _mock_conn(engine)
        select_result = MagicMock()
        select_result.first.return_value = None
        conn.execute.return_value = select_result

        record = await store.update("ws1", "nonexistent", content="x")

        assert record is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_update.py::TestUpdate -v`
Expected: FAIL — `AttributeError: 'MemoryPostgresStore' object has no attribute 'update'`

- [ ] **Step 7: Implement update()**

Add to `MemoryPostgresStore`, after `count_records()`:

```python
    async def update(
        self,
        workspace_id: str,
        record_id: str,
        *,
        content: str | None = None,
        tags: list[str] | None = None,
        importance_score: float | None = None,
    ) -> MemoryRecord | None:
        """Partial update of a memory record. Returns updated record or None."""
        now = datetime.now(UTC)
        async with self._engine.begin() as conn:
            # Fetch existing
            result = await conn.execute(
                text(f"SELECT {_RECORD_COLUMNS} FROM memory_records WHERE id = :id AND workspace_id = :ws"),
                {"id": record_id, "ws": workspace_id},
            )
            row = result.first()
            if row is None:
                return None

            m = row._mapping

            # Build updates
            new_content = content if content is not None else m["content"]
            new_tags = tags if tags is not None else m["tags"]
            new_importance = importance_score if importance_score is not None else m["importance_score"]
            new_hash = hashlib.sha256(new_content.encode()).hexdigest() if content is not None else m["content_hash"]

            set_parts = [
                "content = :content",
                "tags = CAST(:tags AS jsonb)",
                "importance_score = :importance_score",
                "content_hash = :content_hash",
                "updated_at = :updated_at",
            ]
            params = {
                "id": record_id,
                "ws": workspace_id,
                "content": new_content,
                "tags": json.dumps(new_tags),
                "importance_score": new_importance,
                "content_hash": new_hash,
                "updated_at": now,
            }
            await conn.execute(
                text(f"UPDATE memory_records SET {', '.join(set_parts)} WHERE id = :id AND workspace_id = :ws"),
                params,
            )

        scope_raw = m["scope"]
        try:
            scope = MemoryScope(scope_raw)
        except ValueError:
            scope = MemoryScope.PER_AGENT

        return MemoryRecord(
            id=record_id,
            workspace_id=workspace_id,
            agent_id=m["agent_id"],
            scope=scope,
            source_type=m["source_type"],
            content=new_content,
            tags=list(new_tags),
            importance_score=new_importance,
            content_hash=new_hash,
            session_id=m["session_id"],
            metadata=m["metadata"] if isinstance(m["metadata"], dict) else {},
            created_at=m["created_at"],
        )
```

Add `import hashlib` at the top of the file if not already present.

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/unit/test_memory_update.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add src/metatron/storage/memory_postgres.py tests/unit/test_memory_update.py
git commit -m "feat(MTRNIX-310): add count_records() and update() to MemoryPostgresStore"
```

---

### Task 3: MemoryQdrantStore — update_payload()

**Files:**
- Modify: `src/metatron/storage/memory_qdrant.py`

- [ ] **Step 1: Implement update_payload()**

Add to `MemoryQdrantStore`, after the `delete()` method:

```python
    async def update_payload(
        self,
        record_id: str,
        payload_updates: dict[str, Any],
    ) -> None:
        """Update payload fields on an existing point without re-embedding."""
        await self._ensure_collection()
        await self._client.set_payload(
            collection_name=self._collection,
            payload=payload_updates,
            points=[record_id],
        )
        logger.debug("memory_qdrant.payload_updated", record_id=record_id)
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from metatron.storage.memory_qdrant import MemoryQdrantStore; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/metatron/storage/memory_qdrant.py
git commit -m "feat(MTRNIX-310): add update_payload() to MemoryQdrantStore"
```

---

### Task 4: memory_batch_store MCP Tool

**Files:**
- Create: `src/metatron/mcp/tools/memory_batch_store.py`
- Create: `tests/unit/test_memory_batch_store.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_memory_batch_store.py`:

```python
"""Tests for metatron_memory_batch_store MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from metatron.core.models import MemoryRecord, MemoryScope


class TestMemoryBatchStore:
    @patch("metatron.mcp.tools.memory_batch_store._memory_deps")
    async def test_happy_path_two_records(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_batch_store import metatron_memory_batch_store

        service = AsyncMock()
        stored1 = MemoryRecord(
            id="id1", workspace_id="ws1", agent_id="hermes",
            scope=MemoryScope.PER_AGENT, source_type="", content="fact 1",
            content_hash="h1",
        )
        stored2 = MemoryRecord(
            id="id2", workspace_id="ws1", agent_id="hermes",
            scope=MemoryScope.PER_AGENT, source_type="", content="fact 2",
            content_hash="h2",
        )
        service.save.side_effect = [stored1, stored2]
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_batch_store(
            records=[
                {"content": "fact 1", "tags": ["a"]},
                {"content": "fact 2"},
            ],
            agent_id="hermes",
            workspace_id="ws1",
        )

        assert result["stored"] == 2
        assert result["deduped"] == 0
        assert len(result["results"]) == 2
        assert result["results"][0]["id"] == "id1"

    @patch("metatron.mcp.tools.memory_batch_store._memory_deps")
    async def test_dedup_detected(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_batch_store import metatron_memory_batch_store

        service = AsyncMock()
        # save returns record with DIFFERENT id = dedup
        stored = MemoryRecord(
            id="existing-id", workspace_id="ws1", agent_id="hermes",
            scope=MemoryScope.PER_AGENT, source_type="", content="fact",
            content_hash="h1",
        )
        service.save.return_value = stored
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_batch_store(
            records=[{"content": "fact"}],
            agent_id="hermes",
            workspace_id="ws1",
        )

        assert result["deduped"] == 1
        assert result["results"][0]["deduped"] is True

    async def test_over_limit_returns_error(self) -> None:
        from metatron.mcp.tools.memory_batch_store import metatron_memory_batch_store

        records = [{"content": f"fact {i}"} for i in range(101)]
        result = await metatron_memory_batch_store(
            records=records, agent_id="hermes", workspace_id="ws1",
        )

        assert "error" in result

    async def test_empty_records_returns_error(self) -> None:
        from metatron.mcp.tools.memory_batch_store import metatron_memory_batch_store

        result = await metatron_memory_batch_store(
            records=[], agent_id="hermes", workspace_id="ws1",
        )

        assert "error" in result

    async def test_missing_agent_id_returns_error(self) -> None:
        from metatron.mcp.tools.memory_batch_store import metatron_memory_batch_store

        result = await metatron_memory_batch_store(
            records=[{"content": "x"}], agent_id="", workspace_id="ws1",
        )

        assert "error" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_batch_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement memory_batch_store tool**

Create `src/metatron/mcp/tools/memory_batch_store.py`:

```python
"""MCP tool: metatron_memory_batch_store — persist multiple memory records."""

from __future__ import annotations

from typing import Any

import structlog

from metatron.core.models import MemoryRecord, MemoryScope
from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools.models import MemoryBatchStoreResponse, MemoryBatchStoreResult

logger = structlog.get_logger(__name__)

_MAX_BATCH = 100


def _scope_from_str(scope: str) -> MemoryScope:
    try:
        return MemoryScope(scope)
    except ValueError as exc:
        valid = ", ".join(s.value for s in MemoryScope)
        raise ValueError(f"invalid scope {scope!r}; valid: {valid}") from exc


@mcp.tool(
    description=(
        "Store multiple agent memory records in one call.\n\n"
        "**Parameters:**\n"
        "- records: Array of objects with 'content' (required) and 'tags' (optional)\n"
        "- agent_id: Agent identity (required, same for all records)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- scope: global | per_agent | session (default per_agent)\n"
        "- importance_score: 0.0..1.0 (default 0.5, same for all records)\n"
        "- source_type: Free-form origin label (optional)\n"
        "- session_id: Required when scope=session\n\n"
        "**Returns:** stored count, deduped count, per-record results."
    ),
)
async def metatron_memory_batch_store(
    records: list[dict[str, Any]],
    agent_id: str,
    workspace_id: str | None = None,
    scope: str = "per_agent",
    importance_score: float = 0.5,
    source_type: str = "",
    session_id: str | None = None,
) -> dict[str, Any]:
    """Persist multiple memory records — PG+Qdrant+Neo4j for each."""
    try:
        if not agent_id:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message="metatron_memory_batch_store: agent_id is required",
            ).to_dict()}

        if not records:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message="metatron_memory_batch_store: records list is empty",
            ).to_dict()}

        if len(records) > _MAX_BATCH:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message=f"metatron_memory_batch_store: max {_MAX_BATCH} records per call",
            ).to_dict()}

        try:
            scope_enum = _scope_from_str(scope)
        except ValueError as exc:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message=f"metatron_memory_batch_store: {exc}",
            ).to_dict()}

        if scope_enum == MemoryScope.SESSION and not session_id:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message="metatron_memory_batch_store: session_id required for session scope",
            ).to_dict()}

        ws_id = workspace_id or "default"
        service = await _memory_deps.build_memory_service_for_workspace(ws_id)

        results: list[MemoryBatchStoreResult] = []
        stored = 0
        deduped = 0

        for entry in records:
            content = entry.get("content", "")
            if not content or not str(content).strip():
                results.append(MemoryBatchStoreResult(error="empty content"))
                continue

            tags = entry.get("tags", [])
            record = MemoryRecord(
                workspace_id=ws_id,
                agent_id=agent_id,
                scope=scope_enum,
                source_type=source_type,
                content=str(content),
                tags=list(tags) if tags else [],
                importance_score=float(importance_score),
                session_id=session_id,
            )
            new_id = record.id

            try:
                if scope_enum == MemoryScope.SESSION:
                    assert session_id is not None
                    saved = await service.cache_session(ws_id, session_id, record)
                else:
                    saved = await service.save(ws_id, record)

                is_dedup = saved.id != new_id
                if is_dedup:
                    deduped += 1
                else:
                    stored += 1

                results.append(MemoryBatchStoreResult(
                    id=saved.id,
                    content_hash=saved.content_hash,
                    deduped=is_dedup,
                ))
            except Exception as exc:
                results.append(MemoryBatchStoreResult(error=str(exc)[:200]))

        logger.info(
            "metatron_memory_batch_store.done",
            workspace_id=ws_id, agent_id=agent_id,
            stored=stored, deduped=deduped, total=len(records),
        )
        return MemoryBatchStoreResponse(
            stored=stored, deduped=deduped, results=results,
        ).model_dump()

    except Exception as exc:
        error = handle_tool_error("metatron_memory_batch_store", exc)
        return {"error": error.to_dict()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_memory_batch_store.py -v`
Expected: All PASS

- [ ] **Step 5: Lint**

Run: `ruff check src/metatron/mcp/tools/memory_batch_store.py tests/unit/test_memory_batch_store.py`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add src/metatron/mcp/tools/memory_batch_store.py tests/unit/test_memory_batch_store.py
git commit -m "feat(MTRNIX-310): add memory_batch_store MCP tool"
```

---

### Task 5: memory_list MCP Tool

**Files:**
- Create: `src/metatron/mcp/tools/memory_list.py`
- Create: `tests/unit/test_memory_list.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_memory_list.py`:

```python
"""Tests for metatron_memory_list MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from metatron.core.models import MemoryRecord, MemoryScope


class TestMemoryList:
    @patch("metatron.mcp.tools.memory_list._memory_deps")
    async def test_happy_path(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_list import metatron_memory_list

        service = AsyncMock()
        service.pg_store.list_records = AsyncMock(return_value=[
            MemoryRecord(
                id="r1", workspace_id="ws1", agent_id="hermes",
                scope=MemoryScope.PER_AGENT, source_type="conv",
                content="fact 1", tags=["a"], importance_score=0.8,
                content_hash="h1", created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ])
        service.pg_store.count_records = AsyncMock(return_value=42)
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_list(
            agent_id="hermes", workspace_id="ws1", limit=20, offset=0,
        )

        assert result["count"] == 1
        assert result["total"] == 42
        assert result["limit"] == 20
        assert result["offset"] == 0
        assert result["records"][0]["content"] == "fact 1"

    @patch("metatron.mcp.tools.memory_list._memory_deps")
    async def test_empty_results(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_list import metatron_memory_list

        service = AsyncMock()
        service.pg_store.list_records = AsyncMock(return_value=[])
        service.pg_store.count_records = AsyncMock(return_value=0)
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_list(
            agent_id="hermes", workspace_id="ws1",
        )

        assert result["count"] == 0
        assert result["total"] == 0

    async def test_missing_agent_id_returns_error(self) -> None:
        from metatron.mcp.tools.memory_list import metatron_memory_list

        result = await metatron_memory_list(agent_id="", workspace_id="ws1")

        assert "error" in result

    @patch("metatron.mcp.tools.memory_list._memory_deps")
    async def test_tags_post_filter(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_list import metatron_memory_list

        service = AsyncMock()
        service.pg_store.list_records = AsyncMock(return_value=[
            MemoryRecord(
                id="r1", workspace_id="ws1", agent_id="hermes",
                scope=MemoryScope.PER_AGENT, source_type="",
                content="tagged", tags=["alpha", "beta"], content_hash="h1",
            ),
            MemoryRecord(
                id="r2", workspace_id="ws1", agent_id="hermes",
                scope=MemoryScope.PER_AGENT, source_type="",
                content="untagged", tags=["gamma"], content_hash="h2",
            ),
        ])
        service.pg_store.count_records = AsyncMock(return_value=2)
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_list(
            agent_id="hermes", workspace_id="ws1", tags=["alpha"],
        )

        assert result["count"] == 1
        assert result["records"][0]["id"] == "r1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_list.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement memory_list tool**

Create `src/metatron/mcp/tools/memory_list.py`:

```python
"""MCP tool: metatron_memory_list — enumerate agent memory records."""

from __future__ import annotations

from typing import Any

import structlog

from metatron.core.models import MemoryScope
from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools.models import MemoryListResponse, MemoryRecordDTO

logger = structlog.get_logger(__name__)


def _scope_from_str(scope: str | None) -> MemoryScope | None:
    if not scope:
        return None
    try:
        return MemoryScope(scope)
    except ValueError as exc:
        valid = ", ".join(s.value for s in MemoryScope)
        raise ValueError(f"invalid scope {scope!r}; valid: {valid}") from exc


@mcp.tool(
    description=(
        "List all memory records for an agent with pagination.\n\n"
        "**Parameters:**\n"
        "- agent_id: Agent identity (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- scope: Filter by scope: global | per_agent | session (optional)\n"
        "- tags: Filter by tags — records must contain at least one (optional)\n"
        "- limit: Results per page, 1..100 (default 20)\n"
        "- offset: Pagination offset (default 0)\n\n"
        "**Returns:** Records list, count, total, pagination info."
    ),
)
async def metatron_memory_list(
    agent_id: str,
    workspace_id: str | None = None,
    scope: str | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List agent memory records with pagination and filters."""
    try:
        if not agent_id:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message="metatron_memory_list: agent_id is required",
            ).to_dict()}

        try:
            scope_enum = _scope_from_str(scope)
        except ValueError as exc:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message=f"metatron_memory_list: {exc}",
            ).to_dict()}

        ws_id = workspace_id or "default"
        limit = min(max(1, int(limit)), 100)
        offset = max(0, int(offset))

        service = await _memory_deps.build_memory_service_for_workspace(ws_id)

        records = await service.pg_store.list_records(
            ws_id, agent_id=agent_id, scope=scope_enum,
            limit=limit, offset=offset,
        )
        total = await service.pg_store.count_records(
            ws_id, agent_id=agent_id, scope=scope_enum,
        )

        # Post-filter by tags if specified
        if tags:
            tag_set = set(tags)
            records = [r for r in records if tag_set.intersection(r.tags)]

        dto_records = [
            MemoryRecordDTO(
                id=r.id,
                workspace_id=r.workspace_id,
                agent_id=r.agent_id,
                scope=r.scope.value,
                source_type=r.source_type,
                content=r.content,
                tags=list(r.tags),
                importance_score=r.importance_score,
                content_hash=r.content_hash,
                created_at=r.created_at,
                session_id=r.session_id,
                metadata=dict(r.metadata) if r.metadata else {},
            )
            for r in records
        ]

        logger.info(
            "metatron_memory_list.done",
            workspace_id=ws_id, agent_id=agent_id, count=len(dto_records),
        )
        return MemoryListResponse(
            records=dto_records,
            count=len(dto_records),
            total=total,
            limit=limit,
            offset=offset,
        ).model_dump()

    except Exception as exc:
        error = handle_tool_error("metatron_memory_list", exc)
        return {"error": error.to_dict()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_memory_list.py -v`
Expected: All PASS

- [ ] **Step 5: Lint**

Run: `ruff check src/metatron/mcp/tools/memory_list.py tests/unit/test_memory_list.py`

- [ ] **Step 6: Commit**

```bash
git add src/metatron/mcp/tools/memory_list.py tests/unit/test_memory_list.py
git commit -m "feat(MTRNIX-310): add memory_list MCP tool"
```

---

### Task 6: memory_update MCP Tool

**Files:**
- Create: `src/metatron/mcp/tools/memory_update.py`
- Modify: `tests/unit/test_memory_update.py` (add MCP layer tests)

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_memory_update.py`:

```python
from unittest.mock import patch


class TestMemoryUpdateTool:
    @patch("metatron.mcp.tools.memory_update._memory_deps")
    async def test_update_content(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_update import metatron_memory_update

        updated = MemoryRecord(
            id="rec1", workspace_id="ws1", agent_id="hermes",
            scope=MemoryScope.PER_AGENT, source_type="conv",
            content="new content", tags=["a"],
            content_hash="newhash",
        )
        service = AsyncMock()
        service.pg_store.update = AsyncMock(return_value=updated)
        service.qdrant_store = AsyncMock()
        service.qdrant_store.upsert = AsyncMock()
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_update(
            record_id="rec1", workspace_id="ws1", content="new content",
        )

        assert result["id"] == "rec1"
        assert "content" in result["updated_fields"]
        service.qdrant_store.upsert.assert_called_once()

    @patch("metatron.mcp.tools.memory_update._memory_deps")
    async def test_update_tags_only_no_reembed(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_update import metatron_memory_update

        updated = MemoryRecord(
            id="rec1", workspace_id="ws1", agent_id="hermes",
            scope=MemoryScope.PER_AGENT, source_type="conv",
            content="same", tags=["new-tag"],
            content_hash="samehash",
        )
        service = AsyncMock()
        service.pg_store.update = AsyncMock(return_value=updated)
        service.qdrant_store = AsyncMock()
        service.qdrant_store.update_payload = AsyncMock()
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_update(
            record_id="rec1", workspace_id="ws1", tags=["new-tag"],
        )

        assert result["id"] == "rec1"
        assert "tags" in result["updated_fields"]
        assert "content" not in result["updated_fields"]
        service.qdrant_store.update_payload.assert_called_once()
        service.qdrant_store.upsert.assert_not_called()

    @patch("metatron.mcp.tools.memory_update._memory_deps")
    async def test_not_found(self, mock_deps) -> None:
        from metatron.mcp.tools.memory_update import metatron_memory_update

        service = AsyncMock()
        service.pg_store.update = AsyncMock(return_value=None)
        mock_deps.build_memory_service_for_workspace = AsyncMock(return_value=service)

        result = await metatron_memory_update(
            record_id="nope", workspace_id="ws1", content="x",
        )

        assert "error" in result

    async def test_no_fields_returns_error(self) -> None:
        from metatron.mcp.tools.memory_update import metatron_memory_update

        result = await metatron_memory_update(
            record_id="rec1", workspace_id="ws1",
        )

        assert "error" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_memory_update.py::TestMemoryUpdateTool -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement memory_update tool**

Create `src/metatron/mcp/tools/memory_update.py`:

```python
"""MCP tool: metatron_memory_update — update an existing memory record."""

from __future__ import annotations

from typing import Any

import structlog

from metatron.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metatron.mcp.server import mcp
from metatron.mcp.tools import _memory_deps
from metatron.mcp.tools.models import MemoryUpdateResponse
from metatron.storage.memory_graph import upsert_memory_node

logger = structlog.get_logger(__name__)


@mcp.tool(
    description=(
        "Update an existing memory record in place.\n\n"
        "**Parameters:**\n"
        "- record_id: Record ID to update (required)\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- content: New content — triggers re-embedding (optional)\n"
        "- tags: Replace tag list (optional)\n"
        "- importance_score: New importance 0.0..1.0 (optional)\n\n"
        "Only provided fields are updated. Neo4j relationships are preserved.\n\n"
        "**Returns:** id, content_hash, list of updated fields."
    ),
)
async def metatron_memory_update(
    record_id: str,
    workspace_id: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    importance_score: float | None = None,
) -> dict[str, Any]:
    """Update an existing memory record — partial update, preserves graph."""
    try:
        if not record_id:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message="metatron_memory_update: record_id is required",
            ).to_dict()}

        # Check at least one field to update
        if content is None and tags is None and importance_score is None:
            return {"error": MCPError(
                code=ErrorCode.INVALID_PARAMS,
                message="metatron_memory_update: at least one of content, tags, or importance_score is required",
            ).to_dict()}

        ws_id = workspace_id or "default"
        service = await _memory_deps.build_memory_service_for_workspace(ws_id)

        # Update in PG (source of truth)
        updated = await service.pg_store.update(
            ws_id, record_id,
            content=content, tags=tags, importance_score=importance_score,
        )

        if updated is None:
            return {"error": MCPError(
                code=ErrorCode.DOCUMENT_NOT_FOUND,
                message=f"Memory record not found: {record_id}",
                hint="Check record_id or workspace_id",
            ).to_dict()}

        # Sync to Qdrant
        try:
            if content is not None:
                # Content changed — full re-embed
                await service.qdrant_store.upsert(updated)
            else:
                # Only metadata changed — payload update only
                payload_updates: dict[str, Any] = {}
                if tags is not None:
                    payload_updates["tags"] = updated.tags
                if importance_score is not None:
                    payload_updates["importance_score"] = updated.importance_score
                if payload_updates:
                    await service.qdrant_store.update_payload(record_id, payload_updates)
        except Exception as exc:
            logger.warning("metatron_memory_update.qdrant_failed", error=str(exc))

        # Sync to Neo4j (best-effort)
        try:
            import asyncio

            await asyncio.to_thread(upsert_memory_node, updated)
        except Exception as exc:
            logger.warning("metatron_memory_update.neo4j_failed", error=str(exc))

        updated_fields: list[str] = []
        if content is not None:
            updated_fields.append("content")
        if tags is not None:
            updated_fields.append("tags")
        if importance_score is not None:
            updated_fields.append("importance_score")

        logger.info(
            "metatron_memory_update.done",
            workspace_id=ws_id, record_id=record_id,
            updated_fields=updated_fields,
        )
        return MemoryUpdateResponse(
            id=updated.id,
            content_hash=updated.content_hash,
            updated_fields=updated_fields,
        ).model_dump()

    except Exception as exc:
        error = handle_tool_error("metatron_memory_update", exc)
        return {"error": error.to_dict()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_memory_update.py -v`
Expected: All PASS

- [ ] **Step 5: Lint**

Run: `ruff check src/metatron/mcp/tools/memory_update.py`

- [ ] **Step 6: Commit**

```bash
git add src/metatron/mcp/tools/memory_update.py tests/unit/test_memory_update.py
git commit -m "feat(MTRNIX-310): add memory_update MCP tool"
```

---

### Task 7: Register Tools

**Files:**
- Modify: `src/metatron/mcp/tools/__init__.py`

- [ ] **Step 1: Add imports**

Add to `src/metatron/mcp/tools/__init__.py`:

```python
from metatron.mcp.tools.memory_batch_store import metatron_memory_batch_store  # noqa: F401
from metatron.mcp.tools.memory_list import metatron_memory_list  # noqa: F401
from metatron.mcp.tools.memory_update import metatron_memory_update  # noqa: F401
```

Add to `__all__`:

```python
    "metatron_memory_batch_store",
    "metatron_memory_list",
    "metatron_memory_update",
```

- [ ] **Step 2: Verify tools are discoverable**

Run: `python -c "import metatron.mcp.tools; print('Tools registered')"`
Expected: `Tools registered`

- [ ] **Step 3: Commit**

```bash
git add src/metatron/mcp/tools/__init__.py
git commit -m "feat(MTRNIX-310): register batch_store, list, update in MCP tools"
```

---

### Task 8: Update MCP API Documentation

**Files:**
- Modify: `docs/MCP_API.md`

- [ ] **Step 1: Add new tools to Agent Memory section**

In `docs/MCP_API.md`, after the `memory_delete` section and before `### System`, add documentation for all three new tools following the existing format:
- `memory_batch_store` — parameter table, request/response JSON examples
- `memory_list` — parameter table, response with pagination fields
- `memory_update` — parameter table, response with updated_fields

- [ ] **Step 2: Commit**

```bash
git add docs/MCP_API.md
git commit -m "docs(MTRNIX-310): add batch_store, list, update to MCP API reference"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Run all tests**

Run: `pytest tests/unit/test_memory_batch_store.py tests/unit/test_memory_list.py tests/unit/test_memory_update.py -v`
Expected: All PASS

- [ ] **Step 2: Lint all new files**

Run: `ruff check src/metatron/mcp/tools/memory_batch_store.py src/metatron/mcp/tools/memory_list.py src/metatron/mcp/tools/memory_update.py src/metatron/storage/memory_postgres.py src/metatron/storage/memory_qdrant.py`

- [ ] **Step 3: Run full unit suite**

Run: `make test`
Expected: No new failures vs baseline
