from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import xxhash
from lxml import etree
from lxml import html as lxml_html

from ..config import get_config

SelectorSet = dict[str, list[str]]


def dom_skeleton_hash(html: str) -> str:
    """
    Hash of DOM "skeleton": tag names + nesting only (no attrs, no text).

    This is designed to be stable across content changes for the same template.
    """
    doc = lxml_html.fromstring(html or "<html/>")

    def walk(node: etree._Element, out: list[str]) -> None:
        out.append(f"<{node.tag}>")
        for child in node:
            if isinstance(child, etree._Element):
                walk(child, out)
        out.append(f"</{node.tag}>")

    parts: list[str] = []
    walk(doc, parts)
    skeleton = "".join(parts)
    return xxhash.xxh64(skeleton).hexdigest()


def _default_db_path() -> str:
    cfg = get_config()
    base = os.path.expanduser(cfg.cache_path)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "selectors.sqlite")


class SelectorCache:
    def __init__(self, path: str | None = None, ttl_seconds: int | None = None) -> None:
        self.path = path or _default_db_path()
        self.ttl_seconds = ttl_seconds
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS selector_cache (
                    domain TEXT NOT NULL,
                    skeleton_hash TEXT NOT NULL,
                    selector_set_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (domain, skeleton_hash)
                )
                """
            )
            con.commit()

    def get(self, domain: str, skeleton_hash: str) -> SelectorSet | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT selector_set_json, created_at FROM selector_cache WHERE domain=? AND skeleton_hash=?",
                (domain, skeleton_hash),
            ).fetchone()
            if row is None:
                return None
            if self.ttl_seconds is not None:
                try:
                    created = datetime.fromisoformat(str(row["created_at"]))
                    age = (datetime.now(tz=timezone.utc) - created).total_seconds()
                    if age > self.ttl_seconds:
                        return None
                except Exception:
                    pass
            data = json.loads(row["selector_set_json"])
            if not isinstance(data, dict):
                return None
            out: SelectorSet = {}
            for k, v in data.items():
                if (
                    isinstance(k, str)
                    and isinstance(v, list)
                    and all(isinstance(x, str) for x in v)
                ):
                    out[k] = v
            return out

    def set(self, domain: str, skeleton_hash: str, selector_set: SelectorSet) -> None:
        payload = json.dumps(selector_set, ensure_ascii=False, sort_keys=True)
        created_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO selector_cache(domain, skeleton_hash, selector_set_json, created_at)
                VALUES(?,?,?,?)
                ON CONFLICT(domain, skeleton_hash)
                DO UPDATE SET selector_set_json=excluded.selector_set_json, created_at=excluded.created_at
                """,
                (domain, skeleton_hash, payload, created_at),
            )
            con.commit()

    def invalidate(self, domain: str, skeleton_hash: str) -> None:
        with self._connect() as con:
            con.execute(
                "DELETE FROM selector_cache WHERE domain=? AND skeleton_hash=?",
                (domain, skeleton_hash),
            )
            con.commit()

    def clear(self, domain: str | None = None) -> None:
        with self._connect() as con:
            if domain:
                con.execute("DELETE FROM selector_cache WHERE domain=?", (domain,))
            else:
                con.execute("DELETE FROM selector_cache")
            con.commit()

    def stats(self) -> dict[str, Any]:
        with self._connect() as con:
            total = con.execute("SELECT COUNT(*) AS n FROM selector_cache").fetchone()["n"]
            domains = con.execute(
                "SELECT COUNT(DISTINCT domain) AS n FROM selector_cache"
            ).fetchone()["n"]
            return {"entries": int(total), "domains": int(domains), "path": self.path}
