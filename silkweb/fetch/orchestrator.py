from __future__ import annotations

import hashlib
import re
import threading
from typing import Any, Literal
from urllib.parse import urlparse

import structlog

from ..cache.manager import CacheManager
from ..config import SilkwebConfig, get_config
from ..exceptions import (
    SilkwebBlockedError,
    SilkwebCacheError,
    SilkwebHTTPError,
    SilkwebTimeoutError,
)
from ..observability.logging import configure_logging, log_event
from ..observability.metrics import Timer, ensure_metrics_server, get_metrics
from ..observability.replay import maybe_save_fetch
from ..parse.page import SilkPage
from ..stealth.proxy import ProxyPool
from ..stealth.rate_limit import TokenBucketRateLimiter
from .tiers import (
    curl_cffi_fetcher,
    httpx_fetcher,
    playwright_fetcher,
    stealth_fetcher,
)

logger = structlog.get_logger(__name__)

Tier = Literal["auto", 0, 1, 2, 3]

_SINGLETON_LOCK = threading.Lock()

_CACHE_MANAGER: CacheManager | None = None
_CACHE_MANAGER_KEY: tuple[Any, ...] | None = None

_PROXY_POOL: ProxyPool | None = None
_PROXY_POOL_KEY: tuple[Any, ...] | None = None

_RATE_LIMITER: TokenBucketRateLimiter | None = None
_RATE_LIMITER_KEY: tuple[Any, ...] | None = None


def _get_cache_manager(cfg: SilkwebConfig) -> CacheManager:
    global _CACHE_MANAGER, _CACHE_MANAGER_KEY
    key = (
        cfg.cache_enabled,
        cfg.cache_backend,
        cfg.cache_path,
        cfg.http_cache_ttl,
        cfg.page_cache_ttl,
    )
    if _CACHE_MANAGER is not None and key == _CACHE_MANAGER_KEY:
        return _CACHE_MANAGER
    with _SINGLETON_LOCK:
        if _CACHE_MANAGER is not None and key == _CACHE_MANAGER_KEY:
            return _CACHE_MANAGER
        _CACHE_MANAGER = CacheManager.from_config()
        _CACHE_MANAGER_KEY = key
        return _CACHE_MANAGER


def _get_proxy_pool(cfg: SilkwebConfig) -> ProxyPool | None:
    global _PROXY_POOL, _PROXY_POOL_KEY
    proxies = tuple(cfg.proxies or [])
    if not proxies:
        _PROXY_POOL = None
        _PROXY_POOL_KEY = None
        return None
    key = (proxies, cfg.proxy_rotation)
    if _PROXY_POOL is not None and key == _PROXY_POOL_KEY:
        return _PROXY_POOL
    with _SINGLETON_LOCK:
        if _PROXY_POOL is not None and key == _PROXY_POOL_KEY:
            return _PROXY_POOL
        _PROXY_POOL = ProxyPool(list(proxies))
        _PROXY_POOL_KEY = key
        return _PROXY_POOL


def _domain(url: str) -> str:
    p = urlparse(url)
    return p.netloc or p.path.split("/")[0]


def _get_rate_limiter(cfg: SilkwebConfig) -> TokenBucketRateLimiter | None:
    global _RATE_LIMITER, _RATE_LIMITER_KEY
    key = (
        cfg.rate_limit_global,
        cfg.rate_limit_per_domain,
        cfg.respect_robots,
    )
    if _RATE_LIMITER is not None and key == _RATE_LIMITER_KEY:
        return _RATE_LIMITER
    with _SINGLETON_LOCK:
        if _RATE_LIMITER is not None and key == _RATE_LIMITER_KEY:
            return _RATE_LIMITER
        if not cfg.rate_limit_global and not cfg.rate_limit_per_domain and not cfg.respect_robots:
            _RATE_LIMITER = None
            _RATE_LIMITER_KEY = key
            return None
        _RATE_LIMITER = TokenBucketRateLimiter(
            global_rps=cfg.rate_limit_global,
            per_domain_rps=cfg.rate_limit_per_domain,
            honor_robots=bool(cfg.respect_robots),
            jitter=0.0,
        )
        _RATE_LIMITER_KEY = key
        return _RATE_LIMITER


def _html_hash(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()


def _cache_write(cfg: SilkwebConfig, url: str, page: SilkPage, *, allow_cache: bool) -> SilkPage:
    if not allow_cache:
        return page
    cm = _get_cache_manager(cfg)
    try:
        h = _html_hash(page.html)
        cm.page.set(url, h, page)
        cm.http._enforce_max_size()
    except Exception as e:
        raise SilkwebCacheError(
            message="Failed to write page cache.",
            backend=str(cfg.cache_backend),
            context={"error": repr(e)},
        ) from e
    return page


def _body_meaningful(page: SilkPage) -> bool:
    visible_text_len = _visible_text_len(page.html or "")
    html_len = len(page.html or "")
    # Use "visible" text length (ignoring script/style contents). This avoids falsely treating
    # bundled JS as meaningful content.
    if visible_text_len >= 500:
        return True
    # If the HTML is large but the extracted text is tiny, this is often a client-rendered shell
    # (React/Next/Vue) that needs a browser render.
    if html_len >= 8_000 and _looks_like_js_shell(page) and visible_text_len < 200:
        return False
    # Large HTML payloads are often real pages (catalog/listing pages may have short trafilatura
    # text but plenty of structured content in HTML).
    # Tiny HTML + tiny text = likely shell page rendered client-side.
    return html_len >= 8_000


def _looks_like_js_shell(page: SilkPage) -> bool:
    html = (page.html or "").lower()
    if not html:
        return True
    # Common SPA framework markers.
    if "__next_data__" in html or 'id="__next"' in html or "id='__next'" in html:
        return True
    if "data-reactroot" in html or "react-dom" in html:
        return True
    if ('id="app"' in html or "id='app'" in html) and (
        "webpack" in html or "vite" in html or "modulepreload" in html
    ):
        return True
    if "__nuxt" in html or ("nuxt" in html and "window.__nuxt__" in html):
        return True
    # Generic "enable javascript" / noscript warnings.
    if "<noscript" in html and "enable javascript" in html:
        return True
    # Lots of script tags with very little body content.
    script_count = html.count("<script")
    return script_count >= 25


def _visible_text_len(html: str) -> int:
    """
    Approximate visible text length by stripping script/style/noscript and tags.

    This is intentionally lightweight and heuristic-only (not a full HTML renderer).
    """
    if not html:
        return 0
    s = html
    # Remove script/style/noscript blocks (case-insensitive).
    for tag in ("script", "style", "noscript"):
        s = re.sub(rf"(?is)<{tag}[^>]*>.*?</{tag}>", " ", s)
    # Strip tags.
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    # Collapse whitespace.
    s = re.sub(r"\s+", " ", s).strip()
    return len(s)


def _looks_like_cloudflare(page: SilkPage) -> bool:
    title = str((page.metadata or {}).get("title") or "").lower()
    if "just a moment" in title or "checking your browser" in title:
        return True
    headers = {k.lower(): v for k, v in (page.headers or {}).items()}
    if "cf-ray" in headers:
        return True
    set_cookie = headers.get("set-cookie", "")
    return "cf-ray" in set_cookie


async def _fetch_at_tier(
    url: str, tier: int, *, cfg: SilkwebConfig, kwargs: dict[str, Any]
) -> SilkPage:
    limiter = _get_rate_limiter(cfg)
    if limiter is not None:
        await limiter.acquire(url)

    # Proxy selection (passed through to tier fetchers)
    pool = _get_proxy_pool(cfg)
    strategy = str(cfg.proxy_rotation or "on_failure")
    proxy: str | None = None
    if pool is not None and "proxy" not in kwargs:
        try:
            proxy = pool.next_proxy(strategy, domain=_domain(url))  # type: ignore[arg-type]
        except Exception:
            proxy = pool.next_proxy("on_failure", domain=_domain(url))
        if proxy:
            kwargs["proxy"] = proxy

    if tier == 0:
        return await httpx_fetcher.fetch(url, config=cfg, **kwargs)
    if tier == 1:
        # Default impersonate from config, but allow override via kwargs.
        if "impersonate" not in kwargs:
            kwargs["impersonate"] = cfg.impersonate
        return await curl_cffi_fetcher.fetch(url, config=cfg, **kwargs)
    if tier == 2:
        if "config" not in kwargs:
            kwargs["config"] = cfg
        return await playwright_fetcher.fetch(url, **kwargs)
    if tier == 3:
        if "config" not in kwargs:
            kwargs["config"] = cfg
        return await stealth_fetcher.fetch(url, **kwargs)
    raise ValueError(f"Unsupported tier: {tier}")


async def fetch(url: str, tier: Tier = "auto", **kwargs: Any) -> SilkPage:
    """
    Main async fetch orchestrator.

    Auto escalation logic:
    1. Start at Tier 0 (httpx)
    2. On SilkwebHTTPError 403/429/503 -> Tier 1
    3. If response body text is not meaningful (< 500 chars) -> Tier 2
    4. On SilkwebBlockedError or Cloudflare detection -> Tier 3
    5. Log each escalation with reason

    Cache layer: rendered-page cache (Layer 2) keyed by URL + content-hash, with
    a URL->last_hash pointer for lookup.
    """
    cfg = get_config()
    configure_logging(cfg)
    ensure_metrics_server(cfg)
    metrics = get_metrics()
    t_all = Timer()
    max_tier = int(cfg.max_tier)
    no_cache = bool(kwargs.pop("no_cache", False))

    cm = _get_cache_manager(cfg)
    # Cache lookup (rendered pages)
    if cfg.cache_enabled and not no_cache:
        try:
            page = cm.page.get_latest(url)
            if page is not None:
                # Don't serve a lower-tier cached page for an explicitly higher-tier request.
                if tier != "auto" and getattr(page, "fetch_tier", 0) < int(tier):
                    log_event(
                        "cache_miss",
                        url=url,
                        tier=tier,
                        layer="page",
                        reason="requested_tier_gt_cached",
                        cached_tier=getattr(page, "fetch_tier", None),
                    )
                else:
                    log_event(
                        "cache_hit",
                        url=url,
                        tier=getattr(page, "fetch_tier", None),
                        layer="page",
                    )
                    metrics.cache_hits_total.labels(layer="page").inc()
                    return page
            log_event("cache_miss", url=url, tier=tier, layer="page")
        except Exception as e:
            raise SilkwebCacheError(
                message="Failed to read page cache.",
                backend=str(cfg.cache_backend),
                context={"error": repr(e)},
            ) from e

    log_event("fetch_start", url=url, tier=tier)

    if tier != "auto":
        if int(tier) > max_tier:
            raise ValueError(f"Requested tier {tier} exceeds max_tier={max_tier}")
        call_kwargs: dict[str, Any] = dict(kwargs)
        pool = _get_proxy_pool(cfg)
        try:
            if int(tier) == 0:
                if "http_cache" not in call_kwargs:
                    call_kwargs["http_cache"] = cm.http
            else:
                call_kwargs.pop("http_cache", None)
            page = await _fetch_at_tier(url, int(tier), cfg=cfg, kwargs=call_kwargs)
        except Exception:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_failed(proxy_used)
            raise
        else:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_success(proxy_used)
        duration_ms = int(t_all.seconds() * 1000)
        log_event(
            "fetch_complete",
            url=url,
            tier=int(tier),
            duration_ms=duration_ms,
            status_code=getattr(page, "status", None),
        )
        metrics.requests_total.labels(
            tier=str(int(tier)), status=str(page.status), domain=_domain(url)
        ).inc()
        metrics.request_duration_seconds.labels(tier=str(int(tier)), domain=_domain(url)).observe(
            t_all.seconds()
        )
        maybe_save_fetch(
            cfg=cfg,
            page=page,
            url=url,
            tier=int(tier),
            duration_ms=duration_ms,
            cache_hit=False,
        )
        return _cache_write(cfg, url, page, allow_cache=cfg.cache_enabled and not no_cache)

    # If auto escalation is disabled, treat "auto" as tier 0 only.
    if not bool(getattr(cfg, "auto_escalate", True)):
        call_kwargs: dict[str, Any] = dict(kwargs)
        pool = _get_proxy_pool(cfg)
        try:
            if "http_cache" not in call_kwargs:
                call_kwargs["http_cache"] = cm.http
            page = await _fetch_at_tier(url, 0, cfg=cfg, kwargs=call_kwargs)
        except Exception:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_failed(proxy_used)
            raise
        else:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_success(proxy_used)
        duration_ms = int(t_all.seconds() * 1000)
        log_event(
            "fetch_complete",
            url=url,
            tier=0,
            duration_ms=duration_ms,
            status_code=getattr(page, "status", None),
        )
        metrics.requests_total.labels(tier="0", status=str(page.status), domain=_domain(url)).inc()
        metrics.request_duration_seconds.labels(tier="0", domain=_domain(url)).observe(
            t_all.seconds()
        )
        maybe_save_fetch(
            cfg=cfg,
            page=page,
            url=url,
            tier=0,
            duration_ms=duration_ms,
            cache_hit=False,
        )
        return _cache_write(cfg, url, page, allow_cache=cfg.cache_enabled and not no_cache)

    current_tier = 0
    while True:
        if current_tier > max_tier:
            # Should not happen, but keep safe.
            raise SilkwebBlockedError(
                message="Exceeded max_tier during auto escalation.",
                url=url,
                tier_tried=current_tier,
                context={"max_tier": max_tier},
            )

        call_kwargs = dict(kwargs)
        pool = _get_proxy_pool(cfg)
        try:
            if current_tier == 0:
                if "http_cache" not in call_kwargs:
                    call_kwargs["http_cache"] = cm.http
            else:
                call_kwargs.pop("http_cache", None)
            page = await _fetch_at_tier(url, current_tier, cfg=cfg, kwargs=call_kwargs)
        except SilkwebHTTPError as e:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_failed(proxy_used)
            if current_tier == 0 and e.status_code in {403, 429, 503} and max_tier >= 1:
                logger.info(
                    "fetch_escalate",
                    url=url,
                    from_tier=current_tier,
                    to_tier=1,
                    reason="http_status",
                    status_code=e.status_code,
                )
                log_event(
                    "fetch_escalated",
                    url=url,
                    tier=current_tier,
                    to_tier=1,
                    reason="http_status",
                    status_code=e.status_code,
                )
                current_tier = 1
                continue
            if current_tier == 1 and e.status_code in {403, 429, 503} and max_tier >= 2:
                logger.info(
                    "fetch_escalate",
                    url=url,
                    from_tier=current_tier,
                    to_tier=2,
                    reason="http_status",
                    status_code=e.status_code,
                )
                log_event(
                    "fetch_escalated",
                    url=url,
                    tier=current_tier,
                    to_tier=2,
                    reason="http_status",
                    status_code=e.status_code,
                )
                current_tier = 2
                continue
            raise
        except SilkwebTimeoutError:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_failed(proxy_used)
            next_tier = current_tier + 1
            if next_tier <= max_tier:
                logger.info(
                    "fetch_escalate",
                    url=url,
                    from_tier=current_tier,
                    to_tier=next_tier,
                    reason="timeout",
                )
                log_event(
                    "fetch_escalated",
                    url=url,
                    tier=current_tier,
                    to_tier=next_tier,
                    reason="timeout",
                )
                current_tier = next_tier
                continue
            raise
        except SilkwebBlockedError:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_failed(proxy_used)
            if max_tier >= 3 and current_tier < 3:
                logger.info(
                    "fetch_escalate",
                    url=url,
                    from_tier=current_tier,
                    to_tier=3,
                    reason="blocked_error",
                )
                log_event(
                    "fetch_escalated", url=url, tier=current_tier, to_tier=3, reason="blocked_error"
                )
                metrics.blocks_total.labels(
                    domain=_domain(url), challenge_type="blocked_error"
                ).inc()
                current_tier = 3
                continue
            raise
        except Exception:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_failed(proxy_used)
            raise
        else:
            proxy_used = call_kwargs.get("proxy")
            if pool is not None and isinstance(proxy_used, str) and proxy_used:
                pool.mark_success(proxy_used)

        # Cloudflare detection escalation
        if current_tier < 3 and max_tier >= 3 and _looks_like_cloudflare(page):
            logger.info(
                "fetch_escalate",
                url=url,
                from_tier=current_tier,
                to_tier=3,
                reason="cloudflare_detected",
            )
            log_event(
                "fetch_escalated",
                url=url,
                tier=current_tier,
                to_tier=3,
                reason="cloudflare_detected",
            )
            metrics.blocks_total.labels(domain=_domain(url), challenge_type="cloudflare").inc()
            current_tier = 3
            continue

        # Meaningless content escalation (Tier 0/1 -> Tier 2)
        if current_tier < 2 and max_tier >= 2 and not _body_meaningful(page):
            logger.info(
                "fetch_escalate",
                url=url,
                from_tier=current_tier,
                to_tier=2,
                reason="thin_content",
                text_len=len((page.text or "").strip()),
            )
            log_event(
                "fetch_escalated",
                url=url,
                tier=current_tier,
                to_tier=2,
                reason="thin_content",
                text_len=len((page.text or "").strip()),
            )
            current_tier = 2
            continue

        # Success
        duration_ms = int(t_all.seconds() * 1000)
        log_event(
            "fetch_complete",
            url=url,
            tier=current_tier,
            duration_ms=duration_ms,
            status_code=getattr(page, "status", None),
        )
        metrics.requests_total.labels(
            tier=str(current_tier), status=str(page.status), domain=_domain(url)
        ).inc()
        metrics.request_duration_seconds.labels(
            tier=str(current_tier), domain=_domain(url)
        ).observe(t_all.seconds())
        maybe_save_fetch(
            cfg=cfg,
            page=page,
            url=url,
            tier=current_tier,
            duration_ms=duration_ms,
            cache_hit=False,
        )
        return _cache_write(cfg, url, page, allow_cache=cfg.cache_enabled and not no_cache)
