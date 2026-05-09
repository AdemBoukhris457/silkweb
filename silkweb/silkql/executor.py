from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, get_args, get_origin
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel

from ..cache.selectors import SelectorCache
from ..config import get_config
from ..exceptions import SilkwebExtractionError
from ..fetch.orchestrator import fetch as fetch_url
from ..llm.pipelines.clean import clean_html
from ..llm.pipelines.extract import extract_data
from ..llm.pipelines.heal import SelfHealer, _make_skeleton_key
from ..llm.pipelines.orchestrator import _apply_selector_set
from ..llm.pipelines.selectors import compile_selectors
from ..llm.providers.base import LLMProvider
from ..llm.providers.registry import create_provider
from ..observability.logging import log_event
from ..parse.page import SilkPage
from .compiler import compile_query
from .parser import CollectionNode, FieldNode, RootNode, parse_silkql


def _silkql_trace_enabled() -> bool:
    return os.environ.get("SILKWEB_TRACE_SILKQL", "").strip().lower() in ("1", "true", "yes")


def _trace_silkql_rows(
    *,
    url: str,
    items: list[dict[str, Any]],
    extraction_schema: type[BaseModel],
    source: str,
) -> None:
    """When ``SILKWEB_TRACE_SILKQL=1``, log where rows came from and per-field null/empty counts."""
    if not _silkql_trace_enabled() or not items:
        return
    n = len(items)
    fields = list(extraction_schema.model_fields.keys())
    parts: list[str] = []
    for fname in fields:
        missing = sum(1 for it in items if fname not in it)
        nulls = sum(1 for it in items if it.get(fname) is None)
        empties = sum(1 for it in items if it.get(fname) == "")
        str_none = sum(1 for it in items if it.get(fname) == "None")
        parts.append(
            f"{fname}:missing={missing},null={nulls},empty={empties},str('None')={str_none}"
        )
    msg = f"[silkweb:silkql-trace] url={url!r} source={source!r} items={n} " + " ".join(parts)
    print(msg, file=sys.stderr, flush=True)
    log_event(
        "silkql_extract_trace",
        url=url,
        tier=None,
        layer="silkql",
        source=source,
        item_count=n,
        field_stats="; ".join(parts),
    )


@dataclass(frozen=True, slots=True)
class QueryResult:
    data: list[BaseModel]
    pages_scraped: int
    cached: bool


def _domain(url: str) -> str:
    p = urlparse(url)
    return p.netloc or p.path.split("/")[0]


def _has_pagination_next(ast: RootNode) -> bool:
    for ch in ast.children:
        if isinstance(ch, CollectionNode) and ch.name == "pagination":
            for sub in ch.children:
                if isinstance(sub, FieldNode) and sub.name == "next_page_url":
                    return True
    return False


def _find_primary_list_field(
    schema: type[BaseModel],
) -> tuple[str, type[BaseModel]] | None:
    """Detect a single list[SomeModel] collection field at the root.

    Returns (field_name, inner_model) when the root schema has exactly one
    list-of-BaseModel field **and no other required fields**.  This lets us
    extract flat rows and re-wrap them afterward without losing sibling data
    (e.g. a required ``pagination`` object alongside ``stories[]``).
    """
    list_fields: list[tuple[str, type[BaseModel]]] = []
    other_required: list[str] = []
    for name, info in schema.model_fields.items():
        ann = info.annotation
        origin = get_origin(ann)
        if origin is list:
            args = get_args(ann)
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                list_fields.append((name, args[0]))
                continue
        if info.is_required():
            other_required.append(name)
    if len(list_fields) == 1 and not other_required:
        return list_fields[0]
    return None


def _prompt_from_ast(ast: RootNode) -> str:
    lines: list[str] = ["Extract the following fields as structured JSON:"]

    def walk(nodes: list[Any], prefix: str) -> None:
        for n in nodes:
            if isinstance(n, FieldNode):
                tc = f" ({n.type_coercion})" if n.type_coercion else ""
                mods = f" [{', '.join(n.modifiers)}]" if n.modifiers else ""
                lines.append(f"- {prefix}{n.name}{tc}{mods}")
            elif isinstance(n, CollectionNode):
                kind = "list" if n.is_list else "object"
                lines.append(f"- {prefix}{n.name}: {kind}")
                walk(n.children, prefix=f"{prefix}{n.name}.")

    walk(ast.children, prefix="")
    return "\n".join(lines)


def _merge_models(model: type[BaseModel], a: BaseModel, b: BaseModel) -> BaseModel:
    da = a.model_dump()
    db = b.model_dump()
    merged: dict[str, Any] = dict(da)
    for k, v in db.items():
        if k not in merged or merged[k] is None:
            merged[k] = v
            continue
        if isinstance(merged[k], list) and isinstance(v, list):
            # Dedup by stable JSON key (default=str for non-JSON-native values)
            seen: set[str] = set()
            out: list[Any] = []
            for item in merged[k] + v:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
            merged[k] = out
            continue
        if isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = {**merged[k], **v}
            continue
        # last-wins for scalars
        merged[k] = v
    return model.model_validate(merged)


async def _process_silkql_page(
    page: SilkPage,
    current_url: str,
    *,
    schema: type[BaseModel],
    prompt: str,
    list_field_name: str | None,
    inner_model: type[BaseModel] | None,
    extraction_schema: type[BaseModel],
    extraction_provider: LLMProvider,
    cleaner_provider: LLMProvider,
    selector_provider: LLMProvider,
    cache: SelectorCache,
    force_llm: bool,
    healer: SelfHealer,
) -> tuple[BaseModel, bool]:
    """Run one SilkQL extraction pass on ``page`` (fetch already done). Returns root model and whether selector cache was used."""
    dom = _domain(current_url)
    skeleton = _make_skeleton_key(page.html, extraction_schema)

    extraction_source = "llm"
    page_cached = False

    # Fast path: try cached selectors (keyed to extraction_schema)
    cached_selectors = None if force_llm else cache.get(dom, skeleton)
    if cached_selectors is not None:
        try:
            items = _apply_selector_set(page, extraction_schema, cached_selectors)
            if items and not healer.should_heal(items, extraction_schema):
                page_cached = True
                extraction_source = "selector_cache"
            else:
                cache.invalidate(dom, skeleton)
                cached_selectors = None
        except Exception:
            cache.invalidate(dom, skeleton)
            cached_selectors = None

    # Slow path: full LLM pipeline
    if cached_selectors is None:
        cleaned = await clean_html(page.html, provider=cleaner_provider, strategy="auto")
        items = await extract_data(
            cleaned, schema=extraction_schema, prompt=prompt, provider=extraction_provider
        )
        if not items:
            raise SilkwebExtractionError(
                message="SilkQL execution returned no items.", url=current_url
            )

        if healer.should_heal(items, extraction_schema):
            cache.invalidate(dom, skeleton)
            cleaned = await clean_html(page.html, provider=cleaner_provider, strategy="auto")
            items = await extract_data(
                cleaned, schema=extraction_schema, prompt=prompt, provider=extraction_provider
            )
            if healer.should_heal(items, extraction_schema):
                raise SilkwebExtractionError(
                    message="SilkQL execution failed validation after healing.",
                    url=current_url,
                )

        selector_set = await compile_selectors(
            extracted=items,
            schema=extraction_schema,
            html=page.html,
            provider=selector_provider,
        )
        cache.set(dom, skeleton, selector_set)

    _trace_silkql_rows(
        url=current_url,
        items=items,
        extraction_schema=extraction_schema,
        source=extraction_source,
    )

    # Build the root object from extracted items
    if list_field_name is not None and inner_model is not None:
        clean_items = [
            {k: v for k, v in it.items() if k in inner_model.model_fields} for it in items
        ]
        # Collect any non-list root fields (e.g. pagination) from items
        extra_fields: dict[str, Any] = {}
        for it in items:
            for k, v in it.items():
                if k in schema.model_fields and k != list_field_name and k not in extra_fields:
                    extra_fields[k] = v
        root_data: dict[str, Any] = {list_field_name: clean_items, **extra_fields}
        root_obj = schema.model_validate(root_data)
    else:
        if len(items) != 1:
            raise SilkwebExtractionError(
                message=(
                    "SilkQL root schema expects a single extracted object for this query shape "
                    f"(got {len(items)} rows). Use a list collection at the root (e.g. `items[] {{ ... }}`) "
                    "for multi-row data."
                ),
                url=current_url,
            )
        root_obj = schema.model_validate(
            {k: v for k, v in items[0].items() if k in schema.model_fields}
        )

    return root_obj, page_cached


async def execute_query_from_html(
    url: str,
    html: str,
    silkql_string: str,
    *,
    provider: LLMProvider,
    cache: SelectorCache,
    cleaner_provider: LLMProvider | None = None,
    selector_provider: LLMProvider | None = None,
    force_llm: bool = False,
    healer: SelfHealer | None = None,
) -> QueryResult:
    """Execute SilkQL against pre-fetched HTML (same semantics as one page of ``execute_query``)."""
    cfg = get_config()
    cleaner_lp = cleaner_provider or create_provider(cfg.cleaner_model)
    selector_lp = selector_provider or create_provider(cfg.selector_model)
    heal = healer or SelfHealer(max_attempts=max(1, int(cfg.max_retries)))

    ast = parse_silkql(silkql_string)
    schema = compile_query(silkql_string)
    prompt = _prompt_from_ast(ast)

    list_info = _find_primary_list_field(schema)
    if list_info is not None:
        list_field_name, inner_model = list_info
    else:
        list_field_name, inner_model = None, None

    extraction_schema: type[BaseModel] = inner_model if inner_model is not None else schema
    page = SilkPage(html, url=url)
    root_obj, page_cached = await _process_silkql_page(
        page,
        url,
        schema=schema,
        prompt=prompt,
        list_field_name=list_field_name,
        inner_model=inner_model,
        extraction_schema=extraction_schema,
        extraction_provider=provider,
        cleaner_provider=cleaner_lp,
        selector_provider=selector_lp,
        cache=cache,
        force_llm=force_llm,
        healer=heal,
    )
    return QueryResult(data=[root_obj], pages_scraped=1, cached=page_cached)


async def execute_query(
    url: str,
    silkql_string: str,
    *,
    provider: LLMProvider,
    cache: SelectorCache,
    cleaner_provider: LLMProvider | None = None,
    selector_provider: LLMProvider | None = None,
    follow_pagination: bool = False,
    max_pages: int = 20,
    force_llm: bool = False,
    **fetch_kwargs: Any,
) -> QueryResult:
    """
    Execute a SilkQL query using the LLM extraction pipeline.

    For root schemas with a single list collection (e.g. ``stories[]``),
    extraction is done against the **inner** (flat) model so LLMs return
    one row per item.  The flat rows are re-wrapped into the root model
    after extraction.

    Uses ``cleaner_model`` / ``selector_model`` from config (or optional
    ``cleaner_provider`` / ``selector_provider``) for HTML cleaning and selector
    compilation, matching :func:`silkweb.extract`.

    Set environment variable ``SILKWEB_TRACE_SILKQL=1`` to print per-field
    missing/null/empty counts and whether rows came from ``llm`` or
    ``selector_cache`` (stderr + structured log event ``silkql_extract_trace``).
    """
    cfg = get_config()
    cleaner_lp = cleaner_provider or create_provider(cfg.cleaner_model)
    selector_lp = selector_provider or create_provider(cfg.selector_model)
    healer = SelfHealer(max_attempts=max(1, int(cfg.max_retries)))

    ast = parse_silkql(silkql_string)
    schema = compile_query(silkql_string)
    prompt = _prompt_from_ast(ast)

    # Detect single list-at-root → extract flat rows and re-wrap
    list_info = _find_primary_list_field(schema)
    if list_info is not None:
        list_field_name, inner_model = list_info
    else:
        list_field_name, inner_model = None, None

    # Schema used for LLM extraction: flat inner model when available
    extraction_schema: type[BaseModel] = inner_model if inner_model is not None else schema

    pages_scraped = 0
    cached = False
    seen_urls: set[str] = set()

    current_url = url
    merged_model: BaseModel | None = None

    paginate = follow_pagination and _has_pagination_next(ast)

    while True:
        if current_url in seen_urls:
            break
        seen_urls.add(current_url)
        if pages_scraped >= max_pages:
            break

        page = await fetch_url(current_url, tier="auto", **fetch_kwargs)
        pages_scraped += 1

        root_obj, page_cached = await _process_silkql_page(
            page,
            current_url,
            schema=schema,
            prompt=prompt,
            list_field_name=list_field_name,
            inner_model=inner_model,
            extraction_schema=extraction_schema,
            extraction_provider=provider,
            cleaner_provider=cleaner_lp,
            selector_provider=selector_lp,
            cache=cache,
            force_llm=force_llm,
            healer=healer,
        )
        cached = cached or page_cached

        merged_model = (
            root_obj if merged_model is None else _merge_models(schema, merged_model, root_obj)
        )

        if not paginate:
            break

        # Pull next_page_url from nested pagination block (best-effort)
        next_url: str | None = None
        try:
            pag = getattr(merged_model, "pagination", None) if merged_model is not None else None
            if pag is not None:
                next_url = getattr(pag, "next_page_url", None)
        except Exception:
            next_url = None

        if not next_url:
            break
        current_url = urljoin(current_url, str(next_url))

    if merged_model is None:
        raise SilkwebExtractionError(message="SilkQL produced no output.", url=url)
    return QueryResult(data=[merged_model], pages_scraped=pages_scraped, cached=cached)
