from __future__ import annotations

import abc
import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any

from ...exceptions import SilkwebLLMError

Message = dict[str, str]


@dataclass(slots=True)
class RetryConfig:
    max_attempts: int = 4
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0
    jitter: float = 0.2


def _exception_class_name(exc: Exception) -> str:
    return exc.__class__.__name__


def _looks_like_rate_limit(exc: Exception) -> bool:
    name = _exception_class_name(exc).lower()
    if "ratelimit" in name or "too_many_requests" in name:
        return True
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    return status == 429


def _looks_like_timeout(exc: Exception) -> bool:
    name = _exception_class_name(exc).lower()
    if "timeout" in name:
        return True
    # httpx-like
    return isinstance(exc, TimeoutError)


def _looks_like_auth_error(exc: Exception) -> bool:
    name = _exception_class_name(exc).lower()
    if "authentication" in name or "unauthorized" in name or "apikey" in name:
        return True
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    return status in {401, 403}


async def _sleep_backoff(attempt: int, cfg: RetryConfig) -> float:
    # attempt is 1-based
    base = cfg.backoff_base_s * (2 ** (attempt - 1))
    delay = min(cfg.backoff_max_s, base)
    if cfg.jitter:
        delay = delay * (1.0 + random.uniform(-cfg.jitter, cfg.jitter))
        delay = max(0.0, delay)
    await asyncio.sleep(delay)
    return delay


async def with_retries(
    fn,
    *,
    cfg: RetryConfig,
    provider: str,
    model: str | None,
    context: dict[str, Any] | None = None,
) -> Any:
    last_exc: Exception | None = None
    task = (context or {}).get("task", "llm")
    for attempt in range(1, cfg.max_attempts + 1):
        if attempt > 1:
            print(
                f"[silkweb]   llm with_retries: attempt {attempt}/{cfg.max_attempts} "
                f"provider={provider!r} model={model!r} task={task!r}",
                flush=True,
            )
        try:
            return await fn()
        except Exception as exc:
            last_exc = exc

            if _looks_like_auth_error(exc):
                raise SilkwebLLMError(
                    message="LLM authentication failed (check API key / credentials).",
                    provider=provider,
                    model=model,
                    raw_output=None,
                    context={**(context or {}), "error": repr(exc), "attempt": attempt},
                ) from exc

            if attempt >= cfg.max_attempts or not (
                _looks_like_rate_limit(exc) or _looks_like_timeout(exc)
            ):
                raise SilkwebLLMError(
                    message="LLM provider call failed.",
                    provider=provider,
                    model=model,
                    raw_output=None,
                    context={**(context or {}), "error": repr(exc), "attempt": attempt},
                ) from exc

            slept = await _sleep_backoff(attempt, cfg)
            print(
                f"[silkweb]   llm with_retries: slept {slept:.2f}s after "
                f"{_exception_class_name(exc)} (attempt {attempt})",
                flush=True,
            )

    raise SilkwebLLMError(
        message="LLM provider call failed.",
        provider=provider,
        model=model,
        raw_output=None,
        context={**(context or {}), "error": repr(last_exc)},
    )


def parse_json_loose(text: str) -> dict[str, Any]:
    """
    Parse JSON from a model response robustly.

    Strategy:
    1. Try json.loads on the full string
    2. Use json.JSONDecoder().raw_decode from the first '{' (balanced parse)
    """
    s = (text or "").strip()
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Find first '{' and use raw_decode for balanced brace extraction
    idx = s.find("{")
    if idx >= 0:
        decoder = json.JSONDecoder()
        try:
            parsed, _ = decoder.raw_decode(s, idx)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    raise ValueError("Malformed JSON response")


class LLMProvider(abc.ABC):
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        retry: RetryConfig | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.retry = retry or RetryConfig()

    def unwrap(self) -> LLMProvider:
        """Return the underlying concrete provider (identity for non-wrapped)."""
        return self

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    async def generate_json(
        self,
        messages: list[Message],
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
