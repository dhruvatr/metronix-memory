# LLM Call Sites Audit — MTRNIX-336

**Date:** 2026-05-15
**Status:** Implemented (11 of 12 call sites wired; `freshness_decision` deferred)

Every LLM call site in Metatron Core, with telemetry verdict and wiring status.

| # | `call_site` label | File | Verdict | Wired | Notes |
|---|---|---|---|---|---|
| 1 | `rag_answer` | `retrieval/search.py` | **fine-tuning-grade** | ✓ | Primary target. Two branches: `use_schema=True` (`subtype="team_workflow_schema"`) and regular free-form (`subtype="freeform"`). `update_retrieved_context` called before both LLM invocations. |
| 2 | `resolve_query` | `retrieval/search.py` | telemetry-only | ✓ | Pre-step inside the same pipeline. Useful for cost analytics; secondary FT signal. |
| 3 | `translate_query` | `retrieval/search.py` | telemetry-only | ✓ | RU→EN of incoming query. |
| 4 | `hyde` | `retrieval/query_expansion.py` | telemetry-only | ✓ | Optional path; short inputs. Feature-flagged by `HYDE_ENABLED`. |
| 5 | `query_expansion` | `retrieval/query_expansion.py` | telemetry-only | ✓ | Costly when on; useful for cost analytics. |
| 6 | `query_classifier` | `retrieval/query_classifier.py` | **fine-tuning-grade** | ✓ | LLM-fallback path (rule gate handles most queries). Short input → structured JSON; ideal locality target. |
| 7 | `routing` | `retrieval/routing.py` | telemetry-only | ✓ | Keyword-gated; low volume. |
| 8 | `translation_to_english` | `ingestion/processors/translation.py` | telemetry-only | ✓ | Ingestion translation (document content). |
| 9 | `translation_to_russian` | `ingestion/processors/translation.py` | telemetry-only | ✓ | Same as above, reverse direction. |
| 10 | `ner_extraction` | `storage/neo4j_graph.py` | **fine-tuning-grade** | ✓ | Highest-volume call site (per-document). Strong FT target for a local NER SLM. `extra_metadata` carries `text_truncated`. |
| 11 | `mcp_action_planner` | `mcp/action_planner.py` | telemetry-only | ✓ | Low volume; structured-output task. |
| — | `freshness_decision` | `freshness/decision_engine.py` | **deferred (out of scope)** | ✗ | Calls `self._provider.chat_completion` (provider method) directly — NOT the public wrapper. Capturing it requires refactoring `LLMBackedDecisionEngine` to go through `metatron.llm.chat_completion`. Tracked as a follow-up to MTRNIX-336. |
| (legacy) | `agent_smalltalk` | `agent/router.py` | **skip / deprecated** | ✓ | Legacy Telegram channel path. Wired for consistency; marked deprecated per LEGACY.md. |

## Entry-point context coverage

| Source | Entry-point file | `set_telemetry_context` wired | `source` value |
|---|---|---|---|
| REST chat | `api/routes/chat.py` | ✓ | `"rest"` |
| OpenAI-compat API | `api/routes/openai_compat.py` | ✓ | `"oai_compat"` |
| MCP server | `mcp/server.py` | ✓ | `"mcp"` |
| Ingestion pipeline | `ingestion/pipeline.py` | ✓ | `"ingestion"` |
| Freshness worker | `memory/freshness/worker.py` | ✓ | `"freshness"` |
| Benchmarker runner | `benchmarker/services/runner.py` | ✓ | `"benchmark"` |
| Confidence metric | `benchmarker/services/metrics/confidence.py` | ✓ | `"benchmark"` |
| Offline eval script | `scripts/run_eval.py` | ✓ | `"eval"` |

## Key config vars

| Env var | Default | Purpose |
|---|---|---|
| `METATRON_LLM_TELEMETRY_ENABLED` | `true` | Master kill-switch. `false` → all telemetry is a no-op. |
| `METATRON_LLM_TELEMETRY_RETENTION_DAYS` | `0` | Placeholder. `0` = infinite. No cleanup worker in this ticket. |
| `METATRON_LLM_TELEMETRY_OPT_OUT_CACHE_TTL_SECONDS` | `60` | TTL for workspace opt-out flag cache. |

## Export

`scripts/export_llm_dataset.py` — streams rows from `llm_generation_log` to JSONL.
Formats: `openai-chat-ft` (default), `openai-completion-legacy`, `messages-only`.
Benchmark/eval rows excluded by default (`--include-eval` to opt in).

## Open follow-ups

- `freshness_decision` instrumentation — `LLMBackedDecisionEngine.decide` bypasses the public wrapper.
- Background writer thread for `emit_log` if PG round-trip overhead is unacceptable on NER path.
- Retention/cleanup worker for `llm_generation_log` (env var `METATRON_LLM_TELEMETRY_RETENTION_DAYS` is reserved).
- Workspace-settings UI/API for `llm_telemetry_opt_out`.
