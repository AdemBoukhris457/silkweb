![Silkweb](assets/readme/silkweb-banner.svg)

# 🕸️ Silkweb

> **The LLM-native Python web scraping library. Fetch anything. Extract everything. No selectors required.**

[![PyPI version](https://img.shields.io/pypi/v/silkweb.svg)](https://pypi.org/project/silkweb/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Downloads](https://img.shields.io/pypi/dm/silkweb.svg)](https://pypi.org/project/silkweb/)

Silkweb is a fully local, open-source Python library that unifies the entire web scraping stack — HTTP fetching, JavaScript rendering, anti-bot bypass, HTML parsing, and LLM-powered data extraction — behind a single import. It is the first library where you can type a plain-English question and receive a validated, typed Python object, without writing a single CSS selector or XPath expression, with all processing running privately on your own machine.

---

## Table of Contents

1. [Why Silkweb?](#1-why-silkweb)
2. [Installation](#2-installation)
3. [Quick Start](#3-quick-start)
4. [Core Concepts](#4-core-concepts)
5. [Fetcher Tiers](#5-fetcher-tiers)
6. [LLM Auto-Extraction](#6-llm-auto-extraction)
7. [Natural Language Querying](#7-natural-language-querying)
8. [SilkQL Query Language](#8-silkql-query-language)
9. [HTML Parsing & Selectors](#9-html-parsing--selectors)
10. [Anti-Bot & Stealth](#10-anti-bot--stealth)
11. [LLM Providers & Configuration](#11-llm-providers--configuration)
12. [Output Formats](#12-output-formats)
13. [Caching](#13-caching)
14. [Crawling & Concurrency](#14-crawling--concurrency)
15. [Session Management & Authentication](#15-session-management--authentication)
16. [Hidden API Discovery](#16-hidden-api-discovery)
17. [Watch & Change Detection](#17-watch--change-detection)
18. [CLI Reference](#18-cli-reference)
19. [Error Handling](#19-error-handling)
20. [Observability](#20-observability)
21. [Developer Experience](#21-developer-experience)
22. [Architecture Deep Dive](#22-architecture-deep-dive)
23. [Configuration Reference](#23-configuration-reference)
24. [Recipes Library](#24-recipes-library)
25. [FAQ](#25-faq)

---

## 1. Why Silkweb?

### The problem with today's scraping ecosystem

Building a production web scraper in 2025 means gluing together at least four separate libraries:

```
httpx (fetch) + Playwright (JS render) + BeautifulSoup (parse) + custom glue (retry/cache/schema)
```

None of them talk to each other. None of them have LLM integration. None of them bypass modern anti-bot systems out of the box. And none of them let you just *ask* for what you want.

### What Silkweb does differently

| Capability | Traditional approach | Silkweb |
|---|---|---|
| Fetch a page | `requests.get(url)` | `silkweb.fetch(url)` — auto-selects HTTP, stealth HTTP, or browser |
| Parse data | Write CSS/XPath selectors | Describe what you want in plain English |
| Handle JS | Manually configure Playwright | Automatic, transparent |
| Bypass Cloudflare | Multiple plugins, trial and error | Built-in, auto-escalating tiers |
| LLM extraction | No support | First-class, locally private |
| Output typing | Manual Pydantic boilerplate | Schema inferred or user-provided |
| Cache LLM calls | Not applicable | Synthesized selectors persist; LLM called once per template |
| Run locally | Not applicable | Fully offline with Ollama |

### The key insight: extract once with an LLM, scrape millions with CSS

When Silkweb first encounters a page template, it uses an LLM to understand the structure and synthesize robust CSS/XPath selectors. Those selectors are cached. Every subsequent request to pages of the same template uses pure, fast selector-based extraction — **zero LLM cost after the first page**. This makes LLM-quality extraction economically viable at scale.

---

## 2. Installation

### Minimal install (no browser, no LLM)
```bash
pip install silkweb
```

### With browser support (Playwright)
```bash
pip install "silkweb[browser]"
playwright install chromium
```

### With stealth browser support (nodriver + Camoufox)
```bash
pip install "silkweb[stealth]"
```

### Full install (all features)
```bash
pip install "silkweb[all]"
```

### With specific LLM providers
```bash
pip install "silkweb[ollama]"      # Ollama local models
pip install "silkweb[openai]"      # OpenAI GPT-4o etc.
pip install "silkweb[anthropic]"   # Anthropic Claude
pip install "silkweb[llama-cpp]"   # llama.cpp embedded inference
```

### Requirements

- Python 3.10 or higher
- For local LLM features: [Ollama](https://ollama.ai) (recommended) or llama.cpp
- For browser features: Chromium (auto-downloaded by Playwright)

---

## 3. Quick Start

### One-liner extraction
```python
import silkweb

# Ask a plain English question about any URL
prices = silkweb.ask("https://news.ycombinator.com", "top 10 stories with scores and authors")
print(prices)
# [{'title': '...', 'score': 312, 'author': 'pg'}, ...]
```

### Typed extraction with a Pydantic model
```python
from silkweb import extract
from pydantic import BaseModel

class Story(BaseModel):
    title: str
    url: str
    score: int
    author: str
    comments: int

stories: list[Story] = extract(
    "https://news.ycombinator.com",
    schema=Story,
    prompt="all front page stories"
)
```

### Zero-LLM CSS scraping (traditional mode)
```python
import silkweb

page = silkweb.fetch("https://example.com")
titles = page.css("h1, h2, h3")         # CSS selector
links = page.xpath("//a/@href")          # XPath
text = page.text                         # main content via Trafilatura
```

### Async usage
```python
import asyncio
import silkweb

async def main():
    page = await silkweb.async_fetch("https://example.com")
    data = await silkweb.async_ask(page, "product name and price")
    return data

asyncio.run(main())
```

---

## 4. Core Concepts

### The Page object

Every fetch returns a `SilkPage` object — the central data structure in Silkweb:

```python
page = silkweb.fetch("https://example.com")

page.html          # raw HTML string
page.text          # main content text (Trafilatura-cleaned)
page.markdown      # LLM-ready Markdown (ReaderLM-v2)
page.url           # final URL (after redirects)
page.status        # HTTP status code
page.headers       # response headers
page.metadata      # Open Graph, JSON-LD, Twitter Cards, author, date
page.fetch_tier    # which fetcher tier was used (0-4)

# Selectors
page.css("selector")            # returns list of SilkElement
page.xpath("expression")        # returns list of SilkElement
page.find("product title")      # adaptive selector (text/structure)

# LLM extraction
page.ask("product name and price")
page.extract(schema=Product)
page.query("{ products[] { name price } }")   # SilkQL
```

### The SilkElement object

```python
element = page.css("h1")[0]

element.text        # inner text
element.html        # inner HTML
element.attrs       # dict of attributes
element.xpath       # XPath address of this element (provenance)
element["href"]     # attribute shorthand
element.parent      # parent element
element.children    # list of child elements
element.siblings    # list of sibling elements
```

### Provenance

Every extracted field carries a `__silk_meta__` provenance record:

```python
products = page.extract(schema=Product)
print(products[0].__silk_meta__)
# {
#   'url': 'https://example.com/store',
#   'fetched_at': '2025-04-30T12:00:00Z',
#   'fetch_tier': 1,
#   'xpath': '/html/body/div[2]/article[1]/h2',
#   'llm_model': 'ollama/qwen2.5:14b',
#   'selector_from_cache': True,
#   'confidence': 0.97
# }
```

---

## 5. Fetcher Tiers

Silkweb uses a five-tier fetcher architecture. By default, it starts at the cheapest tier and **automatically escalates** when it detects blocks, JS-only content, or CAPTCHA challenges.

### Tier 0 — httpx (async HTTP)

Standard HTTP/1.1 and HTTP/2 requests via `httpx`. Fastest and cheapest. Used for REST APIs, simple static pages, and sitemaps.

```python
page = silkweb.fetch(url, tier=0)
```

**When used automatically:** static pages, APIs, URLs that return non-HTML content.

### Tier 1 — Stealth HTTP (curl_cffi)

HTTP requests with real-browser TLS fingerprints (JA3/JA4), HTTP/2 frame ordering, and header profiles matching Chrome, Firefox, or Safari. Bypasses the majority of WAF-based blocks without launching a browser.

```python
page = silkweb.fetch(url, tier=1)

# Specify browser profile
page = silkweb.fetch(url, tier=1, impersonate="chrome_124")
# Available: chrome_120, chrome_124, firefox_121, safari_17, edge_122
```

**When used automatically:** first retry after a 403 on Tier 0; sites known to use basic WAF checks.

### Tier 2 — Playwright (browser)

Full headless Chromium, Firefox, or WebKit browser via Playwright. Renders JavaScript, executes dynamic content, and supports network interception.

```python
page = silkweb.fetch(url, tier=2)

# Advanced options
page = silkweb.fetch(
    url,
    tier=2,
    browser="firefox",           # "chromium" | "firefox" | "webkit"
    wait_until="networkidle",    # "load" | "domcontentloaded" | "networkidle"
    wait_for="css:.product",     # wait for a specific element
    timeout=30_000,              # ms
    viewport={"width": 1920, "height": 1080},
    intercept_requests=True,     # capture XHR for hidden API discovery
)
```

**When used automatically:** JS-rendered pages, SPAs, pages with dynamic content loading.

### Tier 3 — Stealth Browser

Automatically selects the best stealth approach based on detected fingerprinting technology:

- **nodriver:** Direct Chrome CDP connection (no WebDriver protocol). Best for Cloudflare Turnstile, DataDome, PerimeterX.
- **Camoufox:** Patched Firefox binary with C++-level fingerprint spoofing. Best for sites fingerprinting Firefox.
- **Patchright:** Patched Playwright Chromium. Middle ground.

```python
page = silkweb.fetch(url, tier=3)

# Force a specific stealth engine
page = silkweb.fetch(url, tier=3, stealth_engine="nodriver")    # default
page = silkweb.fetch(url, tier=3, stealth_engine="camoufox")
page = silkweb.fetch(url, tier=3, stealth_engine="patchright")
```

**When used automatically:** Cloudflare challenge pages, 403s on Tier 1, sites with known aggressive bot detection.

### Tier 4 — Vision-Agent (LLM-driven browser)

An LLM agent controls a browser autonomously — clicking, scrolling, filling forms — until the target data is reachable. Powered by a vision LLM (default: Claude Sonnet for screenshot analysis).

```python
page = silkweb.fetch(
    url,
    tier=4,
    goal="navigate to the product listing for laptops and extract all items",
    max_steps=10
)
```

**When used automatically:** sites that require human-like interaction sequences to reveal data. Only activated explicitly or after manual configuration.

### Auto-escalation

```python
# Auto-escalation is on by default
page = silkweb.fetch(url)
# Silkweb tries Tier 0 → detects Cloudflare → upgrades to Tier 1 → success

# Disable auto-escalation
page = silkweb.fetch(url, auto_escalate=False)

# Set maximum tier for auto-escalation
page = silkweb.fetch(url, max_tier=2)  # will not use stealth browser
```

---

## 6. LLM Auto-Extraction

Auto-extraction is Silkweb's flagship feature. Given any page, Silkweb uses a decomposed three-model pipeline to understand the structure, infer a schema, extract structured data, and synthesize CSS/XPath selectors that are cached for future use.

### How it works (the three-model pipeline)

```
HTML Page
    │
    ▼
[Model 1: ReaderLM-v2]          — HTML → clean Flat JSON / Markdown
    │                             (removes nav, scripts, ads, boilerplate)
    │
    ▼
[Token Budget Planner]           — if too large: chunk with DOM-aware splitting
    │
    ▼
[Model 2: Qwen 2.5 Coder 14B]   — infer schema from cleaned content + user prompt
    │                             (generates a Pydantic model automatically)
    │
    ▼
[Model 3: LLM Extractor]         — extract data matching the schema (JSON-mode)
    │                             (returns JSON with XPath provenance per field)
    │
    ▼
[Model 2 again: Selector Compiler] — synthesize robust CSS + XPath selectors
    │                               with adaptive fallbacks
    │
    ▼
[Selector Cache]                 — stored keyed by (domain, DOM-skeleton-hash)
    │
    ▼
[Pydantic Validator]             — validate and return typed result
```

On all future pages matching the same template, **only the selector step runs** — no LLM calls.

### Basic auto-extraction

```python
import silkweb

# Let Silkweb figure everything out
result = silkweb.ask("https://books.toscrape.com", "all books with title, price and rating")
```

### Extraction with your own schema

```python
from pydantic import BaseModel
from typing import Optional
import silkweb

class Book(BaseModel):
    title: str
    price: float
    rating: int  # 1-5
    in_stock: bool
    description: Optional[str] = None

books = silkweb.extract(
    "https://books.toscrape.com",
    schema=Book,
    prompt="all books on the page"
)
# returns list[Book] — fully validated
```

### Controlling the extraction pipeline

```python
result = silkweb.extract(
    url,
    schema=Product,
    prompt="all products",

    # Model overrides
    cleaner_model="ollama/reader-lm-v2",
    extraction_model="ollama/qwen2.5:14b",
    selector_model="ollama/qwen2.5-coder:14b",

    # Chunking strategy when page is large
    chunk_strategy="bm25",       # "bm25" | "semantic" | "dom" | "token"
    max_tokens_per_chunk=8_000,

    # HTML representation fed to the LLM
    representation="flat_json",  # "flat_json" | "slim_html" | "markdown"

    # Cache behaviour
    use_cache=True,
    force_llm=False,             # bypass cache and always call LLM

    # Provenance
    include_provenance=True,     # attach __silk_meta__ to each result
)
```

### Streaming extraction

For large pages, results stream back as they are extracted:

```python
async for product in silkweb.async_stream_extract(url, schema=Product):
    print(product.name, product.price)
```

### Schema inference without extraction

```python
# Just infer the schema — don't extract data yet
schema = silkweb.infer_schema("https://amazon.com/dp/B0001", hint="product page")
print(schema.model_json_schema())
# { "title": "Product", "properties": { "name": {...}, "price": {...}, ... } }
```

---

## 7. Natural Language Querying

Natural language queries let you describe what you want in plain English. Silkweb compiles the query to a Pydantic schema, extracts the data, and returns typed Python objects.

### `silkweb.ask()` — the simplest interface

```python
import silkweb

# Returns list[dict] — schema inferred
data = silkweb.ask(url, "all product names and their prices in euros")

# Returns a specific type when unambiguous
count = silkweb.ask(url, "total number of results as an integer")  # → int

# With context
data = silkweb.ask(url, "only the out-of-stock products with their restock dates")
```

### Query modifiers

Natural language modifiers Silkweb understands:

```python
silkweb.ask(url, "top 5 articles by comment count")          # limit + sort
silkweb.ask(url, "all links that go to external domains")    # filtering
silkweb.ask(url, "every table on the page as separate lists") # multi-entity
silkweb.ask(url, "the main article text and its author")     # mixed types
silkweb.ask(url, "prices converted to USD using current rate")  # transformation
```

### Conversational / interactive mode

```python
with silkweb.Session("https://example.com/store") as session:
    session.fetch()                          # fetch once

    products = session.ask("all products")
    cheap = session.ask("only products under $50")
    rated = session.ask("their star ratings too")  # incremental

    # Refine iteratively without re-fetching
    final = session.ask("format as a table sorted by price")
```

### REPL

Launch an interactive exploration session from the terminal:

```bash
silkweb shell https://example.com/store
```

```
Silkweb Shell v0.1.0  |  https://example.com/store  |  Tier 1
Type a query, a SilkQL expression, or Python. Tab-complete available.

silk> ask("all product names and prices")
[{'name': 'Widget A', 'price': 29.99}, ...]

silk> ask("only the ones in stock")
[{'name': 'Widget A', 'price': 29.99}, ...]

silk> page.css("h1").text
'Best Widgets Online'

silk> page.metadata
{'title': ..., 'description': ..., 'author': ..., 'date': ...}
```

---

## 8. SilkQL Query Language

SilkQL is Silkweb's open-source structured query language for the web. Inspired by AgentQL, it is locally compilable, type-safe, and reusable across websites.

### Syntax overview

```
{
    field_name(type_coercion, modifier)
    collection[] {
        field
        nested_field {
            sub_field
        }
    }
}
```

### Basic example

```python
import silkweb

query = """
{
    products[] {
        name
        price(currency)
        rating(float)
        reviews_count(int)
        in_stock(bool)
        image_url(url)
        product_url(url)
    }
    total_results(int)
    pagination {
        current_page(int)
        next_page_url(url)
    }
}
"""

result = silkweb.query(url, query)
```

### Type coercions

SilkQL automatically coerces extracted strings to typed Python values:

| Coercion | Input example | Python type | Output |
|---|---|---|---|
| `(int)` | `"1,234"` | `int` | `1234` |
| `(float)` | `"€29.99"` | `float` | `29.99` |
| `(currency)` | `"$1,234.56"` | `float` | `1234.56` |
| `(bool)` | `"In Stock"` | `bool` | `True` |
| `(url)` | `"/products/1"` | `str` | `"https://example.com/products/1"` |
| `(iso_date)` | `"Apr 30, 2025"` | `datetime` | `datetime(2025, 4, 30)` |
| `(list)` | `"Red, Blue, Green"` | `list[str]` | `["Red", "Blue", "Green"]` |
| `(json)` | `'{"key": 1}'` | `dict` | `{"key": 1}` |

### Field modifiers

```
name(optional)             — field may not exist; returns None instead of error
price(currency, optional)
tags(list, min_count=1)    — at least 1 item required
id(int, unique)            — deduplicate if same value found multiple times
```

### Automatic pagination

When a query includes a `next_page_url(url)` field in a `pagination` block, Silkweb automatically follows it and merges results:

```python
result = silkweb.query(
    url,
    query,
    follow_pagination=True,
    max_pages=20
)
# result.products — merged across all pages
# result.pages_scraped — number of pages traversed
```

### Compiling SilkQL to Pydantic

```python
from silkweb.silkql import compile_query

PydanticModel = compile_query(query)
# PydanticModel is now a usable Pydantic BaseModel subclass
```

### SilkQL in Python (code API)

```python
from silkweb import Q

result = silkweb.query(url, Q.root(
    Q.list("products",
        Q.field("name"),
        Q.field("price", type="currency"),
        Q.field("rating", type="float", optional=True),
    ),
    Q.field("next_page", type="url", optional=True)
))
```

---

## 9. HTML Parsing & Selectors

Silkweb provides a rich selector API on top of lxml and its own adaptive selector engine.

### CSS selectors

```python
page = silkweb.fetch(url)

# Returns list[SilkElement]
items = page.css(".product-card")

# Chained
prices = page.css(".product-card").css(".price")

# First match
title = page.css_first("h1")

# Text shorthand
title_text = page.css_first("h1").text
```

### XPath selectors

```python
links = page.xpath("//a[@class='product-link']/@href")
prices = page.xpath("//span[contains(@class, 'price')]/text()")
```

### Adaptive selectors

Adaptive selectors generate multiple fallback strategies and return the first that matches, making scrapers resilient to CSS class renames:

```python
# Tries: class match → text match → structural position → attribute similarity
items = page.find(".product-title", adaptive=True)

# Explicit fallback chain
items = page.find(
    primary=".product-card h2",
    fallbacks=[
        "//div[@data-type='product']//h2",
        ".item-name",
        "//h2[contains(@class, 'title')]",
    ]
)
```

### Built-in smart extractors

```python
# Extract all tables → list of DataFrames
tables = page.tables()

# Extract all JSON-LD structured data
json_ld = page.json_ld()   # list[dict]

# Extract Open Graph / Twitter Card metadata
meta = page.metadata       # {'title': ..., 'description': ..., 'image': ..., 'author': ...}

# Extract all links
links = page.links()                  # all links
external = page.links(external=True)  # external only

# Extract main article text (Trafilatura)
article = page.article()    # {'title', 'text', 'author', 'date', 'language'}

# Extract hydration data (Next.js / Nuxt / Remix / SvelteKit)
data = page.hydration_data()   # parsed JSON from __NEXT_DATA__, __NUXT__, etc.
                               # often contains the complete page data as JSON
```

### Repeated pattern detection (no LLM)

```python
# Automatically detect and extract repeating record structures
records = page.detect_records()
# [{'title': '...', 'price': '...', 'image': '...'}, ...]
```

---

## 10. Anti-Bot & Stealth

Silkweb bundles the most comprehensive open-source anti-bot stack available, all configured automatically.

### TLS & HTTP fingerprinting

Via `curl_cffi`, Silkweb mimics the exact TLS handshake, cipher suite order, HTTP/2 settings frames, and header order of real browsers.

```python
silkweb.fetch(url, impersonate="chrome_124")
silkweb.fetch(url, impersonate="firefox_121")
silkweb.fetch(url, impersonate="safari_17")
silkweb.fetch(url, impersonate="edge_122")
```

### Proxy management

```python
# Single proxy
silkweb.fetch(url, proxy="http://user:pass@proxy.example.com:8080")

# Proxy pool with automatic rotation
silkweb.configure(proxies=[
    "http://user:pass@proxy1.example.com:8080",
    "http://user:pass@proxy2.example.com:8080",
    "socks5://user:pass@proxy3.example.com:1080",
])

# Rotation strategy
silkweb.configure(
    proxies=my_proxy_list,
    proxy_rotation="per_request",   # "per_request" | "per_domain" | "on_failure" | "sticky"
    sticky_session_ttl=300,         # seconds (for sticky mode)
)
```

### Rate limiting

```python
silkweb.configure(
    rate_limit={
        "global": 10,              # max 10 requests/second globally
        "per_domain": 2,           # max 2 requests/second per domain
        "respect_crawl_delay": True,  # honor robots.txt Crawl-delay
        "jitter": 0.3,             # add up to 30% random delay
    }
)
```

### Behavioral stealth

```python
silkweb.configure(
    stealth={
        "human_mouse": True,          # Bezier-curve mouse movements
        "human_typing": True,         # randomized typing speed/delays
        "random_scroll": True,        # natural scroll patterns
        "viewport_noise": True,       # slight viewport randomization
        "timezone": "America/New_York",
        "locale": "en-US",
        "geolocation": {"lat": 40.7, "lng": -74.0},
    }
)
```

### CAPTCHA solving

```python
silkweb.configure(
    captcha_solver="local",           # "local" | "2captcha" | "anticaptcha" | "capsolver"
    captcha_api_key="...",            # for cloud solvers
)
```

The `"local"` solver handles:
- **Cloudflare Turnstile** via SeleniumBase UC Mode strategy
- **reCAPTCHA v2** via audio challenge solver
- **hCaptcha** via WASM-based solver

### Robots.txt compliance

```python
# Default: respect robots.txt
silkweb.fetch(url)

# Override (use responsibly and legally)
silkweb.fetch(url, respect_robots=False)

# Just check without fetching
allowed = silkweb.robots_allowed(url, user_agent="SilkwebBot/1.0")
```

---

## 11. LLM Providers & Configuration

### Configuring providers

```python
import silkweb

silkweb.configure(
    # Assign models per task
    cleaner_model    = "ollama/reader-lm-v2",       # HTML → Markdown / Flat JSON
    schema_model     = "ollama/qwen2.5-coder:14b",  # schema inference + selector synthesis
    extraction_model = "ollama/qwen2.5:14b",        # data extraction
    embedding_model  = "ollama/nomic-embed-text",   # BM25/semantic chunking
    vision_model     = "anthropic/claude-3-5-sonnet-20241022",  # vision fallback only
)
```

### Supported providers and model URI format

```
"ollama/<model>"                        → Ollama at localhost:11434
"openai/<model>"                        → OpenAI API
"anthropic/<model>"                     → Anthropic API
"google/<model>"                        → Google Gemini API
"groq/<model>"                          → Groq API
"mistral/<model>"                       → Mistral API
"together/<model>"                      → Together AI
"bedrock/<region>/<model>"              → AWS Bedrock
"azure/<deployment>"                    → Azure OpenAI
"vertex/<project>/<model>"             → Google Vertex AI
"llamacpp/<path/to/model.gguf>"        → llama.cpp embedded (no server needed)
"vllm/<model>"                          → vLLM server
"lmstudio/<model>"                      → LM Studio (OpenAI-compatible)
"mlx/<model>"                          → Apple MLX (Apple Silicon)
"openai_compatible/<base_url>/<model>" → Any OpenAI-compatible endpoint
```

### Recommended local models by use case

| Task | Recommended model | VRAM | Notes |
|---|---|---|---|
| HTML cleaning | `reader-lm-v2` | 2 GB | Jina specialist, 512K context |
| Schema synthesis | `qwen2.5-coder:14b` | 8 GB | Best code/structure understanding |
| Data extraction | `qwen2.5:14b` | 8 GB | Best overall for structured output |
| Embeddings | `nomic-embed-text` | 0.5 GB | Fast, high quality |
| Vision fallback | `llava:13b` or cloud | 8 GB | For screenshot-based extraction |
| Reasoning | `deepseek-r1:14b` | 8 GB | Complex multi-step extractions |

### Bundled starter mode

On first import, Silkweb auto-detects Ollama and available models:

```python
import silkweb

# Auto-configure from detected local models
silkweb.auto_configure()

# Or pull recommended models automatically
silkweb.setup_recommended_models()
# Downloads: reader-lm-v2, qwen2.5-coder:14b, nomic-embed-text via Ollama
```

### API keys

```bash
# Environment variables (recommended)
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_API_KEY=...
```

```python
# Or in code
silkweb.configure(
    api_keys={
        "openai": "sk-...",
        "anthropic": "sk-ant-...",
    }
)
```

---

## 12. Output Formats

### Python dict / list (default)

```python
data = silkweb.ask(url, "products")
# [{'name': '...', 'price': 29.99}, ...]
```

### Pydantic models

```python
products: list[Product] = silkweb.extract(url, schema=Product)
products[0].model_dump()
products[0].model_dump_json()
```

### Pandas DataFrame

```python
df = silkweb.to_dataframe(url, "all products")
# Auto-detected if pandas is installed: silkweb.ask() returns a DataFrame

import pandas as pd
df = silkweb.ask(url, "all products")   # returns DataFrame when pandas is active
```

### Polars DataFrame

```python
import polars as pl
df = silkweb.ask(url, "all products")   # returns Polars DataFrame when polars is active

# Explicit
df = silkweb.to_polars(url, "all products")
```

### JSON / JSONL

```python
silkweb.to_json(url, "products", output="products.json")
silkweb.to_jsonl(url, "products", output="products.jsonl")
silkweb.to_json(url, "products", output="products.json.gz")  # auto-gzip
```

### CSV

```python
silkweb.to_csv(url, "products", output="products.csv")
```

### Parquet

```python
silkweb.to_parquet(url, "products", output="products.parquet")
```

### DuckDB / SQLite

```python
silkweb.to_duckdb(url, "products", db="store.duckdb", table="products")
silkweb.to_sqlite(url, "products", db="store.sqlite", table="products")
```

### Markdown (for RAG)

```python
md = silkweb.to_markdown(url)               # full page as Markdown
silkweb.to_markdown(url, output="page.md")  # save to file
```

### HuggingFace Dataset

```python
dataset = silkweb.to_dataset(url, "all articles")
dataset.push_to_hub("your-org/dataset-name")
```

---

## 13. Caching

### Three-layer cache

**Layer 1 — HTTP cache:** stores raw HTTP responses with conditional GET support (ETag / Last-Modified). Prevents redundant network requests.

**Layer 2 — Rendered page cache:** stores post-JavaScript DOM snapshots. Prevents redundant browser launches.

**Layer 3 — Selector cache:** stores LLM-synthesized CSS/XPath selectors keyed by `(domain, DOM-skeleton-hash)`. This is the most important cache — it means the LLM is called only once per page template.

### Cache configuration

```python
silkweb.configure(
    cache={
        "enabled": True,
        "backend": "sqlite",        # "sqlite" | "redis" | "memory"
        "path": "~/.silkweb/cache", # for sqlite
        "redis_url": "redis://localhost:6379",   # for redis backend
        "http_ttl": 3600,           # HTTP cache TTL in seconds (1 hour)
        "page_ttl": 1800,           # Rendered page cache TTL (30 min)
        "selector_ttl": None,       # Selector cache TTL (None = forever)
        "max_size_gb": 5,           # Max cache size
    }
)
```

### Managing the cache

```python
# Inspect cache stats
stats = silkweb.cache.stats()
# {'http_entries': 1234, 'page_entries': 89, 'selector_entries': 42, 'size_mb': 234}

# Clear specific cache layers
silkweb.cache.clear(layer="http")
silkweb.cache.clear(layer="selectors")
silkweb.cache.clear()  # clear all

# Clear selectors for a specific domain (force LLM re-learning)
silkweb.cache.clear_domain("amazon.com", layer="selectors")

# Force bypass cache for a single request
page = silkweb.fetch(url, no_cache=True)
data = silkweb.ask(url, "products", force_llm=True)
```

---

## 14. Crawling & Concurrency

### Simple multi-URL fetch

```python
pages = silkweb.fetch_all([url1, url2, url3], concurrency=10)
```

### Full crawl

```python
results = silkweb.crawl(
    start_url="https://example.com",

    # What to follow
    follow_links=True,
    allowed_domains=["example.com"],
    url_pattern=r"/products/\d+",     # regex filter on URLs to follow

    # Extraction
    schema=Product,
    prompt="product data",

    # Limits
    max_pages=1000,
    max_depth=3,
    concurrency=20,
    per_domain_concurrency=5,

    # Callbacks
    on_page=lambda page: print(f"scraped {page.url}"),
    on_item=lambda item: db.insert(item),
    on_error=lambda url, err: logger.error(f"failed {url}: {err}"),

    # Dedup
    dedup=True,                       # skip already-visited URLs
    dedup_backend="sqlite",           # or "redis" for distributed

    # Output
    output="products.jsonl",
)
```

### Sitemap crawl

```python
# Crawl all URLs from a sitemap
results = silkweb.crawl_sitemap(
    "https://example.com/sitemap.xml",
    schema=Article,
    prompt="article content",
    concurrency=30,
)
```

### Feed crawl

```python
# Crawl an RSS/Atom feed
items = silkweb.crawl_feed("https://news.ycombinator.com/rss")
```

### Async streaming crawl

```python
async for item in silkweb.async_crawl(start_url, schema=Product):
    await db.insert(item)
```

---

## 15. Session Management & Authentication

### Basic session persistence

```python
# Create a named session (cookies, storage, headers persist)
session = silkweb.Session("my_session")

# Log in once
session.fetch("https://example.com/login")
session.fill("#username", "user@example.com")
session.fill("#password", "password123")
session.click("#login-btn")
session.wait_for(".dashboard")

# Save session to disk
session.save()   # saves to ~/.silkweb/sessions/my_session.silkweb

# Later, resume without logging in again
session = silkweb.Session.load("my_session")
page = session.fetch("https://example.com/protected-data")
```

### Action recorder

```python
# Record a browser session interactively
silkweb.record("my_login_flow")
# Opens a browser — you log in manually — recording is saved

# Replay the recording
silkweb.replay("my_login_flow")
page = silkweb.fetch("https://example.com/data", session="my_login_flow")
```

### OAuth / SSO hand-off

```python
# Opens a real browser for OAuth flow, captures tokens, then switches to headless
session = silkweb.oauth_session(
    url="https://app.example.com",
    session_name="example_oauth"
)
```

---

## 16. Hidden API Discovery

One of Silkweb's most powerful features: instead of scraping the DOM of a JavaScript-heavy page, discover the underlying JSON API it calls and use that directly.

```python
api_info = silkweb.discover_api("https://example.com/store")

print(api_info)
# {
#   'endpoints': [
#     {
#       'url': 'https://api.example.com/v2/products?page=1&limit=24',
#       'method': 'GET',
#       'headers': { 'x-api-token': '...' },
#       'response_schema': { 'items': [...], 'total': 1234 },
#       'pagination': 'cursor',
#     }
#   ],
#   'generated_scraper': '...',  # Python code using httpx directly
# }

# Generate and save a pure-httpx scraper (no browser needed)
silkweb.discover_api(
    "https://example.com/store",
    output="example_api_scraper.py"
)
```

The generated scraper uses direct HTTP calls — typically 10–100× faster than DOM scraping.

---

## 17. Watch & Change Detection

Monitor pages for changes and extract diffs automatically.

### Basic watch

```python
# Watch a page and print changes
silkweb.watch(
    "https://example.com/pricing",
    schema=PricingPlan,
    interval=3600,              # check every hour
    on_change=lambda diff: print(diff),
)
```

### Diff structure

```python
{
    'url': 'https://example.com/pricing',
    'checked_at': '2025-04-30T12:00:00Z',
    'previous_checked_at': '2025-04-30T11:00:00Z',
    'changed': True,
    'changes': [
        {
            'field': 'price',
            'record_id': 'plan_pro',
            'old_value': 49.0,
            'new_value': 59.0,
            'change_type': 'modified',
        },
        {
            'field': 'name',
            'change_type': 'added',
            'new_value': 'Enterprise Plus',
        }
    ]
}
```

### Watch with webhook / callback

```python
silkweb.watch(
    url,
    schema=Product,
    interval=1800,
    on_change=lambda diff: requests.post("https://myapp.com/webhook", json=diff),
    on_error=lambda err: logger.error(err),
    notify_on_no_change=False,   # silent when nothing changed
)
```

### Running multiple watches

```python
# Background watcher (non-blocking)
watcher = silkweb.Watcher()

watcher.add("https://site1.com/products", schema=Product, interval=3600)
watcher.add("https://site2.com/prices", schema=Price, interval=1800)

watcher.start()   # runs in background thread
# ...
watcher.stop()
```

---

## 18. CLI Reference

```bash
# Fetch a URL and print cleaned text
silkweb fetch https://example.com

# Fetch with specific tier
silkweb fetch https://example.com --tier 1

# Ask a natural language question
silkweb ask https://example.com "all product names and prices"

# Extract with a schema file
silkweb extract https://example.com --schema product.py --output products.json

# Open interactive shell
silkweb shell https://example.com

# Crawl a site
silkweb crawl https://example.com --url-pattern "/products/*" --schema product.py --output products.jsonl

# Discover hidden APIs
silkweb discover-api https://example.com --output scraper.py

# Watch a page for changes
silkweb watch https://example.com "prices" --interval 3600

# Manage local models
silkweb models list
silkweb models pull qwen2.5:14b
silkweb models recommend         # shows recommended models for your hardware

# Cache management
silkweb cache stats
silkweb cache clear --layer selectors
silkweb cache clear --domain amazon.com

# Validate a SilkQL query
silkweb silkql validate query.silk

# Browse the recipe library
silkweb recipes list
silkweb recipes show hacker-news
silkweb recipes run hacker-news --output hn.json
```

---

## 19. Error Handling

### Exception hierarchy

```
SilkwebError
├── SilkwebFetchError
│   ├── SilkwebHTTPError          — non-2xx response
│   ├── SilkwebTimeoutError       — request timed out
│   ├── SilkwebBlockedError       — bot detection confirmed
│   └── SilkwebRenderError        — JS rendering failed
├── SilkwebExtractionError
│   ├── SilkwebSchemaError        — Pydantic validation failed
│   ├── SilkwebLLMError           — LLM call failed or returned invalid JSON
│   └── SilkwebSelectorError      — no elements matched selector
├── SilkwebCacheError
└── SilkwebConfigError
```

### Error context

Every exception carries structured context:

```python
try:
    data = silkweb.ask(url, "products")
except silkweb.SilkwebBlockedError as e:
    print(e.url)            # URL that was blocked
    print(e.status_code)    # 403
    print(e.tier_tried)     # which tier failed
    print(e.challenge_type) # "cloudflare_turnstile"
    print(e.html_snippet)   # first 500 chars of response
```

### Retry configuration

```python
silkweb.configure(
    retry={
        "max_attempts": 5,
        "backoff": "exponential",          # "exponential" | "linear" | "constant"
        "backoff_base": 2,                 # seconds
        "backoff_max": 60,                 # max seconds between retries
        "jitter": True,
        "retry_on": [429, 503, 502, 520],  # HTTP codes to retry
        "auto_escalate_on_block": True,    # upgrade tier on BlockedError
    }
)
```

### Self-healing selectors

```python
silkweb.configure(
    self_heal={
        "enabled": True,
        "threshold": 0,          # re-trigger LLM if 0 elements matched
        "validation_fn": None,   # custom Pydantic validator to trigger re-heal
        "max_heal_attempts": 3,
    }
)
```

---

## 20. Observability

### Structured logging

```python
import silkweb
import logging

silkweb.configure(
    log_level="INFO",      # "DEBUG" | "INFO" | "WARNING" | "ERROR"
    log_format="json",     # "json" | "text"
    log_file="silkweb.log",
)
```

Log output (JSON format):
```json
{
  "timestamp": "2025-04-30T12:00:00Z",
  "event": "fetch_completed",
  "url": "https://example.com",
  "tier": 1,
  "status_code": 200,
  "duration_ms": 234,
  "cache_hit": false,
  "llm_calls": 0
}
```

### OpenTelemetry traces

```python
silkweb.configure(
    telemetry={
        "enabled": True,
        "exporter": "otlp",                           # "otlp" | "jaeger" | "zipkin" | "console"
        "endpoint": "http://localhost:4317",
        "service_name": "my-scraper",
    }
)
```

Each scraping operation generates spans for: HTTP fetch → JS render → LLM clean → LLM extract → cache write → validation.

### Prometheus metrics

```python
# Expose metrics endpoint
silkweb.configure(metrics_port=9090)
```

Available metrics:
- `silkweb_requests_total{tier, status, domain}`
- `silkweb_request_duration_seconds{tier, domain}`
- `silkweb_llm_calls_total{model, task}`
- `silkweb_llm_duration_seconds{model, task}`
- `silkweb_cache_hits_total{layer}`
- `silkweb_blocks_total{domain, challenge_type}`

### Replay / debugging

```python
# Save a session for debugging
silkweb.configure(replay_dir="./silkweb_replays")

# Replay a session deterministically (uses saved HTML, no network)
silkweb.replay("./silkweb_replays/session_2025-04-30.silkweb")
```

---

## 21. Developer Experience

### VS Code Extension

Install **"Silkweb"** from the VS Code Marketplace for:
- SilkQL syntax highlighting and autocompletion
- Inline schema preview from a URL
- One-click "Scrape this URL" command
- Selector cache browser sidebar

### Browser DevTools Extension

Install **"Silkweb Inspector"** for Chrome/Firefox:
- Point and click on page elements
- Generates SilkQL query automatically
- Shows cached selectors for the current domain
- Live extraction preview

### Jupyter Notebook support

```python
import silkweb

# Rich HTML rendering in notebooks
page = silkweb.fetch(url)
silkweb.display(page)          # renders page screenshot + metadata

products = silkweb.ask(url, "products")
silkweb.display(products)       # renders as interactive table
```

### Testing

```python
# Mock mode — no real HTTP requests
with silkweb.mock_mode():
    silkweb.mock.register("https://example.com", html="<h1>Test</h1>")
    page = silkweb.fetch("https://example.com")
    assert page.css_first("h1").text == "Test"

# Replay mode — use recorded sessions
with silkweb.replay_mode("./fixtures/example_session.silkweb"):
    data = silkweb.ask("https://example.com", "products")
```

---

## 22. Architecture Deep Dive

### Module layout

```
silkweb/
├── __init__.py              # public API surface
├── fetch/
│   ├── tiers/
│   │   ├── httpx.py         # Tier 0
│   │   ├── curl_cffi.py     # Tier 1
│   │   ├── playwright.py    # Tier 2
│   │   ├── stealth.py       # Tier 3 (nodriver / camoufox)
│   │   └── agent.py         # Tier 4 (LLM vision agent)
│   ├── orchestrator.py      # auto-escalation logic
│   └── fingerprint.py       # TLS/HTTP profile management
├── parse/
│   ├── page.py              # SilkPage, SilkElement
│   ├── selectors.py         # CSS + XPath + adaptive
│   ├── content.py           # Trafilatura, article extraction
│   ├── hydration.py         # Next.js / Nuxt / Remix JSON
│   └── patterns.py          # repeated-record detection
├── llm/
│   ├── providers/           # OpenAI, Anthropic, Ollama, llama.cpp, etc.
│   ├── pipelines/
│   │   ├── clean.py         # ReaderLM-v2 / Trafilatura
│   │   ├── schema.py        # schema inference
│   │   ├── extract.py       # data extraction
│   │   ├── selectors.py     # selector synthesis
│   │   └── heal.py          # self-healing
│   ├── chunking/            # token, BM25, semantic, DOM-aware
│   ├── representations/     # flat_json, slim_html, markdown
│   ├── constrained.py       # Outlines / lm-format-enforcer
│   └── prompts/             # versioned prompt templates
├── silkql/
│   ├── parser.py            # SilkQL grammar and parser
│   ├── compiler.py          # SilkQL → Pydantic model
│   └── executor.py          # SilkQL → extraction pipeline
├── cache/
│   ├── http.py              # hishel-based HTTP cache
│   ├── page.py              # rendered-page cache
│   └── selectors.py         # selector + schema cache
├── crawl/
│   ├── crawler.py           # full-site crawler
│   ├── queue.py             # async request queue
│   └── dedup.py             # URL deduplication
├── stealth/
│   ├── proxy.py             # proxy pool management
│   ├── rate_limit.py        # token-bucket rate limiter
│   ├── captcha.py           # CAPTCHA solvers
│   └── behavior.py          # mouse / scroll / typing
├── session/
│   ├── session.py           # session persistence
│   └── recorder.py          # action recorder / replayer
├── watch.py                 # page change detection
├── discover.py              # hidden API discovery
├── output/                  # pandas, polars, json, csv, parquet, duckdb
├── config.py                # global configuration
├── exceptions.py            # typed exception hierarchy
├── observability/           # logging, OTEL, Prometheus
└── cli/                     # Typer CLI commands
```

### Dependency philosophy

Silkweb has a **zero-LangChain, zero-LlamaIndex policy**. All LLM provider integrations are direct SDK calls through a thin 300-line `LLMProvider` abstraction. This keeps the install small, avoids API breakage, and makes Silkweb's transitive dependency tree manageable.

### Core dependencies

| Package | Purpose |
|---|---|
| `httpx` | Async HTTP client |
| `curl_cffi` | Browser-fingerprint HTTP |
| `playwright` | Browser automation |
| `lxml` | HTML/XML parser (CSS via `lxml.cssselect`, XPath via `lxml`) |
| `parsel` | Scrapy-style CSS/XPath |
| `trafilatura` | Article/content extraction |
| `pydantic` v2 | Schema validation |
| `anyio` | Async backend (asyncio + trio) |
| `hishel` | HTTP caching |
| `diskcache` | Disk-based cache |
| `typer` + `rich` | CLI |
| `structlog` | Structured logging |
| `outlines` | Constrained LLM decoding |
| `diskcache` | Present as a dependency; not currently used as a `cache_backend` implementation |

### Optional dependencies (extras)

| Extra | Packages | Purpose |
|---|---|---|
| `browser` | playwright, playwright-stealth | Full browser support |
| `stealth` | nodriver, camoufox, patchright | Stealth browsers |
| `ollama` | ollama | Local Ollama models |
| `openai` | openai | OpenAI API |
| `anthropic` | anthropic | Anthropic Claude |
| `llama-cpp` | llama-cpp-python | Embedded llama.cpp |
| `vllm` | vllm | vLLM server |
| `pandas` | pandas | DataFrame output |
| `polars` | polars | Polars DataFrame output |
| `duckdb` | duckdb | DuckDB output |
| `otel` | opentelemetry-* | OpenTelemetry tracing |

---

## 23. Configuration Reference

Full configuration with all defaults:

```python
import silkweb

silkweb.configure(
    # === LLM Models ===
    cleaner_model="ollama/reader-lm-v2",
    schema_model="ollama/qwen2.5-coder:14b",
    extraction_model="ollama/qwen2.5:14b",
    embedding_model="ollama/nomic-embed-text",
    vision_model=None,                      # None = disabled unless needed

    # === Fetcher ===
    default_tier="auto",                    # "auto" | 0 | 1 | 2 | 3 | 4
    max_tier=3,                             # max tier for auto-escalation
    auto_escalate=True,
    timeout=30_000,                         # ms
    user_agent="Mozilla/5.0 ...",           # default browser UA
    impersonate="chrome_124",               # default curl_cffi profile
    headers={},                             # default extra headers

    # === Extraction ===
    chunk_strategy="bm25",                  # "bm25" | "semantic" | "dom" | "token"
    max_tokens_per_chunk=8_000,
    representation="flat_json",             # "flat_json" | "slim_html" | "markdown"
    include_provenance=True,
    force_llm=False,
    hydration_first=True,                   # try Next.js/Nuxt JSON before DOM

    # === Cache ===
    cache_enabled=True,
    cache_backend="sqlite",
    cache_path="~/.silkweb/cache",
    http_cache_ttl=3600,
    page_cache_ttl=1800,
    selector_cache_ttl=None,

    # === Proxy & Rate Limiting ===
    proxies=[],
    proxy_rotation="on_failure",
    rate_limit_global=None,
    rate_limit_per_domain=2,
    respect_robots=True,

    # === Retry ===
    max_retries=3,
    retry_backoff="exponential",
    retry_backoff_base=2,

    # === Stealth ===
    human_mouse=False,
    human_typing=False,
    captcha_solver=None,

    # === Output ===
    default_output_format="python",         # "python" | "json" | "csv" | "parquet" | "df"
    auto_detect_dataframe=True,             # return DataFrame if pandas/polars imported

    # === Observability ===
    log_level="WARNING",
    log_format="text",
    metrics_port=None,
    telemetry_enabled=False,
)
```

---

## 24. Recipes Library

Silkweb ships with community-contributed, version-pinned schemas and configurations for common scraping targets. Recipes are fully offline and use only the cached selector system.

```bash
silkweb recipes list
```

| Recipe | Description |
|---|---|
| `hacker-news` | Front page stories, scores, authors, comments |
| `github-repo` | Stars, forks, topics, README content |
| `github-issues` | Issue list with labels, assignees, timestamps |
| `amazon-product` | Title, ASIN, price, rating, reviews, variants |
| `amazon-search` | Search results with prices and ratings |
| `google-serp` | Organic results, featured snippets, PAA |
| `reddit-posts` | Post list with scores, authors, flairs |
| `linkedin-profile` | Public profile: headline, experience, education |
| `twitter-profile` | Bio, followers, following, pinned tweet |
| `youtube-video` | Title, views, description, channel, upload date |
| `wikipedia` | Article text, infobox, categories, references |
| `imdb-movie` | Title, rating, cast, plot, genres |
| `arxiv-paper` | Title, authors, abstract, categories, PDF link |
| `product-listing` | Generic e-commerce product listing (any site) |
| `news-article` | Generic article extraction (any news site) |

```python
# Use a recipe
import silkweb

articles = silkweb.recipes.run(
    "hacker-news",
    url="https://news.ycombinator.com",
)

# Preview a recipe
print(silkweb.recipes.show("amazon-product"))

# Contribute a recipe
silkweb.recipes.create(
    name="my-recipe",
    url="https://example.com",
    schema=MySchema,
    description="Extracts products from example.com",
)
```

---

## 25. FAQ

**Q: Does Silkweb work without any LLM?**
Yes. All LLM features are opt-in. Silkweb works as a fast, stealth-capable scraping library without any LLM configured.

**Q: Is my data sent to a cloud LLM?**
Only if you configure a cloud provider. The default configuration uses Ollama on localhost. All processing is private and local by default.

**Q: How does the selector cache work?**
The first time Silkweb extracts data from a URL template, it uses the LLM pipeline and stores the resulting selectors in a local SQLite database. All future requests to pages with the same DOM structure use only CSS/XPath — no LLM call. The cache is keyed by a hash of the DOM skeleton (tag structure without content), so it is resilient to content changes.

**Q: What happens when a cached selector stops working?**
Self-healing is enabled by default. If a cached selector returns 0 results or fails Pydantic validation, Silkweb automatically re-invokes the LLM to synthesize new selectors, then updates the cache.

**Q: How large can pages be?**
Silkweb handles large pages through its token budget planner. ReaderLM-v2 typically reduces a 200K-token raw HTML page to 5–20K tokens. If still too large for the configured model context, DOM-aware chunking splits by semantic boundaries and results are merged.

**Q: Can I use Silkweb for authenticated scraping?**
Yes. Use `silkweb.Session` for session persistence, `silkweb.record()` for recording login flows, and the OAuth hand-off for SSO. Sessions are stored as portable `.silkweb-session` files.

**Q: Is Silkweb legal to use?**
Silkweb is a tool. Whether scraping a particular website is legal depends on the website's Terms of Service, local laws (CFAA, GDPR, etc.), and the nature of the data. By default, Silkweb respects `robots.txt`. Always check the legal context for your specific use case.

**Q: How does Silkweb compare to Scrapy?**
Scrapy is a mature, powerful framework optimized for large-scale crawls with a complex component model. Silkweb prioritizes developer ergonomics and LLM-first extraction. They serve different needs. For very large-scale production crawls (millions of pages/day), Scrapy's ecosystem is unmatched. For rapid development, LLM extraction, and local-first use, Silkweb is simpler and more powerful.

**Q: What is SilkQL?**
SilkQL is Silkweb's open-source structured query language for describing what to extract from a web page. It is inspired by AgentQL but is fully local, open-source, and compiles to Pydantic models. See [Section 8](#8-silkql-query-language).

**Q: Can I contribute a recipe?**
Yes. Recipes are YAML files in the `silkweb-recipes` repository. Submit a pull request with your schema, a sample URL, and expected output.

---

## License

MIT License. Copyright © 2025 Silkweb Contributors.

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Acknowledgements

Silkweb builds on the shoulders of giants: Scrapy, Playwright, nodriver, Camoufox, curl_cffi, Trafilatura, lxml, Pydantic, Crawl4AI, ScrapeGraphAI, AgentQL, and the open-weights model community (Qwen, Meta, Jina AI).
