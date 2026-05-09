from __future__ import annotations


def test_http_cache_memory_backend_disables_cache() -> None:
    import httpx

    from silkweb.cache.http import HttpCache

    cache = HttpCache(backend="memory")
    transport = httpx.AsyncHTTPTransport()
    wrapped = cache.wrap_transport(transport)
    assert wrapped is transport
