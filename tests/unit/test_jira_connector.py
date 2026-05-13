"""Tests for Jira connector URL generation."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

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


# ---------------------------------------------------------------------------
# _extract_updated_at — sub-minute precision for the post-filter (MTRNIX-332)
# ---------------------------------------------------------------------------


class TestExtractUpdatedAt:
    def test_parses_iso_with_tz_offset(self) -> None:
        raw = {"fields": {"updated": "2026-05-12T14:02:26.002+0300"}}
        ts = JiraConnector._extract_updated_at(raw)
        assert ts == datetime(2026, 5, 12, 11, 2, 26, 2000, tzinfo=UTC)

    def test_parses_iso_with_z_suffix(self) -> None:
        raw = {"fields": {"updated": "2026-05-12T11:02:26.000Z"}}
        ts = JiraConnector._extract_updated_at(raw)
        assert ts is not None
        assert ts.year == 2026
        assert ts.tzinfo is not None

    def test_missing_field_returns_none(self) -> None:
        assert JiraConnector._extract_updated_at({"fields": {}}) is None

    def test_missing_fields_dict_returns_none(self) -> None:
        assert JiraConnector._extract_updated_at({}) is None

    def test_unparseable_value_returns_none(self) -> None:
        raw = {"fields": {"updated": "not-a-date"}}
        assert JiraConnector._extract_updated_at(raw) is None

    def test_does_not_call_process_jira_issue(self) -> None:
        """W1: helper must read raw dict directly, not re-parse the full issue."""
        from unittest.mock import patch

        raw = {"fields": {"updated": "2026-05-12T11:02:26.000+0000"}}
        with patch("metatron.connectors.jira_processing.process_jira_issue") as mock_process:
            JiraConnector._extract_updated_at(raw)
        mock_process.assert_not_called()


# ---------------------------------------------------------------------------
# Sub-minute post-filter in fetch (MTRNIX-332)
# ---------------------------------------------------------------------------


def _raw_issue(key: str, updated: str) -> dict:
    """Minimal raw Jira REST shape needed by _issue_to_document."""
    return {
        "key": key,
        "fields": {
            "summary": "x",
            "description": "y",
            "issuetype": {"name": "Task"},
            "status": {"name": "Open"},
            "priority": {"name": "Medium"},
            "creator": {"displayName": "A", "emailAddress": "a@co"},
            "reporter": {"displayName": "A", "emailAddress": "a@co"},
            "assignee": None,
            "created": updated,
            "updated": updated,
            "resolutiondate": None,
            "labels": [],
            "components": [],
            "comment": {"comments": []},
        },
    }


class TestFetchPostFilter:
    @pytest.mark.asyncio
    async def test_drops_issue_with_updated_equal_to_since(self) -> None:
        """An issue whose updated == since is sub-minute boundary noise — drop it.

        JQL with minute-precision filter (>= "22:09") matches the same-minute
        issue (22:09:27); the post-filter must remove it so we don't re-emit
        the same doc every sync until the cursor's minute advances.
        """
        connector = JiraConnector()
        connector._config = {"url": "https://co.atlassian.net", "project_key": "P"}
        since = datetime(2026, 5, 12, 22, 9, 27, tzinfo=UTC)
        same_minute = "2026-05-12T22:09:27.000+0000"

        connector._client = MagicMock()
        connector._client.enhanced_jql = MagicMock(
            return_value={
                "issues": [_raw_issue("P-1", same_minute)],
                "isLast": True,
            }
        )

        docs = await connector.fetch(workspace_id="ws1", since=since)
        assert docs == [], "issue with updated == since must be filtered out"

    @pytest.mark.asyncio
    async def test_keeps_issue_with_updated_after_since(self) -> None:
        connector = JiraConnector()
        connector._config = {"url": "https://co.atlassian.net", "project_key": "P"}
        since = datetime(2026, 5, 12, 22, 9, 27, tzinfo=UTC)
        later = "2026-05-12T22:09:28.000+0000"

        connector._client = MagicMock()
        connector._client.enhanced_jql = MagicMock(
            return_value={
                "issues": [_raw_issue("P-1", later)],
                "isLast": True,
            }
        )

        docs = await connector.fetch(workspace_id="ws1", since=since)
        assert len(docs) == 1
        assert docs[0].source_id == "P-1"

    @pytest.mark.asyncio
    async def test_no_post_filter_when_since_is_none(self) -> None:
        """Initial sync (since=None) keeps everything regardless of updated."""
        connector = JiraConnector()
        connector._config = {"url": "https://co.atlassian.net", "project_key": "P"}

        connector._client = MagicMock()
        connector._client.enhanced_jql = MagicMock(
            return_value={
                "issues": [
                    _raw_issue("P-1", "2020-01-01T00:00:00.000+0000"),
                    _raw_issue("P-2", "2026-01-01T00:00:00.000+0000"),
                ],
                "isLast": True,
            }
        )

        docs = await connector.fetch(workspace_id="ws1", since=None)
        assert len(docs) == 2
