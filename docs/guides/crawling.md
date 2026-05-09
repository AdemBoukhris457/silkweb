# Crawling & Concurrency

Silkweb's `AsyncCrawler` provides concurrent, rate-limited web crawling with built-in URL deduplication and structured data extraction.

## Basic crawling

```python
import asyncio
import silkweb
from silkweb.crawl.crawler import AsyncCrawler

async def main():
    crawler = AsyncCrawler(
        start_url="https://books.toscrape.com",
        allowed_domains=["books.toscrape.com"],
        max_pages=50,
        concurrency=5,
    )

    async for item in crawler.run():
        print(item)

asyncio.run(main())
```

## Crawl with extraction

Combine crawling with LLM extraction by providing **both** a `schema` and a `prompt` (if either is omitted, pages are still fetched but nothing is extracted). The crawler uses the same cleaner, extraction, and selector models as `silkweb.extract` (including self-heal on the extraction path).

```python
from pydantic import BaseModel

class Book(BaseModel):
    title: str
    price: float
    rating: int

crawler = AsyncCrawler(
    start_url="https://books.toscrape.com",
    allowed_domains=["books.toscrape.com"],
    max_pages=20,
    schema=Book,
    prompt="book title, price, and star rating",
)

async for book in crawler.run():
    print(f"{book.title}: £{book.price}")
```

## Configuration options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `start_url` | `str` | required | Starting URL (HTTP(S) fragment is stripped for dedup) |
| `allowed_domains` | `set[str]` / iterable | `None` | Only crawl these domains (all allowed if unset) |
| `url_pattern` | `str` | `None` | Regex filter for URLs to visit |
| `max_pages` | `int` | `100` | Stop after this many **fetched** pages |
| `max_depth` | `int` | `2` | Maximum link depth from start URL |
| `concurrency` | `int` | `10` | Total concurrent workers |
| `per_domain_concurrency` | `int` | `2` | Concurrent requests per domain |
| `max_pending_urls` | `int` | `5000` | Best-effort cap on the crawl work-queue size (link discovery) |
| `schema` | `BaseModel` | `None` | Pydantic model for extraction (requires `prompt`) |
| `prompt` | `str` | `None` | Extraction prompt (requires `schema`) |

## URL filtering

Control which URLs get crawled:

```python
crawler = AsyncCrawler(
    start_url="https://example.com",
    allowed_domains=["example.com"],
    url_pattern=r"/products/\d+",  # only product detail pages
    max_depth=3,
)
```

URLs are discovered from `page.links()` and filtered by:

1. `allowed_domains` — domain whitelist
2. `url_pattern` — regex match on full URL
3. `max_depth` — link distance from start URL
4. Deduplication — each URL is visited at most once

## URL deduplication

The `SeenSet` tracks visited URLs using a SQLite-backed persistent set (or in-memory for ephemeral crawls):

```python
from silkweb.crawl.dedup import SeenSet

seen = SeenSet(backend="sqlite")
seen.add("https://example.com/page1")  # returns True (new)
seen.add("https://example.com/page1")  # returns False (seen)
print(seen.stats())
# {'backend': 'sqlite', 'entries': 1, ...}
```

## Callbacks

Register async callbacks for fine-grained control:

```python
async def on_page(page):
    print(f"Fetched: {page.url} ({page.status})")

async def on_item(item):
    # Save to database, send to queue, etc.
    await save_to_db(item)

async def on_error(url, error):
    print(f"Error on {url}: {error}")

crawler = AsyncCrawler(
    start_url="https://example.com",
    on_page=on_page,
    on_item=on_item,
    on_error=on_error,
)
```

## Concurrency control

Silkweb uses `asyncio.Semaphore` for concurrency:

- **Global semaphore**: limits total concurrent requests
- **Per-domain semaphore**: limits concurrent requests to each domain

Both respect the rate limiter and proxy pool configured globally.

## Sitemap crawling

`crawl_sitemap` / `async_crawl_sitemap` fetch the sitemap URL, parse **XML** (`urlset` or `sitemapindex`), collect `<loc>` page URLs (trimmed), then run a shallow crawl (`max_depth=0`, one page per URL) for each. Nested **sitemap index** documents are followed up to `max_sitemap_files` (default `20`). Each inner crawl gets `allowed_domains` set from the **sitemap URL’s host** so link expansion stays on-site if you later raise depth.

`schema` and `prompt` follow the same **both or neither** rule as `async_crawl`.

```python
results = silkweb.crawl_sitemap(
    "https://example.com/sitemap.xml",
    schema=Product,
    prompt="product details",
    max_pages=100,
    max_sitemap_files=20,
)
```

## Watch mode

For monitoring pages over time, see [Watch & Change Detection](../reference/api.md).

```python
from silkweb.watch import Watcher

watcher = Watcher()
watcher.add(
    url="https://example.com/pricing",
    schema=PricingSchema,
    interval=3600,  # check every hour
    on_change=handle_price_change,
    on_error=handle_error,
    prompt="pricing tiers with name and monthly price",
)

await watcher.start()
```

## CLI

```bash
# Crawl with output
silkweb crawl https://books.toscrape.com \
    --max-pages 50 \
    --concurrency 5 \
    --output books.jsonl

# Crawl with schema
silkweb crawl https://example.com \
    --schema schema.json \
    --url-pattern "/products/.*" \
    --output products.csv
```
