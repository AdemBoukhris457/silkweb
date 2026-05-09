from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import BaseModel

import silkweb
from silkweb.watch import ChangeEvent, Watcher


class Snapshot(BaseModel):
    title: str


class _Handler(BaseHTTPRequestHandler):
    counter = 0
    lock = threading.Lock()

    def do_GET(self):
        with _Handler.lock:
            _Handler.counter += 1
            n = _Handler.counter
        title = "v1" if n == 1 else "v2"
        body = f"<html><body><h1>{title}</h1></body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


@pytest.fixture()
def mock_server():
    _Handler.counter = 0
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.anyio
async def test_watcher_detects_change(monkeypatch, mock_server, tmp_path) -> None:
    # Disable caching so successive server responses are observed.
    # Also disable robots/rate-limiter fetching robots.txt (would consume first response).
    silkweb.configure(
        cache_path=str(tmp_path),
        cache_enabled=False,
        proxies=[],
        proxy_rotation="per_request",
        respect_robots=False,
        rate_limit_global=None,
        rate_limit_per_domain=0,
    )

    # Deterministic extraction: parse <h1> from fetched HTML.
    async def fake_async_extract(url: str, schema, prompt: str, **kwargs):
        page = await silkweb.async_fetch(url, tier=0, no_cache=True, use_http_cache=False)
        import re

        m = re.search(r"<h1>(.*?)</h1>", page.html)
        title = m.group(1) if m else ""
        return [schema.model_validate({"title": title})]

    monkeypatch.setattr(silkweb, "async_extract", fake_async_extract)

    events: list[ChangeEvent] = []
    errors: list[Exception] = []

    async def on_change(ev: ChangeEvent) -> None:
        events.append(ev)

    async def on_error(_url: str, exc: Exception) -> None:
        errors.append(exc)

    w = Watcher(sqlite_path=str(tmp_path / "watch.sqlite"))
    w.add(mock_server, Snapshot, interval=0.1, on_change=on_change, on_error=on_error)
    await w.start()

    # Wait until we observe a modified title (or timeout)
    import asyncio

    deadline = asyncio.get_running_loop().time() + 2.0
    while asyncio.get_running_loop().time() < deadline:
        if any(
            c.field == "title" and c.change_type == "modified" for e in events for c in e.changes
        ):
            break
        await asyncio.sleep(0.1)
    await w.stop()

    assert not errors
    # First tick stores v1, second tick sees v2 and emits change.
    assert any(e.changed for e in events)
    assert any(
        c.field == "title" and c.change_type == "modified" for e in events for c in e.changes
    )
