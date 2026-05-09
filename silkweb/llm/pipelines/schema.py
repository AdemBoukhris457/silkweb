from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, create_model

from ...exceptions import SilkwebLLMError
from ..pipelines.clean import CleanedContent, clean_html
from ..pipelines.extract import choose_extraction_payload
from ..providers.base import LLMProvider, Message

_SCHEMA_CACHE_MAX = 256
_SCHEMA_CACHE: dict[tuple[str, str], type[BaseModel]] = {}


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _system_prompt(prompt: str) -> str:
    return (
        "You are a schema inference engine.\n"
        "Given cleaned web content and a user description, infer a JSON Schema (draft-2020-12 style).\n"
        "Return JSON ONLY (no markdown).\n"
        "Prefer an object schema with clear field names.\n"
        "Use arrays for repeated items.\n"
        "Use primitive types: string, integer, number, boolean, object, array.\n"
        f"User description:\n{prompt}\n"
    )


async def synthesize_schema(
    cleaned: CleanedContent,
    prompt: str,
    provider: LLMProvider,
) -> type[BaseModel]:
    """
    Ask an LLM to infer a JSON Schema from cleaned content and the user's prompt,
    then convert it into a Pydantic v2 BaseModel.
    """
    content_hash = _sha256(choose_extraction_payload(cleaned) or cleaned.markdown)
    prompt_hash = _sha256(prompt)
    key = (content_hash, prompt_hash)
    if key in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[key]

    sys = _system_prompt(prompt)
    schema_request = {
        "type": "object",
        "properties": {"json_schema": {"type": "object"}},
        "required": ["json_schema"],
    }
    payload = choose_extraction_payload(cleaned)
    messages: list[Message] = [
        {
            "role": "user",
            "content": (
                "Cleaned page content (extraction payload — may be flat_json, markdown, or html_excerpt):\n"
                f"{payload}\n\n"
                "Also provide a JSON Schema that matches what the user wants to extract."
            ),
        }
    ]

    data = await provider.generate_json(
        messages, system=sys, schema=schema_request, temperature=0.0
    )
    js = data.get("json_schema", data)
    if isinstance(js, str):
        try:
            js = json.loads(js)
        except Exception as e:
            raise SilkwebLLMError(
                message="Schema synthesis returned invalid JSON.",
                provider=getattr(provider, "provider_name", None),
                model=getattr(provider, "model", None),
                raw_output=js,
                context={"error": repr(e)},
            ) from e
    if not isinstance(js, dict):
        raise SilkwebLLMError(
            message="Schema synthesis did not return a JSON object schema.",
            provider=getattr(provider, "provider_name", None),
            model=getattr(provider, "model", None),
            raw_output=str(js),
        )

    model = json_schema_to_pydantic_model(js, name=js.get("title") or "SynthesizedModel")
    if len(_SCHEMA_CACHE) >= _SCHEMA_CACHE_MAX:
        oldest_key = next(iter(_SCHEMA_CACHE))
        del _SCHEMA_CACHE[oldest_key]
    _SCHEMA_CACHE[key] = model
    return model


async def infer_schema(url: str, hint: str, provider: LLMProvider) -> type[BaseModel]:
    """
    Convenience API: fetch URL, clean HTML, and synthesize schema from hint.
    """
    from ...fetch.orchestrator import fetch as fetch_url

    page = await fetch_url(url, tier="auto")
    cleaned = await clean_html(page.html, provider=provider, strategy="auto")
    return await synthesize_schema(cleaned, hint, provider)


def _type_from_jsonschema(schema: dict[str, Any], name: str) -> Any:
    t = schema.get("type")
    if isinstance(t, list):
        # simple optional union handling
        if "null" in t and len(t) == 2:
            other = next(x for x in t if x != "null")
            inner = _type_from_jsonschema({**schema, "type": other}, name)
            return inner | None
        t = t[0] if t else "string"

    if t == "string":
        return str
    if t == "integer":
        return int
    if t == "number":
        return float
    if t == "boolean":
        return bool
    if t == "array":
        items = schema.get("items") or {}
        inner = _type_from_jsonschema(items if isinstance(items, dict) else {}, f"{name}Item")
        return list[inner]  # type: ignore[valid-type]
    if t == "object" or (t is None and "properties" in schema):
        return json_schema_to_pydantic_model(schema, name=name)

    return Any


def json_schema_to_pydantic_model(
    schema: dict[str, Any], *, name: str = "Model"
) -> type[BaseModel]:
    if not isinstance(schema, dict):
        raise ValueError("schema must be a dict")

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required") or []
    if not isinstance(required, list):
        required = []

    fields: dict[str, tuple[Any, Any]] = {}
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_name, str):
            continue
        ps = prop_schema if isinstance(prop_schema, dict) else {}
        field_type = _type_from_jsonschema(ps, f"{name}_{prop_name}")

        is_required = prop_name in required
        default = ... if is_required else None
        description = ps.get("description")
        fields[prop_name] = (field_type, Field(default=default, description=description))

    return create_model(str(name), __base__=BaseModel, **fields)  # type: ignore[call-arg]
