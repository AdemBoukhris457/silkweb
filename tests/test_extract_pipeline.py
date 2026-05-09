from __future__ import annotations

import pytest
from pydantic import BaseModel

from silkweb.llm.pipelines.clean import CleanedContent
from silkweb.llm.pipelines.extract import extract_data
from silkweb.llm.providers.base import LLMProvider


class Item(BaseModel):
    name: str
    price: float


class FakeProvider(LLMProvider):
    provider_name = "fake"

    def __init__(self, responses: list[dict]):
        super().__init__(model="fake")
        self.responses = responses
        self.calls = 0

    async def generate(self, messages, system=None, max_tokens=None, temperature=0.2):
        raise NotImplementedError

    async def generate_json(
        self, messages, system=None, schema=None, max_tokens=None, temperature=0.2
    ):
        out = self.responses[self.calls]
        self.calls += 1
        return out

    async def embed(self, texts):
        return [[0.0] for _ in texts]


@pytest.mark.anyio
async def test_single_call_extract_and_meta() -> None:
    cleaned = CleanedContent(
        flat_json='{"heading":"h","items":["Widget $10"]}', markdown="m", token_estimate=10
    )
    provider = FakeProvider(
        responses=[
            {
                "items": [
                    {"name": "Widget", "price": 10.0, "__xpath__": {"name": "/x", "price": "/y"}},
                ]
            }
        ]
    )
    out = await extract_data(cleaned, Item, "products", provider)
    assert out[0]["name"] == "Widget"
    assert "__silk_meta__" in out[0]
    assert "__xpath__" in out[0]


@pytest.mark.anyio
async def test_validation_retry_once() -> None:
    cleaned = CleanedContent(flat_json="{}", markdown="m", token_estimate=10)
    provider = FakeProvider(
        responses=[
            {
                "items": [
                    {"name": "Widget", "price": "nope", "__xpath__": {"name": "/x", "price": "/y"}}
                ]
            },
            {
                "items": [
                    {"name": "Widget", "price": 10.0, "__xpath__": {"name": "/x", "price": "/y"}}
                ]
            },
        ]
    )
    out = await extract_data(cleaned, Item, "products", provider)
    assert out[0]["price"] == 10.0
    assert provider.calls == 2


@pytest.mark.anyio
async def test_chunk_merge_union() -> None:
    cleaned = CleanedContent(flat_json="{}", markdown="m", token_estimate=10)

    def chunker(_cleaned, _prompt, _provider):
        return ["chunk1", "chunk2"]

    provider = FakeProvider(
        responses=[
            {"items": [{"name": "A", "price": 1.0, "__xpath__": {"name": "/a", "price": "/ap"}}]},
            {"items": [{"name": "B", "price": 2.0, "__xpath__": {"name": "/b", "price": "/bp"}}]},
        ]
    )
    out = await extract_data(cleaned, Item, "products", provider, chunker=chunker)
    names = sorted([x["name"] for x in out])
    assert names == ["A", "B"]
