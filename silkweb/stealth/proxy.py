from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

ProxyStrategy = Literal["per_request", "per_domain", "on_failure", "sticky"]


@dataclass(slots=True)
class _ProxyState:
    failures: int = 0
    backoff_until: float = 0.0
    requests: int = 0


@dataclass(slots=True)
class ProxyPool:
    proxies: list[str]
    sticky_ttl_s: float = 600.0
    backoff_base_s: float = 30.0
    backoff_max_s: float = 10 * 60.0

    _rr_index: int = 0
    _states: dict[str, _ProxyState] = field(default_factory=dict)
    _domain_sticky: dict[str, str] = field(default_factory=dict)
    _current: str | None = None  # for on_failure
    _sticky_proxy: str | None = None
    _sticky_expires_at: float = 0.0

    def __post_init__(self) -> None:
        self.proxies = [p.strip() for p in (self.proxies or []) if str(p).strip()]
        for p in self.proxies:
            self._states.setdefault(p, _ProxyState())

    def _active(self) -> list[str]:
        now = time.monotonic()
        return [p for p in self.proxies if self._states.get(p, _ProxyState()).backoff_until <= now]

    def _pick_rr(self) -> str | None:
        active = self._active()
        if not active:
            return None
        self._rr_index = self._rr_index % len(active)
        p = active[self._rr_index]
        self._rr_index = (self._rr_index + 1) % len(active)
        return p

    def next_proxy(self, strategy: ProxyStrategy, *, domain: str | None = None) -> str | None:
        if not self.proxies:
            return None

        if strategy == "per_request":
            p = self._pick_rr()
            if p:
                self._states[p].requests += 1
            return p

        if strategy == "per_domain":
            dom = (domain or "").strip().lower()
            if not dom:
                # fall back to per-request
                p = self._pick_rr()
                if p:
                    self._states[p].requests += 1
                return p
            existing = self._domain_sticky.get(dom)
            if existing and existing in self._active():
                self._states[existing].requests += 1
                return existing
            p = self._pick_rr()
            if p:
                self._domain_sticky[dom] = p
                self._states[p].requests += 1
            return p

        if strategy == "on_failure":
            if self._current and self._current in self._active():
                self._states[self._current].requests += 1
                return self._current
            self._current = self._pick_rr()
            if self._current:
                self._states[self._current].requests += 1
            return self._current

        if strategy == "sticky":
            now = time.monotonic()
            if (
                self._sticky_proxy
                and self._sticky_proxy in self._active()
                and now < self._sticky_expires_at
            ):
                self._states[self._sticky_proxy].requests += 1
                return self._sticky_proxy
            p = self._pick_rr()
            self._sticky_proxy = p
            self._sticky_expires_at = now + float(self.sticky_ttl_s)
            if p:
                self._states[p].requests += 1
            return p

        raise ValueError(f"Unknown strategy: {strategy}")

    def mark_failed(self, proxy_url: str) -> None:
        p = (proxy_url or "").strip()
        if not p or p not in self._states:
            return
        st = self._states[p]
        st.failures += 1
        delay = min(self.backoff_max_s, self.backoff_base_s * (2 ** max(0, st.failures - 1)))
        jitter = random.uniform(0, delay * 0.25)
        st.backoff_until = time.monotonic() + float(delay) + jitter

        # Break stickiness if this proxy was sticky/current
        if self._current == p:
            self._current = None
        if self._sticky_proxy == p:
            self._sticky_proxy = None
            self._sticky_expires_at = 0.0

        # Remove from per-domain stickies
        for dom, val in list(self._domain_sticky.items()):
            if val == p:
                self._domain_sticky.pop(dom, None)

    def mark_success(self, proxy_url: str) -> None:
        p = (proxy_url or "").strip()
        if not p or p not in self._states:
            return
        st = self._states[p]
        st.failures = 0
        st.backoff_until = 0.0

    def stats(self) -> dict[str, Any]:
        active = self._active()
        failed = [p for p in self.proxies if p not in active]
        return {
            "active": len(active),
            "failed": len(failed),
            "requests": {p: self._states[p].requests for p in self.proxies},
            "failures": {p: self._states[p].failures for p in self.proxies},
        }
