from __future__ import annotations

import math
from dataclasses import dataclass

from ..providers.base import LLMProvider
from .token import estimate_tokens


@dataclass(frozen=True, slots=True)
class SemanticChunk:
    text: str
    token_estimate: int
    group: int


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split("\n\n") if p.strip()]


class SemanticChunker:
    def __init__(self, *, similarity_threshold: float = 0.75) -> None:
        self.similarity_threshold = similarity_threshold

    async def chunk(self, text: str, *, provider: LLMProvider) -> list[SemanticChunk]:
        paras = _paragraphs(text)
        if not paras:
            return []

        vectors = await provider.embed(paras)
        if len(vectors) != len(paras):
            raise ValueError(
                f"Embedding returned {len(vectors)} vectors for {len(paras)} paragraphs. "
                "Ensure the embedding provider returns one vector per input."
            )
        groups: list[list[int]] = []
        centroids: list[list[float]] = []

        def update_centroid(idxs: list[int]) -> list[float]:
            n = len(idxs)
            if n == 0:
                return []
            dim = len(vectors[idxs[0]])
            out = [0.0] * dim
            for i in idxs:
                for j, v in enumerate(vectors[i], start=0):
                    out[j] += float(v)
            return [x / n for x in out]

        for i, v in enumerate(vectors):
            best_g = -1
            best_s = 0.0
            for gi, c in enumerate(centroids):
                s = _cosine(v, c)
                if s > best_s:
                    best_s = s
                    best_g = gi
            if best_g >= 0 and best_s >= self.similarity_threshold:
                groups[best_g].append(i)
                centroids[best_g] = update_centroid(groups[best_g])
            else:
                groups.append([i])
                centroids.append(list(v))

        chunks: list[SemanticChunk] = []
        for gi, idxs in enumerate(groups):
            txt = "\n\n".join(paras[i] for i in idxs).strip()
            chunks.append(SemanticChunk(text=txt, token_estimate=estimate_tokens(txt), group=gi))
        return chunks
