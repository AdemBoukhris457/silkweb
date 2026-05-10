from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from silkweb.explain import ExtractionReport, render


@pytest.fixture()
def sample_report() -> ExtractionReport:
    return ExtractionReport(
        tier_used=1,
        tier_name="curl_cffi (ChromeTLS)",
        hydration_source="__NEXT_DATA__",
        schema_inferred="Row(title: str, score: int)",
        records_extracted=3,
        selector_cache_hit=True,
        selector_cache_key="example.com:abc123deadbeef",
        llm_calls_made=0,
        llm_models_used=[],
        total_duration_ms=42.5,
    )


def test_render_contains_expected_strings(sample_report: ExtractionReport) -> None:
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, width=120, color_system="standard")
    render(sample_report, console=console)
    out = buf.getvalue()
    assert "curl_cffi" in out
    assert "__NEXT_DATA__" in out
    assert "title" in out and "score" in out
    assert "3" in out
    assert "example.com:abc123deadbeef" in out
    assert "42.5" in out
    assert "cache" in out.lower() or "hit" in out.lower()


def test_render_cache_miss_shows_llm_warning() -> None:
    r = ExtractionReport(
        tier_used=0,
        tier_name="httpx HTTP/2",
        hydration_source=None,
        schema_inferred="Item(name: str)",
        records_extracted=1,
        selector_cache_hit=False,
        selector_cache_key="x.test:hash",
        llm_calls_made=3,
        llm_models_used=["OllamaProvider:llama3", "OllamaProvider:llama3", "OllamaProvider:llama3"],
        total_duration_ms=100.0,
    )
    buf = StringIO()
    render(r, console=Console(file=buf, force_terminal=True, width=120))
    out = buf.getvalue()
    assert "httpx" in out
    assert "3" in out
    assert "OllamaProvider" in out
