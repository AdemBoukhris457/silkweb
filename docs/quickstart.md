# Quick Start

Get from zero to structured web data in 5 minutes.

## 1. Install Silkweb

```bash
pip install "silkweb[all]"
```

For local LLM support, install [Ollama](https://ollama.ai) and pull a model:

```bash
ollama pull qwen2.5:14b
```

## 2. Fetch a page

The simplest operation — fetch any URL and get a `SilkPage` object:

```python
import silkweb

page = silkweb.fetch("https://books.toscrape.com")

print(page.status)         # 200
print(page.url)            # https://books.toscrape.com/
print(len(page.html))      # raw HTML length
print(page.text[:200])     # cleaned plain text via Trafilatura
print(page.markdown[:200]) # cleaned markdown (headings, links, lists preserved)
```

Every `SilkPage` exposes the content in multiple formats:

| Property | Format | Description |
|----------|--------|-------------|
| `page.html` | Raw HTML | The full HTML source |
| `page.text` | Plain text | Cleaned text with boilerplate removed (via Trafilatura) |
| `page.markdown` | Markdown | Cleaned content with headings, links, bold/italic preserved |

Silkweb automatically selects the best fetcher tier. If a simple HTTP request fails (anti-bot, JavaScript-rendered content), it escalates to a stealth browser transparently.

## 3. Extract data with plain English

No selectors needed — just describe what you want:

```python
books = silkweb.ask(
    "https://books.toscrape.com",
    "all books with title and price"
)

for book in books:
    print(f"{book['title']}: £{book['price']}")
```

Behind the scenes, Silkweb:

1. Fetches the page (auto-selecting the right tier)
2. Cleans the HTML (strips nav, footer, ads)
3. Uses an LLM to infer a schema from your prompt
4. Extracts structured data matching that schema
5. Compiles CSS/XPath selectors and caches them
6. Returns typed results

!!! note "Progress logging"

    `ask` / `async_ask` emit structured logs (via `structlog`) when `log_level` is set to `INFO` or lower.
    By default (`log_level="WARNING"`), they are quiet and do not print progress to stdout.

## 4. Use a Pydantic schema for type safety

When you know the shape of the data ahead of time:

```python
from pydantic import BaseModel
from silkweb import extract

class Book(BaseModel):
    title: str
    price: float
    rating: int
    in_stock: bool

books = extract(
    "https://books.toscrape.com",
    schema=Book,
    prompt="all books on the page"
)

for book in books:
    print(f"{book.title} — £{book.price} ({book.rating} stars)")
```

Every item is validated against your Pydantic model. Invalid results trigger automatic self-healing (re-extraction with corrected prompts).

## 5. Use SilkQL for structured queries

SilkQL is Silkweb's query language for the web:

```python
results = silkweb.query("https://news.ycombinator.com", """
{
    stories[] {
        title
        url
        score(int)
        author
        comments(int)
    }
}
""")

for item in results.data:
    print(f"[{item.score}] {item.title}")
```

## 6. Traditional CSS/XPath scraping

Silkweb works perfectly fine without LLMs:

```python
page = silkweb.fetch("https://example.com")

# Content formats
print(page.html)       # raw HTML
print(page.text)       # clean plain text
print(page.markdown)   # clean markdown

# CSS selectors
headings = page.css("h1, h2, h3")
for h in headings:
    print(h.text)

# XPath
links = page.xpath("//a[@href]", kind="elements")
for link in links:
    print(link["href"], link.text)

# Convenience methods
all_links = page.links()
tables = page.tables()
json_ld = page.json_ld()
```

## 7. Async usage

All functions have async counterparts:

```python
import asyncio
import silkweb

async def main():
    page = await silkweb.async_fetch("https://example.com")
    data = await silkweb.async_ask(
        "https://books.toscrape.com",
        "all book titles and prices"
    )
    return data

results = asyncio.run(main())
```

## 8. Configure Silkweb

```python
import silkweb

silkweb.configure(
    extraction_model="ollama/qwen2.5:14b",
    max_tier=2,                 # don't go beyond Playwright
    rate_limit_per_domain=3,    # max 3 req/s per domain
    cache_backend="sqlite",     # persistent caching
    log_level="INFO",           # see what's happening
)
```

## Next steps

- [Fetcher Tiers](guides/fetcher-tiers.md) — understand auto-escalation
- [LLM Extraction](guides/llm-extraction.md) — the full extraction pipeline
- [SilkQL](guides/silkql.md) — structured queries
- [Anti-Bot](guides/anti-bot.md) — proxy pools, rate limiting, stealth
- [API Reference](reference/api.md) — complete function signatures
