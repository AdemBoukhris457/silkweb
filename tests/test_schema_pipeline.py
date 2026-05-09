from __future__ import annotations

import pytest
from pydantic import BaseModel

from silkweb.llm.pipelines.clean import clean_html
from silkweb.llm.pipelines.schema import infer_schema, synthesize_schema
from silkweb.llm.providers.base import LLMProvider
from silkweb.parse.page import SilkPage

HTML = """
<html>
  <head><title>Store</title></head>
  <body>
    <h1>Products</h1>
    <div class="product"><span class="name">Widget</span><span class="price">$10</span></div>
    <div class="product"><span class="name">Gadget</span><span class="price">$20</span></div>
  </body>
</html>
""".strip()


class FakeSchemaProvider(LLMProvider):
    provider_name = "fake"

    def __init__(self, schema: dict):
        super().__init__(model="fake")
        self.schema = schema
        self.calls = 0

    async def generate(self, messages, system=None, max_tokens=None, temperature=0.2):
        raise NotImplementedError

    async def generate_json(
        self, messages, system=None, schema=None, max_tokens=None, temperature=0.2
    ):
        self.calls += 1
        return {"json_schema": self.schema}

    async def embed(self, texts):
        return [[0.0] for _ in texts]


@pytest.mark.anyio
async def test_synthesize_schema_creates_model_and_caches() -> None:
    schema = {
        "title": "Product",
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "price": {"type": "number"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "price"],
    }
    provider = FakeSchemaProvider(schema)
    cleaned = await clean_html(HTML, provider=provider, strategy="trafilatura")

    Model1 = await synthesize_schema(cleaned, "product name, price, tags", provider)
    Model2 = await synthesize_schema(cleaned, "product name, price, tags", provider)
    assert Model1 is Model2
    assert provider.calls == 1

    obj = Model1.model_validate({"name": "x", "price": 1.2, "tags": ["a"]})
    assert obj.name == "x"


@pytest.mark.anyio
async def test_synthesize_schema_different_prompt_different_cache_key() -> None:
    schema1 = {
        "title": "A",
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
    }
    schema2 = {
        "title": "B",
        "type": "object",
        "properties": {"b": {"type": "string"}},
        "required": ["b"],
    }
    provider1 = FakeSchemaProvider(schema1)
    provider2 = FakeSchemaProvider(schema2)
    cleaned = await clean_html(HTML, provider=provider1, strategy="trafilatura")

    M1 = await synthesize_schema(cleaned, "field a", provider1)
    M2 = await synthesize_schema(cleaned, "field b", provider2)
    assert M1 is not M2


@pytest.mark.anyio
async def test_infer_schema_fetches_and_cleans(monkeypatch) -> None:
    schema = {
        "title": "X",
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    provider = FakeSchemaProvider(schema)

    async def fake_fetch(url: str, tier="auto", **kwargs):
        return SilkPage(HTML, url=url, status=200, fetch_tier=0)

    import sys
    import types

    # `silkweb` exports a top-level `fetch` symbol, which can interfere with
    # attribute-based module resolution in some pytest helpers. We sidestep that by
    # injecting the module that `infer_schema()` imports.
    mod = types.ModuleType("silkweb.fetch.orchestrator")
    mod.fetch = fake_fetch  # type: ignore[attr-defined]
    sys.modules["silkweb.fetch.orchestrator"] = mod

    M = await infer_schema("https://example.com", "name field", provider)
    assert issubclass(M, BaseModel)
    assert M.model_validate({"name": "ok"}).name == "ok"
