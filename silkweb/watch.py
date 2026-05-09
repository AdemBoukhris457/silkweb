from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel

from .config import get_config

ChangeType = Literal["added", "removed", "modified"]


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    record_id: str
    old_value: Any
    new_value: Any
    change_type: ChangeType


@dataclass(frozen=True, slots=True)
class ChangeEvent:
    url: str
    checked_at: datetime
    changed: bool
    changes: list[FieldChange]


def _default_watch_db_path() -> str:
    cfg = get_config()
    base = os.path.expanduser(cfg.cache_path)
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "watch.sqlite")


def _to_jsonable_models(items: list[BaseModel]) -> list[dict[str, Any]]:
    return [it.model_dump() for it in items]


def _record_id(obj: dict[str, Any], index: int) -> str:
    for key in ("id", "uuid", "slug", "url"):
        v = obj.get(key)
        if v is not None and str(v).strip():
            return str(v)
    return str(index)


def _diff(old: list[dict[str, Any]] | None, new: list[dict[str, Any]]) -> list[FieldChange]:
    old = old or []
    old_by_id: dict[str, dict[str, Any]] = {_record_id(o, i): o for i, o in enumerate(old)}
    new_by_id: dict[str, dict[str, Any]] = {_record_id(n, i): n for i, n in enumerate(new)}

    changes: list[FieldChange] = []
    all_ids = set(old_by_id) | set(new_by_id)
    for rid in sorted(all_ids):
        o = old_by_id.get(rid)
        n = new_by_id.get(rid)
        if o is None and n is not None:
            for field, val in n.items():
                changes.append(
                    FieldChange(
                        field=str(field),
                        record_id=rid,
                        old_value=None,
                        new_value=val,
                        change_type="added",
                    )
                )
            continue
        if o is not None and n is None:
            for field, val in o.items():
                changes.append(
                    FieldChange(
                        field=str(field),
                        record_id=rid,
                        old_value=val,
                        new_value=None,
                        change_type="removed",
                    )
                )
            continue
        assert o is not None and n is not None
        keys = set(o.keys()) | set(n.keys())
        for k in sorted(keys):
            if k == "__silk_meta__":
                continue
            ov = o.get(k)
            nv = n.get(k)
            if ov != nv:
                changes.append(
                    FieldChange(
                        field=str(k),
                        record_id=rid,
                        old_value=ov,
                        new_value=nv,
                        change_type="modified",
                    )
                )

    return changes


class Watcher:
    def __init__(self, sqlite_path: str | None = None) -> None:
        self.sqlite_path = sqlite_path or _default_watch_db_path()
        os.makedirs(os.path.dirname(self.sqlite_path), exist_ok=True)
        self._init_db()
        self._watches: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.sqlite_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS watch_state (
                    url TEXT PRIMARY KEY,
                    last_json TEXT,
                    last_checked_at TEXT
                )
                """
            )
            con.commit()

    def add(
        self,
        url: str,
        schema: type[BaseModel],
        interval: float,
        on_change: Callable[[ChangeEvent], Awaitable[None]],
        on_error: Callable[[str, Exception], Awaitable[None]] | None,
        *,
        prompt: str | None = None,
        notify_on_no_change: bool = False,
    ) -> None:
        if prompt is None:
            fields = ", ".join(schema.model_fields.keys())
            prompt = f"Extract {fields} from the page"
        self._watches[url] = {
            "url": url,
            "schema": schema,
            "interval": float(interval),
            "on_change": on_change,
            "on_error": on_error,
            "prompt": prompt,
            "notify_on_no_change": bool(notify_on_no_change),
            "next_run": 0.0,
        }

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    def _load_state(self, url: str) -> tuple[list[dict[str, Any]] | None, datetime | None]:
        with self._connect() as con:
            row = con.execute(
                "SELECT last_json, last_checked_at FROM watch_state WHERE url=?",
                (url,),
            ).fetchone()
            if row is None:
                return None, None
            last_json = row["last_json"]
            last_checked_at = row["last_checked_at"]
            data = json.loads(last_json) if isinstance(last_json, str) and last_json else None
            dt = None
            if isinstance(last_checked_at, str) and last_checked_at:
                try:
                    dt = datetime.fromisoformat(last_checked_at)
                except Exception:
                    dt = None
            return data if isinstance(data, list) else None, dt

    def _save_state(self, url: str, items: list[dict[str, Any]], checked_at: datetime) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO watch_state(url, last_json, last_checked_at)
                VALUES(?,?,?)
                ON CONFLICT(url) DO UPDATE SET last_json=excluded.last_json, last_checked_at=excluded.last_checked_at
                """,
                (
                    url,
                    json.dumps(items, ensure_ascii=False, sort_keys=True, default=str),
                    checked_at.isoformat(),
                ),
            )
            con.commit()

    async def _tick(
        self,
        url: str,
        schema: type[BaseModel],
        prompt: str,
        on_change,
        on_error,
        notify_on_no_change: bool,
    ) -> None:
        checked_at = datetime.now(tz=timezone.utc)
        try:
            import silkweb as _silkweb

            items: list[BaseModel] = await _silkweb.async_extract(url, schema, prompt=prompt)
            new = _to_jsonable_models(items)
            old, _ = self._load_state(url)
            changes = _diff(old, new)
            changed = bool(changes)
            event = ChangeEvent(url=url, checked_at=checked_at, changed=changed, changes=changes)
            self._save_state(url, new, checked_at)
            if changed or notify_on_no_change:
                await on_change(event)
        except Exception as e:
            if on_error:
                await on_error(url, e)

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            now = asyncio.get_running_loop().time()
            due: list[dict[str, Any]] = []
            for w in self._watches.values():
                if w["next_run"] <= now:
                    due.append(w)

            tasks: list[asyncio.Task[None]] = []
            for w in due:
                w["next_run"] = now + float(w["interval"])
                tasks.append(
                    asyncio.create_task(
                        self._tick(
                            w["url"],
                            w["schema"],
                            w["prompt"],
                            w["on_change"],
                            w["on_error"],
                            w["notify_on_no_change"],
                        )
                    )
                )

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            await asyncio.sleep(0.05)
