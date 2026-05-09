from __future__ import annotations

import pytest

from silkweb.silkql.parser import CollectionNode, FieldNode, RootNode, parse_silkql


def _names(children):
    return [c.name for c in children]


def test_parse_basic_fields() -> None:
    ast = parse_silkql(
        """
        {
            name
            price(currency, optional)
            tags(list, min_count=1)
            id(int, unique)
        }
        """
    )
    assert isinstance(ast, RootNode)
    assert _names(ast.children) == ["name", "price", "tags", "id"]

    price = ast.children[1]
    assert isinstance(price, FieldNode)
    assert price.type_coercion == "currency"
    assert price.modifiers == ["optional"]

    tags = ast.children[2]
    assert isinstance(tags, FieldNode)
    assert tags.type_coercion == "list"
    assert tags.modifiers == ["min_count=1"]

    fid = ast.children[3]
    assert isinstance(fid, FieldNode)
    assert fid.type_coercion == "int"
    assert fid.modifiers == ["unique"]


def test_parse_collections_and_nesting() -> None:
    ast = parse_silkql(
        """
        {
          products[] {
            name
            price(currency)
          }
          pagination {
            next_page_url(url, optional)
          }
        }
        """
    )
    assert _names(ast.children) == ["products", "pagination"]

    products = ast.children[0]
    assert isinstance(products, CollectionNode)
    assert products.is_list is True
    assert _names(products.children) == ["name", "price"]

    pagination = ast.children[1]
    assert isinstance(pagination, CollectionNode)
    assert pagination.is_list is False
    assert _names(pagination.children) == ["next_page_url"]
    np = pagination.children[0]
    assert isinstance(np, FieldNode)
    assert np.type_coercion == "url"
    assert np.modifiers == ["optional"]


def test_parse_empty_root() -> None:
    ast = parse_silkql("{ }")
    assert isinstance(ast, RootNode)
    assert ast.children == []


@pytest.mark.parametrize(
    "q",
    [
        "name",  # missing braces
        "{ name ",  # missing close
        "{ products[] name }",  # missing inner braces
        "{ name( ) }",  # empty args not allowed by grammar
    ],
)
def test_invalid_syntax_raises_value_error(q: str) -> None:
    with pytest.raises(ValueError):
        parse_silkql(q)


def test_invalid_type_coercion_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown coercion/modifier"):
        parse_silkql("{ name(str) }")


def test_multiple_type_coercions_rejected() -> None:
    with pytest.raises(ValueError, match="Multiple type coercions"):
        parse_silkql("{ price(int, float) }")


def test_unknown_modifier_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown coercion/modifier"):
        parse_silkql("{ name(required) }")


def test_min_count_requires_int() -> None:
    with pytest.raises(ValueError):
        parse_silkql("{ tags(list, min_count=) }")


def test_min_count_non_negative() -> None:
    with pytest.raises(ValueError, match="min_count must be"):
        parse_silkql("{ tags(list, min_count=-1) }")


def test_duplicate_modifier_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate modifier"):
        parse_silkql("{ name(optional, optional) }")
