from __future__ import annotations

import json

import httpx
import pytest

from backend.services.client_model import SelectedModel
from backend.services.search import UnsupportedSearchOperation
from backend.services.search.mimo_provider import MiMoNativeSearchProvider

SENTINEL_KEY = "sk-mimo-offline-sentinel"


def _client_with_response(
    payload: object,
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests


@pytest.mark.asyncio
async def test_search_uses_mimo_web_tool_and_only_maps_citation_summaries() -> None:
    client, requests = _client_with_response(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "综合回答不得归给任意单一来源。",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.cn/apple-a",
                                "title": "苹果公司来源 A",
                                "summary": "来源 A 自身返回的摘要。",
                                "site_name": "示例站点",
                                "publish_time": "2026-08-01T08:00:00+08:00",
                                "logo_url": "https://example.cn/favicon.ico",
                            },
                            {
                                "type": "url_citation",
                                "url": "http://[::1]/internal",
                                "title": "回环地址",
                                "summary": "不应进入报告。",
                            },
                            {
                                "type": "url_citation",
                                "url": "https://example.cn/apple-b",
                                "title": "苹果公司来源 B",
                                "summary": "来源 B 自身返回的摘要。",
                                "site_name": "示例站点",
                                "publish_time": "2026-08-02T08:00:00+08:00",
                                "logo_url": "https://example.cn/favicon.ico",
                            },
                        ],
                    },
                }
            ]
        }
    )
    provider = MiMoNativeSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="mimo", model="mimo-v2.5"),
        client=client,
    )
    try:
        results = await provider.search("苹果公司 最新财报", max_results=2)
    finally:
        await client.aclose()

    assert [(item.url, item.title, item.content) for item in results] == [
        (
            "https://example.cn/apple-a",
            "苹果公司来源 A",
            "来源 A 自身返回的摘要。",
        ),
        (
            "https://example.cn/apple-b",
            "苹果公司来源 B",
            "来源 B 自身返回的摘要。",
        ),
    ]
    assert results[0].published_date == "2026-08-01T08:00:00+08:00"
    assert [item.score for item in results] == [1.0, 0.95]
    assert results[0].raw == {
        "type": "url_citation",
        "site_name": "示例站点",
        "logo_url": "https://example.cn/favicon.ico",
    }
    assert requests[0].url == httpx.URL(
        "https://api.xiaomimimo.com/v1/chat/completions"
    )
    assert requests[0].headers["api-key"] == SENTINEL_KEY
    assert json.loads(requests[0].content) == {
        "model": "mimo-v2.5",
        "messages": [
            {
                "role": "user",
                "content": (
                    "请联网检索：苹果公司 最新财报。最多使用 2 个可靠公开来源，"
                    "不要引用没有 URL 的内容。"
                ),
            }
        ],
        "tools": [
            {
                "type": "web_search",
                "max_keyword": 1,
                "force_search": True,
                "limit": 2,
            }
        ],
        "tool_choice": "auto",
        "stream": False,
        "max_completion_tokens": 1024,
        "thinking": {"type": "disabled"},
    }
    assert SENTINEL_KEY not in repr(provider)


@pytest.mark.asyncio
async def test_mimo_search_never_uses_combined_answer_as_source_content() -> None:
    client, _ = _client_with_response(
        {
            "choices": [
                {
                    "message": {
                        "content": "只有模型综合回答，没有可验证的逐来源摘要。",
                        "annotations": [],
                    }
                }
            ]
        }
    )
    provider = MiMoNativeSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="mimo", model="mimo-v2.5-pro"),
        client=client,
    )
    try:
        assert await provider.search("苹果公司") == []
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_mimo_provider_explicitly_rejects_page_operations() -> None:
    client, _ = _client_with_response({"choices": []})
    provider = MiMoNativeSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="mimo", model="mimo-v2.5-pro"),
        client=client,
    )
    try:
        with pytest.raises(UnsupportedSearchOperation, match="不支持站点递归抓取"):
            await provider.crawl("https://example.cn")
        with pytest.raises(UnsupportedSearchOperation, match="不支持批量正文抽取"):
            await provider.extract(["https://example.cn"])
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    ("api_key", "selection", "message"),
    [
        (" ", SelectedModel(vendor="mimo", model="mimo-v2.5"), "API Key 不能为空"),
        (
            "tp-token-plan-not-supported",
            SelectedModel(vendor="mimo", model="mimo-v2.5"),
            "不支持 Token Plan Key",
        ),
        (
            SENTINEL_KEY,
            SelectedModel(vendor="qwen", model="qwen3.7-plus"),
            "只能使用小米 MiMo 模型选择",
        ),
        (
            SENTINEL_KEY,
            SelectedModel(vendor="mimo", model="mimo-v2"),
            "当前不支持原生联网检索",
        ),
    ],
)
def test_mimo_provider_rejects_invalid_configuration(
    api_key: str,
    selection: SelectedModel,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        MiMoNativeSearchProvider(api_key=api_key, selection=selection)
