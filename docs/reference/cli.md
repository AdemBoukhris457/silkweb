# CLI Reference

Silkweb provides a command-line interface via the `silkweb` command.

## Commands

### `silkweb fetch`

Fetch a URL and display the result.

```bash
silkweb fetch <url> [--tier INT] [--output FILE] [--capture-network] [--capture-network-bodies] [--max-network-events INT] [--network-output FILE]
```

### `silkweb ask`

Ask a plain-English question about a URL.

```bash
silkweb ask <url> <prompt> [--output FILE] [--format json|csv|parquet]
```

### `silkweb extract`

Extract structured data using a Pydantic schema file.

```bash
silkweb extract <url> --schema FILE [--prompt TEXT] [--output FILE]
```

### `silkweb shell`

Drop into an interactive IPython session with the page loaded.

```bash
silkweb shell <url>
```

### `silkweb crawl`

Crawl a site and extract data.

```bash
silkweb crawl <url> [--url-pattern REGEX] [--schema FILE] [--output FILE] [--max-pages INT] [--concurrency INT]
```

### `silkweb discover-api`

Discover hidden JSON APIs from a page's network requests.

```bash
silkweb discover-api <url> [--output FILE]
```

### `silkweb watch`

Watch a URL for changes.

```bash
silkweb watch <url> <prompt> [--interval INT]
```

### `silkweb cache stats`

Show cache statistics for all layers.

```bash
silkweb cache stats
```

### `silkweb cache clear`

Clear cache entries.

```bash
silkweb cache clear [--layer http|page|selectors] [--domain DOMAIN]
```

### `silkweb models list`

List detected Ollama models.

```bash
silkweb models list
```

### `silkweb models pull`

Pull a model via Ollama.

```bash
silkweb models pull <model>
```

### `silkweb models recommend`

Print recommended models for your hardware.

```bash
silkweb models recommend
```

### `silkweb recipes list`

List available built-in recipes.

```bash
silkweb recipes list
```

### `silkweb recipes run`

Run a recipe against a URL.

```bash
silkweb recipes run <name> [--url URL] [--output FILE]
```

### `silkweb silkql validate`

Validate a SilkQL query file.

```bash
silkweb silkql validate <file>
```

## Source

::: silkweb.cli.main
    options:
      show_root_heading: true
      members_order: source
      show_source: false
