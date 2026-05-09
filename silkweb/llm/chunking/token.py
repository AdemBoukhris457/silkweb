from __future__ import annotations

import re
from dataclasses import dataclass

_CJK_RANGE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str
    token_estimate: int


def estimate_tokens(text: str) -> int:
    s = (text or "").strip()
    if not s:
        return 1
    cjk_chars = len(_CJK_RANGE.findall(s))
    latin_chars = len(s) - cjk_chars
    # CJK: ~1.5 chars per token; Latin: ~4 chars per token
    return max(1, int(cjk_chars / 1.5) + int(latin_chars / 4))


def token_chunk(text: str, *, max_tokens: int) -> list[TextChunk]:
    """
    Simple token-count chunker using a char->token heuristic.
    Splits on paragraph boundaries when possible; otherwise hard-splits.
    """
    if max_tokens < 32:
        raise ValueError("max_tokens too small")

    raw = (text or "").strip()
    if not raw:
        return []

    max_chars = max_tokens * 4
    paras = [p.strip() for p in raw.split("\n\n") if p.strip()]

    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0

    def _flush() -> None:
        nonlocal cur, cur_len
        if cur:
            chunks.append("\n\n".join(cur).strip())
        cur = []
        cur_len = 0

    for p in paras:
        if len(p) > max_chars:
            _flush()
            # hard split huge paragraph
            for i in range(0, len(p), max_chars):
                part = p[i : i + max_chars].strip()
                if part:
                    chunks.append(part)
            continue

        if cur_len + len(p) + 2 > max_chars:
            _flush()
        cur.append(p)
        cur_len += len(p) + 2

    _flush()
    return [TextChunk(text=c, token_estimate=estimate_tokens(c)) for c in chunks]
