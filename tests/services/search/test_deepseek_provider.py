"""DeepSeek 官方结构化检索契约的离线回归。"""

import json

import httpx
import pytest

from backend.services.client_model import SelectedModel
from backend.services.search import UnsupportedSearchOperation
from backend.services.search.deepseek_provider import DeepSeekSearchProvider
from backend.services.search.native_http import NativeSearchResponseInvalid


@pytest.mark.asyncio
async def test_deepseek_search_preserves_each_sources_content_and_normalizes_score():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.cn/a",
                        "title": "公司年报",
                        "summary": "该页摘要",
                        "content": "该页原文",
                        "rerank_score": 2.4,
                        "date": "2026-10-01",
                    },
                    {
                        "url": "https://example.cn/b",
                        "summary": "另一页摘要",
                        "rerank_score": 1.5,
                    },
                    {"url": "https://example.cn/a", "summary": "重复"},
                    {"url": "http://127.0.0.1/secret", "summary": "不应采用"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DeepSeekSearchProvider(
            api_key="sk-offline-only",
            selection=SelectedModel("deepseek", "deepseek-flash"),
            client=client,
        )
        results = await provider.search("苹果公司年报", max_results=5)
    assert [(r.url, r.content) for r in results] == [
        ("https://example.cn/a", "该页原文"),
        ("https://example.cn/b", "另一页摘要"),
    ]
    assert results[0].score == pytest.approx(0.8)
    assert results[1].score == pytest.approx(0.5)
    assert requests[0].url == httpx.URL("https://api.deepseek.com/v1/tools/search")
    assert requests[0].headers["authorization"] == "Bearer sk-offline-only"
    assert json.loads(requests[0].content) == {
        "query": "苹果公司年报",
        "count": 5,
        "need_content": True,
    }
    assert "sk-offline-only" not in repr(provider)


@pytest.mark.asyncio
async def test_deepseek_fetch_is_single_page_and_crawl_is_explicitly_unsupported():
    def handler(request):
        assert json.loads(request.content) == {"url": "https://example.cn/report"}
        assert request.url.path == "/v1/tools/fetch"
        return httpx.Response(200, json={"title": "年报", "content": "# 年报正文"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DeepSeekSearchProvider(
            api_key="sk-offline-only",
            selection=SelectedModel("deepseek", "deepseek-flash"),
            client=client,
        )
        pages = await provider.extract(["https://example.cn/report"])
        with pytest.raises(UnsupportedSearchOperation):
            await provider.crawl("https://example.cn")
    assert [(p.url, p.raw_content) for p in pages] == [
        ("https://example.cn/report", "# 年报正文")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": "invalid"}])
async def test_deepseek_unknown_success_shape_is_not_empty_search(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        provider = DeepSeekSearchProvider(
            api_key="sk-offline-only",
            selection=SelectedModel("deepseek", "deepseek-flash"),
            client=client,
        )
        with pytest.raises(NativeSearchResponseInvalid):
            await provider.search("苹果公司")


@pytest.mark.asyncio
async def test_deepseek_empty_and_oversized_queries_do_not_make_paid_requests():
    def handler(_):
        raise AssertionError("无效查询不应发送请求")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = DeepSeekSearchProvider(
            api_key="sk-offline-only",
            selection=SelectedModel("deepseek", "deepseek-flash"),
            client=client,
        )
        assert await provider.search(" ") == []
        with pytest.raises(ValueError, match="128"):
            await provider.search("司" * 129)


@pytest.mark.asyncio
async def test_deepseek_explicit_empty_results_are_valid():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"results": []})
        )
    ) as client:
        provider = DeepSeekSearchProvider(
            api_key="sk-offline-only",
            selection=SelectedModel("deepseek", "deepseek-flash"),
            client=client,
        )
        assert await provider.search("苹果公司") == []
