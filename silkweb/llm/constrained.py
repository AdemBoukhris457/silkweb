from __future__ import annotations

import re
from typing import Any, TypeVar

from pydantic import BaseModel

from ..exceptions import SilkwebLLMError, SilkwebSchemaError
from .providers.base import LLMProvider, Message, parse_json_loose
from .providers.llamacpp import LlamaCppProvider
from .providers.openai import OpenAIProvider

TModel = TypeVar("TModel", bound=BaseModel)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", flags=re.IGNORECASE | re.MULTILINE)


def strip_code_fences(text: str) -> str:
    return _FENCE_RE.sub("", (text or "").strip()).strip()


class ConstrainedDecoder:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def generate_json(
        self,
        messages: list[Message],
        pydantic_model: type[TModel],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        return await generate_json_constrained(
            self.provider,
            messages,
            pydantic_model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )


async def generate_json_constrained(
    provider: LLMProvider,
    messages: list[Message],
    pydantic_model: type[TModel],
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """
    Generate JSON that validates against `pydantic_model` using a 3-step strategy.

    Strategy 1: Use native JSON mode (OpenAI; Anthropic treated as "native-ish" via provider.generate_json).
    Strategy 2: Use `outlines` constrained decoding (when available) for GGUF-based local models.
    Strategy 3: Prompt-only fallback with strict JSON-only instructions + parse + retry.
    """
    schema = pydantic_model.model_json_schema()

    inner = provider.unwrap()

    # Strategy 1: native JSON mode
    if isinstance(inner, OpenAIProvider):
        data = await provider.generate_json(
            messages,
            system=system,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return _validate_dict(data, pydantic_model)

    # If provider has a custom JSON generator, try it first.
    try:
        data = await provider.generate_json(
            messages,
            system=system,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return _validate_dict(data, pydantic_model)
    except SilkwebLLMError as e:
        # Re-raise auth/config errors; only swallow "unsupported mode" type errors
        ctx = getattr(e, "context", {}) or {}
        err_str = str(ctx.get("error", "")).lower()
        if "auth" in err_str or "api_key" in err_str or "unauthorized" in err_str:
            raise
        # keep going; this may be an unsupported mode for the provider

    # Strategy 2: outlines constrained decoding for local GGUF (best-effort)
    if isinstance(inner, LlamaCppProvider):
        data = await _try_outlines_llamacpp(inner, messages, schema, system=system)
        if data is not None:
            return _validate_dict(data, pydantic_model)

    # Strategy 3: prompt-only JSON with retries
    last_text: str | None = None
    for _attempt in range(1, 4):
        json_system = _json_only_system(system, schema)
        text = await provider.generate(
            messages,
            system=json_system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        last_text = text
        try:
            parsed = parse_json_loose(strip_code_fences(text))
            return _validate_dict(parsed, pydantic_model)
        except SilkwebSchemaError:
            # Schema mismatch is not a parse failure; don't retry silently.
            raise
        except Exception:
            continue

    raise SilkwebLLMError(
        message="Failed to produce valid JSON after retries.",
        provider=getattr(provider, "provider_name", None),
        model=getattr(provider, "model", None),
        raw_output=last_text,
        context={"strategy": 3},
    )


def _json_only_system(system: str | None, schema: dict[str, Any]) -> str:
    instructions = (
        "Return ONLY a single JSON object. Do not include markdown code fences, comments, or extra text.\n"
        "The JSON MUST validate against this JSON Schema:\n"
        f"{schema}\n"
    )
    return f"{system}\n\n{instructions}".strip() if system else instructions


def _validate_dict(data: dict[str, Any], model: type[TModel]) -> dict[str, Any]:
    try:
        obj = model.model_validate(data)
    except Exception as e:
        raise SilkwebSchemaError(
            message="JSON did not validate against Pydantic schema.",
            validation_errors=str(e),
            context={"schema": model.model_json_schema()},
        ) from e
    return obj.model_dump()


async def _try_outlines_llamacpp(
    provider: LlamaCppProvider,
    messages: list[Message],
    schema: dict[str, Any],
    *,
    system: str | None,
) -> dict[str, Any] | None:
    """
    Best-effort outlines integration.

    Notes:
    - Outlines isn't available on all Python versions/platforms in this repo.
    - If anything isn't available, we return None and let Strategy 3 handle it.
    """
    try:
        import outlines  # type: ignore
        import outlines.generate  # type: ignore
        import outlines.models  # type: ignore
    except Exception:
        return None

    # Only attempt if we have a local GGUF path.
    model_path = getattr(provider, "model_path", None)
    if not model_path:
        return None

    prompt = _format_prompt(messages, system)
    try:
        llamacpp_model = outlines.models.llamacpp(model_path)  # type: ignore[attr-defined]
        generator = outlines.generate.json(llamacpp_model, schema)  # type: ignore[attr-defined]
        text = generator(prompt)
        parsed = parse_json_loose(strip_code_fences(str(text)))
        return parsed
    except Exception:
        return None


def _format_prompt(messages: list[Message], system: str | None) -> str:
    parts: list[str] = []
    if system:
        parts.append(f"System: {system}")
    for m in messages:
        role = m.get("role", "user")
        parts.append(f"{role.title()}: {m.get('content', '')}")
    parts.append("Assistant:")
    return "\n".join(parts)
