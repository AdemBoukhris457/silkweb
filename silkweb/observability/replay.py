"""
HTTP fetch replay: ``maybe_save_fetch`` writes JSON + HTML under ``configure(replay_dir=...)``;
:func:`replay` loads them into :class:`ReplaySession`.

For **Playwright** session record/replay, use :func:`silkweb.record_session` /
:func:`silkweb.replay_session` instead.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from ..config import SilkwebConfig, get_config
from ..exceptions import SilkwebError
from ..parse.page import SilkPage


def _safe_name(s: str) -> str:
    out = []
    for ch in s or "":
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)[:120] or "session"


def maybe_save_fetch(
    *,
    cfg: SilkwebConfig,
    page: SilkPage,
    url: str,
    tier: int,
    duration_ms: int | None,
    cache_hit: bool | None,
    error: str | None = None,
) -> str | None:
    """
    Save raw HTML + metadata to cfg.replay_dir, returning session_file path.
    """
    if not cfg.replay_dir:
        return None

    os.makedirs(cfg.replay_dir, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H-%M-%S", time.gmtime())
    name = _safe_name(f"session_{ts}_{tier}_{url}")
    html_path = os.path.join(cfg.replay_dir, f"{name}.html")
    session_path = os.path.join(cfg.replay_dir, f"{name}.silkweb")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page.html or "")

    meta = {
        "url": url,
        "final_url": page.url,
        "tier": tier,
        "status": page.status,
        "headers": page.headers,
        "duration_ms": duration_ms,
        "cache_hit": cache_hit,
        "error": error,
        "html_path": os.path.basename(html_path),
    }
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")
    return session_path


@dataclass(frozen=True, slots=True)
class ReplaySession:
    url: str
    html: str
    tier: int | None = None
    status: int | None = None
    headers: dict[str, Any] | None = None

    def page(self) -> SilkPage:
        return SilkPage(
            self.html,
            url=self.url,
            status=int(self.status or 200),
            headers=self.headers or {},
            metadata=None,
            fetch_tier=int(self.tier or 0),
        )

    def ask(self, prompt: str, **kwargs: Any):
        import silkweb as sw

        return sw.ask_from_html(self.url, self.html, prompt=prompt, **kwargs)

    def extract(self, schema, prompt: str, **kwargs: Any):
        import silkweb as sw

        return sw.extract_from_html(self.url, self.html, schema=schema, prompt=prompt, **kwargs)

    def query(self, silkql_string: str, **kwargs: Any):
        import silkweb as sw

        return sw.query_from_html(self.url, self.html, silkql_string=silkql_string, **kwargs)


def replay(session_file: str) -> ReplaySession:
    """
    Load a recorded **HTTP fetch** session (JSON metadata + sibling HTML file).

    This is not the same as :func:`silkweb.replay_session`, which replays a
    **Playwright** session file from ``record_session`` (cookies/actions under
    ``~/.silkweb/sessions``). Files here are produced when ``configure(replay_dir=...)``
    is set and fetches call :func:`maybe_save_fetch`.
    """
    cfg = get_config()
    base_dir = cfg.replay_dir or os.path.dirname(os.path.abspath(session_file))
    try:
        with open(session_file, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SilkwebError(
            message=f"Could not read HTTP replay session file: {session_file}",
            context={"error": repr(e)},
        ) from e
    if not isinstance(meta, dict):
        raise SilkwebError(
            message=f"HTTP replay session must be a JSON object: {session_file}",
            context={"path": session_file},
        )
    html_rel = meta.get("html_path")
    if not html_rel or not str(html_rel).strip():
        raise SilkwebError(
            message=(
                f"HTTP replay metadata missing non-empty 'html_path' (expected basename "
                f"next to the .silkweb file): {session_file}"
            ),
            context={"path": session_file, "keys": sorted(meta.keys())},
        )
    html_path = (
        str(html_rel) if os.path.isabs(str(html_rel)) else os.path.join(base_dir, str(html_rel))
    )
    if not os.path.isfile(html_path):
        raise SilkwebError(
            message=f"HTTP replay HTML file not found: {html_path}",
            context={"session_file": session_file, "html_path": html_path, "base_dir": base_dir},
        )
    try:
        with open(html_path, encoding="utf-8") as f:
            html = f.read()
    except OSError as e:
        raise SilkwebError(
            message=f"Could not read HTTP replay HTML file: {html_path}",
            context={"session_file": session_file, "error": repr(e)},
        ) from e
    return ReplaySession(
        url=str(meta.get("url") or ""),
        html=html,
        tier=meta.get("tier"),
        status=meta.get("status"),
        headers=meta.get("headers"),
    )
