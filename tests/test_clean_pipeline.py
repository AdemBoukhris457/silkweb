from __future__ import annotations

import json

import pytest

from silkweb.llm.pipelines.clean import clean_html
from silkweb.llm.providers.ollama import OllamaProvider

SAMPLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>My Article</title>
    <script>console.log("track");</script>
    <style>.ad{display:none}</style>
  </head>
  <body>
    <nav>Home About Contact</nav>
    <div id="cookie-banner">We use cookies</div>
    <article>
      <h1>Real Heading</h1>
      <p>First paragraph with meaning.</p>
      <ul>
        <li>Item A</li>
        <li>Item B</li>
      </ul>
      <p>Second paragraph.</p>
    </article>
    <footer>Copyright 2026</footer>
  </body>
</html>
""".strip()


class FakeReaderProvider(OllamaProvider):
    def __init__(self, captured: dict):
        super().__init__(model="ollama/reader-lm-v2")
        self.captured = captured

    async def generate_json(
        self, messages, system=None, schema=None, max_tokens=None, temperature=0.0
    ):
        # capture what was passed (ensure noise stripped)
        self.captured["content"] = messages[0]["content"]
        return {
            "heading": "Real Heading",
            "items": ["Item A", "Item B"],
            "markdown": "# Real Heading\n\n- Item A\n- Item B\n\nFirst paragraph with meaning.\n",
        }

    async def generate(self, messages, system=None, max_tokens=None, temperature=0.0):
        raise AssertionError("should not be called in this test")

    async def embed(self, texts):
        return [[0.0] for _ in texts]


@pytest.mark.anyio
async def test_trafilatura_strategy_strips_boilerplate() -> None:
    c = await clean_html(SAMPLE_HTML, provider=FakeReaderProvider({}), strategy="trafilatura")
    assert "Home About Contact" not in c.markdown
    assert "We use cookies" not in c.markdown
    assert "Real Heading" in c.markdown
    assert c.token_estimate > 1

    flat = json.loads(c.flat_json)
    assert "heading" in flat
    assert "items" in flat


@pytest.mark.anyio
async def test_reader_lm_strategy_uses_provider_and_strips_scripts() -> None:
    captured: dict[str, str] = {}
    provider = FakeReaderProvider(captured)
    c = await clean_html(SAMPLE_HTML, provider=provider, strategy="reader_lm")
    assert "Real Heading" in c.markdown
    assert "<script>" not in captured["content"]
    assert "<nav>" not in captured["content"]


@pytest.mark.anyio
async def test_auto_prefers_reader_lm_when_provider_is_reader() -> None:
    captured: dict[str, str] = {}
    provider = FakeReaderProvider(captured)
    c = await clean_html(SAMPLE_HTML, provider=provider, strategy="auto")
    assert "Real Heading" in c.markdown
    assert captured["content"]
