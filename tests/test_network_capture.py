from __future__ import annotations

from silkweb.fetch.tiers.network_capture import capture_body_json, redact_headers


def test_redact_headers() -> None:
    out = redact_headers(
        {
            "Authorization": "Bearer abc",
            "cookie": "a=b",
            "X-Api-Key": "secret",
            "Content-Type": "application/json",
        }
    )
    assert out["Authorization"] == "<redacted>"
    assert out["cookie"] == "<redacted>"
    assert out["X-Api-Key"] == "<redacted>"
    assert out["Content-Type"] == "application/json"


def test_capture_body_json_only_json_ct() -> None:
    assert capture_body_json('{"a":1}', content_type="text/html", max_bytes=1000) is None
    assert capture_body_json("", content_type="application/json", max_bytes=1000) is None


def test_capture_body_json_parses_and_truncates() -> None:
    ok = capture_body_json('{"a":1}', content_type="application/json", max_bytes=1000)
    assert ok == {"json": {"a": 1}}

    big = capture_body_json(
        '{"a":"' + ("x" * 5000) + '"}', content_type="application/json", max_bytes=10
    )
    assert big is not None
    assert big.get("truncated") is True
    assert int(big.get("size") or 0) > 10
