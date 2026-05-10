"""
Public ``ask`` / ``extract`` entrypoints (including ``explain=``).

You can import these from the package root (``import silkweb``) or from
``silkweb.api`` interchangeably after the package is loaded.
"""

from __future__ import annotations

from typing import Any


def ask(url: str, prompt: str, *, explain: bool = False, **fetch_kwargs: Any):
    import silkweb

    return silkweb.ask(url, prompt, explain=explain, **fetch_kwargs)


async def async_ask(url: str, prompt: str, *, explain: bool = False, **fetch_kwargs: Any):
    import silkweb

    return await silkweb.async_ask(url, prompt, explain=explain, **fetch_kwargs)


def extract(url: str, schema: Any, prompt: str, *, explain: bool = False, **kwargs: Any):
    import silkweb

    return silkweb.extract(url, schema, prompt, explain=explain, **kwargs)


async def async_extract(url: str, schema: Any, prompt: str, *, explain: bool = False, **kwargs: Any):
    import silkweb

    return await silkweb.async_extract(url, schema, prompt, explain=explain, **kwargs)


__all__ = ["ask", "async_ask", "extract", "async_extract"]
