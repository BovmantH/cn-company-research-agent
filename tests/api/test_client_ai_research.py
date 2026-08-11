from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

import application
from backend.services.client_model import SelectedModel
from backend.services.model_catalog import ModelCatalogService
from backend.services.search.glm_provider import GlmWebSearchProvider
from backend.services.search.mimo_provider import MiMoNativeSearchProvider
from backend.services.search.qwen_provider import QwenNativeSearchProvider
from backend.services.search.responses_provider import ResponsesNativeSearchProvider

SENTINEL_KEY = "sk-user-secret-sentinel"


@pytest.fixture(autouse=True)
def restore_model_catalog() -> None:
    original = application.app.state.model_catalog
    yield
    application.app.state.model_catalog = original


@pytest.fixture
def capture_research(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_process(job_id: str, data: Any, **kwargs: Any):
        captured.update(job_id=job_id, data=data, kwargs=kwargs)

        async def noop() -> None:
            return None

        return noop()

    def fake_schedule(coroutine: Any, **_kwargs: Any) -> object:
        coroutine.close()
        return object()

    monkeypatch.setattr(application, "process_research", fake_process)
    monkeypatch.setattr(application, "_schedule_research", fake_schedule)
    return captured


def _payload(**ai_overrides: Any) -> dict[str, Any]:
    ai = {
        "vendor": "qwen",
        "model": "qwen3.7-plus",
        "api_key": SENTINEL_KEY,
        "web_search": True,
        **ai_overrides,
    }
    return {"company": "示例科技有限公司", "ai": ai}


def test_model_catalog_returns_curated_qwen_options_without_exposing_key() -> None:
    response = TestClient(application.app).post(
        "/ai/models",
        json={"vendor": "qwen"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "vendor": "qwen",
        "source": "curated",
        "models": [
            {"id": "qwen3.7-plus", "name": "Qwen3.7 Plus"},
            {"id": "qwen3.7-max", "name": "Qwen3.7 Max"},
        ],
        "available_for_research": True,
    }
    assert SENTINEL_KEY not in response.text


def test_provider_options_come_from_backend_capability_registry() -> None:
    response = TestClient(application.app).get("/ai/providers")

    assert response.status_code == 200
    providers = {provider["id"]: provider for provider in response.json()["providers"]}
    assert providers["qwen"] == {
        "id": "qwen",
        "name": "阿里百炼（Qwen）",
        "short_name": "Qwen",
        "description": "阿里云百炼提供的通义千问模型服务。",
        "api_console_url": (
            "https://bailian.console.aliyun.com/cn-beijing/?tab=app#/api-key"
        ),
        "catalog_source": "curated",
        "requires_key_to_list": False,
        "available_for_research": True,
    }
    assert all(provider["short_name"] for provider in providers.values())
    assert all(provider["description"] for provider in providers.values())
    assert providers["kimi"]["catalog_source"] == "official_api"
    assert providers["kimi"]["requires_key_to_list"] is True
    assert providers["kimi"]["available_for_research"] is False
    assert providers["glm"]["available_for_research"] is True
    assert providers["mimo"]["available_for_research"] is True
    assert providers["openrouter"]["available_for_research"] is True
    assert providers["openai"]["available_for_research"] is True


def test_provider_options_expose_safe_official_api_console_urls() -> None:
    response = TestClient(application.app).get("/ai/providers")
    providers = {provider["id"]: provider for provider in response.json()["providers"]}
    expected = {
        "opencode": "https://opencode.ai/auth",
        "deepseek": "https://platform.deepseek.com/api_keys",
        "kimi": "https://platform.kimi.com/console/api-keys",
        "qwen": "https://bailian.console.aliyun.com/cn-beijing/?tab=app#/api-key",
        "glm": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "minimax": "https://platform.minimaxi.com/console/access?tab=api-keys",
        "mimo": "https://platform.xiaomimimo.com/",
        "openrouter": "https://openrouter.ai/settings/keys",
        "openai": "https://platform.openai.com/api-keys",
    }

    assert {key: item["api_console_url"] for key, item in providers.items()} == expected
    for item in providers.values():
        parsed = urlsplit(item["api_console_url"])
        assert parsed.scheme == "https"
        assert parsed.hostname
        assert parsed.username is None
        assert parsed.password is None


def test_dynamic_model_catalog_requires_key_without_scheduling_work() -> None:
    response = TestClient(application.app).post(
        "/ai/models",
        json={"vendor": "kimi"},
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "读取该厂商的官方模型目录需要 API Key"}


def test_model_catalog_reads_dynamic_vendor_from_fixed_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": [{"id": "kimi-k4", "name": "Kimi K4"}]},
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    application.app.state.model_catalog = ModelCatalogService(client=client)
    try:
        response = TestClient(application.app).post(
            "/ai/models",
            json={"vendor": "kimi", "api_key": SENTINEL_KEY},
        )
    finally:
        import asyncio

        asyncio.run(client.aclose())

    assert response.status_code == 200
    assert response.json()["models"] == [{"id": "kimi-k4", "name": "Kimi K4"}]
    assert response.json()["available_for_research"] is False
    assert requests[0].url == httpx.URL("https://api.moonshot.cn/v1/models")
    assert requests[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"
    assert SENTINEL_KEY not in response.text


def test_research_uses_ephemeral_qwen_dependencies_without_exposing_key(
    capture_research: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = TestClient(application.app).post("/research", json=_payload())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert SENTINEL_KEY not in response.text
    assert capture_research["data"].ai is None
    dependencies = capture_research["kwargs"]["research_dependencies"]
    assert isinstance(dependencies.search, QwenNativeSearchProvider)
    assert dependencies.researcher_llm.model_name == "qwen3.7-plus"
    assert dependencies.briefing_llm.model_name == "qwen3.7-plus"
    assert dependencies.editor_llm.model_name == "qwen3.7-plus"
    assert SENTINEL_KEY not in repr(dependencies)
    assert SENTINEL_KEY not in caplog.text


@pytest.mark.parametrize(
    ("vendor", "model", "expected_provider"),
    [
        ("glm", "glm-5.2", GlmWebSearchProvider),
        ("mimo", "mimo-v2.5", MiMoNativeSearchProvider),
        ("openrouter", "vendor/report-model", ResponsesNativeSearchProvider),
        ("openai", "gpt-5.6-terra", ResponsesNativeSearchProvider),
    ],
)
def test_research_builds_selected_native_search_provider(
    vendor: str,
    model: str,
    expected_provider: type[object],
    capture_research: dict[str, Any],
) -> None:
    class StubCatalog:
        async def require_model(self, **_kwargs: Any) -> SelectedModel:
            return SelectedModel(vendor=vendor, model=model)

    application.app.state.model_catalog = StubCatalog()

    response = TestClient(application.app).post(
        "/research",
        json=_payload(vendor=vendor, model=model),
    )

    assert response.status_code == 200
    dependencies = capture_research["kwargs"]["research_dependencies"]
    assert isinstance(dependencies.search, expected_provider)
    assert dependencies.researcher_llm.model_name == model
    assert SENTINEL_KEY not in response.text
    assert SENTINEL_KEY not in repr(dependencies)


def test_mimo_token_plan_key_is_rejected_before_model_catalog_request() -> None:
    class FailIfCalledCatalog:
        async def require_model(self, **_kwargs: Any) -> SelectedModel:
            raise AssertionError("Token Plan Key 不得发送到普通 API 模型目录")

    application.app.state.model_catalog = FailIfCalledCatalog()

    response = TestClient(application.app).post(
        "/research",
        json=_payload(
            vendor="mimo",
            model="mimo-v2.5",
            api_key="tp-offline-sentinel",
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "请求参数有误: 字段取值不合法"
    assert "tp-offline-sentinel" not in response.text


def test_mimo_token_plan_key_is_rejected_before_listing_models() -> None:
    class FailIfCalledCatalog:
        async def list_models(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("Token Plan Key 不得发送到普通 API 模型目录")

    application.app.state.model_catalog = FailIfCalledCatalog()

    response = TestClient(application.app).post(
        "/ai/models",
        json={
            "vendor": "mimo",
            "api_key": "tp-offline-catalog-sentinel",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "请求参数有误: 字段取值不合法"
    assert "tp-offline-catalog-sentinel" not in response.text


@pytest.mark.parametrize(
    "ai_overrides",
    [
        {"vendor": "deepseek"},
        {"model": "gpt-5.6-terra"},
        {"base_url": "https://attacker.example/v1"},
        {"api_key": "short"},
        {"web_search": False},
    ],
)
def test_research_rejects_unsupported_client_ai_configuration_without_echoing_key(
    ai_overrides: dict[str, Any],
) -> None:
    response = TestClient(application.app).post(
        "/research",
        json=_payload(**ai_overrides),
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert SENTINEL_KEY not in response.text
    assert "attacker.example" not in response.text


def test_persistent_research_input_never_contains_client_ai_secret() -> None:
    request = application.ResearchRequest.model_validate(_payload())

    persisted = application._persistent_research_input(request)

    assert persisted == {"company": "示例科技有限公司"}
    assert SENTINEL_KEY not in json.dumps(persisted, ensure_ascii=False)
    assert SENTINEL_KEY not in repr(request)


def test_research_start_failure_does_not_expose_client_key(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_schedule(coroutine: Any, **_kwargs: Any) -> None:
        coroutine.close()
        raise RuntimeError(f"Authorization: Bearer {SENTINEL_KEY}")

    monkeypatch.setattr(application, "_schedule_research", fail_schedule)

    response = TestClient(application.app).post("/research", json=_payload())

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "启动调研任务失败"}
    assert SENTINEL_KEY not in response.text
    assert SENTINEL_KEY not in caplog.text


def test_research_without_client_or_server_key_fails_before_scheduling(
    capture_research: dict[str, Any],
) -> None:
    response = TestClient(application.app).post(
        "/research",
        json={"company": "示例科技有限公司"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "当前部署未配置服务端模型，请填写本次任务的 API Key"
    }
    assert capture_research == {}
