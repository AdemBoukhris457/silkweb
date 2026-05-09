from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from ...config import get_config
from ...exceptions import SilkwebLLMError
from ..providers.base import LLMProvider, Message

SelectorSet = dict[str, list[str]]


def _system_prompt(schema: type[BaseModel]) -> str:
    fields = list(schema.model_fields.keys())
    return (
        "You are a selector compiler.\n"
        "Given extracted field values and their source XPaths, generate robust selectors.\n"
        "For EACH field, output an ordered list of fallbacks:\n"
        "- First 3 entries MUST be CSS selectors\n"
        "- Next 2 entries MUST be XPath expressions\n"
        "Selectors should be robust across minor DOM changes:\n"
        "- Prefer stable attributes and tag structures\n"
        "- Include adaptive fallbacks: class-based, text-contains, and structural position\n"
        "Return JSON only.\n"
        f"Fields: {fields}\n"
    )


def _response_schema(schema: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            k: {"type": "array", "items": {"type": "string"}} for k in schema.model_fields
        },
        "required": list(schema.model_fields),
    }


async def compile_selectors(
    extracted: list[dict[str, Any]],
    schema: type[BaseModel],
    html: str,
    provider: LLMProvider,
) -> SelectorSet:
    """
    Compile robust selector fallbacks per field using an LLM.

    Inputs:
    - extracted: list of extracted items; each item should include `__xpath__` mapping.
    - schema: Pydantic model describing the fields.
    - html: raw HTML (context only; LLM uses XPaths primarily).
    """
    sys = _system_prompt(schema)

    # Provide a small sample of extracted values + xpaths to keep prompts short.
    sample = extracted[:3]
    payload = {
        "sample_items": sample,
        "note": "Each item includes __xpath__ mapping from field->XPath.",
    }

    messages: list[Message] = [
        {
            "role": "user",
            "content": (
                "HTML (for context, may be truncated):\n"
                f"{html[:5000]}\n\n"
                "Extracted sample items with XPaths:\n"
                f"{json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                "Generate selector fallbacks per field."
            ),
        }
    ]

    cap = max(512, int(get_config().extraction_max_tokens or 8192))
    data = await provider.generate_json(
        messages,
        system=sys,
        schema=_response_schema(schema),
        temperature=0.0,
        max_tokens=cap,
    )
    if not isinstance(data, dict):
        raise SilkwebLLMError(
            message="Selector compiler returned non-object.",
            provider=getattr(provider, "provider_name", None),
            model=getattr(provider, "model", None),
            raw_output=str(data),
        )

    out: SelectorSet = {}
    for field in schema.model_fields:
        val = data.get(field)
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            raise SilkwebLLMError(
                message="Selector compiler returned invalid selector list.",
                provider=getattr(provider, "provider_name", None),
                model=getattr(provider, "model", None),
                raw_output=str(data),
                context={"field": field},
            )
        out[field] = val

    return out
