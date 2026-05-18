"""LLM generation telemetry context and emission (MTRNIX-336).

This module owns the per-request TelemetryContext ContextVar, the
``set_telemetry_context`` context-manager helper used by entry-points
(REST, MCP, ingestion, freshness), the ``update_retrieved_context`` mutator
called just before the RAG-answer LLM call, and the synchronous ``emit_log``
that writes one row to ``llm_generation_log``.

Design constraints
------------------
* ``emit_log`` is **fully synchronous** — ``chat_completion`` runs inside
  ``asyncio.to_thread`` (no event loop in the calling thread), so
  ``asyncio.create_task`` would raise RuntimeError. The insert goes via
  ``storage.pg_connection.get_session()`` (psycopg2) in the same thread.
* The module never raises from ``emit_log`` — any write failure is logged at
  WARNING and silently discarded.
* The opt-out cache is protected by ``threading.Lock`` (sync code path).
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from metatron.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Generator
    from uuid import UUID

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# TelemetryContext dataclass — mutable so update_retrieved_context can patch
# the current instance in-place without resetting the ContextVar token.
# ---------------------------------------------------------------------------


@dataclass
class TelemetryContext:
    """Mutable per-request telemetry context propagated via ContextVar."""

    workspace_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    source: str | None = None
    correlation_id: UUID | None = None
    retrieved_context: str | None = None
    extra_metadata: dict[str, Any] | None = None


# Module-level ContextVar — isolated per asyncio Task and per thread.
current_telemetry_ctx: ContextVar[TelemetryContext | None] = ContextVar(
    "current_telemetry_ctx", default=None
)


# ---------------------------------------------------------------------------
# Context manager for entry-points
# ---------------------------------------------------------------------------


@contextmanager
def set_telemetry_context(
    *,
    workspace_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    source: str | None = None,
    correlation_id: UUID | None = None,
) -> Generator[TelemetryContext, None, None]:
    """Push a fresh TelemetryContext onto the ContextVar for the duration of the block.

    Nested usage: the child scope replaces the parent for its duration; on exit
    the parent's token is restored.  The child does NOT inherit the parent's
    ``retrieved_context`` — each scope starts clean.
    """
    ctx = TelemetryContext(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        source=source,
        correlation_id=correlation_id,
    )
    token: Token[TelemetryContext | None] = current_telemetry_ctx.set(ctx)
    try:
        yield ctx
    finally:
        current_telemetry_ctx.reset(token)


# ---------------------------------------------------------------------------
# Mutator — called just before the RAG-answer LLM call
# ---------------------------------------------------------------------------


def update_retrieved_context(text: str) -> None:
    """Set retrieved_context on the current TelemetryContext instance.

    No-op when no context is active.
    """
    ctx = current_telemetry_ctx.get()
    if ctx is not None:
        ctx.retrieved_context = text


def add_extra_metadata(**kv: Any) -> None:
    """Merge keys into ``extra_metadata`` on the current TelemetryContext.

    Safer than ``current_telemetry_ctx.get().extra_metadata = {...}``: assign
    obliterates whatever a previous call site wrote. This helper merges, so
    multiple call sites in the same scope (search.py setting subtype/lang,
    neo4j_graph.py setting doc_label) can coexist.

    No-op when no context is active.
    """
    ctx = current_telemetry_ctx.get()
    if ctx is None:
        return
    if ctx.extra_metadata is None:
        ctx.extra_metadata = {}
    ctx.extra_metadata.update(kv)


# ---------------------------------------------------------------------------
# Opt-out cache (workspace-level, TTL-based, threading.Lock guarded)
# ---------------------------------------------------------------------------

# {workspace_id: (opt_out: bool, fetched_at: float)}
_opt_out_cache: dict[str, tuple[bool, float]] = {}
# Coarse lock guarding the cache dict and the per-workspace lock dict below.
_opt_out_cache_lock = threading.Lock()
# Per-workspace locks ensure N concurrent misses on the same workspace_id
# issue ONE PG SELECT, not N — without blocking misses on other workspaces.
_opt_out_per_ws_locks: dict[str, threading.Lock] = {}


def _get_per_ws_lock(workspace_id: str) -> threading.Lock:
    """Return the lock for ``workspace_id``, creating it if needed."""
    with _opt_out_cache_lock:
        lock = _opt_out_per_ws_locks.get(workspace_id)
        if lock is None:
            lock = threading.Lock()
            _opt_out_per_ws_locks[workspace_id] = lock
        return lock


def _is_opted_out(workspace_id: str) -> bool:
    """Return True if the workspace has llm_telemetry_opt_out=true.

    Uses a TTL cache to avoid a PG round-trip on every LLM call. Concurrent
    misses on the same ``workspace_id`` are serialised by a per-workspace
    lock that is held across the SELECT — so a thundering herd of N callers
    issues exactly one query; the (N-1) followers read the freshly-populated
    cache entry on entry into the critical section.
    """
    settings = get_settings()
    ttl = settings.llm_telemetry_opt_out_cache_ttl_seconds
    now = time.monotonic()

    # Fast path — read cache without holding the per-ws lock.
    with _opt_out_cache_lock:
        entry = _opt_out_cache.get(workspace_id)
    if entry is not None:
        opt_out, fetched_at = entry
        if now - fetched_at < ttl:
            return opt_out

    # Slow path — acquire the per-workspace lock so only one caller queries PG.
    ws_lock = _get_per_ws_lock(workspace_id)
    with ws_lock:
        # Re-check under the lock — another waiter may have populated the entry.
        now = time.monotonic()
        with _opt_out_cache_lock:
            entry = _opt_out_cache.get(workspace_id)
        if entry is not None:
            opt_out, fetched_at = entry
            if now - fetched_at < ttl:
                return opt_out

        # Still missing — issue the SELECT.
        try:
            from metatron.storage.pg_connection import get_session
            from metatron.storage.pg_models import WorkspaceRow

            with get_session() as session:
                row = session.query(WorkspaceRow).filter_by(id=workspace_id).first()
                opt_out = bool(row.llm_telemetry_opt_out) if row is not None else False
        except Exception as exc:
            logger.warning(
                "llm_telemetry.opt_out_check_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            # Fail open — write the row so we don't lose data on transient DB errors.
            return False

        with _opt_out_cache_lock:
            _opt_out_cache[workspace_id] = (opt_out, time.monotonic())

        return opt_out


# ---------------------------------------------------------------------------
# Public predicate — lets callers skip building the request-message snapshot
# entirely when telemetry will not write anything for this call. Used by
# llm.chat_completion to honour GDPR opt-out semantics ("we don't process",
# not just "we don't store"): when the workspace has opted out, the prompt
# never leaves the message-object list as a separate copy.
# ---------------------------------------------------------------------------


def is_telemetry_writable() -> bool:
    """Return True iff a row produced now would actually be written.

    Cheap path: kill-switch check + opt-out cache lookup. Workspace_id is
    read from the ambient :data:`current_telemetry_ctx`; when missing the
    function returns True (writes proceed with ``workspace_id IS NULL`` so
    the data is not lost).

    Race window: if the workspace flips opt-out between this check and the
    eventual :func:`emit_log` call, ``emit_log`` re-checks under the lock
    and drops the row — so this predicate is a fast-path optimisation,
    not a correctness gate.
    """
    settings = get_settings()
    if not settings.llm_telemetry_enabled:
        return False
    ctx = current_telemetry_ctx.get()
    if ctx is None or not ctx.workspace_id:
        return True
    return not _is_opted_out(ctx.workspace_id)


# ---------------------------------------------------------------------------
# emit_log — the main entry point called by chat_completion()
# ---------------------------------------------------------------------------


def emit_log(
    *,
    call_site: str,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    response: Any | None,  # LLMResponse | None — typed as Any to avoid circular import
    latency_ms: int,
    success: bool,
    error_class: str | None,
    error_message: str | None,
    fallback_used: bool,
    fallback_provider: str | None,
) -> None:
    """Write one telemetry row to llm_generation_log.

    Fully synchronous.  Never raises — all exceptions are caught and logged.

    Args:
        call_site: Identifier string from the audit table (e.g. "rag_answer").
        provider: Provider name (e.g. "ollama", "deepseek").
        model: Model name as returned by the provider.
        messages: The request messages list (serialisable dicts).
        response: LLMResponse on success, None on failure.
        latency_ms: Wall-clock ms for the LLM call.
        success: True if the provider returned non-empty content.
        error_class: Exception class name on failure (or "EmptyResponse").
        error_message: Short error text, already truncated to ≤512 chars.
        fallback_used: True when the primary provider failed and fallback ran.
        fallback_provider: Fallback provider name when fallback_used=True.
    """
    settings = get_settings()
    if not settings.llm_telemetry_enabled:
        return

    # Read the ambient ContextVar.
    ctx = current_telemetry_ctx.get()
    workspace_id = ctx.workspace_id if ctx is not None else None
    user_id = ctx.user_id if ctx is not None else None
    agent_id = ctx.agent_id if ctx is not None else None
    source = ctx.source if ctx is not None else None
    correlation_id = ctx.correlation_id if ctx is not None else None
    retrieved_context = ctx.retrieved_context if ctx is not None else None
    extra_metadata = dict(ctx.extra_metadata) if ctx is not None and ctx.extra_metadata else {}

    # Per-workspace opt-out.
    if workspace_id is not None and _is_opted_out(workspace_id):
        return

    # Token counts via property accessors (always return int, default 0).
    if response is not None:
        prompt_tokens: int = response.prompt_tokens
        completion_tokens: int = response.completion_tokens
        total_tokens: int = response.total_tokens
        response_content: str | None = response.content if success else None
    else:
        prompt_tokens = completion_tokens = total_tokens = 0
        response_content = None

    zero_tokens = total_tokens == 0 and prompt_tokens == 0 and completion_tokens == 0

    # Build metadata JSONB.
    metadata: dict[str, Any] = {
        "fallback_used": fallback_used,
        "fallback_provider": fallback_provider,
        "zero_tokens": zero_tokens,
        **extra_metadata,
    }
    if retrieved_context is not None and call_site == "rag_answer":
        metadata["retrieved_context"] = retrieved_context

    try:
        from metatron.storage.llm_generation_log import LLMLogRowData, insert_log_row_sync

        row = LLMLogRowData(
            call_site=call_site,
            source=source,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=agent_id,
            correlation_id=str(correlation_id) if correlation_id is not None else None,
            provider=provider,
            model=model,
            request_messages=messages,
            response_content=response_content,
            prompt_tokens=prompt_tokens if prompt_tokens else None,
            completion_tokens=completion_tokens if completion_tokens else None,
            total_tokens=total_tokens if total_tokens else None,
            latency_ms=latency_ms,
            success=success,
            error_class=error_class,
            error_message=error_message,
            metadata=metadata,
        )
        insert_log_row_sync(row)
    except Exception as exc:
        logger.warning(
            "llm_telemetry.write_failed",
            call_site=call_site,
            provider=provider,
            error=str(exc),
        )
