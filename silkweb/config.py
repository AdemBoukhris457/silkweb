from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .exceptions import SilkwebConfigError


@dataclass(slots=True)
class SilkwebConfig:
    # === LLM Models ===
    cleaner_model: str = "ollama/reader-lm-v2"
    schema_model: str = "ollama/qwen2.5-coder:14b"
    extraction_model: str = "ollama/qwen2.5:14b"
    # Model used for compiling selectors (CSS/XPath) from extracted provenance.
    # Defaults to the same model as schema synthesis for backward compatibility.
    selector_model: str = "ollama/qwen2.5-coder:14b"
    embedding_model: str = "ollama/nomic-embed-text"
    vision_model: str | None = None  # None = disabled unless needed

    # === Fetcher ===
    default_tier: str | int = "auto"  # "auto" | 0 | 1 | 2 | 3 | 4
    max_tier: int = 3
    auto_escalate: bool = True
    timeout: int = 30_000  # ms (page fetch / HTTP clients)
    # LLM API HTTP client timeout (OpenAI, Anthropic, Ollama HTTP, …), in ms.
    # Kept separate from `timeout` because JSON extraction often needs longer than a simple GET.
    llm_timeout_ms: int = 120_000
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    impersonate: str = "chrome_124"
    headers: dict[str, str] = field(default_factory=dict)

    # === Extraction ===
    chunk_strategy: str = "bm25"  # "bm25" | "semantic" | "dom" | "token"
    max_tokens_per_chunk: int = 8_000
    # auto: compact flat_json for articles; falls back to stripped HTML when flat_json looks
    # like a degraded catalog (many price/stock tokens, few long text lines).
    representation: str = "auto"  # "auto" | "flat_json" | "markdown" | "slim_html"
    extraction_html_max_chars: int = 400_000
    # Max chars of page text (html_excerpt or markdown body) sent to the extraction LLM.
    # Stored excerpts can be larger (extraction_*_max_chars); huge prompts often return empty items.
    extraction_prompt_body_max_chars: int = 100_000
    # Cap JSON-mode extraction output; multi-row + __xpath__ needs >4k; unbounded is slow.
    extraction_max_tokens: int = 8192
    extraction_markdown_max_chars: int = 400_000
    include_provenance: bool = True
    force_llm: bool = False
    hydration_first: bool = True
    # When hydration_first=True, prefer a smaller stable subset (e.g. Next.js pageProps)
    # over dumping the full hydration payload into the LLM prompt.
    hydration_subset: bool = True
    # Safety cap: if hydration JSON exceeds this many characters, skip hydration and
    # fall back to HTML cleaning.
    hydration_max_chars: int = 80_000

    # === Cache ===
    cache_enabled: bool = True
    # Cache backend:
    # - "sqlite": default, persistent local cache
    # - "redis": persistent shared cache (requires a Redis server)
    # - "memory": in-process only (testing / short-lived scripts)
    # Note: "diskcache" is not supported (will raise SilkwebConfigError).
    cache_backend: str = "sqlite"
    cache_path: str = "~/.silkweb/cache"  # used by sqlite-backed caches
    # Used when `cache_backend="redis"` (HTTP cache and rendered page cache).
    # Selector cache remains SQLite for now.
    redis_url: str | None = None
    http_cache_ttl: int = 3600
    page_cache_ttl: int = 1800
    selector_cache_ttl: int | None = None

    # === Proxy & Rate Limiting ===
    proxies: list[str] = field(default_factory=list)
    proxy_rotation: str = "on_failure"
    rate_limit_global: int | None = None
    rate_limit_per_domain: int = 2
    respect_robots: bool = True

    # === Retry ===
    max_retries: int = 3
    retry_backoff: str = "exponential"
    retry_backoff_base: int = 2

    # === Stealth ===
    # Tier 3 engine selection:
    # - default (False): `stealth_engine="auto"` prefers patchright / Playwright-based stealth.
    # - when True: `stealth_engine="auto"` may pick nodriver if installed (experimental).
    prefer_nodriver: bool = False
    human_mouse: bool = False
    human_typing: bool = False
    captcha_solver: str | None = None

    # === Output ===
    default_output_format: str = "python"  # "python" | "json" | "csv" | "parquet" | "df"
    auto_detect_dataframe: bool = True

    # === Observability ===
    log_level: str = "WARNING"
    log_format: str = "text"
    metrics_port: int | None = None
    telemetry_enabled: bool = False
    replay_dir: str | None = None

    # Catch-all for forward-compat custom options
    extra: dict[str, Any] = field(default_factory=dict)


_CONFIG = SilkwebConfig()


def get_config() -> SilkwebConfig:
    return _CONFIG


def configure(**kwargs: Any) -> SilkwebConfig:
    """
    Update global Silkweb configuration.

    Known fields are set on :class:`SilkwebConfig`; unknown keys go into ``extra``.

    When environment variable ``SILKWEB_STRICT_CONFIG`` is ``1`` / ``true`` / ``yes``,
    unknown **top-level** keys raise :class:`SilkwebConfigError` instead of being stored
    in ``extra`` (helps catch typos like ``configure(timeouts=30)``).
    """
    strict = os.environ.get("SILKWEB_STRICT_CONFIG", "").strip().lower() in ("1", "true", "yes")
    for key, value in kwargs.items():
        if hasattr(_CONFIG, key):
            setattr(_CONFIG, key, value)
        else:
            if strict:
                raise SilkwebConfigError(
                    message=f"Unknown SilkwebConfig field {key!r}. "
                    f"Set SILKWEB_STRICT_CONFIG=0 or use `extra` via supported keys only.",
                    key=key,
                    value=value,
                )
            _CONFIG.extra[key] = value
    return _CONFIG
