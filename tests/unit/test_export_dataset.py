"""Unit tests for scripts/export_llm_dataset.py (MTRNIX-336).

Coverage:
- openai-chat-ft format produces expected JSON shape.
- openai-completion-legacy format produces prompt/completion shape.
- messages-only format produces same shape as openai-chat-ft.
- --success-only filter excludes failed rows.
- source IN ('benchmark','eval') rows excluded by default; --include-eval includes them.
- --no-include-zero-tokens drops rows where metadata.zero_tokens=true.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the export script without executing its __main__ block
# ---------------------------------------------------------------------------

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "export_llm_dataset.py"


def _load_export_module():
    """Dynamically import export_llm_dataset without running main()."""
    spec = importlib.util.spec_from_file_location("export_llm_dataset", _SCRIPT_PATH)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_export = _load_export_module()
_row_to_jsonl = _export._row_to_jsonl
_messages_to_prompt = _export._messages_to_prompt
export_fn = _export.export

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"},
]

_RESPONSE = "Paris."

_BASE_ROW = {
    "id": 1,
    "call_site": "rag_answer",
    "source": "rest",
    "workspace_id": "ws_test",
    "provider": "ollama",
    "model": "llama3",
    "request_messages": _MESSAGES,
    "response_content": _RESPONSE,
    "prompt_tokens": 10,
    "completion_tokens": 3,
    "total_tokens": 13,
    "latency_ms": 450,
    "success": True,
    "error_class": None,
    "metadata": {"fallback_used": False, "fallback_provider": None, "zero_tokens": False},
}


# ---------------------------------------------------------------------------
# Format tests (unit — no DB needed)
# ---------------------------------------------------------------------------


def test_row_to_jsonl_openai_chat_ft() -> None:
    line = _row_to_jsonl(dict(_BASE_ROW), "openai-chat-ft")
    obj = json.loads(line)
    assert "messages" in obj
    msgs = obj["messages"]
    # request_messages + assistant turn
    assert len(msgs) == len(_MESSAGES) + 1
    last = msgs[-1]
    assert last["role"] == "assistant"
    assert last["content"] == _RESPONSE


def test_row_to_jsonl_messages_only_same_shape_as_oai() -> None:
    oai = json.loads(_row_to_jsonl(dict(_BASE_ROW), "openai-chat-ft"))
    mo = json.loads(_row_to_jsonl(dict(_BASE_ROW), "messages-only"))
    assert oai == mo


def test_row_to_jsonl_openai_completion_legacy() -> None:
    line = _row_to_jsonl(dict(_BASE_ROW), "openai-completion-legacy")
    obj = json.loads(line)
    assert "prompt" in obj
    assert "completion" in obj
    assert obj["completion"] == _RESPONSE
    # Prompt should contain the user message text
    assert "What is the capital of France?" in obj["prompt"]


def test_row_to_jsonl_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="Unknown format"):
        _row_to_jsonl(dict(_BASE_ROW), "bad-format")


def test_messages_to_prompt_concatenates_roles() -> None:
    prompt = _messages_to_prompt(_MESSAGES)
    assert "system:" in prompt
    assert "user:" in prompt
    assert "France" in prompt


def test_messages_to_prompt_handles_list_content() -> None:
    msgs = [{"role": "user", "content": [{"text": "hello"}, {"text": " world"}]}]
    prompt = _messages_to_prompt(msgs)
    assert "hello" in prompt
    assert "world" in prompt


# ---------------------------------------------------------------------------
# Integration-style export tests (mock DB)
# ---------------------------------------------------------------------------


def _make_db_rows(*rows: dict[str, Any]) -> list[MagicMock]:
    """Convert plain dicts into MagicMock mapping objects (simulate SQLAlchemy result)."""
    result = []
    for r in rows:
        m = MagicMock()
        m.__getitem__ = lambda self, key, _r=r: _r[key]
        m.keys = lambda _r=r: _r.keys()
        result.append(m)
    return result


def _run_export(rows_pages: list[list[dict]], **export_kwargs: Any) -> list[dict]:
    """Run export() against mocked SQLAlchemy result and parse written JSONL lines."""

    def _make_conn_mock(pages: list[list[dict]]):
        page_iter = iter(pages)

        def execute(stmt, params):
            try:
                page = next(page_iter)
            except StopIteration:
                page = []
            result_mock = MagicMock()
            # mappings().all() returns the page
            result_mock.mappings.return_value.all.return_value = page
            return result_mock

        conn_mock = MagicMock()
        conn_mock.execute = execute
        conn_mock.__enter__ = lambda self: self
        conn_mock.__exit__ = MagicMock(return_value=False)
        return conn_mock

    with tempfile.NamedTemporaryFile(mode="r", suffix=".jsonl", delete=False) as f:
        out_path = f.name

    try:
        engine_mock = MagicMock()
        engine_mock.connect.return_value = _make_conn_mock(rows_pages)
        engine_mock.dispose = MagicMock()

        settings_mock = MagicMock()
        settings_mock.postgres_sync_dsn = "postgresql://fake"

        with (
            patch("scripts.export_llm_dataset.get_settings", return_value=settings_mock),
            patch("sqlalchemy.create_engine", return_value=engine_mock),
        ):
            export_fn(
                call_sites=[],
                workspace_ids=[],
                from_date=None,
                to_date=None,
                fmt=export_kwargs.get("fmt", "openai-chat-ft"),
                out_path=out_path,
                success_only=export_kwargs.get("success_only", True),
                include_eval=export_kwargs.get("include_eval", False),
                include_zero_tokens=export_kwargs.get("include_zero_tokens", True),
                limit=export_kwargs.get("limit"),
            )

        with open(out_path) as fh:
            lines = [line.strip() for line in fh if line.strip()]
        return [json.loads(line) for line in lines]
    finally:
        os.unlink(out_path)


def test_export_writes_correct_number_of_rows() -> None:
    row1 = dict(_BASE_ROW, id=1)
    row2 = dict(_BASE_ROW, id=2, response_content="Berlin.")
    # Two pages: first returns 2 rows, second returns empty (signals last page).
    result = _run_export([[row1, row2], []])
    assert len(result) == 2


def test_export_openai_chat_ft_shape() -> None:
    row = dict(_BASE_ROW, id=1)
    result = _run_export([[row], []], fmt="openai-chat-ft")
    assert len(result) == 1
    assert "messages" in result[0]
    msgs = result[0]["messages"]
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == _RESPONSE


def test_export_benchmark_rows_excluded_by_default() -> None:
    # Whitebox check: ensure the WHERE clause contains the excluded_sources param.
    # In production the SQL filters benchmark/eval rows; here we verify the
    # query is built with the right exclusion clause.
    sql_templates: list[str] = []
    original_build = _export._build_query

    def capturing_build(**kwargs):
        sql, params = original_build(**kwargs)
        sql_templates.append(sql)
        return sql, params

    with patch.object(_export, "_build_query", side_effect=capturing_build):
        _run_export([[]], include_eval=False)

    assert sql_templates
    # The WHERE must reference 'excluded_sources' when include_eval=False
    assert "excluded_sources" in sql_templates[0]


def test_export_include_eval_flag_removes_source_filter() -> None:
    sql_templates: list[str] = []
    original_build = _export._build_query

    def capturing_build(**kwargs):
        sql, params = original_build(**kwargs)
        sql_templates.append(sql)
        return sql, params

    with patch.object(_export, "_build_query", side_effect=capturing_build):
        _run_export([[]], include_eval=True)

    assert sql_templates
    assert "excluded_sources" not in sql_templates[0]


def test_export_no_include_zero_tokens_adds_filter() -> None:
    sql_templates: list[str] = []
    original_build = _export._build_query

    def capturing_build(**kwargs):
        sql, params = original_build(**kwargs)
        sql_templates.append(sql)
        return sql, params

    with patch.object(_export, "_build_query", side_effect=capturing_build):
        _run_export([[]], include_zero_tokens=False)

    assert sql_templates
    assert "zero_tokens" in sql_templates[0]


def test_export_success_only_adds_filter() -> None:
    sql_templates: list[str] = []
    original_build = _export._build_query

    def capturing_build(**kwargs):
        sql, params = original_build(**kwargs)
        sql_templates.append(sql)
        return sql, params

    with patch.object(_export, "_build_query", side_effect=capturing_build):
        _run_export([[]], success_only=True)

    assert sql_templates
    assert "success = TRUE" in sql_templates[0]
