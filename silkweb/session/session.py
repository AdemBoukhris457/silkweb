from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ..config import get_config
from ..exceptions import SilkwebSessionError, SilkwebSessionExpiredError


def _sessions_dir() -> str:
    base = os.path.expanduser("~/.silkweb/sessions")
    os.makedirs(base, exist_ok=True)
    return base


def _session_path(name: str) -> str:
    return os.path.join(_sessions_dir(), f"{name}.silkweb")


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _cookie_is_expired(cookie: dict[str, Any], now_ts: float) -> bool:
    exp = cookie.get("expires")
    if exp in (None, -1):
        return False
    try:
        return float(exp) != 0.0 and float(exp) < now_ts
    except Exception:
        return False


def _looks_auth_cookie(name: str) -> bool:
    n = (name or "").lower()
    return any(x in n for x in ("session", "auth", "token", "jwt", "sid"))


def _build_storage_init_script(
    origin: str,
    local_storage: dict[str, Any],
    session_storage: dict[str, Any],
) -> str:
    """Single-string init script for Playwright (payload embedded as JSON.parse(...))."""
    payload_obj: dict[str, Any] = {
        "origin": origin,
        "localStorageData": local_storage,
        "sessionStorageData": session_storage,
    }
    payload_json = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
    payload_js_literal = json.dumps(payload_json)
    return f"""
(() => {{
  try {{
    const payload = JSON.parse({payload_js_literal});
    const origin = payload.origin;
    const localStorageData = payload.localStorageData || {{}};
    const sessionStorageData = payload.sessionStorageData || {{}};
    if (origin && location.origin !== origin) {{
      return;
    }}
    for (const [k, v] of Object.entries(localStorageData)) {{
      localStorage.setItem(k, String(v));
    }}
    for (const [k, v] of Object.entries(sessionStorageData)) {{
      sessionStorage.setItem(k, String(v));
    }}
  }} catch (e) {{}}
}})();
"""


@dataclass(slots=True)
class SilkSession:
    """
    Persisted Playwright session (cookies + localStorage + sessionStorage).

    Storage format (JSON):
    {cookies, localStorage, sessionStorage, url, created_at, ua, actions?}
    """

    name: str

    url: str | None = None
    created_at: str | None = None
    ua: str | None = None
    cookies: list[dict[str, Any]] | None = None
    localStorage: dict[str, Any] | None = None
    sessionStorage: dict[str, Any] | None = None
    actions: list[dict[str, Any]] | None = None

    _playwright: Any | None = None
    _browser: Any | None = None
    _context: Any | None = None
    _page: Any | None = None

    def __post_init__(self) -> None:
        path = _session_path(self.name)
        if os.path.exists(path):
            data = self._load_file(path, session_name=self.name)
            self.cookies = list(data.get("cookies") or [])
            self.localStorage = dict(data.get("localStorage") or {})
            self.sessionStorage = dict(data.get("sessionStorage") or {})
            self.url = data.get("url")
            self.created_at = data.get("created_at")
            self.ua = data.get("ua")
            self.actions = (
                list(data.get("actions") or []) if isinstance(data.get("actions"), list) else None
            )
        else:
            self.created_at = _now_utc().isoformat()

    @property
    def path(self) -> str:
        return _session_path(self.name)

    async def _ensure_browser(self, *, headless: bool = True) -> None:
        if self._browser is not None and self._context is not None and self._page is not None:
            return
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Playwright is required for SilkSession. Install with `pip install 'silkweb[browser]'`."
            ) from e

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        cfg = get_config()
        ua = self.ua or cfg.user_agent
        self.ua = ua
        self._browser = await self._playwright.chromium.launch(headless=headless)
        self._context = await self._browser.new_context(user_agent=ua)

        # Apply persisted cookies
        if self.cookies:
            await self._context.add_cookies(self.cookies)

        # Apply storage best-effort for the origin
        origin = None
        if self.url:
            p = urlparse(self.url)
            if p.scheme and p.netloc:
                origin = f"{p.scheme}://{p.netloc}"
        if origin and (self.localStorage or self.sessionStorage):
            init_script = _build_storage_init_script(
                origin, self.localStorage or {}, self.sessionStorage or {}
            )
            await self._context.add_init_script(init_script)

        self._page = await self._context.new_page()

    def _check_cookie_expiry(self) -> None:
        if not self.cookies:
            return
        now_ts = _now_utc().timestamp()
        expired = [c.get("name") for c in self.cookies if _cookie_is_expired(c, now_ts)]
        expired = [str(x) for x in expired if x]
        # If any auth-like cookies are expired, treat session as expired.
        auth_expired = [n for n in expired if _looks_auth_cookie(n)]
        if auth_expired:
            raise SilkwebSessionExpiredError(
                message=(
                    "Session cookies appear expired. Re-record the session with "
                    "`await record_session(...)` / `record_session(...)` and save again."
                ),
                name=self.name,
                expired_cookies=auth_expired,
                context={"path": self.path},
            )

    async def fetch(self, url: str, *, tier: int = 2, proxy: str | None = None) -> Any:
        """
        Navigate to a URL using a persisted session (Playwright).

        ``tier`` and ``proxy`` are reserved for alignment with HTTP fetch tiers; the browser
        context currently uses global ``configure()`` defaults (user agent, etc.). Use
        Playwright-only proxy wiring in a future release if you need it here.
        """
        del tier, proxy  # reserved for API parity with HTTP fetch
        self._check_cookie_expiry()
        headless = True
        await self._ensure_browser(headless=headless)
        assert self._page is not None
        self.url = url
        await self._page.goto(url, wait_until="load", timeout=30_000)
        return self._page

    async def fill(self, selector: str, value: str) -> None:
        await self._ensure_browser(headless=True)
        assert self._page is not None
        await self._page.fill(selector, value)

    async def click(self, selector: str) -> None:
        await self._ensure_browser(headless=True)
        assert self._page is not None
        cfg = get_config()
        if cfg.human_mouse:
            from ..stealth.behavior import human_mouse_move

            await human_mouse_move(self._page, selector)
        await self._page.click(selector)

    async def wait_for(self, selector: str, timeout: int = 10_000) -> None:
        await self._ensure_browser(headless=True)
        assert self._page is not None
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def save(self) -> None:
        """
        Serialize cookies + localStorage + sessionStorage to disk.
        """
        if self._context is None or self._page is None:
            # Nothing to save yet; still write minimal metadata.
            payload = {
                "cookies": self.cookies or [],
                "localStorage": self.localStorage or {},
                "sessionStorage": self.sessionStorage or {},
                "url": self.url,
                "created_at": self.created_at,
                "ua": self.ua,
                "actions": self.actions or [],
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
            return

        self.cookies = await self._context.cookies()
        try:
            self.localStorage = await self._page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            )
        except Exception:
            self.localStorage = self.localStorage or {}
        try:
            self.sessionStorage = await self._page.evaluate(
                "() => Object.fromEntries(Object.entries(sessionStorage))"
            )
        except Exception:
            self.sessionStorage = self.sessionStorage or {}

        payload = {
            "cookies": self.cookies or [],
            "localStorage": self.localStorage or {},
            "sessionStorage": self.sessionStorage or {},
            "url": self.url,
            "created_at": self.created_at,
            "ua": self.ua,
            "actions": self.actions or [],
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    async def close(self) -> None:
        if self._page is not None:
            await self._page.close()
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None

    @classmethod
    def load(cls, name: str) -> SilkSession:
        path = _session_path(name)
        s = cls(name=name)
        if os.path.exists(path):
            data = s._load_file(path, session_name=name)
            s.cookies = list(data.get("cookies") or [])
            s.localStorage = dict(data.get("localStorage") or {})
            s.sessionStorage = dict(data.get("sessionStorage") or {})
            s.url = data.get("url")
            s.created_at = data.get("created_at")
            s.ua = data.get("ua")
            s.actions = (
                list(data.get("actions") or []) if isinstance(data.get("actions"), list) else None
            )
        return s

    @staticmethod
    def _load_file(path: str, *, session_name: str = "") -> dict[str, Any]:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise SilkwebSessionError(
                message=f"Could not read session file: {path}",
                name=session_name,
                context={"path": path, "error": repr(e)},
            ) from e
        if not isinstance(data, dict):
            raise SilkwebSessionError(
                message=f"Session file must contain a JSON object: {path}",
                name=session_name,
                context={"path": path},
            )
        return data
