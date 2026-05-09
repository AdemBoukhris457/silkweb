from __future__ import annotations

import sys
from typing import Any

import pytest
from pydantic import BaseModel

import silkweb
from silkweb.cache.selectors import SelectorCache
from silkweb.llm.pipelines.heal import _make_skeleton_key
from silkweb.parse.page import SilkPage


class Product(BaseModel):
    title: str


class FakeOllamaAsyncClient:
    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    async def chat(self, *, model: str, messages: list[dict[str, str]], options: dict[str, Any]):  # type: ignore[override]
        self._state["chat_calls"].append({"model": model, "messages": messages})

        system = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                break

        if "schema inference engine" in system.lower():
            return {
                "message": {
                    "content": (
                        '{"json_schema":{"title":"AskSchema","type":"object","properties":'
                        '{"answer":{"type":"string"}}, "required":["answer"]}}'
                    )
                }
            }

        if "web data extractor" in system.lower():
            if "answer" in system.lower():
                return {
                    "message": {
                        "content": (
                            '{"items":[{"answer":"42","__xpath__":{"answer":"/html/body/h1[1]"}}]}'
                        )
                    }
                }
            return {
                "message": {
                    "content": (
                        '{"items":[{"title":"Hello","__xpath__":{"title":"/html/body/h1[1]"}}]}'
                    )
                }
            }

        if "selector compiler" in system.lower():
            if "answer" in system:
                return {
                    "message": {
                        "content": (
                            '{"answer":["h1","body h1","h1:nth-of-type(1)","//h1","//body//h1"]}'
                        )
                    }
                }
            return {
                "message": {
                    "content": (
                        '{"title":["h1.title","h1","body h1","//h1[contains(@class,\\"title\\")]","//h1"]}'
                    )
                }
            }

        # Cleaner not used in these tests (we use non-reader model)
        return {"message": {"content": "{}"}}

    async def embeddings(self, *, model: str, prompt: str):  # pragma: no cover
        raise NotImplementedError


class FakeOllamaModule:
    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    def AsyncClient(self):
        return FakeOllamaAsyncClient(self._state)


@pytest.fixture()
def fake_ollama(monkeypatch):
    state: dict[str, Any] = {"chat_calls": []}
    sys.modules["ollama"] = FakeOllamaModule(state)  # type: ignore[assignment]
    yield state
    sys.modules.pop("ollama", None)


@pytest.mark.anyio
async def test_async_extract_selector_cache_skips_llm(monkeypatch, tmp_path, fake_ollama) -> None:
    silkweb.configure(cache_path=str(tmp_path))

    html = "<html><body><h1 class='title'>Hello</h1></body></html>"
    url = "https://example.com/p/1"

    async def fake_fetch(_url: str, tier="auto", **kwargs):
        return SilkPage(html, url=_url)

    monkeypatch.setattr(silkweb, "_async_fetch", fake_fetch)

    # First call: should hit extraction+selector compilation (2 chats)
    out1 = await silkweb.async_extract(
        url,
        Product,
        "extract title",
        cleaner_model="ollama/qwen2.5:14b",
        extraction_model="ollama/qwen2.5:14b",
        selector_model="ollama/qwen2.5-coder:14b",
    )
    assert out1 and out1[0].title == "Hello"
    assert len(fake_ollama["chat_calls"]) == 2

    # Second call: cache hit should avoid LLM calls entirely
    out2 = await silkweb.async_extract(
        url,
        Product,
        "extract title",
        cleaner_model="ollama/qwen2.5:14b",
        extraction_model="ollama/qwen2.5:14b",
        selector_model="ollama/qwen2.5-coder:14b",
    )
    assert out2 and out2[0].title == "Hello"
    assert len(fake_ollama["chat_calls"]) == 2


@pytest.mark.anyio
async def test_async_extract_self_heals_bad_cached_selectors(
    monkeypatch, tmp_path, fake_ollama
) -> None:
    silkweb.configure(cache_path=str(tmp_path))

    html = "<html><body><h1 class='title'>Hello</h1></body></html>"
    url = "https://example.com/p/2"
    domain = "example.com"
    sk = _make_skeleton_key(html, Product)

    cache = SelectorCache()
    cache.set(domain, sk, {"title": [".does-not-exist", "h9", "div h9", "//h9", "//div//h9"]})

    async def fake_fetch(_url: str, tier="auto", **kwargs):
        return SilkPage(html, url=_url)

    monkeypatch.setattr(silkweb, "_async_fetch", fake_fetch)

    out = await silkweb.async_extract(
        url,
        Product,
        "extract title",
        cleaner_model="ollama/qwen2.5:14b",
        extraction_model="ollama/qwen2.5:14b",
        selector_model="ollama/qwen2.5-coder:14b",
    )
    assert out and out[0].title == "Hello"
    # Heal path should call extraction+selector compile at least once
    assert len(fake_ollama["chat_calls"]) >= 2


@pytest.mark.anyio
async def test_async_ask_hydration_first(monkeypatch, tmp_path, fake_ollama) -> None:
    silkweb.configure(cache_path=str(tmp_path))

    html = """
    <html><body>
      <h1>Answer</h1>
      <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"answer":"42"}}}
      </script>
    </body></html>
    """.strip()
    url = "https://example.com/a/1"

    async def fake_fetch(_url: str, tier="auto", **kwargs):
        return SilkPage(html, url=_url)

    monkeypatch.setattr(silkweb, "_async_fetch", fake_fetch)

    out = await silkweb.async_ask(
        url,
        "What is the answer?",
        cleaner_model="ollama/qwen2.5:14b",
        schema_model="ollama/qwen2.5-coder:14b",
        extraction_model="ollama/qwen2.5:14b",
        selector_model="ollama/qwen2.5-coder:14b",
    )
    assert out == "42"


@pytest.mark.anyio
async def test_async_ask_respects_hydration_first_false(monkeypatch, tmp_path, fake_ollama) -> None:
    silkweb.configure(cache_path=str(tmp_path), hydration_first=False)

    html = """
    <html><body>
      <h1>Answer</h1>
      <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"answer":"42"}}}
      </script>
    </body></html>
    """.strip()
    url = "https://example.com/a/2"

    async def fake_fetch(_url: str, tier="auto", **kwargs):
        return SilkPage(html, url=_url)

    # If the hydration fast-path is used despite hydration_first=False, fail loudly.
    def boom(*_a, **_k):
        raise AssertionError(
            "_cleaned_from_hydration should not be called when hydration_first=False"
        )

    monkeypatch.setattr(silkweb, "_async_fetch", fake_fetch)
    monkeypatch.setattr(silkweb, "_cleaned_from_hydration", boom)

    out = await silkweb.async_ask(
        url,
        "What is the answer?",
        cleaner_model="ollama/qwen2.5:14b",
        schema_model="ollama/qwen2.5-coder:14b",
        extraction_model="ollama/qwen2.5:14b",
        selector_model="ollama/qwen2.5-coder:14b",
    )
    assert out == "42"


@pytest.mark.anyio
async def test_async_ask_skips_hydration_when_too_large(monkeypatch, tmp_path, fake_ollama) -> None:
    silkweb.configure(cache_path=str(tmp_path), hydration_first=True, hydration_max_chars=200)

    html = """
    <html><body>
      <h1>Answer</h1>
      <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"answer":"42"}}}
      </script>
    </body></html>
    """.strip()
    url = "https://example.com/a/3"

    async def fake_fetch(_url: str, tier="auto", **kwargs):
        page = SilkPage(html, url=_url)
        monkeypatch.setattr(
            page,
            "hydration_data",
            lambda: {"props": {"pageProps": {"answer": "42", "big": ("x" * 5000)}}},
        )
        return page

    async def fake_clean_html(_html: str, provider=None, strategy="auto"):
        # Return a tiny deterministic cleaned payload so schema+extract work with fake_ollama.
        return silkweb.CleanedContent(
            flat_json='{"heading":"","items":["Answer 42"]}', markdown="Answer 42", token_estimate=3
        )

    monkeypatch.setattr(silkweb, "_async_fetch", fake_fetch)
    monkeypatch.setattr(silkweb, "clean_html", fake_clean_html)

    out = await silkweb.async_ask(
        url,
        "What is the answer?",
        cleaner_model="ollama/qwen2.5:14b",
        schema_model="ollama/qwen2.5-coder:14b",
        extraction_model="ollama/qwen2.5:14b",
        selector_model="ollama/qwen2.5-coder:14b",
    )
    assert out == "42"


@pytest.mark.anyio
async def test_async_extract_from_html_returns_base_models(monkeypatch, tmp_path) -> None:
    silkweb.configure(cache_path=str(tmp_path))

    html = "<html><body><h1 class='title'>Hello</h1></body></html>"
    url = "https://example.com/from-html"

    async def fake_extract_url(**_kwargs):
        return [{"title": "Hello", "__xpath__": {"title": "/html/body/h1[1]"}}]

    monkeypatch.setattr(silkweb, "_extract_url", fake_extract_url)

    out = await silkweb.async_extract_from_html(
        url,
        html,
        schema=Product,
        prompt="extract title",
    )
    assert len(out) == 1
    assert isinstance(out[0], Product)
    assert out[0].title == "Hello"


@pytest.mark.anyio
async def test_async_extract_invalid_output_raises(monkeypatch, tmp_path) -> None:
    silkweb.configure(cache_path=str(tmp_path))
    html = "<html/>"
    url = "https://example.com/bad-output"

    async def boom(**_kw):
        raise AssertionError("_extract_url must not run when output is invalid")

    monkeypatch.setattr(silkweb, "_extract_url", boom)

    with pytest.raises(ValueError, match="Invalid extract output"):
        await silkweb.async_extract_from_html(
            url,
            html,
            schema=Product,
            prompt="x",
            output="parquet",
        )
