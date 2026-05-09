from __future__ import annotations

import types

import pytest

from silkweb.config import configure, get_config
from silkweb.exceptions import SilkwebConfigError, SilkwebLLMError
from silkweb.llm.providers.registry import create_provider, parse_model_uri


@pytest.mark.anyio
async def test_registry_parse_model_uri() -> None:
    parsed = parse_model_uri("ollama/qwen2.5:14b")
    assert parsed.provider == "ollama"
    assert parsed.model == "qwen2.5:14b"

    with pytest.raises(SilkwebConfigError):
        parse_model_uri("nope")


@pytest.mark.anyio
async def test_ollama_generate_and_json(monkeypatch) -> None:
    class FakeAsyncClient:
        async def chat(self, model, messages, options):
            return {"message": {"content": '{"ok": true}'}}

        async def embeddings(self, model, prompt):
            return {"embedding": [0.1, 0.2]}

    fake = types.SimpleNamespace(AsyncClient=lambda: FakeAsyncClient())
    monkeypatch.setitem(__import__("sys").modules, "ollama", fake)

    p = create_provider("ollama/test")
    out = await p.generate([{"role": "user", "content": "hi"}], system="sys")
    assert out == '{"ok": true}'
    js = await p.generate_json([{"role": "user", "content": "hi"}])
    assert js["ok"] is True
    emb = await p.embed(["a", "b"])
    assert emb == [[0.1, 0.2], [0.1, 0.2]]


@pytest.mark.anyio
async def test_openai_json_retries_rate_limit(monkeypatch) -> None:
    calls = {"n": 0}

    class RateLimitError(Exception):
        status_code = 429

    class FakeChoice:
        def __init__(self, content: str):
            self.message = types.SimpleNamespace(content=content)

    class FakeResp:
        def __init__(self, content: str):
            self.choices = [FakeChoice(content)]

    class FakeEmbItem:
        def __init__(self, emb):
            self.embedding = emb

    class FakeEmbResp:
        def __init__(self):
            self.data = [FakeEmbItem([0.0, 1.0])]

    class FakeChat:
        class completions:
            @staticmethod
            async def create(**kwargs):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RateLimitError("rl")
                return FakeResp('{"a": 1}')

    class FakeEmbeddings:
        @staticmethod
        async def create(**kwargs):
            return FakeEmbResp()

    class FakeAsyncOpenAI:
        def __init__(self, api_key=None, timeout=None):
            self.chat = FakeChat()
            self.embeddings = FakeEmbeddings()

    fake_openai = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI, RateLimitError=RateLimitError)
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_openai)

    # avoid real sleeping
    async def no_sleep(_):
        return None

    monkeypatch.setattr("silkweb.llm.providers.base.asyncio.sleep", no_sleep)

    p = create_provider("openai/gpt-test", api_key="k")
    js = await p.generate_json([{"role": "user", "content": "hi"}])
    assert js == {"a": 1}
    assert calls["n"] == 2

    emb = await p.embed(["x"])
    assert emb == [[0.0, 1.0]]


@pytest.mark.anyio
async def test_anthropic_generate_and_malformed_json(monkeypatch) -> None:
    class FakeBlock:
        def __init__(self, text: str):
            self.text = text

    class FakeResp:
        def __init__(self, text: str):
            self.content = [FakeBlock(text)]

    class FakeMessages:
        @staticmethod
        async def create(**kwargs):
            return FakeResp("not-json")

    class FakeAsyncAnthropic:
        def __init__(self, api_key=None, timeout=None):
            self.messages = FakeMessages()

    fake = types.SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic)
    monkeypatch.setitem(__import__("sys").modules, "anthropic", fake)

    p = create_provider("anthropic/claude-test", api_key="k")
    txt = await p.generate([{"role": "user", "content": "hi"}])
    assert txt == "not-json"
    with pytest.raises(SilkwebLLMError):
        await p.generate_json([{"role": "user", "content": "hi"}])


@pytest.mark.anyio
async def test_llamacpp_generate_and_json(monkeypatch) -> None:
    class FakeLlama:
        def __init__(self, model_path, n_ctx, **kwargs):
            self.model_path = model_path

        def __call__(self, prompt, max_tokens, temperature):
            return {"choices": [{"text": '{"ok": true}'}]}

    fake = types.SimpleNamespace(Llama=FakeLlama)
    monkeypatch.setitem(__import__("sys").modules, "llama_cpp", fake)

    p = create_provider("llamacpp/C:\\model.gguf")
    assert await p.generate([{"role": "user", "content": "hi"}]) == '{"ok": true}'
    assert (await p.generate_json([{"role": "user", "content": "hi"}]))["ok"] is True


def test_create_provider_uses_config_llm_timeout_ms() -> None:
    cfg = get_config()
    prev = cfg.llm_timeout_ms
    try:
        configure(llm_timeout_ms=45_000)
        p = create_provider("openai/gpt-test", api_key="k")
        assert p.unwrap().timeout_s == 45.0
    finally:
        configure(llm_timeout_ms=prev)


def test_create_provider_explicit_timeout_overrides_config() -> None:
    cfg = get_config()
    prev = cfg.llm_timeout_ms
    try:
        configure(llm_timeout_ms=99_000)
        p = create_provider("openai/gpt-test", api_key="k", timeout_s=12.5)
        assert p.unwrap().timeout_s == 12.5
    finally:
        configure(llm_timeout_ms=prev)
