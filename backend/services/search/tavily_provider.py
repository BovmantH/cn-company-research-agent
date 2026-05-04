"""Tavily 实现的 ``SearchProvider``。

封装 ``tavily.AsyncTavilyClient`` 三个核心方法(search / crawl / extract),
把响应映射为 ``SearchResult`` / ``CrawledPage`` 数据类。

Tavily 专有参数(如 ``topic``、``time_range``、``search_depth``、
``include_raw_content``、``max_depth``、``max_breadth``、``extract_depth``、
``instructions``)通过 ``**kwargs`` 透传,上层节点可继续使用。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from tavily import AsyncTavilyClient

from . import CrawledPage, SearchResult

logger = logging.getLogger(__name__)


class TavilyProvider:
    """Tavily 检索 provider。"""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            raise RuntimeError(
                "未配置 TAVILY_API_KEY,无法使用 TavilyProvider。"
                "请在 .env 中设置或在初始化时显式传入 api_key。"
            )
        self._client = AsyncTavilyClient(api_key=key)

    # ---- search ----

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """对 ``query`` 调 Tavily search,返回标准化 ``SearchResult`` 列表。

        Tavily 专有参数(``topic``、``search_depth``、``include_raw_content`` 等)
        通过 ``**kwargs`` 透传。
        """
        params: dict[str, Any] = {"max_results": max_results}
        if time_range is not None:
            params["time_range"] = time_range
        params.update(kwargs)

        response = await self._client.search(query, **params)
        return [_to_search_result(item) for item in response.get("results", [])]

    # ---- crawl ----

    async def crawl(
        self,
        url: str,
        *,
        max_pages: int = 5,
        **kwargs: Any,
    ) -> list[CrawledPage]:
        """对 ``url`` 调 Tavily crawl,返回多页正文。

        Tavily 的 crawl 参数命名是 ``max_breadth``,本接口约定 ``max_pages``,
        在内部映射(若 kwargs 显式传 ``max_breadth`` 则以 kwargs 为准)。
        其他 Tavily 专有参数(``instructions``、``max_depth``、
        ``extract_depth``)走 kwargs 透传。
        """
        params: dict[str, Any] = {}

        # max_pages 映射为 Tavily 的 max_breadth(若 kwargs 没显式覆盖)
        if "max_breadth" not in kwargs:
            params["max_breadth"] = max_pages

        params.update(kwargs)

        response = await self._client.crawl(url=url, **params)
        return [
            _to_crawled_page(item, fallback_url=url)
            for item in response.get("results", [])
            if item.get("raw_content")
        ]

    # ---- extract ----

    async def extract(
        self,
        urls: list[str],
        **kwargs: Any,
    ) -> list[CrawledPage]:
        """从给定 URL 批量抽取正文。Tavily ``extract`` API 直接接受 url 列表。"""
        if not urls:
            return []

        response = await self._client.extract(urls=urls, **kwargs)
        return [
            _to_crawled_page(item, fallback_url="")
            for item in response.get("results", [])
            if item.get("raw_content")
        ]


# === 私有映射函数 ===


def _to_search_result(item: dict[str, Any]) -> SearchResult:
    """Tavily search 单条结果 → ``SearchResult``。"""
    return SearchResult(
        url=item.get("url", "") or "",
        title=item.get("title", "") or "",
        content=item.get("content", "") or "",
        score=_safe_float(item.get("score"), 0.0),
        published_date=item.get("published_date"),
        raw=dict(item),  # 保留原始字段(包括 raw_content 等)
    )


def _to_crawled_page(item: dict[str, Any], *, fallback_url: str) -> CrawledPage:
    """Tavily crawl/extract 单条结果 → ``CrawledPage``。"""
    return CrawledPage(
        url=item.get("url", fallback_url) or fallback_url,
        raw_content=item.get("raw_content", "") or "",
        title=item.get("title", "") or "",
        raw=dict(item),
    )


def _safe_float(value: Any, default: float) -> float:
    """把可能是 None / 字符串的 score 安全转 float。"""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
