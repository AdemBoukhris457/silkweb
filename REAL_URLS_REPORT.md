# Silkweb real-URL smoke report (2026-04-30)

This document captures real-world runs against:

- `https://news.ycombinator.com` (static, simple)
- `https://books.toscrape.com` (static listing)
- `https://quotes.toscrape.com/js` (JS-rendered listing)
- `https://www.amazon.com/s?k=laptop` (anti-bot protected; inconsistent)
- `https://github.com/trending` (dynamic-ish)

All runs were executed on **Windows** with `tier="auto"` (and some explicit tier checks) using the project `.venv`.

## Summary of Silkweb fixes made during this run

- **Fixed**: `fetch(url, tier=2)` returning Tier 0 cached pages.
  - The rendered-page cache now **won’t serve a lower-tier cached page** when an explicitly higher tier is requested.
- **Fixed**: `TypeError: fetch() got an unexpected keyword argument 'http_cache'` when escalating to Tier 2/3.
  - `http_cache` is now only injected for **Tier 0** calls.
- **Improved**: `tier="auto"` escalation for JS/shell pages.
  - Added a small-HTML heuristic so “shell” responses can escalate to Tier 2 even when `text_len` alone looks “meaningful”.
- **Improved**: `tier="auto"` escalation when Tier 1 still returns a blocking status.
  - If Tier 1 returns 403/429/503, auto now escalates to **Tier 2**.
- **Fixed**: `hishel` HTTP cache raising `RuntimeError: Cannot parse Expires header`.
  - Tier 0 now retries once **without HTTP caching** when cache header parsing fails.

## Results by URL

### `https://news.ycombinator.com`
- **auto**: Tier 0, status 200, expected output.
- **notes**: No unexpected markers; HTML and text look sane.

### `https://books.toscrape.com`
- **auto**: Tier 0, status 200, expected output.
- **notes**: Listing content present; record detection works well.

### `https://quotes.toscrape.com/js`
- **before fixes**: `tier="auto"` stayed on Tier 0 (HTML had **0** quotes; Playwright Tier 2 had **10** quotes).
- **after fixes**: **auto escalates to Tier 2**, status 200, quotes are present in HTML.
- **edge case**: This site returns a “normal looking” HTML shell without classic “enable JavaScript” markers, so plain `text_len` is not reliable.

### `https://www.amazon.com/s?k=laptop`
- **observed behavior is inconsistent** (expected for anti-bot sites).
- Tier 0 can return:
  - **503** (blocked / bot mitigation), OR
  - **200** with a large HTML response (appears to be the results page for this run, but may still contain partial/region-specific interstitials).
- Tier 2 (Playwright) frequently returns **200** with title `Sorry! Something went wrong!` (likely bot/automation mitigation UX).
- **fixed failure**: `hishel` cache header parsing error (`Cannot parse Expires header`) no longer crashes the fetch; Tier 0 retries without caching.

### `https://github.com/trending`
- **auto**: Tier 0, status 200, expected output.
- **note**: A naive “captcha keyword” scan can be a **false positive** for GitHub pages.

## Known limitation observed in this environment (Windows + Python 3.14)

When using Tier 2 (Playwright) in a **short-lived script**, Python 3.14 on Windows may print an asyncio transport deallocation warning at interpreter exit (e.g. `_ProactorBasePipeTransport.__del__` / “I/O operation on closed pipe”).

- **impact**: noisy stderr output at process exit; fetch result is still correct.
- **status**: appears upstream/runtime-related (Windows Proactor loop + Playwright driver); not seen in the library’s unit tests/CI targets (Python 3.10–3.12).

