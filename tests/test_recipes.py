from __future__ import annotations

import pytest


def test_recipes_registry_loads_builtins() -> None:
    import silkweb as sw

    names = {r.name for r in sw.recipes.list()}
    assert {
        "hacker-news",
        "github-repo",
        "amazon-product",
        "google-serp",
        "reddit-posts",
        "news-article",
        "product-listing",
    }.issubset(names)


def test_recipes_show_contains_query() -> None:
    import silkweb as sw

    s = sw.recipes.show("hacker-news")
    assert "SilkQL:" in s
    assert "stories[]" in s


def test_recipes_run_delegates_to_query(monkeypatch: pytest.MonkeyPatch) -> None:
    import silkweb as sw

    calls = {"count": 0}

    class _QR:
        def __init__(self) -> None:
            self.data = []
            self.pages_scraped = 1
            self.cached = False

    def fake_query(url: str, silkql_string: str, **kwargs):
        calls["count"] += 1
        assert "tier" in kwargs
        return _QR()

    monkeypatch.setattr(sw, "query", fake_query)
    out = sw.recipes.run("hacker-news", "https://news.ycombinator.com/")
    assert calls["count"] == 1
    assert out == []


def test_recipe_registry_skips_invalid_yaml(tmp_path) -> None:
    from silkweb.recipes.registry import RecipeRegistry

    (tmp_path / "broken.yaml").write_text("not: [\n", encoding="utf-8")
    reg = RecipeRegistry(directory=str(tmp_path))
    assert reg._recipes == {}


def test_recipes_run_rejects_non_matching_url() -> None:
    import silkweb as sw

    with pytest.raises(ValueError):
        sw.recipes.run("github-repo", "https://example.com/")


def test_write_output_unwraps_queryresult(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import BaseModel

    from silkweb.recipes.registry import _write_output
    from silkweb.silkql.executor import QueryResult

    captured: dict = {}

    def fake_to_json(rows, path):
        captured["rows"] = rows
        captured["path"] = path

    monkeypatch.setattr("silkweb.output.files.to_json", fake_to_json)

    class Row(BaseModel):
        u: str

    qr = QueryResult(data=[Row(u="https://a")], pages_scraped=1, cached=False)
    out = tmp_path / "out.json"
    _write_output(qr, str(out))
    assert len(captured["rows"]) == 1
    assert isinstance(captured["rows"][0], Row)
    assert captured["rows"][0].u == "https://a"
