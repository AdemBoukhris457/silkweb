from __future__ import annotations

import pytest

from silkweb.cache.http import HttpCache
from silkweb.config import configure, get_config
from silkweb.fetch.tiers import httpx_fetcher
from silkweb.parse.page import SilkPage


class _Resp:
    def __init__(self) -> None:
        self.status_code = 200
        self.headers = {}
        self.url = "https://example.test/"
        self.text = "<html><body>ok</body></html>"


class _Client:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, url: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Cannot parse Expires header")
        return _Resp()


@pytest.mark.anyio
async def test_http_cache_header_parse_error_retries_without_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(cache_enabled=True)
    cfg = get_config()

    c = _Client()

    def fake_get_client(**kwargs):
        # Always return same client; fetch() should call it twice (first fails, second succeeds)
        return c

    monkeypatch.setattr(httpx_fetcher, "_get_client", fake_get_client)
    page = await httpx_fetcher.fetch(
        "https://example.test/",
        config=cfg,
        http_cache=HttpCache(backend="memory"),
        use_http_cache=True,
    )
    assert isinstance(page, SilkPage)
    assert page.status == 200
    assert c.calls == 2
