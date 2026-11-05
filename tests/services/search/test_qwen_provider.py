"""百炼官方原生流式搜索与明确角标的离线契约。"""

import json

import httpx
import pytest

from backend.services.client_model import SelectedModel
from backend.services.search.native_http import NativeSearchResponseInvalid
from backend.services.search.qwen_provider import QwenNativeSearchProvider


def _events(text="苹果公司披露营收增长[ref_1]。另一来源报道新品[ref_2]。"):
    # 形状来自官方 DashScope SSE 示例；内容和域名为离线合成样例。
    return [
        {
            "output": {
                "search_info": {
                    "search_results": [
                        {
                            "index": 1,
                            "url": "https://example.cn/report",
                            "title": "年报",
                        },
                        {"index": 2, "url": "https://example.cn/news", "title": "新闻"},
                    ]
                },
                "choices": [
                    {"message": {"content": [{"text": text}]}, "finish_reason": "stop"}
                ],
            }
        },
    ]


def _response(events):
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(
            "data:" + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events
        ).encode(),
    )


@pytest.mark.asyncio
async def test_qwen_uses_multimodal_streaming_and_keeps_citations_separate():
    requests = []

    def handler(request):
        requests.append(request)
        return _response(_events())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = QwenNativeSearchProvider(
            api_key="sk-qwen-offline",
            selection=SelectedModel("qwen", "qwen3.8-flash"),
            client=client,
            workspace_id="workspace-1",
        )
        results = await provider.search("苹果公司")
    assert [(r.url, r.content) for r in results] == [
        ("https://example.cn/report", "苹果公司披露营收增长"),
        ("https://example.cn/news", "另一来源报道新品"),
    ]
    assert requests[0].url == httpx.URL(
        "https://workspace-1.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    body = json.loads(requests[0].content)
    assert body["model"] == "qwen3.8-flash"
    assert body["parameters"]["search_options"] == {
        "search_strategy": "turbo",
        "forced_search": True,
        "enable_source": True,
        "enable_citation": True,
        "citation_format": "[ref_<number>]",
    }
    assert requests[0].headers["X-DashScope-SSE"] == "enable"
    assert "sk-qwen-offline" not in repr(provider)
    assert results[0].raw["content_kind"] == "cited_sentence"


@pytest.mark.asyncio
async def test_qwen_does_not_present_sources_only_as_evidence():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: _response(_events("没有角标的综合回答"))
        )
    ) as client:
        provider = QwenNativeSearchProvider(
            api_key="sk-offline",
            selection=SelectedModel("qwen", "qwen3.7-plus"),
            client=client,
        )
        with pytest.raises(NativeSearchResponseInvalid, match="没有可归属"):
            await provider.search("苹果公司")


@pytest.mark.asyncio
async def test_qwen_keeps_early_sources_when_later_stream_events_omit_them():
    events = _events("事实[ref_1]")
    events[0]["output"]["choices"][0]["finish_reason"] = "null"
    events.append(
        {
            "output": {
                "search_info": {"search_results": []},
                "choices": [{"message": {"content": []}, "finish_reason": "stop"}],
            }
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: _response(events))
    ) as client:
        results = await QwenNativeSearchProvider(
            api_key="sk-offline",
            selection=SelectedModel("qwen", "qwen3.7-plus"),
            client=client,
        ).search("苹果公司")
    assert len(results) == 1
    assert results[0].content == "事实"


@pytest.mark.asyncio
async def test_qwen_stream_requires_complete_response():
    events = _events()
    events[0]["output"]["choices"][0]["finish_reason"] = "length"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: _response(events))
    ) as client:
        with pytest.raises(NativeSearchResponseInvalid, match="未完整"):
            await QwenNativeSearchProvider(
                api_key="sk-offline",
                selection=SelectedModel("qwen", "qwen3.7-plus"),
                client=client,
            ).search("苹果公司")


@pytest.mark.parametrize(
    "workspace", ["attacker.example", "x/y", "x@attacker", "a" * 65]
)
def test_qwen_never_sends_key_to_user_supplied_endpoint(workspace):
    with pytest.raises(ValueError, match="业务空间"):
        QwenNativeSearchProvider(
            api_key="sk-offline",
            selection=SelectedModel("qwen", "qwen3.7-plus"),
            workspace_id=workspace,
        )
