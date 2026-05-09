from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from silkweb.cache.selectors import SelectorCache
from silkweb.exceptions import SilkwebExtractionError
from silkweb.llm.pipelines.clean import CleanedContent
from silkweb.llm.pipelines.heal import _make_skeleton_key
from silkweb.llm.providers.base import LLMProvider
from silkweb.parse.page import SilkPage
from silkweb.silkql.compiler import compile_query
from silkweb.silkql.executor import execute_query


def test_compile_query_type_coercions() -> None:
    q = """
    {
      price(currency)
      count(int)
      rating(float, optional)
      in_stock(bool)
      tags(list, min_count=1)
      payload(json, optional)
    }
    """
    Model = compile_query(q)
    obj = Model.model_validate(
        {
            "price": "$1,234.50",
            "count": "1,000",
            "rating": None,
            "in_stock": "In Stock",
            "tags": "Red, Blue",
            "payload": '{"a": 1}',
        }
    )
    assert obj.price == 1234.50
    assert obj.count == 1000
    assert obj.rating is None
    assert obj.in_stock is True
    assert obj.tags == ["Red", "Blue"]
    assert obj.payload == {"a": 1}

    with pytest.raises(ValidationError):
        Model.model_validate({"price": "$1", "count": "1", "in_stock": "yes", "tags": []})


class FakeProvider(LLMProvider):
    provider_name = "fake"

    def __init__(self) -> None:
        super().__init__(model="fake-model")
        self.calls: list[dict[str, Any]] = []

    async def generate(self, messages, system=None, max_tokens=None, temperature=0.0) -> str:  # type: ignore[override]
        raise NotImplementedError

    async def generate_json(  # type: ignore[override]
        self, messages, system=None, schema=None, max_tokens=None, temperature=0.0
    ) -> dict:
        self.calls.append({"system": system, "messages": messages})

        if system and "selector compiler" in system.lower():
            return {
                "products": [
                    ".products",
                    "div.products",
                    "main .products",
                    "//div[@class='products']",
                    "//main//div",
                ],
                "pagination": [
                    ".pagination",
                    "div.pagination",
                    "main .pagination",
                    "//div[@class='pagination']",
                    "//main//div",
                ],
            }

        content = messages[0]["content"]
        if "PAGE2" in content:
            return {
                "items": [
                    {
                        "products": [{"name": "B"}],
                        "pagination": {"next_page_url": None},
                        "__xpath__": {"products": "/html", "pagination": "/html"},
                    }
                ]
            }
        return {
            "items": [
                {
                    "products": [{"name": "A"}],
                    "pagination": {"next_page_url": "/page2"},
                    "__xpath__": {"products": "/html", "pagination": "/html"},
                }
            ]
        }

    async def embed(self, texts):  # type: ignore[override]
        raise NotImplementedError


@pytest.mark.anyio
async def test_execute_query_with_pagination_merge(monkeypatch, tmp_path) -> None:
    provider = FakeProvider()
    cache = SelectorCache(path=str(tmp_path / "selectors.sqlite"))

    q = """
    {
      products[] { name }
      pagination { next_page_url(url, optional) }
    }
    """

    async def fake_fetch(url: str, tier="auto", **kwargs):
        html = (
            "<html><body>PAGE2</body></html>"
            if url.endswith("/page2")
            else "<html><body>PAGE1</body></html>"
        )
        return SilkPage(html, url=url)

    monkeypatch.setattr("silkweb.silkql.executor.fetch_url", fake_fetch)

    result = await execute_query(
        "https://example.com/page1",
        q,
        provider=provider,
        cache=cache,
        cleaner_provider=provider,
        selector_provider=provider,
        follow_pagination=True,
        max_pages=5,
    )

    assert result.pages_scraped == 2
    root = result.data[0]
    assert [p.name for p in root.products] == ["A", "B"]  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_execute_query_uses_cached_selectors(monkeypatch, tmp_path) -> None:
    """On the second call with the same schema, cached selectors skip LLM calls."""
    cache = SelectorCache(path=str(tmp_path / "selectors.sqlite"))

    q = "{ title }"
    schema = compile_query(q)
    html = "<html><body><h1 class='title'>Hello</h1></body></html>"

    sk = _make_skeleton_key(html, schema)
    cache.set("example.com", sk, {"title": [".title", "h1"]})

    provider = FakeProvider()

    async def fake_fetch(url: str, tier="auto", **kwargs):
        return SilkPage(html, url=url)

    monkeypatch.setattr("silkweb.silkql.executor.fetch_url", fake_fetch)

    result = await execute_query(
        "https://example.com/page",
        q,
        provider=provider,
        cache=cache,
        cleaner_provider=provider,
        selector_provider=provider,
    )

    assert result.cached is True
    assert len(provider.calls) == 0, "No LLM calls should be made when selectors are cached"


@pytest.mark.anyio
async def test_execute_query_flat_root_rejects_multiple_rows(monkeypatch, tmp_path) -> None:
    """Non-list root schemas must receive exactly one extracted row."""
    provider = FakeProvider()
    cache = SelectorCache(path=str(tmp_path / "selectors.sqlite"))

    async def fake_fetch(url: str, tier="auto", **kwargs):
        return SilkPage("<html><body>x</body></html>", url=url)

    async def fake_clean(html: str, provider=None, strategy="auto"):
        return CleanedContent(
            flat_json="{}",
            markdown="x",
            token_estimate=1,
            html_excerpt="<p/>",
        )

    async def fake_extract(cleaned, schema=None, prompt=None, provider=None):
        return [{"title": "a"}, {"title": "b"}]

    async def fake_compile_selectors(extracted, schema=None, html=None, provider=None):
        return {"title": [".title", "h1", "main h1", "//h1", "//body//h1"]}

    monkeypatch.setattr("silkweb.silkql.executor.fetch_url", fake_fetch)
    monkeypatch.setattr("silkweb.silkql.executor.clean_html", fake_clean)
    monkeypatch.setattr("silkweb.silkql.executor.extract_data", fake_extract)
    monkeypatch.setattr("silkweb.silkql.executor.compile_selectors", fake_compile_selectors)

    with pytest.raises(SilkwebExtractionError) as excinfo:
        await execute_query(
            "https://example.com/page",
            "{ title }",
            provider=provider,
            cache=cache,
            cleaner_provider=provider,
            selector_provider=provider,
        )
    assert "got 2 rows" in str(excinfo.value.message)
