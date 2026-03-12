# Clickable Source Links Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make document reference links in chat responses clickable by propagating source URLs through the Qdrant metadata pipeline and including them in the citation format the frontend already parses.

**Architecture:** URLs are stored in Qdrant chunk metadata during ingestion, surfaced through `_format_result()` at query time, and appended to the source citation string in the format `"{icon} {title} — {url}"` that the frontend already parses. Uploaded files are persisted to disk via `FileStore` and served by a new download endpoint.

**Tech Stack:** Python 3.12+, FastAPI, Qdrant, pytest

**Spec:** `docs/superpowers/specs/2026-03-12-clickable-source-links-design.md`

---

## Chunk 1: URL propagation through search pipeline

### Task 1: Add URL to `_append_sources()` in search.py

**Files:**
- Modify: `src/metatron/retrieval/search.py:451-475`
- Test: `tests/unit/test_diversify_results.py:130-173`

- [ ] **Step 1: Write failing tests for URL in sources**

Add these tests to `TestAppendSources` class in `tests/unit/test_diversify_results.py`:

```python
def test_appends_url_when_present(self) -> None:
    results = [
        {"title": "Page One", "type": "confluence", "url": "https://wiki.example.com/page/1"},
    ]
    out = _append_sources("Answer.", results)
    assert "\U0001f4c4 Page One \u2014 https://wiki.example.com/page/1" in out

def test_omits_url_separator_when_no_url(self) -> None:
    results = [
        {"title": "Page One", "type": "confluence", "url": ""},
    ]
    out = _append_sources("Answer.", results)
    assert "\U0001f4c4 Page One" in out
    assert "\u2014" not in out

def test_url_from_payload_fallback(self) -> None:
    results = [
        {"payload": {"title": "Deep Page", "type": "confluence", "url": "https://wiki.example.com/deep"}},
    ]
    out = _append_sources("Answer.", results)
    assert "Deep Page \u2014 https://wiki.example.com/deep" in out

def test_notion_icon(self) -> None:
    results = [
        {"title": "Notion Doc", "type": "notion"},
    ]
    out = _append_sources("Answer.", results)
    assert "\U0001f4d3 Notion Doc" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_diversify_results.py::TestAppendSources -v`
Expected: 4 FAIL (new tests), existing tests PASS

- [ ] **Step 3: Update `_SOURCE_ICONS` and `_append_sources()`**

In `src/metatron/retrieval/search.py`, line 451, change `_SOURCE_ICONS` to add notion:

```python
_SOURCE_ICONS = {"confluence": "\U0001f4c4", "jira": "\U0001f4cb", "upload": "\U0001f4ce", "notion": "\U0001f4d3"}
```

Then replace `_append_sources()` (lines 455-475) with:

```python
def _append_sources(answer: str, results: list) -> str:
    """Append a sources section to the answer with document titles and types."""
    seen_titles: set[str] = set()
    sources: list[str] = []
    for mem in results:
        title = (
            mem.get("title")
            or (mem.get("payload") or {}).get("title")
            or ""
        )
        source_type = _result_type(mem)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)
        icon = _SOURCE_ICONS.get(source_type, "\U0001f4c4")
        url = (
            mem.get("url")
            or (mem.get("payload") or {}).get("url")
            or ""
        )
        if url:
            sources.append(f"{icon} {title} \u2014 {url}")
        else:
            sources.append(f"{icon} {title}")
        if len(sources) >= _MAX_SOURCES:
            break
    if sources:
        return answer + "\n\n\U0001f4da Sources:\n" + "\n".join(sources)
    return answer
```

- [ ] **Step 4: Run all `TestAppendSources` tests**

Run: `pytest tests/unit/test_diversify_results.py::TestAppendSources -v`
Expected: ALL PASS (new + existing)

- [ ] **Step 5: Commit**

```bash
git add src/metatron/retrieval/search.py tests/unit/test_diversify_results.py
git commit -m "feat: include source URLs in chat citation format"
```

---

### Task 2: Surface URL in Qdrant `_format_result()`

**Files:**
- Modify: `src/metatron/storage/qdrant.py:78-87`

- [ ] **Step 1: Add `url` to `_format_result()`**

In `src/metatron/storage/qdrant.py`, line 82-87, change the return dict to include `url`:

```python
    def _format_result(self, point: Any, score: float) -> Dict:
        """Format a Qdrant point into a standardized result dict."""
        payload = point.payload or {}
        data = payload.get("data") or payload.get("memory") or ""
        return {
            "id": str(point.id), "score": score, "memory": data, "data": data,
            "title": payload.get("title", ""), "type": payload.get("type", ""),
            "url": payload.get("url", ""),
            "date": payload.get("date", ""), "doc_label": payload.get("doc_label", ""),
            "workspace_id": payload.get("workspace_id", ""), "payload": payload,
        }
```

- [ ] **Step 2: Run existing tests to ensure no regression**

Run: `pytest tests/unit/test_diversify_results.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/metatron/storage/qdrant.py
git commit -m "feat: surface url field in Qdrant result formatting"
```

---

### Task 3: Persist URL in chunk metadata during ingestion

**Files:**
- Modify: `src/metatron/ingestion/pipeline.py:206-216`

- [ ] **Step 1: Add `"url": doc.url` to metadata dict**

In `src/metatron/ingestion/pipeline.py`, lines 206-216, add `url` **after** the metadata spread:

```python
                metadata = {
                    "title": doc.title,
                    "type": doc.source_type or connector_type,
                    "source_id": doc.source_id,
                    "doc_label": doc.source_id,
                    "workspace_id": workspace_id,
                    "author": doc.author,
                    "date": doc_date,
                    "simhash": chunk_hash,
                    **(doc.metadata or {}),
                    "url": doc.url,
                }
```

Key: `"url": doc.url` is placed **after** `**(doc.metadata or {})` so the explicit `doc.url` field takes precedence if `doc.metadata` also contains a `"url"` key.

- [ ] **Step 2: Run existing pipeline tests**

Run: `pytest tests/unit/test_incremental_sync.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/metatron/ingestion/pipeline.py
git commit -m "feat: persist document URL in Qdrant chunk metadata"
```

---

## Chunk 2: Connector fixes

### Task 4: Set URL in Jira connector

**Files:**
- Modify: `src/metatron/connectors/jira.py:126-149`
- Test: `tests/unit/test_diversify_results.py` (or new test file)

- [ ] **Step 1: Write failing test for Jira document URL**

Create test in `tests/unit/test_jira_connector.py` (or add to existing test file if one exists):

```python
"""Tests for Jira connector URL generation."""

from metatron.connectors.jira import JiraConnector


class TestJiraDocumentUrl:
    def test_issue_to_document_sets_url(self) -> None:
        connector = JiraConnector()
        connector._config = {"url": "https://mycompany.atlassian.net"}
        raw_issue = {
            "key": "MTRNIX-42",
            "fields": {
                "summary": "Test issue",
                "description": "Body text",
                "issuetype": {"name": "Task"},
                "status": {"name": "Open"},
                "priority": {"name": "Medium"},
                "creator": {"displayName": "Alice", "emailAddress": "a@co.il"},
                "reporter": {"displayName": "Alice", "emailAddress": "a@co.il"},
                "assignee": None,
                "created": "2026-01-01T00:00:00.000+0000",
                "updated": "2026-01-02T00:00:00.000+0000",
                "resolutiondate": None,
                "labels": [],
                "components": [],
                "comment": {"comments": []},
            },
        }
        doc = connector._issue_to_document(raw_issue, workspace_id="ws1")
        assert doc.url == "https://mycompany.atlassian.net/browse/MTRNIX-42"

    def test_issue_url_strips_trailing_slash(self) -> None:
        connector = JiraConnector()
        connector._config = {"url": "https://mycompany.atlassian.net/"}
        raw_issue = {
            "key": "PROJ-1",
            "fields": {
                "summary": "Slash test",
                "description": "",
                "issuetype": {"name": "Bug"},
                "status": {"name": "Open"},
                "priority": {"name": "Low"},
                "creator": {"displayName": "Bob", "emailAddress": "b@co.il"},
                "reporter": {"displayName": "Bob", "emailAddress": "b@co.il"},
                "assignee": None,
                "created": "2026-01-01T00:00:00.000+0000",
                "updated": "2026-01-01T00:00:00.000+0000",
                "resolutiondate": None,
                "labels": [],
                "components": [],
                "comment": {"comments": []},
            },
        }
        doc = connector._issue_to_document(raw_issue, workspace_id="ws1")
        assert doc.url == "https://mycompany.atlassian.net/browse/PROJ-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_jira_connector.py -v`
Expected: FAIL — `doc.url` is empty string

- [ ] **Step 3: Add URL to Jira Document construction**

In `src/metatron/connectors/jira.py`, line 126-128, add `url` field:

```python
        return Document(
            source_type="jira",
            source_id=issue_key,
            url=f"{self._config['url'].rstrip('/')}/browse/{issue_key}",
            workspace_id=workspace_id,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_jira_connector.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/metatron/connectors/jira.py tests/unit/test_jira_connector.py
git commit -m "feat: set source URL on Jira documents"
```

---

## Chunk 3: File upload persistence and download endpoint

### Task 5: Persist uploaded files to disk and set URL in metadata

**Files:**
- Modify: `src/metatron/api/routes/chat.py:227-340`
- Test: new tests in `tests/unit/test_file_upload.py` or separate file

- [ ] **Step 1: Write failing test for upload metadata**

Add to `tests/unit/test_diversify_results.py` (TestAppendSources) or create a new focused test. The simplest approach is to unit-test `_ingest_text()` directly. However, `_ingest_text` has heavy dependencies (Qdrant, workspace manager). Instead, test the metadata construction by checking the upload endpoint integration.

Add a test to `tests/unit/test_diversify_results.py`:

```python
def test_append_sources_upload_with_url(self) -> None:
    results = [
        {"title": "report.pdf", "type": "upload", "url": "/api/v1/files/abc123/download"},
    ]
    out = _append_sources("Answer.", results)
    assert "\U0001f4ce report.pdf \u2014 /api/v1/files/abc123/download" in out
```

- [ ] **Step 2: Run test — should pass (uses already-updated `_append_sources`)**

Run: `pytest tests/unit/test_diversify_results.py::TestAppendSources::test_append_sources_upload_with_url -v`
Expected: PASS (since `_append_sources` was already updated in Task 1)

- [ ] **Step 3: Update `_ingest_text()` in chat.py**

In `src/metatron/api/routes/chat.py`, modify `_ingest_text()` signature (line 281) to accept optional `file_id`:

```python
def _ingest_text(
    text: str,
    file_name: str,
    user_id: str = "user",
    workspace_id: str | None = None,
    extract_graph: bool = True,
    file_id: str = "",
) -> dict:
```

Then update the metadata dict (lines 314-322). Preserve the existing `doc_date` conditional that follows:

```python
    metadata = {
        "title": file_name,
        "type": "upload",
        "workspace_id": workspace_id,
        "user_id": user_id,
        "doc_label": doc_label,
        "url": f"/api/v1/files/{file_id}/download" if file_id else "",
    }
    if doc_date:
        metadata["date"] = doc_date
```

Note: the `if doc_date:` block (currently lines 321-322) already exists — keep it as-is.

- [ ] **Step 4: Update `upload_file()` to persist raw bytes and pass file_id**

In `src/metatron/api/routes/chat.py`, update `upload_file()` (lines 227-278). Add file persistence before `_ingest_text()` call:

Add import at top of file (after existing imports):
```python
from uuid import uuid4
```

Then in `upload_file()`, after `file_name = file.filename or "document.txt"` (line 239), add file persistence:

```python
    file_name = file.filename or "document.txt"

    # Persist original file for later download
    from metatron.core.config import get_settings
    from metatron.storage.file_store import FileStore
    file_id = uuid4().hex
    settings = get_settings()
    file_store = FileStore(settings.file_store_path)
    try:
        await file_store.save(
            workspace_id=workspace_id or "default",
            file_id=file_id,
            filename=file_name,
            content=raw_bytes,
        )
    except Exception as exc:
        logger.warning("upload.file_persist_failed", error=str(exc))
        file_id = ""
```

Then update the `_ingest_text()` call (lines 264-270) to pass `file_id`:

```python
        result = _ingest_text(
            text=text,
            file_name=file_name,
            user_id=user_id,
            workspace_id=workspace_id,
            extract_graph=extract_graph,
            file_id=file_id,
        )
```

- [ ] **Step 5: Write unit test for `_ingest_text()` metadata changes**

Add `tests/unit/test_ingest_text_metadata.py`:

```python
"""Tests for _ingest_text() metadata: type and URL fields."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestIngestTextMetadata:
    @patch("metatron.api.routes.chat.get_hybrid_store")
    @patch("metatron.api.routes.chat.get_workspace_manager")
    def test_metadata_has_upload_type_and_url(self, mock_wm, mock_store) -> None:
        from metatron.api.routes.chat import _ingest_text

        ws = MagicMock()
        ws.workspace_id = "ws1"
        mock_wm.return_value.get_workspace.return_value = ws
        store = MagicMock()
        mock_store.return_value = store

        _ingest_text(
            text="Hello world content here",
            file_name="report.txt",
            user_id="u1",
            workspace_id="ws1",
            extract_graph=False,
            file_id="abc123",
        )

        call_args = store.add_document.call_args
        metadata = call_args.kwargs.get("metadata") or call_args[1].get("metadata")
        assert metadata["type"] == "upload"
        assert metadata["url"] == "/api/v1/files/abc123/download"

    @patch("metatron.api.routes.chat.get_hybrid_store")
    @patch("metatron.api.routes.chat.get_workspace_manager")
    def test_metadata_url_empty_when_no_file_id(self, mock_wm, mock_store) -> None:
        from metatron.api.routes.chat import _ingest_text

        ws = MagicMock()
        ws.workspace_id = "ws1"
        mock_wm.return_value.get_workspace.return_value = ws
        store = MagicMock()
        mock_store.return_value = store

        _ingest_text(
            text="Hello world content here",
            file_name="report.txt",
            user_id="u1",
            workspace_id="ws1",
            extract_graph=False,
        )

        call_args = store.add_document.call_args
        metadata = call_args.kwargs.get("metadata") or call_args[1].get("metadata")
        assert metadata["type"] == "upload"
        assert metadata["url"] == ""
```

- [ ] **Step 6: Run new test — should fail until implementation is done, then pass**

Run: `pytest tests/unit/test_ingest_text_metadata.py -v`
Expected: PASS (if Steps 3-4 are already done) or FAIL (if running before implementation)

- [ ] **Step 7: Run existing upload tests to check for regression**

Run: `pytest tests/unit/test_file_upload.py -v`
Expected: ALL PASS (these tests mock `ingest_documents` from pipeline, not `_ingest_text` from chat.py)

- [ ] **Step 8: Commit**

```bash
git add src/metatron/api/routes/chat.py tests/unit/test_ingest_text_metadata.py tests/unit/test_diversify_results.py
git commit -m "feat: persist uploaded files and set download URL in metadata"
```

---

### Task 6: Add file download endpoint

**Files:**
- Modify: `src/metatron/api/routes/files.py`
- Test: `tests/unit/test_file_download.py` (new)

- [ ] **Step 1: Write failing test for download endpoint**

Create `tests/unit/test_file_download.py`:

```python
"""Tests for file download endpoint."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def file_store_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def app(file_store_dir):
    """Create test app with overridden file_store_path."""
    from unittest.mock import patch
    with patch("metatron.core.config.get_settings") as mock_settings:
        mock_settings.return_value.file_store_path = file_store_dir
        mock_settings.return_value.auth_enabled = False
        from metatron.api.routes.files import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/files")
        yield app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestFileDownload:
    def test_download_existing_file(self, client, file_store_dir) -> None:
        ws_dir = Path(file_store_dir) / "ws1"
        ws_dir.mkdir()
        (ws_dir / "abc123_report.pdf").write_bytes(b"%PDF-fake-content")

        resp = client.get("/api/v1/files/abc123/download", params={"workspace_id": "ws1"})
        assert resp.status_code == 200
        assert resp.content == b"%PDF-fake-content"
        assert "report.pdf" in resp.headers.get("content-disposition", "")

    def test_download_nonexistent_file_returns_404(self, client, file_store_dir) -> None:
        ws_dir = Path(file_store_dir) / "ws1"
        ws_dir.mkdir()

        resp = client.get("/api/v1/files/nonexistent/download", params={"workspace_id": "ws1"})
        assert resp.status_code == 404

    def test_download_nonexistent_workspace_returns_404(self, client, file_store_dir) -> None:
        resp = client.get("/api/v1/files/abc123/download", params={"workspace_id": "nope"})
        assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_file_download.py -v`
Expected: FAIL — no `/download` endpoint exists

- [ ] **Step 3: Implement download endpoint**

In `src/metatron/api/routes/files.py`, add the download endpoint. Update imports and add the endpoint:

```python
"""Files API — upload, list, verify integrity, download. /api/v1/files."""

from __future__ import annotations

import mimetypes
from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from metatron.core.config import get_settings

logger = structlog.get_logger()

router = APIRouter(prefix="/files", tags=["files"])


# NOTE: Rename the existing pydantic `FileResponse` model to `FileRecordResponse`
# to avoid clash with fastapi.responses.FileResponse. Update the 3 existing
# endpoints that reference it (upload_file, list_files, verify_file).
# ... keep existing upload_file, list_files, verify_file endpoints ...


@router.get("/{file_id}/download")
async def download_file(file_id: str, workspace_id: str) -> FileResponse:
    """Download an uploaded file by ID.

    Locates the file on disk by scanning the workspace directory for
    a file starting with ``{file_id}_``. Returns the file as a streaming
    response with appropriate Content-Type and Content-Disposition headers.
    """
    settings = get_settings()
    ws_dir = Path(settings.file_store_path) / workspace_id
    if not ws_dir.is_dir():
        raise HTTPException(status_code=404, detail="File not found")

    # Find file matching the file_id prefix
    matches = [f for f in ws_dir.iterdir() if f.name.startswith(f"{file_id}_")]
    if not matches:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = matches[0]
    # Extract original filename: everything after "{file_id}_"
    original_name = file_path.name[len(file_id) + 1:]
    content_type, _ = mimetypes.guess_type(original_name)
    content_type = content_type or "application/octet-stream"

    return FileResponse(
        path=file_path,
        media_type=content_type,
        filename=original_name,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_file_download.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `pytest tests/unit/ -x -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/metatron/api/routes/files.py tests/unit/test_file_download.py
git commit -m "feat: add file download endpoint for uploaded documents"
```

---

## Chunk 4: Documentation update

### Task 7: Update project documentation

**Files:**
- Modify: `docs/API.md` — document new `GET /api/v1/files/{file_id}/download` endpoint
- Modify: `docs/CONNECTORS.md` — verify Jira connector section mentions URL
- Review: `docs/ARCHITECTURE.md` — check if source citation flow needs updating
- Review: `CLAUDE.md` — check if Search Pipeline section needs updating

- [ ] **Step 1: Update `docs/API.md`**

Add documentation for the new download endpoint in the Files section. Find the existing files endpoints (around the `POST /api/v1/files` section) and add:

```markdown
### Download File

Download an uploaded file by its ID.

**Endpoint:** `GET /api/v1/files/{file_id}/download`

**Query Parameters:**
- `workspace_id` (required) — Workspace the file belongs to

**Response:** Raw file content with appropriate `Content-Type` header.

**Headers:**
- `Content-Disposition: inline; filename="original_name.pdf"`

**Error Responses:**
- `404 Not Found` — File or workspace not found
```

- [ ] **Step 2: Review and update `docs/CONNECTORS.md`**

Verify that the Jira section mentions that `url` is set on documents. The doc already says `Metadata: source=jira, issue_key, project_key, issue_type, url` on line 76 — confirm this is accurate after our change.

Also fix a pre-existing doc bug: `CONNECTORS.md` line 63 says the Jira required config key is `base_url`, but the actual code uses `url` (see `jira.py` line 44: `decrypted_config["url"]`). Correct the doc to match the code.

- [ ] **Step 3: Review `docs/ARCHITECTURE.md` and `CLAUDE.md`**

Check if the search pipeline description mentions source citations. Update if needed to mention that sources now include URLs. The CLAUDE.md Search Pipeline section shows the high-level flow — it doesn't need to mention URL details.

- [ ] **Step 4: Commit**

```bash
git add docs/
git commit -m "docs: document file download endpoint and source URL flow"
```

---

## Chunk 5: Final verification

### Task 8: Run full test suite and lint

- [ ] **Step 1: Run full unit test suite**

Run: `make test`
Expected: ALL PASS

- [ ] **Step 2: Run linter**

Run: `make lint`
Expected: No errors

- [ ] **Step 3: Run type checker**

Run: `make typecheck`
Expected: No new errors

- [ ] **Step 4: Fix any issues found in steps 1-3, then commit fixes**

If any fixes are needed:
```bash
git add -u
git commit -m "fix: address lint/type issues from source links feature"
```
