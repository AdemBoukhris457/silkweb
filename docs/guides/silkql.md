# SilkQL Query Language

SilkQL is Silkweb's structured query language for web data extraction. It lets you define exactly what fields you want, with type coercions and modifiers, in a compact syntax.

## Basic syntax

```
{
    field_name
    field_name(type)
    field_name(type, modifier)
    collection_name[] {
        nested_field
    }
}
```

## Example

```python
import silkweb

results = silkweb.query("https://news.ycombinator.com", """
{
    stories[] {
        title
        url
        score(int)
        author
        comments(int, optional)
    }
}
""")

for story in results.data:
    print(f"[{story.score}] {story.title} by {story.author}")

print(f"Pages scraped: {results.pages_scraped}")
print(f"Cached: {results.cached}")
```

## Type coercions

Type coercions convert extracted string values to Python types:

| Coercion | Result type | Example |
|----------|------------|---------|
| `int` | `int` | `score(int)` → `312` |
| `float` | `float` | `rating(float)` → `4.5` |
| `currency` | `float` | `price(currency)` → strips `$`, `,` → `29.99` |
| `bool` | `bool` | `in_stock(bool)` → `True` |
| `url` | `str` | `link(url)` → absolute URL |
| `iso_date` | `str` | `published(iso_date)` → `"2024-01-15"` |
| `list` | `list[str]` | `tags(list)` → `["python", "web"]` |
| `json` | `Any` | `metadata(json)` → parsed JSON |

## Modifiers

| Modifier | Effect |
|----------|--------|
| `optional` | Field defaults to `None` if not found |
| `unique` | Deduplicate values |
| `min_count=N` | Require at least N items in a collection |

```
{
    products[] {
        name
        price(currency)
        description(optional)
        tags(list, unique)
    }
}
```

## Collections

Use `[]` to denote a collection (list of records):

```
{
    articles[] {
        title
        author
        date(iso_date)
    }
}
```

Collections can be nested:

```
{
    categories[] {
        name
        products[] {
            title
            price(currency)
        }
    }
}
```

## Pagination

Add a `pagination` block to automatically follow paginated results:

```python
results = silkweb.query("https://example.com/products", """
{
    products[] {
        name
        price(currency)
    }
    pagination {
        next_page_url(url)
    }
}
""", follow_pagination=True)
```

When `follow_pagination=True`, Silkweb will:

1. Extract the `next_page_url` from each page
2. Navigate to the next page
3. Merge results across all pages
4. Continue until no more `next_page_url` is found

## Python API details

- **`query` / `async_query`** use the same cleaner / extraction / selector **models** as `extract` (from `get_config()` or `configure(...)`); pass `cleaner_model=` and `selector_model=` on the call to override. Those kwargs are **not** forwarded to the fetcher.
- **`QueryResult`**: `data` is a one-element list containing the merged root model for multi-page runs; `cached` is true if **any** page used the selector cache.
- **Flat root queries** (no single list collection at the root): the extractor must return exactly one row; otherwise a `SilkwebExtractionError` is raised (use a root list like `items[] { ... }` for many rows).
- **`query_from_html`**: same SilkQL pipeline as one page of `async_query` (no pagination); useful when you already have HTML.

## Validation

Validate a SilkQL string without executing it:

```python
from silkweb.silkql.parser import parse

ast = parse("""
{
    title
    price(currency)
    items[] {
        name
        quantity(int)
    }
}
""")
print(ast)  # RootNode with fields and collections
```

Or via the CLI:

```bash
silkweb silkql validate query.silkql
```

## Compilation

SilkQL queries are compiled to Pydantic models:

```python
from silkweb.silkql.compiler import compile_query

Model = compile_query("""
{
    name
    price(currency)
    in_stock(bool)
}
""")

# Model is a Pydantic BaseModel with validated fields
print(Model.model_json_schema())
```

The `currency` coercion generates a `BeforeValidator` that strips currency symbols and commas before parsing as `float`.
