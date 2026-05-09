# LLM Providers

Silkweb supports multiple LLM backends through a unified `LLMProvider` interface.

## Base class

::: silkweb.llm.providers.base.LLMProvider
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## Ollama

::: silkweb.llm.providers.ollama.OllamaProvider
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## OpenAI

::: silkweb.llm.providers.openai.OpenAIProvider
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## Anthropic

::: silkweb.llm.providers.anthropic.AnthropicProvider
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## llama.cpp

::: silkweb.llm.providers.llamacpp.LlamaCppProvider
    options:
      show_root_heading: true
      members_order: source
      show_source: true

## Registry

::: silkweb.llm.providers.registry.parse_model_uri
    options:
      show_root_heading: true

::: silkweb.llm.providers.registry.create_provider
    options:
      show_root_heading: true
