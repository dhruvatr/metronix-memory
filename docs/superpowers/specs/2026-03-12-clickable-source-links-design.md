# Design: Clickable Document Reference Links in Chat Responses

**Date:** 2026-03-12
**Task:** Make document reference links clickable in chat responses
**Approach:** Propagate URL through Qdrant chunk metadata, include in source citation format

## Problem

Source citations in chat responses are text-only (`"📄 Title"`). The frontend already supports clickable links when the format is `"📄 Title — URL"`, but the backend never includes URLs because:

1. `doc.url` is not added to chunk metadata during ingestion — lost when stored to Qdrant
2. `_append_sources()` in `search.py` only emits `"{icon} {title}"` — no URL
3. Jira connector doesn't set `doc.url` at all
4. Uploaded files have no serving endpoint, no URL, and raw bytes are not persisted
5. Uploaded files are incorrectly typed as `"confluence"` instead of `"upload"`
6. `_SOURCE_ICONS` has no entry for `"notion"` — falls back to generic icon

## Changes

### 1. Ingestion pipeline — persist URL in Qdrant metadata

**File:** `src/metatron/ingestion/pipeline.py` (line ~206-216)

Add `"url": doc.url` to the metadata dict. Place it **after** the `**(doc.metadata or {})` spread to ensure the explicit `doc.url` field takes precedence over any `"url"` key that might exist in `doc.metadata`:

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
    "url": doc.url,                 # NEW — after spread to avoid override
}
```

### 2. Source citation format — include URL

**File:** `src/metatron/retrieval/search.py` (lines 451-475)

Add `"notion"` to `_SOURCE_ICONS` and change `_append_sources()` to extract URL from results:

```python
_SOURCE_ICONS = {
    "confluence": "\U0001f4c4",
    "jira": "\U0001f4cb",
    "upload": "\U0001f4ce",
    "notion": "\U0001f4d3",         # NEW
}

def _append_sources(answer: str, results: list) -> str:
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

The `" — "` (em-dash) separator matches what the frontend `parseSource()` already expects.

### 3. Jira connector — set URL

**File:** `src/metatron/connectors/jira.py` (line ~126-149)

Add `url` field to Document construction using `self._config["url"]` (set during `configure()` from `decrypted_config`):

```python
return Document(
    source_type="jira",
    source_id=issue_key,
    url=f"{self._config['url'].rstrip('/')}/browse/{issue_key}",   # NEW
    ...
)
```

Note: there is no `self._base_url` — the base URL lives in `self._config["url"]`.

### 4. Upload handler — persist file and set URL

**File:** `src/metatron/api/routes/chat.py`

Currently the upload endpoint (`upload_document()`) reads `raw_bytes`, extracts text, passes it to `_ingest_text()`, and discards the original file. To make uploaded files downloadable:

1. **In `upload_document()`** — save `raw_bytes` via `FileStore.save()` before calling `_ingest_text()`. Generate a `file_id` (uuid4). Pass it into `_ingest_text()`.
2. **In `_ingest_text()`** — accept optional `file_id` parameter. Update metadata:

```python
metadata = {
    "title": file_name,
    "type": "upload",                                          # FIX: was "confluence"
    "workspace_id": workspace_id,
    "user_id": user_id,
    "doc_label": doc_label,
    "url": f"/api/v1/files/{file_id}/download" if file_id else "",  # NEW
}
```

`FileStore.save()` is already implemented — it writes to `{base_path}/{workspace_id}/{file_id}_{filename}`.

`FileStore` needs a `base_path` — use `settings.file_store_path` (already exists in config as `FILE_STORE_PATH`, default `./data/files`).

### 5. File download endpoint

**File:** `src/metatron/api/routes/files.py`

Add a GET endpoint:

```
GET /api/v1/files/{file_id}/download
```

Implementation:
1. Look up the file on disk via `FileStore` (use `file_id` to find the file in the workspace directory)
2. Return as `StreamingResponse` with `Content-Type` from the file extension and `Content-Disposition: inline` header
3. Must be `async def` per project convention

Since `create_file_record()` in PG is not yet implemented, the download endpoint should locate the file directly on disk by scanning the workspace directory for a file starting with `{file_id}_`. Do **not** use `FileStore.read()` — it requires `expected_sha256` which is only available from PG records. Instead, read the file directly via `Path` operations. This is a pragmatic approach that avoids implementing the full PG file records system for this task.

**Security note:** When `AUTH_ENABLED` is true, the download endpoint should enforce workspace-level access. For now, it follows the same pattern as existing files API stubs (no auth). This should be hardened in a follow-up.

### 6. Qdrant result formatting — surface URL

**File:** `src/metatron/storage/qdrant.py` (lines 78-87, `_format_result()`)

Add `"url"` to the result dict:

```python
return {
    "id": str(point.id), "score": score,
    "memory": data, "data": data,
    "title": payload.get("title", ""),
    "type": payload.get("type", ""),
    "url": payload.get("url", ""),        # NEW
    "date": payload.get("date", ""),
    "doc_label": payload.get("doc_label", ""),
    "workspace_id": payload.get("workspace_id", ""),
    "payload": payload,
}
```

## Files Changed

| File | Change |
|------|--------|
| `src/metatron/ingestion/pipeline.py` | Add `"url": doc.url` to chunk metadata (after spread) |
| `src/metatron/retrieval/search.py` | Add notion icon; include URL in `_append_sources()` |
| `src/metatron/connectors/jira.py` | Set `url` field using `self._config["url"]` |
| `src/metatron/storage/qdrant.py` | Add `url` to `_format_result()` |
| `src/metatron/api/routes/chat.py` | Fix type bug, persist file via FileStore, pass file_id, set URL |
| `src/metatron/api/routes/files.py` | Add GET `/{file_id}/download` endpoint |
| Tests | Update `_append_sources` tests, add file download test |

## Architectural Notes

- **Two metadata paths:** `_ingest_text()` in `chat.py` constructs chunk metadata independently from `ingest_documents()` in `pipeline.py`. Both must include `"url"`. This duplication is pre-existing; unifying them is out of scope.
- **No PG file records needed:** The download endpoint locates files on disk by `file_id` prefix, avoiding the need to implement `create_file_record()` in PG for this task.

## Out of Scope

- Frontend changes (already handles `"📄 Title — URL"` format)
- Re-indexing existing documents (handled manually via re-sync after infra recreate)
- Memgraph URL storage (not needed — sources come from Qdrant)
- Structured JSON sources SSE event (future improvement — currently sources are string-encoded)
- Unifying the two metadata construction paths (`pipeline.py` and `chat.py`)
- PG `file_records` table implementation
- Unimplemented connectors (GitHub, Google Drive, Slack History, Files connector)

## Risks

- **Existing indexed documents won't have URLs** until re-synced. `_append_sources` gracefully degrades — no URL = no link, title still shown.
- **File download endpoint** has no auth initially. Must be hardened when `AUTH_ENABLED` is true (follow-up).
- **`doc_label` in upload URLs** may contain characters that need URL encoding (filenames with spaces, unicode). The `file_id` (uuid4 hex) used instead is URL-safe.

## Frontend Contract

Frontend `parseSource()` in `useChat.ts` splits on `" — "` (space-emdash-space):
- Icon: first character
- Title: between icon and ` — `
- URL: everything after ` — `

The backend must use em-dash (`\u2014`), not en-dash or hyphen.

## Re-sync Strategy

After deploying this change, existing documents in Qdrant will not have URLs in their metadata. To populate URLs:
- Trigger a full re-sync for each connector via the sync API (`POST /api/v1/sync/{connection_id}`)
- Or recreate infrastructure (as planned by the team)
