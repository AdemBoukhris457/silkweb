from __future__ import annotations

import time
from typing import Any

from ...exceptions import SilkwebLLMError
from .base import LLMProvider, Message, parse_json_loose, with_retries


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    async def _client(self):
        try:
            import openai  # type: ignore
        except Exception as e:
            raise SilkwebLLMError(
                message="openai SDK is not installed.",
                provider=self.provider_name,
                model=self.model,
                context={"error": repr(e)},
            ) from e

        # Async client (OpenAI v1+)
        return openai.AsyncOpenAI(api_key=self.api_key, timeout=self.timeout_s)  # type: ignore[attr-defined]

    async def generate(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        req_messages: list[dict[str, str]] = []
        if system:
            req_messages.append({"role": "system", "content": system})
        req_messages.extend(messages)

        async def _call() -> str:
            client = await self._client()
            resp = await client.chat.completions.create(  # type: ignore[attr-defined]
                model=self.model,
                messages=req_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            content = resp.choices[0].message.content
            if content is None:
                raise SilkwebLLMError(
                    message="OpenAI returned empty/null content (possible refusal).",
                    provider=self.provider_name,
                    model=self.model,
                    raw_output=None,
                    context={"finish_reason": getattr(resp.choices[0], "finish_reason", None)},
                )
            return str(content)

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
        req_messages: list[dict[str, str]] = []
        if system:
            req_messages.append({"role": "system", "content": system})
        req_messages.extend(messages)

        async def _call() -> str:
            t0 = time.perf_counter()
            print(
                f"[silkweb]   openai: creating AsyncOpenAI client (timeout={self.timeout_s}s)...",
                flush=True,
            )
            client = await self._client()
            print(
                f"[silkweb]   openai: client ready in {time.perf_counter() - t0:.2f}s, "
                f"POST chat.completions model={self.model!r} max_tokens={max_tokens}",
                flush=True,
            )
            t_api = time.perf_counter()
            resp = await client.chat.completions.create(  # type: ignore[attr-defined]
                model=self.model,
                messages=req_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            fr = getattr(resp.choices[0], "finish_reason", None)
            print(
                f"[silkweb]   openai: chat.completions returned in {time.perf_counter() - t_api:.2f}s "
                f"finish_reason={fr!r}",
                flush=True,
            )
            content = resp.choices[0].message.content
            if content is None:
                raise SilkwebLLMError(
                    message="OpenAI returned empty/null content in JSON mode.",
                    provider=self.provider_name,
                    model=self.model,
                    raw_output=None,
                )
            return str(content)

        text = await with_retries(
            _call,
            cfg=self.retry,
            provider=self.provider_name,
            model=self.model,
            context={"task": "generate_json"},
        )
        try:
            return parse_json_loose(text)
        except Exception as e:
            raise SilkwebLLMError(
                message="Malformed JSON response from OpenAI.",
                provider=self.provider_name,
                model=self.model,
                raw_output=text,
                context={"error": repr(e)},
            ) from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async def _call() -> list[list[float]]:
            client = await self._client()
            resp = await client.embeddings.create(model=self.model, input=texts)  # type: ignore[attr-defined]
            return [list(item.embedding) for item in resp.data]

        return await with_retries(
            _call,
            cfg=self.retry,
            provider=self.provider_name,
            model=self.model,
            context={"task": "embed"},
        )
