from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any

from .session import SilkSession


async def record(name: str) -> SilkSession:
    """
    Open a real (non-headless) browser and record navigations, clicks, and fills.

    Persists to ``~/.silkweb/sessions/<name>.silkweb`` (cookies, storage, actions).
    This is **Playwright session** recording — not the same as HTTP ``replay_dir`` /
    :func:`silkweb.replay`, which stores raw HTML + metadata for a single fetch.
    """
    s = SilkSession(name)
    s.actions = []
    await s._ensure_browser(headless=False)
    assert s._page is not None

    async def add_action(action: dict[str, Any]) -> None:
        s.actions.append(action)

    # Record top-frame navigations
    def on_nav(frame: Any) -> None:
        try:
            if getattr(frame, "parent_frame", None):
                return
            url = str(getattr(frame, "url", "") or "")
            if url:
                s.url = url
                s.actions.append({"type": "navigate", "url": url})
        except Exception:
            return

    s._page.on("framenavigated", on_nav)

    # Expose bindings for JS event capture
    await s._page.expose_binding(  # type: ignore[attr-defined]
        "__silkweb_record_action",
        lambda _source, payload: asyncio.create_task(add_action(dict(payload))),
    )

    # Inject event listeners for clicks and input changes
    await s._page.add_init_script(
        """
        (() => {
          const send = (payload) => {
            try { window.__silkweb_record_action(payload); } catch (e) {}
          };

          document.addEventListener('click', (e) => {
            const el = e.target;
            if (!el) return;
            const sel = el.id ? ('#' + el.id) : (el.getAttribute && el.getAttribute('name') ? ('[name=\"' + el.getAttribute('name') + '\"]') : el.tagName.toLowerCase());
            send({type: 'click', selector: sel, ts: Date.now()});
          }, true);

          document.addEventListener('input', (e) => {
            const el = e.target;
            if (!el) return;
            const tag = (el.tagName || '').toLowerCase();
            if (tag !== 'input' && tag !== 'textarea') return;
            const sel = el.id ? ('#' + el.id) : (el.getAttribute('name') ? ('[name=\"' + el.getAttribute('name') + '\"]') : tag);
            send({type: 'fill', selector: sel, value: el.value, ts: Date.now()});
          }, true);
        })();
        """
    )

    # Wait until user closes browser window (best-effort)
    with contextlib.suppress(Exception):
        await s._page.wait_for_event("close")  # type: ignore[attr-defined]

    s.created_at = datetime.now(tz=timezone.utc).isoformat()
    await s.save()
    await s.close()
    return s


async def replay(name: str) -> SilkSession:
    """
    Replay a **Playwright** session by ``name`` (see :func:`record`) in headless mode.

    Unlike :func:`silkweb.replay`, this does not load ``replay_dir`` HTML snapshots;
    it uses the session JSON written by ``record``.
    """
    s = SilkSession.load(name)
    s._check_cookie_expiry()
    await s._ensure_browser(headless=True)
    assert s._page is not None

    for act in s.actions or []:
        t = str(act.get("type") or "")
        if t == "navigate":
            url = str(act.get("url") or "")
            if url:
                await s._page.goto(url, wait_until="load", timeout=30_000)
                s.url = url
        elif t == "click":
            sel = str(act.get("selector") or "")
            if sel:
                await s._page.click(sel)
        elif t == "fill":
            sel = str(act.get("selector") or "")
            val = str(act.get("value") or "")
            if sel:
                await s._page.fill(sel, val)

    await s.save()
    await s.close()
    return s
