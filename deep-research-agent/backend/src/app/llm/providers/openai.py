"""OpenAI provider (real implementation via the official SDK).

The provider is the only place that knows about the OpenAI SDK: it translates
our :class:`LLMMessage` objects into OpenAI message dicts, calls the API, and
maps the response (and token usage) back to our canonical :class:`LLMResponse`.
OpenAI exceptions are translated to our application error hierarchy so they
never leak out of this module.
"""

from __future__ import annotations

import logging
import os
import time
from functools import wraps

from openai import (
    APIConnectionError,
    APIError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.common.exceptions import AppError, LLMProviderError, LLMRequestError
from app.llm.base import (
    AsyncLLMProvider,
    LLMMessage,
    LLMResponse,
    LLMStreamEvent,
    LLMUsage,
)
from app.observability.metrics import (
    LLM_CALL_DURATION,
    LLM_CALLS,
    LLM_TOKENS,
    PROVIDER_CIRCUIT_STATE,
)
from app.observability.usage import record_llm_usage

logger = logging.getLogger(__name__)

#: Official OpenAI endpoint; used whenever no custom gateway is configured.
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

#: Retry policy for transient (retryable) provider failures (rate limits, network flaps, 5xx).
_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_MIN_WAIT = 0.5
_LLM_RETRY_MAX_WAIT = 30.0

#: Circuit breaker: trip open after N consecutive logical failures(per caller invocation=1),
#: regardless of retry attempts; a half-open probe passes after ``_CIRCUIT_RESET_SECONDS``.
_LLM_CIRCUIT_FAILURE_THRESHOLD = 5
_LLM_CIRCUIT_RESET_SECONDS =  60.0
_LLM_CIRCUIT_HALF_OPEN_PROBE_SECONDS =  10.0


def _with_transient_retry(func: object) -> object:
    """Retry transient provider failures with exponential backoff + jitter.

    Applies to ``_generate``: only :class:`LLMProviderError` (which the provider
    raises for rate limits / connection errors / 5xx upstream failures) is retried;
    authentication and other permanent rejections (:class:`LLMRequestError`) fail fast.
    """

    @wraps(func)  # type: ignore[arg-type]
    @retry(  # type: ignore[misc]
        retry=retry_if_exception_type(LLMProviderError),
        wait=wait_exponential_jitter(initial=_LLM_RETRY_MIN_WAIT, max=_LLM_RETRY_MAX_WAIT),
        stop=stop_after_attempt(_LLM_RETRY_ATTEMPTS),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def wrapper(*args: object, **kwargs: object) -> LLMResponse:
        """..."""
        return await func(*args, **kwargs)  # type: ignore[no-any-return, operator]

    return wrapper


class OpenAIProvider(AsyncLLMProvider):
    name = "openai"
    default_model = "gpt-4o-mini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(api_key=api_key, model=model)
        self.base_url = base_url
        self.timeout = timeout
        # Resolve an explicit base URL. The OpenAI SDK also reads the
        # ``OPENAI_BASE_URL`` environment variable directly; when Docker Compose
        # exports that variable as an *empty string* (a common .env placeholder),
        # the SDK builds requests with no scheme and fails with
        # ``UnsupportedProtocol``. Always passing a concrete URL removes that
        # failure mode while still honoring an explicitly configured gateway.
        resolved_base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "").strip()
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=resolved_base_url or _DEFAULT_OPENAI_BASE_URL,
            timeout=timeout,
        )

        # Circuit breaker state (conservative defaults; see module constants).
        self._consecutive_failures: int = 0
        self._circuit_open_until: float = 0.0
        self._circuit_probe_at: float = 0.0

    async def generate(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> LLMResponse:
        """Add circuit breaker + per-call metrics; delegates to the base for retry/time/logging.

        ``LLM_CALLS`` / ``LLM_TOKENS`` / ``LLM_CALL_DURATION`` feed cost accounting
        and dashboards; the breaker limits blast radius when the provider degrades.
        """
        start = time.perf_counter()
        outcome = "error"
        usage: LLMUsage | None = None
        try:
            if not self._circuit_allows():
                raise LLMProviderError("LLM provider temporarily unavailable (circuit open.)")
            response = await super().generate(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                timeout=timeout,
            )
            self._record_success()
            outcome = "ok"
            usage = response.usage
            if usage is not None:
                record_llm_usage(
                    provider=self.name,
                    model=response.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )
        except AppError:
            self._record_failure()
            outcome = "error"
            raise
        finally:
            LLM_CALLS.labels(agent=self.name, outcome=outcome).inc()
            LLM_CALL_DURATION.labels(agent=self.name).observe(time.perf_counter() - start)
            if usage is not None:
                LLM_TOKENS.labels(agent=self.name, kind="prompt").inc(usage.prompt_tokens)
                LLM_TOKENS.labels(agent=self.name, kind="completion").inc(usage.completion_tokens)
        return response

    def _circuit_allows(self) -> bool:
        """True when the breaker admits a request (closed or half-open probe window)."""
        if not self._circuit_open():
            return True
        now = time.monotonic()
        if now < self._circuit_probe_at:
            PROVIDER_CIRCUIT_STATE.labels(provider=self.name).set(1.0)  # fail-fast
            return False
        # Reset window elapsed: admit one probe request, cool down until its result lands.

        self._circuit_probe_at = now + _LLM_CIRCUIT_HALF_OPEN_PROBE_SECONDS
        PROVIDER_CIRCUIT_STATE.labels(provider=self.name).set(0.5)  # half-open
        return True

    def _circuit_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= _LLM_CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until = time.monotonic() + _LLM_CIRCUIT_RESET_SECONDS
            self._circuit_probe_at = 0.0
        PROVIDER_CIRCUIT_STATE.labels(provider=self.name).set(
            1.0 if self._circuit_open() else 0.0
        )

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._circuit_probe_at = 0.0
        PROVIDER_CIRCUIT_STATE.labels(provider=self.name).set(0.0)

    @_with_transient_retry
    async def _generate(
        self,
        *,
        messages: list[LLMMessage],
        temperature: float,
        max_tokens: int | None,
        model: str,
        timeout: float,
    ) -> LLMResponse:
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            completion = await self._client.chat.completions.create(**payload)
        except AuthenticationError as exc:
            raise LLMRequestError("LLM provider authentication failed.") from exc
        except (RateLimitError, APIConnectionError) as exc:
            raise LLMProviderError("LLM provider is temporarily unavailable.") from exc
        except APIError as exc:
            raise LLMProviderError("LLM provider request failed.") from exc

        return self._to_response(completion, model=model)

    def _to_response(self, completion: object, *, model: str) -> LLMResponse:
        """Map an OpenAI completion object to our canonical response."""
        choices = getattr(completion, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        content = getattr(message, "content", None) or ""

        usage_payload = getattr(completion, "usage", None)
        usage: LLMUsage | None = None
        if usage_payload is not None:
            usage = LLMUsage(
                prompt_tokens=getattr(usage_payload, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage_payload, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage_payload, "total_tokens", 0) or 0,
            )

        return LLMResponse(
            content=content,
            model=model,
            provider=self.name,
            usage=usage,
            raw=completion,
        )

    # ---- Streaming (Phase C) ----

    def supports_streaming(self) -> bool:
        return True

    async def generate_stream(  # noqa: RUF029 - generator by design
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ):
        """Stream token deltas; terminal event carries the aggregated response.

        Circuit breaker + call/token metrics mirror :meth:`generate`. Retries
        are intentionally NOT applied: a stream that fails mid-flight cannot be
        replayed transparently, so failures surface as :class:`AppError` and the
        caller decides (the chat layer emits an SSE error event).
        """
        target_model = model or self.model
        start = time.perf_counter()
        outcome = "error"
        usage: LLMUsage | None = None
        response: LLMResponse | None = None
        try:
            if not self._circuit_allows():
                raise LLMProviderError(
                    "LLM provider temporarily unavailable (circuit open.)"
                )

            payload: dict[str, object] = {
                "model": target_model,
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                "temperature": temperature,
                "stream": True,
                # Ask OpenAI to append a final chunk carrying token usage.
                "stream_options": {"include_usage": True},
            }
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens

            parts: list[str] = []
            try:
                stream = await self._client.chat.completions.create(**payload)
                async for chunk in stream:
                    choices = getattr(chunk, "choices", None) or []
                    delta_obj = getattr(choices[0], "delta", None) if choices else None
                    delta = getattr(delta_obj, "content", None) if delta_obj else None
                    if delta:
                        parts.append(delta)
                        yield LLMStreamEvent(delta=delta)
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage = LLMUsage(
                            prompt_tokens=getattr(chunk_usage, "prompt_tokens", 0) or 0,
                            completion_tokens=(
                                getattr(chunk_usage, "completion_tokens", 0) or 0
                            ),
                            total_tokens=getattr(chunk_usage, "total_tokens", 0) or 0,
                        )
            except AuthenticationError as exc:
                raise LLMRequestError("LLM provider authentication failed.") from exc
            except (RateLimitError, APIConnectionError) as exc:
                raise LLMProviderError("LLM provider is temporarily unavailable.") from exc
            except APIError as exc:
                raise LLMProviderError("LLM provider request failed.") from exc

            response = LLMResponse(
                content="".join(parts),
                model=target_model,
                provider=self.name,
                usage=usage,
            )
            self._record_success()
            outcome = "ok"
            yield LLMStreamEvent(response=response)
        except AppError:
            self._record_failure()
            raise
        finally:
            LLM_CALLS.labels(agent=self.name, outcome=outcome).inc()
            LLM_CALL_DURATION.labels(agent=self.name).observe(time.perf_counter() - start)
            if usage is not None:
                LLM_TOKENS.labels(agent=self.name, kind="prompt").inc(usage.prompt_tokens)
                LLM_TOKENS.labels(agent=self.name, kind="completion").inc(
                    usage.completion_tokens
                )
                record_llm_usage(
                    provider=self.name,
                    model=target_model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                )
