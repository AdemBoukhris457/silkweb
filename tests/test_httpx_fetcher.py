from __future__ import annotations

import httpx
import pytest

from silkweb.exceptions import SilkwebHTTPError, SilkwebTimeoutError
from silkweb.fetch.tiers.httpx_fetcher import fetch


@pytest.mark.anyio
async def test_fetch_success_returns_page(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://example.com/",
        status_code=200,
        text="<html><body><h1>OK</h1></body></html>",
        headers={"content-type": "text/html"},
    )

    page = await fetch("https://example.com/", headers={"x-test": "1"}, timeout_ms=1234)
    assert page.fetch_tier == 0
    assert page.status == 200
    assert page.url == "https://example.com/"
    assert "OK" in page.text

    req = httpx_mock.get_requests()[0]
    assert req.headers["x-test"] == "1"


@pytest.mark.anyio
async def test_fetch_non_2xx_raises_http_error(httpx_mock) -> None:
    httpx_mock.add_response(url="https://example.com/404", status_code=404, text="nope")

    with pytest.raises(SilkwebHTTPError) as ei:
        await fetch("https://example.com/404")

    assert ei.value.status_code == 404
    assert ei.value.url == "https://example.com/404"


@pytest.mark.anyio
async def test_fetch_timeout_raises_timeout_error(httpx_mock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("boom"), url="https://example.com/slow")

    with pytest.raises(SilkwebTimeoutError) as ei:
        await fetch("https://example.com/slow", timeout_ms=50)

    assert ei.value.url == "https://example.com/slow"
    assert ei.value.timeout_ms == 50


@pytest.mark.anyio
async def test_fetch_follow_redirects_final_url(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://example.com/start",
        status_code=302,
        headers={"location": "https://example.com/final"},
        text="",
    )
    httpx_mock.add_response(
        url="https://example.com/final",
        status_code=200,
        text="<html><body>final</body></html>",
    )

    page = await fetch("https://example.com/start", follow_redirects=True)
    assert page.url == "https://example.com/final"
