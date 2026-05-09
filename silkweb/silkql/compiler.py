from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, create_model

from .parser import CollectionNode, FieldNode, RootNode, parse_silkql


def _strip(s: Any) -> str:
    """Coerce SilkQL string fields. JSON null / Python None maps to empty string (not the text None)."""
    if s is None:
        return ""
    return str(s).strip()


_CURRENCY_RE = re.compile(r"[^0-9.\-]+")


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    s = _strip(v)
    s = s.replace(",", "")
    if not s:
        return None
    return int(float(s))


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    s = _strip(v)
    s = s.replace(",", "")
    if not s:
        return None
    return float(s)


def _coerce_currency(v: Any) -> float | None:
    if v is None:
        return None
    s = _strip(v)
    if not s:
        return None
    s = s.replace(",", "")
    s = _CURRENCY_RE.sub("", s)
    if not s:
        return None
    return float(s)


def _coerce_bool(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = _strip(v).lower()
    if s in {"1", "true", "yes", "y", "in stock", "available"}:
        return True
    if s in {"0", "false", "no", "n", "out of stock", "unavailable"}:
        return False
    # fall back: non-empty string -> True
    return bool(s)


def _coerce_url(v: Any) -> str | None:
    if v is None:
        return None
    s = _strip(v)
    return s or None


def _coerce_iso_date(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = _strip(v)
    if not s:
        return None
    # Try ISO first
    with_iso = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(with_iso)
    except Exception:
        pass
    # Common doc example: "Apr 30, 2025"
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    raise ValueError(f"Could not parse iso_date: {s}")


def _coerce_list(v: Any) -> list[str] | None:
    if v is None:
        return None
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = _strip(v)
    if not s:
        return []
    parts = [p.strip() for p in re.split(r"[,;\n]+", s) if p.strip()]
    return parts


def _coerce_json(v: Any) -> dict[str, Any] | list[Any] | None:
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    s = _strip(v)
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception as e:
        raise ValueError("Invalid JSON") from e


def _type_and_coercer(type_coercion: str | None) -> tuple[Any, Callable[[Any], Any] | None]:
    if type_coercion is None:
        return (str, _strip)
    if type_coercion == "int":
        return (int, _coerce_int)
    if type_coercion == "float":
        return (float, _coerce_float)
    if type_coercion == "currency":
        return (float, _coerce_currency)
    if type_coercion == "bool":
        return (bool, _coerce_bool)
    if type_coercion == "url":
        return (str, _coerce_url)
    if type_coercion == "iso_date":
        return (datetime, _coerce_iso_date)
    if type_coercion == "list":
        return (list[str], _coerce_list)
    if type_coercion == "json":
        return (Any, _coerce_json)
    raise ValueError(f"Unknown type coercion: {type_coercion}")


def _apply_modifiers(field_type: Any, modifiers: list[str] | None) -> Any:
    if not modifiers:
        return field_type

    min_count: int | None = None
    for m in modifiers:
        if m.startswith("min_count="):
            try:
                min_count = int(m.split("=", 1)[1])
            except Exception:
                min_count = None

    if min_count is None:
        return field_type

    def _check_min_count(v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, list) and len(v) < min_count:
            raise ValueError(f"min_count={min_count} violated")
        return v

    return Annotated[field_type, AfterValidator(_check_min_count)]


def _field_def(node: FieldNode) -> tuple[Any, Any]:
    base_type, coercer = _type_and_coercer(node.type_coercion)
    annotated_type = Annotated[base_type, BeforeValidator(coercer)] if coercer else base_type
    final_type = _apply_modifiers(annotated_type, node.modifiers)

    optional = bool(node.modifiers and "optional" in node.modifiers)
    if optional:
        return (final_type | None, None)
    return (final_type, ...)


def _model_name(prefix: str, name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "Model"
    return f"{prefix}_{safe}"


def _compile_collection(node: CollectionNode, prefix: str) -> tuple[str, Any, Any]:
    model = _compile_block(node.children, _model_name(prefix, node.name))
    if node.is_list:
        return (node.name, list[model], ...)
    return (node.name, model, ...)


def _compile_block(children: list[Any], name: str) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for ch in children:
        if isinstance(ch, FieldNode):
            fields[ch.name] = _field_def(ch)
        elif isinstance(ch, CollectionNode):
            fname, ftype, default = _compile_collection(ch, name)
            fields[fname] = (ftype, default)
        else:
            raise TypeError(f"Unknown AST node: {ch!r}")
    return create_model(name, __base__=BaseModel, **fields)  # type: ignore[call-arg]


def compile_query(silkql_string: str) -> type[BaseModel]:
    """
    Compile a SilkQL string into a Pydantic v2 model.
    """
    ast = parse_silkql(silkql_string)
    if not isinstance(ast, RootNode):
        raise TypeError("Expected RootNode")
    return _compile_block(ast.children, "SilkQLRoot")
