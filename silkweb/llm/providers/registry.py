from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from ...exceptions import SilkwebConfigError
from ...observability.logging import log_event
from ...observability.metrics import Timer, ensure_metrics_server, get_metrics
from .anthropic import AnthropicProvider
from .base import LLMProvider
from .llamacpp import LlamaCppProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider

ProviderName = Literal["ollama", "openai", "anthropic", "llamacpp"]


@dataclass(frozen=True, slots=True)
class ParsedModelURI:
    provider: ProviderName
    model: str


def _approx_llm_chars(messages: list[Any], system: str | None) -> int:
    n = len(system) if isinstance(system, str) else 0
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str):
            n += len(c)
    return n


def parse_model_uri(uri: str) -> ParsedModelURI:
    """
    Parse `provider/model` URIs like `ollama/qwen2.5:14b`.
    """
    if not uri or "/" not in uri:
        raise SilkwebConfigError(message="Invalid model URI.", key="model", value=uri)
    provider, model = uri.split("/", 1)
    provider = provider.strip().lower()
    model = model.strip()
    if provider not in {"ollama", "openai", "anthropic", "llamacpp"}:
        raise SilkwebConfigError(message="Unknown model provider.", key="provider", value=provider)
    if not model:
        raise SilkwebConfigError(message="Missing model name in URI.", key="model", value=uri)
    return ParsedModelURI(provider=provider, model=model)  # type: ignore[arg-type]


def create_provider(
    uri: str,
    *,
    api_key: str | None = None,
    timeout_s: float | None = None,
    **kwargs: Any,
) -> LLMProvider:
    if timeout_s is None:
        from ...config import get_config

        timeout_s = get_config().llm_timeout_ms / 1000.0

    parsed = parse_model_uri(uri)

    ensure_metrics_server()
    metrics = get_metrics()

    class LoggedProvider(LLMProvider):
        def __init__(self, inner: LLMProvider, provider_name: str) -> None:
            super().__init__(
                model=inner.model,
                api_key=getattr(inner, "api_key", None),
                timeout_s=inner.timeout_s,
                retry=inner.retry,
            )
            self._inner = inner
            self._provider_name = provider_name

        def unwrap(self) -> LLMProvider:
            """Return the underlying concrete provider instance."""
            return self._inner

        async def generate(self, messages, system=None, max_tokens=None, temperature=0.2) -> str:  # type: ignore[override]
            t = Timer()
            log_event(
                "llm_call_start", model=self.model, task="generate", provider=self._provider_name
            )
            try:
                out = await self._inner.generate(
                    messages,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return out
            except Exception as e:
                log_event(
                    "llm_call_complete",
                    model=self.model,
                    task="generate",
                    duration_ms=int(t.seconds() * 1000),
                    error=repr(e),
                )
                raise
            else:
                log_event(
                    "llm_call_complete",
                    model=self.model,
                    task="generate",
                    duration_ms=int(t.seconds() * 1000),
                )
            finally:
                metrics.llm_calls_total.labels(model=self.model, task="generate").inc()
                metrics.llm_duration_seconds.labels(model=self.model, task="generate").observe(
                    t.seconds()
                )

        async def generate_json(
            self, messages, system=None, schema=None, max_tokens=None, temperature=0.2
        ):  # type: ignore[override]
            t = Timer()
            t_wall = time.perf_counter()
            approx_in = _approx_llm_chars(messages, system)
            print(
                f"[silkweb]   llm generate_json → provider: "
                f"chars≈{approx_in:,} max_tokens={max_tokens} "
                f"timeout_s={self.timeout_s} model={self.model!r}",
                flush=True,
            )
            log_event(
                "llm_call_start",
                model=self.model,
                task="generate_json",
                provider=self._provider_name,
            )
            try:
                print(
                    f"[silkweb]   llm generate_json: awaiting {self._provider_name!r} "
                    f"(this is usually network + model time)...",
                    flush=True,
                )
                out = await self._inner.generate_json(
                    messages,
                    system=system,
                    schema=schema,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return out
            except Exception as e:
                log_event(
                    "llm_call_complete",
                    model=self.model,
                    task="generate_json",
                    duration_ms=int(t.seconds() * 1000),
                    error=repr(e),
                )
                print(
                    f"[silkweb]   llm generate_json: failed after {time.perf_counter() - t_wall:.2f}s: "
                    f"{type(e).__name__}",
                    flush=True,
                )
                raise
            else:
                log_event(
                    "llm_call_complete",
                    model=self.model,
                    task="generate_json",
                    duration_ms=int(t.seconds() * 1000),
                )
                print(
                    f"[silkweb]   llm generate_json: done in {time.perf_counter() - t_wall:.2f}s",
                    flush=True,
                )
            finally:
                metrics.llm_calls_total.labels(model=self.model, task="generate_json").inc()
                metrics.llm_duration_seconds.labels(model=self.model, task="generate_json").observe(
                    t.seconds()
                )

        async def embed(self, texts):  # type: ignore[override]
            t = Timer()
            log_event(
                "llm_call_start", model=self.model, task="embed", provider=self._provider_name
            )
            try:
                out = await self._inner.embed(texts)
                return out
            except Exception as e:
                log_event(
                    "llm_call_complete",
                    model=self.model,
                    task="embed",
                    duration_ms=int(t.seconds() * 1000),
                    error=repr(e),
                )
                raise
            else:
                log_event(
                    "llm_call_complete",
                    model=self.model,
                    task="embed",
                    duration_ms=int(t.seconds() * 1000),
                )
            finally:
                metrics.llm_calls_total.labels(model=self.model, task="embed").inc()
                metrics.llm_duration_seconds.labels(model=self.model, task="embed").observe(
                    t.seconds()
                )

    if parsed.provider == "ollama":
        inner = OllamaProvider(model=parsed.model, api_key=api_key, timeout_s=timeout_s, **kwargs)
        return LoggedProvider(inner, "ollama")
    if parsed.provider == "openai":
        inner = OpenAIProvider(model=parsed.model, api_key=api_key, timeout_s=timeout_s, **kwargs)
        return LoggedProvider(inner, "openai")
    if parsed.provider == "anthropic":
        inner = AnthropicProvider(
            model=parsed.model, api_key=api_key, timeout_s=timeout_s, **kwargs
        )
        return LoggedProvider(inner, "anthropic")
    if parsed.provider == "llamacpp":
        inner = LlamaCppProvider(model=parsed.model, api_key=api_key, timeout_s=timeout_s, **kwargs)
        return LoggedProvider(inner, "llamacpp")

    raise SilkwebConfigError(message="Unknown provider.", key="provider", value=parsed.provider)
