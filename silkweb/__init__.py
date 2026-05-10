"""
Silkweb public API surface.

Project overview and design live in the repository README.md.
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import asyncio
import contextlib
import json
import sys
import threading
from importlib.metadata import PackageNotFoundError, version
from typing import Any, cast

_SYNC_LOOP: asyncio.AbstractEventLoop | None = None
_SYNC_LOCK = threading.Lock()


def _get_sync_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for sync wrappers.

    Using a single loop avoids the 'Event loop is closed' crash on Windows
    that occurs when ``anyio.run()`` repeatedly creates and destroys loops
    while httpx ``AsyncClient`` instances are cached from a prior loop.
    """
    global _SYNC_LOOP
    if _SYNC_LOOP is not None and not _SYNC_LOOP.is_closed():
        return _SYNC_LOOP
    with _SYNC_LOCK:
        if _SYNC_LOOP is not None and not _SYNC_LOOP.is_closed():
            return _SYNC_LOOP
        loop = asyncio.new_event_loop()
        _SYNC_LOOP = loop
        return loop


def _run_sync(coro):
    """Run a coroutine on the persistent sync event loop."""
    loop = _get_sync_loop()
    return loop.run_until_complete(coro)


from .cache.manager import CacheManager
from .cache.selectors import SelectorCache
from .config import SilkwebConfig, configure, get_config
from .crawl.crawler import AsyncCrawler
from .discover import discover_api as _async_discover_api
from .explain import ExtractionReport, pydantic_schema_line, render as _render_extraction_report
from .exceptions import (
    SilkwebBlockedError,
    SilkwebCacheError,
    SilkwebConfigError,
    SilkwebError,
    SilkwebExtractionError,
    SilkwebFetchError,
    SilkwebHTTPError,
    SilkwebLLMError,
    SilkwebRenderError,
    SilkwebSchemaError,
    SilkwebSelectorError,
    SilkwebSessionError,
    SilkwebSessionExpiredError,
    SilkwebTimeoutError,
)
from .fetch.orchestrator import fetch as _async_fetch
from .llm.pipelines.clean import CleanedContent, clean_html
from .llm.pipelines.heal import SelfHealer
from .llm.pipelines.orchestrator import extract_url as _extract_url
from .llm.pipelines.schema import synthesize_schema
from .llm.providers.registry import create_provider
from .observability.logging import log_event
from .observability.replay import ReplaySession as _ReplaySession
from .observability.replay import replay as _replay
from .recipes.registry import recipes
from .session.recorder import record as record_session
from .session.recorder import replay as replay_session
from .session.session import SilkSession
from .silkql.executor import QueryResult
from .silkql.executor import execute_query as _execute_query
from .silkql.executor import execute_query_from_html as _execute_query_from_html
from .watch import Watcher


class _CacheFacade:
    """
    Small convenience wrapper so docs can use `silkweb.cache.*`.

    This delegates to `CacheManager.from_config()` on each call so it always reflects
    current configuration.
    """

    def clear(self, *, layer: str | None = None, domain: str | None = None) -> None:
        CacheManager.from_config().clear(layer=layer, domain=domain)  # type: ignore[arg-type]

    def stats(self) -> dict[str, Any]:
        return CacheManager.from_config().stats()


cache = _CacheFacade()

try:
    __version__ = version("silkweb")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "QueryResult",
    "SilkSession",
    "SilkwebBlockedError",
    "SilkwebCacheError",
    "SilkwebConfig",
    "SilkwebConfigError",
    "SilkwebError",
    "SilkwebExtractionError",
    "SilkwebFetchError",
    "SilkwebHTTPError",
    "SilkwebLLMError",
    "SilkwebRenderError",
    "SilkwebSchemaError",
    "SilkwebSelectorError",
    "SilkwebSessionError",
    "SilkwebSessionExpiredError",
    "SilkwebTimeoutError",
    "ask",
    "async_ask",
    "async_crawl",
    "async_crawl_sitemap",
    "async_extract",
    "async_extract_from_html",
    "async_fetch",
    "async_query",
    "cache",
    "configure",
    "crawl",
    "crawl_sitemap",
    "discover_api",
    "extract",
    "fetch",
    "get_config",
    "query",
    "query_from_html",
    "recipes",
    "record_session",
    "replay",
    "replay_session",
    "watch",
]


def replay(session_file: str) -> _ReplaySession:
    """
    Load an **HTTP fetch replay** bundle (JSON ``*.silkweb`` + HTML sibling) written when
    ``configure(replay_dir=...)`` is set. Returns :class:`observability.replay.ReplaySession`
    with ``.html`` / ``.ask()`` / ``.extract()`` / ``.query()`` helpers.

    This is **not** the same as :func:`replay_session`, which replays a **Playwright**
    recording from ``record_session`` (cookies and actions under ``~/.silkweb/sessions``).
    """
    return _replay(session_file)


async def _ask_from_html(
    url: str,
    html: str,
    *,
    prompt: str,
    cleaner_model: str | None = None,
    schema_model: str | None = None,
    extraction_model: str | None = None,
    selector_model: str | None = None,
    force_llm: bool | None = None,
    output: str = "auto",
    dataframe_engine: str = "auto",
):
    cfg = get_config()
    if force_llm is None:
        force_llm = bool(cfg.force_llm)
    cleaner_provider = create_provider(cleaner_model or cfg.cleaner_model)
    schema_provider = create_provider(schema_model or cfg.schema_model)
    extraction_provider = create_provider(extraction_model or cfg.extraction_model)
    selector_provider = create_provider(selector_model or cfg.selector_model)
    cleaned = await clean_html(html, provider=cleaner_provider, strategy="auto")
    schema = await synthesize_schema(cleaned, prompt=prompt, provider=schema_provider)
    from .cache.manager import CacheManager as _CM

    selector_cache = _CM.from_config().selectors
    healer = SelfHealer(max_attempts=max(1, int(cfg.max_retries)))
    items = await _extract_url(
        url=url,
        html=html,
        schema=schema,
        prompt=prompt,
        cleaner_provider=cleaner_provider,
        extraction_provider=extraction_provider,
        selector_provider=selector_provider,
        selector_cache=selector_cache,
        healer=healer,
        force_llm=bool(force_llm),
    )
    out_fmt = str(output or "auto").lower()
    if out_fmt in {"df", "dataframe"}:
        from .output.dataframe import to_dataframe

        df = to_dataframe(items, engine=cast(Any, dataframe_engine))
        return df if df is not None else items
    if out_fmt in {"python", "list", "dict"}:
        return items
    df = _maybe_to_dataframe(items)
    return df if df is not None else items


def ask_from_html(url: str, html: str, *, prompt: str, **kwargs: Any):
    return _run_sync(_ask_from_html(url, html, prompt=prompt, **kwargs))


async def async_extract_from_html(
    url: str,
    html: str,
    *,
    schema,
    prompt: str,
    output: str = "python",
    dataframe_engine: str = "auto",
    **kwargs: Any,
):
    """
    Same extraction contract as `async_extract`, but uses pre-fetched HTML (no network fetch).

    Returns `list[BaseModel]` by default, or a DataFrame when ``output="df"`` / ``"dataframe"``,
    or auto-converts like `async_extract` when ``output="auto"``.
    """
    from pydantic import BaseModel

    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise TypeError("schema must be a Pydantic BaseModel type")
    _normalize_extract_output(output)

    cfg = get_config()
    cleaner_model = cast(str, kwargs.pop("cleaner_model", cfg.cleaner_model))
    extraction_model = cast(str, kwargs.pop("extraction_model", cfg.extraction_model))
    selector_model = cast(str, kwargs.pop("selector_model", cfg.selector_model))
    force_llm = bool(kwargs.pop("force_llm", cfg.force_llm))

    selector_cache = CacheManager.from_config().selectors
    healer = SelfHealer(max_attempts=max(1, int(cfg.max_retries)))
    items = await _extract_url(
        url=url,
        html=html,
        schema=schema,
        prompt=prompt,
        cleaner_provider=create_provider(cleaner_model),
        extraction_provider=create_provider(extraction_model),
        selector_provider=create_provider(selector_model),
        selector_cache=selector_cache,
        healer=healer,
        force_llm=force_llm,
    )
    return _finalize_extract_output(
        items,
        schema,
        output=output,
        dataframe_engine=dataframe_engine,
    )


def extract_from_html(url: str, html: str, *, schema: Any, prompt: str, **kwargs: Any):
    """Sync wrapper around `async_extract_from_html` (same return contract as `extract`)."""
    return _run_sync(async_extract_from_html(url, html, schema=schema, prompt=prompt, **kwargs))


async def _query_from_html(
    url: str,
    html: str,
    *,
    silkql_string: str,
    provider=None,
    cache: SelectorCache | None = None,
    force_llm: bool | None = None,
    **kwargs: Any,
):
    """Run SilkQL on pre-fetched HTML (same pipeline as ``async_query`` for one page)."""
    cfg = get_config()
    prov = provider or create_provider(cfg.extraction_model)
    cleaner_model = cast(str, kwargs.pop("cleaner_model", cfg.cleaner_model))
    selector_model = cast(str, kwargs.pop("selector_model", cfg.selector_model))
    selector_cache = cache or CacheManager.from_config().selectors
    return await _execute_query_from_html(
        url,
        html,
        silkql_string,
        provider=prov,
        cache=selector_cache,
        cleaner_provider=create_provider(cleaner_model),
        selector_provider=create_provider(selector_model),
        force_llm=bool(cfg.force_llm if force_llm is None else force_llm),
        healer=SelfHealer(max_attempts=max(1, int(cfg.max_retries))),
    )


def query_from_html(url: str, html: str, *, silkql_string: str, **kwargs: Any):
    """Sync SilkQL on existing HTML. Same pipeline as :func:`async_query` for a single page; see :func:`async_query` for options."""
    return _run_sync(_query_from_html(url, html, silkql_string=silkql_string, **kwargs))


def fetch(url: str, *args, **kwargs):
    """Fetch a URL and return a `SilkPage`."""
    return _run_sync(_async_fetch(url, *args, **kwargs))


async def async_fetch(url: str, *args, **kwargs):
    """Async variant of `fetch`."""
    return await _async_fetch(url, *args, **kwargs)


def discover_api(url: str, session: SilkSession | None = None, *, output_path: str | None = None):
    """Discover JSON API endpoints for a URL."""
    return _run_sync(_async_discover_api(url, session, output_path))


def _maybe_to_dataframe(items: list[dict[str, Any]]):
    # Only auto-convert if user already imported a DF library.
    cfg = get_config()
    if not cfg.auto_detect_dataframe:
        return None
    if "pandas" in sys.modules:
        import pandas as pd  # type: ignore

        return pd.DataFrame(items)
    if "polars" in sys.modules:
        import polars as pl  # type: ignore

        return pl.DataFrame(items)
    return None


_EXTRACT_OUTPUTS = frozenset({"python", "list", "dict", "auto", "df", "dataframe"})


def _normalize_extract_output(output: str) -> str:
    out = str(output or "python").lower().strip()
    if out not in _EXTRACT_OUTPUTS:
        allowed = ", ".join(sorted(_EXTRACT_OUTPUTS))
        raise ValueError(f"Invalid extract output={output!r}. Use one of: {allowed}")
    return out


def _finalize_extract_output(
    items: list[dict[str, Any]],
    schema: type[Any],
    *,
    output: str,
    dataframe_engine: str,
) -> Any:
    """Validate dict rows to `schema`, attach meta, apply output / DataFrame rules."""
    from pydantic import BaseModel

    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise TypeError("schema must be a Pydantic BaseModel type")

    out_fmt = _normalize_extract_output(output)
    out_models: list[BaseModel] = []
    for it in items:
        payload = {k: v for k, v in it.items() if k in schema.model_fields}
        obj = schema.model_validate(payload)
        meta = it.get("__silk_meta__")
        if meta is not None:
            with contextlib.suppress(Exception):
                object.__setattr__(obj, "__silk_meta__", meta)
        out_models.append(obj)

    if out_fmt in {"df", "dataframe"}:
        from .output.dataframe import to_dataframe

        df = to_dataframe(out_models, engine=cast(Any, dataframe_engine))
        return df if df is not None else out_models

    if out_fmt in {"python", "list", "dict"}:
        return out_models

    if out_fmt == "auto":
        cfg = get_config()
        if cfg.auto_detect_dataframe and ("pandas" in sys.modules or "polars" in sys.modules):
            payload_rows = [o.model_dump() for o in out_models]
            df = _maybe_to_dataframe(payload_rows)
            if df is not None:
                return df
        return out_models

    return out_models


def _cleaned_from_hydration(hydration: Any, *, heading: str | None) -> CleanedContent:
    payload = json.dumps(hydration, ensure_ascii=False)
    flat = json.dumps({"heading": heading or "", "items": [payload]}, ensure_ascii=False)
    token_estimate = max(1, int(len(payload) / 4))
    return CleanedContent(flat_json=flat, markdown=payload, token_estimate=token_estimate)


def _best_effort_hydration_subset(hydration: dict[str, Any]) -> Any:
    """
    Try to pick the most stable, smallest subset of common SSR hydration payloads.
    Falls back to the full dict if no known structure is found.
    """
    # Next.js: __NEXT_DATA__ typically contains props.pageProps with the meaningful data.
    props = hydration.get("props")
    if isinstance(props, dict):
        page_props = props.get("pageProps")
        if page_props is not None:
            return page_props

    # Nuxt: extremely variable; keep it small when possible.
    state = hydration.get("state")
    if state is not None:
        return state

    data = hydration.get("data")
    if data is not None:
        return data

    return hydration


def ask(
    url: str,
    prompt: str,
    *,
    explain: bool = False,
    **fetch_kwargs: Any,
):
    """Sync wrapper around `async_ask`."""
    return _run_sync(async_ask(url, prompt, explain=explain, **fetch_kwargs))


async def async_ask(
    url: str,
    prompt: str,
    *,
    output: str = "auto",
    dataframe_engine: str = "auto",
    explain: bool = False,
    **fetch_kwargs: Any,
):
    """
    Ask a natural-language question of a URL.

    Pipeline:
    - fetch (auto tier)
    - hydration-first (optional: use hydration JSON as cleaned content)
    - otherwise clean → synthesize schema → extract → compile selectors → cache
    - output selection:
      - output="python": list[dict]
      - output="df": DataFrame (pandas/polars) if available
      - output="auto": backward-compatible auto-conversion when caller already imported pandas/polars
    """
    fetch_kwargs = dict(fetch_kwargs)

    cfg = get_config()

    cleaner_model = cast(str, fetch_kwargs.pop("cleaner_model", cfg.cleaner_model))
    schema_model = cast(str, fetch_kwargs.pop("schema_model", cfg.schema_model))
    extraction_model = cast(str, fetch_kwargs.pop("extraction_model", cfg.extraction_model))
    selector_model = cast(str, fetch_kwargs.pop("selector_model", cfg.selector_model))
    force_llm = bool(fetch_kwargs.pop("force_llm", cfg.force_llm))
    hydration_first = bool(fetch_kwargs.pop("hydration_first", cfg.hydration_first))
    hydration_subset = bool(fetch_kwargs.pop("hydration_subset", cfg.hydration_subset))
    hydration_max_chars = int(fetch_kwargs.pop("hydration_max_chars", cfg.hydration_max_chars))

    import time as _t

    report: ExtractionReport | None = ExtractionReport() if explain else None
    _wall0 = _t.time()

    _t0 = _t.time()
    page = await _async_fetch(url, tier="auto", **fetch_kwargs)
    _t_fetch = _t.time() - _t0
    log_event(
        "ask_fetch_done",
        url=url,
        tier=getattr(page, "fetch_tier", None),
        duration_ms=int(_t_fetch * 1000),
        html_chars=len(page.html or ""),
    )

    if report is not None:
        from .explain import tier_name_for_page

        report.tier_used = int(getattr(page, "fetch_tier", 0) or 0)
        report.tier_name = tier_name_for_page(report.tier_used, page)

    selector_cache = CacheManager.from_config().selectors

    cleaner_provider = create_provider(cleaner_model)
    schema_provider = create_provider(schema_model)
    extraction_provider = create_provider(extraction_model)
    selector_provider = create_provider(selector_model)
    healer = SelfHealer(max_attempts=max(1, int(cfg.max_retries)))

    hydration = page.hydration_data() if hydration_first else None
    if isinstance(hydration, dict) and hydration_subset:
        hydration_any: Any = _best_effort_hydration_subset(hydration)
    else:
        hydration_any = hydration

    hydration_payload = None
    if hydration_any is not None:
        with contextlib.suppress(Exception):
            hydration_payload = json.dumps(hydration_any, ensure_ascii=False)

    if (
        hydration_any is not None
        and hydration_payload is not None
        and 0 < hydration_max_chars < len(hydration_payload)
    ):
        log_event(
            "ask_hydration_skipped",
            url=url,
            tier=getattr(page, "fetch_tier", None),
            reason="too_large",
            hydration_chars=len(hydration_payload),
            max_chars=hydration_max_chars,
        )
        hydration_any = None

    if hydration_any is not None:
        cleaned = _cleaned_from_hydration(
            hydration_any, heading=str(page.metadata.get("title") or "")
        )
        log_event(
            "ask_clean_done",
            url=url,
            tier=getattr(page, "fetch_tier", None),
            method="hydration",
            hydration_chars=len(cleaned.markdown),
        )
    else:
        _t1 = _t.time()
        cleaned = await clean_html(page.html, provider=cleaner_provider, strategy="auto")
        log_event(
            "ask_clean_done",
            url=url,
            tier=getattr(page, "fetch_tier", None),
            method="clean_html",
            duration_ms=int((_t.time() - _t1) * 1000),
            token_estimate=getattr(cleaned, "token_estimate", None),
        )

    if report is not None:
        if hydration_any is not None:
            report.hydration_source = page.hydration_source()
        else:
            report.hydration_source = None

    _t2 = _t.time()
    log_event("ask_schema_start", url=url, tier=getattr(page, "fetch_tier", None))
    schema = await synthesize_schema(cleaned, prompt=prompt, provider=schema_provider)
    log_event(
        "ask_schema_done",
        url=url,
        tier=getattr(page, "fetch_tier", None),
        duration_ms=int((_t.time() - _t2) * 1000),
        fields=list(getattr(schema, "model_fields", {}).keys()),
    )

    if report is not None:
        report.note_llm(schema_provider)
        report.schema_inferred = pydantic_schema_line(schema)

    _t3 = _t.time()
    log_event("ask_extract_start", url=url, tier=getattr(page, "fetch_tier", None))
    items = await _extract_url(
        url=url,
        html=page.html,
        schema=schema,
        prompt=prompt,
        cleaner_provider=cleaner_provider,
        extraction_provider=extraction_provider,
        selector_provider=selector_provider,
        selector_cache=selector_cache,
        healer=healer,
        force_llm=force_llm,
        report=report,
    )
    log_event(
        "ask_extract_done",
        url=url,
        tier=getattr(page, "fetch_tier", None),
        duration_ms=int((_t.time() - _t3) * 1000),
        items=len(items),
    )

    if report is not None:
        report.records_extracted = len(items)
        report.total_duration_ms = (_t.time() - _wall0) * 1000.0
        _render_extraction_report(report)

    # Scalar convenience: single item + single field
    if len(items) == 1 and len(schema.model_fields) == 1:
        only_key = next(iter(schema.model_fields.keys()))
        return items[0].get(only_key)

    out_fmt = str(output or "auto").lower()
    if out_fmt in {"df", "dataframe"}:
        from .output.dataframe import to_dataframe

        df = to_dataframe(items, engine=cast(Any, dataframe_engine))
        return df if df is not None else items

    if out_fmt in {"python", "list", "dict"}:
        return items

    # Backward-compatible "auto": only auto-convert if caller already imported pandas/polars.
    df = _maybe_to_dataframe(items)
    return df if df is not None else items


def extract(url: str, schema, prompt: str, *, explain: bool = False, **kwargs: Any):
    """Sync wrapper around `async_extract`."""
    return _run_sync(async_extract(url, schema, prompt, explain=explain, **kwargs))


async def async_extract(
    url: str,
    schema,
    prompt: str,
    *,
    output: str = "python",
    dataframe_engine: str = "auto",
    explain: bool = False,
    **kwargs: Any,
):
    """
    Extract typed data from a URL using a provided Pydantic schema.

    - selector cache fast-path
    - self-heal on validation failure
    - ``output`` controls the return shape:
      - ``"python"`` / ``"list"`` / ``"dict"``: ``list[BaseModel]`` with ``__silk_meta__`` when present
      - ``"df"`` / ``"dataframe"``: pandas or polars DataFrame (see ``dataframe_engine``), else falls back to list
      - ``"auto"``: same as historical behavior — DataFrame only if ``auto_detect_dataframe`` and pandas/polars already imported
    """
    from pydantic import BaseModel

    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise TypeError("schema must be a Pydantic BaseModel type")
    _normalize_extract_output(output)

    cfg = get_config()
    cleaner_model = cast(str, kwargs.pop("cleaner_model", cfg.cleaner_model))
    extraction_model = cast(str, kwargs.pop("extraction_model", cfg.extraction_model))
    selector_model = cast(str, kwargs.pop("selector_model", cfg.selector_model))
    force_llm = bool(kwargs.pop("force_llm", cfg.force_llm))

    import time as _t

    report: ExtractionReport | None = ExtractionReport() if explain else None
    _wall0 = _t.time()

    _t0 = _t.time()
    page = await _async_fetch(url, tier="auto", **kwargs)
    _t_fetch = _t.time() - _t0
    log_event(
        "extract_fetch_done",
        url=url,
        tier=getattr(page, "fetch_tier", None),
        duration_ms=int(_t_fetch * 1000),
        html_chars=len(page.html or ""),
    )

    if report is not None:
        from .explain import tier_name_for_page

        report.tier_used = int(getattr(page, "fetch_tier", 0) or 0)
        report.tier_name = tier_name_for_page(report.tier_used, page)
        report.hydration_source = None
        report.schema_inferred = pydantic_schema_line(schema)

    selector_cache = CacheManager.from_config().selectors

    healer = SelfHealer(max_attempts=max(1, int(cfg.max_retries)))
    _t1 = _t.time()
    log_event("extract_llm_start", url=url, tier=getattr(page, "fetch_tier", None))
    items = await _extract_url(
        url=url,
        html=page.html,
        schema=schema,
        prompt=prompt,
        cleaner_provider=create_provider(cleaner_model),
        extraction_provider=create_provider(extraction_model),
        selector_provider=create_provider(selector_model),
        selector_cache=selector_cache,
        healer=healer,
        force_llm=force_llm,
        report=report,
    )
    log_event(
        "extract_llm_done",
        url=url,
        tier=getattr(page, "fetch_tier", None),
        duration_ms=int((_t.time() - _t1) * 1000),
        items=len(items),
    )

    if report is not None:
        report.records_extracted = len(items)
        report.total_duration_ms = (_t.time() - _wall0) * 1000.0
        _render_extraction_report(report)

    return _finalize_extract_output(
        items,
        schema,
        output=output,
        dataframe_engine=dataframe_engine,
    )


def query(*args, **kwargs):
    """Compile and run a SilkQL query (sync). Arguments and return type match :func:`async_query`."""
    return _run_sync(async_query(*args, **kwargs))


async def async_query(
    url: str,
    silkql_string: str,
    *,
    provider=None,
    cache: SelectorCache | None = None,
    follow_pagination: bool = False,
    max_pages: int = 20,
    **fetch_kwargs: Any,
) -> QueryResult:
    """
    Compile and run a SilkQL query against ``url``.

    Fetches the page (tier ``"auto"`` by default; pass ``tier=`` like :func:`fetch`),
    extracts with the compiled schema, caches CSS/XPath selectors per domain, and returns
    a :class:`QueryResult` whose ``data`` is a one-element list containing the merged root
    model (list collections are merged across pages when ``follow_pagination`` is true).

    - ``provider``: extraction LLM; defaults to ``configure(extraction_model=...)``.
    - ``cleaner_model`` / ``selector_model``: optional model strings (popped from ``**fetch_kwargs``),
      defaulting to config — same split as :func:`extract`.
    - ``cache``: selector cache instance; defaults to ``CacheManager.from_config().selectors``.
    - ``follow_pagination``: when the SilkQL AST includes ``pagination { next_page_url }``, follow
      relative/absolute next links up to ``max_pages``.
    - ``force_llm``: skip selector cache (popped from ``fetch_kwargs``, default ``configure(force_llm=...)``).
    - ``cached`` on the result is true if **any** scraped page used a selector-cache hit.
    """
    cfg = get_config()
    prov = provider or create_provider(cfg.extraction_model)
    selector_cache = cache or CacheManager.from_config().selectors
    force_llm = bool(fetch_kwargs.pop("force_llm", cfg.force_llm))
    cleaner_model = cast(str, fetch_kwargs.pop("cleaner_model", cfg.cleaner_model))
    selector_model = cast(str, fetch_kwargs.pop("selector_model", cfg.selector_model))
    return await _execute_query(
        url,
        silkql_string,
        provider=prov,
        cache=selector_cache,
        cleaner_provider=create_provider(cleaner_model),
        selector_provider=create_provider(selector_model),
        follow_pagination=follow_pagination,
        max_pages=max_pages,
        force_llm=force_llm,
        **fetch_kwargs,
    )


def crawl(*args, **kwargs):
    """
    Multi-page crawl (sync). See :func:`async_crawl` for parameters and return value.

    Returns a list of extracted ``BaseModel`` instances when ``schema`` and ``prompt`` are
    both set; otherwise pages are still fetched (hooks only) and the result is an empty list.
    """
    return _run_sync(async_crawl(*args, **kwargs))


async def async_crawl(
    start_url: str,
    *,
    allowed_domains: set[str] | None = None,
    url_pattern: str | None = None,
    max_pages: int = 100,
    max_depth: int = 2,
    concurrency: int = 10,
    per_domain_concurrency: int = 2,
    max_pending_urls: int = 5000,
    schema=None,
    prompt: str | None = None,
    on_page=None,
    on_item=None,
    on_error=None,
    **fetch_kwargs: Any,
):
    """
    Breadth-first crawl from ``start_url`` with URL dedup, global and per-domain concurrency,
    and optional structured extraction on each page.

    - ``schema`` / ``prompt``: both required together for extraction; if both omitted, only
      ``on_page`` / link discovery run and the returned list is empty.
    - ``max_pages``: hard cap on fetched pages.
    - ``max_depth``: link-following depth from the start URL (0 = start page only).
    - ``max_pending_urls``: best-effort cap on the crawl work-queue size to limit memory.
    - ``on_page``, ``on_item``, ``on_error``: optional async callbacks (page after fetch, each
      extracted model, errors per URL).
    - Remaining keyword arguments are passed to the fetcher (same as :func:`fetch`).
    """
    from pydantic import BaseModel

    if (schema is not None) ^ (prompt is not None):
        raise ValueError("async_crawl requires both schema and prompt together, or neither")

    if schema is not None and (not isinstance(schema, type) or not issubclass(schema, BaseModel)):
        raise TypeError("schema must be a Pydantic BaseModel type")

    crawler = AsyncCrawler(
        start_url=start_url,
        allowed_domains=allowed_domains,
        url_pattern=url_pattern,
        max_pages=max_pages,
        max_depth=max_depth,
        concurrency=concurrency,
        per_domain_concurrency=per_domain_concurrency,
        max_pending_urls=max_pending_urls,
        schema=schema,
        prompt=prompt,
        on_page=on_page,
        on_item=on_item,
        on_error=on_error,
    )
    out: list[BaseModel] = []
    async for item in crawler.run(**fetch_kwargs):
        out.append(item)
    return out


def crawl_sitemap(*args, **kwargs):
    """Sync wrapper around :func:`async_crawl_sitemap`."""
    return _run_sync(async_crawl_sitemap(*args, **kwargs))


async def async_crawl_sitemap(
    sitemap_url: str,
    *,
    schema=None,
    prompt: str | None = None,
    max_pages: int = 100,
    max_sitemap_files: int = 20,
    concurrency: int = 10,
    per_domain_concurrency: int = 2,
    **fetch_kwargs: Any,
):
    """
    Fetch a sitemap (``urlset`` or ``sitemapindex``), collect page ``<loc>`` URLs via XML
    parsing, then run :func:`async_crawl` on each (``max_depth=0``, ``max_pages=1`` per URL).

    ``allowed_domains`` for each crawl defaults to the sitemap URL host. Pass ``max_sitemap_files``
    to cap nested sitemap documents when the root is an index.
    """
    from pydantic import BaseModel

    from .crawl.sitemap import collect_page_urls_from_sitemap, host_allowed_domains

    if (schema is not None) ^ (prompt is not None):
        raise ValueError("async_crawl_sitemap requires both schema and prompt together, or neither")

    if schema is not None and (not isinstance(schema, type) or not issubclass(schema, BaseModel)):
        raise TypeError("schema must be a Pydantic BaseModel type")

    allowed = host_allowed_domains(sitemap_url)
    locs = await collect_page_urls_from_sitemap(
        _async_fetch,
        sitemap_url,
        max_pages=max_pages,
        max_sitemap_files=max_sitemap_files,
        **fetch_kwargs,
    )
    results: list[Any] = []
    for loc in locs:
        results.extend(
            await async_crawl(
                loc,
                schema=schema,
                prompt=prompt,
                allowed_domains=allowed,
                max_pages=1,
                max_depth=0,
                concurrency=concurrency,
                per_domain_concurrency=per_domain_concurrency,
                **fetch_kwargs,
            )
        )
    return results


def watch(*args, **kwargs) -> Watcher:
    """
    Create a Watcher instance (use `await watcher.start()` to begin).
    """
    return Watcher(*args, **kwargs)
