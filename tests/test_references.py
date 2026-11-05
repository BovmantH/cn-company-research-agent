from __future__ import annotations

import pytest

from backend.utils.references import (
    format_references_section,
    normalize_url,
    process_references_from_search_results,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "https://news.example.com/article?id=1#headline",
            "https://news.example.com/article?id=1",
        ),
        (
            "https://cdn.example.com/article/?id=1&Signature=a%2Fb+z&tag=x&tag=y",
            "https://cdn.example.com/article/?id=1&Signature=a%2Fb+z&tag=x&tag=y",
        ),
        (
            "https://example.com/article?id=value/",
            "https://example.com/article?id=value/",
        ),
        ("news.example.com/article?id=1", "https://news.example.com/article?id=1"),
        ("", ""),
    ],
)
def test_normalize_url_preserves_resource_identity(source: str, expected: str) -> None:
    assert normalize_url(source) == expected


def test_reference_dedup_keeps_best_original_address_and_matching_title() -> None:
    low = "https://news.example.com/article?id=1&utm_source=low"
    high = "https://news.example.com/article?id=1&utm_source=high"
    another = "https://news.example.com/article?id=2"
    unknown = "https://news.example.com/article?id=1&source=business"
    state = {
        "curated_company_data": {
            low: {"url": low, "title": "低分标题", "score": 0.5},
            another: {"url": another, "title": "另一篇文章", "score": 0.8},
            unknown: {"url": unknown, "title": "业务参数来源", "score": 0.7},
        },
        "curated_news_data": {
            high: {"url": high, "title": "高分标题", "score": 0.9},
        },
    }

    references, titles, info = process_references_from_search_results(state)
    markdown = format_references_section(references, info, titles)

    assert references == [high, another, unknown]
    assert titles[high] == "高分标题"
    assert info[high]["score"] == 0.9
    assert info[high]["url"] == high
    assert high in markdown and another in markdown and unknown in markdown
    assert "高分标题" in markdown and "低分标题" not in markdown


def test_reference_metadata_comes_from_the_highest_ranked_duplicate() -> None:
    url = "https://news.example.com/article?id=1"
    state = {
        "curated_company_data": {url: {"url": url, "title": "低分标题", "score": 0.5}},
        "curated_news_data": {url: {"url": url, "title": "高分标题", "score": 0.9}},
    }

    references, titles, info = process_references_from_search_results(state)

    assert references == [url]
    assert titles[url] == "高分标题"
    assert info[url]["title"] == "高分标题"
    assert info[url]["score"] == 0.9
