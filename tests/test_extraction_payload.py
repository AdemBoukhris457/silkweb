from __future__ import annotations

import json
from itertools import chain

import pytest

from silkweb.config import configure, get_config
from silkweb.llm.pipelines.clean import CleanedContent
from silkweb.llm.pipelines.extract import choose_extraction_payload, degraded_catalog_signal


def _books_like_flat() -> str:
    prefix = ["A Light in the ...", "£51.77", "In stock"]
    extra = (x for i in range(15) for x in (f"£{50 + i}.00", "In stock"))
    items = list(chain(prefix, extra))
    return json.dumps({"heading": "Books", "items": items}, ensure_ascii=False)


def test_degraded_catalog_signal_true_for_price_stream() -> None:
    flat = _books_like_flat()
    cleaned = CleanedContent(
        flat_json=flat,
        markdown=flat,
        token_estimate=10,
        html_excerpt="<article class='x'>full</article>",
    )
    assert degraded_catalog_signal(cleaned) is True


def test_degraded_catalog_signal_false_for_article_like_items() -> None:
    items = [f"Paragraph line about topic {i} and more words here." for i in range(8)]
    flat = json.dumps({"heading": "Article", "items": items}, ensure_ascii=False)
    cleaned = CleanedContent(flat_json=flat, markdown="\n\n".join(items), token_estimate=50)
    assert degraded_catalog_signal(cleaned) is False


@pytest.mark.parametrize("representation", ["auto", "flat_json"])
def test_choose_auto_prefers_html_when_degraded(representation: str) -> None:
    flat = _books_like_flat()
    html = (
        "<html><body>"
        + ("<article class='pod'><h3><a title='T'>x</a></h3></article>" * 5)
        + "</body></html>"
    )
    cleaned = CleanedContent(flat_json=flat, markdown="x", token_estimate=1, html_excerpt=html)

    if representation == "auto":
        out = choose_extraction_payload(cleaned, representation="auto")
        d = json.loads(out)
        assert d.get("format") == "html_excerpt"
        assert "pod" in d.get("body", "")
    else:
        out = choose_extraction_payload(cleaned, representation="flat_json")
        assert out == flat


def test_choose_markdown_envelope() -> None:
    cleaned = CleanedContent(
        flat_json="{}",
        markdown="# Hi\nbody",
        token_estimate=1,
        html_excerpt="<div/>",
    )
    out = json.loads(choose_extraction_payload(cleaned, representation="markdown"))
    assert out["format"] == "markdown"
    assert "Hi" in out["body"]


def test_choose_auto_prefers_html_when_listing_numbers_only_in_excerpt() -> None:
    """Reader dropped grid metrics; tag-stripped HTML still has many counts (site-agnostic)."""
    flat = json.dumps(
        {"heading": "Trending", "items": ["acme / widget", "Beta / tool", "Taglines only here."]},
        ensure_ascii=False,
    )
    md = "## acme / widget\n\nTaglines only here.\n"
    rows = "".join(
        f'<div class="row"><span class="n">{10_000 + i * 111:,}</span>'
        f'<span class="f">{500 + i * 11:,}</span></div>'
        for i in range(8)
    )
    html = f"<main>{rows}</main>"
    cleaned = CleanedContent(flat_json=flat, markdown=md, token_estimate=1, html_excerpt=html)
    out = json.loads(choose_extraction_payload(cleaned, representation="auto"))
    assert out["format"] == "html_excerpt"
    assert "10,000" in out["body"]


def test_choose_auto_stays_flat_when_plain_text_has_matching_numeric_density() -> None:
    flat = json.dumps({"heading": "x", "items": ["y"]}, ensure_ascii=False)
    md = ", ".join(f"{10_000 + i * 111:,} stars" for i in range(8))
    rows = "".join(
        f"<div><span>{10_000 + i * 111:,}</span><span>{500 + i:,}</span></div>" for i in range(8)
    )
    html = f"<article>{rows}</article>"
    cleaned = CleanedContent(flat_json=flat, markdown=md, token_estimate=1, html_excerpt=html)
    assert choose_extraction_payload(cleaned, representation="auto") == flat


def test_choose_auto_stays_flat_when_excerpt_too_few_numbers() -> None:
    flat = json.dumps({"heading": "x", "items": ["y"]}, ensure_ascii=False)
    html = "<div>" + ("<p>hello</p>" * 30) + "<span>12,345</span><span>99</span></div>"
    cleaned = CleanedContent(
        flat_json=flat, markdown="hello world", token_estimate=1, html_excerpt=html
    )
    assert choose_extraction_payload(cleaned, representation="auto") == flat


def test_html_payload_respects_extraction_prompt_body_max_chars() -> None:
    cfg = get_config()
    prev = cfg.extraction_prompt_body_max_chars
    configure(extraction_prompt_body_max_chars=800)
    try:
        filler = "x" * 5000
        rows = "".join(
            f"<div><span>{10_000 + i * 111:,}</span><span>{500 + i * 11:,}</span></div>"
            for i in range(8)
        )
        html = f"<main>{rows}{filler}</main>"
        flat = json.dumps({"heading": "t", "items": ["a"]}, ensure_ascii=False)
        cleaned = CleanedContent(
            flat_json=flat, markdown="# x", token_estimate=1, html_excerpt=html
        )
        out = json.loads(choose_extraction_payload(cleaned, representation="auto"))
        assert out["format"] == "html_excerpt"
        assert len(out["body"]) == 800
    finally:
        configure(extraction_prompt_body_max_chars=prev)
