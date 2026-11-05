"""DeepSeek 同 Key 的独立 Search/Fetch 适配器。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..client_model import CLIENT_MODEL_ID_PATTERN, SelectedModel
from . import CrawledPage, SearchResult, UnsupportedSearchOperation
from .native_http import NativeSearchResponseInvalid, post_native_search_json
from .native_utils import is_public_web_url, ranked_source_score, safe_string

DEEPSEEK_TOOLS_URL = "https://api.deepseek.com/v1/tools"
MAX_QUERY_CHARACTERS = 128
MAX_RESULTS = 10
MAX_CONTENT_CHARACTERS = 8_000
_TIME_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


class DeepSeekSearchProvider:
    """逐条保留原厂来源；检索不依赖模型自由选择工具。"""

    def __init__(
        self,
        *,
        api_key: str,
        selection: SelectedModel,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API Key 不能为空")
        if selection.vendor != "deepseek" or not CLIENT_MODEL_ID_PATTERN.fullmatch(
            selection.model
        ):
            raise ValueError("DeepSeek 检索需要已确认的原厂模型选择")
        self._api_key = api_key.strip()
        self._client = client

    async def _post(self, operation: str, payload: dict[str, Any]):
        return await post_native_search_json(
            url=f"{DEEPSEEK_TOOLS_URL}/{operation}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            payload=payload,
            provider_name="DeepSeek",
            client=self._client,
            operation=operation,
        )

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **_kwargs: Any,
    ) -> list[SearchResult]:
        """只使用来源自身的正文或摘要，0～3 的原厂分数归一至 0～1。"""
        normalized = query.strip()
        if not normalized:
            return []
        if time_range:
            days = _TIME_RANGE_DAYS.get(time_range)
            if days is None:
                raise ValueError("DeepSeek 搜索时间范围必须为 day/week/month/year")
            after = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
            normalized = f"{normalized} after:{after}"
        if len(normalized) > MAX_QUERY_CHARACTERS:
            raise ValueError("DeepSeek 搜索词（含时间条件）不能超过 128 字符")
        limit = min(max(max_results, 1), MAX_RESULTS)
        payload = await self._post(
            "search", {"query": normalized, "count": limit, "need_content": True}
        )
        records = payload.get("results")
        if "error" in payload or not isinstance(records, list):
            raise NativeSearchResponseInvalid("DeepSeek 搜索返回格式异常")
        results: list[SearchResult] = []
        seen: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                continue
            url = safe_string(record.get("url"))
            content = next(
                (
                    text
                    for key in ("content", "summary", "snippet")
                    if (text := safe_string(record.get(key)))
                ),
                "",
            )
            if not is_public_web_url(url) or url in seen or not content:
                continue
            score = record.get("rerank_score")
            normalized_score = (
                min(max(float(score) / 3, 0.0), 1.0)
                if type(score) in (int, float) and math.isfinite(score)
                else ranked_source_score(len(results))
            )
            results.append(
                SearchResult(
                    url=url,
                    title=safe_string(record.get("title")),
                    content=content[:MAX_CONTENT_CHARACTERS],
                    score=normalized_score,
                    published_date=safe_string(record.get("date")) or None,
                    raw={"provider": "deepseek"},
                )
            )
            seen.add(url)
            if len(results) >= limit:
                break
        if records and not results:
            raise NativeSearchResponseInvalid("DeepSeek 搜索未返回可用的公开来源")
        return results

    async def extract(self, urls: list[str], **_kwargs: Any) -> list[CrawledPage]:
        """按 URL 提取单页；任务级预算由统一检索边界进一步限制。"""
        pages: list[CrawledPage] = []
        candidates = list(dict.fromkeys(urls))[:MAX_RESULTS]
        for url in candidates:
            if not is_public_web_url(url):
                raise ValueError("DeepSeek 正文提取只接受公开 HTTP(S) 页面")
        for url in candidates:
            payload = await self._post("fetch", {"url": url})
            content = payload.get("content")
            if "error" in payload or not isinstance(content, str):
                raise NativeSearchResponseInvalid("DeepSeek 正文提取返回格式异常")
            if content.strip():
                pages.append(
                    CrawledPage(
                        url=url,
                        raw_content=content[:MAX_CONTENT_CHARACTERS],
                        title=safe_string(payload.get("title")),
                    )
                )
        return pages

    async def crawl(self, url: str, *, max_pages: int = 5, **_kwargs: Any):
        """官方 Fetch 是单页提取，不提供递归站点抓取。"""
        raise UnsupportedSearchOperation("DeepSeek 不支持站点递归抓取")


__all__ = ["DeepSeekSearchProvider"]
