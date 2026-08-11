from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.client_model import SelectedModel
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


def test_provider_rejects_unsafe_model_identifier() -> None:
    with pytest.raises(ValueError, match="千问模型标识格式不合法"):
        QwenNativeSearchProvider(
            api_key="sk-user-qwen",
            selection=SelectedModel(vendor="qwen", model="包含 空格"),
            client=_client_with_response({}),
        )


def test_provider_rejects_qwen_model_without_confirmed_web_search() -> None:
    with pytest.raises(ValueError, match="当前不支持 Responses 原生联网检索"):
        QwenNativeSearchProvider(
            api_key="sk-user-qwen",
            selection=SelectedModel(vendor="qwen", model="qwen3.7-flash"),
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
                                    "content": "示例公司近期公开信息摘要。",
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
        selection=SelectedModel(vendor="qwen", model="qwen3.7-plus"),
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
async def test_search_uses_citation_ranges_without_cross_source_attribution() -> None:
    summary = "甲事实。乙事实。"
    client = _client_with_response(
        {
            "output_text": summary,
            "output": [
                {
                    "type": "output_text",
                    "text": summary,
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://example.cn/a",
                            "start_index": 0,
                            "end_index": 4,
                        },
                        {
                            "type": "url_citation",
                            "url": "https://example.cn/b",
                            "start_index": 4,
                            "end_index": 8,
                        },
                    ],
                }
            ],
        }
    )
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        selection=SelectedModel(vendor="qwen", model="qwen3.7-plus"),
        client=client,
    )

    results = await provider.search("示例公司")

    assert [(result.url, result.content) for result in results] == [
        ("https://example.cn/a", "甲事实。"),
        ("https://example.cn/b", "乙事实。"),
    ]


@pytest.mark.asyncio
async def test_search_drops_citation_without_content_or_text_range() -> None:
    client = _client_with_response(
        {
            "output_text": "多来源综合摘要",
            "output": [
                {
                    "type": "url_citation",
                    "url": "https://example.cn/company",
                }
            ],
        }
    )
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        selection=SelectedModel(vendor="qwen", model="qwen3.7-plus"),
        client=client,
    )

    assert await provider.search("示例公司") == []


@pytest.mark.asyncio
async def test_search_drops_non_public_citation_urls() -> None:
    client = _client_with_response(
        {
            "output_text": "公开来源摘要",
            "output": [
                {
                    "type": "output_text",
                    "text": "公开来源摘要",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "http://localhost/internal",
                            "content": "本地主机来源",
                        },
                        {
                            "type": "url_citation",
                            "url": "http://10.0.0.1/internal",
                            "content": "私网来源",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://example.cn/public",
                            "content": "公开来源摘要",
                        },
                    ],
                }
            ],
        }
    )
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        selection=SelectedModel(vendor="qwen", model="qwen3.7-plus"),
        client=client,
    )

    results = await provider.search("示例公司")

    assert [(result.url, result.content) for result in results] == [
        ("https://example.cn/public", "公开来源摘要")
    ]


@pytest.mark.asyncio
async def test_search_without_verifiable_citation_returns_no_documents() -> None:
    client = _client_with_response({"output_text": "没有附带来源的回答", "output": []})
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        selection=SelectedModel(vendor="qwen", model="qwen3.7-plus"),
        client=client,
    )

    assert await provider.search("示例公司") == []


@pytest.mark.asyncio
async def test_qwen_provider_explicitly_rejects_unsupported_page_operations() -> None:
    provider = QwenNativeSearchProvider(
        api_key="sk-user-qwen",
        selection=SelectedModel(vendor="qwen", model="qwen3.7-plus"),
        client=_client_with_response({}),
    )

    with pytest.raises(UnsupportedSearchOperation, match="不支持站点递归抓取"):
        await provider.crawl("https://example.cn")
    with pytest.raises(UnsupportedSearchOperation, match="不支持批量正文抽取"):
        await provider.extract(["https://example.cn"])
