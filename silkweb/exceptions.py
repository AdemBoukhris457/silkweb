from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SilkwebError(Exception):
    """Base error for all Silkweb exceptions."""

    message: str = "Silkweb error"
    context: dict[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover
        return self.message


@dataclass
class SilkwebFetchError(SilkwebError):
    """Base error for fetch failures."""

    url: str | None = None


@dataclass
class SilkwebHTTPError(SilkwebFetchError):
    """Non-2xx HTTP response."""

    status_code: int | None = None


@dataclass
class SilkwebTimeoutError(SilkwebFetchError):
    """Request timed out."""

    timeout_ms: int | None = None


@dataclass
class SilkwebBlockedError(SilkwebFetchError):
    """Bot detection confirmed / challenge page encountered."""

    status_code: int | None = None
    tier_tried: int | None = None
    challenge_type: str | None = None
    html_snippet: str | None = None


@dataclass
class SilkwebRenderError(SilkwebFetchError):
    """JavaScript rendering failed."""

    tier_tried: int | None = None


@dataclass
class SilkwebExtractionError(SilkwebError):
    """Base error for extraction failures."""

    url: str | None = None


@dataclass
class SilkwebSchemaError(SilkwebExtractionError):
    """Pydantic validation failed."""

    validation_errors: Any | None = None


@dataclass
class SilkwebLLMError(SilkwebExtractionError):
    """LLM call failed or returned invalid JSON."""

    provider: str | None = None
    model: str | None = None
    raw_output: str | None = None


@dataclass
class SilkwebSelectorError(SilkwebExtractionError):
    """No elements matched selector."""

    selector: str | None = None


@dataclass
class SilkwebCacheError(SilkwebError):
    """Cache backend failure."""

    backend: str | None = None


@dataclass
class SilkwebConfigError(SilkwebError):
    """Invalid configuration."""

    key: str | None = None
    value: Any | None = None


@dataclass
class SilkwebSessionError(SilkwebError):
    """Base error for session/recording failures."""

    name: str | None = None


@dataclass
class SilkwebSessionExpiredError(SilkwebSessionError):
    """Session has expired (auth cookies likely stale)."""

    expired_cookies: list[str] | None = None
