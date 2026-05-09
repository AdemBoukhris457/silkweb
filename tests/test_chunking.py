from __future__ import annotations

import pytest

from silkweb.llm.chunking.bm25 import BM25Chunker
from silkweb.llm.chunking.budget import TokenBudgetPlanner
from silkweb.llm.chunking.dispatcher import chunk_content
from silkweb.llm.chunking.dom import DOMChunker
from silkweb.llm.chunking.semantic import SemanticChunker
from silkweb.llm.chunking.token import token_chunk
from silkweb.llm.pipelines.clean import CleanedContent
from silkweb.llm.providers.base import LLMProvider

TEXT = """
# Heading

Apples are red and tasty.

Bananas are yellow and sweet.

Cars have engines and wheels.

Trucks are large vehicles.
""".strip()


class FakeEmbedProvider(LLMProvider):
    provider_name = "fake"

    def __init__(self):
        super().__init__(model="fake")

    async def generate(self, messages, system=None, max_tokens=None, temperature=0.2):
        raise NotImplementedError

    async def generate_json(
        self, messages, system=None, schema=None, max_tokens=None, temperature=0.2
    ):
        raise NotImplementedError

    async def embed(self, texts):
        # Make fruit paragraphs similar, vehicle paragraphs similar.
        vecs = []
        for t in texts:
            if "Apples" in t or "Bananas" in t:
                vecs.append([1.0, 0.0])
            else:
                vecs.append([0.0, 1.0])
        return vecs


def test_token_chunker_splits() -> None:
    big = "\n\n".join([TEXT] * 5)
    chunks = token_chunk(big, max_tokens=40)
    assert len(chunks) >= 2


def test_bm25_ranks_relevant() -> None:
    ranked = BM25Chunker(top_k=2).chunk_and_rank(TEXT, query="banana sweet")
    assert ranked
    assert "Bananas" in ranked[0].chunk.text


def test_dom_chunker_basic() -> None:
    html = "<html><body><div>One</div><div>Two</div><div class='product'>A</div><div class='product'>B</div></body></html>"
    chunks = DOMChunker(min_tokens=1).chunk(html)
    assert chunks
    # repeated record containers should appear as separate atomic chunks
    assert any("A" in c.text for c in chunks)
    assert any("B" in c.text for c in chunks)


@pytest.mark.anyio
async def test_semantic_chunker_groups() -> None:
    provider = FakeEmbedProvider()
    chunks = await SemanticChunker(similarity_threshold=0.8).chunk(TEXT, provider=provider)
    assert len(chunks) == 2


def test_budget_planner() -> None:
    c = CleanedContent(flat_json="{}", markdown="x" * 1000, token_estimate=300)
    planner = TokenBudgetPlanner(reserved_tokens=100)
    d = planner.decide(c, context_window=256, max_tokens_per_chunk=200)
    assert d.decision == "chunk"


@pytest.mark.anyio
async def test_dispatcher_token_and_bm25_and_semantic() -> None:
    token_chunks = await chunk_content(TEXT, strategy="token", max_tokens=40)
    assert token_chunks

    bm25_chunks = await chunk_content(TEXT, strategy="bm25", query="engines wheels", top_k=1)
    assert len(bm25_chunks) == 1
    assert "Cars" in bm25_chunks[0] or "Trucks" in bm25_chunks[0]

    sem_chunks = await chunk_content(TEXT, strategy="semantic", provider=FakeEmbedProvider())
    assert len(sem_chunks) == 2
