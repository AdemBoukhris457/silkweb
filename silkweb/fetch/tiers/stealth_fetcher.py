from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import time
from typing import Any, Literal

import structlog

from ...config import SilkwebConfig, get_config
from ...exceptions import SilkwebRenderError
from ...parse.page import SilkPage
from ...stealth.behavior import human_mouse_move, human_type, random_scroll
from .network_capture import capture_body_json, redact_headers

logger = structlog.get_logger(__name__)

StealthEngine = Literal["auto", "nodriver", "camoufox", "patchright"]
WaitUntil = Literal["load", "domcontentloaded", "networkidle"]

_lock = asyncio.Lock()
_pw: Any | None = None
_pw_browsers: dict[str | None, Any] = {}

_pr_pw: Any | None = None
_pr_browsers: dict[str | None, Any] = {}


def _is_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _pick_auto_engine(cfg: SilkwebConfig) -> StealthEngine:
    # Professional default: prefer stable Playwright-based paths. nodriver is opt-in.
    if _is_installed("patchright"):
        return "patchright"
    # camoufox isn't implemented in this scaffold; keep ordering for future.
    if _is_installed("playwright_stealth") or _is_installed("playwright-stealth"):
        # still run via Playwright with stealth patches
        return "patchright" if _is_installed("patchright") else "camoufox"
    if bool(getattr(cfg, "prefer_nodriver", False)) and _is_installed("nodriver"):
        return "nodriver"
    return "camoufox"


async def _ensure_playwright_browser(*, proxy: str | None) -> Any:
    global _pw, _pw_browsers
    async with _lock:
        if proxy in _pw_browsers:
            return _pw_browsers[proxy]
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception as e:
            raise SilkwebRenderError(
                message="Playwright is required for stealth fetching in this scaffold.",
                url=None,
                tier_tried=3,
                context={"tier": 3, "error": repr(e)},
            ) from e
        if _pw is None:
            _pw = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": True}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        b = await _pw.chromium.launch(**launch_kwargs)
        _pw_browsers[proxy] = b
        return b


async def _ensure_patchright_browser(*, proxy: str | None) -> Any:
    """
    Patchright path: use patchright's Playwright fork if installed.
    """
    global _pr_pw, _pr_browsers
    async with _lock:
        if proxy in _pr_browsers:
            return _pr_browsers[proxy]
        try:
            # Patchright generally mirrors Playwright's async API.
            from patchright.async_api import async_playwright as pr_async_playwright  # type: ignore
        except Exception as e:
            raise SilkwebRenderError(
                message="patchright is not available.",
                url=None,
                tier_tried=3,
                context={"tier": 3, "engine": "patchright", "error": repr(e)},
            ) from e
        if _pr_pw is None:
            _pr_pw = await pr_async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": True}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        b = await _pr_pw.chromium.launch(**launch_kwargs)
        _pr_browsers[proxy] = b
        return b


def _looks_like_cloudflare(title: str | None, headers: dict[str, str] | None) -> bool:
    t = (title or "").strip().lower()
    if "just a moment" in t or "checking your browser" in t:
        return True
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return "cf-ray" in h


async def _has_cf_clearance_cookie(context: Any) -> bool:
    try:
        cookies = await context.cookies()
    except Exception:
        return False
    return any(c.get("name") == "cf_clearance" for c in cookies if isinstance(c, dict))


async def _wait_for_challenge_resolution(page: Any, context: Any, *, timeout_ms: int) -> None:
    deadline = time.perf_counter() + (timeout_ms / 1000.0)
    while time.perf_counter() < deadline:
        try:
            title = await page.title()
        except Exception:
            title = ""

        # If Cloudflare has set clearance cookie and title looks normal, assume resolved.
        if await _has_cf_clearance_cookie(context) and not _looks_like_cloudflare(title, None):
            return

        # Otherwise, keep waiting briefly for navigations / auto-refresh.
        await asyncio.sleep(1.0)


async def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    user_agent: str | None = None,
    stealth_engine: StealthEngine = "auto",
    # "networkidle" often never completes on SPAs (WebSockets, long-polling, beacons).
    # Tier 2 Playwright defaults to "load"; match that here. Pass wait_until="networkidle"
    # when you truly need a quiet network (and the site cooperates).
    wait_until: WaitUntil = "load",
    timeout: int = 30_000,
    viewport: dict[str, int] | None = None,
    capture_network: bool = False,
    capture_network_bodies: bool = False,
    max_network_events: int = 500,
    max_network_body_bytes: int = 200_000,
    proxy: str | None = None,
    config: SilkwebConfig | None = None,
) -> SilkPage:
    """
    Tier 3 fetcher: stealth browser orchestration.

    Engines:
    - nodriver (best, if available): CDP-connected Chrome (placeholder in this scaffold)
    - patchright (if available): patched Playwright Chromium
    - playwright-stealth fallback: uses Playwright with stealth scripts if present

    Cloudflare detection: checks for `cf-ray` header (when available), "Just a moment" title,
    and whether `cf_clearance` cookie appears. If detected, waits up to 30s for resolution.

    Navigation uses Playwright ``wait_until`` (default ``"load"``). Prefer ``"load"`` or
    ``"domcontentloaded"`` for SPAs; use ``"networkidle"`` only when the page actually
    reaches an idle network state.
    """
    cfg = config or get_config()
    merged_headers: dict[str, str] = {}
    merged_headers.update(cfg.headers or {})
    if headers:
        merged_headers.update(headers)
    ua = user_agent or cfg.user_agent
    engine = stealth_engine
    if engine == "auto":
        engine = _pick_auto_engine(cfg)

    start = time.perf_counter()

    if engine == "nodriver":
        if not _is_installed("nodriver"):
            raise SilkwebRenderError(
                message="nodriver not installed.",
                url=url,
                tier_tried=3,
                context={"tier": 3, "engine": "nodriver"},
            )

        # NOTE: nodriver API varies; this is a best-effort placeholder that may be refined later.
        # We intentionally fall back to Playwright-based stealth if nodriver path fails.
        nd_browser = None
        try:
            import nodriver as uc  # type: ignore

            nd_browser = await uc.start(headless=True)  # type: ignore[attr-defined]
            tab = await nd_browser.get(url)  # type: ignore[attr-defined]
            await tab.wait("networkidle", timeout=timeout)  # type: ignore[attr-defined]
            html = await tab.content()  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(
                "stealth_engine_failed", url=url, tier=3, engine="nodriver", error=repr(e)
            )
            engine = "patchright" if _is_installed("patchright") else "camoufox"
        else:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "fetch_completed",
                url=url,
                status_code=200,
                duration_ms=duration_ms,
                tier=3,
                engine="nodriver",
            )
            return SilkPage(html, url=url, status=200, headers={}, metadata=None, fetch_tier=3)
        finally:
            if nd_browser is not None:
                with contextlib.suppress(Exception):
                    nd_browser.stop()

    # patchright preferred over playwright-stealth
    if engine == "patchright":
        browser_obj = await _ensure_patchright_browser(proxy=proxy)
        context = await browser_obj.new_context(
            viewport=viewport or {"width": 1280, "height": 720},
            user_agent=ua or None,
            extra_http_headers=merged_headers or None,
        )
        try:
            page = await context.new_page()
        except Exception:
            await context.close()
            raise
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout)
            if cfg.human_mouse:
                await random_scroll(page)
                await human_mouse_move(page, "body")
            if cfg.human_typing:
                await human_type(page, "body", "")
            html = await page.content()
            title = await page.title()
            resp_headers = response.headers if response is not None else {}

            if _looks_like_cloudflare(title, resp_headers) or not await _has_cf_clearance_cookie(
                context
            ):
                await _wait_for_challenge_resolution(page, context, timeout_ms=timeout)
                html = await page.content()
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            ctx: dict[str, Any] = {
                "tier": 3,
                "engine": "patchright",
                "duration_ms": duration_ms,
                "error": repr(e),
                "wait_until": wait_until,
            }
            if wait_until == "networkidle" and (
                "Timeout" in type(e).__name__ or "timeout" in repr(e).lower()
            ):
                ctx["hint"] = (
                    "networkidle timed out; many SPAs never go idle. "
                    "Retry with wait_until='load' or 'domcontentloaded' (Tier 3 default is load)."
                )
            raise SilkwebRenderError(
                message="Stealth render failed.",
                url=url,
                tier_tried=3,
                context=ctx,
            ) from e
        finally:
            await page.close()
            await context.close()

        duration_ms = int((time.perf_counter() - start) * 1000)
        status = int(getattr(response, "status", 200)) if response is not None else 200
        final_headers = (
            {str(k).lower(): str(v) for k, v in (getattr(response, "headers", None) or {}).items()}
            if response is not None
            else {}
        )
        logger.info(
            "fetch_completed",
            url=url,
            status_code=status,
            duration_ms=duration_ms,
            tier=3,
            engine="patchright",
        )
        out = SilkPage(
            html, url=url, status=status, headers=final_headers, metadata=None, fetch_tier=3
        )
        # Note: network capture is only implemented in the Playwright fallback path in this scaffold.
        return out

    # camoufox / playwright-stealth fallback path (uses Playwright Chromium in this scaffold)
    browser_obj = await _ensure_playwright_browser(proxy=proxy)
    context = await browser_obj.new_context(
        viewport=viewport or {"width": 1280, "height": 720},
        user_agent=ua or None,
        extra_http_headers=merged_headers or None,
    )
    try:
        page = await context.new_page()
    except Exception:
        await context.close()
        raise

    # Apply playwright-stealth scripts if available
    if _is_installed("playwright_stealth"):
        try:
            from playwright_stealth import stealth_async  # type: ignore

            await stealth_async(page)
        except Exception as e:
            logger.warning(
                "stealth_patch_failed", url=url, tier=3, engine="playwright-stealth", error=repr(e)
            )
    else:
        logger.warning(
            "stealth_deps_missing",
            url=url,
            tier=3,
            engine="playwright",
            message="No stealth engines installed; using plain Playwright.",
        )

    network_log: list[dict[str, Any]] = []
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
        if cfg.human_mouse:
            await random_scroll(page)
            await human_mouse_move(page, "body")
        if cfg.human_typing:
            await human_type(page, "body", "")
        html = await page.content()
        title = await page.title()
        resp_headers = response.headers if response is not None else {}

        if _looks_like_cloudflare(title, resp_headers) or not await _has_cf_clearance_cookie(
            context
        ):
            await _wait_for_challenge_resolution(page, context, timeout_ms=timeout)
            html = await page.content()
    except Exception as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        ctx2: dict[str, Any] = {
            "tier": 3,
            "engine": "playwright",
            "duration_ms": duration_ms,
            "error": repr(e),
            "wait_until": wait_until,
        }
        if wait_until == "networkidle" and (
            "Timeout" in type(e).__name__ or "timeout" in repr(e).lower()
        ):
            ctx2["hint"] = (
                "networkidle timed out; many SPAs never go idle. "
                "Retry with wait_until='load' or 'domcontentloaded' (Tier 3 default is load)."
            )
        raise SilkwebRenderError(
            message="Stealth render failed.",
            url=url,
            tier_tried=3,
            context=ctx2,
        ) from e
    finally:
        await page.close()
        await context.close()

    duration_ms = int((time.perf_counter() - start) * 1000)
    status = int(getattr(response, "status", 200)) if response is not None else 200
    final_headers = (
        {str(k).lower(): str(v) for k, v in (getattr(response, "headers", None) or {}).items()}
        if response is not None
        else {}
    )
    logger.info(
        "fetch_completed",
        url=url,
        status_code=status,
        duration_ms=duration_ms,
        tier=3,
        engine="playwright-stealth" if _is_installed("playwright_stealth") else "playwright",
    )
    out = SilkPage(html, url=url, status=status, headers=final_headers, metadata=None, fetch_tier=3)
    if capture_network:
        out._network_log = network_log  # type: ignore[attr-defined]
    return out
