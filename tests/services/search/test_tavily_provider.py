"""``backend.services.search.tavily_provider.TavilyProvider`` 单元测试。

策略:mock ``AsyncTavilyClient`` 类(在 TavilyProvider 内部实例化)
而不是发真实 HTTP。这样既快又稳,接口契约也一目了然。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.search import (
    CrawledPage,
    SearchResult,
    SearchProvider,
    get_search_provider,
)


# === fixture: 把 TavilyProvider 内部的 AsyncTavilyClient 换成 mock ===


@pytest.fixture
def fake_tavily_client(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """构造一个 mock 的 AsyncTavilyClient 实例,monkeypatch 到 provider 模块。"""
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily-key")

    fake_instance = MagicMock()
    fake_instance.search = AsyncMock()
    fake_instance.crawl = AsyncMock()
    fake_instance.extract = AsyncMock()

    fake_class = MagicMock(return_value=fake_instance)
    monkeypatch.setattr(
        "backend.services.search.tavily_provider.AsyncTavilyClient",
        fake_class,
    )
    return fake_instance


# === 实例化 / API key ===


def test_init_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        TavilyProvider()


def test_init_accepts_explicit_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    # 不应该抛异常
    TavilyProvider(api_key="explicit-key")


# === search ===


@pytest.mark.asyncio
async def test_search_maps_response_to_search_result(
    fake_tavily_client: MagicMock,
) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.search.return_value = {
        "results": [
            {
                "url": "https://example.com/a",
                "title": "Example A",
                "content": "Some content",
                "score": 0.85,
                "published_date": "2025-01-01",
                "raw_content": "<html>...</html>",
            },
            {
                "url": "https://example.com/b",
                "title": "",
                "content": "",
                "score": None,  # 缺失场景
            },
        ]
    }

    provider = TavilyProvider()
    results = await provider.search("test query", max_results=5)

    assert len(results) == 2
    assert all(isinstance(r, SearchResult) for r in results)

    r0 = results[0]
    assert r0.url == "https://example.com/a"
    assert r0.title == "Example A"
    assert r0.content == "Some content"
    assert r0.score == 0.85
    assert r0.published_date == "2025-01-01"
    # raw 字段保留所有原始数据,包括 raw_content
    assert r0.raw["raw_content"] == "<html>...</html>"

    # 缺 score 时降级为 0.0
    assert results[1].score == 0.0


@pytest.mark.asyncio
async def test_search_passes_params_to_client(
    fake_tavily_client: MagicMock,
) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.search.return_value = {"results": []}
    provider = TavilyProvider()

    await provider.search(
        "q",
        max_results=15,
        time_range="month",
        topic="news",
        search_depth="advanced",
    )

    fake_tavily_client.search.assert_awaited_once()
    args, kwargs = fake_tavily_client.search.call_args
    assert args == ("q",)
    assert kwargs["max_results"] == 15
    assert kwargs["time_range"] == "month"
    assert kwargs["topic"] == "news"  # provider 专有参数透传
    assert kwargs["search_depth"] == "advanced"


@pytest.mark.asyncio
async def test_search_empty_results(fake_tavily_client: MagicMock) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.search.return_value = {"results": []}
    provider = TavilyProvider()

    assert await provider.search("nothing") == []


# === crawl ===


@pytest.mark.asyncio
async def test_crawl_maps_to_crawled_page(
    fake_tavily_client: MagicMock,
) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.crawl.return_value = {
        "results": [
            {
                "url": "https://x.com/a",
                "raw_content": "page A content",
                "title": "Page A",
            },
            {
                "url": "https://x.com/b",
                "raw_content": "page B content",
                # title 缺失
            },
            {
                "url": "https://x.com/c",
                "raw_content": "",  # 空内容应被过滤
            },
        ]
    }

    provider = TavilyProvider()
    pages = await provider.crawl("https://x.com")

    # 第三条因 raw_content 为空被过滤
    assert len(pages) == 2
    assert all(isinstance(p, CrawledPage) for p in pages)
    assert pages[0].url == "https://x.com/a"
    assert pages[0].raw_content == "page A content"
    assert pages[0].title == "Page A"
    assert pages[1].title == ""  # 缺失字段填空字符串


@pytest.mark.asyncio
async def test_crawl_max_pages_maps_to_max_breadth(
    fake_tavily_client: MagicMock,
) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.crawl.return_value = {"results": []}
    provider = TavilyProvider()

    await provider.crawl("https://x.com", max_pages=20)

    _, kwargs = fake_tavily_client.crawl.call_args
    assert kwargs["max_breadth"] == 20


@pytest.mark.asyncio
async def test_crawl_explicit_max_breadth_wins(
    fake_tavily_client: MagicMock,
) -> None:
    """显式 ``max_breadth`` kwargs 覆盖 ``max_pages``。"""
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.crawl.return_value = {"results": []}
    provider = TavilyProvider()

    await provider.crawl("https://x.com", max_pages=20, max_breadth=50)

    _, kwargs = fake_tavily_client.crawl.call_args
    assert kwargs["max_breadth"] == 50


@pytest.mark.asyncio
async def test_crawl_passes_tavily_specific_params(
    fake_tavily_client: MagicMock,
) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.crawl.return_value = {"results": []}
    provider = TavilyProvider()

    await provider.crawl(
        "https://x.com",
        instructions="find product info",
        max_depth=2,
        extract_depth="advanced",
    )

    _, kwargs = fake_tavily_client.crawl.call_args
    assert kwargs["instructions"] == "find product info"
    assert kwargs["max_depth"] == 2
    assert kwargs["extract_depth"] == "advanced"


# === extract ===


@pytest.mark.asyncio
async def test_extract_maps_to_crawled_pages(
    fake_tavily_client: MagicMock,
) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    fake_tavily_client.extract.return_value = {
        "results": [
            {"url": "https://a.com", "raw_content": "A"},
            {"url": "https://b.com", "raw_content": "B"},
        ]
    }
    provider = TavilyProvider()

    pages = await provider.extract(["https://a.com", "https://b.com"])

    assert len(pages) == 2
    assert pages[0].raw_content == "A"
    assert pages[1].raw_content == "B"
    fake_tavily_client.extract.assert_awaited_once_with(
        urls=["https://a.com", "https://b.com"]
    )


@pytest.mark.asyncio
async def test_extract_empty_url_list(fake_tavily_client: MagicMock) -> None:
    from backend.services.search.tavily_provider import TavilyProvider

    provider = TavilyProvider()
    assert await provider.extract([]) == []
    # 空列表不应该调底层
    fake_tavily_client.extract.assert_not_awaited()


# === get_search_provider 工厂 ===


def test_factory_default_returns_tavily(
    fake_tavily_client: MagicMock,
) -> None:
    """默认返回 Tavily,且符合 SearchProvider 协议。"""
    provider = get_search_provider()

    # Protocol 用 isinstance 验证(@runtime_checkable)
    assert isinstance(provider, SearchProvider)


def test_factory_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEARCH_PROVIDER", "made_up_xyz")

    with pytest.raises(ValueError, match="未知的 SEARCH_PROVIDER"):
        get_search_provider()


def test_factory_explicit_tavily(fake_tavily_client: MagicMock) -> None:
    """``SEARCH_PROVIDER=tavily`` 显式也能工作。"""
    import os

    os.environ["SEARCH_PROVIDER"] = "tavily"
    try:
        provider = get_search_provider()
        from backend.services.search.tavily_provider import TavilyProvider

        assert isinstance(provider, TavilyProvider)
    finally:
        os.environ.pop("SEARCH_PROVIDER", None)
