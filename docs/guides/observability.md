# Observability

Silkweb provides structured logging, optional Prometheus metrics, and a replay mode for deterministic debugging.

## Structured logging

Silkweb uses `structlog` for structured, machine-readable logs.

### Configuration

```python
import silkweb

silkweb.configure(
    log_level="INFO",       # "DEBUG" | "INFO" | "WARNING" | "ERROR"
    log_format="json",      # "json" | "text"
)
```

### Log events

All major operations emit structured log events:

| Event | When |
|-------|------|
| `fetch_start` | A fetch request begins |
| `fetch_complete` | A fetch request completes |
| `fetch_escalated` | Tier escalation triggered |
| `cache_hit` | Cache lookup succeeded |
| `cache_miss` | Cache lookup missed |
| `llm_call_start` | An LLM call begins |
| `llm_call_complete` | An LLM call completes |
| `extraction_complete` | Data extraction finished |
| `selector_cached` | Selectors saved to cache |
| `self_heal_triggered` | Self-healer activated |

### Log fields

Each event includes contextual fields:

```json
{
  "timestamp": "2025-04-30T12:00:00Z",
  "event": "fetch_complete",
  "url": "https://example.com",
  "tier": 1,
  "status_code": 200,
  "duration_ms": 234,
  "cache_hit": false
}
```

## Prometheus metrics

When `config.metrics_port` is set, Silkweb exposes Prometheus-compatible metrics:

```python
silkweb.configure(metrics_port=9090)
```

### Available metrics

| Metric | Labels | Description |
|--------|--------|-------------|
| `silkweb_requests_total` | `tier`, `status`, `domain` | Total fetch requests |
| `silkweb_request_duration_seconds` | `tier`, `domain` | Fetch request duration |
| `silkweb_llm_calls_total` | `model`, `task` | Total LLM calls |
| `silkweb_llm_duration_seconds` | `model`, `task` | LLM call duration |
| `silkweb_cache_hits_total` | `layer` | Cache hits per layer |
| `silkweb_blocks_total` | `domain`, `challenge_type` | Bot detection blocks |

!!! note
    Requires the `prometheus_client` package. Silkweb imports it lazily — no overhead when metrics are disabled.

## Replay mode

Save raw HTML and metadata on every fetch, then replay extraction without network calls — perfect for deterministic debugging and CI testing.

### Recording

```python
silkweb.configure(replay_dir="./silkweb_replays")

# All fetches are now saved to disk alongside normal operation
data = silkweb.ask("https://example.com", "products")
```

### Replaying

```python
# Replay extraction from saved HTML — no network calls
result = silkweb.replay("./silkweb_replays/session_2025-04-30.silkweb")
```

The JSON session file must include a non-empty `html_path` (basename next to the `.silkweb` file). Missing keys or missing HTML raise **`SilkwebError`**. This is **not** `replay_session`, which replays Playwright actions from `~/.silkweb/sessions/` (see [Sessions](../guides/sessions.md)).

### Use cases

- **Debugging**: reproduce extraction issues without hitting the live site
- **CI testing**: run extraction tests against saved HTML fixtures
- **Development**: iterate on extraction prompts/schemas offline
- **Auditing**: keep a record of what HTML was seen and what was extracted
