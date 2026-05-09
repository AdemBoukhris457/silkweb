from __future__ import annotations

from typing import Any

from ...exceptions import SilkwebLLMError
from .base import LLMProvider, Message, parse_json_loose, with_retries


class AnthropicProvider(LLMProvider):
    provider_name = "anthropic"

    async def _client(self):
        try:
            import anthropic  # type: ignore
        except Exception as e:
            raise SilkwebLLMError(
                message="anthropic SDK is not installed.",
                provider=self.provider_name,
                model=self.model,
                context={"error": repr(e)},
            ) from e
        return anthropic.AsyncAnthropic(api_key=self.api_key, timeout=self.timeout_s)  # type: ignore[attr-defined]

    def _to_anthropic_messages(self, messages: list[Message]) -> list[dict[str, str]]:
        # Anthropics expects role=user/assistant. We pass through.
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    async def generate(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        async def _call() -> str:
            client = await self._client()
            resp = await client.messages.create(  # type: ignore[attr-defined]
                model=self.model,
                system=system,
                messages=self._to_anthropic_messages(messages),
                max_tokens=max_tokens or 1024,
                temperature=temperature,
            )
            content = getattr(resp, "content", None)
            if isinstance(content, list) and content:
                parts: list[str] = []
                for block in content:
                    t = getattr(block, "text", None)
                    if t is None and isinstance(block, dict):
                        t = block.get("text")
                    if t is not None:
                        parts.append(str(t))
                if parts:
                    return "\n".join(parts)
            fallback = getattr(resp, "completion", None)
            if fallback is None:
                raise SilkwebLLMError(
                    message="Anthropic returned empty content.",
                    provider=self.provider_name,
                    model=self.model,
                    raw_output=None,
                )
            return str(fallback)

        return await with_retries(
            _call,
            cfg=self.retry,
            provider=self.provider_name,
            model=self.model,
            context={"task": "generate"},
        )

    async def generate_json(
        self,
        messages: list[Message],
        system: str | None = None,
        schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        text = await self.generate(
            messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            return parse_json_loose(text)
        except Exception as e:
            raise SilkwebLLMError(
                message="Malformed JSON response from Anthropic.",
                provider=self.provider_name,
                model=self.model,
                raw_output=text,
                context={"error": repr(e)},
            ) from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Anthropic doesn't provide embeddings in their SDK in the same way.
        raise SilkwebLLMError(
            message="Anthropic embeddings are not supported in this scaffold.",
            provider=self.provider_name,
            model=self.model,
        )
