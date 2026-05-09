from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

import trafilatura
from lxml import etree
from lxml import html as lxml_html

from ...config import get_config
from ...exceptions import SilkwebLLMError
from ..providers.base import LLMProvider, Message
from ..providers.ollama import OllamaProvider


@dataclass(frozen=True, slots=True)
class CleanedContent:
    flat_json: str
    markdown: str
    token_estimate: int
    #: Stripped HTML (scripts/nav removed) for LLM extraction when flat_json is listing-degraded.
    html_excerpt: str = ""


CleanStrategy = Literal["auto", "trafilatura", "reader_lm"]


_REMOVE_TAGS = {"script", "style", "noscript"}
_REMOVE_CONTAINERS = {"nav", "footer", "aside"}
_CLASS_ID_PAT = re.compile(
    r"(cookie|consent|banner|subscribe|newsletter|promo|ad-|ads|advert|navbar|footer|header|modal)",
    flags=re.IGNORECASE,
)


def _strip_noise(html: str) -> str:
    """
    Remove scripts/styles and common boilerplate containers (nav/footer/ads/cookie banners).
    """
    doc = lxml_html.fromstring(html or "<html/>")

    for tag in list(_REMOVE_TAGS):
        for el in doc.xpath(f"//{tag}"):
            if isinstance(el, etree._Element) and el.getparent() is not None:
                el.getparent().remove(el)

    for tag in list(_REMOVE_CONTAINERS):
        for el in doc.xpath(f"//{tag}"):
            if isinstance(el, etree._Element) and el.getparent() is not None:
                el.getparent().remove(el)

    # Remove div/section that looks like ads/cookie banners by class/id
    for el in doc.xpath("//*[@class or @id]"):
        if not isinstance(el, etree._Element):
            continue
        ident = f"{el.get('id', '')} {el.get('class', '')}"
        if _CLASS_ID_PAT.search(ident):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    return lxml_html.tostring(doc, encoding="unicode")


def _estimate_tokens(text: str) -> int:
    from ..chunking.token import estimate_tokens

    return estimate_tokens(text)


def _html_excerpt_for_extraction(html: str) -> str:
    """Noise-stripped HTML capped for extraction fallback (dense listings, tables, grids)."""
    raw = _strip_noise(html)
    max_c = int(get_config().extraction_html_max_chars)
    if max_c <= 0:
        return raw
    if len(raw) > max_c:
        return raw[:max_c]
    return raw


def _flat_json_from_markdown(markdown: str, *, heading: str | None = None) -> str:
    lines = [ln.strip() for ln in (markdown or "").splitlines() if ln.strip()]
    items: list[str] = []
    title = heading or ""

    for ln in lines:
        if not title and ln.startswith("#"):
            title = ln.lstrip("#").strip()
            continue
        if ln.startswith(("-", "*")):
            items.append(ln.lstrip("-* ").strip())
        else:
            # keep a few short paragraph lines as items (helps extraction)
            if len(ln) <= 240:
                items.append(ln)

    if not title and items:
        title = items[0][:120]

    payload = {"heading": title, "items": items}
    return json.dumps(payload, ensure_ascii=False)


async def _clean_with_reader_lm(html: str, provider: LLMProvider) -> CleanedContent:
    cleaned_html = _strip_noise(html)
    schema = {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string"}},
            "markdown": {"type": "string"},
        },
        "required": ["markdown", "heading", "items"],
    }
    system = (
        "You are a web content cleaner. Remove navigation, cookie banners, ads, footers, "
        "and boilerplate. Return JSON only.\n"
        "Produce a concise markdown representation suitable for LLM extraction.\n"
    )
    messages: list[Message] = [{"role": "user", "content": cleaned_html}]

    try:
        data = await provider.generate_json(messages, system=system, schema=schema, temperature=0.0)
    except SilkwebLLMError:
        # If provider can't do JSON mode, try plain generate and parse.
        txt = await provider.generate(messages, system=system, temperature=0.0)
        try:
            data = json.loads(txt)
        except Exception as e:
            raise SilkwebLLMError(
                message="ReaderLM cleaning returned invalid JSON.",
                provider=getattr(provider, "provider_name", None),
                model=getattr(provider, "model", None),
                raw_output=txt,
                context={"error": repr(e)},
            ) from e

    markdown = str(data.get("markdown", "") or "").strip()
    heading = str(data.get("heading", "") or "").strip()
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    flat = json.dumps({"heading": heading, "items": items}, ensure_ascii=False)
    excerpt = _html_excerpt_for_extraction(html)
    return CleanedContent(
        flat_json=flat,
        markdown=markdown,
        token_estimate=_estimate_tokens(markdown),
        html_excerpt=excerpt,
    )


def _clean_with_trafilatura(html: str) -> CleanedContent:
    cleaned_html = _strip_noise(html)
    text = trafilatura.extract(cleaned_html) or ""
    markdown = text.strip()

    # Heading heuristic: first <h1> or <title>
    heading = ""
    try:
        doc = lxml_html.fromstring(cleaned_html or "<html/>")
        h1 = doc.xpath("//h1")
        if h1 and isinstance(h1[0], etree._Element):
            heading = (h1[0].text_content() or "").strip()
        if not heading:
            title_el = doc.xpath("//title")
            if title_el and isinstance(title_el[0], etree._Element):
                heading = (title_el[0].text or "").strip()
    except Exception:
        heading = ""

    flat = _flat_json_from_markdown(markdown, heading=heading)
    excerpt = _html_excerpt_for_extraction(html)
    return CleanedContent(
        flat_json=flat,
        markdown=markdown,
        token_estimate=_estimate_tokens(markdown),
        html_excerpt=excerpt,
    )


async def clean_html(
    html: str,
    provider: LLMProvider,
    strategy: CleanStrategy = "auto",
) -> CleanedContent:
    """
    Clean raw HTML into:
    - `markdown`: LLM-ready cleaned text
    - `flat_json`: JSON string with `heading` + `items[]`
    - `token_estimate`: rough token count of markdown
    - `html_excerpt`: noise-stripped HTML (capped) for extraction when flat_json is listing-degraded
    """
    if strategy == "trafilatura":
        return _clean_with_trafilatura(html)

    if strategy == "reader_lm":
        return await _clean_with_reader_lm(html, provider)

    # auto
    inner = provider.unwrap()
    if isinstance(inner, OllamaProvider) and "reader" in inner.model.lower():
        return await _clean_with_reader_lm(html, provider)

    return _clean_with_trafilatura(html)
