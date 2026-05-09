from __future__ import annotations

import json

from typer.testing import CliRunner

from silkweb.cli.main import app

runner = CliRunner()


def test_cli_fetch_prints_html(monkeypatch) -> None:
    class _Page:
        html = "<html>ok</html>"

    monkeypatch.setattr("silkweb.cli.main.sw.fetch", lambda url, **kwargs: _Page())
    res = runner.invoke(app, ["fetch", "https://example.test/"])
    assert res.exit_code == 0
    assert "<html>ok</html>" in res.stdout


def test_cli_discover_api_prints_codegen(monkeypatch) -> None:
    class _Ep:
        def __init__(self) -> None:
            self.url = "https://api.example.test/items?page=1"
            self.method = "GET"
            self.request_headers = {}
            self.request_body = None
            self.response_status = 200
            self.response_headers = {"content-type": "application/json"}
            self.response_schema = {"type": "object"}
            self.pagination = {"query_params": ["page"], "body_keys": []}
            self.auth = None

    class _Res:
        def __init__(self) -> None:
            self.endpoints = [_Ep()]
            self.generated_scraper = "async def scrape_endpoint_1():\n    return {}"

    monkeypatch.setattr("silkweb.cli.main.sw.discover_api", lambda url, output_path=None: _Res())
    res = runner.invoke(app, ["discover-api", "https://example.test/"])
    assert res.exit_code == 0
    assert "scrape_endpoint_1" in res.stdout


def test_cli_ask_json(monkeypatch) -> None:
    monkeypatch.setattr("silkweb.cli.main.sw.ask", lambda url, prompt: [{"a": 1}])
    res = runner.invoke(app, ["ask", "https://example.test/", "hi"])
    assert res.exit_code == 0
    parsed = json.loads(res.stdout)
    assert parsed == [{"a": 1}]
