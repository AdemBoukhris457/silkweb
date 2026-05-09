from __future__ import annotations


def test_seen_set_memory_roundtrip() -> None:
    from silkweb.crawl.dedup import SeenSet

    s = SeenSet(backend="memory")
    assert s.add("https://a.test/") is True
    assert s.add("https://a.test/") is False
    st = s.stats()
    assert st["entries"] == 1


def test_seen_set_sqlite_roundtrip(tmp_path) -> None:
    from silkweb.crawl.dedup import SeenSet

    p = tmp_path / "seen.sqlite"
    s = SeenSet(backend="sqlite", sqlite_path=str(p))
    assert s.add("https://a.test/1") is True
    assert s.add("https://a.test/1") is False
    assert s.stats()["entries"] == 1
    s.clear()
    assert s.stats()["entries"] == 0
