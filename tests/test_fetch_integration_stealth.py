from __future__ import annotations

import os

import pytest


@pytest.mark.anyio
async def test_stealth_fetch_integration_optional() -> None:
    """
    Optional integration test for Tier 3.

    Runs only when:
    - SILKWEB_RUN_INTEGRATION=1
    - playwright is installed (tier 3 fallback path)

    If patchright is installed, we also exercise the patchright engine explicitly.
    """
    if os.environ.get("SILKWEB_RUN_INTEGRATION", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("Set SILKWEB_RUN_INTEGRATION=1 to run integration tests.")

    pytest.importorskip("playwright.async_api")

    from silkweb.fetch.tiers.stealth_fetcher import fetch

    # Fallback path should work anywhere Playwright works.
    page = await fetch(
        "https://example.com",
        stealth_engine="camoufox",
        capture_network=True,
        timeout=30_000,
    )
    assert page.status in (200, 204)
    assert isinstance(page.headers, dict)
    events = page.network_requests()
    assert isinstance(events, list)

    # If patchright is installed, ensure the patchright engine path works too.
    try:
        pytest.importorskip("patchright.async_api")
    except Exception:
        return

    page2 = await fetch(
        "https://example.com",
        stealth_engine="patchright",
        capture_network=True,
        timeout=30_000,
    )
    assert page2.status in (200, 204)
    assert isinstance(page2.headers, dict)
    assert isinstance(page2.network_requests(), list)
