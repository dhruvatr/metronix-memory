"""Tests for memgraph_retry decorator."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from metatron.storage.memgraph import memgraph_retry


class TestMemgraphRetry:
    def test_succeeds_first_attempt(self) -> None:
        @memgraph_retry()
        def ok():
            return "done"

        assert ok() == "done"

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_service_unavailable(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ServiceUnavailable("gone")
            return "recovered"

        assert flaky() == "recovered"
        assert calls["n"] == 2
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_session_expired(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise SessionExpired("expired")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 2
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_broken_pipe(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise BrokenPipeError("pipe")
            return "ok"

        assert flaky() == "ok"
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_retries_on_generic_connection_string(self, mock_close) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("connection reset by peer")
            return "ok"

        assert flaky() == "ok"
        mock_close.assert_called_once()

    @patch("metatron.storage.memgraph.close_memgraph_driver")
    def test_raises_after_max_attempts(self, mock_close) -> None:
        @memgraph_retry(max_attempts=3)
        def always_fails():
            raise ServiceUnavailable("down")

        with pytest.raises(ServiceUnavailable):
            always_fails()
        assert mock_close.call_count == 2  # called on attempts 1 and 2, not 3

    def test_non_connection_error_raises_immediately(self) -> None:
        calls = {"n": 0}

        @memgraph_retry()
        def bad():
            calls["n"] += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            bad()
        assert calls["n"] == 1  # no retry

    def test_preserves_function_args(self) -> None:
        @memgraph_retry()
        def add(a: int, b: int, extra: str = "") -> str:
            return f"{a + b}{extra}"

        assert add(2, 3) == "5"
        assert add(1, 2, extra="!") == "3!"
