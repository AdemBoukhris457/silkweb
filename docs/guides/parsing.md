# HTML Parsing & Selectors

Silkweb exposes a selector API on top of **`lxml`**: CSS via `lxml.cssselect`, XPath via `lxml`, plus extractors that work without any LLM.

## Page content formats

Every `SilkPage` returned by `fetch()` exposes the content in three formats:

| Property | Format | Description |
|----------|--------|-------------|
| `page.html` | Raw HTML | The full HTML source as received |
| `page.text` | Plain text | Cleaned text with boilerplate removed (via Trafilatura) |
| `page.markdown` | Markdown | Cleaned content with headings, links, bold/italic, lists preserved |

```python
import silkweb

page = silkweb.fetch("https://example.com")

print(page.html)         # raw HTML source
print(page.text)         # "Example Domain\nThis domain is..."
print(page.markdown)     # "# Example Domain\n\nThis domain is..."
```

## CSS selectors

`page.css()` uses `lxml.cssselect.CSSSelector` (Selectors Level 3 subset supported by `cssselect`).

```python
page = silkweb.fetch(url)

# Returns list[SilkElement]
items = page.css(".product-card")

# First match only
title = page.css_first("h1")

# Text shorthand
title_text = page.css_first("h1").text
```

## XPath selectors

- **`kind="elements"` (default):** returns `list[SilkElement]` — use for paths that match **element nodes**.
- **`kind="values"`:** returns raw XPath results (strings, numbers, attribute values, text nodes) — use for `//@href`, `/text()`, etc.

```python
# Elements (default)
items = page.xpath("//div[@class='product-card']")

# Attribute nodes and text — use kind="values"
hrefs = page.xpath("//a[@class='product-link']/@href", kind="values")
prices = page.xpath("//span[contains(@class, 'price')]/text()", kind="values")
```

## SilkElement

Every element returned by `css()` or `xpath()` (with `kind="elements"`) is a `SilkElement` with a rich API:

```python
el = page.css_first(".product-card")

el.text          # inner text content
el.html          # outer HTML
el.attrs         # dict of all attributes
el["href"]       # access attribute by name
el.xpath         # XPath address in the document
el.parent        # parent SilkElement
el.children      # list of child SilkElements
el.siblings      # list of sibling SilkElements
```

## Built-in smart extractors

These methods work without any LLM — they use heuristics and standard patterns:

### Links

`page.links(external=...)` needs a **non-empty `page.url`** (or the URL you passed to `SilkPage`) to decide what “internal” vs “external” means. If there is no base URL, external filtering is not applied.

```python
all_links = page.links()                    # all <a href> as absolute URLs
external = page.links(external=True)        # external domains only
internal = page.links(external=False)       # same-domain only
```

### Tables

Returns each `<table>` as a list of rows; **colspan/rowspan** are not expanded. Nested tables each appear as a separate top-level table.

```python
tables = page.tables()
# Returns a list of tables, each as a list of rows
```

### JSON-LD structured data

```python
json_ld = page.json_ld()
# Parses all <script type="application/ld+json"> tags
# [{"@type": "Product", "name": "...", "price": "..."}, ...]
```

### Metadata

```python
meta = page.metadata
# {'title': '...', 'description': '...', ...} from <title> and <meta name|property>
# Open Graph / Twitter tags appear when present as meta tags (e.g. og:title, twitter:card)
```

### Article extraction

```python
article = page.article()
# {'title': '...', 'text': '...', 'author': '...', 'date': '...', 'language': '...'}
# `text` is the same main-body text as `page.text` (Trafilatura when available).
```

### Hydration data

Embedded JSON from common SPA patterns (best-effort):

- **Next.js** — `<script id="__NEXT_DATA__" type="application/json">`
- **Nuxt** — `<script id="__NUXT_DATA__" ...>` when present, else a regex for inline `__NUXT__ = {...}`

Other stacks (Remix, SvelteKit, etc.) are **not** parsed automatically yet; use `page.html` and custom extraction if needed.

```python
data = page.hydration_data()  # dict | None
```

### Repeated pattern detection

Heuristic: finds the most repeated `(tag, class)` pair under `<body>` among elements **that have a `class` attribute**, then returns one record per element.

Each record has **`text`**, **`xpath`**, and **`url`** (first `a[href]` inside the element, made absolute with `page.url`), not separate title/price fields.

```python
records = page.detect_records()
# [{'text': '...', 'xpath': '...', 'url': '...' | None}, ...]
```

### Network log (browser tiers)

`page.network_requests()` is only non-empty when a browser tier fetcher captured events (see fetch guides). Otherwise it returns `[]`.

## SilkMeta provenance

Every extracted item can carry provenance metadata:

```python
from silkweb.parse.page import SilkMeta

# SilkMeta fields:
# - url: source URL
# - fetched_at: timestamp
# - fetch_tier: which tier was used (0-3)
# - xpath: XPath address of the source element
# - llm_model: which model extracted this (if LLM was used)
# - selector_from_cache: whether cached selectors were used
# - confidence: extraction confidence score
```
