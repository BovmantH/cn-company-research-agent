"""百炼原生流式联网及明确角标来源的适配器。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import httpx

from ..client_model import (
    CLIENT_MODEL_ID_PATTERN,
    QWEN_RESPONSES_WEB_SEARCH_MODELS,
    SelectedModel,
)
from ..qwen_config import normalize_qwen_workspace_id
from . import CrawledPage, SearchResult, UnsupportedSearchOperation
from .native_http import NativeSearchResponseInvalid, post_native_search_json
from .native_utils import is_public_web_url, ranked_source_score, safe_string

MAX_RESULT_CONTENT_LENGTH = 8_000
_CITATION_GROUP = re.compile(r"(?:\[ref_\d+\])+")
_CITATION_INDEX = re.compile(r"\[ref_(\d+)\]")


class QwenNativeSearchProvider:
    """使用原厂 search_info 与明确角标关联文本，不把综合回答复制给每个 URL。"""

    def __init__(
        self,
        *,
        api_key: str,
        selection: SelectedModel,
        client: httpx.AsyncClient | None = None,
        workspace_id: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("千问 API Key 不能为空")
        if selection.vendor != "qwen" or not CLIENT_MODEL_ID_PATTERN.fullmatch(
            selection.model
        ):
            raise ValueError("千问联网检索只能使用千问模型选择")
        if selection.model not in QWEN_RESPONSES_WEB_SEARCH_MODELS:
            raise ValueError("该千问模型当前不支持原生联网检索")
        workspace = normalize_qwen_workspace_id(workspace_id)
        host = (
            f"{workspace}.cn-beijing.maas.aliyuncs.com"
            if workspace
            else "dashscope.aliyuncs.com"
        )
        # 3.7 Max 是文本接口；其余已核新模型必须使用多模态流式接口。
        self._multimodal = selection.model != "qwen3.7-max"
        route = "multimodal-generation" if self._multimodal else "text-generation"
        self._url = f"https://{host}/api/v1/services/aigc/{route}/generation"
        self._model = selection.model
        self._key = api_key.strip()
        self._client = client

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **_kwargs: Any,
    ) -> list[SearchResult]:
        normalized = query.strip()[:500]
        if not normalized:
            return []
        prompt = f"请联网检索：{normalized}。请给事实标注对应来源。"
        if time_range:
            prompt += f"时间范围：{time_range}。"
        payload = await post_native_search_json(
            url=self._url,
            headers={
                "Authorization": f"Bearer {self._key}",
                "X-DashScope-SSE": "enable",
            },
            payload={
                "model": self._model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}]
                            if self._multimodal
                            else prompt,
                        }
                    ]
                },
                "parameters": {
                    "enable_search": True,
                    "incremental_output": True,
                    "max_tokens": 4096,
                    "result_format": "message",
                    "search_options": {
                        "search_strategy": "turbo",
                        "forced_search": True,
                        "enable_source": True,
                        "enable_citation": True,
                        "citation_format": "[ref_<number>]",
                    },
                },
            },
            provider_name="千问",
            client=self._client,
            sse=True,
        )
        return _cited_results(payload["events"], min(max(max_results, 1), 10))

    async def crawl(
        self, url: str, *, max_pages: int = 5, **_kwargs: Any
    ) -> list[CrawledPage]:
        raise UnsupportedSearchOperation("千问原生联网不支持站点递归抓取")

    async def extract(self, urls: list[str], **_kwargs: Any) -> list[CrawledPage]:
        raise UnsupportedSearchOperation("千问原生联网不支持批量正文抽取")


def _cited_results(events: list[Mapping[str, Any]], limit: int) -> list[SearchResult]:
    """只接受官方结果索引中有对应来源的角标文本。"""
    sources: dict[int, Mapping[str, Any]] = {}
    texts: list[str] = []
    completed = False
    search_observed = False
    for event in events:
        if event.get("code") or event.get("error"):
            raise NativeSearchResponseInvalid("千问联网响应异常")
        output = event.get("output")
        if not isinstance(output, Mapping):
            raise NativeSearchResponseInvalid("千问联网返回格式异常")
        info = output.get("search_info")
        if isinstance(info, Mapping):
            records = info.get("search_results")
            if not isinstance(records, list):
                raise NativeSearchResponseInvalid("千问搜索来源格式异常")
            search_observed = True
            for source in records:
                if (
                    not isinstance(source, Mapping)
                    or type(source.get("index")) is not int
                ):
                    continue
                index = source["index"]
                if index in sources and sources[index].get("url") != source.get("url"):
                    raise NativeSearchResponseInvalid("千问来源索引不一致")
                sources[index] = source
        for choice in output.get("choices", []):
            if not isinstance(choice, Mapping):
                continue
            completed |= choice.get("finish_reason") == "stop"
            message = choice.get("message")
            if not isinstance(message, Mapping):
                continue
            content = message.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(
                    safe_string(part.get("text"))
                    for part in content
                    if isinstance(part, Mapping)
                )
    if not completed:
        raise NativeSearchResponseInvalid("千问联网响应未完整结束")
    if not search_observed:
        raise NativeSearchResponseInvalid("千问未返回可验证的联网来源")
    text = "".join(texts)
    fragments: dict[str, list[str]] = {}
    metadata: dict[str, Mapping[str, Any]] = {}
    previous_end = 0
    for group in _CITATION_GROUP.finditer(text):
        segment = text[previous_end : group.start()].strip()
        previous_end = group.end()
        # 最近一句与当前角标绑定；连续多个角标共享该句。
        segment = re.split(r"[。！？!?\n]", segment.rstrip("。！？!?"))[-1].strip()
        if not segment:
            continue
        for raw_index in _CITATION_INDEX.findall(group.group()):
            source = sources.get(int(raw_index), {})
            url = safe_string(source.get("url"))
            if not is_public_web_url(url):
                continue
            fragments.setdefault(url, []).append(segment)
            metadata[url] = source
    results = [
        SearchResult(
            url=url,
            title=safe_string(metadata[url].get("title")),
            content="\n".join(parts)[:MAX_RESULT_CONTENT_LENGTH],
            score=ranked_source_score(index),
            raw={"provider": "qwen", "content_kind": "cited_sentence"},
        )
        for index, (url, parts) in enumerate(fragments.items())
    ]
    if sources and not results:
        raise NativeSearchResponseInvalid("千问已返回来源链接，但没有可归属的引用内容")
    return results[:limit]


__all__ = ["QwenNativeSearchProvider"]
