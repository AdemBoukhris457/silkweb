from __future__ import annotations

import httpx
import pytest

from silkweb.cache.http import HttpCache


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:  # type: ignore[override]
        self.calls += 1
        return httpx.Response(
            200,
            text="ok",
            headers={"etag": "abc", "cache-control": "public, max-age=3600"},
        )


@pytest.mark.anyio
async def test_http_cache_uses_cached_response(tmp_path) -> None:
    cache = HttpCache(backend="sqlite", ttl_s=60, sqlite_path=str(tmp_path / "http.sqlite"))
    ft = FakeTransport()
    transport = cache.wrap_transport(ft)

    async with httpx.AsyncClient(transport=transport) as client:
        r1 = await client.get("https://example.com/")
        r2 = await client.get("https://example.com/")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert ft.calls == 1
