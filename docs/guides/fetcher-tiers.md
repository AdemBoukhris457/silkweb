# Fetcher Tiers

Silkweb uses a multi-tier fetching system that automatically escalates when simpler methods fail.

## Page content formats

Every tier returns a `SilkPage` with the content available in multiple formats:

| Property | Format | Description |
|----------|--------|-------------|
| `page.html` | Raw HTML | The full HTML source as received |
| `page.text` | Plain text | Cleaned text with boilerplate removed (via Trafilatura) |
| `page.markdown` | Markdown | Cleaned content with headings, links, bold/italic, lists preserved |
| `page.json_ld()` | JSON-LD | Structured data from `<script type="application/ld+json">` tags |
| `page.hydration_data()` | Dict \| None | Next.js `__NEXT_DATA__`, Nuxt `__NUXT_DATA__` or inline `__NUXT__` (best-effort) |
| `page.network_requests()` | List[dict] | Browser-tier fetch capture only; empty otherwise |
| `page.tables()` | List | All `<table>` elements parsed into row/column lists |
| `page.links()` | List[str] | All `<a href>` links as absolute URLs |
| `page.article()` | Dict | Article metadata (title, author, date, content) |

```python
page = silkweb.fetch("https://example.com")

# Three main content representations
print(page.html)         # raw HTML
print(page.text)         # "Example Domain\nThis domain is..."
print(page.markdown)     # "# Example Domain\n\nThis domain is..."

# Structured data
print(page.json_ld())    # [{"@type": "WebPage", ...}]
print(page.tables())     # [[["Header", "Header"], ["row1", "row2"]]]
print(page.links())      # ["https://www.iana.org/domains/example"]
```

## Tier overview

| Tier | Engine | When used | Speed |
|------|--------|-----------|-------|
| **0** | `httpx` (HTTP/2) | Static pages, APIs | ~50ms |
| **1** | `curl_cffi` | Sites checking TLS fingerprints | ~100ms |
| **2** | Playwright (Chromium) | JavaScript-rendered pages | ~2s |
| **3** | Stealth browser (nodriver/patchright) | Anti-bot protected pages | ~5-30s |

## Auto-escalation

When `tier="auto"` (the default), Silkweb attempts each tier in order:

1. **Tier 0** — simple async HTTP via `httpx`
2. If the response is 403/429/503, escalate to **Tier 1** (TLS-impersonating HTTP)
3. If the page body is too thin (< 500 chars of text), escalate to **Tier 2** (browser rendering)
4. If Cloudflare or anti-bot challenge is detected, escalate to **Tier 3** (stealth browser)

Each escalation is logged so you can see exactly what happened.

```python
import silkweb

# Auto-escalation (default)
page = silkweb.fetch("https://example.com")

# Force a specific tier
page = silkweb.fetch("https://example.com", tier=2)  # always use Playwright
```

## Tier 0: httpx

The fastest tier — plain async HTTP with HTTP/2 support and connection pooling.

```python
page = silkweb.fetch("https://httpbin.org/get", tier=0)
```

- Shared `AsyncClient` per configuration (connection pooling)
- Configurable headers, timeout, redirect following
- Integrated with the HTTP cache layer (hishel)

## Tier 1: curl_cffi

Uses `curl_cffi` to impersonate real browser TLS fingerprints.

```python
page = silkweb.fetch("https://example.com", tier=1)
```

Supported impersonation profiles:

- `chrome_120`, `chrome_124` (default)
- `firefox_121`
- `safari_17`
- `edge_122`

Falls back to Tier 0 transparently if `curl_cffi` is not installed.

## Tier 2: Playwright

Full browser rendering with Chromium (or Firefox/WebKit).

```python
page = silkweb.fetch(
    "https://example.com",
    tier=2,
    wait_for=".product-list",   # wait for this CSS selector
    timeout=15_000,              # 15 second timeout
)
```

Options:

- `browser`: `"chromium"` (default), `"firefox"`, `"webkit"`
- `wait_until`: `"load"`, `"domcontentloaded"`, `"networkidle"`
- `wait_for`: CSS selector to wait for before capturing HTML
- `viewport`: `{"width": 1280, "height": 720}`
- `intercept_requests`: capture XHR/fetch calls for API discovery
- `capture_network`: capture a lightweight network log for debugging (view via `page.network_requests()`)
- `capture_network_bodies`: capture JSON response bodies (redacted + size-capped)
- `max_network_events`: cap the number of captured network events (default: 500)
- `max_network_body_bytes`: cap JSON body capture size (default: 200_000 bytes)

## Tier 3: Stealth browser

For pages with aggressive anti-bot protection (Cloudflare, Akamai, etc.).

```python
page = silkweb.fetch("https://protected-site.com", tier=3)
```

Tier 3 forwards the same browser-style kwargs as Tier 2 where applicable, including:

- `wait_until`: `"load"` (default), `"domcontentloaded"`, or `"networkidle"`. The default is **`load`** so SPAs and analytics-heavy pages do not hang forever waiting for a quiet network (`networkidle` is easy to exceed the navigation timeout on sites with long-lived connections).
- `timeout`: navigation timeout in ms (default `30_000`; raise for slow first paints).
- `stealth_engine`: `"auto"` (patchright when installed), `"patchright"`, `"camoufox"`, or `"nodriver"`.
- `viewport`, `proxy`, `capture_network`, `capture_network_bodies`, etc.

```python
page = silkweb.fetch(
    "https://skills.sh/aws-samples/sample-strands-agent-with-agentcore/financial-news",
    tier=3,
    wait_until="load",
    timeout=60_000,
)
```

Stealth engines (in priority order):

1. **patchright** — patched Playwright fork (preferred default when installed)
2. **playwright-stealth** — Playwright with stealth scripts
3. **nodriver** — CDP-connected Chrome (experimental; only auto-selected when opted in)

!!! note "nodriver is opt-in"

    By default, `stealth_engine="auto"` does **not** pick `nodriver` even if it is installed.
    To enable it, set `silkweb.configure(prefer_nodriver=True)` or explicitly pass
    `stealth_engine="nodriver"` for Tier 3.

Cloudflare detection checks for:

- `cf-ray` response header
- "Just a moment" / "Checking your browser" page title
- `cf_clearance` cookie presence

### Network capture (debugging)

For browser tiers (Tier 2 and Tier 3), you can capture a lightweight network log:

```python
page = silkweb.fetch("https://example.com", tier=2, capture_network=True)
print(page.network_requests()[:3])
```

This is useful for debugging “why is the DOM empty?” on SPAs, and for spotting internal JSON endpoints.

## Controlling escalation

```python
import silkweb

silkweb.configure(
    max_tier=2,           # never go beyond Playwright
    auto_escalate=True,   # enable auto-escalation (default)
    timeout=30_000,       # global timeout in ms
)
```

## Async usage

```python
page = await silkweb.async_fetch("https://example.com", tier="auto")
```

## Running integration tests (optional)

Some fetch behaviors (real browser rendering, network capture) are validated by optional integration tests.
They are skipped by default to avoid flakiness and dependency requirements.

To run them locally:

```bash
# Install browser deps (one-time)
python -m pip install -e ".[browser]"
playwright install chromium

# Run integration tests
set SILKWEB_RUN_INTEGRATION=1
python -m pytest -q
```
