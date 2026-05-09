# Public API

The main entry points for Silkweb. Functions and types below are available from `import silkweb` (see `__all__` in the package for the canonical list).

## Fetching

::: silkweb.fetch
    options:
      show_root_heading: true

::: silkweb.async_fetch
    options:
      show_root_heading: true

## Extraction

::: silkweb.ask
    options:
      show_root_heading: true

::: silkweb.async_ask
    options:
      show_root_heading: true

::: silkweb.extract
    options:
      show_root_heading: true

::: silkweb.async_extract
    options:
      show_root_heading: true

::: silkweb.async_extract_from_html
    options:
      show_root_heading: true

## SilkQL

::: silkweb.query
    options:
      show_root_heading: true

::: silkweb.async_query
    options:
      show_root_heading: true

::: silkweb.QueryResult
    options:
      show_root_heading: true

## Crawling

::: silkweb.crawl
    options:
      show_root_heading: true

::: silkweb.async_crawl
    options:
      show_root_heading: true

::: silkweb.crawl_sitemap
    options:
      show_root_heading: true

::: silkweb.async_crawl_sitemap
    options:
      show_root_heading: true

## API Discovery

::: silkweb.discover_api
    options:
      show_root_heading: true

## Fetch replay (observability)

`silkweb.replay(session_file)` reloads a **recorded HTTP fetch** session for debugging. It is **not** the same as `replay_session`, which replays **browser** actions from a saved `SilkSession` (see [Sessions & authentication](../guides/sessions.md)).

::: silkweb.replay
    options:
      show_root_heading: true

## Sessions (browser)

Interactive recording and headless replay use async Playwright helpers:

::: silkweb.record_session
    options:
      show_root_heading: true

::: silkweb.replay_session
    options:
      show_root_heading: true

::: silkweb.SilkSession
    options:
      show_root_heading: true

## Change watching

::: silkweb.watch
    options:
      show_root_heading: true

## Bundled recipes

The `silkweb.recipes` object is a `RecipeRegistry` loaded from built-in YAML recipes:

::: silkweb.recipes.registry.RecipeRegistry
    options:
      show_root_heading: true

## Pre-fetched HTML

When you already have HTML (no network fetch), you can run the same pipelines against a string:

::: silkweb.ask_from_html
    options:
      show_root_heading: true

::: silkweb.extract_from_html
    options:
      show_root_heading: true

::: silkweb.query_from_html
    options:
      show_root_heading: true

## Configuration

::: silkweb.get_config
    options:
      show_root_heading: true

::: silkweb.configure
    options:
      show_root_heading: true

Unknown `configure(...)` keys normally go into `SilkwebConfig.extra`. With environment variable **`SILKWEB_STRICT_CONFIG`** set to `1`, `true`, or `yes`, unknown top-level keys raise `SilkwebConfigError` instead (helps catch typos).

## Session errors

::: silkweb.SilkwebSessionError
    options:
      show_root_heading: true

::: silkweb.SilkwebSessionExpiredError
    options:
      show_root_heading: true
