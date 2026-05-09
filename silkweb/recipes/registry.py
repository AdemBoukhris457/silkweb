from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class Recipe:
    name: str
    description: str
    url_pattern: str
    silkql_query: str | None
    schema: str | None
    fetch_tier: str | int
    wait_for: str | None
    notes: str | None


@dataclass(frozen=True, slots=True)
class RecipeSummary:
    name: str
    description: str
    url_pattern: str


def _recipes_dir() -> str:
    return os.path.dirname(__file__)


def _load_yaml_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        obj = yaml.safe_load(f) or {}
    if not isinstance(obj, dict):
        raise ValueError(f"Recipe YAML must be a mapping: {path}")
    return obj


def _normalize_recipe(d: dict[str, Any], *, path: str) -> Recipe:
    name = str(d.get("name") or "").strip()
    if not name:
        raise ValueError(f"Recipe missing `name`: {path}")
    description = str(d.get("description") or "").strip()
    url_pattern = str(d.get("url_pattern") or "").strip()
    if not url_pattern:
        raise ValueError(f"Recipe missing `url_pattern`: {path}")
    silkql_query = d.get("silkql_query")
    silkql_query = str(silkql_query).strip() if silkql_query is not None else None
    schema = d.get("schema")
    schema = str(schema).strip() if schema is not None else None
    if not silkql_query and not schema:
        raise ValueError(f"Recipe must define `silkql_query` or `schema`: {path}")
    fetch_tier: str | int = d.get("fetch_tier", "auto")
    wait_for = d.get("wait_for")
    wait_for = str(wait_for).strip() if wait_for is not None else None
    notes = d.get("notes")
    notes = str(notes).strip() if notes is not None else None
    return Recipe(
        name=name,
        description=description,
        url_pattern=url_pattern,
        silkql_query=silkql_query,
        schema=schema,
        fetch_tier=fetch_tier,
        wait_for=wait_for,
        notes=notes,
    )


class RecipeRegistry:
    def __init__(self, *, directory: str | None = None) -> None:
        self.directory = directory or _recipes_dir()
        self._recipes: dict[str, Recipe] = {}
        self.reload()

    def reload(self) -> None:
        recipes: dict[str, Recipe] = {}
        for fn in sorted(os.listdir(self.directory)):
            if not fn.endswith(".yaml") and not fn.endswith(".yml"):
                continue
            if fn.startswith("_"):
                continue
            path = os.path.join(self.directory, fn)
            try:
                rec = _normalize_recipe(_load_yaml_file(path), path=path)
            except Exception as e:
                warnings.warn(f"Skipping invalid recipe {path}: {e}", stacklevel=2)
                continue
            recipes[rec.name] = rec
        self._recipes = recipes

    def list(self) -> list[RecipeSummary]:
        return [
            RecipeSummary(name=r.name, description=r.description, url_pattern=r.url_pattern)
            for r in sorted(self._recipes.values(), key=lambda r: r.name)
        ]

    def get(self, name: str) -> Recipe:
        if name not in self._recipes:
            raise KeyError(f"Unknown recipe: {name}")
        return self._recipes[name]

    def show(self, name: str) -> str:
        r = self.get(name)
        parts: list[str] = []
        parts.append(f"Name: {r.name}")
        if r.description:
            parts.append(f"Description: {r.description}")
        parts.append(f"URL pattern: {r.url_pattern}")
        parts.append(f"Fetch tier: {r.fetch_tier}")
        if r.wait_for:
            parts.append(f"Wait-for selector: {r.wait_for}")
        if r.notes:
            parts.append("")
            parts.append("Notes:")
            parts.append(r.notes)
        parts.append("")
        if r.silkql_query:
            parts.append("SilkQL:")
            parts.append(r.silkql_query.strip())
        if r.schema:
            parts.append("Schema:")
            parts.append(r.schema.strip())
        return "\n".join(parts).strip() + "\n"

    def run(self, name: str, url: str, *, output: str | None = None):
        r = self.get(name)
        if not re.search(r.url_pattern, url):
            raise ValueError(f"URL does not match recipe url_pattern: {r.url_pattern}")

        import silkweb as sw

        # Fetch kwargs: tier + optional wait_for (playwright tiers)
        fetch_kwargs: dict[str, Any] = {}
        fetch_kwargs["tier"] = r.fetch_tier
        if r.wait_for:
            fetch_kwargs["wait_for"] = r.wait_for

        if r.silkql_query:
            result = sw.query(url, r.silkql_query, **fetch_kwargs)
            data = result.data
        else:
            # `schema` can be either a python file path containing Schema, or a fully qualified import path.
            schema_obj = _load_schema_ref(r.schema or "")
            data = sw.extract(
                url, schema_obj, prompt=r.description or "extract items", **fetch_kwargs
            )

        if output:
            _write_output(data, output)
        return data


def _load_schema_ref(ref: str):
    from importlib import import_module
    from importlib.machinery import SourceFileLoader
    from types import ModuleType

    from pydantic import BaseModel

    ref = (ref or "").strip()
    if not ref:
        raise ValueError("schema ref is empty")

    if os.path.exists(ref):
        module_name = f"_silkweb_recipe_schema_{abs(hash(os.path.abspath(ref)))}"
        mod = ModuleType(module_name)
        loader = SourceFileLoader(module_name, ref)
        loader.exec_module(mod)
        for cand in ("Schema", "schema", "MODEL", "model"):
            if hasattr(mod, cand):
                obj = getattr(mod, cand)
                if isinstance(obj, type) and issubclass(obj, BaseModel):
                    return obj
                if isinstance(obj, BaseModel):
                    return obj.__class__
        raise ValueError("Schema file must define a Pydantic model named `Schema` (recommended).")

    # import path: "package.module:Schema" or "package.module.Schema"
    mod_path = ref
    attr = "Schema"
    if ":" in ref:
        mod_path, attr = ref.split(":", 1)
    elif "." in ref:
        # allow full dotted, last segment is attribute
        mod_path, attr = ref.rsplit(".", 1)
    mod = import_module(mod_path)
    obj = getattr(mod, attr)
    return obj


def _write_output(data: Any, output: str) -> None:
    # Defer to silkweb.output.files based on suffix.
    from silkweb.output.files import (
        to_csv,
        to_duckdb,
        to_json,
        to_jsonl,
        to_markdown,
        to_parquet,
        to_sqlite,
    )

    # Normalize into list for writers (extract list, single model, or SilkQL QueryResult.data).
    rows = data
    inner = getattr(data, "data", None)
    if isinstance(inner, list):
        rows = list(inner)
    elif hasattr(data, "model_dump"):
        rows = [data]
    if not isinstance(rows, list):
        rows = [rows]

    out = output.lower()
    if out.endswith(".json") or out.endswith(".json.gz"):
        to_json(rows, output)
        return
    if out.endswith(".jsonl") or out.endswith(".jsonl.gz"):
        to_jsonl(rows, output)
        return
    if out.endswith(".csv") or out.endswith(".csv.gz"):
        to_csv(rows, output)
        return
    if out.endswith(".parquet"):
        to_parquet(rows, output)
        return
    if out.endswith(".duckdb"):
        to_duckdb(rows, output)
        return
    if out.endswith(".sqlite") or out.endswith(".db"):
        to_sqlite(rows, output)
        return
    if out.endswith(".md") or out.endswith(".md.gz"):
        to_markdown(rows, output)
        return
    # Default to JSON.
    to_json(rows, output)


recipes = RecipeRegistry()
