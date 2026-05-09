from __future__ import annotations

import contextlib
import importlib.util
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from silkweb.fetch.tiers.playwright_fetcher import fetch


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            body = (
                b"<html><body>"
                b"<div id='status'>loading</div>"
                b"<script>"
                b"async function run(){"
                b"  await fetch('/api/fetch');"
                b"  await new Promise((r)=>{"
                b"    const x=new XMLHttpRequest();"
                b"    x.open('GET','/api/xhr');"
                b"    x.onload=()=>r();"
                b"    x.send();"
                b"  });"
                b"  document.getElementById('status').id='done';"
                b"}"
                b"run();"
                b"</script>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path in {"/api/fetch", "/api/xhr"}:
            payload = json.dumps({"ok": True, "path": self.path}).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def http_server_base_url() -> str:
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.anyio
async def test_playwright_fetch_returns_page(http_server_base_url: str) -> None:
    if importlib.util.find_spec("playwright") is None:
        pytest.skip("playwright not installed")

    url = f"{http_server_base_url}/"
    try:
        page = await fetch(
            url, browser="chromium", wait_for="#done", intercept_requests=True, timeout=15_000
        )
    except Exception as e:  # browsers not installed, etc.
        pytest.skip(f"playwright not usable in this environment: {e!r}")

    assert page.fetch_tier == 2
    assert page.status == 200
    assert "done" in page.html
    intercepted = getattr(page, "_intercepted_requests", [])
    urls = {r["url"] for r in intercepted}
    assert any(u.endswith("/api/fetch") for u in urls)
    assert any(u.endswith("/api/xhr") for u in urls)
