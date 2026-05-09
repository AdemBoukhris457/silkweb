from __future__ import annotations

from silkweb.cache.page import RenderedPageCache
from silkweb.parse.page import SilkPage


def test_page_cache_memory_roundtrip() -> None:
    cache = RenderedPageCache(backend="memory")
    page = SilkPage(
        "<html><body>x</body></html>", url="https://example.com", status=200, fetch_tier=0
    )
    page._network_log = [{"url": "https://example.com", "status": 200}]  # type: ignore[attr-defined]
    cache.set("https://example.com", "h1", page)
    got = cache.get("https://example.com", "h1")
    assert got is not None
    assert got.html == page.html
    assert got.network_requests() == [{"url": "https://example.com", "status": 200}]

    latest = cache.get_latest("https://example.com")
    assert latest is not None
    assert latest.html == page.html

    # Ensure clear() fully resets all in-memory state (including timestamps).
    cache.clear()
    assert cache.get("https://example.com", "h1") is None
    assert cache.get_latest("https://example.com") is None
    assert cache.stats()["entries"] == 0


def test_page_cache_sqlite_roundtrip(tmp_path) -> None:
    cache = RenderedPageCache(backend="sqlite", sqlite_path=str(tmp_path / "page.sqlite"))
    page = SilkPage(
        "<html><body>y</body></html>", url="https://example.com/a", status=200, fetch_tier=1
    )
    cache.set("https://example.com/a", "h2", page)
    got = cache.get_latest("https://example.com/a")
    assert got is not None
    assert got.fetch_tier == 1
    assert got.html == page.html
