from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.search import UnsupportedSearchOperation
from backend.services.search.qwen_provider import QwenNativeSearchProvider


class StubResponses:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def _client_with_response(response: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(responses=StubResponses(response))


def test_provider_rejects_model_outside_qwen_allowlist() -> None:
    with pytest.raises(ValueError, match="千问原生联网不支持模型"):
        QwenNativeSearchProvider(
            api_key="sk-user-qwen",
            model="gpt-5.6-terra",
            client=_client_with_response({}),
        )


@pytest.mark.asyncio
async def test_search_uses_qwen_web_tools_and_normalizes_citations() -> None:
    client = _client_with_response(
        {
            "output_text": "示例公司近期公开信息摘要。",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "示例公司近期公开信息摘要。",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.cn/company",
                                    "title": "示例公司工商信息",
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://example.cn/company",
                                    "title": "重复来源",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    )
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        model="qwen3.7-plus",
        client=client,
    )

    results = await provider.search("示例公司 工商信息", max_results=5)

    assert [(item.title, item.url, item.content) for item in results] == [
        (
            "示例公司工商信息",
            "https://example.cn/company",
            "示例公司近期公开信息摘要。",
        )
    ]
    call = client.responses.calls[0]
    assert call["model"] == "qwen3.7-plus"
    assert {tool["type"] for tool in call["tools"]} == {
        "web_search",
        "web_extractor",
    }
    assert "sk-user-qwen" not in repr(provider)


@pytest.mark.asyncio
async def test_search_without_verifiable_citation_returns_no_documents() -> None:
    client = _client_with_response({"output_text": "没有附带来源的回答", "output": []})
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        model="qwen3.7-plus",
        client=client,
    )

    assert await provider.search("示例公司") == []


@pytest.mark.asyncio
async def test_qwen_provider_explicitly_rejects_unsupported_page_operations() -> None:
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        model="qwen3.7-plus",
        client=_client_with_response({}),
    )

    with pytest.raises(UnsupportedSearchOperation, match="不支持站点递归抓取"):
        await provider.crawl("https://example.cn")
    with pytest.raises(UnsupportedSearchOperation, match="不支持批量正文抽取"):
        await provider.extract(["https://example.cn"])
