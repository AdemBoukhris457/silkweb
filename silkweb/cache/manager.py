from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..config import get_config
from ..exceptions import SilkwebConfigError
from .http import HttpCache
from .page import PageBackend, RenderedPageCache
from .selectors import SelectorCache

CacheLayer = Literal["http", "page", "selectors"]


@dataclass(slots=True)
class CacheManager:
    http: HttpCache
    page: RenderedPageCache
    selectors: SelectorCache

    @classmethod
    def from_config(cls) -> CacheManager:
        cfg = get_config()
        backend = str(cfg.cache_backend or "sqlite").lower()
        if backend == "diskcache":
            raise SilkwebConfigError(
                message="cache_backend='diskcache' is not supported yet. Use 'sqlite', 'redis', or 'memory'.",
                key="cache_backend",
                value=backend,
            )

        http_cache = HttpCache(
            enabled=backend != "memory",
            backend="sqlite" if backend == "sqlite" else "redis",
            ttl_s=float(cfg.http_cache_ttl) if cfg.http_cache_ttl else None,
            redis_url=getattr(cfg, "redis_url", None),
        )
        page_ttl = int(cfg.page_cache_ttl) if cfg.page_cache_ttl else None
        page_backend: PageBackend
        if backend == "redis":
            page_backend = "redis"
        elif backend == "sqlite":
            page_backend = "sqlite"
        else:
            page_backend = "memory"
        page_cache = RenderedPageCache(
            backend=page_backend,
            ttl_seconds=page_ttl,
            redis_url=getattr(cfg, "redis_url", None),
        )
        sel_ttl = int(cfg.selector_cache_ttl) if cfg.selector_cache_ttl else None
        selectors_cache = SelectorCache(ttl_seconds=sel_ttl)
        return cls(http=http_cache, page=page_cache, selectors=selectors_cache)

    def clear(self, *, layer: CacheLayer | None = None, domain: str | None = None) -> None:
        if layer is None or layer == "http":
            self.http.clear()
        if layer is None or layer == "page":
            self.page.clear()
        if layer is None or layer == "selectors":
            if domain:
                self.selectors.clear(domain=domain)
            else:
                self.selectors.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "http": self.http.stats(),
            "page": self.page.stats(),
            "selectors": self.selectors.stats(),
        }
