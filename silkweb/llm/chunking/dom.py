from __future__ import annotations

from dataclasses import dataclass

from lxml import etree
from lxml import html as lxml_html

from .token import estimate_tokens


@dataclass(frozen=True, slots=True)
class DOMChunk:
    text: str
    token_estimate: int
    xpath: str | None = None


BOUNDARY_TAGS = {"section", "article", "main", "div"}


def _collect_record_xpaths(doc: etree._Element) -> set[str]:
    """
    Detect repeated-record containers by (tag, class) repetition; return their XPaths.
    This mirrors the heuristic in `SilkPage.detect_records()` but works from raw html.
    """
    body = doc.xpath("//body")
    root = doc if not body or not isinstance(body[0], etree._Element) else body[0]

    buckets: dict[tuple[str, str], list[etree._Element]] = {}
    for el in root.iterdescendants():
        if not isinstance(el, etree._Element):
            continue
        cls = (el.get("class") or "").strip()
        if not cls:
            continue
        buckets.setdefault((el.tag, cls), []).append(el)

    best: list[etree._Element] = []
    for els in buckets.values():
        if len(els) >= 2 and len(els) > len(best):
            best = els

    tree = doc.getroottree()
    return {tree.getpath(el) for el in best}


class DOMChunker:
    def __init__(self, *, min_tokens: int = 200) -> None:
        self.min_tokens = min_tokens

    def chunk(self, html: str) -> list[DOMChunk]:
        raw = html or ""
        doc = lxml_html.fromstring(raw) if raw else lxml_html.fromstring("<html/>")
        tree = doc.getroottree()
        record_xpaths = _collect_record_xpaths(doc)

        chunks: list[DOMChunk] = []
        buffer: list[str] = []
        buffer_tokens = 0
        buffer_first_xpath: str | None = None

        def flush() -> None:
            nonlocal buffer, buffer_tokens, buffer_first_xpath
            if buffer:
                text = "\n".join(buffer).strip()
                if text:
                    chunks.append(
                        DOMChunk(
                            text=text,
                            token_estimate=estimate_tokens(text),
                            xpath=buffer_first_xpath,
                        )
                    )
            buffer = []
            buffer_tokens = 0
            buffer_first_xpath = None

        for el in doc.iterdescendants():
            if not isinstance(el, etree._Element):
                continue
            if el.tag not in BOUNDARY_TAGS:
                continue
            xp = tree.getpath(el)
            text = (el.text_content() or "").strip()
            if not text:
                continue

            if xp in record_xpaths:
                flush()
                chunks.append(DOMChunk(text=text, token_estimate=estimate_tokens(text), xpath=xp))
                continue

            tok = estimate_tokens(text)
            if buffer_tokens + tok >= self.min_tokens:
                buffer.append(text)
                if buffer_first_xpath is None:
                    buffer_first_xpath = xp
                flush()
            else:
                buffer.append(text)
                if buffer_first_xpath is None:
                    buffer_first_xpath = xp
                buffer_tokens += tok

        flush()
        return chunks
