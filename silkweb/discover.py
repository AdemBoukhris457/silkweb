from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from genson import SchemaBuilder

from .exceptions import SilkwebRenderError
from .session.session import SilkSession


@dataclass(frozen=True, slots=True)
class DiscoveredEndpoint:
    url: str
    method: str
    request_headers: dict[str, str]
    request_body: Any | None
    response_status: int
    response_headers: dict[str, str]
    response_schema: dict[str, Any]
    pagination: dict[str, Any] | None
    auth: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class APIDiscoveryResult:
    endpoints: list[DiscoveredEndpoint]
    generated_scraper: str


_PAGINATION_KEYS = {
    "page",
    "offset",
    "cursor",
    "limit",
    "per_page",
    "page_size",
    "next",
    "after",
    "before",
}
_AUTH_HEADER_KEYS = {"authorization", "x-api-key", "x-auth-token"}


def _infer_schema(obj: Any) -> dict[str, Any]:
    b = SchemaBuilder()
    b.add_object(obj)
    return b.to_schema()


def _detect_pagination(url: str, body: Any | None) -> dict[str, Any] | None:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query or "")
    found = {k: qs[k] for k in qs if k.lower() in _PAGINATION_KEYS}
    body_keys: set[str] = set()
    if isinstance(body, dict):
        body_keys = {str(k).lower() for k in body}
    if found or (body_keys & _PAGINATION_KEYS):
        return {
            "query_params": list(found.keys()),
            "body_keys": sorted(body_keys & _PAGINATION_KEYS),
        }
    return None


def _detect_auth(headers: dict[str, str]) -> dict[str, Any] | None:
    low = {k.lower(): v for k, v in headers.items()}
    found = {k: low[k] for k in low if k in _AUTH_HEADER_KEYS}
    if not found:
        return None
    return {"headers": {k: ("<redacted>" if found[k] else "") for k in found}}


def _safe_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def _dedupe_key(*, method: str, url: str, request_body: Any) -> str:
    """Stable key for deduplicating captured JSON endpoints in the scaffold."""
    if request_body is None:
        body_part = ""
    elif isinstance(request_body, (dict, list)):
        body_part = json.dumps(request_body, sort_keys=True, ensure_ascii=False, default=str)
    else:
        body_part = str(request_body)
    h = hashlib.sha256(body_part.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"{method.upper()}\t{url}\t{h}"


async def _capture_json_endpoints(url: str, session: SilkSession | None) -> list[dict[str, Any]]:
    """
    Playwright capture that records request+response for XHR/fetch returning JSON.
    Returns list of dicts {url, method, request_headers, request_body, status, response_headers, response_text}.
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except Exception as e:
        raise SilkwebRenderError(
            message="Playwright is required for API discovery.",
            url=url,
            tier_tried=2,
            context={"error": repr(e)},
        ) from e

    captured: list[dict[str, Any]] = []

    async def handle_response(resp: Any) -> None:
        try:
            req = resp.request
            rtype = str(getattr(req, "resource_type", "") or "").lower()
            if rtype not in {"xhr", "fetch"}:
                return
            headers = {str(k).lower(): str(v) for k, v in (resp.headers or {}).items()}
            ctype = headers.get("content-type", "")
            if "application/json" not in ctype:
                return
            status = int(getattr(resp, "status", 0))
            text = await resp.text()
            captured.append(
                {
                    "url": str(req.url),
                    "method": str(req.method),
                    "request_headers": dict(req.headers or {}),
                    "request_body": getattr(req, "post_data", None),
                    "status": status,
                    "response_headers": dict(resp.headers or {}),
                    "response_text": text,
                }
            )
        except Exception:
            return

    if session is not None:
        await session._ensure_browser(headless=True)
        assert session._page is not None
        page = session._page
        page.on("response", lambda r: asyncio.create_task(handle_response(r)))
        await page.goto(url, wait_until="load", timeout=30_000)
        await page.wait_for_timeout(2000)
        return captured

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(handle_response(r)))
        await page.goto(url, wait_until="load", timeout=30_000)
        await page.wait_for_timeout(2000)
        await page.close()
        await context.close()
        await browser.close()
    return captured


def _generate_scraper(endpoints: list[DiscoveredEndpoint]) -> str:
    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "import httpx",
        "",
        "",
        "async def _request_json(method: str, url: str, *, headers: dict[str, str] | None = None, json_body=None):",
        "    async with httpx.AsyncClient(timeout=30.0) as client:",
        "        resp = await client.request(method, url, headers=headers, json=json_body)",
        "        resp.raise_for_status()",
        "        return resp.json()",
        "",
        "",
    ]
    for i, ep in enumerate(endpoints, start=1):
        fn = f"scrape_endpoint_{i}"
        headers = {}
        for k, _v in ep.request_headers.items():
            if k.lower() in _AUTH_HEADER_KEYS:
                if k.lower() == "authorization":
                    headers[k] = "Bearer <YOUR_TOKEN>"
                else:
                    headers[k] = "<YOUR_API_KEY>"
        lines.extend(
            [
                f"async def {fn}():",
                f"    url = {ep.url!r}",
                f"    method = {ep.method!r}",
                f"    headers = {headers!r}",
                f"    json_body = {ep.request_body!r}",
                "    return await _request_json(method, url, headers=headers or None, json_body=json_body)",
                "",
                "",
            ]
        )
    return "\n".join(lines)


async def discover_api(
    url: str,
    session: SilkSession | None = None,
    *,
    output_path: str | None = None,
) -> APIDiscoveryResult:
    """
    Discover JSON API endpoints by loading the page in Playwright and capturing
    ``xhr`` / ``fetch`` responses whose ``Content-Type`` includes ``application/json``.

    Requires Playwright (``pip install 'silkweb[browser]'``). Pass a :class:`SilkSession`
    to reuse cookies/storage for authenticated discovery.
    """
    captured = await _capture_json_endpoints(url, session=session)

    endpoints: list[DiscoveredEndpoint] = []
    seen_keys: set[str] = set()
    for c in captured:
        resp_headers = {
            str(k).lower(): str(v) for k, v in (c.get("response_headers") or {}).items()
        }
        ctype = resp_headers.get("content-type", "")
        if "application/json" not in ctype:
            continue

        text = str(c.get("response_text") or "")
        parsed = _safe_json(text)
        if parsed is None:
            continue

        body = c.get("request_body")
        if isinstance(body, bytes):
            try:
                body = body.decode("utf-8", errors="replace")
            except Exception:
                body = str(body)
        body_json = _safe_json(body) if isinstance(body, str) else body

        schema = _infer_schema(parsed)
        method_u = str(c.get("method") or "GET").upper()
        url_s = str(c.get("url") or "")
        body_for_key: Any = (
            body_json
            if isinstance(body_json, (dict, list))
            else (c.get("request_body") if c.get("request_body") is not None else None)
        )
        dk = _dedupe_key(method=method_u, url=url_s, request_body=body_for_key)
        if dk in seen_keys:
            continue
        seen_keys.add(dk)

        endpoint = DiscoveredEndpoint(
            url=url_s,
            method=method_u,
            request_headers={str(k): str(v) for k, v in (c.get("request_headers") or {}).items()},
            request_body=body_for_key,
            response_status=int(c.get("status") or 0),
            response_headers={str(k): str(v) for k, v in (c.get("response_headers") or {}).items()},
            response_schema=schema,
            pagination=_detect_pagination(url_s, body_json),
            auth=_detect_auth(
                {str(k): str(v) for k, v in (c.get("request_headers") or {}).items()}
            ),
        )
        endpoints.append(endpoint)

    generated = _generate_scraper(endpoints)

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(generated)

    return APIDiscoveryResult(endpoints=endpoints, generated_scraper=generated)
