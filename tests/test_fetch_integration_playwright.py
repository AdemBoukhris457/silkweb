from __future__ import annotations

import os

import pytest


@pytest.mark.anyio
async def test_playwright_fetch_integration_optional() -> None:
    """
    Optional integration test.

    Runs only when:
    - playwright is installed
    - SILKWEB_RUN_INTEGRATION=1
    """
    if os.environ.get("SILKWEB_RUN_INTEGRATION", "").strip() not in {"1", "true", "yes"}:
        pytest.skip("Set SILKWEB_RUN_INTEGRATION=1 to run integration tests.")

    pytest.importorskip("playwright.async_api")

    from silkweb.fetch.tiers.playwright_fetcher import fetch

    page = await fetch("https://example.com", capture_network=True)
    assert page.status in (200, 204)
    assert isinstance(page.headers, dict)
    events = page.network_requests()
    assert isinstance(events, list)
    if events:
        assert "url" in events[0]
        assert "status" in events[0]
