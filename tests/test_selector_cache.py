from __future__ import annotations

from pydantic import BaseModel

from silkweb.cache.selectors import SelectorCache, dom_skeleton_hash
from silkweb.llm.pipelines.heal import _make_skeleton_key


def test_dom_skeleton_hash_ignores_text_and_attrs() -> None:
    html1 = "<html><body><div class='a'>Hello</div><span id='x'>World</span></body></html>"
    html2 = "<html><body><div class='b'>Different</div><span id='y'>Text</span></body></html>"
    assert dom_skeleton_hash(html1) == dom_skeleton_hash(html2)

    html3 = "<html><body><div><div>Nested</div></div><span>World</span></body></html>"
    assert dom_skeleton_hash(html1) != dom_skeleton_hash(html3)


def test_selector_cache_hit_miss_and_stats(tmp_path) -> None:
    path = tmp_path / "selectors.sqlite"
    cache = SelectorCache(path=str(path))
    cache.clear()

    ss = {"title": [".title", "h1", "div h1", "//h1", "//div//h1"]}
    assert cache.get("example.com", "abc") is None
    cache.set("example.com", "abc", ss)
    assert cache.get("example.com", "abc") == ss

    stats = cache.stats()
    assert stats["entries"] == 1
    assert stats["domains"] == 1

    cache.clear(domain="example.com")
    assert cache.get("example.com", "abc") is None


def test_different_schemas_produce_separate_cache_entries(tmp_path) -> None:
    """Two schemas with different fields on the same DOM must use separate rows."""

    class SchemaA(BaseModel):
        title: str

    class SchemaB(BaseModel):
        title: str
        price: float

    html = "<html><body><h1>Product</h1><span>$9.99</span></body></html>"

    sk_a = _make_skeleton_key(html, SchemaA)
    sk_b = _make_skeleton_key(html, SchemaB)
    assert sk_a != sk_b

    cache = SelectorCache(path=str(tmp_path / "selectors.sqlite"))
    cache.set("shop.com", sk_a, {"title": ["h1"]})
    cache.set("shop.com", sk_b, {"title": ["h1"], "price": ["span"]})

    assert cache.get("shop.com", sk_a) == {"title": ["h1"]}
    assert cache.get("shop.com", sk_b) == {"title": ["h1"], "price": ["span"]}

    stats = cache.stats()
    assert stats["entries"] == 2


def test_same_fields_different_types_produce_separate_keys() -> None:
    """Two schemas with the same field names but different types must not collide."""

    class SchemaStrPrice(BaseModel):
        price: str

    class SchemaFloatPrice(BaseModel):
        price: float

    html = "<html><body><span>$9.99</span></body></html>"
    sk_str = _make_skeleton_key(html, SchemaStrPrice)
    sk_float = _make_skeleton_key(html, SchemaFloatPrice)
    assert sk_str != sk_float
