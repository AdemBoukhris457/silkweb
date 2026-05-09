from __future__ import annotations

import pytest


def test_ask_extract_discover_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    import silkweb

    async def fake_async_ask(url: str, prompt: str, **kwargs):
        return [{"x": 1}]

    async def fake_async_extract(url: str, schema, prompt: str, **kwargs):
        return [{"name": "a"}]

    class _R:
        endpoints: list[object]
        generated_scraper: str

        def __init__(self) -> None:
            self.endpoints = []
            self.generated_scraper = "print('ok')"

    def fake_discover(url: str, session=None, output_path=None):
        return _R()

    async def fake_async_discover(url: str, session, output_path):
        return fake_discover(url, session=session, output_path=output_path)

    monkeypatch.setattr(silkweb, "async_ask", fake_async_ask)
    monkeypatch.setattr(silkweb, "async_extract", fake_async_extract)
    monkeypatch.setattr(silkweb, "_async_discover_api", fake_async_discover)

    assert silkweb.ask("https://example.test/", "p") == [{"x": 1}]
    assert silkweb.extract("https://example.test/", schema=object, prompt="p") == [{"name": "a"}]
    r = silkweb.discover_api("https://example.test/")
    assert r.generated_scraper == "print('ok')"


def test_to_dataframe_polars_and_type_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from silkweb.output.dataframe import to_dataframe

    class _PL:
        @staticmethod
        def DataFrame(rows):
            return ("pl", rows)

    monkeypatch.setitem(__import__("sys").modules, "polars", _PL)
    assert to_dataframe([{"a": 1}], engine="auto") == ("pl", [{"a": 1}])

    with pytest.raises(TypeError):
        to_dataframe({"a": 1}, engine="auto")  # type: ignore[arg-type]
