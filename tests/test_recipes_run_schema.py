from __future__ import annotations

import json

import pytest


def test_recipe_run_schema_path_and_writes_output(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from silkweb.recipes.registry import RecipeRegistry

    schema_file = tmp_path / "schema.py"
    schema_file.write_text(
        """
from pydantic import BaseModel

class Schema(BaseModel):
    name: str
""".strip(),
        encoding="utf-8",
    )

    recipe_file = tmp_path / "r.yaml"
    schema_ref = str(schema_file).replace("\\", "/")
    recipe_file.write_text(
        f"""
name: tmp-schema
description: tmp
url_pattern: "^https://example\\\\.test/"
schema: '{schema_ref}'
fetch_tier: 0
wait_for: null
notes: null
""".strip(),
        encoding="utf-8",
    )

    reg = RecipeRegistry(directory=str(tmp_path))

    def fake_extract(url: str, schema, prompt: str, **kwargs):
        assert kwargs.get("tier") == 0
        return [schema.model_validate({"name": "x"})]

    import silkweb as sw

    monkeypatch.setattr(sw, "extract", fake_extract)

    out_path = tmp_path / "out.json"
    data = reg.run("tmp-schema", "https://example.test/a", output=str(out_path))
    assert len(data) == 1
    assert json.loads(out_path.read_text(encoding="utf-8")) == [{"name": "x"}]
