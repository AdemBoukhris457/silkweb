# Watch & Change Detection

Monitor web pages for changes and receive structured diffs automatically.

## Basic watch

```python
import asyncio

import silkweb
from pydantic import BaseModel

class PricingPlan(BaseModel):
    name: str
    price: float
    features: list[str]

async def main():
    watcher = silkweb.watch()
    watcher.add(
        "https://example.com/pricing",
        schema=PricingPlan,
        interval=3600,  # check every hour (seconds)
        on_change=lambda event: print(event),
        on_error=None,
    )
    await watcher.start()
    await asyncio.Event().wait()  # keep the process alive

asyncio.run(main())
```

## Change events

When a change is detected, the `on_change` callback receives a `ChangeEvent`:

```python
# ChangeEvent structure:
{
    'url': 'https://example.com/pricing',
    'checked_at': '2025-04-30T12:00:00Z',
    'changed': True,
    'changes': [
        {
            'field': 'price',
            'record_id': 'plan_pro',
            'old_value': 49.0,
            'new_value': 59.0,
            'change_type': 'modified',
        },
        {
            'field': 'name',
            'change_type': 'added',
            'new_value': 'Enterprise Plus',
        }
    ]
}
```

### Change types

| Type | Meaning |
|------|---------|
| `"added"` | A new record or field appeared |
| `"removed"` | A record or field disappeared |
| `"modified"` | A field value changed |

## Running multiple watches

Use the `Watcher` class to monitor multiple pages:

```python
from silkweb import Watcher

watcher = Watcher()

watcher.add("https://site1.com/products", schema=Product, interval=3600, on_change=..., on_error=None)
watcher.add("https://site2.com/prices", schema=Price, interval=1800, on_change=..., on_error=None)

await watcher.start()   # runs in background asyncio loop
# ... your application continues ...
await watcher.stop()    # gracefully shuts down
```

## Watch with webhook

Send changes to an external service:

```python
import requests

watcher = silkweb.watch()
watcher.add(
    url,
    schema=Product,
    interval=1800,
    on_change=lambda event: requests.post("https://myapp.com/webhook", json=event),
    on_error=lambda _url, err: logger.error(err),
    notify_on_no_change=False,  # silent when nothing changed
)
await watcher.start()
```

## How it works

1. On each interval tick, Silkweb re-fetches and re-extracts the page
2. The current extraction is compared to the previous one at the field level
3. Changes are classified as added, removed, or modified
4. The `on_change` callback fires with the structured diff
5. Previous extraction data is stored in SQLite for persistence across restarts

## CLI

```bash
silkweb watch https://example.com/pricing "plan names and prices" --interval 3600
```

## Configuration options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | required | URL to monitor |
| `schema` | `BaseModel` | required | Pydantic schema for extraction |
| `interval` | `int` | required | Check interval in seconds |
| `on_change` | `callable` | required | Callback for change events |
| `on_error` | `callable` | `None` | Callback for errors |
| `prompt` | `str` | auto-generated | Extraction prompt (auto-generated from schema fields if omitted) |
| `notify_on_no_change` | `bool` | `False` | Call `on_change` even when nothing changed |
