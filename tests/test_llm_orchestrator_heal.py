from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from silkweb.cache.selectors import SelectorCache
from silkweb.exceptions import SilkwebExtractionError, SilkwebSelectorError
from silkweb.llm.pipelines.clean import CleanedContent
from silkweb.llm.pipelines.heal import SelfHealer, _make_skeleton_key, heal
from silkweb.llm.pipelines.orchestrator import _apply_selector_set, extract_url
from silkweb.llm.providers.base import LLMProvider
from silkweb.parse.page import SilkPage


class Product(BaseModel):
    title: str


class TitlePrice(BaseModel):
    title: str
    price: str


class FakeProvider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(model="fake-model")
        self.provider_name = "fake"

    async def generate(  # type: ignore[override]
        self, messages, system=None, max_tokens=None, temperature=0.0
    ) -> str:
        raise NotImplementedError

    async def generate_json(  # type: ignore[override]
        self, messages, system=None, schema=None, max_tokens=None, temperature=0.0
    ) -> dict:
        return {}

    async def embed(self, texts):  # type: ignore[override]
        raise NotImplementedError


@pytest.mark.anyio
async def test_orchestrator_invalidates_on_selector_failure(monkeypatch, tmp_path) -> None:
    """When cached selectors fail to apply, the stale entry is invalidated then re-populated."""
    html = "<html><body><h1>OK</h1></body></html>"
    url = "https://example.com/p/1"
    domain = "example.com"
    sk = _make_skeleton_key(html, Product)

    cache = SelectorCache(path=str(tmp_path / "selectors.sqlite"))
    bad_selectors = {"title": [".does-not-exist", "h9", "div h9", "//h9", "//div//h9"]}
    cache.set(domain, sk, bad_selectors)
    assert cache.get(domain, sk) is not None

    async def fake_clean(html, provider, strategy="auto"):
        return CleanedContent(flat_json="{}", markdown="OK", token_estimate=5)

    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.clean_html", fake_clean)

    async def fake_extract(cleaned, schema, prompt, provider):
        return [{"title": "OK", "__xpath__": {"title": "/html/body/h1[1]"}}]

    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.extract_data", fake_extract)

    good_selectors = {"title": ["h1"]}

    async def fake_compile(extracted, schema, html, provider):
        return good_selectors

    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.compile_selectors", fake_compile)

    out = await extract_url(
        url=url,
        html=html,
        schema=Product,
        prompt="get title",
        cleaner_provider=FakeProvider(),
        extraction_provider=FakeProvider(),
        selector_provider=FakeProvider(),
        selector_cache=cache,
        healer=None,
    )
    assert out and out[0]["title"] == "OK"
    # Cache should now hold the good selectors, not the bad ones
    cached = cache.get(domain, sk)
    assert cached == good_selectors


@pytest.mark.anyio
async def test_orchestrator_triggers_heal_on_bad_results(monkeypatch, tmp_path) -> None:
    """When the full pipeline returns results that fail validation, heal() is invoked."""
    html = "<html><body><p>no heading here</p></body></html>"
    url = "https://example.com/p/1"

    cache = SelectorCache(path=str(tmp_path / "selectors.sqlite"))

    async def fake_clean(html, provider, strategy="auto"):
        return CleanedContent(flat_json="{}", markdown="OK", token_estimate=5)

    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.clean_html", fake_clean)

    async def fake_extract(cleaned, schema, prompt, provider):
        return [{"title": None, "__xpath__": {}}]

    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.extract_data", fake_extract)

    # Selectors that won't match anything in the HTML
    async def fake_compile(extracted, schema, html, provider):
        return {"title": [".nonexistent"]}

    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.compile_selectors", fake_compile)

    heal_called: dict[str, Any] = {"n": 0}

    async def fake_heal(**kwargs):
        heal_called["n"] += 1
        return [{"title": "healed", "__xpath__": {"title": "/html/body/p[1]"}}]

    monkeypatch.setattr("silkweb.llm.pipelines.orchestrator.heal", fake_heal)

    out = await extract_url(
        url=url,
        html=html,
        schema=Product,
        prompt="get title",
        cleaner_provider=FakeProvider(),
        extraction_provider=FakeProvider(),
        selector_provider=FakeProvider(),
        selector_cache=cache,
        healer=SelfHealer(max_attempts=1),
    )
    assert heal_called["n"] == 1
    assert out and out[0]["title"] == "healed"


@pytest.mark.anyio
async def test_orchestrator_cache_key_includes_schema(tmp_path) -> None:
    """Two different schemas on the same HTML produce separate cache entries."""
    html = "<html><body><h1>Test</h1><p>Text</p></body></html>"

    class SchemaA(BaseModel):
        title: str

    class SchemaB(BaseModel):
        title: str
        body: str

    sk_a = _make_skeleton_key(html, SchemaA)
    sk_b = _make_skeleton_key(html, SchemaB)
    assert sk_a != sk_b, "Different schemas must produce different cache keys"


def test_apply_selector_set_raises_on_mismatched_field_counts() -> None:
    """Do not zip rows when cached selectors yield different cardinalities across fields."""
    html = "<html><body><h1>A</h1><h1>B</h1><span class='p'>10</span></body></html>"
    page = SilkPage(html, url="https://example.com/")
    # Two h1 matches, one .p match — would silently duplicate price across rows.
    selector_set = {"title": ["h1"], "price": [".p"]}
    with pytest.raises(SilkwebSelectorError, match="mismatched row counts"):
        _apply_selector_set(page, TitlePrice, selector_set)


@pytest.mark.anyio
async def test_heal_invalidates_cache_after_exhausted_attempts(monkeypatch, tmp_path) -> None:
    """After heal gives up, selector cache entry must not remain poisoned."""
    from urllib.parse import urlparse

    html = "<html><body><h1>x</h1></body></html>"
    url = "https://example.com/p/99"
    domain = urlparse(url).netloc
    sk = _make_skeleton_key(html, Product)
    cache = SelectorCache(path=str(tmp_path / "heal_invalidate.sqlite"))

    async def fake_clean(html, provider, strategy="auto"):
        return CleanedContent(flat_json="{}", markdown="x", token_estimate=1)

    monkeypatch.setattr("silkweb.llm.pipelines.heal.clean_html", fake_clean)

    async def bad_extract(cleaned, schema, prompt, provider):
        return [{"title": None, "__xpath__": {}}]

    monkeypatch.setattr("silkweb.llm.pipelines.heal.extract_data", bad_extract)

    async def fake_compile(extracted, schema, html, provider):
        return {"title": ["h1"]}

    monkeypatch.setattr("silkweb.llm.pipelines.heal.compile_selectors", fake_compile)

    with pytest.raises(SilkwebExtractionError, match="Self-healing failed"):
        await heal(
            url=url,
            html=html,
            schema=Product,
            prompt="t",
            cleaner_provider=FakeProvider(),
            extraction_provider=FakeProvider(),
            selector_provider=FakeProvider(),
            cache=cache,
            healer=SelfHealer(max_attempts=2),
        )

    assert cache.get(domain, sk) is None


def test_apply_selector_set_aligned_multi_row() -> None:
    html = "<html><body><h1>A</h1><h1>B</h1><span class='p'>1</span><span class='p'>2</span></body></html>"
    page = SilkPage(html, url="https://example.com/")
    selector_set = {"title": ["h1"], "price": [".p"]}
    rows = _apply_selector_set(page, TitlePrice, selector_set)
    assert len(rows) == 2
    assert rows[0]["title"] == "A"
    assert rows[1]["title"] == "B"


class OptionalRow(BaseModel):
    """All fields optional — threshold uses 'any schema field non-None' per row."""

    a: str | None = None
    b: str | None = None


def test_self_healer_threshold_all_optional_sparse_rows() -> None:
    healer = SelfHealer(max_attempts=2, threshold=0.9)
    # 10 rows, only one has data → ratio 0.1 < 0.9 → should heal
    sparse = [{"a": None, "b": None} for _ in range(9)] + [{"a": "ok", "b": None}]
    assert healer.should_heal(sparse, OptionalRow) is True

    # Most rows have at least one value
    dense = [{"a": str(i), "b": None} for i in range(10)]
    assert healer.should_heal(dense, OptionalRow) is False
