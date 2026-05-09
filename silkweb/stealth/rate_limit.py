from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


@dataclass(slots=True)
class _TokenBucket:
    rate_per_s: float
    capacity: float
    tokens: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        now = time.monotonic()
        self.tokens = float(self.capacity)
        self.updated_at = now

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.updated_at)
        self.updated_at = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_s)

    def can_take(self, n: float, now: float) -> bool:
        self._refill(now)
        return self.tokens >= n

    def take(self, n: float, now: float) -> None:
        self._refill(now)
        self.tokens = max(0.0, self.tokens - n)

    def seconds_until(self, n: float, now: float) -> float:
        self._refill(now)
        if self.tokens >= n:
            return 0.0
        deficit = n - self.tokens
        if self.rate_per_s <= 0:
            return 3600.0
        return deficit / self.rate_per_s


_CRAWL_DELAY_RE = re.compile(r"(?im)^\s*crawl-delay\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$")
_UA_RE = re.compile(r"(?im)^\s*user-agent\s*:\s*(.+?)\s*$")


def _parse_crawl_delay(robots_txt: str) -> float | None:
    """
    Minimal robots.txt parser for Crawl-delay under User-agent: *.
    """
    if not robots_txt:
        return None

    lines = robots_txt.splitlines()
    current_ua: str | None = None
    ua_matches_star = False
    crawl_delay: float | None = None

    for line in lines:
        s = line.split("#", 1)[0].strip()
        if not s:
            continue
        m_ua = _UA_RE.match(s)
        if m_ua:
            current_ua = m_ua.group(1).strip().lower()
            ua_matches_star = current_ua == "*"
            continue
        if ua_matches_star:
            m_cd = _CRAWL_DELAY_RE.match(s)
            if m_cd:
                try:
                    crawl_delay = float(m_cd.group(1))
                except Exception:
                    crawl_delay = None

    return crawl_delay


@dataclass(slots=True)
class TokenBucketRateLimiter:
    """
    Async rate limiter:
    - Global token bucket: max N req/s across all domains
    - Per-domain buckets: max M req/s per domain
    - robots.txt Crawl-delay honoring (User-agent: *): minimum interval per domain
    - jitter: multiplies computed sleep by factor in [1, 1+jitter]
    """

    global_rps: int | None = None
    per_domain_rps: int | None = None
    honor_robots: bool = True
    jitter: float = 0.0
    robots_timeout_s: float = 5.0

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _global_bucket: _TokenBucket | None = None
    _domain_buckets: dict[str, _TokenBucket] = field(default_factory=dict)
    _domain_next_allowed_at: dict[str, float] = field(default_factory=dict)
    _robots_cache: dict[str, float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.global_rps is not None and self.global_rps > 0:
            self._global_bucket = _TokenBucket(
                rate_per_s=float(self.global_rps), capacity=float(self.global_rps)
            )

    def _get_domain_bucket(self, domain: str) -> _TokenBucket | None:
        if not self.per_domain_rps or self.per_domain_rps <= 0:
            return None
        b = self._domain_buckets.get(domain)
        if b is None:
            b = _TokenBucket(
                rate_per_s=float(self.per_domain_rps), capacity=float(self.per_domain_rps)
            )
            self._domain_buckets[domain] = b
        return b

    async def _fetch_robots_txt(self, base_url: str) -> str:
        async with httpx.AsyncClient(
            timeout=self.robots_timeout_s, follow_redirects=True
        ) as client:
            resp = await client.get(urljoin(base_url, "/robots.txt"))
            if resp.status_code >= 400:
                return ""
            return resp.text or ""

    async def _crawl_delay_for_domain(self, url: str) -> float | None:
        if not self.honor_robots:
            return None
        dom = urlparse(url).netloc
        if not dom:
            return None
        if dom in self._robots_cache:
            return self._robots_cache[dom]
        base = f"{urlparse(url).scheme or 'https'}://{dom}"
        try:
            txt = await self._fetch_robots_txt(base)
        except Exception:
            delay = None
        else:
            delay = _parse_crawl_delay(txt)
        self._robots_cache[dom] = delay
        return delay

    async def acquire(self, url: str) -> None:
        dom = urlparse(url).netloc or urlparse(url).path.split("/")[0]
        if not dom:
            dom = "default"

        crawl_delay = await self._crawl_delay_for_domain(url)

        while True:
            async with self._lock:
                now = time.monotonic()
                wait_s = 0.0

                if self._global_bucket is not None:
                    wait_s = max(wait_s, self._global_bucket.seconds_until(1.0, now))

                dom_bucket = self._get_domain_bucket(dom)
                if dom_bucket is not None:
                    wait_s = max(wait_s, dom_bucket.seconds_until(1.0, now))

                if crawl_delay is not None and crawl_delay > 0:
                    next_at = self._domain_next_allowed_at.get(dom, 0.0)
                    wait_s = max(wait_s, max(0.0, next_at - now))

                if wait_s <= 0:
                    if self._global_bucket is not None:
                        self._global_bucket.take(1.0, now)
                    if dom_bucket is not None:
                        dom_bucket.take(1.0, now)
                    if crawl_delay is not None and crawl_delay > 0:
                        self._domain_next_allowed_at[dom] = now + float(crawl_delay)
                    return

            # Sleep outside lock (with jitter)
            factor = 1.0
            if self.jitter and self.jitter > 0:
                factor = random.uniform(1.0, 1.0 + float(self.jitter))
            await asyncio.sleep(wait_s * factor)

    def stats(self) -> dict[str, Any]:
        now = time.monotonic()
        out: dict[str, Any] = {
            "global_rps": self.global_rps,
            "per_domain_rps": self.per_domain_rps,
            "honor_robots": self.honor_robots,
            "domains": len(self._domain_buckets),
            "robots_cached": len(self._robots_cache),
        }
        if self._global_bucket is not None:
            out["global_tokens"] = self._global_bucket.tokens
            out["global_capacity"] = self._global_bucket.capacity
            out["global_updated_at"] = self._global_bucket.updated_at
        out["domain_next_allowed_in_s"] = {
            d: max(0.0, t - now) for d, t in self._domain_next_allowed_at.items()
        }
        return out
