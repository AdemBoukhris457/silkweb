from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from rich.console import Console


def pydantic_schema_line(schema: type[BaseModel]) -> str:
    """Short single-line representation of a Pydantic model for transparency output."""
    bits: list[str] = []
    for name, f in schema.model_fields.items():
        ann = f.annotation
        tn = getattr(ann, "__name__", str(ann))
        bits.append(f"{name}: {tn}")
    return f"{schema.__name__}(" + ", ".join(bits) + ")"


def tier_name_for_page(tier: int, page: Any) -> str:
    """Human-readable fetch tier label (best-effort; tier-1 impersonate is not always on the page)."""
    if tier <= 0:
        return "httpx HTTP/2"
    if tier == 1:
        imp = None
        try:
            ua = (page.headers or {}).get("user-agent") if page is not None else None
            if isinstance(ua, str) and ua.strip():
                imp = ua.strip()[:80]
        except Exception:
            imp = None
        if imp:
            return f"curl_cffi ({imp})"
        return "curl_cffi (TLS impersonation)"
    if tier == 2:
        return "Playwright"
    if tier >= 3:
        return "Stealth browser"
    return f"tier {tier}"


@dataclass
class ExtractionReport:
    tier_used: int = 0
    tier_name: str = ""
    hydration_source: str | None = None
    schema_inferred: str | None = None
    records_extracted: int = 0
    selector_cache_hit: bool = False
    selector_cache_key: str | None = None
    llm_calls_made: int = 0
    llm_models_used: list[str] = field(default_factory=list)
    total_duration_ms: float = 0.0

    def note_llm(self, provider: Any) -> None:
        """Record one LLM invocation (unwraps provider wrappers when possible)."""
        self.llm_calls_made += 1
        p = provider
        try:
            p = p.unwrap() if hasattr(p, "unwrap") else p
            name = f"{p.__class__.__name__}:{getattr(p, 'model', '')}"
        except Exception:
            name = repr(provider)
        self.llm_models_used.append(name)


def render(report: ExtractionReport, *, console: Console | None = None) -> None:
    """Print a structured transparency report to the console (side-effect only)."""
    c = console or Console()
    sep = "──────────────────"

    c.print(f"[green]✅[/green] Fetch tier: [bold]{report.tier_used}[/bold] — {report.tier_name}")

    if report.hydration_source:
        c.print(
            f"[green]✅[/green] Hydration payload: [bold]{report.hydration_source}[/bold] "
            "(SSR JSON used for cleaning)"
        )
    else:
        c.print("[yellow]⚠️[/yellow] No hydration script payload used (HTML clean path)")

    if report.schema_inferred:
        c.print(f"[green]✅[/green] Schema: {report.schema_inferred}")
    else:
        c.print("[yellow]⚠️[/yellow] Schema: (not inferred — caller-supplied schema path)")

    c.print(f"[green]✅[/green] Records extracted: [bold]{report.records_extracted}[/bold]")

    if report.selector_cache_key:
        c.print(f"[dim]Selector cache key:[/dim] {report.selector_cache_key}")

    if report.selector_cache_hit:
        c.print(
            "[blue]⚡[/blue] Selector cache [bold]hit[/bold] — next call can be 100% CSS/XPath with no LLM on this skeleton."
        )
    else:
        c.print("[yellow]⚠️[/yellow] Selector cache miss — LLM pipeline ran for extraction/compile.")

    if report.llm_calls_made:
        c.print(
            f"[yellow]⚠️[/yellow] LLM calls this run: [bold]{report.llm_calls_made}[/bold] "
            f"({', '.join(report.llm_models_used)})"
        )
    else:
        c.print("[blue]⚡[/blue] No LLM calls for extraction (selector cache fast path).")

    c.print(f"[dim]{sep}[/dim]")
    c.print(f"Total duration: [bold]{report.total_duration_ms:.1f} ms[/bold]")
