from __future__ import annotations

from typing import Any

from ...exceptions import SilkwebLLMError
from .base import LLMProvider, Message, parse_json_loose, with_retries


class OllamaProvider(LLMProvider):
    provider_name = "ollama"

    async def generate(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        try:
            import ollama  # type: ignore
        except Exception as e:
            raise SilkwebLLMError(
                message="ollama SDK is not installed.",
                provider=self.provider_name,
                model=self.model,
                context={"error": repr(e)},
            ) from e

        req_messages: list[dict[str, str]] = []
        if system:
            req_messages.append({"role": "system", "content": system})
        req_messages.extend(messages)

        async def _call() -> str:
            options: dict[str, Any] = {"temperature": temperature}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            resp = await ollama.AsyncClient().chat(  # type: ignore[attr-defined]
                model=self.model,
                messages=req_messages,
                options=options,
            )
            return str(resp["message"]["content"])

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
                message="Malformed JSON response from ollama.",
                provider=self.provider_name,
                model=self.model,
                raw_output=text,
                context={"error": repr(e)},
            ) from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            import ollama  # type: ignore
        except Exception as e:
            raise SilkwebLLMError(
                message="ollama SDK is not installed.",
                provider=self.provider_name,
                model=self.model,
                context={"error": repr(e)},
            ) from e

        async def _call() -> list[list[float]]:
            client = ollama.AsyncClient()  # type: ignore[attr-defined]
            vectors: list[list[float]] = []
            for t in texts:
                resp = await client.embeddings(model=self.model, prompt=t)
                vectors.append(list(resp["embedding"]))
            return vectors

        return await with_retries(
            _call,
            cfg=self.retry,
            provider=self.provider_name,
            model=self.model,
            context={"task": "embed"},
        )
