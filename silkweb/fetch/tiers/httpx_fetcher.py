from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import structlog

from ...cache.http import HttpCache
from ...config import SilkwebConfig, get_config
from ...exceptions import SilkwebHTTPError, SilkwebTimeoutError
from ...parse.page import SilkPage

logger = structlog.get_logger(__name__)

_CLIENTS_LOCK = threading.Lock()
_CLIENTS: dict[tuple[Any, ...], httpx.AsyncClient] = {}


def _client_key(
    *,
    timeout_ms: int,
    follow_redirects: bool,
    headers: dict[str, str],
    proxy: str | None,
    cache: bool,
) -> tuple[Any, ...]:
    return (
        timeout_ms,
        follow_redirects,
        proxy or "",
        cache,
        tuple(sorted((k.lower(), v) for k, v in headers.items())),
    )


def _merge_headers(
    config: SilkwebConfig,
    headers: dict[str, str] | None,
) -> dict[str, str]:
    merged: dict[str, str] = {}

    # Global defaults
    if config.user_agent:
        merged["user-agent"] = config.user_agent
    merged.update(config.headers or {})

    # Per-call overrides
    if headers:
        merged.update(headers)

    return merged


def _get_client(
    *,
    timeout_ms: int,
    follow_redirects: bool,
    headers: dict[str, str],
    proxy: str | None,
    cache: bool,
    http_cache: HttpCache | None,
) -> httpx.AsyncClient:
    key = _client_key(
        timeout_ms=timeout_ms,
        follow_redirects=follow_redirects,
        headers=headers,
        proxy=proxy,
        cache=cache,
    )
    client = _CLIENTS.get(key)
    if client is not None:
        return client

    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is not None:
            return client
        timeout = httpx.Timeout(timeout_ms / 1000.0)
        transport: httpx.AsyncBaseTransport | None = None
        if cache and http_cache is not None:
            transport = http_cache.wrap_transport(httpx.AsyncHTTPTransport())
        client = httpx.AsyncClient(
            http2=True,
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers=headers,
            proxy=proxy,
            transport=transport,
        )
        _CLIENTS[key] = client
        return client


async def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_ms: int | None = None,
    follow_redirects: bool = True,
    proxy: str | None = None,
    config: SilkwebConfig | None = None,
    http_cache: HttpCache | None = None,
    use_http_cache: bool = True,
) -> SilkPage:
    """
    Tier 0 fetcher: async HTTP via httpx (HTTP/2 enabled).

    Returns a `SilkPage` for HTML-like responses.
    """
    cfg = config or get_config()
    effective_timeout_ms = int(timeout_ms if timeout_ms is not None else cfg.timeout)
    merged_headers = _merge_headers(cfg, headers)
    client = _get_client(
        timeout_ms=effective_timeout_ms,
        follow_redirects=follow_redirects,
        headers=merged_headers,
        proxy=proxy,
        cache=bool(use_http_cache and cfg.cache_enabled),
        http_cache=http_cache,
    )

    start = time.perf_counter()
    try:
        resp = await client.get(url)
    except RuntimeError as e:
        # Defensive: hishel can raise on malformed caching headers from some sites.
        # Retry once without HTTP caching.
        if (
            use_http_cache
            and cfg.cache_enabled
            and http_cache is not None
            and "expires header" in str(e).lower()
        ):
            logger.warning(
                "http_cache_disabled",
                url=url,
                tier=0,
                reason="cache_header_parse_error",
                error=str(e),
            )
            uncached = _get_client(
                timeout_ms=effective_timeout_ms,
                follow_redirects=follow_redirects,
                headers=merged_headers,
                proxy=proxy,
                cache=False,
                http_cache=None,
            )
            resp = await uncached.get(url)
        else:
            raise
    except httpx.TimeoutException as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "fetch_failed",
            url=url,
            tier=0,
            duration_ms=duration_ms,
            error="timeout",
        )
        raise SilkwebTimeoutError(
            message=f"Request timed out after {effective_timeout_ms}ms",
            url=url,
            timeout_ms=effective_timeout_ms,
            context={"tier": 0, "duration_ms": duration_ms, "error": repr(e)},
        ) from e

    duration_ms = int((time.perf_counter() - start) * 1000)

    logger.info(
        "fetch_completed",
        url=str(resp.url),
        status_code=resp.status_code,
        duration_ms=duration_ms,
        tier=0,
    )

    if not (200 <= resp.status_code < 300):
        raise SilkwebHTTPError(
            message=f"Non-2xx response: {resp.status_code}",
            url=str(resp.url),
            status_code=resp.status_code,
            context={
                "tier": 0,
                "duration_ms": duration_ms,
                "response_headers": dict(resp.headers),
            },
        )

    return SilkPage(
        resp.text,
        url=str(resp.url),
        status=resp.status_code,
        headers=dict(resp.headers),
        metadata=None,
        fetch_tier=0,
    )
