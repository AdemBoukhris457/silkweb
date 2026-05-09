from __future__ import annotations

import time
import warnings

import structlog

from ...config import SilkwebConfig, get_config
from ...exceptions import SilkwebHTTPError, SilkwebTimeoutError
from ...parse.page import SilkPage
from .httpx_fetcher import fetch as httpx_fetch

logger = structlog.get_logger(__name__)

SUPPORTED_IMPERSONATE_PROFILES: set[str] = {
    "chrome_120",
    "chrome_124",
    "firefox_121",
    "safari_17",
    "edge_122",
}

# curl_cffi uses names like "chrome124"; older docs used "chrome_124". Map stable silkweb names.
_IMPERSONATE_TO_CURL_CFFI: dict[str, str] = {
    "chrome_120": "chrome120",
    "chrome_124": "chrome124",
    "firefox_121": "firefox133",
    "safari_17": "safari17_0",
    "edge_122": "edge101",
}


def _curl_cffi_impersonate_token(profile: str) -> str:
    return _IMPERSONATE_TO_CURL_CFFI.get(profile, profile)


async def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_ms: int | None = None,
    follow_redirects: bool = True,
    impersonate: str = "chrome_124",
    proxy: str | None = None,
    config: SilkwebConfig | None = None,
) -> SilkPage:
    """
    Tier 1 fetcher: curl_cffi with real-browser TLS fingerprints.

    If curl_cffi isn't installed, falls back to Tier 0 (httpx) with a warning.
    """
    cfg = config or get_config()
    effective_timeout_ms = int(timeout_ms if timeout_ms is not None else cfg.timeout)

    if impersonate not in SUPPORTED_IMPERSONATE_PROFILES:
        raise ValueError(
            f"Unsupported impersonate profile: {impersonate}. "
            f"Supported: {sorted(SUPPORTED_IMPERSONATE_PROFILES)}"
        )

    try:
        from curl_cffi.requests import AsyncSession  # type: ignore
    except ImportError:
        warnings.warn(
            "curl_cffi is not installed; falling back to Tier 0 (httpx). "
            "Install with `pip install 'silkweb[stealth]'`.",
            RuntimeWarning,
            stacklevel=2,
        )
        page = await httpx_fetch(
            url,
            headers=headers,
            timeout_ms=effective_timeout_ms,
            follow_redirects=follow_redirects,
            config=cfg,
        )
        page.fetch_tier = 1
        return page

    # curl_cffi>=0.15 exposes timeout types under requests.exceptions; older used requests.errors.
    try:
        from curl_cffi.requests.exceptions import (  # type: ignore  # noqa: I001
            ConnectTimeout as _ConnectTimeout,
            ReadTimeout as _ReadTimeout,
            Timeout as _RequestsTimeout,
        )

        _CURL_TIMEOUT_TYPES: tuple[type[BaseException], ...] = (
            _RequestsTimeout,
            _ConnectTimeout,
            _ReadTimeout,
        )
    except ImportError:
        try:
            from curl_cffi.requests import errors as _curl_errors  # type: ignore

            _t = getattr(_curl_errors, "Timeout", None)
            _CURL_TIMEOUT_TYPES = (_t,) if _t is not None else ()
        except ImportError:
            _CURL_TIMEOUT_TYPES = ()

    merged_headers: dict[str, str] = {}
    if cfg.user_agent:
        merged_headers["user-agent"] = cfg.user_agent
    merged_headers.update(cfg.headers or {})
    if headers:
        merged_headers.update(headers)

    curl_impersonate = _curl_cffi_impersonate_token(impersonate)

    start = time.perf_counter()
    try:
        async with AsyncSession(impersonate=curl_impersonate, headers=merged_headers) as session:
            req_kwargs: dict[str, object] = {
                "timeout": effective_timeout_ms / 1000.0,
                "allow_redirects": follow_redirects,
            }
            if proxy:
                req_kwargs["proxy"] = proxy
            resp = await session.get(url, **req_kwargs)
    except Exception as e:
        if _CURL_TIMEOUT_TYPES and isinstance(e, _CURL_TIMEOUT_TYPES):
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                "fetch_failed",
                url=url,
                tier=1,
                duration_ms=duration_ms,
                impersonate=impersonate,
                error="timeout",
            )
            raise SilkwebTimeoutError(
                message=f"Request timed out after {effective_timeout_ms}ms",
                url=url,
                timeout_ms=effective_timeout_ms,
                context={"tier": 1, "duration_ms": duration_ms, "impersonate": impersonate},
            ) from e
        raise

    duration_ms = int((time.perf_counter() - start) * 1000)
    final_url = str(getattr(resp, "url", url))
    status_code = int(getattr(resp, "status_code", 0))
    resp_headers = dict(getattr(resp, "headers", {}) or {})
    body_text = str(getattr(resp, "text", "") or "")

    logger.info(
        "fetch_completed",
        url=final_url,
        status_code=status_code,
        duration_ms=duration_ms,
        tier=1,
        impersonate=impersonate,
    )

    if not (200 <= status_code < 300):
        raise SilkwebHTTPError(
            message=f"Non-2xx response: {status_code}",
            url=final_url,
            status_code=status_code,
            context={
                "tier": 1,
                "duration_ms": duration_ms,
                "impersonate": impersonate,
                "response_headers": resp_headers,
            },
        )

    return SilkPage(
        body_text,
        url=final_url,
        status=status_code,
        headers=resp_headers,
        metadata=None,
        fetch_tier=1,
    )
