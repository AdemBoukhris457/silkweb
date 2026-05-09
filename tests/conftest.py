from __future__ import annotations

import pytest

pytest_plugins = ["pytest_httpx"]


@pytest.fixture()
def html_ecommerce_listing() -> str:
    return """
    <html>
      <head><title>Shop</title></head>
      <body>
        <main>
          <h1>Products</h1>
          <div class="grid">
            <article class="card">
              <a class="link" href="/p/1"><h2 class="name">Alpha</h2></a>
              <span class="price">$12.34</span>
              <span class="rating">4.6</span>
            </article>
            <article class="card">
              <a class="link" href="/p/2"><h2 class="name">Beta</h2></a>
              <span class="price">$99.00</span>
              <span class="rating">3.9</span>
            </article>
          </div>
        </main>
      </body>
    </html>
    """.strip()


@pytest.fixture()
def html_article_page() -> str:
    return """
    <html>
      <head>
        <title>Breaking News</title>
        <meta property="og:title" content="Breaking News"/>
      </head>
      <body>
        <article>
          <h1>Breaking News</h1>
          <p class="byline">By Alice</p>
          <time datetime="2026-04-30">Apr 30, 2026</time>
          <div class="content">
            <p>First paragraph.</p>
            <p>Second paragraph.</p>
          </div>
        </article>
      </body>
    </html>
    """.strip()


@pytest.fixture()
def html_spa_hydration() -> str:
    # Mimics a Next.js-style __NEXT_DATA__ payload.
    return """
    <html>
      <head><title>SPA</title></head>
      <body>
        <div id="__next"></div>
        <script id="__NEXT_DATA__" type="application/json">
          {"props":{"pageProps":{"items":[{"id":1,"name":"Alpha"},{"id":2,"name":"Beta"}]}}}
        </script>
      </body>
    </html>
    """.strip()


@pytest.fixture()
def html_cloudflare_mock() -> str:
    # Matches orchestrator's `_looks_like_cloudflare()` heuristics.
    return """
    <html>
      <head><title>Just a moment...</title></head>
      <body>
        <h1>Checking your browser before accessing</h1>
      </body>
    </html>
    """.strip()
