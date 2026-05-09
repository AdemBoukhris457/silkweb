# LLM Providers & Configuration

Silkweb supports multiple LLM providers through a unified `LLMProvider` interface. All provider integrations are direct SDK calls — no LangChain or LlamaIndex dependency.

## Model URI format

Every model in Silkweb is referenced by a URI string:

```
"ollama/<model>"                        → Ollama at localhost:11434
"openai/<model>"                        → OpenAI API
"anthropic/<model>"                     → Anthropic API
"llamacpp/<path/to/model.gguf>"        → llama.cpp embedded (no server needed)
```

## Configuring providers

```python
import silkweb

silkweb.configure(
    cleaner_model    = "ollama/reader-lm-v2",       # HTML → clean Flat JSON / Markdown
    schema_model     = "ollama/qwen2.5-coder:14b",  # schema inference + selector synthesis
    extraction_model = "ollama/qwen2.5:14b",        # data extraction
    embedding_model  = "ollama/nomic-embed-text",   # BM25/semantic chunking
)
```

## Supported providers

### Ollama (local, recommended)

Runs models locally with zero API costs:

```python
silkweb.configure(extraction_model="ollama/qwen2.5:14b")
```

Requires [Ollama](https://ollama.ai) running at `localhost:11434`.

### OpenAI

```python
silkweb.configure(extraction_model="openai/gpt-4o")
```

Uses the `OPENAI_API_KEY` environment variable, or set it explicitly:

```python
silkweb.configure(api_keys={"openai": "sk-..."})
```

OpenAI's native `json_object` response format is used automatically for structured extraction.

### Anthropic

```python
silkweb.configure(extraction_model="anthropic/claude-3-5-sonnet-20241022")
```

Uses `ANTHROPIC_API_KEY` environment variable.

### llama.cpp (embedded)

Run GGUF models directly without a server:

```python
silkweb.configure(extraction_model="llamacpp/path/to/model.gguf")
```

Supports constrained decoding via the `outlines` library for guaranteed valid JSON output.

## Recommended local models

| Task | Recommended model | VRAM | Notes |
|------|-------------------|------|-------|
| HTML cleaning | `reader-lm-v2` | 2 GB | Jina specialist, 512K context |
| Schema synthesis | `qwen2.5-coder:14b` | 8 GB | Best code/structure understanding |
| Data extraction | `qwen2.5:14b` | 8 GB | Best overall for structured output |
| Embeddings | `nomic-embed-text` | 0.5 GB | Fast, high quality |
| Vision fallback | `llava:13b` or cloud | 8 GB | For screenshot-based extraction |

## Auto-configuration

On first import, Silkweb can auto-detect Ollama and available models:

```python
silkweb.auto_configure()
```

Or pull the recommended model set:

```bash
silkweb models pull qwen2.5:14b
silkweb models recommend    # shows recommended models for your hardware
```

## API keys

Set via environment variables (recommended):

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
```

Or in code:

```python
silkweb.configure(
    api_keys={
        "openai": "sk-...",
        "anthropic": "sk-ant-...",
    }
)
```

## Per-task model overrides

Override models for specific pipeline stages in any extraction call:

```python
data = silkweb.extract(
    url,
    schema=Product,
    prompt="all products",
    cleaner_model="ollama/reader-lm-v2",
    extraction_model="openai/gpt-4o",
    selector_model="ollama/qwen2.5-coder:14b",
)
```

## Provider capabilities

| Provider | JSON mode | Embeddings | Constrained decoding | Local |
|----------|-----------|------------|---------------------|-------|
| Ollama | Prompt-based | Yes | Via outlines | Yes |
| OpenAI | Native `json_object` | Yes | N/A | No |
| Anthropic | Prompt-based | No | N/A | No |
| llama.cpp | Via outlines | No | Yes (guaranteed) | Yes |

## Error handling

All providers handle:

- **API key errors**: raises `SilkwebLLMError` with clear message
- **Rate limits**: auto-retry with exponential backoff
- **Timeouts**: configurable, raises `SilkwebTimeoutError`
- **Malformed JSON**: strips markdown code fences, retries on parse failure

```python
from silkweb.exceptions import SilkwebLLMError

try:
    data = silkweb.ask(url, "products")
except SilkwebLLMError as e:
    print(e)  # includes provider name and error details
```
