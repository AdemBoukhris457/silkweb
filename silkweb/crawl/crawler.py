from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel

from ..config import get_config
from ..llm.pipelines.heal import SelfHealer
from ..parse.page import SilkPage
from .dedup import SeenSet

OnPage = Callable[[SilkPage], Awaitable[None]] | None
OnItem = Callable[[BaseModel], Awaitable[None]] | None
OnError = Callable[[str, Exception], Awaitable[None]] | None


def _domain(url: str) -> str:
    p = urlparse(url)
    return p.netloc or p.path.split("/")[0]


def _normalize_link(base: str, href: str) -> str | None:
    if not href:
        return None
    abs_url = urljoin(base, href)
    # Drop fragments
    parsed = urlparse(abs_url)
    if parsed.scheme not in {"http", "https"}:
        return None
    return parsed._replace(fragment="").geturl()


def _normalize_seed_url(url: str) -> str:
    """Strip fragment from http(s) seed URLs so dedup matches discovered links."""
    u = (url or "").strip()
    if not u:
        return u
    parsed = urlparse(u)
    if parsed.scheme not in {"http", "https"}:
        return u
    return parsed._replace(fragment="").geturl()


@dataclass(slots=True)
class AsyncCrawler:
    start_url: str
    allowed_domains: set[str] | None = None
    url_pattern: str | None = None
    max_pages: int = 100
    max_depth: int = 2
    concurrency: int = 10
    per_domain_concurrency: int = 2
    #: Best-effort cap on ``asyncio.Queue`` depth for discovered URLs (avoids huge queues).
    max_pending_urls: int = 5000
    schema: type[BaseModel] | None = None
    prompt: str | None = None
    dedup: SeenSet = field(default_factory=SeenSet)

    on_page: OnPage = None
    on_item: OnItem = None
    on_error: OnError = None

    # injection points for tests
    fetch_func: Callable[..., Awaitable[SilkPage]] | None = None
    extract_func: Callable[..., Awaitable[list[BaseModel]]] | None = None

    _pattern_re: re.Pattern[str] | None = None
    _global_sem: asyncio.Semaphore = field(init=False)
    _domain_sems: dict[str, asyncio.Semaphore] = field(default_factory=dict)
    _pages_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _queue_cap_lock: asyncio.Lock = field(init=False)
    _pages_fetched: int = 0

    def __post_init__(self) -> None:
        self._global_sem = asyncio.Semaphore(max(1, int(self.concurrency)))
        self._queue_cap_lock = asyncio.Lock()
        if self.url_pattern:
            self._pattern_re = re.compile(self.url_pattern)

    def _domain_sem(self, domain: str) -> asyncio.Semaphore:
        sem = self._domain_sems.get(domain)
        if sem is None:
            sem = asyncio.Semaphore(max(1, int(self.per_domain_concurrency)))
            self._domain_sems[domain] = sem
        return sem

    def _allowed(self, url: str) -> bool:
        dom = _domain(url).lower()
        if self.allowed_domains and dom not in {d.lower() for d in self.allowed_domains}:
            return False
        return not (self._pattern_re and not self._pattern_re.search(url))

    async def _default_fetch(self, url: str, **fetch_kwargs: Any) -> SilkPage:
        from ..fetch.orchestrator import fetch as fetch_url

        return await fetch_url(url, tier="auto", **fetch_kwargs)

    async def _default_extract(self, *, page: SilkPage) -> list[BaseModel]:
        if self.schema is None or self.prompt is None:
            return []
        cfg = get_config()
        from ..cache.manager import CacheManager
        from ..llm.pipelines.orchestrator import extract_url
        from ..llm.providers.registry import create_provider

        selectors = CacheManager.from_config().selectors
        healer = SelfHealer(max_attempts=max(1, int(cfg.max_retries)))
        items = await extract_url(
            url=page.url,
            html=page.html,
            schema=self.schema,
            prompt=self.prompt,
            cleaner_provider=create_provider(cfg.cleaner_model),
            extraction_provider=create_provider(cfg.extraction_model),
            selector_provider=create_provider(cfg.selector_model),
            selector_cache=selectors,
            healer=healer,
        )
        out: list[BaseModel] = []
        for it in items:
            payload = {k: v for k, v in it.items() if k in self.schema.model_fields}
            out.append(self.schema.model_validate(payload))
        return out

    async def run(self, **fetch_kwargs: Any) -> AsyncGenerator[BaseModel, None]:
        """
        Crawl starting at `start_url`, yielding extracted items.

        Requires ``schema`` and ``prompt`` both set or both omitted; mismatched
        configuration raises ``ValueError``.
        """
        if (self.schema is None) ^ (self.prompt is None):
            raise ValueError("AsyncCrawler requires both schema and prompt, or neither")

        fetch = self.fetch_func or self._default_fetch
        extract = self.extract_func or (lambda **kw: self._default_extract(page=kw["page"]))

        q: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()
        start = _normalize_seed_url(self.start_url)
        if self._allowed(start) and self.dedup.add(start):
            q.put_nowait((start, 0))

        out_q: asyncio.Queue[BaseModel | None] = asyncio.Queue()

        async def worker() -> None:
            while True:
                item = await q.get()
                if item is None:
                    q.task_done()
                    break
                url, depth = item

                async with self._pages_lock:
                    if self._pages_fetched >= int(self.max_pages):
                        q.task_done()
                        continue
                    self._pages_fetched += 1

                dom = _domain(url)
                async with self._global_sem, self._domain_sem(dom):
                    try:
                        page = await fetch(url, **fetch_kwargs)
                        if self.on_page:
                            await self.on_page(page)

                        # Discover links
                        if depth < int(self.max_depth):
                            cap = max(1, int(self.max_pending_urls))
                            for href in page.links(external=False):
                                nxt = _normalize_link(page.url or url, href)
                                if not nxt or not self._allowed(nxt):
                                    continue
                                async with self._queue_cap_lock:
                                    if q.qsize() >= cap:
                                        continue
                                    if self.dedup.add(nxt):
                                        q.put_nowait((nxt, depth + 1))

                        # Extract items
                        if self.schema and self.prompt:
                            models = await extract(page=page)
                            for m in models:
                                if self.on_item:
                                    await self.on_item(m)
                                await out_q.put(m)
                    except Exception as e:
                        if self.on_error:
                            await self.on_error(url, e)
                    finally:
                        q.task_done()

        n_workers = max(1, int(self.concurrency))
        tasks = [asyncio.create_task(worker()) for _ in range(n_workers)]

        async def closer() -> None:
            await q.join()
            for _ in tasks:
                q.put_nowait(None)
            await asyncio.gather(*tasks, return_exceptions=True)
            await out_q.put(None)

        closer_task = asyncio.create_task(closer())

        while True:
            it = await out_q.get()
            if it is None:
                break
            yield it

        # Ensure closer completes (and avoid task warnings)
        await closer_task
