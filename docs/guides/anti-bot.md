# Anti-Bot & Stealth

Silkweb includes a full anti-detection toolkit for scraping sites with aggressive bot protection.

## Proxy pool

Rotate proxies across requests using configurable strategies:

```python
import silkweb

silkweb.configure(
    proxies=[
        "http://user:pass@proxy1.example.com:8080",
        "http://user:pass@proxy2.example.com:8080",
        "socks5://proxy3.example.com:1080",
    ],
    proxy_rotation="on_failure",  # rotate only when a proxy fails
)
```

### Rotation strategies

| Strategy | Behavior |
|----------|----------|
| `per_request` | Round-robin across all proxies |
| `per_domain` | Sticky proxy per domain |
| `on_failure` | Same proxy until it fails, then rotate |
| `sticky` | Same proxy with TTL-based refresh |

Failed proxies are temporarily removed with exponential backoff (with jitter) and automatically re-added after recovery.

```python
from silkweb.stealth.proxy import ProxyPool

pool = ProxyPool(["http://proxy1:8080", "http://proxy2:8080"])
proxy = pool.next_proxy("per_request")

# On error:
pool.mark_failed("http://proxy1:8080")

# On success:
pool.mark_success("http://proxy2:8080")

# Stats:
print(pool.stats())
# {'total': 2, 'active': 1, 'failed': 1, 'per_proxy': {...}}
```

## Rate limiting

Silkweb enforces rate limits at two levels:

```python
silkweb.configure(
    rate_limit_global=10,        # max 10 req/s total
    rate_limit_per_domain=2,     # max 2 req/s per domain
    respect_robots=True,         # honor robots.txt Crawl-delay
)
```

The rate limiter uses a token bucket algorithm with:

- **Global bucket**: caps total request rate
- **Per-domain buckets**: caps rate per individual domain
- **robots.txt Crawl-delay**: parsed once per domain, enforced as a minimum interval
- **Jitter**: randomizes delays to avoid detection patterns

## Human-like behavior

For Tier 2/3 fetchers, Silkweb can simulate human browsing:

```python
silkweb.configure(
    human_mouse=True,    # Bezier-curve mouse movements
    human_typing=True,   # character-by-character typing with random delays
)
```

### Mouse movement

`human_mouse_move(page, selector)` generates a Bezier curve path from the current mouse position to the target element and moves in small steps.

### Typing simulation

`human_type(page, selector, text)` types each character with:

- Random inter-key delay (50-200ms)
- 2% chance of typo (backspace + retype)

### Random scrolling

`random_scroll(page)` scrolls down in random increments with random pauses, simulating a human reading the page.

## TLS fingerprinting

Tier 1 uses `curl_cffi` to impersonate real browser TLS fingerprints:

```python
page = silkweb.fetch("https://example.com", tier=1)
```

Default profile is `chrome_124`. Available profiles:

- `chrome_120`, `chrome_124`
- `firefox_121`
- `safari_17`
- `edge_122`

## Cloudflare bypass

Tier 3 includes Cloudflare challenge detection and waiting:

1. Checks for `cf-ray` header and "Just a moment" title
2. Waits for `cf_clearance` cookie to appear
3. Re-captures HTML after challenge resolution
4. Configurable timeout (matches the `timeout` parameter)

## Combining stealth features

All stealth features compose naturally:

```python
silkweb.configure(
    proxies=["http://proxy1:8080", "http://proxy2:8080"],
    proxy_rotation="per_domain",
    rate_limit_per_domain=1,
    respect_robots=True,
    human_mouse=True,
    human_typing=True,
    max_tier=3,
)

# This fetch will:
# 1. Acquire a rate limit token
# 2. Select a proxy for this domain
# 3. Try Tier 0, escalate as needed
# 4. Simulate human behavior in browser tiers
page = silkweb.fetch("https://protected-site.com")
```
