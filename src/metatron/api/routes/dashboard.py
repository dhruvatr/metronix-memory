"""Dashboard API — /api/v1/dashboard.

Provides aggregated metrics and statistics for the dashboard UI.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal
import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from metatron.storage.pg_connection import get_session
from metatron.storage.pg_models import ConnectionRow, QueryTraceRow, SyncLogRow
from metatron.workspaces import get_workspace_manager

logger = structlog.get_logger()

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Constants
MAX_ERROR_MESSAGE_LENGTH = 200
MAX_ORPHAN_NODES_LIMIT = 100


class OverviewKPIResponse(BaseModel):
    """Overview KPI metrics for dashboard."""

    documents: int
    jira_issues: int
    active_connectors: int
    last_upload: str | None


def _count_active_connectors(workspace_id: str) -> int:
    """Count active connections for a workspace (sync function).

    Args:
        workspace_id: Workspace ID to query.

    Returns:
        Number of active connections.
    """
    try:
        with get_session() as session:
            result = session.execute(
                select(func.count(ConnectionRow.id)).where(
                    ConnectionRow.workspace_id == workspace_id,
                    ConnectionRow.status == "active",
                )
            )
            count = result.scalar()
            return count or 0
    except Exception as e:
        logger.warning(
            "dashboard.overview.connections.error",
            workspace_id=workspace_id,
            error=str(e),
        )
        return 0


@router.get("/overview", response_model=OverviewKPIResponse)
async def get_overview_kpi(workspace_id: str) -> OverviewKPIResponse:
    """Get overview KPI metrics for dashboard.

    Args:
        workspace_id: Workspace ID (query parameter).

    Returns:
        Overview metrics: documents, jira_issues, active_connectors, last_upload.

    Raises:
        HTTPException: 404 if workspace not found.
    """
    # Verify workspace exists
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_id}' not found",
        )

    # Get document count from Qdrant
    document_count = 0
    last_upload = None
    try:
        from metatron.storage.qdrant import get_hybrid_store
        store = get_hybrid_store(workspace_id)
        qdrant_stats = store.get_stats()
        document_count = qdrant_stats.get("file_count", 0)
    except Exception as e:
        logger.warning(
            "dashboard.overview.qdrant.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    # Get jira_issues count from Memgraph
    jira_issues = 0
    try:
        from metatron.storage.memgraph import get_memgraph_driver
        driver = get_memgraph_driver()
        with driver.session() as session:
            result = session.run(
                "MATCH (j:JiraIssue {workspace_id: $wid}) RETURN count(j) AS cnt",
                {"wid": workspace_id},
            )
            record = result.single()
            if record:
                jira_issues = record["cnt"]
    except Exception as e:
        logger.warning(
            "dashboard.overview.memgraph.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    # Count active connectors from PostgreSQL (run in thread pool)
    active_connectors = await asyncio.to_thread(
        _count_active_connectors,
        workspace_id,
    )

    # Get last_upload from workspace stats (if available)
    stats = manager.get_workspace_stats(workspace_id)
    last_upload = stats.last_upload_time if stats else None

    return OverviewKPIResponse(
        documents=document_count,
        jira_issues=jira_issues,
        active_connectors=active_connectors,
        last_upload=last_upload,
    )



class SyncHistoryItem(BaseModel):
    """Single sync history entry."""

    id: str
    source: str
    title: str
    started: str
    duration_ms: float
    records: int
    status: Literal["success", "partial", "failed"]


class SyncHistoryResponse(BaseModel):
    """Sync history response."""

    items: list[SyncHistoryItem]


def _get_sync_history(workspace_id: str, limit: int) -> list[SyncHistoryItem]:
    """Get sync history for a workspace (sync function).

    Args:
        workspace_id: Workspace ID to query.
        limit: Maximum number of records to return.

    Returns:
        List of sync history items.
    """
    try:
        with get_session() as session:
            result = session.execute(
                select(SyncLogRow)
                .where(SyncLogRow.workspace_id == workspace_id)
                .order_by(SyncLogRow.created_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            
            items = []
            for row in rows:
                items.append(
                    SyncHistoryItem(
                        id=row.id,
                        source=row.connector_type,
                        title=row.source_title or f"{row.connector_type.capitalize()} Sync",
                        started=row.created_at.isoformat() if row.created_at else "",
                        duration_ms=row.duration_ms,
                        records=row.qdrant_chunks,
                        status=row.status,  # type: ignore[arg-type]
                    )
                )
            return items
    except Exception as e:
        logger.warning(
            "dashboard.sync_history.error",
            workspace_id=workspace_id,
            error=str(e),
        )
        return []


@router.get("/sync-history", response_model=SyncHistoryResponse)
async def get_sync_history(
    workspace_id: str,
    limit: int = Query(default=10, ge=1, le=100),
) -> SyncHistoryResponse:
    """Get sync history for dashboard.

    Args:
        workspace_id: Workspace ID (query parameter).
        limit: Maximum number of records (default: 10, max: 100).

    Returns:
        Sync history items.

    Raises:
        HTTPException: 404 if workspace not found.
    """
    # Verify workspace exists
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_id}' not found",
        )

    # Get sync history from PostgreSQL (run in thread pool)
    items = await asyncio.to_thread(_get_sync_history, workspace_id, limit)

    return SyncHistoryResponse(items=items)


class IngestionErrorItem(BaseModel):
    """Single ingestion error entry."""

    source: str
    record: str
    error: str
    time: str
    severity: Literal["critical", "warning", "info"]


class IngestionErrorsResponse(BaseModel):
    """Ingestion errors response."""

    total: int
    items: list[IngestionErrorItem]


def _get_ingestion_errors(workspace_id: str, limit: int) -> tuple[int, list[IngestionErrorItem]]:
    """Get ingestion errors for a workspace (sync function).

    Args:
        workspace_id: Workspace ID to query.
        limit: Maximum number of error records to return.

    Returns:
        Tuple of (total_count, error_items).
    """
    try:
        with get_session() as session:
            # Count total errors
            count_result = session.execute(
                select(func.count(SyncLogRow.id)).where(
                    SyncLogRow.workspace_id == workspace_id,
                    SyncLogRow.status != "success",
                )
            )
            total = count_result.scalar() or 0

            # Get error records
            result = session.execute(
                select(SyncLogRow)
                .where(
                    SyncLogRow.workspace_id == workspace_id,
                    SyncLogRow.status != "success",
                )
                .order_by(SyncLogRow.created_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()

            items = []
            for row in rows:
                # Determine severity based on status
                severity: Literal["critical", "warning", "info"] = "warning"
                if row.status == "failed":
                    severity = "critical"
                elif row.status == "partial":
                    severity = "warning"

                # Format record identifier
                record = row.source_title or f"{row.connector_type.capitalize()} Sync"

                # Extract error message from errors JSONB field
                error_msg = "Unknown error"
                if row.errors and isinstance(row.errors, list) and len(row.errors) > 0:
                    # Take first error from array
                    first_error = row.errors[0]
                    if isinstance(first_error, dict):
                        error_msg = first_error.get("message", str(first_error))
                    else:
                        error_msg = str(first_error)
                    # Truncate to MAX_ERROR_MESSAGE_LENGTH
                    if len(error_msg) > MAX_ERROR_MESSAGE_LENGTH:
                        error_msg = error_msg[:MAX_ERROR_MESSAGE_LENGTH - 3] + "..."

                items.append(
                    IngestionErrorItem(
                        source=row.connector_type,
                        record=record,
                        error=error_msg,
                        time=row.created_at.isoformat() if row.created_at else "",
                        severity=severity,
                    )
                )

            return total, items
    except Exception as e:
        logger.warning(
            "dashboard.ingestion_errors.error",
            workspace_id=workspace_id,
            error=str(e),
        )
        return 0, []


@router.get("/ingestion-errors", response_model=IngestionErrorsResponse)
async def get_ingestion_errors(
    workspace_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> IngestionErrorsResponse:
    """Get ingestion errors for dashboard.

    Args:
        workspace_id: Workspace ID (query parameter).
        limit: Maximum number of error records (default: 20, max: 100).

    Returns:
        Ingestion errors with total count and items.

    Raises:
        HTTPException: 404 if workspace not found.
    """
    # Verify workspace exists
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_id}' not found",
        )

    # Get ingestion errors from PostgreSQL (run in thread pool)
    total, items = await asyncio.to_thread(_get_ingestion_errors, workspace_id, limit)

    return IngestionErrorsResponse(total=total, items=items)


class QueryTrendResponse(BaseModel):
    """Query trend response."""

    labels: list[str]
    values: list[int]


def _get_query_trend(workspace_id: str, days: int) -> tuple[list[str], list[int]]:
    """Get query trend for a workspace (sync function).

    Args:
        workspace_id: Workspace ID to query.
        days: Number of days to look back.

    Returns:
        Tuple of (date_labels, query_counts).
    """
    try:
        from datetime import timedelta
        from sqlalchemy import cast, Date

        with get_session() as session:
            # Calculate date range
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=days - 1)

            # Query: group by date, count queries
            result = session.execute(
                select(
                    cast(QueryTraceRow.created_at, Date).label("date"),
                    func.count(QueryTraceRow.id).label("count"),
                )
                .where(
                    QueryTraceRow.workspace_id == workspace_id,
                    QueryTraceRow.created_at >= start_date,
                )
                .group_by(cast(QueryTraceRow.created_at, Date))
                .order_by(cast(QueryTraceRow.created_at, Date))
            )
            rows = result.all()

            # Build date -> count mapping
            date_counts = {row.date: row.count for row in rows}

            # Generate complete date range (fill missing dates with 0)
            labels = []
            values = []
            current_date = start_date
            while current_date <= end_date:
                labels.append(current_date.isoformat())
                values.append(date_counts.get(current_date, 0))
                current_date += timedelta(days=1)

            return labels, values
    except Exception as e:
        logger.warning(
            "dashboard.query_trend.error",
            workspace_id=workspace_id,
            error=str(e),
        )
        return [], []


@router.get("/query-trend", response_model=QueryTrendResponse)
async def get_query_trend(
    workspace_id: str,
    days: int = Query(default=30, ge=1, le=365),
) -> QueryTrendResponse:
    """Get query trend for dashboard.

    Args:
        workspace_id: Workspace ID (query parameter).
        days: Number of days to look back (default: 30, max: 365).

    Returns:
        Query trend with date labels and query counts.

    Raises:
        HTTPException: 404 if workspace not found.
    """
    # Verify workspace exists
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_id}' not found",
        )

    # Get query trend from PostgreSQL (run in thread pool)
    labels, values = await asyncio.to_thread(_get_query_trend, workspace_id, days)

    return QueryTrendResponse(labels=labels, values=values)


class OrphanNode(BaseModel):
    """Orphan node details."""

    id: str
    label: str
    name: str


class GraphLineage(BaseModel):
    """Data lineage statistics."""

    raw_documents: int
    chunks: int
    graph_nodes: int


class GraphStatsResponse(BaseModel):
    """Knowledge graph statistics response."""

    total_nodes: int
    total_edges: int
    orphan_nodes: int
    orphan_list: list[OrphanNode]
    lineage: GraphLineage


def _get_graph_stats(workspace_id: str) -> dict:
    """Get knowledge graph statistics (sync function).

    Args:
        workspace_id: Workspace ID to query.

    Returns:
        Dictionary with graph statistics.
    """
    result = {
        "total_nodes": 0,
        "total_edges": 0,
        "orphan_nodes": 0,
        "orphan_list": [],
        "raw_documents": 0,
        "chunks": 0,
    }

    # Get graph stats from Memgraph
    try:
        from metatron.storage.memgraph import get_memgraph_driver

        driver = get_memgraph_driver()
        with driver.session() as session:
            # Count total nodes
            node_result = session.run(
                "MATCH (n {workspace_id: $wid}) RETURN count(n) AS cnt",
                {"wid": workspace_id},
            )
            node_record = node_result.single()
            if node_record:
                result["total_nodes"] = node_record["cnt"]

            # Count total edges
            edge_result = session.run(
                "MATCH (a {workspace_id: $wid})-[r]-(b {workspace_id: $wid}) RETURN count(r) AS cnt",
                {"wid": workspace_id},
            )
            edge_record = edge_result.single()
            if edge_record:
                # Divide by 2 because undirected edges are counted twice
                result["total_edges"] = edge_record["cnt"] // 2

            # Find orphan nodes (nodes without any relationships)
            orphan_result = session.run(
                f"""
                MATCH (n {{workspace_id: $wid}})
                WHERE NOT (n)--()
                RETURN elementId(n) AS id, labels(n)[0] AS label, 
                       COALESCE(n.name, n.title, n.id, 'Unknown') AS name
                LIMIT {MAX_ORPHAN_NODES_LIMIT}
                """,
                {"wid": workspace_id},
            )
            orphan_list = []
            for record in orphan_result:
                orphan_list.append({
                    "id": record["id"],
                    "label": record["label"] or "Node",
                    "name": record["name"],
                })
            result["orphan_nodes"] = len(orphan_list)
            result["orphan_list"] = orphan_list

    except Exception as e:
        logger.warning(
            "dashboard.graph_stats.memgraph.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    # Get document and chunk counts from Qdrant
    try:
        from metatron.storage.qdrant import get_hybrid_store

        store = get_hybrid_store(workspace_id)
        qdrant_stats = store.get_stats()
        result["raw_documents"] = qdrant_stats.get("file_count", 0)
        result["chunks"] = qdrant_stats.get("chunk_count", 0)
    except Exception as e:
        logger.warning(
            "dashboard.graph_stats.qdrant.error",
            workspace_id=workspace_id,
            error=str(e),
        )

    return result


@router.get("/graph-stats", response_model=GraphStatsResponse)
async def get_graph_stats(workspace_id: str) -> GraphStatsResponse:
    """Get knowledge graph statistics for dashboard.

    Args:
        workspace_id: Workspace ID (query parameter).

    Returns:
        Graph statistics including nodes, edges, orphans, and lineage.

    Raises:
        HTTPException: 404 if workspace not found.
    """
    # Verify workspace exists
    manager = get_workspace_manager()
    workspace = manager.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=404,
            detail=f"Workspace '{workspace_id}' not found",
        )

    # Get graph stats (run in thread pool for Memgraph sync calls)
    stats = await asyncio.to_thread(_get_graph_stats, workspace_id)

    return GraphStatsResponse(
        total_nodes=stats["total_nodes"],
        total_edges=stats["total_edges"],
        orphan_nodes=stats["orphan_nodes"],
        orphan_list=[
            OrphanNode(id=o["id"], label=o["label"], name=o["name"])
            for o in stats["orphan_list"]
        ],
        lineage=GraphLineage(
            raw_documents=stats["raw_documents"],
            chunks=stats["chunks"],
            graph_nodes=stats["total_nodes"],
        ),
    )
