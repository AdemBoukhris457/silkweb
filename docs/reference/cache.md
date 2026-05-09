# Cache

Silkweb uses a three-layer caching system to minimize network requests and LLM calls.

## Selector cache key (how reuse works)

The selector cache stores synthesized selector sets under a key derived from:

- **domain**: the URL hostname (e.g. `books.toscrape.com`)
- **DOM skeleton hash**: a stable fingerprint of the page’s tag nesting (ignores text/attributes)
- **schema signature**: a signature of the schema’s field names/types, so selectors compiled for one schema
  aren’t reused for a different schema

## Cache Manager

::: silkweb.cache.manager.CacheManager
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## HTTP Cache (Layer 1)

::: silkweb.cache.http.HttpCache
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## Rendered Page Cache (Layer 2)

::: silkweb.cache.page.RenderedPageCache
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## Selector Cache (Layer 3)

::: silkweb.cache.selectors.SelectorCache
    options:
      show_root_heading: true
      members_order: source
      show_source: true

::: silkweb.cache.selectors.dom_skeleton_hash
    options:
      show_root_heading: true
