from __future__ import annotations

import csv
import gzip
import json
import os
import re
import sqlite3
from typing import IO, Any

from pydantic import BaseModel

from .dataframe import to_dataframe

_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_sql_table(name: str) -> str:
    """SQLite / DuckDB table identifier (alphanumeric + underscore only)."""
    n = (name or "").strip()
    if not _SQL_IDENT.match(n):
        raise ValueError(f"Invalid SQL table name {name!r}: use letters, digits, underscore only.")
    return n


def _to_rows(data: list[Any]) -> list[dict[str, Any]]:
    if data is None:
        return []
    rows: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, BaseModel):
            rows.append(item.model_dump())
        elif isinstance(item, dict):
            rows.append(item)
        else:
            raise TypeError("Expected list[dict] or list[BaseModel].")
    return rows


def _open_text(path: str) -> IO[str]:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if path.endswith(".gz"):
        return gzip.open(path, mode="wt", encoding="utf-8", newline="")  # type: ignore[return-value]
    return open(path, mode="w", encoding="utf-8", newline="")


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def to_json(data: list[Any] | None, output_path: str) -> None:
    rows = _to_rows(data)
    with _open_text(output_path) as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=_jsonable)
        f.write("\n")


def to_jsonl(data: list[Any], output_path: str) -> None:
    rows = _to_rows(data)
    with _open_text(output_path) as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=_jsonable) + "\n")


def to_csv(data: list[Any] | None, output_path: str) -> None:
    rows = _to_rows(data)
    fieldnames = sorted({k for r in rows for k in r})
    with _open_text(output_path) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: _jsonable(r.get(k)) for k in fieldnames})


def to_parquet(data: list[Any] | None, output_path: str) -> None:
    # Prefer pandas if present; otherwise try importing it.
    df = to_dataframe(data, engine="pandas")
    try:
        import pyarrow  # noqa: F401  # type: ignore
    except Exception as e:
        raise RuntimeError("`pyarrow` is required for Parquet output.") from e

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df.to_parquet(output_path, index=False)  # type: ignore[attr-defined]


def to_duckdb(data: list[Any] | None, output_path: str, *, table: str = "data") -> None:
    try:
        import duckdb  # type: ignore
    except Exception as e:
        raise RuntimeError("`duckdb` is required for DuckDB output.") from e

    rows = _to_rows(data)
    safe_table = _safe_sql_table(table)
    df = to_dataframe(rows, engine="pandas")
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    con = duckdb.connect(output_path)
    try:
        con.register("_df", df)
        con.execute(f'CREATE OR REPLACE TABLE "{safe_table}" AS SELECT * FROM _df')
    finally:
        con.close()


def to_sqlite(data: list[Any] | None, output_path: str, *, table: str = "data") -> None:
    rows = _to_rows(data)
    safe_table = _safe_sql_table(table)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    con = sqlite3.connect(output_path)
    try:
        keys = sorted({k for r in rows for k in r})
        cols = ", ".join(f'"{k}" TEXT' for k in keys) or '"_empty" TEXT'
        con.execute(f'CREATE TABLE IF NOT EXISTS "{safe_table}" ({cols})')
        if keys:
            placeholders = ", ".join("?" for _ in keys)
            col_list = ", ".join(f'"{k}"' for k in keys)
            con.executemany(
                f'INSERT INTO "{safe_table}" ({col_list}) VALUES ({placeholders})',
                [
                    tuple(json.dumps(r.get(k), ensure_ascii=False, default=_jsonable) for k in keys)
                    for r in rows
                ],
            )
        con.commit()
    finally:
        con.close()


def to_markdown(data: list[Any] | None, output_path: str) -> None:
    rows = _to_rows(data)
    keys = sorted({k for r in rows for k in r})

    def esc(v: Any) -> str:
        return str(_jsonable(v)).replace("|", "\\|")

    lines: list[str] = []
    lines.append("| " + " | ".join(keys) + " |")
    lines.append("| " + " | ".join("---" for _ in keys) + " |")
    for r in rows:
        lines.append("| " + " | ".join(esc(r.get(k)) for k in keys) + " |")
    with _open_text(output_path) as f:
        f.write("\n".join(lines) + "\n")
