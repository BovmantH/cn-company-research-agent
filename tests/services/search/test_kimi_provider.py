"""Kimi 独立 Search Pro 接口的离线契约测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.services.client_model import SelectedModel
from backend.services.search import UnsupportedSearchOperation
from backend.services.search.kimi_provider import KimiSearchProvider
from backend.services.search.native_http import (
    NativeSearchRequestError,
    NativeSearchResponseInvalid,
    NativeSearchUnavailable,
)

SENTINEL_KEY = "sk-kimi-offline-sentinel"


def _provider(client: httpx.AsyncClient) -> KimiSearchProvider:
    return KimiSearchProvider(
        api_key=SENTINEL_KEY,
        selection=SelectedModel(vendor="kimi", model="kimi-k3.1-pro"),
        client=client,
    )


@pytest.mark.asyncio
async def test_kimi_search_uses_rest_and_preserves_per_page_chunks() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "search_results": [
                    {
                        "url": "https://example.cn/apple",
                        "title": "苹果公司公告",
                        "snippet": "不应优先使用的摘要",
                        "date": "2026-11-01",
                        "authority": "S",
                        "site_name": "官方公告",
                        "chunks": [
                            {"text": "同一页面的第一段正文。", "score": 1.23},
                            {"text": "同一页面的第二段正文。", "score": 1.01},
                        ],
                    },
                    {
                        "url": "https://example.cn/industry",
                        "title": "行业报道",
                        "snippet": "另一页面自己的摘要。",
                        "chunks": [],
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        result = await provider.search("  苹果公司 最新财报  ", max_results=5)

    assert requests[0].url == httpx.URL("https://api.moonshot.cn/v1/tools/search_pro")
    assert requests[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"
    assert json.loads(requests[0].content) == {
        "text_query": "苹果公司 最新财报",
        "limit": 5,
        "timeout_seconds": 30,
    }
    assert [(item.url, item.content) for item in result] == [
        (
            "https://example.cn/apple",
            "同一页面的第一段正文。\n\n同一页面的第二段正文。",
        ),
        ("https://example.cn/industry", "另一页面自己的摘要。"),
    ]
    assert result[0].published_date == "2026-11-01"
    assert result[0].score == 1.0
    assert result[1].score >= 0.4
    assert result[0].raw == {"authority": "S", "site_name": "官方公告"}
    assert SENTINEL_KEY not in repr(provider)


@pytest.mark.asyncio
async def test_kimi_search_drops_duplicate_unsafe_and_empty_sources() -> None:
    payload = {
        "search_results": [
            {"url": "https://example.cn/a", "snippet": "有效摘要"},
            {"url": "https://example.cn/a", "snippet": "重复摘要"},
            {"url": "file:///etc/passwd", "snippet": "非法来源"},
            {"url": "http://127.0.0.1/private", "snippet": "内部地址"},
            {"url": "https://user:secret@example.cn/a", "snippet": "凭证URL"},
            {"url": "https://example.cn/empty", "chunks": [{"text": " "}]},
            {"url": "https://example.cn/b", "snippet": "第二个有效摘要"},
        ]
    }
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        result = await _provider(client).search("苹果公司", max_results=2)

    assert [(item.url, item.content) for item in result] == [
        ("https://example.cn/a", "有效摘要"),
        ("https://example.cn/b", "第二个有效摘要"),
    ]


@pytest.mark.asyncio
async def test_kimi_empty_query_does_not_send_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("空查询不能消耗搜索额度")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await _provider(client).search("  ") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"search_results": None}, {"error": {}}, {"error": {}, "search_results": []}],
)
async def test_kimi_invalid_root_is_not_treated_as_no_results(payload: object) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NativeSearchResponseInvalid):
            await _provider(client).search("苹果公司")


@pytest.mark.asyncio
async def test_kimi_explicit_empty_results_are_valid() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"search_results": []})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        assert await _provider(client).search("苹果公司") == []


@pytest.mark.asyncio
async def test_kimi_rejects_oversized_query_before_paid_request() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("超限查询应在请求之前拒绝")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="搜索词不能超过"):
            await _provider(client).search("字" * 501)


@pytest.mark.asyncio
async def test_kimi_search_bounds_results_and_content_and_uses_time_window() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "search_results": [
                    {
                        "url": f"https://example.cn/{index}",
                        "chunks": [{"text": "字" * 9_000}],
                    }
                    for index in range(12)
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await _provider(client).search(
            "苹果公司", max_results=99, time_range="week"
        )

    request_body = json.loads(requests[0].content)
    assert request_body["limit"] == 10
    assert set(request_body["time_window"]) == {"start", "end"}
    assert request_body["time_window"]["start"] < request_body["time_window"]["end"]
    assert len(results) == 10
    assert all(len(item.content) == 8_000 for item in results)


@pytest.mark.asyncio
async def test_kimi_network_error_does_not_preserve_sensitive_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(SENTINEL_KEY, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NativeSearchUnavailable) as exc_info:
            await _provider(client).search("苹果公司")

    assert SENTINEL_KEY not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.parametrize(
    ("api_key", "selection", "message"),
    [
        (" ", SelectedModel("kimi", "kimi-k3.1-pro"), "API Key 不能为空"),
        (SENTINEL_KEY, SelectedModel("qwen", "qwen3.8-max"), "只能使用 Kimi"),
        (SENTINEL_KEY, SelectedModel("kimi", "bad model"), "标识格式不合法"),
    ],
)
def test_kimi_rejects_invalid_configuration(
    api_key: str,
    selection: SelectedModel,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        KimiSearchProvider(api_key=api_key, selection=selection)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_kimi_http_failure_never_exposes_body_or_key(status: int) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(status, text=f"Bearer {SENTINEL_KEY}")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NativeSearchUnavailable) as exc_info:
            await _provider(client).search("苹果公司")

    assert SENTINEL_KEY not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.asyncio
async def test_kimi_does_not_claim_recursive_crawl() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"search_results": []})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = _provider(client)
        with pytest.raises(UnsupportedSearchOperation, match="递归"):
            await provider.crawl("https://example.cn")


@pytest.mark.asyncio
async def test_kimi_fetch_maps_markdown_to_requested_source_and_deduplicates() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "url": "https://example.cn/redirected",
                "title": "苹果公司公告",
                "markdown": "# 公告\n\n这是原页面正文。",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = _provider(client)
        results = await provider.extract(
            ["https://example.cn/apple", "https://example.cn/apple"]
        )

    assert len(requests) == 1
    assert requests[0].url == httpx.URL("https://api.moonshot.cn/v1/tools/fetch")
    assert requests[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"
    assert json.loads(requests[0].content) == {"url": "https://example.cn/apple"}
    assert [(page.url, page.title, page.raw_content) for page in results] == [
        ("https://example.cn/apple", "苹果公司公告", "# 公告\n\n这是原页面正文。")
    ]


@pytest.mark.asyncio
async def test_kimi_fetch_limits_attempts_even_when_pages_have_no_content() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"title": "", "markdown": ""})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _provider(client).extract(
            [f"https://example.cn/{index}" for index in range(25)]
        )

    assert result == []
    assert len(requests) == 10


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://127.0.0.1/", "https://user:secret@example.cn/"],
)
async def test_kimi_fetch_rejects_unsafe_source_before_any_request(url: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("非法URL不能提交给付费抓取服务")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="公开网页"):
            await _provider(client).extract(["https://example.cn/valid", url])


@pytest.mark.asyncio
async def test_kimi_fetch_404_preserves_operation_without_upstream_body() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(404, text=f"Bearer {SENTINEL_KEY}")
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NativeSearchRequestError) as exc_info:
            await _provider(client).extract(["https://example.cn/apple"])

    assert exc_info.value.status_code == 404
    assert exc_info.value.operation == "fetch"
    assert SENTINEL_KEY not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"markdown": None}, {"error": {}}])
async def test_kimi_fetch_rejects_unknown_success_shape(payload: object) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(NativeSearchResponseInvalid):
            await _provider(client).extract(["https://example.cn/apple"])
