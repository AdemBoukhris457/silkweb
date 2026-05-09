from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, overload
from urllib.parse import urljoin, urlparse

from lxml import etree
from lxml import html as lxml_html


@dataclass(frozen=True, slots=True)
class SilkMeta:
    url: str
    fetched_at: datetime
    fetch_tier: int
    xpath: str
    llm_model: str | None = None
    selector_from_cache: bool | None = None
    confidence: float | None = None


class SilkElement:
    def __init__(self, element: etree._Element):
        self._el = element

    @property
    def text(self) -> str:
        return (self._el.text_content() or "").strip()

    @property
    def html(self) -> str:
        return lxml_html.tostring(self._el, encoding="unicode", with_tail=False)

    @property
    def attrs(self) -> dict[str, str]:
        return {k: v for k, v in self._el.attrib.items()}

    def __getitem__(self, attr: str) -> str | None:
        return self._el.attrib.get(attr)

    @property
    def xpath(self) -> str:
        return self._el.getroottree().getpath(self._el)

    @property
    def parent(self) -> SilkElement | None:
        parent = self._el.getparent()
        return SilkElement(parent) if parent is not None else None

    @property
    def children(self) -> list[SilkElement]:
        return [SilkElement(child) for child in self._el if isinstance(child, etree._Element)]

    @property
    def siblings(self) -> list[SilkElement]:
        parent = self._el.getparent()
        if parent is None:
            return []
        return [
            SilkElement(sib)
            for sib in parent
            if isinstance(sib, etree._Element) and sib is not self._el
        ]

    def _unwrap(self) -> etree._Element:
        return self._el


def _safe_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except Exception:
        return None


def _plain_title_text(title_el: etree._Element) -> str:
    """
    Visible title text. Prefer ``text_content()``; strip tag-like fragments when markup
    appears as literal text (parser / entity edge cases).
    """
    raw = (title_el.text_content() or "").strip()
    if "<" in raw and ">" in raw:
        raw = re.sub(r"<[^>]+>", "", raw)
        raw = " ".join(raw.split())
    return raw.strip()


class SilkPage:
    def __init__(
        self,
        html: str,
        *,
        url: str = "",
        status: int = 200,
        headers: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        fetch_tier: int = 0,
    ) -> None:
        self.html: str = html
        self.url: str = url
        self.status: int = status
        self.headers: dict[str, str] = headers or {}
        self.fetch_tier: int = fetch_tier

        try:
            self._lxml_root = (
                lxml_html.fromstring(html) if html else lxml_html.fromstring("<html/>")
            )
        except (ValueError, etree.ParserError, etree.XMLSyntaxError):
            # e.g. XML sitemap bodies with ``<?xml ...?>`` are not valid HTML for lxml.html
            self._lxml_root = lxml_html.fromstring("<html/>")

        self.metadata: dict[str, Any] = metadata or self._extract_metadata()
        self.text: str = self._extract_text()
        self.markdown: str = self._extract_markdown()

    def _extract_text(self) -> str:
        try:
            import trafilatura

            result = trafilatura.extract(self.html, output_format="txt")
            if result:
                return result.strip()
        except Exception:
            pass
        return (self._lxml_root.text_content() or "").strip()

    def _extract_markdown(self) -> str:
        try:
            import trafilatura

            result = trafilatura.extract(self.html, output_format="markdown")
            if result:
                return result.strip()
        except Exception:
            pass
        return self.text

    def _extract_metadata(self) -> dict[str, Any]:
        meta: dict[str, Any] = {}

        title_el = self._lxml_root.xpath("//title")
        if title_el and isinstance(title_el[0], etree._Element):
            meta["title"] = _plain_title_text(title_el[0])

        for m in self._lxml_root.xpath("//meta[@property or @name]"):
            if not isinstance(m, etree._Element):
                continue
            key = (m.get("property") or m.get("name") or "").strip()
            if not key:
                continue
            content = (m.get("content") or "").strip()
            if content:
                meta[key] = content

        return meta

    def _lxml_from_xpath(self, xpath: str) -> etree._Element | None:
        try:
            results = self._lxml_root.xpath(xpath)
        except Exception:
            return None
        if not isinstance(results, list):
            return None
        for r in results:
            if isinstance(r, etree._Element):
                return r
        return None

    def css(self, selector: str) -> list[SilkElement]:
        from lxml.cssselect import CSSSelector

        sel = CSSSelector(selector)
        return [SilkElement(el) for el in sel(self._lxml_root) if isinstance(el, etree._Element)]

    def css_first(self, selector: str) -> SilkElement | None:
        items = self.css(selector)
        return items[0] if items else None

    @overload
    def xpath(self, expr: str, *, kind: Literal["elements"] = "elements") -> list[SilkElement]: ...

    @overload
    def xpath(self, expr: str, *, kind: Literal["values"]) -> list[Any]: ...

    def xpath(self, expr: str, *, kind: Literal["elements", "values"] = "elements") -> list[Any]:
        """
        Run an XPath expression against the page root.

        - `kind="elements"` returns `SilkElement` wrappers (default). Use for node paths.
        - `kind="values"` returns raw values (e.g. `//@href`, `/text()`), not elements.
        """
        try:
            results = self._lxml_root.xpath(expr)
        except Exception:
            return []

        if kind == "values":
            return list(results) if isinstance(results, list) else [results]

        if not isinstance(results, list):
            return []
        return [SilkElement(r) for r in results if isinstance(r, etree._Element)]

    def links(self, *, external: bool | None = None) -> list[str]:
        """
        Return all <a href> links as absolute URLs.

        Args:
            external: None returns all links, True returns only external,
                      False returns only internal (same-domain).
        """
        hrefs = self._lxml_root.xpath("//a[@href]/@href")
        parsed_base = urlparse(self.url) if self.url else None
        out: list[str] = []
        for href in hrefs:
            if not isinstance(href, str):
                continue
            abs_url = urljoin(self.url or "", href)
            if external is None or parsed_base is None:
                out.append(abs_url)
            else:
                is_ext = bool(
                    urlparse(abs_url).netloc and urlparse(abs_url).netloc != parsed_base.netloc
                )
                if (external and is_ext) or (not external and not is_ext):
                    out.append(abs_url)
        return out

    def network_requests(self) -> list[dict[str, Any]]:
        """
        Return captured network events (browser tiers only, when enabled).

        This is populated by tier 2/3 fetchers when `capture_network=True`.
        """
        val = getattr(self, "_network_log", None)
        return list(val) if isinstance(val, list) else []

    def tables(self) -> list[list[list[str]]]:
        tables: list[list[list[str]]] = []
        for table in self._lxml_root.xpath("//table"):
            if not isinstance(table, etree._Element):
                continue
            rows: list[list[str]] = []
            for tr in table.xpath(".//tr"):
                if not isinstance(tr, etree._Element):
                    continue
                cells = tr.xpath("./th|./td")
                row: list[str] = []
                for c in cells:
                    if isinstance(c, etree._Element):
                        row.append((c.text_content() or "").strip())
                if row:
                    rows.append(row)
            if rows:
                tables.append(rows)
        return tables

    def json_ld(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        scripts = self._lxml_root.xpath("//script[@type='application/ld+json']/text()")
        for s in scripts:
            if not isinstance(s, str):
                continue
            parsed = _safe_json_loads(s.strip())
            if isinstance(parsed, dict):
                items.append(parsed)
            elif isinstance(parsed, list):
                for x in parsed:
                    if isinstance(x, dict):
                        items.append(x)
        return items

    def hydration_data(self) -> dict[str, Any] | None:
        # Next.js
        next_data = self._lxml_root.xpath("//script[@id='__NEXT_DATA__']/text()")
        for s in next_data:
            if isinstance(s, str):
                parsed = _safe_json_loads(s.strip())
                if isinstance(parsed, dict):
                    return parsed

        # Nuxt: embedded payload tag (when present)
        nuxt_tagged = self._lxml_root.xpath("//script[@id='__NUXT_DATA__']/text()")
        for s in nuxt_tagged:
            if isinstance(s, str):
                parsed = _safe_json_loads(s.strip())
                if isinstance(parsed, dict):
                    return parsed

        # Nuxt (very naive heuristic)
        scripts = self._lxml_root.xpath("//script/text()")
        for s in scripts:
            if not isinstance(s, str):
                continue
            m = re.search(r"__NUXT__\s*=\s*(\{.*\})\s*;?\s*$", s.strip(), flags=re.DOTALL)
            if m:
                parsed = _safe_json_loads(m.group(1))
                if isinstance(parsed, dict):
                    return parsed
        return None

    def article(self) -> dict[str, Any]:
        title = ""
        h1 = self._lxml_root.xpath("//h1")
        if h1 and isinstance(h1[0], etree._Element):
            title = (h1[0].text_content() or "").strip()
        if not title:
            title = str(self.metadata.get("title", "") or "")

        return {
            "title": title,
            "text": self.text,
            "author": self.metadata.get("author") or self.metadata.get("article:author"),
            "date": self.metadata.get("date") or self.metadata.get("article:published_time"),
            "language": self.metadata.get("language"),
        }

    def detect_records(self) -> list[dict[str, Any]]:
        """
        Heuristic repeated-record detection (no LLM).

        For now: find the most repeated (tag, class) among elements under <body>,
        and turn each into a small record dict.
        """
        body = self._lxml_root.xpath("//body")
        if not body or not isinstance(body[0], etree._Element):
            return []
        body_el = body[0]

        buckets: dict[tuple[str, str], list[etree._Element]] = {}
        for el in body_el.iterdescendants():
            if not isinstance(el, etree._Element):
                continue
            cls = (el.get("class") or "").strip()
            if not cls:
                continue
            key = (el.tag, cls)
            buckets.setdefault(key, []).append(el)

        best: list[etree._Element] = []
        for els in buckets.values():
            if len(els) >= 2 and len(els) > len(best):
                best = els

        records: list[dict[str, Any]] = []
        for el in best:
            wrapper = SilkElement(el)
            link_el = el.xpath(".//a[@href]")
            href = None
            if link_el and isinstance(link_el[0], etree._Element):
                href = link_el[0].get("href")
            records.append(
                {
                    "text": wrapper.text,
                    "xpath": wrapper.xpath,
                    "url": urljoin(self.url or "", href) if href else None,
                }
            )
        return records

    def provenance_for_element(
        self,
        element: SilkElement,
        *,
        llm_model: str | None = None,
        selector_from_cache: bool | None = None,
        confidence: float | None = None,
        fetched_at: datetime | None = None,
    ) -> SilkMeta:
        fetched = fetched_at or datetime.now(tz=timezone.utc)
        return SilkMeta(
            url=self.url,
            fetched_at=fetched,
            fetch_tier=self.fetch_tier,
            xpath=element.xpath,
            llm_model=llm_model,
            selector_from_cache=selector_from_cache,
            confidence=confidence,
        )
