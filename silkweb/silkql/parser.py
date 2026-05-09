from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from lark import Lark, Transformer
from lark.exceptions import UnexpectedInput, VisitError

ValidTypeCoercion = Literal["int", "float", "currency", "bool", "url", "iso_date", "list", "json"]

VALID_TYPE_COERCIONS: set[str] = {
    "int",
    "float",
    "currency",
    "bool",
    "url",
    "iso_date",
    "list",
    "json",
}

VALID_MODIFIERS: set[str] = {"optional", "unique"}


@dataclass(frozen=True, slots=True)
class FieldNode:
    name: str
    type_coercion: ValidTypeCoercion | None = None
    modifiers: list[str] | None = None


@dataclass(frozen=True, slots=True)
class CollectionNode:
    name: str
    is_list: bool
    children: list[Any]


@dataclass(frozen=True, slots=True)
class RootNode:
    children: list[Any]


_GRAMMAR = r"""
    start: root

    root: "{" stmt* "}"
    stmt: field | collection

    field: NAME args?
    collection: NAME list_marker? "{" stmt* "}"

    args: "(" _WS? arg ( _WS? "," _WS? arg )* _WS? ")"
    ?arg: NAME               -> bare_arg
        | "min_count" _WS? "=" _WS? SIGNED_INT  -> min_count_arg

    list_marker: "[" "]"

    NAME: /[A-Za-z_][A-Za-z0-9_]*/

    _WS: (" " | "\t")+

    %import common.SIGNED_INT
    %import common.WS

    %ignore WS
    %ignore /[\r\n]+/
"""


class _BuildAst(Transformer):
    def start(self, items: list[Any]) -> RootNode:
        return cast(RootNode, items[0])

    def root(self, items: list[Any]) -> RootNode:
        children = [x for x in items if isinstance(x, (FieldNode, CollectionNode))]
        return RootNode(children=children)

    def stmt(self, items: list[Any]) -> Any:
        return items[0] if items else None

    def field(self, items: list[Any]) -> FieldNode:
        name = str(items[0])
        args = items[1] if len(items) > 1 else {}
        type_coercion = cast(ValidTypeCoercion | None, args.get("type_coercion"))
        modifiers = cast(list[str] | None, args.get("modifiers"))
        return FieldNode(name=name, type_coercion=type_coercion, modifiers=modifiers)

    def collection(self, items: list[Any]) -> CollectionNode:
        name = str(items[0])
        is_list = False
        idx = 1
        if len(items) > 1 and items[1] == "[]":
            is_list = True
            idx = 2
        children = [x for x in items[idx:] if isinstance(x, (FieldNode, CollectionNode))]
        return CollectionNode(name=name, is_list=is_list, children=children)

    def list_marker(self, _items: list[Any]) -> str:
        return "[]"

    def args(self, items: list[Any]) -> dict[str, Any]:
        type_coercion: str | None = None
        modifiers: list[str] = []

        for arg in items:
            if isinstance(arg, tuple) and arg[0] == "min_count":
                n = int(arg[1])
                if n < 0:
                    raise ValueError("min_count must be >= 0")
                modifiers.append(f"min_count={n}")
                continue

            token = str(arg)
            if token in VALID_TYPE_COERCIONS:
                if type_coercion is not None:
                    raise ValueError("Multiple type coercions specified.")
                type_coercion = token
                continue

            if token in VALID_MODIFIERS:
                if token in modifiers:
                    raise ValueError(f"Duplicate modifier: {token}")
                modifiers.append(token)
                continue

            raise ValueError(f"Unknown coercion/modifier: {token}")

        out: dict[str, Any] = {"type_coercion": type_coercion, "modifiers": modifiers or None}
        return out

    def bare_arg(self, items: list[Any]) -> str:
        return str(items[0])

    def min_count_arg(self, items: list[Any]) -> tuple[str, int]:
        return ("min_count", int(items[-1]))

    def NAME(self, token) -> str:
        return str(token)


_PARSER = Lark(_GRAMMAR, start="start", parser="lalr", maybe_placeholders=False)


def parse_silkql(query: str) -> RootNode:
    """
    Parse a SilkQL string into an AST.

    Grammar supports:
    - Root block: `{ ... }`
    - Fields: `name(type_coercion, modifier, min_count=N)`
    - Collections/objects: `items[] { ... }` or `pagination { ... }`
    """
    try:
        tree = _PARSER.parse(query or "")
        return cast(RootNode, _BuildAst().transform(tree))
    except VisitError as e:
        # Transformer-raised ValueError is wrapped in VisitError.
        if isinstance(e.orig_exc, ValueError):
            raise ValueError(str(e.orig_exc)) from e
        raise
    except UnexpectedInput as e:
        raise ValueError(f"Invalid SilkQL syntax near: {e.get_context(query)}") from e
