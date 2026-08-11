"""使用百炼同一把用户 Key 执行千问原生联网搜索。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from openai import AsyncOpenAI

from ..client_model import (
    CLIENT_MODEL_ID_PATTERN,
    QWEN_RESPONSES_WEB_SEARCH_MODELS,
    SelectedModel,
)
from ..provider_registry import VENDOR_REGISTRY
from . import CrawledPage, SearchResult, UnsupportedSearchOperation
from .native_utils import is_public_web_url, ranked_source_score

MAX_SEARCH_QUERY_LENGTH = 500
MAX_SEARCH_RESULTS = 10
MAX_RESULT_CONTENT_LENGTH = 8_000


class QwenNativeSearchProvider:
    """通过百炼 Responses API 的托管工具返回带来源的检索结果。"""

    def __init__(
        self,
        *,
        api_key: str,
        selection: SelectedModel,
        client: Any | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("千问 API Key 不能为空")
        if selection.vendor != "qwen":
            raise ValueError("千问联网检索只能使用千问模型选择")
        normalized_model = selection.model.strip()
        if not CLIENT_MODEL_ID_PATTERN.fullmatch(normalized_model):
            raise ValueError("千问模型标识格式不合法")
        if normalized_model not in QWEN_RESPONSES_WEB_SEARCH_MODELS:
            raise ValueError("该千问模型当前不支持 Responses 原生联网检索")
        self._model = normalized_model
        self._client = client or AsyncOpenAI(
            api_key=normalized_key,
            base_url=VENDOR_REGISTRY["qwen"].base_url,
            timeout=60.0,
            max_retries=2,
        )

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **_kwargs: Any,
    ) -> list[SearchResult]:
        """执行一次强制联网检索，只返回包含可验证 URL 引用的结果。"""
        normalized_query = query.strip()[:MAX_SEARCH_QUERY_LENGTH]
        if not normalized_query:
            return []
        result_limit = min(max(max_results, 1), MAX_SEARCH_RESULTS)
        time_hint = f"，时间范围为 {time_range}" if time_range else ""
        prompt = (
            f"请联网检索以下主题{time_hint}：{normalized_query}\n"
            f"最多使用 {result_limit} 个可靠公开来源，概括与主题直接相关的事实，"
            "不要引用没有 URL 的内容。"
        )
        response = await self._client.responses.create(
            model=self._model,
            input=prompt,
            tools=[{"type": "web_search"}, {"type": "web_extractor"}],
            extra_body={"enable_thinking": True},
        )
        payload = _response_payload(response)
        summary = _response_text(payload)[:MAX_RESULT_CONTENT_LENGTH]
        return _citation_results(payload, summary, result_limit)

    async def crawl(
        self,
        url: str,
        *,
        max_pages: int = 5,
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """千问原生搜索不提供与现有契约等价的递归站点抓取。"""
        raise UnsupportedSearchOperation("千问原生联网不支持站点递归抓取")

    async def extract(
        self,
        urls: list[str],
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """千问原生搜索不提供批量原文抽取，避免把摘要伪装为正文。"""
        raise UnsupportedSearchOperation("千问原生联网不支持批量正文抽取")


def _response_payload(response: Any) -> Mapping[str, Any]:
    """把 SDK 对象或测试字典转换为只读映射。"""
    if isinstance(response, Mapping):
        return response
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def _response_text(payload: Mapping[str, Any]) -> str:
    """提取 Responses 顶层或消息块中的最终文本。"""
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text.strip()
    for item in _walk_mappings(payload.get("output", [])):
        if item.get("type") == "output_text" and isinstance(item.get("text"), str):
            return str(item["text"]).strip()
    return ""


def _citation_results(
    payload: Mapping[str, Any],
    summary: str,
    limit: int,
) -> list[SearchResult]:
    """按首次出现顺序去重 URL，并丢弃非 HTTP(S) 或缺少来源的内容。"""
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for item in _walk_mappings(payload):
        if item.get("type") != "url_citation":
            continue
        nested = item.get("url_citation")
        citation = nested if isinstance(nested, Mapping) else item
        url = citation.get("url")
        if not isinstance(url, str) or not is_public_web_url(url) or url in seen_urls:
            continue
        title = citation.get("title")
        normalized_content = _citation_content(citation, summary)
        if not normalized_content:
            continue
        seen_urls.add(url)
        results.append(
            SearchResult(
                url=url,
                title=title.strip() if isinstance(title, str) else "",
                content=normalized_content[:MAX_RESULT_CONTENT_LENGTH],
                score=ranked_source_score(len(results)),
                raw={
                    "type": "url_citation",
                    "url": url,
                    "title": title.strip() if isinstance(title, str) else "",
                },
            )
        )
        if len(results) >= limit:
            break
    return results


def _citation_content(citation: Mapping[str, Any], summary: str) -> str:
    """只采用来源自带正文或明确文本区间，禁止把综合摘要归给单一来源。"""
    content = citation.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    start = citation.get("start_index")
    end = citation.get("end_index")
    if type(start) is int and type(end) is int and 0 <= start < end <= len(summary):
        return summary[start:end].strip()
    return ""


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    """深度遍历 JSON 结构中的字典节点。"""
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _walk_mappings(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            yield from _walk_mappings(nested)


__all__ = ["QwenNativeSearchProvider"]
