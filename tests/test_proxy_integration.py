from __future__ import annotations

import importlib

import pytest

import silkweb
from silkweb.parse.page import SilkPage


@pytest.mark.anyio
async def test_fetch_passes_proxy_to_tier0(monkeypatch) -> None:
    silkweb.configure(proxies=["http://proxy1:8080"], proxy_rotation="per_request")

    used = {"proxy": None}

    async def fake_fetch(url: str, *, proxy=None, **kwargs):
        used["proxy"] = proxy
        return SilkPage("<html/>", url=url, status=200, fetch_tier=0, headers={}, metadata=None)

    orch = importlib.import_module("silkweb.fetch.orchestrator")
    monkeypatch.setattr(orch.httpx_fetcher, "fetch", fake_fetch)

    page = await silkweb.async_fetch("https://example.com", tier=0, no_cache=True)
    assert page.fetch_tier == 0
    assert used["proxy"] == "http://proxy1:8080"
