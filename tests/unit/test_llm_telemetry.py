"""Unit tests for llm/telemetry.py (MTRNIX-336).

Coverage:
- set_telemetry_context — set/reset, nested scopes, child does not inherit
  parent's retrieved_context.
- update_retrieved_context — mutates current ctx; no-op when no ctx active.
- emit_log — no-op when kill-switch disabled.
- emit_log — no-op when workspace opt-out is true (mocked store).
- emit_log — writes when workspace_id is NULL.
- emit_log — on store failure, warning logged, never raises.
- emit_log — from asyncio.to_thread succeeds (regression guard for sync path).
- zero_tokens flag is true when response.total_tokens == 0.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    import pytest

from metatron.llm.telemetry import (
    current_telemetry_ctx,
    set_telemetry_context,
    update_retrieved_context,
)

# Path to the real module's insert function — patching it directly works no
# matter what other tests have already imported.
_INSERT_PATH = "metatron.storage.llm_generation_log.insert_log_row_sync"

# ---------------------------------------------------------------------------
# set_telemetry_context
# ---------------------------------------------------------------------------


def test_set_telemetry_context_sets_and_resets() -> None:
    assert current_telemetry_ctx.get() is None
    with set_telemetry_context(workspace_id="ws_a", source="rest"):
        ctx = current_telemetry_ctx.get()
        assert ctx is not None
        assert ctx.workspace_id == "ws_a"
        assert ctx.source == "rest"
    assert current_telemetry_ctx.get() is None


def test_set_telemetry_context_nested_child_does_not_inherit_retrieved() -> None:
    """Child scope starts with retrieved_context=None even if parent set it."""
    with set_telemetry_context(workspace_id="ws_parent", source="rest") as parent_ctx:
        parent_ctx.retrieved_context = "parent docs"
        with set_telemetry_context(workspace_id="ws_child", source="mcp") as child_ctx:
            assert child_ctx.retrieved_context is None
        # Parent restored after child scope exits.
        restored = current_telemetry_ctx.get()
        assert restored is not None
        assert restored.workspace_id == "ws_parent"
        assert restored.retrieved_context == "parent docs"


def test_set_telemetry_context_resets_on_exception() -> None:
    try:
        with set_telemetry_context(workspace_id="ws_x"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert current_telemetry_ctx.get() is None


def test_set_telemetry_context_isolation_across_tasks() -> None:
    """Each asyncio Task gets its own ContextVar copy."""

    async def task(ws: str) -> str | None:
        with set_telemetry_context(workspace_id=ws):
            await asyncio.sleep(0)
            ctx = current_telemetry_ctx.get()
            return ctx.workspace_id if ctx else None

    async def run() -> tuple[str | None, str | None]:
        return await asyncio.gather(task("ws_a"), task("ws_b"))

    a, b = asyncio.run(run())
    assert a == "ws_a"
    assert b == "ws_b"
    assert current_telemetry_ctx.get() is None


# ---------------------------------------------------------------------------
# update_retrieved_context
# ---------------------------------------------------------------------------


def test_update_retrieved_context_mutates_current_ctx() -> None:
    with set_telemetry_context(workspace_id="ws"):
        update_retrieved_context("some retrieved docs")
        ctx = current_telemetry_ctx.get()
        assert ctx is not None
        assert ctx.retrieved_context == "some retrieved docs"


def test_update_retrieved_context_noop_when_no_ctx() -> None:
    assert current_telemetry_ctx.get() is None
    # Should not raise.
    update_retrieved_context("docs")
    assert current_telemetry_ctx.get() is None


# ---------------------------------------------------------------------------
# emit_log — kill-switch
# ---------------------------------------------------------------------------


def test_emit_log_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """emit_log returns immediately when METATRON_LLM_TELEMETRY_ENABLED=false."""
    from metatron.llm import telemetry as tel_mod

    monkeypatch.setattr(
        tel_mod,
        "get_settings",
        lambda: MagicMock(
            llm_telemetry_enabled=False,
            llm_telemetry_opt_out_cache_ttl_seconds=60,
        ),
    )

    with patch(_INSERT_PATH) as mock_insert:
        # Need to import after monkeypatching to pick up the new settings mock
        from metatron.llm.telemetry import emit_log

        emit_log(
            call_site="rag_answer",
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
            response=None,
            latency_ms=100,
            success=False,
            error_class="LLMConnectionError",
            error_message="timeout",
            fallback_used=False,
            fallback_provider=None,
        )
        mock_insert.assert_not_called()


# ---------------------------------------------------------------------------
# emit_log — opt-out
# ---------------------------------------------------------------------------


def test_emit_log_noop_when_workspace_opted_out() -> None:
    """emit_log skips write when the workspace has opt_out=true."""
    from metatron.llm import telemetry as tel_mod

    with (
        patch.object(tel_mod, "_is_opted_out", return_value=True),
        patch(_INSERT_PATH) as mock_insert,
        patch.object(
            tel_mod,
            "get_settings",
            return_value=MagicMock(
                llm_telemetry_enabled=True,
                llm_telemetry_opt_out_cache_ttl_seconds=60,
            ),
        ),
        set_telemetry_context(workspace_id="ws_opted_out", source="rest"),
    ):
        from metatron.llm.telemetry import emit_log

        emit_log(
            call_site="rag_answer",
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
            response=None,
            latency_ms=50,
            success=False,
            error_class="LLMConnectionError",
            error_message="x",
            fallback_used=False,
            fallback_provider=None,
        )
        mock_insert.assert_not_called()


def test_emit_log_writes_when_workspace_id_is_null() -> None:
    """When workspace_id is None, opt-out cannot be evaluated — row is written."""
    from metatron.llm import telemetry as tel_mod
    from metatron.llm.base import LLMResponse

    response = LLMResponse(
        content="ok",
        model="llama3",
        provider="ollama",
        usage={"prompt_tokens": 5, "completion_tokens": 3},
    )

    with (
        patch.object(tel_mod, "get_settings") as mock_settings,
        patch(_INSERT_PATH) as mock_insert,
    ):
        mock_settings.return_value = MagicMock(
            llm_telemetry_enabled=True,
            llm_telemetry_opt_out_cache_ttl_seconds=60,
        )
        # No telemetry context → workspace_id is None.
        from metatron.llm.telemetry import emit_log

        emit_log(
            call_site="rag_answer",
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
            response=response,
            latency_ms=50,
            success=True,
            error_class=None,
            error_message=None,
            fallback_used=False,
            fallback_provider=None,
        )
        mock_insert.assert_called_once()


# ---------------------------------------------------------------------------
# emit_log — store failure is swallowed
# ---------------------------------------------------------------------------


def test_emit_log_swallows_store_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """emit_log catches store exceptions, logs warning, and does not re-raise."""
    from metatron.llm import telemetry as tel_mod
    from metatron.llm.base import LLMResponse

    response = LLMResponse(
        content="ok",
        model="llama3",
        provider="ollama",
        usage={"prompt_tokens": 1},
    )

    with (
        patch.object(
            tel_mod,
            "get_settings",
            return_value=MagicMock(
                llm_telemetry_enabled=True,
                llm_telemetry_opt_out_cache_ttl_seconds=60,
            ),
        ),
        patch(
            _INSERT_PATH,
            side_effect=RuntimeError("DB offline"),
        ),
    ):
        from metatron.llm.telemetry import emit_log

        # Must not raise.
        emit_log(
            call_site="rag_answer",
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
            response=response,
            latency_ms=10,
            success=True,
            error_class=None,
            error_message=None,
            fallback_used=False,
            fallback_provider=None,
        )


# ---------------------------------------------------------------------------
# emit_log — sync path works inside asyncio.to_thread (no event loop in thread)
# ---------------------------------------------------------------------------


async def test_emit_log_from_to_thread_does_not_raise() -> None:
    """Smoke test: emit_log can be called from a thread-pool worker (no event loop)."""
    from metatron.llm import telemetry as tel_mod

    with (
        patch.object(
            tel_mod,
            "get_settings",
            return_value=MagicMock(
                llm_telemetry_enabled=True,
                llm_telemetry_opt_out_cache_ttl_seconds=60,
            ),
        ),
        patch(_INSERT_PATH),
    ):
        from metatron.llm.telemetry import emit_log

        def sync_call() -> None:
            emit_log(
                call_site="rag_answer",
                provider="ollama",
                model="llama3",
                messages=[{"role": "user", "content": "hi"}],
                response=None,
                latency_ms=5,
                success=False,
                error_class="LLMConnectionError",
                error_message="x",
                fallback_used=False,
                fallback_provider=None,
            )

        # asyncio.to_thread runs in a thread where there is NO running event loop.
        await asyncio.to_thread(sync_call)


# ---------------------------------------------------------------------------
# zero_tokens metadata flag
# ---------------------------------------------------------------------------


def test_emit_log_zero_tokens_flag_true_when_all_zero() -> None:
    """zero_tokens=true when provider omits usage counts (all 0)."""
    from metatron.llm import telemetry as tel_mod
    from metatron.llm.base import LLMResponse

    # Provider that returns empty usage dict (e.g. Ollama without eval_count)
    response = LLMResponse(content="ok", model="llama3", provider="ollama", usage={})
    captured: list[dict] = []

    def fake_insert(row: object) -> None:
        # row is LLMLogRowData; grab metadata
        captured.append(row.metadata)  # type: ignore[union-attr]

    with (
        patch.object(
            tel_mod,
            "get_settings",
            return_value=MagicMock(
                llm_telemetry_enabled=True,
                llm_telemetry_opt_out_cache_ttl_seconds=60,
            ),
        ),
        patch(_INSERT_PATH, side_effect=fake_insert),
    ):
        from metatron.llm.telemetry import emit_log

        emit_log(
            call_site="rag_answer",
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
            response=response,
            latency_ms=50,
            success=True,
            error_class=None,
            error_message=None,
            fallback_used=False,
            fallback_provider=None,
        )

    assert len(captured) == 1
    assert captured[0]["zero_tokens"] is True


def test_emit_log_zero_tokens_flag_false_when_tokens_present() -> None:
    """zero_tokens=false when provider returns real token counts."""
    from metatron.llm import telemetry as tel_mod
    from metatron.llm.base import LLMResponse

    response = LLMResponse(
        content="ok",
        model="llama3",
        provider="ollama",
        usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    )
    captured: list[dict] = []

    def fake_insert(row: object) -> None:
        captured.append(row.metadata)  # type: ignore[union-attr]

    with (
        patch.object(
            tel_mod,
            "get_settings",
            return_value=MagicMock(
                llm_telemetry_enabled=True,
                llm_telemetry_opt_out_cache_ttl_seconds=60,
            ),
        ),
        patch(_INSERT_PATH, side_effect=fake_insert),
    ):
        from metatron.llm.telemetry import emit_log

        emit_log(
            call_site="rag_answer",
            provider="ollama",
            model="llama3",
            messages=[{"role": "user", "content": "hi"}],
            response=response,
            latency_ms=50,
            success=True,
            error_class=None,
            error_message=None,
            fallback_used=False,
            fallback_provider=None,
        )

    assert len(captured) == 1
    assert captured[0]["zero_tokens"] is False
