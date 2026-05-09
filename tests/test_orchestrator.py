from __future__ import annotations

import pytest

from silkweb.config import configure
from silkweb.exceptions import SilkwebHTTPError
from silkweb.fetch import orchestrator
from silkweb.parse.page import SilkPage


@pytest.fixture()
def temp_cache_dir(tmp_path) -> str:
    path = tmp_path / "cache"
    path.mkdir(parents=True, exist_ok=True)
    configure(
        cache_path=str(path), cache_enabled=True, page_cache_ttl=60, max_tier=3, auto_escalate=True
    )
    yield str(path)


@pytest.mark.anyio
async def test_auto_escalates_0_to_1_on_403(monkeypatch, temp_cache_dir: str) -> None:
    calls: list[int] = []

    async def t0(url: str, **kwargs):
        calls.append(0)
        raise SilkwebHTTPError(message="blocked", url=url, status_code=403)

    async def t1(url: str, **kwargs):
        calls.append(1)
        return SilkPage(
            "<html><body>" + ("x" * 9000) + "</body></html>", url=url, status=200, fetch_tier=1
        )

    monkeypatch.setattr(orchestrator.httpx_fetcher, "fetch", t0)
    monkeypatch.setattr(orchestrator.curl_cffi_fetcher, "fetch", t1)

    page = await orchestrator.fetch("https://example.com", tier="auto")
    assert page.fetch_tier == 1
    assert calls == [0, 1]


@pytest.mark.anyio
async def test_auto_escalates_to_2_on_thin_content(monkeypatch, temp_cache_dir: str) -> None:
    calls: list[int] = []

    async def t0(url: str, **kwargs):
        calls.append(0)
        return SilkPage("<html><body>hi</body></html>", url=url, status=200, fetch_tier=0)

    async def t2(url: str, **kwargs):
        calls.append(2)
        return SilkPage(
            "<html><body>" + ("y" * 800) + "</body></html>", url=url, status=200, fetch_tier=2
        )

    monkeypatch.setattr(orchestrator.httpx_fetcher, "fetch", t0)
    monkeypatch.setattr(orchestrator.playwright_fetcher, "fetch", t2)

    page = await orchestrator.fetch("https://example.com/thin", tier="auto")
    assert page.fetch_tier == 2
    assert calls == [0, 2]


@pytest.mark.anyio
async def test_auto_escalates_to_2_on_large_js_shell(monkeypatch, temp_cache_dir: str) -> None:
    calls: list[int] = []

    async def t0(url: str, **kwargs):
        calls.append(0)
        # Large HTML payload, but effectively no meaningful text: should be treated as JS shell.
        html = (
            "<html><head><title>App</title></head>"
            "<body><div id='__next'></div>" + ("<script>/*x*/</script>" * 300) + "</body></html>"
        )
        return SilkPage(html, url=url, status=200, fetch_tier=0)

    async def t2(url: str, **kwargs):
        calls.append(2)
        return SilkPage(
            "<html><body>" + ("rendered" * 500) + "</body></html>",
            url=url,
            status=200,
            fetch_tier=2,
        )

    monkeypatch.setattr(orchestrator.httpx_fetcher, "fetch", t0)
    monkeypatch.setattr(orchestrator.playwright_fetcher, "fetch", t2)

    page = await orchestrator.fetch("https://example.com/js-shell", tier="auto", no_cache=True)
    assert page.fetch_tier == 2
    assert calls == [0, 2]


@pytest.mark.anyio
async def test_respects_max_tier(monkeypatch, temp_cache_dir: str) -> None:
    configure(max_tier=0)

    async def t0(url: str, **kwargs):
        raise SilkwebHTTPError(message="blocked", url=url, status_code=403)

    monkeypatch.setattr(orchestrator.httpx_fetcher, "fetch", t0)

    with pytest.raises(SilkwebHTTPError):
        await orchestrator.fetch("https://example.com/blocked", tier="auto")


@pytest.mark.anyio
async def test_auto_escalate_disabled_does_not_escalate(monkeypatch, temp_cache_dir: str) -> None:
    configure(auto_escalate=False, max_tier=3)
    calls: list[int] = []

    async def t0(url: str, **kwargs):
        calls.append(0)
        raise SilkwebHTTPError(message="blocked", url=url, status_code=403)

    async def t1(url: str, **kwargs):
        calls.append(1)
        return SilkPage(
            "<html><body>should not be called</body></html>", url=url, status=200, fetch_tier=1
        )

    monkeypatch.setattr(orchestrator.httpx_fetcher, "fetch", t0)
    monkeypatch.setattr(orchestrator.curl_cffi_fetcher, "fetch", t1)

    with pytest.raises(SilkwebHTTPError):
        await orchestrator.fetch("https://example.com/no-escalate", tier="auto", no_cache=True)
    assert calls == [0]


@pytest.mark.anyio
async def test_layer2_cache_reuses_page(monkeypatch, temp_cache_dir: str) -> None:
    calls: list[int] = []

    async def t0(url: str, **kwargs):
        calls.append(0)
        return SilkPage(
            "<html><body>" + ("z" * 9000) + "</body></html>", url=url, status=200, fetch_tier=0
        )

    monkeypatch.setattr(orchestrator.httpx_fetcher, "fetch", t0)

    url = "https://example.com/cached"
    page1 = await orchestrator.fetch(url, tier="auto")
    page2 = await orchestrator.fetch(url, tier="auto")

    assert page1.html == page2.html
    assert calls == [0]  # second call should hit cache


@pytest.mark.anyio
async def test_auto_escalates_1_to_2_on_503(monkeypatch, temp_cache_dir: str) -> None:
    calls: list[int] = []

    async def t0(url: str, **kwargs):
        calls.append(0)
        raise SilkwebHTTPError(message="blocked", url=url, status_code=503)

    async def t1(url: str, **kwargs):
        calls.append(1)
        raise SilkwebHTTPError(message="still blocked", url=url, status_code=503)

    async def t2(url: str, **kwargs):
        calls.append(2)
        return SilkPage(
            "<html><body>" + ("ok" * 6000) + "</body></html>", url=url, status=200, fetch_tier=2
        )

    monkeypatch.setattr(orchestrator.httpx_fetcher, "fetch", t0)
    monkeypatch.setattr(orchestrator.curl_cffi_fetcher, "fetch", t1)
    monkeypatch.setattr(orchestrator.playwright_fetcher, "fetch", t2)

    page = await orchestrator.fetch("https://example.com/escalate", tier="auto", no_cache=True)
    assert page.fetch_tier == 2
    assert calls == [0, 1, 2]
