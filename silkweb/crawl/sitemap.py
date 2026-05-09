from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from urllib.parse import urlparse

from ..parse.page import SilkPage

RootKind = Literal["urlset", "sitemapindex", "unknown"]


def _local_tag(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _loc_text(elem: ET.Element) -> str:
    if elem.text:
        return (elem.text or "").strip()
    return ""


def _child_by_local(parent: ET.Element, local: str) -> ET.Element | None:
    want = local.lower()
    for ch in parent:
        if _local_tag(ch.tag).lower() == want:
            return ch
    return None


def _children_by_local(parent: ET.Element, local: str) -> list[ET.Element]:
    want = local.lower()
    return [ch for ch in parent if _local_tag(ch.tag).lower() == want]


def sitemap_root_kind(root: ET.Element) -> RootKind:
    lt = _local_tag(root.tag).lower()
    if lt == "urlset":
        return "urlset"
    if lt == "sitemapindex":
        return "sitemapindex"
    return "unknown"


def page_locs_from_urlset(root: ET.Element) -> list[str]:
    """`<urlset>` / `<url>` / `<loc>` page URLs."""
    out: list[str] = []
    for url_el in _children_by_local(root, "url"):
        loc_el = _child_by_local(url_el, "loc")
        if loc_el is None:
            continue
        t = _loc_text(loc_el)
        if t:
            out.append(t)
    return out


def nested_sitemap_locs_from_index(root: ET.Element) -> list[str]:
    """`<sitemapindex>` / `<sitemap>` / `<loc>` nested sitemap document URLs."""
    out: list[str] = []
    for sm_el in _children_by_local(root, "sitemap"):
        loc_el = _child_by_local(sm_el, "loc")
        if loc_el is None:
            continue
        t = _loc_text(loc_el)
        if t:
            out.append(t)
    return out


def parse_sitemap_xml(content: str) -> tuple[RootKind, list[str]]:
    """
    Parse sitemap XML into (kind, urls).

    For ``urlset``, urls are page ``<loc>`` entries.
    For ``sitemapindex``, urls are nested sitemap document URLs.
    """
    raw = (content or "").strip()
    if not raw:
        return "unknown", []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return "unknown", []

    kind = sitemap_root_kind(root)
    if kind == "urlset":
        return kind, page_locs_from_urlset(root)
    if kind == "sitemapindex":
        return kind, nested_sitemap_locs_from_index(root)
    return "unknown", []


def host_allowed_domains(sitemap_url: str) -> set[str] | None:
    """Single-host set derived from sitemap URL netloc (lowercase)."""
    host = (urlparse(sitemap_url).netloc or "").lower()
    if not host:
        return None
    return {host}


async def collect_page_urls_from_sitemap(
    fetch: Callable[..., Awaitable[SilkPage]],
    sitemap_url: str,
    *,
    max_pages: int,
    max_sitemap_files: int = 20,
    **fetch_kwargs: Any,
) -> list[str]:
    """
    Fetch a sitemap (or index), return up to ``max_pages`` page URLs to crawl.

    Nested sitemap index documents are fetched up to ``max_sitemap_files`` entries.
    If a nested document is itself an index, one further expansion is performed.
    """
    p0 = await fetch(sitemap_url, tier=0, **fetch_kwargs)
    kind0, locs0 = parse_sitemap_xml(p0.html or "")
    if kind0 == "urlset":
        return locs0[:max_pages]
    if kind0 != "sitemapindex":
        return []

    out: list[str] = []

    async def append_from_urlset(url: str) -> None:
        nonlocal out
        px = await fetch(url, tier=0, **fetch_kwargs)
        k, ls = parse_sitemap_xml(px.html or "")
        if k != "urlset":
            return
        for u in ls:
            if len(out) >= max_pages:
                return
            out.append(u)

    for sub in locs0[:max_sitemap_files]:
        if len(out) >= max_pages:
            break
        px = await fetch(sub, tier=0, **fetch_kwargs)
        k2, locs2 = parse_sitemap_xml(px.html or "")
        if k2 == "urlset":
            for u in locs2:
                if len(out) >= max_pages:
                    break
                out.append(u)
        elif k2 == "sitemapindex":
            for sub2 in locs2[:max_sitemap_files]:
                if len(out) >= max_pages:
                    break
                await append_from_urlset(sub2)

    return out[:max_pages]
