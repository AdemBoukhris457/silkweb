from __future__ import annotations

from silkweb.config import SilkwebConfig
from silkweb.fetch.tiers import stealth_fetcher


def test_auto_engine_prefers_patchright(monkeypatch) -> None:
    cfg = SilkwebConfig(prefer_nodriver=True)

    def installed(name: str) -> bool:
        return name in {"patchright", "nodriver"}

    monkeypatch.setattr(stealth_fetcher, "_is_installed", installed)
    assert stealth_fetcher._pick_auto_engine(cfg) == "patchright"


def test_auto_engine_uses_nodriver_only_when_opted_in(monkeypatch) -> None:
    def installed(name: str) -> bool:
        return name == "nodriver"

    monkeypatch.setattr(stealth_fetcher, "_is_installed", installed)

    cfg_off = SilkwebConfig(prefer_nodriver=False)
    assert stealth_fetcher._pick_auto_engine(cfg_off) != "nodriver"

    cfg_on = SilkwebConfig(prefer_nodriver=True)
    assert stealth_fetcher._pick_auto_engine(cfg_on) == "nodriver"
