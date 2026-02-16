"""Token-aware context budget management for LLM calls.

Estimates token counts without external tokenizer dependencies and
selects fragments that fit within a configurable token budget.
"""

from __future__ import annotations

import json

import structlog

logger = structlog.get_logger()


def estimate_tokens(text: str) -> int:
    """Estimate token count for mixed-language text.

    Rule of thumb: ~4 chars per token for Latin script,
    ~2 chars per token for Cyrillic/CJK. Fast and dependency-free.
    """
    if not text:
        return 0
    cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
    other = len(text) - cyrillic
    return (other // 4) + (cyrillic // 2)


def estimate_graph_tokens(
    g_ents: list[dict],
    g_rels: list[dict],
    g_docs: list[dict],
) -> int:
    """Estimate tokens for the graph context section of the prompt."""
    raw = json.dumps(
        {"entities": g_ents, "relationships": g_rels, "documents": g_docs},
        ensure_ascii=False,
    )
    return estimate_tokens(raw)


def select_fragments_within_budget(
    fragments: list[str],
    max_tokens: int = 6000,
    system_prompt_tokens: int = 500,
    answer_reserve_tokens: int = 1500,
    graph_tokens: int = 0,
) -> list[str]:
    """Select as many fragments as fit within the token budget.

    Budget = max_tokens - system_prompt - answer_reserve - graph_context.
    Fragments are already ranked by relevance (best first).
    Greedily adds fragments until the budget is exhausted.

    Args:
        fragments: Relevance-ranked text fragments.
        max_tokens: Total token budget for the LLM context window.
        system_prompt_tokens: Estimated tokens for the system prompt.
        answer_reserve_tokens: Tokens reserved for LLM answer generation.
        graph_tokens: Tokens already allocated to graph context.

    Returns:
        List of fragments that fit within the budget.
    """
    available = max_tokens - system_prompt_tokens - answer_reserve_tokens - graph_tokens
    if available <= 0:
        logger.warning("token_budget.no_room",
                        max_tokens=max_tokens, graph_tokens=graph_tokens)
        return []

    selected: list[str] = []
    used = 0

    for frag in fragments:
        frag_tokens = estimate_tokens(frag)
        if used + frag_tokens > available:
            if not selected:
                ratio = available / max(frag_tokens, 1)
                truncated = frag[: int(len(frag) * ratio)]
                selected.append(truncated)
            break
        selected.append(frag)
        used += frag_tokens

    logger.info("token_budget.selected",
                available=len(fragments), selected=len(selected),
                tokens_used=used, tokens_budget=available)
    return selected
