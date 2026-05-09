from __future__ import annotations

import pytest
from pydantic import BaseModel

from silkweb.exceptions import SilkwebLLMError, SilkwebSchemaError
from silkweb.llm.constrained import ConstrainedDecoder, generate_json_constrained
from silkweb.llm.providers.base import LLMProvider


class M(BaseModel):
    a: int


class FakeProvider(LLMProvider):
    provider_name = "fake"

    def __init__(self, outputs: list[str]):
        super().__init__(model="fake")
        self.outputs = outputs
        self.calls = 0

    async def generate(self, messages, system=None, max_tokens=None, temperature=0.2):
        out = self.outputs[self.calls]
        self.calls += 1
        return out

    async def generate_json(
        self, messages, system=None, schema=None, max_tokens=None, temperature=0.2
    ):
        raise SilkwebLLMError(message="no json mode", provider="fake", model="fake")

    async def embed(self, texts):
        return [[0.0] for _ in texts]


@pytest.mark.anyio
async def test_strip_fences_and_retry_then_success() -> None:
    p = FakeProvider(outputs=["```json\n{bad}\n```", '```json\n{"a": 1}\n```'])
    out = await generate_json_constrained(p, [{"role": "user", "content": "x"}], M)
    assert out == {"a": 1}
    assert p.calls == 2


@pytest.mark.anyio
async def test_schema_validation_failure() -> None:
    p = FakeProvider(outputs=['{"a": "nope"}'])
    with pytest.raises(SilkwebSchemaError):
        await generate_json_constrained(p, [{"role": "user", "content": "x"}], M)


@pytest.mark.anyio
async def test_decoder_wrapper() -> None:
    p = FakeProvider(outputs=['{"a": 2}'])
    dec = ConstrainedDecoder(p)
    out = await dec.generate_json([{"role": "user", "content": "x"}], M)
    assert out == {"a": 2}
