from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from ..config import get_config
from ..parse.page import SilkPage

PageBackend = Literal["sqlite", "memory", "redis"]


def _default_page_db_path() -> str:
    cfg = get_config()
    base = os.path.expanduser(cfg.cache_path)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "page_cache.sqlite")


def _serialize_page(page: SilkPage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "html": page.html,
        "url": page.url,
        "status": page.status,
        "headers": page.headers,
        "metadata": page.metadata,
        "fetch_tier": page.fetch_tier,
    }
    intercepted = getattr(page, "_intercepted_requests", None)
    if intercepted is not None:
        payload["_intercepted_requests"] = intercepted
    network_log = getattr(page, "_network_log", None)
    if network_log is not None:
        payload["_network_log"] = network_log
    return payload


def _deserialize_page(payload: dict[str, Any]) -> SilkPage:
    page = SilkPage(
        payload.get("html", ""),
        url=str(payload.get("url", "")),
        status=int(payload.get("status", 200)),
        headers=dict(payload.get("headers", {}) or {}),
        metadata=payload.get("metadata"),
        fetch_tier=int(payload.get("fetch_tier", 0)),
    )
    if "_intercepted_requests" in payload:
        page._intercepted_requests = payload["_intercepted_requests"]  # type: ignore[attr-defined]
    if "_network_log" in payload:
        page._network_log = payload["_network_log"]  # type: ignore[attr-defined]
    return page


@dataclass(slots=True)
class RenderedPageCache:
    backend: PageBackend = "sqlite"
    sqlite_path: str | None = None
    ttl_seconds: int | None = None
    redis_url: str | None = None

    # memory backend
    _mem_pages: dict[tuple[str, str], dict[str, Any]] | None = None
    _mem_last: dict[str, str] | None = None
    _mem_timestamps: dict[tuple[str, str], datetime] | None = None

    def __post_init__(self) -> None:
        if self.backend == "memory":
            self._mem_pages = {}
            self._mem_last = {}
            self._mem_timestamps = {}
        if self.backend == "sqlite":
            self._init_sqlite()

    @property
    def path(self) -> str:
        return self.sqlite_path or _default_page_db_path()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_sqlite(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    url TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (url, content_hash)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS url_last_hash (
                    url TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.commit()

    def _redis_client(self) -> Any:
        try:
            import redis
        except ImportError as e:
            raise RuntimeError("redis-py is required for the redis page cache backend") from e
        return redis.Redis.from_url(
            self.redis_url or os.environ.get("SILKWEB_REDIS_URL", "") or "redis://localhost:6379/0"
        )

    def _redis_key(self, url: str, content_hash: str) -> str:
        return f"silkweb:page:{url}:{content_hash}"

    def _redis_latest_key(self, url: str) -> str:
        return f"silkweb:page_latest:{url}"

    def get(self, url: str, content_hash: str) -> SilkPage | None:
        if self.backend == "memory":
            assert self._mem_pages is not None
            payload = self._mem_pages.get((url, content_hash))
            return _deserialize_page(payload) if isinstance(payload, dict) else None

        if self.backend == "redis":
            r = self._redis_client()
            raw = r.get(self._redis_key(url, content_hash))
            if raw is None:
                return None
            payload = json.loads(raw)
            return _deserialize_page(payload) if isinstance(payload, dict) else None

        if self.backend != "sqlite":
            return None

        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM pages WHERE url=? AND content_hash=?",
                (url, content_hash),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                return None
            return _deserialize_page(payload)

    def _is_expired(self, created_at_str: str) -> bool:
        if self.ttl_seconds is None:
            return False
        try:
            created = datetime.fromisoformat(created_at_str)
            age = (datetime.now(tz=timezone.utc) - created).total_seconds()
            return age > self.ttl_seconds
        except Exception:
            return False

    def get_latest(self, url: str) -> SilkPage | None:
        if self.backend == "memory":
            assert self._mem_last is not None and self._mem_timestamps is not None
            last = self._mem_last.get(url)
            if not last:
                return None
            ts = self._mem_timestamps.get((url, last))
            if ts is not None and self._is_expired(ts.isoformat()):
                return None
            return self.get(url, last)

        if self.backend == "redis":
            r = self._redis_client()
            raw = r.get(self._redis_latest_key(url))
            if raw is None:
                return None
            info = json.loads(raw)
            if isinstance(info, dict):
                updated_at = info.get("updated_at", "")
                if self._is_expired(str(updated_at)):
                    return None
                return self.get(url, str(info.get("content_hash", "")))
            return None

        if self.backend != "sqlite":
            return None

        with self._connect() as con:
            row = con.execute(
                "SELECT content_hash, updated_at FROM url_last_hash WHERE url=?",
                (url,),
            ).fetchone()
            if row is None:
                return None
            if self._is_expired(str(row["updated_at"])):
                return None
            return self.get(url, str(row["content_hash"]))

    def set(self, url: str, content_hash: str, page: SilkPage) -> None:
        payload = _serialize_page(page)
        if self.backend == "memory":
            assert self._mem_pages is not None and self._mem_last is not None
            assert self._mem_timestamps is not None
            self._mem_pages[(url, content_hash)] = payload
            self._mem_last[url] = content_hash
            self._mem_timestamps[(url, content_hash)] = datetime.now(tz=timezone.utc)
            return

        if self.backend == "redis":
            r = self._redis_client()
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            ttl = self.ttl_seconds
            if ttl:
                r.setex(self._redis_key(url, content_hash), ttl, payload_json)
            else:
                r.set(self._redis_key(url, content_hash), payload_json)
            now_iso = datetime.now(tz=timezone.utc).isoformat()
            latest_info = json.dumps({"content_hash": content_hash, "updated_at": now_iso})
            if ttl:
                r.setex(self._redis_latest_key(url), ttl, latest_info)
            else:
                r.set(self._redis_latest_key(url), latest_info)
            return

        if self.backend != "sqlite":
            return

        created_at = datetime.now(tz=timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO pages(url, content_hash, payload_json, created_at)
                VALUES(?,?,?,?)
                ON CONFLICT(url, content_hash) DO UPDATE SET payload_json=excluded.payload_json
                """,
                (url, content_hash, payload_json, created_at),
            )
            con.execute(
                """
                INSERT INTO url_last_hash(url, content_hash, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(url) DO UPDATE SET content_hash=excluded.content_hash, updated_at=excluded.updated_at
                """,
                (url, content_hash, created_at),
            )
            con.commit()

    def clear(self) -> None:
        if self.backend == "memory":
            assert self._mem_pages is not None and self._mem_last is not None
            assert self._mem_timestamps is not None
            self._mem_pages.clear()
            self._mem_last.clear()
            self._mem_timestamps.clear()
            return
        if self.backend == "redis":
            r = self._redis_client()
            for pattern in ("silkweb:page:*", "silkweb:page_latest:*"):
                for key in r.scan_iter(match=pattern):
                    r.delete(key)
            return
        if self.backend == "sqlite":
            # Avoid deleting the file on Windows (can be locked); clear tables instead.
            self._init_sqlite()
            with self._connect() as con:
                con.execute("DELETE FROM pages")
                con.execute("DELETE FROM url_last_hash")
                con.commit()

    def stats(self) -> dict[str, Any]:
        if self.backend == "memory":
            assert self._mem_pages is not None
            return {"backend": "memory", "entries": len(self._mem_pages)}
        if self.backend != "sqlite":
            return {"backend": self.backend, "entries": 0}
        with self._connect() as con:
            n = con.execute("SELECT COUNT(*) AS n FROM pages").fetchone()["n"]
        size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        return {"backend": "sqlite", "entries": int(n), "path": self.path, "size_bytes": size}
