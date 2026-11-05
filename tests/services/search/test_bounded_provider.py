"""通过 HTTP 边界验证任务共享的付费检索次数和正文去重。"""

import asyncio

import httpx
import pytest

from backend.services.client_model import SelectedModel
from backend.services.search.bounded_provider import BoundedSearchProvider
from backend.services.search.deepseek_provider import DeepSeekSearchProvider


@pytest.mark.asyncio
async def test_search_limit_is_shared_by_concurrent_analysts():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BoundedSearchProvider(
            DeepSeekSearchProvider(
                api_key="sk-offline",
                selection=SelectedModel("deepseek", "deepseek-flash"),
                client=client,
            ),
            max_searches=2,
        )
        results = await asyncio.gather(
            *(provider.search(f"公司{i}") for i in range(6)), return_exceptions=True
        )
    assert len(requests) == 2
    assert sum(isinstance(result, Exception) for result in results) == 4


@pytest.mark.asyncio
async def test_fetch_budget_deduplicates_urls_across_concurrent_categories():
    requests = []

    async def handler(request):
        requests.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json={"title": "年报", "content": "来源正文"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = BoundedSearchProvider(
            DeepSeekSearchProvider(
                api_key="sk-offline",
                selection=SelectedModel("deepseek", "deepseek-flash"),
                client=client,
            ),
            max_fetches=2,
        )
        first, second = await asyncio.gather(
            provider.extract(["https://example.cn/a", "https://example.cn/b"]),
            provider.extract(["https://example.cn/a", "https://example.cn/c"]),
        )
    assert len(requests) == 2
    assert [page.url for page in first] == [
        "https://example.cn/a",
        "https://example.cn/b",
    ]
    assert [page.url for page in second] == ["https://example.cn/a"]
