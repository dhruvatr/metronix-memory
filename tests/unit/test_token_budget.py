"""Tests for retrieval/token_budget.py — token estimation and fragment selection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from metatron.retrieval.token_budget import (
    estimate_graph_tokens,
    estimate_tokens,
    select_fragments_within_budget,
)


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_english_text(self) -> None:
        """English text: ~4 chars per token."""
        text = "Hello world, this is a test."  # 28 chars
        tokens = estimate_tokens(text)
        assert tokens == 28 // 4  # 7

    def test_russian_text(self) -> None:
        """Russian text: ~2 chars per token."""
        text = "Привет мир"  # 10 chars, all Cyrillic (9 letters + 1 space)
        tokens = estimate_tokens(text)
        # 9 Cyrillic chars → 9 // 2 = 4, 1 space (other) → 1 // 4 = 0
        assert tokens == 4

    def test_mixed_text(self) -> None:
        """Mixed English + Russian text."""
        text = "Hello Привет"  # 6 latin + 1 space + 6 cyrillic = 12 chars
        tokens = estimate_tokens(text)
        # 7 other chars → 7 // 4 = 1, 6 cyrillic → 6 // 2 = 3
        assert tokens == 4

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_none_like_empty(self) -> None:
        assert estimate_tokens("") == 0


# ---------------------------------------------------------------------------
# select_fragments_within_budget
# ---------------------------------------------------------------------------

class TestSelectFragmentsWithinBudget:
    def test_all_fit(self) -> None:
        """When all fragments fit within budget, all are returned."""
        frags = ["short frag one", "short frag two", "short frag three"]
        result = select_fragments_within_budget(
            frags, max_tokens=6000, answer_reserve_tokens=500,
        )
        assert result == frags

    def test_budget_exceeded(self) -> None:
        """When budget is tight, only first N fragments are returned."""
        # Each fragment ~500 tokens (2000 chars / 4)
        frags = ["A" * 2000 for _ in range(10)]
        result = select_fragments_within_budget(
            frags, max_tokens=2000, system_prompt_tokens=500,
            answer_reserve_tokens=500,
        )
        # Budget = 2000 - 500 - 500 = 1000 tokens → 2 fragments fit (500 each)
        assert len(result) == 2

    def test_single_huge_fragment_truncated(self) -> None:
        """A single fragment exceeding budget gets truncated."""
        huge = "B" * 40000  # ~10000 tokens
        result = select_fragments_within_budget(
            [huge], max_tokens=2000, system_prompt_tokens=500,
            answer_reserve_tokens=500,
        )
        assert len(result) == 1
        assert len(result[0]) < len(huge)

    def test_empty_list(self) -> None:
        result = select_fragments_within_budget([])
        assert result == []

    def test_respects_answer_reserve(self) -> None:
        """Higher answer reserve → fewer fragments fit."""
        frag = "C" * 4000  # ~1000 tokens
        # Low reserve: budget = 3000 - 500 - 500 = 2000 → fits
        result_low = select_fragments_within_budget(
            [frag], max_tokens=3000, system_prompt_tokens=500,
            answer_reserve_tokens=500,
        )
        assert len(result_low) == 1

        # High reserve: budget = 3000 - 500 - 2000 = 500 → doesn't fit (truncated)
        result_high = select_fragments_within_budget(
            [frag], max_tokens=3000, system_prompt_tokens=500,
            answer_reserve_tokens=2000,
        )
        assert len(result_high) == 1
        assert len(result_high[0]) < len(frag)

    def test_graph_tokens_reduce_fragment_budget(self) -> None:
        """Graph context tokens reduce the space available for fragments."""
        frag = "D" * 4000  # ~1000 tokens
        # No graph: budget = 3000 - 500 - 500 = 2000 → fits
        result_no_graph = select_fragments_within_budget(
            [frag], max_tokens=3000, system_prompt_tokens=500,
            answer_reserve_tokens=500, graph_tokens=0,
        )
        assert len(result_no_graph) == 1
        assert result_no_graph[0] == frag

        # With large graph: budget = 3000 - 500 - 500 - 1500 = 500 → truncated
        result_with_graph = select_fragments_within_budget(
            [frag], max_tokens=3000, system_prompt_tokens=500,
            answer_reserve_tokens=500, graph_tokens=1500,
        )
        assert len(result_with_graph) == 1
        assert len(result_with_graph[0]) < len(frag)


# ---------------------------------------------------------------------------
# estimate_graph_tokens
# ---------------------------------------------------------------------------

class TestEstimateGraphTokens:
    def test_empty_graph(self) -> None:
        tokens = estimate_graph_tokens([], [], [])
        # Even empty JSON has some chars: {"entities":[],"relationships":[],"documents":[]}
        assert tokens > 0
        assert tokens < 50

    def test_graph_with_data(self) -> None:
        ents = [{"name": "Qdrant", "type": "Technology"}]
        rels = [{"source": "Alice", "target": "Qdrant", "type": "uses"}]
        docs = [{"doc_label": "DOC-1"}]
        tokens = estimate_graph_tokens(ents, rels, docs)
        assert tokens > 20


# ---------------------------------------------------------------------------
# Integration: search pipeline uses token budget
# ---------------------------------------------------------------------------

class TestSearchPipelineIntegration:
    @patch("metatron.retrieval.search.chat_completion_with_retry")
    @patch("metatron.retrieval.search.search_with_date_filter")
    @patch("metatron.retrieval.search.expand_query", side_effect=lambda q: q)
    @patch("metatron.retrieval.search.get_entities_by_doc_labels", return_value=[])
    @patch("metatron.retrieval.search._search_by_title", return_value=[])
    def test_token_budget_applied_before_llm_call(
        self,
        mock_title: MagicMock,
        mock_graph_ents: MagicMock,
        mock_expand: MagicMock,
        mock_search: MagicMock,
        mock_llm: MagicMock,
    ) -> None:
        """Token budget limits fragments passed to _build_ctx."""
        # Return many large results
        mock_search.return_value = [
            {"memory": "X" * 8000, "type": "jira", "title": f"Issue-{i}",
             "doc_label": f"DOC-{i}"}
            for i in range(20)
        ]
        mock_llm.return_value = "Test answer"

        from metatron.retrieval.search import hybrid_search_and_answer

        with patch("metatron.retrieval.search._s") as mock_settings:
            mock_settings.search_max_total_chars = 400000
            mock_settings.search_max_fragment_chars = 8000
            mock_settings.search_pool_multiplier = 3
            mock_settings.search_pool_min = 15
            mock_settings.llm_context_max_tokens = 3000
            mock_settings.llm_answer_reserve_tokens = 1500

            hybrid_search_and_answer("test query", workspace_id="TEST")

        # LLM was called
        mock_llm.assert_called_once()
        # The user content passed to LLM should be bounded
        call_messages = mock_llm.call_args.kwargs.get("messages") or mock_llm.call_args[1].get("messages")
        user_content = call_messages[-1]["content"]
        # With 3000 max tokens and 1500 answer reserve, ~1000 tokens for fragments
        # That's roughly ~4000 chars — far less than 20 * 8000 = 160000
        assert len(user_content) < 20000
