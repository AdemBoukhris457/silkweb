from __future__ import annotations

import gzip
import json
import sqlite3

import pytest
from pydantic import BaseModel

from silkweb.output.dataframe import to_dataframe
from silkweb.output.dataset import to_dataset
from silkweb.output.files import (
    to_csv,
    to_duckdb,
    to_json,
    to_jsonl,
    to_markdown,
    to_parquet,
    to_sqlite,
)


class Item(BaseModel):
    a: int
    b: str


def test_to_dataframe_auto_none_when_not_imported() -> None:
    # Don't import pandas/polars in this test: auto should return None.
    assert to_dataframe([{"a": 1}], engine="auto") is None


def test_to_json_and_jsonl_and_gz(tmp_path) -> None:
    data = [Item(a=1, b="x"), Item(a=2, b="y")]
    p_json = tmp_path / "out.json"
    p_json_gz = tmp_path / "out.json.gz"
    p_jsonl = tmp_path / "out.jsonl"

    to_json(data, str(p_json))
    assert json.loads(p_json.read_text(encoding="utf-8")) == [
        {"a": 1, "b": "x"},
        {"a": 2, "b": "y"},
    ]

    to_json(data, str(p_json_gz))
    with gzip.open(p_json_gz, "rt", encoding="utf-8") as f:
        assert json.loads(f.read()) == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]

    to_jsonl(data, str(p_jsonl))
    lines = p_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(x) for x in lines] == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]


def test_to_csv_and_markdown(tmp_path) -> None:
    data = [Item(a=1, b="x"), Item(a=2, b="y")]
    p_csv = tmp_path / "out.csv"
    p_md = tmp_path / "out.md"

    to_csv(data, str(p_csv))
    txt = p_csv.read_text(encoding="utf-8")
    assert "a,b" in txt
    assert "1,x" in txt

    to_markdown(data, str(p_md))
    md = p_md.read_text(encoding="utf-8")
    assert "| a | b |" in md
    assert "| 1 | x |" in md


def test_to_sqlite(tmp_path) -> None:
    data = [Item(a=1, b="x"), Item(a=2, b="y")]
    p = tmp_path / "out.sqlite"
    to_sqlite(data, str(p), table="items")

    con = sqlite3.connect(str(p))
    try:
        rows = con.execute('SELECT a, b FROM "items" ORDER BY a').fetchall()
        # values are JSON-serialized strings
        assert rows == [("1", '"x"'), ("2", '"y"')]
    finally:
        con.close()


def test_to_parquet_optional(tmp_path) -> None:
    data = [Item(a=1, b="x")]
    p = tmp_path / "out.parquet"
    try:
        import pandas as pd  # noqa: F401  # type: ignore
        import pyarrow  # noqa: F401  # type: ignore
    except Exception:
        pytest.skip("pandas+pyarrow not installed")

    to_parquet(data, str(p))
    assert p.exists()


def test_to_duckdb_optional(tmp_path) -> None:
    data = [Item(a=1, b="x"), Item(a=2, b="y")]
    p = tmp_path / "out.duckdb"
    try:
        import duckdb  # type: ignore
    except Exception:
        pytest.skip("duckdb not installed")

    to_duckdb(data, str(p), table="items")
    con = duckdb.connect(str(p))
    try:
        got = con.execute("select count(*) from items").fetchone()[0]
        assert got == 2
    finally:
        con.close()


def test_to_dataset_optional() -> None:
    try:
        import datasets  # noqa: F401  # type: ignore
    except Exception:
        pytest.skip("datasets not installed")

    ds = to_dataset([Item(a=1, b="x")])
    assert len(ds) == 1
    assert ds[0]["a"] == 1
