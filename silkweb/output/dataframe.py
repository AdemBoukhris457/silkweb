from __future__ import annotations

import sys
from typing import Any, Literal

from pydantic import BaseModel

Engine = Literal["auto", "pandas", "polars", "none"]


def _to_rows(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        if not data:
            return []
        first = data[0]
        if isinstance(first, BaseModel):
            return [x.model_dump() for x in data if isinstance(x, BaseModel)]
        if isinstance(first, dict):
            return [x for x in data if isinstance(x, dict)]
    raise TypeError("Expected list[dict] or list[BaseModel].")


def _detect_engine() -> Literal["pandas", "polars", "none"]:
    # Only consider engines already imported by the caller.
    if "pandas" in sys.modules:
        return "pandas"
    if "polars" in sys.modules:
        return "polars"
    return "none"


def to_dataframe(data: Any, engine: Engine = "auto"):
    """
    Convert list[dict] or list[pydantic.BaseModel] to a DataFrame.

    - engine="auto": selects pandas/polars ONLY if already imported (sys.modules)
    - engine="pandas"/"polars": imports the requested library
    - engine="none": returns None
    """
    rows = _to_rows(data)
    if engine == "auto":
        engine = _detect_engine()

    if engine == "none":
        return None

    if engine == "pandas":
        import pandas as pd  # type: ignore

        return pd.DataFrame(rows)

    if engine == "polars":
        import polars as pl  # type: ignore

        return pl.DataFrame(rows)

    raise ValueError(f"Unknown engine: {engine}")
