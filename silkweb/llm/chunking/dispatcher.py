from __future__ import annotations

from typing import Literal

from ..providers.base import LLMProvider
from .bm25 import BM25Chunker
from .dom import DOMChunker
from .semantic import SemanticChunker
from .token import token_chunk

ChunkStrategy = Literal["token", "bm25", "dom", "semantic"]


async def chunk_content(
    content: str,
    *,
    strategy: ChunkStrategy,
    query: str | None = None,
    max_tokens: int = 2000,
    provider: LLMProvider | None = None,
    top_k: int = 5,
) -> list[str]:
    """
    Dispatcher returning a list of chunk texts.
    """
    if strategy == "token":
        return [c.text for c in token_chunk(content, max_tokens=max_tokens)]

    if strategy == "bm25":
        if not query:
            raise ValueError("bm25 strategy requires query")
        ranked = BM25Chunker(top_k=top_k).chunk_and_rank(content, query=query)
        return [r.chunk.text for r in ranked]

    if strategy == "dom":
        chunks = DOMChunker().chunk(content)
        return [c.text for c in chunks]

    if strategy == "semantic":
        if provider is None:
            raise ValueError("semantic strategy requires provider")
        chunks = await SemanticChunker().chunk(content, provider=provider)
        return [c.text for c in chunks]

    raise ValueError(f"Unknown strategy: {strategy}")
