from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from silkweb.exceptions import SilkwebSessionError, SilkwebSessionExpiredError
from silkweb.session.session import SilkSession, _build_storage_init_script


@pytest.mark.anyio
async def test_session_save_and_load(tmp_path, monkeypatch) -> None:
    # Redirect sessions dir into tmp by patching os.path.expanduser used in session module.
    import silkweb.session.session as mod

    monkeypatch.setattr(mod, "_sessions_dir", lambda: str(tmp_path))

    s = SilkSession("t1")
    s.cookies = [{"name": "sid", "value": "x", "expires": -1, "domain": "example.com", "path": "/"}]
    s.localStorage = {"k": "v"}
    s.sessionStorage = {"s": "1"}
    s.url = "https://example.com"
    await s.save()

    loaded = SilkSession.load("t1")
    assert loaded.cookies and loaded.cookies[0]["name"] == "sid"
    assert loaded.localStorage == {"k": "v"}
    assert loaded.sessionStorage == {"s": "1"}


def test_session_expired_cookie_raises(tmp_path, monkeypatch) -> None:
    import silkweb.session.session as mod

    monkeypatch.setattr(mod, "_sessions_dir", lambda: str(tmp_path))

    s = SilkSession("expired")
    exp = (datetime.now(tz=timezone.utc) - timedelta(days=1)).timestamp()
    s.cookies = [{"name": "session", "value": "x", "expires": exp, "domain": "x", "path": "/"}]
    with pytest.raises(SilkwebSessionExpiredError):
        s._check_cookie_expiry()


def test_storage_init_script_embeds_json_literal() -> None:
    js = _build_storage_init_script("https://example.com", {"a": "b"}, {"x": "1"})
    assert "JSON.parse(" in js
    assert "localStorageData" in js
    assert "https://example.com" in js


def test_session_corrupt_file_raises(tmp_path, monkeypatch) -> None:
    import silkweb.session.session as mod

    monkeypatch.setattr(mod, "_sessions_dir", lambda: str(tmp_path))
    (tmp_path / "bad.silkweb").write_text("{not json", encoding="utf-8")
    with pytest.raises(SilkwebSessionError):
        SilkSession.load("bad")
