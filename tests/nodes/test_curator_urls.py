from __future__ import annotations

import logging

import pytest

from backend.nodes.curator import Curator
from backend.nodes.enricher import Enricher
from backend.services.search import CrawledPage
from backend.utils.references import format_references_section


def _document(url: str, title: str, *, score: float = 0.8) -> dict:
    return {"url": url, "title": title, "content": title, "score": score}


class RecordingExtractor:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def extract(self, urls: list[str]) -> list[CrawledPage]:
        self.urls.extend(urls)
        return [CrawledPage(url=url, raw_content=f"正文：{url}") for url in urls]


@pytest.mark.asyncio
async def test_distinct_article_ids_reach_extraction_and_references() -> None:
    first = "https://news.example.com/article?id=1"
    second = "https://news.example.com/article?id=2"
    state = await Curator().run(
        {
            "company": "示例公司",
            "company_data": {
                first: _document(first, "第一篇文章"),
                second: _document(second, "第二篇文章"),
            },
        }
    )
    extractor = RecordingExtractor()
    state = await Enricher(search=extractor).run(state)

    assert set(extractor.urls) == {first, second}
    assert set(state["curated_company_data"]) == {first, second}
    assert set(state["references"]) == {first, second}
    assert state["reference_titles"] == {first: "第一篇文章", second: "第二篇文章"}
    assert all(doc["raw_content"] for doc in state["curated_company_data"].values())


@pytest.mark.asyncio
async def test_tracking_variants_keep_the_best_document_and_original_fetch_url() -> (
    None
):
    first = "https://news.example.com/article?id=1&utm_source=first#section"
    better = "https://news.example.com/article?id=1&utm_source=second"
    original = _document(first, "低分摘要", score=0.5)
    state = await Curator().run(
        {
            "company": "示例公司",
            "company_data": {
                first: original,
                better: _document(better, "高分原始标题", score=0.9),
            },
        }
    )
    extractor = RecordingExtractor()
    state = await Enricher(search=extractor).run(state)

    assert extractor.urls == [better]
    assert state["references"] == [better]
    assert state["reference_titles"][better] == "高分原始标题"
    assert original["url"] == first


@pytest.mark.asyncio
async def test_signed_urls_preserve_query_bytes_order_and_path() -> None:
    urls = [
        "https://cdn.example.com/article/?id=1&Signature=a%2Fb+z&tag=x&tag=y",
        "https://cdn.example.com/article/?id=1&Signature=other&tag=x&tag=y",
    ]
    state = await Curator().run(
        {
            "company": "示例公司",
            "company_data": {
                url: _document(url, f"签名来源{index}")
                for index, url in enumerate(urls)
            },
        }
    )

    assert list(state["curated_company_data"]) == urls
    assert state["references"] == urls


@pytest.mark.asyncio
async def test_schemeless_source_retains_host_and_article_id() -> None:
    url = "news.example.com/article?id=1"
    state = await Curator().run(
        {"company": "示例公司", "company_data": {url: _document(url, "公司公告")}}
    )

    assert list(state["curated_company_data"]) == [f"https://{url}"]


@pytest.mark.asyncio
@pytest.mark.parametrize("title_is_url", [False, True])
async def test_source_query_values_are_not_written_to_logs(
    caplog: pytest.LogCaptureFixture,
    title_is_url: bool,
) -> None:
    url = "https://news.example.com/article?id=1&Signature=signature-audit-marker"
    caplog.set_level(logging.INFO)
    title = url if title_is_url else "原始公告"
    state = await Curator().run(
        {"company": "示例公司", "company_data": {url: _document(url, title)}}
    )

    markdown = format_references_section(
        state["references"], state["reference_info"], state["reference_titles"]
    )

    assert url in markdown
    assert "signature-audit-marker" not in caplog.text


@pytest.mark.asyncio
async def test_extraction_failure_does_not_log_source_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingExtractor:
        async def extract(self, _urls: list[str]) -> list[CrawledPage]:
            raise RuntimeError("正文暂不可用")

    url = "https://news.example.com/article?id=1&Signature=signature-audit-marker"
    result = await Enricher(search=FailingExtractor()).fetch_single_content(url)

    assert result == {url: ""}
    assert "signature-audit-marker" not in caplog.text
    assert "RuntimeError" in caplog.text
