"""检索失败不能被报告成公司没有相关记录。"""

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from backend.nodes.researchers.company import CompanyAnalyzer
from backend.services.client_model import SelectedModel
from backend.services.provider_errors import classify_provider_failure
from backend.services.search.deepseek_provider import DeepSeekSearchProvider
from backend.services.search.native_http import NativeSearchRequestError


@pytest.mark.asyncio
async def test_failed_search_reaches_public_error_classification_without_secret():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(402, text="Authorization: Bearer sk-sensitive")
        )
    ) as client:
        node = CompanyAnalyzer(
            search=DeepSeekSearchProvider(
                api_key="sk-offline",
                selection=SelectedModel("deepseek", "deepseek-flash"),
                client=client,
            ),
            llm=GenericFakeChatModel(messages=iter([])),
        )
        events = []
        with pytest.raises(NativeSearchRequestError) as exc_info:
            async for event in node.search_documents({}, ["苹果公司"]):
                events.append(event)
    assert all(event["type"] != "search_complete" for event in events)
    assert (
        classify_provider_failure(exc_info.value).reason_code
        == "provider_balance_insufficient"
    )
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert "sk-sensitive" not in str(exc_info.value)


def test_fetch_404_is_page_unavailable_not_model_retirement():
    error = NativeSearchRequestError(
        status_code=404, operation="fetch", provider_name="DeepSeek"
    )
    assert classify_provider_failure(error).reason_code == "source_page_unavailable"
