# Silkweb

**The LLM-native Python web scraping library. Fetch anything. Extract everything. No selectors required.**

[Quick start](quickstart.md) · [API reference](reference/api.md) · [PyPI](https://pypi.org/project/silkweb/)

---

## Three lines. Any website. Structured data.

### Ask a question, get a table

```python
import silkweb

stories = silkweb.ask("https://news.ycombinator.com", "top 10 stories with title, score, author")
# [{'title': 'Show HN: ...', 'score': 312, 'author': 'pg'}, ...]
```

### Typed extraction with Pydantic

```python
from pydantic import BaseModel
from silkweb import extract

class Product(BaseModel):
    name: str
    price: float
    rating: float

products = extract("https://books.toscrape.com", schema=Product, prompt="all books")
# [Product(name='A Light in the Attic', price=51.77, rating=3.0), ...]
```

### SilkQL: a query language for the web

```python
import silkweb

results = silkweb.query("https://github.com/trending", """
{
    repos[] {
        name
        author
        stars(int)
        language
        description(optional)
    }
}
""")
```

---

## Why Silkweb?

| Capability | Traditional approach | Silkweb |
|---|---|---|
| Fetch a page | `requests.get(url)` | `silkweb.fetch(url)` — auto-selects HTTP, stealth HTTP, or browser |
| Parse data | Write CSS/XPath selectors | Describe what you want in plain English |
| Handle JS | Manually configure Playwright | Automatic, transparent escalation |
| Bypass Cloudflare | Multiple plugins, trial and error | Built-in auto-escalating tiers |
| LLM extraction | No support | First-class, runs locally with Ollama |
| Output typing | Manual Pydantic boilerplate | Schema inferred or user-provided |
| Cache LLM calls | Not applicable | Synthesized selectors persist; repeat visits can reuse cached selectors when the layout still matches |

### The key insight

When Silkweb first encounters a page template, it uses an LLM to understand the structure and synthesize robust CSS/XPath selectors. Those selectors are **cached** (keyed by domain, a structural skeleton hash, and your schema fields). When a later page matches that cache entry, extraction can skip LLM work and run selector-based extraction instead. If the layout drifts or the cache misses, the pipeline may call an LLM again.

---

## Installation

=== "Minimal"

    ```bash
    pip install silkweb
    ```

=== "With browser"

    ```bash
    pip install "silkweb[browser]"
    playwright install chromium
    ```

=== "Full install"

    ```bash
    pip install "silkweb[all]"
    ```

---

## What's next?

<div class="grid cards" markdown>

- :material-rocket-launch:{ .lg .middle } **Quick Start**

    ---

    Go from `pip install` to your first extraction in 5 minutes.

    [:octicons-arrow-right-24: Quick Start](quickstart.md)

- :material-layers-triple:{ .lg .middle } **Fetcher Tiers**

    ---

    Learn how Silkweb auto-escalates from HTTP to stealth browser.

    [:octicons-arrow-right-24: Fetcher Tiers](guides/fetcher-tiers.md)

- :material-brain:{ .lg .middle } **LLM Extraction**

    ---

    Understand the clean → schema → extract → cache pipeline.

    [:octicons-arrow-right-24: LLM Extraction](guides/llm-extraction.md)

- :material-database-search:{ .lg .middle } **SilkQL**

    ---

    Write structured queries for the web.

    [:octicons-arrow-right-24: SilkQL](guides/silkql.md)

</div>
