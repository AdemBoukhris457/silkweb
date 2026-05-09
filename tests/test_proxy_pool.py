from __future__ import annotations

from silkweb.stealth.proxy import ProxyPool


def test_per_request_round_robin() -> None:
    pool = ProxyPool(["http://p1", "http://p2"])
    assert pool.next_proxy("per_request") == "http://p1"
    assert pool.next_proxy("per_request") == "http://p2"
    assert pool.next_proxy("per_request") == "http://p1"


def test_per_domain_sticky() -> None:
    pool = ProxyPool(["http://p1", "http://p2"])
    a1 = pool.next_proxy("per_domain", domain="a.com")
    a2 = pool.next_proxy("per_domain", domain="a.com")
    b1 = pool.next_proxy("per_domain", domain="b.com")
    assert a1 == a2
    assert b1 in {"http://p1", "http://p2"}


def test_on_failure_sticky_until_failed() -> None:
    pool = ProxyPool(["http://p1", "http://p2"])
    p = pool.next_proxy("on_failure")
    assert pool.next_proxy("on_failure") == p
    pool.mark_failed(p)
    p2 = pool.next_proxy("on_failure")
    assert p2 != p


def test_mark_failed_backoff_temporarily_removes(monkeypatch) -> None:
    # Control time.monotonic
    t = {"now": 100.0}

    import silkweb.stealth.proxy as mod

    monkeypatch.setattr(mod.time, "monotonic", lambda: t["now"])

    pool = ProxyPool(["http://p1", "http://p2"], backoff_base_s=10.0, backoff_max_s=60.0)
    p1 = pool.next_proxy("per_request")
    pool.mark_failed(p1)

    # Immediately, p1 should be excluded
    nxt = pool.next_proxy("per_request")
    assert nxt == "http://p2"

    # After backoff, p1 is active again
    t["now"] += 11.0
    nxt2 = pool.next_proxy("per_request")
    assert nxt2 in {"http://p1", "http://p2"}


def test_stats_counts_requests_and_failures() -> None:
    pool = ProxyPool(["http://p1", "http://p2"])
    p = pool.next_proxy("per_request")
    pool.mark_failed(p)
    s = pool.stats()
    assert s["active"] in {0, 1, 2}
    assert s["requests"]["http://p1"] + s["requests"]["http://p2"] >= 1
    assert s["failures"][p] >= 1
