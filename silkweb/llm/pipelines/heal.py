from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from ...cache.selectors import SelectorCache, dom_skeleton_hash
from ...explain import ExtractionReport
from ...exceptions import SilkwebExtractionError
from ...observability.logging import log_event
from ..pipelines.clean import clean_html
from ..pipelines.extract import extract_data
from ..pipelines.selectors import SelectorSet, compile_selectors
from ..providers.base import LLMProvider

ValidationFn = Callable[[list[dict[str, Any]], type[BaseModel]], bool]


@dataclass(slots=True)
class SelfHealer:
    max_attempts: int = 2
    #: Minimum fraction of rows that must be "OK" to skip healing (only evaluated when the
    #: schema has **no required fields**). Values outside ``[0, 1]`` are ignored. A row is OK
    #: if at least one schema field is non-``None``. When there are required fields, missing
    #: required values are handled by the required-field check above, not by this ratio.
    threshold: float | None = None
    validation_fn: ValidationFn | None = None

    def should_heal(self, results: list[dict[str, Any]], schema: type[BaseModel]) -> bool:
        if not results:
            return True

        required = [name for name, f in schema.model_fields.items() if f.is_required()]
        if required:
            for it in results:
                if any(it.get(k) is None for k in required):
                    return True

        if self.threshold is not None and (0.0 <= float(self.threshold) <= 1.0) and not required:
            schema_fields = list(schema.model_fields.keys())
            ok = 0
            for it in results:
                row_ok = any(it.get(k) is not None for k in schema_fields)
                if row_ok:
                    ok += 1
            ratio = ok / max(1, len(results))
            if ratio < float(self.threshold):
                return True

        if self.validation_fn is not None:
            try:
                if not bool(self.validation_fn(results, schema)):
                    return True
            except Exception:
                # Validation functions are user-supplied; on error we conservatively heal.
                return True

        return False


def _make_skeleton_key(html: str, schema: type[BaseModel]) -> str:
    """Build the compound cache key: dom skeleton hash + sorted schema field signatures."""
    raw = dom_skeleton_hash(html)
    parts = []
    for k, f in sorted(schema.model_fields.items()):
        ann = f.annotation
        type_name = getattr(ann, "__name__", str(ann))
        parts.append(f"{k}:{type_name}")
    return raw + ":" + "_".join(parts)


async def heal(
    *,
    url: str,
    html: str,
    schema: type[BaseModel],
    prompt: str,
    cleaner_provider: LLMProvider,
    extraction_provider: LLMProvider,
    selector_provider: LLMProvider,
    cache: SelectorCache,
    healer: SelfHealer | None = None,
    skeleton_key: str | None = None,
    report: ExtractionReport | None = None,
) -> list[dict[str, Any]]:
    """
    Self-healing loop for selector-based extraction failures.

    Steps:
    1) Invalidate cached selectors for domain+skeleton
    2) Re-run the full pipeline (clean → extract → compile → cache)
    3) Repeat up to max_attempts
    """
    h = healer or SelfHealer()
    domain = urlparse(url).netloc or urlparse(url).path.split("/")[0]
    skeleton = skeleton_key or _make_skeleton_key(html, schema)

    last_error: str | None = None
    for _attempt in range(max(1, int(h.max_attempts))):
        att_n = _attempt + 1
        att_max = max(1, int(h.max_attempts))
        t_att = time.perf_counter()
        log_event(
            "self_heal_triggered",
            url=url,
            tier=None,
            attempt=att_n,
            attempt_max=att_max,
            phase="heal",
        )
        cache.invalidate(domain, skeleton)
        dt_clean = dt_extract = dt_compile = 0.0
        try:
            t0 = time.perf_counter()
            cleaned = await clean_html(html, provider=cleaner_provider, strategy="auto")
            if report is not None:
                report.note_llm(cleaner_provider)
            dt_clean = time.perf_counter() - t0
            t1 = time.perf_counter()
            items = await extract_data(
                cleaned, schema=schema, prompt=prompt, provider=extraction_provider
            )
            if report is not None:
                report.note_llm(extraction_provider)
            dt_extract = time.perf_counter() - t1
            t2 = time.perf_counter()
            selector_set: SelectorSet = await compile_selectors(
                extracted=items, schema=schema, html=html, provider=selector_provider
            )
            if report is not None:
                report.note_llm(selector_provider)
            dt_compile = time.perf_counter() - t2
            cache.set(domain, skeleton, selector_set)
            log_event("selector_cached", url=url, tier=None, domain=domain, healed=True)
            log_event(
                "self_heal_attempt_pipeline_ok",
                url=url,
                tier=None,
                phase="heal",
                attempt=att_n,
                attempt_max=att_max,
                duration_ms=int((time.perf_counter() - t_att) * 1000),
                duration_clean_ms=int(dt_clean * 1000),
                duration_extract_ms=int(dt_extract * 1000),
                duration_compile_ms=int(dt_compile * 1000),
                items=len(items),
            )
        except Exception as e:
            last_error = repr(e)
            log_event(
                "self_heal_attempt_pipeline_error",
                url=url,
                tier=None,
                phase="heal",
                attempt=att_n,
                attempt_max=att_max,
                error=last_error,
                duration_clean_ms=int(dt_clean * 1000),
                duration_extract_ms=int(dt_extract * 1000),
                duration_compile_ms=int(dt_compile * 1000),
            )
            continue

        if not h.should_heal(items, schema):
            return items

        last_error = "healed_results_failed_validation"
        log_event(
            "self_heal_attempt_validation_failed",
            url=url,
            tier=None,
            phase="heal",
            attempt=att_n,
            attempt_max=att_max,
        )

    cache.invalidate(domain, skeleton)
    raise SilkwebExtractionError(
        message="Self-healing failed to produce valid results.",
        url=url,
        context={"domain": domain, "skeleton_hash": skeleton, "last_error": last_error},
    )
