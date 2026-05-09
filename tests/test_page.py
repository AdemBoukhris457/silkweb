from __future__ import annotations

import pytest

from silkweb.parse.page import SilkElement, SilkPage


@pytest.fixture()
def fixture_html() -> str:
    return """
<!doctype html>
<html>
  <head>
    <title>Test Page</title>
    <meta property="og:title" content="OG Test Title"/>
    <script type="application/ld+json">
      {"@context": "https://schema.org", "@type": "WebPage", "name": "JSONLD Name"}
    </script>
    <script id="__NEXT_DATA__" type="application/json">
      {"props": {"pageProps": {"items": [1,2,3]}}}
    </script>
  </head>
  <body>
    <h1 id="main">Hello World</h1>
    <p class="lead">This is the lead paragraph.</p>

    <a href="/internal">Internal</a>
    <a href="https://external.example.com/x">External</a>

    <table id="t1">
      <tr><th>Name</th><th>Price</th></tr>
      <tr><td>Widget</td><td>$10</td></tr>
    </table>

    <div class="product">
      <a href="/p/1">Widget A</a>
      <span class="price">$10</span>
    </div>
    <div class="product">
      <a href="/p/2">Widget B</a>
      <span class="price">$20</span>
    </div>
  </body>
</html>
""".strip()


@pytest.fixture()
def page(fixture_html: str) -> SilkPage:
    return SilkPage(fixture_html, url="https://example.com/store", status=200, fetch_tier=1)


def test_css_and_css_first(page: SilkPage) -> None:
    h1 = page.css_first("h1#main")
    assert h1 is not None
    assert isinstance(h1, SilkElement)
    assert h1.text == "Hello World"
    assert h1["id"] == "main"
    assert h1.attrs["id"] == "main"

    products = page.css("div.product")
    assert len(products) == 2
    assert products[0].siblings  # at least one sibling


def test_xpath_elements(page: SilkPage) -> None:
    p = page.xpath("//p[@class='lead']")
    assert len(p) == 1
    assert p[0].text == "This is the lead paragraph."


def test_xpath_values_href(page: SilkPage) -> None:
    hrefs = page.xpath("//a[@href]/@href", kind="values")
    assert isinstance(hrefs, list)
    assert "/internal" in hrefs
    assert "https://external.example.com/x" in hrefs


def test_links_external_filter(page: SilkPage) -> None:
    all_links = page.links()
    assert "https://example.com/internal" in all_links
    assert "https://external.example.com/x" in all_links

    external = page.links(external=True)
    assert external == ["https://external.example.com/x"]


def test_tables(page: SilkPage) -> None:
    tables = page.tables()
    assert tables == [[["Name", "Price"], ["Widget", "$10"]]]


def test_json_ld(page: SilkPage) -> None:
    items = page.json_ld()
    assert len(items) == 1
    assert items[0]["@type"] == "WebPage"
    assert items[0]["name"] == "JSONLD Name"


def test_hydration_data(page: SilkPage) -> None:
    data = page.hydration_data()
    assert data is not None
    assert data["props"]["pageProps"]["items"] == [1, 2, 3]


def test_article(page: SilkPage) -> None:
    article = page.article()
    assert article["title"] == "Hello World"
    assert "This is the lead paragraph." in article["text"]


def test_detect_records(page: SilkPage) -> None:
    records = page.detect_records()
    assert len(records) == 2
    assert records[0]["url"] == "https://example.com/p/1"
    assert records[1]["url"] == "https://example.com/p/2"
    assert "text" in records[0] and "xpath" in records[0]


def test_metadata_title_uses_text_content() -> None:
    html = "<html><head><title>Hello <b>World</b></title></head><body></body></html>"
    p = SilkPage(html, url="https://example.com/")
    assert p.metadata.get("title") == "Hello World"


def test_metadata_title_strips_markup_when_entities_decode_to_angle_brackets() -> None:
    # Title text can surface as literal ``<b>``…``</b>`` after entity decoding on some stacks.
    html = "<html><head><title>Hello &lt;b&gt;World&lt;/b&gt;</title></head><body></body></html>"
    p = SilkPage(html, url="https://example.com/")
    assert p.metadata.get("title") == "Hello World"


def test_hydration_nuxt_data_script() -> None:
    html = """
    <html><body>
      <script id="__NUXT_DATA__" type="application/json">
        {"data": {"x": 1}}
      </script>
    </body></html>
    """.strip()
    p = SilkPage(html)
    d = p.hydration_data()
    assert d is not None
    assert d.get("data") == {"x": 1}
