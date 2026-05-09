from __future__ import annotations

import pytest
from pydantic import BaseModel

import silkweb
from silkweb.crawl.crawler import AsyncCrawler
from silkweb.crawl.dedup import SeenSet
from silkweb.crawl.sitemap import collect_page_urls_from_sitemap, parse_sitemap_xml
from silkweb.parse.page import SilkPage


class Item(BaseModel):
    url: str


@pytest.mark.anyio
async def test_crawler_traverses_10_pages_and_dedups() -> None:
    # Build a 10-page mock site: /p0 links to /p1 and /p2, etc.
    base = "https://example.com"
    pages: dict[str, list[str]] = {}
    for i in range(10):
        links: list[str] = []
        if i + 1 < 10:
            links.append(f"{base}/p{i + 1}")
        if i + 2 < 10:
            links.append(f"{base}/p{i + 2}")
        pages[f"{base}/p{i}"] = links

    async def fake_fetch(url: str, **kwargs):
        html = f"<html><body>{url}</body></html>"
        page = SilkPage(html, url=url, status=200, fetch_tier=0, headers={}, metadata=None)
        # monkeypatch links() by setting url and using built-in links extraction is hard;
        # instead, we patch a method on the instance.
        page.links = lambda external=False, _u=url: pages[_u]  # type: ignore[method-assign]
        return page

    async def fake_extract(*, page: SilkPage):
        return [Item(url=page.url)]

    crawler = AsyncCrawler(
        start_url=f"{base}/p0",
        allowed_domains={"example.com"},
        url_pattern=r"/p\d+$",
        max_pages=10,
        max_depth=5,
        concurrency=5,
        per_domain_concurrency=2,
        schema=Item,
        prompt="url",
        fetch_func=fake_fetch,
        extract_func=fake_extract,
        dedup=SeenSet(backend="memory"),
    )

    seen: set[str] = set()
    items = []
    async for it in crawler.run():
        items.append(it)
        seen.add(it.url)

    assert len(items) == 10
    assert len(seen) == 10


@pytest.mark.anyio
async def test_crawler_start_url_fragment_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    base = "https://example.com"
    pages: dict[str, list[str]] = {f"{base}/p0": [f"{base}/p1"], f"{base}/p1": []}
    fetched: list[str] = []

    async def fake_fetch(url: str, **kwargs):
        fetched.append(url)
        html = "<html><body></body></html>"
        page = SilkPage(html, url=url, status=200, fetch_tier=0, headers={}, metadata=None)
        page.links = lambda external=False, _u=url: pages.get(_u, [])  # type: ignore[method-assign]
        return page

    async def fake_extract(*, page: SilkPage):
        return [Item(url=page.url)]

    crawler = AsyncCrawler(
        start_url=f"{base}/p0#section",
        allowed_domains={"example.com"},
        max_pages=10,
        max_depth=2,
        concurrency=2,
        schema=Item,
        prompt="x",
        fetch_func=fake_fetch,
        extract_func=fake_extract,
        dedup=SeenSet(backend="memory"),
    )
    items = [it async for it in crawler.run()]
    assert len(items) == 2
    assert fetched[0] == f"{base}/p0"


@pytest.mark.anyio
async def test_default_extract_passes_healer_and_selector_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from silkweb.config import get_config

    models: list[str] = []

    def track_create_provider(model: str):
        models.append(model)
        m = MagicMock()
        m.model = model
        return m

    captured: dict = {}

    async def fake_extract_url(**kwargs):
        captured.update(kwargs)
        return [{"u": "https://x.test/"}]

    monkeypatch.setattr("silkweb.llm.providers.registry.create_provider", track_create_provider)
    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.extract_url", fake_extract_url)

    class U(BaseModel):
        u: str

    cfg = get_config()
    crawler = AsyncCrawler(
        start_url="https://x.test/",
        schema=U,
        prompt="p",
        fetch_func=None,
        extract_func=None,
    )
    page = SilkPage("<html/>", url="https://x.test/")
    out = await crawler._default_extract(page=page)
    assert captured.get("healer") is not None
    assert models == [cfg.cleaner_model, cfg.extraction_model, cfg.selector_model]
    assert out[0].u == "https://x.test/"


@pytest.mark.anyio
async def test_async_crawl_schema_without_prompt_raises() -> None:
    class M(BaseModel):
        a: int

    with pytest.raises(ValueError, match="both schema and prompt"):
        await silkweb.async_crawl("https://ex.com/", schema=M)


@pytest.mark.anyio
async def test_parse_sitemap_urlset_and_index() -> None:
    urlset_xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc> https://ex.com/a </loc></url>
  <url><loc>https://ex.com/b</loc></url>
</urlset>"""
    k, locs = parse_sitemap_xml(urlset_xml)
    assert k == "urlset"
    assert locs == ["https://ex.com/a", "https://ex.com/b"]

    index_xml = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://ex.com/sm1.xml</loc></sitemap>
</sitemapindex>"""
    k2, locs2 = parse_sitemap_xml(index_xml)
    assert k2 == "sitemapindex"
    assert locs2 == ["https://ex.com/sm1.xml"]


@pytest.mark.anyio
async def test_collect_page_urls_from_sitemap_index_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaf = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ex.com/page1</loc></url>
</urlset>"""
    index_xml = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://ex.com/nested.xml</loc></sitemap>
</sitemapindex>"""

    async def fake_fetch(url: str, tier=0, **kwargs):
        if "sitemap.xml" in url or url.endswith("sitemap.xml"):
            return SilkPage(index_xml, url=url)
        if "nested.xml" in url:
            return SilkPage(leaf, url=url)
        return SilkPage("", url=url)

    urls = await collect_page_urls_from_sitemap(
        fake_fetch, "https://ex.com/sitemap.xml", max_pages=10, max_sitemap_files=5
    )
    assert urls == ["https://ex.com/page1"]


@pytest.mark.anyio
async def test_async_crawl_sitemap_invokes_crawl_per_loc(monkeypatch: pytest.MonkeyPatch) -> None:
    xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://ex.com/u1</loc></url>
  <url><loc>https://ex.com/u2</loc></url>
</urlset>"""

    async def fake_fetch(url: str, tier=0, **kwargs):
        return SilkPage(xml, url=url)

    crawled: list[str] = []

    async def fake_async_crawl(start_url: str, **kwargs):
        crawled.append(start_url)
        assert kwargs.get("allowed_domains") == {"ex.com"}
        return []

    monkeypatch.setattr(silkweb, "_async_fetch", fake_fetch)
    monkeypatch.setattr(silkweb, "async_crawl", fake_async_crawl)

    await silkweb.async_crawl_sitemap(
        "https://ex.com/sitemap.xml", schema=Item, prompt="x", max_pages=10
    )
    assert set(crawled) == {"https://ex.com/u1", "https://ex.com/u2"}
