from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.client_model import SelectedModel
from backend.services.search import UnsupportedSearchOperation
from backend.services.search.responses_provider import ResponsesNativeSearchProvider


class StubResponses:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


def _client_with_response(response: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(responses=StubResponses(response))


@pytest.mark.asyncio
async def test_openai_search_forces_one_web_call_and_maps_inline_citation() -> None:
    cited_fact = "苹果公司披露营收增长。"
    client = _client_with_response(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws_fixture",
                    "status": "completed",
                    "action": {"type": "search", "query": "苹果公司 年报"},
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": f"{cited_fact}[来源]",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://www.apple.com/newsroom/",
                                    "title": "Apple Newsroom",
                                    "start_index": 0,
                                    "end_index": len(cited_fact),
                                }
                            ],
                        }
                    ],
                },
            ]
        }
    )
    provider = ResponsesNativeSearchProvider(
        api_key="sk-openai-offline",
        selection=SelectedModel(vendor="openai", model="gpt-5.6-terra"),
        client=client,
    )

    results = await provider.search("苹果公司 最新财报", max_results=4)

    assert [(item.url, item.title, item.content, item.score) for item in results] == [
        (
            "https://www.apple.com/newsroom/",
            "Apple Newsroom",
            cited_fact,
            1.0,
        )
    ]
    assert results[0].raw == {
        "provider": "openai",
        "type": "url_citation",
        "url": "https://www.apple.com/newsroom/",
        "title": "Apple Newsroom",
        "content_kind": "text_range",
    }
    assert client.responses.calls == [
        {
            "model": "gpt-5.6-terra",
            "input": (
                "请联网检索以下主题：苹果公司 最新财报\n"
                "最多使用 4 个可靠公开来源，概括与主题直接相关的事实，"
                "不要引用没有 URL 的内容。"
            ),
            "tools": [{"type": "web_search", "search_context_size": "medium"}],
            "tool_choice": "required",
            "max_tool_calls": 1,
            "include": ["web_search_call.action.sources"],
        }
    ]
    assert "sk-openai-offline" not in repr(provider)


@pytest.mark.asyncio
async def test_openrouter_search_limits_paid_tool_and_prefers_citation_content() -> (
    None
):
    client = _client_with_response(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "苹果公司公开信息综合摘要。",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.cn/apple",
                                    "title": "苹果公司公开资料",
                                    "content": "来源自身返回的摘录。",
                                }
                            ],
                        }
                    ],
                },
            ],
            "usage": {"server_tool_use": {"web_search_requests": 1}},
        }
    )
    provider = ResponsesNativeSearchProvider(
        api_key="sk-openrouter-offline",
        selection=SelectedModel(
            vendor="openrouter",
            model="vendor/report-model",
        ),
        client=client,
    )

    results = await provider.search("苹果公司", max_results=3, time_range="month")

    assert [(item.url, item.content) for item in results] == [
        ("https://example.cn/apple", "来源自身返回的摘录。")
    ]
    assert results[0].raw["provider"] == "openrouter"
    assert results[0].raw["content_kind"] == "citation_content"
    assert client.responses.calls == [
        {
            "model": "vendor/report-model",
            "input": (
                "请联网检索以下主题，时间范围为 month：苹果公司\n"
                "最多使用 3 个可靠公开来源，概括与主题直接相关的事实，"
                "不要引用没有 URL 的内容。"
            ),
            "tools": [
                {
                    "type": "openrouter:web_search",
                    "parameters": {
                        "engine": "auto",
                        "max_results": 3,
                        "max_total_results": 3,
                        "max_uses": 1,
                        "max_characters": 8000,
                    },
                }
            ],
            "tool_choice": "required",
            "max_tool_calls": 1,
        }
    ]
    assert "sk-openrouter-offline" not in repr(provider)


@pytest.mark.asyncio
async def test_responses_search_never_cross_attributes_text_blocks() -> None:
    client = _client_with_response(
        {
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "甲来源事实。",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.cn/a",
                                    "start_index": 0,
                                    "end_index": 6,
                                }
                            ],
                        },
                        {
                            "type": "output_text",
                            "text": "乙来源事实。",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.cn/b",
                                    "start_index": 0,
                                    "end_index": 6,
                                }
                            ],
                        },
                    ],
                },
            ]
        }
    )
    provider = ResponsesNativeSearchProvider(
        api_key="sk-openai-offline",
        selection=SelectedModel(vendor="openai", model="gpt-5.6-sol"),
        client=client,
    )

    results = await provider.search("苹果公司")

    assert [(item.url, item.content) for item in results] == [
        ("https://example.cn/a", "甲来源事实。"),
        ("https://example.cn/b", "乙来源事实。"),
    ]


@pytest.mark.asyncio
async def test_responses_search_requires_vendor_search_evidence() -> None:
    client = _client_with_response(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "没有执行搜索的模型回答。",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.cn/untrusted",
                                    "content": "不应接受",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    provider = ResponsesNativeSearchProvider(
        api_key="sk-openrouter-offline",
        selection=SelectedModel(vendor="openrouter", model="vendor/report-model"),
        client=client,
    )

    assert await provider.search("苹果公司") == []


@pytest.mark.asyncio
async def test_responses_provider_explicitly_rejects_page_operations() -> None:
    provider = ResponsesNativeSearchProvider(
        api_key="sk-openai-offline",
        selection=SelectedModel(vendor="openai", model="gpt-5.6-luna"),
        client=_client_with_response({}),
    )

    with pytest.raises(UnsupportedSearchOperation, match="不支持站点递归抓取"):
        await provider.crawl("https://example.cn")
    with pytest.raises(UnsupportedSearchOperation, match="不支持批量正文抽取"):
        await provider.extract(["https://example.cn"])


@pytest.mark.parametrize(
    ("api_key", "selection", "message"),
    [
        (
            " ",
            SelectedModel(vendor="openai", model="gpt-5.6-terra"),
            "API Key 不能为空",
        ),
        (
            "sk-test",
            SelectedModel(vendor="glm", model="glm-5.2"),
            "只能使用 OpenAI 或 OpenRouter",
        ),
        (
            "sk-test",
            SelectedModel(vendor="openai", model="gpt-4o"),
            "当前不支持原生联网检索",
        ),
    ],
)
def test_responses_provider_rejects_invalid_configuration(
    api_key: str,
    selection: SelectedModel,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ResponsesNativeSearchProvider(api_key=api_key, selection=selection)


def test_responses_search_clients_disable_whole_request_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def capture_client(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return _client_with_response({})

    monkeypatch.setattr(
        "backend.services.search.responses_provider.AsyncOpenAI",
        capture_client,
    )

    ResponsesNativeSearchProvider(
        api_key="sk-openai-offline",
        selection=SelectedModel(vendor="openai", model="gpt-5.6-luna"),
    )
    ResponsesNativeSearchProvider(
        api_key="sk-openrouter-offline",
        selection=SelectedModel(
            vendor="openrouter",
            model="vendor/report-model",
        ),
    )

    assert [call["base_url"] for call in calls] == [
        "https://api.openai.com/v1",
        "https://openrouter.ai/api/v1",
    ]
    assert [call["max_retries"] for call in calls] == [0, 0]
