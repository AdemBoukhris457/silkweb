from __future__ import annotations

import pytest

from silkweb.config import configure, get_config
from silkweb.exceptions import SilkwebConfigError


def test_configure_strict_rejects_unknown_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILKWEB_STRICT_CONFIG", "1")
    try:
        with pytest.raises(SilkwebConfigError, match="Unknown SilkwebConfig"):
            configure(not_a_real_field=123)
    finally:
        monkeypatch.delenv("SILKWEB_STRICT_CONFIG", raising=False)
    cfg = get_config()
    assert "not_a_real_field" not in cfg.extra


def test_configure_loose_stores_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SILKWEB_STRICT_CONFIG", raising=False)
    configure(custom_recipe_flag=True)
    cfg = get_config()
    assert cfg.extra.get("custom_recipe_flag") is True
    # clean up for other tests
    cfg.extra.pop("custom_recipe_flag", None)
