# FAQ

## General

### Does Silkweb require an LLM to work?

No. Silkweb works perfectly fine without any LLM. You can use `fetch()`, CSS/XPath selectors, `page.text`, `page.markdown`, `page.tables()`, `page.json_ld()`, `page.links()`, `page.detect_records()`, and all other parsing features without an LLM. The LLM is only needed for `ask()`, `extract()`, `query()`, and schema inference.

### Does it work fully offline?

Yes. With Ollama running locally, Silkweb processes everything on your machine — no data leaves your network. This makes it suitable for sensitive data scraping.

### What Python versions are supported?

Python 3.10 and above.

### What's the difference between `ask()`, `extract()`, and `query()`?

- **`ask(url, prompt)`** — natural language, schema is inferred automatically. Returns `list[dict]` (or DataFrame).
- **`extract(url, schema, prompt)`** — you provide a Pydantic schema; rows are validated to **`list[BaseModel]`** by default (`output="python"`). Use ``output="df"`` / ``"dataframe"`` for a DataFrame, or ``output="auto"`` for the same import-based heuristic as `ask()`.
- **`query(url, silkql_string)`** — you write a SilkQL query with type coercions. Returns `QueryResult`.

### How does Silkweb handle JavaScript-rendered pages?

Silkweb auto-escalates through fetcher tiers. If a simple HTTP request returns thin content (< 500 chars of body text), it transparently upgrades to Playwright (Tier 2) or a stealth browser (Tier 3).

## LLM & Extraction

### How much does it cost to use Silkweb with LLMs?

With local models (Ollama), it's free. Silkweb also caches synthesized selectors, so the LLM is only called on the first page of each template — subsequent pages use pure CSS/XPath extraction at zero cost.

### Which local models should I use?

See the [LLM Providers guide](guides/llm-providers.md#recommended-local-models) for the recommended model set. The minimum useful setup is:

- `reader-lm-v2` (2 GB VRAM) for HTML cleaning
- `qwen2.5:14b` (8 GB VRAM) for extraction
- `nomic-embed-text` (0.5 GB VRAM) for embeddings

### Can I use OpenAI or Anthropic instead of local models?

Yes. Set the model URI to `openai/gpt-4o` or `anthropic/claude-3-5-sonnet-20241022` and provide your API key.

### What is the self-healer?

When cached selectors fail to extract data (empty results or validation errors), the self-healer automatically invalidates the cache and re-runs the full LLM pipeline. This handles site redesigns transparently.

## Anti-Bot & Stealth

### Can Silkweb bypass Cloudflare?

Silkweb's Tier 3 (stealth browser) handles most Cloudflare challenges. It uses `nodriver` or `patchright` with undetected browser fingerprints and challenge-waiting logic.

### Does Silkweb respect robots.txt?

Yes, by default. The rate limiter parses `robots.txt` for each domain and honors the `Crawl-delay` directive. You can override this with `respect_robots=False` (use responsibly).

### How do I use proxies?

```python
silkweb.configure(
    proxies=["http://user:pass@proxy1:8080", "socks5://user:pass@proxy2:1080"],
    proxy_rotation="per_request",   # "per_request" | "per_domain" | "on_failure" | "sticky"
)
```

## Caching

### Where is the cache stored?

By default, in `~/.silkweb/cache/` using SQLite. You can change the backend to Redis or memory.

### How do I clear the cache?

```python
silkweb.cache.clear()                                    # clear all
silkweb.cache.clear(layer="selectors")                   # clear selectors only
silkweb.cache.clear(domain="example.com", layer="selectors")  # domain-specific
```

Or via CLI: `silkweb cache clear --layer selectors`

### What does "DOM skeleton hash" mean?

Silkweb hashes the tag structure of a page (ignoring text and attributes) using xxhash. For the selector cache, this skeleton hash is combined with a signature of your schema fields, so cached selectors are reused only when both the template *and* the extraction schema match.

## Output

### What output formats are supported?

JSON, JSONL, CSV, Parquet, DuckDB, SQLite, Markdown tables, pandas/polars DataFrames, and HuggingFace Datasets. See the [Output Formats guide](guides/output-formats.md).

### Can I get a DataFrame directly from `ask()`?

Yes.

- If `pandas` or `polars` is imported in your namespace, `ask()` can auto-return a DataFrame.
- For deterministic behavior, force it:

```python
df = silkweb.ask(url, "products", output="df", dataframe_engine="pandas")
```

## Crawling

### How does URL deduplication work?

The crawler uses a SQLite-backed seen-set that persists across runs. Each URL is checked before being enqueued, preventing duplicate visits.

### Can I crawl with extraction?

Yes. Pass a `schema` and `prompt` to `silkweb.crawl()` and each page is automatically extracted:

```python
async for item in silkweb.crawl("https://example.com", schema=Product, prompt="products"):
    print(item)
```

## Performance

### How fast is Silkweb?

- Tier 0 (httpx): ~50ms per request
- Tier 1 (curl_cffi): ~100ms per request
- Tier 2 (Playwright): ~2s per request
- Tier 3 (stealth browser): ~5-30s per request
- Cached selector extraction: microseconds (no LLM)

### Does it support async?

Yes. Every public function has an async variant: `async_fetch()`, `async_ask()`, `async_extract()`, `async_query()`. The crawler and watcher are fully async.
