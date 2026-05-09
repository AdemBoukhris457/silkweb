from __future__ import annotations

import json

import pytest

from silkweb.exceptions import SilkwebError


def test_replay_save_and_load(tmp_path: pytest.TempPathFactory) -> None:
    from silkweb.config import configure, get_config
    from silkweb.observability.replay import maybe_save_fetch, replay
    from silkweb.parse.page import SilkPage

    out_dir = tmp_path / "replays"
    out_dir.mkdir(parents=True, exist_ok=True)
    configure(replay_dir=str(out_dir))
    cfg = get_config()

    page = SilkPage("<html><h1>x</h1></html>", url="https://example.test/", status=200, headers={})
    session_file = maybe_save_fetch(
        cfg=cfg,
        page=page,
        url="https://example.test/",
        tier=0,
        duration_ms=12,
        cache_hit=False,
    )
    assert session_file is not None

    sess = replay(session_file)
    assert sess.url == "https://example.test/"
    assert "<h1>x</h1>" in sess.html

    # ReplaySession convenience methods delegate to public helpers.
    import silkweb as sw

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(sw, "ask_from_html", lambda url, html, prompt, **kwargs: {"ok": True})
        assert sess.ask("p") == {"ok": True}
    finally:
        monkeypatch.undo()

    # Ensure session file is valid JSON with html_path
    with open(session_file, encoding="utf-8") as f:
        meta = json.loads(f.read())
    assert "html_path" in meta
    assert (out_dir / meta["html_path"]).exists()


def test_replay_raises_on_missing_html_path(tmp_path) -> None:
    from silkweb.observability.replay import replay as http_replay

    bad = tmp_path / "bad.silkweb"
    bad.write_text(json.dumps({"url": "https://x.test/", "tier": 0}), encoding="utf-8")
    with pytest.raises(SilkwebError) as ei:
        http_replay(str(bad))
    assert "html_path" in str(ei.value.message).lower()


def test_replay_raises_on_missing_html_file(tmp_path) -> None:
    from silkweb.observability.replay import replay as http_replay

    bad = tmp_path / "bad2.silkweb"
    bad.write_text(
        json.dumps({"url": "https://x.test/", "html_path": "nope.html"}),
        encoding="utf-8",
    )
    with pytest.raises(SilkwebError) as ei:
        http_replay(str(bad))
    assert "not found" in str(ei.value.message).lower()
