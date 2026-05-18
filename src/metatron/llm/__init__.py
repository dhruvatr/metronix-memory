"""Multi-provider LLM abstraction for Metatron.

Usage::

    from metatron.llm import chat_completion

    # Simple usage - uses configured provider
    result = chat_completion(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ]
    )
    print(result)  # "Hello! How can I help you today?"

    # With options
    result = chat_completion(
        messages=[...],
        temperature=0.1,
        max_tokens=500,
        json_mode=True,
    )

    # Direct provider access
    from metatron.llm import get_llm

    llm = get_llm()
    response = llm.chat_completion(messages=[...])
    print(response.content)
    print(response.model, response.provider)

Configuration via environment variables::

    LLM_PROVIDER=deepseek|openrouter|ollama|custom
    LLM_MODEL=model-name (optional, uses provider default)

    # Fallback (optional)
    LLM_FALLBACK_PROVIDER=ollama
    LLM_FALLBACK_MODEL=llama3

    # Provider-specific
    DEEPSEEK_API_KEY=sk-xxx
    OPENROUTER_API_KEY=sk-xxx
    OLLAMA_LLM_HOST=http://localhost:11434
    OLLAMA_LLM_MODEL=llama3
    CUSTOM_LLM_URL=http://server:8080/v1/chat/completions
"""

import time
from time import perf_counter
from typing import Any

import structlog

from metatron.llm.base import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    Message,
)
from metatron.llm.provider import (
    PROVIDERS,
    _get_cached_fallback,
    create_provider,
    get_fallback_provider,
    get_llm,
    get_provider_class,
)
from metatron.llm.telemetry import emit_log, is_telemetry_writable
from metatron.observability.metrics import timed

logger = structlog.get_logger()

__all__ = [
    # Public API
    "chat_completion",
    "chat_completion_with_retry",
    "get_llm",
    # Provider management
    "create_provider",
    "get_provider_class",
    "get_fallback_provider",
    "PROVIDERS",
    # Types and exceptions
    "LLMProvider",
    "LLMResponse",
    "Message",
    "LLMError",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
]


@timed("llm_completion")
def chat_completion(  # TODO: async migration
    messages: list[dict[str, str] | Message],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    json_mode: bool = False,
    timeout: int = 60,
    provider: str | None = None,
    model: str | None = None,
    use_fallback: bool = True,
    *,
    call_site: str,
    **kwargs: Any,
) -> str:
    """Send a chat completion request to the configured LLM provider.

    This is the main entry point for LLM calls. It handles provider
    selection, fallback on failure, and returns just the response content.

    Args:
        messages: Sequence of messages, each as a dict or Message instance.
        temperature: Sampling temperature (0-2, default 0.7).
        max_tokens: Maximum tokens in response (optional).
        json_mode: Request JSON output format (default False).
        timeout: Request timeout in seconds (default 60).
        provider: Provider name override (optional).
        model: Model name override (optional).
        use_fallback: Whether to try fallback provider on failure.
        call_site: Identifier for this LLM call site (required, keyword-only).
            Used as the ``call_site`` column in ``llm_generation_log``.
        **kwargs: Additional provider-specific parameters.

    Returns:
        Response content as string.

    Raises:
        LLMError: If all providers fail.
    """
    # Convert dicts to Message objects
    msg_objects: list[Message] = []
    for m in messages:
        if isinstance(m, Message):
            msg_objects.append(m)
        elif isinstance(m, dict):
            role = m.get("role")
            content = m.get("content")
            if not role or content is None:
                raise ValueError(f"Invalid message format: missing 'role' or 'content' in {m}")
            msg_objects.append(Message(role=role, content=content))
        else:
            raise ValueError(f"Invalid message type: {type(m)}")

    # Telemetry early-gate — when the workspace has opted out (or the master
    # kill-switch is off), do NOT build a copy of the prompt content. This
    # makes the privacy story "we do not process this prompt" rather than the
    # weaker "we do not store it". emit_log() still re-checks under its own
    # lock, so a flip mid-call is safe.
    telemetry_on = is_telemetry_writable()
    messages_for_log = (
        [{"role": mo.role, "content": mo.content} for mo in msg_objects] if telemetry_on else []
    )

    # Get primary provider
    llm = get_llm(provider_name=provider, model=model)

    fallback_provider_name: str | None = None
    response: LLMResponse | None = None
    t0 = perf_counter()

    try:
        response = llm.chat_completion(
            messages=msg_objects,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            timeout=timeout,
            **kwargs,
        )

        latency_ms = int((perf_counter() - t0) * 1000)

        # Empty-content guard — convert to synthetic failure so the DB
        # CHECK constraint (success=true → response_content NOT NULL) stays
        # satisfied and export filters are trivial.
        if not response.content.strip():
            emit_log(
                call_site=call_site,
                provider=llm.name,
                model=getattr(llm, "model", "unknown"),
                messages=messages_for_log,
                response=response,
                latency_ms=latency_ms,
                success=False,
                error_class="EmptyResponse",
                error_message="provider returned empty content",
                fallback_used=False,
                fallback_provider=None,
            )
            # Return the empty string — callers expect a string, not an exception.
            return response.content

        emit_log(
            call_site=call_site,
            provider=llm.name,
            model=getattr(llm, "model", "unknown"),
            messages=messages_for_log,
            response=response,
            latency_ms=latency_ms,
            success=True,
            error_class=None,
            error_message=None,
            fallback_used=False,
            fallback_provider=None,
        )
        return response.content

    except (LLMConnectionError, LLMAuthenticationError, LLMRateLimitError) as e:
        logger.warning("primary_llm_failed", provider=llm.name, error=str(e))

        if not use_fallback:
            latency_ms = int((perf_counter() - t0) * 1000)
            emit_log(
                call_site=call_site,
                provider=llm.name,
                model=getattr(llm, "model", "unknown"),
                messages=messages_for_log,
                response=None,
                latency_ms=latency_ms,
                success=False,
                error_class=type(e).__name__,
                error_message=str(e)[:512],
                fallback_used=False,
                fallback_provider=None,
            )
            raise

        # Try fallback provider
        fallback = _get_cached_fallback()
        if fallback and fallback.is_available():
            logger.info("trying_fallback_provider", provider=fallback.name)
            fallback_provider_name = fallback.name
            try:
                response = fallback.chat_completion(
                    messages=msg_objects,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    timeout=timeout,
                    **kwargs,
                )
                latency_ms = int((perf_counter() - t0) * 1000)

                if not response.content.strip():
                    emit_log(
                        call_site=call_site,
                        provider=fallback.name,
                        model=getattr(fallback, "model", "unknown"),
                        messages=messages_for_log,
                        response=response,
                        latency_ms=latency_ms,
                        success=False,
                        error_class="EmptyResponse",
                        error_message="fallback provider returned empty content",
                        fallback_used=True,
                        fallback_provider=fallback_provider_name,
                    )
                    return response.content

                emit_log(
                    call_site=call_site,
                    provider=fallback.name,
                    model=getattr(fallback, "model", "unknown"),
                    messages=messages_for_log,
                    response=response,
                    latency_ms=latency_ms,
                    success=True,
                    error_class=None,
                    error_message=None,
                    fallback_used=True,
                    fallback_provider=fallback_provider_name,
                )
                return response.content

            except LLMError as fallback_error:
                latency_ms = int((perf_counter() - t0) * 1000)
                logger.error(
                    "fallback_llm_failed",
                    provider=fallback.name,
                    error=str(fallback_error),
                )
                emit_log(
                    call_site=call_site,
                    provider=fallback.name,
                    model=getattr(fallback, "model", "unknown"),
                    messages=messages_for_log,
                    response=None,
                    latency_ms=latency_ms,
                    success=False,
                    error_class=type(fallback_error).__name__,
                    error_message=str(fallback_error)[:512],
                    fallback_used=True,
                    fallback_provider=fallback_provider_name,
                )
                raise LLMError(
                    f"Primary ({llm.name}) and fallback ({fallback.name}) "
                    f"providers both failed. Primary error: {e}. "
                    f"Fallback error: {fallback_error}"
                ) from e

        # No fallback available — emit failure row for the primary error.
        latency_ms = int((perf_counter() - t0) * 1000)
        emit_log(
            call_site=call_site,
            provider=llm.name,
            model=getattr(llm, "model", "unknown"),
            messages=messages_for_log,
            response=None,
            latency_ms=latency_ms,
            success=False,
            error_class=type(e).__name__,
            error_message=str(e)[:512],
            fallback_used=False,
            fallback_provider=None,
        )
        raise


def chat_completion_with_retry(
    messages: list[dict[str, str] | Message],
    max_retries: int = 3,
    *,
    call_site: str,
    **kwargs: Any,
) -> str:
    """Chat completion with exponential backoff retry on connection errors.

    Retries only on LLMConnectionError (timeout, network). Auth and rate
    limit errors are raised immediately since retrying won't help.

    Each retry attempt is a fresh call into ``chat_completion``, so a
    retried call produces N rows (failed) followed by one (success) in
    ``llm_generation_log``, each sharing the same ``correlation_id``
    inherited from the ambient ContextVar.

    Args:
        messages: Sequence of messages, each as a dict or Message instance.
        max_retries: Maximum number of attempts (default 3).
        call_site: Identifier for this LLM call site (required, keyword-only).
        **kwargs: Passed through to chat_completion().

    Returns:
        Response content as string.

    Raises:
        LLMConnectionError: If all retry attempts fail.
        LLMAuthenticationError: Immediately on auth failure.
        LLMRateLimitError: Immediately on rate limit.
        LLMError: On other non-retryable errors.
    """
    last_error: LLMConnectionError | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return chat_completion(messages=messages, call_site=call_site, **kwargs)
        except LLMConnectionError as e:
            last_error = e
            if attempt < max_retries:
                delay = 2**attempt  # 2s, 4s
                logger.warning(
                    "llm.retry",
                    attempt=attempt,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(e),
                )
                time.sleep(delay)
            # Auth/rate-limit errors bubble up from chat_completion
            # since they are NOT subclasses of LLMConnectionError
    raise last_error  # type: ignore[misc]
