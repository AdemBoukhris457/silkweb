# Sessions & Authentication

Silkweb sessions persist browser state (cookies, localStorage, sessionStorage) across requests, enabling scraping of authenticated pages.

## Creating a session

### Record a session interactively

Open a real browser, log in manually, and Silkweb saves the session state.

`record_session` is **async** (it drives Playwright). Call it from an async entrypoint or `asyncio.run`:

```python
import asyncio
import silkweb

async def main():
    # Opens a visible browser window — log in, navigate, etc.
    # Session is saved when you close the browser.
    await silkweb.record_session("my-site")

asyncio.run(main())
```

The session is stored at `~/.silkweb/sessions/my-site.silkweb`.

### Session file format

The `.silkweb` file is JSON containing:

```json
{
    "cookies": [...],
    "localStorage": {...},
    "url": "https://example.com/dashboard",
    "created_at": "2024-01-15T10:30:00Z",
    "ua": "Mozilla/5.0 ...",
    "actions": [...]
}
```

## Using a session

### Fetch with persisted auth

```python
import asyncio

from silkweb.session.session import SilkSession

async def main():
    session = SilkSession("my-site")  # loads from disk
    page = await session.fetch("https://example.com/dashboard")
    # Cookies and localStorage are automatically applied.
    #
    # NOTE: `SilkSession.fetch()` returns a Playwright `Page`, not a `SilkPage`,
    # so use Playwright methods to read content:
    html = await page.content()
    print(html[:500])

asyncio.run(main())
```

### Interact with pages

```python
import asyncio

from silkweb.session.session import SilkSession

async def main():
    session = SilkSession("my-site")

    # Fill a search box
    await session.fill("input[name='query']", "python")

    # Click a button
    await session.click("button[type='submit']")

    # Wait for results
    await session.wait_for(".results-list", timeout=10000)

    # Fetch the resulting page
    page = await session.fetch("https://example.com/search?q=python")

asyncio.run(main())
```

### Save and reload

```python
import asyncio
from silkweb.session.session import SilkSession

async def persist():
    session = SilkSession("my-site")
    # ... interact with pages ...
    await session.save()  # persist updated cookies/storage

asyncio.run(persist())

# Later:
session = SilkSession.load("my-site")
```

## Replay a session

Replay recorded actions in headless mode. `replay_session` is **async** (same as `record_session`):

```python
import asyncio
import silkweb

async def main():
    await silkweb.replay_session("my-site")

asyncio.run(main())
```

This plays back all recorded navigations, form fills, and clicks without opening a visible browser.

!!! note "`replay` vs `replay_session`"

    - **`replay_session(name)`** — Replays a **browser** session saved under `~/.silkweb/sessions/<name>.silkweb` (see above).
    - **`replay(session_file)`** — Loads **HTTP fetch** recordings from `configure(replay_dir=...)`: a JSON `*.silkweb` file with an `html_path` key pointing at a sibling `.html` file. Missing metadata or files raise **`SilkwebError`** with a clear message. Not the same as Playwright session replay.

## Cookie expiry detection

When fetching with a session, Silkweb checks auth cookies for expiry:

```python
import asyncio

from silkweb.exceptions import SilkwebSessionExpiredError
from silkweb.session.session import SilkSession

async def main():
    session = SilkSession("my-site")
    try:
        page = await session.fetch("https://example.com/dashboard")
    except SilkwebSessionExpiredError as e:
        print(e)  # suggests re-recording, e.g. await silkweb.record_session("my-site")

asyncio.run(main())
```

Cookies identified as auth-related (containing `session`, `auth`, `token`, `jwt`, or `sid` in the name) are checked for `expires` timestamps.

## CLI

```bash
# Record a session
silkweb shell https://example.com/login

# Fetch with a session (via the Python API)
python -c "
from silkweb.session.session import SilkSession
import asyncio

async def main():
    s = SilkSession('my-site')
    page = await s.fetch('https://example.com/dashboard')
    html = await page.content()
    print(html[:500])

asyncio.run(main())
"
```
