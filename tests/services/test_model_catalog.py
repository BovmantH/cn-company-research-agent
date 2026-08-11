"""官方模型目录服务测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.services.client_model import CLIENT_MODEL_VENDORS
from backend.services.model_catalog import (
    CURATED_MODEL_OPTIONS,
    DYNAMIC_MODEL_VENDORS,
    ModelCatalogCredentialError,
    ModelCatalogService,
    ModelCatalogUnavailable,
    official_model_catalog_url,
)


@pytest.mark.parametrize(
    ("vendor", "url"),
    [
        ("opencode", "https://opencode.ai/zen/v1/models"),
        ("deepseek", "https://api.deepseek.com/models"),
        ("kimi", "https://api.moonshot.cn/v1/models"),
        ("minimax", "https://api.minimaxi.com/v1/models"),
        ("mimo", "https://api.xiaomimimo.com/v1/models"),
        ("openrouter", "https://openrouter.ai/api/v1/models/user"),
        ("openai", "https://api.openai.com/v1/models"),
    ],
)
def test_dynamic_catalog_vendors_use_fixed_official_urls(vendor: str, url: str) -> None:
    assert official_model_catalog_url(vendor) == url


@pytest.mark.parametrize("vendor", ["qwen", "glm"])
def test_undocumented_model_routes_are_not_used(vendor: str) -> None:
    with pytest.raises(ValueError, match="没有文档化"):
        official_model_catalog_url(vendor)


def test_every_client_vendor_has_exactly_one_catalog_source() -> None:
    assert set(CLIENT_MODEL_VENDORS) == (
        set(DYNAMIC_MODEL_VENDORS) | set(CURATED_MODEL_OPTIONS)
    )
    assert not set(DYNAMIC_MODEL_VENDORS) & set(CURATED_MODEL_OPTIONS)


@pytest.mark.asyncio
async def test_catalog_uses_fixed_official_endpoint_and_user_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "kimi-k4",
                        "object": "model",
                        "owned_by": "moonshot",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = ModelCatalogService(client=client)
        result = await catalog.list_models("kimi", "sk-user-catalog")

    assert result.source == "official_api"
    assert [model.id for model in result.models] == ["kimi-k4"]
    assert requests[0].url == httpx.URL("https://api.moonshot.cn/v1/models")
    assert requests[0].headers["Authorization"] == "Bearer sk-user-catalog"


@pytest.mark.asyncio
async def test_catalog_keeps_only_safe_text_model_fields() -> None:
    payload = {
        "data": [
            {
                "id": "vendor/report-chat",
                "name": "报告模型",
                "description": "不应传给前端的上游说明",
                "architecture": {"output_modalities": ["text"]},
            },
            {
                "id": "vendor/report-chat",
                "name": "重复项",
            },
            {
                "id": "vendor/image-generator",
                "name": "图片模型",
                "architecture": {"output_modalities": ["image"]},
            },
            {
                "id": "vendor/image-understanding-chat",
                "name": "视觉理解模型",
                "architecture": {"output_modalities": ["text"]},
            },
            {"id": "text-embedding-4", "name": "向量模型"},
            {"id": "包含 空格", "name": "非法标识"},
        ]
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(payload).encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ModelCatalogService(client=client).list_models(
            "openrouter",
            "sk-test",
        )

    assert [model.model_dump() for model in result.models] == [
        {"id": "vendor/report-chat", "name": "报告模型"},
        {
            "id": "vendor/image-understanding-chat",
            "name": "视觉理解模型",
        },
    ]


@pytest.mark.asyncio
async def test_openrouter_uses_user_filtered_text_catalog() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "vendor/chat"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await ModelCatalogService(client=client).list_models("openrouter", "sk-test")

    assert requests[0].url == httpx.URL(
        "https://openrouter.ai/api/v1/models/user?output_modalities=text"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vendor", "expected_ids"),
    [
        ("qwen", ["qwen3.7-plus", "qwen3.7-max"]),
        ("glm", ["glm-4.7", "glm-5.2", "glm-4.7-flash"]),
    ],
)
async def test_catalog_marks_vendors_without_official_api_as_curated(
    vendor: str,
    expected_ids: list[str],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("没有官方目录的厂商不得调用未文档化端点")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ModelCatalogService(client=client).list_models(vendor, "")

    assert result.source == "curated"
    assert [model.id for model in result.models] == expected_ids


@pytest.mark.asyncio
async def test_dynamic_catalog_requires_user_key_before_request() -> None:
    with pytest.raises(ValueError, match="需要 API Key"):
        await ModelCatalogService().list_models("kimi", "")


@pytest.mark.asyncio
async def test_catalog_rejects_unknown_vendor_without_sending_request() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = ModelCatalogService(client=client)
        with pytest.raises(ValueError, match="不支持的模型供应商"):
            await catalog.list_models("custom", "sk-test")

    assert called is False


@pytest.mark.asyncio
async def test_catalog_credential_error_does_not_expose_key_or_body() -> None:
    secret = "sk-user-catalog-secret"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"Authorization: Bearer {secret}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelCatalogCredentialError) as exc_info:
            await ModelCatalogService(client=client).list_models("mimo", secret)

    assert secret not in str(exc_info.value)
    assert "Authorization" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.asyncio
async def test_catalog_network_error_drops_sensitive_exception_context() -> None:
    secret = "sk-user-network-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"Authorization: Bearer {secret}",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelCatalogUnavailable) as exc_info:
            await ModelCatalogService(client=client).list_models("kimi", secret)

    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="上游敏感错误"),
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={"data": None}),
        httpx.Response(200, json={"data": []}),
    ],
)
async def test_catalog_fails_closed_on_unavailable_or_invalid_response(
    response: httpx.Response,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelCatalogUnavailable, match="模型目录暂时不可用"):
            await ModelCatalogService(client=client).list_models("mimo", "sk-test")


@pytest.mark.asyncio
async def test_catalog_stops_when_streamed_response_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.services.model_catalog.MAX_MODEL_CATALOG_BYTES", 10)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"data": [{"id": "too-large"}]}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ModelCatalogUnavailable):
            await ModelCatalogService(client=client).list_models("kimi", "sk-test")


@pytest.mark.asyncio
async def test_catalog_validates_selected_model_against_latest_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"id": "kimi-k4", "object": "model"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        catalog = ModelCatalogService(client=client)
        selected = await catalog.require_model(
            vendor="kimi",
            model="kimi-k4",
            api_key="sk-test",
        )
        with pytest.raises(ValueError, match="官方模型目录中不存在"):
            await catalog.require_model(
                vendor="kimi",
                model="kimi-k3",
                api_key="sk-test",
            )

    assert selected.vendor == "kimi"
    assert selected.model == "kimi-k4"
