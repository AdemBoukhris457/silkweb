from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from .token import TextChunk, estimate_tokens

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]


def _semantic_splits(text: str) -> list[str]:
    # split by headings or paragraph breaks
    raw = (text or "").strip()
    if not raw:
        return []
    parts = re.split(r"\n(?=#{1,6}\s)|\n{2,}", raw)
    return [p.strip() for p in parts if p.strip()]


@dataclass(frozen=True, slots=True)
class RankedChunk:
    chunk: TextChunk
    score: float


class BM25Chunker:
    def __init__(self, *, top_k: int = 5) -> None:
        self.top_k = top_k

    def chunk_and_rank(self, text: str, *, query: str) -> list[RankedChunk]:
        splits = _semantic_splits(text)
        if not splits:
            return []
        corpus = [_tokenize(s) for s in splits]
        bm25 = BM25Okapi(corpus)
        q = _tokenize(query)
        scores = bm25.get_scores(q)

        ranked: list[RankedChunk] = []
        for s, score in zip(splits, scores, strict=False):
            ranked.append(
                RankedChunk(
                    chunk=TextChunk(text=s, token_estimate=estimate_tokens(s)), score=float(score)
                )
            )
        ranked.sort(key=lambda x: x.score, reverse=True)
        return ranked[: self.top_k]
