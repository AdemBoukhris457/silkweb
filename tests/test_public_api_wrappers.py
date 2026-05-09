from __future__ import annotations

import types

import pytest
from pydantic import BaseModel


def test_fetch_wrapper_calls_async(monkeypatch: pytest.MonkeyPatch) -> None:
    import silkweb
    from silkweb.parse.page import SilkPage

    async def fake_async_fetch(url: str, *args, **kwargs):
        return SilkPage("<html/>", url=url, status=200, headers={}, metadata={}, fetch_tier=0)

    monkeypatch.setattr(silkweb, "_async_fetch", fake_async_fetch)
    page = silkweb.fetch("https://example.test/")
    assert page.url == "https://example.test/"
    assert page.status == 200


def test_query_wrapper_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    import silkweb
    from silkweb.silkql.executor import QueryResult

    class R(BaseModel):
        name: str

    async def fake_execute(url: str, silkql_string: str, **kwargs):
        return QueryResult(data=[R(name="x")], pages_scraped=1, cached=False)

    monkeypatch.setattr(silkweb, "_execute_query", fake_execute)
    out = silkweb.query("https://example.test/", "{ name }")
    assert out.pages_scraped == 1
    assert out.data[0].name == "x"


def test_crawl_sitemap_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    import silkweb
    from silkweb.parse.page import SilkPage

    async def fake_async_fetch(url: str, tier=0, **kwargs):
        assert tier == 0
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://a.test/p1</loc></url>
</urlset>"""
        return SilkPage(xml, url=url)

    async def fake_async_crawl(start_url: str, **kwargs):
        # Return one fake item per URL.
        class Item(BaseModel):
            url: str

        return [Item(url=start_url)]

    monkeypatch.setattr(silkweb, "_async_fetch", fake_async_fetch)
    monkeypatch.setattr(silkweb, "async_crawl", fake_async_crawl)
    items = silkweb.crawl_sitemap("https://a.test/sitemap.xml")
    assert len(items) == 1


def test_dataframe_auto_detect_uses_sys_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    from silkweb.output.dataframe import to_dataframe

    # Fake pandas module.
    fake_pd = types.SimpleNamespace(DataFrame=lambda rows: ("pd", rows))
    monkeypatch.setitem(__import__("sys").modules, "pandas", fake_pd)
    df = to_dataframe([{"a": 1}], engine="auto")
    assert df == ("pd", [{"a": 1}])
