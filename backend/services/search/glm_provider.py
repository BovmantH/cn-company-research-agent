"""使用同一把智谱用户 Key 调用官方 Web Search API。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..client_model import (
    CLIENT_MODEL_ID_PATTERN,
    GLM_WEB_SEARCH_MODELS,
    SelectedModel,
)
from . import CrawledPage, SearchResult, UnsupportedSearchOperation
from .native_http import NativeSearchResponseInvalid, post_native_search_json
from .native_utils import is_public_web_url, ranked_source_score, safe_string

GLM_WEB_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"
MAX_GLM_SEARCH_QUERY_LENGTH = 70
MAX_SEARCH_RESULTS = 10
MAX_RESULT_CONTENT_LENGTH = 8_000
GLM_RECENCY_FILTERS: dict[str | None, str] = {
    None: "noLimit",
    "day": "oneDay",
    "week": "oneWeek",
    "month": "oneMonth",
    "year": "oneYear",
}


class GlmWebSearchProvider:
    """把智谱结构化网页搜索结果映射到统一检索接口。"""

    def __init__(
        self,
        *,
        api_key: str,
        selection: SelectedModel,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("智谱 API Key 不能为空")
        if selection.vendor != "glm":
            raise ValueError("智谱联网检索只能使用智谱模型选择")
        normalized_model = selection.model.strip()
        if not CLIENT_MODEL_ID_PATTERN.fullmatch(normalized_model):
            raise ValueError("智谱模型标识格式不合法")
        if normalized_model not in GLM_WEB_SEARCH_MODELS:
            raise ValueError("该智谱模型当前不支持原生联网检索")
        self._authorization = f"Bearer {normalized_key}"
        self._client = client

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **_kwargs: Any,
    ) -> list[SearchResult]:
        """调用智谱搜索接口，只保留带公开 URL 和来源摘要的记录。"""
        normalized_query = query.strip()[:MAX_GLM_SEARCH_QUERY_LENGTH]
        if not normalized_query:
            return []
        result_limit = min(max(max_results, 1), MAX_SEARCH_RESULTS)
        payload = await post_native_search_json(
            url=GLM_WEB_SEARCH_URL,
            headers={"Authorization": self._authorization},
            payload={
                "search_query": normalized_query,
                "search_engine": "search_std",
                "search_intent": False,
                "count": result_limit,
                "search_recency_filter": GLM_RECENCY_FILTERS.get(time_range, "noLimit"),
                "content_size": "medium",
            },
            provider_name="智谱",
            client=self._client,
        )
        records = payload.get("search_result")
        if not isinstance(records, list):
            raise NativeSearchResponseInvalid("智谱联网搜索返回格式异常")

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                continue
            url = record.get("link")
            content = record.get("content")
            if (
                not isinstance(url, str)
                or not is_public_web_url(url)
                or url in seen_urls
                or not isinstance(content, str)
                or not content.strip()
            ):
                continue
            title = record.get("title")
            published_date = record.get("publish_date")
            seen_urls.add(url)
            results.append(
                SearchResult(
                    url=url,
                    title=title.strip() if isinstance(title, str) else "",
                    content=content.strip()[:MAX_RESULT_CONTENT_LENGTH],
                    score=ranked_source_score(len(results)),
                    published_date=(
                        published_date.strip()
                        if isinstance(published_date, str) and published_date.strip()
                        else None
                    ),
                    raw={
                        "media": safe_string(record.get("media")),
                        "refer": safe_string(record.get("refer")),
                        "icon": safe_string(record.get("icon")),
                    },
                )
            )
            if len(results) >= result_limit:
                break
        return results

    async def crawl(
        self,
        url: str,
        *,
        max_pages: int = 5,
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """智谱 Web Search API 不提供递归站点抓取。"""
        raise UnsupportedSearchOperation("智谱原生联网不支持站点递归抓取")

    async def extract(
        self,
        urls: list[str],
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """智谱 Web Search API 不提供批量正文抽取。"""
        raise UnsupportedSearchOperation("智谱原生联网不支持批量正文抽取")


__all__ = ["GlmWebSearchProvider"]
