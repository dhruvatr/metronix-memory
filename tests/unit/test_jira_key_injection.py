"""Tests for Jira key exact-match injection in search pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.retrieval.search import _JIRA_KEY_RE, _inject_jira_key_results


class TestJiraKeyRegex:
    def test_extracts_standard_key(self) -> None:
        assert _JIRA_KEY_RE.findall("What is MTRNIX-108?") == ["MTRNIX-108"]

    def test_extracts_multiple_keys(self) -> None:
        keys = _JIRA_KEY_RE.findall("Compare MTRNIX-108 and PROJ-42")
        assert set(k.upper() for k in keys) == {"MTRNIX-108", "PROJ-42"}

    def test_case_insensitive(self) -> None:
        keys = _JIRA_KEY_RE.findall("mtrnix-108")
        assert [k.upper() for k in keys] == ["MTRNIX-108"]

    def test_no_match_without_key(self) -> None:
        assert _JIRA_KEY_RE.findall("What is the team doing?") == []

    def test_deduplicates_keys(self) -> None:
        keys = _JIRA_KEY_RE.findall("MTRNIX-108 vs MTRNIX-108")
        # findall returns both, but _inject_jira_key_results deduplicates
        assert len(keys) == 2  # regex finds both


class TestInjectJiraKeyResults:
    @patch("metatron.retrieval.search.get_hybrid_store")
    def test_returns_exact_match(self, mock_store) -> None:
        store = MagicMock()
        store.search_by_doc_labels.return_value = [
            {"memory": "MTRNIX-108 content", "doc_label": "MTRNIX-108"},
        ]
        mock_store.return_value = store

        results = _inject_jira_key_results("What is MTRNIX-108?", None)
        assert len(results) == 1
        store.search_by_doc_labels.assert_called_once_with(["MTRNIX-108"])

    @patch("metatron.retrieval.search.get_hybrid_store")
    def test_handles_store_error_gracefully(self, mock_store) -> None:
        mock_store.side_effect = RuntimeError("Qdrant down")

        results = _inject_jira_key_results("MTRNIX-108", None)
        assert results == []

    @patch("metatron.retrieval.search.get_hybrid_store")
    def test_deduplicates_keys(self, mock_store) -> None:
        store = MagicMock()
        store.search_by_doc_labels.return_value = []
        mock_store.return_value = store

        _inject_jira_key_results("MTRNIX-108 vs mtrnix-108", None)
        store.search_by_doc_labels.assert_called_once_with(["MTRNIX-108"])
