# Caching

Silkweb uses a three-layer cache system to minimize redundant network requests, browser launches, and LLM calls.

## Three-layer cache

### Layer 1 — HTTP cache

Stores raw HTTP responses with conditional GET support (ETag / Last-Modified). Prevents redundant network requests.

- Backend: `hishel` library
- Key: URL
- Supports conditional GET headers
- Configurable TTL and max size

### Layer 2 — Rendered page cache

Stores post-JavaScript DOM snapshots as serialized `SilkPage` objects. Prevents redundant browser launches for Tier 2/3 fetches.

- Key: `(url, content-hash of raw HTML)`
- Backend: SQLite with JSON serialization (or Redis)
- Configurable TTL

### Layer 3 — Selector cache

Stores LLM-synthesized CSS/XPath selectors keyed by `(domain, skeleton_key)`. This is the most impactful cache — it means the LLM is called only once per page template and schema.

- Key: `(domain, skeleton_key)`
- `skeleton_key`: `xxhash(dom_tag_nesting)` plus a signature of the schema fields (prevents reusing selectors compiled for a different schema)
- Backend: SQLite
- Configurable TTL (default: never expires)

## Configuration

```python
silkweb.configure(
    cache_enabled=True,
    cache_backend="sqlite",             # "sqlite" | "redis" | "memory"
    cache_path="~/.silkweb/cache",      # for sqlite
    http_cache_ttl=3600,                # HTTP cache TTL in seconds (1 hour)
    page_cache_ttl=1800,                # Rendered page cache TTL (30 min)
    selector_cache_ttl=None,            # Selector cache TTL (None = forever)
)
```

!!! note "`cache_backend='memory'`"

    `cache_backend="memory"` uses an in-process **RAM** cache for rendered pages (Layer 2).
    The HTTP cache (Layer 1) is **disabled** in this mode (it is only implemented for SQLite/Redis backends).

### Redis backend

```python
silkweb.configure(
    cache_backend="redis",
    redis_url="redis://localhost:6379",
)
```

## Managing the cache

### Inspect stats

```python
stats = silkweb.cache.stats()
# {
#   'http': {...},
#   'page': {...},
#   'selectors': {...}
# }
```

### Clear cache

```python
# Clear all layers
silkweb.cache.clear()

# Clear specific layer
silkweb.cache.clear(layer="http")
silkweb.cache.clear(layer="page")
silkweb.cache.clear(layer="selectors")

# Clear by domain
silkweb.cache.clear(domain="amazon.com")
silkweb.cache.clear(domain="amazon.com", layer="selectors")
```

### CLI cache management

```bash
silkweb cache stats
silkweb cache clear --layer selectors
silkweb cache clear --domain amazon.com
```

## Bypassing the cache

```python
# Skip cache for a single fetch
page = silkweb.fetch(url, no_cache=True)

# Force LLM re-extraction (bypass selector cache)
data = silkweb.ask(url, "products", force_llm=True)
```

!!! note "`force_llm` scope"

    `force_llm=True` bypasses the **selector-cache fast path** (so Silkweb runs the full LLM extraction pipeline even if selectors are cached).
    It does **not** automatically bypass the HTTP cache or rendered page cache. Use `no_cache=True` on `fetch()` / `ask()` / `extract()` / `query()` to bypass page caching for a call.

## How the selector cache works

The selector cache is the key to Silkweb's "extract once, scrape millions" approach:

1. First visit to a page template: full LLM pipeline runs (clean, schema, extract, compile selectors)
2. Selectors are cached keyed by `(domain, skeleton_key)`
3. The `skeleton_key` includes a DOM skeleton hash (tag structure only) plus a signature of the schema fields
4. Subsequent pages whose structure matches (and schema matches) can reuse selectors and skip LLM extraction for that path
5. If selectors fail (empty results, validation errors), the self-healer invalidates the cache and re-runs the LLM pipeline

## Cache backends

| Backend | Persistence | Distributed | Best for |
|---------|:-----------:|:-----------:|----------|
| `sqlite` | Yes | No | Default, single-machine |
| `redis` | Yes | Yes | Multi-process or distributed |
| `memory` | No | No | Testing, short-lived scripts |
