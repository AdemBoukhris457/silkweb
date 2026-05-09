from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from ...cache.selectors import SelectorCache
from ...exceptions import SilkwebSchemaError, SilkwebSelectorError
from ...observability.logging import log_event
from ...observability.metrics import get_metrics
from ...parse.page import SilkPage
from ..pipelines.clean import clean_html
from ..pipelines.extract import extract_data
from ..pipelines.heal import SelfHealer, _make_skeleton_key, heal
from ..pipelines.selectors import SelectorSet, compile_selectors
from ..providers.base import LLMProvider


def _domain(url: str) -> str:
    p = urlparse(url)
    return p.netloc or p.path.split("/")[0]


def _extract_field_values(page: SilkPage, selectors: list[str]) -> list[tuple[str, str | None]]:
    """Return all (text, xpath) pairs found by trying each selector."""
    results: list[tuple[str, str | None]] = []
    for sel in selectors:
        if not isinstance(sel, str) or not sel.strip():
            continue
        s = sel.strip()
        try:
            if s.startswith("/") or s.startswith("("):
                elements = page.xpath(s, kind="elements")
                for el in elements:
                    text = (el.text or "").strip()
                    if text:
                        results.append((text, el.xpath))
            else:
                css_elements = page.css(s)
                for el in css_elements:
                    text = (el.text or "").strip()
                    if text:
                        results.append((text, el.xpath))
        except Exception:
            continue
        if results:
            break
    return results


def _apply_selector_set(
    page: SilkPage, schema: type[BaseModel], selector_set: SelectorSet
) -> list[dict[str, Any]]:
    field_names = list(schema.model_fields.keys())
    if not field_names:
        return []

    field_values: dict[str, list[tuple[str, str | None]]] = {}
    max_count = 1
    for field_name in field_names:
        selectors = selector_set.get(field_name) or []
        vals = _extract_field_values(page, selectors)
        field_values[field_name] = vals
        if len(vals) > max_count:
            max_count = len(vals)

    positive_lens = [len(field_values[f]) for f in field_names if len(field_values[f]) > 0]
    if len(positive_lens) > 1 and min(positive_lens) != max(positive_lens):
        raise SilkwebSelectorError(
            message=(
                "Cached selectors produced mismatched row counts across fields "
                f"(counts={{{', '.join(f'{k}: {len(field_values[k])}' for k in field_names)}}}); refusing to zip rows."
            ),
            selector=",".join(field_names),
        )

    items: list[dict[str, Any]] = []
    for i in range(max_count):
        item: dict[str, Any] = {"__xpath__": {}}
        for field_name in field_names:
            vals = field_values[field_name]
            if i < len(vals):
                text, xpath = vals[i]
                item[field_name] = text
                if xpath:
                    item["__xpath__"][field_name] = xpath
            else:
                item[field_name] = vals[0][0] if vals else None
                if vals and vals[0][1]:
                    item["__xpath__"][field_name] = vals[0][1]
        items.append(item)

    if not items:
        raise SilkwebSelectorError(
            message="Selectors matched no records.", selector=",".join(field_names)
        )

    for name, f in schema.model_fields.items():
        if f.is_required() and all(it.get(name) is None for it in items):
            raise SilkwebSelectorError(
                message="Missing required field from selectors.", selector=name
            )

    validated: list[dict[str, Any]] = []
    for item in items:
        payload = {k: v for k, v in item.items() if k in schema.model_fields}
        try:
            schema.model_validate(payload)
        except Exception as e:
            raise SilkwebSchemaError(
                message="Selector-based result did not validate against schema.",
                validation_errors=str(e),
                context={"item": payload},
            ) from e
        validated.append(item)

    return validated


async def extract_url(
    *,
    url: str,
    html: str,
    schema: type[BaseModel],
    prompt: str,
    cleaner_provider: LLMProvider,
    extraction_provider: LLMProvider,
    selector_provider: LLMProvider,
    selector_cache: SelectorCache,
    healer: SelfHealer | None = None,
    force_llm: bool = False,
) -> list[dict[str, Any]]:
    """
    High-level extraction orchestrator.

    - Try selector cache (fast path)
    - If cached selectors fail, invalidate and run full LLM pipeline
    - If full pipeline results fail validation, run self-healer
    - Otherwise cache compiled selectors and return
    """
    dom = _domain(url)
    skeleton = _make_skeleton_key(html, schema)
    t_extract_url = time.perf_counter()

    cached = None if force_llm else selector_cache.get(dom, skeleton)
    if cached is not None:
        log_event("cache_hit", url=url, tier=None, layer="selectors")
        get_metrics().cache_hits_total.labels(layer="selectors").inc()
        log_event(
            "extract_selector_cache_apply_start",
            url=url,
            tier=None,
            phase="selector_cache",
            domain=dom,
            html_chars=len(html or ""),
        )
        t_cache_apply = time.perf_counter()
        try:
            page = SilkPage(html, url=url)
            results = _apply_selector_set(page, schema, cached)
            log_event(
                "extract_selector_cache_applied",
                url=url,
                tier=None,
                phase="selector_cache",
                duration_ms=int((time.perf_counter() - t_cache_apply) * 1000),
                items=len(results),
                domain=dom,
            )
            log_event(
                "extract_url_complete",
                url=url,
                tier=None,
                phase="cache_hit",
                duration_ms=int((time.perf_counter() - t_extract_url) * 1000),
                items=len(results),
            )
            return results
        except Exception as exc:
            log_event(
                "extract_selector_cache_failed",
                url=url,
                tier=None,
                phase="selector_cache",
                error=str(exc),
                domain=dom,
            )
            selector_cache.invalidate(dom, skeleton)

    log_event(
        "cache_miss",
        url=url,
        tier=None,
        layer="selectors",
        force_llm=force_llm,
        domain=dom,
        html_chars=len(html or ""),
    )

    t0 = time.perf_counter()
    cleaned = await clean_html(html, provider=cleaner_provider, strategy="auto")
    dt_clean = time.perf_counter() - t0
    log_event(
        "extract_pipeline_clean_done",
        url=url,
        tier=None,
        phase="clean_html",
        duration_ms=int(dt_clean * 1000),
        token_estimate=getattr(cleaned, "token_estimate", None),
    )

    t1 = time.perf_counter()
    log_event("extract_pipeline_extract_start", url=url, tier=None, phase="extract_data")
    items = await extract_data(cleaned, schema=schema, prompt=prompt, provider=extraction_provider)
    dt_extract = time.perf_counter() - t1
    log_event(
        "extract_pipeline_extract_done",
        url=url,
        tier=None,
        phase="extract_data",
        duration_ms=int(dt_extract * 1000),
        items=len(items),
    )

    dt_sel = 0.0
    dt_heal = 0.0
    # Bad LLM rows: heal first — skip compile+cache on doomed rows (heal re-runs full pipeline).
    if healer is not None and healer.should_heal(items, schema):
        log_event("extract_self_heal_start", url=url, tier=None, phase="heal")
        th = time.perf_counter()
        items = await heal(
            url=url,
            html=html,
            schema=schema,
            prompt=prompt,
            cleaner_provider=cleaner_provider,
            extraction_provider=extraction_provider,
            selector_provider=selector_provider,
            cache=selector_cache,
            healer=healer,
            skeleton_key=skeleton,
        )
        dt_heal = time.perf_counter() - th
        log_event(
            "extract_self_heal_done",
            url=url,
            tier=None,
            phase="heal",
            duration_ms=int(dt_heal * 1000),
            items=len(items),
        )
    else:
        t2 = time.perf_counter()
        log_event("extract_pipeline_compile_start", url=url, tier=None, phase="compile_selectors")
        selector_set = await compile_selectors(
            extracted=items, schema=schema, html=html, provider=selector_provider
        )
        dt_sel = time.perf_counter() - t2
        log_event(
            "extract_pipeline_compile_done",
            url=url,
            tier=None,
            phase="compile_selectors",
            duration_ms=int(dt_sel * 1000),
        )

        selector_cache.set(dom, skeleton, selector_set)
        log_event("selector_cached", url=url, tier=None, domain=dom)

    dt_total = time.perf_counter() - t_extract_url
    log_event(
        "extract_url_complete",
        url=url,
        tier=None,
        phase="full_pipeline",
        duration_ms=int(dt_total * 1000),
        items=len(items),
        duration_clean_ms=int(dt_clean * 1000),
        duration_extract_ms=int(dt_extract * 1000),
        duration_compile_ms=int(dt_sel * 1000) if dt_sel > 0 else None,
        duration_heal_ms=int(dt_heal * 1000) if dt_heal > 0 else None,
    )
    log_event("extraction_complete", url=url, tier=None, items=len(items))
    return items
