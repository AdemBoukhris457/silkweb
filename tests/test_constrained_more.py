from __future__ import annotations

import pytest
from pydantic import BaseModel

from silkweb.exceptions import SilkwebLLMError, SilkwebSchemaError
from silkweb.llm.constrained import generate_json_constrained, strip_code_fences
from silkweb.llm.providers.base import LLMProvider, Message


class M(BaseModel):
    a: int


class FakeProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(model="fake")
        self.calls = 0

    async def generate(
        self, messages: list[Message], system=None, max_tokens=None, temperature=0.2
    ) -> str:  # type: ignore[override]
        self.calls += 1
        return '```json\n{"a": 1}\n```'

    async def generate_json(
        self, messages: list[Message], system=None, schema=None, max_tokens=None, temperature=0.2
    ):  # type: ignore[override]
        raise SilkwebLLMError(
            message="no json mode", provider="fake", model="fake", raw_output=None, context={}
        )

    async def embed(self, texts):  # type: ignore[override]
        return [[0.0] * 3 for _ in texts]


@pytest.mark.anyio
async def test_strip_code_fences_and_strategy3_success() -> None:
    assert strip_code_fences('```json\n{"a":1}\n```') == '{"a":1}'
    prov = FakeProvider()
    out = await generate_json_constrained(
        prov, messages=[{"role": "user", "content": "x"}], pydantic_model=M
    )
    assert out == {"a": 1}
    assert prov.calls == 1


@pytest.mark.anyio
async def test_schema_mismatch_raises_no_retry() -> None:
    class BadProvider(FakeProvider):
        async def generate(
            self, messages: list[Message], system=None, max_tokens=None, temperature=0.2
        ) -> str:  # type: ignore[override]
            self.calls += 1
            return '{"a": "not_int"}'

    prov = BadProvider()
    with pytest.raises(SilkwebSchemaError):
        await generate_json_constrained(
            prov, messages=[{"role": "user", "content": "x"}], pydantic_model=M
        )
    assert prov.calls == 1
