"""使用同一把小米 MiMo 用户 Key 调用原生联网工具。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ..client_model import (
    CLIENT_MODEL_ID_PATTERN,
    MIMO_WEB_SEARCH_MODELS,
    SelectedModel,
)
from . import CrawledPage, SearchResult, UnsupportedSearchOperation
from .native_http import NativeSearchResponseInvalid, post_native_search_json
from .native_utils import is_public_web_url, ranked_source_score, safe_string

MIMO_CHAT_COMPLETIONS_URL = "https://api.xiaomimimo.com/v1/chat/completions"
MAX_SEARCH_QUERY_LENGTH = 500
MAX_SEARCH_RESULTS = 10
MAX_RESULT_CONTENT_LENGTH = 8_000


class MiMoNativeSearchProvider:
    """强制调用 MiMo Web Search，并只接受逐来源 citation 摘要。"""

    def __init__(
        self,
        *,
        api_key: str,
        selection: SelectedModel,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("小米 MiMo API Key 不能为空")
        if normalized_key.startswith("tp-"):
            raise ValueError("当前按量 API 端点不支持 Token Plan Key")
        if selection.vendor != "mimo":
            raise ValueError("小米 MiMo 联网检索只能使用小米 MiMo 模型选择")
        normalized_model = selection.model.strip()
        if not CLIENT_MODEL_ID_PATTERN.fullmatch(normalized_model):
            raise ValueError("小米 MiMo 模型标识格式不合法")
        if normalized_model not in MIMO_WEB_SEARCH_MODELS:
            raise ValueError("该小米 MiMo 模型当前不支持原生联网检索")
        self._api_key = normalized_key
        self._model = normalized_model
        self._client = client

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **_kwargs: Any,
    ) -> list[SearchResult]:
        """强制执行一次搜索，只读取官方 annotation 中的来源摘要。"""
        normalized_query = query.strip()[:MAX_SEARCH_QUERY_LENGTH]
        if not normalized_query:
            return []
        result_limit = min(max(max_results, 1), MAX_SEARCH_RESULTS)
        time_hint = f"，时间范围为 {time_range}" if time_range else ""
        prompt = (
            f"请联网检索{time_hint}：{normalized_query}。"
            f"最多使用 {result_limit} 个可靠公开来源，不要引用没有 URL 的内容。"
        )
        payload = await post_native_search_json(
            url=MIMO_CHAT_COMPLETIONS_URL,
            headers={"api-key": self._api_key},
            payload={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "tools": [
                    {
                        "type": "web_search",
                        "max_keyword": 1,
                        "force_search": True,
                        "limit": result_limit,
                    }
                ],
                "tool_choice": "auto",
                "stream": False,
                "max_completion_tokens": 1024,
                "thinking": {"type": "disabled"},
            },
            provider_name="小米 MiMo",
            client=self._client,
        )
        annotations = _annotations(payload)
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for annotation in annotations:
            if annotation.get("type") != "url_citation":
                continue
            url = annotation.get("url")
            summary = annotation.get("summary")
            if (
                not isinstance(url, str)
                or not is_public_web_url(url)
                or url in seen_urls
                or not isinstance(summary, str)
                or not summary.strip()
            ):
                continue
            title = annotation.get("title")
            published_date = annotation.get("publish_time")
            seen_urls.add(url)
            results.append(
                SearchResult(
                    url=url,
                    title=title.strip() if isinstance(title, str) else "",
                    content=summary.strip()[:MAX_RESULT_CONTENT_LENGTH],
                    score=ranked_source_score(len(results)),
                    published_date=(
                        published_date.strip()
                        if isinstance(published_date, str) and published_date.strip()
                        else None
                    ),
                    raw={
                        "type": "url_citation",
                        "site_name": safe_string(annotation.get("site_name")),
                        "logo_url": safe_string(annotation.get("logo_url")),
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
        """MiMo 原生搜索不提供递归站点抓取。"""
        raise UnsupportedSearchOperation("小米 MiMo 原生联网不支持站点递归抓取")

    async def extract(
        self,
        urls: list[str],
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """MiMo 原生搜索不提供批量正文抽取。"""
        raise UnsupportedSearchOperation("小米 MiMo 原生联网不支持批量正文抽取")


def _annotations(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise NativeSearchResponseInvalid("小米 MiMo 联网搜索返回格式异常")
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise NativeSearchResponseInvalid("小米 MiMo 联网搜索返回格式异常")
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise NativeSearchResponseInvalid("小米 MiMo 联网搜索返回格式异常")
    annotations = message.get("annotations")
    if not isinstance(annotations, list):
        raise NativeSearchResponseInvalid("小米 MiMo 联网搜索返回格式异常")
    return [item for item in annotations if isinstance(item, Mapping)]


__all__ = ["MiMoNativeSearchProvider"]
