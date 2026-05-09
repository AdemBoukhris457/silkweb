from __future__ import annotations

import asyncio
from typing import Any

from ...exceptions import SilkwebLLMError
from .base import LLMProvider, Message, parse_json_loose, with_retries


class LlamaCppProvider(LLMProvider):
    provider_name = "llamacpp"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        retry=None,
        model_path: str | None = None,
        n_ctx: int = 8192,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, api_key=api_key, timeout_s=timeout_s, retry=retry)
        self.model_path = model_path or model
        self.n_ctx = n_ctx
        self._llama = None
        self._llama_kwargs = kwargs

    def _ensure_llama(self):
        if self._llama is not None:
            return self._llama
        try:
            from llama_cpp import Llama  # type: ignore
        except Exception as e:
            raise SilkwebLLMError(
                message="llama-cpp-python is not installed.",
                provider=self.provider_name,
                model=self.model,
                context={"error": repr(e)},
            ) from e
        self._llama = Llama(model_path=self.model_path, n_ctx=self.n_ctx, **self._llama_kwargs)
        return self._llama

    def _format_prompt(self, messages: list[Message], system: str | None) -> str:
        parts: list[str] = []
        if system:
            parts.append(f"System: {system}")
        for m in messages:
            role = m.get("role", "user")
            parts.append(f"{role.title()}: {m.get('content', '')}")
        parts.append("Assistant:")
        return "\n".join(parts)

    async def generate(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
    ) -> str:
        prompt = self._format_prompt(messages, system)

        async def _call() -> str:
            llama = self._ensure_llama()

            # run sync in thread
            def _run() -> str:
                out = llama(prompt, max_tokens=max_tokens or 256, temperature=temperature)
                return str(out["choices"][0]["text"])

            return await asyncio.to_thread(_run)

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
                message="Malformed JSON response from llama.cpp.",
                provider=self.provider_name,
                model=self.model,
                raw_output=text,
                context={"error": repr(e)},
            ) from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise SilkwebLLMError(
            message="llama.cpp embeddings are not implemented in this scaffold.",
            provider=self.provider_name,
            model=self.model,
        )
