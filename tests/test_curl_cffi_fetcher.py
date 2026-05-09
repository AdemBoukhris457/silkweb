from __future__ import annotations

import contextlib
import importlib.util
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from silkweb.fetch.tiers.curl_cffi_fetcher import SUPPORTED_IMPERSONATE_PROFILES, fetch


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            body = b"<html><body><h1>Hello</h1></body></html>"
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("location", "/")
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        # Silence noisy test output
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
async def test_fetch_returns_silkpage(http_server_base_url: str) -> None:
    url = f"{http_server_base_url}/"

    if importlib.util.find_spec("curl_cffi") is not None:
        page = await fetch(url)
        assert page.fetch_tier == 1
    else:
        with pytest.warns(RuntimeWarning):
            page = await fetch(url)
        assert page.fetch_tier == 1

    assert page.status == 200
    assert "Hello" in page.text
    assert page.url.endswith("/")


@pytest.mark.anyio
async def test_fetch_follow_redirects(http_server_base_url: str) -> None:
    url = f"{http_server_base_url}/redirect"

    if importlib.util.find_spec("curl_cffi") is not None:
        page = await fetch(url, follow_redirects=True)
        assert page.fetch_tier == 1
    else:
        with pytest.warns(RuntimeWarning):
            page = await fetch(url, follow_redirects=True)
        assert page.fetch_tier == 1

    assert page.status == 200
    assert page.url.endswith("/")


@pytest.mark.anyio
async def test_unsupported_impersonate_raises(http_server_base_url: str) -> None:
    url = f"{http_server_base_url}/"
    assert "chrome_124" in SUPPORTED_IMPERSONATE_PROFILES
    with pytest.raises(ValueError):
        await fetch(url, impersonate="not_a_profile")
