from __future__ import annotations

import asyncio
import atexit
import contextlib
import time
from typing import Any, Literal, TypedDict

import structlog

from ...config import SilkwebConfig, get_config
from ...exceptions import SilkwebRenderError
from ...parse.page import SilkPage
from ...stealth.behavior import human_mouse_move, human_type, random_scroll
from .network_capture import capture_body_json, redact_headers

logger = structlog.get_logger(__name__)

BrowserName = Literal["chromium", "firefox", "webkit"]
WaitUntil = Literal["load", "domcontentloaded", "networkidle"]


class InterceptedRequest(TypedDict):
    url: str
    method: str
    headers: dict[str, str]
    body: str | None


class NetworkEvent(TypedDict, total=False):
    url: str
    method: str
    resource_type: str
    status: int
    request_headers: dict[str, str]
    response_headers: dict[str, str]
    body: dict[str, Any] | None


_playwright: Any | None = None
_browsers: dict[tuple[BrowserName, str | None], Any] = {}
_atexit_registered = False
# asyncio.Lock cannot be reused across asyncio.run() sessions — bind lazily per loop id.
_pw_lock: asyncio.Lock | None = None
_pw_lock_loop_id: int | None = None


def _async_lock() -> asyncio.Lock:
    """Return an asyncio.Lock for the currently running loop (handles multiple asyncio.run)."""
    global _pw_lock, _pw_lock_loop_id
    loop = asyncio.get_running_loop()
    lid = id(loop)
    if _pw_lock is None or _pw_lock_loop_id != lid:
        _pw_lock = asyncio.Lock()
        _pw_lock_loop_id = lid
    return _pw_lock


async def shutdown_playwright_pools() -> None:
    """Stop shared Playwright / browser instances."""
    await _close_all()


async def _close_all() -> None:
    global _playwright
    # Close browsers first.
    for b in list(_browsers.values()):
        with contextlib.suppress(Exception):
            await b.close()
    _browsers.clear()
    if _playwright is not None:
        with contextlib.suppress(Exception):
            await _playwright.stop()
        _playwright = None


def _close_all_sync() -> None:
    # Best-effort cleanup for short-lived scripts on Windows to avoid
    # noisy asyncio subprocess transport warnings at interpreter exit.
    with contextlib.suppress(Exception):
        asyncio.run(_close_all())


async def _get_browser(browser: BrowserName, *, proxy: str | None) -> Any:
    global _atexit_registered, _playwright
    async with _async_lock():
        if _playwright is None:
            try:
                from playwright.async_api import async_playwright  # type: ignore
            except Exception as e:
                raise SilkwebRenderError(
                    message="Playwright is not installed. Install with `pip install 'silkweb[browser]'`.",
                    url=None,
                    tier_tried=2,
                    context={"tier": 2, "error": repr(e)},
                ) from e

            _playwright = await async_playwright().start()
            if not _atexit_registered:
                atexit.register(_close_all_sync)
                _atexit_registered = True

        key = (browser, proxy)
        if key in _browsers:
            return _browsers[key]

        try:
            browser_type = getattr(_playwright, browser)
            launch_kwargs: dict[str, Any] = {"headless": True}
            if proxy:
                launch_kwargs["proxy"] = {"server": proxy}
            b = await browser_type.launch(**launch_kwargs)
        except Exception as e:
            raise SilkwebRenderError(
                message="Playwright browser failed to launch.",
                url=None,
                tier_tried=2,
                context={"tier": 2, "browser": browser, "error": repr(e)},
            ) from e

        _browsers[key] = b
        return b


async def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    user_agent: str | None = None,
    browser: BrowserName = "chromium",
    wait_until: WaitUntil = "load",
    wait_for: str | None = None,
    timeout: int = 30_000,
    viewport: dict[str, int] | None = None,
    intercept_requests: bool = False,
    capture_network: bool = False,
    capture_network_bodies: bool = False,
    max_network_events: int = 500,
    max_network_body_bytes: int = 200_000,
    proxy: str | None = None,
    config: SilkwebConfig | None = None,
) -> SilkPage:
    """
    Tier 2 fetcher: Playwright browser rendering.

    When `intercept_requests=True`, capture XHR/fetch network requests into
    `SilkPage._intercepted_requests`.
    """
    start = time.perf_counter()
    intercepted: list[InterceptedRequest] = []
    network_log: list[NetworkEvent] = []

    cfg = config or get_config()
    merged_headers: dict[str, str] = {}
    merged_headers.update(cfg.headers or {})
    if headers:
        merged_headers.update(headers)
    ua = user_agent or cfg.user_agent
    b = await _get_browser(browser, proxy=proxy)
    context = await b.new_context(
        viewport=viewport or {"width": 1280, "height": 720},
        user_agent=ua or None,
        extra_http_headers=merged_headers or None,
    )
    try:
        page = await context.new_page()
    except Exception:
        await context.close()
        raise

    if intercept_requests:

        def _on_request(req: Any) -> None:
            try:
                if getattr(req, "resource_type", None) not in {"xhr", "fetch"}:
                    return
                body = getattr(req, "post_data", None)
                if callable(body):
                    body = body()
                intercepted.append(
                    {
                        "url": str(req.url),
                        "method": str(req.method),
                        "headers": dict(req.headers or {}),
                        "body": body if isinstance(body, str) else None,
                    }
                )
            except Exception:
                # best-effort interception
                return

        page.on("request", _on_request)

    if capture_network:

        async def _on_response(resp: Any) -> None:
            try:
                if max_network_events > 0 and len(network_log) >= int(max_network_events):
                    return
                req = resp.request
                req_headers = redact_headers(getattr(req, "headers", {}) or {})
                res_headers = redact_headers(getattr(resp, "headers", {}) or {})
                body: dict[str, Any] | None = None
                if capture_network_bodies:
                    try:
                        txt = await resp.text()
                    except Exception:
                        txt = None
                    body = capture_body_json(
                        txt,
                        content_type=str(res_headers.get("content-type", "") or ""),
                        max_bytes=int(max_network_body_bytes),
                    )
                network_log.append(
                    {
                        "url": str(getattr(req, "url", "") or ""),
                        "method": str(getattr(req, "method", "") or ""),
                        "resource_type": str(getattr(req, "resource_type", "") or ""),
                        "status": int(getattr(resp, "status", 0) or 0),
                        "request_headers": req_headers,
                        "response_headers": res_headers,
                        "body": body,
                    }
                )
            except Exception:
                return

        page.on("response", lambda r: asyncio.create_task(_on_response(r)))

    try:
        response = await page.goto(url, wait_until=wait_until, timeout=timeout)
        if wait_for:
            await page.wait_for_selector(wait_for, timeout=timeout)

        # Optional "human" behavior (best-effort, kept benign)
        if cfg.human_mouse:
            await random_scroll(page)
            await human_mouse_move(page, wait_for or "body")

        if cfg.human_typing and wait_for:
            # Only probe typing if the element is an input-like control.
            try:
                is_typable = await page.eval_on_selector(
                    wait_for,
                    "(el) => !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)",
                )
            except Exception:
                is_typable = False
            if is_typable:
                # Type a harmless character and delete it.
                await human_type(page, wait_for, " ")
                with contextlib.suppress(Exception):
                    await page.keyboard.press("Backspace")

        html = await page.content()
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "fetch_failed",
            url=url,
            tier=2,
            duration_ms=duration_ms,
            browser=browser,
            error=repr(e),
        )
        raise SilkwebRenderError(
            message="Playwright render failed (timeout/crash).",
            url=url,
            tier_tried=2,
            context={
                "tier": 2,
                "duration_ms": duration_ms,
                "browser": browser,
                "wait_until": wait_until,
                "wait_for": wait_for,
                "timeout": timeout,
                "error": repr(e),
            },
        ) from e
    finally:
        await page.close()
        await context.close()

    duration_ms = int((time.perf_counter() - start) * 1000)
    status = int(getattr(response, "status", 200)) if response is not None else 200
    resp_headers: dict[str, str] = (
        {str(k).lower(): str(v) for k, v in (getattr(response, "headers", None) or {}).items()}
        if response is not None
        else {}
    )
    logger.info(
        "fetch_completed",
        url=url,
        status_code=status,
        duration_ms=duration_ms,
        tier=2,
        browser=browser,
    )

    silk_page = SilkPage(
        html, url=url, status=status, headers=resp_headers, metadata=None, fetch_tier=2
    )
    if intercept_requests:
        silk_page._intercepted_requests = intercepted  # type: ignore[attr-defined]
    if capture_network:
        silk_page._network_log = network_log  # type: ignore[attr-defined]
    return silk_page
