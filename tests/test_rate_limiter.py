from __future__ import annotations

import time

import pytest

from silkweb.stealth.rate_limit import TokenBucketRateLimiter


@pytest.mark.anyio
async def test_per_domain_rps_enforced() -> None:
    limiter = TokenBucketRateLimiter(
        global_rps=None, per_domain_rps=2, honor_robots=False, jitter=0.0
    )
    url = "https://example.com/a"

    await limiter.acquire(url)
    await limiter.acquire(url)

    start = time.perf_counter()
    await limiter.acquire(url)
    elapsed = time.perf_counter() - start
    # 2 rps => third request should wait ~0.5s
    assert elapsed >= 0.45


@pytest.mark.anyio
async def test_global_rps_enforced_across_domains() -> None:
    limiter = TokenBucketRateLimiter(
        global_rps=2, per_domain_rps=None, honor_robots=False, jitter=0.0
    )
    await limiter.acquire("https://a.com/x")
    await limiter.acquire("https://b.com/y")

    start = time.perf_counter()
    await limiter.acquire("https://c.com/z")
    elapsed = time.perf_counter() - start
    # 2 rps => third request should wait ~0.5s
    assert elapsed >= 0.45


@pytest.mark.anyio
async def test_robots_crawl_delay_enforced(monkeypatch) -> None:
    limiter = TokenBucketRateLimiter(
        global_rps=None, per_domain_rps=None, honor_robots=True, jitter=0.0
    )

    async def fake_crawl_delay(self, _url: str):
        return 1.0

    monkeypatch.setattr(TokenBucketRateLimiter, "_crawl_delay_for_domain", fake_crawl_delay)

    url = "https://example.com/a"
    await limiter.acquire(url)

    start = time.perf_counter()
    await limiter.acquire(url)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.95
