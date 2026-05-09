from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from ...config import SilkwebConfig, get_config
from ...exceptions import SilkwebLLMError, SilkwebSchemaError
from ...parse.page import SilkMeta
from ..chunking.dispatcher import chunk_content
from ..pipelines.clean import CleanedContent
from ..providers.base import LLMProvider, Message

Chunker = Callable[[CleanedContent, str, LLMProvider], list[str]]

# Counts human-facing numbers in plain text (prices, star counts, "1,234", years with 4 digits, etc.).
_NUMERIC_TOKEN_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"  # 1,234 or 50,329.5
    r"|\b\d{4,}(?:\.\d+)?\b"  # 2024, 50329
    r"|\b\d{2,3}(?:\.\d+)?\b"
)


def _numeric_token_count(s: str) -> int:
    return len(_NUMERIC_TOKEN_RE.findall(s or ""))


def _extraction_text_blob(cleaned: CleanedContent) -> str:
    """Markdown plus flat_json human strings (heading + items), for comparing to HTML text."""
    parts: list[str] = [cleaned.markdown or ""]
    try:
        d = json.loads(cleaned.flat_json or "{}")
        h = d.get("heading")
        if isinstance(h, str) and h.strip():
            parts.append(h)
        items = d.get("items")
        if isinstance(items, list):
            parts.extend(str(x) for x in items if x is not None and str(x).strip())
    except Exception:
        parts.append(cleaned.flat_json or "")
    return "\n".join(parts)


def _tag_stripped_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _html_excerpt_richer_than_text_view(cleaned: CleanedContent) -> bool:
    """
    True when stripped HTML still encodes many numeric/listing tokens that the
    markdown + flat_json view largely lost (common trafilatura behavior on dense UIs).

    Site-agnostic complement to ``degraded_catalog_signal`` (which targets price-token grids).
    """
    ex = (cleaned.html_excerpt or "").strip()
    if len(ex) < 200:
        return False
    blob = _extraction_text_blob(cleaned)
    blob_s = re.sub(r"\s+", " ", blob).strip()
    html_text = _tag_stripped_text(ex)
    n_html = _numeric_token_count(html_text)
    n_plain = _numeric_token_count(blob_s)
    if n_html < 8:
        return False
    if n_plain > max(4, n_html // 4):
        return False
    # Avoid switching for long-form pages where markdown already carries most content.
    if len(blob_s) > 14_000:
        return False
    return len(blob_s) <= max(2_500, int(len(html_text) * 0.42))


def _is_price_or_stock_token(s: str) -> bool:
    t = (s or "").strip().lower()
    if not t:
        return False
    if t in ("in stock", "out of stock", "pre-order", "available"):
        return True
    if len(t) > 28:
        return False
    remainder = re.sub(r"[\d\s.,€£$¥₹₽\-]+", "", t)
    return len(remainder) <= 1


def _string_list_looks_like_degraded_catalog(lines: list[str]) -> bool:
    """Detect trafilatura-style loss: many short price/stock tokens, few substantive text lines."""
    strs = [str(x).strip() for x in lines if str(x).strip()]
    if len(strs) < 6:
        return False
    priceish = sum(1 for s in strs if _is_price_or_stock_token(s))
    substantive = sum(1 for s in strs if len(s) > 22 and not _is_price_or_stock_token(s))
    return priceish >= len(strs) * 0.28 and substantive <= max(4, len(strs) // 4)


def degraded_catalog_signal(cleaned: CleanedContent) -> bool:
    """
    True when flat_json / markdown look like a catalog grid collapsed to price rows
    (so extraction should prefer ``html_excerpt`` in ``auto`` mode).
    """
    try:
        d = json.loads(cleaned.flat_json or "{}")
        items = d.get("items")
        if (
            isinstance(items, list)
            and all(isinstance(x, str) for x in items)
            and _string_list_looks_like_degraded_catalog(items)
        ):
            return True
    except Exception:
        pass
    md_lines = [ln.strip() for ln in (cleaned.markdown or "").splitlines() if ln.strip()]
    return _string_list_looks_like_degraded_catalog(md_lines)


def _llm_body_slice(cfg: SilkwebConfig, storage_cap: int, body: str) -> str:
    """Clamp extraction payload body by storage cap and ``extraction_prompt_body_max_chars``."""
    hard = max(1024, int(storage_cap))
    # Allow caps below 1024 for tests/small prompts (floor avoids accidental empty slices).
    soft = max(256, int(cfg.extraction_prompt_body_max_chars))
    return body[: min(hard, soft)]


def choose_extraction_payload(cleaned: CleanedContent, *, representation: str | None = None) -> str:
    """
    Pick the JSON string passed to the LLM for extraction.

    - ``flat_json``: legacy compact ``CleanedContent.flat_json``.
    - ``markdown``: ``{"format":"markdown","body":...}`` from cleaned markdown.
    - ``slim_html``: ``{"format":"html_excerpt","body":...}`` from ``html_excerpt`` (stripped HTML).
    - ``auto`` (default): flat_json for normal pages; when ``html_excerpt`` is present, use it
      if flat_json/markdown look like a degraded product grid *or* the HTML text still
      contains many more numeric listing tokens than the markdown/flat view (typical when
      readers drop table/grid metrics that remain in the DOM).
      HTML/markdown bodies are further capped by ``extraction_prompt_body_max_chars`` so API
      models receive a bounded prompt (oversized envelopes often yield empty ``items``).
    """
    cfg = get_config()
    rep = (representation or cfg.representation or "auto").strip().lower()

    if rep == "markdown":
        cap = max(1024, int(cfg.extraction_markdown_max_chars))
        body = _llm_body_slice(cfg, cap, cleaned.markdown or "")
        return json.dumps({"format": "markdown", "body": body}, ensure_ascii=False)

    if rep == "slim_html":
        cap = max(1024, int(cfg.extraction_html_max_chars))
        ex = (cleaned.html_excerpt or "").strip()
        if not ex:
            return cleaned.flat_json
        body = _llm_body_slice(cfg, cap, ex)
        return json.dumps({"format": "html_excerpt", "body": body}, ensure_ascii=False)

    if rep == "flat_json":
        return cleaned.flat_json

    # auto
    if degraded_catalog_signal(cleaned) or _html_excerpt_richer_than_text_view(cleaned):
        ex = (cleaned.html_excerpt or "").strip()
        if ex:
            cap = max(1024, int(cfg.extraction_html_max_chars))
            body = _llm_body_slice(cfg, cap, ex)
            return json.dumps({"format": "html_excerpt", "body": body}, ensure_ascii=False)
    return cleaned.flat_json


def _system_prompt(
    prompt: str, schema: type[BaseModel], *, include_validation_error: str | None
) -> str:
    base = (
        "You are a web data extractor.\n"
        "You are given cleaned page content as ONE JSON object and a user request.\n"
        "The JSON uses one of these shapes:\n"
        '- Legacy: {"heading": "...", "items": ["line", ...]} (article-style lines).\n'
        '- Markdown: {"format":"markdown","body":"..."} — extract from the body text.\n'
        '- HTML excerpt: {"format":"html_excerpt","body":"<html>..."} — dense listings; '
        "use element text and attributes (e.g. title= on links) for each record.\n"
        "Return ONLY JSON with this shape:\n"
        '{ "items": [ <object matching the schema fields> , ... ] }\n'
        "IMPORTANT:\n"
        "- For EACH returned item, include an `__xpath__` object mapping each field name to the source XPath.\n"
        '  Example: {"name": "Widget", "price": 10.0, "__xpath__": {"name": "/html/...", "price": "/html/..."}}\n'
        "- Do not include markdown fences or extra keys besides schema fields and `__xpath__`.\n"
        "- Use null only when truly missing.\n"
        f"User request:\n{prompt}\n"
        f"Target schema JSON Schema:\n{schema.model_json_schema()}\n"
    )
    if include_validation_error:
        base += (
            f"\nPrevious validation error:\n{include_validation_error}\nFix the output to validate."
        )
    return base


def _extract_envelope_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """
    A permissive envelope schema for provider.generate_json.
    We validate each item with Pydantic afterwards.
    """
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "object"}}},
        "required": ["items"],
    }


def _validate_item(item: dict[str, Any], schema: type[BaseModel]) -> dict[str, Any]:
    # Validate only schema fields; ignore __xpath__ for validation safety.
    schema_keys = set(schema.model_fields.keys())
    payload = {k: v for k, v in item.items() if k in schema_keys}
    try:
        obj = schema.model_validate(payload)
    except Exception as e:
        raise SilkwebSchemaError(
            message="Item did not validate against schema.",
            validation_errors=str(e),
            context={"item": payload},
        ) from e
    validated = obj.model_dump()

    xpath = item.get("__xpath__")
    if isinstance(xpath, dict):
        validated["__xpath__"] = {str(k): str(v) for k, v in xpath.items()}
    else:
        validated["__xpath__"] = {}
    return validated


def _attach_meta(items: list[dict[str, Any]], provider: LLMProvider) -> list[dict[str, Any]]:
    llm_model = (
        f"{getattr(provider, 'provider_name', 'provider')}/{getattr(provider, 'model', '')}".strip(
            "/"
        )
    )
    fetched_at = datetime.now(tz=timezone.utc)
    out: list[dict[str, Any]] = []
    for it in items:
        xpath_map = it.get("__xpath__") if isinstance(it.get("__xpath__"), dict) else {}
        first_xpath = ""
        if isinstance(xpath_map, dict) and xpath_map:
            first_xpath = str(next(iter(xpath_map.values())))
        meta = SilkMeta(
            url="",
            fetched_at=fetched_at,
            fetch_tier=-1,
            xpath=first_xpath,
            llm_model=llm_model or None,
            selector_from_cache=None,
            confidence=None,
        )
        enriched = dict(it)
        enriched["__silk_meta__"] = asdict(meta)
        out.append(enriched)
    return out


def _merge_items(all_items: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """
    Merge chunk results.
    - union for lists (dedup by stable JSON string)
    """
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for items in all_items:
        for it in items:
            key = json.dumps(it, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
    return merged


async def _extract_once(
    *,
    content: str,
    cleaned: CleanedContent,
    schema: type[BaseModel],
    prompt: str,
    provider: LLMProvider,
    validation_error: str | None,
) -> list[dict[str, Any]]:
    t_build = time.perf_counter()
    system = _system_prompt(prompt, schema, include_validation_error=validation_error)
    user_body = (
        "Extraction input (JSON envelope — see system instructions for formats):\n"
        f"{content}\n\n"
        "Extract items according to the request."
    )
    messages: list[Message] = [
        {
            "role": "user",
            "content": user_body,
        }
    ]
    cap = max(512, int(get_config().extraction_max_tokens or 8192))
    phase = "retry" if validation_error else "first"
    print(
        f"[silkweb]   extract_data _extract_once ({phase}): built prompts in "
        f"{time.perf_counter() - t_build:.3f}s "
        f"(system_chars={len(system):,} user_chars={len(user_body):,} max_tokens={cap})",
        flush=True,
    )
    t_llm = time.perf_counter()
    print(
        f"[silkweb]   extract_data _extract_once ({phase}): calling provider.generate_json...",
        flush=True,
    )
    data = await provider.generate_json(
        messages,
        system=system,
        schema=_extract_envelope_schema(schema),
        temperature=0.0,
        max_tokens=cap,
    )
    print(
        f"[silkweb]   extract_data generate_json ({phase}): {time.perf_counter() - t_llm:.2f}s",
        flush=True,
    )
    items = data.get("items", data)
    if isinstance(items, dict) and "items" in items:
        items = items["items"]
    if not isinstance(items, list):
        raise SilkwebLLMError(
            message="Extractor did not return a list of items.",
            provider=getattr(provider, "provider_name", None),
            model=getattr(provider, "model", None),
            raw_output=str(data),
        )
    validated: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            validated.append(_validate_item(it, schema))
        except (SilkwebSchemaError, Exception):
            continue
    if not validated and items:
        raise SilkwebSchemaError(
            message="No items validated against schema.",
            validation_errors=f"{len(items)} items failed validation",
            context={"sample": items[:2]},
        )
    return validated


async def extract_data(
    cleaned: CleanedContent,
    schema: type[BaseModel],
    prompt: str,
    provider: LLMProvider,
    chunker: Chunker | str | None = None,
) -> list[dict[str, Any]]:
    """
    Extract structured data from cleaned content.

    - Single-call path: payload from ``choose_extraction_payload`` (respects
      ``SilkwebConfig.representation``: auto / flat_json / markdown / slim_html)
      -> LLM -> items
    - Chunked path: chunk cleaned.markdown, extract per chunk, merge items
    - Requires per-item `__xpath__` mapping for provenance
    - Validates against `schema`; on failure retries once with error details
    - Attaches `__silk_meta__` provenance to each item
    """
    print(
        f"[silkweb]   extract_data: start schema={getattr(schema, '__name__', schema)!r} "
        f"chunker={'set' if chunker is not None else 'none'}",
        flush=True,
    )
    chunks: list[str] | None = None
    if chunker is None:
        chunks = None
    elif isinstance(chunker, str):
        chunks = await chunk_content(
            cleaned.markdown,
            strategy=chunker,  # type: ignore[arg-type]
            query=prompt,
            max_tokens=2000,
            provider=provider,
        )
    else:
        chunks = chunker(cleaned, prompt, provider)

    async def run_with_retry(content: str) -> list[dict[str, Any]]:
        print(
            f"[silkweb]   extract_data run_with_retry: content_chars={len(content):,}",
            flush=True,
        )
        t_chunk = time.perf_counter()
        try:
            out = await _extract_once(
                content=content,
                cleaned=cleaned,
                schema=schema,
                prompt=prompt,
                provider=provider,
                validation_error=None,
            )
            print(
                f"[silkweb]   extract_data run ok in {time.perf_counter() - t_chunk:.2f}s",
                flush=True,
            )
            return out
        except (SilkwebSchemaError, SilkwebLLMError) as e:
            print(
                f"[silkweb]   extract_data first call failed ({type(e).__name__}), retrying with error hint...",
                flush=True,
            )
            try:
                out = await _extract_once(
                    content=content,
                    cleaned=cleaned,
                    schema=schema,
                    prompt=prompt,
                    provider=provider,
                    validation_error=str(e),
                )
                print(
                    f"[silkweb]   extract_data run ok after retry in "
                    f"{time.perf_counter() - t_chunk:.2f}s",
                    flush=True,
                )
                return out
            except (SilkwebSchemaError, SilkwebLLMError) as e2:
                print(
                    f"[silkweb]   extract_data gave up after retry ({type(e2).__name__}) "
                    f"in {time.perf_counter() - t_chunk:.2f}s",
                    flush=True,
                )
                return []

    if not chunks:
        print("[silkweb]   extract_data: choosing payload (representation / caps)...", flush=True)
        t_pick = time.perf_counter()
        payload = choose_extraction_payload(cleaned)
        dt_pick = time.perf_counter() - t_pick
        fmt = "flat_json"
        try:
            env = json.loads(payload)
            if isinstance(env, dict) and isinstance(env.get("format"), str):
                fmt = str(env["format"])
        except Exception:
            if payload.lstrip().startswith("{"):
                fmt = "json_envelope"
        print(
            f"[silkweb]   extract_data: payload format={fmt!r} chars={len(payload):,} "
            f"(choose took {dt_pick:.3f}s)",
            flush=True,
        )
        items = await run_with_retry(payload)
        return _attach_meta(items, provider)

    per_chunk: list[list[dict[str, Any]]] = []
    for ch in chunks:
        per_chunk.append(await run_with_retry(ch))
    merged = _merge_items(per_chunk)
    return _attach_meta(merged, provider)
