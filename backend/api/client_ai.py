"""Web 用户任务级模型、目录和临时 Key 的 API 边界。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from backend.graph import ResearchDependencies
from backend.services.client_model import (
    CLIENT_MODEL_ID_PATTERN,
    CLIENT_MODEL_VENDORS,
    SelectedModel,
)
from backend.services.llm_factory import VENDOR_REGISTRY, build_client_llm
from backend.services.model_catalog import (
    CURATED_MODEL_OPTIONS,
    ModelCatalogCredentialError,
    ModelCatalogUnavailable,
)
from backend.services.search.qwen_provider import QwenNativeSearchProvider

router = APIRouter(prefix="/ai", tags=["任务级模型"])

MIN_CLIENT_API_KEY_LENGTH = 8
MAX_CLIENT_API_KEY_LENGTH = 4_096
CLIENT_WEB_SEARCH_VENDORS = frozenset({"qwen"})


def _validate_client_api_key(value: str) -> str:
    """校验任务级密钥的最小边界，不记录或返回密钥内容。"""
    normalized = value.strip()
    if not MIN_CLIENT_API_KEY_LENGTH <= len(normalized) <= MAX_CLIENT_API_KEY_LENGTH:
        raise ValueError("用户 API Key 长度不合法")
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise ValueError("用户 API Key 包含不允许的控制字符")
    return normalized


class ModelCatalogRequest(BaseModel):
    """读取单个厂商模型目录所需的临时凭证。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    vendor: str = Field(min_length=1, max_length=32)
    api_key: SecretStr | None = None

    @field_validator("vendor")
    @classmethod
    def normalize_vendor(cls, value: str) -> str:
        return value.lower()

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return _validate_client_api_key(value)


class ClientAIRequest(BaseModel):
    """Web 用户为单次调研提交的模型与联网配置。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    vendor: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    api_key: SecretStr
    web_search: Literal[True] = True

    @field_validator("vendor")
    @classmethod
    def normalize_vendor(cls, value: str) -> str:
        """统一厂商标识，避免大小写导致白名单绕过。"""
        return value.lower()

    @field_validator("api_key", mode="before")
    @classmethod
    def normalize_api_key(cls, value: object) -> object:
        """仅清理复制时常见的首尾空白，不记录或回显密钥。"""
        if not isinstance(value, str):
            return value
        return _validate_client_api_key(value)

    @model_validator(mode="after")
    def validate_client_selection(self) -> ClientAIRequest:
        if self.vendor not in CLIENT_WEB_SEARCH_VENDORS:
            raise ValueError("当前尚未开放该厂商的用户自带 Key 联网调研")
        if not CLIENT_MODEL_ID_PATTERN.fullmatch(self.model):
            raise ValueError("模型标识格式不合法")
        return self


def build_client_research_dependencies(
    config: ClientAIRequest,
    selection: SelectedModel,
) -> ResearchDependencies:
    """构造与当前请求绑定的模型和联网实例，不读取服务端厂商选择。"""
    api_key = config.api_key.get_secret_value()
    common = {"selection": selection, "api_key": api_key}
    return ResearchDependencies(
        search=QwenNativeSearchProvider(api_key=api_key, selection=selection),
        researcher_llm=build_client_llm(
            role="researcher",
            streaming=True,
            **common,
        ),
        briefing_llm=build_client_llm(
            role="briefing",
            streaming=False,
            **common,
        ),
        editor_llm=build_client_llm(
            role="editor",
            streaming=True,
            **common,
        ),
    )


def model_catalog_error_response(exc: Exception) -> JSONResponse:
    """把目录失败映射为稳定中文响应，不透传上游正文。"""
    if isinstance(exc, ModelCatalogCredentialError):
        status_code = 401
        detail = "API Key 无效或无权读取该厂商的官方模型目录"
    elif isinstance(exc, ModelCatalogUnavailable):
        status_code = 503
        detail = "该厂商的模型目录暂时不可用，请稍后重试"
    else:
        status_code = 422
        detail = str(exc)
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers={"Cache-Control": "no-store"},
    )


async def require_client_model(
    config: ClientAIRequest,
    request: Request,
) -> SelectedModel:
    """按当前目录重新校验提交的厂商和模型。"""
    return await request.app.state.model_catalog.require_model(
        vendor=config.vendor,
        model=config.model,
        api_key=config.api_key.get_secret_value(),
    )


@router.get("/providers")
async def list_client_model_providers():
    """返回前端可展示的固定厂商能力，不包含端点或服务端配置。"""
    providers = [
        {
            "id": vendor,
            "name": VENDOR_REGISTRY[vendor].display_name,
            "short_name": VENDOR_REGISTRY[vendor].short_name,
            "description": VENDOR_REGISTRY[vendor].description,
            "api_console_url": VENDOR_REGISTRY[vendor].api_console_url,
            "catalog_source": (
                "curated" if vendor in CURATED_MODEL_OPTIONS else "official_api"
            ),
            "requires_key_to_list": vendor not in CURATED_MODEL_OPTIONS,
            "available_for_research": vendor in CLIENT_WEB_SEARCH_VENDORS,
        }
        for vendor in CLIENT_MODEL_VENDORS
    ]
    return JSONResponse(content={"providers": providers})


@router.post("/models")
async def list_client_models(data: ModelCatalogRequest, request: Request):
    """使用临时 Key 读取模型目录，响应只包含厂商、来源和模型名称。"""
    try:
        catalog = await request.app.state.model_catalog.list_models(
            data.vendor,
            data.api_key.get_secret_value() if data.api_key is not None else "",
        )
    except (ModelCatalogCredentialError, ModelCatalogUnavailable, ValueError) as exc:
        return model_catalog_error_response(exc)
    return JSONResponse(
        content={
            **catalog.model_dump(mode="json"),
            "available_for_research": catalog.vendor in CLIENT_WEB_SEARCH_VENDORS,
        },
        headers={"Cache-Control": "no-store"},
    )


__all__ = [
    "ClientAIRequest",
    "build_client_research_dependencies",
    "model_catalog_error_response",
    "require_client_model",
    "router",
]
