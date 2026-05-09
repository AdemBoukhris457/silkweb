from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import hishel
import httpx
from hishel.httpx import AsyncCacheTransport

from ..config import get_config

HttpBackend = Literal["sqlite", "redis"]


def _http_cache_db_path() -> str:
    cfg = get_config()
    base = os.path.expanduser(cfg.cache_path)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "http_cache.sqlite")


@dataclass(slots=True)
class HttpCache:
    """
    HTTP cache via hishel for httpx.

    Notes:
    - Conditional GET (ETag/Last-Modified) is handled by hishel.
    - TTL is implemented through AsyncSqliteStorage(default_ttl=...).
    - `max_size` is best-effort; currently not enforced by hishel storage directly.
    """

    enabled: bool = True
    backend: HttpBackend = "sqlite"
    ttl_s: float | None = None
    max_size_bytes: int | None = None
    redis_url: str | None = None
    sqlite_path: str | None = None

    def _storage(self) -> hishel.AsyncBaseStorage | None:
        if not self.enabled:
            return None
        if self.backend == "sqlite":
            path = self.sqlite_path or _http_cache_db_path()
            return hishel.AsyncSqliteStorage(database_path=path, default_ttl=self.ttl_s)
        if self.backend == "redis":
            # hishel's AsyncRedisStorage takes the URL as a positional arg.
            return hishel.AsyncRedisStorage(self.redis_url or "redis://localhost:6379/0")
        return None

    def wrap_transport(self, next_transport: httpx.AsyncBaseTransport) -> httpx.AsyncBaseTransport:
        storage = self._storage()
        if storage is None:
            return next_transport
        return AsyncCacheTransport(next_transport=next_transport, storage=storage)

    def _enforce_max_size(self) -> None:
        """Delete the SQLite cache file if it exceeds max_size_bytes."""
        if self.max_size_bytes is None or self.backend != "sqlite":
            return
        path = self.sqlite_path or _http_cache_db_path()
        if os.path.exists(path) and os.path.getsize(path) > self.max_size_bytes:
            os.remove(path)

    def clear(self) -> None:
        if not self.enabled:
            return
        if self.backend == "sqlite":
            path = self.sqlite_path or _http_cache_db_path()
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    # Best-effort: on Windows the file can be locked by another process.
                    return

    def stats(self) -> dict[str, Any]:
        if not self.enabled:
            return {"backend": "disabled", "ttl_s": self.ttl_s}
        if self.backend == "sqlite":
            path = self.sqlite_path or _http_cache_db_path()
            size = os.path.getsize(path) if os.path.exists(path) else 0
            return {
                "backend": "sqlite",
                "path": path,
                "size_bytes": size,
                "max_size_bytes": self.max_size_bytes,
                "ttl_s": self.ttl_s,
            }
        return {"backend": self.backend, "ttl_s": self.ttl_s}
