"""OpenAI 与 OpenRouter Responses 托管联网搜索适配器。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from openai import AsyncOpenAI

from ..client_model import (
    CLIENT_MODEL_ID_PATTERN,
    OPENAI_RESPONSES_WEB_SEARCH_MODELS,
    SelectedModel,
)
from ..provider_registry import VENDOR_REGISTRY
from . import CrawledPage, SearchResult, UnsupportedSearchOperation
from .native_utils import is_public_web_url, ranked_source_score, safe_string

RESPONSES_SEARCH_VENDORS = frozenset({"openai", "openrouter"})
MAX_SEARCH_QUERY_LENGTH = 500
MAX_SEARCH_RESULTS = 10
MAX_RESULT_CONTENT_LENGTH = 8_000


class ResponsesNativeSearchProvider:
    """强制执行一次托管搜索，并标准化逐文本块 URL citation。"""

    def __init__(
        self,
        *,
        api_key: str,
        selection: SelectedModel,
        client: Any | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("Responses API Key 不能为空")
        if selection.vendor not in RESPONSES_SEARCH_VENDORS:
            raise ValueError("Responses 联网检索只能使用 OpenAI 或 OpenRouter 模型选择")
        normalized_model = selection.model.strip()
        if not CLIENT_MODEL_ID_PATTERN.fullmatch(normalized_model):
            raise ValueError("Responses 模型标识格式不合法")
        if (
            selection.vendor == "openai"
            and normalized_model not in OPENAI_RESPONSES_WEB_SEARCH_MODELS
        ):
            raise ValueError("该 OpenAI 模型当前不支持原生联网检索")

        self._provider = selection.vendor
        self._model = normalized_model
        self._client = client or AsyncOpenAI(
            api_key=normalized_key,
            base_url=VENDOR_REGISTRY[selection.vendor].base_url,
            timeout=60.0,
            # 付费搜索没有可用的幂等键，整请求自动重试可能重复计费。
            max_retries=0,
        )

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **_kwargs: Any,
    ) -> list[SearchResult]:
        """执行一次受限托管搜索，只返回可归属到单个文本块的来源。"""
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
        request: dict[str, Any] = {
            "model": self._model,
            "input": prompt,
            "tools": [self._search_tool(result_limit)],
            "tool_choice": "required",
            "max_tool_calls": 1,
        }
        if self._provider == "openai":
            request["include"] = ["web_search_call.action.sources"]
        response = await self._client.responses.create(**request)
        payload = _response_payload(response)
        if not _has_search_evidence(payload, self._provider):
            return []
        return _citation_results(payload, result_limit, self._provider)

    def _search_tool(self, result_limit: int) -> dict[str, Any]:
        """返回厂商文档化的固定工具配置，并锁住单次搜索费用。"""
        if self._provider == "openai":
            return {"type": "web_search", "search_context_size": "medium"}
        return {
            "type": "openrouter:web_search",
            "parameters": {
                "engine": "auto",
                "max_results": result_limit,
                "max_total_results": result_limit,
                "max_uses": 1,
                "max_characters": MAX_RESULT_CONTENT_LENGTH,
            },
        }

    async def crawl(
        self,
        url: str,
        *,
        max_pages: int = 5,
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """Responses 托管搜索不提供递归站点抓取。"""
        raise UnsupportedSearchOperation("Responses 原生联网不支持站点递归抓取")

    async def extract(
        self,
        urls: list[str],
        **_kwargs: Any,
    ) -> list[CrawledPage]:
        """Responses 托管搜索不提供批量正文抽取。"""
        raise UnsupportedSearchOperation("Responses 原生联网不支持批量正文抽取")


def _response_payload(response: Any) -> Mapping[str, Any]:
    if isinstance(response, Mapping):
        return response
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    return {}


def _has_search_evidence(payload: Mapping[str, Any], provider: str) -> bool:
    """按厂商正式响应契约确认搜索已执行，拒绝仅由模型生成的伪引用。"""
    if provider == "openai":
        return any(
            item.get("type") == "web_search_call" and item.get("status") == "completed"
            for item in _walk_mappings(payload.get("output", []))
        )

    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return False
    server_tool_use = usage.get("server_tool_use")
    if not isinstance(server_tool_use, Mapping):
        return False
    search_requests = server_tool_use.get("web_search_requests")
    return type(search_requests) is int and search_requests > 0


def _citation_results(
    payload: Mapping[str, Any],
    limit: int,
    provider: str,
) -> list[SearchResult]:
    """按文本块解析 citation，禁止跨块或跨来源复制综合回答。"""
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for block in _walk_mappings(payload.get("output", [])):
        if block.get("type") != "output_text":
            continue
        block_text = safe_string(block.get("text"))
        annotations = block.get("annotations")
        if not isinstance(annotations, list):
            continue
        for item in annotations:
            if not isinstance(item, Mapping) or item.get("type") != "url_citation":
                continue
            nested = item.get("url_citation")
            citation = nested if isinstance(nested, Mapping) else item
            url = citation.get("url")
            if (
                not isinstance(url, str)
                or not is_public_web_url(url)
                or url in seen_urls
            ):
                continue
            content, content_kind = _citation_content(citation, block_text)
            if not content:
                continue
            title = safe_string(citation.get("title"))
            seen_urls.add(url)
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    content=content[:MAX_RESULT_CONTENT_LENGTH],
                    score=ranked_source_score(len(results)),
                    raw={
                        "provider": provider,
                        "type": "url_citation",
                        "url": url,
                        "title": title,
                        "content_kind": content_kind,
                    },
                )
            )
            if len(results) >= limit:
                return results
    return results


def _citation_content(
    citation: Mapping[str, Any],
    block_text: str,
) -> tuple[str, str]:
    direct_content = safe_string(citation.get("content"))
    if direct_content:
        return direct_content, "citation_content"
    start = citation.get("start_index")
    end = citation.get("end_index")
    if type(start) is int and type(end) is int and 0 <= start < end <= len(block_text):
        segment = block_text[start:end].strip()
        if segment and not _looks_like_citation_marker(segment):
            return segment, "text_range"
        sentence = _preceding_sentence(block_text, start)
        if sentence:
            return sentence, "cited_sentence"
    return "", ""


def _looks_like_citation_marker(value: str) -> bool:
    return (
        (value.startswith("[") and value.endswith("]"))
        or (value.startswith("(") and value.endswith(")"))
        or value.startswith("http://")
        or value.startswith("https://")
    )


def _preceding_sentence(text: str, end: int) -> str:
    prefix = text[:end].rstrip()
    if not prefix:
        return ""
    start = max(prefix.rfind(mark) for mark in "。！？.!?\n")
    return prefix[start + 1 :].strip()


def _walk_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for nested in value.values():
            yield from _walk_mappings(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            yield from _walk_mappings(nested)


__all__ = ["ResponsesNativeSearchProvider"]
