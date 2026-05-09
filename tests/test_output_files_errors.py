from __future__ import annotations

import types

import pytest


def test_to_rows_type_error() -> None:
    from silkweb.output.files import to_json

    with pytest.raises(TypeError):
        to_json([object()], "out.json")  # type: ignore[arg-type]


def test_to_sqlite_rejects_invalid_table_name(tmp_path) -> None:
    from silkweb.output.files import to_sqlite

    with pytest.raises(ValueError, match="Invalid SQL table name"):
        to_sqlite([{"a": 1}], str(tmp_path / "x.db"), table='bad";--')


def test_to_parquet_requires_pyarrow(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from silkweb.output import files as f

    # Force to_dataframe() to return an object with to_parquet, but keep pyarrow missing.
    monkeypatch.setattr(
        f,
        "to_dataframe",
        lambda data, engine="pandas": types.SimpleNamespace(to_parquet=lambda *a, **k: None),
    )
    with pytest.raises(RuntimeError):
        f.to_parquet([{"a": 1}], str(tmp_path / "x.parquet"))
