from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import asdict, is_dataclass
from importlib.machinery import SourceFileLoader
from types import ModuleType
from typing import Any, Literal

import typer
from rich import box
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

import silkweb as sw

from ..cache.manager import CacheManager
from ..discover import APIDiscoveryResult
from ..silkql.compiler import compile_query
from ..silkql.parser import parse_silkql

app = typer.Typer(help="Silkweb CLI.")

cache_app = typer.Typer(help="Cache utilities.")
models_app = typer.Typer(help="LLM model helpers.")
recipes_app = typer.Typer(
    help="Built-in YAML recipes (fetch/query/extract). Not HTTP replay or Playwright record_session."
)
silkql_app = typer.Typer(help="SilkQL tools.")

app.add_typer(cache_app, name="cache")
app.add_typer(models_app, name="models")
app.add_typer(recipes_app, name="recipes")
app.add_typer(silkql_app, name="silkql")

console = Console()

JsonFormat = Literal["json", "csv", "parquet"]


@app.callback()
def _root() -> None:
    return


def _jsonable(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (list, dict, str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_jsonable)
        f.write("\n")


def _write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fieldnames = sorted({k for r in rows for k in r})
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: _jsonable(r.get(k)) for k in fieldnames})


def _write_parquet(path: str, rows: list[dict[str, Any]]) -> None:
    try:
        import pandas as pd  # type: ignore
    except Exception as e:
        raise typer.BadParameter("Parquet output requires `pandas`.") from e
    try:
        import pyarrow  # noqa: F401  # type: ignore
    except Exception as e:
        raise typer.BadParameter("Parquet output requires `pyarrow`.") from e
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)  # type: ignore[call-arg]


def _load_schema_from_py(path: str):
    from pydantic import BaseModel

    module_name = f"_silkweb_schema_{abs(hash(os.path.abspath(path)))}"
    mod = ModuleType(module_name)
    loader = SourceFileLoader(module_name, path)
    loader.exec_module(mod)

    for cand in ("Schema", "schema", "MODEL", "model"):
        if hasattr(mod, cand):
            obj = getattr(mod, cand)
            if isinstance(obj, type) and issubclass(obj, BaseModel):
                return obj
            if isinstance(obj, BaseModel):
                return obj.__class__
    raise typer.BadParameter(
        "Schema file must define a Pydantic model named `Schema` (recommended) or `schema`."
    )


def _render_endpoints_table(res: APIDiscoveryResult) -> None:
    t = Table(title="Discovered JSON endpoints", box=box.SIMPLE_HEAVY)
    t.add_column("#", justify="right", style="cyan", no_wrap=True)
    t.add_column("method", style="magenta", no_wrap=True)
    t.add_column("url", overflow="fold")
    t.add_column("auth", style="yellow", no_wrap=True)
    t.add_column("pagination", style="green", no_wrap=True)
    for i, ep in enumerate(res.endpoints, start=1):
        auth = "yes" if ep.auth else "no"
        pag = "yes" if ep.pagination else "no"
        t.add_row(str(i), ep.method, ep.url, auth, pag)
    console.print(t)


@app.command("fetch")
def cmd_fetch(
    url: str,
    tier: int | None = typer.Option(None, "--tier", help="Fetch tier (0-3). Default: auto."),
    output: str | None = typer.Option(None, "--output", help="Write HTML to file."),
    capture_network: bool = typer.Option(
        False, "--capture-network", help="Capture a lightweight network log (Tier 2/3)."
    ),
    capture_network_bodies: bool = typer.Option(
        False,
        "--capture-network-bodies",
        help="Capture JSON response bodies (redacted + size-capped). Implies --capture-network.",
    ),
    max_network_events: int = typer.Option(
        500, "--max-network-events", help="Max network events to capture (Tier 2/3)."
    ),
    network_output: str | None = typer.Option(
        None, "--network-output", help="Write captured network log JSON to file."
    ),
) -> None:
    kwargs: dict[str, Any] = {}
    if tier is not None:
        kwargs["tier"] = tier
    if capture_network:
        kwargs["capture_network"] = True
    if capture_network_bodies:
        kwargs["capture_network"] = True
        kwargs["capture_network_bodies"] = True
        kwargs["max_network_events"] = int(max_network_events)
    page = sw.fetch(url, **kwargs)
    if network_output:
        _write_json(network_output, page.network_requests())
        console.print(f"Wrote network log to `{network_output}`.")
    if output:
        _write_text(output, page.html)
        console.print(f"Wrote HTML to `{output}`.")
        return
    console.print(page.html)


@app.command("ask")
def cmd_ask(
    url: str,
    prompt: str,
    output: str | None = typer.Option(None, "--output", help="Write output to file."),
    format: JsonFormat = typer.Option("json", "--format", help="Output format."),  # noqa: B008
) -> None:
    out = sw.ask(url, prompt)

    # scalar
    if isinstance(out, (str, int, float, bool)) or out is None:
        text = str(out)
        if output:
            _write_text(output, text + "\n")
        else:
            console.print(text)
        return

    if hasattr(out, "to_dict") and hasattr(out, "to_csv"):
        # pandas-like
        rows = out.to_dict(orient="records")  # type: ignore[attr-defined]
    elif hasattr(out, "to_dicts"):
        # polars-like
        rows = out.to_dicts()  # type: ignore[attr-defined]
    else:
        rows = out

    if not isinstance(rows, list):
        payload = _jsonable(rows)
        if output:
            _write_json(output, payload)
        else:
            console.print_json(json.dumps(payload, default=_jsonable))
        return

    if format == "json":
        payload = [_jsonable(x) for x in rows]
        if output:
            _write_json(output, payload)
        else:
            console.print_json(json.dumps(payload, default=_jsonable))
        return

    if not all(isinstance(x, dict) for x in rows):
        raise typer.BadParameter("csv/parquet output requires list[dict] rows.")
    dict_rows = [x for x in rows if isinstance(x, dict)]

    if not output:
        raise typer.BadParameter("--output is required for csv/parquet formats.")

    if format == "csv":
        _write_csv(output, dict_rows)
    else:
        _write_parquet(output, dict_rows)
    console.print(f"Wrote `{format}` to `{output}`.")


@app.command("extract")
def cmd_extract(
    url: str,
    schema: str = typer.Option(..., "--schema", help="Path to Python file defining `Schema`."),
    prompt: str = typer.Option("extract items", "--prompt", help="Extraction prompt."),
    output: str | None = typer.Option(None, "--output", help="Write JSON output to file."),
) -> None:
    model = _load_schema_from_py(schema)
    items = sw.extract(url, model, prompt)
    payload = [_jsonable(it) for it in items]
    if output:
        _write_json(output, payload)
        console.print(f"Wrote JSON to `{output}`.")
    else:
        console.print_json(json.dumps(payload, default=_jsonable))


@app.command("shell")
def cmd_shell(url: str) -> None:
    page = sw.fetch(url, tier="auto")
    try:
        from IPython import embed  # type: ignore
    except Exception as e:
        raise typer.BadParameter("`ipython` is required for `silkweb shell`.") from e

    console.print("Launching IPython. Variables: `page`, `silk` (module), `ask`, `extract`.")
    embed(
        user_ns={
            "page": page,
            "silk": sw,
            "ask": sw.ask,
            "extract": sw.extract,
            "fetch": sw.fetch,
        }
    )


@app.command("crawl")
def cmd_crawl(
    url: str,
    url_pattern: str | None = typer.Option(None, "--url-pattern", help="Regex for URLs to keep."),
    schema: str | None = typer.Option(None, "--schema", help="Path to Python schema file."),
    output: str | None = typer.Option(None, "--output", help="Write JSON output to file."),
    max_pages: int = typer.Option(100, "--max-pages"),
    concurrency: int = typer.Option(10, "--concurrency"),
) -> None:
    schema_model = _load_schema_from_py(schema) if schema else None

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as prog:
        task = prog.add_task("Crawling…", total=None)
        items = sw.crawl(
            url,
            url_pattern=url_pattern,
            max_pages=max_pages,
            concurrency=concurrency,
            schema=schema_model,
            prompt="extract items" if schema_model else None,
        )
        prog.update(task, description=f"Crawled {len(items)} item(s)")

    payload = [_jsonable(it) for it in items]
    if output:
        _write_json(output, payload)
        console.print(f"Wrote JSON to `{output}`.")
    else:
        console.print_json(json.dumps(payload, default=_jsonable))


@app.command(
    "discover-api",
    help=(
        "Infer JSON XHR/fetch endpoints (Playwright) and print a small httpx scaffold. "
        "Not the same as HTTP replay (configure replay_dir + silkweb.replay)."
    ),
)
def cmd_discover_api(
    url: str,
    output: str | None = typer.Option(
        None, "--output", help="Write generated scraper code to file."
    ),
) -> None:
    res = sw.discover_api(url, output_path=output)
    _render_endpoints_table(res)
    if output:
        console.print(f"Wrote scraper to `{output}`.")
    else:
        console.print(res.generated_scraper)


@app.command("watch")
def cmd_watch(
    url: str,
    prompt: str,
    interval: int = typer.Option(60, "--interval", help="Seconds between checks."),
) -> None:
    # CLI watch uses `ask` and diffs the JSON output. (The library Watcher currently needs a schema.)
    last: Any | None = None
    console.print(f"Watching `{url}` every {interval}s. Ctrl+C to stop.")
    try:
        while True:
            out = sw.ask(url, prompt)
            payload = _jsonable(out)
            if last is not None and payload != last:
                console.print("[bold yellow]Change detected[/bold yellow]")
                console.print_json(json.dumps(payload, default=_jsonable))
            last = payload
            time.sleep(interval)
    except KeyboardInterrupt:
        return


@cache_app.command("stats")
def cmd_cache_stats() -> None:
    stats = CacheManager.from_config().stats()
    t = Table(title="Cache stats", box=box.SIMPLE_HEAVY)
    t.add_column("layer", style="cyan")
    t.add_column("entries", justify="right")
    for layer, v in stats.items():
        t.add_row(str(layer), str(v))
    console.print(t)


@cache_app.command("clear")
def cmd_cache_clear(
    layer: str | None = typer.Option(None, "--layer", help="http|page|selectors"),
    domain: str | None = typer.Option(
        None, "--domain", help="Domain scope for selectors, if supported."
    ),
) -> None:
    CacheManager.from_config().clear(layer=layer, domain=domain)
    console.print("Cache cleared.")


@models_app.command("list")
def cmd_models_list() -> None:
    try:
        import ollama  # type: ignore
    except Exception as e:
        raise typer.BadParameter("Ollama SDK not installed. Install `silkweb[ollama]`.") from e

    data = ollama.list()
    models = data.get("models", []) if isinstance(data, dict) else []
    t = Table(title="Ollama models", box=box.SIMPLE_HEAVY)
    t.add_column("name", style="cyan")
    t.add_column("size", justify="right")
    for m in models:
        t.add_row(str(m.get("name", "")), str(m.get("size", "")))
    console.print(t)


@models_app.command("pull")
def cmd_models_pull(model: str) -> None:
    try:
        import ollama  # type: ignore
    except Exception as e:
        raise typer.BadParameter("Ollama SDK not installed. Install `silkweb[ollama]`.") from e

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as prog:
        task = prog.add_task(f"Pulling `{model}`…", total=None)
        ollama.pull(model)
        prog.update(task, description=f"Pulled `{model}`")


@models_app.command("recommend")
def cmd_models_recommend() -> None:
    t = Table(title="Recommended models (heuristic)", box=box.SIMPLE_HEAVY)
    t.add_column("use-case", style="cyan")
    t.add_column("model")
    t.add_row("cleaning / ReaderLM", "reader-lm-v2")
    t.add_row("general extraction", "qwen2.5:7b or qwen2.5:14b")
    t.add_row("fast / small", "qwen2.5:3b")
    t.add_row("high quality", "qwen2.5:32b (needs lots of RAM/VRAM)")
    console.print(t)
    console.print("Tip: run `silkweb models list` to see what you already have.")


@recipes_app.command("list")
def cmd_recipes_list() -> None:
    t = Table(title="Recipes", box=box.SIMPLE_HEAVY)
    t.add_column("name", style="cyan")
    t.add_column("description")
    t.add_column("url_pattern", overflow="fold")
    for r in sw.recipes.list():
        t.add_row(r.name, r.description, r.url_pattern)
    console.print(t)


@recipes_app.command("run")
def cmd_recipes_run(
    name: str,
    url: str | None = typer.Option(None, "--url"),
    output: str | None = typer.Option(None, "--output"),
) -> None:
    if not url:
        raise typer.BadParameter("--url is required.")
    data = sw.recipes.run(name, url, output=output)
    if output:
        console.print(f"Wrote `{output}`.")
    else:
        console.print_json(json.dumps(_jsonable(data), default=_jsonable))


@recipes_app.command("show")
def cmd_recipes_show(name: str) -> None:
    console.print(sw.recipes.show(name))


@silkql_app.command("validate")
def cmd_silkql_validate(file: str) -> None:
    with open(file, encoding="utf-8") as f:
        q = f.read()
    parse_silkql(q)
    model = compile_query(q)
    t = Table(title="SilkQL validation", box=box.SIMPLE_HEAVY)
    t.add_column("status", style="green")
    t.add_column("fields")
    t.add_row("ok", ", ".join(sorted(model.model_fields.keys())))
    console.print(t)
