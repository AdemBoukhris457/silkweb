from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from ..config import get_config

DedupBackend = Literal["sqlite", "memory"]


def _default_dedup_db_path() -> str:
    cfg = get_config()
    base = os.path.expanduser(cfg.cache_path)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "crawl_seen.sqlite")


@dataclass(slots=True)
class SeenSet:
    """
    URL deduplication set.

    Backends:
    - sqlite: persistent set backed by a single table (single persistent connection).
    - memory: in-process set.
    """

    backend: DedupBackend = "sqlite"
    sqlite_path: str | None = None

    _mem: set[str] | None = None
    _con: sqlite3.Connection | None = None

    def __post_init__(self) -> None:
        if self.backend == "memory":
            self._mem = set()
        else:
            self._init_sqlite()

    @property
    def path(self) -> str:
        return self.sqlite_path or _default_dedup_db_path()

    def _get_con(self) -> sqlite3.Connection:
        if self._con is None:
            dirname = os.path.dirname(self.path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            self._con = sqlite3.connect(self.path)
            self._con.row_factory = sqlite3.Row
            self._con.execute("PRAGMA journal_mode=WAL")
        return self._con

    def _init_sqlite(self) -> None:
        con = self._get_con()
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_urls (
                url TEXT PRIMARY KEY
            )
            """
        )
        con.commit()

    def add(self, url: str) -> bool:
        """
        Add url to seen-set.
        Returns True if it was newly added, False if already present.
        """
        u = (url or "").strip()
        if not u:
            return False
        if self.backend == "memory":
            assert self._mem is not None
            if u in self._mem:
                return False
            self._mem.add(u)
            return True

        con = self._get_con()
        cur = con.execute("INSERT OR IGNORE INTO seen_urls(url) VALUES(?)", (u,))
        con.commit()
        return cur.rowcount == 1

    def clear(self) -> None:
        if self.backend == "memory":
            assert self._mem is not None
            self._mem.clear()
            return
        self._init_sqlite()
        con = self._get_con()
        con.execute("DELETE FROM seen_urls")
        con.commit()

    def stats(self) -> dict[str, Any]:
        if self.backend == "memory":
            assert self._mem is not None
            return {"backend": "memory", "entries": len(self._mem)}
        self._init_sqlite()
        con = self._get_con()
        n = con.execute("SELECT COUNT(*) AS n FROM seen_urls").fetchone()["n"]
        size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        return {"backend": "sqlite", "entries": int(n), "path": self.path, "size_bytes": size}
