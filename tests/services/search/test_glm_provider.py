from __future__ import annotations

import json

import httpx
import pytest

from backend.services.client_model import SelectedModel
from backend.services.search import UnsupportedSearchOperation
from backend.services.search.glm_provider import GlmWebSearchProvider
from backend.services.search.native_http import (
    NativeSearchResponseInvalid,
    NativeSearchUnavailable,
)

SENTINEL_KEY = "sk-glm-offline-sentinel"


def _client_with_response(
    payload: object,
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), requests


def _glm_provider(client: httpx.AsyncClient) -> GlmWebSearchProvider:
    return GlmWebSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="glm", model="glm-5.2"),
        client=client,
    )


@pytest.mark.asyncio
async def test_search_uses_glm_web_search_api_and_normalizes_sources() -> None:
    client, requests = _client_with_response(
        {
            "search_result": [
                {
                    "title": "苹果公司公开资料",
                    "content": "苹果公司公开披露的离线测试摘要。",
                    "link": "https://example.cn/apple",
                    "media": "示例站点",
                    "icon": "https://example.cn/favicon.ico",
                    "refer": "ref_1",
                    "publish_date": "2026-08-01",
                }
            ]
        }
    )
    provider = GlmWebSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="glm", model="glm-5.2"),
        client=client,
    )
    try:
        results = await provider.search(
            "苹果公司 最新财报",
            max_results=5,
            time_range="month",
        )
    finally:
        await client.aclose()

    assert [(item.title, item.url, item.content) for item in results] == [
        (
            "苹果公司公开资料",
            "https://example.cn/apple",
            "苹果公司公开披露的离线测试摘要。",
        )
    ]
    assert results[0].published_date == "2026-08-01"
    assert results[0].score == 1.0
    assert results[0].raw == {
        "media": "示例站点",
        "refer": "ref_1",
        "icon": "https://example.cn/favicon.ico",
    }
    assert requests[0].url == httpx.URL(
        "https://open.bigmodel.cn/api/paas/v4/web_search"
    )
    assert requests[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"
    assert json.loads(requests[0].content) == {
        "search_query": "苹果公司 最新财报",
        "search_engine": "search_std",
        "search_intent": False,
        "count": 5,
        "search_recency_filter": "oneMonth",
        "content_size": "medium",
    }
    assert SENTINEL_KEY not in repr(provider)


@pytest.mark.asyncio
async def test_glm_search_drops_unverifiable_or_duplicate_sources() -> None:
    client, _ = _client_with_response(
        {
            "search_result": [
                {
                    "title": "合法来源",
                    "content": "来源自身摘要",
                    "link": "https://example.cn/apple",
                },
                {
                    "title": "重复来源",
                    "content": "重复摘要",
                    "link": "https://example.cn/apple",
                },
                {
                    "title": "本地地址",
                    "content": "不应进入报告",
                    "link": "file:///etc/passwd",
                },
                {
                    "title": "回环地址",
                    "content": "不应进入报告",
                    "link": "http://127.0.0.1/internal",
                },
                {
                    "title": "链路本地地址",
                    "content": "不应进入报告",
                    "link": "http://169.254.169.254/latest/meta-data",
                },
                {
                    "title": "本地主机名",
                    "content": "不应进入报告",
                    "link": "http://localhost/internal",
                },
                {
                    "title": "空摘要",
                    "content": " ",
                    "link": "https://example.cn/empty",
                },
            ]
        }
    )
    provider = GlmWebSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="glm", model="glm-4.7"),
        client=client,
    )
    try:
        results = await provider.search("苹果公司")
    finally:
        await client.aclose()

    assert [(item.url, item.content) for item in results] == [
        ("https://example.cn/apple", "来源自身摘要")
    ]
    assert results[0].score >= 0.4


@pytest.mark.asyncio
async def test_glm_provider_explicitly_rejects_page_operations() -> None:
    client, _ = _client_with_response({"search_result": []})
    provider = GlmWebSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="glm", model="glm-4.7-flash"),
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
        (" ", SelectedModel(vendor="glm", model="glm-5.2"), "API Key 不能为空"),
        (
            SENTINEL_KEY,
            SelectedModel(vendor="qwen", model="qwen3.7-plus"),
            "只能使用智谱模型选择",
        ),
    ],
)
def test_glm_provider_rejects_invalid_configuration(
    api_key: str,
    selection: SelectedModel,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        GlmWebSearchProvider(api_key=api_key, selection=selection)


@pytest.mark.asyncio
async def test_glm_search_drops_sensitive_upstream_error_context() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            text=f"Authorization: Bearer {SENTINEL_KEY}",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NativeSearchUnavailable) as exc_info:
            await _glm_provider(client).search("苹果公司")

    assert SENTINEL_KEY not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.asyncio
async def test_glm_search_drops_sensitive_network_exception_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"Authorization: Bearer {SENTINEL_KEY}",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NativeSearchUnavailable) as exc_info:
            await _glm_provider(client).search("苹果公司")

    assert SENTINEL_KEY not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        b"not-json",
        b'{"search_result": ["too-large"]}',
    ],
)
async def test_glm_search_rejects_invalid_or_oversized_success_response(
    content: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if content.startswith(b"{"):
        monkeypatch.setattr(
            "backend.services.search.native_http.MAX_NATIVE_SEARCH_RESPONSE_BYTES",
            10,
        )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NativeSearchResponseInvalid) as exc_info:
            await _glm_provider(client).search("苹果公司")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
