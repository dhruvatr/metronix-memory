"""MCP tool: metronix_store — store a document."""

from __future__ import annotations

import uuid
from typing import Any

from metronix.mcp.errors import handle_tool_error
from metronix.mcp.server import mcp
from metronix.mcp.tools.models import StoreResponse


@mcp.tool(
    description=(
        "Store a new document or memory in the knowledge base.\n\n"
        "**Parameters:**\n"
        "- content: Document content (required)\n"
        "- title: Optional document title\n"
        "- workspace_id: Target workspace (optional, uses default)\n"
        "- doc_label: Optional unique identifier (auto-generated if not provided)\n"
        "- metadata: Additional key-value metadata\n\n"
        "**Returns:** Success status, document label, and chunk count."
    ),
)
async def metronix_store(
    content: str,
    title: str | None = None,
    workspace_id: str | None = None,
    doc_label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a new document in the knowledge base."""
    try:
        from metronix.core.models import Document
        from metronix.ingestion.pipeline import ingest_documents

        if not content:
            raise ValueError("content is required")

        if not doc_label:
            doc_label = f"MEM-{uuid.uuid4().hex[:8].upper()}"

        doc = Document(
            title=title or doc_label,
            content=content,
            source_type="memory",
            source_id=doc_label,
            workspace_id=workspace_id or "default",
            metadata=metadata or {},
        )

        # ingest_documents returns SyncResult (not .success / .new_chunks)
        result = await ingest_documents(
            [doc],
            workspace_id or "default",
            connector_type="memory",
            incremental=False,
        )

        return StoreResponse(
            success=len(result.errors) == 0,
            doc_label=doc_label,
            chunks_stored=result.documents_new,
        ).model_dump()

    except Exception as e:
        error = handle_tool_error("metronix_store", e)
        return {"error": error.to_dict()}
