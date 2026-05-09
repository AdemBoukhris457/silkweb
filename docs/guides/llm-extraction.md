# LLM Extraction

Silkweb's LLM extraction pipeline turns any web page into structured data using a multi-stage approach that minimizes LLM cost through aggressive caching.

## The extraction pipeline

```
Fetch → Clean → Schema → Extract → Compile selectors → Cache
                                          ↓
                               (subsequent requests skip LLM)
```

### Stage 1: Clean

Raw HTML is stripped of noise (scripts, styles, nav, footer, cookie banners, ads) and converted to either:

- **Trafilatura** output (no LLM, fast, default for non-Ollama setups)
- **ReaderLM-v2** output (LLM-based, more accurate, used when available via Ollama)

The result is a `CleanedContent` with `flat_json`, `markdown`, and `token_estimate`.

### Stage 2: Schema synthesis

If no schema is provided (i.e., using `ask()`), Silkweb asks the LLM to infer one:

```python
# The LLM sees the cleaned content + your prompt and returns a JSON Schema
# which is automatically converted to a Pydantic model
data = silkweb.ask(url, "all products with name and price")
```

Schemas are cached by `(content_hash, prompt_hash)` so the same request never re-synthesizes.

### Stage 3: Extract

The cleaned content + schema + prompt are sent to the LLM. For large pages, the content is chunked first.

**Chunking strategies:**

| Strategy | When used | How it works |
|----------|-----------|-------------|
| `bm25` | Default | Scores chunks by BM25 relevance to the prompt, sends top-k |
| `dom` | Record-heavy pages | Splits at HTML boundaries, never breaks a record |
| `semantic` | Long-form content | Groups by embedding similarity |
| `token` | Fallback | Simple character-count splitting |

### Stage 4: Compile selectors

After successful extraction, Silkweb asks the LLM to generate CSS/XPath selectors for each field:

```
Field "price" → ["span.price", "div.product span:first-child", "//span[@class='price']"]
```

Each field gets 3 CSS selectors and 2 XPath expressions as ordered fallbacks.

### Stage 5: Cache

Selectors are stored in a SQLite cache keyed by `(domain, skeleton_key)`. The skeleton key is based on:

- a DOM “skeleton hash” computed from tag names + nesting only (stable across content changes), and
- a schema-field signature (so selectors compiled for one schema aren’t reused for a different schema).

**On subsequent requests to the same template**, the LLM is never called — selectors are applied directly.

## Using `ask()` vs `extract()`

### `ask()` — schema-free

```python
data = silkweb.ask("https://example.com", "all product names and prices")
```

- LLM infers the schema from your prompt
- Returns `list[dict]`, a DataFrame, or a scalar
- Best for exploration and ad-hoc queries

### `extract()` — typed

```python
from pydantic import BaseModel

class Product(BaseModel):
    name: str
    price: float

products = extract("https://example.com", schema=Product, prompt="all products")
```

- You provide the Pydantic schema
- Rows are validated to Pydantic instances after the pipeline; bad **pre-validate** LLM/selector rows trigger self-healing (see below). Unknown ``output`` values raise ``ValueError``.
- Returns ``list[BaseModel]`` by default (``output="python"``); use ``output="auto"`` or ``output="df"`` / ``"dataframe"`` as documented in the output formats guide (same as ``async_extract``)

### `extract_from_html()` / `async_extract_from_html()`

Use these when you already have HTML (no network fetch). They run the **same** extraction pipeline and return the **same** shapes as `extract()` / `async_extract()`, including `output` and `dataframe_engine`.

```python
products = silkweb.extract_from_html(
    "https://example.com/page",
    html_string,
    schema=Product,
    prompt="all products",
)
```

## Self-healing

When the orchestrator decides results are not usable yet (for example **empty** rows or **missing required** fields on any row), the `SelfHealer` automatically:

1. Invalidates cached selectors for this URL's template
2. Re-runs the full extraction pipeline
3. Repeats up to `max_retries` times (from global config)
4. Raises `SilkwebExtractionError` if all attempts fail, and **clears** the selector cache entry for that template so the next request does not keep a bad cached selector set

The public `extract()` / `async_extract()` helpers construct a `SelfHealer` with **`max_attempts` only**; advanced options such as ``threshold`` or ``validation_fn`` apply when calling lower-level APIs (for example ``extract_url``) with a custom healer.

## Model overrides

Use different models for different stages:

```python
silkweb.configure(
    cleaner_model="ollama/reader-lm-v2",
    schema_model="ollama/qwen2.5-coder:14b",
    extraction_model="ollama/qwen2.5:14b",
    selector_model="ollama/qwen2.5-coder:14b",
    embedding_model="ollama/nomic-embed-text",
)
```

Or per-call:

```python
data = silkweb.ask(
    url,
    prompt,
    cleaner_model="ollama/reader-lm-v2",
    extraction_model="openai/gpt-4o",
)
```

## Constrained decoding

Silkweb uses a 3-strategy approach to ensure valid JSON output:

1. **Native JSON mode** — for providers that support it (OpenAI `json_object`, Anthropic)
2. **Outlines** — constrained decoding for local GGUF models (guaranteed valid JSON)
3. **Prompt fallback** — strong JSON-only instructions with parse + retry

## Output formats

Extraction results can be saved to various file formats:

```python
from silkweb.output.files import to_json, to_jsonl, to_csv, to_parquet, to_sqlite, to_markdown

data = silkweb.ask("https://example.com", "all products")

to_json(data, "products.json")          # JSON array
to_jsonl(data, "products.jsonl")        # one JSON object per line
to_csv(data, "products.csv")            # CSV with headers
to_parquet(data, "products.parquet")    # Apache Parquet (needs pandas + pyarrow)
to_sqlite(data, "products.db")         # SQLite database table
to_markdown(data, "products.md")       # Markdown table
```

Auto-gzip when the path ends in `.gz`:

```python
to_jsonl(data, "products.jsonl.gz")     # gzipped JSONL
to_csv(data, "products.csv.gz")         # gzipped CSV
```

### DataFrame conversion

Results auto-convert to pandas/polars DataFrames when those libraries are imported:

```python
import pandas  # just importing enables auto-detection
import silkweb

df = silkweb.ask("https://example.com", "all products")
# df is now a pandas DataFrame, not a list[dict]
```

Or explicitly:

```python
from silkweb.output.dataframe import to_dataframe

df = to_dataframe(data, engine="pandas")   # or "polars" or "auto"
```

### HuggingFace Dataset

```python
from silkweb.output.dataset import to_dataset

ds = to_dataset(data)  # returns datasets.Dataset
ds.push_to_hub("your-org/scraped-products")
```

### All supported output formats

| Format | Function | Requires |
|--------|----------|----------|
| JSON | `to_json()` | built-in |
| JSONL | `to_jsonl()` | built-in |
| CSV | `to_csv()` | built-in |
| Parquet | `to_parquet()` | `pandas`, `pyarrow` |
| DuckDB | `to_duckdb()` | `duckdb` |
| SQLite | `to_sqlite()` | built-in |
| Markdown table | `to_markdown()` | built-in |
| pandas DataFrame | `to_dataframe(engine="pandas")` | `pandas` |
| polars DataFrame | `to_dataframe(engine="polars")` | `polars` |
| HuggingFace Dataset | `to_dataset()` | `datasets` |

## Hydration shortcut

For SPAs that embed data in `<script>` tags (Next.js, Nuxt, etc.), Silkweb can use `page.hydration_data()` as a shortcut for the *cleaning* stage:

- If `hydration_first=True` (default), Silkweb will prefer hydration data as the input “content” for schema + extraction.
- It still runs **schema synthesis + extraction** (and selector compilation) — it simply avoids sending noisy raw HTML when good JSON is available.
- To keep prompts small and stable, Silkweb tries to extract a smaller subset (e.g. Next.js `props.pageProps`) and will fall back to HTML cleaning if hydration is too large.

You can control it globally:

```python
silkweb.configure(
    hydration_first=True,
    hydration_subset=True,     # prefer stable subset when possible
    hydration_max_chars=80000, # skip hydration if bigger than this
)
```
