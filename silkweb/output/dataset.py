from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def to_dataset(data: Any):
    """
    Convert list[dict] or list[pydantic.BaseModel] to a HuggingFace `datasets.Dataset`.
    Lazy import to avoid hard dependency.
    """
    try:
        from datasets import Dataset  # type: ignore
    except Exception as e:
        raise RuntimeError("`datasets` is required for Dataset output.") from e

    if data is None:
        return Dataset.from_list([])
    if isinstance(data, list):
        if not data:
            return Dataset.from_list([])
        first = data[0]
        if isinstance(first, BaseModel):
            return Dataset.from_list([x.model_dump() for x in data if isinstance(x, BaseModel)])
        if isinstance(first, dict):
            return Dataset.from_list([x for x in data if isinstance(x, dict)])
    raise TypeError("Expected list[dict] or list[BaseModel].")
