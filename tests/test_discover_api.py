from __future__ import annotations

import pytest

import silkweb.discover as discover


@pytest.mark.anyio
async def test_discover_api_filters_json_and_generates_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_capture(url: str, session: object | None):
        assert url == "https://example.test/"
        return [
            # non-JSON
            {
                "url": "https://api.example.test/html",
                "method": "GET",
                "request_headers": {"Accept": "*/*"},
                "request_body": None,
                "status": 200,
                "response_headers": {"content-type": "text/html"},
                "response_text": "<html/>",
            },
            # JSON XHR with auth header + pagination
            {
                "url": "https://api.example.test/items?page=2&limit=10",
                "method": "POST",
                "request_headers": {"Authorization": "Bearer SECRET", "Accept": "application/json"},
                "request_body": '{"cursor":"abc"}',
                "status": 200,
                "response_headers": {"content-type": "application/json; charset=utf-8"},
                "response_text": '{"items":[{"id":1,"name":"a"}],"next_cursor":"def"}',
            },
        ]

    monkeypatch.setattr(discover, "_capture_json_endpoints", fake_capture)

    result = await discover.discover_api("https://example.test/")
    assert len(result.endpoints) == 1

    ep = result.endpoints[0]
    assert ep.url == "https://api.example.test/items?page=2&limit=10"
    assert ep.method == "POST"
    assert ep.pagination is not None
    assert "page" in {p.lower() for p in ep.pagination["query_params"]}
    assert ep.auth is not None
    assert "authorization" in ep.auth["headers"]
    assert ep.response_schema["type"] in {"object", "array"}

    # Codegen should not embed the real secret
    assert "SECRET" not in result.generated_scraper
    assert "Bearer <YOUR_TOKEN>" in result.generated_scraper
    assert "scrape_endpoint_1" in result.generated_scraper


@pytest.mark.anyio
async def test_discover_api_dedupes_identical_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    dup = {
        "url": "https://api.example.test/x",
        "method": "GET",
        "request_headers": {},
        "request_body": None,
        "status": 200,
        "response_headers": {"content-type": "application/json"},
        "response_text": '{"a":1}',
    }

    async def fake_capture(url: str, session: object | None):
        return [dup, dup]

    monkeypatch.setattr(discover, "_capture_json_endpoints", fake_capture)

    result = await discover.discover_api("https://example.test/")
    assert len(result.endpoints) == 1
    assert "scrape_endpoint_2" not in result.generated_scraper
