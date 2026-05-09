# Output Formats

Silkweb supports a wide range of output formats for both page content and extracted data.

## Page content formats

Every `SilkPage` returned by `fetch()` provides the content in multiple representations:

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

print(page.html)         # raw HTML
print(page.text)         # "Example Domain\nThis domain is..."
print(page.markdown)     # "# Example Domain\n\nThis domain is..."
```

## Extraction return types

### Python dict / list (default)

```python
data = silkweb.ask(url, "all products")
# [{'name': '...', 'price': 29.99}, ...]
```

### Pydantic models

```python
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float

products: list[Product] = silkweb.extract(url, schema=Product, prompt="all products")
products[0].model_dump()
products[0].model_dump_json()
```

### Automatic DataFrame detection (`ask` only by default)

`async_ask` / `ask` default to ``output="auto"``. When pandas or polars is **already imported** and ``auto_detect_dataframe`` is enabled, `ask()` can return a DataFrame instead of `list[dict]`.

**`extract()` / `async_extract()`** default to ``output="python"``, so they return **`list[BaseModel]`** even if pandas is imported. Use ``output="auto"`` for the same import-based heuristic, or ``output="df"`` for a deterministic DataFrame.

```python
import pandas  # importing enables auto-detection for ask()
import silkweb

df = silkweb.ask(url, "all products")
# df is a pandas DataFrame, not a list[dict]
```

```python
import polars
import silkweb

df = silkweb.ask(url, "all products")
# df is a polars DataFrame
```

Typed extraction with a schema:

```python
import pandas
import silkweb
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float

# Same heuristic as ask: needs output="auto" (not the default for extract)
rows = silkweb.extract(url, schema=Product, prompt="all products", output="auto")

# Or force a DataFrame explicitly (recommended for extract)
df = silkweb.extract(url, schema=Product, prompt="all products", output="df", dataframe_engine="pandas")
```

### Forcing a DataFrame (recommended)

If you want deterministic behavior (no auto-detection), force the output:

```python
df = silkweb.ask(url, "all products", output="df", dataframe_engine="pandas")
```

### Explicit DataFrame conversion

```python
from silkweb.output.dataframe import to_dataframe

df = to_dataframe(data, engine="pandas")   # force pandas
df = to_dataframe(data, engine="polars")   # force polars
df = to_dataframe(data, engine="auto")     # auto-detect
```

## File output formats

All file output functions accept a list of results (dicts or Pydantic models) and an output path.

### JSON

```python
from silkweb.output.files import to_json

to_json(data, "products.json")
to_json(data, "products.json.gz")   # auto-gzip
```

### JSONL (JSON Lines)

One JSON object per line — ideal for streaming and large datasets:

```python
from silkweb.output.files import to_jsonl

to_jsonl(data, "products.jsonl")
to_jsonl(data, "products.jsonl.gz")  # auto-gzip
```

### CSV

```python
from silkweb.output.files import to_csv

to_csv(data, "products.csv")
to_csv(data, "products.csv.gz")  # auto-gzip
```

### Parquet

Columnar format, excellent for analytics:

```python
from silkweb.output.files import to_parquet

to_parquet(data, "products.parquet")
```

!!! note
    Requires `pandas` and `pyarrow` to be installed.

### SQLite

```python
from silkweb.output.files import to_sqlite

to_sqlite(data, "products.db", table="products")
```

### DuckDB

```python
from silkweb.output.files import to_duckdb

to_duckdb(data, "store.duckdb", table="products")
```

!!! note
    Requires the `duckdb` package to be installed.

### Markdown table

```python
from silkweb.output.files import to_markdown

to_markdown(data, "products.md")
```

### HuggingFace Dataset

Convert results to a HuggingFace `datasets.Dataset` for ML pipelines:

```python
from silkweb.output.dataset import to_dataset

ds = to_dataset(data)
ds.push_to_hub("your-org/scraped-products")
```

!!! note
    Requires the `datasets` package to be installed.

## Auto-gzip

Any file output function automatically gzips when the path ends in `.gz`:

```python
to_json(data, "products.json.gz")
to_jsonl(data, "products.jsonl.gz")
to_csv(data, "products.csv.gz")
```

## Format summary

| Format | Function | Requires | Gzip support |
|--------|----------|----------|:------------:|
| JSON | `to_json()` | built-in | Yes |
| JSONL | `to_jsonl()` | built-in | Yes |
| CSV | `to_csv()` | built-in | Yes |
| Parquet | `to_parquet()` | `pandas`, `pyarrow` | No |
| DuckDB | `to_duckdb()` | `duckdb` | No |
| SQLite | `to_sqlite()` | built-in | No |
| Markdown table | `to_markdown()` | built-in | No |
| pandas DataFrame | `to_dataframe(engine="pandas")` | `pandas` | N/A |
| polars DataFrame | `to_dataframe(engine="polars")` | `polars` | N/A |
| HuggingFace Dataset | `to_dataset()` | `datasets` | N/A |
