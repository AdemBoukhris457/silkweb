from __future__ import annotations

import pytest
from pydantic import ValidationError

from silkweb.silkql.compiler import compile_query


def test_compiler_type_coercions_and_modifiers() -> None:
    Model = compile_query(
        """
        {
          price(currency)
          in_stock(bool, optional)
          tags(list, min_count=2)
        }
        """
    )

    obj = Model.model_validate({"price": "$1,234.50", "in_stock": "true", "tags": ["a", "b"]})
    assert abs(obj.price - 1234.5) < 1e-6
    assert obj.in_stock is True
    assert obj.tags == ["a", "b"]

    # min_count enforcement
    with pytest.raises(ValidationError):
        Model.model_validate({"price": "$1.00", "tags": ["only-one"]})


def test_str_field_json_null_coerces_to_empty_not_text_none() -> None:
    """JSON null / Python None for a plain SilkQL string must not become the literal 'None'."""
    Model = compile_query("{ title }")
    obj = Model.model_validate({"title": None})
    assert obj.title == ""
