"""Tests for dashboard API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from metatron.api.app import create_app
from metatron.workspaces.models import Workspace, WorkspaceStats


@pytest.fixture
def client():
    """Create test client."""
    app = create_app()
    return TestClient(app)


def test_overview_kpi_success(client):
    """Test successful overview KPI retrieval."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._count_active_connectors") as mock_count, \
         patch("metatron.storage.qdrant.get_hybrid_store") as mock_qdrant, \
         patch("metatron.storage.memgraph.get_memgraph_driver") as mock_memgraph:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_stats = WorkspaceStats(
            last_upload_time="2026-03-02T09:12:00Z",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        mock_mgr.return_value.get_workspace_stats.return_value = mock_stats
        
        # Mock Qdrant stats
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"file_count": 12483}
        mock_qdrant.return_value = mock_store
        
        # Mock Memgraph jira count
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"cnt": 841}
        mock_session.run.return_value = mock_result
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_memgraph.return_value = mock_driver
        
        # Mock active connectors count
        mock_count.return_value = 3
        
        response = client.get("/api/v1/dashboard/overview?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 12483
        assert data["jira_issues"] == 841
        assert data["active_connectors"] == 3
        assert data["last_upload"] == "2026-03-02T09:12:00Z"


def test_overview_kpi_workspace_not_found(client):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None
        
        response = client.get("/api/v1/dashboard/overview?workspace_id=nonexistent")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_overview_kpi_postgres_error_graceful_degradation(client):
    """Test graceful degradation when PostgreSQL fails."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._count_active_connectors") as mock_count, \
         patch("metatron.storage.qdrant.get_hybrid_store") as mock_qdrant, \
         patch("metatron.storage.memgraph.get_memgraph_driver") as mock_memgraph:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_stats = WorkspaceStats(
            last_upload_time="2026-03-02T09:12:00Z",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        mock_mgr.return_value.get_workspace_stats.return_value = mock_stats
        
        # Mock Qdrant stats
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"file_count": 100}
        mock_qdrant.return_value = mock_store
        
        # Mock Memgraph jira count
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"cnt": 10}
        mock_session.run.return_value = mock_result
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_memgraph.return_value = mock_driver
        
        # Mock PostgreSQL error - function returns 0
        mock_count.return_value = 0
        
        response = client.get("/api/v1/dashboard/overview?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 100
        assert data["jira_issues"] == 10
        assert data["active_connectors"] == 0  # Graceful degradation
        assert data["last_upload"] == "2026-03-02T09:12:00Z"


def test_overview_kpi_null_last_upload(client):
    """Test handling of null last_upload_time."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._count_active_connectors") as mock_count, \
         patch("metatron.storage.qdrant.get_hybrid_store") as mock_qdrant, \
         patch("metatron.storage.memgraph.get_memgraph_driver") as mock_memgraph:
        
        # Mock workspace manager with null last_upload_time
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_stats = WorkspaceStats(
            last_upload_time=None,  # No uploads yet
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        mock_mgr.return_value.get_workspace_stats.return_value = mock_stats
        
        # Mock Qdrant stats
        mock_store = MagicMock()
        mock_store.get_stats.return_value = {"file_count": 0}
        mock_qdrant.return_value = mock_store
        
        # Mock Memgraph jira count
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.single.return_value = {"cnt": 0}
        mock_session.run.return_value = mock_result
        mock_driver = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_memgraph.return_value = mock_driver
        
        mock_count.return_value = 0
        
        response = client.get("/api/v1/dashboard/overview?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == 0
        assert data["jira_issues"] == 0
        assert data["active_connectors"] == 0
        assert data["last_upload"] is None


def test_overview_kpi_missing_workspace_id(client):
    """Test 422 when workspace_id parameter is missing."""
    response = client.get("/api/v1/dashboard/overview")
    
    assert response.status_code == 422  # FastAPI validation error



def test_sync_history_success(client):
    """Test successful sync history retrieval."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_sync_history") as mock_history:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock sync history
        from metatron.api.routes.dashboard import SyncHistoryItem
        mock_history.return_value = [
            SyncHistoryItem(
                id="sync_1",
                source="confluence",
                title="Confluence Sync",
                started="2026-03-02T08:45:12Z",
                duration_ms=1240.5,
                records=18,
                status="success",
            ),
            SyncHistoryItem(
                id="sync_2",
                source="jira",
                title="Jira Sync",
                started="2026-03-02T07:30:00Z",
                duration_ms=890.2,
                records=12,
                status="partial",
            ),
        ]
        
        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=10")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["items"][0]["id"] == "sync_1"
        assert data["items"][0]["source"] == "confluence"
        assert data["items"][0]["title"] == "Confluence Sync"
        assert data["items"][0]["duration_ms"] == 1240.5
        assert data["items"][0]["records"] == 18
        assert data["items"][0]["status"] == "success"


def test_sync_history_workspace_not_found(client):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None
        
        response = client.get("/api/v1/dashboard/sync-history?workspace_id=nonexistent")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_sync_history_empty_result(client):
    """Test empty sync history."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_sync_history") as mock_history:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock empty history
        mock_history.return_value = []
        
        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []


def test_sync_history_custom_limit(client):
    """Test sync history with custom limit."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_sync_history") as mock_history:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock sync history
        from metatron.api.routes.dashboard import SyncHistoryItem
        mock_history.return_value = [
            SyncHistoryItem(
                id=f"sync_{i}",
                source="confluence",
                title=f"Sync {i}",
                started="2026-03-02T08:00:00Z",
                duration_ms=1000.0,
                records=10,
                status="success",
            )
            for i in range(5)
        ]
        
        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=5")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5
        # Verify limit was passed to the function
        mock_history.assert_called_once_with("test-ws", 5)


def test_sync_history_limit_validation(client):
    """Test limit parameter validation."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Test limit too large
        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=101")
        assert response.status_code == 422
        
        # Test limit too small
        response = client.get("/api/v1/dashboard/sync-history?workspace_id=test-ws&limit=0")
        assert response.status_code == 422


def test_ingestion_errors_success(client):
    """Test successful ingestion errors retrieval."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_ingestion_errors") as mock_errors:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock ingestion errors
        from metatron.api.routes.dashboard import IngestionErrorItem
        mock_errors.return_value = (
            14,  # total count
            [
                IngestionErrorItem(
                    source="confluence",
                    record="page_id:12345 — Migration Guide",
                    error="Qdrant timeout after 30s",
                    time="2026-03-02T07:30:00Z",
                    severity="warning",
                ),
                IngestionErrorItem(
                    source="jira",
                    record="Jira Sync",
                    error="Connection refused",
                    time="2026-03-02T06:15:00Z",
                    severity="critical",
                ),
            ],
        )
        
        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=20")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 14
        assert len(data["items"]) == 2
        assert data["items"][0]["source"] == "confluence"
        assert data["items"][0]["record"] == "page_id:12345 — Migration Guide"
        assert data["items"][0]["error"] == "Qdrant timeout after 30s"
        assert data["items"][0]["severity"] == "warning"
        assert data["items"][1]["severity"] == "critical"


def test_ingestion_errors_workspace_not_found(client):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None
        
        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=nonexistent")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_ingestion_errors_empty_result(client):
    """Test empty ingestion errors (no failures)."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_ingestion_errors") as mock_errors:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock empty errors
        mock_errors.return_value = (0, [])
        
        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


def test_ingestion_errors_custom_limit(client):
    """Test ingestion errors with custom limit."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_ingestion_errors") as mock_errors:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock ingestion errors
        from metatron.api.routes.dashboard import IngestionErrorItem
        mock_errors.return_value = (
            50,  # total count
            [
                IngestionErrorItem(
                    source="confluence",
                    record=f"Error {i}",
                    error="Test error",
                    time="2026-03-02T08:00:00Z",
                    severity="warning",
                )
                for i in range(10)
            ],
        )
        
        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=10")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 50
        assert len(data["items"]) == 10
        # Verify limit was passed to the function
        mock_errors.assert_called_once_with("test-ws", 10)


def test_ingestion_errors_limit_validation(client):
    """Test limit parameter validation."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Test limit too large
        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=101")
        assert response.status_code == 422
        
        # Test limit too small
        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws&limit=0")
        assert response.status_code == 422


def test_ingestion_errors_graceful_degradation(client):
    """Test graceful degradation when PostgreSQL fails."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_ingestion_errors") as mock_errors:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock PostgreSQL error - function returns empty result
        mock_errors.return_value = (0, [])
        
        response = client.get("/api/v1/dashboard/ingestion-errors?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


def test_query_trend_success(client):
    """Test successful query trend retrieval."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_query_trend") as mock_trend:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock query trend data
        mock_trend.return_value = (
            ["2026-02-01", "2026-02-02", "2026-02-03"],
            [124, 98, 156],
        )
        
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=30")
        
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == ["2026-02-01", "2026-02-02", "2026-02-03"]
        assert data["values"] == [124, 98, 156]


def test_query_trend_workspace_not_found(client):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None
        
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=nonexistent")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_query_trend_empty_result(client):
    """Test empty query trend (no queries yet)."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_query_trend") as mock_trend:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock empty trend (all zeros)
        mock_trend.return_value = (
            ["2026-03-01", "2026-03-02", "2026-03-03"],
            [0, 0, 0],
        )
        
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=3")
        
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == ["2026-03-01", "2026-03-02", "2026-03-03"]
        assert data["values"] == [0, 0, 0]


def test_query_trend_custom_days(client):
    """Test query trend with custom days parameter."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_query_trend") as mock_trend:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock trend data for 7 days
        mock_trend.return_value = (
            [f"2026-02-{i:02d}" for i in range(1, 8)],
            [10, 20, 15, 30, 25, 18, 22],
        )
        
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=7")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["labels"]) == 7
        assert len(data["values"]) == 7
        # Verify days parameter was passed to the function
        mock_trend.assert_called_once_with("test-ws", 7)


def test_query_trend_default_days(client):
    """Test query trend with default days parameter (30)."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_query_trend") as mock_trend:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock trend data
        mock_trend.return_value = ([], [])
        
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws")
        
        assert response.status_code == 200
        # Verify default days=30 was used
        mock_trend.assert_called_once_with("test-ws", 30)


def test_query_trend_days_validation(client):
    """Test days parameter validation."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Test days too large
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=366")
        assert response.status_code == 422
        
        # Test days too small
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws&days=0")
        assert response.status_code == 422


def test_query_trend_graceful_degradation(client):
    """Test graceful degradation when PostgreSQL fails."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_query_trend") as mock_trend:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock PostgreSQL error - function returns empty arrays
        mock_trend.return_value = ([], [])
        
        response = client.get("/api/v1/dashboard/query-trend?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["labels"] == []
        assert data["values"] == []


def test_graph_stats_success(client):
    """Test successful graph stats retrieval."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_graph_stats") as mock_stats:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock graph stats
        mock_stats.return_value = {
            "total_nodes": 89200,
            "total_edges": 142800,
            "orphan_nodes": 2,
            "orphan_list": [
                {"id": "node_123", "label": "Entity", "name": "Deprecated API v1"},
                {"id": "node_456", "label": "Document", "name": "Old Doc"},
            ],
            "raw_documents": 24831,
            "chunks": 412000,
        }
        
        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 89200
        assert data["total_edges"] == 142800
        assert data["orphan_nodes"] == 2
        assert len(data["orphan_list"]) == 2
        assert data["orphan_list"][0]["id"] == "node_123"
        assert data["orphan_list"][0]["label"] == "Entity"
        assert data["orphan_list"][0]["name"] == "Deprecated API v1"
        assert data["lineage"]["raw_documents"] == 24831
        assert data["lineage"]["chunks"] == 412000
        assert data["lineage"]["graph_nodes"] == 89200


def test_graph_stats_workspace_not_found(client):
    """Test 404 when workspace doesn't exist."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr:
        mock_mgr.return_value.get_workspace.return_value = None
        
        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=nonexistent")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


def test_graph_stats_empty_graph(client):
    """Test graph stats with empty graph."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_graph_stats") as mock_stats:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock empty graph
        mock_stats.return_value = {
            "total_nodes": 0,
            "total_edges": 0,
            "orphan_nodes": 0,
            "orphan_list": [],
            "raw_documents": 0,
            "chunks": 0,
        }
        
        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 0
        assert data["total_edges"] == 0
        assert data["orphan_nodes"] == 0
        assert data["orphan_list"] == []
        assert data["lineage"]["raw_documents"] == 0
        assert data["lineage"]["chunks"] == 0
        assert data["lineage"]["graph_nodes"] == 0


def test_graph_stats_no_orphans(client):
    """Test graph stats with no orphan nodes."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_graph_stats") as mock_stats:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock graph with no orphans
        mock_stats.return_value = {
            "total_nodes": 1000,
            "total_edges": 2500,
            "orphan_nodes": 0,
            "orphan_list": [],
            "raw_documents": 100,
            "chunks": 5000,
        }
        
        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 1000
        assert data["total_edges"] == 2500
        assert data["orphan_nodes"] == 0
        assert data["orphan_list"] == []


def test_graph_stats_graceful_degradation(client):
    """Test graceful degradation when Memgraph/Qdrant fails."""
    with patch("metatron.api.routes.dashboard.get_workspace_manager") as mock_mgr, \
         patch("metatron.api.routes.dashboard._get_graph_stats") as mock_stats:
        
        # Mock workspace manager
        mock_ws = Workspace(
            workspace_id="test-ws",
            name="Test Workspace",
        )
        mock_mgr.return_value.get_workspace.return_value = mock_ws
        
        # Mock error - function returns zeros
        mock_stats.return_value = {
            "total_nodes": 0,
            "total_edges": 0,
            "orphan_nodes": 0,
            "orphan_list": [],
            "raw_documents": 0,
            "chunks": 0,
        }
        
        response = client.get("/api/v1/dashboard/graph-stats?workspace_id=test-ws")
        
        assert response.status_code == 200
        data = response.json()
        assert data["total_nodes"] == 0
        assert data["total_edges"] == 0
