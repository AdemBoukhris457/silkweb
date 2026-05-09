from __future__ import annotations

from silkweb.cache.manager import CacheManager


def test_cache_manager_stats_and_clear(tmp_path) -> None:
    # Ensure cache_path points to tmp for isolation
    import silkweb

    silkweb.configure(cache_path=str(tmp_path))
    cm = CacheManager.from_config()

    stats = cm.stats()
    assert "http" in stats and "page" in stats and "selectors" in stats

    cm.clear(layer="selectors")
    cm.clear(layer="page")
    cm.clear(layer="http")
