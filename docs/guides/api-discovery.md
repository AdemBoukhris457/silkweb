# Hidden API Discovery

One of Silkweb's most powerful features: instead of scraping the DOM of a JavaScript-heavy page, discover the underlying JSON API it calls and use that directly.

## How it works

1. Silkweb loads the page with Playwright and listens for responses
2. Filters to **XHR/fetch** requests whose `Content-Type` includes `application/json`
3. For each JSON endpoint, it records: URL, method, headers, response schema
4. **Deduplicates** identical `(method, URL, request body)` captures before codegen
5. Detects pagination patterns (page/offset/cursor parameters)
6. Detects auth-related headers (`Authorization`, `x-api-key`, `x-auth-token`) — values are redacted in the scaffold
7. Generates a standalone Python scraper using `httpx`

The generated scraper uses direct HTTP calls — typically 10-100x faster than DOM scraping.

## Basic usage

```python
import silkweb

api_info = silkweb.discover_api("https://example.com/store")

print(api_info.endpoints)
# [
#   {
#     'url': 'https://api.example.com/v2/products?page=1&limit=24',
#     'method': 'GET',
#     'headers': {'x-api-token': '...'},
#     'response_schema': {'items': [...], 'total': 1234},
#     'pagination': 'cursor',
#   }
# ]

print(api_info.generated_scraper)
# Python code using httpx to call each discovered endpoint
```

## Generating a scraper file

```python
silkweb.discover_api(
    "https://example.com/store",
    output_path="example_api_scraper.py"
)
```

This writes a self-contained Python script that replicates the API calls without needing a browser.

## Using with a session

For authenticated pages, pass a session so the browser has the right cookies:

```python
session = silkweb.SilkSession.load("my_login")
api_info = silkweb.discover_api(
    "https://example.com/dashboard",
    session=session,
)
```

(`discover_api` is synchronous; it runs the async capture internally.)

## CLI

```bash
silkweb discover-api https://example.com/store
silkweb discover-api https://example.com/store --output scraper.py
```

## What gets detected

| Feature | Detection method |
|---------|-----------------|
| JSON endpoints | `Content-Type: application/json` responses from XHR/fetch |
| Response schema | Inferred via `genson` library |
| Pagination | `page`, `offset`, `cursor` params in URL or body |
| Auth headers | `Authorization`, `x-api-key`, `x-auth-token` (redacted in generated code) |
| Request method | GET, POST, PUT, etc. |

## When to use API discovery

API discovery is most useful when:

- The site is a Single Page Application (SPA) that loads data via AJAX
- DOM scraping is slow or fragile due to complex JavaScript rendering
- You want the fastest possible data retrieval (direct HTTP, no browser overhead)
- The site has an undocumented internal API that returns structured JSON
