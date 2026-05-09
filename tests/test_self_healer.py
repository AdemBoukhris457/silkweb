from __future__ import annotations

from pydantic import BaseModel

from silkweb.llm.pipelines.heal import SelfHealer


class Item(BaseModel):
    name: str
    price: float | None = None


def test_should_heal_empty_results() -> None:
    h = SelfHealer()
    assert h.should_heal([], Item) is True


def test_should_heal_missing_required_field_none() -> None:
    h = SelfHealer()
    assert h.should_heal([{"name": None, "price": 1.0}], Item) is True


def test_should_not_heal_valid_results() -> None:
    h = SelfHealer()
    assert h.should_heal([{"name": "Widget", "price": 1.0}], Item) is False


def test_validation_fn_can_trigger_heal() -> None:
    def v(results, _schema):
        return False

    h = SelfHealer(validation_fn=v)
    assert h.should_heal([{"name": "Widget"}], Item) is True
