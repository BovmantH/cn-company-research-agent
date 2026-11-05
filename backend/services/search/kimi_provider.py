"""使用同一把 Kimi 用户 Key 调用结构化 Search Pro 接口。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..client_model import CLIENT_MODEL_ID_PATTERN, SelectedModel
from . import CrawledPage, SearchResult, UnsupportedSearchOperation
from .native_http import NativeSearchResponseInvalid, post_native_search_json
from .native_utils import is_public_web_url, ranked_source_score, safe_string

KIMI_SEARCH_PRO_URL = "https://api.moonshot.cn/v1/tools/search_pro"
KIMI_FETCH_URL = "https://api.moonshot.cn/v1/tools/fetch"
MAX_SEARCH_QUERY_LENGTH = 500
MAX_SEARCH_RESULTS = 10
MAX_RESULT_CONTENT_LENGTH = 8_000
MAX_FETCH_URLS = 10
MAX_FETCH_CONTENT_LENGTH = 80_000
SEARCH_TIMEOUT_SECONDS = 30
_TIME_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}


class KimiSearchProvider:
    """将 Kimi 按页面归组的正文片段映射到统一检索接口。"""

    def __init__(
        self,
        *,
        api_key: str,
        selection: SelectedModel,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("Kimi API Key 不能为空")
        if selection.vendor != "kimi":
            raise ValueError("Kimi 联网检索只能使用 Kimi 模型选择")
        if not CLIENT_MODEL_ID_PATTERN.fullmatch(selection.model):
            raise ValueError("Kimi 模型标识格式不合法")
        # Search Pro 是独立接口，模型 ID 仅由任务目录校验，不参与搜索请求。
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
        """一次请求取得结构化来源，不由模型自主调用或循环调用付费工具。"""
        normalized_query = query.strip()
        if not normalized_query:
            return []
        if len(normalized_query) > MAX_SEARCH_QUERY_LENGTH:
            raise ValueError("Kimi 搜索词不能超过 500 个字符")
        result_limit = min(max(max_results, 1), MAX_SEARCH_RESULTS)
        request: dict[str, Any] = {
            "text_query": normalized_query,
            "limit": result_limit,
            "timeout_seconds": SEARCH_TIMEOUT_SECONDS,
        }
        if days := _TIME_RANGE_DAYS.get(time_range):
            today = datetime.now(UTC).date()
            request["time_window"] = {
                "start": (today - timedelta(days=days)).isoformat(),
                "end": today.isoformat(),
            }
        payload = await post_native_search_json(
            url=KIMI_SEARCH_PRO_URL,
            headers={"Authorization": self._authorization},
            payload=request,
            provider_name="Kimi",
            client=self._client,
        )
        records = payload.get("search_results")
        if "error" in payload or not isinstance(records, list):
            raise NativeSearchResponseInvalid("Kimi 联网搜索返回格式异常")

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for record in records:
            if not isinstance(record, Mapping):
                continue
            url = record.get("url")
            if (
                not isinstance(url, str)
                or not is_public_web_url(url)
                or url in seen_urls
            ):
                continue
            content = _page_content(record)
            if not content:
                continue
            seen_urls.add(url)
            results.append(
                SearchResult(
                    url=url,
                    title=safe_string(record.get("title")),
                    content=content,
                    score=ranked_source_score(len(results)),
                    published_date=safe_string(record.get("date")) or None,
                    raw={
                        "authority": safe_string(record.get("authority")),
                        "site_name": safe_string(record.get("site_name")),
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
        """独立搜索与单页提取接口不等价于递归站点抓取。"""
        raise UnsupportedSearchOperation("Kimi 原生联网不支持站点递归抓取")

    async def extract(
        self,
        urls: list[str],
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """按 URL 去重且限制尝试次数；任务总预算由外层共享包装器负责。"""
        candidates: list[str] = []
        seen_urls: set[str] = set()
        for url in urls:
            if not isinstance(url, str) or not is_public_web_url(url):
                raise ValueError("Kimi 正文提取只接受不含凭证的公开网页地址")
            if url in seen_urls:
                continue
            candidates.append(url)
            seen_urls.add(url)
            if len(candidates) >= MAX_FETCH_URLS:
                break

        pages: list[CrawledPage] = []
        for url in candidates:
            payload = await post_native_search_json(
                url=KIMI_FETCH_URL,
                headers={"Authorization": self._authorization},
                payload={"url": url},
                provider_name="Kimi",
                client=self._client,
                operation="fetch",
            )
            markdown = payload.get("markdown")
            if "error" in payload or not isinstance(markdown, str):
                raise NativeSearchResponseInvalid("Kimi 正文提取返回格式异常")
            content = markdown.strip()
            if not content:
                continue
            pages.append(
                CrawledPage(
                    # 上游 URL 可能因重定向改变，增强阶段仍需关联原始来源。
                    url=url,
                    title=safe_string(payload.get("title")),
                    raw_content=content[:MAX_FETCH_CONTENT_LENGTH],
                )
            )
        return pages


def _page_content(record: Mapping[str, Any]) -> str:
    """只拼同一页面的有效正文片段，无正文时使用该页自身摘要。"""
    chunks = record.get("chunks")
    content_parts: list[str] = []
    remaining = MAX_RESULT_CONTENT_LENGTH
    if isinstance(chunks, list):
        for chunk in chunks:
            if not isinstance(chunk, Mapping):
                continue
            text = safe_string(chunk.get("text"))
            if not text:
                continue
            content_parts.append(text[:remaining])
            remaining -= len(content_parts[-1]) + 2
            if remaining <= 0:
                break
    if content_parts:
        return "\n\n".join(content_parts)[:MAX_RESULT_CONTENT_LENGTH]
    return safe_string(record.get("snippet"))[:MAX_RESULT_CONTENT_LENGTH]


__all__ = ["KimiSearchProvider"]
